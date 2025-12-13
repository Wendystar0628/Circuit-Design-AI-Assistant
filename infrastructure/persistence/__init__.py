# Persistence
"""
持久化模块

包含：
- file_manager.py: 统一文件操作管理器
- json_repository.py: JSON存储操作
"""

from infrastructure.persistence.file_manager import (
    FileManager,
    FileLock,
    FileManagerError,
    PathSecurityError,
    FileExistsError,
    DirectoryCreationError,
    SearchNotFoundError,
    MultipleMatchError,
    FileLockTimeoutError,
    FileOperationError,
)

from infrastructure.persistence.json_repository import (
    JsonRepository,
)

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
    "FileLockTimeoutError",
    "FileOperationError",
]
