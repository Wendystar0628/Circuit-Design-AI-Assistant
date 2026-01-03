# Session State Manager - Session Lifecycle Coordinator
"""
会话状态管理器 - 会话生命周期协调器

职责：
- 协调会话的完整生命周期（新建、切换、保存、恢复）
- 是 MessageStore 和 ContextService 的上层协调者
- 发布 EVENT_SESSION_CHANGED 事件通知所有订阅者

设计原则：
- 有状态：持有当前 session_id 和 project_root
- 协调者：不直接操作文件，通过 context_service 模块进行
- 不直接操作 GraphState.messages，通过 MessageStore 进行

三层职责分离：
┌─────────────────────────────────────────────────────────────┐
│              SessionStateManager (协调层)                    │
│  职责：会话生命周期协调（新建、切换、保存、恢复）              │
│  特点：有状态，持有当前 session_id                           │
└─────────────────────────────────────────────────────────────┘
                   │                      │
                   ↓                      ↓
┌──────────────────────────┐  ┌──────────────────────────────┐
│   MessageStore (内存层)   │  │   context_service (文件层)   │
│  职责：                   │  │  职责：                      │
│  - GraphState.messages   │  │  - 会话文件 CRUD             │
│  - 消息添加/获取/分类     │  │  - 会话索引管理              │
│  特点：无状态，纯内存操作  │  │  特点：无状态，纯文件 I/O    │
└──────────────────────────┘  └──────────────────────────────┘

使用示例：
    from domain.llm.session_state_manager import SessionStateManager
    
    manager = SessionStateManager()
    
    # 应用启动时恢复会话
    state = manager.on_app_startup(project_root, initial_state)
    
    # 创建新会话
    session_id = manager.create_session(project_root, "free_chat")
    
    # 切换会话
    state = manager.switch_session(project_root, session_id, state)
    
    # 保存当前会话
    manager.save_current_session(state, project_root)
"""

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from application.graph.state import GraphState


@dataclass
class SessionInfo:
    """会话信息数据结构"""
    session_id: str
    name: str
    created_at: str
    updated_at: str
    message_count: int
    preview: str = ""
    has_partial_response: bool = False


class SessionStateManager:
    """
    会话状态管理器 - 会话生命周期协调器
    
    作为 MessageStore 和 context_service 的上层协调者，
    管理会话的完整生命周期。
    """
    
    def __init__(self):
        """初始化会话状态管理器"""
        self._lock = threading.RLock()
        
        # 状态属性
        self._current_session_id: str = ""
        self._project_root: str = ""
        self._is_dirty: bool = False
        
        # 延迟获取的服务
        self._message_store = None
        self._event_bus = None
        self._logger = None
    
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
    # 会话生命周期方法
    # ============================================================
    
    def create_session(
        self,
        project_root: str,
        work_mode: str = "free_chat"
    ) -> str:
        """
        创建新会话
        
        执行步骤：
        1. 生成新会话 ID（时间戳格式）
        2. 在 context_service 中创建会话文件
        3. 更新会话索引
        4. 更新内部状态
        5. 发布 EVENT_SESSION_CHANGED 事件
        
        Args:
            project_root: 项目根目录路径
            work_mode: 工作模式（"workflow" | "free_chat"）
            
        Returns:
            str: 新会话 ID
        """
        from domain.services import context_service
        
        with self._lock:
            # 生成会话 ID
            session_id = self._generate_session_id()
            session_name = self._generate_session_name()
            
            previous_session_id = self._current_session_id
            
            # 创建空会话文件
            context_service.save_messages(project_root, session_id, [])
            
            # 更新会话索引
            context_service.update_session_index(
                project_root,
                session_id,
                {
                    "session_id": session_id,
                    "name": session_name,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "message_count": 0,
                    "work_mode": work_mode,
                },
                set_current=True
            )
            
            # 更新内部状态
            self._current_session_id = session_id
            self._project_root = project_root
            self._is_dirty = False
            
            if self.logger:
                self.logger.info(f"新会话已创建: {session_id}")
            
            # 发布事件
            self._publish_session_changed_event(
                action="new",
                previous_session_id=previous_session_id
            )
            
            return session_id

    def switch_session(
        self,
        project_root: str,
        session_id: str,
        state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        切换到指定会话
        
        执行步骤：
        1. 保存当前会话（若有未保存的更改）
        2. 从 context_service 加载目标会话消息
        3. 通过 MessageStore 更新 GraphState.messages
        4. 更新会话索引中的当前会话
        5. 更新内部状态
        6. 发布 EVENT_SESSION_CHANGED 事件
        
        Args:
            project_root: 项目根目录路径
            session_id: 目标会话 ID
            state: 当前 GraphState（字典形式）
            
        Returns:
            Dict: 更新后的 GraphState（字典形式）
        """
        from domain.services import context_service
        from domain.llm.message_types import Message
        
        with self._lock:
            # 保存当前会话（如果有未保存的更改）
            if self._is_dirty and self._current_session_id:
                self.save_current_session(state, project_root)
            
            previous_session_id = self._current_session_id
            
            # 加载目标会话消息
            messages_data = context_service.load_messages(project_root, session_id)
            
            # 重建消息对象
            messages = []
            for msg_data in messages_data:
                try:
                    messages.append(Message.from_dict(msg_data))
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"消息反序列化失败: {e}")
            
            # 通过 MessageStore 更新状态
            new_state = self.message_store._message_adapter.update_state_messages(
                state, messages
            )
            
            # 恢复摘要
            metadata = context_service.get_session_metadata(project_root, session_id)
            if metadata:
                new_state["conversation_summary"] = metadata.get("summary", "")
            
            # 更新会话索引中的当前会话
            context_service.set_current_session_id(project_root, session_id)
            
            # 更新内部状态
            self._current_session_id = session_id
            self._project_root = project_root
            self._is_dirty = False
            
            if self.logger:
                self.logger.info(f"已切换到会话: {session_id}")
            
            # 发布事件
            self._publish_session_changed_event(
                action="switch",
                previous_session_id=previous_session_id
            )
            
            return new_state
    
    def save_current_session(
        self,
        state: Dict[str, Any],
        project_root: str
    ) -> bool:
        """
        保存当前会话
        
        执行步骤：
        1. 从 GraphState 提取消息
        2. 通过 context_service 保存到文件
        3. 更新会话索引
        4. 重置 _is_dirty 标志
        5. 发布 EVENT_SESSION_CHANGED 事件
        
        Args:
            state: 当前 GraphState（字典形式）
            project_root: 项目根目录路径
            
        Returns:
            bool: 是否保存成功
        """
        from domain.services import context_service
        
        with self._lock:
            if not self._current_session_id:
                if self.logger:
                    self.logger.warning("无当前会话，无法保存")
                return False
            
            # 提取消息
            messages = self.message_store.get_messages(state)
            messages_data = [msg.to_dict() for msg in messages]
            
            # 获取首条用户消息作为预览
            preview = ""
            for msg in messages:
                if msg.is_user():
                    preview = msg.content[:50]
                    break
            
            # 保存消息到文件
            context_service.save_messages(
                project_root,
                self._current_session_id,
                messages_data
            )
            
            # 更新会话索引
            context_service.update_session_index(
                project_root,
                self._current_session_id,
                {
                    "updated_at": datetime.now().isoformat(),
                    "message_count": len(messages),
                    "preview": preview,
                    "summary": state.get("conversation_summary", ""),
                }
            )
            
            # 重置脏标志
            self._is_dirty = False
            
            if self.logger:
                self.logger.debug(f"会话已保存: {self._current_session_id}")
            
            # 发布事件
            self._publish_session_changed_event(action="save")
            
            return True
    
    def delete_session(
        self,
        project_root: str,
        session_id: str
    ) -> bool:
        """
        删除指定会话
        
        Args:
            project_root: 项目根目录路径
            session_id: 要删除的会话 ID
            
        Returns:
            bool: 是否删除成功
        """
        from domain.services import context_service
        
        with self._lock:
            # 删除会话文件
            success = context_service.delete_session(project_root, session_id)
            
            if success:
                # 从索引中移除
                context_service.remove_from_session_index(project_root, session_id)
                
                if self.logger:
                    self.logger.info(f"会话已删除: {session_id}")
                
                # 如果删除的是当前会话，清空状态
                if session_id == self._current_session_id:
                    self._current_session_id = ""
                    self._is_dirty = False
                
                # 发布事件
                self._publish_session_changed_event(action="delete")
            
            return success
    
    def rename_session(
        self,
        project_root: str,
        session_id: str,
        new_name: str
    ) -> bool:
        """
        重命名会话
        
        Args:
            project_root: 项目根目录路径
            session_id: 会话 ID
            new_name: 新名称
            
        Returns:
            bool: 是否重命名成功
        """
        from domain.services import context_service
        
        with self._lock:
            # 更新会话索引中的名称
            success = context_service.update_session_index(
                project_root,
                session_id,
                {
                    "name": new_name,
                    "updated_at": datetime.now().isoformat(),
                }
            )
            
            if success:
                if self.logger:
                    self.logger.info(f"会话已重命名: {session_id} -> {new_name}")
                
                # 发布事件
                self._publish_session_changed_event(action="rename")
            
            return success

    # ============================================================
    # 会话查询方法
    # ============================================================
    
    def get_current_session_id(self) -> str:
        """
        获取当前会话 ID
        
        Returns:
            str: 当前会话 ID，无会话时返回空字符串
        """
        with self._lock:
            return self._current_session_id
    
    def get_all_sessions(self, project_root: str) -> List[SessionInfo]:
        """
        获取所有会话列表
        
        Args:
            project_root: 项目根目录路径
            
        Returns:
            List[SessionInfo]: 会话信息列表，按更新时间倒序
        """
        from domain.services import context_service
        
        sessions_data = context_service.list_sessions(project_root)
        
        result = []
        for data in sessions_data:
            result.append(SessionInfo(
                session_id=data.get("session_id", ""),
                name=data.get("name", data.get("session_id", "")),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
                message_count=data.get("message_count", 0),
                preview=data.get("preview", ""),
                has_partial_response=data.get("has_partial_response", False),
            ))
        
        return result
    
    def get_session_info(
        self,
        project_root: str,
        session_id: str
    ) -> Optional[SessionInfo]:
        """
        获取会话详情
        
        Args:
            project_root: 项目根目录路径
            session_id: 会话 ID
            
        Returns:
            SessionInfo: 会话信息，不存在返回 None
        """
        from domain.services import context_service
        
        metadata = context_service.get_session_metadata(project_root, session_id)
        
        if not metadata:
            return None
        
        return SessionInfo(
            session_id=session_id,
            name=metadata.get("name", session_id),
            created_at=metadata.get("created_at", ""),
            updated_at=metadata.get("updated_at", ""),
            message_count=metadata.get("message_count", 0),
            preview=metadata.get("preview", ""),
            has_partial_response=metadata.get("has_partial_response", False),
        )
    
    def get_last_session_id(self, project_root: str) -> Optional[str]:
        """
        获取上次使用的会话 ID
        
        从会话索引中读取 current_session_id。
        
        Args:
            project_root: 项目根目录路径
            
        Returns:
            str: 上次使用的会话 ID，不存在返回 None
        """
        from domain.services import context_service
        
        return context_service.get_current_session_id(project_root)
    
    # ============================================================
    # 应用生命周期集成
    # ============================================================
    
    def on_app_startup(
        self,
        project_root: str,
        state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        应用启动时恢复会话
        
        执行步骤：
        1. 读取会话索引获取 current_session_id
        2. 若存在当前会话，加载会话消息
        3. 若不存在当前会话，创建新会话
        4. 发布 EVENT_SESSION_CHANGED 事件
        
        Args:
            project_root: 项目根目录路径
            state: 初始 GraphState（字典形式）
            
        Returns:
            Dict: 更新后的 GraphState（字典形式）
        """
        from domain.services import context_service
        
        with self._lock:
            self._project_root = project_root
            
            # 获取上次使用的会话 ID
            last_session_id = context_service.get_current_session_id(project_root)
            
            if last_session_id:
                # 检查会话文件是否存在
                messages = context_service.load_messages(project_root, last_session_id)
                
                if messages is not None:
                    # 恢复会话
                    new_state = self.switch_session(
                        project_root, last_session_id, state
                    )
                    
                    if self.logger:
                        self.logger.info(f"会话已恢复: {last_session_id}")
                    
                    return new_state
            
            # 无可恢复的会话，创建新会话
            session_id = self.create_session(project_root)
            
            if self.logger:
                self.logger.info(f"创建新会话: {session_id}")
            
            return state
    
    def on_app_shutdown(
        self,
        state: Dict[str, Any],
        project_root: str
    ) -> None:
        """
        应用关闭时保存会话
        
        Args:
            state: 当前 GraphState（字典形式）
            project_root: 项目根目录路径
        """
        with self._lock:
            if self._current_session_id and self._is_dirty:
                self.save_current_session(state, project_root)
                
                if self.logger:
                    self.logger.info(f"应用关闭，会话已保存: {self._current_session_id}")
    
    def mark_dirty(self) -> None:
        """
        标记有未保存的更改
        
        当消息被添加或修改时调用此方法。
        """
        with self._lock:
            self._is_dirty = True
    
    # ============================================================
    # 内部辅助方法
    # ============================================================
    
    def _generate_session_id(self) -> str:
        """
        生成会话 ID
        
        格式：YYYYMMDD_HHMMSS
        
        Returns:
            str: 会话 ID
        """
        return datetime.now().strftime("%Y%m%d_%H%M%S")
    
    def _generate_session_name(self) -> str:
        """
        生成会话名称
        
        格式：Chat YYYY-MM-DD HH:mm
        
        Returns:
            str: 会话名称
        """
        return f"Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    
    def _publish_session_changed_event(
        self,
        action: str,
        previous_session_id: str = ""
    ) -> None:
        """
        发布会话变更事件
        
        Args:
            action: 触发动作（"new", "switch", "save", "delete", "rename", "restore"）
            previous_session_id: 之前的会话 ID
        """
        if self.event_bus:
            try:
                from shared.event_types import EVENT_SESSION_CHANGED
                
                self.event_bus.publish(EVENT_SESSION_CHANGED, {
                    "session_id": self._current_session_id,
                    "session_name": self._get_current_session_name(),
                    "action": action,
                    "previous_session_id": previous_session_id,
                })
            except ImportError:
                if self.logger:
                    self.logger.warning("EVENT_SESSION_CHANGED not defined")
    
    def _get_current_session_name(self) -> str:
        """获取当前会话名称"""
        if not self._current_session_id or not self._project_root:
            return ""
        
        from domain.services import context_service
        
        metadata = context_service.get_session_metadata(
            self._project_root, self._current_session_id
        )
        
        return metadata.get("name", self._current_session_id) if metadata else ""


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SessionStateManager",
    "SessionInfo",
]
