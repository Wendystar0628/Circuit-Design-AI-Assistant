from typing import List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QVBoxLayout,
)

from presentation.panels.simulation.analysis_chart_viewer import ChartViewer
from presentation.panels.simulation.analysis_info_panel import AnalysisInfoPanel
from presentation.panels.simulation.metrics_panel import MetricsPanel
from presentation.panels.simulation.output_log_viewer import OutputLogViewer
from presentation.panels.simulation.raw_data_table import RawDataTable
from presentation.panels.simulation.simulation_export_panel import SimulationExportPanel
from presentation.panels.simulation.simulation_view_model import DisplayMetric
from presentation.panels.simulation.waveform_widget import WaveformWidget
from resources.theme import (
    BORDER_RADIUS_NORMAL,
    COLOR_ACCENT,
    COLOR_ACCENT_LIGHT,
    COLOR_BG_PRIMARY,
    COLOR_BG_TERTIARY,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING_LIGHT,
    FONT_SIZE_NORMAL,
    FONT_SIZE_SMALL,
    SPACING_NORMAL,
    SPACING_SMALL,
)


STATUS_BAR_HEIGHT = 48
METRICS_PANEL_MIN_WIDTH = 280
CHART_PANEL_MIN_WIDTH = 400


class SimulationStatusBanner(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("statusIndicator")
        self.setFixedHeight(STATUS_BAR_HEIGHT)

        self._setup_ui()
        self._apply_style()
        self.hide()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        layout.setSpacing(SPACING_NORMAL)

        self._icon_label = QLabel()
        self._icon_label.setObjectName("statusIcon")
        self._icon_label.setFixedSize(24, 24)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon_label)

        self._text_label = QLabel()
        self._text_label.setObjectName("statusText")
        layout.addWidget(self._text_label, 1)

        self._progress_bar = QProgressBar()
        self._progress_bar.setObjectName("statusProgress")
        self._progress_bar.setFixedWidth(120)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, 0)
        self._progress_bar.hide()
        layout.addWidget(self._progress_bar)

    def _apply_style(self):
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
        self._icon_label.setText("⏸")
        self._text_label.setText(self._get_text(
            "simulation.awaiting_confirmation",
            "迭代完成，请在对话面板中选择下一步操作"
        ))
        self._progress_bar.hide()
        self.show()

    def show_running(self, message: str = ""):
        self._icon_label.setText("⏳")
        text = message or self._get_text(
            "simulation.running",
            "优化进行中，请等待本轮完成..."
        )
        self._text_label.setText(text)
        self._progress_bar.show()
        self.show()

    def hide_status(self):
        self.hide()

    def _get_text(self, key: str, default: str) -> str:
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(key, default)
        except ImportError:
            return default

    def retranslate_ui(self):
        pass


class SimulationMetricsSummaryPanel(QFrame):
    history_clicked = pyqtSignal()
    refresh_clicked = pyqtSignal()
    add_to_conversation_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("metricsSummaryPanel")
        self.setMinimumWidth(METRICS_PANEL_MIN_WIDTH)
        self._overall_score: float = 0.0

        self._setup_ui()
        self._apply_style()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header_bar = QFrame()
        self._header_bar.setObjectName("headerBar")
        self._header_bar.setFixedHeight(36)
        header_layout = QHBoxLayout(self._header_bar)
        header_layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        header_layout.setSpacing(SPACING_SMALL)

        timestamp_container = QFrame()
        timestamp_layout = QHBoxLayout(timestamp_container)
        timestamp_layout.setContentsMargins(0, 0, 0, 0)
        timestamp_layout.setSpacing(4)

        self._timestamp_icon = QLabel()
        self._timestamp_icon.setObjectName("timestampIcon")
        self._timestamp_icon.setFixedSize(14, 14)
        self._load_timestamp_icon()
        timestamp_layout.addWidget(self._timestamp_icon)

        self._timestamp_label = QLabel()
        self._timestamp_label.setObjectName("timestampLabel")
        timestamp_layout.addWidget(self._timestamp_label)
        header_layout.addWidget(timestamp_container)

        header_layout.addStretch(1)

        score_container = QFrame()
        score_layout = QHBoxLayout(score_container)
        score_layout.setContentsMargins(0, 0, 0, 0)
        score_layout.setSpacing(SPACING_SMALL)

        self._score_title = QLabel()
        self._score_title.setObjectName("scoreTitle")
        score_layout.addWidget(self._score_title)

        self._score_bar = QProgressBar()
        self._score_bar.setObjectName("scoreBar")
        self._score_bar.setRange(0, 100)
        self._score_bar.setValue(0)
        self._score_bar.setTextVisible(False)
        self._score_bar.setFixedWidth(80)
        self._score_bar.setFixedHeight(6)
        score_layout.addWidget(self._score_bar)

        self._score_value = QLabel("0%")
        self._score_value.setObjectName("scoreValue")
        self._score_value.setFixedWidth(50)
        score_layout.addWidget(self._score_value)

        header_layout.addWidget(score_container)
        header_layout.addStretch(1)

        btn_container = QFrame()
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(SPACING_SMALL)

        self._refresh_btn = QPushButton()
        self._refresh_btn.setObjectName("refreshBtn")
        self._refresh_btn.setFixedHeight(24)
        self._refresh_btn.clicked.connect(self.refresh_clicked.emit)
        btn_layout.addWidget(self._refresh_btn)

        self._add_to_conversation_btn = QPushButton()
        self._add_to_conversation_btn.setObjectName("refreshBtn")
        self._add_to_conversation_btn.setFixedHeight(24)
        self._add_to_conversation_btn.setEnabled(False)
        self._add_to_conversation_btn.clicked.connect(self.add_to_conversation_clicked.emit)
        btn_layout.addWidget(self._add_to_conversation_btn)

        self._history_btn = QPushButton()
        self._history_btn.setObjectName("historyBtn")
        self._history_btn.setFixedHeight(24)
        self._history_btn.clicked.connect(self.history_clicked.emit)
        btn_layout.addWidget(self._history_btn)

        header_layout.addWidget(btn_container)

        layout.addWidget(self._header_bar)
        self._header_bar.hide()

        self._metrics_panel = MetricsPanel()
        self._metrics_panel._score_frame.hide()
        layout.addWidget(self._metrics_panel, 1)

        self.retranslate_ui()

    def _load_timestamp_icon(self):
        try:
            from pathlib import Path
            from PyQt6.QtGui import QPixmap

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
        return self._metrics_panel

    def update_metrics(self, metrics_list: List[DisplayMetric]):
        self._metrics_panel.update_metrics(metrics_list)
        self._add_to_conversation_btn.setEnabled(bool(metrics_list))

    def set_overall_score(self, score: float):
        if score < 0:
            self._overall_score = -1.0
            self._score_value.setText("N/A")
            self._score_bar.setValue(0)
            self._score_bar.setEnabled(False)
        else:
            self._overall_score = max(0.0, min(100.0, score))
            self._score_value.setText(f"{self._overall_score:.1f}%")
            self._score_bar.setValue(int(self._overall_score))
            self._score_bar.setEnabled(True)
        self._metrics_panel.set_overall_score(score)

    def set_result_timestamp(self, timestamp: str):
        formatted = self._format_timestamp(timestamp)
        self._timestamp_label.setText(formatted)
        self._header_bar.show()

    def clear_result_timestamp(self):
        self._timestamp_label.clear()
        self._header_bar.hide()

    def show_header_bar(self):
        self._header_bar.show()

    def hide_header_bar(self):
        self._header_bar.hide()

    def _format_timestamp(self, iso_str: str) -> str:
        if not iso_str:
            return ""

        try:
            from datetime import datetime
            if "T" in iso_str:
                dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(iso_str)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return iso_str

    def clear(self):
        self._metrics_panel.clear()
        self.clear_result_timestamp()
        self._overall_score = 0.0
        self._score_value.setText("0%")
        self._score_bar.setValue(0)
        self._score_bar.setEnabled(True)
        self._add_to_conversation_btn.setEnabled(False)

    def retranslate_ui(self):
        self._refresh_btn.setText(self._get_text("simulation.refresh", "刷新"))
        self._add_to_conversation_btn.setText(self._get_text("simulation.add_to_conversation", "添加至对话"))
        self._history_btn.setText(self._get_text("simulation.view_history", "查看历史"))
        self._score_title.setText(self._get_text("simulation.overall_score", "Overall Score"))
        self._metrics_panel.retranslate_ui()

    def _get_text(self, key: str, default: str) -> str:
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(key, default)
        except ImportError:
            return default


class SimulationResultTabView(QFrame):
    TAB_METRICS = 0
    TAB_CHART = 1
    TAB_WAVEFORM = 2
    TAB_ANALYSIS_INFO = 3
    TAB_RAW_DATA = 4
    TAB_LOG = 5
    TAB_EXPORT = 6

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("chartViewerPanel")
        self.setMinimumWidth(CHART_PANEL_MIN_WIDTH)

        self._setup_ui()
        self._apply_style()

    def _setup_ui(self):
        from PyQt6.QtWidgets import QTabWidget

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tab_widget = QTabWidget()
        self._tab_widget.setObjectName("chartTabWidget")
        self._tab_widget.setDocumentMode(True)

        self._metrics_summary_panel = SimulationMetricsSummaryPanel()
        self._tab_widget.addTab(self._metrics_summary_panel, "")

        self._chart_viewer = ChartViewer()
        self._tab_widget.addTab(self._chart_viewer, "")

        self._waveform_widget = WaveformWidget()
        self._tab_widget.addTab(self._waveform_widget, "")

        self._analysis_info_panel = AnalysisInfoPanel()
        self._tab_widget.addTab(self._analysis_info_panel, "")

        self._raw_data_table = RawDataTable()
        self._tab_widget.addTab(self._raw_data_table, "")

        self._output_log_viewer = OutputLogViewer()
        self._tab_widget.addTab(self._output_log_viewer, "")

        self._export_panel = SimulationExportPanel(self._chart_viewer, self._waveform_widget)
        self._tab_widget.addTab(self._export_panel, "")

        layout.addWidget(self._tab_widget)
        self._update_tab_titles()

    def _apply_style(self):
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
        self._tab_widget.setTabText(self.TAB_METRICS, self._get_text("simulation.tab.metrics", "仿真指标"))
        self._tab_widget.setTabText(self.TAB_CHART, self._get_text("simulation.tab.chart", "图表"))
        self._tab_widget.setTabText(self.TAB_WAVEFORM, self._get_text("simulation.tab.waveform", "波形"))
        self._tab_widget.setTabText(self.TAB_ANALYSIS_INFO, self._get_text("simulation.tab.analysis_info", "分析信息"))
        self._tab_widget.setTabText(self.TAB_RAW_DATA, self._get_text("simulation.tab.raw_data", "原始数据"))
        self._tab_widget.setTabText(self.TAB_LOG, self._get_text("simulation.tab.log", "输出日志"))
        self._tab_widget.setTabText(self.TAB_EXPORT, self._get_text("simulation.tab.export", "数据导出"))

    @property
    def chart_viewer(self) -> ChartViewer:
        return self._chart_viewer

    @property
    def metrics_summary_panel(self) -> SimulationMetricsSummaryPanel:
        return self._metrics_summary_panel

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
        self._metrics_summary_panel.clear()
        self._chart_viewer.clear()
        self._waveform_widget.clear_waveforms()
        self._analysis_info_panel.clear()
        self._raw_data_table.clear()
        self._output_log_viewer.clear()
        self._export_panel.clear()

    def switch_to_metrics(self):
        self._tab_widget.setCurrentIndex(self.TAB_METRICS)

    def switch_to_chart(self):
        self._tab_widget.setCurrentIndex(self.TAB_CHART)

    def switch_to_waveform(self):
        self._tab_widget.setCurrentIndex(self.TAB_WAVEFORM)

    def switch_to_analysis_info(self):
        self._tab_widget.setCurrentIndex(self.TAB_ANALYSIS_INFO)

    def switch_to_raw_data(self):
        self._tab_widget.setCurrentIndex(self.TAB_RAW_DATA)

    def switch_to_log(self):
        self._tab_widget.setCurrentIndex(self.TAB_LOG)

    def retranslate_ui(self):
        self._update_tab_titles()
        self._metrics_summary_panel.retranslate_ui()
        self._chart_viewer.retranslate_ui()
        self._waveform_widget.retranslate_ui()
        self._analysis_info_panel.retranslate_ui()
        self._raw_data_table.retranslate_ui()
        self._output_log_viewer.retranslate_ui()
        self._export_panel.retranslate_ui()

    def _get_text(self, key: str, default: str) -> str:
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(key, default)
        except ImportError:
            return default


__all__ = [
    "SimulationStatusBanner",
    "SimulationMetricsSummaryPanel",
    "SimulationResultTabView",
]
