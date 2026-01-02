# Conversation Panel Submodule
"""
对话面板子模块

包含对话面板的各个组件：
- ConversationViewModel - ViewModel 层，隔离 UI 与数据层
- MessageBubble - 消息气泡组件
- SuggestionMessage - 建议选项消息组件
- InputArea - 输入区域组件
- StreamDisplayHandler - 流式显示处理器
- TitleBar - 标题栏组件
- MessageArea - 消息显示区域
- StatusBar - 状态栏组件
- AttachmentManager - 附件管理器
"""

from presentation.panels.conversation.conversation_view_model import (
    ConversationViewModel,
    DisplayMessage,
    SuggestionItem,
    SUGGESTION_STATE_ACTIVE,
    SUGGESTION_STATE_SELECTED,
    SUGGESTION_STATE_EXPIRED,
)

from presentation.panels.conversation.message_bubble import (
    MessageBubble,
    USER_MESSAGE_BG,
    ASSISTANT_MESSAGE_BG,
)

from presentation.panels.conversation.suggestion_message import (
    SuggestionMessage,
    STATE_ACTIVE,
    STATE_SELECTED,
    STATE_EXPIRED,
)

from presentation.panels.conversation.input_area import (
    InputArea,
    ButtonMode,
    MAX_IMAGE_SIZE_MB,
    ALLOWED_IMAGE_EXTENSIONS,
)

from presentation.panels.conversation.stream_display_handler import (
    StreamDisplayHandler,
    PHASE_REASONING,
    PHASE_CONTENT,
)

from presentation.panels.conversation.title_bar import (
    TitleBar,
    TITLE_BAR_HEIGHT,
)

from presentation.panels.conversation.message_area import (
    MessageArea,
    MESSAGE_SPACING,
    STREAM_THROTTLE_MS,
)

from presentation.panels.conversation.status_bar import (
    StatusBar,
    STATUS_BAR_HEIGHT,
    WARNING_THRESHOLD,
    CRITICAL_THRESHOLD,
    STATE_NORMAL,
    STATE_WARNING,
    STATE_CRITICAL,
)

from presentation.panels.conversation.attachment_manager import (
    AttachmentManager,
    ATTACHMENT_TYPE_IMAGE,
    ATTACHMENT_TYPE_FILE,
)

__all__ = [
    # ViewModel
    "ConversationViewModel",
    "DisplayMessage",
    "SuggestionItem",
    "SUGGESTION_STATE_ACTIVE",
    "SUGGESTION_STATE_SELECTED",
    "SUGGESTION_STATE_EXPIRED",
    # MessageBubble
    "MessageBubble",
    "USER_MESSAGE_BG",
    "ASSISTANT_MESSAGE_BG",
    # SuggestionMessage
    "SuggestionMessage",
    "STATE_ACTIVE",
    "STATE_SELECTED",
    "STATE_EXPIRED",
    # InputArea
    "InputArea",
    "ButtonMode",
    "MAX_IMAGE_SIZE_MB",
    "ALLOWED_IMAGE_EXTENSIONS",
    # StreamDisplayHandler
    "StreamDisplayHandler",
    "PHASE_REASONING",
    "PHASE_CONTENT",
    # TitleBar
    "TitleBar",
    "TITLE_BAR_HEIGHT",
    # MessageArea
    "MessageArea",
    "MESSAGE_SPACING",
    "STREAM_THROTTLE_MS",
    # StatusBar
    "StatusBar",
    "STATUS_BAR_HEIGHT",
    "WARNING_THRESHOLD",
    "CRITICAL_THRESHOLD",
    "STATE_NORMAL",
    "STATE_WARNING",
    "STATE_CRITICAL",
    # AttachmentManager
    "AttachmentManager",
    "ATTACHMENT_TYPE_IMAGE",
    "ATTACHMENT_TYPE_FILE",
]
