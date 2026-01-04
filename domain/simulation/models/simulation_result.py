# Simulation Result - Simulation Result Data Classes
"""
仿真结果数据类

职责：
- 定义仿真结果的数据结构
- 支持序列化/反序列化
- 提供结果状态判断方法
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class SimulationStatus(Enum):
    """仿真状态枚举"""
    
    PENDING = "pending"
    """等待执行"""
    
    RUNNING = "running"
    """执行中"""
    
    COMPLETED = "completed"
    """执行完成"""
    
    FAILED = "failed"
    """执行失败"""
    
    TIMEOUT = "timeout"
    """执行超时"""
    
    CANCELLED = "cancelled"
    """已取消"""


@dataclass
class SimulationResult:
    """
    仿真结果
    
    Attributes:
        id: 结果唯一标识
        circuit_file: 电路文件路径
        analysis_type: 分析类型
        status: 仿真状态
        timestamp: 执行时间戳
        data: 仿真数据（波形数据等）
        metrics: 提取的性能指标
        error: 错误信息（失败时）
        duration: 执行耗时 (秒)
        config: 使用的仿真配置
    """
    
    id: str = ""
    """结果唯一标识"""
    
    circuit_file: str = ""
    """电路文件路径"""
    
    analysis_type: str = ""
    """分析类型"""
    
    status: SimulationStatus = SimulationStatus.PENDING
    """仿真状态"""
    
    timestamp: str = ""
    """执行时间戳 (ISO 格式)"""
    
    data: Dict[str, List[float]] = field(default_factory=dict)
    """
    仿真数据，格式：
    {
        "frequency": [1, 10, 100, ...],
        "gain": [0.1, 0.5, 1.0, ...],
        "phase": [-10, -45, -90, ...]
    }
    """
    
    metrics: Dict[str, Any] = field(default_factory=dict)
    """
    提取的性能指标，格式：
    {
        "gain_db": 20.5,
        "bandwidth_hz": 10000000,
        "phase_margin_deg": 60.2
    }
    """
    
    error: Optional[str] = None
    """错误信息（失败时）"""
    
    duration: float = 0.0
    """执行耗时 (秒)"""
    
    config: Dict[str, Any] = field(default_factory=dict)
    """使用的仿真配置"""
    
    # ============================================================
    # 状态判断方法
    # ============================================================
    
    @property
    def success(self) -> bool:
        """是否执行成功"""
        return self.status == SimulationStatus.COMPLETED
    
    @property
    def is_running(self) -> bool:
        """是否正在执行"""
        return self.status == SimulationStatus.RUNNING
    
    @property
    def has_data(self) -> bool:
        """是否有仿真数据"""
        return bool(self.data)
    
    # ============================================================
    # 序列化方法
    # ============================================================
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 JSON 序列化）"""
        return {
            "id": self.id,
            "circuit_file": self.circuit_file,
            "analysis_type": self.analysis_type,
            "status": self.status.value,
            "timestamp": self.timestamp,
            "data": self.data,
            "metrics": self.metrics,
            "error": self.error,
            "duration": self.duration,
            "config": self.config,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimulationResult":
        """从字典创建"""
        status_str = data.get("status", "pending")
        try:
            status = SimulationStatus(status_str)
        except ValueError:
            status = SimulationStatus.PENDING
        
        return cls(
            id=data.get("id", ""),
            circuit_file=data.get("circuit_file", ""),
            analysis_type=data.get("analysis_type", ""),
            status=status,
            timestamp=data.get("timestamp", ""),
            data=data.get("data", {}),
            metrics=data.get("metrics", {}),
            error=data.get("error"),
            duration=data.get("duration", 0.0),
            config=data.get("config", {}),
        )
    
    # ============================================================
    # 工厂方法
    # ============================================================
    
    @classmethod
    def create_pending(
        cls,
        result_id: str,
        circuit_file: str,
        analysis_type: str,
        config: Dict[str, Any]
    ) -> "SimulationResult":
        """创建待执行的结果对象"""
        return cls(
            id=result_id,
            circuit_file=circuit_file,
            analysis_type=analysis_type,
            status=SimulationStatus.PENDING,
            timestamp=datetime.now().isoformat(),
            config=config,
        )
    
    @classmethod
    def create_failed(
        cls,
        result_id: str,
        circuit_file: str,
        analysis_type: str,
        error: str,
        config: Dict[str, Any]
    ) -> "SimulationResult":
        """创建失败的结果对象"""
        return cls(
            id=result_id,
            circuit_file=circuit_file,
            analysis_type=analysis_type,
            status=SimulationStatus.FAILED,
            timestamp=datetime.now().isoformat(),
            error=error,
            config=config,
        )


@dataclass
class MetricsSummary:
    """
    指标摘要（用于 GraphState）
    
    轻量级结构，只包含关键指标和状态
    """
    
    status: str = "unknown"
    """状态：completed | failed | pending"""
    
    timestamp: str = ""
    """时间戳"""
    
    values: Dict[str, Any] = field(default_factory=dict)
    """指标值"""
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "status": self.status,
            "timestamp": self.timestamp,
        }
        result.update(self.values)
        return result
    
    @classmethod
    def from_simulation_result(cls, result: SimulationResult) -> "MetricsSummary":
        """从仿真结果创建摘要"""
        return cls(
            status=result.status.value,
            timestamp=result.timestamp,
            values=result.metrics.copy(),
        )


__all__ = [
    "SimulationStatus",
    "SimulationResult",
    "MetricsSummary",
]
