# Constants Package
"""
常量定义包

包含所有系统级常量定义。
"""

from shared.constants.paths import *

__all__ = [
    # 从 paths 模块导出
    "SYSTEM_DIR",
    "SIM_RESULTS_DIR",
    "SIM_CONFIG_FILE",
    "ANALYSIS_SELECTION_FILE",
    "CHART_SELECTION_FILE",
    "DESIGN_GOALS_FILE",
    "ITERATION_HISTORY_FILE",
    "UNDO_SNAPSHOTS_DIR",
    "SNAPSHOTS_DIR",
    "CONVERSATIONS_DIR",
    "TEMP_DIR",
    "CHECKPOINTS_DB",
]
