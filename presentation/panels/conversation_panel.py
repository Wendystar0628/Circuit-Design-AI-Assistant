# Conversation Panel - Main Panel Class (Refactored)
"""
对话面板主类（重构版）

职责：
- 协调各子组件（TitleBar、MessageArea、StatusBar、InputArea、AttachmentManager）
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

import os
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QMessageBox,
    QFileDialog,
)

# 从子模块导入组件
from presentation.panels.conversation import (
    ConversationViewModel,
    TitleBar,
    MessageArea,
    InputArea,
    AttachmentManager,
    ButtonMode,
    SUGGESTION_STATE_ACTIVE,
    SUGGESTION_STATE_SELECTED,
    SUGGESTION_STATE_EXPIRED,
    ALLOWED_IMAGE_EXTENSIONS,
)


# ============================================================
# 常量定义
# ============================================================

PANEL_BACKGROUND = "#ffffff"
PRIMARY_COLOR = "#4a9eff"
USER_MESSAGE_BG = "#e3f2fd"
ASSISTANT_MESSAGE_BG = "#f8f9fa"
SYSTEM_MESSAGE_COLOR = "#6c757d"
WARNING_COLOR = "#ff9800"
CRITICAL_COLOR = "#f44336"


# ============================================================
# ConversationPanel 类
# ============================================================

class ConversationPanel(QWidget):
    """
    对话面板主类（重构版）
    
    协调各子组件，管理面板整体布局，通过 ViewModel 获取数据。
    """
    
    # 信号定义
    message_sent = pyqtSignal(str, list)           # 用户发送消息 (text, attachments)
    suggestion_selected = pyqtSignal(str)          # 用户点击建议按钮 (suggestion_id)
    file_selected = pyqtSignal(list)               # 用户选择阅读文件 (paths)
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
        self._session_state = None
        
        # 子组件引用
        self._title_bar: Optional[TitleBar] = None
        self._message_area: Optional[MessageArea] = None
        self._input_area: Optional[InputArea] = None
        self._attachment_manager: Optional[AttachmentManager] = None
        
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
        
        # 3. 附件管理器（隐藏，用于管理附件数据）
        self._attachment_manager = AttachmentManager(self)
        main_layout.addWidget(self._attachment_manager)
        
        # 4. 输入区域
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
        
        # 附件管理器信号
        if self._attachment_manager:
            self._attachment_manager.attachments_changed.connect(
                self._on_attachments_changed
            )
            self._attachment_manager.attachment_error.connect(
                self._on_attachment_error
            )
    
    def _connect_view_model_signals(self) -> None:
        """连接 ViewModel 信号"""
        if self._view_model is None:
            return
        
        self._view_model.messages_changed.connect(self._on_messages_changed)
        self._view_model.stream_updated.connect(self._on_stream_updated)
        self._view_model.stream_finished.connect(self._on_stream_finished)
        self._view_model.usage_changed.connect(self._on_usage_changed)
        self._view_model.can_send_changed.connect(self._on_can_send_changed)
        self._view_model.suggestion_added.connect(self._on_suggestion_added)
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
        
        # 订阅事件
        self._subscribe_events()
        
        # 初始刷新
        self.refresh_display()
    
    def cleanup(self) -> None:
        """清理资源"""
        self._unsubscribe_events()
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
                EVENT_STATE_PROJECT_OPENED,
                EVENT_STATE_PROJECT_CLOSED,
                EVENT_LANGUAGE_CHANGED,
                EVENT_WORKFLOW_LOCKED,
                EVENT_WORKFLOW_UNLOCKED,
                EVENT_ITERATION_AWAITING_CONFIRMATION,
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
            self.event_bus.subscribe(
                EVENT_WORKFLOW_LOCKED, self._on_workflow_locked
            )
            self.event_bus.subscribe(
                EVENT_WORKFLOW_UNLOCKED, self._on_workflow_unlocked
            )
            # 注意：EVENT_LLM_CHUNK 和 EVENT_LLM_COMPLETE 由 ViewModel 处理
            # ConversationPanel 通过 ViewModel 的信号（stream_updated, stream_finished）响应
            self.event_bus.subscribe(
                EVENT_ITERATION_AWAITING_CONFIRMATION,
                self._on_iteration_awaiting
            )
            # 订阅会话变更事件，更新标题栏
            self.event_bus.subscribe(
                EVENT_SESSION_CHANGED, self._on_session_changed
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
                EVENT_STATE_PROJECT_OPENED,
                EVENT_STATE_PROJECT_CLOSED,
                EVENT_LANGUAGE_CHANGED,
                EVENT_WORKFLOW_LOCKED,
                EVENT_WORKFLOW_UNLOCKED,
                EVENT_ITERATION_AWAITING_CONFIRMATION,
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
                EVENT_WORKFLOW_LOCKED, self._on_workflow_locked
            )
            self.event_bus.unsubscribe(
                EVENT_WORKFLOW_UNLOCKED, self._on_workflow_unlocked
            )
            self.event_bus.unsubscribe(
                EVENT_ITERATION_AWAITING_CONFIRMATION,
                self._on_iteration_awaiting
            )
            self.event_bus.unsubscribe(
                EVENT_SESSION_CHANGED, self._on_session_changed
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
            self._message_area.render_messages(self.view_model.messages)
        
        # 更新状态栏
        self._update_usage_display()
    
    def _update_usage_display(self) -> None:
        """更新上下文占用显示"""
        if self.view_model is None or self._input_area is None:
            return
        
        # 获取完整的使用信息
        usage_info = self.view_model.get_usage_info()
        ratio = usage_info.get("ratio", 0.0)
        current_tokens = usage_info.get("current_tokens", 0)
        max_tokens = usage_info.get("max_tokens", 0)
        
        # 更新输入区域的占用显示
        self._input_area.update_usage(ratio, current_tokens, max_tokens)

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
    
    def _on_workflow_locked(self, event_data: Dict[str, Any]) -> None:
        """处理工作流锁定事件"""
        if self._input_area:
            self._input_area.set_send_enabled(False)
    
    def _on_workflow_unlocked(self, event_data: Dict[str, Any]) -> None:
        """处理工作流解锁事件"""
        if self._input_area:
            self._input_area.set_send_enabled(True)
    
    def _on_iteration_awaiting(self, event_data: Dict[str, Any]) -> None:
        """处理迭代等待确认事件"""
        # ViewModel 的 _on_iteration_awaiting 会调用 append_suggestion_message
        # 它会触发 messages_changed 信号，由 _on_messages_changed 处理刷新
        pass
    
    def _on_session_changed(self, event_data: Dict[str, Any]) -> None:
        """
        处理会话变更事件（由 SessionStateManager 发布）
        
        更新标题栏显示会话名称。
        注意：不在这里刷新消息显示，由 ViewModel 的 messages_changed 信号触发。
        """
        data = event_data.get("data", {})
        session_name = data.get("session_name", "")
        action = data.get("action", "")
        
        if self.logger:
            self.logger.debug(f"Session changed in panel: {action}, name={session_name}")
        
        # 只更新标题栏，不刷新消息显示（避免重复刷新）
        if self._title_bar and session_name:
            self._title_bar.set_session_name(session_name)
    
    def _on_model_changed(self, event_data: Dict[str, Any]) -> None:
        """
        处理模型变更事件（由 ModelRegistry 或 ModelConfigDialog 发布）
        
        更新输入区域的模型卡片显示。
        """
        if self._input_area:
            # 尝试从事件数据中获取 display_name
            data = event_data.get("data", {})
            display_name = data.get("display_name")
            
            if display_name:
                self._input_area.update_model_display(display_name)
            else:
                # 没有 display_name，让 InputArea 自己从配置获取
                self._input_area.update_model_display()

    # ============================================================
    # 事件处理 - ViewModel 信号
    # ============================================================
    
    @pyqtSlot()
    def _on_messages_changed(self) -> None:
        """处理消息列表变化"""
        self.refresh_display()
    
    @pyqtSlot(str, str)
    def _on_stream_updated(self, content: str, reasoning: str) -> None:
        """处理流式内容更新"""
        if self._message_area:
            self._message_area.update_streaming(content, reasoning)
    
    @pyqtSlot()
    def _on_stream_finished(self) -> None:
        """处理流式输出完成"""
        # 只结束流式输出，不刷新显示
        # 刷新由 messages_changed 信号触发的 _on_messages_changed 处理
        if self._message_area:
            self._message_area.finish_streaming()
    
    @pyqtSlot(float)
    def _on_usage_changed(self, ratio: float) -> None:
        """处理上下文占用变化"""
        self._update_usage_display()
    
    @pyqtSlot(bool)
    def _on_can_send_changed(self, can_send: bool) -> None:
        """处理可发送状态变化"""
        if self._input_area:
            if can_send:
                # 恢复发送模式（停止完成或工作流解锁时）
                self._input_area.set_button_mode(ButtonMode.SEND)
                self._input_area.set_send_enabled(True)
            else:
                # 禁用发送（工作流锁定时）
                self._input_area.set_send_enabled(False)
    
    @pyqtSlot()
    def _on_stop_requested(self) -> None:
        """处理停止请求信号（来自 ViewModel）"""
        # InputArea 已在点击时切换到 STOPPING 模式
        # 这里可以更新状态栏等其他 UI
        if self.logger:
            self.logger.debug("Stop requested, UI updated")
    
    @pyqtSlot(dict)
    def _on_stop_completed(self, result: dict) -> None:
        """
        处理停止完成信号（来自 ViewModel）
        
        此时 ViewModel 已经：
        1. 处理了部分响应
        2. 重置了 StopController
        3. 发出了 can_send_changed(True) 信号
        
        这里只需要刷新显示。
        """
        # 刷新显示（显示部分响应消息）
        self.refresh_display()
        
        if self.logger:
            saved = result.get("saved", False)
            self.logger.info(f"Stop completed, partial saved: {saved}")
    
    @pyqtSlot(str)
    def _on_suggestion_added(self, message_id: str) -> None:
        """处理建议选项消息添加"""
        # 不需要调用 refresh_display，因为 append_suggestion_message 
        # 已经触发了 messages_changed 信号，会由 _on_messages_changed 处理
        if self._message_area:
            self._message_area.scroll_to_bottom()
    
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
        # 直接开始新对话，无需确认（当前会话自动保存）
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
    
    def _on_session_name_changed(self, name: str) -> None:
        """处理会话名称变更"""
        self.session_name_changed.emit(name)
        if self.view_model and hasattr(self.view_model, 'set_session_name'):
            self.view_model.set_session_name(name)
    
    def _on_compress_clicked(self) -> None:
        """处理压缩按钮点击"""
        self.compress_requested.emit()
        if self.view_model:
            self.view_model.request_compress()
    
    def _on_send_clicked(self) -> None:
        """处理发送按钮点击"""
        self._send_message()
    
    def _on_stop_clicked(self) -> None:
        """处理停止按钮点击"""
        if self.view_model:
            success = self.view_model.request_stop()
            if not success:
                # 停止请求失败，恢复按钮状态
                if self._input_area:
                    self._input_area.set_button_mode(ButtonMode.SEND)
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
        
        # 添加到 InputArea 的附件列表
        if self._input_area:
            for path in paths:
                self._input_area.add_attachment(path, "image")
    
    def _on_select_file_clicked(self) -> None:
        """处理选择文件按钮点击"""
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            self._get_text("dialog.select_file.title", "选择文件"),
            "",
            "All Files (*.*)"
        )
        
        # 添加到 InputArea 的附件列表
        if self._input_area:
            for path in paths:
                self._input_area.add_attachment(path, "file")
        
        if paths:
            self.file_selected.emit(paths)
    
    def _on_model_card_clicked(self) -> None:
        """处理模型卡片点击，打开模型设置对话框"""
        try:
            from presentation.dialogs.model_config_dialog import ModelConfigDialog
            
            dialog = ModelConfigDialog(self)
            if dialog.exec():
                # 用户保存了配置，更新模型卡片显示
                if self._input_area:
                    self._input_area.update_model_display()
                
                if self.logger:
                    self.logger.info("Model configuration updated from conversation panel")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to open model config dialog: {e}")
    
    def _on_attachments_changed(self, count: int) -> None:
        """处理附件数量变化"""
        # 可以在这里更新输入区域的附件预览
        pass
    
    def _on_attachment_error(self, message: str) -> None:
        """处理附件错误"""
        QMessageBox.warning(
            self,
            self._get_text("dialog.warning.title", "警告"),
            message
        )


    # ============================================================
    # 拖放处理
    # ============================================================
    
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """处理拖入事件"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def dropEvent(self, event: QDropEvent) -> None:
        """处理放下事件"""
        if self._attachment_manager is None:
            return
        
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path):
                ext = os.path.splitext(path)[1].lower()
                if ext in ALLOWED_IMAGE_EXTENSIONS:
                    self._attachment_manager.add_attachment(path, "image")
                else:
                    self._attachment_manager.add_attachment(path, "file")

    # ============================================================
    # 公共方法
    # ============================================================
    
    def _send_message(self) -> None:
        """发送消息"""
        if self._input_area is None:
            return
        
        text = self._input_area.get_text().strip()
        if not text:
            return
        
        # 检查是否可以发送
        if self.view_model and not self.view_model.can_send:
            return
        
        # 获取附件（从 InputArea 获取）
        attachments = self._input_area.get_attachments()
        
        # 清空输入和附件
        self._input_area.clear()
        
        # 通过 ViewModel 发送
        if self.view_model:
            success = self.view_model.send_message(text, attachments)
            if success:
                # 切换按钮为停止模式
                self._input_area.set_button_mode(ButtonMode.STOP)
                self.message_sent.emit(text, attachments)
    
    def clear_display(self) -> None:
        """清空显示区（不清空 ViewModel 数据）"""
        if self._message_area:
            self._message_area.clear_messages()
        if self._attachment_manager:
            self._attachment_manager.clear_attachments()
    
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
            # 委托给 ViewModel，ViewModel 再委托给 SessionStateManager
            success, new_session_name = self.view_model.request_new_session()
            
            if success:
                # 清空 ViewModel 显示数据
                self.view_model.clear()
                
                # 清空显示
                self.clear_display()
                
                # 更新标题栏显示新会话名称
                if new_session_name and self._title_bar:
                    self._title_bar.set_session_name(new_session_name)
                
                if self.logger:
                    self.logger.info(f"New conversation started: {new_session_name}")
            else:
                if self.logger:
                    self.logger.warning(f"Failed to start new conversation: {new_session_name}")
        
        # 发出信号
        self.new_conversation_requested.emit()
    
    def _save_current_conversation(self, session_name: str) -> None:
        """
        保存当前对话
        
        Args:
            session_name: 会话名称
        """
        if not session_name:
            return
        
        # 获取项目路径
        project_path = None
        if self.session_state:
            project_path = self.session_state.project_root
        
        if not project_path:
            if self.logger:
                self.logger.debug("No project path, skip save")
            return
        
        # 通过 SessionStateManager 保存
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_SESSION_STATE_MANAGER, SVC_CONTEXT_MANAGER
            
            session_manager = ServiceLocator.get_optional(SVC_SESSION_STATE_MANAGER)
            context_manager = ServiceLocator.get_optional(SVC_CONTEXT_MANAGER)
            
            if session_manager and context_manager:
                state = context_manager._get_internal_state()
                success = session_manager.save_current_session(state, project_path)
                if success:
                    if self.logger:
                        self.logger.info(f"对话已保存: {session_name}")
                else:
                    if self.logger:
                        self.logger.warning("保存失败")
        except Exception as e:
            if self.logger:
                self.logger.error(f"保存对话时出错: {e}")
    
    def _create_new_session_file(self, session_name: str) -> None:
        """
        创建新会话文件
        
        Args:
            session_name: 新会话名称
        """
        if not session_name:
            return
        
        # 获取项目路径
        project_path = None
        if self.session_state:
            project_path = self.session_state.project_root
        
        if not project_path:
            return
        
        # 通过 SessionStateManager 创建新会话
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_SESSION_STATE_MANAGER
            
            session_manager = ServiceLocator.get_optional(SVC_SESSION_STATE_MANAGER)
            if session_manager:
                session_manager.create_session(project_path)
        except Exception as e:
            if self.logger:
                self.logger.warning(f"创建新会话文件失败: {e}")
    
    def handle_stream_chunk(self, chunk_type: str, text: str) -> None:
        """
        处理流式输出块（由 MainWindow 调用）
        
        Args:
            chunk_type: 内容类型 ("reasoning" | "content")
            text: 文本内容
        """
        if self._message_area:
            self._message_area.append_stream_chunk(chunk_type, text)
    
    def handle_phase_change(self, phase: str) -> None:
        """
        处理阶段切换（由 MainWindow 调用）
        
        Args:
            phase: 新阶段 ("searching" | "reasoning" | "content")
        """
        if not self._message_area:
            return
        
        if phase == "searching":
            # 开始搜索阶段
            self._message_area.start_searching()
        elif phase == "content":
            # 从思考阶段切换到内容阶段，更新思考状态显示
            self._message_area.finish_thinking()
    
    def handle_search_complete(self, results: List[Dict[str, Any]]) -> None:
        """
        处理联网搜索完成（由 MainWindow 调用）
        
        Args:
            results: 搜索结果列表
        """
        if self._message_area:
            self._message_area.finish_searching(len(results))
            self._message_area.update_search_results(results)
    
    def finish_stream(self, result: Dict[str, Any]) -> None:
        """
        完成流式输出（由 MainWindow 调用）
        
        Args:
            result: LLM 完整响应结果
        
        注意：助手消息已在 MainWindow._on_llm_result() 中通过 ContextManager 添加，
        这里只需要结束流式输出并刷新显示，不需要重复添加消息。
        """
        # 结束流式输出气泡
        if self._message_area:
            self._message_area.finish_streaming()
        
        # 更新 ViewModel 状态（不添加消息，消息已由 ContextManager 添加）
        if self.view_model:
            self.view_model._is_loading = False
            self.view_model._current_stream_content = ""
            self.view_model._current_reasoning_content = ""
            self.view_model.can_send_changed.emit(True)
        
        # 刷新显示（从 ContextManager 获取最新消息）
        self.refresh_display()
    
    def handle_error(self, error_msg: str) -> None:
        """
        处理错误（由 MainWindow 调用）
        
        Args:
            error_msg: 错误消息
        """
        if self._message_area and self._message_area.is_streaming():
            self._message_area.finish_streaming()
        
        if self.logger:
            self.logger.error(f"LLM error in conversation panel: {error_msg}")
    
    def get_user_input(self) -> str:
        """获取用户输入"""
        if self._input_area:
            return self._input_area.get_text()
        return ""
    
    def get_attachments(self) -> List[Dict[str, Any]]:
        """获取附件列表"""
        if self._attachment_manager:
            return self._attachment_manager.get_attachments()
        return []
    
    def set_session_name(self, name: str) -> None:
        """设置会话名称显示"""
        if self._title_bar:
            self._title_bar.set_session_name(name)
    
    def get_session_name(self) -> str:
        """获取当前会话名称"""
        if self._title_bar:
            return self._title_bar.get_session_name()
        return ""
    
    def append_suggestion_message(
        self,
        suggestions: List[Dict[str, Any]],
        status_summary: str = ""
    ) -> None:
        """追加建议选项消息"""
        if self.view_model:
            self.view_model.append_suggestion_message(suggestions, status_summary)
    
    def mark_suggestion_selected(self, suggestion_id: str) -> None:
        """标记建议选项已选择"""
        if self.view_model:
            self.view_model.mark_suggestion_selected(suggestion_id)
    
    def mark_suggestion_expired(self) -> None:
        """标记建议选项已过期"""
        if self.view_model:
            self.view_model.mark_suggestion_expired()

    # ============================================================
    # 国际化
    # ============================================================
    
    def retranslate_ui(self) -> None:
        """刷新 UI 文本"""
        if self._title_bar:
            self._title_bar.retranslate_ui()
        if self._input_area:
            self._input_area.retranslate_ui()
        
        # 刷新显示
        self.refresh_display()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ConversationPanel",
    # 常量
    "PANEL_BACKGROUND",
    "PRIMARY_COLOR",
    "USER_MESSAGE_BG",
    "ASSISTANT_MESSAGE_BG",
    "SYSTEM_MESSAGE_COLOR",
    "WARNING_COLOR",
    "CRITICAL_COLOR",
]
