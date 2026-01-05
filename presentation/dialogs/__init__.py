# Dialogs
"""
对话框模块

包含：
- model_config_dialog.py: 模型配置对话框（多厂商支持）
- api_config_dialog.py: API配置对话框（旧版，保留兼容）
- about_dialog.py: 关于对话框
- context_compress_dialog.py: 上下文压缩预览对话框
- history_dialog.py: 对话历史查看对话框
- simulation_settings_dialog.py: 仿真设置对话框
- prompt_editor/: Prompt 模板编辑器模块
"""

from .model_config_dialog import ModelConfigDialog, PROVIDER_DISPLAY_NAMES
from .api_config_dialog import ApiConfigDialog, get_zhipu_models, DEFAULT_BASE_URL
from .about_dialog import AboutDialog, APP_VERSION
from .context_compress_dialog import ContextCompressDialog
from .history_dialog import HistoryDialog, SessionInfo
from .simulation_settings_dialog import SimulationSettingsDialog
from .prompt_editor import PromptEditorDialog

__all__ = [
    # 新版模型配置对话框
    "ModelConfigDialog",
    "PROVIDER_DISPLAY_NAMES",
    # 旧版 API 配置对话框（保留兼容，建议使用 ModelConfigDialog）
    "ApiConfigDialog",
    "get_zhipu_models",
    "DEFAULT_BASE_URL",
    # 关于对话框
    "AboutDialog",
    "APP_VERSION",
    # 上下文压缩对话框
    "ContextCompressDialog",
    # 对话历史对话框
    "HistoryDialog",
    "SessionInfo",
    # 仿真设置对话框
    "SimulationSettingsDialog",
    # Prompt 模板编辑器
    "PromptEditorDialog",
]
