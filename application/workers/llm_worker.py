# LLM Worker - Background LLM API Caller
"""
LLM 生成线程 - 在后台线程中异步执行 LLM API 调用

职责：
- 在后台线程中异步执行 LLM API 调用，避免阻塞 GUI
- 支持流式和非流式输出
- 支持深度思考模式
- 处理错误和超时

初始化顺序：
- Phase 3 延迟初始化阶段
- 依赖 WorkerManager、ExternalServiceManager
- 注册到 WorkerManager

使用示例：
    worker = LLMWorker()
    worker.set_request(
        messages=[{"role": "user", "content": "Hello"}],
        streaming=True,
        thinking=True
    )
    worker.chunk.connect(on_chunk)
    worker.result.connect(on_result)
    worker.start()
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import pyqtSignal

from application.workers.base_worker import BaseWorker



# ============================================================
# 常量定义
# ============================================================

# Worker 类型标识
WORKER_TYPE_LLM = "llm_worker"

# 流式输出节流间隔（毫秒）
STREAM_THROTTLE_MS = 50

# 默认超时配置
DEFAULT_TIMEOUT = 60
DEFAULT_THINKING_TIMEOUT = 300


# ============================================================
# 数据结构
# ============================================================

@dataclass
class LLMRequest:
    """LLM 请求参数"""
    messages: List[Dict[str, Any]] = field(default_factory=list)
    model: Optional[str] = None
    streaming: bool = True
    tools: Optional[List[Dict[str, Any]]] = None
    thinking: bool = True
    timeout: Optional[int] = None


@dataclass
class LLMResult:
    """LLM 响应结果"""
    content: str = ""
    reasoning_content: str = ""
    tool_calls: Optional[List[Dict[str, Any]]] = None
    usage: Optional[Dict[str, Any]] = None
    is_partial: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "content": self.content,
            "reasoning_content": self.reasoning_content,
            "tool_calls": self.tool_calls,
            "usage": self.usage,
            "is_partial": self.is_partial,
        }


# ============================================================
# LLM Worker
# ============================================================

class LLMWorker(BaseWorker):
    """
    LLM 生成线程
    
    在后台线程中异步执行 LLM API 调用，支持：
    - 流式和非流式输出
    - 深度思考模式
    - 中途取消
    - 错误处理和重试
    
    信号说明：
    - chunk(str): 流式数据块，JSON 格式 {"type": "reasoning"|"content", "text": str}
    - phase_changed(str): 阶段切换信号，"reasoning" -> "content"
    - result(object): 完整响应结果
    - error(str, object): 错误信息
    """

    # 阶段切换信号：从思考阶段切换到回答阶段
    phase_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__(worker_type=WORKER_TYPE_LLM)
        
        # 请求参数
        self._request: Optional[LLMRequest] = None
        
        # 流式处理状态
        self._thinking_phase = True  # 当前是否在思考阶段
        self._last_chunk_time = 0.0  # 上次发送 chunk 的时间
        self._pending_chunk = ""     # 待发送的聚合内容
        
        # 延迟获取的服务
        self._config_manager = None
        self._llm_client = None


    # ============================================================
    # 服务获取
    # ============================================================

    @property
    def config_manager(self):
        """延迟获取 ConfigManager"""
        if self._config_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CONFIG_MANAGER
                self._config_manager = ServiceLocator.get_optional(SVC_CONFIG_MANAGER)
            except Exception:
                pass
        return self._config_manager

    @property
    def llm_client(self):
        """延迟获取 LLM 客户端"""
        if self._llm_client is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_LLM_CLIENT
                self._llm_client = ServiceLocator.get_optional(SVC_LLM_CLIENT)
            except Exception:
                pass
        return self._llm_client

    # ============================================================
    # 请求设置
    # ============================================================

    def set_request(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        streaming: bool = True,
        tools: Optional[List[Dict[str, Any]]] = None,
        thinking: Optional[bool] = None,
        timeout: Optional[int] = None,
    ) -> None:
        """
        设置请求参数
        
        Args:
            messages: 消息列表
            model: 模型名称（可选，使用配置默认值）
            streaming: 是否流式输出（默认 True）
            tools: 工具定义列表
            thinking: 是否启用深度思考（默认从配置读取）
            timeout: 超时秒数（可选，根据 thinking 自动选择）
        """
        # 从配置读取默认值
        if thinking is None:
            thinking = self._get_config("enable_thinking", True)
        
        if timeout is None:
            if thinking:
                timeout = self._get_config("thinking_timeout", DEFAULT_THINKING_TIMEOUT)
            else:
                timeout = self._get_config("timeout", DEFAULT_TIMEOUT)
        
        self._request = LLMRequest(
            messages=messages,
            model=model,
            streaming=streaming,
            tools=tools,
            thinking=thinking,
            timeout=timeout,
        )
        
        # 重置流式处理状态
        self._thinking_phase = True
        self._last_chunk_time = 0.0
        self._pending_chunk = ""

    def _get_config(self, key: str, default: Any) -> Any:
        """从 ConfigManager 获取配置"""
        if self.config_manager:
            return self.config_manager.get(key, default)
        return default


    # ============================================================
    # 任务执行
    # ============================================================

    def do_work(self) -> None:
        """
        执行 LLM 调用
        
        根据 streaming 参数选择流式或非流式调用。
        """
        if self._request is None:
            self.emit_error("No request set", ValueError("Request not configured"))
            return
        
        if self.llm_client is None:
            self.emit_error(
                "LLM client not available",
                RuntimeError("LLM client not initialized")
            )
            return
        
        if self.logger:
            self.logger.info(
                f"LLM request: streaming={self._request.streaming}, "
                f"thinking={self._request.thinking}, "
                f"timeout={self._request.timeout}s"
            )
        
        try:
            if self._request.streaming:
                self._do_streaming_call()
            else:
                self._do_non_streaming_call()
                
        except Exception as e:
            self._handle_error(e)

    def _do_non_streaming_call(self) -> None:
        """执行非流式调用"""
        if self.is_cancelled():
            return
        
        try:
            response = self.llm_client.chat(
                messages=self._request.messages,
                model=self._request.model,
                streaming=False,
                tools=self._request.tools,
                thinking=self._request.thinking,
            )
            
            if self.is_cancelled():
                return
            
            # 构建结果
            result = LLMResult(
                content=response.content,
                reasoning_content=response.reasoning_content or "",
                tool_calls=response.tool_calls,
                usage=self._extract_usage(response.usage),
                is_partial=False,
            )
            
            # 记录缓存统计
            self._log_cache_stats(result.usage)
            
            # 发送结果
            self.emit_result(result.to_dict())
            
            # 发布 LLM 完成事件
            self._publish_llm_complete_event(result)
            
        except Exception as e:
            raise e


    def _do_streaming_call(self) -> None:
        """执行流式调用"""
        import asyncio
        
        # 创建事件循环执行异步流式调用
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(self._async_streaming_call())
        finally:
            # 清理所有待处理的任务，避免 "Task was destroyed but it is pending" 警告
            self._cleanup_event_loop(loop)

    def _cleanup_event_loop(self, loop) -> None:
        """
        清理事件循环中的待处理任务
        
        在关闭事件循环前，确保所有异步生成器和任务都被正确清理，
        避免 "Task was destroyed but it is pending" 警告。
        
        Args:
            loop: 要清理的事件循环
        """
        import asyncio
        
        try:
            # 关闭所有异步生成器
            loop.run_until_complete(loop.shutdown_asyncgens())
            
            # 取消所有待处理的任务
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            
            # 等待所有任务完成取消
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
        except Exception:
            pass  # 清理失败不影响主流程
        finally:
            loop.close()

    async def _async_streaming_call(self) -> None:
        """异步流式调用"""
        result = LLMResult()
        stream = None
        
        try:
            # 获取异步生成器
            stream = self.llm_client.chat_stream(
                messages=self._request.messages,
                model=self._request.model,
                tools=self._request.tools,
                thinking=self._request.thinking,
            )
            
            async for chunk in stream:
                if self.is_cancelled():
                    result.is_partial = True
                    break
                
                # 处理思考内容
                if chunk.reasoning_content:
                    result.reasoning_content += chunk.reasoning_content
                    self._emit_throttled_chunk("reasoning", chunk.reasoning_content)
                
                # 处理回答内容
                if chunk.content:
                    # 检测阶段切换
                    if self._thinking_phase and result.reasoning_content:
                        self._thinking_phase = False
                        self._flush_pending_chunk()
                        self.phase_changed.emit("content")
                    
                    result.content += chunk.content
                    self._emit_throttled_chunk("content", chunk.content)
                
                # 处理最后一块的 usage 信息
                if chunk.is_finished and chunk.usage:
                    result.usage = self._extract_usage(chunk.usage)
            
            # 刷新剩余的待发送内容
            self._flush_pending_chunk()
            
            # 记录缓存统计
            self._log_cache_stats(result.usage)
            
            # 发送结果
            self.emit_result(result.to_dict())
            
            # 发布 LLM 完成事件
            self._publish_llm_complete_event(result)
            
        except Exception as e:
            # 流式传输中断，返回部分内容
            if result.content or result.reasoning_content:
                result.is_partial = True
                self.emit_result(result.to_dict())
            raise e
        finally:
            # 确保异步生成器被正确关闭
            if stream is not None:
                await stream.aclose()


    # ============================================================
    # 流式输出处理
    # ============================================================

    def _emit_throttled_chunk(self, chunk_type: str, text: str) -> None:
        """
        节流发送流式数据块
        
        按 50-100ms 间隔聚合后发送，避免过于频繁的 UI 更新。
        
        Args:
            chunk_type: 内容类型 ("reasoning" | "content")
            text: 文本内容
        """
        import json
        
        current_time = time.time() * 1000  # 转换为毫秒
        
        # 聚合内容
        self._pending_chunk += text
        
        # 检查是否需要发送
        if current_time - self._last_chunk_time >= STREAM_THROTTLE_MS:
            if self._pending_chunk:
                chunk_data = json.dumps({
                    "type": chunk_type,
                    "text": self._pending_chunk,
                })
                self.emit_chunk(chunk_data)
                self._pending_chunk = ""
                self._last_chunk_time = current_time

    def _flush_pending_chunk(self) -> None:
        """刷新待发送的聚合内容"""
        import json
        
        if self._pending_chunk:
            chunk_type = "reasoning" if self._thinking_phase else "content"
            chunk_data = json.dumps({
                "type": chunk_type,
                "text": self._pending_chunk,
            })
            self.emit_chunk(chunk_data)
            self._pending_chunk = ""

    # ============================================================
    # 响应处理
    # ============================================================

    def _extract_usage(self, usage: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        提取 Token 使用统计
        
        Args:
            usage: 原始 usage 数据
            
        Returns:
            标准化的 usage 字典
        """
        if not usage:
            return None
        
        result = {
            "total_tokens": usage.get("total_tokens", 0),
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "cached_tokens": 0,
        }
        
        # 提取缓存命中的 token 数
        prompt_details = usage.get("prompt_tokens_details", {})
        if prompt_details:
            result["cached_tokens"] = prompt_details.get("cached_tokens", 0)
        
        return result

    def _log_cache_stats(self, usage: Optional[Dict[str, Any]]) -> None:
        """记录缓存统计日志"""
        if not usage or not self.logger:
            return
        
        cached = usage.get("cached_tokens", 0)
        prompt = usage.get("prompt_tokens", 0)
        
        if prompt > 0 and cached > 0:
            hit_rate = (cached / prompt) * 100
            self.logger.info(
                f"Cache stats: {cached}/{prompt} tokens cached ({hit_rate:.1f}% hit rate)"
            )


    # ============================================================
    # 错误处理
    # ============================================================

    def _publish_llm_complete_event(self, result: LLMResult) -> None:
        """
        发布 LLM 完成事件
        
        Args:
            result: LLM 响应结果
        """
        if self.event_bus:
            from shared.event_types import EVENT_LLM_COMPLETE
            self.event_bus.publish(
                EVENT_LLM_COMPLETE,
                data={
                    "content": result.content,
                    "reasoning_content": result.reasoning_content,
                    "tool_calls": result.tool_calls,
                    "usage": result.usage,
                    "is_partial": result.is_partial,
                },
                source="llm_worker"
            )

    def _handle_error(self, error: Exception) -> None:
        """
        处理 LLM 调用错误
        
        根据错误类型生成适当的错误消息和建议。
        """
        from infrastructure.llm_adapters.base_client import (
            AuthError,
            RateLimitError,
            ContextOverflowError,
            ResponseParseError,
            APIError,
        )
        
        error_msg = str(error)
        
        if isinstance(error, AuthError):
            error_msg = "Authentication failed. Please check your API Key."
            if self.logger:
                self.logger.error(f"LLM auth error: {error}")
                
        elif isinstance(error, RateLimitError):
            retry_after = getattr(error, "retry_after", None)
            if retry_after:
                error_msg = f"Rate limit exceeded. Please wait {retry_after} seconds."
            else:
                error_msg = "Rate limit exceeded. Please try again later."
            if self.logger:
                self.logger.warning(f"LLM rate limit: {error}")
                
        elif isinstance(error, ContextOverflowError):
            max_tokens = getattr(error, "max_tokens", None)
            if max_tokens:
                error_msg = f"Context too long. Maximum: {max_tokens} tokens."
            else:
                error_msg = "Context too long. Please reduce message history."
            if self.logger:
                self.logger.warning(f"LLM context overflow: {error}")
                
        elif isinstance(error, ResponseParseError):
            error_msg = "Failed to parse LLM response."
            if self.logger:
                self.logger.error(f"LLM response parse error: {error}")
                
        elif isinstance(error, APIError):
            status_code = getattr(error, "status_code", None)
            if status_code:
                error_msg = f"API error (status {status_code}): {error}"
            if self.logger:
                self.logger.error(f"LLM API error: {error}")
                
        elif isinstance(error, TimeoutError):
            timeout = self._request.timeout if self._request else DEFAULT_TIMEOUT
            error_msg = f"Request timed out after {timeout} seconds."
            if self.logger:
                self.logger.error(f"LLM timeout: {error}")
                
        else:
            if self.logger:
                self.logger.error(f"LLM unexpected error: {error}", exc_info=True)
        
        self.emit_error(error_msg, error)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "LLMWorker",
    "LLMRequest",
    "LLMResult",
    "WORKER_TYPE_LLM",
]
