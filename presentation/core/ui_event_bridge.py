# UI Event Bridge
"""
UI 事件桥接器

职责：
- 桥接业务层事件与 UI 层响应
- 确保事件处理在主线程执行
- 提供类型安全的事件绑定接口

设计原则：
- 使用 QMetaObject.invokeMethod 确保 UI 更新在主线程
- 自动检测当前线程，非主线程时自动切换
- 支持事件解绑，避免内存泄漏

被调用方：
- 各面板的 ViewModel
- main_window.py
"""

from typing import Callable, Dict, List, Any, Optional, Set
from functools import wraps
import threading

from PyQt6.QtCore import QObject, QThread, QMetaObject, Qt, Q_ARG, pyqtSlot
from PyQt6.QtWidgets import QApplication


class UIEventBridge(QObject):
    """
    UI 事件桥接器
    
    桥接业务层事件与 UI 层响应，确保所有 UI 更新在主线程执行
    
    使用示例：
        bridge = UIEventBridge()
        
        # 桥接事件到 UI 处理器
        bridge.bridge_event(EVENT_SESSION_CHANGED, self._on_session_changed)
        
        # 解除桥接
        bridge.unbind_event(EVENT_SESSION_CHANGED, self._on_session_changed)
        
        # 销毁时清理所有绑定
        bridge.dispose()
    """
    
    def __init__(self):
        super().__init__()
        
        # 延迟获取的服务
        self._event_bus = None
        self._logger = None
        
        # 事件绑定记录：event_type -> [(original_handler, wrapped_handler), ...]
        self._bindings: Dict[str, List[tuple]] = {}
        
        # 已绑定的事件类型集合（用于快速查找）
        self._bound_events: Set[str] = set()
        
        # 是否已销毁
        self._disposed = False
    
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
        ui_handler: Callable[[Dict[str, Any]], None],
    ):
        """
        桥接事件到 UI 处理器
        
        自动包装处理器以确保在主线程执行
        
        Args:
            event_type: 事件类型
            ui_handler: UI 处理器函数
        """
        if self._disposed:
            if self.logger:
                self.logger.warning("Cannot bridge event: UIEventBridge is disposed")
            return
        
        if not self.event_bus:
            if self.logger:
                self.logger.warning(f"Cannot bridge event '{event_type}': EventBus not available")
            return
        
        # 创建线程安全的包装器
        wrapped_handler = self._create_main_thread_wrapper(ui_handler, event_type)
        
        # 订阅事件
        self.event_bus.subscribe(event_type, wrapped_handler)
        
        # 记录绑定
        if event_type not in self._bindings:
            self._bindings[event_type] = []
        self._bindings[event_type].append((ui_handler, wrapped_handler))
        self._bound_events.add(event_type)
        
        if self.logger:
            self.logger.debug(f"Event '{event_type}' bridged to UI handler")
    
    def unbind_event(
        self,
        event_type: str,
        ui_handler: Callable[[Dict[str, Any]], None],
    ):
        """
        解除事件桥接
        
        Args:
            event_type: 事件类型
            ui_handler: 原始 UI 处理器函数
        """
        if event_type not in self._bindings:
            return
        
        # 查找并移除绑定
        bindings = self._bindings[event_type]
        for i, (original, wrapped) in enumerate(bindings):
            if original is ui_handler:
                # 取消订阅
                if self.event_bus:
                    self.event_bus.unsubscribe(event_type, wrapped)
                
                # 移除记录
                bindings.pop(i)
                
                if self.logger:
                    self.logger.debug(f"Event '{event_type}' unbound from UI handler")
                break
        
        # 清理空列表
        if not bindings:
            del self._bindings[event_type]
            self._bound_events.discard(event_type)
    
    def unbind_all_for_event(self, event_type: str):
        """
        解除指定事件的所有桥接
        
        Args:
            event_type: 事件类型
        """
        if event_type not in self._bindings:
            return
        
        for original, wrapped in self._bindings[event_type]:
            if self.event_bus:
                self.event_bus.unsubscribe(event_type, wrapped)
        
        del self._bindings[event_type]
        self._bound_events.discard(event_type)
        
        if self.logger:
            self.logger.debug(f"All bindings for event '{event_type}' removed")
    
    def dispose(self):
        """
        销毁桥接器，清理所有绑定
        """
        if self._disposed:
            return
        
        # 取消所有订阅
        for event_type, bindings in self._bindings.items():
            for original, wrapped in bindings:
                if self.event_bus:
                    try:
                        self.event_bus.unsubscribe(event_type, wrapped)
                    except Exception:
                        pass
        
        self._bindings.clear()
        self._bound_events.clear()
        self._disposed = True
        
        if self.logger:
            self.logger.debug("UIEventBridge disposed")
    
    # ============================================================
    # 主线程执行
    # ============================================================
    
    def _create_main_thread_wrapper(
        self,
        handler: Callable[[Dict[str, Any]], None],
        event_type: str,
    ) -> Callable[[Dict[str, Any]], None]:
        """
        创建确保在主线程执行的包装器
        
        Args:
            handler: 原始处理器
            event_type: 事件类型（用于日志）
            
        Returns:
            包装后的处理器
        """
        bridge = self
        
        def wrapper(event_data: Dict[str, Any]):
            if bridge._disposed:
                return
            
            # 检查是否在主线程
            if bridge._is_main_thread():
                # 已在主线程，直接执行
                try:
                    handler(event_data)
                except Exception as e:
                    if bridge.logger:
                        bridge.logger.error(
                            f"Error in UI handler for '{event_type}': {e}"
                        )
            else:
                # 不在主线程，调度到主线程执行
                bridge._invoke_on_main_thread(handler, event_data, event_type)
        
        return wrapper
    
    def _is_main_thread(self) -> bool:
        """检查当前是否在主线程"""
        app = QApplication.instance()
        if app is None:
            return True  # 无 QApplication 时假定在主线程
        
        return QThread.currentThread() is app.thread()
    
    def _invoke_on_main_thread(
        self,
        handler: Callable[[Dict[str, Any]], None],
        event_data: Dict[str, Any],
        event_type: str,
    ):
        """
        在主线程中调用处理器
        
        Args:
            handler: 处理器函数
            event_data: 事件数据
            event_type: 事件类型
        """
        # 使用 QMetaObject.invokeMethod 调度到主线程
        # 由于 Python 函数不能直接通过 invokeMethod 调用，
        # 我们使用 QTimer.singleShot 作为替代方案
        from PyQt6.QtCore import QTimer
        
        def execute():
            if self._disposed:
                return
            try:
                handler(event_data)
            except Exception as e:
                if self.logger:
                    self.logger.error(
                        f"Error in UI handler for '{event_type}' (main thread): {e}"
                    )
        
        # 使用 0ms 延迟将执行调度到主线程事件循环
        QTimer.singleShot(0, execute)
    
    # ============================================================
    # 工具方法
    # ============================================================
    
    def is_event_bound(self, event_type: str) -> bool:
        """
        检查事件是否已绑定
        
        Args:
            event_type: 事件类型
            
        Returns:
            是否已绑定
        """
        return event_type in self._bound_events
    
    def get_bound_events(self) -> List[str]:
        """
        获取所有已绑定的事件类型
        
        Returns:
            事件类型列表
        """
        return list(self._bound_events)
    
    def get_handler_count(self, event_type: str) -> int:
        """
        获取指定事件的处理器数量
        
        Args:
            event_type: 事件类型
            
        Returns:
            处理器数量
        """
        return len(self._bindings.get(event_type, []))


def ensure_main_thread(handler: Callable) -> Callable:
    """
    装饰器：确保函数在主线程执行
    
    用于装饰需要操作 UI 的函数，自动检测线程并调度
    
    使用示例：
        @ensure_main_thread
        def update_label(self, text: str):
            self.label.setText(text)
    
    Args:
        handler: 原始函数
        
    Returns:
        包装后的函数
    """
    @wraps(handler)
    def wrapper(*args, **kwargs):
        app = QApplication.instance()
        
        # 检查是否在主线程
        if app is None or QThread.currentThread() is app.thread():
            return handler(*args, **kwargs)
        
        # 不在主线程，调度到主线程
        from PyQt6.QtCore import QTimer
        
        result_holder = [None]
        exception_holder = [None]
        
        def execute():
            try:
                result_holder[0] = handler(*args, **kwargs)
            except Exception as e:
                exception_holder[0] = e
        
        QTimer.singleShot(0, execute)
        
        # 注意：由于是异步调度，无法直接返回结果
        # 如果需要返回值，应使用信号槽机制
        return None
    
    return wrapper


# ============================================================
# 常用事件桥接预设
# ============================================================

class CommonEventBridges:
    """
    常用事件桥接预设
    
    提供常见事件的快捷桥接方法
    """
    
    @staticmethod
    def bridge_session_events(
        bridge: UIEventBridge,
        on_session_changed: Optional[Callable] = None,
        on_session_loaded: Optional[Callable] = None,
    ):
        """
        桥接会话相关事件
        
        Args:
            bridge: UIEventBridge 实例
            on_session_changed: 会话变更处理器
            on_session_loaded: 会话加载处理器
        """
        from shared.event_types import EVENT_SESSION_CHANGED, EVENT_SESSION_LOADED
        
        if on_session_changed:
            bridge.bridge_event(EVENT_SESSION_CHANGED, on_session_changed)
        if on_session_loaded:
            bridge.bridge_event(EVENT_SESSION_LOADED, on_session_loaded)
    
    @staticmethod
    def bridge_simulation_events(
        bridge: UIEventBridge,
        on_sim_started: Optional[Callable] = None,
        on_sim_complete: Optional[Callable] = None,
        on_sim_error: Optional[Callable] = None,
    ):
        """
        桥接仿真相关事件
        
        Args:
            bridge: UIEventBridge 实例
            on_sim_started: 仿真开始处理器
            on_sim_complete: 仿真完成处理器
            on_sim_error: 仿真错误处理器
        """
        from shared.event_types import (
            EVENT_SIM_STARTED,
            EVENT_SIM_COMPLETE,
            EVENT_SIM_ERROR,
        )
        
        if on_sim_started:
            bridge.bridge_event(EVENT_SIM_STARTED, on_sim_started)
        if on_sim_complete:
            bridge.bridge_event(EVENT_SIM_COMPLETE, on_sim_complete)
        if on_sim_error:
            bridge.bridge_event(EVENT_SIM_ERROR, on_sim_error)
    
    @staticmethod
    def bridge_llm_events(
        bridge: UIEventBridge,
        on_llm_chunk: Optional[Callable] = None,
        on_llm_complete: Optional[Callable] = None,
        on_model_changed: Optional[Callable] = None,
    ):
        """
        桥接 LLM 相关事件
        
        Args:
            bridge: UIEventBridge 实例
            on_llm_chunk: LLM 流式输出处理器
            on_llm_complete: LLM 完成处理器
            on_model_changed: 模型切换处理器
        """
        from shared.event_types import (
            EVENT_LLM_CHUNK,
            EVENT_LLM_COMPLETE,
            EVENT_MODEL_CHANGED,
        )
        
        if on_llm_chunk:
            bridge.bridge_event(EVENT_LLM_CHUNK, on_llm_chunk)
        if on_llm_complete:
            bridge.bridge_event(EVENT_LLM_COMPLETE, on_llm_complete)
        if on_model_changed:
            bridge.bridge_event(EVENT_MODEL_CHANGED, on_model_changed)
    
    @staticmethod
    def bridge_workflow_events(
        bridge: UIEventBridge,
        on_workflow_locked: Optional[Callable] = None,
        on_workflow_unlocked: Optional[Callable] = None,
        on_iteration_awaiting: Optional[Callable] = None,
    ):
        """
        桥接工作流相关事件
        
        Args:
            bridge: UIEventBridge 实例
            on_workflow_locked: 工作流锁定处理器
            on_workflow_unlocked: 工作流解锁处理器
            on_iteration_awaiting: 等待确认处理器
        """
        from shared.event_types import (
            EVENT_WORKFLOW_LOCKED,
            EVENT_WORKFLOW_UNLOCKED,
            EVENT_ITERATION_AWAITING_CONFIRMATION,
        )
        
        if on_workflow_locked:
            bridge.bridge_event(EVENT_WORKFLOW_LOCKED, on_workflow_locked)
        if on_workflow_unlocked:
            bridge.bridge_event(EVENT_WORKFLOW_UNLOCKED, on_workflow_unlocked)
        if on_iteration_awaiting:
            bridge.bridge_event(EVENT_ITERATION_AWAITING_CONFIRMATION, on_iteration_awaiting)
    
    @staticmethod
    def bridge_context_events(
        bridge: UIEventBridge,
        on_compress_requested: Optional[Callable] = None,
        on_compress_preview: Optional[Callable] = None,
        on_compress_complete: Optional[Callable] = None,
    ):
        """
        桥接上下文压缩相关事件
        
        Args:
            bridge: UIEventBridge 实例
            on_compress_requested: 压缩请求处理器
            on_compress_preview: 压缩预览处理器
            on_compress_complete: 压缩完成处理器
        """
        from shared.event_types import (
            EVENT_CONTEXT_COMPRESS_REQUESTED,
            EVENT_CONTEXT_COMPRESS_PREVIEW_READY,
            EVENT_CONTEXT_COMPRESS_COMPLETE,
        )
        
        if on_compress_requested:
            bridge.bridge_event(EVENT_CONTEXT_COMPRESS_REQUESTED, on_compress_requested)
        if on_compress_preview:
            bridge.bridge_event(EVENT_CONTEXT_COMPRESS_PREVIEW_READY, on_compress_preview)
        if on_compress_complete:
            bridge.bridge_event(EVENT_CONTEXT_COMPRESS_COMPLETE, on_compress_complete)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "UIEventBridge",
    "ensure_main_thread",
    "CommonEventBridges",
]
