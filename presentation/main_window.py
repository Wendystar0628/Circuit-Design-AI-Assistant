# Main Window - Application Main Window (Skeleton Version)
"""
主窗口类（骨架版）- 应用程序主窗口框架

职责：
- 建立三栏+下栏的 QSplitter 嵌套布局结构
- 创建菜单栏、工具栏、状态栏骨架
- 各面板区域使用 QWidget 占位
- 实现国际化支持和语言切换

初始化顺序：
- Phase 2.2，依赖 ServiceLocator（获取 I18nManager 等）

设计原则：
- 延迟获取 ServiceLocator 中的服务
- 所有用户可见文本通过 i18n_manager.get_text() 获取
- 实现 retranslate_ui() 方法支持语言切换
"""

from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QLabel, QMenuBar, QMenu, QToolBar,
    QStatusBar, QPushButton, QComboBox, QFileDialog,
    QMessageBox
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction, QIcon


# ============================================================
# 主窗口类
# ============================================================

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
        
        # UI 组件引用
        self._actions: Dict[str, QAction] = {}
        self._menus: Dict[str, QMenu] = {}
        self._panels: Dict[str, QWidget] = {}
        self._splitters: Dict[str, QSplitter] = {}
        
        # 状态栏组件
        self._status_label: Optional[QLabel] = None
        self._iteration_label: Optional[QLabel] = None
        self._worker_label: Optional[QLabel] = None
        
        # 欢迎遮罩层
        self._welcome_overlay: Optional[QWidget] = None
        
        # 初始化 UI
        self._setup_window()
        self._setup_central_widget()
        self._setup_menu_bar()
        self._setup_tool_bar()
        self._setup_status_bar()
        self._setup_welcome_overlay()
        
        # 应用国际化文本
        self.retranslate_ui()
        
        # 订阅语言变更事件
        self._subscribe_events()
        
        # 恢复窗口状态
        self._restore_window_state()
        
        # 检查是否需要显示欢迎遮罩
        self._check_welcome_overlay()


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
        """创建面板占位部件"""
        # 左栏 - 文件浏览器
        self._panels["file_browser"] = self._create_placeholder_panel("panel.file_browser")
        self._panels["file_browser"].setMinimumWidth(150)
        self._splitters["horizontal"].addWidget(self._panels["file_browser"])
        
        # 中栏 - 代码编辑器
        self._panels["code_editor"] = self._create_placeholder_panel("panel.code_editor")
        self._panels["code_editor"].setMinimumWidth(400)
        self._splitters["horizontal"].addWidget(self._panels["code_editor"])
        
        # 右栏 - 对话面板
        self._panels["chat"] = self._create_placeholder_panel("panel.chat")
        self._panels["chat"].setMinimumWidth(250)
        self._splitters["horizontal"].addWidget(self._panels["chat"])
        
        # 下栏 - 仿真结果
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
    # 菜单栏
    # ============================================================

    def _setup_menu_bar(self):
        """设置菜单栏"""
        menubar = self.menuBar()
        
        # 文件菜单
        self._menus["file"] = menubar.addMenu("")
        self._setup_file_menu()
        
        # 编辑菜单
        self._menus["edit"] = menubar.addMenu("")
        self._setup_edit_menu()
        
        # 视图菜单
        self._menus["view"] = menubar.addMenu("")
        self._setup_view_menu()
        
        # 仿真菜单
        self._menus["simulation"] = menubar.addMenu("")
        self._setup_simulation_menu()
        
        # 知识库菜单
        self._menus["knowledge"] = menubar.addMenu("")
        self._setup_knowledge_menu()
        
        # 工具菜单
        self._menus["tools"] = menubar.addMenu("")
        self._setup_tools_menu()
        
        # 帮助菜单
        self._menus["help"] = menubar.addMenu("")
        self._setup_help_menu()

    def _setup_file_menu(self):
        """设置文件菜单"""
        menu = self._menus["file"]
        
        # 打开工作文件夹
        self._actions["file_open"] = QAction(self)
        self._actions["file_open"].triggered.connect(self._on_open_workspace)
        menu.addAction(self._actions["file_open"])
        
        # 关闭工作文件夹（灰显）
        self._actions["file_close"] = QAction(self)
        self._actions["file_close"].setEnabled(False)
        menu.addAction(self._actions["file_close"])
        
        menu.addSeparator()
        
        # 保存（灰显）
        self._actions["file_save"] = QAction(self)
        self._actions["file_save"].setEnabled(False)
        menu.addAction(self._actions["file_save"])
        
        # 全部保存（灰显）
        self._actions["file_save_all"] = QAction(self)
        self._actions["file_save_all"].setEnabled(False)
        menu.addAction(self._actions["file_save_all"])
        
        menu.addSeparator()
        
        # 退出
        self._actions["file_exit"] = QAction(self)
        self._actions["file_exit"].triggered.connect(self.close)
        menu.addAction(self._actions["file_exit"])

    def _setup_edit_menu(self):
        """设置编辑菜单"""
        menu = self._menus["edit"]
        
        # 撤销（灰显）
        self._actions["edit_undo"] = QAction(self)
        self._actions["edit_undo"].setEnabled(False)
        menu.addAction(self._actions["edit_undo"])
        
        # 重做（灰显）
        self._actions["edit_redo"] = QAction(self)
        self._actions["edit_redo"].setEnabled(False)
        menu.addAction(self._actions["edit_redo"])
        
        menu.addSeparator()
        
        # 剪切（灰显）
        self._actions["edit_cut"] = QAction(self)
        self._actions["edit_cut"].setEnabled(False)
        menu.addAction(self._actions["edit_cut"])
        
        # 复制（灰显）
        self._actions["edit_copy"] = QAction(self)
        self._actions["edit_copy"].setEnabled(False)
        menu.addAction(self._actions["edit_copy"])
        
        # 粘贴（灰显）
        self._actions["edit_paste"] = QAction(self)
        self._actions["edit_paste"].setEnabled(False)
        menu.addAction(self._actions["edit_paste"])

    def _setup_view_menu(self):
        """设置视图菜单"""
        menu = self._menus["view"]
        
        # 文件浏览器（可勾选）
        self._actions["view_file_browser"] = QAction(self)
        self._actions["view_file_browser"].setCheckable(True)
        self._actions["view_file_browser"].setChecked(True)
        self._actions["view_file_browser"].triggered.connect(
            lambda checked: self._toggle_panel("file_browser", checked)
        )
        menu.addAction(self._actions["view_file_browser"])
        
        # 代码编辑器（可勾选）
        self._actions["view_code_editor"] = QAction(self)
        self._actions["view_code_editor"].setCheckable(True)
        self._actions["view_code_editor"].setChecked(True)
        self._actions["view_code_editor"].triggered.connect(
            lambda checked: self._toggle_panel("code_editor", checked)
        )
        menu.addAction(self._actions["view_code_editor"])
        
        # 对话面板（可勾选）
        self._actions["view_chat_panel"] = QAction(self)
        self._actions["view_chat_panel"].setCheckable(True)
        self._actions["view_chat_panel"].setChecked(True)
        self._actions["view_chat_panel"].triggered.connect(
            lambda checked: self._toggle_panel("chat", checked)
        )
        menu.addAction(self._actions["view_chat_panel"])
        
        # 仿真结果（可勾选）
        self._actions["view_simulation"] = QAction(self)
        self._actions["view_simulation"].setCheckable(True)
        self._actions["view_simulation"].setChecked(True)
        self._actions["view_simulation"].triggered.connect(
            lambda checked: self._toggle_panel("simulation", checked)
        )
        menu.addAction(self._actions["view_simulation"])


    def _setup_simulation_menu(self):
        """设置仿真菜单"""
        menu = self._menus["simulation"]
        
        # 运行仿真（灰显，阶段四启用）
        self._actions["sim_run"] = QAction(self)
        self._actions["sim_run"].setEnabled(False)
        menu.addAction(self._actions["sim_run"])
        
        # 停止仿真（灰显，阶段四启用）
        self._actions["sim_stop"] = QAction(self)
        self._actions["sim_stop"].setEnabled(False)
        menu.addAction(self._actions["sim_stop"])

    def _setup_knowledge_menu(self):
        """设置知识库菜单"""
        menu = self._menus["knowledge"]
        
        # 导入文档（灰显，阶段四启用）
        self._actions["knowledge_import"] = QAction(self)
        self._actions["knowledge_import"].setEnabled(False)
        menu.addAction(self._actions["knowledge_import"])
        
        # 重建索引（灰显，阶段四启用）
        self._actions["knowledge_rebuild"] = QAction(self)
        self._actions["knowledge_rebuild"].setEnabled(False)
        menu.addAction(self._actions["knowledge_rebuild"])

    def _setup_tools_menu(self):
        """设置工具菜单"""
        menu = self._menus["tools"]
        
        # 配置大模型API
        self._actions["tools_api_config"] = QAction(self)
        self._actions["tools_api_config"].triggered.connect(self._on_api_config)
        menu.addAction(self._actions["tools_api_config"])
        
        # 压缩上下文（灰显）
        self._actions["tools_compress"] = QAction(self)
        self._actions["tools_compress"].setEnabled(False)
        menu.addAction(self._actions["tools_compress"])

    def _setup_help_menu(self):
        """设置帮助菜单"""
        menu = self._menus["help"]
        
        # 文档
        self._actions["help_docs"] = QAction(self)
        self._actions["help_docs"].triggered.connect(self._on_help_docs)
        menu.addAction(self._actions["help_docs"])
        
        # 关于
        self._actions["help_about"] = QAction(self)
        self._actions["help_about"].triggered.connect(self._on_about)
        menu.addAction(self._actions["help_about"])

    # ============================================================
    # 工具栏
    # ============================================================

    def _setup_tool_bar(self):
        """设置工具栏"""
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(toolbar)
        
        # 打开工作文件夹
        self._actions["toolbar_open"] = QAction(self)
        self._actions["toolbar_open"].triggered.connect(self._on_open_workspace)
        toolbar.addAction(self._actions["toolbar_open"])
        
        # 保存（灰显）
        self._actions["toolbar_save"] = QAction(self)
        self._actions["toolbar_save"].setEnabled(False)
        toolbar.addAction(self._actions["toolbar_save"])
        
        toolbar.addSeparator()
        
        # 运行仿真（灰显）
        self._actions["toolbar_run"] = QAction(self)
        self._actions["toolbar_run"].setEnabled(False)
        toolbar.addAction(self._actions["toolbar_run"])
        
        # 停止仿真（灰显）
        self._actions["toolbar_stop"] = QAction(self)
        self._actions["toolbar_stop"].setEnabled(False)
        toolbar.addAction(self._actions["toolbar_stop"])
        
        toolbar.addSeparator()
        
        # 撤销（灰显）
        self._actions["toolbar_undo"] = QAction(self)
        self._actions["toolbar_undo"].setEnabled(False)
        toolbar.addAction(self._actions["toolbar_undo"])
        
        # 重做（灰显）
        self._actions["toolbar_redo"] = QAction(self)
        self._actions["toolbar_redo"].setEnabled(False)
        toolbar.addAction(self._actions["toolbar_redo"])


    # ============================================================
    # 状态栏
    # ============================================================

    def _setup_status_bar(self):
        """设置状态栏（多分区布局）"""
        statusbar = self.statusBar()
        
        # 左侧：任务状态文本
        self._status_label = QLabel()
        self._status_label.setMinimumWidth(200)
        statusbar.addWidget(self._status_label, 1)
        
        # 中间：当前迭代信息（阶段五显示）
        self._iteration_label = QLabel()
        self._iteration_label.setMinimumWidth(150)
        self._iteration_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        statusbar.addWidget(self._iteration_label)
        
        # 右侧：Worker 状态指示器（阶段三显示）
        self._worker_label = QLabel()
        self._worker_label.setMinimumWidth(100)
        self._worker_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        statusbar.addPermanentWidget(self._worker_label)

    # ============================================================
    # 欢迎遮罩层
    # ============================================================

    def _setup_welcome_overlay(self):
        """设置欢迎遮罩层"""
        self._welcome_overlay = QWidget(self)
        self._welcome_overlay.setStyleSheet(
            "background-color: rgba(0, 0, 0, 0.5);"
        )
        
        # 遮罩层布局
        overlay_layout = QVBoxLayout(self._welcome_overlay)
        overlay_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 欢迎卡片
        welcome_card = QWidget()
        welcome_card.setFixedSize(400, 300)
        welcome_card.setStyleSheet(
            "background-color: white; border-radius: 10px; padding: 20px;"
        )
        overlay_layout.addWidget(welcome_card)
        
        # 卡片内容布局
        card_layout = QVBoxLayout(welcome_card)
        card_layout.setSpacing(20)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 欢迎标题
        title_label = QLabel()
        title_label.setProperty("welcome_title", True)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #333;")
        card_layout.addWidget(title_label)
        
        # 欢迎说明
        desc_label = QLabel()
        desc_label.setProperty("welcome_desc", True)
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setStyleSheet("font-size: 14px; color: #666;")
        desc_label.setWordWrap(True)
        card_layout.addWidget(desc_label)
        
        card_layout.addStretch()
        
        # 选择工作文件夹按钮
        open_btn = QPushButton()
        open_btn.setProperty("welcome_open_btn", True)
        open_btn.setFixedHeight(40)
        open_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "border: none; border-radius: 5px; font-size: 14px; }"
            "QPushButton:hover { background-color: #45a049; }"
        )
        open_btn.clicked.connect(self._on_open_workspace)
        card_layout.addWidget(open_btn)
        
        # 最近打开下拉列表
        recent_combo = QComboBox()
        recent_combo.setProperty("welcome_recent", True)
        recent_combo.setFixedHeight(35)
        recent_combo.currentIndexChanged.connect(self._on_recent_project_selected)
        card_layout.addWidget(recent_combo)
        
        # 初始隐藏
        self._welcome_overlay.hide()

    def _check_welcome_overlay(self):
        """检查是否需要显示欢迎遮罩"""
        # 检查 AppState 中是否有已打开的项目
        has_project = False
        if self.app_state:
            from shared.app_state import STATE_PROJECT_PATH
            project_path = self.app_state.get(STATE_PROJECT_PATH)
            has_project = project_path is not None and project_path != ""
        
        if not has_project:
            self._show_welcome_overlay()
        else:
            self._hide_welcome_overlay()

    def _show_welcome_overlay(self):
        """显示欢迎遮罩层"""
        if self._welcome_overlay:
            self._welcome_overlay.setGeometry(self.centralWidget().geometry())
            self._welcome_overlay.raise_()
            self._welcome_overlay.show()
            self._update_recent_projects()

    def _hide_welcome_overlay(self):
        """隐藏欢迎遮罩层"""
        if self._welcome_overlay:
            self._welcome_overlay.hide()

    def _update_recent_projects(self):
        """更新最近打开项目列表"""
        recent_combo = self._welcome_overlay.findChild(
            QComboBox, "", Qt.FindChildOption.FindChildrenRecursively
        )
        if not recent_combo:
            return
        
        recent_combo.clear()
        recent_combo.addItem(self._get_text("hint.select_file", "Select recent project..."))
        
        # 从配置读取最近项目
        if self.config_manager:
            recent_projects = self.config_manager.get("recent_projects", [])
            for project in recent_projects[:5]:
                recent_combo.addItem(project)

    def resizeEvent(self, event):
        """窗口大小变化时调整遮罩层"""
        super().resizeEvent(event)
        if self._welcome_overlay and self._welcome_overlay.isVisible():
            self._welcome_overlay.setGeometry(self.centralWidget().geometry())


    # ============================================================
    # 国际化支持
    # ============================================================

    def retranslate_ui(self):
        """刷新所有 UI 文本（语言切换时调用）"""
        # 窗口标题
        self.setWindowTitle(self._get_text("app.title", "Circuit AI Design Assistant"))
        
        # 菜单标题
        self._menus["file"].setTitle(self._get_text("menu.file", "File"))
        self._menus["edit"].setTitle(self._get_text("menu.edit", "Edit"))
        self._menus["view"].setTitle(self._get_text("menu.view", "View"))
        self._menus["simulation"].setTitle(self._get_text("menu.simulation", "Simulation"))
        self._menus["knowledge"].setTitle(self._get_text("menu.knowledge", "Knowledge Base"))
        self._menus["tools"].setTitle(self._get_text("menu.tools", "Tools"))
        self._menus["help"].setTitle(self._get_text("menu.help", "Help"))
        
        # 文件菜单项
        self._actions["file_open"].setText(self._get_text("menu.file.open", "Open Workspace"))
        self._actions["file_close"].setText(self._get_text("menu.file.close", "Close Workspace"))
        self._actions["file_save"].setText(self._get_text("menu.file.save", "Save"))
        self._actions["file_save_all"].setText(self._get_text("menu.file.save_all", "Save All"))
        self._actions["file_exit"].setText(self._get_text("menu.file.exit", "Exit"))
        
        # 编辑菜单项
        self._actions["edit_undo"].setText(self._get_text("menu.edit.undo", "Undo"))
        self._actions["edit_redo"].setText(self._get_text("menu.edit.redo", "Redo"))
        self._actions["edit_cut"].setText(self._get_text("menu.edit.cut", "Cut"))
        self._actions["edit_copy"].setText(self._get_text("menu.edit.copy", "Copy"))
        self._actions["edit_paste"].setText(self._get_text("menu.edit.paste", "Paste"))
        
        # 视图菜单项
        self._actions["view_file_browser"].setText(
            self._get_text("menu.view.file_browser", "File Browser")
        )
        self._actions["view_code_editor"].setText(
            self._get_text("menu.view.code_editor", "Code Editor")
        )
        self._actions["view_chat_panel"].setText(
            self._get_text("menu.view.chat_panel", "Chat Panel")
        )
        self._actions["view_simulation"].setText(
            self._get_text("menu.view.simulation", "Simulation Results")
        )
        
        # 仿真菜单项
        self._actions["sim_run"].setText(self._get_text("menu.simulation.run", "Run Simulation"))
        self._actions["sim_stop"].setText(self._get_text("menu.simulation.stop", "Stop Simulation"))
        
        # 知识库菜单项
        self._actions["knowledge_import"].setText(
            self._get_text("menu.knowledge.import", "Import Documents")
        )
        self._actions["knowledge_rebuild"].setText(
            self._get_text("menu.knowledge.rebuild", "Rebuild Index")
        )
        
        # 工具菜单项
        self._actions["tools_api_config"].setText(
            self._get_text("menu.tools.api_config", "API Configuration")
        )
        self._actions["tools_compress"].setText(
            self._get_text("menu.tools.compress_context", "Compress Context")
        )
        
        # 帮助菜单项
        self._actions["help_docs"].setText(self._get_text("menu.help.documentation", "Documentation"))
        self._actions["help_about"].setText(self._get_text("menu.help.about", "About"))
        
        # 工具栏按钮
        self._actions["toolbar_open"].setText(self._get_text("menu.file.open", "Open"))
        self._actions["toolbar_save"].setText(self._get_text("btn.save", "Save"))
        self._actions["toolbar_run"].setText(self._get_text("menu.simulation.run", "Run"))
        self._actions["toolbar_stop"].setText(self._get_text("btn.stop", "Stop"))
        self._actions["toolbar_undo"].setText(self._get_text("menu.edit.undo", "Undo"))
        self._actions["toolbar_redo"].setText(self._get_text("menu.edit.redo", "Redo"))
        
        # 状态栏
        self._status_label.setText(self._get_text("status.ready", "Ready"))
        
        # 面板占位文本
        self._update_panel_placeholders()
        
        # 欢迎遮罩层
        self._update_welcome_overlay_texts()

    def _update_panel_placeholders(self):
        """更新面板占位文本"""
        for panel_name, panel in self._panels.items():
            label = panel.findChild(QLabel)
            if label:
                title_key = label.property("title_key")
                if title_key:
                    title = self._get_text(title_key, panel_name)
                    hint = self._get_text("status.open_workspace", "Please open a workspace folder")
                    label.setText(f"{title}\n\n{hint}")

    def _update_welcome_overlay_texts(self):
        """更新欢迎遮罩层文本"""
        if not self._welcome_overlay:
            return
        
        # 查找并更新标题
        for child in self._welcome_overlay.findChildren(QLabel):
            if child.property("welcome_title"):
                child.setText(self._get_text("app.title", "Circuit AI Design Assistant"))
            elif child.property("welcome_desc"):
                child.setText(self._get_text(
                    "status.open_workspace", 
                    "Please open a workspace folder to get started"
                ))
        
        # 更新按钮文本
        for child in self._welcome_overlay.findChildren(QPushButton):
            if child.property("welcome_open_btn"):
                child.setText(self._get_text("menu.file.open", "Open Workspace"))


    # ============================================================
    # 事件订阅
    # ============================================================

    def _subscribe_events(self):
        """订阅事件"""
        if self.event_bus:
            from shared.event_types import EVENT_LANGUAGE_CHANGED
            self.event_bus.subscribe(EVENT_LANGUAGE_CHANGED, self._on_language_changed)

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
                # 验证水平分割器大小（确保每个面板都有最小宽度）
                if "horizontal" in splitter_sizes:
                    h_sizes = splitter_sizes["horizontal"]
                    # 检查是否所有值都大于最小值（避免面板被压缩到不可见）
                    if isinstance(h_sizes, list) and len(h_sizes) == 3:
                        min_sizes = [150, 400, 250]  # 左栏、中栏、右栏最小宽度
                        valid_sizes = all(
                            isinstance(s, (int, float)) and s >= min_sizes[i] 
                            for i, s in enumerate(h_sizes)
                        )
                        if valid_sizes:
                            self._splitters["horizontal"].setSizes(h_sizes)
                
                # 验证垂直分割器大小（确保每个区域都有最小高度）
                if "vertical" in splitter_sizes:
                    v_sizes = splitter_sizes["vertical"]
                    if isinstance(v_sizes, list) and len(v_sizes) == 2:
                        # 上部最小 400，下部最小 100
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
                    # 确保 visible 是布尔值
                    is_visible = bool(visible) if visible is not None else True
                    self._panels[panel_name].setVisible(is_visible)
                    # 同步菜单勾选状态
                    action_key = f"view_{panel_name}"
                    if action_key in self._actions:
                        self._actions[action_key].setChecked(is_visible)

    def _save_window_state(self):
        """保存窗口状态"""
        if not self.config_manager:
            return
        
        # 保存窗口位置和尺寸
        geo = self.geometry()
        self.config_manager.set("window_geometry", [geo.x(), geo.y(), geo.width(), geo.height()])
        
        # 保存分割器比例（只保存有效值）
        h_sizes = self._splitters["horizontal"].sizes()
        v_sizes = self._splitters["vertical"].sizes()
        
        # 验证分割器大小是否有效（避免保存 0 值）
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
        
        # 更新 AppState
        if self.app_state:
            from shared.app_state import STATE_PROJECT_PATH, STATE_PROJECT_INITIALIZED
            self.app_state.set(STATE_PROJECT_PATH, folder_path)
            self.app_state.set(STATE_PROJECT_INITIALIZED, True)
        
        # 添加到最近项目
        self._add_to_recent_projects(folder_path)
        
        # 隐藏欢迎遮罩
        self._hide_welcome_overlay()
        
        # 启用相关功能
        self._actions["file_close"].setEnabled(True)
        
        # 更新状态栏
        self._status_label.setText(f"{self._get_text('status.ready', 'Ready')} - {folder_path}")

    def _add_to_recent_projects(self, folder_path: str):
        """添加到最近项目列表"""
        if not self.config_manager:
            return
        
        recent = self.config_manager.get("recent_projects", [])
        
        # 移除已存在的相同路径
        if folder_path in recent:
            recent.remove(folder_path)
        
        # 添加到开头
        recent.insert(0, folder_path)
        
        # 保留最多 5 个
        recent = recent[:5]
        
        self.config_manager.set("recent_projects", recent)

    def _on_recent_project_selected(self, index: int):
        """最近项目选择"""
        if index <= 0:
            return
        
        recent_combo = self._welcome_overlay.findChild(
            QComboBox, "", Qt.FindChildOption.FindChildrenRecursively
        )
        if recent_combo:
            folder_path = recent_combo.itemText(index)
            if folder_path:
                self._open_project(folder_path)

    def _on_api_config(self):
        """打开 API 配置对话框"""
        from presentation.dialogs import ApiConfigDialog
        dialog = ApiConfigDialog(self)
        dialog.exec()

    def _on_help_docs(self):
        """打开文档"""
        # TODO: 打开文档链接
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
