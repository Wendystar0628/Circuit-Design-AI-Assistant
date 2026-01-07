# Analysis Module - Advanced Simulation Analysis
"""
高级仿真分析模块

包含：
- pvt_analysis.py: PVT 角点仿真
- monte_carlo_analysis.py: 蒙特卡洛分析
- parametric_sweep.py: 参数扫描分析
- worst_case_analysis.py: 最坏情况分析
- sensitivity_analysis.py: 敏感度分析
- post_processor.py: 仿真数据后处理

设计说明：
- 所有分析模块作为工具类按需实例化
- 通过 SimulationService 或 tool_executor 调用
- 结果通过事件系统发布进度
"""

from domain.simulation.analysis.pvt_analysis import (
    PVTAnalyzer,
    PVTCorner,
    PVTCornerResult,
    PVTAnalysisResult,
    ProcessCorner,
)
from domain.simulation.analysis.monte_carlo_analysis import (
    MonteCarloAnalyzer,
    ParameterVariation,
    DistributionType,
    MonteCarloRunResult,
    MonteCarloAnalysisResult,
    MonteCarloStatistics,
)
from domain.simulation.analysis.parametric_sweep import (
    ParametricSweepAnalyzer,
    SweepParameter,
    SweepType,
    NestedSweepConfig,
    SweepPointResult,
    SweepAnalysisResult,
)
from domain.simulation.analysis.worst_case_analysis import (
    WorstCaseAnalyzer,
    WorstCaseMethod,
    ToleranceSpec,
    ParameterSensitivity,
    WorstCaseResult,
)
from domain.simulation.analysis.sensitivity_analysis import (
    SensitivityAnalyzer,
    SensitivityParam,
    ParamSensitivityData,
    TornadoChartData,
    OptimizationSuggestion,
    SensitivityAnalysisResult,
)
from domain.simulation.analysis.post_processor import (
    PostProcessor,
    PoleZeroResult,
    GroupDelayResult,
    PhaseMarginResult,
)

__all__ = [
    # PVT 分析
    "PVTAnalyzer",
    "PVTCorner",
    "PVTCornerResult",
    "PVTAnalysisResult",
    "ProcessCorner",
    # 蒙特卡洛分析
    "MonteCarloAnalyzer",
    "ParameterVariation",
    "DistributionType",
    "MonteCarloRunResult",
    "MonteCarloAnalysisResult",
    "MonteCarloStatistics",
    # 参数扫描分析
    "ParametricSweepAnalyzer",
    "SweepParameter",
    "SweepType",
    "NestedSweepConfig",
    "SweepPointResult",
    "SweepAnalysisResult",
    # 最坏情况分析
    "WorstCaseAnalyzer",
    "WorstCaseMethod",
    "ToleranceSpec",
    "ParameterSensitivity",
    "WorstCaseResult",
    # 敏感度分析
    "SensitivityAnalyzer",
    "SensitivityParam",
    "ParamSensitivityData",
    "TornadoChartData",
    "OptimizationSuggestion",
    "SensitivityAnalysisResult",
    # 后处理
    "PostProcessor",
    "PoleZeroResult",
    "GroupDelayResult",
    "PhaseMarginResult",
]
