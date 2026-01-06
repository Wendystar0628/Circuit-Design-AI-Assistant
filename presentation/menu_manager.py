# Menu Manager - Centralized Menu Bar Management
"""
菜单栏管理器 - 集中管理所有菜单的创建、动作绑定和国际化

职责：
- 创建所有菜单和菜单项
- 管理动作的启用/禁用状态
- 刷新所有菜单文本（国际化支持）
- 更新最近项目子菜单

设计原则：
- 动作处理器回调由 MainWindow 提供，管理器只负责 UI 创建和文本刷新
- 菜单项文本使用 i18n_manager.get_text("menu.xxx") 获取

被调用方：main_window.py
"""

from typing import Dict, Optional, Callable, Any

from PyQt6.QtWidgets import QMainWindow, QMenu, QMenuBar
from PyQt6.QtGui import QAction, QActionGroup


class MenuManager:
    """
    菜单栏管理器
    
    集中管理所有菜单的创建、动作绑定和国际化。
    """

    def __init__(self, main_window: QMainWindow):
        """
        初始化菜单管理器
        
        Args:
            main_window: 主窗口引用，用于获取服务和回调
        """
        self._main_window = main_window
        
        # 菜单和动作引用
        self._menus: Dict[str, QMenu] = {}
        self._actions: Dict[str, QAction] = {}
        
        # 回调函数引用
        self._callbacks: Dict[str, Callable] = {}

    # ============================================================
    # 服务访问（通过主窗口）
    # ============================================================

    def _get_text(self, key: str, default: Optional[str] = None) -> str:
        """获取国际化文本"""
        if hasattr(self._main_window, '_get_text'):
            return self._main_window._get_text(key, default)
        return default if default else key

    # ============================================================
    # 核心方法
    # ============================================================

    def setup_menus(self, callbacks: Dict[str, Callable]) -> None:
        """
        创建所有菜单和菜单项
        
        Args:
            callbacks: 动作回调函数字典，键为动作名，值为回调函数
        """
        self._callbacks = callbacks
        menubar = self._main_window.menuBar()
        
        # 文件菜单
        self._menus["file"] = menubar.addMenu("")
        self._setup_file_menu()
        
        # 编辑菜单
        self._menus["edit"] = menubar.addMenu("")
        self._setup_edit_menu()
        
        # 视图菜单
        self._menus["view"] = menubar.addMenu("")
        self._setup_view_menu()
        
        # 设计菜单
        self._menus["design"] = menubar.addMenu("")
        self._setup_design_menu()
        
        # 仿真菜单
        self._menus["simulation"] = menubar.addMenu("")
        self._setup_simulation_menu()
        
        # 知识库菜单
        self._menus["knowledge"] = menubar.addMenu("")
        self._setup_knowledge_menu()
        
        # 模型配置菜单（顶级菜单）
        self._menus["model"] = menubar.addMenu("")
        self._setup_model_menu()
        
        # 设置菜单
        self._menus["settings"] = menubar.addMenu("")
        self._setup_settings_menu()
        
        # 工具菜单
        self._menus["tools"] = menubar.addMenu("")
        self._setup_tools_menu()
        
        # 语言菜单
        self._menus["language"] = menubar.addMenu("")
        self._setup_language_menu()
        
        # 帮助菜单
        self._menus["help"] = menubar.addMenu("")
        self._setup_help_menu()

    def _setup_file_menu(self) -> None:
        """设置文件菜单"""
        menu = self._menus["file"]
        
        # 打开工作文件夹
        self._actions["file_open"] = QAction(self._main_window)
        if "on_open_workspace" in self._callbacks:
            self._actions["file_open"].triggered.connect(self._callbacks["on_open_workspace"])
        menu.addAction(self._actions["file_open"])
        
        # 关闭工作文件夹（灰显）
        self._actions["file_close"] = QAction(self._main_window)
        self._actions["file_close"].setEnabled(False)
        if "on_close_workspace" in self._callbacks:
            self._actions["file_close"].triggered.connect(self._callbacks["on_close_workspace"])
        menu.addAction(self._actions["file_close"])
        
        menu.addSeparator()
        
        # 最近打开子菜单
        self._menus["recent"] = QMenu(self._main_window)
        menu.addMenu(self._menus["recent"])
        
        menu.addSeparator()
        
        # 保存（Ctrl+S）
        self._actions["file_save"] = QAction(self._main_window)
        self._actions["file_save"].setShortcut("Ctrl+S")
        self._actions["file_save"].setEnabled(False)
        if "on_save_file" in self._callbacks:
            self._actions["file_save"].triggered.connect(self._callbacks["on_save_file"])
        menu.addAction(self._actions["file_save"])
        
        # 全部保存（Ctrl+Shift+S）
        self._actions["file_save_all"] = QAction(self._main_window)
        self._actions["file_save_all"].setShortcut("Ctrl+Shift+S")
        self._actions["file_save_all"].setEnabled(False)
        if "on_save_all_files" in self._callbacks:
            self._actions["file_save_all"].triggered.connect(self._callbacks["on_save_all_files"])
        menu.addAction(self._actions["file_save_all"])
        
        menu.addSeparator()
        
        # 退出
        self._actions["file_exit"] = QAction(self._main_window)
        self._actions["file_exit"].triggered.connect(self._main_window.close)
        menu.addAction(self._actions["file_exit"])

    def _setup_edit_menu(self) -> None:
        """设置编辑菜单"""
        menu = self._menus["edit"]
        
        # 撤销（编辑器级别，Ctrl+Z）
        self._actions["edit_undo"] = QAction(self._main_window)
        self._actions["edit_undo"].setShortcut("Ctrl+Z")
        self._actions["edit_undo"].setEnabled(False)
        if "on_editor_undo" in self._callbacks:
            self._actions["edit_undo"].triggered.connect(self._callbacks["on_editor_undo"])
        menu.addAction(self._actions["edit_undo"])
        
        # 重做（编辑器级别，Ctrl+Y）
        self._actions["edit_redo"] = QAction(self._main_window)
        self._actions["edit_redo"].setShortcut("Ctrl+Y")
        self._actions["edit_redo"].setEnabled(False)
        if "on_editor_redo" in self._callbacks:
            self._actions["edit_redo"].triggered.connect(self._callbacks["on_editor_redo"])
        menu.addAction(self._actions["edit_redo"])
        
        menu.addSeparator()
        
        # 撤回本次迭代（迭代级别，阶段四启用）
        self._actions["edit_undo_iteration"] = QAction(self._main_window)
        self._actions["edit_undo_iteration"].setEnabled(False)
        if "on_undo_iteration" in self._callbacks:
            self._actions["edit_undo_iteration"].triggered.connect(self._callbacks["on_undo_iteration"])
        menu.addAction(self._actions["edit_undo_iteration"])
        
        menu.addSeparator()
        
        # 剪切（灰显）
        self._actions["edit_cut"] = QAction(self._main_window)
        self._actions["edit_cut"].setEnabled(False)
        menu.addAction(self._actions["edit_cut"])
        
        # 复制（灰显）
        self._actions["edit_copy"] = QAction(self._main_window)
        self._actions["edit_copy"].setEnabled(False)
        menu.addAction(self._actions["edit_copy"])
        
        # 粘贴（灰显）
        self._actions["edit_paste"] = QAction(self._main_window)
        self._actions["edit_paste"].setEnabled(False)
        menu.addAction(self._actions["edit_paste"])

    def _setup_view_menu(self) -> None:
        """设置视图菜单"""
        menu = self._menus["view"]
        
        # 文件浏览器（可勾选）
        self._actions["view_file_browser"] = QAction(self._main_window)
        self._actions["view_file_browser"].setCheckable(True)
        self._actions["view_file_browser"].setChecked(True)
        if "on_toggle_panel" in self._callbacks:
            self._actions["view_file_browser"].triggered.connect(
                lambda checked: self._callbacks["on_toggle_panel"]("file_browser", checked)
            )
        menu.addAction(self._actions["view_file_browser"])
        
        # 代码编辑器（可勾选）
        self._actions["view_code_editor"] = QAction(self._main_window)
        self._actions["view_code_editor"].setCheckable(True)
        self._actions["view_code_editor"].setChecked(True)
        if "on_toggle_panel" in self._callbacks:
            self._actions["view_code_editor"].triggered.connect(
                lambda checked: self._callbacks["on_toggle_panel"]("code_editor", checked)
            )
        menu.addAction(self._actions["view_code_editor"])
        
        # 对话面板（可勾选）
        self._actions["view_chat_panel"] = QAction(self._main_window)
        self._actions["view_chat_panel"].setCheckable(True)
        self._actions["view_chat_panel"].setChecked(True)
        if "on_toggle_panel" in self._callbacks:
            self._actions["view_chat_panel"].triggered.connect(
                lambda checked: self._callbacks["on_toggle_panel"]("chat", checked)
            )
        menu.addAction(self._actions["view_chat_panel"])
        
        # 仿真结果（可勾选）
        self._actions["view_simulation"] = QAction(self._main_window)
        self._actions["view_simulation"].setCheckable(True)
        self._actions["view_simulation"].setChecked(True)
        if "on_toggle_panel" in self._callbacks:
            self._actions["view_simulation"].triggered.connect(
                lambda checked: self._callbacks["on_toggle_panel"]("simulation", checked)
            )
        menu.addAction(self._actions["view_simulation"])

    def _setup_design_menu(self) -> None:
        """设置设计菜单"""
        menu = self._menus["design"]
        
        # 设计目标（打开设计目标编辑对话框）
        self._actions["design_goals"] = QAction(self._main_window)
        if "on_design_goals" in self._callbacks:
            self._actions["design_goals"].triggered.connect(self._callbacks["on_design_goals"])
        menu.addAction(self._actions["design_goals"])

    def _setup_simulation_menu(self) -> None:
        """设置仿真菜单"""
        menu = self._menus["simulation"]
        
        # 运行仿真（灰显，阶段四启用）
        self._actions["sim_run"] = QAction(self._main_window)
        self._actions["sim_run"].setEnabled(False)
        menu.addAction(self._actions["sim_run"])
        
        # 停止仿真（灰显，阶段四启用）
        self._actions["sim_stop"] = QAction(self._main_window)
        self._actions["sim_stop"].setEnabled(False)
        menu.addAction(self._actions["sim_stop"])
        
        menu.addSeparator()
        
        # 导出波形数据子菜单
        self._menus["export_data"] = menu.addMenu("")
        
        # CSV 导出
        self._actions["export_csv"] = QAction(self._main_window)
        self._actions["export_csv"].setShortcut("Ctrl+Shift+E")
        if "on_export_csv" in self._callbacks:
            self._actions["export_csv"].triggered.connect(self._callbacks["on_export_csv"])
        self._menus["export_data"].addAction(self._actions["export_csv"])
        
        # JSON 导出
        self._actions["export_json"] = QAction(self._main_window)
        if "on_export_json" in self._callbacks:
            self._actions["export_json"].triggered.connect(self._callbacks["on_export_json"])
        self._menus["export_data"].addAction(self._actions["export_json"])
        
        # MATLAB 导出
        self._actions["export_matlab"] = QAction(self._main_window)
        if "on_export_matlab" in self._callbacks:
            self._actions["export_matlab"].triggered.connect(self._callbacks["on_export_matlab"])
        self._menus["export_data"].addAction(self._actions["export_matlab"])
        
        # NumPy 导出
        self._actions["export_numpy"] = QAction(self._main_window)
        if "on_export_numpy" in self._callbacks:
            self._actions["export_numpy"].triggered.connect(self._callbacks["on_export_numpy"])
        self._menus["export_data"].addAction(self._actions["export_numpy"])

    def _setup_knowledge_menu(self) -> None:
        """设置知识库菜单"""
        menu = self._menus["knowledge"]
        
        # 导入文档（灰显，阶段四启用）
        self._actions["knowledge_import"] = QAction(self._main_window)
        self._actions["knowledge_import"].setEnabled(False)
        menu.addAction(self._actions["knowledge_import"])
        
        # 重建索引（灰显，阶段四启用）
        self._actions["knowledge_rebuild"] = QAction(self._main_window)
        self._actions["knowledge_rebuild"].setEnabled(False)
        menu.addAction(self._actions["knowledge_rebuild"])

    def _setup_model_menu(self) -> None:
        """设置模型配置菜单（顶级菜单）"""
        menu = self._menus["model"]
        
        # 模型配置
        self._actions["model_config"] = QAction(self._main_window)
        if "on_api_config" in self._callbacks:
            self._actions["model_config"].triggered.connect(self._callbacks["on_api_config"])
        menu.addAction(self._actions["model_config"])

    def _setup_settings_menu(self) -> None:
        """设置设置菜单"""
        menu = self._menus["settings"]
        
        # 仿真设置（分析类型和图表选择）
        self._actions["settings_simulation"] = QAction(self._main_window)
        self._actions["settings_simulation"].setShortcut("Ctrl+Shift+,")
        if "on_simulation_settings" in self._callbacks:
            self._actions["settings_simulation"].triggered.connect(
                self._callbacks["on_simulation_settings"]
            )
        menu.addAction(self._actions["settings_simulation"])
        
        # 仿真参数配置（AC/DC/瞬态/噪声/收敛参数）
        self._actions["settings_simulation_config"] = QAction(self._main_window)
        self._actions["settings_simulation_config"].setShortcut("Ctrl+Alt+,")
        if "on_simulation_config" in self._callbacks:
            self._actions["settings_simulation_config"].triggered.connect(
                self._callbacks["on_simulation_config"]
            )
        menu.addAction(self._actions["settings_simulation_config"])
        
        menu.addSeparator()
        
        # Prompt 模板管理
        self._actions["settings_prompt_editor"] = QAction(self._main_window)
        self._actions["settings_prompt_editor"].setToolTip(
            self._get_text(
                "menu.settings.prompt_editor_tip",
                "管理和编辑 LLM 提示词模板"
            )
        )
        if "on_prompt_editor" in self._callbacks:
            self._actions["settings_prompt_editor"].triggered.connect(
                self._callbacks["on_prompt_editor"]
            )
        menu.addAction(self._actions["settings_prompt_editor"])

    def _setup_tools_menu(self) -> None:
        """设置工具菜单"""
        menu = self._menus["tools"]
        
        # 压缩上下文（灰显）
        self._actions["tools_compress"] = QAction(self._main_window)
        self._actions["tools_compress"].setEnabled(False)
        menu.addAction(self._actions["tools_compress"])

    def _setup_language_menu(self) -> None:
        """设置语言菜单"""
        menu = self._menus["language"]
        
        # 创建动作组实现单选互斥
        self._language_group = QActionGroup(self._main_window)
        self._language_group.setExclusive(True)
        
        # English
        self._actions["lang_en"] = QAction("English", self._main_window)
        self._actions["lang_en"].setCheckable(True)
        self._actions["lang_en"].setData("en_US")
        self._actions["lang_en"].triggered.connect(lambda: self._on_language_selected("en_US"))
        self._language_group.addAction(self._actions["lang_en"])
        menu.addAction(self._actions["lang_en"])
        
        # 简体中文
        self._actions["lang_zh"] = QAction("简体中文", self._main_window)
        self._actions["lang_zh"].setCheckable(True)
        self._actions["lang_zh"].setData("zh_CN")
        self._actions["lang_zh"].triggered.connect(lambda: self._on_language_selected("zh_CN"))
        self._language_group.addAction(self._actions["lang_zh"])
        menu.addAction(self._actions["lang_zh"])
        
        # 设置当前语言的勾选状态
        self._update_language_check()

    def _on_language_selected(self, lang_code: str) -> None:
        """
        语言选择回调
        
        Args:
            lang_code: 语言代码（如 "en_US"、"zh_CN"）
        """
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_I18N_MANAGER
            i18n_manager = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            if i18n_manager:
                i18n_manager.set_language(lang_code)
        except Exception:
            pass

    def _update_language_check(self) -> None:
        """更新语言菜单的勾选状态"""
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_I18N_MANAGER
            i18n_manager = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            if i18n_manager:
                current_lang = i18n_manager.get_current_language()
                if current_lang == "en_US":
                    self._actions["lang_en"].setChecked(True)
                elif current_lang == "zh_CN":
                    self._actions["lang_zh"].setChecked(True)
        except Exception:
            # 默认选中英文
            self._actions["lang_en"].setChecked(True)

    def _setup_help_menu(self) -> None:
        """设置帮助菜单"""
        menu = self._menus["help"]
        
        # 文档
        self._actions["help_docs"] = QAction(self._main_window)
        if "on_help_docs" in self._callbacks:
            self._actions["help_docs"].triggered.connect(self._callbacks["on_help_docs"])
        menu.addAction(self._actions["help_docs"])
        
        # 关于
        self._actions["help_about"] = QAction(self._main_window)
        if "on_about" in self._callbacks:
            self._actions["help_about"].triggered.connect(self._callbacks["on_about"])
        menu.addAction(self._actions["help_about"])

    def retranslate_ui(self) -> None:
        """刷新所有菜单文本"""
        # 菜单标题
        self._menus["file"].setTitle(self._get_text("menu.file", "File"))
        self._menus["edit"].setTitle(self._get_text("menu.edit", "Edit"))
        self._menus["view"].setTitle(self._get_text("menu.view", "View"))
        self._menus["design"].setTitle(self._get_text("menu.design", "Design"))
        self._menus["simulation"].setTitle(self._get_text("menu.simulation", "Simulation"))
        self._menus["knowledge"].setTitle(self._get_text("menu.knowledge", "Knowledge Base"))
        self._menus["model"].setTitle(self._get_text("menu.model", "Model"))
        self._menus["settings"].setTitle(self._get_text("menu.settings", "Settings"))
        self._menus["tools"].setTitle(self._get_text("menu.tools", "Tools"))
        self._menus["language"].setTitle(self._get_text("menu.language", "Language"))
        self._menus["help"].setTitle(self._get_text("menu.help", "Help"))
        
        # 更新语言菜单勾选状态
        self._update_language_check()
        
        # 文件菜单项
        self._actions["file_open"].setText(self._get_text("menu.file.open", "Open Workspace"))
        self._actions["file_close"].setText(self._get_text("menu.file.close", "Close Workspace"))
        self._actions["file_save"].setText(self._get_text("menu.file.save", "Save"))
        self._actions["file_save_all"].setText(self._get_text("menu.file.save_all", "Save All"))
        self._actions["file_exit"].setText(self._get_text("menu.file.exit", "Exit"))
        
        # 最近打开子菜单
        self._menus["recent"].setTitle(self._get_text("menu.file.recent", "Recent Projects"))
        
        # 编辑菜单项
        self._actions["edit_undo"].setText(self._get_text("menu.edit.undo", "Undo"))
        self._actions["edit_redo"].setText(self._get_text("menu.edit.redo", "Redo"))
        self._actions["edit_undo_iteration"].setText(
            self._get_text("menu.edit.undo_iteration", "Undo Iteration")
        )
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
        
        # 设计菜单项
        self._actions["design_goals"].setText(
            self._get_text("menu.design.goals", "Design Goals")
        )
        
        # 仿真菜单项
        self._actions["sim_run"].setText(self._get_text("menu.simulation.run", "Run Simulation"))
        self._actions["sim_stop"].setText(self._get_text("menu.simulation.stop", "Stop Simulation"))
        
        # 导出数据子菜单
        self._menus["export_data"].setTitle(
            self._get_text("menu.simulation.export_data", "Export Waveform Data")
        )
        self._actions["export_csv"].setText(
            self._get_text("menu.simulation.export_csv", "Export as CSV...")
        )
        self._actions["export_json"].setText(
            self._get_text("menu.simulation.export_json", "Export as JSON...")
        )
        self._actions["export_matlab"].setText(
            self._get_text("menu.simulation.export_matlab", "Export as MATLAB...")
        )
        self._actions["export_numpy"].setText(
            self._get_text("menu.simulation.export_numpy", "Export as NumPy...")
        )
        
        # 知识库菜单项
        self._actions["knowledge_import"].setText(
            self._get_text("menu.knowledge.import", "Import Documents")
        )
        self._actions["knowledge_rebuild"].setText(
            self._get_text("menu.knowledge.rebuild", "Rebuild Index")
        )
        
        # 模型菜单项
        self._actions["model_config"].setText(
            self._get_text("menu.model.config", "Model Configuration")
        )
        
        # 设置菜单项
        self._actions["settings_simulation"].setText(
            self._get_text("menu.settings.simulation", "Simulation Settings...")
        )
        self._actions["settings_simulation_config"].setText(
            self._get_text("menu.settings.simulation_config", "Simulation Parameters...")
        )
        self._actions["settings_prompt_editor"].setText(
            self._get_text("menu.settings.prompt_editor", "Prompt Template Manager...")
        )
        
        # 工具菜单项
        self._actions["tools_compress"].setText(
            self._get_text("menu.tools.compress_context", "Compress Context")
        )
        
        # 帮助菜单项
        self._actions["help_docs"].setText(self._get_text("menu.help.documentation", "Documentation"))
        self._actions["help_about"].setText(self._get_text("menu.help.about", "About"))

    def update_recent_menu(self, recent_projects: list, callbacks: Dict[str, Callable]) -> None:
        """
        更新最近项目子菜单
        
        Args:
            recent_projects: 最近项目列表，每项包含 path, name, exists
            callbacks: 回调函数字典，包含 on_recent_click, on_clear_recent
        """
        menu = self._menus.get("recent")
        if not menu:
            return
        
        menu.clear()
        
        if not recent_projects:
            # 无最近项目
            empty_action = QAction(
                self._get_text("menu.file.recent.empty", "No Recent Projects"),
                self._main_window
            )
            empty_action.setEnabled(False)
            menu.addAction(empty_action)
            return
        
        # 添加最近项目（最多 10 个）
        for project in recent_projects[:10]:
            path = project.get("path", "")
            name = project.get("name", "")
            exists = project.get("exists", True)
            
            # 显示文件夹名，悬停显示完整路径
            display_name = name
            if not exists:
                display_name += f" {self._get_text('menu.file.recent.not_exist', '(Not Exist)')}"
            
            action = QAction(display_name, self._main_window)
            action.setToolTip(path)
            action.setEnabled(exists)
            action.setData(path)
            if "on_recent_click" in callbacks:
                action.triggered.connect(lambda checked, p=path: callbacks["on_recent_click"](p))
            menu.addAction(action)
        
        menu.addSeparator()
        
        # 清除记录
        clear_action = QAction(
            self._get_text("menu.file.recent.clear", "Clear Recent"),
            self._main_window
        )
        if "on_clear_recent" in callbacks:
            clear_action.triggered.connect(callbacks["on_clear_recent"])
        menu.addAction(clear_action)

    def get_action(self, name: str) -> Optional[QAction]:
        """
        获取指定动作对象
        
        Args:
            name: 动作名称
            
        Returns:
            QAction 对象，不存在则返回 None
        """
        return self._actions.get(name)

    def get_menu(self, name: str) -> Optional[QMenu]:
        """
        获取指定菜单对象
        
        Args:
            name: 菜单名称
            
        Returns:
            QMenu 对象，不存在则返回 None
        """
        return self._menus.get(name)

    def set_action_enabled(self, name: str, enabled: bool) -> None:
        """
        设置动作启用状态
        
        Args:
            name: 动作名称
            enabled: 是否启用
        """
        action = self._actions.get(name)
        if action:
            action.setEnabled(enabled)

    def set_action_checked(self, name: str, checked: bool) -> None:
        """
        设置动作勾选状态
        
        Args:
            name: 动作名称
            checked: 是否勾选
        """
        action = self._actions.get(name)
        if action and action.isCheckable():
            action.setChecked(checked)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "MenuManager",
]
