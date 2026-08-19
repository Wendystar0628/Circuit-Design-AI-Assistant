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

from PyQt6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox, QWidget


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
        self._session_state_manager = None
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
    def session_state_manager(self):
        """延迟获取权威会话状态管理器。"""
        if self._session_state_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE_MANAGER

                self._session_state_manager = ServiceLocator.get_optional(
                    SVC_SESSION_STATE_MANAGER
                )
            except Exception:
                pass
        return self._session_state_manager

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

    def _get_right_panel(self):
        return self._main_window.get_right_panel()

    @staticmethod
    def _get_focus_widget() -> Optional[QWidget]:
        return QApplication.focusWidget()

    def _panel_contains_focus(self, panel: Optional[QWidget]) -> bool:
        if panel is None:
            return False
        focus_widget = self._get_focus_widget()
        if focus_widget is None:
            return False
        return focus_widget is panel or panel.isAncestorOf(focus_widget)

    def _dispatch_copy_like_action(self, method_name: str) -> None:
        code_editor = self._get_panel("code_editor")
        right_panel = self._get_right_panel()

        if self._panel_contains_focus(code_editor) and code_editor is not None:
            handler = getattr(code_editor, method_name, None)
            if callable(handler):
                handler()
                return

        if self._panel_contains_focus(right_panel) and right_panel is not None:
            getattr(right_panel, method_name)()
            return

        if code_editor is not None:
            handler = getattr(code_editor, method_name, None)
            if callable(handler):
                handler()
                return

        if right_panel is not None:
            getattr(right_panel, method_name)()

    def _activate_right_panel(self, panel_id: str) -> None:
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

    def prepare_workspace_transition(self) -> bool:
        """Resolve editor buffers and persist conversation state before moving.

        The editor performs a synchronous prepare phase and returns ``False``
        when the user cancels or a requested save fails.  Callers must stop
        immediately in that case; no project service or fallback state may be
        touched.  Conversation persistence is likewise a precondition, so the
        same method safely guards project switch, project close and app close.
        """
        code_editor = self._get_panel("code_editor")
        if code_editor is not None:
            prepare_close_all = getattr(code_editor, "prepare_close_all", None)
            if not callable(prepare_close_all):
                if self.logger:
                    self.logger.error(
                        "Code editor does not expose prepare_close_all(); "
                        "workspace transition vetoed"
                    )
                return False

            try:
                if not bool(prepare_close_all()):
                    return False
            except Exception as exc:
                # A broken preflight must fail closed.  Continuing here could
                # bind an old dirty editor to newly initialised services.
                if self.logger:
                    self.logger.error(f"Workspace transition preflight failed: {exc}")
                return False

        manager = self.session_state_manager
        project_root = ""
        project_service = self.project_service
        get_project_root = getattr(project_service, "get_current_project_path", None)
        if callable(get_project_root):
            try:
                project_root = str(get_project_root() or "")
            except Exception:
                project_root = ""
        if not project_root and manager is not None:
            get_manager_root = getattr(manager, "get_project_root", None)
            if callable(get_manager_root):
                try:
                    project_root = str(get_manager_root() or "")
                except Exception:
                    project_root = ""

        # No active project/conversation means there is nothing else to save.
        if not project_root:
            return True
        if manager is None:
            self._report_session_persistence_failure(
                "Conversation session service is unavailable."
            )
            return False
        try:
            if manager.ensure_current_session_persisted(project_root):
                return True
        except Exception as exc:
            if self.logger:
                self.logger.error(f"Conversation persistence preflight failed: {exc}")
            self._report_session_persistence_failure(str(exc))
            return False

        self._report_session_persistence_failure(
            "The current conversation could not be saved."
        )
        return False

    def _report_session_persistence_failure(self, detail: str) -> None:
        """Show one actionable warning for a transition persistence veto."""
        message = self._get_text(
            "dialog.session_persistence_failed",
            "The current conversation could not be saved. The workspace was "
            "left open so you can retry.",
        )
        if detail and self.logger:
            self.logger.error(f"{message} Detail: {detail}")
        QMessageBox.warning(
            self._main_window,
            self._get_text("dialog.error.title", "Error"),
            message,
        )

    def _report_project_service_unavailable(self) -> None:
        """Report a hard lifecycle dependency without faking project state."""
        message = self._get_text(
            "dialog.project_service_unavailable",
            "Project service is unavailable. Workspace state was not changed. "
            "Please restart the application.",
        )
        if self.logger:
            self.logger.error(message)
        QMessageBox.warning(
            self._main_window,
            self._get_text("dialog.error.title", "Error"),
            message,
        )

    def _open_project(self, folder_path: str) -> bool:
        """
        打开项目
        
        每次打开项目都会：
        1. 同步预检并处理未保存编辑器；Cancel 时不改变任何项目状态
        2. 通过 project_service.switch_project() 关闭旧项目并初始化新项目
        3. 初始化项目状态目录并发布项目打开状态
        """
        if self.logger:
            self.logger.info(f"Opening workspace: {folder_path}")

        project_service = self.project_service
        if project_service is None:
            self._report_project_service_unavailable()
            return False

        if not self.prepare_workspace_transition():
            if self.logger:
                self.logger.info("Workspace transition cancelled before project state changed")
            return False

        # Both the folder picker and the recent-project menu use this same
        # path.  ``switch_project`` is also valid when no project is open:
        # close_project() is then a successful no-op.
        success, msg = project_service.switch_project(folder_path)
        if not success:
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.error.title", "Error"),
                msg
            )
            return False
        if self.logger:
            self.logger.info(f"Project initialized: {msg}")
        return True

    def on_close_workspace(self) -> bool:
        """关闭工作文件夹"""
        project_service = self.project_service
        if project_service is None:
            self._report_project_service_unavailable()
            return False

        if not self.prepare_workspace_transition():
            if self.logger:
                self.logger.info("Workspace close cancelled before project state changed")
            return False

        success, msg = project_service.close_project()
        if not success:
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.error.title", "Error"),
                msg
            )
            return False
        if self.logger:
            self.logger.info(f"Project closed: {msg}")
        return True

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

    def on_recent_project_clicked(self, path: str) -> bool:
        """点击最近项目"""
        if os.path.isdir(path):
            # Keep recent-project restore and the normal folder picker on the
            # exact same vetoable transition path.
            return self._open_project(path)
        else:
            reply = QMessageBox.question(
                self._main_window,
                self._get_text("dialog.confirm.title", "Confirm"),
                f"Path does not exist: {path}\n\nRemove from recent list?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                if self.project_service:
                    return bool(self.project_service.remove_from_recent(path))
        return False

    def on_clear_recent_projects(self):
        """清除最近项目记录"""
        if self.project_service:
            self.project_service.clear_recent_projects()
        elif self.config_manager:
            self.config_manager.set("recent_projects", [])

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
        self._dispatch_copy_like_action("copy")

    def on_edit_paste(self):
        panel = self._get_panel("code_editor")
        if panel is not None and hasattr(panel, "paste"):
            panel.paste()

    def on_edit_select_all(self):
        self._dispatch_copy_like_action("select_all")

    def on_show_conversation(self):
        self._activate_right_panel("conversation")

    def on_show_rag(self):
        self._activate_right_panel("rag")

    def on_new_conversation(self):
        self.on_show_conversation()
        panel = self._get_right_panel()
        if panel is not None:
            panel.start_new_conversation()

    def on_conversation_history(self):
        self.on_show_conversation()
        panel = self._get_right_panel()
        if panel is not None:
            panel.request_history()

    def on_conversation_compress(self):
        self.on_show_conversation()
        panel = self._get_right_panel()
        if panel is not None:
            panel.request_compress_context()

    def on_reindex_knowledge(self):
        self.on_show_rag()
        panel = self._get_right_panel()
        if panel is not None:
            panel.trigger_reindex()

    def on_clear_knowledge(self):
        self.on_show_rag()
        panel = self._get_right_panel()
        if panel is not None:
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
    # 工具操作回调
    # ============================================================

    def on_api_config(self):
        """打开模型配置对话框"""
        self._main_window.open_model_config_surface()

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
