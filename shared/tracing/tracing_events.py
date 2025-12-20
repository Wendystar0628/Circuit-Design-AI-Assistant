# Tracing Events - EventBus Event Definitions
"""
追踪系统事件定义

职责：
- 定义追踪系统相关的 EventBus 事件
- 提供事件数据结构说明

事件数据结构：
- SPAN_STARTED: {"trace_id", "span_id", "operation_name", "service_name"}
- SPAN_ENDED: {"trace_id", "span_id", "status", "duration_ms"}
- SPANS_FLUSHED: {"count"}
- TRACE_STARTED: {"trace_id", "operation_name"}
- TRACE_COMPLETED: {"trace_id", "duration_ms", "span_count"}
- SPAN_ERROR: {"trace_id", "span_id", "error_message"}
"""


class TracingEvents:
    """追踪系统事件常量"""
    
    # --------------------------------------------------------
    # Span 生命周期事件
    # --------------------------------------------------------
    
    # Span 开始
    # 携带数据：
    #   - trace_id: str - 追踪 ID
    #   - span_id: str - Span ID
    #   - operation_name: str - 操作名称
    #   - service_name: str - 服务名称
    SPAN_STARTED = "tracing.span_started"
    
    # Span 结束
    # 携带数据：
    #   - trace_id: str - 追踪 ID
    #   - span_id: str - Span ID
    #   - status: str - 状态（success/error/cancelled）
    #   - duration_ms: float - 耗时（毫秒）
    SPAN_ENDED = "tracing.span_ended"
    
    # --------------------------------------------------------
    # 批量刷新事件
    # --------------------------------------------------------
    
    # 批量写入完成
    # 携带数据：
    #   - count: int - 写入的 Span 数量
    SPANS_FLUSHED = "tracing.spans_flushed"
    
    # --------------------------------------------------------
    # 追踪链路事件
    # --------------------------------------------------------
    
    # 新追踪链路开始
    # 携带数据：
    #   - trace_id: str - 追踪 ID
    #   - operation_name: str - 根操作名称
    TRACE_STARTED = "tracing.trace_started"
    
    # 追踪链路完成
    # 携带数据：
    #   - trace_id: str - 追踪 ID
    #   - duration_ms: float - 总耗时（毫秒）
    #   - span_count: int - Span 数量
    TRACE_COMPLETED = "tracing.trace_completed"
    
    # --------------------------------------------------------
    # 错误事件
    # --------------------------------------------------------
    
    # Span 执行出错
    # 携带数据：
    #   - trace_id: str - 追踪 ID
    #   - span_id: str - Span ID
    #   - error_message: str - 错误信息
    #   - error_type: str - 错误类型（可选）
    SPAN_ERROR = "tracing.span_error"


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "TracingEvents",
]
