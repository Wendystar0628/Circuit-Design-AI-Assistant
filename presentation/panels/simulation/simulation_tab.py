# SimulationTab - Simulation Results Tab
"""
仿真结果标签页

职责：
- 作为仿真结果面板的权威协调器
- 将前端状态序列化并推送给 SimulationWebHost
- 维护隐藏 backend runtime 以承载图表、波形、原始数据、日志、导出等后端能力
- 响应项目/仿真事件并切换前端 peer tab 状态

设计原则：
- 使用 QWidget 作为基类
- 通过 SimulationViewModel 获取数据
- 订阅事件响应项目切换和仿真完成
- 可见主路径只保留 Web host，旧 Qt 结果组件只作为隐藏 backend surface 存活
- 支持国际化

被调用方：
- main_window.py
"""

import copy
import logging
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QSizePolicy,
    QMessageBox,
)

from presentation.panels.simulation.simulation_view_model import (
    SimulationViewModel,
    SimulationStatus,
    DisplayMetric,
)
from domain.simulation.service.simulation_result_repository import (
    CircuitResultGroup,
    SimulationResultSummary,
    simulation_result_repository,
)
from presentation.panels.simulation.simulation_backend_runtime import SimulationBackendRuntime
from presentation.panels.simulation.simulation_conversation_attachment_coordinator import SimulationConversationAttachmentCoordinator
from presentation.panels.simulation.simulation_frontend_state_serializer import SimulationFrontendStateSerializer
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
    EVENT_ITERATION_AWAITING_CONFIRMATION,
    EVENT_ITERATION_USER_CONFIRMED,
    EVENT_SIM_RESULT_FILE_CREATED,
)
from shared.sim_event_payload import extract_sim_payload


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
        # Displayed-result triple — the single authoritative answer
        # to "what is the panel currently showing?".
        #
        # Exactly three writers are permitted to touch this triple
        # (each in a clearly-named function, never ad-hoc):
        #
        #   (a) ``_on_simulation_started`` — only when the STARTED
        #       payload carries ``origin == ui_editor``. Writes
        #       ``job_id`` + ``circuit_file``; ``result_path`` stays
        #       ``None`` until the corresponding COMPLETE arrives.
        #   (b) ``load_history_result`` (entry for both user-picked
        #       history tabs *and* project-open restore). Writes
        #       ``result_path`` + ``circuit_file``; ``job_id`` is
        #       explicitly cleared to ``None`` — this is the
        #       historical-load branch and carries no live job.
        #   (c) ``clear`` — all three back to ``None``.
        #
        # Critically, ``_on_sim_result_file_created`` does **not** write
        # to these fields; that callback's sole job is to refresh the
        # history index so an agent-origin simulation shows up in the
        # history list without ever replacing what the user is
        # currently viewing.
        self._displayed_job_id: Optional[str] = None
        self._displayed_result_path: Optional[str] = None
        self._displayed_circuit_file: Optional[str] = None
        self._awaiting_confirmation = False
        self._active_frontend_tab = "metrics"
        self._runtime_status_message = ""
        self._state_serializer = SimulationFrontendStateSerializer()
        self._authoritative_frontend_state = self._state_serializer.serialize_main_state()
        self._authoritative_schematic_document = self._state_serializer.serialize_schematic_document()
        self._authoritative_schematic_write_result = self._state_serializer.serialize_schematic_write_result()
        self._authoritative_raw_data_document = self._state_serializer.serialize_raw_data_document()
        self._authoritative_raw_data_viewport = self._state_serializer.serialize_raw_data_viewport()
        self._raw_data_copy_sequence = 0
        self._authoritative_raw_data_copy_result = self._state_serializer.serialize_raw_data_copy_result()
        # Step 9 — single by-circuit aggregated history-index cache.
        # The shared data source feeding both the history-results tab
        # (via :meth:`_history_index_flat_view`) and any future
        # circuit-selection tab. Refreshed via one and only one
        # disk-scan entry point (``_refresh_history_index``) hooked to
        # the Step 9 trigger set: project open/close, SIM_COMPLETE,
        # SIM_ERROR, and the file-watcher fallback.
        self._history_index_cache: List[CircuitResultGroup] = []
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
        
        # 初始化 ViewModel
        self._view_model.initialize()
        
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
        # ViewModel 属性变更
        self._view_model.property_changed.connect(self._on_property_changed)
        self._backend_runtime.spice_schematic_document.schematic_document_changed.connect(
            self._on_runtime_schematic_document_changed
        )
        self._backend_runtime.spice_schematic_document.schematic_write_result_changed.connect(
            self._on_runtime_schematic_write_result_changed
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

    def get_authoritative_raw_data_document(self):
        return copy.deepcopy(self._authoritative_raw_data_document)

    def get_authoritative_raw_data_viewport(self):
        return copy.deepcopy(self._authoritative_raw_data_viewport)

    def get_authoritative_raw_data_copy_result(self):
        return copy.deepcopy(self._authoritative_raw_data_copy_result)

    def _normalize_frontend_tab_id(self, tab_id: str) -> str:
        return str(tab_id or "metrics")

    def _is_allowed_frontend_tab(self, tab_id: str) -> bool:
        return tab_id in {
            "metrics",
            "schematic",
            "chart",
            "waveform",
            "analysis_info",
            "raw_data",
            "output_log",
            "export",
            "history",
            "op_result",
        }

    def _set_active_frontend_tab(self, tab_id: str) -> bool:
        normalized_tab_id = self._normalize_frontend_tab_id(tab_id)
        if not self._is_allowed_frontend_tab(normalized_tab_id):
            return False
        self._active_frontend_tab = normalized_tab_id
        return True

    def _refresh_history_index(self) -> None:
        """Rebuild the by-circuit aggregated history index (Step 9).

        **The single disk-scan entry point** for the simulation panel:
        every other consumer — the history-results tab's flat view,
        any future circuit-selection tab, the project-open restore
        flow — reads from :attr:`_history_index_cache` instead of
        hitting the repository on its own. A grep in
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
            bundles also land on disk and belong in the history view)
          * :meth:`_on_sim_result_file_created` (fallback for manual
            drops into ``simulation_results/``)
          * :meth:`refresh_history_index` — the public entry point
            wired to the bottom-panel refresh button
          * :meth:`_render_result` — after an explicit
            ``load_history_result`` render, to catch any bundles
            persisted while the render was in flight

        Runs on the main thread; EventBus already marshals signals
        there, so no lock is taken.
        """
        if not self._project_root:
            self._history_index_cache = []
            return
        try:
            self._history_index_cache = simulation_result_repository.list_by_circuit(
                self._project_root
            )
        except Exception as exc:
            self._history_index_cache = []
            self._logger.warning(f"Failed to refresh simulation history index: {exc}")

    def _history_index_flat_view(self) -> List[SimulationResultSummary]:
        """Project the aggregated cache into the flat time-descending
        view consumed by the history-results tab.

        Equivalent to what ``simulation_result_repository.list`` used
        to return, but derived from :attr:`_history_index_cache` so
        only **one** scan ever hits disk per refresh cycle. Groups
        are already per-circuit-sorted newest-first by the repository,
        so flattening + global timestamp-descending sort yields the
        same ordering as the tier-2 flat browse.
        """
        flat: List[SimulationResultSummary] = []
        for group in self._history_index_cache:
            flat.extend(group.results)
        flat.sort(key=lambda summary: summary.timestamp, reverse=True)
        return flat

    def _build_frontend_runtime_snapshots(self):
        active_tab = self._normalize_frontend_tab_id(self._active_frontend_tab)
        current_result = self._view_model.current_result
        analysis_chart_snapshot = self._backend_runtime.chart_viewer.get_web_snapshot() if active_tab == "chart" else None
        waveform_snapshot = self._backend_runtime.waveform_widget.get_web_snapshot() if active_tab == "waveform" else None
        output_log_snapshot = None
        export_snapshot = self._backend_runtime.export_panel.get_web_snapshot()
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
        }
     
    def _build_authoritative_frontend_state(self):
        snapshot_payloads = self._build_frontend_runtime_snapshots()
        return self._state_serializer.serialize_main_state(
            project_root=self._project_root or "",
            active_tab=self._normalize_frontend_tab_id(self._active_frontend_tab),
            current_result=self._view_model.current_result,
            current_result_path=self._displayed_result_path or "",
            metrics=self._view_model.metrics_list,
            simulation_status=self._view_model.simulation_status,
            status_message=self._runtime_status_message,
            error_message=self._view_model.error_message,
            history_results=self._history_index_flat_view(),
            latest_project_export_root=self._current_displayed_bundle_dir() or "",
            awaiting_confirmation=self._awaiting_confirmation,
            analysis_chart_snapshot=snapshot_payloads["analysis_chart_snapshot"],
            waveform_snapshot=snapshot_payloads["waveform_snapshot"],
            output_log_snapshot=snapshot_payloads["output_log_snapshot"],
            export_snapshot=snapshot_payloads["export_snapshot"],
        )

    def _build_authoritative_raw_data_document(self):
        return self._state_serializer.serialize_raw_data_document(
            self._backend_runtime.raw_data_table.get_document_payload()
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
            (EVENT_ITERATION_AWAITING_CONFIRMATION, self._on_awaiting_confirmation),
            (EVENT_ITERATION_USER_CONFIRMED, self._on_user_confirmed),
            (EVENT_SIM_RESULT_FILE_CREATED, self._on_sim_result_file_created),
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
    
    def _on_property_changed(self, name: str, value):
        """处理 ViewModel 属性变更"""
        if name == "metrics_list":
            self._update_metrics(value)
        elif name == "simulation_status":
            self._update_status(value)
        elif name == "error_message":
            if value:
                self._show_error(value)
        self._update_frontend_payloads()
    
    def _on_project_opened(self, event_data: dict):
        """处理项目打开事件"""
        # 事件数据在 "data" 字段中
        data = event_data.get("data", event_data)
        self._project_root = data.get("path")
        self._awaiting_confirmation = False
        self._runtime_status_message = ""
        self._logger.info(f"Project opened: {self._project_root}")
        self._refresh_history_index()

        # 清空当前显示
        self.clear()

        QTimer.singleShot(250, self._restore_project_result_after_project_opened)
    
    def _on_project_closed(self, event_data: dict):
        """处理项目关闭事件"""
        self._project_root = None
        self._awaiting_confirmation = False
        self._runtime_status_message = ""
        self._refresh_history_index()
        self.clear()

    def _on_simulation_started(self, event_data: dict):
        """STARTED handler — UI-editor jobs claim the displayed triple.

        Identity routing rules (Step 7):
          * ``origin != ui_editor`` → ignore. Agent jobs run in the
            background; their progress must never replace what the user
            is currently looking at.
          * ``origin == ui_editor`` → take ownership of the triple by
            writing ``displayed_job_id`` and ``displayed_circuit_file``.
            ``displayed_result_path`` is reset to ``None`` because the
            job has not yet produced a bundle; the matching COMPLETE
            event will fill it.

        UX policy (single in-flight UI submission, enforced by
        :class:`SimulationCommandController`) means this handler can
        unconditionally overwrite the triple on a UI-editor STARTED:
        there is at most one such job at a time.
        """
        payload = extract_sim_payload(EVENT_SIM_STARTED, event_data)
        if payload["origin"] != "ui_editor":
            return
        job_id = payload["job_id"]
        self._displayed_job_id = job_id
        self._displayed_circuit_file = payload["circuit_file"]
        self._displayed_result_path = None
        self._logger.info(
            f"Simulation started (UI): job_id={job_id} "
            f"circuit_file={payload['circuit_file']}"
        )
        self._awaiting_confirmation = False
        self._runtime_status_message = self._get_text("simulation.running", "仿真进行中，请等待...")
        self._update_frontend_payloads()

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
        # Step 9: history-index refresh precedes the displayed-triple
        # filter. Agent-origin completions persist bundles too, and the
        # circuit-selection / history-results tabs must reflect every
        # completion regardless of whether the triple will be mutated.
        self._refresh_history_index()
        job_id = payload["job_id"]
        if job_id != self._displayed_job_id:
            # Republish frontend state so the history list visibly
            # gains the new row even when the displayed triple stays
            # put (agent-origin completions are the main use case).
            self._update_frontend_payloads()
            return
        self._logger.info(
            f"Simulation complete (mine): job_id={job_id} "
            f"result_path={payload['result_path']} success={payload['success']}"
        )
        self._awaiting_confirmation = False
        self._runtime_status_message = ""
        self._apply_completed_job(payload)

    def _on_language_changed(self, event_data: dict):
        """处理语言切换事件"""
        self.retranslate_ui()

    def _on_awaiting_confirmation(self, event_data: dict):
        """处理等待用户确认事件"""
        del event_data
        self._awaiting_confirmation = True
        self._runtime_status_message = self._get_text(
            "simulation.awaiting_confirmation",
            "迭代完成，请在对话面板中选择下一步操作"
        )
        self._update_frontend_payloads()

    def _on_user_confirmed(self, event_data: dict):
        """处理用户确认事件"""
        del event_data
        self._awaiting_confirmation = False
        self._runtime_status_message = ""
        self._update_frontend_payloads()

    def _on_simulation_error(self, event_data: dict):
        """ERROR handler — only touches UI when ``job_id`` matches.

        Agent-origin errors are logged (at error level so they remain
        diagnosable) but must not overwrite the status message of a
        UI-displayed bundle: the user would see "failed" text while
        looking at an unrelated successful result.

        Step 9: refresh the history index unconditionally — failed
        runs still persist a bundle when the producer opted to (and
        the tab's history list must show them regardless of origin).
        The refresh precedes the ``job_id`` filter for the same reason
        as :meth:`_on_simulation_complete`.
        """
        payload = extract_sim_payload(EVENT_SIM_ERROR, event_data)
        self._refresh_history_index()
        job_id = payload["job_id"]
        if job_id != self._displayed_job_id:
            # Republish so the history list reflects any newly-landed
            # failure bundle even though the triple stays put.
            self._update_frontend_payloads()
            return
        error_message = payload["error_message"]
        self._logger.error(
            f"Simulation error (mine): job_id={job_id} "
            f"cancelled={payload['cancelled']} message={error_message}"
        )
        self._awaiting_confirmation = False
        self._runtime_status_message = error_message
        self._update_frontend_payloads()

    def _on_add_metrics_to_conversation_clicked(self):
        result = self._view_model.current_result
        if result is None:
            return
        try:
            self._conversation_attachment_coordinator.attach_metrics(
                self._project_root or "",
                self._current_displayed_bundle_dir(),
                result,
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
                self._current_displayed_bundle_dir(),
                result,
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
                self._current_displayed_bundle_dir(),
                result,
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
                self._current_displayed_bundle_dir(),
                result,
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
                self._current_displayed_bundle_dir(),
                result,
            )
        except Exception as exc:
            self._show_add_to_conversation_error(exc)
    
    def _on_sim_result_file_created(self, event_data: dict):
        """File-watcher callback — refreshes the history index, nothing
        else.

        Before Step 7 this handler doubled as a "new result detected,
        swap displayed bundle" trigger. That behaviour is now
        architecturally forbidden: the displayed triple can only be
        rewritten by (a) a UI-editor-origin SIM_COMPLETE that matches
        ``displayed_job_id`` or (b) an explicit ``load_history_result``
        call. A stray file write — e.g. an agent-origin job finishing
        in the background — must appear in the history list but must
        **not** hijack the user's current view.
        """
        data = event_data.get("data", event_data)
        event_project_root = data.get("project_root", "")
        if self._project_root and event_project_root:
            if self._project_root != event_project_root:
                return
        self._logger.info(
            f"Sim result file created: {data.get('file_path', '')} (refreshing history index only)"
        )
        self._refresh_history_index()
        self._update_frontend_payloads()

    def bind_web_bridge(self, bridge: Optional[SimulationWebBridge]):
        if bridge is None or bridge is self._bound_web_bridge:
            return
        self._bound_web_bridge = bridge
        bridge.activate_tab_requested.connect(self.activate_result_tab)
        bridge.load_history_result_requested.connect(self.load_history_result)
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
        bridge.export_type_selection_changed.connect(self._on_export_type_selection_changed)
        bridge.export_all_selection_requested.connect(self._on_export_all_selection_requested)
        bridge.export_directory_pick_requested.connect(self._on_export_directory_pick_requested)
        bridge.export_directory_clear_requested.connect(self._on_export_directory_clear_requested)
        bridge.export_requested.connect(self._on_export_requested)
        bridge.add_to_conversation_requested.connect(self._on_bridge_add_to_conversation_requested)
        bridge.update_metric_targets_requested.connect(self._on_update_metric_targets_requested)
        bridge.text_clipboard_copy_requested.connect(self._on_text_clipboard_copy_requested)

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
        a target). After persistence we:
          1. Ask the ViewModel to reinject targets into the current
             ``metrics_list`` so already-loaded metrics pick up the new
             strings without re-running the simulation.
          2. Rewrite ``metrics/metrics.json`` inside the simulation's
             latest auto-export directory so the on-disk artifact
             stays in lock-step with the UI. Without this step the
             saved result would still carry stale (or missing) target
             strings after a user edit, breaking the "\u4fdd\u5b58\u7684\u7ed3\u679c
             \u5305\u542b\u6700\u65b0\u6307\u6807\u4e0e\u76ee\u6807" invariant.
        """
        if not isinstance(payload, dict):
            return
        source_file_path = str(payload.get("source_file_path") or "")
        targets = payload.get("targets") or {}
        if not isinstance(targets, dict):
            return
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_METRIC_TARGET_SERVICE

            service = ServiceLocator.get_optional(SVC_METRIC_TARGET_SERVICE)
            if service is None:
                return
            service.set_targets_for_file(source_file_path, targets)
        except Exception as exc:
            self._logger.warning(f"Failed to persist metric targets: {exc}")
            return
        self._view_model.refresh_metric_targets()
        self._refresh_metrics_artifact_on_disk()

    def _refresh_metrics_artifact_on_disk(self) -> None:
        """Re-export ``metrics/metrics.json`` into the simulation's
        latest auto-export directory using the ViewModel's current
        ``metrics_list`` (which already carries the freshly-confirmed
        targets). We intentionally only touch the ``metrics`` category
        so charts / waveforms / logs / raw data stay untouched, and we
        never create a new timestamp directory here \u2014 if there is no
        existing export root we silently return, because there is
        nothing for the agent to re-read yet.
        """
        result = self._view_model.current_result
        if result is None:
            return
        export_root_str = self._current_displayed_bundle_dir()
        if not export_root_str:
            return
        from domain.simulation.data.simulation_artifact_exporter import simulation_artifact_exporter

        export_root = Path(export_root_str)
        if not export_root.is_dir():
            return
        try:
            simulation_artifact_exporter.export_metrics(
                export_root,
                result,
                self._view_model.metrics_list,
            )
        except Exception as exc:
            self._logger.warning(f"Failed to refresh metrics artifact on disk: {exc}")

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

    def _on_text_clipboard_copy_requested(self, text: str):
        # Generic clipboard pipe used by any frontend "Copy" button
        # whose payload is already plain text (e.g. the output log
        # tab). Routed through QClipboard because the embedded
        # QtWebEngine cannot reliably write to the system clipboard
        # from JavaScript.
        payload = str(text or "")
        if not payload:
            return
        app = QApplication.instance()
        if app is None:
            return
        clipboard = app.clipboard()
        if clipboard is None:
            return
        clipboard.setText(payload)

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

    def _on_export_requested(self):
        execution = self._backend_runtime.export_panel.export_selected()
        if execution is not None:
            self._update_frontend_payloads()

    def _on_bridge_add_to_conversation_requested(self, target: str):
        normalized_target = str(target or "metrics")
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
        self._on_add_metrics_to_conversation_clicked()
    
    def _render_result(self, result, *, activate_op_tab: bool) -> None:
        """Pure UI-injection step — populates the backend runtime from a
        loaded ``SimulationResult`` without touching the displayed
        triple.

        Every caller (``_apply_completed_job``, ``load_history_result``)
        is responsible for setting the triple *before* calling this
        function. Separating "decide what we're displaying" from
        "inject it into widgets" is what makes the two branches
        visually distinct while still sharing the widget-population
        logic.
        """
        self._backend_runtime.clear()
        self._view_model.load_result(result)
        self._backend_runtime.analysis_info_panel.load_result(result)
        self._backend_runtime.export_panel.set_result(result)

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
        self._refresh_history_index()
        self._backend_runtime.spice_schematic_document.load_from_result_file(str(getattr(result, 'file_path', '') or ''))
        self._update_frontend_payloads(include_raw_data=True)

    def _apply_completed_job(self, payload: dict) -> None:
        """Display-branch for "my UI-editor job just finished".

        Invariants by the time this is called:
          * ``payload["job_id"] == self._displayed_job_id`` — the
            STARTED handler already claimed the triple.
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
            return
        if not load_result.success or load_result.data is None:
            self._logger.warning(
                f"Failed to load completed-job bundle {result_path}: {load_result.error_message}"
            )
            return
        self._displayed_result_path = result_path
        self._displayed_circuit_file = circuit_file
        # _displayed_job_id stays as-is (matched in caller).
        self._render_result(load_result.data, activate_op_tab=True)

    def _restore_project_result_after_project_opened(self):
        """Project-open restore — a convenience UX that replays "show
        the most recent historical bundle" on open.

        Implemented **as a history load**, not as an event replay: the
        triple therefore ends with ``displayed_job_id is None``, which
        is the whole point. This means no subsequent SIM_COMPLETE can
        match against a stale "job id I had at project open" — the
        trio becomes inert until either the user runs a simulation or
        picks another history entry.

        Step 8 pins the entry point to
        :meth:`SimulationResultRepository.list_by_circuit` — "first
        group's first result" — instead of the flat history list. The
        two are guaranteed equivalent by the repository (groups are
        sorted by their newest bundle), and routing through the
        aggregation API keeps ``get_latest`` off the UI path as
        required by the plan.

        Step 9: reads the already-populated :attr:`_history_index_cache`
        instead of issuing its own ``list_by_circuit`` call.
        :meth:`_on_project_opened` refreshes the index synchronously
        before scheduling this 250 ms restore, so the cache is
        guaranteed current by the time we get here (``clear`` does
        not reset the cache).
        """
        if not self._project_root:
            return
        if self._view_model.current_result is not None or self._displayed_result_path:
            return
        groups = self._history_index_cache
        if not groups or not groups[0].results:
            return
        most_recent = groups[0].results[0]
        if not most_recent.result_path:
            return
        self.load_history_result(most_recent.result_path)

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
        """Reset the displayed triple and wipe every widget-held result.

        ``clear`` is one of the three permitted triple-writers (see the
        ``__init__`` docstring). After this call the panel is in the
        same state as a freshly-constructed instance with no project
        ever opened.
        """
        self._displayed_job_id = None
        self._displayed_result_path = None
        self._displayed_circuit_file = None
        self._awaiting_confirmation = False
        self._active_frontend_tab = "metrics"
        self._runtime_status_message = ""
        self._backend_runtime.clear()
        self._view_model.clear()
        self._update_frontend_payloads(include_raw_data=True)

    def refresh_history_index(self) -> None:
        """Rebuild the history-results cache and republish frontend state.

        Replaces the pre-Step-7 ``reload_latest_result`` used by the
        bottom-panel refresh button. The old behaviour silently
        overwrote the displayed bundle with "whatever
        :meth:`SimulationResultRepository.get_latest` returns", which
        clashes with Step 7's invariant that the displayed triple is
        only mutated by STARTED/COMPLETE with a matching job id or by
        an explicit history load. Refresh, post-Step-7, therefore only
        re-scans the on-disk history index — newly-persisted bundles
        from agent jobs become visible in the history tab without
        hijacking the user's current view.
        """
        if not self._project_root:
            return
        self._refresh_history_index()
        self._update_frontend_payloads()

    def activate_result_tab(self, tab_id: str) -> bool:
        normalized_tab_id = self._normalize_frontend_tab_id(tab_id)
        if not self._is_allowed_frontend_tab(normalized_tab_id):
            return False
        if normalized_tab_id == self._active_frontend_tab:
            return True
        self._active_frontend_tab = normalized_tab_id
        self._update_frontend_payloads()
        return True

    def load_history_result(self, result_path: str) -> bool:
        """History-load branch — the user (or project-open restore)
        explicitly asks to display a historical bundle.

        Semantics:
          * ``displayed_job_id`` is set to ``None``. A history load
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
        if not self._project_root or not result_path:
            return False
        try:
            load_result = simulation_result_repository.load(self._project_root, result_path)
        except Exception as exc:
            self._logger.warning(f"Exception loading history bundle {result_path}: {exc}")
            return False
        if not load_result.success or load_result.data is None:
            self._logger.warning(
                f"Failed to load history bundle {result_path}: {load_result.error_message}"
            )
            return False
        self._displayed_job_id = None
        self._displayed_result_path = result_path
        self._displayed_circuit_file = str(getattr(load_result.data, "file_path", "") or "")
        self._render_result(load_result.data, activate_op_tab=False)
        return True
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._backend_runtime.retranslate_ui()
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _update_metrics(self, metrics_list: List[DisplayMetric]):
        """更新指标显示"""
        self._backend_runtime.export_panel.set_metrics(metrics_list)
    
    def _update_status(self, status: SimulationStatus):
        """更新状态显示"""
        del status
    
    def _show_error(self, message: str):
        """显示错误信息"""
        self._logger.error(f"Simulation error: {message}")
        # 可以在状态栏或对话框中显示错误

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

        Delegates to
        :meth:`SimulationResultRepository.resolve_bundle_dir` — the
        single authority for ``result_path → export_root`` post-Step-8.
        Attachment tooling and the metrics-refresh path both consume
        this method; by concentrating the resolution in the
        repository we ensure every disk hit uses the same parsing
        rules (POSIX normalisation, existence check) instead of each
        call site rolling its own :class:`Path` math.

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
        self._view_model.dispose()
        super().closeEvent(event)
    
    def showEvent(self, event):
        """处理显示事件"""
        super().showEvent(event)
        # 延迟刷新布局
        QTimer.singleShot(0, self._on_shown)
    
    def _on_shown(self):
        """显示后的处理"""
        # 仿真结果由项目打开和仿真事件驱动；显示阶段不主动恢复。
        pass


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SimulationTab",
]
