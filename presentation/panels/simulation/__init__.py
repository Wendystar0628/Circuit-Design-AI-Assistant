# Simulation Panel Package
"""
仿真面板包

包含仿真结果展示相关的 UI 组件：
- SimulationViewModel: 仿真面板 ViewModel
- MetricCard: 指标卡片组件
- MetricsPanel: 指标显示面板
- ChartViewer: 图表查看器
- WaveformWidget: 交互式波形图表组件
- RawDataTable: 原始数据表格（虚拟滚动）
- OutputLogViewer: 仿真输出日志查看器
- TuningPanel: 快速调参面板
- SimulationTab: 仿真结果标签页主类
- PVTResultTab: PVT 角点分析结果标签页
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
from presentation.panels.simulation.raw_data_table import RawDataTable, RawDataTableModel
from presentation.panels.simulation.output_log_viewer import OutputLogViewer, LogHighlighter
from presentation.panels.simulation.tuning_panel import TuningPanel, ParameterSliderWidget
from presentation.panels.simulation.simulation_tab import (
    SimulationTab,
    MetricsSummaryPanel,
    ChartViewerPanel,
    StatusIndicator,
)
from presentation.panels.simulation.pvt_result_tab import (
    PVTResultTab,
    CornerSelectorBar,
    MetricsComparisonTable,
    CornerDetailPanel,
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
    "RawDataTable",
    "RawDataTableModel",
    "OutputLogViewer",
    "LogHighlighter",
    "TuningPanel",
    "ParameterSliderWidget",
    "SimulationTab",
    "MetricsSummaryPanel",
    "ChartViewerPanel",
    "StatusIndicator",
    "PVTResultTab",
    "CornerSelectorBar",
    "MetricsComparisonTable",
    "CornerDetailPanel",
]
