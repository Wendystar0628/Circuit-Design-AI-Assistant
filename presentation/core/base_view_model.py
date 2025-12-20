# Base ViewModel
"""
ViewModel 基类

职责：
- 定义所有 ViewModel 的基类
- 提供状态管理、事件订阅、属性变更通知的统一接口
- 管理 ViewModel 生命周期

设计原则：
- View 层通过 property_changed 信号响应 ViewModel 状态变化
- ViewModel 通过 EventBus 订阅业务层事件
- 延迟获取 ServiceLocator 中的服务

被继承方：
- ConversationViewModel（阶段三）
- SimulationViewModel（阶段四）
- InfoPanelViewModel（阶段九）
- ComponentViewModel（阶段十）
"""

from typing import Optional, Callable, Dict, List, Any
from PyQt6.QtCore import QObject, pyqtSignal


class BaseViewModel(QObject):
    """
    ViewModel 基类
    
    提供：
    - 属性变更通知机制
    - EventBus 事件订阅管理
    - 生命周期管理（初始化、销毁）
    
    使用示例：
        class MyViewModel(BaseViewModel):
            def __init__(self):
                super().__init__()
                self._data = None
            
            def initialize(self):
                super().initialize()
                self.subscribe(EVENT_DATA_CHANGED, self._on_data_changed)
            
            def _on_data_changed(self, event_data):
                self._data = event_data.get("data")
                self.notify_property_changed("data", self._data)
    """
    
    # 属性变更信号（属性名，新值）
    property_changed = pyqtSignal(str, object)
    
    def __init__(self):
        super().__init__()
        
        # 延迟获取的服务
        self._event_bus = None
        self._logger = None
        
        # 事件订阅记录（用于 dispose 时取消）
        self._subscriptions: List[tuple] = []
        
        # 初始化状态
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
                self._logger = get_logger(f"viewmodel.{class_name}")
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
    
    def initialize(self):
        """
        初始化 ViewModel
        
        子类应重写此方法以：
        - 订阅所需的事件
        - 加载初始数据
        - 设置初始状态
        
        注意：在 View 准备好后调用，确保信号连接已建立
        """
        if self._is_initialized:
            if self.logger:
                self.logger.warning(f"{self.__class__.__name__} already initialized")
            return
        
        self._is_initialized = True
        
        if self.logger:
            self.logger.debug(f"{self.__class__.__name__} initialized")
    
    def dispose(self):
        """
        销毁 ViewModel，清理资源
        
        - 取消所有事件订阅
        - 释放持有的资源
        - 标记为已销毁
        """
        if self._is_disposed:
            return
        
        # 取消所有事件订阅
        self._unsubscribe_all()
        
        self._is_disposed = True
        
        if self.logger:
            self.logger.debug(f"{self.__class__.__name__} disposed")
    
    # ============================================================
    # 事件订阅管理
    # ============================================================
    
    def subscribe(self, event_type: str, handler: Callable):
        """
        订阅事件
        
        Args:
            event_type: 事件类型
            handler: 事件处理函数
        """
        if self._is_disposed:
            if self.logger:
                self.logger.warning(
                    f"Cannot subscribe to {event_type}: ViewModel is disposed"
                )
            return
        
        if self.event_bus:
            self.event_bus.subscribe(event_type, handler)
            self._subscriptions.append((event_type, handler))
            
            if self.logger:
                self.logger.debug(f"Subscribed to {event_type}")
    
    def unsubscribe(self, event_type: str, handler: Callable):
        """
        取消订阅事件
        
        Args:
            event_type: 事件类型
            handler: 事件处理函数
        """
        if self.event_bus:
            self.event_bus.unsubscribe(event_type, handler)
            
            # 从记录中移除
            try:
                self._subscriptions.remove((event_type, handler))
            except ValueError:
                pass
            
            if self.logger:
                self.logger.debug(f"Unsubscribed from {event_type}")
    
    def _unsubscribe_all(self):
        """取消所有事件订阅"""
        if not self.event_bus:
            self._subscriptions.clear()
            return
        
        for event_type, handler in self._subscriptions:
            try:
                self.event_bus.unsubscribe(event_type, handler)
            except Exception as e:
                if self.logger:
                    self.logger.warning(
                        f"Failed to unsubscribe from {event_type}: {e}"
                    )
        
        self._subscriptions.clear()
    
    # ============================================================
    # 属性变更通知
    # ============================================================
    
    def notify_property_changed(self, property_name: str, value: Any):
        """
        通知属性变更
        
        View 层连接 property_changed 信号以响应状态变化
        
        Args:
            property_name: 属性名称
            value: 新值
        """
        if self._is_disposed:
            return
        
        self.property_changed.emit(property_name, value)
        
        if self.logger:
            self.logger.debug(f"Property changed: {property_name}")
    
    def notify_properties_changed(self, properties: Dict[str, Any]):
        """
        批量通知属性变更
        
        Args:
            properties: 属性名到新值的映射
        """
        for name, value in properties.items():
            self.notify_property_changed(name, value)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "BaseViewModel",
]
