# Simulation Models Module
"""
仿真数据模型模块

职责：
- 定义标准化的仿真数据结构
- 提供类型安全的数据容器
- 支持序列化和反序列化

设计原则：
- 使用 dataclass 定义数据结构
- 提供完整的类型注解
- 支持 JSON 序列化
"""

from domain.simulation.models.simulation_config import (
    ACAnalysisConfig,
    ConvergenceConfig,
    DCAnalysisConfig,
    GlobalSimulationConfig,
    NoiseConfig,
    TransientConfig,
)
from domain.simulation.models.simulation_error import (
    ErrorSeverity,
    SimulationError,
    SimulationErrorType,
    create_convergence_error,
    create_model_missing_error,
    create_syntax_error,
    create_timeout_error,
)
from domain.simulation.models.simulation_result import (
    SimulationData,
    SimulationResult,
    create_error_result,
    create_success_result,
)
from domain.simulation.models.analysis_result import (
    # 基类
    AnalysisResultBase,
    # PVT 分析
    PVTCorner,
    PVTAnalysisResult,
    # 蒙特卡洛分析
    MetricStatistics,
    HistogramData,
    MonteCarloResult,
    # 参数扫描
    SweepParam,
    SweepResult,
    # 最坏情况分析
    CriticalParam,
    WorstCaseResult,
    # 敏感度分析
    ParamSensitivity,
    TornadoChartData,
    SensitivityResult,
    # FFT 后处理
    HarmonicData,
    SpectrumData,
    FFTResult,
    # 拓扑识别
    TopologyResult,
    # 收敛诊断
    SuggestedFix,
    ConvergenceDiagnosis,
)

__all__ = [
    # Simulation Result
    "SimulationData",
    "SimulationResult",
    "create_success_result",
    "create_error_result",
    # Simulation Error
    "SimulationError",
    "SimulationErrorType",
    "ErrorSeverity",
    "create_syntax_error",
    "create_model_missing_error",
    "create_convergence_error",
    "create_timeout_error",
    # Simulation Config
    "ACAnalysisConfig",
    "DCAnalysisConfig",
    "TransientConfig",
    "NoiseConfig",
    "ConvergenceConfig",
    "GlobalSimulationConfig",
    # Analysis Result - 基类
    "AnalysisResultBase",
    # Analysis Result - PVT 分析
    "PVTCorner",
    "PVTAnalysisResult",
    # Analysis Result - 蒙特卡洛分析
    "MetricStatistics",
    "HistogramData",
    "MonteCarloResult",
    # Analysis Result - 参数扫描
    "SweepParam",
    "SweepResult",
    # Analysis Result - 最坏情况分析
    "CriticalParam",
    "WorstCaseResult",
    # Analysis Result - 敏感度分析
    "ParamSensitivity",
    "TornadoChartData",
    "SensitivityResult",
    # Analysis Result - FFT 后处理
    "HarmonicData",
    "SpectrumData",
    "FFTResult",
    # Analysis Result - 拓扑识别
    "TopologyResult",
    # Analysis Result - 收敛诊断
    "SuggestedFix",
    "ConvergenceDiagnosis",
]
