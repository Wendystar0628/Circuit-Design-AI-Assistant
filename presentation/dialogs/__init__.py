# Dialogs
"""
对话框模块

包含：
- model_config_dialog.py: 模型配置对话框（多厂商支持）
- about_dialog.py: 关于对话框
- context_compress_dialog.py: 上下文压缩预览对话框
- iteration_history_dialog.py: 迭代历史记录对话框
- design_goals_dialog.py: 设计目标编辑对话框
"""

from .model_config_dialog import ModelConfigDialog
from .about_dialog import AboutDialog, APP_VERSION
from .context_compress_dialog import ContextCompressDialog
from .iteration_history_dialog import IterationHistoryDialog, IterationRecord
from .design_goals_dialog import DesignGoalsDialog, GoalEditDialog
__all__ = [
    # 新版模型配置对话框
    "ModelConfigDialog",
    # 关于对话框
    "AboutDialog",
    "APP_VERSION",
    # 上下文压缩对话框
    "ContextCompressDialog",
    # 迭代历史记录对话框
    "IterationHistoryDialog",
    "IterationRecord",
    # 设计目标编辑对话框
    "DesignGoalsDialog",
    "GoalEditDialog",
]
