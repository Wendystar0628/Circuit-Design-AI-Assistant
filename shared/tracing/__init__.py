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
"""

from shared.tracing.tracing_types import (
    TraceStatus,
    SpanType,
    SpanRecord,
)

__all__ = [
    # 数据类型
    "TraceStatus",
    "SpanType",
    "SpanRecord",
]
