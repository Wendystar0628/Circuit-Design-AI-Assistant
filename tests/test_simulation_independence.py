import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from domain.llm.session_state_manager import SessionStateManager
from domain.services.snapshot_service import (
    SNAPSHOTS_DIR,
    create_snapshot,
    preview_restore_snapshot,
    restore_snapshot,
)
from presentation.panels.simulation.simulation_tab import SimulationTab
from presentation.panels.simulation.simulation_view_model import SimulationViewModel
from shared.event_types import (
    EVENT_SESSION_CHANGED,
    EVENT_SIM_ERROR,
    EVENT_SIM_STARTED,
)
from shared.service_locator import ServiceLocator
from shared.service_names import SVC_EVENT_BUS


class _FakeEventBus:
    def __init__(self):
        self.subscriptions = []
        self.published = []

    def subscribe(self, event_type: str, handler):
        self.subscriptions.append((event_type, handler))

    def unsubscribe(self, event_type: str, handler):
        try:
            self.subscriptions.remove((event_type, handler))
            return True
        except ValueError:
            return False

    def publish(self, event_type: str, payload=None, source: str = None):
        self.published.append((event_type, payload, source))


def test_simulation_tab_does_not_subscribe_to_session_changed(qapp):
    event_bus = _FakeEventBus()
    ServiceLocator.register(SVC_EVENT_BUS, event_bus)

    tab = None
    try:
        tab = SimulationTab()
        subscribed_events = [event_type for event_type, _ in event_bus.subscriptions]
        assert EVENT_SESSION_CHANGED not in subscribed_events
    finally:
        if tab is not None:
            tab.close()
            tab.deleteLater()
        ServiceLocator.unregister(SVC_EVENT_BUS)


def test_simulation_view_model_does_not_subscribe_to_global_lifecycle_events(qapp):
    """The tab is the only SIM lifecycle owner and performs identity routing."""
    event_bus = _FakeEventBus()
    ServiceLocator.register(SVC_EVENT_BUS, event_bus)
    try:
        SimulationViewModel()
        subscribed_events = [event_type for event_type, _ in event_bus.subscriptions]
        assert EVENT_SIM_STARTED not in subscribed_events
        assert EVENT_SIM_ERROR not in subscribed_events
    finally:
        ServiceLocator.unregister(SVC_EVENT_BUS)


def test_simulation_tab_updates_view_model_only_after_job_identity_filtering():
    class _RecordingViewModel:
        def __init__(self):
            self.running_calls = 0
            self.errors = []

        def mark_running(self):
            self.running_calls += 1

        def mark_error(self, message):
            self.errors.append(message)

    view_model = _RecordingViewModel()
    frontend_updates = []
    fake_tab = SimpleNamespace(
        _view_model=view_model,
        _project_root="/project",
        _displayed_job_id=None,
        _displayed_circuit_file=None,
        _displayed_result_path=None,
        _runtime_status_message="",
        _panel_error_message="",
        _logger=logging.getLogger("test.simulation_tab_owner"),
        _get_text=lambda _key, fallback: fallback,
        _update_frontend_payloads=lambda **_kwargs: frontend_updates.append(True),
        _refresh_circuit_result_index=lambda: None,
        _payload_belongs_to_current_project=lambda payload: payload.get("project_root") == "/project",
        _load_error_result_bundle=lambda _payload, _message: False,
        _set_active_frontend_tab=lambda _tab_id: True,
        _backend_runtime=SimpleNamespace(
            clear=lambda: None,
            export_panel=SimpleNamespace(set_metrics=lambda _metrics: None),
        ),
    )

    agent_started = {
        "type": EVENT_SIM_STARTED,
        "data": {
            "job_id": "job_agent",
            "origin": "agent_tool",
            "circuit_file": "/project/agent.cir",
            "project_root": "/project",
            "session_id": "session-test",
        },
    }
    SimulationTab._on_simulation_started(fake_tab, agent_started)
    assert view_model.running_calls == 0
    assert fake_tab._displayed_job_id is None

    inactive_project_started = {
        "type": EVENT_SIM_STARTED,
        "data": {
            "job_id": "job_old_ui",
            "origin": "ui_editor",
            "circuit_file": "/other-project/old.cir",
            "project_root": "/other-project",
            "session_id": "session-test",
        },
    }
    SimulationTab._on_simulation_started(fake_tab, inactive_project_started)
    assert view_model.running_calls == 0
    assert fake_tab._displayed_job_id is None

    ui_started = {
        "type": EVENT_SIM_STARTED,
        "data": {
            "job_id": "job_ui",
            "origin": "ui_editor",
            "circuit_file": "/project/ui.cir",
            "project_root": "/project",
            "session_id": "session-test",
        },
    }
    # STARTED cannot claim presentation ownership on its own, even when the
    # project path matches. This is what protects close/reopen of the same path
    # from an old queued job.
    SimulationTab._on_simulation_started(fake_tab, ui_started)
    assert view_model.running_calls == 0
    assert fake_tab._displayed_job_id is None

    assert SimulationTab.claim_ui_job(
        fake_tab,
        job_id="job_ui",
        project_root="/project",
        circuit_file="/project/ui.cir",
    ) is True
    SimulationTab._on_simulation_started(fake_tab, ui_started)
    assert view_model.running_calls == 1
    assert fake_tab._displayed_job_id == "job_ui"

    unrelated_error = {
        "type": EVENT_SIM_ERROR,
        "data": {
            "job_id": "job_agent",
            "origin": "agent_tool",
            "circuit_file": "/project/agent.cir",
            "project_root": "/project",
            "error_message": "agent failed",
            "result_path": "",
            "cancelled": False,
            "duration_seconds": 0.1,
            "session_id": "session-test",
            "export_root": "",
        },
    }
    SimulationTab._on_simulation_error(fake_tab, unrelated_error)
    assert view_model.errors == []

    own_error = {
        "type": EVENT_SIM_ERROR,
        "data": {
            "job_id": "job_ui",
            "origin": "ui_editor",
            "circuit_file": "/project/ui.cir",
            "project_root": "/project",
            "error_message": "ui failed",
            "result_path": "",
            "cancelled": False,
            "duration_seconds": 0.2,
            "session_id": "session-test",
            "export_root": "",
        },
    }
    SimulationTab._on_simulation_error(fake_tab, own_error)
    assert view_model.errors == ["ui failed"]


def test_same_path_reopen_rejects_started_job_from_previous_generation():
    fake_tab = SimpleNamespace(
        _project_root="/project",
        # Project close/open cleared the old explicit controller claim.
        _displayed_job_id=None,
        _displayed_circuit_file=None,
        _logger=logging.getLogger("test.same-path-reopen"),
        _payload_belongs_to_current_project=lambda payload: payload.get("project_root") == "/project",
        _update_frontend_payloads=lambda **_kwargs: pytest.fail(
            "unowned STARTED must not republish or claim state"
        ),
    )
    old_queued_started = {
        "type": EVENT_SIM_STARTED,
        "data": {
            "job_id": "job_from_closed_generation",
            "origin": "ui_editor",
            "circuit_file": "/project/old.cir",
            "project_root": "/project",
            "session_id": "old-session",
        },
    }

    SimulationTab._on_simulation_started(fake_tab, old_queued_started)

    assert fake_tab._displayed_job_id is None
    assert fake_tab._displayed_circuit_file is None


def test_session_state_manager_session_changed_event_omits_sim_result_path():
    event_bus = _FakeEventBus()
    manager = SessionStateManager()
    manager._event_bus = event_bus
    manager._current_session_id = "session-001"
    manager._project_root = ""
    manager._get_current_state = lambda: {
        "sim_result_path": "simulation_results/amp/2026-04-06_00-10-00/result.json",
        "circuit_file_path": "designs/amp.cir",
    }

    manager._publish_session_changed_event(
        action="rollback",
        previous_session_id="session-000",
    )

    assert len(event_bus.published) == 1
    event_type, payload, _ = event_bus.published[0]
    assert event_type == EVENT_SESSION_CHANGED
    assert payload["action"] == "rollback"
    assert payload["previous_session_id"] == "session-000"
    assert payload["circuit_file_path"] == "designs/amp.cir"
    assert "sim_result_path" not in payload


def test_create_snapshot_excludes_persisted_simulation_artifacts(tmp_path: Path):
    """Snapshots should never carry the regeneratable bundle tree.

    The authoritative simulation artifacts live under
    ``simulation_results/<stem>/<ts>/`` (single-tree contract); the legacy
    ``.circuit_ai/sim_results/`` location no longer exists. Snapshots
    only need to capture user-authored sources.
    """
    design_file = tmp_path / "amp.cir"
    design_file.write_text("before", encoding="utf-8")

    export_file = tmp_path / "simulation_results" / "amp" / "export_manifest.json"
    export_file.parent.mkdir(parents=True, exist_ok=True)
    export_file.write_text('{"result": "export"}', encoding="utf-8")

    create_snapshot(str(tmp_path), "iter_001")

    snapshot_dir = tmp_path / SNAPSHOTS_DIR / "iter_001"
    assert snapshot_dir.exists()
    assert (snapshot_dir / "amp.cir").read_text(encoding="utf-8") == "before"
    assert not (snapshot_dir / "simulation_results").exists()


def test_restore_snapshot_preserves_persisted_simulation_artifacts(tmp_path: Path):
    """Restoring a snapshot must leave the live simulation bundle tree
    untouched so the most recent results stay visible after a rollback.
    """
    design_file = tmp_path / "amp.cir"
    design_file.write_text("before", encoding="utf-8")

    export_file = tmp_path / "simulation_results" / "amp" / "export_manifest.json"
    export_file.parent.mkdir(parents=True, exist_ok=True)
    export_file.write_text('{"result": "old-export"}', encoding="utf-8")

    create_snapshot(str(tmp_path), "iter_001")

    design_file.write_text("after", encoding="utf-8")
    extra_file = tmp_path / "stale.txt"
    extra_file.write_text("stale", encoding="utf-8")
    export_file.write_text('{"result": "new-export"}', encoding="utf-8")

    restore_snapshot(str(tmp_path), "iter_001", backup_current=False)

    assert design_file.read_text(encoding="utf-8") == "before"
    assert not extra_file.exists()
    assert export_file.read_text(encoding="utf-8") == '{"result": "new-export"}'


def test_preview_restore_snapshot_reports_authoritative_line_stats(tmp_path: Path):
    modified_file = tmp_path / "design.txt"
    modified_file.write_text("base-1\nbase-2\nbase-3\n", encoding="utf-8")

    restored_file = tmp_path / "restored.txt"
    restored_file.write_text("restore-1\nrestore-2\n", encoding="utf-8")

    create_snapshot(str(tmp_path), "iter_001")

    modified_file.write_text("base-1\nchanged-2\n", encoding="utf-8")
    restored_file.unlink()

    deleted_file = tmp_path / "deleted.txt"
    deleted_file.write_text("delete-1\ndelete-2\n", encoding="utf-8")

    preview = preview_restore_snapshot(str(tmp_path), "iter_001")
    changes = {change.relative_path: change for change in preview.changed_files}

    assert preview.changed_file_count == 3
    assert preview.total_added_lines == 4
    assert preview.total_deleted_lines == 3

    assert changes["design.txt"].change_type == "modified"
    assert changes["design.txt"].added_lines == 2
    assert changes["design.txt"].deleted_lines == 1

    assert changes["restored.txt"].change_type == "added"
    assert changes["restored.txt"].added_lines == 2
    assert changes["restored.txt"].deleted_lines == 0

    assert changes["deleted.txt"].change_type == "deleted"
    assert changes["deleted.txt"].added_lines == 0
    assert changes["deleted.txt"].deleted_lines == 2
