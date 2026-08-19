# Persistence
"""
持久化模块

包含：
- file_exceptions.py: 文件操作异常类定义
- file_lock.py: 文件锁管理（进程内并发控制）
- file_manager.py: 统一文件操作管理器（同步接口）
- content_hash.py: 内容哈希计算器（标准化哈希计算）
- file_version_tracker.py: 文件版本追踪器（TOCTOU 竞态条件检测）

调用边界：
- FileManager 是工作区用户文件读写的同步权威入口
- 长时间或批量操作由调用者通过现有 task owner 或
  ``asyncio.to_thread()`` 卸载，不在持久化层另设一个门面

并发控制架构：
- FileLock: 进程内文件锁，防止同一进程内多线程并发写入
- FileVersionTracker: 乐观锁机制，检测 LLM 工具调用期间的外部文件修改

JSON 序列化/反序列化由
``infrastructure.utils.json_utils`` 提供纯工具函数。
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
    FileModifiedExternallyError,
)

# 文件锁（从独立模块导入）
from infrastructure.persistence.file_lock import FileLock, get_lock_registry

# 内容哈希（从独立模块导入）
from infrastructure.persistence.content_hash import (
    normalize_content,
    compute_content_hash,
    compute_file_hash,
)

# 文件版本追踪（从独立模块导入）
from infrastructure.persistence.file_version_tracker import (
    VersionCheckResult,
    FileVersionTracker,
)

# 主类
from infrastructure.persistence.file_manager import FileManager

__all__ = [
    # 主类
    "FileManager",
    "FileLock",
    # 锁注册表（调试用）
    "get_lock_registry",
    # 内容哈希
    "normalize_content",
    "compute_content_hash",
    "compute_file_hash",
    # 文件版本追踪
    "VersionCheckResult",
    "FileVersionTracker",
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
    "FileModifiedExternallyError",
]
