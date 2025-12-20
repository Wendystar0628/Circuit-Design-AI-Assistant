# Base ViewModel - ViewModel 基类
"""
ViewModel 基类 - 定义所有 ViewModel 的基类

职责：
- 提供状态管理、事件订阅、属性变更通知的统一接口
- 管理 ViewModel 生命周期
- 提供属性变更信号供 View 层响应

设计原则：
- MVVM 模式：View 只负责渲染，ViewModel 负责状态管理和业务逻辑调用
- 事件驱动：通过 EventBus 订阅状态变更
- 线程安全：属性变更通知在主线程执行

被继承方：ConversationViewModel、SimulationViewModel、InfoPanelViewModel、ComponentViewModel
"""

from typing import Optional, Dict, Any, Callable, List
from PyQt6.QtCore import QObject, pyqtSignal


class BaseViewModel(QObject):
    """
    ViewModel 基类
    
    所有复杂面板的 ViewModel 应继承此类，获得统一的：
    - 属性变更通知机制
    - 事件订阅管理
    - 生命周期管理
    """
    
    # 属性变更信号（属性名，新值）
    property_changed = pyqtSignal(str, object)
    
    def __init__(self, parent: Optional[QObject] = None):
        """
        初始化 ViewModel
        
        Args:
            parent: 父对象（可选）
        """
        super().__init__(parent)
        
        # 延迟获取的服务
        self._event_bus = None
        self._logger = None
        
        # 事件订阅记录（用于清理）
        self._subscriptions: List[tuple] = []
        
        # 初始化状态标志
        self._is_initialized = False
        self._is_disposed = False
    
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
                class_name = self.__class__.__name__
                self._logger = get_logger(class_name.lower())
            except Exception:
                pass
        return self._logger
    
    # ============================================================
    # 生命周期管理
    # ============================================================
    
    @property
    def is_initialized(self) -> bool:
        """是否已初始化"""
        return self._is_initialized
    
    @property
    def is_disposed(self) -> bool:
        """是否已销毁"""
        return self._is_disposed
    
    def initialize(self) -> None:
        """
        初始化 ViewModel
        
        延迟初始化，在 View 准备好后调用。
        子类应重写此方法以执行初始化逻辑。
        """
        if self._is_initialized:
            return
        
        self._is_initialized = True
        
        if self.logger:
            self.logger.debug(f"{self.__class__.__name__} initialized")
    
    def dispose(self) -> None:
        """
        销毁 ViewModel
        
        清理资源，取消所有订阅。
        子类应重写此方法以执行清理逻辑。
        """
        if self._is_disposed:
            return
        
        # 取消所有事件订阅
        for event_type, handler in self._subscriptions:
            self.unsubscribe(event_type, handler)
        self._subscriptions.clear()
        
        self._is_disposed = True
        
        if self.logger:
            self.logger.debug(f"{self.__class__.__name__} disposed")
    
    # ============================================================
    # 事件订阅管理
    # ============================================================
    
    def subscribe(self, event_type: str, handler: Callable[[Dict[str, Any]], None]) -> bool:
        """
        订阅事件
        
        Args:
            event_type: 事件类型
            handler: 事件处理器
            
        Returns:
            是否订阅成功
        """
        if not self.event_bus:
            return False
        
        try:
            self.event_bus.subscribe(event_type, handler)
            self._subscriptions.append((event_type, handler))
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to subscribe to {event_type}: {e}")
            return False
    
    def unsubscribe(self, event_type: str, handler: Callable[[Dict[str, Any]], None]) -> bool:
        """
        取消订阅事件
        
        Args:
            event_type: 事件类型
            handler: 事件处理器
            
        Returns:
            是否取消成功
        """
        if not self.event_bus:
            return False
        
        try:
            self.event_bus.unsubscribe(event_type, handler)
            # 从订阅记录中移除
            if (event_type, handler) in self._subscriptions:
                self._subscriptions.remove((event_type, handler))
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to unsubscribe from {event_type}: {e}")
            return False
    
    # ============================================================
    # 属性变更通知
    # ============================================================
    
    def notify_property_changed(self, property_name: str, value: Any) -> None:
        """
        通知属性变更
        
        发射 property_changed 信号，View 层连接此信号以响应状态变化。
        
        Args:
            property_name: 属性名
            value: 新值
        """
        self.property_changed.emit(property_name, value)
    
    def set_property(self, property_name: str, value: Any) -> None:
        """
        设置属性并通知变更
        
        便捷方法，设置实例属性并发射变更信号。
        
        Args:
            property_name: 属性名（不含下划线前缀）
            value: 新值
        """
        attr_name = f"_{property_name}"
        old_value = getattr(self, attr_name, None)
        
        if old_value != value:
            setattr(self, attr_name, value)
            self.notify_property_changed(property_name, value)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "BaseViewModel",
]
