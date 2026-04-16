# UI Panels
"""
UI面板模块

包含：
- web_file_browser_panel.py: 基于 WebEngine 的工作区文件浏览器面板
- workspace_code_editor_panel.py: 工作区代码编辑器面板
  - editor/: 代码编辑器核心组件
  - viewers/: 文件预览器
- conversation_panel.py: 对话面板主类
- conversation/: 对话面板子模块
  - conversation_view_model.py: ViewModel 层
"""

from presentation.panels.web_file_browser_panel import FileBrowserPanel

# 从子模块直接导入
from presentation.panels.editor import CodeEditor

# 从主面板模块导入
from presentation.panels.workspace_code_editor_panel import CodeEditorPanel

# 从对话面板主类导入
from presentation.panels.conversation_panel import (
    ConversationPanel,
    PANEL_BACKGROUND,
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
    # Code Editor
    "CodeEditorPanel",
    "CodeEditor",
    # Conversation Panel
    "ConversationPanel",
    "PANEL_BACKGROUND",
    # Conversation ViewModel
    "ConversationViewModel",
    "DisplayMessage",
    "SuggestionItem",
    "SUGGESTION_STATE_ACTIVE",
    "SUGGESTION_STATE_SELECTED",
    "SUGGESTION_STATE_EXPIRED",
]
