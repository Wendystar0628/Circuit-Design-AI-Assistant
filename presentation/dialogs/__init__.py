# Dialogs
"""
对话框模块

包含：
- api_config_dialog.py: API配置对话框（智谱GLM配置）
- about_dialog.py: 关于对话框
"""

from .api_config_dialog import ApiConfigDialog, ZHIPU_MODELS, DEFAULT_BASE_URL
from .about_dialog import AboutDialog, APP_VERSION

__all__ = [
    "ApiConfigDialog",
    "ZHIPU_MODELS",
    "DEFAULT_BASE_URL",
    "AboutDialog",
    "APP_VERSION",
]
