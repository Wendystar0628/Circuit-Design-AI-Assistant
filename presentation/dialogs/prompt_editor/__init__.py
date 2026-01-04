# Prompt Editor Module
"""
Prompt 设置模块

提供可视化界面让用户查看、编辑和管理 Prompt 模板和身份提示词。

组件：
- PromptEditorDialog: 主对话框（标签页容器）
- WorkflowPromptTab: 工作流模式标签页
- IdentityPromptTab: 身份提示词标签页
- PromptEditorViewModel: 工作流模式业务逻辑层
- PromptContentEditor: 模板内容编辑器
- PromptVariablePanel: 变量面板
"""

from .prompt_editor_dialog import PromptEditorDialog
from .workflow_prompt_tab import WorkflowPromptTab
from .identity_prompt_tab import IdentityPromptTab
from .prompt_editor_view_model import PromptEditorViewModel
from .prompt_content_editor import PromptContentEditor
from .prompt_variable_panel import PromptVariablePanel

__all__ = [
    "PromptEditorDialog",
    "WorkflowPromptTab",
    "IdentityPromptTab",
    "PromptEditorViewModel",
    "PromptContentEditor",
    "PromptVariablePanel",
]
