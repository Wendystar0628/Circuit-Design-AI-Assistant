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

__all__ = [
    "MetricCategory",
    "MetricResult",
    "create_metric_result",
    "create_error_metric",
    "AmplifierMetrics",
    "amplifier_metrics",
    "NoiseMetrics",
    "noise_metrics",
    "DistortionMetrics",
    "distortion_metrics",
]
