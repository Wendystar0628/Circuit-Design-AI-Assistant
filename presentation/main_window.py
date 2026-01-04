# Main Window - Application Main Window
"""
主窗口类 - 应用程序主窗口框架

职责：
- 窗口布局管理、面板协调
- 组件初始化
- 事件订阅与分发

委托关系：
- 菜单栏创建委托给 MenuManager
- 工具栏创建委托给 ToolbarManager
- 状态栏创建委托给 StatusbarManager
- 窗口状态管理委托给 WindowStateManager
- 会话管理委托给 SessionManager
- 动作处理委托给 ActionHandlers
- 面板生命周期管理委托给 PanelManager
- 右栏标签页管理委托给 TabController

初始化顺序：
- Phase 2.2，依赖 ServiceLocator（获取 I18nManager 等）

设计原则：
- 单一职责：主窗口类仅负责布局协调和组件初始化
- 延迟获取 ServiceLocator 中的服务
- 所有用户可见文本通过 i18n_manager.get_text() 获取
- 面板管理通过 PanelManager 统一处理
- 右栏使用 QTabWidget + TabController 管理多个标签页
"""

from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QSplitter, QLabel, QTabWidget
)
from PyQt6.QtCore import Qt, QTimer

from presentation.menu_manager import MenuManager
from presentation.toolbar_manager import ToolbarManager
from presentation.statusbar_manager import StatusbarManager
from presentation.window_state_manager import WindowStateManager
from presentation.session_manager import SessionManager
from presentation.action_handlers import ActionHandlers
from presentation.core.panel_manager import PanelManager, PanelRegion
from presentation.core.tab_controller import (
    TabController, TAB_CONVERSATION, TAB_DEVTOOLS
)


class MainWindow(QMainWindow):
    """
    应用程序主窗口
    
    布局结构：
    - 外层：垂直 QSplitter，分割上部主区域和下部仿真结果区
    - 上部：水平 QSplitter，分割左栏、中栏、右栏
    - 右栏：QTabWidget 承载多个标签页（对话、调试等）
    - 初始比例：左栏 10%、中栏 60%、右栏 30%、下栏 20% 高度
    """

    def __init__(self):
        super().__init__()

        # 延迟获取的服务
        self._i18n_manager = None
        self._event_bus = None
        self._logger = None
        self._config_manager = None
        
        # UI 组件引用
        self._panels: Dict[str, QWidget] = {}  # 内部使用，外部通过 PanelManager 访问
        self._splitters: Dict[str, QSplitter] = {}
        
        # 面板管理器
        self._panel_manager: Optional[PanelManager] = None
        
        # 右栏标签页控制器
        self._tab_controller: Optional[TabController] = None
        
        # 管理器实例（延迟初始化）
        self._menu_manager: Optional[MenuManager] = None
        self._toolbar_manager: Optional[ToolbarManager] = None
        self._statusbar_manager: Optional[StatusbarManager] = None
        self._window_state_manager: Optional[WindowStateManager] = None
        self._session_manager: Optional[SessionManager] = None
        self._action_handlers: Optional[ActionHandlers] = None
        
        # 初始化 UI（按照设计规范的顺序）
        self._setup_window()
        self._setup_panel_manager()
        self._setup_central_widget()
        self._setup_managers()
        self._connect_panel_signals()
        
        # 应用国际化文本
        self.retranslate_ui()
        
        # 订阅事件
        self._subscribe_events()
        
        # 恢复窗口状态
        self._window_state_manager.restore_window_state(
            self._splitters, self._panels
        )
        
        # 注意：会话状态恢复（项目路径、打开的文件）移到 _on_init_complete 中
        # 确保在 Phase 3 延迟初始化完成后执行，此时 ProjectService 等服务已可用

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
    def config_manager(self):
        """延迟获取 ConfigManager"""
        if self._config_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CONFIG_MANAGER
                self._config_manager = ServiceLocator.get_optional(SVC_CONFIG_MANAGER)
            except Exception:
                pass
        return self._config_manager

    @property
    def panel_manager(self) -> Optional[PanelManager]:
        """获取面板管理器"""
        return self._panel_manager

    @property
    def tab_controller(self) -> Optional[TabController]:
        """获取右栏标签页控制器"""
        return self._tab_controller

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

    def _setup_panel_manager(self):
        """初始化面板管理器"""
        self._panel_manager = PanelManager()

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
        
        # 创建四个面板
        self._create_panels()
        
        # 设置分割比例
        self._setup_splitter_sizes()

    def _create_panels(self):
        """创建面板部件并注册到 PanelManager"""
        # 左栏 - 文件浏览器
        from presentation.panels.file_browser_panel import FileBrowserPanel
        file_browser = FileBrowserPanel()
        file_browser.setMinimumWidth(150)
        self._splitters["horizontal"].addWidget(file_browser)
        self._panels["file_browser"] = file_browser
        self._panel_manager.register_panel(
            "file_browser", file_browser, PanelRegion.LEFT,
            title_key="panel.file_browser"
        )
        
        # 中栏 - 代码编辑器
        from presentation.panels.code_editor_panel import CodeEditorPanel
        code_editor = CodeEditorPanel()
        code_editor.setMinimumWidth(400)
        self._splitters["horizontal"].addWidget(code_editor)
        self._panels["code_editor"] = code_editor
        self._panel_manager.register_panel(
            "code_editor", code_editor, PanelRegion.CENTER,
            title_key="panel.code_editor"
        )
        
        # 连接文件浏览器和代码编辑器
        file_browser.file_selected.connect(code_editor.load_file)
        
        # 右栏 - 使用 QTabWidget 承载多个面板
        self._create_right_panel_tabs()
        
        # 下栏 - 仿真结果（占位）
        simulation_panel = self._create_placeholder_panel("panel.simulation")
        simulation_panel.setMinimumHeight(100)
        self._splitters["vertical"].addWidget(simulation_panel)
        self._panels["simulation"] = simulation_panel
        self._panel_manager.register_panel(
            "simulation", simulation_panel, PanelRegion.BOTTOM,
            title_key="panel.simulation"
        )

    def _create_right_panel_tabs(self):
        """创建右栏标签页容器和面板"""
        # 创建标签页容器
        right_tab_widget = QTabWidget()
        right_tab_widget.setMinimumWidth(250)
        right_tab_widget.setDocumentMode(True)  # 更现代的外观
        
        # 初始化标签页控制器
        self._tab_controller = TabController()
        self._tab_controller.bind_tab_widget(right_tab_widget)
        
        # 注册对话面板
        from presentation.panels.conversation_panel import ConversationPanel
        chat_panel = ConversationPanel()
        self._tab_controller.register_tab(
            TAB_CONVERSATION,
            chat_panel,
            self._get_text("panel.chat", "Chat"),
            "resources/icons/panel/chat.svg"
        )
        self._panels["chat"] = chat_panel
        self._panel_manager.register_panel(
            "conversation", chat_panel, PanelRegion.RIGHT,
            title_key="panel.chat"
        )
        
        # 注册调试面板（根据配置）
        if self._should_show_devtools():
            from presentation.panels.devtools_panel import DevToolsPanel
            devtools_panel = DevToolsPanel()
            self._tab_controller.register_tab(
                TAB_DEVTOOLS,
                devtools_panel,
                self._get_text("panel.devtools", "DevTools"),
                "resources/icons/panel/bug.svg"
            )
            self._panels["devtools"] = devtools_panel
            self._panel_manager.register_panel(
                "devtools", devtools_panel, PanelRegion.RIGHT,
                title_key="panel.devtools"
            )
        
        # 添加到分割器
        self._splitters["horizontal"].addWidget(right_tab_widget)
        self._panels["right_tabs"] = right_tab_widget

    def _should_show_devtools(self) -> bool:
        """检查是否应显示调试面板"""
        if self.config_manager:
            return self.config_manager.get("debug.show_devtools_panel", True)
        return True  # 默认显示

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
        
        # 添加 Prompt 编辑器回调
        callbacks["on_prompt_editor"] = self._on_prompt_editor_triggered
        
        # 添加面板切换回调
        callbacks["on_toggle_panel"] = self._on_toggle_panel
        
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

    # ============================================================
    # 面板信号连接
    # ============================================================

    def _connect_panel_signals(self):
        """连接面板信号"""
        # 连接代码编辑器面板信号
        if "code_editor" in self._panels:
            editor = self._panels["code_editor"]
            editor.open_workspace_requested.connect(
                self._action_handlers.on_open_workspace
            )
            editor.undo_redo_state_changed.connect(
                self._on_undo_redo_state_changed
            )
            editor.editable_file_state_changed.connect(
                self._on_editable_file_state_changed
            )
        
        # 连接对话面板信号
        # 注意：不在这里调用 chat_panel.initialize()
        # 对话面板的初始化延迟到 EVENT_INIT_COMPLETE 事件后执行
        # 因为 ContextManager 在 Phase 3.4 才注册，此时（Phase 2.2）还不可用
        if "chat" in self._panels:
            chat_panel = self._panels["chat"]
            chat_panel.file_clicked.connect(self._on_file_clicked)
            chat_panel.new_conversation_requested.connect(self._on_new_conversation)
            chat_panel.history_requested.connect(self._on_show_history_dialog)
            chat_panel.session_name_changed.connect(self._on_session_name_changed)

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
        
        # 刷新右栏标签页标题
        if self._tab_controller:
            self._retranslate_tab_titles()
        
        # 面板占位文本
        self._update_panel_placeholders()

    def _retranslate_tab_titles(self):
        """刷新右栏标签页标题"""
        if not self._tab_controller:
            return
        
        # 更新对话标签页标题
        self._tab_controller.update_tab_title(
            TAB_CONVERSATION,
            self._get_text("panel.conversation", "对话")
        )
        
        # 更新调试标签页标题（如果存在）
        if "devtools" in self._panels:
            self._tab_controller.update_tab_title(
                TAB_DEVTOOLS,
                self._get_text("panel.devtools", "调试")
            )

    def _update_panel_placeholders(self):
        """更新面板占位文本"""
        placeholder_panels = ["simulation"]
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
        
        在 Phase 3 延迟初始化完成后调用，此时所有服务已注册。
        用于初始化需要依赖 Phase 3 服务的组件。
        """
        # 初始化对话面板（此时 ContextManager 已可用）
        if "chat" in self._panels:
            self._panels["chat"].initialize()
            if self.logger:
                self.logger.info("ConversationPanel initialized after EVENT_INIT_COMPLETE")
        
        # 恢复布局状态
        if self._panel_manager:
            self._panel_manager.restore_layout_state()
        
        # 恢复会话状态（项目路径、打开的文件）
        # 必须在 Phase 3 完成后执行，因为 ProjectService 在 Phase 3.3 初始化
        # 注意：对话会话恢复在 _on_project_opened 中触发，确保项目已打开
        self._restore_session()

    def _restore_conversation_session(self):
        """恢复对话会话"""
        if self._session_manager:
            self._session_manager.restore_full_session()

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
        
        # 恢复对话会话（项目打开后立即恢复）
        # 延迟 100ms 确保 SessionState.project_root 已更新
        QTimer.singleShot(100, self._restore_conversation_session)
        
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
        # 保存布局状态
        if self._panel_manager:
            self._panel_manager.save_layout_state()
        
        # 保存窗口状态
        if self._window_state_manager:
            self._window_state_manager.save_window_state(
                self._splitters, self._panels
            )
        
        # 保存会话状态（编辑器会话）
        if self._session_manager:
            self._session_manager.save_session_state()
            # 保存对话会话
            self._session_manager.save_current_conversation()
        
        super().closeEvent(event)

    # ============================================================
    # 面板显示/隐藏
    # ============================================================

    def _on_toggle_panel(self, panel_id: str, visible: Optional[bool] = None):
        """
        切换面板显示/隐藏
        
        Args:
            panel_id: 面板 ID
            visible: 指定可见性，None 表示切换
        """
        if not self._panel_manager:
            return
        
        if visible is None:
            self._panel_manager.toggle_panel(panel_id)
        elif visible:
            self._panel_manager.show_panel(panel_id)
        else:
            self._panel_manager.hide_panel(panel_id)

    def show_panel(self, panel_id: str):
        """显示面板"""
        if self._panel_manager:
            self._panel_manager.show_panel(panel_id)

    def hide_panel(self, panel_id: str):
        """隐藏面板"""
        if self._panel_manager:
            self._panel_manager.hide_panel(panel_id)

    def toggle_panel(self, panel_id: str) -> bool:
        """切换面板可见性，返回新状态"""
        if self._panel_manager:
            return self._panel_manager.toggle_panel(panel_id)
        return False

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

    def _on_file_clicked(self, file_path: str):
        """处理文件点击（跳转到代码编辑器）"""
        if "code_editor" in self._panels:
            self._panels["code_editor"].load_file(file_path)

    def _on_new_conversation(self):
        """处理新开对话请求"""
        if self.logger:
            self.logger.info("New conversation requested")

    def _on_show_history_dialog(self):
        """显示对话历史对话框"""
        try:
            from presentation.dialogs.history_dialog import HistoryDialog
            from PyQt6.QtWidgets import QMessageBox
            dialog = HistoryDialog(self)
            dialog.exec()
        except ImportError:
            from PyQt6.QtWidgets import QMessageBox
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
        
        if self._session_manager:
            self._session_manager.set_current_session_name(name)

    def _on_prompt_editor_triggered(self):
        """显示 Prompt 模板编辑器对话框"""
        try:
            from presentation.dialogs.prompt_editor import PromptEditorDialog
            dialog = PromptEditorDialog(self)
            dialog.exec()
        except ImportError as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                self._get_text("dialog.warning.title", "Warning"),
                self._get_text(
                    "dialog.prompt_editor.import_error",
                    "Failed to load Prompt Editor module."
                )
            )
            if self.logger:
                self.logger.error(f"Failed to import PromptEditorDialog: {e}")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to open prompt editor dialog: {e}")

    # ============================================================
    # 公共接口
    # ============================================================

    def get_panel(self, panel_id: str) -> Optional[QWidget]:
        """
        获取指定面板实例
        
        Args:
            panel_id: 面板 ID
            
        Returns:
            面板实例，不存在则返回 None
        """
        if self._panel_manager:
            return self._panel_manager.get_panel(panel_id)
        return None

    def get_statusbar_manager(self) -> Optional[StatusbarManager]:
        """获取状态栏管理器"""
        return self._statusbar_manager


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "MainWindow",
]
