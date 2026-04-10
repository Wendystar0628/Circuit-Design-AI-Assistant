# Conversation Panel - Main Panel Class (Refactored)
"""
对话面板主类（重构版）

职责：
- 协调各子组件（TitleBar、MessageArea、InputArea）
- 通过 ViewModel 获取数据，保持 UI 与数据层解耦
- 处理用户交互和事件转发
- 响应项目切换和语言变更事件

设计目标：
- 参考 Cursor/ChatGPT 风格的现代化对话界面
- 使用组合模式，将职责委托给子组件
- 保持主类精简，仅负责协调

使用示例：
    from presentation.panels.conversation_panel import ConversationPanel
    
    panel = ConversationPanel()
    panel.refresh_display()
"""

import copy
import asyncio
import os
from pathlib import Path
from typing import Any, Dict, Optional

from PyQt6.QtCore import pyqtSignal, pyqtSlot, QUrl, Qt
from PyQt6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QFileDialog,
)

from domain.rag.file_extractor import resolve_attachment_type
from presentation.panels.conversation import (
    ConversationViewModel,
)
from presentation.panels.conversation.conversation_attachment_support import (
    ConversationAttachmentError,
    ConversationAttachmentSupport,
)
from presentation.panels.conversation.conversation_session_support import (
    ConversationSessionSupport,
)
from presentation.panels.conversation.conversation_state_serializer import ConversationStateSerializer
from presentation.panels.conversation.react_conversation_host import ReactConversationHost

# ============================================================
# 常量定义
# ============================================================

PANEL_BACKGROUND = "#ffffff"
ACTION_MODE_SEND = "send"
ACTION_MODE_STOP = "stop"
ACTION_MODE_STOPPING = "stopping"
ACTION_MODE_ROLLBACKING = "rollbacking"


# ============================================================
# ConversationPanel 类
# ============================================================

class ConversationPanel(QWidget):
    """
    对话面板主类（重构版）
    
    协调各子组件，管理面板整体布局，通过 ViewModel 获取数据。
    """
    
    # 信号定义
    compress_requested = pyqtSignal()              # 用户请求压缩上下文
    file_clicked = pyqtSignal(str)                 # 用户点击文件名 (file_path)
    
    def __init__(self, parent: Optional[QWidget] = None):
        """初始化对话面板"""
        super().__init__(parent)
        
        # 延迟获取的服务
        self._view_model = None
        self._event_bus = None
        self._i18n = None
        self._logger = None
        self._rag_manager = None
        self._pending_workspace_edit_service = None
        self._session_support = ConversationSessionSupport()
        self._send_in_progress = False
        self._rollback_in_progress = False
        self._state_serializer = ConversationStateSerializer()
        self._composer_action_mode = ACTION_MODE_SEND
        self._composer_action_status = ""
        self._draft_clear_nonce = 0
        self._history_overlay_state = self._create_history_overlay_state()
        self._rollback_overlay_state = self._create_rollback_overlay_state()
        self._confirm_dialog_state = self._create_confirm_dialog_state()
        self._notice_dialog_state = self._create_notice_dialog_state()
        self._active_surface = "conversation"
        self._rag_progress_state = self._create_rag_progress_state()
        self._rag_info_state = self._create_rag_info_state()
        self._rag_search_state = self._create_rag_search_state()
        self._authoritative_frontend_state: Dict[str, Any] = self._state_serializer.serialize_main_state(
            session_id="",
            session_name="",
            messages=[],
            runtime_steps=[],
        )
        
        # 子组件引用
        self._react_host: Optional[ReactConversationHost] = None
        
        # 初始化 UI
        self._setup_ui()
        self._connect_component_signals()
        
        # 启用拖放
        self.setAcceptDrops(True)
    
    # ============================================================
    # 延迟获取服务
    # ============================================================
    
    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("conversation_panel")
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
    def i18n(self):
        """延迟获取国际化管理器"""
        if self._i18n is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_I18N_MANAGER
                self._i18n = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            except Exception:
                pass
        return self._i18n

    @property
    def pending_workspace_edit_service(self):
        if self._pending_workspace_edit_service is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_PENDING_WORKSPACE_EDIT_SERVICE
                self._pending_workspace_edit_service = ServiceLocator.get_optional(
                    SVC_PENDING_WORKSPACE_EDIT_SERVICE
                )
            except Exception:
                pass
        return self._pending_workspace_edit_service

    @property
    def rag_manager(self):
        if self._rag_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_RAG_MANAGER

                self._rag_manager = ServiceLocator.get_optional(SVC_RAG_MANAGER)
            except Exception:
                pass
        return self._rag_manager
    
    @property
    def view_model(self):
        """延迟获取 ViewModel"""
        if self._view_model is None:
            try:
                self._view_model = ConversationViewModel(self)
                self._view_model.initialize()
                self._connect_view_model_signals()
            except Exception as e:
                if self.logger:
                    self.logger.error(f"创建 ViewModel 失败: {e}")
        return self._view_model
    
    def _get_text(self, key: str, default: str = "") -> str:
        """获取国际化文本"""
        if self.i18n:
            return self.i18n.get_text(key, default)
        return default

    def _create_history_export_dialog_state(
        self,
        session_id: str = "",
        export_format: str = "md",
        file_path: str = "",
        *,
        is_open: bool = False,
    ) -> Dict[str, Any]:
        normalized_session_id = str(session_id or "")
        normalized_format = self._session_support.normalize_export_format(export_format) or "md"
        normalized_path = ""
        if normalized_session_id:
            normalized_path = self._session_support.normalize_export_file_path(
                file_path
                or self._session_support.build_default_export_path(
                    normalized_session_id,
                    normalized_format,
                ),
                normalized_format,
            )
        return {
            "is_open": bool(is_open and normalized_session_id),
            "session_id": normalized_session_id,
            "export_format": normalized_format,
            "file_path": normalized_path,
        }

    def _set_history_export_dialog_state(
        self,
        session_id: str = "",
        export_format: str = "md",
        file_path: str = "",
        *,
        is_open: bool = False,
    ) -> None:
        self._history_overlay_state["export_dialog"] = self._create_history_export_dialog_state(
            session_id,
            export_format,
            file_path,
            is_open=is_open,
        )

    def _clear_history_export_dialog_state(self) -> None:
        self._set_history_export_dialog_state()

    def _current_history_export_dialog_state(self) -> Dict[str, Any]:
        dialog_state = self._history_overlay_state.get("export_dialog", {})
        return dialog_state if isinstance(dialog_state, dict) else {}

    def _create_history_overlay_state(self) -> Dict[str, Any]:
        return {
            "is_open": False,
            "is_loading": False,
            "error_message": "",
            "current_session_id": "",
            "selected_session_id": "",
            "sessions": [],
            "preview_messages": [],
            "export_dialog": self._create_history_export_dialog_state(),
        }

    def _create_rollback_overlay_state(self) -> Dict[str, Any]:
        return {
            "is_open": False,
            "is_loading": False,
            "error_message": "",
            "target_message_id": "",
            "preview": None,
        }

    def _create_confirm_dialog_state(self) -> Dict[str, Any]:
        return {
            "is_open": False,
            "kind": "",
            "title": "",
            "message": "",
            "confirm_label": "",
            "cancel_label": "",
            "tone": "normal",
            "payload": {},
        }

    def _create_notice_dialog_state(self) -> Dict[str, Any]:
        return {
            "is_open": False,
            "title": "",
            "message": "",
            "tone": "info",
        }

    def _create_rag_progress_state(self) -> Dict[str, Any]:
        return {
            "is_visible": False,
            "processed": 0,
            "total": 0,
            "current_file": "",
        }

    def _create_rag_info_state(self) -> Dict[str, Any]:
        return {
            "message": "",
            "tone": "neutral",
        }

    def _create_rag_search_state(self) -> Dict[str, Any]:
        return {
            "is_running": False,
            "result_text": "",
        }

    def _reset_rag_runtime_state(self, *, clear_search: bool = True) -> None:
        self._rag_progress_state = self._create_rag_progress_state()
        self._rag_info_state = self._create_rag_info_state()
        if clear_search:
            self._rag_search_state = self._create_rag_search_state()

    def _set_rag_info(self, message: str = "", tone: str = "neutral") -> None:
        self._rag_info_state = {
            "message": str(message or ""),
            "tone": str(tone or "neutral"),
        }

    def _open_confirm_dialog(
        self,
        *,
        kind: str,
        title: str,
        message: str,
        confirm_label: str,
        cancel_label: str,
        tone: str = "normal",
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._confirm_dialog_state = {
            "is_open": True,
            "kind": str(kind or ""),
            "title": str(title or ""),
            "message": str(message or ""),
            "confirm_label": str(confirm_label or ""),
            "cancel_label": str(cancel_label or ""),
            "tone": str(tone or "normal"),
            "payload": dict(payload or {}),
        }
        self._update_authoritative_frontend_state()

    def _close_confirm_dialog(self) -> None:
        self._confirm_dialog_state = self._create_confirm_dialog_state()
        self._update_authoritative_frontend_state()

    def _open_notice_dialog(
        self,
        message: str,
        *,
        title: str = "",
        tone: str = "info",
    ) -> None:
        if not message:
            return
        self._notice_dialog_state = {
            "is_open": True,
            "title": str(title or ""),
            "message": str(message or ""),
            "tone": str(tone or "info"),
        }
        self._update_authoritative_frontend_state()

    def _close_notice_dialog(self) -> None:
        self._notice_dialog_state = self._create_notice_dialog_state()
        self._update_authoritative_frontend_state()

    def _close_history_overlay(self) -> None:
        self._history_overlay_state = self._create_history_overlay_state()
        self._update_authoritative_frontend_state()

    def _close_rollback_overlay(self) -> None:
        self._rollback_overlay_state = self._create_rollback_overlay_state()
        self._update_authoritative_frontend_state()

    def _refresh_history_overlay(self, preferred_session_id: str = "") -> None:
        self._session_support.ensure_current_session_persisted()
        sessions = self._session_support.list_sessions()
        current_session_id = self._session_support.get_current_session_id()
        selected_session_id = str(
            preferred_session_id
            or self._history_overlay_state.get("selected_session_id", "")
            or current_session_id
        )
        available_session_ids = {
            str(getattr(session, "session_id", "") or "") for session in sessions
        }
        if not selected_session_id or selected_session_id not in available_session_ids:
            selected_session_id = current_session_id
        if (not selected_session_id or selected_session_id not in available_session_ids) and sessions:
            selected_session_id = str(getattr(sessions[0], "session_id", "") or "")
        preview_messages = (
            self._session_support.get_session_messages(selected_session_id)
            if selected_session_id
            else []
        )
        self._history_overlay_state = {
            "is_open": True,
            "is_loading": False,
            "error_message": "",
            "current_session_id": current_session_id,
            "selected_session_id": selected_session_id,
            "sessions": sessions,
            "preview_messages": preview_messages,
            "export_dialog": self._create_history_export_dialog_state(),
        }
        self._update_authoritative_frontend_state()


    # ============================================================
    # UI 初始化
    # ============================================================
    
    def _setup_ui(self) -> None:
        """设置 UI 布局"""
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.setStyleSheet(f"background-color: {PANEL_BACKGROUND};")
        
        # React 消息区与输入区
        self._react_host = ReactConversationHost(self)
        main_layout.addWidget(self._react_host, 1)
    
    def _connect_component_signals(self) -> None:
        """连接子组件信号"""
        if self._react_host:
            self._react_host.files_dropped.connect(self.add_attachments)

        bridge = self._react_host.bridge if self._react_host else None
        if bridge is not None:
            bridge.surface_activation_requested.connect(self.activate_surface)
            bridge.send_requested.connect(self._on_send_requested)
            bridge.stop_requested.connect(self._on_stop_requested)
            bridge.new_conversation_requested.connect(self._on_new_conversation_requested)
            bridge.history_requested.connect(self._on_history_requested)
            bridge.history_close_requested.connect(self._on_history_close_requested)
            bridge.history_session_selected.connect(self._on_history_session_selected)
            bridge.history_session_open_requested.connect(
                self._on_history_session_open_requested
            )
            bridge.history_export_dialog_open_requested.connect(
                self._on_history_export_dialog_open_requested
            )
            bridge.history_export_dialog_close_requested.connect(
                self._on_history_export_dialog_close_requested
            )
            bridge.history_export_format_changed.connect(
                self._on_history_export_format_changed
            )
            bridge.history_export_path_pick_requested.connect(
                self._on_history_export_path_pick_requested
            )
            bridge.history_session_export_requested.connect(
                self._on_history_session_export_requested
            )
            bridge.history_session_delete_requested.connect(
                self._on_history_session_delete_requested
            )
            bridge.confirm_dialog_resolved.connect(self._on_confirm_dialog_resolved)
            bridge.notice_dialog_close_requested.connect(self._on_notice_dialog_close_requested)
            bridge.compress_requested.connect(self._on_compress_requested)
            bridge.session_name_changed.connect(self._on_session_name_changed)
            bridge.suggestion_selected.connect(self._on_suggestion_selected)
            bridge.rollback_requested.connect(self._on_rollback_requested)
            bridge.rollback_preview_close_requested.connect(
                self._on_rollback_preview_close_requested
            )
            bridge.rollback_confirm_requested.connect(
                self._on_rollback_confirm_requested
            )
            bridge.pending_edit_accept_all_requested.connect(
                self._on_pending_edit_accept_all_requested
            )
            bridge.pending_edit_reject_all_requested.connect(
                self._on_pending_edit_reject_all_requested
            )
            bridge.pending_edit_file_requested.connect(self._on_pending_edit_file_requested)
            bridge.file_open_requested.connect(self._on_file_open_requested)
            bridge.link_open_requested.connect(self._on_link_open_requested)
            bridge.image_preview_requested.connect(self._on_image_preview_requested)
            bridge.upload_image_requested.connect(self._on_upload_image_requested)
            bridge.select_file_requested.connect(self._on_select_file_requested)
            bridge.model_config_requested.connect(self._on_model_config_requested)
            bridge.rag_reindex_requested.connect(self._on_rag_reindex_requested)
            bridge.rag_clear_requested.connect(self._on_rag_clear_requested)
            bridge.rag_search_requested.connect(self._on_rag_search_requested)
            bridge.attachments_selected.connect(self.add_attachments)

    def _connect_view_model_signals(self) -> None:
        """连接 ViewModel 信号"""
        if self._view_model is None:
            return

        self._view_model.display_state_changed.connect(self._on_display_state_changed)
        self._view_model.usage_changed.connect(self._on_usage_changed)
        self._view_model.can_send_changed.connect(self._on_can_send_changed)
        self._view_model.new_conversation_suggested.connect(
            self._on_new_conversation_suggested
        )
        self._view_model.stop_requested.connect(self._on_stop_requested_signal)
        self._view_model.stop_completed.connect(self._on_stop_completed)

    # ============================================================
    # 初始化和清理
    # ============================================================

    def initialize(self) -> None:
        """初始化面板，订阅事件"""
        # 确保 ViewModel 已创建
        _ = self.view_model

        if self.pending_workspace_edit_service is not None:
            try:
                self.pending_workspace_edit_service.summary_changed.connect(
                    self._on_pending_workspace_edit_summary_changed
                )
            except Exception:
                pass

        # 订阅事件
        self._subscribe_events()

        # 初始刷新
        self.refresh_display()
        self._refresh_pending_workspace_edit_summary()

    def cleanup(self) -> None:
        """清理资源"""
        self._unsubscribe_events()
        if self.pending_workspace_edit_service is not None:
            try:
                self.pending_workspace_edit_service.summary_changed.disconnect(
                    self._on_pending_workspace_edit_summary_changed
                )
            except Exception:
                pass
        if self._view_model:
            self._view_model.cleanup()
        if self._react_host:
            self._react_host.cleanup()

    def _subscribe_events(self) -> None:
        """订阅事件"""
        if self.event_bus is None:
            return

        try:
            from shared.event_types import (
                EVENT_UI_ATTACH_FILES_TO_CONVERSATION,
                EVENT_LANGUAGE_CHANGED,
                EVENT_RAG_INIT_COMPLETE,
                EVENT_RAG_INDEX_STARTED,
                EVENT_RAG_INDEX_PROGRESS,
                EVENT_RAG_INDEX_COMPLETE,
                EVENT_RAG_INDEX_ERROR,
                EVENT_SESSION_CHANGED,
                EVENT_STATE_PROJECT_OPENED,
                EVENT_STATE_PROJECT_CLOSED,
            )

            self.event_bus.subscribe(
                EVENT_LANGUAGE_CHANGED, self._on_language_changed
            )
            self.event_bus.subscribe(
                EVENT_SESSION_CHANGED, self._on_session_changed
            )
            self.event_bus.subscribe(
                EVENT_UI_ATTACH_FILES_TO_CONVERSATION,
                self._on_attach_files_requested,
            )
            self.event_bus.subscribe(EVENT_RAG_INIT_COMPLETE, self._on_rag_init_complete)
            self.event_bus.subscribe(EVENT_RAG_INDEX_STARTED, self._on_rag_index_started)
            self.event_bus.subscribe(EVENT_RAG_INDEX_PROGRESS, self._on_rag_index_progress)
            self.event_bus.subscribe(EVENT_RAG_INDEX_COMPLETE, self._on_rag_index_complete)
            self.event_bus.subscribe(EVENT_RAG_INDEX_ERROR, self._on_rag_index_error)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_OPENED, self._on_rag_project_opened)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_CLOSED, self._on_rag_project_closed)

            from shared.event_types import EVENT_MODEL_CHANGED

            self.event_bus.subscribe(
                EVENT_MODEL_CHANGED, self._on_model_changed
            )

        except ImportError:
            if self.logger:
                self.logger.warning("无法导入事件类型，事件订阅跳过")

    def _unsubscribe_events(self) -> None:
        """取消事件订阅"""
        if self.event_bus is None:
            return

        try:
            from shared.event_types import (
                EVENT_UI_ATTACH_FILES_TO_CONVERSATION,
                EVENT_LANGUAGE_CHANGED,
                EVENT_RAG_INIT_COMPLETE,
                EVENT_RAG_INDEX_STARTED,
                EVENT_RAG_INDEX_PROGRESS,
                EVENT_RAG_INDEX_COMPLETE,
                EVENT_RAG_INDEX_ERROR,
                EVENT_SESSION_CHANGED,
                EVENT_STATE_PROJECT_OPENED,
                EVENT_STATE_PROJECT_CLOSED,
            )

            self.event_bus.unsubscribe(
                EVENT_LANGUAGE_CHANGED, self._on_language_changed
            )
            self.event_bus.unsubscribe(
                EVENT_SESSION_CHANGED, self._on_session_changed
            )
            self.event_bus.unsubscribe(
                EVENT_UI_ATTACH_FILES_TO_CONVERSATION,
                self._on_attach_files_requested,
            )
            self.event_bus.unsubscribe(EVENT_RAG_INIT_COMPLETE, self._on_rag_init_complete)
            self.event_bus.unsubscribe(EVENT_RAG_INDEX_STARTED, self._on_rag_index_started)
            self.event_bus.unsubscribe(EVENT_RAG_INDEX_PROGRESS, self._on_rag_index_progress)
            self.event_bus.unsubscribe(EVENT_RAG_INDEX_COMPLETE, self._on_rag_index_complete)
            self.event_bus.unsubscribe(EVENT_RAG_INDEX_ERROR, self._on_rag_index_error)
            self.event_bus.unsubscribe(EVENT_STATE_PROJECT_OPENED, self._on_rag_project_opened)
            self.event_bus.unsubscribe(EVENT_STATE_PROJECT_CLOSED, self._on_rag_project_closed)

            from shared.event_types import EVENT_MODEL_CHANGED

            self.event_bus.unsubscribe(
                EVENT_MODEL_CHANGED, self._on_model_changed
            )

        except ImportError:
            pass

    # ============================================================
    # 消息显示
    # ============================================================

    def get_authoritative_frontend_state(self) -> Dict[str, Any]:
        return copy.deepcopy(self._authoritative_frontend_state)

    def _get_pending_workspace_edit_summary_state(self) -> Dict[str, Any]:
        service = self.pending_workspace_edit_service
        if service is None:
            return {
                "file_count": 0,
                "added_lines": 0,
                "deleted_lines": 0,
                "files": [],
            }
        try:
            summary_state = service.get_summary_state()
            return summary_state if isinstance(summary_state, dict) else {
                "file_count": 0,
                "added_lines": 0,
                "deleted_lines": 0,
                "files": [],
            }
        except Exception as exc:
            if self.logger:
                self.logger.error(f"Failed to get pending workspace edit state: {exc}")
            return {
                "file_count": 0,
                "added_lines": 0,
                "deleted_lines": 0,
                "files": [],
            }

    def _get_model_display_name(self) -> str:
        display_name = "模型"
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_LLM_RUNTIME_CONFIG_MANAGER

            llm_runtime_config_manager = ServiceLocator.get_optional(
                SVC_LLM_RUNTIME_CONFIG_MANAGER
            )
            if llm_runtime_config_manager:
                active_config = llm_runtime_config_manager.resolve_active_config()
                model_name = active_config.model
                provider = active_config.provider
                if active_config.display_name:
                    display_name = active_config.display_name

                from shared.model_registry import ModelRegistry

                if provider and model_name:
                    model_id = f"{provider}:{model_name}"
                    model_config = ModelRegistry.get_model(model_id)
                    if model_config:
                        display_name = model_config.display_name
                    else:
                        display_name = model_name.upper().replace("GLM-", "GLM-")
        except Exception:
            pass
        return display_name

    def _build_authoritative_frontend_state(self) -> Dict[str, Any]:
        view_model = self.view_model
        session_manager = view_model.session_state_manager if view_model else None
        session_id = session_manager.get_current_session_id() if session_manager else ""
        session_name = session_manager.get_current_session_name() if session_manager else ""
        return self._state_serializer.serialize_main_state(
            session_id=session_id,
            session_name=session_name,
            messages=view_model.messages if view_model else [],
            runtime_steps=view_model.active_agent_steps if view_model else [],
            usage_info=view_model.get_usage_info() if view_model else None,
            pending_workspace_edit_summary=self._get_pending_workspace_edit_summary_state(),
            model_display_name=self._get_model_display_name(),
            action_mode=self._composer_action_mode,
            action_status=self._composer_action_status,
            clear_draft_nonce=self._draft_clear_nonce,
            history_overlay=self._history_overlay_state,
            rollback_overlay=self._rollback_overlay_state,
            confirm_dialog=self._confirm_dialog_state,
            notice_dialog=self._notice_dialog_state,
            is_loading=view_model.is_loading if view_model else False,
            can_send=view_model.can_send if view_model else True,
            send_in_progress=self._send_in_progress,
            rollback_in_progress=self._rollback_in_progress,
            active_surface=self._active_surface,
            rag_state=self._build_rag_frontend_state(),
        )

    def _resolve_rag_file_path(self, relative_path: str) -> str:
        manager = self.rag_manager
        if manager is None or not manager.project_root or not relative_path:
            return ""
        try:
            return str((Path(manager.project_root) / relative_path.replace("/", os.sep)).resolve())
        except Exception:
            return ""

    def _build_rag_status_state(self, total_files: int) -> Dict[str, Any]:
        manager = self.rag_manager
        progress_state = self._rag_progress_state
        if manager is None or not manager.project_root:
            return {
                "phase": "idle",
                "label": self._get_text("rag.status.await_project", "等待项目"),
                "tone": "neutral",
            }
        if progress_state.get("is_visible", False) or getattr(manager, "is_indexing", False):
            total = max(0, int(progress_state.get("total", 0) or 0))
            processed = max(0, int(progress_state.get("processed", 0) or 0))
            progress_label = (
                f"索引中 {processed}/{total}" if total > 0 else self._get_text("rag.status.indexing", "索引中...")
            )
            return {
                "phase": "indexing",
                "label": progress_label,
                "tone": "info",
            }
        if getattr(manager, "init_error", None):
            return {
                "phase": "error",
                "label": self._get_text("rag.status.init_error", "初始化失败"),
                "tone": "error",
            }
        if getattr(manager, "is_available", False):
            return {
                "phase": "ready",
                "label": f"已就绪 ({total_files} 文件)",
                "tone": "success",
            }
        return {
            "phase": "initializing",
            "label": self._get_text("rag.status.initializing", "初始化中..."),
            "tone": "info",
        }

    def _build_rag_frontend_state(self) -> Dict[str, Any]:
        manager = self.rag_manager
        status = None
        if manager is not None:
            try:
                status = manager.get_index_status()
            except Exception as exc:
                if self.logger:
                    self.logger.debug(f"Failed to query RAG status: {exc}")

        stats = getattr(status, "stats", None)
        files = getattr(status, "files", []) if status is not None else []
        total_files = max(0, int(getattr(stats, "total_files", 0) or 0)) if stats is not None else 0

        return {
            "status": self._build_rag_status_state(total_files),
            "stats": {
                "total_files": total_files,
                "processed": max(0, int(getattr(stats, "processed", 0) or 0)) if stats is not None else 0,
                "failed": max(0, int(getattr(stats, "failed", 0) or 0)) if stats is not None else 0,
                "excluded": max(0, int(getattr(stats, "excluded", 0) or 0)) if stats is not None else 0,
                "total_chunks": max(0, int(getattr(stats, "total_chunks", 0) or 0)) if stats is not None else 0,
                "total_entities": max(0, int(getattr(stats, "total_entities", 0) or 0)) if stats is not None else 0,
                "total_relations": max(0, int(getattr(stats, "total_relations", 0) or 0)) if stats is not None else 0,
                "storage_size_mb": max(0.0, float(getattr(stats, "storage_size_mb", 0.0) or 0.0)) if stats is not None else 0.0,
            },
            "progress": dict(self._rag_progress_state),
            "actions": {
                "can_reindex": bool(manager and manager.project_root and manager.is_available and not manager.is_indexing),
                "can_clear": bool(manager and manager.project_root and manager.is_available and not manager.is_indexing),
                "can_search": bool(manager and manager.project_root and manager.is_available and not self._rag_search_state.get("is_running", False)),
                "is_indexing": bool(manager.is_indexing) if manager is not None else False,
            },
            "files": [
                {
                    "path": self._resolve_rag_file_path(str(getattr(file_info, "relative_path", "") or "")),
                    "relative_path": str(getattr(file_info, "relative_path", "") or ""),
                    "status": str(getattr(file_info, "status", "pending") or "pending"),
                    "status_label": {
                        "processed": "已索引",
                        "processing": "索引中",
                        "failed": "失败",
                        "excluded": "排除索引",
                        "pending": "待索引",
                    }.get(str(getattr(file_info, "status", "pending") or "pending"), str(getattr(file_info, "status", "pending") or "pending")),
                    "chunks_count": max(0, int(getattr(file_info, "chunks_count", 0) or 0)),
                    "indexed_at": str(getattr(file_info, "indexed_at", "") or ""),
                    "tooltip": str(getattr(file_info, "exclude_reason", "") or getattr(file_info, "error", "") or ""),
                }
                for file_info in files
            ],
            "search": dict(self._rag_search_state),
            "info": dict(self._rag_info_state),
        }

    def _update_authoritative_frontend_state(self) -> None:
        self._authoritative_frontend_state = self._build_authoritative_frontend_state()
        if self._react_host is not None:
            self._react_host.set_state(self._authoritative_frontend_state)

    def refresh_display(self) -> None:
        """从 ViewModel 获取数据并刷新显示"""
        if self.view_model is None:
            return

        self._update_authoritative_frontend_state()

    def _refresh_pending_workspace_edit_summary(self) -> None:
        self._update_authoritative_frontend_state()

    def _update_usage_display(self) -> None:
        """更新上下文占用显示"""
        if self.view_model is None:
            return
        self._update_authoritative_frontend_state()

    # ============================================================
    # 事件处理 - EventBus 事件
    # ============================================================

    def _on_language_changed(self, event_data: Dict[str, Any]) -> None:
        """处理语言变更事件"""
        del event_data
        self.retranslate_ui()

    def _on_session_changed(self, event_data: Dict[str, Any]) -> None:
        """
        处理会话变更事件（由 SessionStateManager 发布）

        更新标题栏显示会话名称。
        注意：不在这里刷新消息显示，由 ViewModel 的消息变更信号触发。
        """
        data = event_data.get("data", event_data)
        session_name = data.get("session_name", "")
        action = data.get("action", "")

        if self.logger:
            self.logger.debug(f"Session changed in panel: {action}, name={session_name}")

        if action == "project_closed":
            self._close_confirm_dialog()
            self._close_notice_dialog()
            self._close_history_overlay()
            self._close_rollback_overlay()
            self._draft_clear_nonce += 1

        if self._history_overlay_state.get("is_open", False):
            self._refresh_history_overlay()
        self._update_authoritative_frontend_state()

    def _on_model_changed(self, event_data: Dict[str, Any]) -> None:
        """
        处理模型变更事件（由应用层统一发布）

        更新输入区域的模型卡片显示。
        """
        del event_data
        self._update_authoritative_frontend_state()

    def _on_rag_project_opened(self, event_data: Dict[str, Any]) -> None:
        del event_data
        self._reset_rag_runtime_state(clear_search=True)
        self._update_authoritative_frontend_state()

    def _on_rag_project_closed(self, event_data: Dict[str, Any]) -> None:
        del event_data
        self._reset_rag_runtime_state(clear_search=True)
        self._update_authoritative_frontend_state()

    def _on_rag_init_complete(self, event_data: Dict[str, Any]) -> None:
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        if isinstance(data, dict) and data.get("status") == "error":
            self._set_rag_info(str(data.get("error", "") or ""), tone="error")
        elif isinstance(data, dict) and data.get("status") == "ready":
            self._set_rag_info("", tone="neutral")
        self._update_authoritative_frontend_state()

    def _on_rag_index_started(self, event_data: Dict[str, Any]) -> None:
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        total_files = max(0, int(data.get("total_files", 0) or 0)) if isinstance(data, dict) else 0
        self._rag_progress_state = {
            "is_visible": True,
            "processed": 0,
            "total": total_files,
            "current_file": "",
        }
        self._set_rag_info("", tone="neutral")
        self._update_authoritative_frontend_state()

    def _on_rag_index_progress(self, event_data: Dict[str, Any]) -> None:
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        if not isinstance(data, dict):
            return
        self._rag_progress_state = {
            "is_visible": True,
            "processed": max(0, int(data.get("processed", 0) or 0)),
            "total": max(0, int(data.get("total", 0) or 0)),
            "current_file": str(data.get("current_file", "") or ""),
        }
        self._update_authoritative_frontend_state()

    def _on_rag_index_complete(self, event_data: Dict[str, Any]) -> None:
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        self._rag_progress_state = self._create_rag_progress_state()
        if isinstance(data, dict):
            total = max(0, int(data.get("total_indexed", 0) or 0))
            failed = max(0, int(data.get("failed", 0) or 0))
            duration = float(data.get("duration_s", 0.0) or 0.0)
            if data.get("already_up_to_date"):
                self._set_rag_info("索引已是最新", tone="neutral")
            elif failed > 0:
                self._set_rag_info(f"索引完成：{total} 成功，{failed} 失败，耗时 {duration:.1f}s", tone="neutral")
            else:
                self._set_rag_info(f"索引完成：{total} 文件，耗时 {duration:.1f}s", tone="success")
        self._update_authoritative_frontend_state()

    def _on_rag_index_error(self, event_data: Dict[str, Any]) -> None:
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        if isinstance(data, dict):
            error = str(data.get("error", "") or "")
            file_path = str(data.get("file_path", "") or "")
            if file_path:
                self._set_rag_info(f"错误 ({file_path}): {error}", tone="error")
            else:
                self._set_rag_info(f"错误: {error}", tone="error")
            self._update_authoritative_frontend_state()

    def _on_attach_files_requested(self, event_data: Dict[str, Any]) -> None:
        data = event_data.get("data", event_data)
        paths = data.get("paths") if isinstance(data, dict) else None
        if not isinstance(paths, list):
            return
        self.add_attachments(paths)

    # ============================================================
    # 事件处理 - ViewModel 信号
    # ============================================================

    @pyqtSlot()
    def _on_display_state_changed(self) -> None:
        self.refresh_display()

    @pyqtSlot(dict)
    def _on_pending_workspace_edit_summary_changed(self, summary_state: Dict[str, Any]) -> None:
        del summary_state
        self._update_authoritative_frontend_state()

    @pyqtSlot(float)
    def _on_usage_changed(self, ratio: float) -> None:
        """处理上下文占用变化"""
        del ratio
        self._update_usage_display()
        self._update_authoritative_frontend_state()

    @pyqtSlot(bool)
    def _on_can_send_changed(self, can_send: bool) -> None:
        """处理可发送状态变化"""
        del can_send
        self._sync_input_action_state()

    @pyqtSlot()
    def _on_stop_requested_signal(self) -> None:
        """处理停止请求信号（来自 ViewModel）"""
        if self._composer_action_mode != ACTION_MODE_STOPPING:
            self._composer_action_mode = ACTION_MODE_STOPPING
        self._sync_input_action_state()
        if self.logger:
            self.logger.debug("Stop requested, UI updated")

    @pyqtSlot(dict)
    def _on_stop_completed(self, result: dict) -> None:
        """
        处理停止完成信号（来自 ViewModel）

        此时 ViewModel 已经：
        1. 处理了部分响应
        2. 发出了 can_send_changed(True) 信号

        这里只需要刷新显示。
        """
        if self.logger:
            saved = result.get("saved", False)
            self.logger.info(f"Stop completed, partial saved: {saved}")
        self._sync_input_action_state()

    @pyqtSlot()
    def _on_new_conversation_suggested(self) -> None:
        """处理建议新开对话"""
        self._open_notice_dialog(
            self._get_text(
                "msg.suggest_new_conversation",
                "上下文已接近上限，建议开启新对话以获得更好的体验。"
            ),
            title=self._get_text("dialog.info.title", "提示"),
            tone="info",
        )

    # ============================================================
    # 事件处理 - 子组件信号
    # ============================================================

    @pyqtSlot(str, dict)
    def _on_send_requested(self, text: str, composer_state: Dict[str, Any]) -> None:
        if self._send_in_progress or self._rollback_in_progress:
            return
        asyncio.create_task(self._send_message(text, composer_state))

    @pyqtSlot()
    def _on_stop_requested(self) -> None:
        if self._rollback_in_progress or self._send_in_progress:
            return
        if self.view_model is None or not self.view_model.is_loading:
            return
        self.view_model.request_stop()

    @pyqtSlot()
    def _on_new_conversation_requested(self) -> None:
        """处理新开对话请求"""
        self.start_new_conversation()

    @pyqtSlot()
    def _on_history_requested(self) -> None:
        """处理历史对话请求"""
        self._refresh_history_overlay()

    def _on_history_close_requested(self) -> None:
        self._close_history_overlay()

    def _on_history_session_selected(self, session_id: str) -> None:
        self._refresh_history_overlay(session_id)

    def _on_history_session_open_requested(self, session_id: str) -> None:
        if not session_id:
            return
        success = self._session_support.open_session(session_id)
        if success:
            self._close_history_overlay()
            self._draft_clear_nonce += 1
            self._update_authoritative_frontend_state()
            return
        self._open_notice_dialog(
            self._get_text("dialog.history.open_failed", "打开会话失败"),
            title=self._get_text("dialog.error.title", "错误"),
            tone="error",
        )

    def _on_history_export_dialog_open_requested(self, session_id: str) -> None:
        normalized_session_id = str(
            session_id
            or self._history_overlay_state.get("selected_session_id", "")
            or self._history_overlay_state.get("current_session_id", "")
            or ""
        )
        if not normalized_session_id:
            return
        self._set_history_export_dialog_state(
            normalized_session_id,
            is_open=True,
        )
        self._update_authoritative_frontend_state()

    def _on_history_export_dialog_close_requested(self) -> None:
        if not self._history_overlay_state.get("is_open", False):
            return
        self._clear_history_export_dialog_state()
        self._update_authoritative_frontend_state()

    def _on_history_export_format_changed(self, export_format: str) -> None:
        dialog_state = self._current_history_export_dialog_state()
        session_id = str(dialog_state.get("session_id", "") or "")
        normalized_format = self._session_support.normalize_export_format(export_format)
        if not session_id or not normalized_format:
            return
        self._set_history_export_dialog_state(
            session_id,
            normalized_format,
            str(dialog_state.get("file_path", "") or ""),
            is_open=bool(dialog_state.get("is_open", False)),
        )
        self._update_authoritative_frontend_state()

    def _on_history_export_path_pick_requested(self) -> None:
        dialog_state = self._current_history_export_dialog_state()
        session_id = str(dialog_state.get("session_id", "") or "")
        export_format = self._session_support.normalize_export_format(
            str(dialog_state.get("export_format", "") or "")
        )
        if not session_id or not export_format:
            return
        selected_path = self._session_support.choose_export_file_path(
            session_id,
            export_format,
            parent=self,
            dialog_title=self._get_text("dialog.export.title", "选择导出路径"),
            initial_path=str(dialog_state.get("file_path", "") or ""),
        )
        if not selected_path:
            return
        self._set_history_export_dialog_state(
            session_id,
            export_format,
            selected_path,
            is_open=True,
        )
        self._update_authoritative_frontend_state()

    def _on_history_session_export_requested(
        self,
        session_id: str,
        export_format: str,
        file_path: str,
    ) -> None:
        normalized_format = self._session_support.normalize_export_format(export_format)
        normalized_path = self._session_support.normalize_export_file_path(
            file_path,
            normalized_format,
        )
        if not session_id or not normalized_format or not normalized_path:
            self._open_notice_dialog(
                self._get_text("dialog.export.failed", "导出会话失败"),
                title=self._get_text("dialog.error.title", "错误"),
                tone="error",
            )
            return
        success, export_path = self._session_support.export_session_to_path(
            session_id,
            normalized_format,
            normalized_path,
        )
        if success:
            self._clear_history_export_dialog_state()
            self._update_authoritative_frontend_state()
            self._open_notice_dialog(
                self._get_text("dialog.export.success", "会话导出成功"),
                title=self._get_text("dialog.info.title", "提示"),
                tone="success",
            )
            if self.logger:
                self.logger.info(f"Session exported to: {export_path}")
            return

    def _on_history_session_delete_requested(self, session_id: str) -> None:
        if not session_id:
            return
        self._open_confirm_dialog(
            kind="history_delete",
            title=self._get_text("dialog.warning.title", "警告"),
            message=self._get_text(
                "dialog.history.delete_confirm",
                "确定删除这个会话吗？此操作无法撤销。",
            ),
            confirm_label=self._get_text("btn.delete", "删除"),
            cancel_label=self._get_text("btn.cancel", "取消"),
            tone="danger",
            payload={"session_id": session_id},
        )

    def request_history(self) -> None:
        self._on_history_requested()

    def request_compress_context(self) -> None:
        self._on_compress_requested()

    def activate_surface(self, surface_id: str) -> bool:
        normalized_surface = "rag" if str(surface_id or "") == "rag" else "conversation"
        if self._active_surface == normalized_surface:
            return True
        self._active_surface = normalized_surface
        self._update_authoritative_frontend_state()
        return True

    def trigger_reindex(self) -> None:
        self.activate_surface("rag")
        manager = self.rag_manager
        if manager is None or not manager.is_available:
            return
        manager.trigger_index()

    def request_clear_index(self) -> None:
        self.activate_surface("rag")
        manager = self.rag_manager
        if manager is None or not manager.is_available:
            return
        self._open_confirm_dialog(
            kind="rag_clear",
            title=self._get_text("dialog.warning.title", "警告"),
            message="确定要清空当前项目的索引库吗？\n已索引的内容将被全部删除。",
            confirm_label=self._get_text("btn.delete", "删除"),
            cancel_label=self._get_text("btn.cancel", "取消"),
            tone="danger",
        )

    def request_rag_search(self, query: str) -> None:
        self.activate_surface("rag")
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return
        manager = self.rag_manager
        if manager is None or not manager.is_available:
            self._rag_search_state = {
                "is_running": False,
                "result_text": "索引库未就绪（请等待初始化完成）",
            }
            self._update_authoritative_frontend_state()
            return
        self._rag_search_state = {
            "is_running": True,
            "result_text": "检索中...",
        }
        self._update_authoritative_frontend_state()
        asyncio.create_task(self._async_rag_search(normalized_query))

    async def _async_rag_search(self, query: str) -> None:
        manager = self.rag_manager
        if manager is None:
            self._rag_search_state = {
                "is_running": False,
                "result_text": "索引库未就绪（请等待初始化完成）",
            }
            self._update_authoritative_frontend_state()
            return
        try:
            result = await manager.query_async(query)
            if result.is_empty:
                result_text = f'未找到与 "{query}" 相关的内容'
            else:
                result_text = f"片段: {result.chunks_count}\n\n{result.format_as_context(max_tokens=3000)}"
            self._rag_search_state = {
                "is_running": False,
                "result_text": result_text,
            }
        except Exception as exc:
            self._rag_search_state = {
                "is_running": False,
                "result_text": f"检索失败: {exc}",
            }
        self._update_authoritative_frontend_state()

    async def _async_clear_rag_index(self) -> None:
        manager = self.rag_manager
        if manager is None:
            return
        try:
            await manager.clear_index_async()
            self._rag_search_state = self._create_rag_search_state()
            self._set_rag_info("索引库已清空", tone="success")
        except Exception as exc:
            self._set_rag_info(f"清空失败: {exc}", tone="error")
        self._update_authoritative_frontend_state()

    def _on_confirm_dialog_resolved(self, accepted: bool) -> None:
        confirm_state = dict(self._confirm_dialog_state)
        self._close_confirm_dialog()
        if not accepted:
            return
        kind = str(confirm_state.get("kind", "") or "")
        payload = confirm_state.get("payload", {})
        if kind == "history_delete":
            session_id = str(payload.get("session_id", "") or "") if isinstance(payload, dict) else ""
            if not session_id:
                return
            success = self._session_support.delete_session(session_id)
            if success:
                self._refresh_history_overlay()
                return
            self._open_notice_dialog(
                self._get_text("dialog.history.delete_failed", "删除会话失败"),
                title=self._get_text("dialog.error.title", "错误"),
                tone="error",
            )
        if kind == "rag_clear":
            asyncio.create_task(self._async_clear_rag_index())

    def _on_notice_dialog_close_requested(self) -> None:
        self._close_notice_dialog()

    def _on_session_name_changed(self, name: str) -> None:
        """处理会话名称变更"""
        normalized_name = str(name or "").strip()
        if not normalized_name:
            return
        if self._session_support.rename_current_session(normalized_name):
            self._update_authoritative_frontend_state()
            return
        self._open_notice_dialog(
            self._get_text("dialog.history.rename_failed", "重命名会话失败"),
            title=self._get_text("dialog.error.title", "错误"),
            tone="error",
        )

    @pyqtSlot()
    def _on_compress_requested(self) -> None:
        """处理压缩请求"""
        self.compress_requested.emit()

    def _on_attachment_error(self, message: str) -> None:
        """处理附件错误"""
        self._open_notice_dialog(
            message,
            title=self._get_text("dialog.warning.title", "警告"),
            tone="error",
        )

    @pyqtSlot()
    def _on_upload_image_requested(self) -> None:
        image_paths, _ = QFileDialog.getOpenFileNames(
            self,
            self._get_text("dialog.select_image.title", "选择图片"),
            "",
            "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;所有文件 (*)",
        )
        if image_paths:
            self.add_attachments(image_paths)

    @pyqtSlot()
    def _on_select_file_requested(self) -> None:
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            self._get_text("dialog.select_file.title", "选择文件"),
            "",
            "所有文件 (*)",
        )
        if file_paths:
            self.add_attachments(file_paths)

    @pyqtSlot()
    def _on_model_config_requested(self) -> None:
        from presentation.dialogs import ModelConfigDialog

        dialog = ModelConfigDialog(self)
        dialog.exec()

    @pyqtSlot()
    def _on_rag_reindex_requested(self) -> None:
        self.trigger_reindex()

    @pyqtSlot()
    def _on_rag_clear_requested(self) -> None:
        self.request_clear_index()

    @pyqtSlot(str)
    def _on_rag_search_requested(self, query: str) -> None:
        self.request_rag_search(query)

    def _on_image_preview_requested(self, image_path: str) -> None:
        self._open_image_preview(image_path)

    def _on_pending_edit_accept_all_requested(self) -> None:
        service = self.pending_workspace_edit_service
        if service is None:
            return
        service.accept_all_edits()

    def _on_pending_edit_reject_all_requested(self) -> None:
        service = self.pending_workspace_edit_service
        if service is None:
            return
        service.reject_all_edits()

    def _on_pending_edit_file_requested(self, file_path: str) -> None:
        if file_path:
            self.file_clicked.emit(file_path)

    def _on_file_open_requested(self, file_path: str) -> None:
        attachment_type = resolve_attachment_type(file_path, "")
        if attachment_type == "image":
            self._open_image_preview(file_path)
            return
        self.file_clicked.emit(file_path)

    def _on_link_open_requested(self, url: str) -> None:
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _on_suggestion_selected(self, suggestion_id: str) -> None:
        if not suggestion_id or not self.view_model:
            return
        selected_value = self.view_model.select_suggestion(suggestion_id)
        if self.event_bus is not None:
            try:
                from shared.event_types import EVENT_ITERATION_USER_CONFIRMED

                self.event_bus.publish(
                    EVENT_ITERATION_USER_CONFIRMED,
                    {
                        "suggestion_id": suggestion_id,
                        "value": selected_value,
                    },
                    source="conversation_panel",
                )
            except Exception as exc:
                if self.logger:
                    self.logger.warning(f"Failed to publish suggestion selection: {exc}")

    def _on_rollback_requested(self, message_id: str) -> None:
        if self._rollback_in_progress or self._send_in_progress:
            return
        asyncio.create_task(self._confirm_and_perform_rollback(message_id))

    def _on_rollback_preview_close_requested(self) -> None:
        self._close_rollback_overlay()

    def _on_rollback_confirm_requested(self) -> None:
        target_message_id = str(
            self._rollback_overlay_state.get("target_message_id", "") or ""
        )
        if not target_message_id:
            return
        self._close_rollback_overlay()
        asyncio.create_task(self._perform_rollback(target_message_id))

    def _open_image_preview(self, image_path: str) -> None:
        if not image_path or not os.path.isfile(image_path):
            return
        from presentation.dialogs.image_preview_dialog import ImagePreviewDialog

        dialog = ImagePreviewDialog(image_path, self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.exec()

    # ============================================================
    # 拖放处理
    # ============================================================

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """处理拖入事件"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        """处理放下事件"""
        accepted_paths = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path):
                accepted_paths.append(path)
        if accepted_paths:
            self.add_attachments(accepted_paths)

    # ============================================================

    async def _send_message(self, text: str, composer_state: Optional[Dict[str, Any]] = None) -> None:
        """发送消息"""
        if self._send_in_progress:
            return

        payload = composer_state if isinstance(composer_state, dict) else {}
        attachments = []
        for raw_attachment in payload.get("attachments", []) or []:
            try:
                attachments.append(
                    ConversationAttachmentSupport.attachment_from_payload(raw_attachment)
                )
            except ConversationAttachmentError:
                continue
        if not text.strip() and not attachments:
            return

        if self.view_model and not self.view_model.can_send:
            return

        if self.view_model:
            self._send_in_progress = True
            self._sync_input_action_state()
            try:
                success = await self.view_model.send_message(text, attachments)
                if success:
                    self._draft_clear_nonce += 1
            finally:
                self._send_in_progress = False
                self._sync_input_action_state()

    async def _confirm_and_perform_rollback(self, message_id: str) -> None:
        if not message_id or self.view_model is None:
            return
        if self._rollback_in_progress or self._send_in_progress:
            return

        preview, error_message = await self.view_model.preview_rollback_to_message(message_id)
        if preview is None:
            self._open_notice_dialog(
                error_message or self._get_text("msg.rollback_failed", "撤回失败"),
                title=self._get_text("dialog.error.title", "错误"),
                tone="error",
            )
            return

        self._rollback_overlay_state = {
            "is_open": True,
            "is_loading": False,
            "error_message": "",
            "target_message_id": str(message_id or ""),
            "preview": preview,
        }
        self._update_authoritative_frontend_state()

    async def _perform_rollback(self, message_id: str) -> None:
        if not message_id or self.view_model is None:
            return
        if self._rollback_in_progress or self._send_in_progress:
            return

        self._rollback_in_progress = True
        self._sync_input_action_state()
        try:
            success, error_message = await self.view_model.rollback_to_message(message_id)
            if not success:
                self._open_notice_dialog(
                    error_message or self._get_text("msg.rollback_failed", "撤回失败"),
                    title=self._get_text("dialog.error.title", "错误"),
                    tone="error",
                )
        finally:
            self._rollback_in_progress = False
            self._sync_input_action_state()

    def _sync_input_action_state(self) -> None:
        if self._send_in_progress:
            self._composer_action_status = self._get_text(
                "conversation.send.in_progress", "正在发送…"
            )
            self._composer_action_mode = ACTION_MODE_SEND
            self._update_authoritative_frontend_state()
            return
        if self._rollback_in_progress:
            self._composer_action_status = self._get_text(
                "conversation.rollback.in_progress", "正在撤回…"
            )
            self._composer_action_mode = ACTION_MODE_ROLLBACKING
            self._update_authoritative_frontend_state()
            return
        if self.view_model and self.view_model.is_loading:
            if self._composer_action_mode != ACTION_MODE_STOPPING:
                self._composer_action_mode = ACTION_MODE_STOP
                self._composer_action_status = self._get_text(
                    "conversation.generate.in_progress", "正在生成…"
                )
            else:
                self._composer_action_status = self._get_text(
                    "conversation.stop.in_progress", "正在停止…"
                )
            self._update_authoritative_frontend_state()
            return
        self._composer_action_status = ""
        self._composer_action_mode = ACTION_MODE_SEND
        self._update_authoritative_frontend_state()

    def add_attachments(self, paths: list[str]) -> None:
        if self._react_host is None:
            return
        serialized_attachments = []
        for path in paths:
            if isinstance(path, str) and path:
                try:
                    attachment = ConversationAttachmentSupport.build_attachment_from_path(path)
                except ConversationAttachmentError as exc:
                    self._on_attachment_error(str(exc))
                    continue
                serialized_attachments.append(
                    self._state_serializer.serialize_attachment(attachment)
                )
        if serialized_attachments:
            self._react_host.append_draft_attachments(serialized_attachments)

    def start_new_conversation(self) -> None:
        """
        新开对话（委托给 SessionStateManager）

        SessionStateManager 原子执行：
        1. 保存当前会话
        2. 清空消息
        3. 生成新名称
        4. 发布 EVENT_SESSION_CHANGED 事件
        5. UI 组件订阅事件后自动刷新
        """
        if self.view_model:
            success, new_session_name = self.view_model.request_new_session()
            
            if success:
                self._draft_clear_nonce += 1
                self._close_history_overlay()
                self._close_rollback_overlay()
                
                if self.logger:
                    self.logger.info(f"New conversation started: {new_session_name}")
            else:
                if self.logger:
                    self.logger.warning(f"Failed to start new conversation: {new_session_name}")

    # ============================================================
    # 国际化
    # ============================================================
    
    def retranslate_ui(self) -> None:
        """刷新 UI 文本"""
        self.refresh_display()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ConversationPanel",
    "PANEL_BACKGROUND",
]
