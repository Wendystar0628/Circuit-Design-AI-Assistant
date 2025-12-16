# Message Bubble Component
"""
消息气泡组件

职责：
- 专注于单条消息的渲染
- 根据消息角色渲染不同样式
- 支持深度思考内容的可折叠展示
- 支持操作摘要卡片渲染

使用示例：
    from presentation.panels.conversation.message_bubble import MessageBubble
    
    bubble = MessageBubble()
    widget = bubble.render(display_message)
"""

from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
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
USER_MESSAGE_BG = "#e3f2fd"
ASSISTANT_MESSAGE_BG = "#f8f9fa"
SYSTEM_MESSAGE_BG = "transparent"
THINKING_BG = "#f5f5f5"
OPERATIONS_CARD_BG = "#f0f7ff"

# 文字颜色
USER_TEXT_COLOR = "#333333"
ASSISTANT_TEXT_COLOR = "#333333"
SYSTEM_TEXT_COLOR = "#6c757d"
THINKING_TEXT_COLOR = "#555555"
TIMESTAMP_COLOR = "#999999"

# 布局常量
MESSAGE_PADDING = 12
MESSAGE_BORDER_RADIUS = 12
# 注意：不再使用固定的最大宽度比例，气泡宽度随对话区域自动调整

# 主题色
PRIMARY_COLOR = "#4a9eff"
SUCCESS_COLOR = "#4caf50"
WARNING_COLOR = "#ff9800"
ERROR_COLOR = "#f44336"


# ============================================================
# MessageBubble 类
# ============================================================

class MessageBubble(QWidget):
    """
    消息气泡组件
    
    专注于单条消息的渲染，根据角色渲染不同样式。
    """
    
    # 信号定义
    link_clicked = pyqtSignal(str)           # 链接点击 (url)
    file_clicked = pyqtSignal(str)           # 文件点击 (file_path)
    reasoning_toggled = pyqtSignal(bool)     # 思考内容折叠状态变化
    
    def __init__(self, parent: Optional[QWidget] = None):
        """初始化消息气泡"""
        super().__init__(parent)
        
        # 内部状态
        self._message = None
        self._reasoning_collapsed = True
        
        # UI 组件引用
        self._reasoning_frame: Optional[QFrame] = None
        self._reasoning_toggle: Optional[QPushButton] = None
    
    def render(self, message) -> QWidget:
        """
        渲染消息内容
        
        Args:
            message: DisplayMessage 对象
            
        Returns:
            QWidget: 渲染后的消息组件
        """
        self._message = message
        
        if message.role == "user":
            return self.render_user_message(message)
        elif message.role == "assistant":
            return self.render_assistant_message(message)
        elif message.role == "system":
            return self.render_system_message(message)
        else:
            return self.render_system_message(message)
    
    def render_user_message(self, message) -> QWidget:
        """
        渲染用户消息样式
        
        Args:
            message: DisplayMessage 对象
            
        Returns:
            QWidget: 用户消息组件（右对齐、浅蓝背景）
        """
        # 用户消息：右对齐，使用左侧 stretch 推到右边
        container = QWidget()
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 左侧弹性空间（占 30%）
        layout.addStretch(3)
        
        bubble = QFrame()
        bubble.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bubble.setStyleSheet(f"""
            QFrame {{
                background-color: {USER_MESSAGE_BG};
                border-radius: {MESSAGE_BORDER_RADIUS}px;
                padding: {MESSAGE_PADDING}px;
            }}
        """)
        
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(0, 0, 0, 0)
        bubble_layout.setSpacing(4)
        
        # 消息内容
        content_label = QLabel()
        content_label.setTextFormat(Qt.TextFormat.RichText)
        content_label.setWordWrap(True)
        content_label.setText(message.content_html)
        content_label.setStyleSheet(f"color: {USER_TEXT_COLOR}; font-size: 14px;")
        content_label.setOpenExternalLinks(True)
        bubble_layout.addWidget(content_label)
        
        # 附件预览
        if message.attachments:
            attachments_widget = self._render_attachments(message.attachments)
            bubble_layout.addWidget(attachments_widget)
        
        # 右侧占 70%
        layout.addWidget(bubble, 7)
        return container
    
    def render_assistant_message(self, message) -> QWidget:
        """
        渲染助手消息（含深度思考）
        
        Args:
            message: DisplayMessage 对象
            
        Returns:
            QWidget: 助手消息组件（左对齐、浅灰背景、Markdown渲染）
        """
        # 助手消息：填满整个宽度（头像 + 内容）
        container = QWidget()
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
        
        # 思考过程（可折叠）
        if message.reasoning_html:
            thinking_widget = self._render_thinking_section(message.reasoning_html)
            bubble_layout.addWidget(thinking_widget)
        
        # 消息内容
        content_label = QLabel()
        content_label.setTextFormat(Qt.TextFormat.RichText)
        content_label.setWordWrap(True)
        content_label.setText(message.content_html)
        content_label.setStyleSheet(f"color: {ASSISTANT_TEXT_COLOR}; font-size: 14px;")
        content_label.setOpenExternalLinks(True)
        content_label.linkActivated.connect(self._on_link_activated)
        bubble_layout.addWidget(content_label)
        
        # 操作摘要卡片
        if message.operations:
            ops_card = self.render_operations_card(message.operations)
            bubble_layout.addWidget(ops_card)
        
        # 不使用 stretch，让 bubble 自然填满
        layout.addWidget(bubble, 1)
        
        return container


    def render_system_message(self, message) -> QWidget:
        """
        渲染系统消息样式
        
        Args:
            message: DisplayMessage 对象
            
        Returns:
            QWidget: 系统消息组件（居中、灰色小字）
        """
        # 系统消息：居中显示
        container = QWidget()
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 左右各占 20%，中间 60%
        layout.addStretch(2)
        
        label = QLabel()
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setText(message.content_html)
        label.setStyleSheet(f"""
            QLabel {{
                color: {SYSTEM_TEXT_COLOR};
                font-size: 12px;
                padding: 8px 16px;
            }}
        """)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label, 6)
        
        layout.addStretch(2)
        return container
    
    def render_operations_card(self, operations: List[str]) -> QWidget:
        """
        渲染操作摘要卡片
        
        Args:
            operations: 操作描述列表
            
        Returns:
            QWidget: 操作摘要卡片组件
        """
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {OPERATIONS_CARD_BG};
                border-left: 3px solid {PRIMARY_COLOR};
                border-radius: 4px;
                padding: 8px;
            }}
        """)
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)
        
        # 标题
        title = QLabel("📋 操作记录")
        title.setStyleSheet(f"color: {PRIMARY_COLOR}; font-size: 12px; font-weight: bold;")
        layout.addWidget(title)
        
        # 操作列表
        max_display = 5
        for i, op in enumerate(operations[:max_display]):
            op_widget = self._render_operation_item(op)
            layout.addWidget(op_widget)
        
        # 更多提示
        if len(operations) > max_display:
            more_label = QLabel(f"... 还有 {len(operations) - max_display} 条操作")
            more_label.setStyleSheet(f"color: {TIMESTAMP_COLOR}; font-size: 11px;")
            layout.addWidget(more_label)
        
        return card
    
    def _render_operation_item(self, operation: str) -> QWidget:
        """渲染单条操作项"""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)
        
        # 状态图标
        icon = "✅"  # 默认完成状态
        if "进行中" in operation or "running" in operation.lower():
            icon = "⏳"
        elif "失败" in operation or "error" in operation.lower():
            icon = "❌"
        
        icon_label = QLabel(icon)
        icon_label.setFixedWidth(16)
        layout.addWidget(icon_label)
        
        # 操作描述
        desc_label = QLabel(operation)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #555555; font-size: 12px;")
        
        # 检查是否包含文件路径
        if self._contains_file_path(operation):
            desc_label.setCursor(Qt.CursorShape.PointingHandCursor)
            desc_label.setStyleSheet("""
                color: #555555; 
                font-size: 12px;
            """)
            desc_label.mousePressEvent = lambda e: self._on_operation_clicked(operation)
        
        layout.addWidget(desc_label, 1)
        
        return container
    
    def _render_thinking_section(self, reasoning_html: str) -> QWidget:
        """渲染可折叠的思考过程区域"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 折叠标题栏
        self._reasoning_toggle = QPushButton("💭 思考过程 ▶")
        self._reasoning_toggle.setCheckable(True)
        self._reasoning_toggle.setChecked(False)
        self._reasoning_toggle.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                text-align: left;
                padding: 4px 0;
                color: #666666;
                font-size: 12px;
            }
            QPushButton:hover {
                color: #333333;
            }
        """)
        layout.addWidget(self._reasoning_toggle)
        
        # 思考内容区
        self._reasoning_frame = QFrame()
        self._reasoning_frame.setVisible(False)
        self._reasoning_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {THINKING_BG};
                border-radius: 8px;
                padding: 8px;
            }}
        """)
        
        content_layout = QVBoxLayout(self._reasoning_frame)
        content_layout.setContentsMargins(8, 8, 8, 8)
        
        content_label = QLabel()
        content_label.setTextFormat(Qt.TextFormat.RichText)
        content_label.setWordWrap(True)
        content_label.setText(reasoning_html)
        content_label.setStyleSheet(f"color: {THINKING_TEXT_COLOR}; font-size: 13px;")
        content_layout.addWidget(content_label)
        
        layout.addWidget(self._reasoning_frame)
        
        # 连接折叠/展开
        self._reasoning_toggle.toggled.connect(self.toggle_reasoning_collapse)
        
        return container
    
    def toggle_reasoning_collapse(self, expanded: bool = None) -> None:
        """
        切换思考内容折叠状态
        
        Args:
            expanded: 是否展开，None 则切换当前状态
        """
        if expanded is None:
            self._reasoning_collapsed = not self._reasoning_collapsed
        else:
            self._reasoning_collapsed = not expanded
        
        is_expanded = not self._reasoning_collapsed
        
        if self._reasoning_frame:
            self._reasoning_frame.setVisible(is_expanded)
        
        if self._reasoning_toggle:
            self._reasoning_toggle.setText(
                "💭 思考过程 ▼" if is_expanded else "💭 思考过程 ▶"
            )
            self._reasoning_toggle.setChecked(is_expanded)
        
        self.reasoning_toggled.emit(is_expanded)


    def _render_attachments(self, attachments: List[Dict[str, Any]]) -> QWidget:
        """渲染附件预览"""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)
        
        for att in attachments[:3]:  # 最多显示3个
            att_widget = self._render_attachment_item(att)
            layout.addWidget(att_widget)
        
        if len(attachments) > 3:
            more_label = QLabel(f"+{len(attachments) - 3}")
            more_label.setStyleSheet("""
                color: #666666;
                font-size: 12px;
                padding: 4px 8px;
                background-color: #e0e0e0;
                border-radius: 4px;
            """)
            layout.addWidget(more_label)
        
        layout.addStretch()
        return container
    
    def _render_attachment_item(self, attachment: Dict[str, Any]) -> QWidget:
        """渲染单个附件项"""
        container = QFrame()
        container.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 4px 8px;
            }
        """)
        
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # 图标
        icon = "🖼️" if attachment.get("type") == "image" else "📄"
        icon_label = QLabel(icon)
        layout.addWidget(icon_label)
        
        # 文件名
        name = attachment.get("name", "未知文件")
        if len(name) > 15:
            name = name[:12] + "..."
        name_label = QLabel(name)
        name_label.setStyleSheet("color: #333333; font-size: 12px;")
        layout.addWidget(name_label)
        
        return container
    
    def _contains_file_path(self, text: str) -> bool:
        """检查文本是否包含文件路径"""
        import os
        # 简单检查是否包含路径分隔符和文件扩展名
        if os.sep in text or "/" in text:
            extensions = [".py", ".cir", ".json", ".txt", ".md", ".spice"]
            return any(ext in text.lower() for ext in extensions)
        return False
    
    def _extract_file_path(self, text: str) -> Optional[str]:
        """从文本中提取文件路径"""
        import re
        # 匹配常见文件路径模式
        patterns = [
            r'`([^`]+\.\w+)`',  # 反引号包裹的路径
            r'"([^"]+\.\w+)"',  # 双引号包裹的路径
            r"'([^']+\.\w+)'",  # 单引号包裹的路径
            r'(\S+\.\w+)',      # 无空格的路径
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return None
    
    def _on_link_activated(self, link: str) -> None:
        """处理链接点击"""
        import os
        if link.startswith("file://"):
            file_path = link[7:]
            self.file_clicked.emit(file_path)
        elif os.path.exists(link):
            self.file_clicked.emit(link)
        else:
            self.link_clicked.emit(link)
    
    def _on_operation_clicked(self, operation: str) -> None:
        """处理操作项点击"""
        file_path = self._extract_file_path(operation)
        if file_path:
            self.file_clicked.emit(file_path)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "MessageBubble",
    # 样式常量
    "USER_MESSAGE_BG",
    "ASSISTANT_MESSAGE_BG",
    "SYSTEM_MESSAGE_BG",
    "THINKING_BG",
    "PRIMARY_COLOR",
]

