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
from typing import List, Optional

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
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
from domain.simulation.service.simulation_result_repository import simulation_result_repository
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


class SimulationTab(QWidget):
    """
    仿真结果标签页
    
    协调各子组件，管理仿真结果标签页整体布局。
    
    Signals:
        authoritative_frontend_state_changed: 权威前端状态更新
    """

    authoritative_frontend_state_changed = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # ViewModel
        self._view_model = SimulationViewModel()
        
        # 项目状态
        self._project_root: Optional[str] = None
        self._last_loaded_result_path: Optional[str] = None
        self._awaiting_confirmation = False
        self._active_frontend_tab = "metrics"
        self._runtime_status_message = ""
        self._state_serializer = SimulationFrontendStateSerializer()
        self._authoritative_frontend_state = self._state_serializer.serialize_main_state()
        self._history_results_cache: List[dict] = []
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
        self._update_authoritative_frontend_state()
    
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

    def get_authoritative_frontend_state(self):
        return copy.deepcopy(self._authoritative_frontend_state)

    def _normalize_frontend_tab_id(self, tab_id: str) -> str:
        return str(tab_id or "metrics")

    def _is_allowed_frontend_tab(self, tab_id: str) -> bool:
        return tab_id in {
            "metrics",
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

    def _refresh_history_results_cache(self) -> None:
        if not self._project_root:
            self._history_results_cache = []
            return
        try:
            self._history_results_cache = simulation_result_repository.list(self._project_root, limit=20)
        except Exception as exc:
            self._history_results_cache = []
            self._logger.warning(f"Failed to list simulation result history: {exc}")

    def _build_frontend_runtime_snapshots(self):
        active_tab = self._normalize_frontend_tab_id(self._active_frontend_tab)
        current_result = self._view_model.current_result
        analysis_chart_snapshot = self._backend_runtime.chart_viewer.get_web_snapshot() if active_tab == "chart" else None
        waveform_snapshot = self._backend_runtime.waveform_widget.get_web_snapshot() if active_tab == "waveform" else None
        raw_data_snapshot = None
        output_log_snapshot = None
        export_snapshot = self._backend_runtime.export_panel.get_web_snapshot()
        if current_result is not None:
            raw_data_snapshot = self._backend_runtime.raw_data_table.get_web_snapshot()
            if active_tab == "output_log":
                output_log_snapshot = self._backend_runtime.output_log_viewer.get_web_snapshot()
            else:
                output_log_snapshot = self._backend_runtime.output_log_viewer.get_web_snapshot(max_lines=0)
        return {
            "analysis_chart_snapshot": analysis_chart_snapshot,
            "waveform_snapshot": waveform_snapshot,
            "raw_data_snapshot": raw_data_snapshot,
            "output_log_snapshot": output_log_snapshot,
            "export_snapshot": export_snapshot,
        }
     
    def _build_authoritative_frontend_state(self):
        snapshot_payloads = self._build_frontend_runtime_snapshots()
        return self._state_serializer.serialize_main_state(
            project_root=self._project_root or "",
            active_tab=self._normalize_frontend_tab_id(self._active_frontend_tab),
            current_result=self._view_model.current_result,
            current_result_path=self._last_loaded_result_path or "",
            metrics=self._view_model.metrics_list,
            overall_score=self._view_model.overall_score,
            has_goals=self._view_model.has_goals,
            simulation_status=self._view_model.simulation_status,
            status_message=self._runtime_status_message,
            error_message=self._view_model.error_message,
            history_results=list(self._history_results_cache),
            latest_project_export_root=self._get_latest_project_export_root() or "",
            awaiting_confirmation=self._awaiting_confirmation,
            analysis_chart_snapshot=snapshot_payloads["analysis_chart_snapshot"],
            waveform_snapshot=snapshot_payloads["waveform_snapshot"],
            raw_data_snapshot=snapshot_payloads["raw_data_snapshot"],
            output_log_snapshot=snapshot_payloads["output_log_snapshot"],
            export_snapshot=snapshot_payloads["export_snapshot"],
        )

    def _update_authoritative_frontend_state(self):
        self._authoritative_frontend_state = self._build_authoritative_frontend_state()
        self.authoritative_frontend_state_changed.emit(copy.deepcopy(self._authoritative_frontend_state))

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
        elif name == "overall_score":
            self._backend_runtime.export_panel.set_overall_score(value)
        elif name == "simulation_status":
            self._update_status(value)
        elif name == "error_message":
            if value:
                self._show_error(value)
        self._update_authoritative_frontend_state()
    
    def _on_project_opened(self, event_data: dict):
        """处理项目打开事件"""
        # 事件数据在 "data" 字段中
        data = event_data.get("data", event_data)
        self._project_root = data.get("path")
        self._awaiting_confirmation = False
        self._runtime_status_message = ""
        self._logger.info(f"Project opened: {self._project_root}")
        self._refresh_history_results_cache()
         
        # 清空当前显示
        self.clear()

        QTimer.singleShot(250, self._restore_project_result_after_project_opened)
    
    def _on_project_closed(self, event_data: dict):
        """处理项目关闭事件"""
        self._project_root = None
        self._awaiting_confirmation = False
        self._runtime_status_message = ""
        self._refresh_history_results_cache()
        self.clear()

    def _on_simulation_started(self, event_data: dict):
        """处理仿真开始事件"""
        # 事件数据在 "data" 字段中
        data = event_data.get("data", event_data)
        circuit_file = data.get("circuit_file", "")
        self._logger.info(f"Simulation started: {circuit_file}")
        self._awaiting_confirmation = False
        self._runtime_status_message = self._get_text("simulation.running", "仿真进行中，请等待...")
        self._update_authoritative_frontend_state()
    
    def _on_simulation_complete(self, event_data: dict):
        """处理仿真完成事件"""
        # 事件数据在 "data" 字段中
        data = event_data.get("data", event_data)
        result_path = data.get("result_path")
        success = data.get("success", False)
        
        self._logger.info(f"Simulation complete: result_path={result_path}, success={success}")
        self._awaiting_confirmation = False
        self._runtime_status_message = ""
        loaded = False
        if result_path and self._project_root:
            loaded = self._load_simulation_result(result_path, activate_op_tab=True)
        elif not result_path:
            self._logger.warning("No result_path in event, trying to load latest result")
            loaded = self._load_project_simulation_result(activate_op_tab=True)

        if loaded and self._project_root:
            self._auto_export_current_result()
        self._update_authoritative_frontend_state()

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
        self._update_authoritative_frontend_state()

    def _on_user_confirmed(self, event_data: dict):
        """处理用户确认事件"""
        del event_data
        self._awaiting_confirmation = False
        self._runtime_status_message = ""
        self._update_authoritative_frontend_state()

    def _on_simulation_error(self, event_data: dict):
        """处理仿真错误事件"""
        # 事件数据在 "data" 字段中
        data = event_data.get("data", event_data)
        error_message = data.get("error_message", "")
        self._logger.error(f"Simulation error: {error_message}")
        self._awaiting_confirmation = False
        self._runtime_status_message = error_message
        self._update_authoritative_frontend_state()

    def _on_add_metrics_to_conversation_clicked(self):
        result = self._view_model.current_result
        if result is None:
            return
        try:
            self._conversation_attachment_coordinator.attach_metrics(
                self._project_root or "",
                self._get_latest_project_export_root(),
                result,
                self._view_model.metrics_list,
                self._view_model.overall_score,
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
                self._get_latest_project_export_root(),
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
                self._get_latest_project_export_root(),
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
                self._get_latest_project_export_root(),
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
                self._get_latest_project_export_root(),
                result,
            )
        except Exception as exc:
            self._show_add_to_conversation_error(exc)
    
    def _on_sim_result_file_created(self, event_data: dict):
        """
        处理仿真结果文件创建事件（文件监控触发）
        
        Args:
            event_data: 事件数据，包含 file_path 和 project_root
        """
        # 事件数据在 "data" 字段中
        data = event_data.get("data", event_data)
        file_path = data.get("file_path", "")
        event_project_root = data.get("project_root", "")
        
        # 检查是否为当前项目
        if self._project_root and event_project_root:
            if self._project_root != event_project_root:
                return
        
        self._logger.info(f"Sim result file created: {file_path}")
        
        # 检查是否需要重新加载
        if self._should_reload(file_path):
            self._load_simulation_result(file_path)
    
    def _should_reload(self, file_path: str) -> bool:
        """
        判断是否需要重新加载
        
        避免重复加载相同的结果文件
        
        Args:
            file_path: 结果文件路径
            
        Returns:
            bool: 是否需要重新加载
        """
        normalized_path = self._normalize_result_path(file_path)
        if not normalized_path:
            return False

        if normalized_path == self._last_loaded_result_path:
            return False
        return True

    def bind_web_bridge(self, bridge: Optional[SimulationWebBridge]):
        if bridge is None or bridge is self._bound_web_bridge:
            return
        self._bound_web_bridge = bridge
        bridge.activate_tab_requested.connect(self.activate_result_tab)
        bridge.load_history_result_requested.connect(self.load_history_result)
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

    def _on_chart_clear_all_requested(self):
        self._backend_runtime.chart_viewer.clear_all_series()
        self._update_authoritative_frontend_state()

    def _on_chart_series_visibility_toggled(self, series_name: str, visible: bool):
        chart_viewer = self._backend_runtime.chart_viewer
        chart_viewer.set_series_visible(series_name, visible)
        if chart_viewer.is_measurement_point_enabled():
            self._sync_chart_measurement_point_target(chart_viewer)
        self._update_authoritative_frontend_state()

    def _on_chart_measurement_enabled_changed(self, enabled: bool):
        self._backend_runtime.chart_viewer.set_measurement_enabled(enabled)
        self._update_authoritative_frontend_state()

    def _on_chart_measurement_cursor_move_requested(self, cursor_id: str, position: float):
        self._backend_runtime.chart_viewer.set_measurement_cursor(cursor_id, position)
        self._update_authoritative_frontend_state()

    def _on_chart_measurement_point_enabled_changed(self, enabled: bool):
        chart_viewer = self._backend_runtime.chart_viewer
        chart_viewer.set_measurement_point_enabled(enabled)
        if enabled:
            self._sync_chart_measurement_point_target(chart_viewer)
        self._update_authoritative_frontend_state()

    def _on_chart_measurement_point_target_changed(self, target_id: str):
        chart_viewer = self._backend_runtime.chart_viewer
        chart_viewer.set_measurement_point_target(target_id)
        if chart_viewer.is_measurement_point_enabled():
            self._sync_chart_measurement_point_target(chart_viewer)
        self._update_authoritative_frontend_state()

    def _on_chart_measurement_point_move_requested(self, position: float):
        self._backend_runtime.chart_viewer.set_measurement_point_position(position)
        self._update_authoritative_frontend_state()

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
        self._update_authoritative_frontend_state()

    def _on_chart_viewport_reset_requested(self):
        self._backend_runtime.chart_viewer.reset_viewport()
        self._update_authoritative_frontend_state()

    def _on_waveform_clear_all_requested(self):
        self._backend_runtime.waveform_widget.clear_displayed_signals()
        self._update_authoritative_frontend_state()

    def _on_waveform_signal_visibility_toggled(self, signal_name: str, visible: bool):
        self._backend_runtime.waveform_widget.set_signal_visible(signal_name, visible)
        self._update_authoritative_frontend_state()

    def _on_waveform_cursor_visibility_toggled(self, cursor_id: str, visible: bool):
        waveform_widget = self._backend_runtime.waveform_widget
        if cursor_id == "b":
            waveform_widget.set_cursor_b_visible(visible)
        else:
            waveform_widget.set_cursor_a_visible(visible)
        self._update_authoritative_frontend_state()

    def _on_waveform_cursor_move_requested(self, cursor_id: str, position: float):
        waveform_widget = self._backend_runtime.waveform_widget
        if cursor_id == "b":
            waveform_widget.set_cursor_b(position)
        else:
            waveform_widget.set_cursor_a(position)
        self._update_authoritative_frontend_state()

    def _on_waveform_viewport_changed(self, viewport: dict):
        self._backend_runtime.waveform_widget.set_viewport(viewport)
        self._update_authoritative_frontend_state()

    def _on_waveform_viewport_reset_requested(self):
        self._backend_runtime.waveform_widget.reset_viewport()
        self._update_authoritative_frontend_state()

    def _on_output_log_search_requested(self, keyword: str):
        self._backend_runtime.output_log_viewer.search(keyword)
        self._update_authoritative_frontend_state()

    def _on_output_log_filter_requested(self, level: str):
        self._backend_runtime.output_log_viewer.filter_by_level(level)
        self._update_authoritative_frontend_state()

    def _on_export_type_selection_changed(self, export_type: str, selected: bool):
        self._backend_runtime.export_panel.set_export_type_selected(export_type, selected)
        self._update_authoritative_frontend_state()

    def _on_export_all_selection_requested(self, selected: bool):
        self._backend_runtime.export_panel.set_all_types_selected(selected)
        self._update_authoritative_frontend_state()

    def _on_export_directory_pick_requested(self):
        changed = self._backend_runtime.export_panel.choose_export_directory()
        if changed:
            self._update_authoritative_frontend_state()

    def _on_export_directory_clear_requested(self):
        self._backend_runtime.export_panel.clear_manual_export_directory()
        self._update_authoritative_frontend_state()

    def _on_export_requested(self):
        execution = self._backend_runtime.export_panel.export_selected()
        if execution is not None:
            self._update_authoritative_frontend_state()

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
    
    def load_result(self, result, result_path: Optional[str] = None, activate_op_tab: bool = False):
        """
        加载仿真结果
        
        Args:
            result: SimulationResult 对象
        """
        if result_path:
            self._last_loaded_result_path = self._normalize_result_path(result_path)

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
        self._refresh_history_results_cache()
        self._update_authoritative_frontend_state()

    def _restore_project_result_after_project_opened(self):
        if not self._project_root:
            return

        if self._view_model.current_result is not None or self._last_loaded_result_path:
            return

        self._load_project_simulation_result()

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
        """清空所有显示"""
        self._last_loaded_result_path = None
        self._awaiting_confirmation = False
        self._active_frontend_tab = "metrics"
        self._runtime_status_message = ""
        self._backend_runtime.clear()
        self._view_model.clear()
        self._update_authoritative_frontend_state()

    def reload_latest_result(self):
        """刷新显示"""
        if self._project_root:
            self._load_project_simulation_result()

    def activate_result_tab(self, tab_id: str) -> bool:
        normalized_tab_id = self._normalize_frontend_tab_id(tab_id)
        if not self._is_allowed_frontend_tab(normalized_tab_id):
            return False
        if normalized_tab_id == self._active_frontend_tab:
            return True
        self._active_frontend_tab = normalized_tab_id
        self._update_authoritative_frontend_state()
        return True

    def load_history_result(self, result_path: str) -> bool:
        return self._load_simulation_result(result_path, activate_op_tab=False)
    
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
    
    def _load_project_simulation_result(self, activate_op_tab: bool = False) -> bool:
        """加载项目的仿真结果"""
        if not self._project_root:
            return False
        
        try:
            load_result = simulation_result_repository.get_latest(self._project_root)
            if load_result.success and load_result.data:
                self._last_loaded_result_path = self._normalize_result_path(load_result.file_path)
                self.load_result(load_result.data, load_result.file_path, activate_op_tab=activate_op_tab)
                self._logger.info(f"Loaded simulation result: {load_result.file_path}")
                return True
            else:
                self._logger.info(f"No simulation result found: {load_result.error_message}")
                self.clear()
                return False
                
        except Exception as e:
            self._logger.warning(f"Failed to load simulation result: {e}")
            self.clear()
            return False
    
    def _load_simulation_result(self, result_path: str, activate_op_tab: bool = False) -> bool:
        """加载指定的仿真结果"""
        if not self._project_root:
            return False
        
        try:
            load_result = simulation_result_repository.load(self._project_root, result_path)
            if load_result.success and load_result.data:
                # load_result.data 已经是 SimulationResult 对象
                self._last_loaded_result_path = self._normalize_result_path(result_path)
                self.load_result(load_result.data, result_path, activate_op_tab=activate_op_tab)
                return True
            else:
                self._logger.warning(f"Failed to load result: {load_result.error_message}")
                return False
                
        except Exception as e:
            self._logger.warning(f"Failed to load simulation result: {e}")
            return False

    def _auto_export_current_result(self):
        execution = self._backend_runtime.export_panel.auto_export_to_project(self._project_root or "")
        if execution is None:
            return
        if execution.errors:
            self._logger.warning(
                "Project auto export completed with errors: root=%s, errors=%s",
                execution.export_root,
                execution.errors,
            )
            self._update_authoritative_frontend_state()
            return
        self._logger.info(
            "Project auto export completed: root=%s, files=%s",
            execution.export_root,
            len(execution.exported_files),
        )
        self._update_authoritative_frontend_state()

    def _get_latest_project_export_root(self) -> Optional[str]:
        export_root = self._backend_runtime.export_panel.latest_project_export_root
        if export_root is None:
            return None
        return str(export_root)

    def _normalize_result_path(self, result_path: str) -> str:
        if not result_path:
            return ""
        return result_path.replace('\\', '/').lower()
    
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
