# Conversation Panel Submodule
"""
对话面板子模块

包含对话面板的各个组件：
- ConversationViewModel - ViewModel 层，隔离 UI 与数据层
- ConversationAttachmentSupport - 附件支持组件
- TitleBar - 标题栏组件
- ReactConversationHost - React 会话宿主
"""

from presentation.panels.conversation.conversation_view_model import (
    ConversationViewModel,
    DisplayMessage,
    SuggestionItem,
    SUGGESTION_STATE_ACTIVE,
    SUGGESTION_STATE_SELECTED,
    SUGGESTION_STATE_EXPIRED,
)

from presentation.panels.conversation.conversation_attachment_support import (
    ConversationAttachmentError,
    ConversationAttachmentSupport,
    MAX_IMAGE_SIZE_MB,
)

from presentation.panels.conversation.conversation_session_support import (
    ConversationSessionSupport,
)

from presentation.panels.conversation.conversation_state_serializer import (
    ConversationStateSerializer,
)

from presentation.panels.conversation.conversation_web_bridge import (
    ConversationWebBridge,
)

from presentation.panels.conversation.react_conversation_host import (
    ReactConversationHost,
)

__all__ = [
    # ViewModel
    "ConversationViewModel",
    "DisplayMessage",
    "SuggestionItem",
    "SUGGESTION_STATE_ACTIVE",
    "SUGGESTION_STATE_SELECTED",
    "SUGGESTION_STATE_EXPIRED",
    # Attachment support
    "ConversationAttachmentError",
    "ConversationAttachmentSupport",
    "MAX_IMAGE_SIZE_MB",
    "ConversationSessionSupport",
    # Frontend contract and web host
    "ConversationStateSerializer",
    "ConversationWebBridge",
    "ReactConversationHost",
]
