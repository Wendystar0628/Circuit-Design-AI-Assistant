# Simulation Config - Simulation Configuration Data Classes
"""
仿真配置数据类

职责：
- 定义仿真执行所需的配置参数
- 支持各种分析类型的参数配置
- 提供配置验证和默认值
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .analysis_types import AnalysisType, get_analysis_defaults


@dataclass
class SimulationConfig:
    """
    仿真配置
    
    Attributes:
        analysis_type: 分析类型
        parameters: 分析参数（覆盖默认值）
        temperature: 仿真温度 (°C)
        include_files: 需要包含的子电路/模型文件
        options: SPICE 选项
        save_nodes: 需要保存的节点列表（空列表表示保存所有）
        timeout: 仿真超时时间 (秒)
    """
    
    analysis_type: AnalysisType = AnalysisType.AC
    """分析类型"""
    
    parameters: Dict[str, Any] = field(default_factory=dict)
    """分析参数（覆盖默认值）"""
    
    temperature: float = 27.0
    """仿真温度 (°C)"""
    
    include_files: List[str] = field(default_factory=list)
    """需要包含的子电路/模型文件路径"""
    
    options: Dict[str, Any] = field(default_factory=dict)
    """SPICE 选项（如 abstol, reltol 等）"""
    
    save_nodes: List[str] = field(default_factory=list)
    """需要保存的节点列表（空列表表示保存所有）"""
    
    timeout: float = 60.0
    """仿真超时时间 (秒)"""
    
    def get_merged_parameters(self) -> Dict[str, Any]:
        """获取合并后的参数（默认值 + 用户配置）"""
        defaults = get_analysis_defaults(self.analysis_type)
        defaults.update(self.parameters)
        return defaults
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "analysis_type": self.analysis_type.value,
            "parameters": self.parameters,
            "temperature": self.temperature,
            "include_files": self.include_files,
            "options": self.options,
            "save_nodes": self.save_nodes,
            "timeout": self.timeout,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimulationConfig":
        """从字典创建"""
        analysis_type_str = data.get("analysis_type", "ac")
        try:
            analysis_type = AnalysisType(analysis_type_str)
        except ValueError:
            analysis_type = AnalysisType.AC
        
        return cls(
            analysis_type=analysis_type,
            parameters=data.get("parameters", {}),
            temperature=data.get("temperature", 27.0),
            include_files=data.get("include_files", []),
            options=data.get("options", {}),
            save_nodes=data.get("save_nodes", []),
            timeout=data.get("timeout", 60.0),
        )


@dataclass
class PVTCorner:
    """
    PVT 角点配置
    
    Attributes:
        name: 角点名称（如 "tt", "ff", "ss"）
        process: 工艺角（如 "typical", "fast", "slow"）
        voltage: 电源电压 (V)
        temperature: 温度 (°C)
    """
    
    name: str
    process: str = "typical"
    voltage: float = 3.3
    temperature: float = 27.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "process": self.process,
            "voltage": self.voltage,
            "temperature": self.temperature,
        }


@dataclass
class MonteCarloConfig:
    """
    蒙特卡洛分析配置
    
    Attributes:
        iterations: 迭代次数
        seed: 随机种子（None 表示随机）
        vary_params: 需要变化的参数及其分布
    """
    
    iterations: int = 100
    seed: Optional[int] = None
    vary_params: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    """
    参数变化配置，格式：
    {
        "R1": {"distribution": "gaussian", "sigma": 0.05},
        "C1": {"distribution": "uniform", "tolerance": 0.1}
    }
    """
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "iterations": self.iterations,
            "seed": self.seed,
            "vary_params": self.vary_params,
        }


@dataclass
class ParametricSweepConfig:
    """
    参数扫描配置
    
    Attributes:
        parameter: 扫描参数名
        start: 起始值
        stop: 结束值
        step: 步长（与 points 二选一）
        points: 点数（与 step 二选一）
        scale: 扫描刻度（linear | log）
    """
    
    parameter: str = ""
    start: float = 0
    stop: float = 1
    step: Optional[float] = None
    points: Optional[int] = None
    scale: str = "linear"  # linear | log
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameter": self.parameter,
            "start": self.start,
            "stop": self.stop,
            "step": self.step,
            "points": self.points,
            "scale": self.scale,
        }


__all__ = [
    "SimulationConfig",
    "PVTCorner",
    "MonteCarloConfig",
    "ParametricSweepConfig",
]
