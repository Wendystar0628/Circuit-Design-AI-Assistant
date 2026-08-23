# SimulationTab - Simulation Results Tab
"""
仿真结果标签页

职责：
- 作为仿真结果面板的权威协调器
- 将前端状态序列化并推送给 SimulationWebHost
- 维护结果状态控制器，并为图表/波形导出保留必要的离屏绘制表面
- 响应项目/仿真事件并切换前端 peer tab 状态

设计原则：
- 使用 QWidget 作为基类
- 通过 SimulationViewModel 获取数据
- 订阅事件响应项目切换和仿真完成
- 可见主路径只保留 Web host；仅图表与波形需要离屏 Qt 绘制表面
- 支持国际化

被调用方：
- main_window.py
"""

import copy
import logging
from typing import List, Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QSizePolicy,
    QMessageBox,
)

from presentation.panels.simulation.simulation_view_model import (
    SimulationViewModel,
)
from domain.simulation.service.simulation_result_repository import (
    CircuitResultGroup,
    simulation_result_repository,
)
from presentation.panels.simulation.simulation_backend_runtime import SimulationBackendRuntime
from presentation.panels.simulation.simulation_conversation_attachment_coordinator import SimulationConversationAttachmentCoordinator
from presentation.panels.simulation.simulation_frontend_state_serializer import (
    ALL_TAB_IDS,
    SimulationFrontendStateSerializer,
)
from presentation.panels.simulation.simulation_web_bridge import SimulationWebBridge
from presentation.panels.simulation.simulation_web_host import SimulationWebHost
from resources.theme import (
    COLOR_BG_PRIMARY,
)
from shared.event_types import (
    EVENT_STATE_PROJECT_OPENED,
    EVENT_STATE_PROJECT_CLOSED,
    EVENT_SIM_COMPLETE,
    EVENT_SIM_STARTED,
    EVENT_SIM_ERROR,
    EVENT_LANGUAGE_CHANGED,
)
from shared.sim_event_payload import extract_sim_payload
from shared.path_utils import normalize_identity_path


class SimulationTab(QWidget):
    """
    仿真结果标签页
    
    协调各子组件，管理仿真结果标签页整体布局。
    
    Signals:
        authoritative_frontend_state_changed: 权威前端状态更新
    """

    authoritative_frontend_state_changed = pyqtSignal(dict)
    schematic_document_changed = pyqtSignal(dict)
    schematic_write_result_changed = pyqtSignal(dict)
    raw_data_document_changed = pyqtSignal(dict)
    raw_data_viewport_changed = pyqtSignal(dict)
    raw_data_copy_result_changed = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # ViewModel
        self._view_model = SimulationViewModel()
        
        # 项目状态
        self._project_root: Optional[str] = None
        # The displayed identity has two mutually exclusive forms: a live
        # ``job_id`` while a UI run is active, or a persisted ``result_path``
        # after a bundle has loaded. Project switches clear both.
        self._displayed_job_id: Optional[str] = None
        self._displayed_result_path: Optional[str] = None
        self._displayed_circuit_file: Optional[str] = None
        self._active_frontend_tab = "metrics"
        self._runtime_status_message = ""
        self._panel_error_message = ""
        self._state_serializer = SimulationFrontendStateSerializer()
        self._authoritative_frontend_state = self._state_serializer.serialize_main_state()
        self._authoritative_schematic_document = self._state_serializer.serialize_schematic_document()
        self._authoritative_schematic_write_result = self._state_serializer.serialize_schematic_write_result()
        self._authoritative_raw_data_document = self._state_serializer.serialize_raw_data_document()
        self._authoritative_raw_data_viewport = self._state_serializer.serialize_raw_data_viewport()
        self._raw_data_copy_sequence = 0
        self._authoritative_raw_data_copy_result = self._state_serializer.serialize_raw_data_copy_result()
        # Single by-circuit result-index cache feeding circuit selection.
        # Handed verbatim to
        # :meth:`SimulationFrontendStateSerializer.serialize_main_state`
        # via the ``circuit_groups=`` input, which derives the grouped
        # card grid from this one cache — no consumer ever hits the
        # repository on its own. ``_refresh_circuit_result_index`` is the
        # only disk-scan entry point.
        self._circuit_result_index_cache: List[CircuitResultGroup] = []
        self._bound_web_bridge: Optional[SimulationWebBridge] = None
        
        # EventBus 引用
        self._event_bus = None
        self._subscriptions: List[tuple] = []
        
        # 初始化 UI
        self._setup_ui()
        if self._web_host is not None:
            self._web_host.attach_simulation_tab(self)
        self._conversation_attachment_coordinator = SimulationConversationAttachmentCoordinator(
            self._backend_runtime.chart_viewer,
            self._backend_runtime.waveform_widget,
        )
        self._apply_style()
        self._connect_signals()
        
        # 订阅事件
        self._subscribe_events()
        
        # 初始化文本
        self.retranslate_ui()
        self._update_frontend_payloads(include_raw_data=True)
    
    def _setup_ui(self):
        """初始化 UI 组件"""
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._web_host = SimulationWebHost(self)
        self.setFocusProxy(self._web_host)
        main_layout.addWidget(self._web_host, 1)
        self._backend_runtime = SimulationBackendRuntime(self)

    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            SimulationTab {{
                background-color: {COLOR_BG_PRIMARY};
            }}
        """)
    
    def _connect_signals(self):
        """连接信号"""
        # ViewModel is mutated synchronously by this coordinator. Publishing
        # once after a complete transition avoids WebChannel frames that mix
        # half of the old result with half of the new one.
        self._backend_runtime.spice_schematic_document.schematic_document_changed.connect(
            self._on_runtime_schematic_document_changed
        )
        self._backend_runtime.spice_schematic_document.schematic_write_result_changed.connect(
            self._on_runtime_schematic_write_result_changed
        )
        self._backend_runtime.spice_schematic_document.source_provenance_invalidated.connect(
            self._on_schematic_source_provenance_invalidated
        )
        self._backend_runtime.asc_conversion_panel.state_changed.connect(
            self._update_frontend_payloads
        )

    def get_authoritative_frontend_state(self):
        return copy.deepcopy(self._authoritative_frontend_state)

    def get_authoritative_schematic_document(self):
        return copy.deepcopy(self._authoritative_schematic_document)

    def get_authoritative_schematic_write_result(self):
        return copy.deepcopy(self._authoritative_schematic_write_result)

    def _on_runtime_schematic_document_changed(self, state: dict) -> None:
        next_schematic_document = self._state_serializer.serialize_schematic_document(state)
        if next_schematic_document == self._authoritative_schematic_document:
            return
        self._authoritative_schematic_document = next_schematic_document
        self.schematic_document_changed.emit(copy.deepcopy(self._authoritative_schematic_document))

    def _on_runtime_schematic_write_result_changed(self, state: dict) -> None:
        next_write_result = self._state_serializer.serialize_schematic_write_result(state)
        if next_write_result == self._authoritative_schematic_write_result:
            return
        self._authoritative_schematic_write_result = next_write_result
        self.schematic_write_result_changed.emit(copy.deepcopy(self._authoritative_schematic_write_result))

    def _on_schematic_source_provenance_invalidated(self, reason: str) -> None:
        self._runtime_status_message = str(reason or "")
        self._update_authoritative_frontend_state()

    def get_authoritative_raw_data_document(self):
        return copy.deepcopy(self._authoritative_raw_data_document)

    def get_authoritative_raw_data_viewport(self):
        return copy.deepcopy(self._authoritative_raw_data_viewport)

    def get_authoritative_raw_data_copy_result(self):
        return copy.deepcopy(self._authoritative_raw_data_copy_result)

    def _normalize_frontend_tab_id(self, tab_id: str) -> str:
        return str(tab_id or "metrics")

    def _is_allowed_frontend_tab(self, tab_id: str) -> bool:
        """Membership check against the authoritative tab catalogue.

        The previous implementation maintained a hand-rolled literal
        set that duplicated the serializer's `_BASE_TABS` + conditional
        append list; adding a new tab required editing three separate
        places. The single source of truth now lives in
        :data:`ALL_TAB_IDS`, so every acceptance predicate — here, the
        `available_tabs` serialization, and the tab-bar chip order —
        reads the same catalogue.
        """
        return tab_id in ALL_TAB_IDS

    def _set_active_frontend_tab(self, tab_id: str) -> bool:
        normalized_tab_id = self._normalize_frontend_tab_id(tab_id)
        if not self._is_allowed_frontend_tab(normalized_tab_id):
            return False
        self._active_frontend_tab = normalized_tab_id
        return True

    def _refresh_circuit_result_index(self) -> None:
        """Rebuild the by-circuit aggregated result index.

        **The single disk-scan entry point** for the simulation panel:
        every other consumer — the circuit-selection grid and
        the project-open restore flow — reads from
        :attr:`_circuit_result_index_cache` instead of hitting the
        repository on its own. A grep in
        ``presentation/panels/simulation/`` must show exactly one
        ``simulation_result_repository.list_by_circuit(`` call site,
        and that call site is this one.

        Refresh is triggered — unconditionally, without consulting
        job identity or origin — by:
          * :meth:`_on_project_opened` / :meth:`_on_project_closed`
          * :meth:`_on_simulation_complete` (before the displayed-
            triple ``job_id`` filter — agent-origin completions must
            still update the index)
          * :meth:`_on_simulation_error` (same rationale — failure
            bundles also land on disk and belong in circuit selection)
          * :meth:`_render_result` — after an explicit
            ``load_result_by_path`` render, to catch any bundles
            persisted while the render was in flight

        Runs on the main thread; EventBus already marshals signals
        there, so no lock is taken.
        """
        if not self._project_root:
            self._circuit_result_index_cache = []
            return
        try:
            self._circuit_result_index_cache = simulation_result_repository.list_by_circuit(
                self._project_root
            )
        except Exception as exc:
            self._circuit_result_index_cache = []
            self._logger.warning(f"Failed to refresh simulation circuit result index: {exc}")

    def _build_frontend_runtime_snapshots(self):
        active_tab = self._normalize_frontend_tab_id(self._active_frontend_tab)
        current_result = self._view_model.current_result
        analysis_chart_snapshot = self._backend_runtime.chart_viewer.get_web_snapshot() if active_tab == "chart" else None
        waveform_snapshot = self._backend_runtime.waveform_widget.get_web_snapshot() if active_tab == "waveform" else None
        output_log_snapshot = None
        export_snapshot = self._backend_runtime.export_panel.get_web_snapshot()
        asc_conversion_snapshot = self._backend_runtime.asc_conversion_panel.get_web_snapshot()
        if current_result is not None:
            if active_tab == "output_log":
                output_log_snapshot = self._backend_runtime.output_log_viewer.get_web_snapshot()
            else:
                output_log_snapshot = self._backend_runtime.output_log_viewer.get_web_snapshot(max_lines=0)
        return {
            "analysis_chart_snapshot": analysis_chart_snapshot,
            "waveform_snapshot": waveform_snapshot,
            "output_log_snapshot": output_log_snapshot,
            "export_snapshot": export_snapshot,
            "asc_conversion_snapshot": asc_conversion_snapshot,
        }

    def _build_frontend_ui_text(self):
        entries = [
            ("panel.simulation", "Simulation Panel"),
            ("panel.simulation.tab_navigation", "Simulation result tabs"),
            ("panel.simulation.bridge_disconnected_title", "Frontend bridge is disconnected"),
            ("panel.simulation.bridge_disconnected_message", "Some local actions may be temporarily unavailable, but the current tab layout still reflects the authoritative state shell."),
            ("panel.simulation.error_title", "Simulation Error"),
            ("panel.simulation.status_title", "Runtime Status"),
            ("panel.simulation.empty_title", "No Simulation Result Yet"),
            ("panel.simulation.empty_with_project", "Run a simulation once and the current tab will display the corresponding result."),
            ("panel.simulation.empty_without_project", "Open a project and run a simulation first."),
            ("simulation.cancel", "Cancel Simulation"),
            ("simulation.cancelling", "Cancellation requested. Waiting for the simulator to stop safely..."),
            ("simulation.cancelled", "Simulation cancelled."),
            ("simulation.cancel_failed", "The current simulation could not be cancelled because it is no longer running."),
            ("simulation.result_load_failed", "Could not load simulation result: {message}"),
            ("simulation.metric_targets_failed", "Could not save metric targets: {message}"),
            ("simulation.noise_totals.title", "Integrated Noise Totals"),
            ("simulation.noise_totals.output_rms", "Integrated output noise"),
            ("simulation.noise_totals.input_referred_rms", "Input-referred noise"),
            ("simulation.noise_totals.note", "Read-only sweep-band integrated RMS scalars from ngspice (FSTART–FSTOP). They are not .MEASURE rows or V/√Hz / A/√Hz spectral-density samples."),
            ("simulation.noise_totals.unavailable", "Integrated totals are unavailable for this noise run; the spectral-density curves may still be available."),
            ("panel.simulation.go_to_circuit_selection", "Go to Circuit Selection"),
            ("panel.simulation.tab.circuit_selection", "Circuit Selection"),
            ("panel.simulation.tab.metrics", "Metrics"),
            ("panel.simulation.tab.schematic", "Schematic"),
            ("panel.simulation.tab.chart", "Chart"),
            ("panel.simulation.tab.waveform", "Waveform"),
            ("panel.simulation.tab.analysis_info", "Analysis Info"),
            ("panel.simulation.tab.raw_data", "Raw Data"),
            ("panel.simulation.tab.output_log", "Output Log"),
            ("panel.simulation.tab.export", "Export"),
            ("panel.simulation.tab.asc_conversion", "ASC Conversion"),
            ("panel.simulation.tab.op_result", "Operating Point Result"),
            ("simulation.analysis_label.ac", "AC Small-Signal Analysis"),
            ("simulation.analysis_label.dc", "DC Sweep Analysis"),
            ("simulation.analysis_label.tran", "Transient Analysis"),
            ("simulation.analysis_label.noise", "Noise Analysis"),
            ("simulation.analysis_label.op", "Operating Point Analysis"),
            ("common.current", "Current"),
            ("common.current_value", "Current Value"),
            ("common.target_value", "Target Value"),
            ("common.signal", "Signal"),
            ("common.confirm", "Confirm"),
            ("common.submit", "Submit"),
            ("common.submitting", "Submitting..."),
            ("common.add_to_conversation", "Add to Conversation"),
            ("common.select_signal", "Select Signals"),
            ("common.visible", "Visible"),
            ("common.fit", "Fit"),
            ("common.search", "Search"),
            ("common.filter", "Filter"),
            ("common.copy", "Copy"),
            ("common.copied", "Copied"),
            ("common.all", "All"),
            ("common.error", "Error"),
            ("common.warning", "Warning"),
            ("common.info", "Info"),
            ("common.no_data", "No data available."),
            ("simulation.circuit_selection.no_project", "No project is open yet"),
            ("simulation.circuit_selection.no_project_hint", "Open a project and run a simulation before choosing a circuit here."),
            ("simulation.circuit_selection.no_history", "No simulation history yet"),
            ("simulation.circuit_selection.no_history_hint", "Run a simulation once and results will be grouped by circuit here."),
            ("simulation.circuit_selection.latest_run", "Latest: {meta}"),
            ("simulation.circuit_selection.latest_run_empty", "Latest: No metadata"),
            ("simulation.circuit_selection.run_count", "{count} runs"),
            ("simulation.circuit_selection.latest_failed", "Latest Failed"),
            ("simulation.circuit_selection.not_loadable", "Not Loadable"),
            ("simulation.circuit_selection.unnamed_circuit", "Unnamed Circuit"),
            ("simulation.circuit_selection.result_label", "Result"),
            ("simulation.circuit_selection.choose_result", "Choose result"),
            ("simulation.circuit_selection.run_succeeded", "Succeeded"),
            ("simulation.circuit_selection.run_failed", "Failed"),
            ("simulation.metrics.confirm_changes", "Confirm Changes"),
            ("simulation.metrics.empty_title", "No Metrics"),
            ("simulation.metrics.empty_hint", "Add `.MEASURE` statements to the SPICE file and run a simulation to generate metrics."),
            ("simulation.metrics.target_placeholder", "e.g. ≥ 20 dB"),
            ("simulation.schematic.component_type", "Component Type"),
            ("simulation.schematic.component_name", "Current Component Name"),
            ("simulation.schematic.connected_nodes", "Connected Nodes"),
            ("simulation.schematic.no_pins", "This component has no pins to display."),
            ("simulation.schematic.component_value", "Component Value"),
            ("simulation.schematic.current_value", "Current Value"),
            ("simulation.schematic.replacement_value", "Replacement Value"),
            ("simulation.schematic.value_not_editable", "The current component value cannot be edited."),
            ("simulation.schematic.pending_write", "Submitting changes..."),
            ("simulation.schematic.pending_write_hint", "Requesting backend write-back. The current display follows the refreshed backend result."),
            ("simulation.schematic.no_editable_value", "This component has no editable value."),
            ("simulation.schematic.component_details", "Component Details"),
            ("simulation.schematic.component_details_hint", "Select a component to inspect its type, connected nodes, and component value."),
            ("simulation.schematic.write_pending_banner", "Submitting changes and waiting for the backend to re-parse and refresh."),
            ("simulation.schematic.write_conflict_banner", "The document changed. The submission for the old revision was rejected. Please edit again based on the current content."),
            ("simulation.schematic.write_success_banner", "Changes were submitted. The current display follows the refreshed backend result."),
            ("simulation.chart.default_title", "Chart"),
            ("simulation.chart.enable_measurement", "Enable Measurement"),
            ("simulation.chart.disable_measurement", "Disable Measurement"),
            ("simulation.chart.enable_measurement_point", "Enable Measurement Point"),
            ("simulation.chart.disable_measurement_point", "Disable Measurement Point"),
            ("simulation.chart.clear_signals", "Clear Signals"),
            ("simulation.chart.measurement", "Measurement"),
            ("simulation.chart.measurement_point", "Measurement Point"),
            ("simulation.chart.measurement_point_empty", "No sampled values are available for the current measurement point."),
            ("simulation.chart.measurement_empty", "No measurement values are available for the selected signal."),
            ("simulation.chart.select_signals", "Select Signals"),
            ("simulation.chart.no_selectable_series", "No chart series are available for the current result."),
            ("simulation.chart.visible_series", "Visible"),
            ("simulation.chart.no_visible_series", "No signals are currently visible."),
            ("simulation.chart.empty_hidden", "No series are currently displayed. Re-select them from the left sidebar."),
            ("simulation.chart.empty_no_chart", "No chart is available for the current result."),
            ("simulation.waveform.time_domain_title", "Time-Domain Waveform"),
            ("simulation.waveform.dc_sweep_title", "DC Sweep Waveform"),
            ("simulation.waveform.default_title", "Waveform"),
            ("simulation.waveform.hide_cursor_a", "Hide A"),
            ("simulation.waveform.show_cursor_a", "Show A"),
            ("simulation.waveform.hide_cursor_b", "Hide B"),
            ("simulation.waveform.show_cursor_b", "Show B"),
            ("simulation.waveform.clear_signals", "Clear Signals"),
            ("simulation.waveform.select_signals", "Select Signals"),
            ("simulation.waveform.no_selectable_signals", "No waveform signals are available for the current result."),
            ("simulation.waveform.visible_signals", "Visible"),
            ("simulation.waveform.no_visible_signals", "No signals are currently visible."),
            ("simulation.waveform.measurement", "Measurement"),
            ("simulation.waveform.measurement_empty", "No measurement values are available for the selected signal."),
            ("simulation.waveform.empty_hidden", "No waveform is currently displayed. Select signals from the left sidebar."),
            ("simulation.waveform.empty_no_waveform", "No waveform is available for the current result."),
            ("simulation.output_log.keyword", "Keyword"),
            ("simulation.output_log.search_placeholder", "Enter search keyword"),
            ("simulation.output_log.apply_filter", "Apply Filter"),
            ("simulation.output_log.empty", "There are currently no log lines to display."),
            ("simulation.output_log.truncated", "Showing {visible} of {total} filtered lines. Copy includes all filtered lines."),
            ("simulation.measurement.drag_hint", "Drag to move"),
            ("simulation.measurement.select_signal_aria", "Select measurement signal"),
            ("simulation.measurement_point.select_signal_aria", "Select measurement-point signal"),
            ("simulation.analysis_info.analysis_type", "Analysis Type"),
            ("simulation.analysis_info.not_loaded", "Not Loaded"),
            ("simulation.analysis_info.executor", "Executor"),
            ("simulation.analysis_info.file", "File"),
            ("simulation.analysis_info.x_axis", "X Axis"),
            ("simulation.analysis_info.undefined", "Undefined"),
            ("simulation.analysis_info.parameters", "Parameters"),
            ("simulation.analysis_info.empty_parameters", "No structured parameters are available."),
            ("simulation.export.title", "Export"),
            ("simulation.export.export_selected", "Export Selected Items"),
            ("simulation.export.directory", "Export Directory"),
            ("simulation.export.not_selected", "Not Selected"),
            ("simulation.export.choose_directory", "Choose Directory"),
            ("simulation.export.clear_directory", "Clear Directory"),
            ("simulation.export.select_all", "Select All"),
            ("simulation.export.clear_selection", "Clear Selection"),
            ("simulation.export.empty", "There are no exportable items yet."),
            ("simulation.export.recent_project_directory", "Recent Project Export Directory"),
            ("simulation.export.none", "None"),
            ("simulation.export.metrics", "Metrics"),
            ("simulation.export.charts", "Charts"),
            ("simulation.export.waveforms", "Waveforms"),
            ("simulation.export.analysis_info", "Analysis Info"),
            ("simulation.export.raw_data", "Raw Data"),
            ("simulation.export.output_log", "Output Log"),
            ("simulation.export.op_result", "Operating Point Result"),
            ("simulation.asc.title", "ASC Conversion"),
            ("simulation.asc.description", "Choose one or more LTspice .asc files and the system will generate the corresponding .cir files in the current workspace directory."),
            ("simulation.asc.files", "ASC Files"),
            ("simulation.asc.not_selected", "Not Selected"),
            ("simulation.asc.choose_and_convert", "Choose and Convert"),
            ("simulation.op_result.title", "Operating Point Result"),
            ("simulation.op_result.description", "Local action area plus a structured result table."),
            ("simulation.op_result.result_file", "Result File"),
            ("simulation.op_result.unnamed_result", "Unnamed Result"),
            ("simulation.op_result.analysis_command", "Analysis Command"),
            ("simulation.op_result.row_count", "Row Count"),
            ("simulation.op_result.section_count", "Section Count"),
            ("simulation.op_result.item_count", "{count} items"),
            ("simulation.op_result.invalid_value", "Invalid Value"),
            ("simulation.op_result.empty_section", "No results are available for the current section."),
            ("simulation.op_result.empty", "The current result does not contain structured operating-point data."),
            ("simulation.raw_data.copy_failed", "Copy failed"),
            ("simulation.raw_data.copy_success", "Copied {rows} × {cols}"),
            ("simulation.raw_data.copying_selection", "Copying {selection}"),
            ("simulation.raw_data.copying", "Copying"),
            ("simulation.raw_data.empty", "No raw data is available to display."),
            ("simulation.raw_data.grid_summary", "{rows} rows · {cols} columns"),
            ("simulation.raw_data.copy_shortcuts", "Ctrl/Cmd + C to copy selection, Ctrl/Cmd + A to select all."),
            ("simulation.schematic.stale_draft_notice", "The authoritative document was refreshed and local drafts for the old revision were discarded."),
            ("simulation.schematic.layout_failed", "Failed to compute the schematic layout."),
            ("simulation.schematic.empty_no_source_title", "No schematic source file is available"),
            ("simulation.schematic.empty_layout_pending_title", "Computing schematic layout"),
            ("simulation.schematic.empty_layout_failed_title", "Schematic layout failed"),
            ("simulation.schematic.empty_not_renderable_title", "The current document has no renderable schematic"),
            ("simulation.schematic.empty_no_source_description", "The current result does not yet provide a source file path that the schematic tab can consume."),
            ("simulation.schematic.empty_layout_pending_description", "Computing the schematic layout from the latest schematic document."),
            ("simulation.schematic.empty_not_renderable_description", "The current schematic document did not provide drawable components."),
            ("simulation.schematic.source_missing_historical", "源电路文件在当前项目中不可用，历史结果原理图不可用。"),
            ("simulation.schematic.source_digest_missing", "仿真结果缺少有效的源电路摘要，历史结果原理图不可用。"),
            ("simulation.schematic.select_component", "Select component {name}"),
            ("simulation.schematic.banner_layout_pending_title", "Layout computation in progress"),
            ("simulation.schematic.banner_layout_pending_description", "Only the latest layout result for the current document and revision will be applied."),
            ("simulation.schematic.banner_layout_failed_title", "Layout failed"),
            ("simulation.schematic.banner_parse_warnings_title", "Parse Warnings"),
            ("simulation.schematic.type.resistor", "Resistor"),
            ("simulation.schematic.type.capacitor", "Capacitor"),
            ("simulation.schematic.type.inductor", "Inductor"),
            ("simulation.schematic.type.diode", "Diode"),
            ("simulation.schematic.type.voltage_source", "Voltage Source"),
            ("simulation.schematic.type.current_source", "Current Source"),
            ("simulation.schematic.type.ground", "Ground"),
            ("simulation.schematic.type.subcircuit", "Subcircuit"),
            ("simulation.schematic.type.controlled_source", "Controlled Source"),
            ("simulation.schematic.type.opamp", "Operational Amplifier"),
            ("simulation.schematic.type.bjt", "BJT"),
            ("simulation.schematic.type.mos", "MOSFET"),
            ("simulation.schematic.type.jfet", "JFET"),
            ("simulation.schematic.type.unknown", "Unknown Component"),
        ]
        return {key: self._get_text(key, default) for key, default in entries}
     
    def _build_authoritative_frontend_state(self):
        snapshot_payloads = self._build_frontend_runtime_snapshots()
        return self._state_serializer.serialize_main_state(
            project_root=self._project_root or "",
            active_tab=self._normalize_frontend_tab_id(self._active_frontend_tab),
            current_result=self._view_model.current_result,
            current_result_path=self._displayed_result_path or "",
            current_job_id=self._displayed_job_id or "",
            displayed_circuit_file=self._displayed_circuit_file or "",
            metrics=self._view_model.metrics_list,
            simulation_status=self._view_model.simulation_status,
            status_message=self._runtime_status_message,
            error_message=self._panel_error_message or self._view_model.error_message,
            circuit_groups=self._circuit_result_index_cache,
            latest_project_export_root=self._current_displayed_bundle_dir() or "",
            can_cancel=self._can_cancel_current_job(),
            analysis_chart_snapshot=snapshot_payloads["analysis_chart_snapshot"],
            waveform_snapshot=snapshot_payloads["waveform_snapshot"],
            output_log_snapshot=snapshot_payloads["output_log_snapshot"],
            export_snapshot=snapshot_payloads["export_snapshot"],
            asc_conversion_snapshot=snapshot_payloads["asc_conversion_snapshot"],
            ui_text=self._build_frontend_ui_text(),
        )

    def _build_authoritative_raw_data_document(self):
        return self._state_serializer.serialize_raw_data_document(
            self._backend_runtime.raw_data_table.get_document_payload(),
            self._view_model.current_result,
        )

    def _build_authoritative_raw_data_viewport(
        self,
        *,
        dataset_id: str = "",
        version: Optional[int] = None,
        row_start: int = 0,
        row_end: int = 0,
        col_start: int = 0,
        col_end: int = 0,
    ):
        return self._state_serializer.serialize_raw_data_viewport(
            self._backend_runtime.raw_data_table.get_viewport_payload(
                dataset_id=dataset_id,
                version=version,
                row_start=row_start,
                row_end=row_end,
                col_start=col_start,
                col_end=col_end,
            )
        )

    def _build_authoritative_raw_data_copy_result(
        self,
        *,
        dataset_id: str = "",
        version: int = 0,
        success: bool = False,
        row_count: int = 0,
        col_count: int = 0,
    ):
        return self._state_serializer.serialize_raw_data_copy_result(
            {
                "dataset_id": dataset_id,
                "version": version,
                "sequence": self._raw_data_copy_sequence,
                "success": success,
                "row_count": row_count,
                "col_count": col_count,
            }
        )

    def _update_authoritative_frontend_state(self):
        next_state = self._build_authoritative_frontend_state()
        if next_state == self._authoritative_frontend_state:
            return
        self._authoritative_frontend_state = next_state
        self.authoritative_frontend_state_changed.emit(copy.deepcopy(self._authoritative_frontend_state))

    def _update_authoritative_raw_data_document(self):
        next_raw_data_document = self._build_authoritative_raw_data_document()
        if next_raw_data_document == self._authoritative_raw_data_document:
            return
        self._authoritative_raw_data_document = next_raw_data_document
        self.raw_data_document_changed.emit(copy.deepcopy(self._authoritative_raw_data_document))

    def _update_authoritative_raw_data_viewport(
        self,
        *,
        dataset_id: str = "",
        version: Optional[int] = None,
        row_start: int = 0,
        row_end: int = 0,
        col_start: int = 0,
        col_end: int = 0,
    ):
        next_raw_data_viewport = self._build_authoritative_raw_data_viewport(
            dataset_id=dataset_id,
            version=version,
            row_start=row_start,
            row_end=row_end,
            col_start=col_start,
            col_end=col_end,
        )
        if next_raw_data_viewport == self._authoritative_raw_data_viewport:
            return
        self._authoritative_raw_data_viewport = next_raw_data_viewport
        self.raw_data_viewport_changed.emit(copy.deepcopy(self._authoritative_raw_data_viewport))

    def _emit_authoritative_raw_data_copy_result(
        self,
        *,
        dataset_id: str = "",
        version: int = 0,
        success: bool = False,
        row_count: int = 0,
        col_count: int = 0,
    ):
        self._raw_data_copy_sequence += 1
        self._authoritative_raw_data_copy_result = self._build_authoritative_raw_data_copy_result(
            dataset_id=dataset_id,
            version=version,
            success=success,
            row_count=row_count,
            col_count=col_count,
        )
        self.raw_data_copy_result_changed.emit(copy.deepcopy(self._authoritative_raw_data_copy_result))

    def _update_frontend_payloads(self, *, include_raw_data: bool = False) -> None:
        self._update_authoritative_frontend_state()
        if include_raw_data:
            self._update_authoritative_raw_data_document()
            self._update_authoritative_raw_data_viewport()

    def _subscribe_events(self):
        """订阅事件"""
        event_bus = self._get_event_bus()
        if not event_bus:
            return

        subscriptions = [
            (EVENT_STATE_PROJECT_OPENED, self._on_project_opened),
            (EVENT_STATE_PROJECT_CLOSED, self._on_project_closed),
            (EVENT_SIM_STARTED, self._on_simulation_started),
            (EVENT_SIM_COMPLETE, self._on_simulation_complete),
            (EVENT_SIM_ERROR, self._on_simulation_error),
            (EVENT_LANGUAGE_CHANGED, self._on_language_changed),
        ]

        for event_type, handler in subscriptions:
            event_bus.subscribe(event_type, handler)
            self._subscriptions.append((event_type, handler))

    def _unsubscribe_events(self):
        """取消事件订阅"""
        event_bus = self._get_event_bus()
        if not event_bus:
            return

        for event_type, handler in self._subscriptions:
            try:
                event_bus.unsubscribe(event_type, handler)
            except Exception:
                pass

        self._subscriptions.clear()

    def _get_event_bus(self):
        """获取 EventBus"""
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus

    def _payload_belongs_to_current_project(self, payload: dict) -> bool:
        if not self._project_root:
            return False
        return (
            normalize_identity_path(str(payload.get("project_root") or ""))
            == normalize_identity_path(self._project_root)
        )

    def _request_targets_current_project(self, payload: dict) -> bool:
        return bool(
            isinstance(payload, dict)
            and self._project_root
            and normalize_identity_path(str(payload.get("project_root") or ""))
            == normalize_identity_path(self._project_root)
        )

    def _request_targets_displayed_result(self, payload: dict) -> bool:
        return bool(
            self._request_targets_current_project(payload)
            and self._displayed_result_path
            and str(payload.get("result_path") or "")
            == self._displayed_result_path
            and self._view_model.current_result is not None
        )

    def _current_job(self):
        job_id = self._displayed_job_id
        if not job_id or not self._project_root:
            return None
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_SIMULATION_JOB_MANAGER

            manager = ServiceLocator.get_optional(SVC_SIMULATION_JOB_MANAGER)
            job = manager.query(job_id) if manager is not None else None
        except Exception:
            return None
        if job is None:
            return None
        if (
            normalize_identity_path(str(getattr(job, "project_root", "") or ""))
            != normalize_identity_path(self._project_root)
        ):
            return None
        return job

    def _payload_job_belongs_to_current_project(self, job_id: str) -> bool:
        return bool(job_id and job_id == self._displayed_job_id and self._current_job() is not None)

    def _can_cancel_current_job(self) -> bool:
        job = self._current_job()
        return bool(job is not None and not bool(getattr(job, "is_terminal", False)))

    def claim_ui_job(self, *, job_id: str, project_root: str, circuit_file: str) -> bool:
        """Claim the exact editor submission returned by the command controller.

        Lifecycle events are deliberately unable to establish ownership.  This
        synchronous submit-return hand-off means a queued job from an earlier
        project generation cannot steal the panel merely because the user later
        reopens the same filesystem path.
        """
        if (
            not job_id
            or not circuit_file
            or not self._project_root
            or normalize_identity_path(project_root)
            != normalize_identity_path(self._project_root)
        ):
            return False
        self._displayed_job_id = str(job_id)
        self._displayed_circuit_file = str(circuit_file)
        self._displayed_result_path = None
        self._backend_runtime.clear()
        self._view_model.mark_running()
        self._backend_runtime.export_panel.set_metrics([])
        self._panel_error_message = ""
        self._runtime_status_message = self._get_text(
            "simulation.running",
            "仿真进行中，请等待...",
        )
        self._set_active_frontend_tab("metrics")
        self._update_frontend_payloads(include_raw_data=True)
        return True
    
    def _on_project_opened(self, event_data: dict):
        """处理项目打开事件"""
        # 事件数据在 "data" 字段中
        data = event_data.get("data", event_data)
        self._project_root = data.get("path")
        self._backend_runtime.asc_conversion_panel.set_project_root(self._project_root or "")
        self._backend_runtime.export_panel.set_project_root(self._project_root or "")
        self._runtime_status_message = ""
        self._panel_error_message = ""
        self._logger.info(f"Project opened: {self._project_root}")
        self._refresh_circuit_result_index()

        # 清空当前显示
        self.clear()

        # The repository index is already refreshed synchronously above.
        # Delaying restore created a race where a newly-started job could be
        # replaced by historical data and lose its job identity.
        self._restore_project_result_after_project_opened()
    
    def _on_project_closed(self, event_data: dict):
        """处理项目关闭事件"""
        self._project_root = None
        self._backend_runtime.asc_conversion_panel.set_project_root("")
        self._backend_runtime.export_panel.set_project_root("")
        self._runtime_status_message = ""
        self._panel_error_message = ""
        self._refresh_circuit_result_index()
        self.clear()

    def _on_simulation_started(self, event_data: dict):
        """Refresh only the exact job already claimed at submit return."""
        payload = extract_sim_payload(EVENT_SIM_STARTED, event_data)
        if payload["origin"] != "ui_editor":
            return
        if (
            not self._payload_belongs_to_current_project(payload)
            or payload["job_id"] != self._displayed_job_id
            or normalize_identity_path(payload["circuit_file"])
            != normalize_identity_path(self._displayed_circuit_file or "")
        ):
            self._logger.info(
                "Ignoring unowned UI simulation start: job_id=%s project=%s",
                payload["job_id"],
                payload["project_root"],
            )
            return
        self._logger.info(
            f"Simulation started (UI): job_id={payload['job_id']} "
            f"circuit_file={payload['circuit_file']}"
        )
        # The manager has now transitioned PENDING -> RUNNING, so republish
        # derived controls such as can_cancel.  Ownership and result state are
        # intentionally left untouched.
        self._update_frontend_payloads(include_raw_data=True)

    def _on_simulation_complete(self, event_data: dict):
        """COMPLETE handler — only loads when ``job_id`` matches the
        currently displayed one.

        Why ``job_id`` and not ``origin``: by the time COMPLETE fires
        the originating UI-editor STARTED has already stamped its
        ``job_id`` on the triple, so identity comparison is exact and
        survives the (theoretical) corner case of two UI submissions
        racing through the bus before the first COMPLETE lands.

        ``result_path`` is the authoritative field from the payload;
        there is no scan-disk / ``get_latest`` fallback. A missing
        ``result_path`` is a producer bug surfaced by
        :func:`extract_sim_payload` at the very first line of the
        handler, not by silent loss of state here.
        """
        payload = extract_sim_payload(EVENT_SIM_COMPLETE, event_data)
        if not self._payload_belongs_to_current_project(payload):
            return
        # Refresh precedes the displayed-triple filter. Agent-origin
        # completions persist bundles too, and the
        # circuit-selection tab must reflect every completion regardless
        # of whether the triple will be mutated.
        self._refresh_circuit_result_index()
        job_id = payload["job_id"]
        if job_id != self._displayed_job_id:
            # Republish frontend state so circuit selection visibly
            # gains the new card update even when the displayed triple stays
            # put (agent-origin completions are the main use case).
            self._update_frontend_payloads()
            return
        self._logger.info(
            f"Simulation complete (mine): job_id={job_id} "
            f"result_path={payload['result_path']}"
        )
        self._runtime_status_message = ""
        self._panel_error_message = ""
        self._apply_completed_job(payload)

    def _on_language_changed(self, event_data: dict):
        """处理语言切换事件"""
        self.retranslate_ui()

    def _on_simulation_error(self, event_data: dict):
        """ERROR handler — only touches UI when ``job_id`` matches.

        Agent-origin errors are logged (at error level so they remain
        diagnosable) but must not overwrite the status message of a
        UI-displayed bundle: the user would see "failed" text while
        looking at an unrelated successful result.

        Refresh the result index unconditionally: failed runs may still
        persist a diagnostic bundle, and
        circuit selection must show them regardless of origin).
        The refresh precedes the ``job_id`` filter for the same reason
        as :meth:`_on_simulation_complete`.
        """
        payload = extract_sim_payload(EVENT_SIM_ERROR, event_data)
        if not self._payload_belongs_to_current_project(payload):
            return
        self._refresh_circuit_result_index()
        job_id = payload["job_id"]
        if job_id != self._displayed_job_id:
            # Republish so circuit selection reflects any newly-landed
            # failure bundle even though the triple stays put.
            self._update_frontend_payloads()
            return
        error_message = payload["error_message"]
        self._logger.error(
            f"Simulation error (mine): job_id={job_id} "
            f"cancelled={payload['cancelled']} message={error_message}"
        )
        self._displayed_job_id = None
        self._panel_error_message = ""
        if payload["cancelled"]:
            self._runtime_status_message = self._get_text(
                "simulation.cancelled",
                "Simulation cancelled.",
            )
            self._view_model.mark_cancelled()
        else:
            if self._load_error_result_bundle(payload, error_message):
                return
            self._runtime_status_message = ""
            self._view_model.mark_error(error_message)
        self._update_frontend_payloads()

    def _load_error_result_bundle(self, payload: dict, error_message: str) -> bool:
        """Load exact persisted diagnostics for a failed UI job, if present."""
        result_path = str(payload.get("result_path") or "")
        if not result_path or not self._project_root:
            return False
        try:
            loaded = simulation_result_repository.load(self._project_root, result_path)
        except Exception as exc:
            self._fail_current_result_load(
                f"{error_message}; persisted diagnostics could not be loaded: {exc}"
            )
            return True
        if not loaded.success or loaded.data is None:
            self._fail_current_result_load(
                f"{error_message}; persisted diagnostics could not be loaded: "
                f"{loaded.error_message or 'bundle is missing or damaged'}"
            )
            return True
        if bool(getattr(loaded.data, "success", False)):
            self._fail_current_result_load(
                f"{error_message}; error event referenced a successful result bundle"
            )
            return True
        self._displayed_result_path = result_path
        self._displayed_circuit_file = str(
            getattr(loaded.data, "file_path", "") or payload.get("circuit_file") or ""
        )
        self._render_result(
            loaded.data,
            activate_op_tab=False,
            error_message_override=error_message,
        )
        return True

    def _on_add_metrics_to_conversation_clicked(self):
        result = self._view_model.current_result
        if result is None:
            return
        try:
            self._conversation_attachment_coordinator.attach_metrics(
                self._project_root or "",
                self._displayed_result_path or "",
                self._view_model.metrics_list,
            )
        except Exception as exc:
            self._show_add_to_conversation_error(exc)

    def _on_add_chart_to_conversation_clicked(self):
        result = self._view_model.current_result
        if result is None:
            return
        try:
            self._conversation_attachment_coordinator.attach_chart_image(
                self._project_root or "",
                self._displayed_result_path or "",
            )
        except Exception as exc:
            self._show_add_to_conversation_error(exc)

    def _on_add_op_result_to_conversation_clicked(self):
        result = self._view_model.current_result
        if result is None:
            return
        try:
            self._conversation_attachment_coordinator.attach_op_result(
                self._project_root or "",
                self._displayed_result_path or "",
            )
        except Exception as exc:
            self._show_add_to_conversation_error(exc)

    def _on_add_waveform_to_conversation_clicked(self):
        result = self._view_model.current_result
        if result is None:
            return
        try:
            self._conversation_attachment_coordinator.attach_waveform_image(
                self._project_root or "",
                self._displayed_result_path or "",
            )
        except Exception as exc:
            self._show_add_to_conversation_error(exc)

    def _on_add_output_log_to_conversation_clicked(self):
        result = self._view_model.current_result
        if result is None:
            return
        try:
            self._conversation_attachment_coordinator.attach_output_log(
                self._project_root or "",
                self._displayed_result_path or "",
            )
        except Exception as exc:
            self._show_add_to_conversation_error(exc)
    
    def bind_web_bridge(self, bridge: Optional[SimulationWebBridge]):
        if bridge is None or bridge is self._bound_web_bridge:
            return
        self._bound_web_bridge = bridge
        bridge.activate_tab_requested.connect(self.activate_result_tab)
        bridge.load_result_by_path_requested.connect(self._on_load_result_by_path_requested)
        bridge.cancel_simulation_requested.connect(self._on_cancel_simulation_requested)
        bridge.schematic_value_update_requested.connect(self._on_schematic_value_update_requested)
        bridge.raw_data_viewport_requested.connect(self._on_raw_data_viewport_requested)
        bridge.raw_data_copy_requested.connect(self._on_raw_data_copy_requested)
        bridge.chart_series_visibility_toggled.connect(self._on_chart_series_visibility_toggled)
        bridge.clear_all_chart_series_requested.connect(self._on_chart_clear_all_requested)
        bridge.chart_measurement_enabled_changed.connect(self._on_chart_measurement_enabled_changed)
        bridge.chart_measurement_cursor_move_requested.connect(self._on_chart_measurement_cursor_move_requested)
        bridge.chart_measurement_point_enabled_changed.connect(self._on_chart_measurement_point_enabled_changed)
        bridge.chart_measurement_point_target_changed.connect(self._on_chart_measurement_point_target_changed)
        bridge.chart_measurement_point_move_requested.connect(self._on_chart_measurement_point_move_requested)
        bridge.chart_viewport_changed.connect(self._on_chart_viewport_changed)
        bridge.chart_viewport_reset_requested.connect(self._on_chart_viewport_reset_requested)
        bridge.signal_visibility_toggled.connect(self._on_waveform_signal_visibility_toggled)
        bridge.clear_all_signals_requested.connect(self._on_waveform_clear_all_requested)
        bridge.cursor_visibility_toggled.connect(self._on_waveform_cursor_visibility_toggled)
        bridge.cursor_move_requested.connect(self._on_waveform_cursor_move_requested)
        bridge.waveform_viewport_changed.connect(self._on_waveform_viewport_changed)
        bridge.waveform_viewport_reset_requested.connect(self._on_waveform_viewport_reset_requested)
        bridge.output_log_search_requested.connect(self._on_output_log_search_requested)
        bridge.output_log_filter_requested.connect(self._on_output_log_filter_requested)
        bridge.output_log_copy_requested.connect(self._on_output_log_copy_requested)
        bridge.export_type_selection_changed.connect(self._on_export_type_selection_changed)
        bridge.export_all_selection_requested.connect(self._on_export_all_selection_requested)
        bridge.export_directory_pick_requested.connect(self._on_export_directory_pick_requested)
        bridge.export_directory_clear_requested.connect(self._on_export_directory_clear_requested)
        bridge.export_requested.connect(self._on_export_requested)
        bridge.asc_conversion_pick_requested.connect(self._on_asc_conversion_pick_requested)
        bridge.add_to_conversation_requested.connect(self._on_bridge_add_to_conversation_requested)
        bridge.update_metric_targets_requested.connect(self._on_update_metric_targets_requested)

    def _on_schematic_value_update_requested(self, payload: dict):
        if not isinstance(payload, dict):
            return
        self._backend_runtime.spice_schematic_document.request_value_update(payload)

    def _on_update_metric_targets_requested(self, payload: dict):
        """Persist the metric-target table flushed by the frontend's
        \u786e\u8ba4\u4fee\u6539 button and immediately republish the frontend
        state so the sidebar shows the new targets without having to
        wait for another simulation run.

        The frontend sends a full replacement map for one circuit
        source file; ``MetricTargetService.set_targets_for_file``
        enforces the whole-file write semantic (empty values clear the
        entry; callers are free to submit empty strings to opt out of
        a target). Targets belong to project-scoped ``.circuit_ai`` state,
        not the immutable simulation result bundle. The ViewModel reinjects
        them into the current in-memory metric rows without rewriting
        ``result.json`` or adding derived files to its bundle.
        """
        if not isinstance(payload, dict):
            return
        if not self._request_targets_displayed_result(payload):
            self._set_metric_target_error(
                "The displayed result changed; reload it before saving targets"
            )
            return
        source_file_path = str(payload.get("source_file_path") or "")
        targets = payload.get("targets") or {}
        if not isinstance(targets, dict):
            return
        current_result = self._view_model.current_result
        current_source = str(getattr(current_result, "file_path", "") or "")
        allowed_metric_names = {metric.name for metric in self._view_model.metrics_list}
        if (
            current_result is None
            or not current_source
            or normalize_identity_path(source_file_path)
            != normalize_identity_path(current_source)
            or any(str(name) not in allowed_metric_names for name in targets)
        ):
            self._set_metric_target_error(
                "The displayed result changed; reload it before saving targets"
            )
            return
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_METRIC_TARGET_SERVICE

            service = ServiceLocator.get_optional(SVC_METRIC_TARGET_SERVICE)
            if service is None:
                raise RuntimeError("Metric target storage is unavailable")
            service.set_targets_for_file(source_file_path, targets)
        except Exception as exc:
            self._logger.warning(f"Failed to persist metric targets: {exc}")
            self._set_metric_target_error(str(exc))
            return
        self._panel_error_message = ""
        self._view_model.refresh_metric_targets()
        self._backend_runtime.export_panel.set_metrics(self._view_model.metrics_list)
        self._update_frontend_payloads()

    def _set_metric_target_error(self, reason: str) -> None:
        self._panel_error_message = self._get_text(
            "simulation.metric_targets_failed",
            "Could not save metric targets: {message}",
        ).format(message=str(reason or "unknown error"))
        self._update_frontend_payloads()

    def _on_raw_data_viewport_requested(self, payload: dict):
        if not isinstance(payload, dict):
            return
        self._update_authoritative_raw_data_viewport(
            dataset_id=str(payload.get("dataset_id") or ""),
            version=payload.get("version"),
            row_start=int(payload.get("row_start") or 0),
            row_end=int(payload.get("row_end") or 0),
            col_start=int(payload.get("col_start") or 0),
            col_end=int(payload.get("col_end") or 0),
        )

    def _on_raw_data_copy_requested(self, payload: dict):
        if not isinstance(payload, dict):
            return
        row_start = int(payload.get("row_start") or 0)
        row_end = int(payload.get("row_end") or 0)
        col_start = int(payload.get("col_start") or 0)
        col_end = int(payload.get("col_end") or 0)
        success = self._backend_runtime.raw_data_table.copy_range_to_clipboard(
            dataset_id=str(payload.get("dataset_id") or ""),
            version=payload.get("version"),
            row_start=row_start,
            row_end=row_end,
            col_start=col_start,
            col_end=col_end,
            include_headers=bool(payload.get("include_headers")),
        )
        self._emit_authoritative_raw_data_copy_result(
            dataset_id=str(payload.get("dataset_id") or ""),
            version=int(payload.get("version") or 0),
            success=success,
            row_count=max(0, row_end - row_start),
            col_count=max(0, col_end - col_start),
        )

    def _on_output_log_copy_requested(self):
        payload = self._backend_runtime.output_log_viewer.get_filtered_text()
        if not payload:
            return
        app = QApplication.instance()
        if app is None:
            return
        clipboard = app.clipboard()
        if clipboard is None:
            return
        clipboard.setText(payload)

    def _on_load_result_by_path_requested(self, payload: dict) -> None:
        if not self._request_targets_current_project(payload):
            self._logger.info(f"Ignoring stale result-card request: {payload!r}")
            return
        self.load_result_by_path(str(payload.get("result_path") or ""))

    def _on_cancel_simulation_requested(self, payload: dict):
        if not self._request_targets_current_project(payload):
            self._logger.info(f"Ignoring stale cancellation request: {payload!r}")
            return
        job_id = str(payload.get("job_id") or "")
        if job_id != self._displayed_job_id:
            self._logger.info("Ignoring cancellation for unowned job_id=%s", job_id)
            return
        if not job_id or not self._payload_job_belongs_to_current_project(job_id):
            self._panel_error_message = self._get_text(
                "simulation.cancel_failed",
                "The current simulation could not be cancelled because it is no longer running.",
            )
            self._update_frontend_payloads()
            return
        from shared.service_locator import ServiceLocator
        from shared.service_names import SVC_SIMULATION_JOB_MANAGER

        manager = ServiceLocator.get_optional(SVC_SIMULATION_JOB_MANAGER)
        if manager is None or not manager.request_cancel(job_id):
            self._panel_error_message = self._get_text(
                "simulation.cancel_failed",
                "The current simulation could not be cancelled because it is no longer running.",
            )
            self._update_frontend_payloads()
            return
        # request_cancel may synchronously publish the terminal SIM_ERROR for
        # a queued job. Its handler already owns the final CANCELLED state and
        # clears displayed_job_id; never overwrite that terminal transition
        # with CANCELLING after control returns here.
        job_after_request = self._current_job()
        if (
            self._displayed_job_id != job_id
            or job_after_request is None
            or bool(getattr(job_after_request, "is_terminal", False))
        ):
            return
        self._panel_error_message = ""
        self._runtime_status_message = self._get_text(
            "simulation.cancelling",
            "Cancellation requested. Waiting for the simulator to stop safely...",
        )
        self._view_model.mark_cancelling()
        self._update_frontend_payloads()

    def _on_chart_clear_all_requested(self):
        self._backend_runtime.chart_viewer.clear_all_series()
        self._update_frontend_payloads()

    def _on_chart_series_visibility_toggled(self, series_name: str, visible: bool):
        chart_viewer = self._backend_runtime.chart_viewer
        chart_viewer.set_series_visible(series_name, visible)
        if chart_viewer.is_measurement_point_enabled():
            self._sync_chart_measurement_point_target(chart_viewer)
        self._update_frontend_payloads()

    def _on_chart_measurement_enabled_changed(self, enabled: bool):
        self._backend_runtime.chart_viewer.set_measurement_enabled(enabled)
        self._update_frontend_payloads()

    def _on_chart_measurement_cursor_move_requested(self, cursor_id: str, position: float):
        self._backend_runtime.chart_viewer.set_measurement_cursor(cursor_id, position)
        self._update_frontend_payloads()

    def _on_chart_measurement_point_enabled_changed(self, enabled: bool):
        chart_viewer = self._backend_runtime.chart_viewer
        chart_viewer.set_measurement_point_enabled(enabled)
        if enabled:
            self._sync_chart_measurement_point_target(chart_viewer)
        self._update_frontend_payloads()

    def _on_chart_measurement_point_target_changed(self, target_id: str):
        chart_viewer = self._backend_runtime.chart_viewer
        chart_viewer.set_measurement_point_target(target_id)
        if chart_viewer.is_measurement_point_enabled():
            self._sync_chart_measurement_point_target(chart_viewer)
        self._update_frontend_payloads()

    def _on_chart_measurement_point_move_requested(self, position: float):
        self._backend_runtime.chart_viewer.set_measurement_point_position(position)
        self._update_frontend_payloads()

    def _sync_chart_measurement_point_target(self, chart_viewer):
        snapshot = chart_viewer.get_web_snapshot()
        available_series = snapshot.get("available_series", []) if isinstance(snapshot, dict) else []
        visible_target_ids = []
        for item in available_series:
            if not isinstance(item, dict) or not bool(item.get("visible")):
                continue
            target_id = str(item.get("group_key") or item.get("name") or "")
            if target_id and target_id not in visible_target_ids:
                visible_target_ids.append(target_id)
        if not visible_target_ids:
            if chart_viewer.measurement_point_target():
                chart_viewer.set_measurement_point_target("")
            return
        current_target = str(chart_viewer.measurement_point_target() or "")
        if current_target in visible_target_ids:
            return
        chart_viewer.set_measurement_point_target(visible_target_ids[0])

    def _on_chart_viewport_changed(self, viewport: dict):
        self._backend_runtime.chart_viewer.set_viewport(viewport)
        self._update_frontend_payloads()

    def _on_chart_viewport_reset_requested(self):
        self._backend_runtime.chart_viewer.reset_viewport()
        self._update_frontend_payloads()

    def _on_waveform_clear_all_requested(self):
        self._backend_runtime.waveform_widget.clear_displayed_signals()
        self._update_frontend_payloads()

    def _on_waveform_signal_visibility_toggled(self, signal_name: str, visible: bool):
        self._backend_runtime.waveform_widget.set_signal_visible(signal_name, visible)
        self._update_frontend_payloads()

    def _on_waveform_cursor_visibility_toggled(self, cursor_id: str, visible: bool):
        waveform_widget = self._backend_runtime.waveform_widget
        if cursor_id == "b":
            waveform_widget.set_cursor_b_visible(visible)
        else:
            waveform_widget.set_cursor_a_visible(visible)
        self._update_frontend_payloads()

    def _on_waveform_cursor_move_requested(self, cursor_id: str, position: float):
        waveform_widget = self._backend_runtime.waveform_widget
        if cursor_id == "b":
            waveform_widget.set_cursor_b(position)
        else:
            waveform_widget.set_cursor_a(position)
        self._update_frontend_payloads()

    def _on_waveform_viewport_changed(self, viewport: dict):
        self._backend_runtime.waveform_widget.set_viewport(viewport)
        self._update_frontend_payloads()

    def _on_waveform_viewport_reset_requested(self):
        self._backend_runtime.waveform_widget.reset_viewport()
        self._update_frontend_payloads()

    def _on_output_log_search_requested(self, keyword: str):
        self._backend_runtime.output_log_viewer.search(keyword)
        self._update_frontend_payloads()

    def _on_output_log_filter_requested(self, level: str):
        self._backend_runtime.output_log_viewer.filter_by_level(level)
        self._update_frontend_payloads()

    def _on_export_type_selection_changed(self, export_type: str, selected: bool):
        self._backend_runtime.export_panel.set_export_type_selected(export_type, selected)
        self._update_frontend_payloads()

    def _on_export_all_selection_requested(self, selected: bool):
        self._backend_runtime.export_panel.set_all_types_selected(selected)
        self._update_frontend_payloads()

    def _on_export_directory_pick_requested(self):
        changed = self._backend_runtime.export_panel.choose_export_directory()
        if changed:
            self._update_frontend_payloads()

    def _on_export_directory_clear_requested(self):
        self._backend_runtime.export_panel.clear_manual_export_directory()
        self._update_frontend_payloads()

    def _on_export_requested(self, payload: dict):
        if not self._request_targets_displayed_result(payload):
            self._logger.info(f"Ignoring stale export request: {payload!r}")
            return
        execution = self._backend_runtime.export_panel.export_selected()
        if execution is not None:
            self._update_frontend_payloads()

    def _on_asc_conversion_pick_requested(self):
        execution = self._backend_runtime.asc_conversion_panel.choose_files_and_convert()
        if execution is not None:
            self._update_frontend_payloads()

    def _on_bridge_add_to_conversation_requested(self, payload: dict):
        if not self._request_targets_displayed_result(payload):
            self._logger.info(
                f"Ignoring stale conversation attachment request: {payload!r}"
            )
            return
        normalized_target = str(payload.get("target") or "")
        if normalized_target == "chart":
            self._on_add_chart_to_conversation_clicked()
            return
        if normalized_target == "waveform":
            self._on_add_waveform_to_conversation_clicked()
            return
        if normalized_target == "output_log":
            self._on_add_output_log_to_conversation_clicked()
            return
        if normalized_target == "op_result":
            self._on_add_op_result_to_conversation_clicked()
            return
        if normalized_target == "metrics":
            self._on_add_metrics_to_conversation_clicked()
    
    def _render_result(
        self,
        result,
        *,
        activate_op_tab: bool,
        error_message_override: str = "",
    ) -> None:
        """Pure UI-injection step — populates the backend runtime from a
        loaded ``SimulationResult`` without touching the displayed
        triple.

        Every caller (``_apply_completed_job``, ``load_result_by_path``)
        is responsible for setting the triple *before* calling this
        function. Separating "decide what we're displaying" from
        "inject it into widgets" is what makes the two branches
        visually distinct while still sharing the widget-population
        logic.
        """
        self._backend_runtime.clear()
        self._view_model.load_result(result)
        if error_message_override and not bool(getattr(result, "success", False)):
            self._view_model.mark_error(error_message_override)
        self._backend_runtime.export_panel.set_metrics(self._view_model.metrics_list)
        self._backend_runtime.export_panel.set_result(result)
        self._panel_error_message = ""
        self._runtime_status_message = ""

        if getattr(result, 'success', False) and getattr(result, 'data', None) is not None:
            self._load_waveform_data(result)
            self._backend_runtime.raw_data_table.load_data(result)

        raw_output = getattr(result, 'raw_output', None)
        if raw_output:
            self._backend_runtime.output_log_viewer.load_log_from_text(raw_output)

        next_active_tab = self._active_frontend_tab
        if not getattr(result, 'success', False):
            next_active_tab = "output_log"
        elif activate_op_tab:
            analysis_type = str(getattr(result, 'analysis_type', '') or '').lower()
            if analysis_type == 'op' and getattr(result, 'success', False) and getattr(result, 'data', None) is not None:
                next_active_tab = "op_result"
        self._set_active_frontend_tab(next_active_tab)
        self._refresh_circuit_result_index()
        self._load_result_schematic(result)
        self._update_frontend_payloads(include_raw_data=True)

    def _load_result_schematic(self, result) -> bool:
        """Load a schematic only when it matches the simulated source bytes."""
        source_identity = str(result.file_path or "")
        source_digest = result.source_digest
        resolved_source = simulation_result_repository.resolve_circuit_path(
            self._project_root or "",
            source_identity,
        )
        if resolved_source is None:
            self._backend_runtime.spice_schematic_document.load_unavailable_source(
                source_identity,
                self._get_text(
                    "simulation.schematic.source_missing_historical",
                    "源电路文件在当前项目中不可用，历史结果原理图不可用。",
                ),
            )
            return False
        elif not source_digest:
            self._backend_runtime.spice_schematic_document.load_unavailable_source(
                source_identity,
                self._get_text(
                    "simulation.schematic.source_digest_missing",
                    "仿真结果缺少有效的源电路摘要，历史结果原理图不可用。",
                ),
            )
            return False
        else:
            return self._backend_runtime.spice_schematic_document.load_from_result_file(
                str(resolved_source),
                source_digest,
            )

    def _apply_completed_job(self, payload: dict) -> None:
        """Display-branch for "my UI-editor job just finished".

        Invariants by the time this is called:
          * ``payload["job_id"] == self._displayed_job_id`` — the
            synchronous submit-return hand-off already claimed the live job.
          * ``payload["result_path"]`` is non-empty (guaranteed by
            :func:`extract_sim_payload`).

        The triple is re-stamped here rather than only in STARTED
        because ``result_path`` is only known now; this is the single
        statement that "fills the hole" left open at start time.
        """
        if not self._project_root:
            return
        result_path = payload["result_path"]
        circuit_file = payload["circuit_file"]
        try:
            load_result = simulation_result_repository.load(self._project_root, result_path)
        except Exception as exc:
            self._logger.warning(
                f"Exception loading completed-job bundle {result_path}: {exc}"
            )
            self._fail_current_result_load(str(exc))
            return
        if not load_result.success or load_result.data is None:
            self._logger.warning(
                f"Failed to load completed-job bundle {result_path}: {load_result.error_message}"
            )
            self._fail_current_result_load(load_result.error_message or "result bundle is missing or damaged")
            return
        self._displayed_result_path = result_path
        self._displayed_circuit_file = circuit_file
        self._displayed_job_id = None
        self._render_result(load_result.data, activate_op_tab=True)

    def _fail_current_result_load(self, reason: str) -> None:
        self._displayed_job_id = None
        self._displayed_result_path = None
        self._displayed_circuit_file = None
        message = self._get_text(
            "simulation.result_load_failed",
            "Could not load simulation result: {message}",
        ).format(message=str(reason or "unknown error"))
        self._runtime_status_message = ""
        self._panel_error_message = message
        self._view_model.mark_error(message)
        self._update_frontend_payloads(include_raw_data=True)

    def _restore_project_result_after_project_opened(self):
        """Project-open restore — a convenience UX that replays "show
        the most recent persisted bundle" on open.

        Implemented **as a persisted-result load**, not as an event
        replay: the
        triple therefore ends with ``displayed_job_id is None``, which
        is the whole point. This means no subsequent SIM_COMPLETE can
        match against a stale "job id I had at project open" — the
        trio becomes inert until either the user runs a simulation or
        picks another circuit card.

        The most recent bundle is the first result of the first group;
        repository ordering makes that relationship authoritative. This
        method reads the cache populated synchronously by project-open and
        never issues a second disk scan (``clear`` does not reset the cache).
        """
        if not self._project_root:
            return
        if (
            self._displayed_job_id is not None
            or self._view_model.current_result is not None
            or self._displayed_result_path
        ):
            return
        groups = self._circuit_result_index_cache
        if not groups or not groups[0].results:
            return
        most_recent = groups[0].results[0]
        if not most_recent.result_path:
            return
        self.load_result_by_path(most_recent.result_path)

    def _load_waveform_data(self, result):
        """
        加载波形数据到各组件

        默认仅显示当前排序后的第一个可用信号。

        Args:
            result: SimulationResult 对象
        """
        if result is None:
            return

        data = getattr(result, 'data', None)
        if data is None:
            return

        signal_names = data.get_signal_names() if hasattr(data, 'get_signal_names') else []

        default_signal = None
        if signal_names:
            try:
                from domain.simulation.data.waveform_data_service import waveform_data_service
                resolved_signal_names = waveform_data_service.get_resolved_signal_names(result)
                default_signal = resolved_signal_names[0] if resolved_signal_names else None
            except Exception:
                default_signal = signal_names[0]

        if default_signal:
            self._backend_runtime.waveform_widget.load_waveform(result, default_signal)

        self._load_analysis_charts(result)

    def _load_analysis_charts(self, result):
        """
        根据仿真结果加载交互式分析图

        流程：
        1. 根据仿真结果识别分析类型
        2. 为当前分析自动生成对应交互式图表
        3. 直接基于仿真结果数据加载图表视图

        Args:
            result: SimulationResult 对象
        """
        if result is None or result.data is None:
            return

        try:
            self._backend_runtime.chart_viewer.load_result(result)

        except Exception as e:
            self._logger.warning(f"Interactive chart loading failed: {e}")
    
    def clear(self):
        """Reset live/persisted identity and wipe all result state."""
        self._displayed_job_id = None
        self._displayed_result_path = None
        self._displayed_circuit_file = None
        self._active_frontend_tab = "metrics"
        self._runtime_status_message = ""
        self._panel_error_message = ""
        self._backend_runtime.clear()
        self._view_model.clear()
        self._update_frontend_payloads(include_raw_data=True)

    def activate_result_tab(self, tab_id: str) -> bool:
        normalized_tab_id = self._normalize_frontend_tab_id(tab_id)
        available_tabs = self._authoritative_frontend_state.get("surface_tabs", {}).get(
            "available_tabs", []
        )
        if (
            not self._is_allowed_frontend_tab(normalized_tab_id)
            or normalized_tab_id not in available_tabs
        ):
            return False
        if normalized_tab_id == self._active_frontend_tab:
            return True
        self._active_frontend_tab = normalized_tab_id
        self._update_frontend_payloads()
        return True

    def load_result_by_path(self, result_path: str) -> bool:
        """Persisted-result load branch — the user (or project-open
        restore) explicitly asks to display a saved bundle.

        Semantics:
          * ``displayed_job_id`` is set to ``None``. A persisted-result
            load
            is not an "in-flight job", and pairing it with a job id
            would create a ghost match for whatever COMPLETE arrives
            next.
          * ``displayed_result_path`` / ``displayed_circuit_file``
            are populated from the freshly-loaded bundle. The circuit
            file comes from the persisted ``SimulationResult.file_path``
            rather than from a parallel cache so the triple stays
            self-consistent.

        Returns ``True`` iff the bundle was successfully loaded and
        rendered.
        """
        if self._displayed_job_id:
            self._logger.info(
                "Ignoring persisted-result load while a UI job is still owned"
            )
            return False
        if not self._project_root or not result_path:
            self._set_panel_error("No project or result path is available")
            return False
        try:
            load_result = simulation_result_repository.load(self._project_root, result_path)
        except Exception as exc:
            self._logger.warning(f"Exception loading result bundle {result_path}: {exc}")
            self._set_panel_error(str(exc))
            return False
        if not load_result.success or load_result.data is None:
            self._logger.warning(
                f"Failed to load result bundle {result_path}: {load_result.error_message}"
            )
            self._set_panel_error(load_result.error_message or "result bundle is missing or damaged")
            return False
        self._panel_error_message = ""
        self._displayed_job_id = None
        self._displayed_result_path = result_path
        self._displayed_circuit_file = str(getattr(load_result.data, "file_path", "") or "")
        self._render_result(load_result.data, activate_op_tab=False)
        return True

    def _set_panel_error(self, reason: str) -> None:
        self._panel_error_message = self._get_text(
            "simulation.result_load_failed",
            "Could not load simulation result: {message}",
        ).format(message=str(reason or "unknown error"))
        self._update_frontend_payloads()
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._backend_runtime.retranslate_ui()
        self._update_frontend_payloads()
    
    def _show_add_to_conversation_error(self, error: Exception):
        message = self._get_text(
            "simulation.add_to_conversation_failed",
            "添加至对话失败：{message}",
        ).format(message=str(error))
        QMessageBox.warning(
            self,
            self._get_text("dialog.warning.title", "警告"),
            message,
        )
    
    def _current_displayed_bundle_dir(self) -> Optional[str]:
        """Resolve the on-disk bundle directory of the currently displayed result.

        Delegates to :meth:`SimulationResultRepository.resolve_bundle_dir`,
        the single authority for ``result_path → bundle directory``. This
        keeps path containment and existence checks in the repository.

        The source of truth remains ``_displayed_result_path`` — the
        only answer to "what is the panel showing?". No
        :meth:`SimulationResultRepository.get_latest` scan, no
        parallel cache: attachments must read from exactly the bundle
        the user is looking at, regardless of which agent jobs
        finished after it.
        """
        bundle_dir = simulation_result_repository.resolve_bundle_dir(
            self._project_root or "",
            self._displayed_result_path or "",
        )
        if bundle_dir is None:
            return None
        return str(bundle_dir)

    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(key, default)
        except ImportError:
            return default
    
    # ============================================================
    # 生命周期
    # ============================================================
    
    def closeEvent(self, event):
        """处理关闭事件"""
        self._unsubscribe_events()
        if self._web_host is not None:
            self._web_host.cleanup()
        self._backend_runtime.clear()
        super().closeEvent(event)
    
# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SimulationTab",
]
