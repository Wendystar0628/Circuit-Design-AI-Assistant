from pathlib import Path
from typing import Any, Dict, Optional

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QMainWindow, QMessageBox

from application.tasks.simulation_task import SimulationTask
from shared.workspace_file_types import is_simulatable_circuit_extension


class SimulationCommandController(QObject):
    def __init__(self, main_window: QMainWindow):
        super().__init__(main_window)
        self._main_window = main_window
        self._menu_manager = None
        self._code_editor = None
        self._logger = None
        self._current_file_path = ""
        self._current_file_name = ""
        self._current_file_dirty = False
        self._stop_requested = False
        self._task = SimulationTask(self)
        self._task.simulation_started.connect(self._on_simulation_started)
        self._task.simulation_completed.connect(self._on_simulation_completed)
        self._task.simulation_error.connect(self._on_simulation_error)

    @property
    def logger(self):
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("simulation_command_controller")
            except Exception:
                pass
        return self._logger

    def bind_menu_manager(self, menu_manager) -> None:
        self._menu_manager = menu_manager
        self.refresh_ui_state()

    def bind_code_editor(self, code_editor) -> None:
        if self._code_editor is code_editor:
            return
        if self._code_editor is not None:
            try:
                self._code_editor.workspace_file_state_changed.disconnect(self._on_workspace_file_state_changed)
            except Exception:
                pass
            try:
                self._code_editor.run_simulation_requested.disconnect(self.run_simulation)
            except Exception:
                pass
            try:
                self._code_editor.stop_simulation_requested.disconnect(self.stop_simulation)
            except Exception:
                pass
        self._code_editor = code_editor
        if self._code_editor is not None:
            self._code_editor.workspace_file_state_changed.connect(self._on_workspace_file_state_changed)
            self._code_editor.run_simulation_requested.connect(self.run_simulation)
            self._code_editor.stop_simulation_requested.connect(self.stop_simulation)
            self._on_workspace_file_state_changed(self._code_editor.get_workspace_file_state())
        else:
            self._current_file_path = ""
            self._current_file_name = ""
            self._current_file_dirty = False
            self.refresh_ui_state()

    def retranslate_ui(self) -> None:
        self.refresh_ui_state()

    def refresh_ui_state(self) -> None:
        state = self._build_ui_state()
        if self._menu_manager is not None:
            self._menu_manager.set_action_enabled("sim_run", bool(state.get("canRun", False)))
            self._menu_manager.set_action_enabled("sim_stop", bool(state.get("canStop", False)))
        if self._code_editor is not None:
            self._code_editor.set_simulation_control_state(state)

    def run_simulation(self) -> None:
        if self._task.is_running:
            return

        project_root = self._get_project_root()
        if not project_root:
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.warning.title", "Warning"),
                self._get_text("status.open_workspace", "Please open a workspace folder")
            )
            return

        file_path = self._current_file_path
        if not file_path:
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.warning.title", "Warning"),
                self._get_text(
                    "simulation.require_active_circuit_file",
                    "请先在编辑器中打开一个可仿真的电路文件（.cir / .sp / .spice / .net / .ckt）"
                )
            )
            return

        if not is_simulatable_circuit_extension(file_path):
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.warning.title", "Warning"),
                self._get_text(
                    "simulation.invalid_active_file",
                    "当前活动文件不是可仿真的电路文件：{name}"
                ).format(name=Path(file_path).name)
            )
            return

        if self._current_file_dirty and self._code_editor is not None:
            if not self._code_editor.save_file():
                QMessageBox.warning(
                    self._main_window,
                    self._get_text("dialog.warning.title", "Warning"),
                    self._get_text(
                        "simulation.save_before_run_failed",
                        "当前电路文件保存失败，已取消仿真。"
                    )
                )
                return

        self._stop_requested = False
        if not self._task.run_file(file_path, project_root):
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.warning.title", "Warning"),
                self._get_text("simulation.start_failed", "无法启动仿真任务")
            )
            self.refresh_ui_state()
            return

        if self.logger:
            self.logger.info(f"Started simulation for active editor file: {file_path}")
        self.refresh_ui_state()

    def stop_simulation(self) -> None:
        if not self._task.is_running or self._stop_requested:
            return
        if not self._task.cancel():
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.warning.title", "Warning"),
                self._get_text("simulation.cancel_failed", "无法取消仿真")
            )
            return
        self._stop_requested = True
        if self.logger:
            self.logger.info("Simulation stop requested")
        self.refresh_ui_state()

    def _build_ui_state(self) -> Dict[str, Any]:
        project_root = self._get_project_root()
        is_running = self._task.is_running
        has_active_circuit_file = bool(
            self._current_file_path and is_simulatable_circuit_extension(self._current_file_path)
        )
        can_run = bool(project_root and has_active_circuit_file and not is_running)
        can_stop = bool(is_running and not self._stop_requested)

        if is_running:
            primary_action = "stop"
            primary_enabled = can_stop
            primary_tooltip = self._get_text(
                "simulation.stop_requested_tip",
                "正在请求停止仿真"
            ) if self._stop_requested else self._get_text(
                "menu.simulation.stop",
                "Stop Simulation"
            )
        else:
            primary_action = "run"
            primary_enabled = can_run
            if not project_root:
                primary_tooltip = self._get_text(
                    "status.open_workspace",
                    "Please open a workspace folder"
                )
            elif not self._current_file_path:
                primary_tooltip = self._get_text(
                    "simulation.require_active_circuit_file",
                    "请先在编辑器中打开一个可仿真的电路文件（.cir / .sp / .spice / .net / .ckt）"
                )
            elif not has_active_circuit_file:
                primary_tooltip = self._get_text(
                    "simulation.invalid_active_file",
                    "当前活动文件不是可仿真的电路文件：{name}"
                ).format(name=self._current_file_name or Path(self._current_file_path).name)
            elif self._current_file_dirty:
                primary_tooltip = self._get_text(
                    "simulation.save_and_run_current_file",
                    "保存并运行当前电路文件"
                )
            else:
                primary_tooltip = self._get_text(
                    "simulation.run_current_file",
                    "运行当前电路文件"
                )

        return {
            "currentFilePath": self._current_file_path,
            "currentFileName": self._current_file_name,
            "isCurrentFileDirty": self._current_file_dirty,
            "hasActiveCircuitFile": has_active_circuit_file,
            "isRunning": is_running,
            "isStopRequested": self._stop_requested,
            "canRun": can_run,
            "canStop": can_stop,
            "primaryAction": primary_action,
            "primaryEnabled": primary_enabled,
            "primaryTooltip": primary_tooltip,
        }

    def _on_workspace_file_state_changed(self, state: Dict[str, Any]) -> None:
        items = state.get("items", []) if isinstance(state, dict) else []
        active_item = None
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and item.get("is_active", False):
                active_item = item
                break
        if active_item is None:
            self._current_file_path = ""
            self._current_file_name = ""
            self._current_file_dirty = False
        else:
            self._current_file_path = str(active_item.get("path", "") or "")
            self._current_file_name = str(active_item.get("name", "") or Path(self._current_file_path).name)
            self._current_file_dirty = bool(active_item.get("is_dirty", False))
        self.refresh_ui_state()

    def _on_simulation_started(self, file_path: str) -> None:
        self._stop_requested = False
        if self.logger:
            self.logger.info(f"Simulation started: {file_path}")
        self.refresh_ui_state()

    def _on_simulation_completed(self, result: object) -> None:
        self._stop_requested = False
        if self.logger:
            self.logger.info(f"Simulation completed: success={getattr(result, 'success', False)}")
        self.refresh_ui_state()

    def _on_simulation_error(self, error_type: str, error_message: str) -> None:
        self._stop_requested = False
        if self.logger:
            self.logger.error(f"Simulation error: {error_type} - {error_message}")
        QMessageBox.critical(
            self._main_window,
            self._get_text("dialog.error.title", "Error"),
            f"{error_type}\n{error_message}"
        )
        self.refresh_ui_state()

    def _get_project_root(self) -> Optional[str]:
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_SESSION_STATE
            session_state = ServiceLocator.get_optional(SVC_SESSION_STATE)
            if session_state:
                return str(session_state.project_root or "") or None
        except Exception:
            pass
        return None

    def _get_text(self, key: str, default: str) -> str:
        if hasattr(self._main_window, "_get_text"):
            return self._main_window._get_text(key, default)
        return default


__all__ = ["SimulationCommandController"]
