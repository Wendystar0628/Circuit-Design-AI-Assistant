from PyQt6.QtCore import QObject, QSize, Qt
from PyQt6.QtWidgets import QWidget

from presentation.panels.simulation.analysis_chart_viewer import ChartViewer
from presentation.panels.simulation.output_log_viewer import OutputLogViewer
from presentation.panels.simulation.raw_data_table import RawDataTable
from presentation.panels.simulation.simulation_asc_conversion_panel import SimulationAscConversionPanel
from presentation.panels.simulation.simulation_export_panel import SimulationExportPanel
from presentation.panels.simulation.spice_schematic_document import SpiceSchematicDocument
from presentation.panels.simulation.waveform_widget import WaveformWidget


_PRIMARY_SURFACE_SIZE = QSize(1280, 840)


class SimulationBackendRuntime(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        # React owns the visible UI. Only chart/waveform remain QWidgets
        # because their image-export/rendering implementation genuinely needs
        # a polished Qt paint surface; every pure state component is QObject.
        widget_parent = parent if isinstance(parent, QWidget) else None
        self._chart_viewer = ChartViewer(widget_parent)
        self._waveform_widget = WaveformWidget(widget_parent)
        self._chart_viewer.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self._waveform_widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self._raw_data_table = RawDataTable(self)
        self._output_log_viewer = OutputLogViewer(self)
        self._export_panel = SimulationExportPanel(self._chart_viewer, self._waveform_widget, widget_parent)
        self._asc_conversion_panel = SimulationAscConversionPanel(widget_parent)
        self._spice_schematic_document = SpiceSchematicDocument(self)

        self._prime_surface(self._chart_viewer, _PRIMARY_SURFACE_SIZE)
        self._prime_surface(self._waveform_widget, _PRIMARY_SURFACE_SIZE)

    @property
    def chart_viewer(self) -> ChartViewer:
        return self._chart_viewer

    @property
    def waveform_widget(self) -> WaveformWidget:
        return self._waveform_widget

    @property
    def raw_data_table(self) -> RawDataTable:
        return self._raw_data_table

    @property
    def output_log_viewer(self) -> OutputLogViewer:
        return self._output_log_viewer

    @property
    def export_panel(self) -> SimulationExportPanel:
        return self._export_panel

    @property
    def asc_conversion_panel(self) -> SimulationAscConversionPanel:
        return self._asc_conversion_panel

    @property
    def spice_schematic_document(self) -> SpiceSchematicDocument:
        return self._spice_schematic_document

    def clear(self):
        self._chart_viewer.clear()
        self._waveform_widget.reset()
        self._raw_data_table.clear()
        self._output_log_viewer.clear()
        self._export_panel.clear()
        self._asc_conversion_panel.clear()
        self._spice_schematic_document.clear()

    def retranslate_ui(self):
        self._chart_viewer.retranslate_ui()
        self._waveform_widget.retranslate_ui()
        self._raw_data_table.retranslate_ui()
        self._output_log_viewer.retranslate_ui()
        self._export_panel.retranslate_ui()
        self._asc_conversion_panel.retranslate_ui()

    def _prime_surface(self, widget: QWidget, size: QSize):
        widget.resize(size)
        widget.ensurePolished()
        widget.hide()


__all__ = ["SimulationBackendRuntime"]
