# Measure Module - Declarative Metrics Extraction via .MEASURE
"""
声明式指标提取模块

基于 ngspice 原生 .MEASURE 语句实现指标提取，替代旧的拓扑识别+静态映射方案。

包含：
- measure_result.py: .MEASURE 结果数据类
- measure_parser.py: .MEASURE 结果解析器（支持多种 ngspice 输出格式）
- measure_injector.py: .MEASURE 语句注入器（包含语法验证，不自动修正）

设计说明：
- LLM 负责生成 .MEASURE 语句
- 系统负责验证语法、注入语句到网表、解析结果
- 语法错误直接返回给用户修改，不自动修正
- 结果存储在 SimulationResult.measurements 字段

ngspice .MEASURE 语法注意事项：
- 引用其他测量结果时使用 par('expr')，如 WHEN VDB(out)=par('gain_db-3')
- 不要使用引号直接包裹表达式，如 VDB(out)='gain_db-3' 是错误的
- 幂运算使用 pwr(base, exp) 而不是 ^
- PARAM 表达式需要用引号包裹，如 PARAM='f_3db*pwr(10,gain_db/20)'
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
    MeasureValidationError,
    measure_injector,
)

__all__ = [
    "MeasureResult",
    "MeasureStatus",
    "MeasureParser",
    "measure_parser",
    "MeasureInjector",
    "MeasureValidationError",
    "measure_injector",
]
