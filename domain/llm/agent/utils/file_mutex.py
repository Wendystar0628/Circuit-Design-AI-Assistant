# File Mutex - 文件写入互斥队列
"""
文件写入互斥队列

职责：
- 对同一文件路径的写入操作串行化，防止并发写入导致数据损坏
- 不同文件路径的操作可并行执行
- 自动清理不再使用的锁

参考来源：
- pi-mono: packages/coding-agent/src/core/tools/file-mutation-queue.ts
  - withFileMutationQueue(): 基于 Promise 链的文件互斥队列
  - getMutationQueueKey(): 解析真实路径作为锁的 key

设计说明：
- 使用 asyncio.Lock 替代 Promise 链实现互斥
- 使用 os.path.realpath 解析符号链接，确保同一文件不同路径共用同一把锁
- 通过引用计数自动清理不再使用的锁，避免内存泄漏

使用示例：
    from domain.llm.agent.utils.file_mutex import with_file_mutex

    async with with_file_mutex("/path/to/file.txt"):
        # 此处对 file.txt 的操作是互斥的
        content = read_file(...)
        write_file(...)
"""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Dict, Tuple


# 模块级锁存储：key → (Lock, ref_count)
_file_locks: Dict[str, Tuple[asyncio.Lock, int]] = {}
_registry_lock = asyncio.Lock()


def _get_mutex_key(file_path: str) -> str:
    """
    获取文件互斥锁的 key
    
    对应 pi-mono getMutationQueueKey()：
    解析为真实路径，确保同一文件的不同路径表示共用同一把锁。
    
    Args:
        file_path: 文件路径
        
    Returns:
        规范化后的路径字符串（小写，用于 Windows 大小写不敏感文件系统）
    """
    try:
        resolved = os.path.realpath(file_path)
    except OSError:
        resolved = os.path.normpath(file_path)
    
    # Windows 文件系统大小写不敏感
    if os.name == 'nt':
        resolved = resolved.lower()
    
    return resolved


@asynccontextmanager
async def with_file_mutex(file_path: str):
    """
    文件写入互斥上下文管理器
    
    对应 pi-mono withFileMutationQueue()：
    - 同一文件路径的操作串行执行
    - 不同文件路径的操作可并行
    - 使用引用计数自动清理不再使用的锁
    
    Args:
        file_path: 文件绝对路径
        
    Usage:
        async with with_file_mutex(abs_path):
            # 互斥的文件操作
            ...
    """
    key = _get_mutex_key(file_path)
    
    # 获取或创建锁（需要在注册表锁保护下操作）
    async with _registry_lock:
        if key in _file_locks:
            lock, count = _file_locks[key]
            _file_locks[key] = (lock, count + 1)
        else:
            lock = asyncio.Lock()
            _file_locks[key] = (lock, 1)
    
    # 获取文件锁
    async with lock:
        try:
            yield
        finally:
            # 释放引用计数
            async with _registry_lock:
                if key in _file_locks:
                    current_lock, count = _file_locks[key]
                    if count <= 1:
                        del _file_locks[key]
                    else:
                        _file_locks[key] = (current_lock, count - 1)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "with_file_mutex",
]
