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
from typing import Optional, Dict, Any, Callable, Union

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
            "on_toggle_panel": self.on_toggle_panel,
            "on_design_goals": self.on_design_goals,
            "on_iteration_history": self.on_iteration_history,
            "on_api_config": self.on_api_config,
            "on_help_docs": self.on_help_docs,
            "on_about": self.on_about,
            # 仿真相关回调
            "on_run_auto_simulation": self.on_run_auto_simulation,
            "on_run_select_simulation": self.on_run_select_simulation,
            "on_stop_simulation": self.on_stop_simulation,
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
        # 委托给 MainWindow 的面板管理方法
        if hasattr(self._main_window, '_on_toggle_panel'):
            self._main_window._on_toggle_panel(panel_id, visible)

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

    # ============================================================
    # 仿真操作回调
    # ============================================================

    def _get_simulation_task(self):
        """获取或创建仿真任务实例"""
        if not hasattr(self, '_simulation_task') or self._simulation_task is None:
            from application.tasks.simulation_task import SimulationTask
            self._simulation_task = SimulationTask()
            self._simulation_task.simulation_started.connect(self._on_simulation_started)
            self._simulation_task.simulation_progress.connect(self._on_simulation_progress)
            self._simulation_task.simulation_completed.connect(self._on_simulation_completed)
            self._simulation_task.simulation_error.connect(self._on_simulation_error)
        return self._simulation_task

    def _on_simulation_started(self, file_path: str):
        """仿真开始回调"""
        if self.logger:
            self.logger.info(f"仿真开始: {file_path}")

    def _on_simulation_progress(self, progress: float, message: str):
        """仿真进度回调"""
        # 可通过状态栏显示进度
        pass

    def _on_simulation_completed(self, result):
        """仿真完成回调"""
        if self.logger:
            self.logger.info(f"仿真完成: success={result.success}")
        
        if result.success:
            QMessageBox.information(
                self._main_window,
                self._get_text("dialog.info.title", "Information"),
                self._get_text(
                    "simulation.completed",
                    f"仿真完成\n分析类型: {result.analysis_type}\n耗时: {result.duration_seconds:.2f}s"
                )
            )
        else:
            error_msg = ""
            if result.error:
                error_msg = str(result.error.message) if hasattr(result.error, 'message') else str(result.error)
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.warning.title", "Warning"),
                self._get_text(
                    "simulation.failed",
                    f"仿真失败\n{error_msg}"
                )
            )

    def _on_simulation_error(self, error_type: str, error_message: str):
        """仿真错误回调"""
        if self.logger:
            self.logger.error(f"仿真错误: {error_type} - {error_message}")
        
        QMessageBox.critical(
            self._main_window,
            self._get_text("dialog.error.title", "Error"),
            f"{error_type}\n{error_message}"
        )

    # 支持仿真的电路文件扩展名
    CIRCUIT_EXTENSIONS = {'.cir', '.sp', '.spice', '.net', '.ckt'}

    def on_run_auto_simulation(self):
        """对当前编辑器打开的电路文件运行仿真"""
        # 检查是否已打开项目
        project_root = self._get_project_root()
        if not project_root:
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.warning.title", "Warning"),
                self._get_text("status.open_workspace", "Please open a workspace folder")
            )
            return
        
        # 检查是否有仿真正在运行
        task = self._get_simulation_task()
        if task.is_running:
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.warning.title", "Warning"),
                self._get_text("simulation.already_running", "仿真正在运行中")
            )
            return
        
        # 从编辑器获取当前活动文件
        file_path = self._get_active_editor_file()
        if not file_path:
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.warning.title", "Warning"),
                "请先在编辑器中打开一个电路文件（.cir / .sp / .spice / .net / .ckt）"
            )
            return
        
        # 检查是否为电路文件
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self.CIRCUIT_EXTENSIONS:
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.warning.title", "Warning"),
                f"当前文件不是电路文件：{os.path.basename(file_path)}\n"
                f"请切换到电路文件（.cir / .sp / .spice / .net / .ckt）后再运行仿真"
            )
            return
        
        # 启动仿真
        if task.run_file(file_path, project_root):
            if self.logger:
                self.logger.info(f"启动仿真: {file_path}")
        else:
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.warning.title", "Warning"),
                self._get_text("simulation.start_failed", "无法启动仿真任务")
            )

    def _get_active_editor_file(self) -> Optional[str]:
        """获取当前编辑器活动文件路径"""
        editor_panel = self._panels.get("code_editor")
        if editor_panel and hasattr(editor_panel, 'get_current_file'):
            return editor_panel.get_current_file()
        return None

    def on_run_select_simulation(self):
        """手动选择文件并运行仿真"""
        # 检查是否已打开项目
        project_root = self._get_project_root()
        if not project_root:
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.warning.title", "Warning"),
                self._get_text("status.open_workspace", "Please open a workspace folder")
            )
            return
        
        # 检查是否有仿真正在运行
        task = self._get_simulation_task()
        if task.is_running:
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.warning.title", "Warning"),
                self._get_text("simulation.already_running", "仿真正在运行中")
            )
            return
        
        # 弹出文件选择对话框
        file_path, _ = QFileDialog.getOpenFileName(
            self._main_window,
            self._get_text("dialog.select_simulation_file.title", "Select Simulation File"),
            project_root,
            "Circuit Files (*.cir *.sp *.spice *.net);;Python Scripts (*.py);;All Files (*.*)"
        )
        
        if not file_path:
            return
        
        # 启动仿真
        if task.run_file(file_path, project_root):
            if self.logger:
                self.logger.info(f"启动文件仿真: {file_path}")
        else:
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.warning.title", "Warning"),
                self._get_text("simulation.start_failed", "无法启动仿真任务")
            )

    def on_stop_simulation(self):
        """停止当前仿真"""
        task = self._get_simulation_task()
        
        if not task.is_running:
            QMessageBox.information(
                self._main_window,
                self._get_text("dialog.info.title", "Information"),
                self._get_text("simulation.not_running", "没有正在运行的仿真")
            )
            return
        
        if task.cancel():
            if self.logger:
                self.logger.info("已请求取消仿真")
            QMessageBox.information(
                self._main_window,
                self._get_text("dialog.info.title", "Information"),
                self._get_text("simulation.cancel_requested", "已请求取消仿真")
            )
        else:
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.warning.title", "Warning"),
                self._get_text("simulation.cancel_failed", "无法取消仿真")
            )

__all__ = ["ActionHandlers"]
