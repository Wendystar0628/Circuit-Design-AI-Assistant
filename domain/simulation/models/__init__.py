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

from circuit_design_ai.domain.simulation.models.simulation_result import (
    SimulationData,
    SimulationResult,
)

__all__ = [
    "SimulationData",
    "SimulationResult",
]
