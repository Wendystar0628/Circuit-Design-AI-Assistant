# Persistence
"""
持久化模块

包含：
- file_exceptions.py: 文件操作异常类定义
- file_lock.py: 文件锁管理（进程内并发控制）
- file_manager.py: 统一文件操作管理器（同步底层接口）
- async_file_ops.py: 异步文件操作门面（应用层接口，含 JSON 操作）
- content_hash.py: 内容哈希计算器（标准化哈希计算）
- file_version_tracker.py: 文件版本追踪器（TOCTOU 竞态条件检测）

异步 I/O 架构：
- FileManager 提供同步底层接口，禁止 UI 线程直接调用
- AsyncFileOps 提供异步应用层接口，供 UI 层和 LangGraph 节点使用
- 通过 asyncio.to_thread() 将阻塞操作卸载到线程池，避免阻塞事件循环

并发控制架构：
- FileLock: 进程内文件锁，防止同一进程内多线程并发写入
- FileVersionTracker: 乐观锁机制，检测 LLM 工具调用期间的外部文件修改

JSON 操作说明：
- JSON 序列化/反序列化使用 infrastructure/utils/json_utils.py 提供的工具函数
- 异步 JSON 文件操作通过 AsyncFileOps 的 load_json_async / save_json_async 方法
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
from infrastructure.persistence.async_file_ops import AsyncFileOps

__all__ = [
    # 主类
    "FileManager",
    "AsyncFileOps",
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
