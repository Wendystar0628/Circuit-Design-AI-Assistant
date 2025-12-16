# UI Panels
"""
UI面板模块

包含：
- file_browser_panel.py: 文件浏览器面板
- code_editor_panel.py: 代码编辑器面板（已拆分为子模块）
  - editor/: 代码编辑器核心组件
  - highlighters/: 语法高亮器
  - viewers/: 文件预览器
- conversation_panel.py: 对话面板主类
- conversation/: 对话面板子模块
  - conversation_view_model.py: ViewModel 层
"""

from presentation.panels.file_browser_panel import (
    FileBrowserPanel,
    FileFilterProxyModel,
    ALLOWED_EXTENSIONS,
    HIDDEN_DIRECTORIES,
)

# 从子模块直接导入
from presentation.panels.editor import CodeEditor, LineNumberArea
from presentation.panels.highlighters import SpiceHighlighter, JsonHighlighter, PythonHighlighter
from presentation.panels.viewers import ImageViewer, DocumentViewer

# 从主面板模块导入
from presentation.panels.code_editor_panel import (
    CodeEditorPanel,
    EDITABLE_EXTENSIONS,
    IMAGE_EXTENSIONS,
    DOCUMENT_EXTENSIONS,
)

# 从对话面板主类导入
from presentation.panels.conversation_panel import (
    ConversationPanel,
    PANEL_BACKGROUND,
    USER_MESSAGE_BG,
    ASSISTANT_MESSAGE_BG,
    PRIMARY_COLOR,
)

# 从对话面板子模块导入
from presentation.panels.conversation import (
    ConversationViewModel,
    DisplayMessage,
    SuggestionItem,
    SUGGESTION_STATE_ACTIVE,
    SUGGESTION_STATE_SELECTED,
    SUGGESTION_STATE_EXPIRED,
)

__all__ = [
    # File Browser
    "FileBrowserPanel",
    "FileFilterProxyModel",
    "ALLOWED_EXTENSIONS",
    "HIDDEN_DIRECTORIES",
    # Code Editor
    "CodeEditorPanel",
    "CodeEditor",
    "LineNumberArea",
    "SpiceHighlighter",
    "JsonHighlighter",
    "PythonHighlighter",
    "ImageViewer",
    "DocumentViewer",
    "EDITABLE_EXTENSIONS",
    "IMAGE_EXTENSIONS",
    "DOCUMENT_EXTENSIONS",
    # Conversation Panel
    "ConversationPanel",
    "PANEL_BACKGROUND",
    "USER_MESSAGE_BG",
    "ASSISTANT_MESSAGE_BG",
    "PRIMARY_COLOR",
    # Conversation ViewModel
    "ConversationViewModel",
    "DisplayMessage",
    "SuggestionItem",
    "SUGGESTION_STATE_ACTIVE",
    "SUGGESTION_STATE_SELECTED",
    "SUGGESTION_STATE_EXPIRED",
]
