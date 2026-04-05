# Simulation Service Module
"""
仿真服务层模块

职责：
- 提供参数提取服务
- 提供快速调参服务

设计原则：
- 服务层负责业务逻辑编排
- 数据类仅定义结构，服务层处理读写、校验、持久化

旧的 UI 驱动仿真设置、图表选择、参数配置服务已被移除，
当前仅保留仍服务于网表权威架构的能力。
"""

from domain.simulation.service.parameter_extractor import (
    ParameterExtractor,
    ParameterType,
    TunableParameter,
    ParameterExtractionResult,
    parameter_extractor,
)

from domain.simulation.service.tuning_service import (
    TuningService,
    TuningApplyResult,
    tuning_service,
)

__all__ = [
    # 参数提取服务
    "ParameterExtractor",
    "ParameterType",
    "TunableParameter",
    "ParameterExtractionResult",
    "parameter_extractor",
    # 快速调参服务
    "TuningService",
    "TuningApplyResult",
    "tuning_service",
]
