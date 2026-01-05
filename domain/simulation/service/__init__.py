# Simulation Service Module
"""
仿真服务层模块

职责：
- 提供仿真配置管理服务
- 提供快速调参服务（可选）

设计原则：
- 服务层负责业务逻辑编排
- 数据类仅定义结构，服务层处理读写、校验、持久化
"""

from domain.simulation.service.simulation_config_service import (
    SimulationConfigService,
    ValidationResult,
    ValidationError,
    simulation_config_service,
)

__all__ = [
    "SimulationConfigService",
    "ValidationResult",
    "ValidationError",
    "simulation_config_service",
]
