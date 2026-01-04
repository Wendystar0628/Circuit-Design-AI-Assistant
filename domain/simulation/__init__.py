# Simulation Domain
"""
仿真执行域

包含：
- models/: 仿真数据模型
  - analysis_types.py: 分析类型枚举
  - simulation_config.py: 仿真配置数据类
  - simulation_result.py: 仿真结果数据类
- executor/: 仿真执行器
  - spice_executor.py: SPICE 执行器（封装 PySpice）

后续扩展（阶段四后续）：
- metrics/: 指标提取模块组
- visualization/: 可视化模块
- schematic/: 电路图生成子域
"""

from .models import (
    # Analysis Types
    AnalysisType,
    ANALYSIS_DEFAULTS,
    get_analysis_defaults,
    # Simulation Config
    SimulationConfig,
    PVTCorner,
    MonteCarloConfig,
    ParametricSweepConfig,
    # Simulation Result
    SimulationStatus,
    SimulationResult,
    MetricsSummary,
)

from .executor import (
    SpiceExecutor,
    SpiceExecutorError,
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
    # Executor
    "SpiceExecutor",
    "SpiceExecutorError",
]
