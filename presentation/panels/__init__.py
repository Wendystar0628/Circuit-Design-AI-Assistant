# UI Panels
"""
UI面板模块

包含：
- file_browser_panel.py: 文件浏览器面板
- code_editor_panel.py: 代码编辑器面板
- chat_panel.py: LLM对话面板
- simulation_panel.py: 仿真结果面板
"""

from presentation.panels.file_browser_panel import (
    FileBrowserPanel,
    FileFilterProxyModel,
    ALLOWED_EXTENSIONS,
    HIDDEN_DIRECTORIES,
)

from presentation.panels.code_editor_panel import (
    CodeEditorPanel,
    CodeEditor,
    SpiceHighlighter,
    JsonHighlighter,
    ImageViewer,
    DocumentViewer,
    EDITABLE_EXTENSIONS,
    IMAGE_EXTENSIONS,
    DOCUMENT_EXTENSIONS,
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
    "SpiceHighlighter",
    "JsonHighlighter",
    "ImageViewer",
    "DocumentViewer",
    "EDITABLE_EXTENSIONS",
    "IMAGE_EXTENSIONS",
    "DOCUMENT_EXTENSIONS",
]
