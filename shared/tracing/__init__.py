# Tracing Module - Observability Infrastructure
"""
追踪模块 - 可观测性基础设施

职责：
- 提供分布式追踪能力
- 记录 LLM 调用、工具执行、工作流节点等操作
- 支持异常捕获和性能分析

模块结构：
- tracing_types.py: 数据类型定义（SpanRecord、TraceStatus 等）
- tracing_context.py: 上下文管理（contextvars 封装）
- tracing_logger.py: 追踪日志记录器（内存缓冲 + 定时刷新）
- tracing_store.py: SQLite 存储（aiosqlite 异步写入）
- tracing_events.py: 追踪相关事件定义
- safe_async_slot.py: qasync 异常捕获装饰器

设计原则：
- 追踪系统绝不能阻塞业务系统（可观测性第一原则）
- 采用内存缓冲 + 定时刷新 + aiosqlite 方案
- 上下文穿透通过 contextvars + LangGraph config["configurable"] 实现
- 可视化更新通过 EventBus 事件驱动，不轮询数据库

使用示例：
    from shared.tracing import TracingContext, SpanType
    
    # 开始追踪链路
    async with TracingContext.trace("user_request") as trace:
        # 创建子 Span
        async with TracingContext.span(SpanType.LLM_CALL, "llm_executor") as span:
            span.set_input({"messages": messages})
            result = await llm_client.chat(messages)
            span.set_output({"response": result})
    
    # LangGraph 节点中恢复上下文
    async def my_node(state, config):
        TracingContext.restore_from_langgraph(config)
        async with TracingContext.span("my_node", "graph"):
            ...
"""

from shared.tracing.tracing_types import (
    TraceStatus,
    SpanType,
    SpanRecord,
)
from shared.tracing.tracing_context import (
    TracingContext,
    SpanContext,
)
from shared.tracing.tracing_events import TracingEvents
from shared.tracing.tracing_logger import TracingLogger
from shared.tracing.tracing_store import TracingStore

__all__ = [
    # 数据类型
    "TraceStatus",
    "SpanType",
    "SpanRecord",
    # 上下文管理
    "TracingContext",
    "SpanContext",
    # 事件定义
    "TracingEvents",
    # 日志记录器
    "TracingLogger",
    # 存储
    "TracingStore",
]
