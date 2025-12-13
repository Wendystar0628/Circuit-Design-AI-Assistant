# App State - Central State Container
"""
应用状态容器 - 中央状态管理

职责：
- 作为应用运行时状态的"单一事实来源"
- 状态变更自动发布事件
- 支持细粒度状态订阅

初始化顺序：
- Phase 1.4，依赖 EventBus（状态变更发布事件）

设计原则：
- 延迟获取 EventBus，避免初始化顺序问题
- 事件级联防护，防止 handler 修改状态导致无限循环
- Application 层写入，Presentation 层读取和订阅

使用示例：
    from shared.app_state import AppState
    
    app_state = AppState()
    
    # 读取状态
    project_path = app_state.get("project_path")
    
    # 设置状态（自动发布事件）
    app_state.set("project_path", "/path/to/project")
    
    # 订阅状态变更
    app_state.subscribe_change("project_path", on_project_changed)
"""

import threading
from typing import Any, Callable, Dict, List, Optional

from shared.event_types import (
    EVENT_STATE_PROJECT_OPENED,
    EVENT_STATE_PROJECT_CLOSED,
    EVENT_STATE_CONFIG_CHANGED,
    EVENT_STATE_ITERATION_UPDATED,
    EVENT_WORKFLOW_LOCKED,
    EVENT_WORKFLOW_UNLOCKED,
)


# ============================================================
# 状态字段常量
# ============================================================

# 项目状态
STATE_PROJECT_PATH = "project_path"
STATE_PROJECT_INITIALIZED = "project_initialized"

# UI 状态
STATE_CURRENT_FILE = "current_file"
STATE_SELECTED_ITERATION = "selected_iteration"

# 工作流状态
STATE_WORKFLOW_RUNNING = "workflow_running"
STATE_CURRENT_NODE = "current_node"
STATE_ITERATION_COUNT = "iteration_count"
STATE_WORKFLOW_LOCKED = "workflow_locked"

# 配置状态
STATE_LLM_CONFIGURED = "llm_configured"
STATE_RAG_ENABLED = "rag_enabled"

# 初始化状态
STATE_INIT_PHASE = "init_phase"
STATE_INIT_COMPLETE = "init_complete"


# 状态字段到事件的映射
STATE_EVENT_MAP = {
    STATE_PROJECT_PATH: EVENT_STATE_PROJECT_OPENED,
    STATE_PROJECT_INITIALIZED: EVENT_STATE_PROJECT_OPENED,
    STATE_WORKFLOW_LOCKED: None,  # 特殊处理
    STATE_ITERATION_COUNT: EVENT_STATE_ITERATION_UPDATED,
    STATE_CURRENT_NODE: EVENT_STATE_ITERATION_UPDATED,
    STATE_LLM_CONFIGURED: EVENT_STATE_CONFIG_CHANGED,
    STATE_RAG_ENABLED: EVENT_STATE_CONFIG_CHANGED,
}


# 状态变更处理器类型
StateChangeHandler = Callable[[str, Any, Any], None]  # (key, old_value, new_value)


# ============================================================
# 应用状态容器
# ============================================================

class AppState:
    """
    应用状态容器
    
    中央状态管理，作为应用运行时状态的"单一事实来源"。
    
    事件级联防护：
    - 维护 _is_dispatching 标志位
    - 事件分发期间的状态变更记录到 _pending_changes
    - 当前事件分发完成后批量处理
    """

    def __init__(self):
        # 状态存储
        self._state: Dict[str, Any] = self._get_default_state()
        
        # 状态变更订阅者：{key: [handler1, handler2, ...]}
        self._subscribers: Dict[str, List[StateChangeHandler]] = {}
        
        # 线程锁
        self._lock = threading.Lock()
        
        # 事件级联防护
        self._is_dispatching = False
        self._pending_changes: List[tuple] = []  # [(key, old_value, new_value), ...]
        
        # 延迟获取的服务
        self._event_bus = None
        self._logger = None

    def _get_default_state(self) -> Dict[str, Any]:
        """获取默认状态"""
        return {
            # 项目状态
            STATE_PROJECT_PATH: None,
            STATE_PROJECT_INITIALIZED: False,
            # UI 状态
            STATE_CURRENT_FILE: None,
            STATE_SELECTED_ITERATION: None,
            # 工作流状态
            STATE_WORKFLOW_RUNNING: False,
            STATE_CURRENT_NODE: None,
            STATE_ITERATION_COUNT: 0,
            STATE_WORKFLOW_LOCKED: False,
            # 配置状态
            STATE_LLM_CONFIGURED: False,
            STATE_RAG_ENABLED: False,
            # 初始化状态
            STATE_INIT_PHASE: 0,
            STATE_INIT_COMPLETE: False,
        }

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
                self._logger = get_logger("app_state")
            except Exception:
                pass
        return self._logger


    # ============================================================
    # 状态读取
    # ============================================================

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取状态值
        
        Args:
            key: 状态键
            default: 默认值（键不存在时返回）
            
        Returns:
            状态值
        """
        with self._lock:
            return self._state.get(key, default)

    def get_all(self) -> Dict[str, Any]:
        """获取所有状态（副本）"""
        with self._lock:
            return self._state.copy()

    # ============================================================
    # 状态写入
    # ============================================================

    def set(self, key: str, value: Any) -> None:
        """
        设置状态值
        
        自动发布状态变更事件。
        
        Args:
            key: 状态键
            value: 状态值
        """
        with self._lock:
            old_value = self._state.get(key)
            
            # 值未变化，跳过
            if old_value == value:
                return
            
            self._state[key] = value
            
            if self.logger:
                self.logger.debug(f"State '{key}' changed: {old_value} -> {value}")
        
        # 触发变更通知（锁外执行，避免死锁）
        self._notify_change(key, old_value, value)

    def update(self, updates: Dict[str, Any]) -> None:
        """
        批量更新状态
        
        所有变更合并为单次事件通知。
        
        Args:
            updates: 状态更新字典
        """
        changes = []
        
        with self._lock:
            for key, value in updates.items():
                old_value = self._state.get(key)
                if old_value != value:
                    self._state[key] = value
                    changes.append((key, old_value, value))
                    
                    if self.logger:
                        self.logger.debug(f"State '{key}' changed: {old_value} -> {value}")
        
        # 批量触发变更通知
        for key, old_value, new_value in changes:
            self._notify_change(key, old_value, new_value)

    def reset(self) -> None:
        """重置所有状态为默认值"""
        with self._lock:
            self._state = self._get_default_state()
            
            if self.logger:
                self.logger.info("State reset to defaults")

    # ============================================================
    # 状态订阅
    # ============================================================

    def subscribe_change(self, key: str, handler: StateChangeHandler) -> None:
        """
        订阅特定状态变更
        
        Args:
            key: 状态键
            handler: 变更处理函数，签名为 (key, old_value, new_value) -> None
        """
        if not callable(handler):
            raise ValueError(f"Handler must be callable: {handler}")
        
        with self._lock:
            if key not in self._subscribers:
                self._subscribers[key] = []
            
            if handler not in self._subscribers[key]:
                self._subscribers[key].append(handler)

    def unsubscribe_change(self, key: str, handler: StateChangeHandler) -> bool:
        """
        取消订阅状态变更
        
        Args:
            key: 状态键
            handler: 要取消的处理函数
            
        Returns:
            bool: 是否成功取消
        """
        with self._lock:
            if key in self._subscribers:
                try:
                    self._subscribers[key].remove(handler)
                    return True
                except ValueError:
                    pass
        return False


    # ============================================================
    # 变更通知
    # ============================================================

    def _notify_change(self, key: str, old_value: Any, new_value: Any) -> None:
        """
        通知状态变更
        
        包含事件级联防护机制。
        """
        # 事件级联防护
        if self._is_dispatching:
            # 记录到待处理队列
            self._pending_changes.append((key, old_value, new_value))
            return
        
        self._is_dispatching = True
        
        try:
            # 通知订阅者
            self._dispatch_to_subscribers(key, old_value, new_value)
            
            # 发布 EventBus 事件
            self._publish_state_event(key, old_value, new_value)
            
            # 处理待处理的变更
            while self._pending_changes:
                pending = self._pending_changes.copy()
                self._pending_changes.clear()
                
                for p_key, p_old, p_new in pending:
                    self._dispatch_to_subscribers(p_key, p_old, p_new)
                    self._publish_state_event(p_key, p_old, p_new)
        finally:
            self._is_dispatching = False

    def _dispatch_to_subscribers(self, key: str, old_value: Any, new_value: Any) -> None:
        """分发变更到订阅者"""
        with self._lock:
            handlers = self._subscribers.get(key, []).copy()
        
        for handler in handlers:
            try:
                handler(key, old_value, new_value)
            except Exception as e:
                if self.logger:
                    handler_name = getattr(handler, '__name__', str(handler))
                    self.logger.error(
                        f"State change handler '{handler_name}' failed for '{key}': {e}"
                    )

    def _publish_state_event(self, key: str, old_value: Any, new_value: Any) -> None:
        """发布状态变更事件到 EventBus"""
        if self.event_bus is None:
            return
        
        # 特殊处理：工作流锁定
        if key == STATE_WORKFLOW_LOCKED:
            event_type = EVENT_WORKFLOW_LOCKED if new_value else EVENT_WORKFLOW_UNLOCKED
            try:
                self.event_bus.publish_critical(
                    event_type,
                    {"locked": new_value},
                    source="app_state"
                )
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Failed to publish workflow lock event: {e}")
            return
        
        # 特殊处理：项目关闭
        if key == STATE_PROJECT_PATH and new_value is None and old_value is not None:
            try:
                self.event_bus.publish(
                    EVENT_STATE_PROJECT_CLOSED,
                    {"old_path": old_value},
                    source="app_state"
                )
            except Exception:
                pass
            return
        
        # 通用事件发布
        event_type = STATE_EVENT_MAP.get(key)
        if event_type:
            try:
                self.event_bus.publish(
                    event_type,
                    {"key": key, "old_value": old_value, "new_value": new_value},
                    source="app_state"
                )
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Failed to publish state event: {e}")

    # ============================================================
    # 便捷属性
    # ============================================================

    @property
    def project_path(self) -> Optional[str]:
        """当前项目路径"""
        return self.get(STATE_PROJECT_PATH)

    @property
    def is_project_open(self) -> bool:
        """是否有项目打开"""
        return self.get(STATE_PROJECT_PATH) is not None

    @property
    def is_workflow_running(self) -> bool:
        """工作流是否正在运行"""
        return self.get(STATE_WORKFLOW_RUNNING, False)

    @property
    def is_workflow_locked(self) -> bool:
        """工作流是否锁定"""
        return self.get(STATE_WORKFLOW_LOCKED, False)

    @property
    def iteration_count(self) -> int:
        """当前迭代次数"""
        return self.get(STATE_ITERATION_COUNT, 0)

    @property
    def is_init_complete(self) -> bool:
        """初始化是否完成"""
        return self.get(STATE_INIT_COMPLETE, False)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "AppState",
    "StateChangeHandler",
    # 状态字段常量
    "STATE_PROJECT_PATH",
    "STATE_PROJECT_INITIALIZED",
    "STATE_CURRENT_FILE",
    "STATE_SELECTED_ITERATION",
    "STATE_WORKFLOW_RUNNING",
    "STATE_CURRENT_NODE",
    "STATE_ITERATION_COUNT",
    "STATE_WORKFLOW_LOCKED",
    "STATE_LLM_CONFIGURED",
    "STATE_RAG_ENABLED",
    "STATE_INIT_PHASE",
    "STATE_INIT_COMPLETE",
]
