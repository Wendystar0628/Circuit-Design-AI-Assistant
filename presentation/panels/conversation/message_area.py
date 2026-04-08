# Message Area Component
"""
消息显示区域

职责：
- 管理消息显示区域
- 使用 WebMessageView 渲染消息（支持 Markdown + LaTeX）
- 流式输出显示

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
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self._web_view: Optional[WebMessageView] = None
        self._is_streaming = False
        self._pending_messages: Optional[List[Any]] = None
        
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
        layout.addWidget(self._web_view)
    
    # ============================================================
    # 公共方法 - 消息渲染
    # ============================================================
    
    def render_messages(self, messages: List[Any]) -> None:
        """渲染消息列表"""
        if self._is_streaming:
            self._pending_messages = list(messages)
            return
        if self._web_view:
            self._web_view.render_messages(messages)
    
    def clear_messages(self) -> None:
        """清空消息显示"""
        self._pending_messages = None
        if self._web_view:
            self._web_view.clear_messages()
        if self._is_streaming:
            self.finish_streaming()
    
    # ============================================================
    # 公共方法 - 流式输出
    # ============================================================
    
    def start_streaming(self, with_search: bool = False) -> None:
        """
        开始流式输出显示
        
        Args:
            with_search: 是否显示搜索区域
        """
        if self._is_streaming:
            return
        self._is_streaming = True
        self._pending_messages = None
        if self._web_view:
            self._web_view.start_streaming(with_search=with_search)
    
    def update_streaming(self, content: str, reasoning: str = "") -> None:
        """更新流式内容"""
        if not self._is_streaming:
            self.start_streaming()
        if self._web_view:
            self._web_view.update_streaming(content, reasoning)
    
    def finish_streaming(self) -> None:
        """完成流式输出"""
        self._is_streaming = False
        if self._web_view:
            pending_messages = self._pending_messages
            self._pending_messages = None
            self._web_view.finish_streaming(pending_messages)
    
    def start_searching(self) -> None:
        """开始搜索阶段"""
        if self._web_view:
            self._web_view.start_searching()
    
    def finish_searching(self, result_count: int = 0) -> None:
        """完成搜索阶段"""
        if self._web_view:
            self._web_view.finish_searching(result_count)
    
    def update_search_results(self, results: list) -> None:
        """更新搜索结果显示"""
        if self._web_view:
            self._web_view.update_search_results(results)
    
    def add_tool_card(
        self, tool_call_id: str, tool_name: str, arguments: dict
    ) -> None:
        """在流式消息中插入工具调用卡片"""
        if self._web_view:
            self._web_view.add_tool_card(tool_call_id, tool_name, arguments)

    def update_tool_card(
        self, tool_call_id: str, result_content: str, is_error: bool
    ) -> None:
        """更新工具调用卡片的执行结果"""
        if self._web_view:
            self._web_view.update_tool_card(tool_call_id, result_content, is_error)
    
    # ============================================================
    # 清理
    # ============================================================
    
    def cleanup(self) -> None:
        """清理资源"""
        if self._is_streaming:
            self.finish_streaming()
        if self._web_view:
            self._web_view.cleanup()


__all__ = [
    "MessageArea",
    "MESSAGE_SPACING",
]
