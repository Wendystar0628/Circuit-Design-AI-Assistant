from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QWidget

from presentation.panels.simulation.analysis_chart_viewer import ChartViewer
from presentation.panels.simulation.analysis_info_panel import AnalysisInfoPanel
from presentation.panels.simulation.output_log_viewer import OutputLogViewer
from presentation.panels.simulation.raw_data_table import RawDataTable
from presentation.panels.simulation.simulation_export_panel import SimulationExportPanel
from presentation.panels.simulation.waveform_widget import WaveformWidget


_PRIMARY_SURFACE_SIZE = QSize(1280, 840)
_AUX_SURFACE_SIZE = QSize(1120, 760)


class SimulationBackendRuntime(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("simulationBackendRuntime")
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

        self._chart_viewer = ChartViewer(self)
        self._waveform_widget = WaveformWidget(self)
        self._analysis_info_panel = AnalysisInfoPanel(self)
        self._raw_data_table = RawDataTable(self)
        self._output_log_viewer = OutputLogViewer(self)
        self._export_panel = SimulationExportPanel(self._chart_viewer, self._waveform_widget, self)

        self._prime_surface(self._chart_viewer, _PRIMARY_SURFACE_SIZE)
        self._prime_surface(self._waveform_widget, _PRIMARY_SURFACE_SIZE)
        self._prime_surface(self._analysis_info_panel, _AUX_SURFACE_SIZE)
        self._prime_surface(self._output_log_viewer, _AUX_SURFACE_SIZE)
        self._prime_surface(self._export_panel, _AUX_SURFACE_SIZE)

    @property
    def chart_viewer(self) -> ChartViewer:
        return self._chart_viewer

    @property
    def waveform_widget(self) -> WaveformWidget:
        return self._waveform_widget

    @property
    def analysis_info_panel(self) -> AnalysisInfoPanel:
        return self._analysis_info_panel

    @property
    def raw_data_table(self) -> RawDataTable:
        return self._raw_data_table

    @property
    def output_log_viewer(self) -> OutputLogViewer:
        return self._output_log_viewer

    @property
    def export_panel(self) -> SimulationExportPanel:
        return self._export_panel

    def clear(self):
        self._chart_viewer.clear()
        self._waveform_widget.reset()
        self._analysis_info_panel.clear()
        self._raw_data_table.clear()
        self._output_log_viewer.clear()
        self._export_panel.clear()

    def retranslate_ui(self):
        self._chart_viewer.retranslate_ui()
        self._waveform_widget.retranslate_ui()
        self._analysis_info_panel.retranslate_ui()
        self._raw_data_table.retranslate_ui()
        self._output_log_viewer.retranslate_ui()
        self._export_panel.retranslate_ui()

    def _prime_surface(self, widget: QWidget, size: QSize):
        widget.resize(size)
        widget.ensurePolished()
        widget.hide()


__all__ = ["SimulationBackendRuntime"]
