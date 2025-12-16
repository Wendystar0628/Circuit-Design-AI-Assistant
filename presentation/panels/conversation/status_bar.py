# Status Bar Component
"""
状态栏组件

职责：
- 显示上下文占用状态
- 管理压缩按钮

信号：
- compress_clicked() - 压缩按钮点击
"""

from typing import Optional

from PyQt6.QtCore import pyqtSignal, QSize
from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLabel,
    QFrame,
    QProgressBar,
    QToolButton,
)


# ============================================================
# 常量定义
# ============================================================

STATUS_BAR_HEIGHT = 36
STATUS_BAR_BG = "#fafafa"
STATUS_BAR_BORDER = "#e0e0e0"

# 状态阈值
WARNING_THRESHOLD = 0.60
CRITICAL_THRESHOLD = 0.80

# 状态颜色
COLOR_NORMAL = "#4caf50"
COLOR_WARNING = "#ff9800"
COLOR_CRITICAL = "#f44336"

# 按钮状态
STATE_NORMAL = "normal"
STATE_WARNING = "warning"
STATE_CRITICAL = "critical"


# ============================================================
# StatusBar 类
# ============================================================

class StatusBar(QWidget):
    """
    对话面板状态栏组件
    
    显示上下文占用状态和压缩按钮。
    """
    
    # 信号定义
    compress_clicked = pyqtSignal()
    
    def __init__(self, parent: Optional[QWidget] = None):
        """初始化状态栏"""
        super().__init__(parent)
        
        # 延迟获取的服务
        self._i18n = None
        
        # 内部状态
        self._current_ratio: float = 0.0
        self._button_state: str = STATE_NORMAL
        self._current_tokens: int = 0
        self._max_tokens: int = 0
        
        # UI 组件引用
        self._progress_bar: Optional[QProgressBar] = None
        self._usage_label: Optional[QLabel] = None
        self._token_label: Optional[QLabel] = None
        self._compress_button: Optional[QToolButton] = None
        
        # 初始化 UI
        self._setup_ui()
    
    # ============================================================
    # 延迟获取服务
    # ============================================================
    
    @property
    def i18n(self):
        """延迟获取国际化管理器"""
        if self._i18n is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_I18N_MANAGER
                self._i18n = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            except Exception:
                pass
        return self._i18n
    
    def _get_text(self, key: str, default: str = "") -> str:
        """获取国际化文本"""
        if self.i18n:
            return self.i18n.get_text(key, default)
        return default
    
    # ============================================================
    # UI 初始化
    # ============================================================
    
    def _setup_ui(self) -> None:
        """设置 UI 布局"""
        self.setFixedHeight(STATUS_BAR_HEIGHT)
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {STATUS_BAR_BG};
                border-top: 1px solid {STATUS_BAR_BORDER};
            }}
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(8)
        
        # 上下文占用进度条（缩短宽度）
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setFixedWidth(120)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._update_progress_style(COLOR_NORMAL)
        layout.addWidget(self._progress_bar)
        
        # 占用百分比标签
        self._usage_label = QLabel("0%")
        self._usage_label.setStyleSheet("""
            QLabel {
                color: #666666;
                font-size: 11px;
                background: transparent;
                border: none;
            }
        """)
        self._usage_label.setFixedWidth(32)
        layout.addWidget(self._usage_label)
        
        # Token 数量标签
        self._token_label = QLabel("0 / 0")
        self._token_label.setStyleSheet("""
            QLabel {
                color: #999999;
                font-size: 11px;
                background: transparent;
                border: none;
            }
        """)
        layout.addWidget(self._token_label)
        
        # 弹性空间
        layout.addStretch()
        
        # 压缩按钮
        self._compress_button = QToolButton()
        self._compress_button.setToolTip(
            self._get_text("menu.tools.compress_context", "Compress context")
        )
        self._compress_button.setFixedSize(28, 28)
        self._update_button_style(STATE_NORMAL)
        self._set_icon(self._compress_button, "compress")
        self._compress_button.clicked.connect(self.compress_clicked.emit)
        layout.addWidget(self._compress_button)
    
    def _update_progress_style(self, color: str) -> None:
        """更新进度条样式"""
        if self._progress_bar:
            self._progress_bar.setStyleSheet(f"""
                QProgressBar {{
                    background-color: #e0e0e0;
                    border-radius: 4px;
                    border: none;
                }}
                QProgressBar::chunk {{
                    background-color: {color};
                    border-radius: 4px;
                }}
            """)
    
    def _update_button_style(self, state: str) -> None:
        """更新压缩按钮样式"""
        if not self._compress_button:
            return
        
        if state == STATE_CRITICAL:
            self._compress_button.setStyleSheet(f"""
                QToolButton {{
                    background-color: {COLOR_CRITICAL};
                    color: white;
                    border-radius: 4px;
                    padding: 4px 8px;
                }}
                QToolButton:hover {{
                    background-color: #d32f2f;
                }}
            """)
        elif state == STATE_WARNING:
            self._compress_button.setStyleSheet(f"""
                QToolButton {{
                    background-color: {COLOR_WARNING};
                    color: white;
                    border-radius: 4px;
                    padding: 4px 8px;
                }}
                QToolButton:hover {{
                    background-color: #f57c00;
                }}
            """)
        else:
            self._compress_button.setStyleSheet("""
                QToolButton {
                    background-color: transparent;
                    border: none;
                    border-radius: 4px;
                    padding: 4px 8px;
                }
                QToolButton:hover {
                    background-color: #f0f0f0;
                }
                QToolButton:pressed {
                    background-color: #e0e0e0;
                }
            """)
    
    def _set_icon(self, button: QToolButton, icon_type: str, size: int = 16) -> None:
        """设置按钮图标"""
        try:
            from resources.resource_loader import get_panel_icon
            icon = get_panel_icon(icon_type)
            if not icon.isNull():
                button.setIcon(icon)
                button.setIconSize(QSize(size, size))
        except Exception:
            pass
    
    # ============================================================
    # 公共方法
    # ============================================================
    
    def update_usage(self, ratio: float, current_tokens: int = 0, max_tokens: int = 0) -> None:
        """
        更新占用比例显示
        
        Args:
            ratio: 占用比例 (0.0 - 1.0)
            current_tokens: 当前使用的 token 数
            max_tokens: 最大 token 数
        """
        self._current_ratio = max(0.0, min(1.0, ratio))
        self._current_tokens = current_tokens
        self._max_tokens = max_tokens
        percentage = int(self._current_ratio * 100)
        
        # 更新进度条值
        if self._progress_bar:
            self._progress_bar.setValue(percentage)
        
        # 更新百分比标签
        if self._usage_label:
            self._usage_label.setText(f"{percentage}%")
        
        # 更新 token 数量标签
        if self._token_label:
            if max_tokens > 0:
                self._token_label.setText(f"{self._format_tokens(current_tokens)} / {self._format_tokens(max_tokens)}")
            else:
                self._token_label.setText("")
        
        # 根据占用率更新样式
        if self._current_ratio >= CRITICAL_THRESHOLD:
            self._update_progress_style(COLOR_CRITICAL)
            self.set_compress_button_state(STATE_CRITICAL)
        elif self._current_ratio >= WARNING_THRESHOLD:
            self._update_progress_style(COLOR_WARNING)
            self.set_compress_button_state(STATE_WARNING)
        else:
            self._update_progress_style(COLOR_NORMAL)
            self.set_compress_button_state(STATE_NORMAL)
    
    def _format_tokens(self, tokens: int) -> str:
        """格式化 token 数量显示"""
        if tokens >= 1000:
            return f"{tokens / 1000:.1f}k"
        return str(tokens)
    
    def set_compress_button_state(self, state: str) -> None:
        """
        设置压缩按钮状态
        
        Args:
            state: 状态 ("normal" | "warning" | "critical")
        """
        if state not in (STATE_NORMAL, STATE_WARNING, STATE_CRITICAL):
            state = STATE_NORMAL
        
        self._button_state = state
        self._update_button_style(state)
    
    def get_usage_ratio(self) -> float:
        """获取当前占用比例"""
        return self._current_ratio
    
    def get_button_state(self) -> str:
        """获取当前按钮状态"""
        return self._button_state
    
    # ============================================================
    # 国际化
    # ============================================================
    
    def retranslate_ui(self) -> None:
        """刷新 UI 文本"""
        if self._compress_button:
            self._compress_button.setToolTip(
                self._get_text("menu.tools.compress_context", "Compress context")
            )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "StatusBar",
    "STATUS_BAR_HEIGHT",
    "WARNING_THRESHOLD",
    "CRITICAL_THRESHOLD",
    "STATE_NORMAL",
    "STATE_WARNING",
    "STATE_CRITICAL",
]
