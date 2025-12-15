# File Lock - File Locking Mechanism
"""
文件锁管理

职责：
- 提供进程内文件锁定机制
- 防止并发写入导致数据损坏

使用示例：
    from infrastructure.persistence.file_lock import FileLock
    
    lock = FileLock("/path/to/file", timeout=5.0)
    
    # 方式一：手动获取和释放
    if lock.acquire():
        try:
            # 执行文件操作
            pass
        finally:
            lock.release()
    
    # 方式二：上下文管理器
    with FileLock("/path/to/file") as lock:
        # 执行文件操作
        pass
"""

import threading

from .file_exceptions import FileLockTimeoutError


class FileLock:
    """
    文件锁 - 防止并发写入
    
    使用 threading.Lock 实现进程内锁定
    """
    
    def __init__(self, path: str, timeout: float = 5.0):
        self.path = path
        self.timeout = timeout
        self._lock = threading.Lock()
        self._acquired = False
    
    def acquire(self) -> bool:
        """
        获取文件锁
        
        Returns:
            bool: 是否成功获取
        """
        self._acquired = self._lock.acquire(timeout=self.timeout)
        return self._acquired
    
    def release(self) -> None:
        """释放文件锁"""
        if self._acquired:
            self._lock.release()
            self._acquired = False
    
    def __enter__(self):
        if not self.acquire():
            raise FileLockTimeoutError(self.path, self.timeout)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "FileLock",
]
