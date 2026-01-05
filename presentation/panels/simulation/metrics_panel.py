# MetricsPanel - Performance Metrics Display Panel
"""
指标显示面板

职责：
- 专注于指标网格布局和综合评分显示
- 管理多个 MetricCard 的布局和更新
- 显示综合评分进度条

设计原则：
- 使用 QWidget 作为基类
- 从 SimulationViewModel 获取 DisplayMetric 列表
- 使用 FlowLayout 实现自适应网格布局
- 支持国际化

被调用方：
- simulation_tab.py

使用示例：
    from presentation.panels.simulation.metrics_panel import MetricsPanel
    
    panel = MetricsPanel()
    panel.update_metrics(view_model.metrics_list)
    panel.set_overall_score(85.5)
"""

from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QFrame,
    QSizePolicy,
)

from presentation.panels.simulation.metric_card import MetricCard
from presentation.panels.simulation.simulation_view_model import DisplayMetric
from resources.theme import (
    COLOR_BG_SECONDARY,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_ACCENT,
    COLOR_BORDER,
    FONT_SIZE_NORMAL,
    FONT_SIZE_TITLE,
    SPACING_SMALL,
    SPACING_NORMAL,
    SPACING_LARGE,
    BORDER_RADIUS_NORMAL,
)


class FlowLayout(QVBoxLayout):
    """
    流式布局 - 自适应网格
    
    根据容器宽度自动调整每行卡片数量（2-3列）
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: List[QHBoxLayout] = []
        self._cards: List[MetricCard] = []
        self._min_card_width = 160
        self._max_columns = 3
        self._spacing = SPACING_NORMAL
        
        self.setSpacing(self._spacing)
        self.setContentsMargins(0, 0, 0, 0)
    
    def add_card(self, card: MetricCard):
        """添加卡片到布局"""
        self._cards.append(card)
    
    def relayout(self, container_width: int):
        """根据容器宽度重新布局"""
        # 清除现有行
        for row in self._rows:
            while row.count():
                item = row.takeAt(0)
                if item.widget():
                    item.widget().setParent(None)
            self.removeItem(row)
        self._rows.clear()
        
        if not self._cards or container_width <= 0:
            return
        
        # 计算列数
        available_width = container_width - self._spacing * 2
        columns = max(2, min(self._max_columns, available_width // self._min_card_width))
        
        # 创建行并分配卡片
        current_row = None
        for i, card in enumerate(self._cards):
            if i % columns == 0:
                current_row = QHBoxLayout()
                current_row.setSpacing(self._spacing)
                self._rows.append(current_row)
                self.addLayout(current_row)
            
            current_row.addWidget(card)
        
        # 填充最后一行的空位
        if current_row and len(self._cards) % columns != 0:
            remaining = columns - (len(self._cards) % columns)
            for _ in range(remaining):
                current_row.addStretch(1)
    
    def clear_cards(self):
        """清除所有卡片"""
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()
        
        for row in self._rows:
            while row.count():
                item = row.takeAt(0)
                if item.widget():
                    item.widget().setParent(None)
            self.removeItem(row)
        self._rows.clear()


class MetricsPanel(QWidget):
    """
    指标显示面板
    
    显示性能指标网格和综合评分。
    
    Signals:
        metric_clicked: 指标卡片被点击时发出，携带指标名称
    """
    
    metric_clicked = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 内部状态
        self._metrics: List[DisplayMetric] = []
        self._cards: List[MetricCard] = []
        self._overall_score: float = 0.0
        
        # 初始化 UI
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI 组件"""
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(
            SPACING_NORMAL, SPACING_NORMAL,
            SPACING_NORMAL, SPACING_NORMAL
        )
        main_layout.setSpacing(SPACING_NORMAL)
        
        # 综合评分区域
        self._score_frame = QFrame()
        self._score_frame.setObjectName("scoreFrame")
        score_layout = QVBoxLayout(self._score_frame)
        score_layout.setContentsMargins(
            SPACING_NORMAL, SPACING_SMALL,
            SPACING_NORMAL, SPACING_SMALL
        )
        score_layout.setSpacing(SPACING_SMALL)
        
        # 评分标题行
        score_header = QHBoxLayout()
        self._score_title = QLabel()
        self._score_title.setObjectName("scoreTitle")
        score_header.addWidget(self._score_title)
        
        self._score_value = QLabel("0%")
        self._score_value.setObjectName("scoreValue")
        self._score_value.setAlignment(Qt.AlignmentFlag.AlignRight)
        score_header.addWidget(self._score_value)
        
        score_layout.addLayout(score_header)
        
        # 评分进度条
        self._score_bar = QProgressBar()
        self._score_bar.setObjectName("scoreBar")
        self._score_bar.setRange(0, 100)
        self._score_bar.setValue(0)
        self._score_bar.setTextVisible(False)
        self._score_bar.setFixedHeight(8)
        score_layout.addWidget(self._score_bar)
        
        main_layout.addWidget(self._score_frame)
        
        # 指标网格滚动区域
        self._scroll_area = QScrollArea()
        self._scroll_area.setObjectName("metricsScrollArea")
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        
        # 指标容器
        self._metrics_container = QWidget()
        self._metrics_container.setObjectName("metricsContainer")
        self._flow_layout = FlowLayout(self._metrics_container)
        
        self._scroll_area.setWidget(self._metrics_container)
        main_layout.addWidget(self._scroll_area, 1)
        
        # 空状态提示
        self._empty_label = QLabel()
        self._empty_label.setObjectName("emptyLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.hide()
        main_layout.addWidget(self._empty_label)
        
        # 初始化文本
        self.retranslate_ui()
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            MetricsPanel {{
                background-color: {COLOR_BG_SECONDARY};
            }}
            
            #scoreFrame {{
                background-color: white;
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #scoreTitle {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #scoreValue {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_TITLE}px;
                font-weight: bold;
            }}
            
            #scoreBar {{
                background-color: #e0e0e0;
                border: none;
                border-radius: 4px;
            }}
            
            #scoreBar::chunk {{
                background-color: {COLOR_ACCENT};
                border-radius: 4px;
            }}
            
            #metricsScrollArea {{
                background-color: transparent;
            }}
            
            #metricsContainer {{
                background-color: transparent;
            }}
            
            #emptyLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
        """)
    
    def update_metrics(self, metrics_list: List[DisplayMetric]):
        """
        更新所有指标卡片
        
        Args:
            metrics_list: DisplayMetric 列表
        """
        self._metrics = metrics_list
        
        # 清除现有卡片
        self._flow_layout.clear_cards()
        self._cards.clear()
        
        if not metrics_list:
            self._show_empty_state()
            return
        
        self._hide_empty_state()
        
        # 创建新卡片
        for metric in metrics_list:
            card = MetricCard(self._metrics_container)
            card.set_from_display_metric(metric)
            card.clicked.connect(self._on_card_clicked)
            self._cards.append(card)
            self._flow_layout.add_card(card)
        
        # 触发重新布局
        self._relayout()
    
    def set_overall_score(self, score: float):
        """
        设置综合评分
        
        Args:
            score: 评分值（0-100）
        """
        self._overall_score = max(0.0, min(100.0, score))
        self._score_value.setText(f"{self._overall_score:.1f}%")
        self._score_bar.setValue(int(self._overall_score))
    
    def clear(self):
        """清空所有指标"""
        self._metrics.clear()
        self._flow_layout.clear_cards()
        self._cards.clear()
        self._overall_score = 0.0
        self._score_value.setText("0%")
        self._score_bar.setValue(0)
        self._show_empty_state()
    
    def highlight_metric(self, metric_name: str, enabled: bool = True):
        """
        高亮指定指标卡片
        
        Args:
            metric_name: 指标名称
            enabled: 是否高亮
        """
        for card in self._cards:
            if card.metric_name == metric_name:
                card.set_highlight(enabled)
                break
    
    def get_metric_card(self, metric_name: str) -> Optional[MetricCard]:
        """
        获取指定指标的卡片
        
        Args:
            metric_name: 指标名称
            
        Returns:
            MetricCard 或 None
        """
        for card in self._cards:
            if card.metric_name == metric_name:
                return card
        return None
    
    def _on_card_clicked(self, metric_name: str):
        """处理卡片点击"""
        self.metric_clicked.emit(metric_name)
    
    def _show_empty_state(self):
        """显示空状态"""
        self._scroll_area.hide()
        self._empty_label.show()
    
    def _hide_empty_state(self):
        """隐藏空状态"""
        self._empty_label.hide()
        self._scroll_area.show()
    
    def _relayout(self):
        """重新布局卡片"""
        container_width = self._scroll_area.viewport().width()
        if container_width > 0:
            self._flow_layout.relayout(container_width)
    
    def resizeEvent(self, event):
        """处理窗口大小变化"""
        super().resizeEvent(event)
        self._relayout()
    
    def showEvent(self, event):
        """处理显示事件"""
        super().showEvent(event)
        # 延迟重新布局，确保尺寸已计算
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._relayout)
    
    def retranslate_ui(self):
        """重新翻译 UI 文本（国际化支持）"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            self._score_title.setText(
                i18n.get_text("simulation.overall_score", default="Overall Score")
            )
            self._empty_label.setText(
                i18n.get_text("simulation.no_metrics", default="No metrics available")
            )
        except ImportError:
            self._score_title.setText("Overall Score")
            self._empty_label.setText("No metrics available")
    
    @property
    def metrics(self) -> List[DisplayMetric]:
        """获取当前指标列表"""
        return self._metrics.copy()
    
    @property
    def overall_score(self) -> float:
        """获取综合评分"""
        return self._overall_score
    
    @property
    def card_count(self) -> int:
        """获取卡片数量"""
        return len(self._cards)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "MetricsPanel",
    "FlowLayout",
]
