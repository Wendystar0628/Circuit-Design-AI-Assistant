# SimulationTab - Simulation Results Tab
"""
仿真结果标签页

职责：
- 协调各子组件，管理仿真结果标签页整体布局
- 左栏显示指标网格和综合评分
- 右栏显示图表查看器
- 显示迭代状态提示和运行中状态

设计原则：
- 使用 QWidget 作为基类
- 通过 SimulationViewModel 获取数据
- 订阅事件响应项目切换和仿真完成
- 支持国际化

被调用方：
- bottom_panel.py
- main_window.py
"""

import logging
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QFrame,
    QLabel,
    QPushButton,
    QProgressBar,
    QSizePolicy,
)

from presentation.panels.simulation.simulation_view_model import (
    SimulationViewModel,
    SimulationStatus,
    DisplayMetric,
)
from presentation.panels.simulation.metrics_panel import MetricsPanel
from presentation.panels.simulation.chart_viewer import ChartViewer
from domain.simulation.service.simulation_result_watcher import (
    SimulationResultWatcher,
)
from resources.theme import (
    COLOR_BG_PRIMARY,
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_ACCENT,
    COLOR_ACCENT_LIGHT,
    COLOR_BORDER,
    COLOR_WARNING,
    COLOR_WARNING_LIGHT,
    FONT_SIZE_NORMAL,
    FONT_SIZE_SMALL,
    SPACING_SMALL,
    SPACING_NORMAL,
    SPACING_LARGE,
    BORDER_RADIUS_NORMAL,
)
from shared.event_types import (
    EVENT_STATE_PROJECT_OPENED,
    EVENT_STATE_PROJECT_CLOSED,
    EVENT_SIM_COMPLETE,
    EVENT_ALL_ANALYSES_COMPLETE,
    EVENT_LANGUAGE_CHANGED,
    EVENT_ITERATION_AWAITING_CONFIRMATION,
    EVENT_ITERATION_USER_CONFIRMED,
    EVENT_WORKFLOW_LOCKED,
    EVENT_WORKFLOW_UNLOCKED,
    EVENT_SIM_RESULT_FILE_CREATED,
    EVENT_SESSION_CHANGED,
)


# ============================================================
# 样式常量
# ============================================================

PANEL_BG_COLOR = "#f8f9fa"
LEFT_PANEL_MIN_WIDTH = 280
RIGHT_PANEL_MIN_WIDTH = 400
STATUS_BAR_HEIGHT = 48


class StatusIndicator(QFrame):
    """
    状态指示器
    
    显示迭代等待确认或运行中状态
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("statusIndicator")
        self.setFixedHeight(STATUS_BAR_HEIGHT)
        
        self._setup_ui()
        self._apply_style()
        
        # 默认隐藏
        self.hide()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        layout.setSpacing(SPACING_NORMAL)
        
        # 状态图标
        self._icon_label = QLabel()
        self._icon_label.setObjectName("statusIcon")
        self._icon_label.setFixedSize(24, 24)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon_label)
        
        # 状态文本
        self._text_label = QLabel()
        self._text_label.setObjectName("statusText")
        layout.addWidget(self._text_label, 1)
        
        # 进度条（运行中显示）
        self._progress_bar = QProgressBar()
        self._progress_bar.setObjectName("statusProgress")
        self._progress_bar.setFixedWidth(120)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, 0)  # 不确定进度
        self._progress_bar.hide()
        layout.addWidget(self._progress_bar)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #statusIndicator {{
                background-color: {COLOR_WARNING_LIGHT};
                border-top: 1px solid {COLOR_BORDER};
            }}
            
            #statusIcon {{
                font-size: 16px;
            }}
            
            #statusText {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #statusProgress {{
                background-color: #e0e0e0;
                border: none;
                border-radius: 3px;
            }}
            
            #statusProgress::chunk {{
                background-color: {COLOR_ACCENT};
                border-radius: 3px;
            }}
        """)
    
    def show_awaiting_confirmation(self):
        """显示等待确认状态"""
        self._icon_label.setText("⏸")
        self._text_label.setText(self._get_text(
            "simulation.awaiting_confirmation",
            "迭代完成，请在对话面板中选择下一步操作"
        ))
        self._progress_bar.hide()
        self.show()
    
    def show_running(self, message: str = ""):
        """显示运行中状态"""
        self._icon_label.setText("⏳")
        text = message or self._get_text(
            "simulation.running",
            "优化进行中，请等待本轮完成..."
        )
        self._text_label.setText(text)
        self._progress_bar.show()
        self.show()
    
    def hide_status(self):
        """隐藏状态指示器"""
        self.hide()
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(key, default)
        except ImportError:
            return default
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        # 状态文本在显示时动态设置，此处无需处理
        pass


class LeftPanel(QFrame):
    """
    左侧面板
    
    包含指标网格、综合评分和历史/刷新按钮
    """
    
    history_clicked = pyqtSignal()
    refresh_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("leftPanel")
        self.setMinimumWidth(LEFT_PANEL_MIN_WIDTH)
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 指标面板
        self._metrics_panel = MetricsPanel()
        layout.addWidget(self._metrics_panel, 1)
        
        # 底部操作栏
        bottom_bar = QFrame()
        bottom_bar.setObjectName("bottomBar")
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        bottom_layout.setSpacing(SPACING_NORMAL)
        
        # 刷新按钮
        self._refresh_btn = QPushButton()
        self._refresh_btn.setObjectName("refreshBtn")
        self._refresh_btn.clicked.connect(self.refresh_clicked.emit)
        bottom_layout.addWidget(self._refresh_btn)
        
        # 查看历史按钮
        self._history_btn = QPushButton()
        self._history_btn.setObjectName("historyBtn")
        self._history_btn.clicked.connect(self.history_clicked.emit)
        bottom_layout.addWidget(self._history_btn)
        
        bottom_layout.addStretch()
        
        layout.addWidget(bottom_bar)
        
        # 初始化文本
        self.retranslate_ui()
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #leftPanel {{
                background-color: {PANEL_BG_COLOR};
                border-right: 1px solid {COLOR_BORDER};
            }}
            
            #bottomBar {{
                background-color: {COLOR_BG_TERTIARY};
                border-top: 1px solid {COLOR_BORDER};
            }}
            
            #historyBtn, #refreshBtn {{
                background-color: transparent;
                color: {COLOR_ACCENT};
                border: 1px solid {COLOR_ACCENT};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 6px 12px;
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #historyBtn:hover, #refreshBtn:hover {{
                background-color: {COLOR_ACCENT_LIGHT};
            }}
            
            #historyBtn:pressed, #refreshBtn:pressed {{
                background-color: {COLOR_ACCENT};
                color: white;
            }}
        """)
    
    @property
    def metrics_panel(self) -> MetricsPanel:
        """获取指标面板"""
        return self._metrics_panel
    
    def update_metrics(self, metrics_list: List[DisplayMetric]):
        """更新指标显示"""
        self._metrics_panel.update_metrics(metrics_list)
    
    def set_overall_score(self, score: float):
        """设置综合评分"""
        self._metrics_panel.set_overall_score(score)
    
    def clear(self):
        """清空显示"""
        self._metrics_panel.clear()
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._refresh_btn.setText(self._get_text(
            "simulation.refresh",
            "刷新"
        ))
        self._history_btn.setText(self._get_text(
            "simulation.view_history",
            "查看历史"
        ))
        self._metrics_panel.retranslate_ui()
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(key, default)
        except ImportError:
            return default


class RightPanel(QFrame):
    """
    右侧面板
    
    包含图表查看器
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("rightPanel")
        self.setMinimumWidth(RIGHT_PANEL_MIN_WIDTH)
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 图表查看器
        self._chart_viewer = ChartViewer()
        layout.addWidget(self._chart_viewer)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #rightPanel {{
                background-color: {COLOR_BG_PRIMARY};
            }}
        """)
    
    @property
    def chart_viewer(self) -> ChartViewer:
        """获取图表查看器"""
        return self._chart_viewer
    
    def load_chart(self, chart_path: str, chart_type: Optional[str] = None):
        """加载图表"""
        self._chart_viewer.load_chart(chart_path, chart_type)
    
    def load_charts(self, chart_paths: Dict[str, str]):
        """批量加载图表"""
        self._chart_viewer.load_charts(chart_paths)
    
    def clear(self):
        """清空图表"""
        self._chart_viewer.clear()
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._chart_viewer.retranslate_ui()



class SimulationTab(QWidget):
    """
    仿真结果标签页
    
    协调各子组件，管理仿真结果标签页整体布局。
    
    Signals:
        history_requested: 请求查看历史记录
        settings_requested: 请求打开仿真设置
    """
    
    history_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # ViewModel
        self._view_model = SimulationViewModel()
        
        # 项目状态
        self._project_root: Optional[str] = None
        self._is_workflow_running: bool = False
        
        # 仿真结果文件监控器
        self._result_watcher = SimulationResultWatcher()
        
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
        
        # 主内容区（左右分栏）
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setObjectName("mainSplitter")
        self._splitter.setHandleWidth(1)
        self._splitter.setChildrenCollapsible(False)
        
        # 左侧面板
        self._left_panel = LeftPanel()
        self._splitter.addWidget(self._left_panel)
        
        # 右侧面板
        self._right_panel = RightPanel()
        self._splitter.addWidget(self._right_panel)
        
        # 设置初始比例（40:60）
        self._splitter.setSizes([400, 600])
        
        main_layout.addWidget(self._splitter, 1)
        
        # 状态指示器
        self._status_indicator = StatusIndicator()
        main_layout.addWidget(self._status_indicator)
        
        # 空状态提示
        self._empty_widget = QFrame()
        self._empty_widget.setObjectName("emptyWidget")
        empty_layout = QVBoxLayout(self._empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self._empty_icon = QLabel("📊")
        self._empty_icon.setObjectName("emptyIcon")
        self._empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._empty_icon)
        
        self._empty_label = QLabel()
        self._empty_label.setObjectName("emptyLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._empty_label)
        
        self._empty_hint = QLabel()
        self._empty_hint.setObjectName("emptyHint")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._empty_hint)
        
        main_layout.addWidget(self._empty_widget)
        
        # 初始显示空状态
        self._show_empty_state()
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            SimulationTab {{
                background-color: {PANEL_BG_COLOR};
            }}
            
            #mainSplitter {{
                background-color: {PANEL_BG_COLOR};
            }}
            
            #mainSplitter::handle {{
                background-color: {COLOR_BORDER};
            }}
            
            #emptyWidget {{
                background-color: {PANEL_BG_COLOR};
            }}
            
            #emptyIcon {{
                font-size: 48px;
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
        """)
    
    def _connect_signals(self):
        """连接信号"""
        # ViewModel 属性变更
        self._view_model.property_changed.connect(self._on_property_changed)
        
        # 左侧面板
        self._left_panel.history_clicked.connect(self._on_history_clicked)
        self._left_panel.refresh_clicked.connect(self._on_refresh_clicked)
        
        # 指标卡片点击
        self._left_panel.metrics_panel.metric_clicked.connect(self._on_metric_clicked)
    
    def _subscribe_events(self):
        """订阅事件"""
        event_bus = self._get_event_bus()
        if not event_bus:
            return
        
        subscriptions = [
            (EVENT_STATE_PROJECT_OPENED, self._on_project_opened),
            (EVENT_STATE_PROJECT_CLOSED, self._on_project_closed),
            (EVENT_SIM_COMPLETE, self._on_simulation_complete),
            (EVENT_ALL_ANALYSES_COMPLETE, self._on_all_analyses_complete),
            (EVENT_LANGUAGE_CHANGED, self._on_language_changed),
            (EVENT_ITERATION_AWAITING_CONFIRMATION, self._on_awaiting_confirmation),
            (EVENT_ITERATION_USER_CONFIRMED, self._on_user_confirmed),
            (EVENT_WORKFLOW_LOCKED, self._on_workflow_locked),
            (EVENT_WORKFLOW_UNLOCKED, self._on_workflow_unlocked),
            (EVENT_SIM_RESULT_FILE_CREATED, self._on_sim_result_file_created),
            (EVENT_SESSION_CHANGED, self._on_session_changed),
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
            self._left_panel.set_overall_score(value)
        elif name == "simulation_status":
            self._update_status(value)
        elif name == "chart_paths":
            self._update_charts(value)
        elif name == "error_message":
            if value:
                self._show_error(value)
    
    def _on_project_opened(self, event_data: dict):
        """处理项目打开事件"""
        self._project_root = event_data.get("path")
        self._logger.info(f"Project opened: {self._project_root}")
        
        # 清空当前显示
        self.clear()
        
        # 启动仿真结果文件监控器
        if self._project_root:
            self._result_watcher.start(self._project_root)
        
        # 显示空状态，等待会话变更事件或用户操作
        # 根据 4.0.7 节设计：新会话不自动加载历史结果
        self._show_empty_state()
    
    def _on_project_closed(self, event_data: dict):
        """处理项目关闭事件"""
        # 停止仿真结果文件监控器
        self._result_watcher.stop()
        
        self._project_root = None
        self.clear()
        self._show_empty_state()
    
    def _on_simulation_complete(self, event_data: dict):
        """处理仿真完成事件"""
        result_path = event_data.get("result_path")
        metrics = event_data.get("metrics", {})
        
        self._logger.info(f"Simulation complete: {result_path}")
        
        # 加载仿真结果
        if result_path and self._project_root:
            self._load_simulation_result(result_path)
    
    def _on_all_analyses_complete(self, event_data: dict):
        """处理所有分析完成事件"""
        results = event_data.get("results", {})
        success_count = event_data.get("success_count", 0)
        total_count = event_data.get("total_count", 0)
        
        self._logger.info(f"All analyses complete: {success_count}/{total_count}")
        
        # 更新综合评分
        if total_count > 0:
            score = (success_count / total_count) * 100
            self._left_panel.set_overall_score(score)
    
    def _on_language_changed(self, event_data: dict):
        """处理语言切换事件"""
        self.retranslate_ui()
    
    def _on_awaiting_confirmation(self, event_data: dict):
        """处理等待确认事件"""
        self._status_indicator.show_awaiting_confirmation()
    
    def _on_user_confirmed(self, event_data: dict):
        """处理用户确认事件"""
        self._status_indicator.hide_status()
    
    def _on_workflow_locked(self, event_data: dict):
        """处理工作流锁定事件"""
        self._is_workflow_running = True
        self._status_indicator.show_running()
        self._set_controls_enabled(False)
    
    def _on_workflow_unlocked(self, event_data: dict):
        """处理工作流解锁事件"""
        self._is_workflow_running = False
        self._status_indicator.hide_status()
        self._set_controls_enabled(True)
    
    def _on_session_changed(self, event_data: dict):
        """
        处理会话变更事件
        
        根据 4.0.7 节设计：
        - 新会话启动时，显示空状态，不自动加载历史结果
        - 切换到已有会话时，根据 sim_result_path 加载或显示空状态
        
        Args:
            event_data: 事件数据，包含 session_id, sim_result_path 等
        """
        action = event_data.get("action", "")
        sim_result_path = event_data.get("sim_result_path", "")
        session_id = event_data.get("session_id", "")
        
        self._logger.info(
            f"Session changed: action={action}, session_id={session_id}, "
            f"sim_result_path={sim_result_path}"
        )
        
        # 新会话：显示空状态，不加载历史结果
        if action == "new" or not sim_result_path:
            self.clear()
            self._show_empty_state()
            return
        
        # 切换到已有会话：检查文件是否存在
        if self._project_root and sim_result_path:
            self._load_from_path(sim_result_path)
    
    def _load_from_path(self, sim_result_path: str):
        """
        从路径加载仿真结果
        
        Args:
            sim_result_path: 仿真结果相对路径
        """
        if not self._project_root:
            self._show_empty_state()
            return
        
        try:
            from shared.file_reference_validator import file_reference_validator
            
            # 校验文件是否存在
            if not file_reference_validator.validate_sim_result_path(
                self._project_root, sim_result_path
            ):
                self._show_file_missing_state()
                return
            
            # 加载结果
            self._load_simulation_result(sim_result_path)
            
        except Exception as e:
            self._logger.warning(f"Failed to load from path: {e}")
            self._show_file_missing_state()
    
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
        file_path = event_data.get("file_path", "")
        event_project_root = event_data.get("project_root", "")
        
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
        # 获取当前显示的结果信息
        current_result = self._view_model.current_result
        if current_result is None:
            return True
        
        # 比较时间戳（如果有的话）
        # 新文件总是需要加载
        return True
    
    def _on_metric_clicked(self, metric_name: str):
        """处理指标卡片点击"""
        self._logger.debug(f"Metric clicked: {metric_name}")
        # 可以高亮对应的图表区域或显示详情
    
    # ============================================================
    # 公共方法
    # ============================================================
    
    def set_project_root(self, project_root: str):
        """设置项目根目录"""
        self._project_root = project_root
    
    def load_result(self, result):
        """
        加载仿真结果
        
        Args:
            result: SimulationResult 对象
        """
        self._view_model.load_result(result)
        self._hide_empty_state()
    
    def update_metrics(self, metrics_list: List[DisplayMetric]):
        """
        更新指标显示
        
        Args:
            metrics_list: DisplayMetric 列表
        """
        self._update_metrics(metrics_list)
    
    def load_chart(self, chart_path: str, chart_type: Optional[str] = None):
        """
        加载图表
        
        Args:
            chart_path: 图表文件路径
            chart_type: 图表类型
        """
        self._right_panel.load_chart(chart_path, chart_type)
        self._hide_empty_state()
    
    def load_charts(self, chart_paths: Dict[str, str]):
        """
        批量加载图表
        
        Args:
            chart_paths: 图表类型到路径的映射
        """
        self._right_panel.load_charts(chart_paths)
        self._hide_empty_state()
    
    def clear(self):
        """清空所有显示"""
        self._left_panel.clear()
        self._right_panel.clear()
        self._view_model.clear()
        self._status_indicator.hide_status()
    
    def refresh(self):
        """刷新显示"""
        if self._project_root:
            self._load_project_simulation_result()
    
    def show_history_dialog(self):
        """显示历史记录对话框"""
        self._show_history_dialog()
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._left_panel.retranslate_ui()
        self._right_panel.retranslate_ui()
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
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _update_metrics(self, metrics_list: List[DisplayMetric]):
        """更新指标显示"""
        if metrics_list:
            self._left_panel.update_metrics(metrics_list)
            self._hide_empty_state()
        else:
            self._left_panel.clear()
    
    def _update_charts(self, chart_paths: List[str]):
        """更新图表显示"""
        if chart_paths:
            # 转换为字典格式
            charts_dict = {}
            for i, path in enumerate(chart_paths):
                chart_type = f"chart_{i}"
                charts_dict[chart_type] = path
            self._right_panel.load_charts(charts_dict)
            self._hide_empty_state()
    
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
        self._splitter.hide()
        self._empty_widget.show()
        
        # 更新空状态文本
        self._empty_icon.setText("📊")
        self._empty_label.setText(self._get_text(
            "simulation.no_results",
            "暂无仿真结果"
        ))
        self._empty_hint.setText(self._get_text(
            "simulation.run_hint",
            "运行仿真后，结果将显示在此处"
        ))
    
    def _show_file_missing_state(self):
        """显示文件丢失状态"""
        self._splitter.hide()
        self._empty_widget.show()
        
        # 更新为文件丢失提示
        self._empty_icon.setText("⚠️")
        self._empty_label.setText(self._get_text(
            "simulation.file_missing",
            "仿真结果文件已丢失"
        ))
        self._empty_hint.setText(self._get_text(
            "simulation.file_missing_hint",
            "请重新运行仿真或点击刷新按钮"
        ))
    
    def _hide_empty_state(self):
        """隐藏空状态"""
        self._empty_widget.hide()
        self._splitter.show()
    
    def _set_controls_enabled(self, enabled: bool):
        """设置控件启用状态"""
        self._left_panel.setEnabled(enabled)
        # 图表查看器保持可用（允许查看）
    
    def _load_project_simulation_result(self):
        """加载项目的仿真结果"""
        if not self._project_root:
            return
        
        try:
            from domain.services.simulation_service import SimulationService
            service = SimulationService()
            
            # 尝试加载最新的仿真结果
            load_result = service.get_latest_sim_result(self._project_root)
            if load_result.success and load_result.data:
                self.load_result(load_result.data)
                self._logger.info(f"Loaded simulation result: {load_result.file_path}")
            else:
                self._logger.info(f"No simulation result found: {load_result.error_message}")
                self._show_empty_state()
                
        except Exception as e:
            self._logger.warning(f"Failed to load simulation result: {e}")
            self._show_empty_state()
    
    def _load_simulation_result(self, result_path: str):
        """加载指定的仿真结果"""
        if not self._project_root:
            return
        
        try:
            from domain.services.simulation_service import SimulationService
            service = SimulationService()
            
            load_result = service.load_sim_result(self._project_root, result_path)
            if load_result.success and load_result.data:
                # load_result.data 已经是 SimulationResult 对象
                self.load_result(load_result.data)
            else:
                self._logger.warning(f"Failed to load result: {load_result.error_message}")
                
        except Exception as e:
            self._logger.warning(f"Failed to load simulation result: {e}")
    
    def _show_history_dialog(self):
        """显示历史记录对话框"""
        try:
            # 历史对话框在阶段10实现，此处预留接口
            self._logger.info("History dialog requested")
            # from presentation.dialogs.history_dialog import HistoryDialog
            # dialog = HistoryDialog(self._project_root, self)
            # dialog.exec()
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
        # 停止仿真结果文件监控器
        self._result_watcher.stop()
        
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
        # 根据 4.0.7 节设计：新会话不自动加载历史结果
        # 仿真结果的加载由 EVENT_SESSION_CHANGED 事件触发
        # 或由用户点击刷新按钮手动触发
        pass


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SimulationTab",
    "LeftPanel",
    "RightPanel",
    "StatusIndicator",
]
