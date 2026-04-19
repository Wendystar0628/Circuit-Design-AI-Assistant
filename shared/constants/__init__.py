# Constants Package
"""
常量定义包

包含所有系统级常量定义。
"""

from shared.constants.paths import (
    SYSTEM_DIR,
    SIM_CONFIG_FILE,
    SNAPSHOTS_DIR,
    CONVERSATIONS_DIR,
    TEMP_DIR,
    CHECKPOINTS_DB,
)

__all__ = [
    # 从 paths 模块导出
    "SYSTEM_DIR",
    "SIM_CONFIG_FILE",
    "SNAPSHOTS_DIR",
    "CONVERSATIONS_DIR",
    "TEMP_DIR",
    "CHECKPOINTS_DB",
]
