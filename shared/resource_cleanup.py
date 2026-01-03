# Resource Cleanup Manager - Centralized Resource Cleanup
"""
资源清理管理器 - 集中式资源清理（3.0.10）

职责：
- 统一管理需要清理的资源
- 提供资源注册和清理接口
- 确保停止时正确释放所有资源
- 记录清理状态和错误

资源类型：
- HTTP 连接：调用 session.close() 或 response.close()
- 异步生成器：调用 await gen.aclose()
- 文件句柄：确保 finally 块中关闭
- 临时文件：删除未完成的临时文件
- 内存缓冲：清空流式输出缓冲区

使用示例：
    from shared.resource_cleanup import ResourceCleanupManager
    
    manager = ResourceCleanupManager()
    
    # 注册资源
    manager.register_http_session(session, "llm_api")
    manager.register_async_generator(gen, "stream_response")
    manager.register_file_handle(file, "temp_output")
    manager.register_temp_file(path, "cache_file")
    
    # 清理所有资源
    result = await manager.cleanup_all()
"""

import asyncio
import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union


# ============================================================
# 枚举定义
# ============================================================

class ResourceType(Enum):
    """资源类型"""
    HTTP_SESSION = "http_session"
    HTTP_RESPONSE = "http_response"
    ASYNC_GENERATOR = "async_generator"
    FILE_HANDLE = "file_handle"
    TEMP_FILE = "temp_file"
    MEMORY_BUFFER = "memory_buffer"
    CUSTOM = "custom"


class CleanupStatus(Enum):
    """清理状态"""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


# ============================================================
# 数据结构
# ============================================================

@dataclass
class ResourceEntry:
    """资源条目"""
    resource_type: ResourceType
    resource: Any
    name: str
    cleanup_func: Optional[Callable] = None
    status: CleanupStatus = CleanupStatus.PENDING
    error: Optional[str] = None
    registered_at: float = field(default_factory=lambda: __import__('time').time())


@dataclass
class CleanupResult:
    """清理结果"""
    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    errors: List[str] = field(default_factory=list)
    duration_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
        }


# ============================================================
# ResourceCleanupManager 类
# ============================================================

class ResourceCleanupManager:
    """
    资源清理管理器
    
    集中管理需要清理的资源，确保停止时正确释放。
    """
    
    def __init__(self):
        """初始化资源清理管理器"""
        self._resources: Dict[str, ResourceEntry] = {}
        self._lock = threading.RLock()
        self._logger = None
    
    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("resource_cleanup")
            except Exception:
                pass
        return self._logger
    
    # ============================================================
    # 资源注册方法
    # ============================================================
    
    def register_http_session(
        self,
        session: Any,
        name: str,
        cleanup_func: Optional[Callable] = None
    ) -> str:
        """
        注册 HTTP 会话
        
        Args:
            session: HTTP 会话对象（如 aiohttp.ClientSession）
            name: 资源名称
            cleanup_func: 自定义清理函数，默认调用 session.close()
            
        Returns:
            str: 资源 ID
        """
        return self._register(
            ResourceType.HTTP_SESSION,
            session,
            name,
            cleanup_func or (lambda: session.close())
        )
    
    def register_http_response(
        self,
        response: Any,
        name: str,
        cleanup_func: Optional[Callable] = None
    ) -> str:
        """
        注册 HTTP 响应
        
        Args:
            response: HTTP 响应对象
            name: 资源名称
            cleanup_func: 自定义清理函数，默认调用 response.close()
            
        Returns:
            str: 资源 ID
        """
        return self._register(
            ResourceType.HTTP_RESPONSE,
            response,
            name,
            cleanup_func or (lambda: response.close())
        )
    
    def register_async_generator(
        self,
        gen: Any,
        name: str
    ) -> str:
        """
        注册异步生成器
        
        Args:
            gen: 异步生成器对象
            name: 资源名称
            
        Returns:
            str: 资源 ID
        """
        async def cleanup():
            await gen.aclose()
        
        return self._register(
            ResourceType.ASYNC_GENERATOR,
            gen,
            name,
            cleanup
        )
    
    def register_file_handle(
        self,
        file_handle: Any,
        name: str
    ) -> str:
        """
        注册文件句柄
        
        Args:
            file_handle: 文件句柄对象
            name: 资源名称
            
        Returns:
            str: 资源 ID
        """
        return self._register(
            ResourceType.FILE_HANDLE,
            file_handle,
            name,
            lambda: file_handle.close() if not file_handle.closed else None
        )
    
    def register_temp_file(
        self,
        path: Union[str, Path],
        name: str
    ) -> str:
        """
        注册临时文件
        
        Args:
            path: 临时文件路径
            name: 资源名称
            
        Returns:
            str: 资源 ID
        """
        def cleanup():
            p = Path(path)
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
        
        return self._register(
            ResourceType.TEMP_FILE,
            path,
            name,
            cleanup
        )
    
    def register_memory_buffer(
        self,
        buffer: Any,
        name: str,
        clear_func: Optional[Callable] = None
    ) -> str:
        """
        注册内存缓冲区
        
        Args:
            buffer: 缓冲区对象
            name: 资源名称
            clear_func: 清空函数，默认调用 buffer.clear()
            
        Returns:
            str: 资源 ID
        """
        return self._register(
            ResourceType.MEMORY_BUFFER,
            buffer,
            name,
            clear_func or (lambda: buffer.clear() if hasattr(buffer, 'clear') else None)
        )
    
    def register_custom(
        self,
        resource: Any,
        name: str,
        cleanup_func: Callable
    ) -> str:
        """
        注册自定义资源
        
        Args:
            resource: 资源对象
            name: 资源名称
            cleanup_func: 清理函数
            
        Returns:
            str: 资源 ID
        """
        return self._register(
            ResourceType.CUSTOM,
            resource,
            name,
            cleanup_func
        )
    
    def _register(
        self,
        resource_type: ResourceType,
        resource: Any,
        name: str,
        cleanup_func: Callable
    ) -> str:
        """
        内部注册方法
        
        Args:
            resource_type: 资源类型
            resource: 资源对象
            name: 资源名称
            cleanup_func: 清理函数
            
        Returns:
            str: 资源 ID
        """
        import uuid
        resource_id = f"{resource_type.value}_{name}_{uuid.uuid4().hex[:8]}"
        
        with self._lock:
            self._resources[resource_id] = ResourceEntry(
                resource_type=resource_type,
                resource=resource,
                name=name,
                cleanup_func=cleanup_func,
            )
        
        if self.logger:
            self.logger.debug(f"Resource registered: {resource_id}")
        
        return resource_id
    
    # ============================================================
    # 资源注销方法
    # ============================================================
    
    def unregister(self, resource_id: str) -> bool:
        """
        注销资源
        
        Args:
            resource_id: 资源 ID
            
        Returns:
            bool: 是否成功注销
        """
        with self._lock:
            if resource_id in self._resources:
                del self._resources[resource_id]
                if self.logger:
                    self.logger.debug(f"Resource unregistered: {resource_id}")
                return True
        return False
    
    def unregister_by_name(self, name: str) -> int:
        """
        按名称注销资源
        
        Args:
            name: 资源名称
            
        Returns:
            int: 注销的资源数量
        """
        with self._lock:
            to_remove = [
                rid for rid, entry in self._resources.items()
                if entry.name == name
            ]
            for rid in to_remove:
                del self._resources[rid]
            
            if self.logger and to_remove:
                self.logger.debug(f"Resources unregistered by name '{name}': {len(to_remove)}")
            
            return len(to_remove)
    
    # ============================================================
    # 清理方法
    # ============================================================
    
    async def cleanup_all(self) -> CleanupResult:
        """
        清理所有注册的资源
        
        Returns:
            CleanupResult: 清理结果
        """
        import time
        start_time = time.time()
        
        result = CleanupResult()
        
        with self._lock:
            entries = list(self._resources.items())
            result.total = len(entries)
        
        for resource_id, entry in entries:
            try:
                await self._cleanup_entry(entry)
                entry.status = CleanupStatus.SUCCESS
                result.success += 1
                
                if self.logger:
                    self.logger.debug(f"Resource cleaned: {resource_id}")
                    
            except Exception as e:
                entry.status = CleanupStatus.FAILED
                entry.error = str(e)
                result.failed += 1
                result.errors.append(f"{resource_id}: {e}")
                
                if self.logger:
                    self.logger.warning(f"Resource cleanup failed: {resource_id}, error={e}")
        
        # 清空资源列表
        with self._lock:
            self._resources.clear()
        
        result.duration_ms = (time.time() - start_time) * 1000
        
        if self.logger:
            self.logger.info(
                f"Cleanup completed: total={result.total}, success={result.success}, "
                f"failed={result.failed}, duration={result.duration_ms:.0f}ms"
            )
        
        return result
    
    def cleanup_all_sync(self) -> CleanupResult:
        """
        同步清理所有注册的资源
        
        用于非异步上下文中的清理。
        
        Returns:
            CleanupResult: 清理结果
        """
        import time
        start_time = time.time()
        
        result = CleanupResult()
        
        with self._lock:
            entries = list(self._resources.items())
            result.total = len(entries)
        
        for resource_id, entry in entries:
            try:
                self._cleanup_entry_sync(entry)
                entry.status = CleanupStatus.SUCCESS
                result.success += 1
                
                if self.logger:
                    self.logger.debug(f"Resource cleaned (sync): {resource_id}")
                    
            except Exception as e:
                entry.status = CleanupStatus.FAILED
                entry.error = str(e)
                result.failed += 1
                result.errors.append(f"{resource_id}: {e}")
                
                if self.logger:
                    self.logger.warning(f"Resource cleanup failed (sync): {resource_id}, error={e}")
        
        # 清空资源列表
        with self._lock:
            self._resources.clear()
        
        result.duration_ms = (time.time() - start_time) * 1000
        
        if self.logger:
            self.logger.info(
                f"Cleanup completed (sync): total={result.total}, success={result.success}, "
                f"failed={result.failed}, duration={result.duration_ms:.0f}ms"
            )
        
        return result
    
    async def _cleanup_entry(self, entry: ResourceEntry) -> None:
        """
        清理单个资源条目（异步）
        
        Args:
            entry: 资源条目
        """
        if entry.cleanup_func is None:
            return
        
        # 检查是否为协程函数
        if asyncio.iscoroutinefunction(entry.cleanup_func):
            await entry.cleanup_func()
        else:
            entry.cleanup_func()
    
    def _cleanup_entry_sync(self, entry: ResourceEntry) -> None:
        """
        清理单个资源条目（同步）
        
        Args:
            entry: 资源条目
        """
        if entry.cleanup_func is None:
            return
        
        # 如果是协程函数，尝试在事件循环中运行
        if asyncio.iscoroutinefunction(entry.cleanup_func):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 在运行中的循环中创建任务
                    asyncio.ensure_future(entry.cleanup_func())
                else:
                    loop.run_until_complete(entry.cleanup_func())
            except RuntimeError:
                # 没有事件循环，创建新的
                asyncio.run(entry.cleanup_func())
        else:
            entry.cleanup_func()
    
    async def cleanup_by_type(self, resource_type: ResourceType) -> CleanupResult:
        """
        按类型清理资源
        
        Args:
            resource_type: 资源类型
            
        Returns:
            CleanupResult: 清理结果
        """
        import time
        start_time = time.time()
        
        result = CleanupResult()
        
        with self._lock:
            entries = [
                (rid, entry) for rid, entry in self._resources.items()
                if entry.resource_type == resource_type
            ]
            result.total = len(entries)
        
        cleaned_ids = []
        for resource_id, entry in entries:
            try:
                await self._cleanup_entry(entry)
                entry.status = CleanupStatus.SUCCESS
                result.success += 1
                cleaned_ids.append(resource_id)
                
            except Exception as e:
                entry.status = CleanupStatus.FAILED
                entry.error = str(e)
                result.failed += 1
                result.errors.append(f"{resource_id}: {e}")
        
        # 移除已清理的资源
        with self._lock:
            for rid in cleaned_ids:
                self._resources.pop(rid, None)
        
        result.duration_ms = (time.time() - start_time) * 1000
        
        return result
    
    # ============================================================
    # 状态查询
    # ============================================================
    
    def get_resource_count(self) -> int:
        """获取注册的资源数量"""
        with self._lock:
            return len(self._resources)
    
    def get_resources_by_type(self, resource_type: ResourceType) -> List[str]:
        """
        获取指定类型的资源 ID 列表
        
        Args:
            resource_type: 资源类型
            
        Returns:
            List[str]: 资源 ID 列表
        """
        with self._lock:
            return [
                rid for rid, entry in self._resources.items()
                if entry.resource_type == resource_type
            ]
    
    def has_pending_resources(self) -> bool:
        """检查是否有待清理的资源"""
        with self._lock:
            return len(self._resources) > 0


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ResourceCleanupManager",
    "ResourceType",
    "CleanupStatus",
    "ResourceEntry",
    "CleanupResult",
]
