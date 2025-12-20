# Tracing Context - Coroutine-Safe Context Propagation
"""
追踪上下文管理

职责：
- 管理追踪上下文的创建、传递、恢复
- 使用 contextvars 实现协程安全的上下文传递
- 解决 LangGraph 节点边界的上下文穿透问题

设计说明：
- contextvars 在同一协程链中自动传递
- LangGraph 节点是独立协程，需要通过 config["configurable"] 手动传递
- PyQt 信号在同线程内不会丢失 contextvars

使用示例：
    # 开始追踪链路
    async with TracingContext.trace("user_request") as trace:
        # 创建子 Span
        async with TracingContext.span("llm_call", "llm_executor") as span:
            span.set_input({"messages": messages})
            result = await llm_client.chat(messages)
            span.set_output({"response": result})
    
    # LangGraph 节点中恢复上下文
    async def my_node(state, config):
        TracingContext.restore_from_langgraph(config)
        async with TracingContext.span("my_node", "graph") as span:
            ...
"""

import uuid
from contextvars import ContextVar, copy_context
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from shared.tracing.tracing_types import SpanRecord, TraceStatus, SpanType

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig


# ============================================================
# Context Variables（协程安全）
# ============================================================

# 当前追踪 ID
_current_trace_id: ContextVar[Optional[str]] = ContextVar(
    'tracing_trace_id', default=None
)

# 当前 Span ID
_current_span_id: ContextVar[Optional[str]] = ContextVar(
    'tracing_span_id', default=None
)

# Span 栈（用于嵌套 Span 的父子关系）
_span_stack: ContextVar[List[str]] = ContextVar(
    'tracing_span_stack', default=[]
)


# ============================================================
# ID 生成
# ============================================================

def _generate_trace_id() -> str:
    """生成追踪 ID（16 字符）"""
    return f"trace_{uuid.uuid4().hex[:16]}"


def _generate_span_id() -> str:
    """生成 Span ID（12 字符）"""
    return f"span_{uuid.uuid4().hex[:12]}"


# ============================================================
# Span Context（上下文管理器返回的对象）
# ============================================================

@dataclass
class SpanContext:
    """
    Span 上下文对象
    
    由 TracingContext.span() 返回，提供设置输入输出的便捷方法。
    在 async with 块结束时自动完成 Span。
    """
    record: SpanRecord
    _finished: bool = field(default=False, repr=False)
    
    def set_input(self, inputs: Dict[str, Any]) -> 'SpanContext':
        """设置输入参数"""
        self.record.set_input(inputs)
        return self
    
    def set_output(self, outputs: Dict[str, Any]) -> 'SpanContext':
        """设置输出结果"""
        self.record.set_output(outputs)
        return self
    
    def set_error(self, error_message: str) -> 'SpanContext':
        """设置错误信息"""
        self.record.set_error(error_message)
        return self
    
    def add_metadata(self, key: str, value: Any) -> 'SpanContext':
        """添加元数据"""
        self.record.add_metadata(key, value)
        return self
    
    def finish(
        self,
        status: TraceStatus = TraceStatus.SUCCESS,
        outputs: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> 'SpanContext':
        """
        手动结束 Span
        
        通常不需要调用，async with 块结束时会自动调用。
        """
        if not self._finished:
            self.record.finish(status, outputs, error_message)
            self._finished = True
        return self
    
    @property
    def trace_id(self) -> str:
        return self.record.trace_id
    
    @property
    def span_id(self) -> str:
        return self.record.span_id
    
    @property
    def duration_ms(self) -> Optional[float]:
        return self.record.duration_ms()


# ============================================================
# TracingContext（主接口）
# ============================================================

class TracingContext:
    """
    追踪上下文管理器
    
    提供追踪链路和 Span 的创建、管理功能。
    使用 contextvars 实现协程安全的上下文传递。
    
    类方法设计：所有方法都是类方法或静态方法，无需实例化。
    """
    
    # 回调函数：Span 完成时调用（由 TracingLogger 设置）
    _on_span_finished: Optional[callable] = None
    
    # --------------------------------------------------------
    # 上下文获取
    # --------------------------------------------------------
    
    @classmethod
    def get_current_trace_id(cls) -> Optional[str]:
        """获取当前追踪 ID"""
        return _current_trace_id.get()
    
    @classmethod
    def get_current_span_id(cls) -> Optional[str]:
        """获取当前 Span ID"""
        return _current_span_id.get()
    
    @classmethod
    def get_parent_span_id(cls) -> Optional[str]:
        """获取父 Span ID（栈顶的上一个）"""
        stack = _span_stack.get()
        if len(stack) >= 2:
            return stack[-2]
        return None
    
    @classmethod
    def is_tracing(cls) -> bool:
        """是否在追踪上下文中"""
        return _current_trace_id.get() is not None
    
    # --------------------------------------------------------
    # 追踪链路管理
    # --------------------------------------------------------
    
    @classmethod
    @asynccontextmanager
    async def trace(
        cls,
        operation_name: str,
        service_name: str = "app",
        inputs: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        开始新的追踪链路
        
        创建根 Span，设置 trace_id 到上下文。
        
        Args:
            operation_name: 操作名称
            service_name: 服务名称
            inputs: 输入参数
            metadata: 元数据
            
        Yields:
            SpanContext: Span 上下文对象
            
        Example:
            async with TracingContext.trace("user_request") as trace:
                # trace.trace_id 可用于关联后续操作
                await process_request()
        """
        # 生成新的 trace_id
        trace_id = _generate_trace_id()
        span_id = _generate_span_id()
        
        # 创建根 Span
        record = SpanRecord(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=None,  # 根 Span 无父节点
            operation_name=operation_name,
            service_name=service_name,
            inputs=inputs,
            metadata=metadata,
        )
        
        # 设置上下文
        trace_token = _current_trace_id.set(trace_id)
        span_token = _current_span_id.set(span_id)
        stack = _span_stack.get().copy()
        stack.append(span_id)
        stack_token = _span_stack.set(stack)
        
        span_ctx = SpanContext(record=record)
        
        try:
            yield span_ctx
            # 正常完成
            if not span_ctx._finished:
                span_ctx.finish(TraceStatus.SUCCESS)
        except Exception as e:
            # 异常时标记错误
            if not span_ctx._finished:
                span_ctx.finish(TraceStatus.ERROR, error_message=str(e))
            raise
        finally:
            # 恢复上下文
            _current_trace_id.reset(trace_token)
            _current_span_id.reset(span_token)
            _span_stack.reset(stack_token)
            
            # 通知 TracingLogger
            cls._notify_span_finished(span_ctx.record)
    
    # --------------------------------------------------------
    # Span 管理
    # --------------------------------------------------------
    
    @classmethod
    @asynccontextmanager
    async def span(
        cls,
        operation_name: str,
        service_name: str = "app",
        inputs: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        创建子 Span
        
        自动关联当前 trace_id 和父 span_id。
        如果不在追踪上下文中，会自动创建新的追踪链路。
        
        Args:
            operation_name: 操作名称
            service_name: 服务名称
            inputs: 输入参数
            metadata: 元数据
            
        Yields:
            SpanContext: Span 上下文对象
            
        Example:
            async with TracingContext.span("llm_call", "llm_executor") as span:
                span.set_input({"model": "glm-4"})
                result = await llm.chat(messages)
                span.set_output({"response": result})
        """
        # 获取当前上下文
        trace_id = _current_trace_id.get()
        parent_span_id = _current_span_id.get()
        
        # 如果不在追踪上下文中，创建新的追踪链路
        if trace_id is None:
            async with cls.trace(operation_name, service_name, inputs, metadata) as ctx:
                yield ctx
            return
        
        # 生成新的 span_id
        span_id = _generate_span_id()
        
        # 创建 Span 记录
        record = SpanRecord(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            operation_name=operation_name,
            service_name=service_name,
            inputs=inputs,
            metadata=metadata,
        )
        
        # 更新上下文（仅更新 span_id 和栈）
        span_token = _current_span_id.set(span_id)
        stack = _span_stack.get().copy()
        stack.append(span_id)
        stack_token = _span_stack.set(stack)
        
        span_ctx = SpanContext(record=record)
        
        try:
            yield span_ctx
            # 正常完成
            if not span_ctx._finished:
                span_ctx.finish(TraceStatus.SUCCESS)
        except Exception as e:
            # 异常时标记错误
            if not span_ctx._finished:
                span_ctx.finish(TraceStatus.ERROR, error_message=str(e))
            raise
        finally:
            # 恢复上下文
            _current_span_id.reset(span_token)
            _span_stack.reset(stack_token)
            
            # 通知 TracingLogger
            cls._notify_span_finished(span_ctx.record)
    
    # --------------------------------------------------------
    # LangGraph 边界穿透
    # --------------------------------------------------------
    
    @classmethod
    def get_context_for_langgraph(cls) -> Dict[str, Any]:
        """
        导出上下文到 LangGraph config
        
        在调用 graph.ainvoke() 前调用，将追踪上下文放入 config。
        
        Returns:
            dict: 包含 trace_id 和 parent_span_id 的字典
            
        Example:
            config = {
                "configurable": {
                    "thread_id": thread_id,
                    **TracingContext.get_context_for_langgraph(),
                }
            }
            result = await graph.ainvoke(state, config)
        """
        return {
            "trace_id": _current_trace_id.get(),
            "parent_span_id": _current_span_id.get(),
        }
    
    @classmethod
    def restore_from_langgraph(cls, config: 'RunnableConfig') -> None:
        """
        从 LangGraph config 恢复上下文
        
        在 LangGraph 节点入口处调用，恢复追踪上下文。
        
        Args:
            config: LangGraph RunnableConfig
            
        Example:
            async def my_node(state, config):
                TracingContext.restore_from_langgraph(config)
                async with TracingContext.span("my_node", "graph"):
                    ...
        """
        configurable = config.get("configurable", {})
        trace_id = configurable.get("trace_id")
        parent_span_id = configurable.get("parent_span_id")
        
        if trace_id:
            _current_trace_id.set(trace_id)
        if parent_span_id:
            _current_span_id.set(parent_span_id)
            # 重建栈（仅包含父 span）
            _span_stack.set([parent_span_id])
    
    # --------------------------------------------------------
    # 跨线程上下文传递（用于 QMetaObject.invokeMethod）
    # --------------------------------------------------------
    
    @classmethod
    def export_context(cls) -> Dict[str, Any]:
        """
        导出当前上下文（用于跨线程传递）
        
        Returns:
            dict: 包含完整上下文信息的字典
        """
        return {
            "trace_id": _current_trace_id.get(),
            "span_id": _current_span_id.get(),
            "span_stack": _span_stack.get().copy(),
        }
    
    @classmethod
    def import_context(cls, context: Dict[str, Any]) -> None:
        """
        导入上下文（用于跨线程恢复）
        
        Args:
            context: export_context() 返回的字典
        """
        if context.get("trace_id"):
            _current_trace_id.set(context["trace_id"])
        if context.get("span_id"):
            _current_span_id.set(context["span_id"])
        if context.get("span_stack"):
            _span_stack.set(context["span_stack"])
    
    # --------------------------------------------------------
    # 回调注册（由 TracingLogger 调用）
    # --------------------------------------------------------
    
    @classmethod
    def set_span_finished_callback(cls, callback: callable) -> None:
        """
        设置 Span 完成回调
        
        由 TracingLogger 在初始化时调用，用于接收完成的 Span 记录。
        
        Args:
            callback: 回调函数，签名为 (SpanRecord) -> None
        """
        cls._on_span_finished = callback
    
    @classmethod
    def _notify_span_finished(cls, record: SpanRecord) -> None:
        """通知 Span 完成"""
        if cls._on_span_finished is not None:
            try:
                cls._on_span_finished(record)
            except Exception:
                # 追踪系统不应影响业务逻辑
                pass
    
    # --------------------------------------------------------
    # 便捷方法
    # --------------------------------------------------------
    
    @classmethod
    def record_error(cls, operation_name: str, error: Exception) -> None:
        """
        记录错误（不创建 Span）
        
        用于在异常处理中快速记录错误，不需要完整的 Span 生命周期。
        
        Args:
            operation_name: 操作名称
            error: 异常对象
        """
        trace_id = _current_trace_id.get() or _generate_trace_id()
        span_id = _generate_span_id()
        parent_span_id = _current_span_id.get()
        
        record = SpanRecord(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            operation_name=operation_name,
            service_name="error_handler",
            status=TraceStatus.ERROR,
            error_message=str(error),
            metadata={"error_type": type(error).__name__},
        )
        record.finish(TraceStatus.ERROR, error_message=str(error))
        
        cls._notify_span_finished(record)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "TracingContext",
    "SpanContext",
]
