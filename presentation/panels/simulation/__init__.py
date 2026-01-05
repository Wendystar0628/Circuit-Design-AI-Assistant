# Simulation Panel Package
"""
仿真面板包

包含仿真结果展示相关的 UI 组件：
- SimulationViewModel: 仿真面板 ViewModel
- MetricCard: 指标卡片组件
- MetricsPanel: 指标显示面板
- ChartViewer: 图表查看器
- SimulationTab: 仿真结果标签页
"""

from presentation.panels.simulation.simulation_view_model import (
    SimulationViewModel,
    SimulationStatus,
    DisplayMetric,
    TuningParameter,
)

__all__ = [
    "SimulationViewModel",
    "SimulationStatus",
    "DisplayMetric",
    "TuningParameter",
]
