# Main Window - Application Main Window
"""
主窗口类 - 应用程序主窗口框架

职责：
- 窗口布局管理、面板协调
- 组件初始化
- 事件订阅与分发

委托关系：
- 菜单栏创建委托给 MenuManager
- 仿真命令状态委托给 SimulationCommandController
- 窗口状态管理委托给 WindowStateManager
- 会话管理委托给 SessionManager
- 动作处理委托给 ActionHandlers
- 面板生命周期管理委托给 PanelManager
- 右栏统一面板委托给 React 右栏宿主

初始化顺序：
- Phase 2.2，依赖 ServiceLocator（获取 I18nManager 等）

设计原则：
- 单一职责：主窗口类仅负责布局协调和组件初始化
- 延迟获取 ServiceLocator 中的服务
- 所有用户可见文本通过 i18n_manager.get_text() 获取
- 面板管理通过 PanelManager 统一处理
- 右栏使用单一 React 面板统一承载对话与索引库
"""

from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QSplitter
)
from PyQt6.QtCore import Qt, QTimer

from presentation.web_menu_manager import MenuManager
from presentation.simulation_command_controller import SimulationCommandController
from presentation.window_state_manager import WindowStateManager
from presentation.session_manager import SessionManager
from presentation.action_handlers import ActionHandlers
from presentation.core.panel_manager import PanelManager, PanelRegion


class MainWindow(QMainWindow):
    """
    应用程序主窗口
    
    布局结构：
    - 外层：水平 QSplitter，分割左侧工作区与右栏统一面板
    - 左侧：垂直 QSplitter，分割上部工作区与下部仿真结果区
    - 上部工作区：水平 QSplitter，分割文件浏览器与代码编辑器
    - 右栏：统一 React 面板承载对话与索引库
    - 初始比例：左侧约 70%、右栏约 30%、仿真结果区约 22% 高度
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
        
        # 管理器实例（延迟初始化）
        self._menu_manager: Optional[MenuManager] = None
        self._simulation_command_controller: Optional[SimulationCommandController] = None
        self._window_state_manager: Optional[WindowStateManager] = None
        self._session_manager: Optional[SessionManager] = None
        self._action_handlers: Optional[ActionHandlers] = None
        
        # 初始化 UI（按照设计规范的顺序）
        self._setup_window()
        self._setup_panel_manager()
        self._setup_central_widget()
        self._setup_managers()
        self._connect_panel_signals()
        self._initialize_panels()
        
        # 应用国际化文本
        self.retranslate_ui()
        
        # 订阅事件
        self._subscribe_events()
        
        # 恢复窗口状态
        self._window_state_manager.restore_window_state(
            self._splitters, self._panels
        )
        self._sync_restored_panel_visibility()
        
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
        - 外层水平 QSplitter：左侧工作区 + 右栏标签页
        - 左侧垂直 QSplitter：上部工作区 + 下部仿真结果区
        - 上部水平 QSplitter：文件浏览器 + 代码编辑器
        """
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._splitters["main_horizontal"] = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self._splitters["main_horizontal"])

        self._splitters["left_vertical"] = QSplitter(Qt.Orientation.Vertical)
        self._splitters["workspace_horizontal"] = QSplitter(Qt.Orientation.Horizontal)

        self._splitters["left_vertical"].addWidget(self._splitters["workspace_horizontal"])
        self._splitters["main_horizontal"].addWidget(self._splitters["left_vertical"])
        
        self._create_panels()
        
        # 设置分割比例
        self._setup_splitter_sizes()

    def _create_panels(self):
        """创建面板部件并注册到 PanelManager"""
        # 左栏 - 文件浏览器
        from presentation.panels.web_file_browser_panel import FileBrowserPanel
        file_browser = FileBrowserPanel()
        file_browser.setMinimumWidth(150)
        self._splitters["workspace_horizontal"].addWidget(file_browser)
        self._panels["file_browser"] = file_browser
        self._panel_manager.register_panel(
            "file_browser", file_browser, PanelRegion.LEFT,
            title_key="panel.file_browser"
        )
        
        # 中栏 - 代码编辑器
        from presentation.panels.workspace_code_editor_panel import CodeEditorPanel
        code_editor = CodeEditorPanel()
        code_editor.setMinimumWidth(400)
        self._splitters["workspace_horizontal"].addWidget(code_editor)
        self._panels["code_editor"] = code_editor
        self._panel_manager.register_panel(
            "code_editor", code_editor, PanelRegion.CENTER,
            title_key="panel.code_editor"
        )
        
        # 连接文件浏览器和代码编辑器
        file_browser.file_selected.connect(code_editor.load_file)
        code_editor.workspace_file_state_changed.connect(file_browser.set_workspace_file_state)
        file_browser.set_workspace_file_state(code_editor.get_workspace_file_state())
        
        # 右栏 - 统一 React 面板
        self._create_right_panel()
        
        # 下栏 - 仿真结果面板
        from presentation.panels.simulation.simulation_tab import SimulationTab
        simulation_tab = SimulationTab()
        simulation_tab.setMinimumHeight(100)
        self._splitters["left_vertical"].addWidget(simulation_tab)
        self._panels["simulation"] = simulation_tab
        self._panel_manager.register_panel(
            "simulation", simulation_tab, PanelRegion.BOTTOM,
            title_key="panel.simulation"
        )

    def _create_right_panel(self):
        """创建统一右栏面板"""
        from presentation.panels.conversation_panel import ConversationPanel
        right_panel = ConversationPanel()
        right_panel.setMinimumWidth(250)
        self._panels["right_panel"] = right_panel
        self._panel_manager.register_panel(
            "right_panel", right_panel, PanelRegion.RIGHT,
            title_key="panel.conversation"
        )
        self._splitters["main_horizontal"].addWidget(right_panel)

    def _setup_splitter_sizes(self):
        """设置分割器初始比例"""
        total_width = 1400
        left_width = int(total_width * 0.70)
        right_width = int(total_width * 0.30)

        self._splitters["main_horizontal"].setSizes([
            left_width,
            right_width,
        ])

        self._splitters["workspace_horizontal"].setSizes([
            int(left_width * 0.15),
            int(left_width * 0.85),
        ])

        total_height = 900
        self._splitters["left_vertical"].setSizes([
            int(total_height * 0.78),
            int(total_height * 0.22),
        ])

    # ============================================================
    # 管理器初始化
    # ============================================================

    def _setup_managers(self):
        """初始化各管理器并创建 UI 组件"""
        # 初始化动作处理器
        self._action_handlers = ActionHandlers(self, self._panels)
        self._simulation_command_controller = SimulationCommandController(self)
        callbacks = self._action_handlers.get_callbacks()
        callbacks["on_run_simulation"] = self._simulation_command_controller.run_simulation
        
        # 添加最近项目相关回调
        callbacks["on_recent_click"] = self._action_handlers.on_recent_project_clicked
        callbacks["on_clear_recent"] = self._action_handlers.on_clear_recent_projects
        
        # 添加对话历史回调
        callbacks["on_show_history"] = self._on_show_history_dialog
        
        # 菜单栏管理器
        self._menu_manager = MenuManager(self)
        self._menu_manager.setup_menus(callbacks)
        self._refresh_recent_menu()
        if self._simulation_command_controller:
            self._simulation_command_controller.bind_menu_manager(self._menu_manager)
        
        # 窗口状态管理器
        self._window_state_manager = WindowStateManager(self)
        
        # 会话管理器
        self._session_manager = SessionManager(self, self._panels)

    # ============================================================
    # 面板信号连接
    # ============================================================

    def _connect_panel_signals(self):
        """连接面板信号"""
        if self._action_handlers is None:
            return

        if "code_editor" in self._panels:
            editor = self._panels["code_editor"]
            editor.open_workspace_requested.connect(
                self._action_handlers.on_open_workspace
            )
            editor.workspace_file_state_changed.connect(
                self._on_workspace_file_state_changed
            )
            editor.editable_file_state_changed.connect(
                self._on_editable_file_state_changed
            )
            if self._simulation_command_controller:
                self._simulation_command_controller.bind_code_editor(editor)
            self._on_workspace_file_state_changed(editor.get_workspace_file_state())

        right_panel = self.get_right_panel()
        if right_panel is not None:
            right_panel.file_clicked.connect(self._on_file_clicked)
            right_panel.compress_requested.connect(self._on_compress_requested)

    def _initialize_panels(self) -> None:
        initialized = set()
        for panel in self._panels.values():
            panel_identity = id(panel)
            if panel_identity in initialized:
                continue
            initialized.add(panel_identity)
            initialize = getattr(panel, "initialize", None)
            if callable(initialize):
                initialize()

    # ============================================================
    # 对话面板信号处理
    # ============================================================

    def _on_file_clicked(self, file_path: str):
        """处理文件点击（跳转到代码编辑器）"""
        self.toggle_panel("code_editor", True)
        if "code_editor" in self._panels:
            self._panels["code_editor"].load_file(file_path)

    def _on_show_history_dialog(self):
        """显示对话历史面板"""
        self.activate_right_panel("conversation")
        panel = self.get_right_panel()
        if panel is None:
            return
        try:
            panel.request_history()
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to open conversation history surface: {e}")

    def get_right_panel(self):
        from presentation.panels.conversation_panel import ConversationPanel

        panel = self._panels.get("right_panel")
        return panel if isinstance(panel, ConversationPanel) else None

    def open_model_config_surface(self) -> None:
        self.activate_right_panel("conversation")
        panel = self.get_right_panel()
        if panel is None:
            return
        try:
            panel.open_model_config()
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to open model config surface: {e}")

    def _on_compress_requested(self):
        """处理压缩上下文请求，显示压缩对话框"""
        self.activate_right_panel("conversation")
        try:
            from presentation.dialogs.context_compress_dialog import ContextCompressDialog
            
            dialog = ContextCompressDialog(self)
            dialog.load_preview()
            
            if dialog.exec():
                if self.logger:
                    self.logger.info("Context compression confirmed")

                right_panel = self.get_right_panel()
                if right_panel is not None:
                    right_panel.refresh_display()
            else:
                if self.logger:
                    self.logger.info("Context compression cancelled")
                    
        except ImportError as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                self._get_text("dialog.warning.title", "Warning"),
                self._get_text(
                    "dialog.compress.import_error",
                    "Failed to load Context Compress Dialog module."
                )
            )
            if self.logger:
                self.logger.error(f"Failed to import ContextCompressDialog: {e}")
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(
                self,
                self._get_text("dialog.error.title", "Error"),
                self._get_text(
                    "dialog.compress.error",
                    f"Failed to open context compress dialog: {str(e)}"
                )
            )
            if self.logger:
                self.logger.error(f"Failed to open context compress dialog: {e}")

    def _refresh_recent_menu(self) -> None:
        if self._menu_manager is None or self._action_handlers is None:
            return

        recent_projects = []
        project_service = self._action_handlers.project_service
        if project_service is not None:
            try:
                recent_projects = project_service.get_recent_projects(filter_invalid=False)
            except Exception as exc:
                if self.logger:
                    self.logger.warning(f"Failed to load recent projects: {exc}")

        self._menu_manager.update_recent_menu(
            recent_projects,
            {
                "on_recent_click": self._action_handlers.on_recent_project_clicked,
                "on_clear_recent": self._action_handlers.on_clear_recent_projects,
            },
        )

    def _sync_restored_panel_visibility(self) -> None:
        if self._panel_manager is None:
            return

        for panel_id in ("file_browser", "code_editor", "simulation"):
            panel_info = self._panel_manager.get_panel_info(panel_id)
            panel = self._panels.get(panel_id)
            if panel_info is None or panel is None:
                continue
            actual_visible = not panel.isHidden()
            if actual_visible == panel_info.visible:
                continue
            if actual_visible:
                self._panel_manager.show_panel(panel_id)
            else:
                self._panel_manager.hide_panel(panel_id)

    def toggle_panel(self, panel_id: str, visible: Optional[bool] = None) -> bool:
        if panel_id in {"conversation", "rag"}:
            if visible is False:
                if self.logger:
                    self.logger.warning(
                        f"Right-side surface '{panel_id}' cannot be hidden individually"
                    )
                return False
            return self.activate_right_panel(panel_id)

        if self._panel_manager is None:
            return False

        panel_info = self._panel_manager.get_panel_info(panel_id)
        if panel_info is None:
            if self.logger:
                self.logger.warning(f"Unknown panel id: {panel_id}")
            return False

        if panel_info.region == PanelRegion.RIGHT:
            if panel_id == "right_panel":
                if visible is False:
                    if self.logger:
                        self.logger.warning(
                            "Unified right panel cannot be hidden individually"
                        )
                    return False
                if visible:
                    self._panel_manager.show_panel(panel_id)
                return self._panel_manager.is_panel_visible(panel_id)
            if visible is False:
                if self.logger:
                    self.logger.warning(
                        f"Right-side tab panel '{panel_id}' cannot be hidden individually"
                    )
                return False
            return self.activate_right_panel(panel_id)

        if visible is None:
            return self._panel_manager.toggle_panel(panel_id)
        if visible:
            self._panel_manager.show_panel(panel_id)
        else:
            self._panel_manager.hide_panel(panel_id)
        return self._panel_manager.is_panel_visible(panel_id)

    def activate_right_panel(self, panel_id: str) -> bool:
        if panel_id not in {"conversation", "rag"}:
            if self.logger:
                self.logger.warning(f"Unknown right panel id: {panel_id}")
            return False

        panel = self.get_right_panel()
        if panel is None:
            return False
        return bool(panel.activate_surface(panel_id))

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self._get_text("app.title", "Circuit Design AI"))

        if self._menu_manager is not None:
            self._menu_manager.retranslate_ui()
        if self._simulation_command_controller is not None:
            self._simulation_command_controller.retranslate_ui()

        translated = set()
        for panel in self._panels.values():
            panel_identity = id(panel)
            if panel_identity in translated:
                continue
            translated.add(panel_identity)
            retranslate = getattr(panel, "retranslate_ui", None)
            if callable(retranslate):
                retranslate()

    def _subscribe_events(self) -> None:
        if self.event_bus is None:
            return

        try:
            from shared.event_types import (
                EVENT_INIT_COMPLETE,
                EVENT_LANGUAGE_CHANGED,
                EVENT_STATE_PROJECT_OPENED,
                EVENT_STATE_PROJECT_CLOSED,
            )

            self.event_bus.subscribe(EVENT_INIT_COMPLETE, self._on_init_complete)
            self.event_bus.subscribe(EVENT_LANGUAGE_CHANGED, self._on_language_changed)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_OPENED, self._on_project_opened)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_CLOSED, self._on_project_closed)
        except Exception as exc:
            if self.logger:
                self.logger.warning(f"Failed to subscribe main window events: {exc}")

    def _unsubscribe_events(self) -> None:
        if self.event_bus is None:
            return

        try:
            from shared.event_types import (
                EVENT_INIT_COMPLETE,
                EVENT_LANGUAGE_CHANGED,
                EVENT_STATE_PROJECT_OPENED,
                EVENT_STATE_PROJECT_CLOSED,
            )

            self.event_bus.unsubscribe(EVENT_INIT_COMPLETE, self._on_init_complete)
            self.event_bus.unsubscribe(EVENT_LANGUAGE_CHANGED, self._on_language_changed)
            self.event_bus.unsubscribe(EVENT_STATE_PROJECT_OPENED, self._on_project_opened)
            self.event_bus.unsubscribe(EVENT_STATE_PROJECT_CLOSED, self._on_project_closed)
        except Exception:
            pass

    def _on_init_complete(self, event_data: Dict[str, Any]) -> None:
        del event_data
        self._refresh_recent_menu()
        if self._session_manager is None or self._action_handlers is None:
            return

        try:
            self._session_manager.restore_session_state(
                self._action_handlers.on_recent_project_clicked
            )
        except Exception as exc:
            if self.logger:
                self.logger.error(f"Failed to restore session state: {exc}")

    def _on_language_changed(self, event_data: Dict[str, Any]) -> None:
        del event_data
        self.retranslate_ui()

    def _on_project_opened(self, event_data: Dict[str, Any]) -> None:
        del event_data
        if self._menu_manager is not None:
            self._menu_manager.set_action_enabled("file_close", True)
        self._refresh_recent_menu()

    def _on_project_closed(self, event_data: Dict[str, Any]) -> None:
        del event_data
        if self._menu_manager is not None:
            self._menu_manager.set_action_enabled("file_close", False)
        self._on_workspace_file_state_changed({})
        self._refresh_recent_menu()

    def _on_workspace_file_state_changed(self, state: Dict[str, Any]) -> None:
        if self._menu_manager is None:
            return

        payload = state if isinstance(state, dict) else {}
        has_active_editor = bool(payload.get("has_active_editor", False))
        has_active_editable = bool(payload.get("has_active_editable", False))
        has_any_dirty = bool(payload.get("has_any_dirty", False))
        has_right_surface = self.get_right_panel() is not None
        has_copy_target = has_active_editor or has_right_surface

        self._menu_manager.set_action_enabled("file_save", has_active_editable)
        self._menu_manager.set_action_enabled("file_save_all", has_any_dirty)
        self._menu_manager.set_action_enabled("edit_undo", has_active_editable)
        self._menu_manager.set_action_enabled("edit_redo", has_active_editable)
        self._menu_manager.set_action_enabled("edit_cut", has_active_editable)
        self._menu_manager.set_action_enabled("edit_copy", has_copy_target)
        self._menu_manager.set_action_enabled("edit_paste", has_active_editable)
        self._menu_manager.set_action_enabled("edit_select_all", has_copy_target)

    def _on_editable_file_state_changed(self, has_editable: bool) -> None:
        del has_editable
        editor = self._panels.get("code_editor")
        if editor is None or not hasattr(editor, "get_workspace_file_state"):
            self._on_workspace_file_state_changed({})
            return
        self._on_workspace_file_state_changed(editor.get_workspace_file_state())

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

    def closeEvent(self, event) -> None:
        if self._window_state_manager is not None:
            self._window_state_manager.save_window_state(self._splitters, self._panels)
        if self._session_manager is not None:
            self._session_manager.save_session_state()

        if self._simulation_command_controller is not None:
            # Symmetric with the subscribe in the controller's __init__.
            # Without this the EventBus keeps a reference to the handler
            # methods, which keeps the controller (and transitively the
            # main window) alive across window reopen cycles in tests.
            self._simulation_command_controller.shutdown()

        self._unsubscribe_events()

        cleaned = set()
        for panel in self._panels.values():
            panel_identity = id(panel)
            if panel_identity in cleaned:
                continue
            cleaned.add(panel_identity)
            cleanup = getattr(panel, "cleanup", None)
            if callable(cleanup):
                cleanup()

        if self._session_manager is not None:
            self._session_manager.dispose()

        super().closeEvent(event)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "MainWindow",
]
