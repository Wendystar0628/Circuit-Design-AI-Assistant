# Iteration History Service - Read-Only View from SqliteSaver
"""
迭代历史视图服务 - 从 SqliteSaver 查询 GraphState 历史

设计理念：
- 迭代历史是 GraphState 历史版本的视图投影
- 不独立存储，避免双写一致性问题
- 只读服务，不写入任何数据
- 每次查询实时从 SqliteSaver 获取，保证数据一致性

职责：
- 从 SqliteSaver 查询 GraphState 历史
- 提供迭代历史视图
- 支持迭代详情查询

被调用方：
- 迭代历史面板 UI
- analysis_node（用于判断停滞）

注意：
- 依赖 LangGraph 的 SqliteSaver/Checkpointer
- 完整实现在阶段七（LangGraph 集成后）

使用示例：
    from domain.services import iteration_history_service
    from domain.services.iteration_history_service import IterationRecord
    
    # 获取迭代历史
    history = iteration_history_service.get_iteration_history(
        checkpointer=checkpointer,
        thread_id="session_123"
    )
    
    # 获取最新迭代
    latest = iteration_history_service.get_latest_iteration(
        checkpointer=checkpointer,
        thread_id="session_123"
    )
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class IterationRecord:
    """
    迭代记录数据结构
    
    从 GraphState 检查点中提取的迭代信息
    """
    checkpoint_id: str
    """检查点 ID"""
    
    iteration_count: int
    """迭代次数"""
    
    metrics: Dict[str, Any] = field(default_factory=dict)
    """仿真指标摘要（从 last_metrics 提取）"""
    
    goals_summary: Dict[str, Any] = field(default_factory=dict)
    """设计目标摘要"""
    
    timestamp: str = ""
    """创建时间"""
    
    node_name: str = ""
    """当时执行的节点名称"""
    
    work_mode: str = "workflow"
    """工作模式"""
    
    is_completed: bool = False
    """是否完成"""
    
    termination_reason: str = ""
    """终止原因（如有）"""
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "checkpoint_id": self.checkpoint_id,
            "iteration_count": self.iteration_count,
            "metrics": self.metrics,
            "goals_summary": self.goals_summary,
            "timestamp": self.timestamp,
            "node_name": self.node_name,
            "work_mode": self.work_mode,
            "is_completed": self.is_completed,
            "termination_reason": self.termination_reason,
        }
    
    @classmethod
    def from_checkpoint(
        cls,
        checkpoint_id: str,
        state: Dict[str, Any],
        timestamp: str = ""
    ) -> "IterationRecord":
        """
        从检查点状态创建迭代记录
        
        Args:
            checkpoint_id: 检查点 ID
            state: GraphState 字典
            timestamp: 时间戳
            
        Returns:
            IterationRecord: 迭代记录
        """
        return cls(
            checkpoint_id=checkpoint_id,
            iteration_count=state.get("iteration_count", 0),
            metrics=state.get("last_metrics", {}),
            goals_summary=state.get("design_goals_summary", {}),
            timestamp=timestamp,
            node_name=state.get("current_node", ""),
            work_mode=state.get("work_mode", "workflow"),
            is_completed=state.get("is_completed", False),
            termination_reason=state.get("termination_reason", ""),
        )


def get_iteration_history(
    checkpointer: Any,
    thread_id: str,
    *,
    limit: int = 50
) -> List[IterationRecord]:
    """
    获取迭代历史列表
    
    从 SqliteSaver 查询检查点列表，提取迭代信息
    
    Args:
        checkpointer: LangGraph Checkpointer 实例
        thread_id: 线程/会话 ID
        limit: 返回数量限制
        
    Returns:
        List[IterationRecord]: 迭代记录列表，按时间倒序
        
    注意：
        完整实现在阶段七（LangGraph 集成后）
    """
    if checkpointer is None:
        return []
    
    records = []
    
    try:
        # 调用 checkpointer.list() 获取检查点列表
        # LangGraph 的 list() 方法返回检查点元组列表
        config = {"configurable": {"thread_id": thread_id}}
        
        # 尝试获取检查点列表
        checkpoints = list(checkpointer.list(config, limit=limit))
        
        for checkpoint_tuple in checkpoints:
            # checkpoint_tuple 结构: (config, checkpoint, metadata, ...)
            # 具体结构取决于 LangGraph 版本
            checkpoint_id = _extract_checkpoint_id(checkpoint_tuple)
            state = _extract_state(checkpoint_tuple)
            timestamp = _extract_timestamp(checkpoint_tuple)
            
            if state:
                record = IterationRecord.from_checkpoint(
                    checkpoint_id=checkpoint_id,
                    state=state,
                    timestamp=timestamp
                )
                records.append(record)
    
    except Exception:
        # Checkpointer 未初始化或查询失败
        pass
    
    return records


def get_iteration_detail(
    checkpointer: Any,
    thread_id: str,
    checkpoint_id: str
) -> Optional[IterationRecord]:
    """
    获取单次迭代详情
    
    Args:
        checkpointer: LangGraph Checkpointer 实例
        thread_id: 线程/会话 ID
        checkpoint_id: 检查点 ID
        
    Returns:
        Optional[IterationRecord]: 迭代记录，不存在时返回 None
    """
    if checkpointer is None:
        return None
    
    try:
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id
            }
        }
        
        # 获取特定检查点
        checkpoint_tuple = checkpointer.get_tuple(config)
        
        if checkpoint_tuple:
            state = _extract_state(checkpoint_tuple)
            timestamp = _extract_timestamp(checkpoint_tuple)
            
            if state:
                return IterationRecord.from_checkpoint(
                    checkpoint_id=checkpoint_id,
                    state=state,
                    timestamp=timestamp
                )
    
    except Exception:
        pass
    
    return None


def get_latest_iteration(
    checkpointer: Any,
    thread_id: str
) -> Optional[IterationRecord]:
    """
    获取最新迭代
    
    Args:
        checkpointer: LangGraph Checkpointer 实例
        thread_id: 线程/会话 ID
        
    Returns:
        Optional[IterationRecord]: 最新迭代记录，无记录时返回 None
    """
    history = get_iteration_history(checkpointer, thread_id, limit=1)
    return history[0] if history else None


def get_iteration_count(
    checkpointer: Any,
    thread_id: str
) -> int:
    """
    获取迭代总数
    
    Args:
        checkpointer: LangGraph Checkpointer 实例
        thread_id: 线程/会话 ID
        
    Returns:
        int: 迭代总数
    """
    latest = get_latest_iteration(checkpointer, thread_id)
    return latest.iteration_count if latest else 0


def get_metrics_trend(
    checkpointer: Any,
    thread_id: str,
    metric_key: str,
    *,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    获取指标趋势数据（用于图表显示）
    
    Args:
        checkpointer: LangGraph Checkpointer 实例
        thread_id: 线程/会话 ID
        metric_key: 指标键名
        limit: 数据点数量限制
        
    Returns:
        List[Dict]: 趋势数据列表
        
    示例输出：
        [
            {"iteration": 1, "value": "15dB", "timestamp": "..."},
            {"iteration": 2, "value": "18dB", "timestamp": "..."},
        ]
    """
    history = get_iteration_history(checkpointer, thread_id, limit=limit)
    
    trend = []
    for record in reversed(history):  # 按时间正序
        value = record.metrics.get(metric_key)
        if value is not None:
            trend.append({
                "iteration": record.iteration_count,
                "value": value,
                "timestamp": record.timestamp,
            })
    
    return trend


def check_stagnation(
    checkpointer: Any,
    thread_id: str,
    metric_key: str,
    *,
    window_size: int = 3,
    threshold: float = 0.01
) -> bool:
    """
    检查优化是否停滞
    
    通过比较最近几次迭代的指标变化判断是否停滞
    
    Args:
        checkpointer: LangGraph Checkpointer 实例
        thread_id: 线程/会话 ID
        metric_key: 用于判断的指标键名
        window_size: 比较窗口大小
        threshold: 变化阈值（相对变化率）
        
    Returns:
        bool: 是否停滞
    """
    trend = get_metrics_trend(
        checkpointer, thread_id, metric_key, limit=window_size + 1
    )
    
    if len(trend) < window_size:
        return False  # 数据不足，不判定为停滞
    
    # 提取数值（尝试解析）
    values = []
    for point in trend[-window_size:]:
        try:
            # 尝试提取数值部分
            value_str = str(point["value"])
            # 移除单位
            numeric_str = "".join(c for c in value_str if c.isdigit() or c in ".-")
            if numeric_str:
                values.append(float(numeric_str))
        except (ValueError, TypeError):
            pass
    
    if len(values) < window_size:
        return False  # 无法解析数值
    
    # 计算变化率
    max_val = max(values)
    min_val = min(values)
    
    if max_val == 0:
        return True  # 全为零，视为停滞
    
    change_rate = (max_val - min_val) / abs(max_val)
    
    return change_rate < threshold


# ============================================================
# 内部辅助函数
# ============================================================

def _extract_checkpoint_id(checkpoint_tuple: Any) -> str:
    """从检查点元组提取 ID"""
    try:
        # LangGraph CheckpointTuple 结构
        if hasattr(checkpoint_tuple, "config"):
            config = checkpoint_tuple.config
            if isinstance(config, dict):
                return config.get("configurable", {}).get("checkpoint_id", "")
        # 元组形式
        if isinstance(checkpoint_tuple, tuple) and len(checkpoint_tuple) > 0:
            config = checkpoint_tuple[0]
            if isinstance(config, dict):
                return config.get("configurable", {}).get("checkpoint_id", "")
    except Exception:
        pass
    return ""


def _extract_state(checkpoint_tuple: Any) -> Dict[str, Any]:
    """从检查点元组提取状态"""
    try:
        # LangGraph CheckpointTuple 结构
        if hasattr(checkpoint_tuple, "checkpoint"):
            checkpoint = checkpoint_tuple.checkpoint
            if isinstance(checkpoint, dict):
                return checkpoint.get("channel_values", {})
        # 元组形式
        if isinstance(checkpoint_tuple, tuple) and len(checkpoint_tuple) > 1:
            checkpoint = checkpoint_tuple[1]
            if isinstance(checkpoint, dict):
                return checkpoint.get("channel_values", {})
    except Exception:
        pass
    return {}


def _extract_timestamp(checkpoint_tuple: Any) -> str:
    """从检查点元组提取时间戳"""
    try:
        # LangGraph CheckpointTuple 结构
        if hasattr(checkpoint_tuple, "metadata"):
            metadata = checkpoint_tuple.metadata
            if isinstance(metadata, dict):
                return metadata.get("created_at", "")
        # 元组形式
        if isinstance(checkpoint_tuple, tuple) and len(checkpoint_tuple) > 2:
            metadata = checkpoint_tuple[2]
            if isinstance(metadata, dict):
                return metadata.get("created_at", "")
    except Exception:
        pass
    return ""


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "IterationRecord",
    "get_iteration_history",
    "get_iteration_detail",
    "get_latest_iteration",
    "get_iteration_count",
    "get_metrics_trend",
    "check_stagnation",
]
