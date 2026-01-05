# Metrics Module - Performance Metrics Extraction
"""
性能指标提取模块

职责：
- 从仿真结果中提取关键性能指标
- 提供标准化的指标结果数据结构
- 支持多种电路类型的指标提取

模块组成：
- metric_result.py: 指标结果数据类
- metrics_extractor.py: 指标提取门面类
- amplifier_metrics.py: 放大器指标提取
- noise_metrics.py: 噪声指标提取
- distortion_metrics.py: 失真指标提取
- power_metrics.py: 电源指标提取
- transient_metrics.py: 瞬态指标提取

使用示例：
    from domain.simulation.metrics import metrics_extractor
    
    # 根据拓扑自动提取指标
    metrics = metrics_extractor.extract_metrics(sim_data, topology="amplifier")
    
    # 提取所有可计算的指标
    all_metrics = metrics_extractor.extract_all_metrics(sim_data)
    
    # 按名称提取单个指标
    gain = metrics_extractor.get_metric_by_name(sim_data, "gain")
"""

from domain.simulation.metrics.metric_result import (
    MetricCategory,
    MetricResult,
    create_metric_result,
    create_error_metric,
)
from domain.simulation.metrics.amplifier_metrics import (
    AmplifierMetrics,
    amplifier_metrics,
)
from domain.simulation.metrics.noise_metrics import (
    NoiseMetrics,
    noise_metrics,
)
from domain.simulation.metrics.distortion_metrics import (
    DistortionMetrics,
    distortion_metrics,
)
from domain.simulation.metrics.power_metrics import (
    PowerMetrics,
    power_metrics,
)
from domain.simulation.metrics.transient_metrics import (
    TransientMetrics,
    transient_metrics,
)
from domain.simulation.metrics.metrics_extractor import (
    MetricsExtractor,
    metrics_extractor,
)

__all__ = [
    # 门面类（推荐使用）
    "MetricsExtractor",
    "metrics_extractor",
    # 数据类
    "MetricCategory",
    "MetricResult",
    "create_metric_result",
    "create_error_metric",
    # 子模块提取器
    "AmplifierMetrics",
    "amplifier_metrics",
    "NoiseMetrics",
    "noise_metrics",
    "DistortionMetrics",
    "distortion_metrics",
    "PowerMetrics",
    "power_metrics",
    "TransientMetrics",
    "transient_metrics",
]
