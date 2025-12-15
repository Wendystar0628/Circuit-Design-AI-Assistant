# Action Handlers - 动作处理器集合
"""
动作处理器集合 - 集中管理菜单和工具栏动作的具体实现逻辑

职责：
- 文件操作回调（打开/关闭/保存）
- 编辑操作回调（撤销/重做）
- 视图操作回调（面板切换）
- 工具操作回调（配置/帮助）

设计原则：
- 单一职责：仅作为 UI 动作到服务层的桥接
- 不包含业务逻辑
- 延迟获取 ServiceLocator 中的服务
"""

import os
from typing import Optional, Dict, Any, Callable

from PyQt6.QtWidgets import QMainWindow, QFileDialog, QMessageBox


class ActionHandlers:
    """
    动作处理器集合
    
    集中管理菜单和工具栏动作的具体实现逻辑
    """

    def __init__(self, main_window: QMainWindow, panels: Dict[str, Any]):
        """
        初始化动作处理器
        
        Args:
            main_window: 主窗口引用
            panels: 面板字典
        """
        self._main_window = main_window
        self._panels = panels
        self._i18n_manager = None
        self._config_manager = None
        self._project_service = None
        self._logger = None

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

    @property
    def logger(self):
        """延迟获取 Logger"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("action_handlers")
            except Exception:
                pass
        return self._logger

    def _get_text(self, key: str, default: Optional[str] = None) -> str:
        """获取国际化文本"""
        if self.i18n_manager:
            return self.i18n_manager.get_text(key, default)
        return default if default else key

    # ============================================================
    # 回调字典
    # ============================================================

    def get_callbacks(self) -> Dict[str, Callable]:
        """
        返回所有回调函数的字典，供 MenuManager/ToolbarManager 使用
        
        Returns:
            回调函数字典
        """
        return {
            "on_open_workspace": self.on_open_workspace,
            "on_close_workspace": self.on_close_workspace,
            "on_save_file": self.on_save_file,
            "on_save_all_files": self.on_save_all_files,
            "on_editor_undo": self.on_editor_undo,
            "on_editor_redo": self.on_editor_redo,
            "on_undo_iteration": self.on_undo_iteration,
            "on_toggle_panel": self.on_toggle_panel,
            "on_api_config": self.on_api_config,
            "on_help_docs": self.on_help_docs,
            "on_about": self.on_about,
        }

    # ============================================================
    # 文件操作回调
    # ============================================================

    def on_open_workspace(self):
        """打开工作文件夹"""
        folder = QFileDialog.getExistingDirectory(
            self._main_window,
            self._get_text("dialog.open_workspace.title", "Open Workspace"),
            "",
            QFileDialog.Option.ShowDirsOnly
        )
        
        if folder:
            self._open_project(folder)

    def _open_project(self, folder_path: str):
        """
        打开项目
        
        每次打开项目都会：
        1. 调用 project_service.initialize_project() 初始化项目
        2. 自动检查并补全目录结构
        """
        if self.logger:
            self.logger.info(f"Opening workspace: {folder_path}")
        
        if self.project_service:
            success, msg = self.project_service.initialize_project(folder_path)
            if not success:
                QMessageBox.warning(
                    self._main_window,
                    self._get_text("dialog.error.title", "Error"),
                    msg
                )
                return
            if self.logger:
                self.logger.info(f"Project initialized: {msg}")
        else:
            # 降级处理：project_service 不可用时的备用逻辑
            self._create_project_structure_fallback(folder_path)

    def _create_project_structure_fallback(self, folder_path: str) -> None:
        """
        降级处理：手动创建项目目录结构
        
        当 project_service 不可用时，手动创建必要的目录结构。
        """
        from pathlib import Path
        
        path = Path(folder_path)
        
        # 创建 .circuit_ai/ 隐藏目录
        hidden_dir = path / ".circuit_ai"
        try:
            hidden_dir.mkdir(parents=True, exist_ok=True)
            (hidden_dir / "undo_snapshots").mkdir(parents=True, exist_ok=True)
        except Exception as e:
            if self.logger:
                self.logger.warning(f"创建隐藏目录失败: {e}")
        
        # 创建推荐目录结构
        recommended_dirs = ["parameters", "subcircuits", "uploads", "simulation_results"]
        for dir_name in recommended_dirs:
            try:
                (path / dir_name).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"创建推荐目录失败: {dir_name} - {e}")
        
        # 更新应用状态
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_APP_STATE, SVC_EVENT_BUS
            
            app_state = ServiceLocator.get_optional(SVC_APP_STATE)
            if app_state:
                from shared.app_state import STATE_PROJECT_PATH, STATE_PROJECT_INITIALIZED
                app_state.set(STATE_PROJECT_PATH, folder_path)
                app_state.set(STATE_PROJECT_INITIALIZED, True)
            
            event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            if event_bus:
                from shared.event_types import EVENT_STATE_PROJECT_OPENED
                event_bus.publish(EVENT_STATE_PROJECT_OPENED, {
                    "path": folder_path,
                    "name": os.path.basename(folder_path),
                    "is_existing": False,
                    "has_history": False,
                    "status": "ready",
                })
        except Exception as e:
            if self.logger:
                self.logger.warning(f"更新应用状态失败: {e}")

    def on_close_workspace(self):
        """关闭工作文件夹"""
        if self.project_service:
            success, msg = self.project_service.close_project()
            if not success:
                QMessageBox.warning(
                    self._main_window,
                    self._get_text("dialog.error.title", "Error"),
                    msg
                )
                return
            if self.logger:
                self.logger.info(f"Project closed: {msg}")
        else:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_APP_STATE, SVC_EVENT_BUS
                
                app_state = ServiceLocator.get_optional(SVC_APP_STATE)
                if app_state:
                    from shared.app_state import STATE_PROJECT_PATH, STATE_PROJECT_INITIALIZED
                    app_state.set(STATE_PROJECT_PATH, None)
                    app_state.set(STATE_PROJECT_INITIALIZED, False)
                
                event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
                if event_bus:
                    from shared.event_types import EVENT_STATE_PROJECT_CLOSED
                    event_bus.publish(EVENT_STATE_PROJECT_CLOSED, {"path": None})
            except Exception:
                pass

    def on_save_file(self):
        """保存当前文件"""
        if "code_editor" in self._panels:
            self._panels["code_editor"].save_file()

    def on_save_all_files(self):
        """保存所有已修改的文件"""
        if "code_editor" in self._panels:
            saved_count = self._panels["code_editor"].save_all_files()
            if self.logger:
                self.logger.info(f"Save all: {saved_count} file(s) saved")

    def on_recent_project_clicked(self, path: str):
        """点击最近项目"""
        if os.path.isdir(path):
            if self.project_service:
                success, msg = self.project_service.switch_project(path)
                if not success:
                    QMessageBox.warning(
                        self._main_window,
                        self._get_text("dialog.error.title", "Error"),
                        msg
                    )
            else:
                self._open_project(path)
        else:
            reply = QMessageBox.question(
                self._main_window,
                self._get_text("dialog.confirm.title", "Confirm"),
                f"Path does not exist: {path}\n\nRemove from recent list?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                if self.project_service:
                    self.project_service.remove_from_recent(path)

    def on_clear_recent_projects(self):
        """清除最近项目记录"""
        if self.project_service:
            self.project_service.clear_recent_projects()
        elif self.config_manager:
            self.config_manager.set("recent_projects", [])


    # ============================================================
    # 编辑操作回调
    # ============================================================

    def on_editor_undo(self):
        """编辑器级别撤销（Ctrl+Z）"""
        if "code_editor" in self._panels:
            editor = self._panels["code_editor"]
            if hasattr(editor, 'undo'):
                editor.undo()

    def on_editor_redo(self):
        """编辑器级别重做（Ctrl+Y）"""
        if "code_editor" in self._panels:
            editor = self._panels["code_editor"]
            if hasattr(editor, 'redo'):
                editor.redo()

    def on_undo_iteration(self):
        """撤回本次迭代（迭代级别，阶段四实现）"""
        # TODO: 阶段四实现，调用 undo_manager.restore_snapshot()
        QMessageBox.information(
            self._main_window,
            self._get_text("menu.edit.undo_iteration", "Undo Iteration"),
            "Undo iteration will be implemented in Phase 4"
        )

    # ============================================================
    # 视图操作回调
    # ============================================================

    def on_toggle_panel(self, panel_name: str, visible: bool):
        """切换面板显示/隐藏"""
        if panel_name in self._panels:
            self._panels[panel_name].setVisible(visible)

    # ============================================================
    # 工具操作回调
    # ============================================================

    def on_api_config(self):
        """打开 API 配置对话框"""
        from presentation.dialogs import ApiConfigDialog
        dialog = ApiConfigDialog(self._main_window)
        dialog.exec()

    def on_help_docs(self):
        """打开文档"""
        QMessageBox.information(
            self._main_window,
            self._get_text("menu.help.documentation", "Documentation"),
            "Documentation - Coming soon"
        )

    def on_about(self):
        """打开关于对话框"""
        from presentation.dialogs import AboutDialog
        dialog = AboutDialog(self._main_window)
        dialog.exec()


__all__ = ["ActionHandlers"]
