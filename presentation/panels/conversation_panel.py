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

import asyncio
import os
from typing import Any, Dict, Optional

from PyQt6.QtCore import pyqtSignal, pyqtSlot, QUrl, Qt
from PyQt6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QMessageBox,
    QFileDialog,
)

from domain.rag.file_extractor import resolve_attachment_type
from presentation.dialogs.rollback_confirmation_dialog import RollbackConfirmationDialog
# 从子模块导入组件
from presentation.panels.conversation import (
    ConversationViewModel,
    TitleBar,
    MessageArea,
    InputArea,
    ButtonMode,
)


# ============================================================
# 常量定义
# ============================================================

PANEL_BACKGROUND = "#ffffff"


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
    new_conversation_requested = pyqtSignal()      # 用户请求新开对话
    history_requested = pyqtSignal()               # 用户请求查看历史对话
    session_name_changed = pyqtSignal(str)         # 用户修改会话名称 (name)
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
        self._send_in_progress = False
        self._rollback_in_progress = False
        self._rollback_confirmation_dialog: Optional[RollbackConfirmationDialog] = None
        self._warning_dialog: Optional[QMessageBox] = None
        
        # 子组件引用
        self._title_bar: Optional[TitleBar] = None
        self._message_area: Optional[MessageArea] = None
        self._input_area: Optional[InputArea] = None
        
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


    # ============================================================
    # UI 初始化
    # ============================================================
    
    def _setup_ui(self) -> None:
        """设置 UI 布局"""
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 设置面板背景
        self.setStyleSheet(f"background-color: {PANEL_BACKGROUND};")
        
        # 1. 标题栏
        self._title_bar = TitleBar(self)
        main_layout.addWidget(self._title_bar)
        
        # 2. 消息显示区域
        self._message_area = MessageArea(self)
        main_layout.addWidget(self._message_area, 1)

        # 3. 输入区域
        self._input_area = InputArea(self)
        main_layout.addWidget(self._input_area)
    
    def _connect_component_signals(self) -> None:
        """连接子组件信号"""
        # 标题栏信号
        if self._title_bar:
            self._title_bar.new_conversation_clicked.connect(
                self._on_new_conversation_clicked
            )
            self._title_bar.history_clicked.connect(
                self._on_history_clicked
            )
            self._title_bar.clear_clicked.connect(
                self._on_clear_clicked
            )
            self._title_bar.session_name_changed.connect(
                self._on_session_name_changed
            )
            self._title_bar.compress_clicked.connect(
                self._on_compress_clicked
            )
        
        # 输入区域信号
        if self._input_area:
            self._input_area.send_clicked.connect(self._on_send_clicked)
            self._input_area.stop_clicked.connect(self._on_stop_clicked)
            self._input_area.upload_image_clicked.connect(
                self._on_upload_image_clicked
            )
            self._input_area.select_file_clicked.connect(
                self._on_select_file_clicked
            )
            self._input_area.model_card_clicked.connect(
                self._on_model_card_clicked
            )
            self._input_area.attachment_error.connect(
                self._on_attachment_error
            )
            self._input_area.image_preview_requested.connect(
                self._on_image_preview_requested
            )
            self._input_area.pending_edit_accept_all_requested.connect(
                self._on_pending_edit_accept_all_requested
            )
            self._input_area.pending_edit_reject_all_requested.connect(
                self._on_pending_edit_reject_all_requested
            )
            self._input_area.pending_edit_file_clicked.connect(
                self._on_pending_edit_file_clicked
            )

        if self._message_area:
            self._message_area.file_clicked.connect(
                self._on_message_file_clicked
            )
            self._message_area.link_clicked.connect(
                self._on_link_clicked
            )
            self._message_area.suggestion_clicked.connect(
                self._on_suggestion_clicked
            )
            self._message_area.rollback_requested.connect(
                self._on_rollback_requested
            )
    
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
        if self._rollback_confirmation_dialog is not None:
            self._rollback_confirmation_dialog.close()
            self._rollback_confirmation_dialog.deleteLater()
            self._rollback_confirmation_dialog = None
        if self._warning_dialog is not None:
            self._warning_dialog.close()
            self._warning_dialog.deleteLater()
            self._warning_dialog = None
        if self.pending_workspace_edit_service is not None:
            try:
                self.pending_workspace_edit_service.summary_changed.disconnect(
                    self._on_pending_workspace_edit_summary_changed
                )
            except Exception:
                pass
        if self._view_model:
            self._view_model.cleanup()
        if self._message_area:
            self._message_area.cleanup()

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
    
    def refresh_display(self) -> None:
        """从 ViewModel 获取数据并刷新显示"""
        if self.view_model is None:
            return
        
        # 委托给 MessageArea 渲染消息
        if self._message_area:
            self._message_area.render_conversation(
                self.view_model.messages,
                self.view_model.active_agent_steps,
            )
        
        # 更新状态栏
        self._update_usage_display()
        self._refresh_pending_workspace_edit_summary()

    def _refresh_pending_workspace_edit_summary(self) -> None:
        if self._input_area is None:
            return
        service = self.pending_workspace_edit_service
        if service is None:
            self._input_area.set_pending_workspace_edit_summary_state(
                {
                    "file_count": 0,
                    "added_lines": 0,
                    "deleted_lines": 0,
                    "files": [],
                }
            )
            return
        try:
            self._input_area.set_pending_workspace_edit_summary_state(
                service.get_summary_state()
            )
        except Exception as exc:
            if self.logger:
                self.logger.error(f"Failed to refresh pending workspace edit state: {exc}")
    
    def _update_usage_display(self) -> None:
        """更新上下文占用显示"""
        if self.view_model is None or self._input_area is None:
            return
        
        # 获取完整的使用信息
        usage_info = self.view_model.get_usage_info()
        ratio = usage_info.get("ratio", 0.0)
        current_tokens = usage_info.get("current_tokens", 0)
        max_tokens = usage_info.get("max_tokens", 0)
        input_limit = usage_info.get("input_limit", 0)
        output_reserve = usage_info.get("output_reserve", 0)
        state = usage_info.get("state", "normal")
        
        # 更新输入区域的占用显示
        self._input_area.update_usage(
            ratio,
            current_tokens,
            max_tokens,
            input_limit=input_limit,
            output_reserve=output_reserve,
            state=state,
        )

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
        if self._title_bar and session_name:
            self._title_bar.set_session_name(session_name)
    
    def _on_model_changed(self, event_data: Dict[str, Any]) -> None:
        """
        处理模型变更事件（由应用层统一发布）
        
        更新输入区域的模型卡片显示。
        """
        if self._input_area:
            self._input_area.update_model_display()

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
        if self._input_area:
            self._input_area.set_pending_workspace_edit_summary_state(summary_state)
    
    @pyqtSlot(float)
    def _on_usage_changed(self, ratio: float) -> None:
        """处理上下文占用变化"""
        self._update_usage_display()
    
    @pyqtSlot(bool)
    def _on_can_send_changed(self, can_send: bool) -> None:
        """处理可发送状态变化"""
        self._sync_input_action_state()
    
    @pyqtSlot()
    def _on_stop_requested(self) -> None:
        """处理停止请求信号（来自 ViewModel）"""
        if self._input_area and self._input_area.get_button_mode() != ButtonMode.STOPPING:
            self._input_area.set_button_mode(ButtonMode.STOPPING)
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
        QMessageBox.information(
            self,
            self._get_text("dialog.info.title", "提示"),
            self._get_text(
                "msg.suggest_new_conversation",
                "上下文已接近上限，建议开启新对话以获得更好的体验。"
            )
        )

    # ============================================================
    # 事件处理 - 子组件信号
    # ============================================================
    
    def _on_new_conversation_clicked(self) -> None:
        """处理新开对话按钮点击"""
        self.start_new_conversation()
    
    def _on_history_clicked(self) -> None:
        """处理历史对话按钮点击"""
        self.history_requested.emit()
    
    def _on_clear_clicked(self) -> None:
        """处理清空对话按钮点击"""
        reply = QMessageBox.question(
            self,
            self._get_text("dialog.confirm.title", "确认"),
            self._get_text(
                "msg.confirm_clear_conversation",
                "是否清空当前对话显示？（不影响历史记录）"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.clear_display()

    def request_history(self) -> None:
        self.history_requested.emit()

    def request_clear_display(self) -> None:
        self._on_clear_clicked()

    def request_compress_context(self) -> None:
        self.compress_requested.emit()

    def _on_session_name_changed(self, name: str) -> None:
        """处理会话名称变更"""
        self.session_name_changed.emit(name)
    
    def _on_compress_clicked(self) -> None:
        """处理压缩按钮点击"""
        self.compress_requested.emit()
    
    def _on_send_clicked(self) -> None:
        """处理发送按钮点击"""
        if self._rollback_in_progress:
            return
        asyncio.create_task(self._send_message())
    
    def _on_stop_clicked(self) -> None:
        """处理停止按钮点击"""
        if self.view_model:
            success = self.view_model.request_stop()
            if not success:
                self._sync_input_action_state()
                if self.logger:
                    self.logger.warning("Stop request failed")
    
    def _on_upload_image_clicked(self) -> None:
        """处理上传图片按钮点击"""
        file_filter = "Images (*.png *.jpg *.jpeg *.webp)"
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            self._get_text("dialog.select_image.title", "选择图片"),
            "",
            file_filter
        )
        
        if self._input_area:
            for path in paths:
                self._input_area.add_attachment(path)
    
    def _on_select_file_clicked(self) -> None:
        """处理选择文件按钮点击"""
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            self._get_text("dialog.select_file.title", "选择文件"),
            "",
            "All Files (*.*)"
        )
        
        if self._input_area:
            for path in paths:
                self._input_area.add_attachment(path)

    def _on_model_card_clicked(self) -> None:
        """处理模型卡片点击，打开模型设置对话框"""
        try:
            from presentation.dialogs.model_config_dialog import ModelConfigDialog
            
            dialog = ModelConfigDialog(self)
            if dialog.exec():
                if self._input_area:
                    self._input_area.update_model_display()
                
                if self.logger:
                    self.logger.info("Model configuration updated from conversation panel")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to open model config dialog: {e}")

    def _on_attachment_error(self, message: str) -> None:
        """处理附件错误"""
        QMessageBox.warning(
            self,
            self._get_text("dialog.warning.title", "警告"),
            message
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
        if self._rollback_confirmation_dialog is not None:
            return
        asyncio.create_task(self._confirm_and_perform_rollback(message_id))

    def _open_image_preview(self, image_path: str) -> None:
        if not image_path or not os.path.isfile(image_path):
            return
        from presentation.dialogs.image_preview_dialog import ImagePreviewDialog

        dialog = ImagePreviewDialog(image_path, self)
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
        if self._input_area is None:
            return

        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path):
                self._input_area.add_attachment(path)

    # ============================================================

    async def _send_message(self) -> None:
        """发送消息"""
        if self._input_area is None:
            return
        if self._send_in_progress:
            return

        text = self._input_area.get_text()
        attachments = self._input_area.get_attachments()
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
                    self._input_area.clear()
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
            self._show_warning_dialog(
                error_message or self._get_text("msg.rollback_failed", "撤回失败")
            )
            return

        self._show_rollback_confirmation_dialog(preview, message_id)

    async def _perform_rollback(self, message_id: str) -> None:
        if not message_id or self.view_model is None:
            return
        if self._rollback_in_progress or self._send_in_progress:
            return

        self._rollback_in_progress = True
        self._sync_input_action_state()
        try:
            success, error_message = await self.view_model.rollback_to_message(message_id)
            self._sync_input_action_state()
            if not success:
                self._show_warning_dialog(
                    error_message or self._get_text("msg.rollback_failed", "撤回失败")
                )
        finally:
            self._rollback_in_progress = False
            self._sync_input_action_state()

    def _show_rollback_confirmation_dialog(self, preview: Any, message_id: str) -> None:
        if self._rollback_confirmation_dialog is not None:
            self._rollback_confirmation_dialog.close()
            self._rollback_confirmation_dialog.deleteLater()

        dialog = RollbackConfirmationDialog(preview, self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.finished.connect(
            lambda result, target_message_id=message_id: self._on_rollback_confirmation_finished(
                result,
                target_message_id,
            )
        )
        self._rollback_confirmation_dialog = dialog
        dialog.open()

    def _on_rollback_confirmation_finished(self, result: int, message_id: str) -> None:
        self._rollback_confirmation_dialog = None
        if result != int(QDialog.DialogCode.Accepted):
            return
        if self._rollback_in_progress or self._send_in_progress:
            return
        asyncio.create_task(self._perform_rollback(message_id))

    def _show_warning_dialog(self, message: str) -> None:
        if not message:
            return

        if self._warning_dialog is not None:
            self._warning_dialog.close()
            self._warning_dialog.deleteLater()

        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle(self._get_text("dialog.warning.title", "警告"))
        dialog.setText(message)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.setModal(True)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.finished.connect(self._on_warning_dialog_finished)
        self._warning_dialog = dialog
        dialog.open()

    def _on_warning_dialog_finished(self, result: int) -> None:
        del result
        self._warning_dialog = None

    def _sync_input_action_state(self) -> None:
        if self._input_area is None:
            return
        if self._send_in_progress:
            self._input_area.set_action_status(
                self._get_text("conversation.send.in_progress", "正在发送…")
            )
            self._input_area.set_button_mode(ButtonMode.SEND)
            self._input_area.set_send_enabled(False)
            return
        if self._rollback_in_progress:
            self._input_area.set_action_status(
                self._get_text("conversation.rollback.in_progress", "正在撤回…")
            )
            self._input_area.set_button_mode(ButtonMode.ROLLBACKING)
            self._input_area.set_send_enabled(False)
            return
        if self.view_model and self.view_model.is_loading:
            if self._input_area.get_button_mode() != ButtonMode.STOPPING:
                self._input_area.set_button_mode(ButtonMode.STOP)
                self._input_area.set_action_status(
                    self._get_text("conversation.generate.in_progress", "正在生成…")
                )
            else:
                self._input_area.set_action_status(
                    self._get_text("conversation.stop.in_progress", "正在停止…")
                )
            self._input_area.set_send_enabled(False)
            return
        self._input_area.set_action_status("")
        self._input_area.set_button_mode(ButtonMode.SEND)
        self._input_area.set_send_enabled(self.view_model.can_send if self.view_model else True)

    def add_attachments(self, paths: list[str]) -> None:
        if self._input_area is None:
            return
        for path in paths:
            if isinstance(path, str) and path:
                self._input_area.add_attachment(path)

    def clear_display(self) -> None:
        """清空显示区（不清空 ViewModel 数据）"""
        if self._message_area:
            self._message_area.clear_messages()
        if self._input_area:
            self._input_area.clear_attachments()

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
                if self._input_area:
                    self._input_area.clear_attachments()
                
                if self.logger:
                    self.logger.info(f"New conversation started: {new_session_name}")
            else:
                if self.logger:
                    self.logger.warning(f"Failed to start new conversation: {new_session_name}")
        
        self.new_conversation_requested.emit()

    # ============================================================
    # 国际化
    # ============================================================
    
    def retranslate_ui(self) -> None:
        """刷新 UI 文本"""
        if self._title_bar:
            self._title_bar.retranslate_ui()
        if self._input_area:
            self._input_area.retranslate_ui()
        
        self.refresh_display()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ConversationPanel",
    "PANEL_BACKGROUND",
]
