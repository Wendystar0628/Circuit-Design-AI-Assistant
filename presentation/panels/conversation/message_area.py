# Message Area Component
"""
消息显示区域

职责：
- 管理消息显示区域
- 滚动控制和自动跟随
- 消息渲染
- 流式输出显示

自动滚动逻辑：
- 新消息到达时自动滚动到底部
- 用户手动滚动时暂停跟随
- 滚动到接近底部时恢复自动跟随

流式节流：
- 使用 50ms 定时器聚合更新
- 减少 UI 刷新频率
"""

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QLabel,
    QFrame,
    QSizePolicy,
)


# ============================================================
# 常量定义
# ============================================================

# 布局常量
MESSAGE_SPACING = 12
MESSAGE_PADDING = 12
MESSAGE_BORDER_RADIUS = 12
# 注意：不再使用固定的最大宽度比例，气泡宽度随对话区域自动调整

# 颜色常量
ASSISTANT_MESSAGE_BG = "#f8f9fa"
THINKING_BG = "#f5f5f5"

# 流式输出节流
STREAM_THROTTLE_MS = 50


# ============================================================
# MessageArea 类
# ============================================================

class MessageArea(QWidget):
    """
    消息显示区域组件
    
    管理消息显示、滚动和流式输出。
    """
    
    def __init__(self, parent: Optional[QWidget] = None):
        """初始化消息显示区域"""
        super().__init__(parent)
        
        # 延迟获取的服务
        self._i18n = None
        self._logger = None
        
        # 内部状态
        self._is_auto_scroll: bool = True
        self._is_streaming: bool = False
        self._stream_buffer: str = ""
        self._reasoning_buffer: str = ""
        
        # UI 组件引用
        self._scroll_area: Optional[QScrollArea] = None
        self._messages_container: Optional[QWidget] = None
        self._messages_layout: Optional[QVBoxLayout] = None
        self._streaming_bubble: Optional[QWidget] = None
        
        # 流式输出定时器
        self._stream_timer: Optional[QTimer] = None
        
        # 初始化 UI
        self._setup_ui()
        self._setup_stream_timer()
    
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
    
    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("message_area")
            except Exception:
                pass
        return self._logger
    
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 滚动区域
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: #f0f0f0;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #c0c0c0;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #a0a0a0;
            }
        """)
        
        # 消息容器
        self._messages_container = QWidget()
        self._messages_layout = QVBoxLayout(self._messages_container)
        self._messages_layout.setContentsMargins(12, 12, 12, 12)
        self._messages_layout.setSpacing(MESSAGE_SPACING)
        self._messages_layout.addStretch()
        
        self._scroll_area.setWidget(self._messages_container)
        layout.addWidget(self._scroll_area)
        
        # 监听滚动事件
        self._scroll_area.verticalScrollBar().valueChanged.connect(
            self._on_scroll_changed
        )
    
    def _setup_stream_timer(self) -> None:
        """设置流式输出节流定时器"""
        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(STREAM_THROTTLE_MS)
        self._stream_timer.timeout.connect(self._flush_stream_buffer)
    
    # ============================================================
    # 公共方法 - 消息渲染
    # ============================================================
    
    def render_messages(self, messages: List[Any]) -> None:
        """
        渲染消息列表
        
        Args:
            messages: DisplayMessage 列表
        """
        self.clear_messages()
        
        for msg in messages:
            self.render_message(msg)
        
        # 滚动到底部
        QTimer.singleShot(50, self.scroll_to_bottom)
    
    def render_message(self, display_msg: Any) -> None:
        """
        渲染单条消息
        
        Args:
            display_msg: DisplayMessage 对象
        """
        if self._messages_layout is None:
            return
        
        # 根据消息类型创建渲染器并获取渲染后的 widget
        from presentation.panels.conversation import MessageBubble, SuggestionMessage
        
        if display_msg.is_suggestion():
            renderer = SuggestionMessage()
            widget = renderer.render(
                display_msg.suggestions, 
                display_msg.status_summary
            )
        else:
            renderer = MessageBubble()
            widget = renderer.render(display_msg)
        
        # 插入到 stretch 之前
        self._messages_layout.insertWidget(
            self._messages_layout.count() - 1, widget
        )
    
    def clear_messages(self) -> None:
        """清空消息显示"""
        if self._messages_layout is None:
            return
        
        # 移除所有消息组件（保留最后的 stretch）
        while self._messages_layout.count() > 1:
            item = self._messages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # 清理流式输出
        if self._is_streaming:
            self.finish_streaming()
    
    # ============================================================
    # 公共方法 - 滚动控制
    # ============================================================
    
    def scroll_to_bottom(self) -> None:
        """滚动到底部"""
        if self._scroll_area and self._is_auto_scroll:
            scrollbar = self._scroll_area.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
    
    def set_auto_scroll(self, enabled: bool) -> None:
        """设置自动滚动"""
        self._is_auto_scroll = enabled
    
    def is_auto_scroll_enabled(self) -> bool:
        """获取自动滚动状态"""
        return self._is_auto_scroll
    
    # ============================================================
    # 公共方法 - 流式输出
    # ============================================================
    
    def start_streaming(self) -> None:
        """开始流式输出显示"""
        if self._is_streaming:
            return
        
        self._is_streaming = True
        self._stream_buffer = ""
        self._reasoning_buffer = ""
        
        # 创建流式输出气泡
        self._streaming_bubble = self._create_streaming_bubble()
        if self._messages_layout:
            self._messages_layout.insertWidget(
                self._messages_layout.count() - 1, self._streaming_bubble
            )
        
        # 启动节流定时器
        if self._stream_timer:
            self._stream_timer.start()
        
        self.scroll_to_bottom()
    
    def update_streaming(self, content: str, reasoning: str = "") -> None:
        """
        更新流式内容
        
        Args:
            content: 主要内容
            reasoning: 思考过程内容
        """
        if not self._is_streaming:
            self.start_streaming()
        
        self._stream_buffer = content
        self._reasoning_buffer = reasoning
    
    def finish_streaming(self) -> None:
        """完成流式输出"""
        self._is_streaming = False
        
        # 停止节流定时器
        if self._stream_timer:
            self._stream_timer.stop()
        
        # 移除流式气泡
        if self._streaming_bubble:
            self._streaming_bubble.deleteLater()
            self._streaming_bubble = None
        
        # 清空缓冲区
        self._stream_buffer = ""
        self._reasoning_buffer = ""
    
    def is_streaming(self) -> bool:
        """获取流式输出状态"""
        return self._is_streaming
    
    def append_stream_chunk(self, chunk_type: str, text: str) -> None:
        """
        追加流式输出块
        
        Args:
            chunk_type: 内容类型 ("reasoning" | "content")
            text: 文本内容
        """
        if not self._is_streaming:
            self.start_streaming()
        
        if chunk_type == "reasoning":
            self._reasoning_buffer += text
        else:
            self._stream_buffer += text
    
    # ============================================================
    # 内部方法 - 流式输出
    # ============================================================
    
    def _flush_stream_buffer(self) -> None:
        """刷新流式缓冲区"""
        if self._stream_buffer or self._reasoning_buffer:
            self._update_streaming_content(
                self._stream_buffer, self._reasoning_buffer
            )
    
    def _update_streaming_content(self, content: str, reasoning: str) -> None:
        """更新流式输出内容"""
        if self._streaming_bubble is None:
            return
        
        # 更新思考过程
        thinking_area = self._streaming_bubble.findChild(QFrame, "thinking_area")
        thinking_content = self._streaming_bubble.findChild(QLabel, "thinking_content")
        if thinking_area and thinking_content and reasoning:
            thinking_area.setVisible(True)
            thinking_content.setText(self._simple_markdown_to_html(reasoning))
        
        # 更新内容
        content_area = self._streaming_bubble.findChild(QLabel, "content_area")
        if content_area and content:
            content_area.setText(self._simple_markdown_to_html(content))
        
        # 自动滚动
        if self._is_auto_scroll:
            self.scroll_to_bottom()
    
    def _create_streaming_bubble(self) -> QWidget:
        """创建流式输出气泡"""
        # 流式输出气泡：与助手消息相同的布局
        container = QWidget()
        container.setObjectName("streaming_bubble")
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # AI 头像（固定宽度）
        avatar = QLabel("🤖")
        avatar.setFixedSize(32, 32)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet("""
            QLabel {
                background-color: #e8f5e9;
                border-radius: 16px;
                font-size: 18px;
            }
        """)
        layout.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
        
        # 气泡填满剩余宽度
        bubble = QFrame()
        bubble.setObjectName("streaming_content")
        bubble.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bubble.setStyleSheet(f"""
            QFrame {{
                background-color: {ASSISTANT_MESSAGE_BG};
                border-radius: {MESSAGE_BORDER_RADIUS}px;
                padding: {MESSAGE_PADDING}px;
            }}
        """)
        
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(0, 0, 0, 0)
        bubble_layout.setSpacing(8)
        
        # 思考过程区（初始隐藏）
        thinking_frame = QFrame()
        thinking_frame.setObjectName("thinking_area")
        thinking_frame.setVisible(False)
        thinking_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {THINKING_BG};
                border-radius: 8px;
                padding: 8px;
            }}
        """)
        thinking_layout = QVBoxLayout(thinking_frame)
        thinking_layout.setContentsMargins(8, 8, 8, 8)
        
        thinking_title = QLabel(
            f"💭 {self._get_text('label.thinking', 'Thinking')}..."
        )
        thinking_title.setStyleSheet("color: #666666; font-size: 12px;")
        thinking_layout.addWidget(thinking_title)
        
        thinking_content = QLabel()
        thinking_content.setObjectName("thinking_content")
        thinking_content.setTextFormat(Qt.TextFormat.RichText)
        thinking_content.setWordWrap(True)
        thinking_content.setStyleSheet("color: #555555; font-size: 13px;")
        thinking_layout.addWidget(thinking_content)
        
        bubble_layout.addWidget(thinking_frame)
        
        # 内容区
        content_label = QLabel()
        content_label.setObjectName("content_area")
        content_label.setTextFormat(Qt.TextFormat.RichText)
        content_label.setWordWrap(True)
        content_label.setStyleSheet("color: #333333; font-size: 14px;")
        bubble_layout.addWidget(content_label)
        
        # 加载指示器
        loading_label = QLabel("▌")
        loading_label.setObjectName("loading_indicator")
        loading_label.setStyleSheet("color: #4a9eff; font-size: 14px;")
        bubble_layout.addWidget(loading_label)
        
        # 不使用 stretch，让 bubble 自然填满
        layout.addWidget(bubble, 1)
        
        return container
    
    def _simple_markdown_to_html(self, text: str) -> str:
        """简单的 Markdown 转 HTML（用于流式输出）"""
        if not text:
            return ""
        
        # 简单转义和换行处理
        html = text.replace("<", "&lt;").replace(">", "&gt;")
        html = html.replace("\n", "<br>")
        return html
    
    # ============================================================
    # 事件处理
    # ============================================================
    
    def _on_scroll_changed(self, value: int) -> None:
        """处理滚动变化"""
        if self._scroll_area is None:
            return
        
        scrollbar = self._scroll_area.verticalScrollBar()
        # 如果用户滚动到接近底部，恢复自动滚动
        at_bottom = value >= scrollbar.maximum() - 50
        self._is_auto_scroll = at_bottom
    
    # ============================================================
    # 清理
    # ============================================================
    
    def cleanup(self) -> None:
        """清理资源"""
        if self._stream_timer:
            self._stream_timer.stop()
        
        if self._is_streaming:
            self.finish_streaming()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "MessageArea",
    "MESSAGE_SPACING",
    "STREAM_THROTTLE_MS",
]
