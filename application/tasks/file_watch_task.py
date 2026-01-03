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
- 事件通过 QMetaObject.invokeMethod 转发到主线程
- 主线程通过 EventBus.publish() 发布 EVENT_FILE_CHANGED 事件

生命周期管理：
- 不通过 AsyncTaskRegistry 管理（watchdog 自带线程管理）
- 通过 ServiceLocator 注册为单例服务
- 应用关闭时由 ResourceCleanup 调用 stop_watching()

使用示例：
    from shared.service_locator import ServiceLocator
    from shared.service_names import SVC_FILE_WATCHER
    
    file_watcher = ServiceLocator.get(SVC_FILE_WATCHER)
    
    # 启动监听
    file_watcher.start_watching("/path/to/project")
    
    # 停止监听
    file_watcher.stop_watching()
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional, Set

from PyQt6.QtCore import QObject, QTimer, QMetaObject, Qt, pyqtSlot

from watchdog.observers import Observer
from watchdog.events import (
    FileSystemEventHandler,
    FileSystemEvent,
    FileCreatedEvent,
    FileModifiedEvent,
    FileDeletedEvent,
    FileMovedEvent,
    DirCreatedEvent,
    DirModifiedEvent,
    DirDeletedEvent,
    DirMovedEvent,
)


# ============================================================
# 常量定义
# ============================================================

# 防抖间隔（毫秒）
DEBOUNCE_INTERVAL_MS = 200

# 忽略的目录名
IGNORED_DIRS = {
    ".circuit_ai",
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

# 关注的文件扩展名
WATCHED_EXTENSIONS = {
    ".cir",      # SPICE 电路文件
    ".sp",       # SPICE 文件
    ".spice",    # SPICE 文件
    ".json",     # 配置文件
    ".png",      # 图片
    ".jpg",      # 图片
    ".jpeg",     # 图片
    ".lib",      # 库文件
    ".sub",      # 子电路文件
    ".inc",      # 包含文件
    ".mod",      # 模型文件
}


# ============================================================
# 事件接收器（主线程）
# ============================================================

class FileWatchReceiver(QObject):
    """
    文件监听事件接收器
    
    在主线程中接收来自 watchdog 线程的事件，
    执行防抖处理后通过 EventBus 发布事件。
    """
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        
        # 防抖缓冲区：{file_path: event_data}
        self._debounce_buffer: Dict[str, Dict[str, Any]] = {}
        
        # 防抖定时器
        self._debounce_timer: Optional[QTimer] = None
        
        # 延迟获取的服务
        self._event_bus = None
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
    
    @pyqtSlot(str, str, bool, str)
    def on_file_event(
        self,
        path: str,
        event_type: str,
        is_directory: bool,
        dest_path: str
    ) -> None:
        """
        接收文件事件（在主线程中调用）
        
        Args:
            path: 文件路径
            event_type: 事件类型（created, modified, deleted, moved）
            is_directory: 是否为目录
            dest_path: 移动目标路径（仅 moved 事件）
        """
        # 构建事件数据
        event_data = {
            "path": path,
            "event_type": event_type,
            "is_directory": is_directory,
        }
        if dest_path:
            event_data["dest_path"] = dest_path
        
        # 加入防抖缓冲区（同一文件的多次事件会被覆盖）
        self._debounce_buffer[path] = event_data
        
        # 启动防抖定时器
        self._ensure_debounce_timer()
    
    def _ensure_debounce_timer(self) -> None:
        """确保防抖定时器已启动"""
        if self._debounce_timer is None:
            self._debounce_timer = QTimer(self)
            self._debounce_timer.setSingleShot(True)
            self._debounce_timer.timeout.connect(self._flush_debounce_buffer)
        
        # 重置定时器
        self._debounce_timer.start(DEBOUNCE_INTERVAL_MS)
    
    @pyqtSlot()
    def _flush_debounce_buffer(self) -> None:
        """刷新防抖缓冲区，发布所有缓冲的事件"""
        if not self._debounce_buffer:
            return
        
        # 取出所有缓冲的事件
        events_to_publish = self._debounce_buffer.copy()
        self._debounce_buffer.clear()
        
        # 发布事件
        if self.event_bus:
            from shared.event_types import EVENT_FILE_CHANGED
            
            for path, event_data in events_to_publish.items():
                try:
                    self.event_bus.publish(
                        EVENT_FILE_CHANGED,
                        event_data,
                        source="file_watcher"
                    )
                    
                    if self.logger:
                        self.logger.debug(
                            f"File {event_data['event_type']}: {path}"
                        )
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"Failed to publish file event: {e}")
    
    def clear_buffer(self) -> None:
        """清空防抖缓冲区"""
        self._debounce_buffer.clear()
        if self._debounce_timer and self._debounce_timer.isActive():
            self._debounce_timer.stop()


# ============================================================
# Watchdog 事件处理器
# ============================================================

class CircuitFileEventHandler(FileSystemEventHandler):
    """
    电路文件事件处理器
    
    在 watchdog 线程中运行，过滤事件后转发到主线程。
    """
    
    def __init__(self, receiver: FileWatchReceiver, watch_root: Path):
        """
        初始化事件处理器
        
        Args:
            receiver: 主线程事件接收器
            watch_root: 监听根目录
        """
        super().__init__()
        self._receiver = receiver
        self._watch_root = watch_root
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
            
            # 如果是文件，检查是否在关注的扩展名列表中
            if path_obj.is_file() or not path_obj.exists():
                # 对于已删除的文件，通过扩展名判断
                if suffix and suffix not in WATCHED_EXTENSIONS:
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
        """
        分发事件到主线程
        
        Args:
            path: 文件路径
            event_type: 事件类型
            is_directory: 是否为目录
            dest_path: 移动目标路径
        """
        # 过滤事件
        if self._should_ignore(path):
            return
        
        if dest_path and self._should_ignore(dest_path):
            return
        
        # 通过 Qt 信号机制转发到主线程
        # 使用 Q_ARG 传递参数
        from PyQt6.QtCore import Q_ARG
        QMetaObject.invokeMethod(
            self._receiver,
            "on_file_event",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, path),
            Q_ARG(str, event_type),
            Q_ARG(bool, is_directory),
            Q_ARG(str, dest_path)
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

class FileWatchTask(QObject):
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
    
    def __init__(self, parent: Optional[QObject] = None):
        """初始化文件监听任务"""
        super().__init__(parent)
        
        # watchdog Observer
        self._observer: Optional[Observer] = None
        
        # 事件接收器
        self._receiver = FileWatchReceiver(self)
        
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
            event_handler = CircuitFileEventHandler(self._receiver, path)
            
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
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to start file watching: {e}")
            
            # 清理
            self._observer = None
            self._watch_path = None
            
            return False
    
    def stop_watching(self) -> None:
        """停止文件监听"""
        if self._observer is None:
            return
        
        try:
            # 停止 Observer
            self._observer.stop()
            self._observer.join(timeout=2.0)  # 等待最多 2 秒
            
            if self.logger:
                self.logger.info(f"Stopped watching: {self._watch_path}")
            
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Error stopping file watcher: {e}")
        
        finally:
            # 清理
            self._observer = None
            self._watch_path = None
            
            # 清空防抖缓冲区
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
    "WATCHED_EXTENSIONS",
    "IGNORED_DIRS",
    "IGNORED_EXTENSIONS",
    "DEBOUNCE_INTERVAL_MS",
]
