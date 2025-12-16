# Suggestion Message Component
"""
建议选项消息组件

职责：
- 专注于检查点建议选项的消息式渲染
- 作为一条特殊消息显示在对话历史区
- 用户操作后消息保留在历史中，按钮变为已选择状态

设计理念：
- 建议选项像正常消息一样把上面的内容向上顶，不遮挡对话内容
- 提供快捷操作按钮，同时保持输入框始终可用

使用示例：
    from presentation.panels.conversation.suggestion_message import SuggestionMessage
    
    msg = SuggestionMessage()
    msg.render(suggestions, status_summary)
    msg.suggestion_clicked.connect(on_suggestion_selected)
"""

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QPushButton,
    QSizePolicy,
)

# ============================================================
# 样式常量
# ============================================================

# 背景颜色
SUGGESTION_BG = "#f0f4f8"
SUMMARY_BG = "#f5f5f5"

# 按钮颜色
PRIMARY_COLOR = "#4a9eff"
SUCCESS_COLOR = "#4caf50"
WARNING_COLOR = "#ff9800"
ERROR_COLOR = "#f44336"
SECONDARY_COLOR = "#e0e0e0"
DISABLED_COLOR = "#f5f5f5"

# 文字颜色
TEXT_COLOR = "#333333"
SECONDARY_TEXT_COLOR = "#666666"
DISABLED_TEXT_COLOR = "#999999"

# 布局常量
CARD_BORDER_RADIUS = 12
BUTTON_BORDER_RADIUS = 6
BUTTON_PADDING = "8px 16px"

# 状态常量
STATE_ACTIVE = "active"
STATE_SELECTED = "selected"
STATE_EXPIRED = "expired"


# ============================================================
# SuggestionMessage 类
# ============================================================

class SuggestionMessage(QWidget):
    """
    建议选项消息组件
    
    专注于检查点建议选项的消息式渲染。
    """
    
    # 信号定义
    suggestion_clicked = pyqtSignal(str)  # 用户点击建议按钮 (suggestion_id)
    
    def __init__(self, parent: Optional[QWidget] = None):
        """初始化建议选项消息"""
        super().__init__(parent)
        
        # 内部状态
        self._state = STATE_ACTIVE
        self._selected_id: Optional[str] = None
        self._suggestions: List[Dict[str, Any]] = []
        self._buttons: Dict[str, QPushButton] = {}
        
        # UI 组件引用
        self._summary_label: Optional[QLabel] = None
        self._buttons_layout: Optional[QHBoxLayout] = None
        self._hint_label: Optional[QLabel] = None
        
        # 初始化 UI
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """设置 UI 布局"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(8)
        
        # 卡片容器
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {SUGGESTION_BG};
                border-radius: {CARD_BORDER_RADIUS}px;
                padding: 12px;
            }}
        """)
        
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(12)
        
        # 状态摘要区
        self._summary_label = QLabel()
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet(f"""
            QLabel {{
                color: {SECONDARY_TEXT_COLOR};
                font-size: 13px;
                padding: 8px 12px;
                background-color: {SUMMARY_BG};
                border-radius: 8px;
            }}
        """)
        self._summary_label.setVisible(False)
        card_layout.addWidget(self._summary_label)
        
        # 建议按钮区
        buttons_container = QWidget()
        self._buttons_layout = QHBoxLayout(buttons_container)
        self._buttons_layout.setContentsMargins(0, 0, 0, 0)
        self._buttons_layout.setSpacing(8)
        self._buttons_layout.addStretch()
        card_layout.addWidget(buttons_container)
        
        # 提示文本
        self._hint_label = QLabel("或者直接输入你的想法...")
        self._hint_label.setStyleSheet(f"""
            QLabel {{
                color: {DISABLED_TEXT_COLOR};
                font-size: 12px;
                font-style: italic;
            }}
        """)
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._hint_label)
        
        main_layout.addWidget(card)
    
    def render(
        self,
        suggestions: List[Dict[str, Any]],
        status_summary: str = ""
    ) -> QWidget:
        """
        渲染建议选项消息
        
        Args:
            suggestions: 建议选项列表，每项包含:
                - id: str - 选项唯一标识
                - label: str - 显示文本
                - value: str - 选项值
                - description: str - 详细描述（可选）
                - is_recommended: bool - 是否推荐选项
                - button_type: str - 按钮类型（primary/success/warning/error/secondary）
            status_summary: 状态摘要文本
            
        Returns:
            QWidget: 渲染后的建议选项组件（返回 self）
        """
        self._suggestions = suggestions
        self._state = STATE_ACTIVE
        self._selected_id = None
        
        # 更新状态摘要
        if status_summary:
            self._summary_label.setText(status_summary)
            self._summary_label.setVisible(True)
        else:
            self._summary_label.setVisible(False)
        
        # 清空现有按钮
        self._clear_buttons()
        
        # 创建新按钮
        for suggestion in suggestions:
            btn = self._create_suggestion_button(suggestion)
            self._buttons[suggestion["id"]] = btn
            # 插入到 stretch 之前
            self._buttons_layout.insertWidget(
                self._buttons_layout.count() - 1, btn
            )
        
        # 显示提示
        self._hint_label.setVisible(True)
        
        return self
    
    def _create_suggestion_button(self, suggestion: Dict[str, Any]) -> QPushButton:
        """创建建议按钮"""
        btn = QPushButton(suggestion.get("label", ""))
        btn.setProperty("suggestion_id", suggestion.get("id", ""))
        
        # 确定按钮类型和样式
        button_type = suggestion.get("button_type", "secondary")
        is_recommended = suggestion.get("is_recommended", False)
        
        if is_recommended:
            button_type = "primary"
        
        style = self._get_button_style(button_type, enabled=True)
        btn.setStyleSheet(style)
        
        # 设置提示
        if suggestion.get("description"):
            btn.setToolTip(suggestion["description"])
        
        # 连接点击事件
        btn.clicked.connect(
            lambda checked, sid=suggestion["id"]: self._on_button_clicked(sid)
        )
        
        return btn


    def _get_button_style(
        self,
        button_type: str,
        enabled: bool = True,
        selected: bool = False
    ) -> str:
        """获取按钮样式"""
        if not enabled:
            if selected:
                return f"""
                    QPushButton {{
                        background-color: {PRIMARY_COLOR};
                        color: white;
                        border: none;
                        border-radius: {BUTTON_BORDER_RADIUS}px;
                        padding: {BUTTON_PADDING};
                        font-size: 13px;
                        opacity: 0.7;
                    }}
                """
            else:
                return f"""
                    QPushButton {{
                        background-color: {DISABLED_COLOR};
                        color: {DISABLED_TEXT_COLOR};
                        border: 1px solid #e0e0e0;
                        border-radius: {BUTTON_BORDER_RADIUS}px;
                        padding: {BUTTON_PADDING};
                        font-size: 13px;
                    }}
                """
        
        # 根据类型返回样式
        if button_type == "primary":
            return f"""
                QPushButton {{
                    background-color: {PRIMARY_COLOR};
                    color: white;
                    border: none;
                    border-radius: {BUTTON_BORDER_RADIUS}px;
                    padding: {BUTTON_PADDING};
                    font-size: 13px;
                }}
                QPushButton:hover {{
                    background-color: #3d8be8;
                }}
                QPushButton:pressed {{
                    background-color: #2d7bd8;
                }}
            """
        elif button_type == "success":
            return f"""
                QPushButton {{
                    background-color: {SUCCESS_COLOR};
                    color: white;
                    border: none;
                    border-radius: {BUTTON_BORDER_RADIUS}px;
                    padding: {BUTTON_PADDING};
                    font-size: 13px;
                }}
                QPushButton:hover {{
                    background-color: #43a047;
                }}
            """
        elif button_type == "warning":
            return f"""
                QPushButton {{
                    background-color: transparent;
                    color: {WARNING_COLOR};
                    border: 1px solid {WARNING_COLOR};
                    border-radius: {BUTTON_BORDER_RADIUS}px;
                    padding: {BUTTON_PADDING};
                    font-size: 13px;
                }}
                QPushButton:hover {{
                    background-color: #fff3e0;
                }}
            """
        elif button_type == "error":
            return f"""
                QPushButton {{
                    background-color: transparent;
                    color: {ERROR_COLOR};
                    border: 1px solid {ERROR_COLOR};
                    border-radius: {BUTTON_BORDER_RADIUS}px;
                    padding: {BUTTON_PADDING};
                    font-size: 13px;
                }}
                QPushButton:hover {{
                    background-color: #ffebee;
                }}
            """
        else:  # secondary
            return f"""
                QPushButton {{
                    background-color: #f0f0f0;
                    color: {TEXT_COLOR};
                    border: 1px solid #e0e0e0;
                    border-radius: {BUTTON_BORDER_RADIUS}px;
                    padding: {BUTTON_PADDING};
                    font-size: 13px;
                }}
                QPushButton:hover {{
                    background-color: #e8e8e8;
                }}
            """
    
    def _clear_buttons(self) -> None:
        """清空所有按钮"""
        for btn in self._buttons.values():
            btn.deleteLater()
        self._buttons.clear()
    
    def _on_button_clicked(self, suggestion_id: str) -> None:
        """处理按钮点击"""
        if self._state != STATE_ACTIVE:
            return
        
        self.set_selected(suggestion_id)
        self.suggestion_clicked.emit(suggestion_id)
    
    def set_selected(self, suggestion_id: str) -> None:
        """
        设置已选择的选项
        
        Args:
            suggestion_id: 选择的建议选项 ID
        """
        self._state = STATE_SELECTED
        self._selected_id = suggestion_id
        
        # 更新所有按钮状态
        for sid, btn in self._buttons.items():
            is_selected = (sid == suggestion_id)
            btn.setEnabled(False)
            btn.setStyleSheet(
                self._get_button_style("primary", enabled=False, selected=is_selected)
            )
            if is_selected:
                btn.setText(f"✓ {btn.text()}")
        
        # 隐藏提示
        self._hint_label.setVisible(False)
    
    def set_expired(self) -> None:
        """设置为过期状态（用户通过输入框发送消息）"""
        self._state = STATE_EXPIRED
        
        # 禁用所有按钮但不显示选中标记
        for btn in self._buttons.values():
            btn.setEnabled(False)
            btn.setStyleSheet(
                self._get_button_style("secondary", enabled=False, selected=False)
            )
        
        # 隐藏提示
        self._hint_label.setVisible(False)
    
    def is_active(self) -> bool:
        """检查是否为活跃状态（未选择）"""
        return self._state == STATE_ACTIVE
    
    def get_state(self) -> str:
        """获取当前状态"""
        return self._state
    
    def get_selected_id(self) -> Optional[str]:
        """获取已选择的建议 ID"""
        return self._selected_id


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SuggestionMessage",
    # 状态常量
    "STATE_ACTIVE",
    "STATE_SELECTED",
    "STATE_EXPIRED",
]

