from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from domain.llm.session_state_manager import SessionStateManager
from domain.services.snapshot_service import (
    SNAPSHOTS_DIR,
    create_snapshot,
    preview_restore_snapshot,
    restore_snapshot,
)
from presentation.panels.simulation.simulation_tab import SimulationTab
from shared.event_types import EVENT_SESSION_CHANGED
from shared.service_locator import ServiceLocator
from shared.service_names import SVC_EVENT_BUS


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


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
