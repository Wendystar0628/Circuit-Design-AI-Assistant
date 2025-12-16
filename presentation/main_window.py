# Main Window - Application Main Window
"""
主窗口类 - 应用程序主窗口框架

职责：
- 窗口布局管理、面板协调
- 组件初始化
- 事件订阅与分发
- LLM Worker 信号处理和对话面板集成

委托关系：
- 菜单栏创建委托给 MenuManager
- 工具栏创建委托给 ToolbarManager
- 状态栏创建委托给 StatusbarManager
- 窗口状态管理委托给 WindowStateManager
- 会话管理委托给 SessionManager
- 动作处理委托给 ActionHandlers

初始化顺序：
- Phase 2.2，依赖 ServiceLocator（获取 I18nManager 等）

设计原则：
- 单一职责：主窗口类仅负责布局协调和组件初始化
- 延迟获取 ServiceLocator 中的服务
- 所有用户可见文本通过 i18n_manager.get_text() 获取
"""

import json
from typing import Optional, Dict, Any, List

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QSplitter, QLabel, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer

from presentation.menu_manager import MenuManager
from presentation.toolbar_manager import ToolbarManager
from presentation.statusbar_manager import StatusbarManager
from presentation.window_state_manager import WindowStateManager
from presentation.session_manager import SessionManager
from presentation.action_handlers import ActionHandlers


class MainWindow(QMainWindow):
    """
    应用程序主窗口
    
    布局结构：
    - 外层：垂直 QSplitter，分割上部主区域和下部仿真结果区
    - 上部：水平 QSplitter，分割左栏、中栏、右栏
    - 初始比例：左栏 10%、中栏 60%、右栏 30%、下栏 20% 高度
    """

    def __init__(self):
        super().__init__()

        # 延迟获取的服务
        self._i18n_manager = None
        self._event_bus = None
        self._logger = None
        self._context_manager = None
        
        # UI 组件引用
        self._panels: Dict[str, QWidget] = {}
        self._splitters: Dict[str, QSplitter] = {}
        
        # 管理器实例（延迟初始化）
        self._menu_manager: Optional[MenuManager] = None
        self._toolbar_manager: Optional[ToolbarManager] = None
        self._statusbar_manager: Optional[StatusbarManager] = None
        self._window_state_manager: Optional[WindowStateManager] = None
        self._session_manager: Optional[SessionManager] = None
        self._action_handlers: Optional[ActionHandlers] = None
        
        # LLM Worker 实例
        self._llm_worker = None
        
        # 初始化 UI
        self._setup_window()
        self._setup_central_widget()
        self._setup_managers()
        self._setup_llm_worker()
        self._connect_panel_signals()
        
        # 应用国际化文本
        self.retranslate_ui()
        
        # 订阅语言变更事件
        self._subscribe_events()
        
        # 恢复窗口状态
        self._window_state_manager.restore_window_state(
            self._splitters, self._panels
        )
        
        # 延迟恢复会话状态（等待窗口显示后执行）
        QTimer.singleShot(100, self._restore_session)


    # ============================================================
    # 延迟获取服务
    # ============================================================

    @property
    def i18n_manager(self):
        """延迟获取 I18nManager"""
        if self._i18n_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_I18N_MANAGER
                self._i18n_manager = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            except Exception:
                pass
        return self._i18n_manager

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
                self._logger = get_logger("main_window")
            except Exception:
                pass
        return self._logger

    @property
    def context_manager(self):
        """延迟获取 ContextManager"""
        if self._context_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CONTEXT_MANAGER
                self._context_manager = ServiceLocator.get_optional(SVC_CONTEXT_MANAGER)
            except Exception:
                pass
        return self._context_manager

    def _get_text(self, key: str, default: Optional[str] = None) -> str:
        """获取国际化文本"""
        if self.i18n_manager:
            return self.i18n_manager.get_text(key, default)
        return default if default else key

    # ============================================================
    # 窗口初始化
    # ============================================================

    def _setup_window(self):
        """设置窗口基本属性"""
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)

    def _setup_central_widget(self):
        """
        设置中央部件和布局
        
        布局结构：
        - 外层垂直 QSplitter：上部主区域 + 下部仿真结果区
        - 上部水平 QSplitter：左栏 + 中栏 + 右栏
        """
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 外层垂直分割器（上部主区域 + 下部仿真结果）
        self._splitters["vertical"] = QSplitter(Qt.Orientation.Vertical)
        main_layout.addWidget(self._splitters["vertical"])
        
        # 上部水平分割器（左栏 + 中栏 + 右栏）
        self._splitters["horizontal"] = QSplitter(Qt.Orientation.Horizontal)
        self._splitters["vertical"].addWidget(self._splitters["horizontal"])
        
        # 创建四个面板占位
        self._create_panel_placeholders()
        
        # 设置分割比例
        self._setup_splitter_sizes()

    def _create_panel_placeholders(self):
        """创建面板部件"""
        # 左栏 - 文件浏览器（使用实际组件）
        from presentation.panels.file_browser_panel import FileBrowserPanel
        self._panels["file_browser"] = FileBrowserPanel()
        self._panels["file_browser"].setMinimumWidth(150)
        self._splitters["horizontal"].addWidget(self._panels["file_browser"])
        
        # 中栏 - 代码编辑器（使用实际组件）
        from presentation.panels.code_editor_panel import CodeEditorPanel
        self._panels["code_editor"] = CodeEditorPanel()
        self._panels["code_editor"].setMinimumWidth(400)
        self._splitters["horizontal"].addWidget(self._panels["code_editor"])
        
        # 连接文件浏览器和代码编辑器
        self._panels["file_browser"].file_selected.connect(
            self._panels["code_editor"].load_file
        )
        
        # 右栏 - 对话面板（使用实际组件）
        from presentation.panels.conversation_panel import ConversationPanel
        self._panels["chat"] = ConversationPanel()
        self._panels["chat"].setMinimumWidth(250)
        self._splitters["horizontal"].addWidget(self._panels["chat"])
        
        # 下栏 - 仿真结果（占位）
        self._panels["simulation"] = self._create_placeholder_panel("panel.simulation")
        self._panels["simulation"].setMinimumHeight(100)
        self._splitters["vertical"].addWidget(self._panels["simulation"])

    def _create_placeholder_panel(self, title_key: str) -> QWidget:
        """创建占位面板"""
        panel = QWidget()
        panel.setStyleSheet("background-color: #f5f5f5; border: 1px solid #ddd;")
        
        layout = QVBoxLayout(panel)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 占位标签
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #888; font-size: 14px; border: none;")
        label.setProperty("title_key", title_key)
        layout.addWidget(label)
        
        return panel

    def _setup_splitter_sizes(self):
        """设置分割器初始比例"""
        # 水平分割：左栏 10%、中栏 60%、右栏 30%
        total_width = 1400
        self._splitters["horizontal"].setSizes([
            int(total_width * 0.10),  # 左栏
            int(total_width * 0.60),  # 中栏
            int(total_width * 0.30),  # 右栏
        ])
        
        # 垂直分割：上部 80%、下部 20%
        total_height = 900
        self._splitters["vertical"].setSizes([
            int(total_height * 0.80),  # 上部
            int(total_height * 0.20),  # 下部
        ])


    # ============================================================
    # 管理器初始化
    # ============================================================

    def _setup_managers(self):
        """初始化各管理器并创建 UI 组件"""
        # 初始化动作处理器
        self._action_handlers = ActionHandlers(self, self._panels)
        callbacks = self._action_handlers.get_callbacks()
        
        # 添加最近项目相关回调
        callbacks["on_recent_click"] = self._action_handlers.on_recent_project_clicked
        callbacks["on_clear_recent"] = self._action_handlers.on_clear_recent_projects
        
        # 添加对话历史回调
        callbacks["on_show_history"] = self._on_show_history_dialog
        
        # 菜单栏管理器
        self._menu_manager = MenuManager(self)
        self._menu_manager.setup_menus(callbacks)
        
        # 工具栏管理器
        self._toolbar_manager = ToolbarManager(self)
        self._toolbar_manager.setup_toolbar(callbacks)
        
        # 状态栏管理器
        self._statusbar_manager = StatusbarManager(self)
        self._statusbar_manager.setup_statusbar()
        
        # 窗口状态管理器
        self._window_state_manager = WindowStateManager(self)
        
        # 会话管理器
        self._session_manager = SessionManager(self, self._panels)

    def _setup_llm_worker(self):
        """初始化 LLM Worker 并连接信号"""
        try:
            from application.workers.llm_worker import LLMWorker
            self._llm_worker = LLMWorker()
            
            # 连接 Worker 信号
            self._llm_worker.chunk.connect(self._on_llm_chunk)
            self._llm_worker.phase_changed.connect(self._on_llm_phase_changed)
            self._llm_worker.result.connect(self._on_llm_result)
            self._llm_worker.error.connect(self._on_llm_error)
            self._llm_worker.finished.connect(self._on_llm_finished)
            
            if self.logger:
                self.logger.info("LLM Worker initialized")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to initialize LLM Worker: {e}")

    # ============================================================
    # 面板信号连接
    # ============================================================

    def _connect_panel_signals(self):
        """连接面板信号"""
        # 连接代码编辑器面板的打开工作区请求信号
        if "code_editor" in self._panels:
            self._panels["code_editor"].open_workspace_requested.connect(
                self._action_handlers.on_open_workspace
            )
            # 连接撤销/重做状态变化信号
            self._panels["code_editor"].undo_redo_state_changed.connect(
                self._on_undo_redo_state_changed
            )
            # 连接可编辑文件状态变化信号（用于启用/禁用保存按钮）
            self._panels["code_editor"].editable_file_state_changed.connect(
                self._on_editable_file_state_changed
            )
        
        # 连接对话面板信号
        if "chat" in self._panels:
            chat_panel = self._panels["chat"]
            # 消息发送
            chat_panel.message_sent.connect(self._on_message_sent)
            # 压缩请求
            chat_panel.compress_requested.connect(self._on_compress_requested)
            # 文件点击（跳转到代码编辑器）
            chat_panel.file_clicked.connect(self._on_file_clicked)
            # 新开对话请求
            chat_panel.new_conversation_requested.connect(self._on_new_conversation)
            # 历史对话请求
            chat_panel.history_requested.connect(self._on_show_history_dialog)
            # 会话名称变更
            chat_panel.session_name_changed.connect(self._on_session_name_changed)
            # 注意：不在这里调用 chat_panel.initialize()
            # 对话面板的初始化延迟到 EVENT_INIT_COMPLETE 事件后执行
            # 因为 ContextManager 在 Phase 3.4 才注册，此时（Phase 2.2）还不可用

    # ============================================================
    # 国际化支持
    # ============================================================

    def retranslate_ui(self):
        """刷新所有 UI 文本（语言切换时调用）"""
        # 窗口标题
        self.setWindowTitle(self._get_text("app.title", "Circuit AI Design Assistant"))
        
        # 调用各管理器的 retranslate_ui 方法
        if self._menu_manager:
            self._menu_manager.retranslate_ui()
            self._update_recent_menu()
        
        if self._toolbar_manager:
            self._toolbar_manager.retranslate_ui()
        
        if self._statusbar_manager:
            self._statusbar_manager.retranslate_ui()
        
        # 面板占位文本
        self._update_panel_placeholders()

    def _update_panel_placeholders(self):
        """更新面板占位文本"""
        placeholder_panels = ["chat", "simulation"]
        for panel_name in placeholder_panels:
            panel = self._panels.get(panel_name)
            if panel:
                label = panel.findChild(QLabel)
                if label:
                    title_key = label.property("title_key")
                    if title_key:
                        title = self._get_text(title_key, panel_name)
                        hint = self._get_text("status.open_workspace", "Please open a workspace folder")
                        label.setText(f"{title}\n\n{hint}")

    # ============================================================
    # 事件订阅
    # ============================================================

    def _subscribe_events(self):
        """订阅事件"""
        if self.event_bus:
            from shared.event_types import (
                EVENT_LANGUAGE_CHANGED,
                EVENT_STATE_PROJECT_OPENED,
                EVENT_STATE_PROJECT_CLOSED,
                EVENT_INIT_COMPLETE,
            )
            self.event_bus.subscribe(EVENT_LANGUAGE_CHANGED, self._on_language_changed)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_OPENED, self._on_project_opened)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_CLOSED, self._on_project_closed)
            # 订阅初始化完成事件，用于延迟初始化对话面板
            self.event_bus.subscribe(EVENT_INIT_COMPLETE, self._on_init_complete)

    def _on_init_complete(self, event_data: Dict[str, Any]):
        """
        初始化完成事件处理
        
        在 Phase 3 延迟初始化完成后调用，此时 ContextManager 已注册。
        用于初始化需要依赖 Phase 3 服务的组件。
        """
        # 初始化对话面板（此时 ContextManager 已可用）
        if "chat" in self._panels:
            self._panels["chat"].initialize()
            if self.logger:
                self.logger.info("ConversationPanel initialized after EVENT_INIT_COMPLETE")
        
        # 恢复对话会话（延迟执行，确保对话面板已初始化）
        QTimer.singleShot(100, self._restore_conversation_session)

    def _restore_conversation_session(self):
        """恢复对话会话"""
        if self._session_manager:
            self._session_manager.restore_conversation_session()

    def _on_language_changed(self, event_data: Dict[str, Any]):
        """语言变更事件处理"""
        self.retranslate_ui()
        if self.logger:
            new_lang = event_data.get("new_language", "unknown")
            self.logger.info(f"UI language changed to: {new_lang}")

    def _on_project_opened(self, event_data: Dict[str, Any]):
        """项目打开事件处理"""
        data = event_data.get("data", {})
        if isinstance(data, dict):
            project_path = data.get("path", "")
        else:
            project_path = ""
        
        # 启用相关功能 - 菜单
        if self._menu_manager:
            self._menu_manager.set_action_enabled("file_close", True)
            self._menu_manager.set_action_enabled("file_save", True)
            self._menu_manager.set_action_enabled("file_save_all", True)
        
        # 启用相关功能 - 工具栏
        if self._toolbar_manager:
            self._toolbar_manager.set_action_enabled("toolbar_save", True)
            self._toolbar_manager.set_action_enabled("toolbar_save_all", True)
        
        # 更新状态栏
        if self._statusbar_manager:
            self._statusbar_manager.set_project_info(project_path)
        
        # 更新最近打开菜单
        self._update_recent_menu()
        
        if self.logger:
            self.logger.info(f"Project opened event received: {project_path}")

    def _on_project_closed(self, event_data: Dict[str, Any]):
        """项目关闭事件处理"""
        # 禁用相关功能 - 菜单
        if self._menu_manager:
            self._menu_manager.set_action_enabled("file_close", False)
            self._menu_manager.set_action_enabled("file_save", False)
            self._menu_manager.set_action_enabled("file_save_all", False)
        
        # 禁用相关功能 - 工具栏
        if self._toolbar_manager:
            self._toolbar_manager.set_action_enabled("toolbar_save", False)
            self._toolbar_manager.set_action_enabled("toolbar_save_all", False)
        
        # 更新状态栏
        if self._statusbar_manager:
            self._statusbar_manager.set_project_info(None)
        
        # 关闭代码编辑器中的所有文件
        if "code_editor" in self._panels:
            self._panels["code_editor"].close_all_tabs()
        
        if self.logger:
            self.logger.info("Project closed event received")


    # ============================================================
    # 会话恢复
    # ============================================================

    def _restore_session(self):
        """恢复会话状态"""
        if self._session_manager:
            self._session_manager.restore_session_state(
                self._action_handlers._open_project
            )

    # ============================================================
    # 窗口状态管理
    # ============================================================

    def closeEvent(self, event):
        """窗口关闭事件"""
        # 保存窗口状态
        if self._window_state_manager:
            self._window_state_manager.save_window_state(
                self._splitters, self._panels
            )
        
        # 保存会话状态
        if self._session_manager:
            self._session_manager.save_session_state()
        
        super().closeEvent(event)

    # ============================================================
    # 面板显示/隐藏
    # ============================================================

    def _toggle_panel(self, panel_name: str, visible: bool):
        """切换面板显示/隐藏"""
        if self._action_handlers:
            self._action_handlers.on_toggle_panel(panel_name, visible)

    # ============================================================
    # 辅助方法
    # ============================================================

    def _get_recent_projects(self) -> list:
        """获取最近项目列表"""
        recent_projects = []
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_PROJECT_SERVICE, SVC_CONFIG_MANAGER
            
            project_service = ServiceLocator.get_optional(SVC_PROJECT_SERVICE)
            if project_service:
                recent_projects = project_service.get_recent_projects(filter_invalid=False)
            else:
                config_manager = ServiceLocator.get_optional(SVC_CONFIG_MANAGER)
                if config_manager:
                    import os
                    paths = config_manager.get("recent_projects", [])
                    for path in paths[:10]:
                        recent_projects.append({
                            "path": path,
                            "name": os.path.basename(path),
                            "exists": os.path.isdir(path),
                        })
        except Exception:
            pass
        return recent_projects

    def _update_recent_menu(self):
        """更新最近打开子菜单"""
        if not self._menu_manager:
            return
        
        recent_projects = self._get_recent_projects()
        callbacks = {
            "on_recent_click": self._action_handlers.on_recent_project_clicked,
            "on_clear_recent": self._action_handlers.on_clear_recent_projects,
        }
        self._menu_manager.update_recent_menu(recent_projects, callbacks)

    # ============================================================
    # 信号处理
    # ============================================================

    def _on_undo_redo_state_changed(self, can_undo: bool, can_redo: bool):
        """撤销/重做状态变化处理"""
        if self._menu_manager:
            self._menu_manager.set_action_enabled("edit_undo", can_undo)
            self._menu_manager.set_action_enabled("edit_redo", can_redo)

    def _on_editable_file_state_changed(self, has_editable_file: bool):
        """可编辑文件状态变化处理（用于启用/禁用保存按钮）"""
        # 启用/禁用菜单保存按钮
        if self._menu_manager:
            self._menu_manager.set_action_enabled("file_save", has_editable_file)
            self._menu_manager.set_action_enabled("file_save_all", has_editable_file)
        
        # 启用/禁用工具栏保存按钮
        if self._toolbar_manager:
            self._toolbar_manager.set_action_enabled("toolbar_save", has_editable_file)
            self._toolbar_manager.set_action_enabled("toolbar_save_all", has_editable_file)

    # ============================================================
    # 对话面板信号处理
    # ============================================================

    def _on_message_sent(self, text: str, attachments: List[Dict[str, Any]]):
        """
        处理用户发送消息
        
        Args:
            text: 消息文本
            attachments: 附件列表
        """
        if not text.strip() and not attachments:
            return
        
        if self.logger:
            self.logger.info(f"User message sent: {text[:50]}...")
        
        # 发布工作流锁定事件
        if self.event_bus:
            from shared.event_types import EVENT_WORKFLOW_LOCKED
            self.event_bus.publish(EVENT_WORKFLOW_LOCKED, {"source": "llm_call"})
        
        # 更新状态栏
        if self._statusbar_manager:
            self._statusbar_manager.set_status(
                self._get_text("status.llm_processing", "LLM processing...")
            )
            self._statusbar_manager.set_worker_status("llm", "running")
        
        # 通过 ContextManager 添加用户消息
        if self.context_manager:
            self.context_manager.add_user_message(text, attachments)
        
        # 构建 LLM 请求
        self._send_llm_request()

    def _send_llm_request(self):
        """构建并发送 LLM 请求"""
        if not self._llm_worker:
            if self.logger:
                self.logger.error("LLM Worker not available")
            self._on_llm_finished()
            return
        
        # 从 ContextManager 获取消息列表
        messages = []
        if self.context_manager:
            messages = self.context_manager.get_messages_for_llm()
        
        if not messages:
            if self.logger:
                self.logger.warning("No messages to send to LLM")
            self._on_llm_finished()
            return
        
        # 设置请求参数
        self._llm_worker.set_request(
            messages=messages,
            streaming=True,
            thinking=None,  # 从配置读取
        )
        
        # 启动 Worker
        self._llm_worker.start()

    def _on_compress_requested(self):
        """处理压缩上下文请求"""
        try:
            from presentation.dialogs.context_compress_dialog import ContextCompressDialog
            dialog = ContextCompressDialog(self)
            dialog.exec()
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to open compress dialog: {e}")

    def _on_file_clicked(self, file_path: str):
        """处理文件点击（跳转到代码编辑器）"""
        if "code_editor" in self._panels:
            self._panels["code_editor"].load_file(file_path)

    def _on_new_conversation(self):
        """处理新开对话请求"""
        # 确认对话框
        result = QMessageBox.question(
            self,
            self._get_text("dialog.confirm", "Confirm"),
            self._get_text(
                "dialog.new_conversation.confirm",
                "Archive current conversation and start a new one?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if result != QMessageBox.StandardButton.Yes:
            return
        
        # 归档当前对话并重置
        if self.context_manager:
            self.context_manager.archive_and_reset()
        
        # 刷新对话面板
        if "chat" in self._panels:
            self._panels["chat"].refresh_display()
        
        # 发布对话重置事件
        if self.event_bus:
            from shared.event_types import EVENT_CONVERSATION_RESET
            self.event_bus.publish(EVENT_CONVERSATION_RESET, {})
        
        if self.logger:
            self.logger.info("Conversation archived and reset")

    def _on_show_history_dialog(self):
        """显示对话历史对话框"""
        try:
            from presentation.dialogs.history_dialog import HistoryDialog
            dialog = HistoryDialog(self)
            dialog.exec()
        except ImportError:
            # 对话框尚未实现
            QMessageBox.information(
                self,
                self._get_text("dialog.info", "Information"),
                self._get_text(
                    "dialog.history.not_implemented",
                    "History dialog will be implemented soon."
                )
            )
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to open history dialog: {e}")

    def _on_session_name_changed(self, name: str):
        """处理会话名称变更"""
        if self.logger:
            self.logger.info(f"Session name changed to: {name}")
        
        # 保存会话名称到配置
        if self._session_manager:
            self._session_manager.set_current_session_name(name)

    # ============================================================
    # LLM Worker 信号处理
    # ============================================================

    def _on_llm_chunk(self, chunk_data: str):
        """
        处理 LLM 流式输出块
        
        Args:
            chunk_data: JSON 格式的数据块 {"type": "reasoning"|"content", "text": str}
        """
        try:
            data = json.loads(chunk_data)
            chunk_type = data.get("type", "content")
            text = data.get("text", "")
            
            # 直接调用对话面板处理流式输出
            if "chat" in self._panels:
                self._panels["chat"].handle_stream_chunk(chunk_type, text)
                
        except json.JSONDecodeError as e:
            if self.logger:
                self.logger.warning(f"Failed to parse LLM chunk: {e}")

    def _on_llm_phase_changed(self, phase: str):
        """
        处理 LLM 阶段切换
        
        Args:
            phase: 新阶段 ("reasoning" -> "content")
        """
        if "chat" in self._panels:
            self._panels["chat"].handle_phase_change(phase)

    def _on_llm_result(self, result: Dict[str, Any]):
        """
        处理 LLM 完成结果
        
        Args:
            result: 完整响应结果
        """
        content = result.get("content", "")
        reasoning_content = result.get("reasoning_content", "")
        tool_calls = result.get("tool_calls")
        usage = result.get("usage")
        is_partial = result.get("is_partial", False)
        
        if self.logger:
            self.logger.info(
                f"LLM result received: content_len={len(content)}, "
                f"reasoning_len={len(reasoning_content)}, partial={is_partial}"
            )
        
        # 通过 ContextManager 添加助手消息
        if self.context_manager and content:
            self.context_manager.add_assistant_message(
                content=content,
                reasoning_content=reasoning_content,
                tool_calls=tool_calls,
                usage=usage,
            )
        
        # 直接调用对话面板完成流式输出并刷新显示
        if "chat" in self._panels:
            self._panels["chat"].finish_stream(result)

    def _on_llm_error(self, error_msg: str, error: object):
        """
        处理 LLM 错误
        
        Args:
            error_msg: 错误消息
            error: 错误对象
        """
        if self.logger:
            self.logger.error(f"LLM error: {error_msg}")
        
        # 显示错误提示
        QMessageBox.warning(
            self,
            self._get_text("dialog.error", "Error"),
            error_msg
        )
        
        # 通知对话面板
        if "chat" in self._panels:
            self._panels["chat"].handle_error(error_msg)

    def _on_llm_finished(self):
        """处理 LLM 调用完成（无论成功或失败）"""
        # 发布工作流解锁事件
        if self.event_bus:
            from shared.event_types import EVENT_WORKFLOW_UNLOCKED
            self.event_bus.publish(EVENT_WORKFLOW_UNLOCKED, {"source": "llm_call"})
        
        # 更新状态栏
        if self._statusbar_manager:
            self._statusbar_manager.set_status(
                self._get_text("status.ready", "Ready")
            )
            self._statusbar_manager.set_worker_status("llm", "idle")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "MainWindow",
]
