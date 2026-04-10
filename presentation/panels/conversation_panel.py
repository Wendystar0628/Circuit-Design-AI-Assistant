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

    def _create_history_overlay_state(self) -> Dict[str, Any]:
        return {
            "is_open": False,
            "is_loading": False,
            "error_message": "",
            "current_session_id": "",
            "selected_session_id": "",
            "sessions": [],
            "preview_messages": [],
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
            bridge.send_requested.connect(self._on_send_requested)
            bridge.stop_requested.connect(self._on_stop_clicked)
            bridge.new_conversation_requested.connect(self._on_new_conversation_clicked)
            bridge.history_requested.connect(self._on_history_clicked)
            bridge.history_close_requested.connect(self._on_history_close_requested)
            bridge.history_session_selected.connect(self._on_history_session_selected)
            bridge.history_session_open_requested.connect(
                self._on_history_session_open_requested
            )
            bridge.history_session_export_requested.connect(
                self._on_history_session_export_requested
            )
            bridge.history_session_delete_requested.connect(
                self._on_history_session_delete_requested
            )
            bridge.clear_display_requested.connect(self._on_clear_clicked)
            bridge.confirm_dialog_resolved.connect(self._on_confirm_dialog_resolved)
            bridge.notice_dialog_close_requested.connect(self._on_notice_dialog_close_requested)
            bridge.compress_requested.connect(self._on_compress_clicked)
            bridge.session_name_changed.connect(self._on_session_name_changed)
            bridge.suggestion_selected.connect(self._on_suggestion_clicked)
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
            bridge.pending_edit_file_requested.connect(self._on_pending_edit_file_clicked)
            bridge.file_open_requested.connect(self._on_message_file_clicked)
            bridge.link_open_requested.connect(self._on_link_clicked)
            bridge.image_preview_requested.connect(self._on_image_preview_requested)
            bridge.upload_image_requested.connect(self._on_upload_image_clicked)
            bridge.select_file_requested.connect(self._on_select_file_clicked)
            bridge.model_config_requested.connect(self._on_model_card_clicked)
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
        self._view_model.stop_requested.connect(self._on_stop_requested)
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
                EVENT_STATE_PROJECT_OPENED,
                EVENT_STATE_PROJECT_CLOSED,
                EVENT_LANGUAGE_CHANGED,
                EVENT_SESSION_CHANGED,
            )
            
            self.event_bus.subscribe(
                EVENT_STATE_PROJECT_OPENED, self._on_project_opened
            )
            self.event_bus.subscribe(
                EVENT_STATE_PROJECT_CLOSED, self._on_project_closed
            )
            self.event_bus.subscribe(
                EVENT_LANGUAGE_CHANGED, self._on_language_changed
            )
            # 订阅会话变更事件，更新标题栏
            self.event_bus.subscribe(
                EVENT_SESSION_CHANGED, self._on_session_changed
            )
            self.event_bus.subscribe(
                EVENT_UI_ATTACH_FILES_TO_CONVERSATION,
                self._on_attach_files_requested,
            )
            
            # 订阅模型变更事件，更新模型卡片显示
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
                EVENT_STATE_PROJECT_OPENED,
                EVENT_STATE_PROJECT_CLOSED,
                EVENT_LANGUAGE_CHANGED,
                EVENT_SESSION_CHANGED,
            )
            
            self.event_bus.unsubscribe(
                EVENT_STATE_PROJECT_OPENED, self._on_project_opened
            )
            self.event_bus.unsubscribe(
                EVENT_STATE_PROJECT_CLOSED, self._on_project_closed
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
        display_name = "Model"
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
        )

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
    
    def _on_project_opened(self, event_data: Dict[str, Any]) -> None:
        """处理项目打开事件"""
        # 只调用 load_messages，它会触发 messages_changed 信号
        # 然后 _on_messages_changed 会调用 refresh_display
        if self.view_model:
            self.view_model.load_messages()
    
    def _on_project_closed(self, event_data: Dict[str, Any]) -> None:
        """处理项目关闭事件"""
        self.clear_display()
    
    def _on_language_changed(self, event_data: Dict[str, Any]) -> None:
        """处理语言变更事件"""
        self.retranslate_ui()
    
    
    def _on_session_changed(self, event_data: Dict[str, Any]) -> None:
        """
        处理会话变更事件（由 SessionStateManager 发布）
        
        更新标题栏显示会话名称。
        注意：不在这里刷新消息显示，由 ViewModel 的 messages_changed 信号触发。
        """
        data = event_data.get("data", event_data)
        session_name = data.get("session_name", "")
        action = data.get("action", "")
        
        if self.logger:
            self.logger.debug(f"Session changed in panel: {action}, name={session_name}")
        
        # 只更新标题栏，不刷新消息显示（避免重复刷新）
        if self._history_overlay_state.get("is_open", False):
            self._refresh_history_overlay()
        self._update_authoritative_frontend_state()
    
    def _on_model_changed(self, event_data: Dict[str, Any]) -> None:
        """
        处理模型变更事件（由应用层统一发布）
        
        更新输入区域的模型卡片显示。
        """
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
        self._update_usage_display()
        self._update_authoritative_frontend_state()
    
    @pyqtSlot(bool)
    def _on_can_send_changed(self, can_send: bool) -> None:
        """处理可发送状态变化"""
        self._sync_input_action_state()
    
    @pyqtSlot()
    def _on_stop_requested(self) -> None:
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
    
    def _on_new_conversation_clicked(self) -> None:
        """处理新开对话按钮点击"""
        self.start_new_conversation()
     
    def _on_history_clicked(self) -> None:
        """处理历史对话按钮点击"""
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

    def _on_history_session_export_requested(
        self,
        session_id: str,
        export_format: str,
    ) -> None:
        normalized_format = self._session_support.normalize_export_format(export_format)
        if not session_id or not normalized_format:
            self._open_notice_dialog(
                self._get_text("dialog.export.failed", "导出会话失败"),
                title=self._get_text("dialog.error.title", "错误"),
                tone="error",
            )
            return
        success, export_path = self._session_support.export_session(
            session_id,
            normalized_format,
            parent=self,
            dialog_title=self._get_text("dialog.export.title", "Export Conversation"),
        )
        if success:
            self._open_notice_dialog(
                self._get_text("dialog.export.success", "Conversation exported successfully"),
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
                "Are you sure you want to delete this session? This action cannot be undone.",
            ),
            confirm_label=self._get_text("btn.delete", "Delete"),
            cancel_label=self._get_text("btn.cancel", "Cancel"),
            tone="danger",
            payload={"session_id": session_id},
        )
    
    def _on_clear_clicked(self) -> None:
        """处理清空对话按钮点击"""
        self._open_confirm_dialog(
            kind="clear_display",
            title=self._get_text("dialog.confirm.title", "确认"),
            message=self._get_text(
                "msg.confirm_clear_conversation",
                "是否清空当前对话显示？（不影响历史记录）"
            ),
            confirm_label=self._get_text("btn.confirm", "确认"),
            cancel_label=self._get_text("btn.cancel", "取消"),
            tone="normal",
        )

    def request_history(self) -> None:
        self._refresh_history_overlay()

    def request_clear_display(self) -> None:
        self._on_clear_clicked()

    def request_compress_context(self) -> None:
        self.compress_requested.emit()

    def _on_confirm_dialog_resolved(self, accepted: bool) -> None:
        confirm_state = dict(self._confirm_dialog_state)
        self._close_confirm_dialog()
        if not accepted:
            return
        kind = str(confirm_state.get("kind", "") or "")
        payload = confirm_state.get("payload", {})
        if kind == "clear_display":
            self.clear_display()
            return
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
    
    def _on_compress_clicked(self) -> None:
        """处理压缩按钮点击"""
        self.compress_requested.emit()

    def _on_attachment_error(self, message: str) -> None:
        """处理附件错误"""
        self._open_notice_dialog(
            message,
            title=self._get_text("dialog.warning.title", "警告"),
            tone="error",
        )

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

    def _on_pending_edit_file_clicked(self, file_path: str) -> None:
        if file_path:
            self.file_clicked.emit(file_path)

    def _on_message_file_clicked(self, file_path: str) -> None:
        attachment_type = resolve_attachment_type(file_path, "")
        if attachment_type == "image":
            self._open_image_preview(file_path)
            return
        self.file_clicked.emit(file_path)

    def _on_link_clicked(self, url: str) -> None:
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _on_suggestion_clicked(self, suggestion_id: str) -> None:
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

    def clear_display(self) -> None:
        """清空显示区（不清空 ViewModel 数据）"""
        if self._react_host:
            cleared_state = copy.deepcopy(self._authoritative_frontend_state)
            conversation_state = (
                cleared_state.get("conversation", {})
                if isinstance(cleared_state, dict)
                else {}
            )
            view_flags = (
                cleared_state.get("view_flags", {})
                if isinstance(cleared_state, dict)
                else {}
            )
            if isinstance(conversation_state, dict):
                conversation_state["messages"] = []
                conversation_state["runtime_steps"] = []
                conversation_state["message_count"] = 0
            if isinstance(view_flags, dict):
                view_flags["has_messages"] = False
                view_flags["has_runtime_steps"] = False
            self._react_host.set_state(cleared_state)
            self._react_host.clear_draft_attachments()

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
