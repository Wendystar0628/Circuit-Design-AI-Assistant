# Measure Module - Declarative Metrics Extraction via .MEASURE
"""
声明式指标提取模块

基于 ngspice 原生 .MEASURE 语句实现指标提取，替代旧的拓扑识别+静态映射方案。

包含：
- measure_result.py: .MEASURE 结果数据类
- measure_parser.py: .MEASURE 结果解析器
- measure_injector.py: .MEASURE 语句注入器

设计说明：
- LLM 负责生成 .MEASURE 语句
- 系统负责注入语句到网表和解析结果
- 结果存储在 SimulationResult.measurements 字段
"""

from domain.simulation.measure.measure_result import (
    MeasureResult,
    MeasureStatus,
)
from domain.simulation.measure.measure_parser import (
    MeasureParser,
    measure_parser,
)
from domain.simulation.measure.measure_injector import (
    MeasureInjector,
    measure_injector,
)

__all__ = [
    "MeasureResult",
    "MeasureStatus",
    "MeasureParser",
    "measure_parser",
    "MeasureInjector",
    "measure_injector",
]
