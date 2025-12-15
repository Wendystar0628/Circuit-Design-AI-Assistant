# Persistence
"""
持久化模块

包含：
- file_exceptions.py: 文件操作异常类定义
- file_lock.py: 文件锁管理
- file_manager.py: 统一文件操作管理器
- json_repository.py: JSON存储操作
"""

# 异常类（从独立模块导入）
from infrastructure.persistence.file_exceptions import (
    FileManagerError,
    PathSecurityError,
    FileExistsError,
    DirectoryCreationError,
    SearchNotFoundError,
    MultipleMatchError,
    LineRangeError,
    FileLockTimeoutError,
    FileOperationError,
)

# 文件锁（从独立模块导入）
from infrastructure.persistence.file_lock import FileLock

# 主类
from infrastructure.persistence.file_manager import FileManager
from infrastructure.persistence.json_repository import JsonRepository

__all__ = [
    # 主类
    "FileManager",
    "FileLock",
    "JsonRepository",
    # 异常类
    "FileManagerError",
    "PathSecurityError",
    "FileExistsError",
    "DirectoryCreationError",
    "SearchNotFoundError",
    "MultipleMatchError",
    "LineRangeError",
    "FileLockTimeoutError",
    "FileOperationError",
]
