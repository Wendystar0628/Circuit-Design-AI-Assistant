# Simulation Config Dialog Package
"""
仿真配置对话框模块

包含：
- SimulationConfigViewModel - 配置编辑 ViewModel
- SimulationConfigDialog - 配置对话框主类
- 各分析类型配置标签页（阶段7.3-7.7）
"""

from presentation.dialogs.simulation_config.simulation_config_view_model import (
    SimulationConfigViewModel,
)
from presentation.dialogs.simulation_config.simulation_config_dialog import (
    SimulationConfigDialog,
)

__all__ = [
    "SimulationConfigViewModel",
    "SimulationConfigDialog",
]
