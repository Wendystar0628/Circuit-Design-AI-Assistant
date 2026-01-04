# SimulationResult - Standardized Simulation Result Data Class
"""
仿真结果数据类

职责：
- 定义标准化的仿真结果数据结构
- 提供仿真数据的序列化和反序列化
- 支持仿真结果的查询和验证

设计原则：
- 使用 dataclass 确保类型安全
- 提供 numpy 数组的序列化支持
- 支持数据新鲜度验证（用于缓存）
- 与 SimulationError 数据类集成

使用示例：
    # 创建仿真结果
    result = SimulationResult(
        executor="spice",
        file_path="amplifier.cir",
        analysis_type="ac",
        success=True,
        data=SimulationData(
            frequency=np.array([1e3, 1e4, 1e5]),
            signals={"V(out)": np.array([0.1, 1.0, 10.0])}
        ),
        metrics={"gain": "20dB", "bandwidth": "10MHz"},
        timestamp=datetime.now().isoformat(),
        duration_seconds=2.5,
        version=1
    )
    
    # 序列化
    data_dict = result.to_dict()
    
    # 反序列化
    loaded_result = SimulationResult.from_dict(data_dict)
    
    # 查询信号
    output_signal = result.get_signal("V(out)")
    
    # 检查新鲜度
    if result.is_fresh(max_age_seconds=300):
        # 使用缓存的结果
        pass
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import numpy as np


# ============================================================
# SimulationData - 仿真数据容器
# ============================================================

@dataclass
class SimulationData:
    """
    仿真数据容器
    
    Attributes:
        frequency: AC 分析频率点（Hz）
        time: 瞬态分析时间点（秒）
        signals: 信号数据字典，键为信号名称，值为 numpy 数组
    """
    
    frequency: Optional[np.ndarray] = None
    """AC 分析频率点（Hz）"""
    
    time: Optional[np.ndarray] = None
    """瞬态分析时间点（秒）"""
    
    signals: Dict[str, np.ndarray] = field(default_factory=dict)
    """信号数据字典，键为信号名称（如 "V(out)"），值为 numpy 数组"""
    
    # ============================================================
    # 序列化方法
    # ============================================================
    
    def to_dict(self) -> Dict[str, Any]:
        """
        序列化为字典
        
        Returns:
            Dict: 序列化后的字典
        """
        return {
            "frequency": self.frequency.tolist() if self.frequency is not None else None,
            "time": self.time.tolist() if self.time is not None else None,
            "signals": {
                name: data.tolist() if isinstance(data, np.ndarray) else data
                for name, data in self.signals.items()
            },
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimulationData":
        """
        从字典反序列化
        
        Args:
            data: 序列化的字典
            
        Returns:
            SimulationData: 反序列化后的对象
        """
        return cls(
            frequency=np.array(data["frequency"]) if data.get("frequency") is not None else None,
            time=np.array(data["time"]) if data.get("time") is not None else None,
            signals={
                name: np.array(signal_data) if isinstance(signal_data, list) else signal_data
                for name, signal_data in data.get("signals", {}).items()
            },
        )
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def get_signal(self, name: str) -> Optional[np.ndarray]:
        """
        获取指定信号数据
        
        Args:
            name: 信号名称（如 "V(out)"）
            
        Returns:
            Optional[np.ndarray]: 信号数据，若不存在则返回 None
        """
        return self.signals.get(name)
    
    def has_signal(self, name: str) -> bool:
        """
        检查是否包含指定信号
        
        Args:
            name: 信号名称
            
        Returns:
            bool: 是否包含该信号
        """
        return name in self.signals
    
    def get_signal_names(self) -> list[str]:
        """
        获取所有信号名称列表
        
        Returns:
            list[str]: 信号名称列表
        """
        return list(self.signals.keys())


# ============================================================
# SimulationResult - 标准化仿真结果
# ============================================================

@dataclass
class SimulationResult:
    """
    标准化仿真结果
    
    Attributes:
        executor: 执行器名称（如 "spice", "python"）
        file_path: 仿真文件路径
        analysis_type: 分析类型（如 "ac", "dc", "tran", "noise"）
        success: 是否成功
        data: 仿真数据（成功时有值）
        metrics: 性能指标字典（可选）
        error: 错误信息（失败时有值）
        raw_output: 原始输出（调试用）
        timestamp: ISO 格式时间戳
        duration_seconds: 执行耗时（秒）
        version: 版本号，每次仿真递增
    """
    
    executor: str
    """执行器名称（如 "spice", "python"）"""
    
    file_path: str
    """仿真文件路径"""
    
    analysis_type: str
    """分析类型（如 "ac", "dc", "tran", "noise"）"""
    
    success: bool
    """是否成功"""
    
    data: Optional[SimulationData] = None
    """仿真数据（成功时有值）"""
    
    metrics: Optional[Dict[str, Any]] = None
    """性能指标字典（可选）"""
    
    error: Optional[Any] = None
    """错误信息（失败时有值，类型为 SimulationError）"""
    
    raw_output: Optional[str] = None
    """原始输出（调试用）"""
    
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    """ISO 格式时间戳（如 2024-12-20T14:30:22.123456）"""
    
    duration_seconds: float = 0.0
    """执行耗时（秒）"""
    
    version: int = 1
    """版本号，每次仿真递增，用于验证数据新鲜度"""
    
    # ============================================================
    # 序列化方法
    # ============================================================
    
    def to_dict(self) -> Dict[str, Any]:
        """
        序列化为字典
        
        Returns:
            Dict: 序列化后的字典
        """
        return {
            "executor": self.executor,
            "file_path": self.file_path,
            "analysis_type": self.analysis_type,
            "success": self.success,
            "data": self.data.to_dict() if self.data is not None else None,
            "metrics": self.metrics,
            "error": self.error.to_dict() if self.error is not None and hasattr(self.error, "to_dict") else str(self.error) if self.error is not None else None,
            "raw_output": self.raw_output,
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
            "version": self.version,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimulationResult":
        """
        从字典反序列化
        
        Args:
            data: 序列化的字典
            
        Returns:
            SimulationResult: 反序列化后的对象
        """
        # 反序列化仿真数据
        sim_data = None
        if data.get("data") is not None:
            sim_data = SimulationData.from_dict(data["data"])
        
        # 反序列化错误信息（暂时作为字符串处理，后续集成 SimulationError 时更新）
        error = data.get("error")
        
        return cls(
            executor=data["executor"],
            file_path=data["file_path"],
            analysis_type=data["analysis_type"],
            success=data["success"],
            data=sim_data,
            metrics=data.get("metrics"),
            error=error,
            raw_output=data.get("raw_output"),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            duration_seconds=data.get("duration_seconds", 0.0),
            version=data.get("version", 1),
        )
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def is_successful(self) -> bool:
        """
        判断是否成功
        
        Returns:
            bool: 是否成功
        """
        return self.success
    
    def get_signal(self, name: str) -> Optional[np.ndarray]:
        """
        获取指定信号数据
        
        Args:
            name: 信号名称（如 "V(out)"）
            
        Returns:
            Optional[np.ndarray]: 信号数据，若不存在或仿真失败则返回 None
        """
        if not self.success or self.data is None:
            return None
        return self.data.get_signal(name)
    
    def is_fresh(self, max_age_seconds: float) -> bool:
        """
        检查数据是否在指定时间内（用于缓存验证）
        
        Args:
            max_age_seconds: 最大年龄（秒）
            
        Returns:
            bool: 是否新鲜
        """
        try:
            result_time = datetime.fromisoformat(self.timestamp)
            age = datetime.now() - result_time
            return age <= timedelta(seconds=max_age_seconds)
        except (ValueError, TypeError):
            # 时间戳解析失败，认为数据过期
            return False
    
    def get_age_seconds(self) -> float:
        """
        获取数据年龄（秒）
        
        Returns:
            float: 数据年龄（秒），解析失败返回 -1
        """
        try:
            result_time = datetime.fromisoformat(self.timestamp)
            age = datetime.now() - result_time
            return age.total_seconds()
        except (ValueError, TypeError):
            return -1.0
    
    def has_metrics(self) -> bool:
        """
        检查是否包含性能指标
        
        Returns:
            bool: 是否包含性能指标
        """
        return self.metrics is not None and len(self.metrics) > 0
    
    def get_metric(self, name: str, default: Any = None) -> Any:
        """
        获取指定性能指标
        
        Args:
            name: 指标名称
            default: 默认值
            
        Returns:
            Any: 指标值，若不存在则返回默认值
        """
        if self.metrics is None:
            return default
        return self.metrics.get(name, default)
    
    def get_summary(self) -> str:
        """
        获取结果摘要（用于日志和调试）
        
        Returns:
            str: 结果摘要
        """
        status = "成功" if self.success else "失败"
        return (
            f"SimulationResult(executor={self.executor}, "
            f"file={self.file_path}, "
            f"type={self.analysis_type}, "
            f"status={status}, "
            f"duration={self.duration_seconds:.2f}s, "
            f"version={self.version})"
        )


# ============================================================
# 工厂方法
# ============================================================

def create_success_result(
    executor: str,
    file_path: str,
    analysis_type: str,
    data: SimulationData,
    metrics: Optional[Dict[str, Any]] = None,
    raw_output: Optional[str] = None,
    duration_seconds: float = 0.0,
    version: int = 1
) -> SimulationResult:
    """
    创建成功的仿真结果
    
    Args:
        executor: 执行器名称
        file_path: 仿真文件路径
        analysis_type: 分析类型
        data: 仿真数据
        metrics: 性能指标（可选）
        raw_output: 原始输出（可选）
        duration_seconds: 执行耗时
        version: 版本号
        
    Returns:
        SimulationResult: 成功的仿真结果
    """
    return SimulationResult(
        executor=executor,
        file_path=file_path,
        analysis_type=analysis_type,
        success=True,
        data=data,
        metrics=metrics,
        error=None,
        raw_output=raw_output,
        timestamp=datetime.now().isoformat(),
        duration_seconds=duration_seconds,
        version=version,
    )


def create_error_result(
    executor: str,
    file_path: str,
    analysis_type: str,
    error: Any,
    raw_output: Optional[str] = None,
    duration_seconds: float = 0.0,
    version: int = 1
) -> SimulationResult:
    """
    创建失败的仿真结果
    
    Args:
        executor: 执行器名称
        file_path: 仿真文件路径
        analysis_type: 分析类型
        error: 错误信息（SimulationError 或字符串）
        raw_output: 原始输出（可选）
        duration_seconds: 执行耗时
        version: 版本号
        
    Returns:
        SimulationResult: 失败的仿真结果
    """
    return SimulationResult(
        executor=executor,
        file_path=file_path,
        analysis_type=analysis_type,
        success=False,
        data=None,
        metrics=None,
        error=error,
        raw_output=raw_output,
        timestamp=datetime.now().isoformat(),
        duration_seconds=duration_seconds,
        version=version,
    )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SimulationData",
    "SimulationResult",
    "create_success_result",
    "create_error_result",
]
