# Message Area Component
"""
消息显示区域

职责：
- 管理消息显示区域
- 使用 WebMessageView 渲染消息（支持 Markdown + LaTeX）
- 渲染历史消息与当前运行时步骤

架构说明：
- 使用单个 QWebEngineView 渲染所有消息
- KaTeX 统一处理 LaTeX 公式
- 通过 JavaScript 实现增量更新
"""

from typing import Any, List, Optional
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy

# 导入 WebMessageView
from presentation.panels.conversation.web_message_view import (
    WebMessageView,
)


# 常量
MESSAGE_SPACING = 12


class MessageArea(QWidget):
    """
    消息显示区域组件
    
    使用 WebMessageView 渲染所有消息，支持 Markdown 和 LaTeX。
    """

    file_clicked = pyqtSignal(str)
    link_clicked = pyqtSignal(str)
    suggestion_clicked = pyqtSignal(str)
    rollback_requested = pyqtSignal(str)
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self._web_view: Optional[WebMessageView] = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 使用 WebMessageView
        self._web_view = WebMessageView()
        self._web_view.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        self._web_view.file_clicked.connect(self.file_clicked.emit)
        self._web_view.link_clicked.connect(self.link_clicked.emit)
        self._web_view.suggestion_clicked.connect(self.suggestion_clicked.emit)
        self._web_view.rollback_requested.connect(self.rollback_requested.emit)
        layout.addWidget(self._web_view)
    
    # ============================================================
    # 公共方法 - 消息渲染
    # ============================================================
    
    def render_messages(
        self,
        messages: List[Any],
        runtime_steps: Optional[List[Any]] = None,
    ) -> None:
        self.render_conversation(messages, runtime_steps)

    def render_conversation(
        self,
        messages: List[Any],
        runtime_steps: Optional[List[Any]] = None,
    ) -> None:
        if self._web_view:
            self._web_view.render_conversation(messages, runtime_steps or [])
    
    def clear_messages(self) -> None:
        """清空消息显示"""
        if self._web_view:
            self._web_view.clear_messages()
    
    # ============================================================
    # 清理
    # ============================================================
    
    def cleanup(self) -> None:
        """清理资源"""
        if self._web_view:
            self._web_view.cleanup()


__all__ = [
    "MessageArea",
    "MESSAGE_SPACING",
]
