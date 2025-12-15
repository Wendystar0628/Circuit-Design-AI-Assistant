# File Watcher Worker - Background File System Monitor
"""
文件监听线程 - 监测工作文件夹的文件变化

职责：
- 监测工作文件夹的文件变化
- 通知应用层文件创建、修改、删除、重命名事件
- 过滤无关文件和目录
- 防抖处理避免重复通知

使用示例：
    worker = FileWatcherWorker()
    worker.set_watch_path("/path/to/project")
    worker.result.connect(on_file_changed)
    worker.start()
"""

import os
import time
import threading
from pathlib import Path
from typing import Dict, Optional, Set

from application.workers.base_worker import BaseWorker


# ============================================================
# 常量定义
# ============================================================

# Worker 类型标识
WORKER_TYPE_FILE_WATCHER = "file_watcher_worker"

# 防抖延迟（秒）
DEBOUNCE_DELAY = 0.5

# 忽略的目录
IGNORED_DIRS = {
    ".circuit_ai",
    "__pycache__",
    ".git",
    ".vscode",
    ".idea",
    "node_modules",
}

# 忽略的文件扩展名
IGNORED_EXTENSIONS = {
    ".tmp",
    ".swp",
    ".swo",
    ".bak",
    ".pyc",
    ".pyo",
}

# 关注的文件扩展名
WATCHED_EXTENSIONS = {
    ".cir",
    ".sp",
    ".spice",
    ".json",
    ".png",
    ".jpg",
    ".jpeg",
    ".pdf",
    ".txt",
    ".md",
}



# ============================================================
# 文件事件处理器
# ============================================================

class FileEventHandler:
    """
    文件事件处理器
    
    使用 watchdog 库监听文件系统事件，并进行过滤和防抖处理。
    """

    def __init__(self, worker: 'FileWatcherWorker'):
        self._worker = worker
        self._pending_events: Dict[str, tuple] = {}  # path -> (event_type, timestamp)
        self._lock = threading.Lock()

    def on_created(self, event) -> None:
        """文件创建事件"""
        if not event.is_directory:
            self._queue_event(event.src_path, "created")

    def on_modified(self, event) -> None:
        """文件修改事件"""
        if not event.is_directory:
            self._queue_event(event.src_path, "modified")

    def on_deleted(self, event) -> None:
        """文件删除事件"""
        if not event.is_directory:
            self._queue_event(event.src_path, "deleted")

    def on_moved(self, event) -> None:
        """文件移动/重命名事件"""
        if not event.is_directory:
            self._queue_event(event.src_path, "deleted")
            self._queue_event(event.dest_path, "created")

    def _queue_event(self, path: str, event_type: str) -> None:
        """将事件加入队列（带防抖）"""
        # 检查是否应该忽略
        if self._should_ignore(path):
            return
        
        with self._lock:
            self._pending_events[path] = (event_type, time.time())

    def _should_ignore(self, path: str) -> bool:
        """检查是否应该忽略该路径"""
        path_obj = Path(path)
        
        # 检查是否在忽略的目录中
        for part in path_obj.parts:
            if part in IGNORED_DIRS:
                return True
        
        # 检查扩展名
        ext = path_obj.suffix.lower()
        
        # 忽略临时文件
        if ext in IGNORED_EXTENSIONS:
            return True
        
        # 只关注特定扩展名
        if ext and ext not in WATCHED_EXTENSIONS:
            return True
        
        return False

    def get_pending_events(self) -> Dict[str, str]:
        """
        获取待处理的事件（已完成防抖）
        
        Returns:
            {path: event_type} 字典
        """
        current_time = time.time()
        ready_events = {}
        
        with self._lock:
            paths_to_remove = []
            
            for path, (event_type, timestamp) in self._pending_events.items():
                if current_time - timestamp >= DEBOUNCE_DELAY:
                    ready_events[path] = event_type
                    paths_to_remove.append(path)
            
            for path in paths_to_remove:
                del self._pending_events[path]
        
        return ready_events

    def clear(self) -> None:
        """清空待处理事件"""
        with self._lock:
            self._pending_events.clear()



# ============================================================
# File Watcher Worker
# ============================================================

class FileWatcherWorker(BaseWorker):
    """
    文件监听线程
    
    监测工作文件夹的文件变化，通知应用层。
    
    特性：
    - 过滤 .circuit_ai/ 目录和临时文件
    - 仅关注电路文件和资源文件
    - 防抖处理合并短时间内的多次变化
    
    信号说明：
    - result(object): 文件变化事件 {"event": str, "path": str}
    """

    def __init__(self):
        super().__init__(worker_type=WORKER_TYPE_FILE_WATCHER)
        
        # 监听路径
        self._watch_path: Optional[str] = None
        
        # watchdog 观察者
        self._observer = None
        
        # 事件处理器
        self._event_handler: Optional[FileEventHandler] = None

    # ============================================================
    # 配置
    # ============================================================

    def set_watch_path(self, folder_path: str) -> None:
        """
        设置监听目录
        
        Args:
            folder_path: 要监听的文件夹路径
        """
        self._watch_path = folder_path
        
        if self.logger:
            self.logger.info(f"File watcher path set: {folder_path}")

    # ============================================================
    # 任务执行
    # ============================================================

    def do_work(self) -> None:
        """
        启动文件系统监听
        
        使用 watchdog 库监听文件变化，定期检查防抖后的事件并发送信号。
        """
        if not self._watch_path:
            self.emit_error(
                "Watch path not set",
                ValueError("Watch path not configured")
            )
            return
        
        if not os.path.isdir(self._watch_path):
            self.emit_error(
                f"Watch path does not exist: {self._watch_path}",
                FileNotFoundError(self._watch_path)
            )
            return
        
        try:
            self._start_watching()
        except ImportError as e:
            self.emit_error(
                "watchdog library not installed",
                e
            )
        except Exception as e:
            self.emit_error(f"File watcher failed: {e}", e)

    def _start_watching(self) -> None:
        """启动 watchdog 监听"""
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
        
        # 创建事件处理器
        self._event_handler = FileEventHandler(self)
        
        # 创建 watchdog 适配器
        class WatchdogAdapter(FileSystemEventHandler):
            def __init__(self, handler: FileEventHandler):
                self._handler = handler
            
            def on_created(self, event):
                self._handler.on_created(event)
            
            def on_modified(self, event):
                self._handler.on_modified(event)
            
            def on_deleted(self, event):
                self._handler.on_deleted(event)
            
            def on_moved(self, event):
                self._handler.on_moved(event)
        
        adapter = WatchdogAdapter(self._event_handler)
        
        # 创建并启动观察者
        self._observer = Observer()
        self._observer.schedule(adapter, self._watch_path, recursive=True)
        self._observer.start()
        
        if self.logger:
            self.logger.info(f"File watcher started: {self._watch_path}")
        
        try:
            # 主循环：定期检查防抖后的事件
            while not self.is_cancelled():
                # 获取已完成防抖的事件
                events = self._event_handler.get_pending_events()
                
                # 发送事件
                for path, event_type in events.items():
                    if self.is_cancelled():
                        break
                    
                    self.emit_result({
                        "event": event_type,
                        "path": path,
                    })
                    
                    if self.logger:
                        self.logger.debug(f"File {event_type}: {path}")
                
                # 短暂休眠
                time.sleep(0.1)
                
        finally:
            self._stop_watching()

    def _stop_watching(self) -> None:
        """停止监听"""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2.0)
            self._observer = None
            
            if self.logger:
                self.logger.info("File watcher stopped")
        
        if self._event_handler:
            self._event_handler.clear()
            self._event_handler = None

    # ============================================================
    # 取消处理
    # ============================================================

    def cancel(self) -> None:
        """取消监听"""
        super().cancel()
        self._stop_watching()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "FileWatcherWorker",
    "WORKER_TYPE_FILE_WATCHER",
    "WATCHED_EXTENSIONS",
    "IGNORED_DIRS",
]
