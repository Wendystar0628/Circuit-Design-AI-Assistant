# Tracing Events - EventBus Event Definitions
"""
追踪事件定义

职责：
- 定义追踪系统相关的 EventBus 事件常量
- 提供事件数据结构文档

设计说明：
- 事件命名遵循 "tracing.{action}" 格式
- 与 shared/event_types.py 中的事件分开，保持追踪模块独立性
- 事件数据结构在文档中说明，便于订阅者理解

使用示例：
    from shared.tracing import TracingEvents
    from shared.event_bus import EventBus
    
    # 订阅事件
    event_bus.subscribe(TracingEvents.SPANS_FLUSHED, on_spans_flushed)
    
    # 发布事件
    event_bus.publish(TracingEvents.SPAN_ENDED, {
        "trace_id": "trace_xxx",
        "span_id": "span_xxx",
        "status": "success",
        "duration_ms": 123.4,
    })
"""


class TracingEvents:
    """
    追踪系统事件定义
    
    所有事件通过 EventBus 发布和订阅。
    事件数据结构见各事件的文档注释。
    """
    
    # --------------------------------------------------------
    # Span 生命周期事件
    # --------------------------------------------------------
    
    SPAN_STARTED = "tracing.span_started"
    """
    Span 开始事件
    
    数据结构：
        {
            "trace_id": str,        # 追踪 ID
            "span_id": str,         # Span ID
            "parent_span_id": str,  # 父 Span ID（可能为 None）
            "operation_name": str,  # 操作名称
            "service_name": str,    # 服务名称
            "start_time": float,    # 开始时间戳
        }
    """
    
    SPAN_ENDED = "tracing.span_ended"
    """
    Span 结束事件
    
    数据结构：
        {
            "trace_id": str,        # 追踪 ID
            "span_id": str,         # Span ID
            "operation_name": str,  # 操作名称
            "service_name": str,    # 服务名称
            "status": str,          # 状态（"success", "error", "cancelled"）
            "duration_ms": float,   # 耗时（毫秒）
            "has_error": bool,      # 是否有错误
        }
    """
    
    # --------------------------------------------------------
    # 追踪链路事件
    # --------------------------------------------------------
    
    TRACE_STARTED = "tracing.trace_started"
    """
    新追踪链路开始事件
    
    数据结构：
        {
            "trace_id": str,        # 追踪 ID
            "operation_name": str,  # 根操作名称
            "service_name": str,    # 服务名称
            "start_time": float,    # 开始时间戳
        }
    """
    
    TRACE_COMPLETED = "tracing.trace_completed"
    """
    追踪链路完成事件
    
    数据结构：
        {
            "trace_id": str,        # 追踪 ID
            "span_count": int,      # Span 总数
            "duration_ms": float,   # 总耗时（毫秒）
            "has_error": bool,      # 是否有错误
        }
    """
    
    # --------------------------------------------------------
    # 批量刷新事件
    # --------------------------------------------------------
    
    SPANS_FLUSHED = "tracing.spans_flushed"
    """
    批量写入完成事件
    
    由 TracingLogger 在批量写入 SQLite 后发布。
    DevToolsPanel 订阅此事件以增量更新 UI。
    
    数据结构：
        {
            "count": int,           # 写入的 Span 数量
            "timestamp": float,     # 刷新时间戳
        }
    """
    
    # --------------------------------------------------------
    # 错误事件
    # --------------------------------------------------------
    
    SPAN_ERROR = "tracing.span_error"
    """
    Span 执行出错事件
    
    当 Span 以 ERROR 状态结束时发布。
    DevToolsPanel 订阅此事件以高亮显示错误。
    
    数据结构：
        {
            "trace_id": str,        # 追踪 ID
            "span_id": str,         # Span ID
            "operation_name": str,  # 操作名称
            "service_name": str,    # 服务名称
            "error_message": str,   # 错误信息
            "duration_ms": float,   # 耗时（毫秒）
        }
    """
    
    # --------------------------------------------------------
    # 异步槽错误事件
    # --------------------------------------------------------
    
    ASYNC_SLOT_ERROR = "tracing.async_slot_error"
    """
    异步槽函数错误事件
    
    由 @safe_async_slot 装饰器在捕获异常时发布。
    
    数据结构：
        {
            "function": str,        # 函数名
            "error": str,           # 错误信息
            "error_type": str,      # 错误类型
            "traceback": str,       # 完整堆栈跟踪
        }
    """


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "TracingEvents",
]
