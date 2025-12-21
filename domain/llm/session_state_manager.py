# Session State Manager - Single Source of Truth for Session State
"""
会话状态管理器 - 会话状态的唯一数据源（Single Source of Truth）

职责：
- 持有当前会话名称（_current_session_name）
- 持有会话元数据（_session_metadata）
- 协调 ContextManager（消息）和 MessageStore（持久化）
- 提供原子操作：new_session、switch_session、save_current_session、delete_session
- 发布 EVENT_SESSION_CHANGED 事件通知所有订阅者

设计原则：
- 单一数据源：所有会话状态都从 SessionStateManager 获取
- 原子操作：每个会话操作都是原子的，保证状态一致性
- 事件驱动：状态变更通过事件通知，UI 组件订阅事件后刷新
- 延迟获取：不在 __init__ 中调用 ServiceLocator.get()

使用示例：
    from domain.llm.session_state_manager import SessionStateManager
    
    manager = SessionStateManager()
    
    # 新开对话
    manager.new_session()
    
    # 切换会话
    manager.switch_session("Chat 2024-12-16 14:30")
    
    # 保存当前会话
    manager.save_current_session()
"""

import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


class SessionStateManager:
    """
    会话状态管理器
    
    作为会话状态的唯一数据源，协调 ContextManager 和 MessageStore。
    """
    
    def __init__(self):
        """初始化会话状态管理器"""
        self._lock = threading.RLock()
        
        # 会话状态
        self._current_session_name: str = ""
        self._session_metadata: Dict[str, Any] = {}
        
        # 延迟获取的服务
        self._context_manager = None
        self._session_state = None
        self._event_bus = None
        self._logger = None
        self._message_store = None
    
    # ============================================================
    # 延迟获取服务
    # ============================================================
    
    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("session_state_manager")
            except Exception:
                pass
        return self._logger
    
    @property
    def event_bus(self):
        """延迟获取事件总线"""
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus
    
    @property
    def context_manager(self):
        """延迟获取上下文管理器"""
        if self._context_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CONTEXT_MANAGER
                self._context_manager = ServiceLocator.get_optional(SVC_CONTEXT_MANAGER)
            except Exception:
                pass
        return self._context_manager
    
    @property
    def session_state(self):
        """延迟获取会话状态（只读）"""
        if self._session_state is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE
                self._session_state = ServiceLocator.get_optional(SVC_SESSION_STATE)
            except Exception:
                pass
        return self._session_state
    
    @property
    def message_store(self):
        """延迟获取消息存储"""
        if self._message_store is None:
            try:
                from domain.llm.message_store import MessageStore
                self._message_store = MessageStore()
            except Exception:
                pass
        return self._message_store
    
    # ============================================================
    # 属性访问
    # ============================================================
    
    def get_current_session_name(self) -> str:
        """
        获取当前会话名称
        
        Returns:
            str: 当前会话名称
        """
        with self._lock:
            return self._current_session_name
    
    def get_session_metadata(self) -> Dict[str, Any]:
        """
        获取当前会话元数据
        
        Returns:
            Dict: 会话元数据
        """
        with self._lock:
            return self._session_metadata.copy()
    
    def get_project_path(self) -> Optional[str]:
        """
        获取当前项目路径
        
        Returns:
            str: 项目路径，若无则返回 None
        """
        if self.session_state:
            try:
                return self.session_state.project_root
            except Exception:
                pass
        return None

    # ============================================================
    # 核心操作方法
    # ============================================================
    
    def new_session(self) -> Tuple[bool, str]:
        """
        新开对话（原子操作）
        
        执行步骤：
        1. 保存当前会话消息到会话文件
        2. 生成新会话名称（精确到分钟）
        3. 调用 ContextManager.reset_messages() 清空消息
        4. 创建新会话记录并更新 sessions.json
        5. 更新 _current_session_name
        6. 发布 EVENT_SESSION_CHANGED 事件
        
        Returns:
            (是否成功, 消息或新会话名称)
        """
        with self._lock:
            project_path = self.get_project_path()
            
            # 保存当前会话（如果有消息）
            if self._current_session_name and project_path:
                self._save_current_session_internal(project_path)
            
            # 生成新会话名称
            new_name = self._generate_session_name()
            previous_name = self._current_session_name
            
            # 重置 ContextManager 消息
            if self.context_manager:
                state = self.context_manager._get_internal_state()
                new_state = self.context_manager.reset_messages(state, keep_system=True)
                self.context_manager._set_internal_state(new_state)
            
            # 更新状态
            self._current_session_name = new_name
            self._session_metadata = {
                "name": new_name,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "message_count": 0,
            }
            
            # 创建新会话文件
            if project_path and self.message_store:
                state = self.context_manager._get_internal_state() if self.context_manager else {"messages": []}
                self.message_store.save_session(state, project_path, new_name)
            
            if self.logger:
                self.logger.info(f"New session created: {new_name}")
            
            # 发布事件
            self._publish_session_changed_event(
                action="new",
                previous_session_name=previous_name
            )
            
            return True, new_name
    
    def switch_session(self, session_name: str) -> Tuple[bool, str]:
        """
        切换到指定会话（原子操作）
        
        执行步骤：
        1. 保存当前会话（若有消息）
        2. 从会话文件加载选中会话的消息
        3. 调用 ContextManager.load_messages_from_data() 加载消息
        4. 更新 _current_session_name
        5. 发布 EVENT_SESSION_CHANGED 事件
        
        Args:
            session_name: 目标会话名称
            
        Returns:
            (是否成功, 消息)
        """
        with self._lock:
            project_path = self.get_project_path()
            if not project_path:
                return False, "No project path"
            
            # 保存当前会话
            if self._current_session_name:
                self._save_current_session_internal(project_path)
            
            previous_name = self._current_session_name
            
            # 加载目标会话
            if self.message_store and self.context_manager:
                state = self.context_manager._get_internal_state()
                new_state, success, msg, metadata = self.message_store.load_session(
                    project_path, session_name, state
                )
                
                if not success:
                    return False, msg
                
                # 更新 ContextManager 状态
                self.context_manager._set_internal_state(new_state)
                
                # 更新状态
                self._current_session_name = session_name
                self._session_metadata = metadata or {}
                
                if self.logger:
                    self.logger.info(f"Switched to session: {session_name}")
                
                # 发布事件
                self._publish_session_changed_event(
                    action="switch",
                    previous_session_name=previous_name
                )
                
                return True, f"Switched to: {session_name}"
            
            return False, "MessageStore or ContextManager not available"
    
    def save_current_session(self) -> Tuple[bool, str]:
        """
        保存当前会话
        
        Returns:
            (是否成功, 消息)
        """
        with self._lock:
            project_path = self.get_project_path()
            if not project_path:
                return False, "No project path"
            
            if not self._current_session_name:
                return False, "No current session"
            
            success, msg = self._save_current_session_internal(project_path)
            
            if success:
                # 发布事件
                self._publish_session_changed_event(action="save")
            
            return success, msg
    
    def delete_session(self, session_name: str) -> Tuple[bool, str]:
        """
        删除指定会话
        
        Args:
            session_name: 要删除的会话名称
            
        Returns:
            (是否成功, 消息)
        """
        with self._lock:
            project_path = self.get_project_path()
            if not project_path:
                return False, "No project path"
            
            if not self.message_store:
                return False, "MessageStore not available"
            
            # 删除会话文件
            success, msg = self.message_store.delete_session(project_path, session_name)
            
            if success:
                if self.logger:
                    self.logger.info(f"Session deleted: {session_name}")
                
                # 如果删除的是当前会话，创建新会话
                if session_name == self._current_session_name:
                    self._current_session_name = ""
                    self._session_metadata = {}
                    # 创建新会话
                    self.new_session()
                else:
                    # 发布事件
                    self._publish_session_changed_event(action="delete")
            
            return success, msg
    
    def rename_session(self, old_name: str, new_name: str) -> Tuple[bool, str]:
        """
        重命名会话
        
        Args:
            old_name: 旧会话名称
            new_name: 新会话名称
            
        Returns:
            (是否成功, 消息)
        """
        with self._lock:
            project_path = self.get_project_path()
            if not project_path:
                return False, "No project path"
            
            if not self.message_store:
                return False, "MessageStore not available"
            
            success, msg = self.message_store.rename_session(
                project_path, old_name, new_name
            )
            
            if success:
                # 如果重命名的是当前会话，更新状态
                if old_name == self._current_session_name:
                    self._current_session_name = new_name
                    self._session_metadata["name"] = new_name
                
                if self.logger:
                    self.logger.info(f"Session renamed: {old_name} -> {new_name}")
                
                # 发布事件
                self._publish_session_changed_event(action="rename")
            
            return success, msg

    # ============================================================
    # 启动恢复方法
    # ============================================================
    
    def restore_on_startup(self) -> Tuple[bool, str]:
        """
        启动时恢复会话
        
        执行步骤：
        1. 读取 sessions.json 获取 current_session_name
        2. 若存在当前会话，加载会话消息
        3. 若不存在当前会话，生成新会话名称并创建
        4. 发布 EVENT_SESSION_CHANGED 事件
        
        Returns:
            (是否成功, 消息)
        """
        with self._lock:
            project_path = self.get_project_path()
            if not project_path:
                if self.logger:
                    self.logger.debug("No project path, creating new session")
                return self.new_session()
            
            if not self.message_store or not self.context_manager:
                return self.new_session()
            
            # 尝试加载当前会话
            state = self.context_manager._get_internal_state()
            new_state, success, msg, metadata = self.message_store.load_current_session(
                project_path, state
            )
            
            if success and metadata:
                # 恢复成功
                self.context_manager._set_internal_state(new_state)
                
                session_name = metadata.get("name", "")
                self._current_session_name = session_name
                self._session_metadata = metadata
                
                if self.logger:
                    self.logger.info(f"Session restored: {session_name}")
                
                # 发布事件
                self._publish_session_changed_event(action="restore")
                
                return True, f"Restored: {session_name}"
            else:
                # 加载失败，创建新会话
                if self.logger:
                    self.logger.debug(f"No current session to restore: {msg}")
                return self.new_session()
    
    def get_all_sessions(self) -> List[Dict[str, Any]]:
        """
        获取所有会话列表
        
        Returns:
            会话列表
        """
        project_path = self.get_project_path()
        if not project_path or not self.message_store:
            return []
        
        return self.message_store.get_all_sessions(project_path)
    
    # ============================================================
    # 内部辅助方法
    # ============================================================
    
    def _save_current_session_internal(self, project_path: str) -> Tuple[bool, str]:
        """
        内部保存当前会话方法
        
        Args:
            project_path: 项目路径
            
        Returns:
            (是否成功, 消息)
        """
        if not self._current_session_name:
            return False, "No current session"
        
        if not self.message_store or not self.context_manager:
            return False, "Services not available"
        
        state = self.context_manager._get_internal_state()
        success, msg = self.message_store.save_session(
            state, project_path, self._current_session_name
        )
        
        if success:
            # 更新元数据
            messages = self.context_manager.get_messages(state)
            self._session_metadata["updated_at"] = datetime.now().isoformat()
            self._session_metadata["message_count"] = len(messages)
            
            if self.logger:
                self.logger.debug(f"Session saved: {self._current_session_name}")
        
        return success, msg
    
    def _generate_session_name(self) -> str:
        """
        生成会话名称
        
        格式：Chat YYYY-MM-DD HH:mm（精确到分钟）
        
        Returns:
            str: 会话名称
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        return f"Chat {now}"
    
    def _publish_session_changed_event(
        self,
        action: str,
        previous_session_name: str = ""
    ) -> None:
        """
        发布会话变更事件
        
        Args:
            action: 触发动作（"new", "switch", "save", "delete", "rename", "restore"）
            previous_session_name: 之前的会话名称
        """
        if self.event_bus:
            try:
                from shared.event_types import EVENT_SESSION_CHANGED
                
                # 获取消息数量
                message_count = 0
                if self.context_manager:
                    state = self.context_manager._get_internal_state()
                    messages = self.context_manager.get_messages(state)
                    message_count = len(messages)
                
                self.event_bus.publish(EVENT_SESSION_CHANGED, {
                    "session_name": self._current_session_name,
                    "message_count": message_count,
                    "action": action,
                    "previous_session_name": previous_session_name,
                })
            except ImportError:
                if self.logger:
                    self.logger.warning("EVENT_SESSION_CHANGED not defined")
    
    def _set_session_name_internal(self, name: str) -> None:
        """
        内部设置会话名称（不发布事件）
        
        Args:
            name: 会话名称
        """
        with self._lock:
            self._current_session_name = name


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SessionStateManager",
]
