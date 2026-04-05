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
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
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
from presentation.panels.simulation.analysis_info_panel import AnalysisInfoPanel
from presentation.panels.simulation.analysis_chart_viewer import ChartViewer
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
    EVENT_SIM_STARTED,
    EVENT_SIM_ERROR,
    EVENT_LANGUAGE_CHANGED,
    EVENT_ITERATION_AWAITING_CONFIRMATION,
    EVENT_ITERATION_USER_CONFIRMED,
    EVENT_SIM_RESULT_FILE_CREATED,
    EVENT_SESSION_CHANGED,
)


# ============================================================
# 样式常量
# ============================================================

METRICS_PANEL_MIN_WIDTH = 280
CHART_PANEL_MIN_WIDTH = 400
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


class MetricsSummaryPanel(QFrame):
    """
    指标摘要面板
    
    包含顶部信息栏（时间戳、总体分数、刷新/历史按钮）和指标网格
    布局优化：将时间戳、总体分数、刷新按钮放在同一行，提高空间利用率
    """
    
    history_clicked = pyqtSignal()
    refresh_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("metricsSummaryPanel")
        self.setMinimumWidth(METRICS_PANEL_MIN_WIDTH)
        
        self._overall_score: float = 0.0
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 顶部信息栏（单行布局：时间戳 | 总体分数 | 按钮）
        self._header_bar = QFrame()
        self._header_bar.setObjectName("headerBar")
        self._header_bar.setFixedHeight(36)
        header_layout = QHBoxLayout(self._header_bar)
        header_layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        header_layout.setSpacing(SPACING_SMALL)
        
        # 左侧：时间戳区域
        timestamp_container = QWidget()
        timestamp_layout = QHBoxLayout(timestamp_container)
        timestamp_layout.setContentsMargins(0, 0, 0, 0)
        timestamp_layout.setSpacing(4)
        
        # 时间戳图标
        self._timestamp_icon = QLabel()
        self._timestamp_icon.setObjectName("timestampIcon")
        self._timestamp_icon.setFixedSize(14, 14)
        self._load_timestamp_icon()
        timestamp_layout.addWidget(self._timestamp_icon)
        
        # 时间戳文本
        self._timestamp_label = QLabel()
        self._timestamp_label.setObjectName("timestampLabel")
        timestamp_layout.addWidget(self._timestamp_label)
        
        header_layout.addWidget(timestamp_container)
        
        # 中间弹性空间
        header_layout.addStretch(1)
        
        # 中间：总体分数区域
        score_container = QWidget()
        score_layout = QHBoxLayout(score_container)
        score_layout.setContentsMargins(0, 0, 0, 0)
        score_layout.setSpacing(SPACING_SMALL)
        
        # 分数标签
        self._score_title = QLabel()
        self._score_title.setObjectName("scoreTitle")
        score_layout.addWidget(self._score_title)
        
        # 分数进度条
        self._score_bar = QProgressBar()
        self._score_bar.setObjectName("scoreBar")
        self._score_bar.setRange(0, 100)
        self._score_bar.setValue(0)
        self._score_bar.setTextVisible(False)
        self._score_bar.setFixedWidth(80)
        self._score_bar.setFixedHeight(6)
        score_layout.addWidget(self._score_bar)
        
        # 分数值
        self._score_value = QLabel("0%")
        self._score_value.setObjectName("scoreValue")
        self._score_value.setFixedWidth(50)
        score_layout.addWidget(self._score_value)
        
        header_layout.addWidget(score_container)
        
        # 中间弹性空间
        header_layout.addStretch(1)
        
        # 右侧：按钮区域
        btn_container = QWidget()
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(SPACING_SMALL)
        
        # 刷新按钮
        self._refresh_btn = QPushButton()
        self._refresh_btn.setObjectName("refreshBtn")
        self._refresh_btn.setFixedHeight(24)
        self._refresh_btn.clicked.connect(self.refresh_clicked.emit)
        btn_layout.addWidget(self._refresh_btn)
        
        # 查看历史按钮
        self._history_btn = QPushButton()
        self._history_btn.setObjectName("historyBtn")
        self._history_btn.setFixedHeight(24)
        self._history_btn.clicked.connect(self.history_clicked.emit)
        btn_layout.addWidget(self._history_btn)
        
        header_layout.addWidget(btn_container)
        
        layout.addWidget(self._header_bar)
        self._header_bar.hide()  # 默认隐藏，有数据时显示
        
        # 指标面板（不再包含综合评分，已移到顶部信息栏）
        self._metrics_panel = MetricsPanel()
        # 隐藏 MetricsPanel 内部的综合评分区域
        self._metrics_panel._score_frame.hide()
        layout.addWidget(self._metrics_panel, 1)
        
        # 初始化文本
        self.retranslate_ui()
    
    def _load_timestamp_icon(self):
        """加载时间戳图标"""
        try:
            from PyQt6.QtGui import QPixmap
            from pathlib import Path
            
            icon_path = Path(__file__).parent.parent.parent / "resources" / "icons" / "simulation" / "clock.svg"
            if icon_path.exists():
                pixmap = QPixmap(str(icon_path))
                if not pixmap.isNull():
                    self._timestamp_icon.setPixmap(pixmap.scaled(
                        14, 14,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    ))
        except Exception:
            pass
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #metricsSummaryPanel {{
                background-color: {COLOR_BG_PRIMARY};
                border-right: 1px solid {COLOR_BORDER};
            }}
            
            #headerBar {{
                background-color: {COLOR_BG_PRIMARY};
                border-bottom: 1px solid {COLOR_BORDER};
            }}
            
            #timestampLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #scoreTitle {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #scoreValue {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_SMALL}px;
                font-weight: bold;
            }}
            
            #scoreBar {{
                background-color: #d0d0d0;
                border: none;
                border-radius: 3px;
            }}
            
            #scoreBar::chunk {{
                background-color: {COLOR_ACCENT};
                border-radius: 3px;
            }}
            
            #historyBtn, #refreshBtn {{
                background-color: transparent;
                color: {COLOR_ACCENT};
                border: 1px solid {COLOR_ACCENT};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 2px 8px;
                font-size: {FONT_SIZE_SMALL}px;
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
        """
        设置综合评分
        
        Args:
            score: 评分值（0-100，-1.0 表示无目标模式无评分）
        """
        if score < 0:
            # 无目标模式：显示 N/A
            self._overall_score = -1.0
            self._score_value.setText("N/A")
            self._score_bar.setValue(0)
            self._score_bar.setEnabled(False)
        else:
            # 有目标模式：显示百分比
            self._overall_score = max(0.0, min(100.0, score))
            self._score_value.setText(f"{self._overall_score:.1f}%")
            self._score_bar.setValue(int(self._overall_score))
            self._score_bar.setEnabled(True)
        # 同时更新 MetricsPanel 内部的分数（保持数据一致性）
        self._metrics_panel.set_overall_score(score)
    
    def set_result_timestamp(self, timestamp: str):
        """
        设置仿真结果时间戳
        
        Args:
            timestamp: ISO 格式时间戳
        """
        formatted = self._format_timestamp(timestamp)
        self._timestamp_label.setText(formatted)
        self._header_bar.show()
    
    def clear_result_timestamp(self):
        """清空时间戳显示"""
        self._timestamp_label.clear()
        self._header_bar.hide()
    
    def show_header_bar(self):
        """显示顶部信息栏"""
        self._header_bar.show()
    
    def hide_header_bar(self):
        """隐藏顶部信息栏"""
        self._header_bar.hide()
    
    def _format_timestamp(self, iso_str: str) -> str:
        """
        将 ISO 格式时间戳转换为本地化显示格式
        
        Args:
            iso_str: ISO 格式时间戳（如 2026-01-06T14:30:22）
            
        Returns:
            str: 本地化显示格式（如 2026-01-06 14:30:22）
        """
        if not iso_str:
            return ""
        
        try:
            from datetime import datetime
            
            # 尝试解析 ISO 格式
            if "T" in iso_str:
                dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(iso_str)
            
            # 返回本地化格式
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            # 解析失败，返回原始字符串
            return iso_str
    
    def clear(self):
        """清空显示"""
        self._metrics_panel.clear()
        self.clear_result_timestamp()
        self._overall_score = 0.0
        self._score_value.setText("0%")
        self._score_bar.setValue(0)
        self._score_bar.setEnabled(True)
    
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
        self._score_title.setText(self._get_text(
            "simulation.overall_score",
            "Overall Score"
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


class ChartViewerPanel(QFrame):
    """
    图表查看面板
    
    包含多个标签页：指标、图表视图、波形视图、原始数据、输出日志
    """
    
    # 标签页索引常量
    TAB_METRICS = 0
    TAB_CHART = 1
    TAB_WAVEFORM = 2
    TAB_ANALYSIS_INFO = 3
    TAB_RAW_DATA = 4
    TAB_LOG = 5
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("chartViewerPanel")
        self.setMinimumWidth(CHART_PANEL_MIN_WIDTH)
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 标签页容器
        from PyQt6.QtWidgets import QTabWidget
        self._tab_widget = QTabWidget()
        self._tab_widget.setObjectName("chartTabWidget")
        self._tab_widget.setDocumentMode(True)

        self._metrics_summary_panel = MetricsSummaryPanel()
        self._tab_widget.addTab(self._metrics_summary_panel, "")
        
        # 图表查看器标签页
        self._chart_viewer = ChartViewer()
        self._tab_widget.addTab(self._chart_viewer, "")
        
        # 波形查看器标签页
        from presentation.panels.simulation.waveform_widget import WaveformWidget
        self._waveform_widget = WaveformWidget()
        self._tab_widget.addTab(self._waveform_widget, "")
        
        self._analysis_info_panel = AnalysisInfoPanel()
        self._tab_widget.addTab(self._analysis_info_panel, "")

        # 原始数据表格标签页
        from presentation.panels.simulation.raw_data_table import RawDataTable
        self._raw_data_table = RawDataTable()
        self._tab_widget.addTab(self._raw_data_table, "")
        
        # 输出日志查看器标签页
        from presentation.panels.simulation.output_log_viewer import OutputLogViewer
        self._output_log_viewer = OutputLogViewer()
        self._tab_widget.addTab(self._output_log_viewer, "")
        
        layout.addWidget(self._tab_widget)
        
        # 初始化标签页标题
        self._update_tab_titles()
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #chartViewerPanel {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #chartTabWidget {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #chartTabWidget::pane {{
                border: none;
            }}
            
            #chartTabWidget::tab-bar {{
                alignment: left;
            }}
            
            #chartTabWidget QTabBar::tab {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_SECONDARY};
                padding: 6px 12px;
                margin-right: 2px;
                border: none;
                border-bottom: 2px solid transparent;
            }}
            
            #chartTabWidget QTabBar::tab:selected {{
                color: {COLOR_ACCENT};
                border-bottom: 2px solid {COLOR_ACCENT};
            }}
            
            #chartTabWidget QTabBar::tab:hover:!selected {{
                color: {COLOR_TEXT_PRIMARY};
                background-color: {COLOR_ACCENT_LIGHT};
            }}
        """)
    
    def _update_tab_titles(self):
        """更新标签页标题"""
        self._tab_widget.setTabText(self.TAB_METRICS, self._get_text(
            "simulation.tab.metrics", "仿真指标"
        ))
        self._tab_widget.setTabText(self.TAB_CHART, self._get_text(
            "simulation.tab.chart", "图表"
        ))
        self._tab_widget.setTabText(self.TAB_WAVEFORM, self._get_text(
            "simulation.tab.waveform", "波形"
        ))
        self._tab_widget.setTabText(self.TAB_ANALYSIS_INFO, self._get_text(
            "simulation.tab.analysis_info", "分析信息"
        ))
        self._tab_widget.setTabText(self.TAB_RAW_DATA, self._get_text(
            "simulation.tab.raw_data", "原始数据"
        ))
        self._tab_widget.setTabText(self.TAB_LOG, self._get_text(
            "simulation.tab.log", "输出日志"
        ))
    
    @property
    def chart_viewer(self) -> ChartViewer:
        """获取图表查看器"""
        return self._chart_viewer

    @property
    def metrics_summary_panel(self) -> MetricsSummaryPanel:
        """获取仿真指标标签页"""
        return self._metrics_summary_panel
    
    @property
    def waveform_widget(self):
        """获取波形查看器"""
        return self._waveform_widget
    
    @property
    def analysis_info_panel(self):
        return self._analysis_info_panel

    @property
    def raw_data_table(self):
        """获取原始数据表格"""
        return self._raw_data_table
    
    @property
    def output_log_viewer(self):
        """获取输出日志查看器"""
        return self._output_log_viewer
    
    def clear(self):
        """清空所有内容"""
        self._metrics_summary_panel.clear()
        self._chart_viewer.clear()
        self._waveform_widget.clear_waveforms()
        self._analysis_info_panel.clear()
        self._raw_data_table.clear()
        self._output_log_viewer.clear()

    def switch_to_metrics(self):
        """切换到仿真指标标签页"""
        self._tab_widget.setCurrentIndex(self.TAB_METRICS)
    
    def switch_to_chart(self):
        """切换到图表标签页"""
        self._tab_widget.setCurrentIndex(self.TAB_CHART)
    
    def switch_to_waveform(self):
        """切换到波形标签页"""
        self._tab_widget.setCurrentIndex(self.TAB_WAVEFORM)
    
    def switch_to_analysis_info(self):
        self._tab_widget.setCurrentIndex(self.TAB_ANALYSIS_INFO)

    def switch_to_raw_data(self):
        """切换到原始数据标签页"""
        self._tab_widget.setCurrentIndex(self.TAB_RAW_DATA)
    
    def switch_to_log(self):
        """切换到输出日志标签页"""
        self._tab_widget.setCurrentIndex(self.TAB_LOG)
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._update_tab_titles()
        self._metrics_summary_panel.retranslate_ui()
        self._chart_viewer.retranslate_ui()
        self._waveform_widget.retranslate_ui()
        self._analysis_info_panel.retranslate_ui()
        self._raw_data_table.retranslate_ui()
        self._output_log_viewer.retranslate_ui()
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(key, default)
        except ImportError:
            return default



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

        self._chart_viewer_panel = ChartViewerPanel()
        self._metrics_panel_view = self._chart_viewer_panel.metrics_summary_panel
        main_layout.addWidget(self._chart_viewer_panel, 1)
        
        # 状态指示器
        self._status_indicator = StatusIndicator()
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
            self._metrics_panel_view.set_overall_score(value)
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

        QTimer.singleShot(250, self._restore_last_result_after_project_opened)
    
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
        if result_path and self._project_root:
            self._load_simulation_result(result_path)
        elif not result_path:
            self._logger.warning("No result_path in event, trying to load latest result")
            self._load_project_simulation_result()

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
    
    def _on_session_changed(self, event_data: dict):
        """
        处理会话变更事件
        
        根据 4.0.7 节设计：
        - 新会话启动时，显示空状态，不自动加载历史结果
        - 切换到已有会话时，根据 sim_result_path 加载或显示空状态
        
        Args:
            event_data: 事件数据，包含 session_id, sim_result_path 等
        """
        # 事件数据在 "data" 字段中
        data = event_data.get("data", event_data)
        action = data.get("action", "")
        sim_result_path = data.get("sim_result_path", "")
        session_id = data.get("session_id", "")
        
        self._logger.info(
            f"Session changed: action={action}, session_id={session_id}, "
            f"sim_result_path={sim_result_path}"
        )
        
        if action == "new":
            self.clear()
            self._show_empty_state()
            return
        
        if self._project_root and sim_result_path:
            self._load_from_path(sim_result_path)
            return

        if action == "switch":
            self.clear()
            self._show_empty_state()
    
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
    
    def load_result(self, result, result_path: Optional[str] = None):
        """
        加载仿真结果
        
        Args:
            result: SimulationResult 对象
        """
        if result_path:
            self._last_loaded_result_path = self._normalize_result_path(result_path)
            self._persist_current_session_result_path(result_path)

        self._chart_viewer_panel.clear()
        self._view_model.load_result(result)
        self._chart_viewer_panel.analysis_info_panel.load_result(result)
        
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

    def _restore_last_result_after_project_opened(self):
        if not self._project_root:
            return

        if self._view_model.current_result is not None or self._last_loaded_result_path:
            return

        try:
            from domain.services import context_service

            session_id = context_service.get_current_session_id(self._project_root)
            metadata = context_service.get_session_metadata(self._project_root, session_id) if session_id else None
            sim_result_path = metadata.get("sim_result_path", "") if metadata else ""

            if sim_result_path:
                self._load_from_path(sim_result_path)
                return
        except Exception as e:
            self._logger.debug(f"Failed to restore session-bound simulation result: {e}")

        self._load_project_simulation_result()

    def _persist_current_session_result_path(self, result_path: str):
        if not self._project_root or not result_path:
            return

        persisted_path = result_path.replace('\\', '/')

        try:
            from domain.services import context_service

            session_id = context_service.get_current_session_id(self._project_root)
            if session_id:
                metadata = context_service.get_session_metadata(self._project_root, session_id) or {}
                if metadata.get("sim_result_path") != persisted_path:
                    context_service.update_session_index(
                        self._project_root,
                        session_id,
                        {"sim_result_path": persisted_path},
                    )
        except Exception as e:
            self._logger.debug(f"Failed to persist simulation result path for session: {e}")

        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_CONTEXT_MANAGER

            context_manager = ServiceLocator.get_optional(SVC_CONTEXT_MANAGER)
            if context_manager:
                current_state = context_manager.get_current_state() or {}
                if current_state.get("sim_result_path") != persisted_path:
                    new_state = dict(current_state)
                    new_state["sim_result_path"] = persisted_path
                    context_manager.sync_state(new_state)
        except Exception as e:
            self._logger.debug(f"Failed to sync simulation result path into context state: {e}")

    def _load_waveform_data(self, result):
        """
        加载波形数据到各组件

        默认选择第一个电压信号显示；若无电压信号则选第一个可用信号。

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
                default_signal = waveform_data_service.get_preferred_signal(result)
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
        self._chart_viewer_panel.clear()
        self._view_model.clear()
        self._status_indicator.hide_status()
        self._show_empty_state()
    
    def export_waveform_data(self, format: str = "csv"):
        """
        导出波形数据
        
        Args:
            format: 导出格式（csv/json/mat/npy/npz）
        """
        current_result = self._view_model.current_result
        if current_result is None:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                self._get_text("export.title", "导出数据"),
                self._get_text("export.no_data", "无仿真数据可导出")
            )
            return
        
        # 获取导出路径
        from PyQt6.QtWidgets import QFileDialog
        from domain.simulation.data.data_exporter import data_exporter
        
        ext = data_exporter.get_format_extension(format)
        filter_str = f"{format.upper()} Files (*{ext})"
        
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._get_text("export.title", "导出数据"),
            f"simulation_data{ext}",
            filter_str
        )
        
        if not path:
            return
        
        # 执行导出
        result = data_exporter.export(
            current_result, format, path
        )
        
        if result.success:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self,
                self._get_text("export.title", "导出数据"),
                self._get_text("export.success", "数据导出成功：{path}").format(path=path)
            )
        else:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                self._get_text("export.title", "导出数据"),
                self._get_text("export.failed", "导出失败：{error}").format(error=result.error_message)
            )
    
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
    
    def _show_file_missing_state(self):
        """显示文件丢失状态"""
        self._chart_viewer_panel.hide()
        self._empty_widget.show()
        self._metrics_panel_view.clear_result_timestamp()
        # 隐藏顶部信息栏
        self._metrics_panel_view.hide_header_bar()
        
        # 加载文件丢失图标
        self._load_file_missing_icon()
        
        # 更新为文件丢失提示
        self._empty_label.setText(self._get_text(
            "simulation.file_missing",
            "仿真结果文件已丢失"
        ))
        self._empty_hint.setText(self._get_text(
            "simulation.file_missing_hint",
            "请重新运行仿真或点击刷新按钮"
        ))
        
        # 隐藏加载历史按钮
        self._load_history_btn.hide()
    
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
                self._last_loaded_result_path = self._normalize_result_path(load_result.file_path)
                self.load_result(load_result.data, load_result.file_path)
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
                self._last_loaded_result_path = self._normalize_result_path(result_path)
                self.load_result(load_result.data, result_path)
            else:
                self._logger.warning(f"Failed to load result: {load_result.error_message}")
                
        except Exception as e:
            self._logger.warning(f"Failed to load simulation result: {e}")

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
    
    def _load_file_missing_icon(self):
        """加载文件丢失图标"""
        try:
            from PyQt6.QtGui import QPixmap
            from pathlib import Path
            
            icon_path = Path(__file__).parent.parent.parent / "resources" / "icons" / "simulation" / "file-missing.svg"
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
        # 根据 4.0.7 节设计：新会话不自动加载历史结果
        # 仿真结果的加载由 EVENT_SESSION_CHANGED 事件触发
        # 或由用户点击刷新按钮手动触发
        pass


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SimulationTab",
    "MetricsSummaryPanel",
    "ChartViewerPanel",
    "StatusIndicator",
]
