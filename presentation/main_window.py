# Main Window - Application Main Window (Skeleton Version)
"""
主窗口类（骨架版）- 应用程序主窗口框架

职责：
- 窗口布局管理、面板协调
- 欢迎遮罩层
- 窗口状态持久化
- 事件订阅与分发

委托关系：
- 菜单栏创建委托给 MenuManager
- 工具栏创建委托给 ToolbarManager
- 状态栏创建委托给 StatusbarManager

初始化顺序：
- Phase 2.2，依赖 ServiceLocator（获取 I18nManager 等）

设计原则：
- 单一职责：主窗口类仅负责布局协调和事件处理
- 延迟获取 ServiceLocator 中的服务
- 所有用户可见文本通过 i18n_manager.get_text() 获取
"""

from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QSplitter, QLabel, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt

from presentation.menu_manager import MenuManager
from presentation.toolbar_manager import ToolbarManager
from presentation.statusbar_manager import StatusbarManager


class MainWindow(QMainWindow):
    """
    应用程序主窗口（骨架版）
    
    布局结构：
    - 外层：垂直 QSplitter，分割上部主区域和下部仿真结果区
    - 上部：水平 QSplitter，分割左栏、中栏、右栏
    - 初始比例：左栏 10%、中栏 60%、右栏 30%、下栏 20% 高度
    """

    def __init__(self):
        super().__init__()

        # 延迟获取的服务
        self._i18n_manager = None
        self._config_manager = None
        self._app_state = None
        self._event_bus = None
        self._logger = None
        self._project_service = None
        
        # 管理器实例
        self._menu_manager: Optional[MenuManager] = None
        self._toolbar_manager: Optional[ToolbarManager] = None
        self._statusbar_manager: Optional[StatusbarManager] = None
        
        # UI 组件引用
        self._panels: Dict[str, QWidget] = {}
        self._splitters: Dict[str, QSplitter] = {}
        

        
        # 初始化 UI
        self._setup_window()
        self._setup_central_widget()
        self._setup_managers()
        self._connect_panel_signals()
        
        # 应用国际化文本
        self.retranslate_ui()
        
        # 订阅语言变更事件
        self._subscribe_events()
        
        # 恢复窗口状态
        self._restore_window_state()
        
        # 延迟恢复会话状态（等待窗口显示后执行）
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(100, self._restore_session_state)

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
    def app_state(self):
        """延迟获取 AppState"""
        if self._app_state is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_APP_STATE
                self._app_state = ServiceLocator.get_optional(SVC_APP_STATE)
            except Exception:
                pass
        return self._app_state

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
    def project_service(self):
        """延迟获取 ProjectService"""
        if self._project_service is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_PROJECT_SERVICE
                self._project_service = ServiceLocator.get_optional(SVC_PROJECT_SERVICE)
            except Exception:
                pass
        return self._project_service

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
        
        # 右栏 - 对话面板（占位）
        self._panels["chat"] = self._create_placeholder_panel("panel.chat")
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
        # 准备回调函数
        callbacks = {
            "on_open_workspace": self._on_open_workspace,
            "on_close_workspace": self._on_close_workspace,
            "on_save_file": self._on_save_file,
            "on_save_all_files": self._on_save_all_files,
            "on_editor_undo": self._on_editor_undo,
            "on_editor_redo": self._on_editor_redo,
            "on_undo_iteration": self._on_undo_iteration,
            "on_toggle_panel": self._toggle_panel,
            "on_api_config": self._on_api_config,
            "on_help_docs": self._on_help_docs,
            "on_about": self._on_about,
        }
        
        # 菜单栏管理器
        self._menu_manager = MenuManager(self)
        self._menu_manager.setup_menus(callbacks)
        
        # 工具栏管理器
        self._toolbar_manager = ToolbarManager(self)
        self._toolbar_manager.setup_toolbar(callbacks)
        
        # 状态栏管理器
        self._statusbar_manager = StatusbarManager(self)
        self._statusbar_manager.setup_statusbar()

    # ============================================================
    # 面板信号连接
    # ============================================================

    def _connect_panel_signals(self):
        """连接面板信号"""
        # 连接代码编辑器面板的打开工作区请求信号
        if "code_editor" in self._panels:
            self._panels["code_editor"].open_workspace_requested.connect(
                self._on_open_workspace
            )
            # 连接撤销/重做状态变化信号
            self._panels["code_editor"].undo_redo_state_changed.connect(
                self._on_undo_redo_state_changed
            )
            # 连接可编辑文件状态变化信号（用于启用/禁用保存按钮）
            self._panels["code_editor"].editable_file_state_changed.connect(
                self._on_editable_file_state_changed
            )


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
                EVENT_STATE_PROJECT_CLOSED
            )
            self.event_bus.subscribe(EVENT_LANGUAGE_CHANGED, self._on_language_changed)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_OPENED, self._on_project_opened)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_CLOSED, self._on_project_closed)

    def _on_language_changed(self, event_data: Dict[str, Any]):
        """语言变更事件处理"""
        self.retranslate_ui()
        if self.logger:
            new_lang = event_data.get("new_language", "unknown")
            self.logger.info(f"UI language changed to: {new_lang}")

    # ============================================================
    # 窗口状态管理
    # ============================================================

    def _restore_window_state(self):
        """恢复窗口状态"""
        if not self.config_manager:
            return
        
        # 恢复窗口位置和尺寸
        geometry = self.config_manager.get("window_geometry")
        if geometry:
            try:
                x, y, w, h = geometry
                self.setGeometry(x, y, w, h)
            except (ValueError, TypeError):
                pass
        
        # 恢复分割器比例
        splitter_sizes = self.config_manager.get("splitter_sizes")
        if splitter_sizes:
            try:
                if "horizontal" in splitter_sizes:
                    h_sizes = splitter_sizes["horizontal"]
                    if isinstance(h_sizes, list) and len(h_sizes) == 3:
                        min_sizes = [150, 400, 250]
                        valid_sizes = all(
                            isinstance(s, (int, float)) and s >= min_sizes[i] 
                            for i, s in enumerate(h_sizes)
                        )
                        if valid_sizes:
                            self._splitters["horizontal"].setSizes(h_sizes)
                
                if "vertical" in splitter_sizes:
                    v_sizes = splitter_sizes["vertical"]
                    if isinstance(v_sizes, list) and len(v_sizes) == 2:
                        valid_sizes = (
                            isinstance(v_sizes[0], (int, float)) and v_sizes[0] >= 400 and
                            isinstance(v_sizes[1], (int, float)) and v_sizes[1] >= 100
                        )
                        if valid_sizes:
                            self._splitters["vertical"].setSizes(v_sizes)
            except (ValueError, TypeError):
                pass
        
        # 恢复面板可见性
        panel_visibility = self.config_manager.get("panel_visibility")
        if panel_visibility and isinstance(panel_visibility, dict):
            for panel_name, visible in panel_visibility.items():
                if panel_name in self._panels:
                    is_visible = bool(visible) if visible is not None else True
                    self._panels[panel_name].setVisible(is_visible)
                    # 同步菜单勾选状态
                    if self._menu_manager:
                        action_key = f"view_{panel_name}"
                        self._menu_manager.set_action_checked(action_key, is_visible)

    def _save_window_state(self):
        """保存窗口状态"""
        if not self.config_manager:
            return
        
        # 保存窗口位置和尺寸
        geo = self.geometry()
        self.config_manager.set("window_geometry", [geo.x(), geo.y(), geo.width(), geo.height()])
        
        # 保存分割器比例
        h_sizes = self._splitters["horizontal"].sizes()
        v_sizes = self._splitters["vertical"].sizes()
        
        if all(s > 0 for s in h_sizes) and all(s > 0 for s in v_sizes):
            self.config_manager.set("splitter_sizes", {
                "horizontal": h_sizes,
                "vertical": v_sizes,
            })
        
        # 保存面板可见性
        panel_visibility = {}
        for panel_name, panel in self._panels.items():
            panel_visibility[panel_name] = panel.isVisible()
        self.config_manager.set("panel_visibility", panel_visibility)
        
        # 保存会话状态
        self._save_session_state()

    def _save_session_state(self):
        """保存会话状态（项目路径、打开的文件）"""
        if not self.config_manager:
            return
        
        # 保存当前项目路径
        project_path = None
        if self.app_state:
            from shared.app_state import STATE_PROJECT_PATH
            project_path = self.app_state.get(STATE_PROJECT_PATH)
        self.config_manager.set("last_project_path", project_path)
        
        # 保存编辑器中打开的文件列表和当前激活的标签页
        if "code_editor" in self._panels:
            editor_panel = self._panels["code_editor"]
            if hasattr(editor_panel, 'get_open_files'):
                open_files = editor_panel.get_open_files()
                self.config_manager.set("open_files", open_files)
            if hasattr(editor_panel, 'get_current_file'):
                current_file = editor_panel.get_current_file()
                self.config_manager.set("active_file", current_file)

    def _restore_session_state(self):
        """恢复会话状态（项目路径、打开的文件）"""
        if not self.config_manager:
            return
        
        import os
        
        # 恢复上次打开的项目
        last_project = self.config_manager.get("last_project_path")
        if last_project and os.path.isdir(last_project):
            self._open_project(last_project)
            
            # 延迟恢复打开的文件（等待项目初始化完成）
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(200, self._restore_open_files)
        else:
            # 无项目时清空保存的文件列表
            self.config_manager.set("open_files", [])
            self.config_manager.set("active_file", None)

    def _restore_open_files(self):
        """恢复编辑器中打开的文件"""
        if not self.config_manager:
            return
        
        import os
        
        # 获取保存的文件列表
        open_files = self.config_manager.get("open_files", [])
        active_file = self.config_manager.get("active_file")
        
        if not open_files or "code_editor" not in self._panels:
            return
        
        editor_panel = self._panels["code_editor"]
        
        # 依次打开文件
        for file_path in open_files:
            if file_path and os.path.isfile(file_path):
                editor_panel.load_file(file_path)
        
        # 切换到上次激活的文件
        if active_file and os.path.isfile(active_file):
            if hasattr(editor_panel, 'switch_to_file'):
                editor_panel.switch_to_file(active_file)
        
        # 延迟重置所有文件的修改状态（确保 UI 完全加载后执行）
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(100, lambda: self._reset_all_modification_states(editor_panel))

    def _reset_all_modification_states(self, editor_panel):
        """重置所有打开文件的修改状态"""
        if hasattr(editor_panel, 'reset_all_modification_states'):
            editor_panel.reset_all_modification_states()

    def closeEvent(self, event):
        """窗口关闭事件"""
        self._save_window_state()
        super().closeEvent(event)


    # ============================================================
    # 面板显示/隐藏
    # ============================================================

    def _toggle_panel(self, panel_name: str, visible: bool):
        """切换面板显示/隐藏"""
        if panel_name in self._panels:
            self._panels[panel_name].setVisible(visible)

    # ============================================================
    # 辅助方法
    # ============================================================

    def _get_recent_projects(self) -> list:
        """获取最近项目列表"""
        recent_projects = []
        if self.project_service:
            recent_projects = self.project_service.get_recent_projects(filter_invalid=False)
        elif self.config_manager:
            import os
            paths = self.config_manager.get("recent_projects", [])
            for path in paths[:10]:
                recent_projects.append({
                    "path": path,
                    "name": os.path.basename(path),
                    "exists": os.path.isdir(path),
                })
        return recent_projects

    def _update_recent_menu(self):
        """更新最近打开子菜单"""
        if not self._menu_manager:
            return
        
        recent_projects = self._get_recent_projects()
        callbacks = {
            "on_recent_click": self._on_recent_project_clicked,
            "on_clear_recent": self._on_clear_recent_projects,
        }
        self._menu_manager.update_recent_menu(recent_projects, callbacks)

    # ============================================================
    # 菜单/工具栏动作处理
    # ============================================================

    def _on_open_workspace(self):
        """打开工作文件夹"""
        folder = QFileDialog.getExistingDirectory(
            self,
            self._get_text("dialog.open_workspace.title", "Open Workspace"),
            "",
            QFileDialog.Option.ShowDirsOnly
        )
        
        if folder:
            self._open_project(folder)

    def _open_project(self, folder_path: str):
        """打开项目"""
        if self.logger:
            self.logger.info(f"Opening workspace: {folder_path}")
        
        if self.project_service:
            success, msg = self.project_service.initialize_project(folder_path)
            if not success:
                QMessageBox.warning(
                    self,
                    self._get_text("dialog.error.title", "Error"),
                    msg
                )
                return
            if self.logger:
                self.logger.info(f"Project initialized: {msg}")
        else:
            if self.app_state:
                from shared.app_state import STATE_PROJECT_PATH, STATE_PROJECT_INITIALIZED
                self.app_state.set(STATE_PROJECT_PATH, folder_path)
                self.app_state.set(STATE_PROJECT_INITIALIZED, True)
            
            if self.event_bus:
                from shared.event_types import EVENT_STATE_PROJECT_OPENED
                import os
                self.event_bus.publish(EVENT_STATE_PROJECT_OPENED, {
                    "path": folder_path,
                    "name": os.path.basename(folder_path),
                    "is_existing": False,
                    "has_history": False,
                    "status": "ready",
                })

    def _on_close_workspace(self):
        """关闭工作文件夹"""
        if self.project_service:
            success, msg = self.project_service.close_project()
            if not success:
                QMessageBox.warning(
                    self,
                    self._get_text("dialog.error.title", "Error"),
                    msg
                )
                return
            if self.logger:
                self.logger.info(f"Project closed: {msg}")
        else:
            if self.app_state:
                from shared.app_state import STATE_PROJECT_PATH, STATE_PROJECT_INITIALIZED
                self.app_state.set(STATE_PROJECT_PATH, None)
                self.app_state.set(STATE_PROJECT_INITIALIZED, False)
            
            if self.event_bus:
                from shared.event_types import EVENT_STATE_PROJECT_CLOSED
                self.event_bus.publish(EVENT_STATE_PROJECT_CLOSED, {"path": None})

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

    def _on_recent_project_clicked(self, path: str):
        """点击最近项目"""
        import os
        if os.path.isdir(path):
            if self.project_service:
                success, msg = self.project_service.switch_project(path)
                if not success:
                    QMessageBox.warning(
                        self,
                        self._get_text("dialog.error.title", "Error"),
                        msg
                    )
            else:
                self._open_project(path)
        else:
            reply = QMessageBox.question(
                self,
                self._get_text("dialog.confirm.title", "Confirm"),
                f"Path does not exist: {path}\n\nRemove from recent list?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                if self.project_service:
                    self.project_service.remove_from_recent(path)
                self._update_recent_menu()

    def _on_clear_recent_projects(self):
        """清除最近项目记录"""
        if self.project_service:
            self.project_service.clear_recent_projects()
        elif self.config_manager:
            self.config_manager.set("recent_projects", [])
        
        self._update_recent_menu()

    def _on_save_file(self):
        """保存当前文件"""
        if "code_editor" in self._panels:
            self._panels["code_editor"].save_file()

    def _on_save_all_files(self):
        """保存所有已修改的文件"""
        if "code_editor" in self._panels:
            saved_count = self._panels["code_editor"].save_all_files()
            if self.logger:
                self.logger.info(f"Save all: {saved_count} file(s) saved")

    def _on_editor_undo(self):
        """编辑器级别撤销（Ctrl+Z）"""
        if "code_editor" in self._panels:
            editor = self._panels["code_editor"]
            if hasattr(editor, 'undo'):
                editor.undo()

    def _on_editor_redo(self):
        """编辑器级别重做（Ctrl+Y）"""
        if "code_editor" in self._panels:
            editor = self._panels["code_editor"]
            if hasattr(editor, 'redo'):
                editor.redo()

    def _on_undo_iteration(self):
        """撤回本次迭代（迭代级别，阶段四实现）"""
        # TODO: 阶段四实现，调用 undo_manager.restore_snapshot()
        QMessageBox.information(
            self,
            self._get_text("menu.edit.undo_iteration", "Undo Iteration"),
            "Undo iteration will be implemented in Phase 4"
        )

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

    def _on_api_config(self):
        """打开 API 配置对话框"""
        from presentation.dialogs import ApiConfigDialog
        dialog = ApiConfigDialog(self)
        dialog.exec()

    def _on_help_docs(self):
        """打开文档"""
        QMessageBox.information(
            self,
            self._get_text("menu.help.documentation", "Documentation"),
            "Documentation - Coming soon"
        )

    def _on_about(self):
        """打开关于对话框"""
        from presentation.dialogs import AboutDialog
        dialog = AboutDialog(self)
        dialog.exec()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "MainWindow",
]
