# Simulation Panel Package
"""
仿真面板包

包含仿真结果展示相关的 UI 组件：
- SimulationViewModel: 仿真面板 ViewModel
- ChartViewer: 图表查看器
- WaveformWidget: 交互式波形图表组件
- RawDataTable: 原始数据表格（结果快照绑定）
- OutputLogViewer: 仿真输出日志查看器
- SimulationExportPanel: 统一导出面板
- SimulationTab: 仿真结果标签页主类（Web host + backend runtime）
- SimulationWebHost / SimulationWebBridge: Web 前端宿主与桥接
"""

from presentation.panels.simulation.simulation_view_model import (
    SimulationViewModel,
    SimulationStatus,
    DisplayMetric,
)
from presentation.panels.simulation.metric_card import MetricCard
from presentation.panels.simulation.metrics_panel import MetricsPanel
from presentation.panels.simulation.analysis_chart_viewer import ChartViewer
from presentation.panels.simulation.waveform_widget import WaveformWidget
from presentation.panels.simulation.waveform_plot_types import WaveformMeasurement
from presentation.panels.simulation.raw_data_table import RawDataTable, RawDataTableModel
from presentation.panels.simulation.output_log_viewer import OutputLogViewer
from presentation.panels.simulation.simulation_export_panel import SimulationExportPanel
from presentation.panels.simulation.simulation_frontend_state_serializer import SimulationFrontendStateSerializer
from presentation.panels.simulation.simulation_tab import (
    SimulationTab,
)
from presentation.panels.simulation.simulation_web_bridge import SimulationWebBridge
from presentation.panels.simulation.simulation_web_host import SimulationWebHost

__all__ = [
    "SimulationViewModel",
    "SimulationStatus",
    "DisplayMetric",
    "MetricCard",
    "MetricsPanel",
    "ChartViewer",
    "WaveformWidget",
    "WaveformMeasurement",
    "RawDataTable",
    "RawDataTableModel",
    "OutputLogViewer",
    "SimulationExportPanel",
    "SimulationFrontendStateSerializer",
    "SimulationTab",
    "SimulationWebBridge",
    "SimulationWebHost",
]
