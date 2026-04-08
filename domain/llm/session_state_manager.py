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
- 会话切换时直接构建新 state（含 messages 替换），日常消息追加通过 MessageStore 进行

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
    session_id = manager.create_session(project_root)
    
    # 切换会话
    state = manager.switch_session(project_root, session_id, state)
    
    # 保存当前会话
    manager.save_current_session(state, project_root)
"""

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from domain.llm.working_context_builder import (
    WORKING_CONTEXT_COMPRESSED_COUNT_KEY,
    WORKING_CONTEXT_KEEP_RECENT_KEY,
    WORKING_CONTEXT_SUMMARY_KEY,
)

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
        self._context_manager = None
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
            except Exception as e:
                logging.getLogger(__name__).warning(f"Failed to load custom logger, using stdlib: {e}")
                self._logger = logging.getLogger(__name__)
        return self._logger
    
    @property
    def event_bus(self):
        """延迟获取事件总线"""
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception as e:
                logging.getLogger(__name__).warning(f"Failed to load EventBus: {e}")
        return self._event_bus
    
    @property
    def message_store(self):
        """延迟获取消息存储"""
        if self._message_store is None:
            try:
                from domain.llm.message_store import MessageStore
                self._message_store = MessageStore()
            except Exception as e:
                logging.getLogger(__name__).error(f"Failed to load MessageStore: {e}")
        return self._message_store

    @property
    def context_manager(self):
        """延迟获取上下文管理器"""
        if self._context_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CONTEXT_MANAGER
                self._context_manager = ServiceLocator.get_optional(SVC_CONTEXT_MANAGER)
            except Exception as e:
                logging.getLogger(__name__).warning(f"Failed to load ContextManager: {e}")
        return self._context_manager
    
    # ============================================================
    # 会话生命周期方法
    # ============================================================
    
    def create_session(
        self,
        project_root: Optional[str] = None,
    ) -> str:
        """
        创建新会话
        
        执行步骤：
        1. 生成新会话 ID（时间戳格式）
        2. 在 context_service 中创建会话文件
        3. 更新会话索引
        4. 更新内部状态
        5. 重置 ContextManager 状态（清空消息）
        6. 发布 EVENT_SESSION_CHANGED 事件
        
        Args:
            project_root: 项目根目录路径
            
        Returns:
            str: 新会话 ID
        """
        with self._lock:
            resolved_project_root = self._resolve_project_root(project_root)
            if not resolved_project_root:
                raise ValueError("No project root available")

            if self._is_dirty and self._current_session_id:
                active_project_root = self._project_root or resolved_project_root
                self.save_current_session(
                    project_root=active_project_root,
                )

            previous_session_id = self._current_session_id
            session_id, session_name = self._create_empty_session(resolved_project_root)
            
            if self.logger:
                self.logger.info(f"新会话已创建: {session_id}, 名称: {session_name}")
            
            self._sync_state_to_context_manager(self._build_empty_conversation_state())
            
            # 发布事件
            self._publish_session_changed_event(
                action="new",
                previous_session_id=previous_session_id
            )
            
            return session_id

    def switch_session(
        self,
        project_root: Optional[str],
        session_id: str,
        state: Optional[Dict[str, Any]] = None,
        sync_to_context_manager: bool = True
    ) -> Dict[str, Any]:
        """
        切换到指定会话
        
        执行步骤：
        1. 保存当前会话（若有未保存的更改）
        2. 从 context_service 加载目标会话消息
        3. 通过 MessageStore 更新 GraphState.messages
        4. 更新会话索引中的当前会话
        5. 更新内部状态
        6. 同步状态到 ContextManager（确保 UI 能正确加载消息）
        7. 发布 EVENT_SESSION_CHANGED 事件
        
        Args:
            project_root: 项目根目录路径
            session_id: 目标会话 ID
            state: 当前 GraphState（字典形式）
            sync_to_context_manager: 是否同步状态到 ContextManager（默认 True）
            
        Returns:
            Dict: 更新后的 GraphState（字典形式）
        """
        from domain.services import context_service
        
        with self._lock:
            resolved_project_root = self._resolve_project_root(project_root)
            if not resolved_project_root:
                raise ValueError("No project root available")
            if not session_id:
                raise ValueError("Session ID cannot be empty")
            if not context_service.session_exists(resolved_project_root, session_id):
                raise ValueError(f"Session not found: {session_id}")

            if session_id == self._current_session_id:
                current_state = state if state is not None else self._get_current_state()
                if self._is_dirty:
                    self.save_current_session(
                        state=current_state,
                        project_root=resolved_project_root,
                    )
                if sync_to_context_manager:
                    self._sync_state_to_context_manager(current_state)
                return current_state

            # 保存当前会话（如果有未保存的更改）
            if self._is_dirty and self._current_session_id and self._current_session_id != session_id:
                active_project_root = self._project_root or resolved_project_root
                self.save_current_session(
                    state=state,
                    project_root=active_project_root,
                )
            
            previous_session_id = self._current_session_id
            new_state = self._build_session_state(
                resolved_project_root,
                session_id,
                state,
            )
            self._activate_session(
                resolved_project_root,
                session_id,
                new_state,
                sync_to_context_manager=sync_to_context_manager,
            )
            
            if self.logger:
                self.logger.info(
                    f"已切换到会话: {session_id}, 消息数: {len(new_state.get('messages', []))}"
                )
            
            # 发布事件
            self._publish_session_changed_event(
                action="switch",
                previous_session_id=previous_session_id
            )
            
            return new_state
    
    def _sync_state_to_context_manager(self, state: Dict[str, Any]) -> None:
        """
        同步状态到 ContextManager
        
        确保 ContextManager._internal_state 与当前会话状态一致。
        
        Args:
            state: 要同步的状态
        """
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_CONTEXT_MANAGER
            
            context_manager = ServiceLocator.get_optional(SVC_CONTEXT_MANAGER)
            if context_manager:
                context_manager.sync_state(state)
                if self.logger:
                    self.logger.debug("状态已同步到 ContextManager")
        except Exception as e:
            if self.logger:
                self.logger.warning(f"同步状态到 ContextManager 失败: {e}")
    
    def save_current_session(
        self,
        state: Optional[Dict[str, Any]] = None,
        project_root: Optional[str] = None,
    ) -> bool:
        """
        保存当前会话
        
        执行步骤：
        1. 从 GraphState 提取消息
        2. 通过 context_service 保存到文件
        3. 更新会话索引
        4. 重置 _is_dirty 标志
        
        Args:
            state: 当前 GraphState（字典形式）
            project_root: 项目根目录路径
            
        Returns:
            bool: 是否保存成功
        """
        from domain.services import context_service
        from domain.llm.message_helpers import (
            messages_to_dicts,
            is_human_message,
        )
        from domain.llm.working_context_builder import (
            WORKING_CONTEXT_COMPRESSED_COUNT_KEY,
            WORKING_CONTEXT_KEEP_RECENT_KEY,
            WORKING_CONTEXT_SUMMARY_KEY,
        )
        
        with self._lock:
            if not self._current_session_id:
                if self.logger:
                    self.logger.warning("无当前会话，无法保存")
                return False
            
            resolved_project_root = self._resolve_project_root(project_root)
            if not resolved_project_root:
                if self.logger:
                    self.logger.warning("无项目路径，无法保存会话")
                return False

            current_state = state if state is not None else self._get_current_state()
            
            # 提取消息
            messages = self.message_store.get_messages(current_state)
            messages_data = messages_to_dicts(messages)
            
            # 获取首条用户消息作为预览
            preview = ""
            for msg in messages:
                if is_human_message(msg):
                    content = msg.content if isinstance(msg.content, str) else ""
                    preview = content[:50]
                    break
            
            # 保存消息到文件
            context_service.save_messages(
                resolved_project_root,
                self._current_session_id,
                messages_data
            )
            
            # 更新会话索引
            context_service.update_session_index(
                resolved_project_root,
                self._current_session_id,
                {
                    "updated_at": datetime.now().isoformat(),
                    "message_count": len(messages),
                    "preview": preview,
                    WORKING_CONTEXT_SUMMARY_KEY: current_state.get(WORKING_CONTEXT_SUMMARY_KEY, ""),
                    WORKING_CONTEXT_COMPRESSED_COUNT_KEY: current_state.get(WORKING_CONTEXT_COMPRESSED_COUNT_KEY, 0),
                    WORKING_CONTEXT_KEEP_RECENT_KEY: current_state.get(WORKING_CONTEXT_KEEP_RECENT_KEY, 0),
                    "circuit_file_path": current_state.get("circuit_file_path", ""),
                    "sim_result_path": current_state.get("sim_result_path", ""),
                    "design_goals_path": current_state.get("design_goals_path", ".circuit_ai/design_goals.json"),
                    "last_metrics": current_state.get("last_metrics", {}),
                    "error_context": current_state.get("error_context", ""),
                }
            )
            
            self._project_root = resolved_project_root

            # 重置脏标志
            self._is_dirty = False
            
            if self.logger:
                self.logger.debug(f"会话已保存: {self._current_session_id}")
            
            return True

    def delete_session(
        self,
        project_root: Optional[str],
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
            resolved_project_root = self._resolve_project_root(project_root)
            if not resolved_project_root or not session_id:
                return False

            previous_session_id = session_id
            deleting_current = session_id == self._current_session_id

            # 删除会话文件
            success = context_service.delete_session(resolved_project_root, session_id)
            
            if success:
                # 从索引中移除
                context_service.remove_from_session_index(resolved_project_root, session_id)
                
                if self.logger:
                    self.logger.info(f"会话已删除: {session_id}")
                
                if deleting_current:
                    remaining_sessions = context_service.list_sessions(
                        resolved_project_root,
                        limit=None,
                    )

                    if remaining_sessions:
                        fallback_session_id = remaining_sessions[0].get("session_id", "")
                        if fallback_session_id:
                            fallback_state = self._build_session_state(
                                resolved_project_root,
                                fallback_session_id,
                            )
                            self._activate_session(
                                resolved_project_root,
                                fallback_session_id,
                                fallback_state,
                                sync_to_context_manager=True,
                            )
                        else:
                            self._create_empty_session(resolved_project_root)
                            self._sync_state_to_context_manager(self._build_empty_conversation_state())
                    else:
                        self._create_empty_session(resolved_project_root)
                        self._sync_state_to_context_manager(self._build_empty_conversation_state())
                else:
                    self._project_root = resolved_project_root
                
                # 发布事件
                self._publish_session_changed_event(
                    action="delete",
                    previous_session_id=previous_session_id,
                )
            
            return success

    def rename_session(
        self,
        session_id: str,
        new_name: str,
        project_root: Optional[str] = None,
    ) -> bool:
        """
        重命名会话
        
        Args:
            session_id: 会话 ID
            new_name: 新名称
            project_root: 项目根目录路径
            
        Returns:
            bool: 是否重命名成功
        """
        from domain.services import context_service
        
        with self._lock:
            resolved_project_root = self._resolve_project_root(project_root)
            if not resolved_project_root or not session_id or not new_name:
                return False

            # 更新会话索引中的名称
            success = context_service.update_session_index(
                resolved_project_root,
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
    
    def get_current_session_name(self) -> str:
        """
        获取当前会话名称
        
        Returns:
            str: 当前会话名称，无会话时返回空字符串
        """
        with self._lock:
            if not self._current_session_id or not self._project_root:
                return ""
            
            from domain.services import context_service
            
            metadata = context_service.get_session_metadata(
                self._project_root, self._current_session_id
            )
            
            return metadata.get("name", self._current_session_id) if metadata else ""

    def get_project_root(self) -> str:
        with self._lock:
            return self._project_root

    def get_all_sessions(self, project_root: Optional[str] = None) -> List[SessionInfo]:
        """
        获取所有会话列表
        
        Args:
            project_root: 项目根目录路径
            
        Returns:
            List[SessionInfo]: 会话信息列表，按更新时间倒序
        """
        from domain.services import context_service

        resolved_project_root = self._resolve_project_root(project_root)
        if not resolved_project_root:
            return []
        
        sessions_data = context_service.list_sessions(resolved_project_root, limit=None)
        live_snapshot = self._build_runtime_session_snapshot(resolved_project_root)
        if live_snapshot:
            snapshot_session_id = live_snapshot.get("session_id", "")
            replaced = False
            for idx, data in enumerate(sessions_data):
                if data.get("session_id", "") == snapshot_session_id:
                    merged = dict(data)
                    merged.update(live_snapshot)
                    sessions_data[idx] = merged
                    replaced = True
                    break
            if not replaced:
                sessions_data.insert(0, live_snapshot)
        
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

    def get_session_messages(
        self,
        session_id: str,
        project_root: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取指定会话的消息列表，由 SessionStateManager 统一协调。"""
        from domain.services import context_service
        from domain.llm.message_helpers import messages_to_dicts

        resolved_project_root = self._resolve_project_root(project_root)
        if not resolved_project_root or not session_id:
            return []

        if (
            session_id == self._current_session_id
            and resolved_project_root == self._project_root
        ):
            current_state = self._get_current_state()
            messages = self.message_store.get_messages(current_state)
            return messages_to_dicts(messages)

        return context_service.load_messages(resolved_project_root, session_id)

    def reload_current_session(
        self,
        project_root: Optional[str] = None,
        *,
        action: str = "reload",
    ) -> Dict[str, Any]:
        with self._lock:
            resolved_project_root = self._resolve_project_root(project_root)
            if not resolved_project_root:
                raise ValueError("No project root available")
            if not self._current_session_id:
                raise ValueError("No current session to reload")

            session_id = self._current_session_id
            new_state = self._build_session_state(
                resolved_project_root,
                session_id,
            )
            self._activate_session(
                resolved_project_root,
                session_id,
                new_state,
                sync_to_context_manager=True,
            )
            self._publish_session_changed_event(
                action=action,
                previous_session_id=session_id,
            )
            return new_state

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
        2. 若存在当前会话，加载会话消息并同步到 ContextManager
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
            previous_project_root = self._project_root
            if (
                previous_project_root
                and previous_project_root != project_root
                and self._current_session_id
                and self._is_dirty
            ):
                self.save_current_session(
                    project_root=previous_project_root,
                )

            resolved_project_root = self._resolve_project_root(project_root)
            if not resolved_project_root:
                raise ValueError("No project root available")

            if previous_project_root and previous_project_root != resolved_project_root:
                self._current_session_id = ""
                self._is_dirty = False

            self._project_root = resolved_project_root
            
            # 获取上次使用的会话 ID
            last_session_id = context_service.get_current_session_id(resolved_project_root)
            
            if last_session_id and context_service.session_exists(resolved_project_root, last_session_id):
                new_state = self.switch_session(
                    project_root=resolved_project_root,
                    session_id=last_session_id,
                    state=state,
                    sync_to_context_manager=True,
                )
                
                if self.logger:
                    self.logger.info(
                        f"会话已恢复: {last_session_id}, 消息数: {len(new_state.get('messages', []))}"
                    )
                
                return new_state

            if last_session_id:
                context_service.remove_from_session_index(resolved_project_root, last_session_id)
            
            # 无可恢复的会话，创建新会话
            session_id = self.create_session(resolved_project_root)
            
            if self.logger:
                self.logger.info(f"创建新会话: {session_id}")
            
            return self._get_current_state()
    
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

    def _resolve_project_root(self, project_root: Optional[str]) -> str:
        if project_root:
            return project_root
        if self._project_root:
            return self._project_root

        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_SESSION_STATE

            session_state = ServiceLocator.get_optional(SVC_SESSION_STATE)
            if session_state and session_state.project_root:
                return session_state.project_root
        except Exception:
            pass

        return ""

    def _get_current_state(self) -> Dict[str, Any]:
        if self.context_manager:
            try:
                return self.context_manager.get_current_state() or {}
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"获取当前状态失败: {e}")
        return {}

    def _build_runtime_session_snapshot(self, project_root: str) -> Optional[Dict[str, Any]]:
        if project_root != self._project_root or not self._current_session_id:
            return None

        from domain.services import context_service
        from domain.llm.message_helpers import is_human_message

        current_state = self._get_current_state()
        messages = self.message_store.get_messages(current_state)
        metadata = context_service.get_session_metadata(
            project_root,
            self._current_session_id,
        ) or {}

        preview = ""
        for msg in messages:
            if is_human_message(msg):
                content = msg.content if isinstance(msg.content, str) else ""
                preview = content[:50]
                break

        updated_at = metadata.get("updated_at", "")
        if self._is_dirty:
            updated_at = datetime.now().isoformat()

        return {
            "session_id": self._current_session_id,
            "name": metadata.get("name", self._current_session_id),
            "created_at": metadata.get("created_at", ""),
            "updated_at": updated_at,
            "message_count": len(messages),
            "preview": preview,
            "has_partial_response": metadata.get("has_partial_response", False),
        }

    def _build_session_state(
        self,
        project_root: str,
        session_id: str,
        state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from domain.services import context_service
        from domain.llm.message_helpers import dicts_to_messages
        from domain.llm.working_context_builder import (
            WORKING_CONTEXT_COMPRESSED_COUNT_KEY,
            WORKING_CONTEXT_KEEP_RECENT_KEY,
            WORKING_CONTEXT_SUMMARY_KEY,
        )

        messages_data = context_service.load_messages(project_root, session_id)
        messages = dicts_to_messages(messages_data) if messages_data else []

        base_state = self._build_clean_state_base()
        base_state["messages"] = messages

        metadata = context_service.get_session_metadata(project_root, session_id)
        if metadata:
            base_state[WORKING_CONTEXT_SUMMARY_KEY] = metadata.get(WORKING_CONTEXT_SUMMARY_KEY, "")
            base_state[WORKING_CONTEXT_COMPRESSED_COUNT_KEY] = metadata.get(WORKING_CONTEXT_COMPRESSED_COUNT_KEY, 0)
            base_state[WORKING_CONTEXT_KEEP_RECENT_KEY] = metadata.get(WORKING_CONTEXT_KEEP_RECENT_KEY, 0)
            base_state["circuit_file_path"] = metadata.get("circuit_file_path", "")
            base_state["sim_result_path"] = metadata.get("sim_result_path", "")
            base_state["design_goals_path"] = metadata.get("design_goals_path", ".circuit_ai/design_goals.json")
            base_state["last_metrics"] = metadata.get("last_metrics", {})
            base_state["error_context"] = metadata.get("error_context", "")
        else:
            base_state[WORKING_CONTEXT_SUMMARY_KEY] = ""
            base_state[WORKING_CONTEXT_COMPRESSED_COUNT_KEY] = 0
            base_state[WORKING_CONTEXT_KEEP_RECENT_KEY] = 0
            base_state["circuit_file_path"] = ""
            base_state["sim_result_path"] = ""
            base_state["design_goals_path"] = ".circuit_ai/design_goals.json"
            base_state["last_metrics"] = {}
            base_state["error_context"] = ""

        base_state["session_id"] = session_id
        base_state["project_root"] = project_root

        return base_state

    def _build_empty_conversation_state(
        self,
        state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from domain.llm.working_context_builder import (
            WORKING_CONTEXT_COMPRESSED_COUNT_KEY,
            WORKING_CONTEXT_KEEP_RECENT_KEY,
            WORKING_CONTEXT_SUMMARY_KEY,
        )

        base_state = self._build_clean_state_base()
        base_state["messages"] = []
        base_state[WORKING_CONTEXT_SUMMARY_KEY] = ""
        base_state[WORKING_CONTEXT_COMPRESSED_COUNT_KEY] = 0
        base_state[WORKING_CONTEXT_KEEP_RECENT_KEY] = 0
        base_state["circuit_file_path"] = ""
        base_state["sim_result_path"] = ""
        base_state["design_goals_path"] = ".circuit_ai/design_goals.json"
        base_state["last_metrics"] = {}
        base_state["error_context"] = ""
        return base_state

    def _build_clean_state_base(self) -> Dict[str, Any]:
        try:
            from application.graph.state import GraphState

            return GraphState().to_dict()
        except Exception:
            return {
                "messages": [],
                WORKING_CONTEXT_SUMMARY_KEY: "",
                WORKING_CONTEXT_COMPRESSED_COUNT_KEY: 0,
                WORKING_CONTEXT_KEEP_RECENT_KEY: 0,
                "circuit_file_path": "",
                "sim_result_path": "",
                "design_goals_path": ".circuit_ai/design_goals.json",
                "last_metrics": {},
                "error_context": "",
            }

    def _activate_session(
        self,
        project_root: str,
        session_id: str,
        state: Dict[str, Any],
        sync_to_context_manager: bool = True,
    ) -> None:
        from domain.services import context_service

        context_service.set_current_session_id(project_root, session_id)
        self._current_session_id = session_id
        self._project_root = project_root
        self._is_dirty = False

        if sync_to_context_manager:
            self._sync_state_to_context_manager(state)

    def _create_empty_session(self, project_root: str) -> tuple[str, str]:
        from domain.services import context_service

        session_id = self._generate_session_id()
        session_name = self._generate_session_name()

        context_service.save_messages(project_root, session_id, [])
        context_service.update_session_index(
            project_root,
            session_id,
            {
                "session_id": session_id,
                "name": session_name,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "message_count": 0,
            },
            set_current=True,
        )

        self._current_session_id = session_id
        self._project_root = project_root
        self._is_dirty = False

        return session_id, session_name
    
    def _publish_session_changed_event(
        self,
        action: str,
        previous_session_id: str = ""
    ) -> None:
        """
        发布会话变更事件
        
        Args:
            action: 触发动作（"new", "switch", "delete", "rename"）
            previous_session_id: 之前的会话 ID
        """
        if self.event_bus:
            try:
                from shared.event_types import EVENT_SESSION_CHANGED
                current_state = self._get_current_state()
                
                self.event_bus.publish(EVENT_SESSION_CHANGED, {
                    "session_id": self._current_session_id,
                    "session_name": self.get_current_session_name(),
                    "action": action,
                    "previous_session_id": previous_session_id,
                    "project_root": self._project_root,
                    "sim_result_path": current_state.get("sim_result_path", ""),
                    "circuit_file_path": current_state.get("circuit_file_path", ""),
                    "design_goals_path": current_state.get("design_goals_path", ".circuit_ai/design_goals.json"),
                })
            except ImportError:
                if self.logger:
                    self.logger.warning("EVENT_SESSION_CHANGED not defined")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SessionStateManager",
    "SessionInfo",
]
