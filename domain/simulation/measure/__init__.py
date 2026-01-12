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

ngspice 共享库模式下的 .MEASURE 语法限制：
- 不能引用其他 .MEASURE 的结果（如 WHEN VDB(out)=gain_max-3 会失败）
- 不能使用 par() 函数
- 不能使用 .PARAM 定义的参数
- 只能使用固定数值（如 WHEN VDB(out)=-3）
- 幂运算使用 pwr(base, exp) 而不是 ^
- PARAM 表达式需要用引号包裹，如 PARAM='f_3db*pwr(10,gain_db/20)'

解决方案：
- 使用固定阈值代替动态引用
- 复杂的指标计算在仿真后通过后处理实现
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
