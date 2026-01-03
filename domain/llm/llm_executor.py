# LLM Executor - LLM Call Execution Engine
"""
LLM 调用执行器

职责：
- 封装 LLM API 调用，处理流式响应
- 与节流器集成，优化 UI 更新频率
- 区分深度思考内容和回答内容
- 处理工具调用和错误
- 提供异步生成器接口，支持 AsyncTaskRegistry 任务提交模式

初始化顺序：
- Phase 3.8，依赖 AsyncTaskRegistry、StreamThrottler、ExternalServiceManager

设计原则：
- 使用 @asyncSlot() 装饰器，使异步方法可被 Qt 信号直接调用
- 协程在主线程的 asyncio 循环中执行
- 通过 StreamThrottler 节流高频流式数据
- 通过 ExternalServiceManager 获取 LLM 客户端
- 提供 generate_stream() 异步生成器，适配 AsyncTaskRegistry 任务提交模式

使用示例（信号模式）：
    executor = LLMExecutor()
    executor.stream_chunk.connect(on_stream_chunk)
    executor.generation_complete.connect(on_complete)
    
    await executor.generate(
        task_id="task_1",
        messages=[{"role": "user", "content": "Hello"}],
        model="glm-4-plus",
        streaming=True,
        thinking=True
    )

使用示例（生成器模式，推荐用于 AsyncTaskRegistry）：
    executor = LLMExecutor()
    
    async def llm_task():
        async for chunk in executor.generate_stream(messages, model):
            event_bus.publish_throttled(EVENT_LLM_CHUNK, {"chunk": chunk})
        return executor.get_result()
    
    await registry.submit(TASK_LLM, task_id, llm_task())
"""

import asyncio
from typing import Any, AsyncGenerator, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal
from qasync import asyncSlot

from infrastructure.llm_adapters.base_client import (
    BaseLLMClient,
    StreamChunk,
    LLMError,
    APIError,
    AuthError,
    RateLimitError,
    ContextOverflowError,
)


# ============================================================
# LLMExecutor 类
# ============================================================

class LLMExecutor(QObject):
    """
    LLM 调用执行器
    
    封装 LLM API 调用，处理流式响应，与节流器集成。
    
    提供两种使用模式：
    1. 信号模式：通过 generate() 方法，结果通过信号返回
    2. 生成器模式：通过 generate_stream() 方法，返回异步生成器
    
    推荐使用生成器模式配合 AsyncTaskRegistry 进行任务管理。
    
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
    stream_chunk = pyqtSignal(str, str, dict)  # (task_id, chunk_type, chunk_data)
    generation_complete = pyqtSignal(str, dict)  # (task_id, result)
    generation_error = pyqtSignal(str, str)  # (task_id, error_msg)
    
    def __init__(self, parent: Optional[QObject] = None):
        """初始化 LLM 执行器"""
        super().__init__(parent)
        
        # 延迟获取的服务
        self._task_registry = None
        self._throttler = None
        self._external_service = None
        self._logger = None
        self._stop_controller = None
        self._resource_cleanup = None
        
        # 当前运行的任务
        self._running_tasks: Dict[str, asyncio.Task] = {}
        
        # 最后一次生成的结果（用于 get_result()）
        self._last_result: Optional[Dict[str, Any]] = None
        
        # 订阅停止事件
        self._subscribe_stop_events()
    
    # ============================================================
    # 延迟获取服务
    # ============================================================
    
    @property
    def task_registry(self):
        """延迟获取 AsyncTaskRegistry"""
        if self._task_registry is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_ASYNC_TASK_REGISTRY
                self._task_registry = ServiceLocator.get_optional(SVC_ASYNC_TASK_REGISTRY)
            except Exception:
                pass
        return self._task_registry
    
    @property
    def throttler(self):
        """延迟获取 StreamThrottler"""
        if self._throttler is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_STREAM_THROTTLER
                self._throttler = ServiceLocator.get_optional(SVC_STREAM_THROTTLER)
            except Exception:
                pass
        return self._throttler
    
    @property
    def external_service(self):
        """延迟获取 ExternalServiceManager"""
        if self._external_service is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EXTERNAL_SERVICE_MANAGER
                self._external_service = ServiceLocator.get_optional(SVC_EXTERNAL_SERVICE_MANAGER)
            except Exception:
                pass
        return self._external_service
    
    @property
    def logger(self):
        """延迟获取 Logger"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("llm_executor")
            except Exception:
                pass
        return self._logger
    
    @property
    def stop_controller(self):
        """延迟获取 StopController"""
        if self._stop_controller is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_STOP_CONTROLLER
                self._stop_controller = ServiceLocator.get_optional(SVC_STOP_CONTROLLER)
            except Exception:
                pass
        return self._stop_controller
    
    @property
    def resource_cleanup(self):
        """延迟获取 ResourceCleanupManager"""
        if self._resource_cleanup is None:
            try:
                from shared.resource_cleanup import ResourceCleanupManager
                self._resource_cleanup = ResourceCleanupManager()
            except Exception:
                pass
        return self._resource_cleanup
    
    def _subscribe_stop_events(self) -> None:
        """
        订阅停止事件
        
        通过 EventBus 订阅停止请求事件，实现中断机制。
        延迟订阅以避免初始化顺序问题。
        """
        # 延迟订阅，避免初始化顺序问题
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_EVENT_BUS
            
            event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            if event_bus:
                event_bus.subscribe("EVENT_STOP_REQUESTED", self._on_stop_requested)
                if self.logger:
                    self.logger.debug("Subscribed to EVENT_STOP_REQUESTED")
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to subscribe stop events: {e}")
    
    def _on_stop_requested(self, event_data: Dict[str, Any]) -> None:
        """
        处理停止请求事件
        
        取消所有运行中的 LLM 任务，并通知 StopController。
        
        Args:
            event_data: 事件数据，包含 task_id 和 reason
        """
        # 取消所有运行中的任务
        cancelled_count = 0
        for task_id in list(self._running_tasks.keys()):
            if self.cancel(task_id):
                cancelled_count += 1
        
        if self.logger:
            self.logger.info(
                f"Stop requested, cancelled {cancelled_count} LLM tasks, "
                f"reason={event_data.get('reason', 'unknown')}"
            )
    
    # ============================================================
    # 核心方法
    # ============================================================
    
    @asyncSlot()
    async def generate(
        self,
        task_id: str,
        messages: List[Dict[str, Any]],
        model: str,
        streaming: bool = True,
        tools: Optional[List[Dict[str, Any]]] = None,
        thinking: bool = False,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """
        执行 LLM 生成
        
        Args:
            task_id: 任务标识
            messages: 消息列表
            model: 模型名称
            streaming: 是否流式输出
            tools: 工具定义列表
            thinking: 是否启用深度思考
            **kwargs: 其他参数
            
        Returns:
            dict: 生成结果（非流式模式），流式模式返回 None
        """
        if self.logger:
            self.logger.info(
                f"Starting LLM generation: task_id={task_id}, model={model}, "
                f"streaming={streaming}, thinking={thinking}"
            )
        
        try:
            # 获取 LLM 客户端
            client = self._get_llm_client(model)
            if not client:
                error_msg = f"LLM client not available for model: {model}"
                self.generation_error.emit(task_id, error_msg)
                return None
            
            if streaming:
                # 流式生成
                await self._stream_generate(task_id, client, messages, model, tools, thinking, **kwargs)
                return None
            else:
                # 非流式生成
                result = await self._non_stream_generate(task_id, client, messages, model, tools, thinking, **kwargs)
                return result
                
        except asyncio.CancelledError:
            # 任务被取消
            if self.logger:
                self.logger.info(f"LLM generation cancelled: task_id={task_id}")
            
            # 确保刷新节流器
            if self.throttler:
                await self.throttler.flush_all(task_id)
            
            # 通知 StopController
            if self.stop_controller:
                self.stop_controller.mark_stopping()
                self.stop_controller.mark_stopped({
                    "is_partial": True,
                    "cleanup_success": True,
                })
            
            raise
            
        except Exception as e:
            # 生成错误
            error_msg = self._format_error_message(e)
            
            if self.logger:
                self.logger.error(f"LLM generation failed: task_id={task_id}, error={error_msg}")
            
            self.generation_error.emit(task_id, error_msg)
            return None
    
    async def _stream_generate(
        self,
        task_id: str,
        client: BaseLLMClient,
        messages: List[Dict[str, Any]],
        model: str,
        tools: Optional[List[Dict[str, Any]]],
        thinking: bool,
        **kwargs
    ) -> None:
        """
        流式生成内部实现
        
        Args:
            task_id: 任务标识
            client: LLM 客户端
            messages: 消息列表
            model: 模型名称
            tools: 工具定义列表
            thinking: 是否启用深度思考
            **kwargs: 其他参数
        """
        # 累积内容
        reasoning_content = ""
        content = ""
        usage = None
        stream_gen = None
        
        try:
            # 停止检查点：在开始长时间操作前检查
            if self._check_stop_requested():
                if self.logger:
                    self.logger.info(f"Stop requested before LLM call: task_id={task_id}")
                raise asyncio.CancelledError()
            
            # 调用客户端的流式生成方法
            stream_gen = client.chat_stream(
                messages=messages,
                model=model,
                tools=tools,
                thinking=thinking,
                **kwargs
            )
            
            # 注册异步生成器到资源清理管理器（3.0.10）
            if self.resource_cleanup and stream_gen:
                self.resource_cleanup.register_async_generator(stream_gen, f"llm_stream_{task_id}")
            
            async for chunk in stream_gen:
                # 停止检查点：每个 chunk 后检查是否请求停止
                if self._check_stop_requested():
                    if self.logger:
                        self.logger.info(f"Stop requested during streaming: task_id={task_id}")
                    # 主动抛出 CancelledError 以触发统一的停止处理逻辑
                    raise asyncio.CancelledError()
                
                # 检查是否被取消
                if asyncio.current_task().cancelled():
                    raise asyncio.CancelledError()
                
                # 处理思考内容
                if chunk.reasoning_content:
                    reasoning_content += chunk.reasoning_content
                    
                    # 通过节流器推送
                    if self.throttler:
                        await self.throttler.push(
                            task_id,
                            chunk.reasoning_content
                        )
                    
                    # 发送流式数据块信号
                    self.stream_chunk.emit(task_id, "reasoning", {
                        "type": "reasoning",
                        "text": chunk.reasoning_content
                    })
                
                # 处理回答内容
                if chunk.content:
                    content += chunk.content
                    
                    # 通过节流器推送
                    if self.throttler:
                        await self.throttler.push(
                            task_id,
                            chunk.content
                        )
                    
                    # 发送流式数据块信号
                    self.stream_chunk.emit(task_id, "content", {
                        "type": "content",
                        "text": chunk.content
                    })
                
                # 保存 usage 信息（最后一块）
                if chunk.usage:
                    usage = chunk.usage
                
                # 检查是否结束
                if chunk.is_finished:
                    break
            
            # 确保所有数据发送完毕
            if self.throttler:
                await self.throttler.flush_all(task_id)
            
            # 发送完成信号
            result = {
                "content": content,
                "reasoning_content": reasoning_content if reasoning_content else None,
                "usage": usage
            }
            
            # 保存结果供 get_result() 使用
            self._last_result = result
            
            self.generation_complete.emit(task_id, result)
            
            if self.logger:
                self.logger.info(
                    f"LLM generation completed: task_id={task_id}, "
                    f"content_length={len(content)}, "
                    f"reasoning_length={len(reasoning_content)}"
                )
                
        except asyncio.CancelledError:
            # 任务被取消，刷新节流器并发送部分结果
            if self.throttler:
                await self.throttler.flush_all(task_id)
            
            # 关闭异步生成器（3.0.10）
            if stream_gen:
                try:
                    await stream_gen.aclose()
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"Failed to close stream generator: {e}")
            
            # 清理所有注册的资源（3.0.10）
            if self.resource_cleanup:
                cleanup_result = await self.resource_cleanup.cleanup_all()
                if self.logger:
                    self.logger.debug(
                        f"Resource cleanup: success={cleanup_result.success}, "
                        f"failed={cleanup_result.failed}"
                    )
            
            # 确定停止原因
            stop_reason = "user_cancelled"
            if self.stop_controller:
                stop_reason_enum = self.stop_controller.get_stop_reason()
                if stop_reason_enum:
                    stop_reason = stop_reason_enum.value
            
            # 提取已生成的 token 数
            tokens_generated = 0
            if usage and isinstance(usage, dict):
                # 尝试从不同字段提取 token 数
                tokens_generated = (
                    usage.get("completion_tokens") or 
                    usage.get("output_tokens") or 
                    usage.get("generated_tokens") or 
                    0
                )
            
            # 构建完整的部分结果结构
            partial_result = {
                "content": content,
                "reasoning_content": reasoning_content if reasoning_content else None,
                "usage": usage,
                "is_partial": True,  # 标记为部分结果
                "stop_reason": stop_reason,  # 停止原因
                "tokens_generated": tokens_generated  # 已生成的 token 数
            }
            
            # 保存部分结果供 get_result() 使用
            self._last_result = partial_result
            
            # 发送 generation_complete 信号（即使是部分结果）
            self.generation_complete.emit(task_id, partial_result)
            
            # 通知 StopController
            if self.stop_controller:
                self.stop_controller.mark_stopping()
                self.stop_controller.mark_stopped({
                    "is_partial": True,
                    "cleanup_success": True,
                    "partial_result": partial_result
                })
            
            if self.logger:
                self.logger.info(
                    f"LLM generation cancelled with partial result: task_id={task_id}, "
                    f"partial_content_length={len(content)}, "
                    f"tokens_generated={tokens_generated}, "
                    f"stop_reason={stop_reason}"
                )
            
            raise
            
        except Exception as e:
            # 生成错误，清理资源（3.0.10）
            if stream_gen:
                try:
                    await stream_gen.aclose()
                except Exception:
                    pass
            
            if self.resource_cleanup:
                await self.resource_cleanup.cleanup_all()
            
            error_msg = self._format_error_message(e)
            self.generation_error.emit(task_id, error_msg)
            raise
    
    async def _non_stream_generate(
        self,
        task_id: str,
        client: BaseLLMClient,
        messages: List[Dict[str, Any]],
        model: str,
        tools: Optional[List[Dict[str, Any]]],
        thinking: bool,
        **kwargs
    ) -> Dict[str, Any]:
        """
        非流式生成内部实现
        
        Args:
            task_id: 任务标识
            client: LLM 客户端
            messages: 消息列表
            model: 模型名称
            tools: 工具定义列表
            thinking: 是否启用深度思考
            **kwargs: 其他参数
            
        Returns:
            dict: 生成结果
        """
        try:
            # 停止检查点：在开始长时间操作前检查
            if self._check_stop_requested():
                if self.logger:
                    self.logger.info(f"Stop requested before LLM call: task_id={task_id}")
                raise asyncio.CancelledError()
            
            # 调用客户端的非流式生成方法
            response = client.chat(
                messages=messages,
                model=model,
                streaming=False,
                tools=tools,
                thinking=thinking,
                **kwargs
            )
            
            # 构建结果
            result = {
                "content": response.content,
                "reasoning_content": response.reasoning_content,
                "tool_calls": response.tool_calls,
                "usage": response.usage,
                "finish_reason": response.finish_reason
            }
            
            # 保存结果供 get_result() 使用
            self._last_result = result
            
            # 发送完成信号
            self.generation_complete.emit(task_id, result)
            
            if self.logger:
                self.logger.info(
                    f"LLM generation completed: task_id={task_id}, "
                    f"content_length={len(response.content)}"
                )
            
            return result
            
        except Exception as e:
            # 生成错误
            error_msg = self._format_error_message(e)
            self.generation_error.emit(task_id, error_msg)
            raise
    
    # ============================================================
    # 异步生成器接口（推荐用于 AsyncTaskRegistry）
    # ============================================================
    
    async def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        thinking: bool = False,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式生成异步生成器
        
        返回异步生成器，逐块产出 chunk 数据。
        适合与 AsyncTaskRegistry 配合使用。
        
        Args:
            messages: 消息列表
            model: 模型名称
            tools: 工具定义列表
            thinking: 是否启用深度思考
            **kwargs: 其他参数
            
        Yields:
            dict: chunk 数据，格式为 {"type": "reasoning"|"content", "text": str}
            
        Example:
            async for chunk in executor.generate_stream(messages, model):
                event_bus.publish_throttled(EVENT_LLM_CHUNK, {"chunk": chunk})
            result = executor.get_result()
        """
        if self.logger:
            self.logger.info(
                f"Starting LLM stream generation: model={model}, thinking={thinking}"
            )
        
        # 获取 LLM 客户端
        client = self._get_llm_client(model)
        if not client:
            error_msg = f"LLM client not available for model: {model}"
            if self.logger:
                self.logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        # 累积内容
        reasoning_content = ""
        content = ""
        usage = None
        stream_gen = None
        
        try:
            # 停止检查点
            if self._check_stop_requested():
                if self.logger:
                    self.logger.info("Stop requested before LLM stream call")
                return
            
            # 调用客户端的流式生成方法
            stream_gen = client.chat_stream(
                messages=messages,
                model=model,
                tools=tools,
                thinking=thinking,
                **kwargs
            )
            
            # 注册异步生成器到资源清理管理器
            if self.resource_cleanup and stream_gen:
                self.resource_cleanup.register_async_generator(
                    stream_gen, f"llm_stream_gen"
                )
            
            async for chunk in stream_gen:
                # 停止检查点
                if self._check_stop_requested():
                    if self.logger:
                        self.logger.info("Stop requested during streaming")
                    # 主动抛出 CancelledError 以触发统一的停止处理逻辑
                    raise asyncio.CancelledError()
                
                # 检查是否被取消
                if asyncio.current_task() and asyncio.current_task().cancelled():
                    raise asyncio.CancelledError()
                
                # 处理思考内容
                if chunk.reasoning_content:
                    reasoning_content += chunk.reasoning_content
                    yield {
                        "type": "reasoning",
                        "text": chunk.reasoning_content
                    }
                
                # 处理回答内容
                if chunk.content:
                    content += chunk.content
                    yield {
                        "type": "content",
                        "text": chunk.content
                    }
                
                # 保存 usage 信息
                if chunk.usage:
                    usage = chunk.usage
                
                # 检查是否结束
                if chunk.is_finished:
                    break
            
            # 构建并保存最终结果
            self._last_result = {
                "content": content,
                "reasoning_content": reasoning_content if reasoning_content else None,
                "usage": usage,
                "is_partial": self._check_stop_requested(),
            }
            
            if self.logger:
                self.logger.info(
                    f"LLM stream generation completed: "
                    f"content_length={len(content)}, "
                    f"reasoning_length={len(reasoning_content)}"
                )
                
        except asyncio.CancelledError:
            # 任务被取消，保存部分结果
            stop_reason = "cancelled"
            if self.stop_controller:
                stop_reason_enum = self.stop_controller.get_stop_reason()
                if stop_reason_enum:
                    stop_reason = stop_reason_enum.value
            
            self._last_result = {
                "content": content,
                "reasoning_content": reasoning_content if reasoning_content else None,
                "usage": usage,
                "is_partial": True,
                "stop_reason": stop_reason,
            }
            
            # 关闭异步生成器
            if stream_gen:
                try:
                    await stream_gen.aclose()
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"Failed to close stream generator: {e}")
            
            # 通知 StopController（如果是通过停止检查点触发的）
            if self.stop_controller:
                self.stop_controller.mark_stopping()
                self.stop_controller.mark_stopped({
                    "is_partial": True,
                    "cleanup_success": True,
                    "partial_content": content,
                })
            
            if self.logger:
                self.logger.info(
                    f"LLM stream generation cancelled: "
                    f"partial_content_length={len(content)}, "
                    f"stop_reason={stop_reason}"
                )
            
            raise
            
        except Exception as e:
            # 生成错误，保存部分结果
            self._last_result = {
                "content": content,
                "reasoning_content": reasoning_content if reasoning_content else None,
                "usage": usage,
                "is_partial": True,
                "error": str(e),
            }
            
            if stream_gen:
                try:
                    await stream_gen.aclose()
                except Exception:
                    pass
            
            if self.logger:
                self.logger.error(f"LLM stream generation failed: {e}")
            
            raise
    
    def get_result(self) -> Optional[Dict[str, Any]]:
        """
        获取最后一次生成的完整结果
        
        在 generate_stream() 完成后调用，获取累积的完整结果。
        
        Returns:
            dict: 生成结果，包含 content, reasoning_content, usage 等
            None: 如果没有可用结果
            
        Example:
            async for chunk in executor.generate_stream(messages, model):
                # 处理 chunk...
                pass
            result = executor.get_result()
        """
        return self._last_result
    
    def clear_result(self) -> None:
        """
        清除缓存的结果
        
        在开始新的生成任务前调用，确保不会返回旧结果。
        """
        self._last_result = None
    
    # ============================================================
    # 任务取消
    # ============================================================
    
    def cancel(self, task_id: str) -> bool:
        """
        取消生成任务
        
        Args:
            task_id: 任务标识
            
        Returns:
            bool: 是否成功取消
        """
        if task_id in self._running_tasks:
            task = self._running_tasks[task_id]
            if not task.done():
                task.cancel()
                
                if self.logger:
                    self.logger.info(f"LLM generation cancellation requested: task_id={task_id}")
                
                return True
        
        # 尝试通过 AsyncTaskRegistry 取消
        if self.task_registry:
            return self.task_registry.cancel(task_id)
        
        return False
    
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
        if not self.external_service:
            if self.logger:
                self.logger.error("ExternalServiceManager not available")
            return None
        
        # 根据模型名称确定服务类型
        service_type = self._get_service_type_by_model(model)
        if not service_type:
            if self.logger:
                self.logger.error(f"Unknown model: {model}")
            return None
        
        # 获取客户端
        client = self.external_service.get_client(service_type)
        if not client:
            if self.logger:
                self.logger.error(f"LLM client not registered for service: {service_type}")
            return None
        
        return client
    
    def _get_service_type_by_model(self, model: str) -> Optional[str]:
        """
        根据模型名称确定服务类型
        
        Args:
            model: 模型名称
            
        Returns:
            str: 服务类型常量，未知返回 None
        """
        from domain.llm.external_service_manager import (
            SERVICE_LLM_ZHIPU,
            SERVICE_LLM_GEMINI,
            SERVICE_LLM_OPENAI,
            SERVICE_LLM_CLAUDE,
            SERVICE_LLM_QWEN,
            SERVICE_LLM_DEEPSEEK,
        )
        
        model_lower = model.lower()
        
        # 智谱 GLM
        if "glm" in model_lower or "zhipu" in model_lower:
            return SERVICE_LLM_ZHIPU
        
        # Google Gemini
        if "gemini" in model_lower:
            return SERVICE_LLM_GEMINI
        
        # OpenAI GPT
        if "gpt" in model_lower or "openai" in model_lower:
            return SERVICE_LLM_OPENAI
        
        # Anthropic Claude
        if "claude" in model_lower:
            return SERVICE_LLM_CLAUDE
        
        # 阿里通义千问
        if "qwen" in model_lower or "tongyi" in model_lower:
            return SERVICE_LLM_QWEN
        
        # DeepSeek
        if "deepseek" in model_lower:
            return SERVICE_LLM_DEEPSEEK
        
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
