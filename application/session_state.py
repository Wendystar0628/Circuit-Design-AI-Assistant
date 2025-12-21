# Session State - GraphState Projection for UI Layer
"""
会话状态容器 - GraphState 的只读投影

职责：
- 作为 GraphState 的只读投影，供 UI 层读取业务状态
- UI 组件只读此层，不直接读取 GraphState
- 由 GraphStateProjector 自动从 GraphState 投影更新

初始化顺序：
- Phase 3.5，依赖 EventBus

设计原则：
- 只读投影：UI 组件只能读取，不能直接修改
- 修改业务状态必须通过图节点执行，由 GraphStateProjector 自动投影
- 单向数据流：GraphState → SessionState → UI

三层状态分离架构：
- Layer 1: UIState (Presentation) - 纯 UI 状态
- Layer 2: SessionState (Application) - GraphState 的只读投影，本模块
- Layer 3: GraphState (Domain) - LangGraph 工作流的唯一真理来源

使用示例：
    from application.session_state import SessionState
    
    session_state = SessionState()
    
    # 读取状态（只读）
    project_root = session_state.project_root
    is_locked = session_state.workflow_locked
    
    # 订阅状态变更
    session_state.subscribe_change("workflow_locked", on_lock_changed)
    
    # 禁止直接修改！修改必须通过图节点执行
    # session_state.set("workflow_locked", True)  # 错误！
"""

import threading
from typing import Any, Callable, Dict, List, Optional

from shared.event_types import (
    EVENT_SESSION_CHANGED,
    EVENT_WORKFLOW_LOCKED,
    EVENT_WORKFLOW_UNLOCKED,
)


# ============================================================
# 状态字段常量
# ============================================================

# 项目状态
SESSION_PROJECT_ROOT = "project_root"
SESSION_PROJECT_INITIALIZED = "project_initialized"

# 会话状态（从 GraphState 投影）
SESSION_ID = "session_id"
SESSION_WORK_MODE = "work_mode"

# 工作流状态（从 GraphState 投影）
SESSION_WORKFLOW_LOCKED = "workflow_locked"
SESSION_CURRENT_NODE = "current_node"
SESSION_PREVIOUS_NODE = "previous_node"
SESSION_ITERATION_COUNT = "iteration_count"
SESSION_CHECKPOINT_COUNT = "checkpoint_count"
SESSION_STAGNATION_COUNT = "stagnation_count"
SESSION_IS_COMPLETED = "is_completed"
SESSION_TERMINATION_REASON = "termination_reason"

# 当前文件（从 GraphState 投影）
SESSION_ACTIVE_CIRCUIT_FILE = "active_circuit_file"
SESSION_SIM_RESULT_PATH = "sim_result_path"
SESSION_DESIGN_GOALS_PATH = "design_goals_path"

# 轻量摘要（从 GraphState 投影）
SESSION_DESIGN_GOALS_SUMMARY = "design_goals_summary"
SESSION_LAST_METRICS = "last_metrics"
SESSION_ERROR_CONTEXT = "error_context"


# 状态变更处理器类型
SessionStateChangeHandler = Callable[[str, Any, Any], None]  # (key, old_value, new_value)


# ============================================================
# 会话状态容器
# ============================================================

class SessionState:
    """
    会话状态容器 - GraphState 的只读投影
    
    供 UI 层读取业务状态，由 GraphStateProjector 自动更新。
    UI 组件禁止直接修改此状态，修改必须通过图节点执行。
    """

    def __init__(self):
        # 状态存储
        self._state: Dict[str, Any] = self._get_default_state()
        
        # 状态变更订阅者：{key: [handler1, handler2, ...]}
        self._subscribers: Dict[str, List[SessionStateChangeHandler]] = {}
        
        # 线程锁
        self._lock = threading.Lock()
        
        # 事件级联防护
        self._is_dispatching = False
        self._pending_changes: List[tuple] = []
        
        # 延迟获取的服务
        self._event_bus = None
        self._logger = None

    def _get_default_state(self) -> Dict[str, Any]:
        """获取默认状态"""
        return {
            # 项目状态
            SESSION_PROJECT_ROOT: None,
            SESSION_PROJECT_INITIALIZED: False,
            # 会话状态
            SESSION_ID: "",
            SESSION_WORK_MODE: "free_chat",
            # 工作流状态
            SESSION_WORKFLOW_LOCKED: False,
            SESSION_CURRENT_NODE: "",
            SESSION_PREVIOUS_NODE: "",
            SESSION_ITERATION_COUNT: 0,
            SESSION_CHECKPOINT_COUNT: 0,
            SESSION_STAGNATION_COUNT: 0,
            SESSION_IS_COMPLETED: False,
            SESSION_TERMINATION_REASON: "",
            # 当前文件
            SESSION_ACTIVE_CIRCUIT_FILE: "",
            SESSION_SIM_RESULT_PATH: "",
            SESSION_DESIGN_GOALS_PATH: ".circuit_ai/design_goals.json",
            # 轻量摘要
            SESSION_DESIGN_GOALS_SUMMARY: {},
            SESSION_LAST_METRICS: {},
            SESSION_ERROR_CONTEXT: "",
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
                self._logger = get_logger("session_state")
            except Exception:
                pass
        return self._logger

    # ============================================================
    # 状态读取（公开接口）
    # ============================================================

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取状态值（只读）
        
        Args:
            key: 状态键
            default: 默认值（键不存在时返回）
            
        Returns:
            状态值
        """
        with self._lock:
            return self._state.get(key, default)

    def get_all(self) -> Dict[str, Any]:
        """获取所有状态（副本，只读）"""
        with self._lock:
            return self._state.copy()

    # ============================================================
    # 状态写入（仅供 GraphStateProjector 调用）
    # ============================================================

    def _internal_set(self, key: str, value: Any) -> None:
        """
        内部设置状态值（仅供 GraphStateProjector 调用）
        
        UI 组件禁止调用此方法！
        
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
                self.logger.debug(f"SessionState '{key}' projected: {old_value} -> {value}")
        
        # 触发变更通知（锁外执行，避免死锁）
        self._notify_change(key, old_value, value)

    def _internal_update(self, updates: Dict[str, Any]) -> None:
        """
        内部批量更新状态（仅供 GraphStateProjector 调用）
        
        UI 组件禁止调用此方法！
        
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
                        self.logger.debug(f"SessionState '{key}' projected: {old_value} -> {value}")
        
        # 批量触发变更通知
        for key, old_value, new_value in changes:
            self._notify_change(key, old_value, new_value)

    def _internal_reset(self) -> None:
        """
        内部重置所有状态为默认值（仅供 GraphStateProjector 调用）
        
        UI 组件禁止调用此方法！
        """
        with self._lock:
            self._state = self._get_default_state()
            
            if self.logger:
                self.logger.info("SessionState reset to defaults")

    # ============================================================
    # 状态订阅
    # ============================================================

    def subscribe_change(self, key: str, handler: SessionStateChangeHandler) -> None:
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

    def unsubscribe_change(self, key: str, handler: SessionStateChangeHandler) -> bool:
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
                        f"SessionState change handler '{handler_name}' failed for '{key}': {e}"
                    )

    def _publish_state_event(self, key: str, old_value: Any, new_value: Any) -> None:
        """发布状态变更事件到 EventBus"""
        if self.event_bus is None:
            return
        
        # 特殊处理：工作流锁定
        if key == SESSION_WORKFLOW_LOCKED:
            event_type = EVENT_WORKFLOW_LOCKED if new_value else EVENT_WORKFLOW_UNLOCKED
            try:
                self.event_bus.publish_critical(
                    event_type,
                    {"locked": new_value},
                    source="session_state"
                )
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Failed to publish workflow lock event: {e}")
            return
        
        # 会话相关字段变更发布 EVENT_SESSION_CHANGED
        session_fields = [
            SESSION_ID, SESSION_WORK_MODE, SESSION_CURRENT_NODE,
            SESSION_ITERATION_COUNT, SESSION_CHECKPOINT_COUNT
        ]
        if key in session_fields:
            try:
                self.event_bus.publish(
                    EVENT_SESSION_CHANGED,
                    {
                        "key": key,
                        "old_value": old_value,
                        "new_value": new_value,
                        "session_id": self.session_id,
                        "action": "state_update",
                    },
                    source="session_state"
                )
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Failed to publish session state event: {e}")

    # ============================================================
    # 便捷属性（只读）
    # ============================================================

    @property
    def project_root(self) -> Optional[str]:
        """当前项目根目录"""
        return self.get(SESSION_PROJECT_ROOT)

    @property
    def is_project_open(self) -> bool:
        """是否有项目打开"""
        return self.get(SESSION_PROJECT_ROOT) is not None

    @property
    def session_id(self) -> str:
        """当前会话 ID"""
        return self.get(SESSION_ID, "")

    @property
    def work_mode(self) -> str:
        """工作模式（workflow | free_chat）"""
        return self.get(SESSION_WORK_MODE, "free_chat")

    @property
    def workflow_locked(self) -> bool:
        """
        工作流是否锁定
        
        锁定时禁止：文件切换、模式切换、新建会话
        """
        return self.get(SESSION_WORKFLOW_LOCKED, False)

    @property
    def current_node(self) -> str:
        """当前执行的节点名称"""
        return self.get(SESSION_CURRENT_NODE, "")

    @property
    def iteration_count(self) -> int:
        """迭代次数"""
        return self.get(SESSION_ITERATION_COUNT, 0)

    @property
    def checkpoint_count(self) -> int:
        """检查点计数"""
        return self.get(SESSION_CHECKPOINT_COUNT, 0)

    @property
    def is_completed(self) -> bool:
        """是否完成"""
        return self.get(SESSION_IS_COMPLETED, False)

    @property
    def active_circuit_file(self) -> str:
        """当前激活的电路文件"""
        return self.get(SESSION_ACTIVE_CIRCUIT_FILE, "")

    @property
    def design_goals_summary(self) -> Dict[str, Any]:
        """设计目标摘要"""
        return self.get(SESSION_DESIGN_GOALS_SUMMARY, {})

    @property
    def last_metrics(self) -> Dict[str, Any]:
        """最新仿真指标摘要"""
        return self.get(SESSION_LAST_METRICS, {})

    @property
    def error_context(self) -> str:
        """错误上下文"""
        return self.get(SESSION_ERROR_CONTEXT, "")

    # ============================================================
    # 状态摘要
    # ============================================================

    def get_status_summary(self) -> str:
        """获取状态摘要（用于日志和调试）"""
        return (
            f"SessionState(session={self.session_id}, mode={self.work_mode}, "
            f"node={self.current_node}, iter={self.iteration_count}, "
            f"locked={self.workflow_locked}, completed={self.is_completed})"
        )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SessionState",
    "SessionStateChangeHandler",
    # 状态字段常量
    "SESSION_PROJECT_ROOT",
    "SESSION_PROJECT_INITIALIZED",
    "SESSION_ID",
    "SESSION_WORK_MODE",
    "SESSION_WORKFLOW_LOCKED",
    "SESSION_CURRENT_NODE",
    "SESSION_PREVIOUS_NODE",
    "SESSION_ITERATION_COUNT",
    "SESSION_CHECKPOINT_COUNT",
    "SESSION_STAGNATION_COUNT",
    "SESSION_IS_COMPLETED",
    "SESSION_TERMINATION_REASON",
    "SESSION_ACTIVE_CIRCUIT_FILE",
    "SESSION_SIM_RESULT_PATH",
    "SESSION_DESIGN_GOALS_PATH",
    "SESSION_DESIGN_GOALS_SUMMARY",
    "SESSION_LAST_METRICS",
    "SESSION_ERROR_CONTEXT",
]
