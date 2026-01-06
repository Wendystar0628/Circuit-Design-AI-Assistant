# Simulation Panel Package
"""
仿真面板包

包含仿真结果展示相关的 UI 组件：
- SimulationViewModel: 仿真面板 ViewModel
- MetricCard: 指标卡片组件
- MetricsPanel: 指标显示面板
- ChartViewer: 图表查看器
- WaveformWidget: 交互式波形图表组件
- SimulationTab: 仿真结果标签页主类
"""

from presentation.panels.simulation.simulation_view_model import (
    SimulationViewModel,
    SimulationStatus,
    DisplayMetric,
    TuningParameter,
)
from presentation.panels.simulation.metric_card import MetricCard
from presentation.panels.simulation.metrics_panel import MetricsPanel
from presentation.panels.simulation.chart_viewer import ChartViewer, ZoomableImageLabel
from presentation.panels.simulation.waveform_widget import WaveformWidget, WaveformMeasurement
from presentation.panels.simulation.simulation_tab import (
    SimulationTab,
    MetricsSummaryPanel,
    ChartViewerPanel,
    StatusIndicator,
)

__all__ = [
    "SimulationViewModel",
    "SimulationStatus",
    "DisplayMetric",
    "TuningParameter",
    "MetricCard",
    "MetricsPanel",
    "ChartViewer",
    "ZoomableImageLabel",
    "WaveformWidget",
    "WaveformMeasurement",
    "SimulationTab",
    "MetricsSummaryPanel",
    "ChartViewerPanel",
    "StatusIndicator",
]
