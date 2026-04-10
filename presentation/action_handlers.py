# Action Handlers - 动作处理器集合
"""
动作处理器集合 - 集中管理菜单动作的具体实现逻辑

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
    
    集中管理菜单动作的具体实现逻辑
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

    def _get_panel(self, panel_id: str):
        return self._panels.get(panel_id)

    def _activate_right_panel(self, panel_id: str) -> None:
        if hasattr(self._main_window, "activate_right_panel"):
            self._main_window.activate_right_panel(panel_id)

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
            "on_edit_undo": self.on_edit_undo,
            "on_edit_redo": self.on_edit_redo,
            "on_edit_cut": self.on_edit_cut,
            "on_edit_copy": self.on_edit_copy,
            "on_edit_paste": self.on_edit_paste,
            "on_edit_select_all": self.on_edit_select_all,
            "on_toggle_panel": self.on_toggle_panel,
            "on_show_conversation": self.on_show_conversation,
            "on_show_rag": self.on_show_rag,
            "on_new_conversation": self.on_new_conversation,
            "on_conversation_history": self.on_conversation_history,
            "on_conversation_compress": self.on_conversation_compress,
            "on_reindex_knowledge": self.on_reindex_knowledge,
            "on_clear_knowledge": self.on_clear_knowledge,
            "on_design_goals": self.on_design_goals,
            "on_iteration_history": self.on_iteration_history,
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
        2. 初始化项目状态目录并发布项目打开状态
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
        
        当 project_service 不可用时，仅创建必要的隐藏状态目录。
        """
        from pathlib import Path
        
        path = Path(folder_path)
        
        # 创建 .circuit_ai/ 隐藏目录
        hidden_dir = path / ".circuit_ai"
        try:
            hidden_dir.mkdir(parents=True, exist_ok=True)
            (hidden_dir / "snapshots").mkdir(parents=True, exist_ok=True)
        except Exception as e:
            if self.logger:
                self.logger.warning(f"创建隐藏目录失败: {e}")

        # 发布项目打开事件
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_EVENT_BUS

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
                self.logger.warning(f"发布项目打开事件失败: {e}")

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
                from shared.service_names import SVC_EVENT_BUS
                
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

    def _get_project_root(self) -> Optional[str]:
        """获取当前项目根目录"""
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_SESSION_STATE
            
            session_state = ServiceLocator.get_optional(SVC_SESSION_STATE)
            if session_state:
                return session_state.project_root
        except Exception:
            pass
        return None

    def on_edit_undo(self):
        panel = self._get_panel("code_editor")
        if panel is not None and hasattr(panel, "undo"):
            panel.undo()

    def on_edit_redo(self):
        panel = self._get_panel("code_editor")
        if panel is not None and hasattr(panel, "redo"):
            panel.redo()

    def on_edit_cut(self):
        panel = self._get_panel("code_editor")
        if panel is not None and hasattr(panel, "cut"):
            panel.cut()

    def on_edit_copy(self):
        panel = self._get_panel("code_editor")
        if panel is not None and hasattr(panel, "copy"):
            panel.copy()

    def on_edit_paste(self):
        panel = self._get_panel("code_editor")
        if panel is not None and hasattr(panel, "paste"):
            panel.paste()

    def on_edit_select_all(self):
        panel = self._get_panel("code_editor")
        if panel is not None and hasattr(panel, "select_all"):
            panel.select_all()

    def on_show_conversation(self):
        self._activate_right_panel("conversation")

    def on_show_rag(self):
        self._activate_right_panel("rag")

    def on_new_conversation(self):
        self.on_show_conversation()
        panel = self._get_panel("right_panel")
        if panel is not None and hasattr(panel, "start_new_conversation"):
            panel.start_new_conversation()

    def on_conversation_history(self):
        self.on_show_conversation()
        panel = self._get_panel("right_panel")
        if panel is not None and hasattr(panel, "request_history"):
            panel.request_history()

    def on_conversation_compress(self):
        self.on_show_conversation()
        panel = self._get_panel("right_panel")
        if panel is not None and hasattr(panel, "request_compress_context"):
            panel.request_compress_context()

    def on_reindex_knowledge(self):
        self.on_show_rag()
        panel = self._get_panel("right_panel")
        if panel is not None and hasattr(panel, "trigger_reindex"):
            panel.trigger_reindex()

    def on_clear_knowledge(self):
        self.on_show_rag()
        panel = self._get_panel("right_panel")
        if panel is not None and hasattr(panel, "request_clear_index"):
            panel.request_clear_index()

    # ============================================================
    # 视图操作回调
    # ============================================================

    def on_toggle_panel(self, panel_id: str, visible: Optional[bool] = None):
        """
        切换面板显示/隐藏
        
        Args:
            panel_id: 面板 ID
            visible: 指定可见性，None 表示切换当前状态
        """
        if hasattr(self._main_window, "toggle_panel"):
            self._main_window.toggle_panel(panel_id, visible)

    # ============================================================
    # 设计操作回调
    # ============================================================

    def on_design_goals(self):
        """打开设计目标编辑对话框"""
        # 检查是否已打开项目
        project_root = self._get_project_root()
        if not project_root:
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.warning.title", "Warning"),
                self._get_text("status.open_workspace", "Please open a workspace folder")
            )
            return
        
        try:
            from presentation.dialogs.design_goals_dialog import DesignGoalsDialog
            
            dialog = DesignGoalsDialog(self._main_window)
            dialog.load_goals(project_root)
            dialog.exec()
            
        except ImportError as e:
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.warning.title", "Warning"),
                self._get_text(
                    "dialog.design_goals.import_error",
                    "Failed to load Design Goals module."
                )
            )
            if self.logger:
                self.logger.error(f"Failed to import DesignGoalsDialog: {e}")
        except Exception as e:
            QMessageBox.critical(
                self._main_window,
                self._get_text("dialog.error.title", "Error"),
                f"Failed to open design goals: {str(e)}"
            )
            if self.logger:
                self.logger.error(f"Failed to open design goals dialog: {e}")

    def on_iteration_history(self):
        """打开迭代历史记录对话框"""
        # 检查是否已打开项目
        project_root = self._get_project_root()
        if not project_root:
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.warning.title", "Warning"),
                self._get_text("status.open_workspace", "Please open a workspace folder")
            )
            return
        
        try:
            from presentation.dialogs.iteration_history_dialog import IterationHistoryDialog
            
            dialog = IterationHistoryDialog(self._main_window)
            dialog.load_history(project_root)
            dialog.exec()
            
        except ImportError as e:
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.warning.title", "Warning"),
                self._get_text(
                    "dialog.iteration_history.import_error",
                    "Failed to load Iteration History module."
                )
            )
            if self.logger:
                self.logger.error(f"Failed to import IterationHistoryDialog: {e}")
        except Exception as e:
            QMessageBox.critical(
                self._main_window,
                self._get_text("dialog.error.title", "Error"),
                f"Failed to open iteration history: {str(e)}"
            )
            if self.logger:
                self.logger.error(f"Failed to open iteration history dialog: {e}")

    # ============================================================
    # 工具操作回调
    # ============================================================

    def on_api_config(self):
        """打开模型配置对话框"""
        from presentation.dialogs import ModelConfigDialog
        dialog = ModelConfigDialog(self._main_window)
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
