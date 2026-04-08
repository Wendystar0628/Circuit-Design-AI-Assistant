# LLM Executor - LLM Call Execution Engine
"""
LLM 调用执行器

职责：
- 封装 Agent 模式 LLM 调用
- 处理流式响应、工具调用和错误
- 通过 Qt 信号向对话主链转发结果

初始化顺序：
- Phase 3.6，依赖 ConfigManager、CredentialManager（见 bootstrap._init_llm_client）

设计原则：
- 使用 @asyncSlot() 装饰器，使异步方法可被 Qt 信号直接调用
- 协程在主线程的 asyncio 循环中执行
- 通过 ExternalServiceManager 获取 LLM 客户端

使用示例（信号模式）：
    executor = LLMExecutor()
    executor.stream_chunk.connect(on_stream_chunk)
    executor.generation_complete.connect(on_complete)
    
    await executor.execute_agent(
        task_id="task_1",
        messages=[{"role": "user", "content": "Hello"}],
        model="glm-4-plus",
        thinking=True
    )
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal
from qasync import asyncSlot

from infrastructure.llm_adapters.base_client import (
    BaseLLMClient,
    LLMError,
    APIError,
    AuthError,
    RateLimitError,
    ContextOverflowError,
)
from domain.llm.agent.tool_effect_dispatcher import ToolEffectDispatcher


# ============================================================
# LLMExecutor 类
# ============================================================

class LLMExecutor(QObject):
    """
    LLM 调用执行器
    
    封装 Agent 模式 LLM 调用，处理流式响应。
    
    提供信号模式：通过 execute_agent() 方法，结果通过信号返回。
    
    Signals:
        stream_chunk(str, dict): 流式数据块
            - task_id: 任务标识
            - chunk_data: {"type": "reasoning"|"content", "text": str}
        generation_complete(str, dict): 生成完成
            - task_id: 任务标识
            - result: {"content": str, "reasoning_content": str, "usage": dict}
        generation_error(str, str): 生成错误
            - task_id: 任务标识
            - error_msg: 错误消息
    """
    
    # 信号定义
    agent_turn_started = pyqtSignal(str, int)  # (task_id, step_index)
    stream_chunk = pyqtSignal(str, int, str, dict)  # (task_id, step_index, chunk_type, chunk_data)
    generation_complete = pyqtSignal(str, dict)  # (task_id, result)
    generation_error = pyqtSignal(str, str)  # (task_id, error_msg)
    tool_execution_started = pyqtSignal(str, int, str, str, dict)  # (task_id, step_index, tool_call_id, tool_name, arguments)
    tool_execution_finished = pyqtSignal(str, int, str, str, str, bool, dict)  # (task_id, step_index, tool_call_id, tool_name, result_content, is_error, details)
    
    def __init__(self, parent: Optional[QObject] = None, tool_effect_dispatcher: Optional[ToolEffectDispatcher] = None):
        """初始化 LLM 执行器"""
        super().__init__(parent)
        
        # 延迟获取的服务
        self._logger = None
        self._stop_controller = None
        self._tool_effect_dispatcher = tool_effect_dispatcher
    
    # ============================================================
    # 延迟获取服务
    # ============================================================
    
    @property
    def logger(self):
        """延迟获取 Logger"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("llm_executor")
            except Exception as e:
                logging.getLogger(__name__).warning(f"Failed to load custom logger, using stdlib: {e}")
                self._logger = logging.getLogger(__name__)
        return self._logger
    
    @property
    def stop_controller(self):
        """延迟获取 StopController"""
        if self._stop_controller is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_STOP_CONTROLLER
                self._stop_controller = ServiceLocator.get_optional(SVC_STOP_CONTROLLER)
            except Exception as e:
                logging.getLogger(__name__).warning(f"Failed to load StopController: {e}")
        return self._stop_controller
    
    # ============================================================
    # Agent 模式执行
    # ============================================================

    @asyncSlot()
    async def execute_agent(
        self,
        task_id: str,
        messages: List[Dict[str, Any]],
        model: str,
        thinking: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        以 Agent 模式执行 LLM 调用（带工具自动调用循环）

        流程：
        1. 获取 LLM 客户端
        2. 创建 ToolRegistry 并注册所有可用工具
        3. 构建 Agent 系统提示词（含工具列表和指南）
        4. 运行 AgentLoop 的 ReAct 循环
        5. 通过信号通知 UI 流式更新和工具执行事件

        LLM 在每轮回复中自行决定是否调用工具。
        若不调用工具，循环结束，行为等同普通对话。

        Args:
            task_id: 任务标识
            messages: 消息列表（不含 Agent 系统提示词，由本方法注入）
            model: 模型名称
            thinking: 是否启用深度思考

        Returns:
            dict: 生成结果，失败返回 None
        """
        if self.logger:
            self.logger.info(
                f"Starting Agent execution: task_id={task_id}, model={model}"
            )

        try:
            # 获取 LLM 客户端
            client = self._get_llm_client(model)
            if not client:
                error_msg = f"LLM client not available for model: {model}"
                self.generation_error.emit(task_id, error_msg)
                return None

            # 停止检查点
            if self._check_stop_requested():
                if self.logger:
                    self.logger.info(
                        f"Stop requested before Agent loop: task_id={task_id}"
                    )
                raise asyncio.CancelledError()

            # 获取项目根目录
            project_root = self._get_project_root()

            # 创建工具上下文和注册表（通过工厂集中注册所有工具）
            from domain.llm.agent.types import ToolContext
            from domain.llm.agent.tool_factory import create_default_tools
            from domain.llm.agent.agent_loop import AgentLoop
            from domain.llm.agent.agent_prompt_builder import (
                build_agent_system_prompt,
            )

            context = ToolContext(
                project_root=project_root,
                rag_query_service=self._get_rag_query_service(),
            )
            registry = create_default_tools()

            if self.logger:
                self.logger.info(f"Agent tools registered: {registry.get_names()}")

            # 构建 Agent 系统提示词（自包含，不依赖旧的身份提示词系统）
            system_prompt = build_agent_system_prompt(
                registry=registry,
                project_root=project_root,
            )

            # 注入系统提示词到消息列表
            if messages and messages[0].get("role") == "system":
                messages[0]["content"] = system_prompt
            else:
                messages.insert(0, {
                    "role": "system",
                    "content": system_prompt,
                })

            # 创建并运行 Agent 循环
            loop = AgentLoop(
                client=client,
                registry=registry,
                context=context,
                model=model,
                thinking=thinking,
                stop_requested=self._check_stop_requested,
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
                self.generation_error.emit(task_id, error_msg)
                return None

            # 构建最终结果
            result = {
                "content": agent_result.content,
                "reasoning_content": (
                    agent_result.reasoning_content
                    if agent_result.reasoning_content else None
                ),
                "usage": agent_result.usage,
                "total_turns": agent_result.total_turns,
                "tool_calls_count": agent_result.tool_calls_count,
            }

            # 发射完成信号
            self.generation_complete.emit(task_id, result)

            if self.logger:
                self.logger.info(
                    f"Agent execution completed: task_id={task_id}, "
                    f"turns={agent_result.total_turns}, "
                    f"tool_calls={agent_result.tool_calls_count}, "
                    f"content_len={len(agent_result.content)}"
                )

            return result

        except asyncio.CancelledError:
            if self.logger:
                self.logger.info(
                    f"Agent execution cancelled: task_id={task_id}"
                )

            if self.stop_controller:
                self.stop_controller.complete_stop({
                    "is_partial": True,
                    "cleanup_success": True,
                })

            return None

        except Exception as e:
            error_msg = self._format_error_message(e)
            if self.logger:
                self.logger.error(
                    f"Agent execution failed: task_id={task_id}, error={error_msg}"
                )
            self.generation_error.emit(task_id, error_msg)
            return None

    def _handle_agent_event(
        self, task_id: str, event_type: str, data: Dict[str, Any]
    ) -> None:
        """
        处理 AgentLoop 的事件回调，转发为 Qt 信号和 EventBus 事件

        Args:
            task_id: 任务标识
            event_type: 事件类型
            data: 事件数据
        """
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

            if not is_error and self._tool_effect_dispatcher is not None:
                self._tool_effect_dispatcher.dispatch(
                    tool_name=tool_name,
                    effects=data.get("effects"),
                )

    def _get_project_root(self) -> str:
        """
        获取当前项目根目录

        Returns:
            str: 项目根目录路径，未打开项目时返回当前工作目录
        """
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

    # ============================================================
    # 辅助方法
    # ============================================================
    
    def _check_stop_requested(self) -> bool:
        """
        检查是否请求停止
        
        Returns:
            bool: True 表示已请求停止
        """
        if self.stop_controller:
            return self.stop_controller.is_stop_requested()
        return False
    
    def _get_llm_client(self, model: str) -> Optional[BaseLLMClient]:
        """
        获取 LLM 客户端
        
        Args:
            model: 模型名称
            
        Returns:
            BaseLLMClient: LLM 客户端实例，未找到返回 None
        """
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_LLM_CLIENT

            current_client = ServiceLocator.get_optional(SVC_LLM_CLIENT)
            if current_client:
                return current_client
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Failed to get active LLM client from ServiceLocator: {e}")

        if self.logger:
            self.logger.error(f"No active LLM client is registered for model: {model}")
        return None
    
    def _format_error_message(self, error: Exception) -> str:
        """
        格式化错误消息
        
        Args:
            error: 异常对象
            
        Returns:
            str: 格式化的错误消息
        """
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


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "LLMExecutor",
]
