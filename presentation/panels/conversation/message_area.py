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
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy

# 导入 WebMessageView
from presentation.panels.conversation.web_message_view import (
    WebMessageView, 
    WEBENGINE_AVAILABLE
)


# 常量
MESSAGE_SPACING = 12
STREAM_THROTTLE_MS = 50


class MessageArea(QWidget):
    """
    消息显示区域组件
    
    使用 WebMessageView 渲染所有消息，支持 Markdown 和 LaTeX。
    """
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self._i18n = None
        self._logger = None
        self._web_view: Optional[WebMessageView] = None
        self._is_streaming = False
        self._stream_buffer = ""
        self._reasoning_buffer = ""
        
        self._setup_ui()
    
    @property
    def i18n(self):
        if self._i18n is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_I18N_MANAGER
                self._i18n = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            except:
                pass
        return self._i18n
    
    @property
    def logger(self):
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("message_area")
            except:
                pass
        return self._logger
    
    def _get_text(self, key: str, default: str = "") -> str:
        if self.i18n:
            return self.i18n.get_text(key, default)
        return default
    
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
        layout.addWidget(self._web_view)
    
    # ============================================================
    # 公共方法 - 消息渲染
    # ============================================================
    
    def render_messages(self, messages: List[Any]) -> None:
        """渲染消息列表"""
        if self._web_view:
            self._web_view.render_messages(messages)
    
    def render_message(self, display_msg: Any) -> None:
        """渲染单条消息（追加到现有消息）"""
        # WebMessageView 不支持单条追加，需要重新渲染全部
        pass
    
    def clear_messages(self) -> None:
        """清空消息显示"""
        if self._web_view:
            self._web_view.clear_messages()
        if self._is_streaming:
            self.finish_streaming()
    
    # ============================================================
    # 公共方法 - 滚动控制
    # ============================================================
    
    def scroll_to_bottom(self) -> None:
        """滚动到底部"""
        if self._web_view:
            self._web_view.scroll_to_bottom()
    
    def set_auto_scroll(self, enabled: bool) -> None:
        """设置自动滚动"""
        pass  # WebMessageView 内部处理
    
    def is_auto_scroll_enabled(self) -> bool:
        """获取自动滚动状态"""
        return True
    
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
        self._stream_buffer = ""
        self._reasoning_buffer = ""
        if self._web_view:
            self._web_view.start_streaming(with_search=with_search)
    
    def update_streaming(self, content: str, reasoning: str = "") -> None:
        """更新流式内容"""
        if not self._is_streaming:
            self.start_streaming()
        self._stream_buffer = content
        self._reasoning_buffer = reasoning
        if self._web_view:
            self._web_view.update_streaming(content, reasoning)
    
    def finish_streaming(self) -> None:
        """完成流式输出"""
        self._is_streaming = False
        if self._web_view:
            self._web_view.finish_streaming()
        self._stream_buffer = ""
        self._reasoning_buffer = ""
    
    def finish_thinking(self) -> None:
        """完成思考阶段，更新状态显示"""
        if self._web_view:
            self._web_view.finish_thinking()
    
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
    
    def is_streaming(self) -> bool:
        """获取流式输出状态"""
        return self._is_streaming
    
    def append_stream_chunk(self, chunk_type: str, text: str) -> None:
        """追加流式输出块"""
        if not self._is_streaming:
            self.start_streaming()
        
        if chunk_type == "reasoning":
            self._reasoning_buffer += text
        else:
            self._stream_buffer += text
        
        if self._web_view:
            self._web_view.append_streaming_chunk(text, chunk_type)
    
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
    "STREAM_THROTTLE_MS",
]
