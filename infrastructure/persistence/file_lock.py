# File Lock - File Locking Mechanism
"""
文件锁管理

职责：
- 提供进程内文件锁定机制
- 防止同一进程内的并发写入导致数据损坏

职责边界说明：
- FileLock 解决的问题：同一进程内多个线程同时写入同一文件
- FileLock 不解决的问题：LLM "读取-思考-写入"期间用户修改文件的竞态条件（TOCTOU）
- TOCTOU 竞态条件由 FileVersionTracker（file_version_tracker.py）通过乐观锁机制解决

设计说明：
- 使用全局锁注册表，确保同一文件路径共享同一个底层锁
- 支持上下文管理器（with 语句）
- 默认超时 5 秒

线程安全说明：
- FileLock 基于 threading.Lock，锁的获取和释放必须在同一线程内闭环
- 通过 asyncio.to_thread() 调用时，锁操作在工作线程内完成，不会跨线程
- UI 线程禁止直接调用持有锁的同步方法，避免与工作线程竞争
- 若 UI 线程需要访问文件，必须通过 AsyncFileOps 异步接口

使用示例：
    from infrastructure.persistence.file_lock import FileLock
    
    # 方式一：上下文管理器（推荐）
    with FileLock("/path/to/file") as lock:
        # 执行文件操作
        pass
    
    # 方式二：手动获取和释放
    lock = FileLock("/path/to/file", timeout=5.0)
    if lock.acquire():
        try:
            # 执行文件操作
            pass
        finally:
            lock.release()
    
    # 方式三：在异步上下文中使用（通过 AsyncFileOps）
    # 锁操作在工作线程内闭环，主线程不阻塞
    content = await async_file_ops.read_file_async("main.cir")
"""

import threading
from pathlib import Path
from typing import Dict, Optional

from .file_exceptions import FileLockTimeoutError


# ============================================================
# 全局锁注册表
# ============================================================

class _LockRegistry:
    """
    全局锁注册表（单例）
    
    确保同一文件路径共享同一个底层锁，
    避免多个 FileLock 实例对同一文件创建独立锁导致的并发问题。
    """
    
    _instance: Optional['_LockRegistry'] = None
    _init_lock = threading.Lock()
    
    def __new__(cls) -> '_LockRegistry':
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._locks: Dict[str, threading.Lock] = {}
                    cls._instance._mutex = threading.Lock()
        return cls._instance
    
    def get_lock(self, path: str) -> threading.Lock:
        """
        获取指定路径的锁
        
        如果路径对应的锁不存在，则创建新锁。
        同一路径始终返回同一个锁实例。
        
        Args:
            path: 文件路径（会被规范化为绝对路径）
            
        Returns:
            threading.Lock: 该路径对应的锁
        """
        # 规范化路径，确保不同写法的同一路径使用同一个锁
        normalized_path = str(Path(path).resolve())
        
        with self._mutex:
            if normalized_path not in self._locks:
                self._locks[normalized_path] = threading.Lock()
            return self._locks[normalized_path]
    
    def remove_lock(self, path: str) -> bool:
        """
        移除指定路径的锁（仅用于测试）
        
        Args:
            path: 文件路径
            
        Returns:
            bool: 是否成功移除
        """
        normalized_path = str(Path(path).resolve())
        
        with self._mutex:
            if normalized_path in self._locks:
                del self._locks[normalized_path]
                return True
            return False
    
    def clear(self) -> None:
        """清空所有锁（仅用于测试）"""
        with self._mutex:
            self._locks.clear()
    
    @property
    def lock_count(self) -> int:
        """获取当前注册的锁数量"""
        with self._mutex:
            return len(self._locks)


# 全局锁注册表实例
_lock_registry = _LockRegistry()


# ============================================================
# 文件锁类
# ============================================================

class FileLock:
    """
    文件锁 - 防止并发写入
    
    使用全局锁注册表确保同一文件路径共享同一个底层锁。
    支持上下文管理器和手动获取/释放两种使用方式。
    
    线程安全说明：
    - 同一文件路径的多个 FileLock 实例共享同一个底层锁
    - acquire() 和 release() 是线程安全的
    """
    
    # 默认超时时间（秒）
    DEFAULT_TIMEOUT = 5.0
    
    def __init__(self, path: str, timeout: float = None):
        """
        初始化文件锁
        
        Args:
            path: 文件路径
            timeout: 获取锁的超时时间（秒），默认 5.0
        """
        self.path = path
        self.timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT
        self._lock = _lock_registry.get_lock(path)
        self._acquired = False
        self._owner_thread: Optional[int] = None
    
    def acquire(self, timeout: float = None) -> bool:
        """
        获取文件锁
        
        Args:
            timeout: 超时时间（秒），不指定则使用实例默认值
            
        Returns:
            bool: 是否成功获取
        """
        if timeout is None:
            timeout = self.timeout
        
        self._acquired = self._lock.acquire(timeout=timeout)
        
        if self._acquired:
            self._owner_thread = threading.current_thread().ident
        
        return self._acquired
    
    def release(self) -> None:
        """
        释放文件锁
        
        只有持有锁的线程才能释放锁。
        """
        if self._acquired:
            # 检查是否是持有锁的线程
            current_thread = threading.current_thread().ident
            if self._owner_thread == current_thread:
                self._lock.release()
                self._acquired = False
                self._owner_thread = None
    
    @property
    def is_locked(self) -> bool:
        """检查当前实例是否持有锁"""
        return self._acquired
    
    def __enter__(self) -> 'FileLock':
        """上下文管理器入口"""
        if not self.acquire():
            raise FileLockTimeoutError(self.path, self.timeout)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """上下文管理器出口"""
        self.release()
        return False  # 不抑制异常
    
    def __repr__(self) -> str:
        status = "locked" if self._acquired else "unlocked"
        return f"FileLock(path={self.path!r}, status={status})"


# ============================================================
# 便捷函数
# ============================================================

def get_lock_registry() -> _LockRegistry:
    """
    获取全局锁注册表（仅用于调试和测试）
    
    Returns:
        _LockRegistry: 全局锁注册表实例
    """
    return _lock_registry


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "FileLock",
    "get_lock_registry",
]
