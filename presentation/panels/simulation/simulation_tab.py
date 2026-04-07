# SimulationTab - Simulation Results Tab
"""
仿真结果标签页

职责：
- 协调各子组件，管理仿真结果标签页整体布局
- 指标摘要面板显示指标网格和综合评分
- 图表查看面板显示图表查看器
- 显示迭代状态提示和运行中状态

设计原则：
- 使用 QWidget 作为基类
- 通过 SimulationViewModel 获取数据
- 订阅事件响应项目切换和仿真完成
- 支持国际化

被调用方：
- main_window.py
"""

import logging
from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QFrame,
    QLabel,
    QPushButton,
    QSizePolicy,
)

from presentation.panels.simulation.simulation_view_model import (
    SimulationViewModel,
    SimulationStatus,
    DisplayMetric,
)
from domain.simulation.service.simulation_result_repository import simulation_result_repository
from presentation.panels.simulation.simulation_tab_widgets import (
    SimulationResultTabView,
    SimulationStatusBanner,
)
from resources.theme import (
    COLOR_ACCENT,
    COLOR_ACCENT_LIGHT,
    COLOR_BG_PRIMARY,
    COLOR_TEXT_SECONDARY,
    FONT_SIZE_NORMAL,
    FONT_SIZE_SMALL,
    SPACING_SMALL,
    SPACING_NORMAL,
    BORDER_RADIUS_NORMAL,
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
        history_requested: 请求查看历史记录
    """
    
    history_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # ViewModel
        self._view_model = SimulationViewModel()
        
        # 项目状态
        self._project_root: Optional[str] = None
        self._last_loaded_result_path: Optional[str] = None
        self._last_shown_op_dialog_signature: str = ""
        
        # EventBus 引用
        self._event_bus = None
        self._subscriptions: List[tuple] = []
        
        # 初始化 UI
        self._setup_ui()
        self._apply_style()
        self._connect_signals()
        
        # 初始化 ViewModel
        self._view_model.initialize()
        
        # 订阅事件
        self._subscribe_events()
        
        # 初始化文本
        self.retranslate_ui()
    
    def _setup_ui(self):
        """初始化 UI 组件"""
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._chart_viewer_panel = SimulationResultTabView()
        self._metrics_panel_view = self._chart_viewer_panel.metrics_summary_panel
        main_layout.addWidget(self._chart_viewer_panel, 1)
        
        # 状态指示器
        self._status_indicator = SimulationStatusBanner()
        main_layout.addWidget(self._status_indicator)
        
        # 空状态提示
        self._empty_widget = QFrame()
        self._empty_widget.setObjectName("emptyWidget")
        empty_layout = QVBoxLayout(self._empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 空状态图标（使用 SVG）
        self._empty_icon = QLabel()
        self._empty_icon.setObjectName("emptyIcon")
        self._empty_icon.setFixedSize(48, 48)
        self._empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._load_empty_icon()
        empty_layout.addWidget(self._empty_icon, 0, Qt.AlignmentFlag.AlignCenter)
        
        self._empty_label = QLabel()
        self._empty_label.setObjectName("emptyLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._empty_label)
        
        self._empty_hint = QLabel()
        self._empty_hint.setObjectName("emptyHint")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._empty_hint)
        
        # 加载历史结果按钮
        self._load_history_btn = QPushButton()
        self._load_history_btn.setObjectName("loadHistoryBtn")
        self._load_history_btn.clicked.connect(self._on_load_history_clicked)
        empty_layout.addWidget(self._load_history_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        main_layout.addWidget(self._empty_widget)
        
        # 初始显示空状态
        self._show_empty_state()
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            SimulationTab {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #emptyWidget {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #emptyIcon {{
                margin-bottom: {SPACING_NORMAL}px;
            }}
            
            #emptyLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #emptyHint {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
                margin-top: {SPACING_SMALL}px;
            }}
            
            #loadHistoryBtn {{
                background-color: transparent;
                color: {COLOR_ACCENT};
                border: 1px solid {COLOR_ACCENT};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 8px 16px;
                font-size: {FONT_SIZE_NORMAL}px;
                margin-top: {SPACING_NORMAL}px;
            }}
            
            #loadHistoryBtn:hover {{
                background-color: {COLOR_ACCENT_LIGHT};
            }}
            
            #loadHistoryBtn:pressed {{
                background-color: {COLOR_ACCENT};
                color: white;
            }}
        """)
    
    def _connect_signals(self):
        """连接信号"""
        # ViewModel 属性变更
        self._view_model.property_changed.connect(self._on_property_changed)
        
        # 指标摘要面板
        self._metrics_panel_view.history_clicked.connect(self._on_history_clicked)
        self._metrics_panel_view.refresh_clicked.connect(self._on_refresh_clicked)
        
        # 指标卡片点击
        self._metrics_panel_view.metrics_panel.metric_clicked.connect(self._on_metric_clicked)
    
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
    
    # ============================================================
    # 事件处理
    # ============================================================
    
    def _on_property_changed(self, name: str, value):
        """处理 ViewModel 属性变更"""
        if name == "metrics_list":
            self._update_metrics(value)
        elif name == "overall_score":
            self._metrics_panel_view.set_overall_score(value)
            self._chart_viewer_panel.export_panel.set_overall_score(value)
        elif name == "simulation_status":
            self._update_status(value)
        elif name == "error_message":
            if value:
                self._show_error(value)
    
    def _on_project_opened(self, event_data: dict):
        """处理项目打开事件"""
        # 事件数据在 "data" 字段中
        data = event_data.get("data", event_data)
        self._project_root = data.get("path")
        self._logger.info(f"Project opened: {self._project_root}")
        
        # 清空当前显示
        self.clear()

        QTimer.singleShot(250, self._restore_project_result_after_project_opened)
    
    def _on_project_closed(self, event_data: dict):
        """处理项目关闭事件"""
        self._project_root = None
        self.clear()
        self._show_empty_state()
    
    def _on_simulation_complete(self, event_data: dict):
        """处理仿真完成事件"""
        # 事件数据在 "data" 字段中
        data = event_data.get("data", event_data)
        result_path = data.get("result_path")
        success = data.get("success", False)
        
        self._logger.info(f"Simulation complete: result_path={result_path}, success={success}")
        
        # 隐藏运行状态
        self._status_indicator.hide_status()
        self._set_controls_enabled(True)
        
        # 加载仿真结果
        loaded = False
        if result_path and self._project_root:
            loaded = self._load_simulation_result(result_path, show_op_dialog=True)
        elif not result_path:
            self._logger.warning("No result_path in event, trying to load latest result")
            loaded = self._load_project_simulation_result(show_op_dialog=True)

        if loaded and self._project_root:
            self._auto_export_current_result()

    def _on_language_changed(self, event_data: dict):
        """处理语言切换事件"""
        self.retranslate_ui()

    def _on_awaiting_confirmation(self, event_data: dict):
        """处理等待确认事件"""
        self._status_indicator.show_awaiting_confirmation()
    
    def _on_user_confirmed(self, event_data: dict):
        """处理用户确认事件"""
        self._status_indicator.hide_status()
    
    def _on_simulation_started(self, event_data: dict):
        """处理仿真开始事件"""
        # 事件数据在 "data" 字段中
        data = event_data.get("data", event_data)
        circuit_file = data.get("circuit_file", "")
        self._logger.info(f"Simulation started: {circuit_file}")
        self._status_indicator.show_running(
            self._get_text("simulation.running", "仿真进行中，请等待...")
        )
        self._set_controls_enabled(False)
    
    def _on_simulation_error(self, event_data: dict):
        """处理仿真错误事件"""
        # 事件数据在 "data" 字段中
        data = event_data.get("data", event_data)
        error_message = data.get("error_message", "")
        self._logger.error(f"Simulation error: {error_message}")
        self._status_indicator.hide_status()
        self._set_controls_enabled(True)

    def _on_history_clicked(self):
        """处理历史按钮点击"""
        self.history_requested.emit()
        self._show_history_dialog()
    
    def _on_refresh_clicked(self):
        """处理刷新按钮点击"""
        self._logger.info("Refresh button clicked")
        self.refresh()
    
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
    
    def _on_metric_clicked(self, metric_name: str):
        """处理指标卡片点击"""
        self._logger.debug(f"Metric clicked: {metric_name}")
        # 可以高亮对应的图表区域或显示详情
    
    def load_result(self, result, result_path: Optional[str] = None, show_op_dialog: bool = False):
        """
        加载仿真结果
        
        Args:
            result: SimulationResult 对象
        """
        if result_path:
            self._last_loaded_result_path = self._normalize_result_path(result_path)

        self._chart_viewer_panel.clear()
        self._view_model.load_result(result)
        self._chart_viewer_panel.analysis_info_panel.load_result(result)
        self._chart_viewer_panel.export_panel.set_result(result)
        
        # 显示时间戳
        timestamp = getattr(result, 'timestamp', None)
        if timestamp:
            self._metrics_panel_view.set_result_timestamp(timestamp)
        
        if getattr(result, 'success', False) and getattr(result, 'data', None) is not None:
            self._load_waveform_data(result)
            self._chart_viewer_panel.raw_data_table.load_data(result)

        raw_output = getattr(result, 'raw_output', None)
        if raw_output:
            self._chart_viewer_panel.output_log_viewer.load_log_from_text(raw_output)

        if getattr(result, 'success', False) or raw_output or getattr(result, 'error', None):
            self._hide_empty_state()

        if not getattr(result, 'success', False):
            self._chart_viewer_panel.switch_to_log()

        if show_op_dialog:
            self._maybe_show_op_result_dialog(result, result_path=result_path)

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
            self._chart_viewer_panel.waveform_widget.load_waveform(result, default_signal)

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
            self._chart_viewer_panel.chart_viewer.load_result(result)

        except Exception as e:
            self._logger.warning(f"Interactive chart loading failed: {e}")
    
    def clear(self):
        """清空所有显示"""
        self._last_loaded_result_path = None
        self._last_shown_op_dialog_signature = ""
        self._chart_viewer_panel.clear()
        self._view_model.clear()
        self._status_indicator.hide_status()
        self._show_empty_state()

    def refresh(self):
        """刷新显示"""
        if self._project_root:
            self._load_project_simulation_result()
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._chart_viewer_panel.retranslate_ui()
        self._status_indicator.retranslate_ui()
        
        # 空状态文本
        self._empty_label.setText(self._get_text(
            "simulation.no_results",
            "暂无仿真结果"
        ))
        self._empty_hint.setText(self._get_text(
            "simulation.run_hint",
            "运行仿真后，结果将显示在此处"
        ))
        
        # 加载历史按钮
        self._load_history_btn.setText(self._get_text(
            "simulation.load_history",
            "加载历史结果"
        ))
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _update_metrics(self, metrics_list: List[DisplayMetric]):
        """更新指标显示"""
        self._chart_viewer_panel.export_panel.set_metrics(metrics_list)
        if metrics_list:
            self._metrics_panel_view.update_metrics(metrics_list)
            self._hide_empty_state()
        else:
            self._metrics_panel_view.clear()
    
    def _update_status(self, status: SimulationStatus):
        """更新状态显示"""
        if status == SimulationStatus.RUNNING:
            self._status_indicator.show_running()
        elif status == SimulationStatus.COMPLETE:
            self._status_indicator.hide_status()
        elif status == SimulationStatus.ERROR:
            self._status_indicator.hide_status()
        elif status == SimulationStatus.CANCELLED:
            self._status_indicator.hide_status()
    
    def _show_error(self, message: str):
        """显示错误信息"""
        self._logger.error(f"Simulation error: {message}")
        # 可以在状态栏或对话框中显示错误
    
    def _show_empty_state(self):
        """显示空状态"""
        self._chart_viewer_panel.hide()
        self._empty_widget.show()
        self._metrics_panel_view.clear_result_timestamp()
        # 隐藏顶部信息栏
        self._metrics_panel_view.hide_header_bar()
        
        # 加载空状态图标
        self._load_empty_icon()
        
        # 更新空状态文本
        self._empty_label.setText(self._get_text(
            "simulation.no_results",
            "暂无仿真结果"
        ))
        self._empty_hint.setText(self._get_text(
            "simulation.run_hint",
            "运行仿真后，结果将显示在此处"
        ))
        
        # 显示加载历史按钮
        self._load_history_btn.show()
        self._load_history_btn.setText(self._get_text(
            "simulation.load_history",
            "加载历史结果"
        ))
    
    def _hide_empty_state(self):
        """隐藏空状态"""
        self._empty_widget.hide()
        self._chart_viewer_panel.show()
        # 显示顶部信息栏
        self._metrics_panel_view.show_header_bar()
    
    def _set_controls_enabled(self, enabled: bool):
        """设置控件启用状态"""
        self._metrics_panel_view.setEnabled(enabled)
        # 图表查看器保持可用（允许查看）
    
    def _load_project_simulation_result(self, show_op_dialog: bool = False) -> bool:
        """加载项目的仿真结果"""
        if not self._project_root:
            return False
        
        try:
            load_result = simulation_result_repository.get_latest(self._project_root)
            if load_result.success and load_result.data:
                self._last_loaded_result_path = self._normalize_result_path(load_result.file_path)
                self.load_result(load_result.data, load_result.file_path, show_op_dialog=show_op_dialog)
                self._logger.info(f"Loaded simulation result: {load_result.file_path}")
                return True
            else:
                self._logger.info(f"No simulation result found: {load_result.error_message}")
                self._show_empty_state()
                return False
                
        except Exception as e:
            self._logger.warning(f"Failed to load simulation result: {e}")
            self._show_empty_state()
            return False
    
    def _load_simulation_result(self, result_path: str, show_op_dialog: bool = False) -> bool:
        """加载指定的仿真结果"""
        if not self._project_root:
            return False
        
        try:
            load_result = simulation_result_repository.load(self._project_root, result_path)
            if load_result.success and load_result.data:
                # load_result.data 已经是 SimulationResult 对象
                self._last_loaded_result_path = self._normalize_result_path(result_path)
                self.load_result(load_result.data, result_path, show_op_dialog=show_op_dialog)
                return True
            else:
                self._logger.warning(f"Failed to load result: {load_result.error_message}")
                return False
                
        except Exception as e:
            self._logger.warning(f"Failed to load simulation result: {e}")
            return False

    def _auto_export_current_result(self):
        execution = self._chart_viewer_panel.export_panel.auto_export_to_project(self._project_root or "")
        if execution is None:
            return
        if execution.errors:
            self._logger.warning(
                "Project auto export completed with errors: root=%s, errors=%s",
                execution.export_root,
                execution.errors,
            )
            return
        self._logger.info(
            "Project auto export completed: root=%s, files=%s",
            execution.export_root,
            len(execution.exported_files),
        )

    def _maybe_show_op_result_dialog(self, result, result_path: Optional[str] = None):
        analysis_type = str(getattr(result, "analysis_type", "") or "").lower()
        if analysis_type != "op":
            return

        if not getattr(result, "success", False) or getattr(result, "data", None) is None:
            return

        normalized_result_path = self._normalize_result_path(result_path or "")
        signature = f"{normalized_result_path}|{getattr(result, 'timestamp', '')}"
        if signature == self._last_shown_op_dialog_signature:
            return

        try:
            from presentation.dialogs.op_result_dialog import OPResultDialog

            dialog = OPResultDialog(self)
            dialog.load_result(result)
            self._last_shown_op_dialog_signature = signature
            dialog.exec()
        except Exception as e:
            self._logger.warning(f"Failed to show OP result dialog: {e}")

    def _normalize_result_path(self, result_path: str) -> str:
        if not result_path:
            return ""
        return result_path.replace('\\', '/').lower()
    
    def _load_empty_icon(self):
        """加载空状态图标"""
        try:
            from PyQt6.QtGui import QPixmap
            from pathlib import Path
            
            icon_path = Path(__file__).parent.parent.parent / "resources" / "icons" / "simulation" / "chart-empty.svg"
            if icon_path.exists():
                pixmap = QPixmap(str(icon_path))
                if not pixmap.isNull():
                    self._empty_icon.setPixmap(pixmap.scaled(
                        48, 48,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    ))
        except Exception:
            pass
    
    def _on_load_history_clicked(self):
        """处理加载历史结果按钮点击"""
        self._logger.info("Load history button clicked")
        self._load_project_simulation_result()
    
    def _show_history_dialog(self):
        """显示迭代历史记录对话框"""
        try:
            from presentation.dialogs.iteration_history_dialog import IterationHistoryDialog
            
            if not self._project_root:
                self._logger.warning("No project root, cannot show history dialog")
                return
            
            dialog = IterationHistoryDialog(self)
            dialog.load_history(self._project_root)
            dialog.exec()
            
        except ImportError as e:
            self._logger.warning(f"Failed to import IterationHistoryDialog: {e}")
        except Exception as e:
            self._logger.warning(f"Failed to show history dialog: {e}")
    
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
