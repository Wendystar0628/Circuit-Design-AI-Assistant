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

    @pyqtSlot()
    def request_stop(self) -> bool:
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
        task.cancel()
        if self.logger:
            self.logger.info(f"Stop requested for task: {self._active_task_id}")
        return True

    @asyncSlot()
    async def execute_agent(
        self,
        task_id: str,
        messages: List[Dict[str, Any]],
        model: str,
        thinking: bool = False,
    ) -> None:
        """以 Agent 模式执行 LLM 调用（带工具自动调用循环）。

        本方法由 qasync 包装为 asyncio.Task 运行。方法入口记录
        ``current_task()`` 作为活跃 task 句柄，退出前在 ``finally``
        里清空——这保证 ``request_stop`` 看到的 task 一定还活着。
        """
        if self.logger:
            self.logger.info(
                f"Starting Agent execution: task_id={task_id}, model={model}"
            )

        self._active_task = asyncio.current_task()
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

            if messages and messages[0].get("role") == "system":
                messages[0]["content"] = system_prompt
            else:
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

        import os
        return os.getcwd()

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
        """从 ServiceLocator 取 SimulationResultRepository 注入给 ToolContext。

        read_metrics / read_output_log / read_op_result / read_chart_image
        共用的 read 基座通过 context 使用此仓储完成 ``circuit_file``/
        ``result_path`` → ``SimulationResult`` → bundle 目录的解析链；
        tool 内部禁止再走 ServiceLocator 或 import 模块级单例。
        """
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_SIMULATION_RESULT_REPOSITORY

            return ServiceLocator.get_optional(SVC_SIMULATION_RESULT_REPOSITORY)
        except Exception as e:
            if self.logger:
                self.logger.debug(
                    f"Failed to get simulation result repository: {e}"
                )
            return None

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
        """从 SessionState 读当前活动电路文件绝对路径。

        SessionState.active_circuit_file 是 GraphStateProjector 从
        GraphState.circuit_file_path 投影过来的唯一只读视图，
        作为 agent 未显式传 file_path 时的回落项。无活动文件返回 None。
        """
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_SESSION_STATE

            session_state = ServiceLocator.get_optional(SVC_SESSION_STATE)
            if session_state is None:
                return None
            active = session_state.active_circuit_file
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
]
