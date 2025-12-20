# Event Bus - Publish-Subscribe Communication
"""
事件总线 - 发布-订阅模式的跨组件通信

职责：
- 解耦组件间通信
- 实现发布-订阅模式
- 确保线程安全（handler 在主线程执行）

初始化顺序：
- Phase 0.3，ServiceLocator 之后，创建并注册到 ServiceLocator

设计原则：
- publish() 可从任意线程调用，内部自动切换到主线程
- handler 必须在主线程执行，禁止执行耗时操作
- 单个 handler 异常不影响其他订阅者
- 关键事件有特殊保护机制

使用示例：
    from shared.event_bus import EventBus
    from shared.event_types import EVENT_INIT_COMPLETE
    
    # 订阅事件
    def on_init_complete(event_data):
        print(f"初始化完成: {event_data}")
    
    event_bus.subscribe(EVENT_INIT_COMPLETE, on_init_complete)
    
    # 发布事件
    event_bus.publish(EVENT_INIT_COMPLETE, {"timestamp": time.time()})
"""

import time
import threading
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QObject, QMetaObject, Qt, Q_ARG, pyqtSlot, QTimer
from PyQt6.QtWidgets import QApplication

from shared.event_types import CRITICAL_EVENTS


# 事件处理器类型
EventHandler = Callable[[Dict[str, Any]], None]

# 默认节流间隔（毫秒）
DEFAULT_THROTTLE_MS = 50


class EventBusReceiver(QObject):
    """
    事件接收器 - 在主线程中执行 handler
    
    使用 QObject 的 invokeMethod 机制确保 handler 在主线程执行
    """

    def __init__(self):
        super().__init__()
        self._pending_events: List[tuple] = []
        self._lock = threading.Lock()
        # 引用 EventBus 实例（用于启动节流定时器）
        self._event_bus = None

    def set_event_bus(self, event_bus: 'EventBus'):
        """设置 EventBus 引用"""
        self._event_bus = event_bus

    @pyqtSlot()
    def process_pending_events(self):
        """处理待执行的事件（在主线程中调用）"""
        with self._lock:
            events = self._pending_events.copy()
            self._pending_events.clear()

        for handler, event_data, event_type in events:
            self._execute_handler(handler, event_data, event_type)

    @pyqtSlot()
    def start_throttle_timer(self):
        """启动节流定时器（在主线程中调用）"""
        if self._event_bus:
            self._event_bus._start_throttle_timer()

    def queue_event(self, handler: EventHandler, event_data: Dict, event_type: str):
        """将事件加入队列"""
        with self._lock:
            self._pending_events.append((handler, event_data, event_type))

    def _execute_handler(self, handler: EventHandler, event_data: Dict, event_type: str):
        """执行单个 handler（带异常隔离和性能监控）"""
        start_time = time.time()
        try:
            handler(event_data)
        except Exception as e:
            # 异常隔离：记录错误但不中断其他 handler
            self._log_handler_error(handler, event_type, e)
        finally:
            duration_ms = (time.time() - start_time) * 1000
            # 关键事件超时警告
            if event_type in CRITICAL_EVENTS and duration_ms > 500:
                self._log_handler_timeout(handler, event_type, duration_ms)

    def _log_handler_error(self, handler: EventHandler, event_type: str, error: Exception):
        """记录 handler 执行错误"""
        handler_name = getattr(handler, '__name__', str(handler))
        # 使用延迟获取 logger，避免循环依赖
        try:
            from infrastructure.utils.logger import get_logger
            logger = get_logger("event_bus")
            logger.error(
                f"Handler '{handler_name}' failed for event '{event_type}': {error}"
            )
        except Exception:
            print(f"[EventBus ERROR] Handler '{handler_name}' failed: {error}")

    def _log_handler_timeout(self, handler: EventHandler, event_type: str, duration_ms: float):
        """记录 handler 执行超时"""
        handler_name = getattr(handler, '__name__', str(handler))
        try:
            from infrastructure.utils.logger import get_logger
            logger = get_logger("event_bus")
            logger.warning(
                f"Handler '{handler_name}' for critical event '{event_type}' "
                f"took {duration_ms:.0f}ms (>500ms threshold)"
            )
        except Exception:
            print(f"[EventBus WARNING] Handler timeout: {handler_name} {duration_ms:.0f}ms")



class EventBus:
    """
    事件总线 - 发布-订阅模式的跨组件通信
    
    线程安全说明：
    - publish() 可从任意线程调用
    - handler 始终在主线程执行（通过 QMetaObject.invokeMethod）
    - 订阅列表使用 threading.Lock 保护
    
    事件优先级分类：
    - 关键事件（Critical）：使用 publish_critical()，带重试保护
    - 普通事件（Normal）：使用 publish()，正常队列处理
    - 高频事件（Throttled）：使用 publish_throttled()，节流聚合
    """

    def __init__(self):
        # 订阅者注册表：{event_type: [handler1, handler2, ...]}
        self._subscribers: Dict[str, List[EventHandler]] = {}
        # 订阅列表锁
        self._lock = threading.Lock()
        # 事件接收器（主线程执行）
        self._receiver = EventBusReceiver()
        self._receiver.set_event_bus(self)
        # 日志器（延迟获取）
        self._logger = None
        # 调试模式
        self._debug = False
        
        # 节流缓冲区：{event_type: {"data": Any, "timestamp": float}}
        self._throttle_buffer: Dict[str, Dict[str, Any]] = {}
        self._throttle_lock = threading.Lock()
        # 节流定时器
        self._throttle_timer: Optional[QTimer] = None
        # 默认节流间隔
        self._default_throttle_ms = DEFAULT_THROTTLE_MS
        
        # 统计信息
        self._stats = {
            "total_published": 0,
            "total_throttled": 0,
            "throttle_merged": 0,
        }

    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("event_bus")
            except Exception:
                pass
        return self._logger

    def set_debug(self, enabled: bool):
        """设置调试模式"""
        self._debug = enabled

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """
        订阅事件
        
        Args:
            event_type: 事件类型（使用 event_types.py 中的常量）
            handler: 事件处理函数，签名为 (event_data: Dict) -> None
            
        Note:
            handler 将在主线程中执行，禁止执行耗时操作
        """
        if not callable(handler):
            raise ValueError(f"Handler must be callable: {handler}")

        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            
            # 避免重复订阅
            if handler not in self._subscribers[event_type]:
                self._subscribers[event_type].append(handler)
                
                if self._debug and self.logger:
                    handler_name = getattr(handler, '__name__', str(handler))
                    self.logger.debug(f"Subscribed '{handler_name}' to '{event_type}'")

    def unsubscribe(self, event_type: str, handler: EventHandler) -> bool:
        """
        取消订阅
        
        Args:
            event_type: 事件类型
            handler: 要取消的处理函数
            
        Returns:
            bool: 是否成功取消（handler 存在则为 True）
        """
        with self._lock:
            if event_type in self._subscribers:
                try:
                    self._subscribers[event_type].remove(handler)
                    
                    if self._debug and self.logger:
                        handler_name = getattr(handler, '__name__', str(handler))
                        self.logger.debug(f"Unsubscribed '{handler_name}' from '{event_type}'")
                    
                    return True
                except ValueError:
                    pass
        return False

    def publish(self, event_type: str, data: Any = None, source: str = None) -> None:
        """
        发布事件
        
        可从任意线程调用，handler 将在主线程执行。
        
        Args:
            event_type: 事件类型
            data: 事件数据（可选）
            source: 发布者标识（可选）
        """
        # 构建事件数据结构
        event_data = {
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
            "source": source,
        }

        # 获取订阅者列表（快照）
        with self._lock:
            handlers = self._subscribers.get(event_type, []).copy()

        if not handlers:
            return

        # 更新统计
        self._stats["total_published"] += 1

        # 记录事件发布
        if self._debug and self.logger:
            self.logger.debug(
                f"Publishing '{event_type}' to {len(handlers)} handlers"
            )

        # 判断是否在主线程
        app = QApplication.instance()
        if app is None:
            # 无 QApplication，直接执行（测试场景）
            self._dispatch_directly(handlers, event_data, event_type)
        elif threading.current_thread() is threading.main_thread():
            # 已在主线程，直接执行
            self._dispatch_directly(handlers, event_data, event_type)
        else:
            # 跨线程，通过 invokeMethod 切换到主线程
            self._dispatch_via_qt(handlers, event_data, event_type)

    def _dispatch_directly(
        self, handlers: List[EventHandler], event_data: Dict, event_type: str
    ):
        """直接分发事件（主线程中调用）"""
        is_critical = event_type in CRITICAL_EVENTS
        
        for handler in handlers:
            self._receiver._execute_handler(handler, event_data, event_type)

        # 关键事件发布完成后检查
        if is_critical and self._debug and self.logger:
            self.logger.debug(f"Critical event '{event_type}' dispatched successfully")

    def _dispatch_via_qt(
        self, handlers: List[EventHandler], event_data: Dict, event_type: str
    ):
        """通过 Qt 事件循环分发到主线程"""
        # 将事件加入队列
        for handler in handlers:
            self._receiver.queue_event(handler, event_data, event_type)

        # 触发主线程处理
        QMetaObject.invokeMethod(
            self._receiver,
            "process_pending_events",
            Qt.ConnectionType.QueuedConnection
        )


    def publish_critical(self, event_type: str, data: Any = None, source: str = None) -> bool:
        """
        发布关键事件（带重试保护）
        
        关键事件发布失败时会重试一次，仍失败则记录 CRITICAL 日志。
        
        Args:
            event_type: 事件类型
            data: 事件数据
            source: 发布者标识
            
        Returns:
            bool: 是否发布成功
        """
        try:
            self.publish(event_type, data, source)
            return True
        except Exception as e:
            # 第一次失败，重试
            if self.logger:
                self.logger.warning(
                    f"Critical event '{event_type}' publish failed, retrying: {e}"
                )
            try:
                self.publish(event_type, data, source)
                return True
            except Exception as retry_error:
                # 重试仍失败，记录 CRITICAL
                if self.logger:
                    self.logger.critical(
                        f"Critical event '{event_type}' publish failed after retry: {retry_error}"
                    )
                else:
                    print(f"[CRITICAL] Event '{event_type}' publish failed: {retry_error}")
                return False

    def publish_throttled(
        self,
        event_type: str,
        data: Any = None,
        throttle_ms: int = None,
        source: str = None,
    ) -> None:
        """
        发布节流事件（高频事件聚合）
        
        将事件放入缓冲区，在指定时间窗口内的多次发布合并为一次。
        适用于 LLM 流式输出、进度更新等高频事件。
        
        合并策略：保留最新的 data。
        
        Args:
            event_type: 事件类型
            data: 事件数据
            throttle_ms: 节流间隔（毫秒），默认使用 DEFAULT_THROTTLE_MS
            source: 发布者标识
        """
        if throttle_ms is None:
            throttle_ms = self._default_throttle_ms
        
        with self._throttle_lock:
            # 检查是否已有缓冲的事件
            if event_type in self._throttle_buffer:
                # 合并：保留最新的 data
                self._throttle_buffer[event_type]["data"] = data
                self._throttle_buffer[event_type]["source"] = source
                self._stats["throttle_merged"] += 1
            else:
                # 新事件加入缓冲区
                self._throttle_buffer[event_type] = {
                    "data": data,
                    "source": source,
                    "timestamp": time.time(),
                }
                self._stats["total_throttled"] += 1
            
            # 确保节流定时器已启动
            self._ensure_throttle_timer(throttle_ms)

    def _ensure_throttle_timer(self, interval_ms: int):
        """确保节流定时器已启动"""
        if self._throttle_timer is not None and self._throttle_timer.isActive():
            return
        
        # 需要在主线程创建 QTimer
        app = QApplication.instance()
        if app is None:
            # 无 QApplication，直接刷新
            self._flush_throttle_buffer()
            return
        
        if threading.current_thread() is threading.main_thread():
            self._start_throttle_timer(interval_ms)
        else:
            # 跨线程，通过 invokeMethod 在主线程创建定时器
            QMetaObject.invokeMethod(
                self._receiver,
                "start_throttle_timer",
                Qt.ConnectionType.QueuedConnection,
            )

    def _start_throttle_timer(self, interval_ms: int = None):
        """启动节流定时器（必须在主线程调用）"""
        if interval_ms is None:
            interval_ms = self._default_throttle_ms
        
        if self._throttle_timer is None:
            self._throttle_timer = QTimer()
            self._throttle_timer.timeout.connect(self._flush_throttle_buffer)
        
        if not self._throttle_timer.isActive():
            self._throttle_timer.start(interval_ms)

    def _flush_throttle_buffer(self):
        """刷新节流缓冲区，发布所有缓冲的事件"""
        with self._throttle_lock:
            if not self._throttle_buffer:
                # 缓冲区为空，停止定时器
                if self._throttle_timer and self._throttle_timer.isActive():
                    self._throttle_timer.stop()
                return
            
            # 取出所有缓冲的事件
            events_to_publish = self._throttle_buffer.copy()
            self._throttle_buffer.clear()
        
        # 发布所有事件（锁外执行）
        for event_type, event_info in events_to_publish.items():
            try:
                self.publish(
                    event_type,
                    event_info["data"],
                    event_info.get("source")
                )
            except Exception as e:
                if self.logger:
                    self.logger.warning(
                        f"Failed to publish throttled event '{event_type}': {e}"
                    )
        
        # 检查是否还有新事件加入
        with self._throttle_lock:
            if not self._throttle_buffer and self._throttle_timer:
                self._throttle_timer.stop()

    def clear_all(self) -> None:
        """
        清空所有订阅
        
        仅用于测试场景，生产环境不应调用此方法。
        """
        with self._lock:
            self._subscribers.clear()

    def get_subscriber_count(self, event_type: str) -> int:
        """
        获取指定事件的订阅者数量
        
        Args:
            event_type: 事件类型
            
        Returns:
            int: 订阅者数量
        """
        with self._lock:
            return len(self._subscribers.get(event_type, []))

    def get_all_event_types(self) -> List[str]:
        """
        获取所有已订阅的事件类型
        
        用于调试和诊断。
        
        Returns:
            list: 事件类型列表
        """
        with self._lock:
            return list(self._subscribers.keys())

    def get_stats(self) -> Dict[str, Any]:
        """
        获取事件总线统计信息
        
        Returns:
            dict: 包含订阅者数量和节流统计
        """
        with self._lock:
            subscriber_stats = {
                event_type: len(handlers)
                for event_type, handlers in self._subscribers.items()
            }
        
        return {
            "subscribers": subscriber_stats,
            "total_published": self._stats["total_published"],
            "total_throttled": self._stats["total_throttled"],
            "throttle_merged": self._stats["throttle_merged"],
            "throttle_buffer_size": len(self._throttle_buffer),
        }

    def stop_throttle_timer(self):
        """停止节流定时器（应用关闭时调用）"""
        if self._throttle_timer:
            self._throttle_timer.stop()
            self._throttle_timer = None
        
        # 刷新剩余的缓冲事件
        self._flush_throttle_buffer()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "EventBus",
    "EventBusReceiver",
    "EventHandler",
]
