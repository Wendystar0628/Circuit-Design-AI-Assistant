# Persistence
"""
持久化模块

包含：
- file_exceptions.py: 文件操作异常类定义
- file_lock.py: 文件锁管理（全局锁注册表）
- file_manager.py: 统一文件操作管理器（同步底层接口）
- async_file_ops.py: 异步文件操作门面（应用层接口）
- json_repository.py: JSON存储操作

异步 I/O 架构：
- FileManager 提供同步底层接口，禁止 UI 线程直接调用
- AsyncFileOps 提供异步应用层接口，供 UI 层和 LangGraph 节点使用
- 通过 asyncio.to_thread() 将阻塞操作卸载到线程池，避免阻塞事件循环
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
from infrastructure.persistence.file_lock import FileLock, get_lock_registry

# 主类
from infrastructure.persistence.file_manager import FileManager
from infrastructure.persistence.async_file_ops import AsyncFileOps
from infrastructure.persistence.json_repository import JsonRepository

__all__ = [
    # 主类
    "FileManager",
    "AsyncFileOps",
    "FileLock",
    "JsonRepository",
    # 锁注册表（调试用）
    "get_lock_registry",
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
