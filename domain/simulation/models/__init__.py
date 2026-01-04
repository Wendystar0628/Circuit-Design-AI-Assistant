# Simulation Models
"""
仿真模型定义

包含：
- analysis_types: 分析类型枚举
- simulation_config: 仿真配置数据类
- simulation_result: 仿真结果数据类
"""

from .analysis_types import (
    AnalysisType,
    ANALYSIS_DEFAULTS,
    get_analysis_defaults,
)
from .simulation_config import (
    SimulationConfig,
    PVTCorner,
    MonteCarloConfig,
    ParametricSweepConfig,
)
from .simulation_result import (
    SimulationStatus,
    SimulationResult,
    MetricsSummary,
)

__all__ = [
    # Analysis Types
    "AnalysisType",
    "ANALYSIS_DEFAULTS",
    "get_analysis_defaults",
    # Simulation Config
    "SimulationConfig",
    "PVTCorner",
    "MonteCarloConfig",
    "ParametricSweepConfig",
    # Simulation Result
    "SimulationStatus",
    "SimulationResult",
    "MetricsSummary",
]
