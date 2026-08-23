from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QMainWindow, QMessageBox

from shared.event_types import (
    EVENT_STATE_PROJECT_CLOSED,
    EVENT_STATE_PROJECT_OPENED,
    EVENT_SIM_COMPLETE,
    EVENT_SIM_ERROR,
    EVENT_SIM_STARTED,
)
from shared.path_utils import normalize_identity_path
from shared.service_locator import ServiceLocator
from shared.service_names import (
    SVC_EVENT_BUS,
    SVC_SESSION_STATE,
    SVC_SIMULATION_JOB_MANAGER,
)
from shared.sim_event_payload import extract_sim_payload
from shared.workspace_file_types import is_simulatable_circuit_extension


class SimulationCommandController(QObject):
    """Submit editor runs and own their exact presentation identity.

    Every Run-button click goes through ``SimulationJobManager``.  The
    returned job id is registered together with the project captured at
    submission time, then handed directly to the bound ``SimulationTab``.
    That explicit hand-off is the only way a job may claim the visible run
    state.  A later ``EVENT_SIM_STARTED`` is merely a lifecycle update; it
    cannot make an arbitrary ``ui_editor`` job visible after a project was
    closed and reopened at the same path.

    UX policy
    ---------

    MVP keeps a single in-flight UI submission at a time: while
    :meth:`_has_active_submission` is true the Run button is
    disabled and a redundant programmatic invocation surfaces an
    info dialog. This is **a UX choice**, not an architectural
    constraint — the underlying ``SimulationJobManager`` already
    runs jobs concurrently. Relaxing the policy in the future means
    only changing the gate inside :meth:`run_simulation`; nothing
    else in this file assumes "at most one job".

    Agent-origin jobs and jobs submitted by another UI owner still flow
    through the shared EventBus, but neither the controller nor its bound
    tab accepts them as presentation state.
    """

    def __init__(self, main_window: QMainWindow):
        super().__init__(main_window)
        self._main_window = main_window
        self._menu_manager = None
        self._code_editor = None
        self._simulation_tab = None
        self._logger = None
        self._current_file_path = ""
        self._current_file_name = ""
        self._current_file_dirty = False

        # A job id alone is not a sufficient UI identity: after switching
        # workspaces, an old job may still finish and publish its terminal
        # event.  Bind each submission to the canonical project identity
        # captured at submit time so an old event can neither disable the
        # new workspace's Run action nor pop a modal over it.
        self._submitted_jobs: Dict[str, str] = {}

        # (event_type, handler) pairs we registered with the EventBus,
        # tracked so shutdown() can unsubscribe symmetrically.
        self._event_subscriptions: List[Tuple[str, Any]] = []
        self._subscribe_simulation_events()

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
        self._code_editor = code_editor
        if self._code_editor is not None:
            self._code_editor.workspace_file_state_changed.connect(self._on_workspace_file_state_changed)
            self._code_editor.run_simulation_requested.connect(self.run_simulation)
            self._on_workspace_file_state_changed(self._code_editor.get_workspace_file_state())
        else:
            self._current_file_path = ""
            self._current_file_name = ""
            self._current_file_dirty = False
            self.refresh_ui_state()

    def bind_simulation_tab(self, simulation_tab) -> None:
        """Bind the sole visible result surface owned by this controller."""
        self._simulation_tab = simulation_tab

    def retranslate_ui(self) -> None:
        self.refresh_ui_state()

    def refresh_ui_state(self) -> None:
        state = self._build_ui_state()
        if self._menu_manager is not None:
            self._menu_manager.set_action_enabled("sim_run", bool(state.get("canRun", False)))
        if self._code_editor is not None:
            self._code_editor.set_simulation_control_state(state)

    def run_simulation(self) -> None:
        """Validate the UI preconditions, then submit a job to the manager.

        The prelude (workspace open, active file present, file
        simulatable, dirty file saved, single-in-flight UX gate)
        lives in this method because every gate is a *UI-layer*
        decision — the manager itself accepts any well-formed
        submission regardless of UI state. Once gating passes,
        ``manager.submit(origin=JobOrigin.UI_EDITOR, ...)`` is the
        only path used; ``EVENT_SIM_*`` events come back through
        the bus and are routed by ``job_id``.
        """
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

        # UX policy gate (see class docstring): MVP keeps a single
        # in-flight UI submission. The same gate is also reflected
        # in canRun=False so the button is normally disabled —
        # this branch handles the keyboard-shortcut / tested
        # invocation paths that bypass the disabled visual state.
        if self._has_active_submission():
            QMessageBox.information(
                self._main_window,
                self._get_text("dialog.info.title", "Info"),
                self._get_text(
                    "simulation.another_run_in_progress",
                    "当前已有仿真正在进行，请等待其结束后再发起新的仿真。"
                )
            )
            return

        if self._current_file_dirty and self._code_editor is not None:
            if not self._code_editor.save_file():
                QMessageBox.warning(
                    self._main_window,
                    self._get_text("dialog.warning.title", "Warning"),
                    self._get_text(
                        "simulation.save_before_run_failed",
                        "当前电路文件保存失败，未启动仿真。"
                    )
                )
                return

        manager = ServiceLocator.get_optional(SVC_SIMULATION_JOB_MANAGER)
        if manager is None:
            # The job manager is registered by application.bootstrap;
            # missing it at runtime is a startup-order bug, not a
            # user-recoverable error. Surface it loudly.
            raise RuntimeError(
                "SimulationJobManager is not registered in ServiceLocator; "
                "this is a bootstrap-time bug (expected SVC_SIMULATION_JOB_MANAGER)."
            )
        if self._simulation_tab is None:
            raise RuntimeError(
                "SimulationCommandController has no bound SimulationTab; "
                "submitting would create an unowned UI job."
            )

        # Local import: avoids dragging the domain layer into module
        # import time (which would break the strict layer ordering
        # the rest of the codebase enforces).
        from domain.simulation.models.simulation_job import JobOrigin

        try:
            job = manager.submit(
                circuit_file=file_path,
                origin=JobOrigin.UI_EDITOR,
                project_root=project_root,
            )
        except Exception as exc:
            if self.logger:
                self.logger.exception("Failed to submit UI simulation")
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.error.title", "Error"),
                self._get_text(
                    "simulation.submit_failed",
                    "无法启动仿真：{message}",
                ).format(message=str(exc)),
            )
            self.refresh_ui_state()
            return
        self._submitted_jobs[job.job_id] = normalize_identity_path(job.project_root)
        claimed = self._simulation_tab.claim_ui_job(
            job_id=job.job_id,
            project_root=job.project_root,
            circuit_file=job.circuit_file,
        )
        if not claimed:
            manager.request_cancel(job.job_id)
            self._submitted_jobs.pop(job.job_id, None)
            raise RuntimeError(
                "SimulationTab rejected the submitted job identity; "
                "the job was cancelled to avoid an unowned UI run."
            )
        if self.logger:
            self.logger.info(
                f"SimulationCommandController submitted job_id={job.job_id} "
                f"circuit_file={file_path}"
            )
        # Refresh immediately so the button flips to disabled before
        # the manager's first EVENT_SIM_STARTED roundtrip lands.
        self.refresh_ui_state()

    # ------------------------------------------------------------------
    # EventBus subscription
    # ------------------------------------------------------------------

    def _subscribe_simulation_events(self) -> None:
        """Subscribe to the three simulation lifecycle events.

        Handlers run on the UI main thread (the EventBus dispatches
        cross-thread publishes via ``QMetaObject.invokeMethod``), so
        :class:`QMessageBox` calls inside them are safe.
        """
        bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
        if bus is None:
            return
        for event_type, handler in (
            (EVENT_STATE_PROJECT_OPENED, self._on_project_context_changed),
            (EVENT_STATE_PROJECT_CLOSED, self._on_project_context_changed),
            (EVENT_SIM_STARTED, self._on_sim_started_event),
            (EVENT_SIM_COMPLETE, self._on_sim_complete_event),
            (EVENT_SIM_ERROR, self._on_sim_error_event),
        ):
            bus.subscribe(event_type, handler)
            self._event_subscriptions.append((event_type, handler))

    def shutdown(self) -> None:
        """Symmetrically unsubscribe from the EventBus.

        Idempotent: safe to call multiple times. Called by
        ``MainWindow.closeEvent``; tests can also call it to keep
        the bus clean across cases.
        """
        bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
        if bus is not None:
            for event_type, handler in self._event_subscriptions:
                try:
                    bus.unsubscribe(event_type, handler)
                except Exception:
                    pass
        self._event_subscriptions.clear()

    def _on_sim_started_event(self, event_data: dict) -> None:
        payload = extract_sim_payload(EVENT_SIM_STARTED, event_data)
        if not self._event_matches_current_submission(payload):
            # Not one of ours — agent backend or a future second UI
            # submission channel. Ignore so we never flip our button
            # state on someone else's run.
            return
        # The button is already disabled (set in run_simulation), but
        # external state can shift between submit and STARTED — refresh
        # so tooltip / canRun stay consistent with manager state.
        self.refresh_ui_state()

    def _on_sim_complete_event(self, event_data: dict) -> None:
        payload = extract_sim_payload(EVENT_SIM_COMPLETE, event_data)
        job_id = payload["job_id"]
        if not self._event_matches_current_submission(payload):
            return
        self._submitted_jobs.pop(job_id, None)
        if self.logger:
            self.logger.info(
                f"SimulationCommandController: job_id={job_id} completed "
                f"result_path={payload['result_path']}"
            )
        self.refresh_ui_state()

    def _on_sim_error_event(self, event_data: dict) -> None:
        payload = extract_sim_payload(EVENT_SIM_ERROR, event_data)
        job_id = payload["job_id"]
        if not self._event_matches_current_submission(payload):
            return
        self._submitted_jobs.pop(job_id, None)
        cancelled = bool(payload["cancelled"])
        error_message = payload["error_message"] or "unknown"
        if self.logger:
            self.logger.info(
                f"SimulationCommandController: job_id={job_id} "
                f"{'cancelled' if cancelled else 'failed'}: {error_message}"
            )
        if not cancelled:
            # Cancellation was a deliberate user (or future scripted)
            # action — popping a dialog "you cancelled successfully"
            # would just be noise. Real failures, on the other hand,
            # demand acknowledgement.
            QMessageBox.warning(
                self._main_window,
                self._get_text("dialog.error.title", "Error"),
                self._get_text(
                    "simulation.job_failed",
                    "仿真执行失败：{message}"
                ).format(message=error_message)
            )
        self.refresh_ui_state()

    def _on_project_context_changed(self, event_data: dict) -> None:
        """Release UI ownership of jobs from the previous workspace.

        The manager still owns and settles those jobs.  The controller only
        drops its presentation binding; carrying it into the next project
        would make unrelated work disable the new project's Run button.
        """
        del event_data
        self._submitted_jobs.clear()
        self.refresh_ui_state()

    def _event_matches_current_submission(self, payload: Dict[str, Any]) -> bool:
        job_id = str(payload.get("job_id") or "")
        submitted_project = self._submitted_jobs.get(job_id)
        if not submitted_project:
            return False
        payload_project = normalize_identity_path(str(payload.get("project_root") or ""))
        current_project = normalize_identity_path(self._get_project_root() or "")
        return bool(
            current_project
            and payload_project == submitted_project
            and current_project == submitted_project
        )

    def _has_active_submission(self) -> bool:
        """True iff any controller-submitted job is still non-terminal.

        The manager is the authoritative state owner. The local set
        is just a filter telling us *which* jobs are ours; status
        comes from ``manager.query``. Iterating a snapshot
        (``tuple(self._submitted_jobs)``) prevents the
        ``RuntimeError: Set changed size during iteration`` we'd
        otherwise risk if a terminal event arrives mid-check.
        """
        if not self._submitted_jobs:
            return False
        manager = ServiceLocator.get_optional(SVC_SIMULATION_JOB_MANAGER)
        if manager is None:
            return False
        stale_job_ids = []
        current_project = normalize_identity_path(self._get_project_root() or "")
        for job_id, submitted_project in tuple(self._submitted_jobs.items()):
            if not current_project or submitted_project != current_project:
                stale_job_ids.append(job_id)
                continue
            job = manager.query(job_id)
            if job is not None and not job.is_terminal:
                return True
            stale_job_ids.append(job_id)
        for job_id in stale_job_ids:
            self._submitted_jobs.pop(job_id, None)
        return False

    def _build_ui_state(self) -> Dict[str, Any]:
        project_root = self._get_project_root()
        has_active_circuit_file = bool(
            self._current_file_path and is_simulatable_circuit_extension(self._current_file_path)
        )
        # Authoritatively answered by the manager, filtered to this
        # controller's own submitted jobs — so a concurrent
        # agent-origin simulation does NOT disable the UI Run button.
        has_inflight_submission = self._has_active_submission()
        can_run = bool(project_root and has_active_circuit_file) and not has_inflight_submission

        # Tooltip selection is ordered by urgency: in-flight run trumps
        # every static precondition because it is the one transient
        # state the user is actively waiting on.
        if has_inflight_submission:
            primary_tooltip = self._get_text(
                "simulation.another_run_in_progress",
                "当前已有仿真正在进行，请等待其结束后再发起新的仿真。"
            )
        elif not project_root:
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
            "canRun": can_run,
            "primaryEnabled": can_run,
            "primaryTooltip": primary_tooltip,
            "isRunning": has_inflight_submission,
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

    def _get_project_root(self) -> Optional[str]:
        try:
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
