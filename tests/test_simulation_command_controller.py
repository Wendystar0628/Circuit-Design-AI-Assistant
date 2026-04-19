"""Behavioural tests for ``SimulationCommandController`` (Step 6).

The controller is the editor Run-button glue: it submits jobs to
``SimulationJobManager`` and observes ``EVENT_SIM_*`` to update its
own UI state. The Step-5 AST guard already enforces that every
handler decodes payload via ``extract_sim_payload`` on its first
line; these tests cover the *behavioural* contract that Step 6
locks in:

* Lifecycle events for jobs the controller did **not** submit are
  ignored (so an agent-origin run never flips the editor button).
* Lifecycle events for jobs it *did* submit remove the id from the
  registry and refresh the UI.
* ``EVENT_SIM_ERROR`` with ``cancelled=False`` pops a warning
  dialog; with ``cancelled=True`` it does not (cancellation was
  intentional, not a failure to acknowledge).
* ``_has_active_submission`` consults the manager, not the local
  set — so an out-of-order ``COMPLETED`` event the controller
  somehow missed cannot leave the button stuck-disabled.
* ``run_simulation`` honours the single-in-flight UX policy, then
  delegates to ``manager.submit(origin=JobOrigin.UI_EDITOR, ...)``.
* ``run_simulation`` raises ``RuntimeError`` if the manager is
  unregistered (this is a bootstrap-time bug, not a user error).
* ``shutdown`` is symmetric with ``__init__`` subscription so the
  EventBus does not leak handler references across windows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pytest
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox

from presentation.simulation_command_controller import SimulationCommandController
from shared.event_bus import EventBus
from shared.event_types import (
    EVENT_SIM_COMPLETE,
    EVENT_SIM_ERROR,
    EVENT_SIM_STARTED,
)
from shared.service_locator import ServiceLocator
from shared.service_names import (
    SVC_EVENT_BUS,
    SVC_SESSION_STATE,
    SVC_SIMULATION_JOB_MANAGER,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def qapp():
    """Reuse a single QApplication across the test module — Qt forbids
    constructing more than one per process and pytest-qt's qtbot is
    overkill here since we never run the event loop."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@dataclass
class _FakeJob:
    """Minimal stand-in for ``domain.simulation.models.SimulationJob``.

    The controller only reads ``job_id`` (for routing) and
    ``is_terminal`` (for ``_has_active_submission``). Anything more
    in this fake would be over-fitting."""

    job_id: str
    is_terminal: bool = False


class _FakeManager:
    """SimulationJobManager double scripted by tests.

    The real manager owns a thread pool and a service stack we don't
    need for controller-layer behaviour: tests drive lifecycle events
    by ``bus.publish`` directly so we control the exact ordering and
    payloads. ``submit`` simply mints fresh job ids and remembers what
    arguments it was called with so the test can assert origin /
    project_root / circuit_file passthrough."""

    def __init__(self) -> None:
        self._jobs: Dict[str, _FakeJob] = {}
        self._next_index = 0
        self.submit_calls: List[Dict[str, Any]] = []

    def submit(self, **kwargs: Any) -> _FakeJob:
        self._next_index += 1
        job = _FakeJob(job_id=f"job_{self._next_index:03d}")
        self._jobs[job.job_id] = job
        self.submit_calls.append(dict(kwargs))
        return job

    def query(self, job_id: str) -> Optional[_FakeJob]:
        return self._jobs.get(job_id)

    def mark_terminal(self, job_id: str) -> None:
        """Test helper: simulate the manager finishing a job *before*
        the corresponding event reaches the controller. Used to verify
        that ``_has_active_submission`` consults the manager rather
        than blindly trusting its own set."""
        if job_id in self._jobs:
            self._jobs[job_id].is_terminal = True


class _FakeSessionState:
    def __init__(self, project_root: str = "/tmp/proj") -> None:
        self.project_root = project_root


@pytest.fixture
def services(qapp, monkeypatch):
    """Per-test isolated ServiceLocator with a real EventBus + fake
    session state + fake manager + recorded QMessageBox calls.

    Returning the bag rather than individual fixtures keeps the
    coupling visible at the call site (each test states up front
    what it depends on)."""
    del qapp
    ServiceLocator.clear()

    bus = EventBus()
    manager = _FakeManager()
    ServiceLocator.register(SVC_EVENT_BUS, bus)
    ServiceLocator.register(SVC_SIMULATION_JOB_MANAGER, manager)
    ServiceLocator.register(SVC_SESSION_STATE, _FakeSessionState())

    # QMessageBox.warning / .information would block on a real modal
    # dialog. Capture the (kind, text) tuples instead so tests can
    # assert *which* dialog (or none) the controller chose to pop.
    dialogs: List[Tuple[str, str]] = []

    def _capture(kind: str):
        def _impl(parent, title, text, *args, **kw):
            dialogs.append((kind, str(text)))
            return QMessageBox.StandardButton.Ok
        return _impl

    monkeypatch.setattr(QMessageBox, "warning", _capture("warning"))
    monkeypatch.setattr(QMessageBox, "information", _capture("information"))

    yield {
        "bus": bus,
        "manager": manager,
        "dialogs": dialogs,
    }

    ServiceLocator.clear()


@pytest.fixture
def controller(services):
    """Construct the controller after services are wired so its
    ``__init__`` can subscribe to the bus immediately. ``shutdown``
    runs at teardown to symmetrise."""
    main_window = QMainWindow()
    ctrl = SimulationCommandController(main_window)
    yield ctrl
    ctrl.shutdown()
    main_window.close()


def _payload_started(job_id: str, **overrides: Any) -> Dict[str, Any]:
    base = {
        "job_id": job_id,
        "origin": "ui_editor",
        "circuit_file": "amp.cir",
        "project_root": "/tmp/proj",
        "analysis_type": "tran",
        "config": {},
    }
    base.update(overrides)
    return base


def _payload_complete(job_id: str, **overrides: Any) -> Dict[str, Any]:
    base = {
        "job_id": job_id,
        "origin": "ui_editor",
        "circuit_file": "amp.cir",
        "project_root": "/tmp/proj",
        "result_path": "simulation_results/amp/ts/result.json",
        "export_root": "/tmp/proj/simulation_results/amp/ts",
        "success": True,
        "duration_seconds": 0.1,
    }
    base.update(overrides)
    return base


def _payload_error(job_id: str, **overrides: Any) -> Dict[str, Any]:
    base = {
        "job_id": job_id,
        "origin": "ui_editor",
        "circuit_file": "amp.cir",
        "project_root": "/tmp/proj",
        "error_message": "boom",
        "result_path": "simulation_results/amp/ts/result.json",
        "export_root": "/tmp/proj/simulation_results/amp/ts",
        "cancelled": False,
        "duration_seconds": 0.1,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Identity routing: events for someone else's job are ignored
# ---------------------------------------------------------------------------


def test_complete_event_for_unregistered_job_is_ignored(controller, services):
    """An agent-backend job's lifecycle event must not reach this
    controller's UI-affecting code paths. We assert *no* dialog is
    popped and the registry stays empty — both observable proxies for
    "the handler returned without doing anything"."""
    services["bus"].publish(EVENT_SIM_COMPLETE, _payload_complete("job_external_1"))

    assert services["dialogs"] == []
    assert controller._submitted_jobs == set()


def test_error_event_for_unregistered_job_does_not_pop_dialog(controller, services):
    services["bus"].publish(EVENT_SIM_ERROR, _payload_error("job_external_2"))

    # No warning dialog — the failure belongs to a job we did not
    # submit, so popping a modal would be hijacking the user's
    # attention for someone else's run.
    assert services["dialogs"] == []
    assert controller._submitted_jobs == set()


def test_started_event_for_unregistered_job_does_not_touch_state(controller, services):
    services["bus"].publish(EVENT_SIM_STARTED, _payload_started("job_external_3"))

    assert controller._submitted_jobs == set()


# ---------------------------------------------------------------------------
# Identity routing: events for our own jobs are processed
# ---------------------------------------------------------------------------


def test_complete_event_for_our_job_clears_registry(controller, services):
    """Once the controller has submitted a job, the matching COMPLETE
    event must drop it from ``_submitted_jobs`` so the Run button
    can re-enable. Without this the button would stick disabled
    forever after one successful run."""
    controller._submitted_jobs.add("job_001")

    services["bus"].publish(EVENT_SIM_COMPLETE, _payload_complete("job_001"))

    assert "job_001" not in controller._submitted_jobs


def test_error_event_with_real_failure_pops_warning_dialog(controller, services):
    controller._submitted_jobs.add("job_002")

    services["bus"].publish(
        EVENT_SIM_ERROR,
        _payload_error("job_002", error_message="netlist parse error"),
    )

    assert "job_002" not in controller._submitted_jobs
    assert len(services["dialogs"]) == 1
    kind, text = services["dialogs"][0]
    assert kind == "warning"
    # The actual error text reaches the user — important so the
    # dialog is actionable rather than a generic "something went wrong".
    assert "netlist parse error" in text


def test_error_event_with_cancellation_does_not_pop_dialog(controller, services):
    """Cancellation is intentional — a "you cancelled successfully"
    modal is pure noise. The job must still leave the registry so
    the button re-enables."""
    controller._submitted_jobs.add("job_003")

    services["bus"].publish(
        EVENT_SIM_ERROR,
        _payload_error("job_003", cancelled=True, error_message="cancelled by user"),
    )

    assert "job_003" not in controller._submitted_jobs
    assert services["dialogs"] == []


# ---------------------------------------------------------------------------
# _has_active_submission: manager is the source of truth
# ---------------------------------------------------------------------------


def test_has_active_submission_is_false_when_set_is_empty(controller):
    assert controller._has_active_submission() is False


def test_has_active_submission_returns_false_for_unknown_job(controller, services):
    """If the manager has no record of an id we hold, treat it as not
    running — better to falsely re-enable the button than to leave it
    stuck. Manager-as-truth wins over local-set-as-truth."""
    controller._submitted_jobs.add("job_ghost")
    assert services["manager"].query("job_ghost") is None

    assert controller._has_active_submission() is False


def test_has_active_submission_returns_false_when_manager_marks_terminal(
    controller, services
):
    """The local set might lag behind reality by one event tick (the
    worker thread can flip status before the COMPLETE event reaches
    the main thread). Querying the manager keeps the UI eventually-
    consistent without us having to plumb extra synchronisation."""
    job = services["manager"].submit(
        circuit_file="x.cir",
        origin=None,  # _FakeManager does not validate
        project_root="/tmp/proj",
    )
    controller._submitted_jobs.add(job.job_id)
    assert controller._has_active_submission() is True

    services["manager"].mark_terminal(job.job_id)
    assert controller._has_active_submission() is False


# ---------------------------------------------------------------------------
# run_simulation: prelude → submit
# ---------------------------------------------------------------------------


def _ready_controller_for_run(controller, file_path: str = "/tmp/proj/amp.cir") -> None:
    """Test helper: seed the controller's tracked file state so
    run_simulation's prelude passes. Mirrors what the real
    workspace_file_state_changed signal would deliver."""
    controller._current_file_path = file_path
    controller._current_file_name = "amp.cir"
    controller._current_file_dirty = False


def test_run_simulation_submits_with_ui_editor_origin(controller, services):
    _ready_controller_for_run(controller)

    controller.run_simulation()

    assert len(services["manager"].submit_calls) == 1
    call = services["manager"].submit_calls[0]
    # Origin is the whole point of Step 5/6's identity scheme — make
    # sure the controller stamps it correctly. Importing JobOrigin
    # locally here avoids the production-code's lazy-import dance.
    from domain.simulation.models.simulation_job import JobOrigin
    assert call["origin"] is JobOrigin.UI_EDITOR
    assert call["circuit_file"] == "/tmp/proj/amp.cir"
    assert call["project_root"] == "/tmp/proj"

    # The returned job_id must immediately enter the registry so the
    # next event can be routed before any roundtrip with the manager.
    assert len(controller._submitted_jobs) == 1


def test_run_simulation_refuses_second_submission_while_active(controller, services):
    """UX policy: at most one in-flight UI submission. The second
    click must produce an info dialog and *not* submit a new job."""
    _ready_controller_for_run(controller)
    controller.run_simulation()
    assert len(services["manager"].submit_calls) == 1

    controller.run_simulation()

    # Still exactly one submission; the second was gated.
    assert len(services["manager"].submit_calls) == 1
    # Single info dialog explaining why nothing happened.
    assert any(kind == "information" for kind, _ in services["dialogs"])


def test_run_simulation_re_enables_after_complete_event(controller, services):
    _ready_controller_for_run(controller)
    controller.run_simulation()
    job_id = next(iter(controller._submitted_jobs))
    services["manager"].mark_terminal(job_id)

    services["bus"].publish(EVENT_SIM_COMPLETE, _payload_complete(job_id))

    assert controller._submitted_jobs == set()
    assert controller._has_active_submission() is False
    # And a fresh submission now goes through.
    controller.run_simulation()
    assert len(services["manager"].submit_calls) == 2


def test_run_simulation_raises_if_manager_unregistered(controller, services):
    """Manager registration is a bootstrap-time invariant. Running
    without it is a programmer error and must not be papered over."""
    _ready_controller_for_run(controller)
    ServiceLocator.unregister(SVC_SIMULATION_JOB_MANAGER)

    with pytest.raises(RuntimeError, match="SimulationJobManager"):
        controller.run_simulation()


# ---------------------------------------------------------------------------
# UI state payload exposes isRunning sourced from the manager
# ---------------------------------------------------------------------------


def test_ui_state_is_running_reflects_manager_authority(controller, services):
    _ready_controller_for_run(controller)
    state_before = controller._build_ui_state()
    assert state_before["isRunning"] is False
    assert state_before["canRun"] is True

    controller.run_simulation()
    state_running = controller._build_ui_state()
    assert state_running["isRunning"] is True
    # Button must be disabled while a UI-origin job is in flight.
    assert state_running["canRun"] is False

    job_id = next(iter(controller._submitted_jobs))
    services["manager"].mark_terminal(job_id)
    services["bus"].publish(EVENT_SIM_COMPLETE, _payload_complete(job_id))

    state_after = controller._build_ui_state()
    assert state_after["isRunning"] is False
    assert state_after["canRun"] is True


# ---------------------------------------------------------------------------
# Subscription lifecycle
# ---------------------------------------------------------------------------


def test_shutdown_unsubscribes_so_later_events_are_ignored(services):
    """``shutdown`` must symmetrically detach handlers — otherwise
    the EventBus retains references and the controller (plus its
    QMainWindow) leak across window reopens."""
    main_window = QMainWindow()
    ctrl = SimulationCommandController(main_window)
    ctrl._submitted_jobs.add("job_sub")

    ctrl.shutdown()

    services["bus"].publish(EVENT_SIM_COMPLETE, _payload_complete("job_sub"))

    # Handler did not run, so the id is still in the set — proof
    # the handler was detached, not "ran and discarded".
    assert "job_sub" in ctrl._submitted_jobs
    assert services["dialogs"] == []

    main_window.close()


def test_shutdown_is_idempotent(services):
    main_window = QMainWindow()
    ctrl = SimulationCommandController(main_window)
    ctrl.shutdown()
    # Second call must not raise even though _event_subscriptions is now empty.
    ctrl.shutdown()
    main_window.close()
