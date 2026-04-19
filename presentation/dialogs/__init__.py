# Dialogs
"""
对话框模块

包含：
- about_dialog.py: 关于对话框
- context_compress_dialog.py: 上下文压缩预览对话框
"""

from .about_dialog import AboutDialog, APP_VERSION
from .context_compress_dialog import ContextCompressDialog
__all__ = [
    # 关于对话框
    "AboutDialog",
    "APP_VERSION",
    # 上下文压缩对话框
    "ContextCompressDialog",
]
