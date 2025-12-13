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

from PyQt6.QtCore import QObject, QMetaObject, Qt, Q_ARG, pyqtSlot
from PyQt6.QtWidgets import QApplication

from shared.event_types import CRITICAL_EVENTS


# 事件处理器类型
EventHandler = Callable[[Dict[str, Any]], None]


class EventBusReceiver(QObject):
    """
    事件接收器 - 在主线程中执行 handler
    
    使用 QObject 的 invokeMethod 机制确保 handler 在主线程执行
    """

    def __init__(self):
        super().__init__()
        self._pending_events: List[tuple] = []
        self._lock = threading.Lock()

    @pyqtSlot()
    def process_pending_events(self):
        """处理待执行的事件（在主线程中调用）"""
        with self._lock:
            events = self._pending_events.copy()
            self._pending_events.clear()

        for handler, event_data, event_type in events:
            self._execute_handler(handler, event_data, event_type)

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
    """

    def __init__(self):
        # 订阅者注册表：{event_type: [handler1, handler2, ...]}
        self._subscribers: Dict[str, List[EventHandler]] = {}
        # 订阅列表锁
        self._lock = threading.Lock()
        # 事件接收器（主线程执行）
        self._receiver = EventBusReceiver()
        # 日志器（延迟获取）
        self._logger = None
        # 调试模式
        self._debug = False

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

    def get_stats(self) -> Dict[str, int]:
        """
        获取事件总线统计信息
        
        Returns:
            dict: {event_type: subscriber_count}
        """
        with self._lock:
            return {
                event_type: len(handlers)
                for event_type, handlers in self._subscribers.items()
            }


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "EventBus",
    "EventBusReceiver",
    "EventHandler",
]
