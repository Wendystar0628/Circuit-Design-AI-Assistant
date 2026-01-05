# Simulation Executor Module
"""
仿真执行器模块

职责：
- 定义仿真执行器抽象接口
- 管理执行器注册和调度
- 提供具体执行器实现

设计原则：
- 策略模式：不同仿真方式实现统一接口
- 开闭原则：新增执行器无需修改现有代码
- 单一职责：每个执行器专注于一种仿真方式

执行器列表：
- SpiceExecutor: SPICE 仿真执行器（使用 PySpice/NgSpiceShared）
- PythonExecutor: Python 脚本执行器（在独立子进程中执行）
"""

from domain.simulation.executor.simulation_executor import SimulationExecutor
from domain.simulation.executor.executor_registry import (
    ExecutorRegistry,
    executor_registry,
)
from domain.simulation.executor.spice_executor import SpiceExecutor
from domain.simulation.executor.python_executor import PythonExecutor
from domain.simulation.executor.circuit_analyzer import (
    CircuitAnalyzer,
    CircuitFileInfo,
    MainCircuitDetectionResult,
    ScanResult,
)

__all__ = [
    "SimulationExecutor",
    "ExecutorRegistry",
    "executor_registry",
    "SpiceExecutor",
    "PythonExecutor",
    "CircuitAnalyzer",
    "CircuitFileInfo",
    "MainCircuitDetectionResult",
    "ScanResult",
]
