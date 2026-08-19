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
│  - state["messages"]    │  │  - 会话文件 CRUD             │
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
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.llm.working_context_builder import (
    WORKING_CONTEXT_COMPRESSED_COUNT_KEY,
    WORKING_CONTEXT_KEEP_RECENT_KEY,
    WORKING_CONTEXT_SUMMARY_KEY,
)

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
        self._events_subscribed: bool = False
        
        # 延迟获取的服务
        self._message_store = None
        self._context_manager = None
        self._event_bus = None
        self._logger = None
        self._subscribe_events()
    
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
    # 事件订阅
    # ============================================================
    
    def _subscribe_events(self) -> None:
        if self._events_subscribed or self.event_bus is None:
            return
        try:
            from shared.event_types import EVENT_STATE_PROJECT_OPENED, EVENT_STATE_PROJECT_CLOSED

            self.event_bus.subscribe(EVENT_STATE_PROJECT_OPENED, self._on_project_opened)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_CLOSED, self._on_project_closed)
            self._events_subscribed = True
        except Exception as e:
            if self.logger:
                self.logger.warning(f"订阅项目事件失败: {e}")

    def _unsubscribe_events(self) -> None:
        if not self._events_subscribed or self.event_bus is None:
            return
        try:
            from shared.event_types import EVENT_STATE_PROJECT_OPENED, EVENT_STATE_PROJECT_CLOSED

            self.event_bus.unsubscribe(EVENT_STATE_PROJECT_OPENED, self._on_project_opened)
            self.event_bus.unsubscribe(EVENT_STATE_PROJECT_CLOSED, self._on_project_closed)
        except Exception:
            pass
        self._events_subscribed = False

    def _on_project_opened(self, event_data: Dict[str, Any]) -> None:
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else {}
        project_root = str(data.get("path", "") or "") if isinstance(data, dict) else ""
        if not project_root:
            return
        try:
            self.ensure_active_session(project_root=project_root)
        except Exception as e:
            if self.logger:
                self.logger.error(f"项目打开后激活会话失败: {e}")

    def _on_project_closed(self, event_data: Dict[str, Any]) -> None:
        del event_data
        with self._lock:
            previous_session_id = self._current_session_id
            previous_project_root = self._project_root
            should_persist = bool(previous_session_id and previous_project_root and self._is_dirty)

        if should_persist:
            try:
                if not self.save_current_session(project_root=previous_project_root):
                    # ProjectService performs the authoritative preflight
                    # before publishing the close event.  This handler is only
                    # a last-resort safety net for legacy/direct publishers. A
                    # failed fallback must retain the dirty in-memory state so
                    # it can still be recovered or retried explicitly.
                    if self.logger:
                        self.logger.error(
                            "项目关闭事件到达时会话仍未能持久化；保留 dirty 会话状态"
                        )
                    return
            except Exception as e:
                if self.logger:
                    self.logger.error(f"项目关闭时保存当前会话失败，保留 dirty 状态: {e}")
                return

        with self._lock:
            self._current_session_id = ""
            self._project_root = ""
            self._is_dirty = False

        self._sync_state_to_context_manager(self._build_empty_conversation_state())
        self._publish_session_changed_event(
            action="project_closed",
            previous_session_id=previous_session_id,
        )

    # ============================================================
    # 会话生命周期方法
    # ============================================================

    def ensure_active_session(
        self,
        project_root: Optional[str] = None,
        state: Optional[Dict[str, Any]] = None,
        sync_to_context_manager: bool = True,
    ) -> Dict[str, Any]:
        from domain.services import context_service

        with self._lock:
            resolved_project_root = self._resolve_project_root(project_root)
            if not resolved_project_root:
                raise ValueError("No project root available")

            current_state = state if state is not None else self._get_current_state()
            normalized_runtime_project_root = self._normalize_project_root(
                current_state.get("project_root", "") if isinstance(current_state, dict) else ""
            )
            runtime_session_id = str(
                current_state.get("session_id", "") if isinstance(current_state, dict) else ""
            )

            if (
                self._current_session_id
                and self._normalize_project_root(self._project_root) == resolved_project_root
                and context_service.session_exists(resolved_project_root, self._current_session_id)
            ):
                needs_activation = (
                    sync_to_context_manager
                    and (
                        runtime_session_id != self._current_session_id
                        or normalized_runtime_project_root != resolved_project_root
                    )
                )
                if needs_activation:
                    if isinstance(current_state, dict) and current_state:
                        current_state = self._attach_session_identity(
                            current_state,
                            resolved_project_root,
                            self._current_session_id,
                        )
                    else:
                        current_state = self._build_session_state(
                            resolved_project_root,
                            self._current_session_id,
                            current_state,
                        )
                    self._activate_session(
                        resolved_project_root,
                        self._current_session_id,
                        current_state,
                        sync_to_context_manager=True,
                    )
                else:
                    if not context_service.set_current_session_id(
                        resolved_project_root,
                        self._current_session_id,
                    ):
                        raise IOError("Failed to persist the active session identity")
                    self._project_root = resolved_project_root
                    if sync_to_context_manager:
                        self._sync_state_to_context_manager(current_state)
                return current_state

            last_session_id = context_service.get_current_session_id(resolved_project_root)

        if last_session_id and context_service.session_exists(resolved_project_root, last_session_id):
            return self.switch_session(
                project_root=resolved_project_root,
                session_id=last_session_id,
                state=state,
                sync_to_context_manager=sync_to_context_manager,
            )

        if last_session_id:
            if not context_service.remove_from_session_index(
                resolved_project_root,
                last_session_id,
            ):
                raise IOError("Failed to remove a stale current session from the index")

        session_id = self.create_session(resolved_project_root)
        return self._build_empty_session_state(resolved_project_root, session_id)

    def create_session(
        self,
        project_root: Optional[str] = None,
    ) -> str:
        with self._lock:
            resolved_project_root = self._resolve_project_root(project_root)
            if not resolved_project_root:
                raise ValueError("No project root available")

            if self._is_dirty and self._current_session_id:
                active_project_root = self._project_root or resolved_project_root
                if not self.save_current_session(project_root=active_project_root):
                    raise IOError("Failed to persist current session before creating a new one")

            previous_session_id = self._current_session_id
            session_id, session_name = self._create_empty_session(resolved_project_root)
            
            if self.logger:
                self.logger.info(f"新会话已创建: {session_id}, 名称: {session_name}")
            
            self._sync_state_to_context_manager(
                self._build_empty_session_state(resolved_project_root, session_id)
            )
            
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
                if self._is_dirty and not self.save_current_session(
                        state=current_state,
                        project_root=resolved_project_root,
                    ):
                    raise IOError("Failed to persist current session before synchronizing it")
                if sync_to_context_manager:
                    self._sync_state_to_context_manager(current_state)
                return current_state

            # 保存当前会话（如果有未保存的更改）
            if self._is_dirty and self._current_session_id and self._current_session_id != session_id:
                active_project_root = self._project_root or resolved_project_root
                if not self.save_current_session(
                    state=state,
                    project_root=active_project_root,
                ):
                    raise IOError("Failed to persist current session before switching")
            
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
        *,
        expected_session_id: Optional[str] = None,
    ) -> bool:
        """
        保存当前会话
        
        执行步骤：
        1. 从当前会话状态提取消息
        2. 通过 context_service 保存到文件
        3. 更新会话索引
        4. 重置 _is_dirty 标志
        
        Args:
            state: 当前会话状态字典
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

            if expected_session_id and self._current_session_id != expected_session_id:
                if self.logger:
                    self.logger.warning(
                        "拒绝将候选状态保存到已切换的会话: expected=%s, current=%s",
                        expected_session_id,
                        self._current_session_id,
                    )
                return False
            
            resolved_project_root = self._resolve_project_root(project_root)
            if not resolved_project_root:
                if self.logger:
                    self.logger.warning("无项目路径，无法保存会话")
                return False
            if (
                expected_session_id
                and self._project_root
                and self._normalize_project_root(self._project_root)
                != self._normalize_project_root(resolved_project_root)
            ):
                if self.logger:
                    self.logger.warning("拒绝跨项目保存压缩候选状态")
                return False

            current_state = state if state is not None else self._get_current_state()
            
            # 提取消息
            messages = self.message_store.get_messages(current_state)
            messages_data = messages_to_dicts(messages)
            
            # 获取预览文本
            preview = self._build_session_preview(messages)

            # Fail closed before either durable file is replaced.  Existing
            # corruption is evidence that needs explicit recovery; treating it
            # as an empty session/index would silently destroy that evidence and
            # may drop unrelated session-index entries.
            had_session_file = False
            previous_messages_data: List[Dict[str, Any]] = []
            try:
                had_session_file = context_service.session_exists(
                    resolved_project_root,
                    self._current_session_id,
                )
                if had_session_file:
                    previous_messages_data = context_service.load_messages(
                        resolved_project_root,
                        self._current_session_id,
                    )
                context_service.get_session_metadata(
                    resolved_project_root,
                    self._current_session_id,
                )
            except Exception as exc:
                self._is_dirty = True
                if self.logger:
                    self.logger.error(
                        f"会话存储预检失败，拒绝覆盖并保留 dirty 状态: {exc}"
                    )
                return False

            session_file_replaced = False

            def restore_previous_session_file() -> None:
                """Best-effort rollback when the paired index commit fails."""
                try:
                    if had_session_file:
                        context_service.save_messages(
                            resolved_project_root,
                            self._current_session_id,
                            previous_messages_data,
                        )
                    else:
                        session_path = (
                            Path(resolved_project_root)
                            / context_service.CONVERSATIONS_DIR
                            / f"{self._current_session_id}.json"
                        )
                        session_path.unlink(missing_ok=True)
                except Exception as rollback_exc:
                    if self.logger:
                        self.logger.critical(
                            "会话索引提交失败后无法恢复原会话文件: "
                            f"{rollback_exc}"
                        )

            try:
                # 保存消息到文件
                context_service.save_messages(
                    resolved_project_root,
                    self._current_session_id,
                    messages_data
                )
                session_file_replaced = True

                # A session save is successful only when both the session file
                # and its index metadata are durable.  Keep dirty on failure so
                # a later retry cannot be skipped.
                index_saved = context_service.update_session_index(
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
                        "last_metrics": current_state.get("last_metrics", {}),
                        "error_context": current_state.get("error_context", ""),
                    }
                )
                if not index_saved:
                    restore_previous_session_file()
                    self._is_dirty = True
                    if self.logger:
                        self.logger.error("会话索引保存失败，保留 dirty 状态")
                    return False
            except Exception as exc:
                if session_file_replaced:
                    restore_previous_session_file()
                self._is_dirty = True
                if self.logger:
                    self.logger.error(f"保存会话失败，保留 dirty 状态: {exc}")
                return False
            
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
                if not context_service.remove_from_session_index(
                    resolved_project_root,
                    session_id,
                ):
                    # The durable file has already been removed, but the index
                    # is still authoritative for activation.  Report failure
                    # and stop before selecting a fallback from that stale
                    # index; claiming success here can reactivate the deleted
                    # current session.
                    if self.logger:
                        self.logger.error(
                            f"会话文件已删除但索引更新失败，停止后续激活: {session_id}"
                        )
                    return False
                
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
                            new_session_id, _ = self._create_empty_session(resolved_project_root)
                            self._sync_state_to_context_manager(
                                self._build_empty_session_state(resolved_project_root, new_session_id)
                            )
                    else:
                        new_session_id, _ = self._create_empty_session(resolved_project_root)
                        self._sync_state_to_context_manager(
                            self._build_empty_session_state(resolved_project_root, new_session_id)
                        )
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

    def ensure_current_session_persisted(
        self,
        project_root: Optional[str] = None,
    ) -> bool:
        with self._lock:
            if not self._current_session_id:
                # A transition preflight has nothing to persist when no
                # conversation is active.
                return True

            resolved_project_root = self._resolve_project_root(project_root)
            if not resolved_project_root:
                return False
            if (
                self._project_root
                and self._normalize_project_root(self._project_root)
                != self._normalize_project_root(resolved_project_root)
            ):
                # Never save a current-session candidate into a different
                # project's conversations directory.
                return False

            from domain.services import context_service

            try:
                session_file_exists = context_service.session_exists(
                    resolved_project_root,
                    self._current_session_id,
                )
                if session_file_exists:
                    # Existing-but-corrupt is not equivalent to persisted.
                    context_service.load_messages(
                        resolved_project_root,
                        self._current_session_id,
                    )
                metadata = context_service.get_session_metadata(
                    resolved_project_root,
                    self._current_session_id,
                )
                indexed_current_id = context_service.get_current_session_id(
                    resolved_project_root
                )
            except Exception as exc:
                self._is_dirty = True
                if self.logger:
                    self.logger.error(f"会话持久化预检失败: {exc}")
                return False

            if self._is_dirty or not session_file_exists or metadata is None:
                if not self.save_current_session(
                    project_root=resolved_project_root,
                    expected_session_id=self._current_session_id,
                ):
                    return False

            if indexed_current_id != self._current_session_id:
                if not context_service.set_current_session_id(
                    resolved_project_root,
                    self._current_session_id,
                ):
                    self._is_dirty = True
                    return False

            self._project_root = resolved_project_root
            return True

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
        sessions_data = [
            data
            for data in sessions_data
            if data.get("session_id", "")
            and context_service.session_exists(
                resolved_project_root,
                data.get("session_id", ""),
            )
        ]

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

        sessions_data.sort(
            key=lambda data: data.get("updated_at", ""),
            reverse=True,
        )
        
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
            and resolved_project_root == self._normalize_project_root(self._project_root)
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
            state: 初始会话状态字典
            
        Returns:
            Dict: 更新后的会话状态字典
        """
        return self.ensure_active_session(
            project_root=project_root,
            state=state,
            sync_to_context_manager=True,
        )
    
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
        
        格式：YYYYMMDD_HHMMSS_microseconds_uuid
        
        Returns:
            str: 会话 ID
        """
        return (
            datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            + f"_{uuid.uuid4().hex[:8]}"
        )
    
    def _generate_session_name(self) -> str:
        """
        生成会话名称
        
        格式：Chat YYYY-MM-DD HH:mm
        
        Returns:
            str: 会话名称
        """
        return f"Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    def _normalize_project_root(self, project_root: Optional[str]) -> str:
        if not project_root:
            return ""

        try:
            resolved = Path(project_root).expanduser().resolve()
        except Exception:
            try:
                resolved = Path(project_root).expanduser()
            except Exception:
                return str(project_root).strip()

        return os.path.normcase(os.path.normpath(str(resolved)))

    def _build_session_preview(self, messages: List[Any]) -> str:
        from domain.llm.message_helpers import is_human_message

        for msg in reversed(messages):
            if is_human_message(msg):
                content = msg.content if isinstance(msg.content, str) else ""
                if content:
                    return content[:50]

        for msg in reversed(messages):
            content = msg.content if isinstance(getattr(msg, "content", ""), str) else ""
            if content:
                return content[:50]

        return ""

    def _resolve_project_root(self, project_root: Optional[str]) -> str:
        if project_root:
            return self._normalize_project_root(project_root)
        if self._project_root:
            return self._normalize_project_root(self._project_root)

        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_SESSION_STATE

            session_state = ServiceLocator.get_optional(SVC_SESSION_STATE)
            if session_state and session_state.project_root:
                return self._normalize_project_root(session_state.project_root)
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
        normalized_project_root = self._normalize_project_root(project_root)
        if (
            normalized_project_root != self._normalize_project_root(self._project_root)
            or not self._current_session_id
        ):
            return None

        from domain.services import context_service

        current_state = self._get_current_state()
        messages = self.message_store.get_messages(current_state)
        metadata = context_service.get_session_metadata(
            normalized_project_root,
            self._current_session_id,
        ) or {}

        preview = self._build_session_preview(messages)

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
            base_state["last_metrics"] = metadata.get("last_metrics", {})
            base_state["error_context"] = metadata.get("error_context", "")
        else:
            base_state[WORKING_CONTEXT_SUMMARY_KEY] = ""
            base_state[WORKING_CONTEXT_COMPRESSED_COUNT_KEY] = 0
            base_state[WORKING_CONTEXT_KEEP_RECENT_KEY] = 0
            base_state["circuit_file_path"] = ""
            base_state["sim_result_path"] = ""
            base_state["last_metrics"] = {}
            base_state["error_context"] = ""

        base_state["session_id"] = session_id
        base_state["project_root"] = project_root

        return base_state

    def _build_empty_conversation_state(
        self,
    ) -> Dict[str, Any]:
        return self._build_clean_state_base()

    def _build_empty_session_state(self, project_root: str, session_id: str) -> Dict[str, Any]:
        base_state = self._build_empty_conversation_state()
        base_state["session_id"] = session_id
        base_state["project_root"] = project_root
        return base_state

    def _attach_session_identity(
        self,
        state: Dict[str, Any],
        project_root: str,
        session_id: str,
    ) -> Dict[str, Any]:
        updated_state = dict(state)
        updated_state["session_id"] = session_id
        updated_state["project_root"] = project_root
        return updated_state

    def _build_clean_state_base(self) -> Dict[str, Any]:
        """Build only fields owned and persisted by the conversation runtime."""
        return {
            "messages": [],
            WORKING_CONTEXT_SUMMARY_KEY: "",
            WORKING_CONTEXT_COMPRESSED_COUNT_KEY: 0,
            WORKING_CONTEXT_KEEP_RECENT_KEY: 0,
            "circuit_file_path": "",
            "sim_result_path": "",
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

        if not context_service.set_current_session_id(project_root, session_id):
            raise IOError(f"Failed to persist active session id: {session_id}")
        self._current_session_id = session_id
        self._project_root = project_root
        self._is_dirty = False

        if sync_to_context_manager:
            self._sync_state_to_context_manager(state)

    def _create_empty_session(self, project_root: str) -> tuple[str, str]:
        from domain.services import context_service

        # The UUID suffix makes collisions exceedingly unlikely, while the
        # explicit loop is the authoritative last line of defence against a
        # clock/UUID fault or a test/injected ID generator.
        session_id = ""
        for _attempt in range(64):
            candidate = self._generate_session_id()
            if not context_service.session_exists(project_root, candidate):
                metadata = context_service.get_session_metadata(project_root, candidate)
                if metadata is None:
                    session_id = candidate
                    break
        if not session_id:
            raise IOError("Unable to allocate a unique session id")
        session_name = self._generate_session_name()

        context_service.save_messages(project_root, session_id, [])
        index_saved = context_service.update_session_index(
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
        if not index_saved:
            try:
                context_service.delete_session(project_root, session_id)
            except Exception:
                pass
            raise IOError("Failed to persist new session index")

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
                    "circuit_file_path": current_state.get("circuit_file_path", ""),
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
