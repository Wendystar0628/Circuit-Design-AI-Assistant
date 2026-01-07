# WorstCaseResultTab - Worst Case Analysis Result Tab
"""
最坏情况分析结果标签页

职责：
- 展示最坏情况分析结果
- 显示设计裕度和关键参数
- 支持 RSS/EVA 方法切换显示

设计原则：
- 使用 QWidget 作为基类
- 订阅 EVENT_WORST_CASE_COMPLETE 事件自动更新
- 支持国际化

被调用方：
- simulation_tab.py
"""

import logging
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSizePolicy,
    QGroupBox,
    QProgressBar,
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
    COLOR_SUCCESS,
    COLOR_ERROR,
    COLOR_WARNING,
    FONT_SIZE_NORMAL,
    FONT_SIZE_SMALL,
    FONT_SIZE_TITLE,
    FONT_SIZE_LARGE_TITLE,
    SPACING_SMALL,
    SPACING_NORMAL,
    SPACING_LARGE,
    BORDER_RADIUS_NORMAL,
)


# ============================================================
# 常量
# ============================================================

MARGIN_GOOD_THRESHOLD = 20.0   # 裕度 >= 20% 显示绿色
MARGIN_WARN_THRESHOLD = 10.0   # 裕度 >= 10% 显示黄色


# ============================================================
# 子组件
# ============================================================

class MethodSelector(QFrame):
    """
    分析方法选择器
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("methodSelector")
        self.setFixedHeight(48)
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        layout.setSpacing(SPACING_NORMAL)
        
        # 方法标签
        label = QLabel(self._get_text("wc.method", "分析方法:"))
        label.setObjectName("methodLabel")
        layout.addWidget(label)
        
        # 方法显示
        self._method_value = QLabel("—")
        self._method_value.setObjectName("methodValue")
        layout.addWidget(self._method_value)
        
        layout.addStretch(1)
        
        # 指标显示
        metric_label = QLabel(self._get_text("wc.metric", "分析指标:"))
        metric_label.setObjectName("methodLabel")
        layout.addWidget(metric_label)
        
        self._metric_value = QLabel("—")
        self._metric_value.setObjectName("metricValue")
        layout.addWidget(self._metric_value)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #methodSelector {{
                background-color: {COLOR_BG_SECONDARY};
                border-bottom: 1px solid {COLOR_BORDER};
            }}
            
            #methodLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #methodValue, #metricValue {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
                font-weight: bold;
            }}
        """)
    
    def set_method(self, method: str):
        """设置分析方法"""
        method_text = {
            "rss": "RSS (Root Sum Square)",
            "eva": "EVA (Extreme Value Analysis)",
        }.get(method.lower(), method.upper())
        self._method_value.setText(method_text)
    
    def set_metric(self, metric: str):
        """设置分析指标"""
        self._metric_value.setText(metric)
    
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
        pass


class ResultSummaryCard(QFrame):
    """
    结果摘要卡片
    
    显示标称值、最坏情况值、设计裕度
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("resultSummaryCard")
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_NORMAL)
        
        # 标题
        title = QLabel(self._get_text("wc.summary", "分析结果"))
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        self._title = title
        
        # 标称值
        self._nominal_row = self._create_value_row("wc.nominal", "标称值", "—")
        layout.addWidget(self._nominal_row)
        
        # 最坏情况最大值
        self._wc_max_row = self._create_value_row("wc.worst_max", "最坏情况最大值", "—")
        layout.addWidget(self._wc_max_row)
        
        # 最坏情况最小值
        self._wc_min_row = self._create_value_row("wc.worst_min", "最坏情况最小值", "—")
        layout.addWidget(self._wc_min_row)
        
        # 分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(f"background-color: {COLOR_BORDER};")
        separator.setFixedHeight(1)
        layout.addWidget(separator)
        
        # 设计裕度
        self._margin_row = self._create_value_row("wc.margin", "设计裕度", "—", large=True)
        layout.addWidget(self._margin_row)
        
        layout.addStretch(1)
    
    def _create_value_row(self, key: str, default_label: str, default_value: str, large: bool = False) -> QFrame:
        """创建值显示行"""
        row = QFrame()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(SPACING_SMALL)
        
        label = QLabel(self._get_text(key, default_label))
        label.setObjectName("rowLabel")
        row_layout.addWidget(label)
        
        row_layout.addStretch(1)
        
        value = QLabel(default_value)
        value.setObjectName("rowValueLarge" if large else "rowValue")
        value.setAlignment(Qt.AlignmentFlag.AlignRight)
        row_layout.addWidget(value)
        
        row.label_widget = label
        row.value_widget = value
        row.i18n_key = key
        row.default_label = default_label
        
        return row
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #resultSummaryCard {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #cardTitle {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
                font-weight: bold;
            }}
            
            #rowLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #rowValue {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_SMALL}px;
                font-weight: bold;
            }}
            
            #rowValueLarge {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_TITLE}px;
                font-weight: bold;
            }}
        """)
    
    def set_values(
        self,
        nominal: float,
        wc_max: float,
        wc_min: float,
        margin: float
    ):
        """设置结果值"""
        self._nominal_row.value_widget.setText(f"{nominal:.4g}")
        self._wc_max_row.value_widget.setText(f"{wc_max:.4g}")
        self._wc_min_row.value_widget.setText(f"{wc_min:.4g}")
        
        # 设置裕度显示和颜色
        margin_text = f"{margin:.1f}%"
        self._margin_row.value_widget.setText(margin_text)
        
        if margin >= MARGIN_GOOD_THRESHOLD:
            color = COLOR_SUCCESS
        elif margin >= MARGIN_WARN_THRESHOLD:
            color = COLOR_WARNING
        else:
            color = COLOR_ERROR
        
        self._margin_row.value_widget.setStyleSheet(f"""
            color: {color};
            font-size: {FONT_SIZE_TITLE}px;
            font-weight: bold;
        """)
    
    def clear(self):
        """清空显示"""
        self._nominal_row.value_widget.setText("—")
        self._wc_max_row.value_widget.setText("—")
        self._wc_min_row.value_widget.setText("—")
        self._margin_row.value_widget.setText("—")
    
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
        self._title.setText(self._get_text("wc.summary", "分析结果"))
        for row in [self._nominal_row, self._wc_max_row, self._wc_min_row, self._margin_row]:
            row.label_widget.setText(self._get_text(row.i18n_key, row.default_label))


class MarginGauge(QFrame):
    """
    裕度仪表盘
    
    可视化显示设计裕度
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("marginGauge")
        self.setFixedHeight(120)
        
        self._margin: float = 0.0
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_SMALL)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 标题
        title = QLabel(self._get_text("wc.design_margin", "设计裕度"))
        title.setObjectName("gaugeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        self._title = title
        
        # 裕度值（大字体）
        self._value_label = QLabel("—")
        self._value_label.setObjectName("gaugeValue")
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._value_label)
        
        # 进度条
        self._progress_bar = QProgressBar()
        self._progress_bar.setObjectName("marginProgress")
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(12)
        layout.addWidget(self._progress_bar)
        
        # 状态文本
        self._status_label = QLabel()
        self._status_label.setObjectName("gaugeStatus")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #marginGauge {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #gaugeTitle {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #gaugeValue {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_LARGE_TITLE + 4}px;
                font-weight: bold;
            }}
            
            #marginProgress {{
                background-color: #e0e0e0;
                border: none;
                border-radius: 6px;
            }}
            
            #marginProgress::chunk {{
                border-radius: 6px;
            }}
            
            #gaugeStatus {{
                font-size: {FONT_SIZE_SMALL}px;
            }}
        """)
    
    def set_margin(self, margin: float):
        """设置裕度值"""
        self._margin = margin
        
        # 更新显示
        self._value_label.setText(f"{margin:.1f}%")
        
        # 进度条值（限制在 0-100）
        progress_value = max(0, min(100, margin))
        self._progress_bar.setValue(int(progress_value))
        
        # 根据裕度设置颜色和状态
        if margin >= MARGIN_GOOD_THRESHOLD:
            color = COLOR_SUCCESS
            status = self._get_text("wc.status.good", "裕度充足")
        elif margin >= MARGIN_WARN_THRESHOLD:
            color = COLOR_WARNING
            status = self._get_text("wc.status.warn", "裕度较小")
        elif margin >= 0:
            color = COLOR_ERROR
            status = self._get_text("wc.status.low", "裕度不足")
        else:
            color = COLOR_ERROR
            status = self._get_text("wc.status.fail", "不满足规格")
        
        self._value_label.setStyleSheet(f"""
            color: {color};
            font-size: {FONT_SIZE_LARGE_TITLE + 4}px;
            font-weight: bold;
        """)
        
        self._progress_bar.setStyleSheet(f"""
            #marginProgress {{
                background-color: #e0e0e0;
                border: none;
                border-radius: 6px;
            }}
            #marginProgress::chunk {{
                background-color: {color};
                border-radius: 6px;
            }}
        """)
        
        self._status_label.setText(status)
        self._status_label.setStyleSheet(f"color: {color}; font-size: {FONT_SIZE_SMALL}px;")
    
    def clear(self):
        """清空显示"""
        self._margin = 0.0
        self._value_label.setText("—")
        self._progress_bar.setValue(0)
        self._status_label.clear()
    
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
        self._title.setText(self._get_text("wc.design_margin", "设计裕度"))


class CriticalParamsTable(QTableWidget):
    """
    关键参数表格
    
    显示按影响程度排序的参数列表
    """
    
    param_selected = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("criticalParamsTable")
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        self.setColumnCount(4)
        self.setHorizontalHeaderLabels([
            self._get_text("wc.rank", "排名"),
            self._get_text("wc.parameter", "参数"),
            self._get_text("wc.sensitivity", "敏感度"),
            self._get_text("wc.direction", "方向"),
        ])
        
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        
        self.setColumnWidth(0, 50)
        self.setColumnWidth(2, 80)
        self.setColumnWidth(3, 60)
        
        self.cellClicked.connect(self._on_cell_clicked)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            QTableWidget {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                gridline-color: {COLOR_BORDER};
            }}
            
            QTableWidget::item {{
                padding: 6px;
            }}
            
            QTableWidget::item:selected {{
                background-color: {COLOR_ACCENT_LIGHT};
                color: {COLOR_TEXT_PRIMARY};
            }}
            
            QHeaderView::section {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_PRIMARY};
                padding: 8px;
                border: none;
                border-bottom: 1px solid {COLOR_BORDER};
                font-weight: bold;
            }}
        """)
    
    def set_params(self, sensitivities: List[Any]):
        """设置参数敏感度数据"""
        self.setRowCount(len(sensitivities))
        
        for idx, sens in enumerate(sensitivities):
            # 排名
            rank_item = QTableWidgetItem(str(idx + 1))
            rank_item.setFlags(rank_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            rank_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(idx, 0, rank_item)
            
            # 参数名
            param_key = getattr(sens, 'param_key', str(sens))
            param_item = QTableWidgetItem(param_key)
            param_item.setFlags(param_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(idx, 1, param_item)
            
            # 敏感度系数
            sens_coef = getattr(sens, 'sensitivity_coefficient', 0.0)
            sens_item = QTableWidgetItem(f"{sens_coef:.4g}")
            sens_item.setFlags(sens_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            sens_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(idx, 2, sens_item)
            
            # 影响方向
            direction = getattr(sens, 'influence_direction', 0)
            if direction > 0:
                dir_text = "↑"
                dir_color = COLOR_SUCCESS
            elif direction < 0:
                dir_text = "↓"
                dir_color = COLOR_ERROR
            else:
                dir_text = "↔"
                dir_color = COLOR_WARNING
            
            dir_item = QTableWidgetItem(dir_text)
            dir_item.setFlags(dir_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            dir_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            dir_item.setForeground(QColor(dir_color))
            self.setItem(idx, 3, dir_item)
    
    def _on_cell_clicked(self, row: int, col: int):
        """处理单元格点击"""
        param_item = self.item(row, 1)
        if param_item:
            self.param_selected.emit(param_item.text())
    
    def clear_data(self):
        """清空数据"""
        self.setRowCount(0)
    
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
        self.setHorizontalHeaderLabels([
            self._get_text("wc.rank", "排名"),
            self._get_text("wc.parameter", "参数"),
            self._get_text("wc.sensitivity", "敏感度"),
            self._get_text("wc.direction", "方向"),
        ])



# ============================================================
# WorstCaseResultTab - 主组件
# ============================================================

class WorstCaseResultTab(QWidget):
    """
    最坏情况分析结果标签页
    
    展示最坏情况分析结果，显示设计裕度和关键参数。
    
    Signals:
        export_requested: 请求导出数据
    """
    
    export_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # 数据
        self._wc_result: Optional[Any] = None
        
        # EventBus 引用
        self._event_bus = None
        self._subscriptions: List[tuple] = []
        
        # 初始化 UI
        self._setup_ui()
        self._apply_style()
        
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
        
        # 顶部：方法选择器
        self._method_selector = MethodSelector()
        main_layout.addWidget(self._method_selector)
        
        # 主内容区
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        content_layout.setSpacing(SPACING_NORMAL)
        
        # 左侧面板
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(SPACING_NORMAL)
        
        # 结果摘要卡片
        self._summary_card = ResultSummaryCard()
        left_layout.addWidget(self._summary_card)
        
        # 裕度仪表盘
        self._margin_gauge = MarginGauge()
        left_layout.addWidget(self._margin_gauge)
        
        left_layout.addStretch(1)
        
        left_panel.setFixedWidth(280)
        content_layout.addWidget(left_panel)
        
        # 右侧：关键参数表格
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(SPACING_SMALL)
        
        # 表格标题
        table_title = QLabel(self._get_text("wc.critical_params", "关键参数（按影响程度排序）"))
        table_title.setObjectName("tableTitle")
        table_title.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: {FONT_SIZE_NORMAL}px; font-weight: bold;")
        right_layout.addWidget(table_title)
        self._table_title = table_title
        
        self._params_table = CriticalParamsTable()
        right_layout.addWidget(self._params_table, 1)
        
        content_layout.addWidget(right_panel, 1)
        
        main_layout.addWidget(content_widget, 1)
        
        # 底部：操作栏
        self._action_bar = QFrame()
        self._action_bar.setObjectName("actionBar")
        self._action_bar.setFixedHeight(48)
        action_layout = QHBoxLayout(self._action_bar)
        action_layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        
        # 仿真次数
        self._sim_count_label = QLabel()
        self._sim_count_label.setObjectName("simCountLabel")
        action_layout.addWidget(self._sim_count_label)
        
        action_layout.addStretch(1)
        
        # 导出按钮
        self._export_btn = QPushButton()
        self._export_btn.setObjectName("exportBtn")
        self._export_btn.clicked.connect(self._on_export_clicked)
        action_layout.addWidget(self._export_btn)
        
        main_layout.addWidget(self._action_bar)
        
        # 空状态提示
        self._empty_widget = QFrame()
        self._empty_widget.setObjectName("emptyWidget")
        empty_layout = QVBoxLayout(self._empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self._empty_label = QLabel()
        self._empty_label.setObjectName("emptyLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._empty_label)
        
        main_layout.addWidget(self._empty_widget)
        
        # 初始显示空状态
        self._show_empty_state()
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            WorstCaseResultTab {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #actionBar {{
                background-color: {COLOR_BG_SECONDARY};
                border-top: 1px solid {COLOR_BORDER};
            }}
            
            #simCountLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #exportBtn {{
                background-color: {COLOR_ACCENT};
                color: white;
                border: none;
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 8px 16px;
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #exportBtn:hover {{
                background-color: {COLOR_ACCENT};
                opacity: 0.9;
            }}
            
            #emptyWidget {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #emptyLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
        """)
    
    def _subscribe_events(self):
        """订阅事件"""
        event_bus = self._get_event_bus()
        if not event_bus:
            return
        
        from shared.event_types import EVENT_WORST_CASE_COMPLETE, EVENT_LANGUAGE_CHANGED
        
        subscriptions = [
            (EVENT_WORST_CASE_COMPLETE, self._on_wc_complete),
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
    
    # ============================================================
    # 公开方法
    # ============================================================
    
    def update_results(self, wc_result: Any):
        """
        更新最坏情况分析结果显示
        
        Args:
            wc_result: WorstCaseResult 对象
        """
        self._wc_result = wc_result
        
        if wc_result is None:
            self._show_empty_state()
            return
        
        self._show_content_state()
        
        # 更新方法和指标
        method = getattr(wc_result, 'method', None)
        if method:
            method_value = method.value if hasattr(method, 'value') else str(method)
            self._method_selector.set_method(method_value)
        
        metric = getattr(wc_result, 'metric', '')
        self._method_selector.set_metric(metric)
        
        # 更新结果摘要
        nominal = getattr(wc_result, 'nominal_value', 0.0)
        wc_max = getattr(wc_result, 'worst_case_max', 0.0)
        wc_min = getattr(wc_result, 'worst_case_min', 0.0)
        margin = getattr(wc_result, 'design_margin_percent', 0.0)
        
        self._summary_card.set_values(nominal, wc_max, wc_min, margin)
        self._margin_gauge.set_margin(margin)
        
        # 更新关键参数表格
        sensitivities = getattr(wc_result, 'sensitivities', [])
        self._params_table.set_params(sensitivities)
        
        # 更新仿真次数
        sim_count = getattr(wc_result, 'simulation_count', 0)
        self._sim_count_label.setText(
            self._get_text("wc.sim_count", "仿真次数:") + f" {sim_count}"
        )
    
    def _show_empty_state(self):
        """显示空状态"""
        self._method_selector.hide()
        self._summary_card.hide()
        self._margin_gauge.hide()
        self._params_table.hide()
        self._table_title.hide()
        self._action_bar.hide()
        
        self._empty_label.setText(self._get_text(
            "wc.no_results",
            "暂无最坏情况分析结果"
        ))
        self._empty_widget.show()
    
    def _show_content_state(self):
        """显示内容状态"""
        self._empty_widget.hide()
        
        self._method_selector.show()
        self._summary_card.show()
        self._margin_gauge.show()
        self._params_table.show()
        self._table_title.show()
        self._action_bar.show()
    
    # ============================================================
    # 事件处理
    # ============================================================
    
    def _on_wc_complete(self, event_data: Dict[str, Any]):
        """处理最坏情况分析完成事件"""
        result = event_data.get("result")
        if result:
            self.update_results(result)
    
    def _on_language_changed(self, event_data: Dict[str, Any]):
        """处理语言变更事件"""
        self.retranslate_ui()
    
    def _on_export_clicked(self):
        """处理导出按钮点击"""
        self.export_requested.emit()
    
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
        self._export_btn.setText(self._get_text("wc.export", "导出报告"))
        self._empty_label.setText(self._get_text("wc.no_results", "暂无最坏情况分析结果"))
        self._table_title.setText(self._get_text("wc.critical_params", "关键参数（按影响程度排序）"))
        
        self._method_selector.retranslate_ui()
        self._summary_card.retranslate_ui()
        self._margin_gauge.retranslate_ui()
        self._params_table.retranslate_ui()
    
    def closeEvent(self, event):
        """关闭事件"""
        self._unsubscribe_events()
        super().closeEvent(event)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "WorstCaseResultTab",
]
