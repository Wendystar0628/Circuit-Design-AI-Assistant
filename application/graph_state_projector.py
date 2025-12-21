# GraphState Projector - Automatic State Projection
"""
GraphState 投影器 - 自动将 GraphState 变更投影到 SessionState

职责：
- 监听 GraphState 变更
- 自动将变更投影到 SessionState
- 发布相关事件通知 UI 层

初始化顺序：
- Phase 3.6，依赖 SessionState、EventBus

设计原则：
- 单向数据流：GraphState → SessionState → UI
- UI 组件禁止直接读取或修改 GraphState
- 所有业务状态修改必须通过图节点执行

三层状态分离架构：
- Layer 1: UIState (Presentation) - 纯 UI 状态
- Layer 2: SessionState (Application) - GraphState 的只读投影
- Layer 3: GraphState (Domain) - LangGraph 工作流的唯一真理来源

使用示例：
    from application.graph_state_projector import GraphStateProjector
    from application.session_state import SessionState
    
    session_state = SessionState()
    projector = GraphStateProjector(session_state)
    
    # 当 GraphState 变更时调用
    projector.on_graph_state_changed(old_state, new_state)
"""

from typing import Any, Dict, Optional

from shared.event_types import (
    EVENT_SESSION_CHANGED,
    EVENT_WORKFLOW_LOCKED,
    EVENT_WORKFLOW_UNLOCKED,
    EVENT_FILE_CHANGED,
)

from application.session_state import (
    SessionState,
    SESSION_PROJECT_ROOT,
    SESSION_ID,
    SESSION_WORK_MODE,
    SESSION_WORKFLOW_LOCKED,
    SESSION_CURRENT_NODE,
    SESSION_PREVIOUS_NODE,
    SESSION_ITERATION_COUNT,
    SESSION_CHECKPOINT_COUNT,
    SESSION_STAGNATION_COUNT,
    SESSION_IS_COMPLETED,
    SESSION_TERMINATION_REASON,
    SESSION_ACTIVE_CIRCUIT_FILE,
    SESSION_SIM_RESULT_PATH,
    SESSION_DESIGN_GOALS_PATH,
    SESSION_DESIGN_GOALS_SUMMARY,
    SESSION_LAST_METRICS,
    SESSION_ERROR_CONTEXT,
)


# 工作流锁定状态的节点白名单（这些节点不锁定工作流）
UNLOCKED_NODES = ["", "start", "end", "free_work", "idle"]


def is_workflow_locked(current_node: str) -> bool:
    """
    判断工作流是否锁定
    
    工作流锁定 = 当前节点不在白名单中
    
    Args:
        current_node: 当前节点名称
        
    Returns:
        bool: 是否锁定
    """
    return current_node not in UNLOCKED_NODES


class GraphStateProjector:
    """
    GraphState 投影器
    
    将 GraphState 变更自动投影到 SessionState，
    确保 UI 层能够读取最新的业务状态。
    """

    def __init__(self, session_state: SessionState):
        """
        初始化投影器
        
        Args:
            session_state: SessionState 实例
        """
        self._session_state = session_state
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
                self._logger = get_logger("graph_state_projector")
            except Exception:
                pass
        return self._logger

    # ============================================================
    # 核心投影方法
    # ============================================================

    def on_graph_state_changed(
        self,
        old_state: Optional[Any],
        new_state: Any
    ) -> None:
        """
        GraphState 变更时调用
        
        将变更投影到 SessionState，并发布相关事件。
        
        Args:
            old_state: 旧的 GraphState（可能为 None）
            new_state: 新的 GraphState
        """
        if new_state is None:
            if self.logger:
                self.logger.warning("on_graph_state_changed called with None new_state")
            return

        # 收集需要更新的字段
        updates: Dict[str, Any] = {}

        # 投影会话相关字段
        self._project_session_fields(old_state, new_state, updates)

        # 投影工作流状态字段
        self._project_workflow_fields(old_state, new_state, updates)

        # 投影文件指针字段
        self._project_file_fields(old_state, new_state, updates)

        # 投影轻量摘要字段
        self._project_summary_fields(old_state, new_state, updates)

        # 批量更新 SessionState
        if updates:
            self._session_state._internal_update(updates)
            
            if self.logger:
                self.logger.debug(f"Projected {len(updates)} fields to SessionState")

    def _project_session_fields(
        self,
        old_state: Optional[Any],
        new_state: Any,
        updates: Dict[str, Any]
    ) -> None:
        """投影会话相关字段"""
        # session_id
        new_session_id = getattr(new_state, 'session_id', '')
        old_session_id = getattr(old_state, 'session_id', '') if old_state else ''
        if new_session_id != old_session_id:
            updates[SESSION_ID] = new_session_id

        # work_mode
        new_work_mode = getattr(new_state, 'work_mode', 'free_chat')
        old_work_mode = getattr(old_state, 'work_mode', 'free_chat') if old_state else 'free_chat'
        if new_work_mode != old_work_mode:
            updates[SESSION_WORK_MODE] = new_work_mode
            self._publish_work_mode_changed(old_work_mode, new_work_mode)

        # project_root
        new_project_root = getattr(new_state, 'project_root', '')
        old_project_root = getattr(old_state, 'project_root', '') if old_state else ''
        if new_project_root != old_project_root:
            updates[SESSION_PROJECT_ROOT] = new_project_root or None

    def _project_workflow_fields(
        self,
        old_state: Optional[Any],
        new_state: Any,
        updates: Dict[str, Any]
    ) -> None:
        """投影工作流状态字段"""
        # current_node
        new_node = getattr(new_state, 'current_node', '')
        old_node = getattr(old_state, 'current_node', '') if old_state else ''
        if new_node != old_node:
            updates[SESSION_CURRENT_NODE] = new_node
            updates[SESSION_PREVIOUS_NODE] = old_node

        # workflow_locked（派生自 current_node）
        new_locked = is_workflow_locked(new_node)
        old_locked = is_workflow_locked(old_node)
        if new_locked != old_locked:
            updates[SESSION_WORKFLOW_LOCKED] = new_locked

        # iteration_count
        new_iter = getattr(new_state, 'iteration_count', 0)
        old_iter = getattr(old_state, 'iteration_count', 0) if old_state else 0
        if new_iter != old_iter:
            updates[SESSION_ITERATION_COUNT] = new_iter

        # checkpoint_count
        new_checkpoint = getattr(new_state, 'checkpoint_count', 0)
        old_checkpoint = getattr(old_state, 'checkpoint_count', 0) if old_state else 0
        if new_checkpoint != old_checkpoint:
            updates[SESSION_CHECKPOINT_COUNT] = new_checkpoint

        # stagnation_count
        new_stagnation = getattr(new_state, 'stagnation_count', 0)
        old_stagnation = getattr(old_state, 'stagnation_count', 0) if old_state else 0
        if new_stagnation != old_stagnation:
            updates[SESSION_STAGNATION_COUNT] = new_stagnation

        # is_completed
        new_completed = getattr(new_state, 'is_completed', False)
        old_completed = getattr(old_state, 'is_completed', False) if old_state else False
        if new_completed != old_completed:
            updates[SESSION_IS_COMPLETED] = new_completed

        # termination_reason
        new_reason = getattr(new_state, 'termination_reason', '')
        old_reason = getattr(old_state, 'termination_reason', '') if old_state else ''
        if new_reason != old_reason:
            updates[SESSION_TERMINATION_REASON] = new_reason

    def _project_file_fields(
        self,
        old_state: Optional[Any],
        new_state: Any,
        updates: Dict[str, Any]
    ) -> None:
        """投影文件指针字段"""
        # circuit_file_path
        new_circuit = getattr(new_state, 'circuit_file_path', '')
        old_circuit = getattr(old_state, 'circuit_file_path', '') if old_state else ''
        if new_circuit != old_circuit:
            updates[SESSION_ACTIVE_CIRCUIT_FILE] = new_circuit
            self._publish_active_file_changed(old_circuit, new_circuit)

        # sim_result_path
        new_sim = getattr(new_state, 'sim_result_path', '')
        old_sim = getattr(old_state, 'sim_result_path', '') if old_state else ''
        if new_sim != old_sim:
            updates[SESSION_SIM_RESULT_PATH] = new_sim

        # design_goals_path
        new_goals_path = getattr(new_state, 'design_goals_path', '.circuit_ai/design_goals.json')
        old_goals_path = getattr(old_state, 'design_goals_path', '.circuit_ai/design_goals.json') if old_state else '.circuit_ai/design_goals.json'
        if new_goals_path != old_goals_path:
            updates[SESSION_DESIGN_GOALS_PATH] = new_goals_path

    def _project_summary_fields(
        self,
        old_state: Optional[Any],
        new_state: Any,
        updates: Dict[str, Any]
    ) -> None:
        """投影轻量摘要字段"""
        # design_goals_summary
        new_goals = getattr(new_state, 'design_goals_summary', {})
        old_goals = getattr(old_state, 'design_goals_summary', {}) if old_state else {}
        if new_goals != old_goals:
            updates[SESSION_DESIGN_GOALS_SUMMARY] = new_goals

        # last_metrics
        new_metrics = getattr(new_state, 'last_metrics', {})
        old_metrics = getattr(old_state, 'last_metrics', {}) if old_state else {}
        if new_metrics != old_metrics:
            updates[SESSION_LAST_METRICS] = new_metrics

        # error_context
        new_error = getattr(new_state, 'error_context', '')
        old_error = getattr(old_state, 'error_context', '') if old_state else ''
        if new_error != old_error:
            updates[SESSION_ERROR_CONTEXT] = new_error

    # ============================================================
    # 事件发布
    # ============================================================

    def _publish_work_mode_changed(self, old_mode: str, new_mode: str) -> None:
        """发布工作模式变更事件"""
        if self.event_bus is None:
            return
        
        try:
            self.event_bus.publish(
                EVENT_SESSION_CHANGED,
                {
                    "action": "work_mode_changed",
                    "old_mode": old_mode,
                    "new_mode": new_mode,
                },
                source="graph_state_projector"
            )
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to publish work mode changed event: {e}")

    def _publish_active_file_changed(self, old_path: str, new_path: str) -> None:
        """发布当前文件变更事件"""
        if self.event_bus is None:
            return
        
        try:
            # 使用 EVENT_FILE_CHANGED 事件，携带特定的 action
            self.event_bus.publish(
                EVENT_FILE_CHANGED,
                {
                    "action": "active_file_changed",
                    "old_path": old_path,
                    "new_path": new_path,
                },
                source="graph_state_projector"
            )
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to publish active file changed event: {e}")

    # ============================================================
    # 初始化投影
    # ============================================================

    def project_initial_state(self, graph_state: Any) -> None:
        """
        投影初始状态
        
        在应用启动或会话恢复时调用，将完整的 GraphState 投影到 SessionState。
        
        Args:
            graph_state: GraphState 实例
        """
        self.on_graph_state_changed(None, graph_state)
        
        if self.logger:
            self.logger.info("Initial GraphState projected to SessionState")

    def reset(self) -> None:
        """
        重置 SessionState
        
        在项目关闭或会话清理时调用。
        """
        self._session_state._internal_reset()
        
        if self.logger:
            self.logger.info("SessionState reset")

    # ============================================================
    # 项目状态管理（供 ProjectService 调用）
    # ============================================================

    def update_project_state(
        self,
        project_root: str,
        is_existing: bool = False,
        has_history: bool = False,
    ) -> None:
        """
        更新项目状态
        
        在项目打开时由 ProjectService 调用，更新 SessionState 中的项目相关字段。
        
        Args:
            project_root: 项目根目录路径
            is_existing: 是否为已有项目
            has_history: 是否有历史记录
        """
        updates = {
            SESSION_PROJECT_ROOT: project_root,
        }
        
        self._session_state._internal_update(updates)
        
        if self.logger:
            self.logger.info(f"Project state updated: {project_root} (existing={is_existing}, history={has_history})")

    def clear_project_state(self) -> None:
        """
        清空项目状态
        
        在项目关闭时由 ProjectService 调用，清空 SessionState 中的项目相关字段。
        """
        updates = {
            SESSION_PROJECT_ROOT: None,
            SESSION_ACTIVE_CIRCUIT_FILE: "",
            SESSION_SIM_RESULT_PATH: "",
            SESSION_DESIGN_GOALS_PATH: ".circuit_ai/design_goals.json",
            SESSION_DESIGN_GOALS_SUMMARY: {},
            SESSION_WORKFLOW_LOCKED: False,
            SESSION_CURRENT_NODE: "",
            SESSION_PREVIOUS_NODE: "",
            SESSION_ITERATION_COUNT: 0,
            SESSION_CHECKPOINT_COUNT: 0,
            SESSION_STAGNATION_COUNT: 0,
            SESSION_IS_COMPLETED: False,
            SESSION_TERMINATION_REASON: "",
            SESSION_LAST_METRICS: {},
            SESSION_ERROR_CONTEXT: "",
        }
        
        self._session_state._internal_update(updates)
        
        if self.logger:
            self.logger.info("Project state cleared")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "GraphStateProjector",
    "is_workflow_locked",
    "UNLOCKED_NODES",
]
