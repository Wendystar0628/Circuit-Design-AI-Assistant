# Prompt Editor Module
"""
Prompt 模板编辑器模块

提供可视化界面让用户查看、编辑和管理 Prompt 模板。

组件：
- PromptEditorDialog: 主对话框
- PromptEditorViewModel: 业务逻辑层
- PromptContentEditor: 模板内容编辑器
- PromptVariablePanel: 变量面板
"""

from .prompt_editor_dialog import PromptEditorDialog
from .prompt_editor_view_model import PromptEditorViewModel
from .prompt_content_editor import PromptContentEditor
from .prompt_variable_panel import PromptVariablePanel

__all__ = [
    "PromptEditorDialog",
    "PromptEditorViewModel",
    "PromptContentEditor",
    "PromptVariablePanel",
]
