# SensitivityResultTab - Sensitivity Analysis Result Tab
"""
敏感度分析结果标签页

职责：
- 展示敏感度分析结果
- 显示龙卷风图和敏感度排名
- 提供优化建议

设计原则：
- 使用 QWidget 作为基类
- 订阅 EVENT_SENSITIVITY_COMPLETE 事件自动更新
- 支持国际化

被调用方：
- simulation_tab.py
"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QFrame,
    QLabel,
    QPushButton,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSizePolicy,
    QGroupBox,
    QScrollArea,
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
    SPACING_SMALL,
    SPACING_NORMAL,
    SPACING_LARGE,
    BORDER_RADIUS_NORMAL,
)


# ============================================================
# 子组件
# ============================================================

class MetricSelectorBar(QFrame):
    """
    指标选择器栏
    """
    
    metric_changed = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("metricSelectorBar")
        self.setFixedHeight(48)
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        layout.setSpacing(SPACING_NORMAL)
        
        # 标签
        label = QLabel(self._get_text("sens.select_metric", "分析指标:"))
        label.setObjectName("selectorLabel")
        layout.addWidget(label)
        self._label = label
        
        # 指标显示
        self._metric_value = QLabel("—")
        self._metric_value.setObjectName("metricValue")
        layout.addWidget(self._metric_value)
        
        layout.addStretch(1)
        
        # 扰动量显示
        perturb_label = QLabel(self._get_text("sens.perturbation", "扰动量:"))
        perturb_label.setObjectName("selectorLabel")
        layout.addWidget(perturb_label)
        
        self._perturb_value = QLabel("—")
        self._perturb_value.setObjectName("perturbValue")
        layout.addWidget(self._perturb_value)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #metricSelectorBar {{
                background-color: {COLOR_BG_SECONDARY};
                border-bottom: 1px solid {COLOR_BORDER};
            }}
            
            #selectorLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #metricValue, #perturbValue {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
                font-weight: bold;
            }}
        """)
    
    def set_metric(self, metric: str):
        """设置指标"""
        self._metric_value.setText(metric)
    
    def set_perturbation(self, percent: float):
        """设置扰动量"""
        self._perturb_value.setText(f"±{percent}%")
    
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
        self._label.setText(self._get_text("sens.select_metric", "分析指标:"))


class TornadoChart(QFrame):
    """
    龙卷风图组件
    
    显示参数敏感度的水平条形图
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("tornadoChart")
        
        self._plot_widget = None
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        try:
            import pyqtgraph as pg
            
            pg.setConfigOptions(antialias=True, background='w', foreground='k')
            
            self._plot_widget = pg.PlotWidget()
            self._plot_widget.setObjectName("tornadoPlot")
            self._plot_widget.showGrid(x=True, y=False, alpha=0.3)
            self._plot_widget.setLabel('bottom', self._get_text("sens.impact", "影响量"))
            
            # 隐藏 Y 轴刻度（使用自定义标签）
            self._plot_widget.getAxis('left').setTicks([])
            
            layout.addWidget(self._plot_widget)
            
        except ImportError:
            placeholder = QLabel(self._get_text(
                "sens.pyqtgraph_missing",
                "龙卷风图需要 pyqtgraph 库"
            ))
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
            layout.addWidget(placeholder)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #tornadoChart {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
        """)
    
    def update_tornado(
        self,
        param_names: List[str],
        positive_impacts: List[float],
        negative_impacts: List[float],
        baseline: float
    ):
        """
        更新龙卷风图
        
        Args:
            param_names: 参数名列表
            positive_impacts: 正向影响值
            negative_impacts: 负向影响值
            baseline: 基准值
        """
        if self._plot_widget is None or not param_names:
            return
        
        try:
            import pyqtgraph as pg
            
            self._plot_widget.clear()
            
            n = len(param_names)
            y_positions = list(range(n))
            
            # 绘制正向影响（右侧，蓝色）
            for i, (pos, impact) in enumerate(zip(y_positions, positive_impacts)):
                if impact > 0:
                    bar = pg.BarGraphItem(
                        x0=0, x1=impact, y=pos, height=0.6,
                        brush=pg.mkBrush('#2196F3'),
                        pen=pg.mkPen('#1976D2', width=1)
                    )
                    self._plot_widget.addItem(bar)
                elif impact < 0:
                    bar = pg.BarGraphItem(
                        x0=impact, x1=0, y=pos, height=0.6,
                        brush=pg.mkBrush('#2196F3'),
                        pen=pg.mkPen('#1976D2', width=1)
                    )
                    self._plot_widget.addItem(bar)
            
            # 绘制负向影响（左侧，橙色）
            for i, (pos, impact) in enumerate(zip(y_positions, negative_impacts)):
                if impact < 0:
                    bar = pg.BarGraphItem(
                        x0=impact, x1=0, y=pos, height=0.6,
                        brush=pg.mkBrush('#FF9800'),
                        pen=pg.mkPen('#F57C00', width=1)
                    )
                    self._plot_widget.addItem(bar)
                elif impact > 0:
                    bar = pg.BarGraphItem(
                        x0=0, x1=impact, y=pos, height=0.6,
                        brush=pg.mkBrush('#FF9800'),
                        pen=pg.mkPen('#F57C00', width=1)
                    )
                    self._plot_widget.addItem(bar)
            
            # 添加基准线
            baseline_line = pg.InfiniteLine(
                pos=0, angle=90,
                pen=pg.mkPen('k', width=2, style=Qt.PenStyle.DashLine)
            )
            self._plot_widget.addItem(baseline_line)
            
            # 设置 Y 轴标签
            y_axis = self._plot_widget.getAxis('left')
            ticks = [(i, name) for i, name in enumerate(param_names)]
            y_axis.setTicks([ticks])
            
            # 自动缩放
            self._plot_widget.autoRange()
            
        except Exception as e:
            logging.getLogger(__name__).warning(f"更新龙卷风图失败: {e}")
    
    def clear(self):
        """清空图表"""
        if self._plot_widget:
            self._plot_widget.clear()
    
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
        if self._plot_widget:
            self._plot_widget.setLabel('bottom', self._get_text("sens.impact", "影响量"))


class SensitivityRankingTable(QTableWidget):
    """
    敏感度排名表格
    """
    
    param_selected = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("sensitivityRankingTable")
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        self.setColumnCount(5)
        self.setHorizontalHeaderLabels([
            self._get_text("sens.rank", "排名"),
            self._get_text("sens.parameter", "参数"),
            self._get_text("sens.abs_sens", "绝对敏感度"),
            self._get_text("sens.rel_sens", "相对敏感度"),
            self._get_text("sens.direction", "方向"),
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
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        
        self.setColumnWidth(0, 50)
        self.setColumnWidth(2, 100)
        self.setColumnWidth(3, 100)
        self.setColumnWidth(4, 60)
        
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
    
    def set_sensitivities(self, sensitivities: List[Any]):
        """设置敏感度数据"""
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
            
            # 绝对敏感度
            abs_sens = getattr(sens, 'absolute_sensitivity', 0.0)
            abs_item = QTableWidgetItem(f"{abs_sens:.4g}")
            abs_item.setFlags(abs_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            abs_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(idx, 2, abs_item)
            
            # 相对敏感度
            rel_sens = getattr(sens, 'relative_sensitivity', 0.0)
            rel_item = QTableWidgetItem(f"{rel_sens:.4g}")
            rel_item.setFlags(rel_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            rel_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(idx, 3, rel_item)
            
            # 方向
            direction = getattr(sens, 'direction', 'positive')
            if direction == 'positive':
                dir_text = "正相关"
                dir_color = COLOR_SUCCESS
            elif direction == 'negative':
                dir_text = "负相关"
                dir_color = COLOR_ERROR
            else:
                dir_text = "非单调"
                dir_color = COLOR_WARNING
            
            dir_item = QTableWidgetItem(dir_text)
            dir_item.setFlags(dir_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            dir_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            dir_item.setForeground(QColor(dir_color))
            self.setItem(idx, 4, dir_item)
    
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
            self._get_text("sens.rank", "排名"),
            self._get_text("sens.parameter", "参数"),
            self._get_text("sens.abs_sens", "绝对敏感度"),
            self._get_text("sens.rel_sens", "相对敏感度"),
            self._get_text("sens.direction", "方向"),
        ])


class OptimizationSuggestionsPanel(QFrame):
    """
    优化建议面板
    """
    
    suggestion_applied = pyqtSignal(str, str)  # param_key, action
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("optimizationSuggestionsPanel")
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_SMALL)
        
        # 标题
        title = QLabel(self._get_text("sens.suggestions", "优化建议"))
        title.setObjectName("panelTitle")
        layout.addWidget(title)
        self._title = title
        
        # 建议列表容器
        self._suggestions_frame = QFrame()
        self._suggestions_layout = QVBoxLayout(self._suggestions_frame)
        self._suggestions_layout.setContentsMargins(0, SPACING_SMALL, 0, 0)
        self._suggestions_layout.setSpacing(SPACING_SMALL)
        layout.addWidget(self._suggestions_frame)
        
        layout.addStretch(1)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #optimizationSuggestionsPanel {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #panelTitle {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
                font-weight: bold;
            }}
        """)
    
    def set_suggestions(self, suggestions: List[Any]):
        """设置优化建议"""
        # 清除旧内容
        while self._suggestions_layout.count():
            item = self._suggestions_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # 添加建议
        for suggestion in suggestions:
            card = self._create_suggestion_card(suggestion)
            self._suggestions_layout.addWidget(card)
    
    def _create_suggestion_card(self, suggestion: Any) -> QFrame:
        """创建建议卡片"""
        card = QFrame()
        card.setObjectName("suggestionCard")
        card.setStyleSheet(f"""
            #suggestionCard {{
                background-color: {COLOR_BG_SECONDARY};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 8px;
            }}
        """)
        
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(SPACING_SMALL, SPACING_SMALL, SPACING_SMALL, SPACING_SMALL)
        card_layout.setSpacing(4)
        
        # 参数和动作
        param_key = getattr(suggestion, 'param_key', '')
        action = getattr(suggestion, 'action', '')
        priority = getattr(suggestion, 'priority', 3)
        reason = getattr(suggestion, 'reason', '')
        
        action_text = {
            'increase': '增大',
            'decrease': '减小',
            'fine_tune': '微调',
        }.get(action, action)
        
        # 标题行
        title_row = QHBoxLayout()
        
        param_label = QLabel(f"{param_key}")
        param_label.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-weight: bold;")
        title_row.addWidget(param_label)
        
        action_label = QLabel(f"→ {action_text}")
        action_label.setStyleSheet(f"color: {COLOR_ACCENT};")
        title_row.addWidget(action_label)
        
        title_row.addStretch(1)
        
        priority_label = QLabel(f"P{priority}")
        priority_color = COLOR_ERROR if priority <= 2 else (COLOR_WARNING if priority <= 3 else COLOR_TEXT_SECONDARY)
        priority_label.setStyleSheet(f"color: {priority_color}; font-size: {FONT_SIZE_SMALL}px;")
        title_row.addWidget(priority_label)
        
        card_layout.addLayout(title_row)
        
        # 原因
        if reason:
            reason_label = QLabel(reason)
            reason_label.setWordWrap(True)
            reason_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: {FONT_SIZE_SMALL}px;")
            card_layout.addWidget(reason_label)
        
        return card
    
    def clear(self):
        """清空建议"""
        while self._suggestions_layout.count():
            item = self._suggestions_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
    
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
        self._title.setText(self._get_text("sens.suggestions", "优化建议"))



# ============================================================
# SensitivityResultTab - 主组件
# ============================================================

class SensitivityResultTab(QWidget):
    """
    敏感度分析结果标签页
    
    展示敏感度分析结果，显示龙卷风图和优化建议。
    
    Signals:
        export_requested: 请求导出数据
    """
    
    export_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # 数据
        self._sens_result: Optional[Any] = None
        
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
        
        # 顶部：指标选择器
        self._metric_selector = MetricSelectorBar()
        main_layout.addWidget(self._metric_selector)
        
        # 主内容区（左右分栏）
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setObjectName("sensSplitter")
        self._splitter.setHandleWidth(1)
        self._splitter.setChildrenCollapsible(False)
        
        # 左侧：龙卷风图
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL)
        left_layout.setSpacing(SPACING_SMALL)
        
        # 龙卷风图标题
        tornado_title = QLabel(self._get_text("sens.tornado_chart", "龙卷风图"))
        tornado_title.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: {FONT_SIZE_NORMAL}px; font-weight: bold;")
        left_layout.addWidget(tornado_title)
        self._tornado_title = tornado_title
        
        self._tornado_chart = TornadoChart()
        left_layout.addWidget(self._tornado_chart, 1)
        
        self._splitter.addWidget(left_panel)
        
        # 右侧面板
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(SPACING_SMALL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        right_layout.setSpacing(SPACING_NORMAL)
        
        # 敏感度排名表格
        ranking_title = QLabel(self._get_text("sens.ranking", "敏感度排名"))
        ranking_title.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: {FONT_SIZE_NORMAL}px; font-weight: bold;")
        right_layout.addWidget(ranking_title)
        self._ranking_title = ranking_title
        
        self._ranking_table = SensitivityRankingTable()
        right_layout.addWidget(self._ranking_table, 1)
        
        # 优化建议面板
        self._suggestions_panel = OptimizationSuggestionsPanel()
        self._suggestions_panel.setMaximumHeight(200)
        right_layout.addWidget(self._suggestions_panel)
        
        self._splitter.addWidget(right_panel)
        
        # 设置初始比例（60:40）
        self._splitter.setSizes([600, 400])
        
        main_layout.addWidget(self._splitter, 1)
        
        # 底部：操作栏
        self._action_bar = QFrame()
        self._action_bar.setObjectName("actionBar")
        self._action_bar.setFixedHeight(48)
        action_layout = QHBoxLayout(self._action_bar)
        action_layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        
        # 统计信息
        self._stats_label = QLabel()
        self._stats_label.setObjectName("statsLabel")
        action_layout.addWidget(self._stats_label)
        
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
            SensitivityResultTab {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #sensSplitter {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #sensSplitter::handle {{
                background-color: {COLOR_BORDER};
            }}
            
            #actionBar {{
                background-color: {COLOR_BG_SECONDARY};
                border-top: 1px solid {COLOR_BORDER};
            }}
            
            #statsLabel {{
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
        
        from shared.event_types import EVENT_SENSITIVITY_COMPLETE, EVENT_LANGUAGE_CHANGED
        
        subscriptions = [
            (EVENT_SENSITIVITY_COMPLETE, self._on_sens_complete),
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
    
    def update_results(self, sens_result: Any):
        """
        更新敏感度分析结果显示
        
        Args:
            sens_result: SensitivityAnalysisResult 对象
        """
        self._sens_result = sens_result
        
        if sens_result is None:
            self._show_empty_state()
            return
        
        self._show_content_state()
        
        # 更新指标和扰动量
        metric = getattr(sens_result, 'metric_name', '')
        perturbation = getattr(sens_result, 'perturbation_percent', 1.0)
        
        self._metric_selector.set_metric(metric)
        self._metric_selector.set_perturbation(perturbation)
        
        # 更新龙卷风图
        tornado_data = getattr(sens_result, 'tornado_data', None)
        if tornado_data:
            param_names = getattr(tornado_data, 'param_names', [])
            positive_impacts = getattr(tornado_data, 'positive_impacts', [])
            negative_impacts = getattr(tornado_data, 'negative_impacts', [])
            baseline = getattr(tornado_data, 'baseline_value', 0.0)
            
            self._tornado_chart.update_tornado(
                param_names, positive_impacts, negative_impacts, baseline
            )
        else:
            self._tornado_chart.clear()
        
        # 更新敏感度排名表格
        sensitivities = getattr(sens_result, 'param_sensitivities', [])
        # 按归一化敏感度排序
        sorted_sens = sorted(
            sensitivities,
            key=lambda s: abs(getattr(s, 'normalized_sensitivity', 0)),
            reverse=True
        )
        self._ranking_table.set_sensitivities(sorted_sens)
        
        # 更新优化建议
        suggestions = getattr(sens_result, 'optimization_suggestions', [])
        if suggestions:
            self._suggestions_panel.set_suggestions(suggestions)
            self._suggestions_panel.show()
        else:
            self._suggestions_panel.clear()
            self._suggestions_panel.hide()
        
        # 更新统计信息
        sim_count = getattr(sens_result, 'simulation_count', 0)
        param_count = len(sensitivities)
        self._stats_label.setText(f"{param_count} 个参数, {sim_count} 次仿真")
    
    def _show_empty_state(self):
        """显示空状态"""
        self._metric_selector.hide()
        self._splitter.hide()
        self._action_bar.hide()
        
        self._empty_label.setText(self._get_text(
            "sens.no_results",
            "暂无敏感度分析结果"
        ))
        self._empty_widget.show()
    
    def _show_content_state(self):
        """显示内容状态"""
        self._empty_widget.hide()
        
        self._metric_selector.show()
        self._splitter.show()
        self._action_bar.show()
    
    # ============================================================
    # 事件处理
    # ============================================================
    
    def _on_sens_complete(self, event_data: Dict[str, Any]):
        """处理敏感度分析完成事件"""
        # 事件数据在 "data" 字段中
        data = event_data.get("data", event_data)
        result = data.get("result")
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
        self._export_btn.setText(self._get_text("sens.export", "导出数据"))
        self._empty_label.setText(self._get_text("sens.no_results", "暂无敏感度分析结果"))
        self._tornado_title.setText(self._get_text("sens.tornado_chart", "龙卷风图"))
        self._ranking_title.setText(self._get_text("sens.ranking", "敏感度排名"))
        
        self._metric_selector.retranslate_ui()
        self._tornado_chart.retranslate_ui()
        self._ranking_table.retranslate_ui()
        self._suggestions_panel.retranslate_ui()
    
    def closeEvent(self, event):
        """关闭事件"""
        self._unsubscribe_events()
        super().closeEvent(event)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SensitivityResultTab",
]
