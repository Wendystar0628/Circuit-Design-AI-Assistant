# MetricCard - Performance Metric Card Component
"""
指标卡片组件

职责：
- 专注于单个性能指标的卡片式渲染
- 显示指标名称、数值、单位、目标值、达标状态
- 支持高亮状态和趋势指示

设计原则：
- 使用 QFrame 作为基类，便于样式控制
- 从 DisplayMetric 数据类获取显示数据
- 使用 theme.py 中的色彩规范

使用示例：
    from presentation.panels.simulation.metric_card import MetricCard
    
    card = MetricCard()
    card.set_metric(
        name="gain",
        value="20.5 dB",
        unit="dB",
        target="≥ 20 dB",
        is_met=True
    )
"""

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
)

from resources.theme import (
    COLOR_BG_SECONDARY,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_TEXT_TERTIARY,
    COLOR_SUCCESS,
    COLOR_ERROR,
    COLOR_ACCENT,
    COLOR_ACCENT_LIGHT,
    COLOR_BORDER,
    BORDER_RADIUS_LARGE,
    FONT_SIZE_SMALL,
    FONT_SIZE_NORMAL,
    FONT_SIZE_TITLE,
    SPACING_SMALL,
    SPACING_NORMAL,
)


# ============================================================
# 样式常量
# ============================================================

CARD_BG_NORMAL = "#f0f4f8"
CARD_BG_HIGHLIGHT = COLOR_ACCENT_LIGHT
CARD_MIN_WIDTH = 140
CARD_MIN_HEIGHT = 80


class MetricCard(QFrame):
    """
    指标卡片组件
    
    显示单个性能指标的卡片，包含指标名称、数值、目标值和达标状态。
    
    Signals:
        clicked: 卡片被点击时发出
    """
    
    clicked = pyqtSignal(str)  # 发出指标名称
    
    def __init__(self, parent=None):
        """
        初始化指标卡片
        
        Args:
            parent: 父组件
        """
        super().__init__(parent)
        
        # 内部状态
        self._metric_name: str = ""
        self._is_highlighted: bool = False
        self._is_met: Optional[bool] = None
        
        # 初始化 UI
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI 组件"""
        self.setMinimumSize(CARD_MIN_WIDTH, CARD_MIN_HEIGHT)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # 主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            SPACING_NORMAL, SPACING_NORMAL,
            SPACING_NORMAL, SPACING_NORMAL
        )
        layout.setSpacing(SPACING_SMALL)
        
        # 顶部行：指标名称 + 状态图标
        top_row = QHBoxLayout()
        top_row.setSpacing(SPACING_SMALL)
        
        # 指标名称
        self._name_label = QLabel()
        self._name_label.setStyleSheet(f"""
            color: {COLOR_TEXT_SECONDARY};
            font-size: {FONT_SIZE_SMALL}px;
        """)
        top_row.addWidget(self._name_label, 1)
        
        # 状态图标
        self._status_icon = QLabel()
        self._status_icon.setFixedSize(16, 16)
        self._status_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(self._status_icon)
        
        layout.addLayout(top_row)
        
        # 指标数值
        self._value_label = QLabel()
        self._value_label.setStyleSheet(f"""
            color: {COLOR_TEXT_PRIMARY};
            font-size: {FONT_SIZE_TITLE}px;
            font-weight: bold;
        """)
        layout.addWidget(self._value_label)
        
        # 底部行：目标值 + 趋势
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(SPACING_SMALL)
        
        # 目标值
        self._target_label = QLabel()
        self._target_label.setStyleSheet(f"""
            color: {COLOR_TEXT_TERTIARY};
            font-size: {FONT_SIZE_SMALL}px;
        """)
        bottom_row.addWidget(self._target_label, 1)
        
        # 趋势指示
        self._trend_label = QLabel()
        self._trend_label.setFixedWidth(16)
        self._trend_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom_row.addWidget(self._trend_label)
        
        layout.addLayout(bottom_row)
    
    def _apply_style(self):
        """应用卡片样式"""
        bg_color = CARD_BG_HIGHLIGHT if self._is_highlighted else CARD_BG_NORMAL
        
        self.setStyleSheet(f"""
            MetricCard {{
                background-color: {bg_color};
                border-radius: {BORDER_RADIUS_LARGE}px;
                border: 1px solid {COLOR_BORDER};
            }}
            MetricCard:hover {{
                border: 1px solid {COLOR_ACCENT};
            }}
        """)
    
    def set_metric(
        self,
        name: str,
        value: str,
        unit: str = "",
        target: str = "",
        is_met: Optional[bool] = None,
        trend: str = "unknown"
    ):
        """
        设置指标数据
        
        Args:
            name: 指标显示名称
            value: 格式化后的数值字符串（如 "20.5 dB"）
            unit: 单位（可选，若 value 已包含单位则留空）
            target: 目标值描述（如 "≥ 20 dB"）
            is_met: 是否达标（None 表示无目标）
            trend: 趋势（"up", "down", "stable", "unknown"）
        """
        self._metric_name = name
        self._is_met = is_met
        
        # 更新名称
        self._name_label.setText(name)
        
        # 更新数值
        display_value = value if not unit or unit in value else f"{value} {unit}"
        self._value_label.setText(display_value)
        
        # 更新目标
        self._target_label.setText(target)
        self._target_label.setVisible(bool(target))
        
        # 更新状态图标
        self._update_status_icon(is_met)
        
        # 更新趋势
        self._update_trend_icon(trend)
    
    def _update_status_icon(self, is_met: Optional[bool]):
        """更新达标状态图标"""
        if is_met is None:
            self._status_icon.setText("")
            self._status_icon.setStyleSheet("")
        elif is_met:
            self._status_icon.setText("✓")
            self._status_icon.setStyleSheet(f"""
                color: {COLOR_SUCCESS};
                font-size: 14px;
                font-weight: bold;
            """)
        else:
            self._status_icon.setText("✗")
            self._status_icon.setStyleSheet(f"""
                color: {COLOR_ERROR};
                font-size: 14px;
                font-weight: bold;
            """)
    
    def _update_trend_icon(self, trend: str):
        """更新趋势指示图标"""
        trend_icons = {
            "up": ("↑", COLOR_SUCCESS),
            "down": ("↓", COLOR_ERROR),
            "stable": ("→", COLOR_TEXT_TERTIARY),
            "unknown": ("", ""),
        }
        
        icon, color = trend_icons.get(trend, ("", ""))
        self._trend_label.setText(icon)
        if color:
            self._trend_label.setStyleSheet(f"""
                color: {color};
                font-size: 12px;
                font-weight: bold;
            """)
    
    def set_highlight(self, enabled: bool):
        """
        设置高亮状态
        
        Args:
            enabled: 是否高亮
        """
        if self._is_highlighted != enabled:
            self._is_highlighted = enabled
            self._apply_style()
    
    def update_status(self, is_met: Optional[bool]):
        """
        更新达标状态
        
        Args:
            is_met: 是否达标（None 表示无目标）
        """
        self._is_met = is_met
        self._update_status_icon(is_met)
    
    def set_from_display_metric(self, metric: 'DisplayMetric'):
        """
        从 DisplayMetric 对象设置卡片数据
        
        Args:
            metric: DisplayMetric 数据对象
        """
        self.set_metric(
            name=metric.display_name,
            value=metric.value,
            unit=metric.unit,
            target=metric.target,
            is_met=metric.is_met,
            trend=metric.trend
        )
    
    def mousePressEvent(self, event):
        """处理鼠标点击事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._metric_name)
        super().mousePressEvent(event)
    
    def retranslate_ui(self):
        """
        重新翻译 UI 文本（国际化支持）
        
        注意：指标名称和目标值由外部传入，此方法预留用于
        未来可能的静态文本国际化。
        """
        pass
    
    @property
    def metric_name(self) -> str:
        """获取指标名称"""
        return self._metric_name
    
    @property
    def is_met(self) -> Optional[bool]:
        """获取达标状态"""
        return self._is_met
    
    @property
    def is_highlighted(self) -> bool:
        """获取高亮状态"""
        return self._is_highlighted


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "MetricCard",
]
