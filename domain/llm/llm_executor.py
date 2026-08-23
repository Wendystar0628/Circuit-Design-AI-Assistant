# LLM Executor - LLM Call Execution Engine
"""LLM 调用执行器。

职责：
- 封装 Agent 模式 LLM 调用
- 处理流式响应、工具调用
- 通过 Qt 信号向对话主链转发结果

取消协议（权威设计）：
    asyncio.Task 是活跃生成的**唯一事实源**。
    ``request_stop()`` 直接对保存的 task 调 ``cancel()``，
    让 ``CancelledError`` 从 httpx 最深 await（socket.recv）处抛出，
    沿 ``chat_stream`` 内部的 ``async with`` 栈以异常路径正常展开，
    httpx 通过 ``AsyncShieldCancellation`` 完成同步清理。

    这**彻底避开**了 async generator 的 ``aclose``-GeneratorExit 路径
    （在 httpcore 1.x + anyio 4 + qasync 下会崩溃）。

    所有生成结束（无论完成、被停止、还是出错）都从**同一个信号**
    ``generation_finished`` 发出，消费者（ConversationViewModel）
    通过 ``outcome`` 字段分派处理——没有多个 signal，没有 race。

使用示例：
    executor = LLMExecutor()
    executor.generation_finished.connect(on_finished)
    executor.execute_agent("task_1", messages, "glm-4-plus")
    # 用户点停止按钮：
    executor.request_stop()
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from qasync import asyncSlot

from infrastructure.llm_adapters.base_client import (
    BaseLLMClient,
    LLMError,
    APIError,
    AuthError,
    RateLimitError,
    ContextOverflowError,
)


# Generation outcome enumeration (strings, not Enum, for easier
# cross-signal serialisation).
OUTCOME_COMPLETED = "completed"
OUTCOME_STOPPED = "stopped"
OUTCOME_ERROR = "error"

ACTIVE_GENERATION_ERROR = "A generation is already running"


class LLMExecutor(QObject):
    """LLM 调用执行器。

    Signals:
        agent_turn_started(task_id, step_index)
        stream_chunk(task_id, step_index, chunk_type, chunk_data)
        tool_execution_started(task_id, step_index, tool_call_id, tool_name, arguments)
        tool_execution_finished(task_id, step_index, tool_call_id, tool_name, result_content, is_error, details)
        generation_finished(task_id, result)
            result is a dict with keys:
              - ``outcome``: one of ``"completed"``, ``"stopped"``, ``"error"``
              - completed: ``content``, ``reasoning_content``, ``usage``,
                ``total_turns``, ``tool_calls_count``
              - stopped: (no extra fields; partial content lives in the
                ViewModel's accumulated agent steps)
              - error: ``error_message``
    """

    agent_turn_started = pyqtSignal(str, int)
    stream_chunk = pyqtSignal(str, int, str, dict)
    tool_execution_started = pyqtSignal(str, int, str, str, dict)
    tool_execution_finished = pyqtSignal(str, int, str, str, str, bool, dict)
    generation_finished = pyqtSignal(str, dict)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._logger = None
        self._active_task: Optional[asyncio.Task] = None
        self._active_task_id: Optional[str] = None

    # ============================================================
    # 延迟获取服务
    # ============================================================

    @property
    def logger(self):
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("llm_executor")
            except Exception as e:
                logging.getLogger(__name__).warning(
                    f"Failed to load custom logger, using stdlib: {e}"
                )
                self._logger = logging.getLogger(__name__)
        return self._logger

    # ============================================================
    # 公共接口
    # ============================================================

    @property
    def is_generating(self) -> bool:
        """当前是否有活跃的生成 task。"""
        task = self._active_task
        return task is not None and not task.done()

    def start_agent(
        self,
        task_id: str,
        messages: List[Dict[str, Any]],
        model: str,
        thinking: bool = False,
    ) -> Optional[asyncio.Task]:
        """Schedule and synchronously claim one Agent task.

        ``@asyncSlot`` creates an ``asyncio.Task`` before ``execute_agent``
        gets its first event-loop turn.  Claiming that returned task in this
        same synchronous call closes the project/session transition window in
        which ``request_stop`` previously had no task handle to cancel.
        """
        active_task = self._active_task
        if active_task is not None and not active_task.done():
            active_task_id = self._active_task_id or "unknown"
            error_message = (
                f"{ACTIVE_GENERATION_ERROR}: active_task_id={active_task_id}"
            )
            self.generation_finished.emit(
                task_id,
                {
                    "outcome": OUTCOME_ERROR,
                    "error_message": error_message,
                    "rejected": True,
                    "active_task_id": active_task_id,
                },
            )
            return None

        scheduled_task = self.execute_agent(
            task_id=task_id,
            messages=messages,
            model=model,
            thinking=thinking,
        )
        if not isinstance(scheduled_task, asyncio.Task):
            self._emit_error(task_id, "Agent execution could not be scheduled")
            return None

        self._active_task = scheduled_task
        self._active_task_id = task_id
        scheduled_task.add_done_callback(self._on_claimed_task_done)
        return scheduled_task

    def _on_claimed_task_done(self, task: asyncio.Task) -> None:
        """Settle a task cancelled before ``execute_agent`` could enter.

        Once the coroutine body has entered, its ``except/finally`` emits the
        terminal result and releases the slot before this callback runs.  The
        slot still belonging to *task* here therefore identifies the narrow
        pre-entry path.  Emit the same stopped terminal exactly once before
        releasing ownership; an old callback must never clear or signal for a
        newer owner.
        """
        if self._active_task is not task or not task.done():
            return

        task_id = self._active_task_id
        if task.cancelled() and task_id:
            self.generation_finished.emit(
                task_id,
                {"outcome": OUTCOME_STOPPED},
            )
        self._active_task = None
        self._active_task_id = None

    @pyqtSlot()
    def request_stop(self, expected_task_id: Optional[str] = None) -> bool:
        """取消当前活跃的生成 task。

        这是**唯一**的停止入口。通过 ``task.cancel()`` 让
        ``CancelledError`` 从最深 await 点（httpx socket）抛出，
        沿 async with 栈异常展开，httpx 在
        ``AsyncShieldCancellation`` 保护下完成清理。

        Returns:
            ``True`` 若有活跃 task 被成功请求取消；``False`` 若当前无生成。
        """
        task = self._active_task
        if task is None or task.done():
            if self.logger:
                self.logger.debug("request_stop called but no active task")
            return False
        if expected_task_id and expected_task_id != self._active_task_id:
            if self.logger:
                self.logger.warning(
                    "Ignored stop request for stale task: expected=%s, active=%s",
                    expected_task_id,
                    self._active_task_id,
                )
            return False
        task.cancel()
        if self.logger:
            self.logger.info(f"Stop requested for task: {self._active_task_id}")
        return True

    async def shutdown(self) -> None:
        """Cancel and await the active generation, if any.

        This is the lifecycle boundary for application shutdown.  It is
        intentionally idempotent and identity-safe so multiple shutdown
        callers cannot clear a newer task by awaiting an older snapshot.
        """
        task = self._active_task
        if task is None:
            return

        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            current_task = None
        if task is current_task:
            if self.logger:
                self.logger.warning("LLMExecutor.shutdown cannot await its own task")
            return

        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            # A task cancelled before execute_agent entered cannot emit its
            # normal stopped terminal event; shutdown still owns completion.
            pass
        except Exception as exc:
            if self.logger:
                self.logger.warning(f"LLM shutdown observed task failure: {exc}")
        finally:
            if self._active_task is task and task.done():
                self._active_task = None
                self._active_task_id = None

    @asyncSlot()
    async def execute_agent(
        self,
        task_id: str,
        messages: List[Dict[str, Any]],
        model: str,
        thinking: bool = False,
    ) -> None:
        """以 Agent 模式执行 LLM 调用（带工具自动调用循环）。

        UI callers use :meth:`start_agent`, which claims qasync's returned
        task synchronously.  Direct callers remain supported; method entry
        adopts ``current_task()`` when no earlier claim exists.
        """
        owning_task = asyncio.current_task()
        active_task = self._active_task
        if (
            active_task is not None
            and active_task is not owning_task
            and not active_task.done()
        ):
            active_task_id = self._active_task_id or "unknown"
            error_message = (
                f"{ACTIVE_GENERATION_ERROR}: active_task_id={active_task_id}"
            )
            if self.logger:
                self.logger.warning(
                    "Rejected concurrent Agent execution: requested=%s, active=%s",
                    task_id,
                    active_task_id,
                )
            self.generation_finished.emit(
                task_id,
                {
                    "outcome": OUTCOME_ERROR,
                    "error_message": error_message,
                    "rejected": True,
                    "active_task_id": active_task_id,
                },
            )
            return

        if owning_task is None:
            self._emit_error(task_id, "Agent execution requires an asyncio task")
            return

        if self.logger:
            self.logger.info(
                f"Starting Agent execution: task_id={task_id}, model={model}"
            )

        self._active_task = owning_task
        self._active_task_id = task_id

        try:
            client = self._get_llm_client(model)
            if not client:
                self._emit_error(task_id, f"LLM client not available for model: {model}")
                return

            from domain.llm.agent.types import ToolContext
            from domain.llm.agent.tool_factory import create_default_tools
            from domain.llm.agent.agent_loop import AgentLoop
            from domain.llm.agent.agent_prompt_builder import build_agent_system_prompt

            project_root = self._get_project_root()
            current_file = self._get_active_circuit_file()
            context = ToolContext(
                project_root=project_root,
                current_file=current_file,
                rag_query_service=self._get_rag_query_service(),
                sim_job_manager=self._get_sim_job_manager(),
                sim_result_repository=self._get_sim_result_repository(),
                pending_workspace_edit_service=(
                    self._get_pending_workspace_edit_service()
                ),
            )
            registry = create_default_tools()

            if self.logger:
                self.logger.info(f"Agent tools registered: {registry.get_names()}")

            system_prompt = build_agent_system_prompt(
                registry=registry,
                project_root=project_root,
                current_file=current_file,
            )

            # The working-context builder may already have inserted one or
            # more system messages (notably the compressed-history summary).
            # They are user/session context, not placeholders for the Agent
            # instructions, so replacing messages[0] silently loses history.
            # Copy the input before prepending to avoid mutating the caller's
            # persisted working-context representation.
            messages = [dict(message) for message in messages]
            if not (
                messages
                and messages[0].get("role") == "system"
                and messages[0].get("content") == system_prompt
            ):
                messages.insert(0, {
                    "role": "system",
                    "content": system_prompt,
                })

            loop = AgentLoop(
                client=client,
                registry=registry,
                context=context,
                model=model,
                thinking=thinking,
            )

            agent_result = await loop.run(
                messages=messages,
                on_event=lambda evt, data: self._handle_agent_event(
                    task_id, evt, data
                ),
            )

            if agent_result.is_error:
                error_msg = agent_result.error_message or "Agent loop failed"
                if self.logger:
                    self.logger.error(
                        f"Agent execution failed: task_id={task_id}, error={error_msg}"
                    )
                self._emit_error(task_id, error_msg)
                return

            result = {
                "outcome": OUTCOME_COMPLETED,
                "content": agent_result.content,
                "reasoning_content": (
                    agent_result.reasoning_content
                    if agent_result.reasoning_content else None
                ),
                "usage": agent_result.usage,
                "total_turns": agent_result.total_turns,
                "tool_calls_count": agent_result.tool_calls_count,
            }

            if self.logger:
                self.logger.info(
                    f"Agent execution completed: task_id={task_id}, "
                    f"turns={agent_result.total_turns}, "
                    f"tool_calls={agent_result.tool_calls_count}, "
                    f"content_len={len(agent_result.content)}"
                )

            self.generation_finished.emit(task_id, result)

        except asyncio.CancelledError:
            if self.logger:
                self.logger.info(f"Agent execution cancelled: task_id={task_id}")
            self.generation_finished.emit(task_id, {"outcome": OUTCOME_STOPPED})
            # Swallow CancelledError — this task was cancelled on
            # purpose by request_stop(), it is not an error.
        except Exception as e:
            error_msg = self._format_error_message(e)
            if self.logger:
                self.logger.error(
                    f"Agent execution failed: task_id={task_id}, error={error_msg}"
                )
            self._emit_error(task_id, error_msg)
        finally:
            # Task ownership is identity based.  A stale task must never clear
            # a newer task that has become active in the meantime.
            if self._active_task is owning_task:
                self._active_task = None
                self._active_task_id = None

    # ============================================================
    # Agent 事件转发
    # ============================================================

    def _emit_error(self, task_id: str, error_msg: str) -> None:
        self.generation_finished.emit(task_id, {
            "outcome": OUTCOME_ERROR,
            "error_message": error_msg,
        })

    def _handle_agent_event(
        self, task_id: str, event_type: str, data: Dict[str, Any]
    ) -> None:
        """把 AgentLoop 的事件回调转发为 Qt 信号。"""
        if event_type == "turn_start":
            step_index = int(data.get("step_index", 0) or 0)
            if step_index > 0:
                self.agent_turn_started.emit(task_id, step_index)

        elif event_type == "stream_chunk":
            step_index = int(data.get("step_index", 0) or 0)
            chunk_type = data.get("chunk_type", "content")
            text = data.get("text", "")
            if text and step_index > 0:
                self.stream_chunk.emit(task_id, step_index, chunk_type, {
                    "type": chunk_type,
                    "text": text,
                })

        elif event_type == "tool_execution_start":
            step_index = int(data.get("step_index", 0) or 0)
            tool_call_id = data.get("tool_call_id", "")
            tool_name = data.get("tool_name", "")
            arguments = data.get("arguments", {})
            if step_index > 0:
                self.tool_execution_started.emit(
                    task_id,
                    step_index,
                    tool_call_id,
                    tool_name,
                    arguments,
                )

        elif event_type == "tool_execution_end":
            step_index = int(data.get("step_index", 0) or 0)
            tool_call_id = data.get("tool_call_id", "")
            tool_name = data.get("tool_name", "")
            result_content = data.get("result_content", "")
            is_error = bool(data.get("is_error", False))
            details = data.get("details") if isinstance(data.get("details"), dict) else {}
            if step_index > 0:
                self.tool_execution_finished.emit(
                    task_id,
                    step_index,
                    tool_call_id,
                    tool_name,
                    result_content,
                    is_error,
                    details,
                )

    # ============================================================
    # 辅助方法
    # ============================================================

    def _get_project_root(self) -> str:
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_PROJECT_SERVICE
            project_service = ServiceLocator.get_optional(SVC_PROJECT_SERVICE)
            if project_service:
                path = project_service.get_current_project_path()
                if path:
                    return path
        except Exception as e:
            logging.getLogger(__name__).warning(f"Failed to get project root: {e}")

        # Tools that mutate or inspect project-scoped data must fail closed
        # when no project is open.  Treating the process cwd as a project made
        # run_simulation and result readers operate on an unrelated checkout.
        return ""

    def _get_rag_query_service(self):
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_RAG_MANAGER

            return ServiceLocator.get_optional(SVC_RAG_MANAGER)
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Failed to get RAG query service: {e}")
            return None

    def _get_sim_job_manager(self):
        """从 ServiceLocator 取 SimulationJobManager 注入给 ToolContext。

        这是 agent 工具访问仿真能力的唯一通道——仿真系列 tool 内部
        禁止再走 ServiceLocator。
        """
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_SIMULATION_JOB_MANAGER

            return ServiceLocator.get_optional(SVC_SIMULATION_JOB_MANAGER)
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Failed to get simulation job manager: {e}")
            return None

    def _get_sim_result_repository(self):
        """Inject the stateless result repository into ``ToolContext``.

        The repository has no lifecycle or mutable runtime state, so a second
        ServiceLocator entry only created two misleading access paths.  Tools
        still receive it explicitly through their context and remain easy to
        replace in tests.
        """
        from domain.simulation.service.simulation_result_repository import (
            simulation_result_repository,
        )

        return simulation_result_repository

    def _get_pending_workspace_edit_service(self):
        """从 ServiceLocator 取 PendingWorkspaceEditService 注入给 ToolContext。

        PatchFileTool / RewriteFileTool 通过 context 使用此服务将
        agent 修改排入 pending 队列由用户审核，tool 内部禁止再走
        ServiceLocator。
        """
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_PENDING_WORKSPACE_EDIT_SERVICE

            return ServiceLocator.get_optional(SVC_PENDING_WORKSPACE_EDIT_SERVICE)
        except Exception as e:
            if self.logger:
                self.logger.debug(
                    f"Failed to get pending workspace edit service: {e}"
                )
            return None

    def _get_active_circuit_file(self) -> Optional[str]:
        """从当前会话状态读取活动电路文件路径。

        ``circuit_file_path`` 随会话一起加载和持久化，是 agent 未显式传
        ``file_path`` 时的单一回落来源。无活动文件时返回 ``None``。
        """
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_CONTEXT_MANAGER

            context_manager = ServiceLocator.get_optional(SVC_CONTEXT_MANAGER)
            if context_manager is None:
                return None
            active = context_manager.get_current_state().get("circuit_file_path", "")
            return active or None
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Failed to get active circuit file: {e}")
            return None

    def _get_llm_client(self, model: str) -> Optional[BaseLLMClient]:
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_LLM_CLIENT

            current_client = ServiceLocator.get_optional(SVC_LLM_CLIENT)
            if current_client:
                return current_client
        except Exception as e:
            if self.logger:
                self.logger.debug(
                    f"Failed to get active LLM client from ServiceLocator: {e}"
                )

        if self.logger:
            self.logger.error(f"No active LLM client is registered for model: {model}")
        return None

    def _format_error_message(self, error: Exception) -> str:
        if isinstance(error, AuthError):
            return f"认证失败: {str(error)}"
        elif isinstance(error, RateLimitError):
            return f"速率限制: {str(error)}"
        elif isinstance(error, ContextOverflowError):
            return f"上下文溢出: {str(error)}"
        elif isinstance(error, APIError):
            return f"API 错误: {str(error)}"
        elif isinstance(error, LLMError):
            return f"LLM 错误: {str(error)}"
        else:
            return f"未知错误: {str(error)}"


__all__ = [
    "LLMExecutor",
    "OUTCOME_COMPLETED",
    "OUTCOME_STOPPED",
    "OUTCOME_ERROR",
    "ACTIVE_GENERATION_ERROR",
]
