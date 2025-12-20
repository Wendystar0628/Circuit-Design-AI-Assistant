# UI Event Bridge - UI事件桥接器
"""
UI事件桥接器 - 桥接业务层事件与UI层响应

职责：
- 桥接 EventBus 事件到 UI 处理器
- 确保事件处理在主线程执行
- 管理事件绑定的生命周期

设计原则：
- 线程安全：使用 QMetaObject.invokeMethod 确保 UI 更新在主线程
- 自动检测：非主线程时自动切换到主线程执行
- 统一管理：集中管理所有 UI 事件绑定

被调用方：各面板的 ViewModel
"""

from typing import Optional, Dict, Any, Callable, List
from PyQt6.QtCore import QObject, QThread, QMetaObject, Qt, Q_ARG
from PyQt6.QtWidgets import QApplication


class UIEventBridge(QObject):
    """
    UI事件桥接器
    
    桥接业务层事件与UI层响应，确保事件处理在主线程执行。
    """
    
    def __init__(self, parent: Optional[QObject] = None):
        """
        初始化 UI 事件桥接器
        
        Args:
            parent: 父对象（可选）
        """
        super().__init__(parent)
        
        # 事件绑定记录：event_type -> [(ui_handler, wrapper)]
        self._bindings: Dict[str, List[tuple]] = {}
        
        # 延迟获取的服务
        self._event_bus = None
        self._logger = None
    
    # ============================================================
    # 延迟获取服务
    # ============================================================
    
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
                self._logger = get_logger("ui_event_bridge")
            except Exception:
                pass
        return self._logger
    
    # ============================================================
    # 事件桥接
    # ============================================================
    
    def bridge_event(
        self, 
        event_type: str, 
        ui_handler: Callable[[Dict[str, Any]], None]
    ) -> bool:
        """
        桥接事件到 UI 处理器
        
        创建一个包装器，确保 ui_handler 在主线程执行。
        
        Args:
            event_type: 事件类型
            ui_handler: UI 处理器函数
            
        Returns:
            是否绑定成功
        """
        if not self.event_bus:
            return False
        
        # 创建线程安全的包装器
        def wrapper(event_data: Dict[str, Any]) -> None:
            self._ensure_main_thread(ui_handler, event_data)
        
        try:
            self.event_bus.subscribe(event_type, wrapper)
            
            # 记录绑定
            if event_type not in self._bindings:
                self._bindings[event_type] = []
            self._bindings[event_type].append((ui_handler, wrapper))
            
            if self.logger:
                self.logger.debug(f"Event bridged: {event_type}")
            
            return True
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to bridge event {event_type}: {e}")
            return False
    
    def unbind_event(
        self, 
        event_type: str, 
        ui_handler: Callable[[Dict[str, Any]], None]
    ) -> bool:
        """
        解除事件桥接
        
        Args:
            event_type: 事件类型
            ui_handler: UI 处理器函数
            
        Returns:
            是否解除成功
        """
        if not self.event_bus:
            return False
        
        if event_type not in self._bindings:
            return False
        
        # 查找对应的包装器
        for handler, wrapper in self._bindings[event_type]:
            if handler == ui_handler:
                try:
                    self.event_bus.unsubscribe(event_type, wrapper)
                    self._bindings[event_type].remove((handler, wrapper))
                    
                    if self.logger:
                        self.logger.debug(f"Event unbound: {event_type}")
                    
                    return True
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"Failed to unbind event {event_type}: {e}")
                    return False
        
        return False
    
    def unbind_all(self) -> None:
        """解除所有事件桥接"""
        if not self.event_bus:
            return
        
        for event_type, bindings in self._bindings.items():
            for _, wrapper in bindings:
                try:
                    self.event_bus.unsubscribe(event_type, wrapper)
                except Exception:
                    pass
        
        self._bindings.clear()
        
        if self.logger:
            self.logger.debug("All events unbound")
    
    # ============================================================
    # 线程安全执行
    # ============================================================
    
    def _ensure_main_thread(
        self, 
        handler: Callable[[Dict[str, Any]], None], 
        event_data: Dict[str, Any]
    ) -> None:
        """
        确保处理器在主线程执行
        
        Args:
            handler: 处理器函数
            event_data: 事件数据
        """
        app = QApplication.instance()
        if not app:
            # 无 QApplication 实例，直接执行
            handler(event_data)
            return
        
        # 检查当前线程
        if QThread.currentThread() == app.thread():
            # 已在主线程，直接执行
            handler(event_data)
        else:
            # 非主线程，使用 invokeMethod 切换到主线程
            # 由于 invokeMethod 不支持直接传递 Python 对象，
            # 我们使用 QTimer.singleShot 作为替代方案
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: handler(event_data))
    
    @staticmethod
    def ensure_main_thread(handler: Callable[[], None]) -> None:
        """
        静态方法：确保处理器在主线程执行
        
        Args:
            handler: 无参数处理器函数
        """
        app = QApplication.instance()
        if not app:
            handler()
            return
        
        if QThread.currentThread() == app.thread():
            handler()
        else:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, handler)
    
    @staticmethod
    def is_main_thread() -> bool:
        """
        检查当前是否在主线程
        
        Returns:
            是否在主线程
        """
        app = QApplication.instance()
        if not app:
            return True
        return QThread.currentThread() == app.thread()


# ============================================================
# 全局实例（可选）
# ============================================================

_global_bridge: Optional[UIEventBridge] = None


def get_ui_event_bridge() -> UIEventBridge:
    """
    获取全局 UI 事件桥接器实例
    
    Returns:
        UIEventBridge 实例
    """
    global _global_bridge
    if _global_bridge is None:
        _global_bridge = UIEventBridge()
    return _global_bridge


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "UIEventBridge",
    "get_ui_event_bridge",
]
