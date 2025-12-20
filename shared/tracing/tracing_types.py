# Tracing Types - Core Data Structures
"""
追踪数据类型定义

职责：
- 定义追踪系统的核心数据类型
- 与业务逻辑解耦
- 提供 SQLite 序列化支持

设计原则：
- 纯数据定义，不依赖其他业务模块
- 类型注解完整，便于 IDE 提示
- JSON 序列化使用标准库，避免额外依赖
"""

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class TraceStatus(Enum):
    """
    追踪状态枚举
    
    表示 Span 的执行状态
    """
    RUNNING = "running"      # 执行中
    SUCCESS = "success"      # 成功完成
    ERROR = "error"          # 执行出错
    CANCELLED = "cancelled"  # 被取消


class SpanType:
    """
    Span 类型常量
    
    定义各种操作类型，用于分类和过滤追踪记录
    """
    # LLM 相关
    LLM_CALL = "llm_call"              # LLM API 调用
    LLM_STREAM = "llm_stream"          # LLM 流式输出
    CONTEXT_BUILD = "context_build"    # 上下文构建
    
    # 工具执行
    TOOL_EXECUTE = "tool_execute"      # 工具执行
    TOOL_VALIDATE = "tool_validate"    # 工具参数验证
    
    # 仿真相关
    SIMULATION = "simulation"          # 仿真任务
    CIRCUIT_PARSE = "circuit_parse"    # 电路解析
    
    # RAG 相关
    RAG_SEARCH = "rag_search"          # RAG 检索
    RAG_RERANK = "rag_rerank"          # RAG 重排序
    EMBEDDING = "embedding"            # 向量嵌入
    
    # LangGraph 工作流
    GRAPH_NODE = "graph_node"          # LangGraph 节点
    GRAPH_EDGE = "graph_edge"          # LangGraph 边（条件路由）
    GRAPH_INVOKE = "graph_invoke"      # Graph 调用
    
    # 用户交互
    USER_INPUT = "user_input"          # 用户输入
    USER_ACTION = "user_action"        # 用户操作
    
    # 文件操作
    FILE_READ = "file_read"            # 文件读取
    FILE_WRITE = "file_write"          # 文件写入
    
    # 其他
    INTERNAL = "internal"              # 内部操作
    EXTERNAL_API = "external_api"      # 外部 API 调用


@dataclass
class SpanRecord:
    """
    单个追踪 Span 记录
    
    Span 是追踪系统的基本单元，表示一个操作的执行过程。
    多个 Span 通过 trace_id 关联形成完整的追踪链路。
    
    Attributes:
        trace_id: 追踪 ID（整个请求链路的唯一标识）
        span_id: Span ID（当前操作的唯一标识）
        parent_span_id: 父 Span ID（用于构建调用树）
        operation_name: 操作名称（如 "llm_call", "tool_execute"）
        service_name: 服务名称（如 "llm_executor", "simulation_service"）
        start_time: 开始时间戳（time.time()）
        end_time: 结束时间戳（None 表示仍在执行）
        status: 执行状态
        inputs: 输入参数（JSON 序列化存储）
        outputs: 输出结果（JSON 序列化存储）
        error_message: 错误信息（仅 ERROR 状态时有值）
        metadata: 额外元数据（如 model_name, token_count 等）
    """
    trace_id: str
    span_id: str
    operation_name: str
    service_name: str
    start_time: float = field(default_factory=time.time)
    parent_span_id: Optional[str] = None
    end_time: Optional[float] = None
    status: TraceStatus = TraceStatus.RUNNING
    inputs: Optional[Dict[str, Any]] = None
    outputs: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def duration_ms(self) -> Optional[float]:
        """
        计算执行耗时（毫秒）
        
        Returns:
            float: 耗时毫秒数，若未结束返回 None
        """
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000

    def duration_ms_or_elapsed(self) -> float:
        """
        计算执行耗时或已过时间（毫秒）
        
        若 Span 已结束，返回实际耗时；
        若仍在执行，返回从开始到现在的时间。
        
        Returns:
            float: 耗时或已过时间（毫秒）
        """
        end = self.end_time if self.end_time is not None else time.time()
        return (end - self.start_time) * 1000

    def finish(
        self,
        status: TraceStatus = TraceStatus.SUCCESS,
        outputs: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> 'SpanRecord':
        """
        结束 Span 执行
        
        Args:
            status: 最终状态
            outputs: 输出结果
            error_message: 错误信息（仅 ERROR 状态时设置）
            
        Returns:
            self: 返回自身，支持链式调用
        """
        self.end_time = time.time()
        self.status = status
        if outputs is not None:
            self.outputs = outputs
        if error_message is not None:
            self.error_message = error_message
        return self

    def set_input(self, inputs: Dict[str, Any]) -> 'SpanRecord':
        """设置输入参数"""
        self.inputs = inputs
        return self

    def set_output(self, outputs: Dict[str, Any]) -> 'SpanRecord':
        """设置输出结果"""
        self.outputs = outputs
        return self

    def set_error(self, error_message: str) -> 'SpanRecord':
        """设置错误信息并标记状态为 ERROR"""
        self.error_message = error_message
        self.status = TraceStatus.ERROR
        return self

    def add_metadata(self, key: str, value: Any) -> 'SpanRecord':
        """添加元数据"""
        if self.metadata is None:
            self.metadata = {}
        self.metadata[key] = value
        return self

    def to_main_tuple(self) -> tuple:
        """
        转换为 SQLite spans 主表插入元组
        
        对应字段：
        (trace_id, span_id, parent_span_id, operation_name, 
         service_name, start_time, end_time, status, error_message)
        """
        return (
            self.trace_id,
            self.span_id,
            self.parent_span_id,
            self.operation_name,
            self.service_name,
            self.start_time,
            self.end_time,
            self.status.value,
            self.error_message,
        )

    def to_data_tuple(self) -> tuple:
        """
        转换为 SQLite span_data 表插入元组
        
        对应字段：(span_id, inputs, outputs, metadata)
        JSON 序列化输入输出和元数据
        """
        return (
            self.span_id,
            self._serialize_json(self.inputs),
            self._serialize_json(self.outputs),
            self._serialize_json(self.metadata),
        )

    @staticmethod
    def _serialize_json(data: Optional[Dict[str, Any]]) -> Optional[str]:
        """
        安全地序列化 JSON 数据
        
        处理不可序列化的对象，转换为字符串表示
        """
        if data is None:
            return None
        try:
            return json.dumps(data, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            # 回退：将所有值转为字符串
            safe_data = {k: str(v) for k, v in data.items()}
            return json.dumps(safe_data, ensure_ascii=False)

    @classmethod
    def from_db_row(
        cls,
        main_row: tuple,
        data_row: Optional[tuple] = None,
    ) -> 'SpanRecord':
        """
        从数据库行重建 SpanRecord
        
        Args:
            main_row: spans 主表行
                (id, trace_id, span_id, parent_span_id, operation_name,
                 service_name, start_time, end_time, status, error_message, created_at)
            data_row: span_data 表行（可选）
                (span_id, inputs, outputs, metadata)
                
        Returns:
            SpanRecord: 重建的记录
        """
        # 解析主表数据（跳过 id 和 created_at）
        (_, trace_id, span_id, parent_span_id, operation_name,
         service_name, start_time, end_time, status_str, error_message, _) = main_row
        
        # 解析数据表
        inputs = None
        outputs = None
        metadata = None
        if data_row is not None:
            _, inputs_json, outputs_json, metadata_json = data_row
            inputs = cls._deserialize_json(inputs_json)
            outputs = cls._deserialize_json(outputs_json)
            metadata = cls._deserialize_json(metadata_json)
        
        return cls(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            operation_name=operation_name,
            service_name=service_name,
            start_time=start_time,
            end_time=end_time,
            status=TraceStatus(status_str),
            inputs=inputs,
            outputs=outputs,
            error_message=error_message,
            metadata=metadata,
        )

    @staticmethod
    def _deserialize_json(json_str: Optional[str]) -> Optional[Dict[str, Any]]:
        """安全地反序列化 JSON 数据"""
        if json_str is None:
            return None
        try:
            return json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            return None

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典（用于 EventBus 事件数据）
        """
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "operation_name": self.operation_name,
            "service_name": self.service_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "status": self.status.value,
            "duration_ms": self.duration_ms(),
            "error_message": self.error_message,
            "metadata": self.metadata,
        }

    def __repr__(self) -> str:
        duration = self.duration_ms()
        duration_str = f"{duration:.1f}ms" if duration is not None else "running"
        return (
            f"SpanRecord("
            f"op={self.operation_name}, "
            f"status={self.status.value}, "
            f"duration={duration_str})"
        )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "TraceStatus",
    "SpanType",
    "SpanRecord",
]
