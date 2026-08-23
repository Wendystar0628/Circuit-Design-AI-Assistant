# File Watch Task - File System Monitoring
"""
文件监听任务 - 监测工作文件夹的文件变化

职责：
- 监测工作文件夹的文件变化（创建、修改、删除、重命名）
- 过滤无关文件和目录
- 防抖处理，合并短时间内的多次变化
- 通过 EventBus 发布文件变更事件

实现方式：
- 使用 watchdog 库的 Observer 和 FileSystemEventHandler
- Observer 在独立线程中运行（watchdog 内部管理）
- 使用 threading.Timer 合并短时间内的重复事件
- watchdog 工作线程可直接通过线程安全的 EventBus 发布事件

生命周期管理：
- watchdog 自带 Observer 线程并提供显式 stop 生命周期
- 通过 ServiceLocator 注册为单例服务
- 应用关闭时由 bootstrap 调用 stop_watching()

使用示例：
    from shared.service_locator import ServiceLocator
    from shared.service_names import SVC_FILE_WATCHER
    
    file_watcher = ServiceLocator.get(SVC_FILE_WATCHER)
    
    # 启动监听
    file_watcher.start_watching("/path/to/project")
    
    # 停止监听
    file_watcher.stop_watching()
"""

import threading
from pathlib import Path
from typing import Any, Dict, Optional

from watchdog.observers import Observer
from watchdog.events import (
    FileSystemEvent,
    FileSystemEventHandler,
)


# ============================================================
# 常量定义
# ============================================================

# 防抖间隔（毫秒）
DEBOUNCE_INTERVAL_MS = 200

# 忽略的目录名
IGNORED_DIRS = {
    ".circuit_ai",
    "simulation_results",
    ".git",
    "__pycache__",
    ".vscode",
    ".idea",
    "node_modules",
    ".venv",
    "venv",
}

# 忽略的文件后缀
IGNORED_EXTENSIONS = {
    ".tmp",
    ".swp",
    ".bak",
    ".pyc",
    ".pyo",
    ".log",
}

# 忽略的文件名模式
IGNORED_PATTERNS = {
    "~",  # 备份文件后缀
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}


# ============================================================
# 事件接收器与防抖
# ============================================================

class FileWatchReceiver:
    """
    接收 watchdog 工作线程事件，防抖后通过 EventBus 发布。

    EventBus 支持从任意线程同步发布，因此这里不需要 UI 线程桥接。
    """

    def __init__(self):
        # 防抖缓冲区：{file_path: event_data}
        self._debounce_buffer: Dict[str, Dict[str, Any]] = {}
        self._debounce_lock = threading.RLock()
        self._debounce_timer: Optional[threading.Timer] = None
        self._debounce_generation = 0

        # 延迟获取的服务
        self._event_bus = None
        self._file_manager = None
        self._logger = None
    
    @property
    def event_bus(self):
        """延迟获取 EventBus"""
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus
    
    @property
    def logger(self):
        """延迟获取 Logger"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("file_watcher")
            except Exception:
                pass
        return self._logger

    @property
    def file_manager(self):
        if self._file_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_FILE_MANAGER

                self._file_manager = ServiceLocator.get_optional(SVC_FILE_MANAGER)
            except Exception:
                pass
        return self._file_manager
    
    def on_file_event(
        self,
        path: str,
        event_type: str,
        is_directory: bool,
        dest_path: str,
        project_root: str,
        generation: int,
    ) -> None:
        """Queue one watchdog event for latest-only per-path delivery."""
        operation = {
            "created": "create",
            "modified": "update",
            "deleted": "delete",
            "moved": "move",
        }.get(event_type)
        if operation is None or not project_root or generation <= 0:
            return

        # Capture project identity with the watchdog notification.  Do not
        # resolve it later from mutable FileManager state after a project switch.
        event_data = {
            "path": path,
            "operation": operation,
            "is_directory": is_directory,
            "dest_path": dest_path or "",
            "project_root": project_root,
            "generation": generation,
        }
        
        with self._debounce_lock:
            # 同一路径仅保留最近事件。
            self._debounce_buffer[path] = event_data
            self._restart_debounce_timer_locked()
    
    def _restart_debounce_timer_locked(self) -> None:
        timer = self._debounce_timer
        if timer is not None:
            timer.cancel()
        self._debounce_generation += 1
        generation = self._debounce_generation
        timer = threading.Timer(
            DEBOUNCE_INTERVAL_MS / 1000.0,
            self._flush_debounce_buffer,
            args=(generation,),
        )
        timer.daemon = True
        self._debounce_timer = timer
        timer.start()

    def _flush_debounce_buffer(
        self,
        expected_generation: Optional[int] = None,
    ) -> None:
        """刷新防抖缓冲区，发布所有缓冲的事件"""
        with self._debounce_lock:
            if (
                expected_generation is not None
                and expected_generation != self._debounce_generation
            ):
                return
            timer = self._debounce_timer
            self._debounce_timer = None
            if timer is not None:
                timer.cancel()
            events_to_publish = self._debounce_buffer
            self._debounce_buffer = {}
        if not events_to_publish:
            return
        
        # 发布事件
        if self.event_bus:
            from shared.event_types import EVENT_FILE_CHANGED
            from shared.file_change import FileChange
            
            for path, event_data in events_to_publish.items():
                try:
                    file_manager = self.file_manager
                    operation = event_data["operation"]
                    dest_path = event_data.get("dest_path", "")
                    if (
                        file_manager is not None
                        and file_manager.consume_recent_internal_change(
                            path,
                            operation=operation,
                            dest_path=dest_path,
                        )
                    ):
                        continue

                    revision_path = dest_path if operation == "move" else path
                    revision = (
                        file_manager.get_path_revision(revision_path)
                        if file_manager is not None
                        else ""
                    )
                    change = FileChange(
                        operation=operation,
                        path=path,
                        dest_path=dest_path,
                        is_directory=bool(event_data.get("is_directory", False)),
                        origin="file_watcher",
                        project_root=str(event_data.get("project_root") or ""),
                        generation=int(event_data.get("generation") or 0),
                        revision=revision,
                    )
                    self.event_bus.publish(
                        EVENT_FILE_CHANGED,
                        change.to_payload(),
                        source="file_watcher"
                    )
                    
                    if self.logger:
                        self.logger.debug(
                            f"File {change.operation}: {path}"
                        )
                except Exception as exc:
                    if self.logger:
                        self.logger.warning(f"Failed to publish file event: {exc}")
    
    def clear_buffer(self) -> None:
        """Cancel pending delivery and drop buffered events."""
        with self._debounce_lock:
            timer = self._debounce_timer
            self._debounce_timer = None
            self._debounce_generation += 1
            self._debounce_buffer.clear()
        if timer is not None:
            timer.cancel()


# ============================================================
# Watchdog 事件处理器
# ============================================================

class CircuitFileEventHandler(FileSystemEventHandler):
    """
    电路文件事件处理器
    
    在 watchdog 线程中运行，过滤事件后直接交给线程安全接收器。
    """
    
    def __init__(
        self,
        receiver: FileWatchReceiver,
        watch_root: Path,
        generation: int,
    ):
        """
        初始化事件处理器
        
        Args:
            receiver: 线程安全事件接收器
            watch_root: 监听根目录
        """
        super().__init__()
        self._receiver = receiver
        self._watch_root = watch_root
        self._generation = generation
        self._logger = None
    
    @property
    def logger(self):
        """延迟获取 Logger"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("file_watcher")
            except Exception:
                pass
        return self._logger
    
    def _should_ignore(self, path: str) -> bool:
        """
        检查是否应该忽略该路径
        
        Args:
            path: 文件或目录路径
            
        Returns:
            bool: 是否应该忽略
        """
        try:
            path_obj = Path(path)
            
            # 检查是否在忽略的目录中
            for part in path_obj.parts:
                if part in IGNORED_DIRS:
                    return True
            
            # 检查文件名模式
            name = path_obj.name
            for pattern in IGNORED_PATTERNS:
                if name.endswith(pattern) or name == pattern:
                    return True
            
            # 检查扩展名
            suffix = path_obj.suffix.lower()
            if suffix in IGNORED_EXTENSIONS:
                return True
            
            return False
            
        except Exception:
            return True
    
    def _dispatch_event(
        self,
        path: str,
        event_type: str,
        is_directory: bool,
        dest_path: str = ""
    ) -> None:
        """Filter and enqueue one filesystem event."""
        # 过滤事件
        if self._should_ignore(path):
            return
        
        if dest_path and self._should_ignore(dest_path):
            return
        
        self._receiver.on_file_event(
            path,
            event_type,
            is_directory,
            dest_path,
            str(self._watch_root),
            self._generation,
        )
    
    def on_created(self, event: FileSystemEvent) -> None:
        """处理创建事件"""
        self._dispatch_event(
            event.src_path,
            "created",
            event.is_directory
        )
    
    def on_modified(self, event: FileSystemEvent) -> None:
        """处理修改事件"""
        # 忽略目录的修改事件（通常是子文件变化触发的）
        if event.is_directory:
            return
        
        self._dispatch_event(
            event.src_path,
            "modified",
            event.is_directory
        )
    
    def on_deleted(self, event: FileSystemEvent) -> None:
        """处理删除事件"""
        self._dispatch_event(
            event.src_path,
            "deleted",
            event.is_directory
        )
    
    def on_moved(self, event: FileSystemEvent) -> None:
        """处理移动/重命名事件"""
        dest_path = getattr(event, 'dest_path', '')
        self._dispatch_event(
            event.src_path,
            "moved",
            event.is_directory,
            dest_path
        )


# ============================================================
# 文件监听任务主类
# ============================================================

class FileWatchTask:
    """
    文件监听任务
    
    管理 watchdog Observer 的生命周期，提供启动/停止监听的接口。
    
    使用示例：
        file_watcher = FileWatchTask()
        
        # 启动监听
        success = file_watcher.start_watching("/path/to/project")
        
        # 检查状态
        if file_watcher.is_watching:
            print(f"Watching: {file_watcher.watch_path}")
        
        # 停止监听
        file_watcher.stop_watching()
    """
    
    def __init__(self):
        """初始化文件监听任务"""
        # watchdog Observer
        self._observer: Optional[Observer] = None
        
        # 事件接收器
        self._receiver = FileWatchReceiver()
        
        # 当前监听路径
        self._watch_path: Optional[Path] = None
        
        # 延迟获取的服务
        self._logger = None
    
    @property
    def logger(self):
        """延迟获取 Logger"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("file_watcher")
            except Exception:
                pass
        return self._logger
    
    @property
    def is_watching(self) -> bool:
        """检查是否正在监听"""
        return self._observer is not None and self._observer.is_alive()
    
    @property
    def watch_path(self) -> Optional[str]:
        """获取当前监听路径"""
        return str(self._watch_path) if self._watch_path else None
    
    def start_watching(self, folder_path: str) -> bool:
        """
        启动文件监听
        
        Args:
            folder_path: 要监听的文件夹路径
            
        Returns:
            bool: 是否成功启动
        """
        # 如果已在监听，先停止
        if self.is_watching:
            self.stop_watching()
        
        try:
            path = Path(folder_path).resolve()
            
            # 验证路径
            if not path.exists():
                if self.logger:
                    self.logger.error(f"Watch path does not exist: {path}")
                return False
            
            if not path.is_dir():
                if self.logger:
                    self.logger.error(f"Watch path is not a directory: {path}")
                return False
            
            # 创建事件处理器
            file_manager = self._receiver.file_manager
            generation = (
                int(getattr(file_manager, "project_generation", 0))
                if file_manager is not None else 0
            )
            event_handler = CircuitFileEventHandler(
                self._receiver,
                path,
                generation=generation,
            )
            
            # 创建并启动 Observer
            self._observer = Observer()
            self._observer.schedule(
                event_handler,
                str(path),
                recursive=True  # 递归监听子目录
            )
            self._observer.start()
            
            self._watch_path = path
            
            if self.logger:
                self.logger.info(f"Started watching: {path}")
            
            return True
            
        except Exception as exc:
            if self.logger:
                self.logger.error(f"Failed to start file watching: {exc}")
            observer = self._observer
            if observer is not None:
                try:
                    observer.stop()
                    observer.join(timeout=2.0)
                except Exception:
                    pass
            self._observer = None
            self._watch_path = None
            return False
    
    def stop_watching(self) -> None:
        """停止文件监听"""
        observer = self._observer
        watched_path = self._watch_path
        self._observer = None
        self._watch_path = None
        try:
            if observer is not None:
                observer.stop()
                observer.join(timeout=2.0)
                if self.logger:
                    self.logger.info(f"Stopped watching: {watched_path}")
        except Exception as exc:
            if self.logger:
                self.logger.warning(f"Error stopping file watcher: {exc}")
        finally:
            self._receiver.clear_buffer()
    
    def restart_watching(self) -> bool:
        """
        重启文件监听（使用当前路径）
        
        Returns:
            bool: 是否成功重启
        """
        if self._watch_path is None:
            if self.logger:
                self.logger.warning("Cannot restart: no watch path set")
            return False
        
        path = str(self._watch_path)
        self.stop_watching()
        return self.start_watching(path)
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取监听状态
        
        Returns:
            dict: 状态信息
        """
        return {
            "is_watching": self.is_watching,
            "watch_path": self.watch_path,
            "observer_alive": self._observer.is_alive() if self._observer else False,
        }


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "FileWatchTask",
    "FileWatchReceiver",
    "CircuitFileEventHandler",
    "IGNORED_DIRS",
    "IGNORED_EXTENSIONS",
    "IGNORED_PATTERNS",
    "DEBOUNCE_INTERVAL_MS",
]
