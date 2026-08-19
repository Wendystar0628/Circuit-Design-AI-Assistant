import os
from datetime import datetime as RealDateTime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import domain.llm.session_state_manager as session_module
from domain.llm.context_manager import ContextManager
from domain.llm.session_state_manager import SessionStateManager
from domain.services import context_service
from shared.service_locator import ServiceLocator
from shared.service_names import SVC_CONTEXT_MANAGER


@pytest.fixture(autouse=True)
def _clear_services():
    ServiceLocator.clear()
    yield
    ServiceLocator.clear()


def _manager_with_context():
    context_manager = ContextManager()
    ServiceLocator.register(SVC_CONTEXT_MANAGER, context_manager)
    manager = SessionStateManager()
    manager._context_manager = context_manager
    return manager, context_manager


def _session_file(root: Path, session_id: str) -> Path:
    return root / context_service.CONVERSATIONS_DIR / f"{session_id}.json"


def _index_file(root: Path) -> Path:
    return root / context_service.CONVERSATIONS_DIR / context_service.SESSIONS_INDEX_FILE


def test_same_instant_id_collision_retries_without_overwriting_old_session(
    tmp_path: Path,
    monkeypatch,
):
    class _FrozenDateTime:
        @classmethod
        def now(cls):
            return RealDateTime(2026, 8, 20, 12, 34, 56, 123456)

    uuid_values = iter(
        [
            SimpleNamespace(hex="a" * 32),
            SimpleNamespace(hex="a" * 32),  # forced collision on second create
            SimpleNamespace(hex="b" * 32),
        ]
    )
    monkeypatch.setattr(session_module, "datetime", _FrozenDateTime)
    monkeypatch.setattr(
        session_module,
        "uuid",
        SimpleNamespace(uuid4=lambda: next(uuid_values)),
    )

    manager, _context_manager = _manager_with_context()
    first_id = manager.create_session(str(tmp_path))
    old_messages = [{"type": "user", "content": "must survive"}]
    context_service.save_messages(str(tmp_path), first_id, old_messages)

    second_id = manager.create_session(str(tmp_path))

    assert first_id != second_id
    assert first_id.endswith("_aaaaaaaa")
    assert second_id.endswith("_bbbbbbbb")
    assert context_service.load_messages(str(tmp_path), first_id) == old_messages
    assert context_service.load_messages(str(tmp_path), second_id) == []
    assert _session_file(tmp_path, first_id).exists()
    assert _session_file(tmp_path, second_id).exists()


def test_switch_to_corrupt_session_fails_closed_and_preserves_active_state(
    tmp_path: Path,
):
    manager, context_manager = _manager_with_context()
    active_id = manager.create_session(str(tmp_path))
    target_id = "target-session"
    context_service.save_messages(
        str(tmp_path),
        target_id,
        [{"type": "user", "content": "target"}],
    )
    assert context_service.update_session_index(
        str(tmp_path),
        target_id,
        {"name": "Target", "created_at": "now", "updated_at": "now"},
    )
    corrupt_path = _session_file(tmp_path, target_id)
    corrupt_bytes = b'{"messages": [broken'
    corrupt_path.write_bytes(corrupt_bytes)
    active_state = context_manager.get_current_state()

    with pytest.raises(context_service.CorruptContextStorageError):
        manager.switch_session(str(tmp_path), target_id)

    assert manager.get_current_session_id() == active_id
    assert context_manager.get_current_state() is active_state
    assert corrupt_path.read_bytes() == corrupt_bytes


def test_corrupt_sessions_index_is_not_treated_as_empty_or_overwritten(
    tmp_path: Path,
):
    manager, context_manager = _manager_with_context()
    active_id = manager.create_session(str(tmp_path))
    target_id = "target-session"
    context_service.save_messages(
        str(tmp_path),
        target_id,
        [{"type": "user", "content": "target"}],
    )
    assert context_service.update_session_index(
        str(tmp_path),
        target_id,
        {"name": "Target", "created_at": "now", "updated_at": "now"},
    )
    index_path = _index_file(tmp_path)
    corrupt_bytes = b'{"sessions": [not-json'
    index_path.write_bytes(corrupt_bytes)
    active_state = context_manager.get_current_state()

    with pytest.raises(context_service.CorruptContextStorageError):
        manager.switch_session(str(tmp_path), target_id)

    assert manager.get_current_session_id() == active_id
    assert context_manager.get_current_state() is active_state
    assert index_path.read_bytes() == corrupt_bytes
    with pytest.raises(context_service.CorruptContextStorageError):
        context_service.list_sessions(str(tmp_path))
    assert index_path.read_bytes() == corrupt_bytes


@pytest.mark.parametrize("corrupt_target", ["session", "index"])
def test_transition_persistence_preflight_rejects_corrupt_storage(
    tmp_path: Path,
    corrupt_target: str,
):
    manager, _context_manager = _manager_with_context()
    session_id = manager.create_session(str(tmp_path))
    target = (
        _session_file(tmp_path, session_id)
        if corrupt_target == "session"
        else _index_file(tmp_path)
    )
    corrupt_bytes = b'{"broken": [not-json'
    target.write_bytes(corrupt_bytes)

    assert manager.ensure_current_session_persisted(str(tmp_path)) is False
    assert manager.get_current_session_id() == session_id
    assert manager._is_dirty is True
    assert target.read_bytes() == corrupt_bytes


def test_index_write_failure_keeps_session_dirty_and_reports_failure(
    tmp_path: Path,
    monkeypatch,
):
    manager, context_manager = _manager_with_context()
    session_id = manager.create_session(str(tmp_path))
    context_manager.add_user_message("unsaved change")
    manager.mark_dirty()
    monkeypatch.setattr(context_service, "update_session_index", lambda *args, **kwargs: False)

    assert manager.save_current_session(project_root=str(tmp_path)) is False
    assert manager._is_dirty is True
    assert manager.get_current_session_id() == session_id
    assert context_service.load_messages(str(tmp_path), session_id) == []


def test_same_session_switch_aborts_when_dirty_save_returns_false(
    tmp_path: Path,
    monkeypatch,
):
    manager, context_manager = _manager_with_context()
    session_id = manager.create_session(str(tmp_path))
    context_manager.add_user_message("must remain in the active runtime")
    manager.mark_dirty()
    sync = MagicMock()
    monkeypatch.setattr(manager, "_sync_state_to_context_manager", sync)
    monkeypatch.setattr(
        context_service,
        "update_session_index",
        lambda *args, **kwargs: False,
    )

    with pytest.raises(IOError):
        manager.switch_session(str(tmp_path), session_id)

    assert manager.get_current_session_id() == session_id
    assert manager._is_dirty is True
    sync.assert_not_called()


def test_ensure_active_session_rejects_failed_current_identity_write(
    tmp_path: Path,
    monkeypatch,
):
    manager, context_manager = _manager_with_context()
    session_id = manager.create_session(str(tmp_path))
    active_state = context_manager.get_current_state()
    monkeypatch.setattr(
        context_service,
        "set_current_session_id",
        lambda *args, **kwargs: False,
    )

    with pytest.raises(IOError):
        manager.ensure_active_session(str(tmp_path))

    assert manager.get_current_session_id() == session_id
    assert context_manager.get_current_state() is active_state


def test_stale_current_session_index_remove_failure_does_not_create_session(
    tmp_path: Path,
    monkeypatch,
):
    stale_id = "missing-current-session"
    assert context_service.update_session_index(
        str(tmp_path),
        stale_id,
        {"name": "stale", "created_at": "now", "updated_at": "now"},
        set_current=True,
    )
    manager, context_manager = _manager_with_context()
    initial_state = context_manager.get_current_state()
    monkeypatch.setattr(
        context_service,
        "remove_from_session_index",
        lambda *args, **kwargs: False,
    )

    with pytest.raises(IOError):
        manager.ensure_active_session(str(tmp_path))

    assert manager.get_current_session_id() == ""
    assert context_manager.get_current_state() is initial_state
    assert list(
        (tmp_path / context_service.CONVERSATIONS_DIR).glob("*.json")
    ) == [_index_file(tmp_path)]


def test_delete_current_session_stops_when_index_remove_fails(
    tmp_path: Path,
    monkeypatch,
):
    manager, context_manager = _manager_with_context()
    first_id = manager.create_session(str(tmp_path))
    current_id = manager.create_session(str(tmp_path))
    active_state = context_manager.get_current_state()
    publish = MagicMock()
    monkeypatch.setattr(manager, "_publish_session_changed_event", publish)
    monkeypatch.setattr(
        context_service,
        "remove_from_session_index",
        lambda *args, **kwargs: False,
    )

    assert manager.delete_session(str(tmp_path), current_id) is False

    assert not _session_file(tmp_path, current_id).exists()
    assert _session_file(tmp_path, first_id).exists()
    assert manager.get_current_session_id() == current_id
    assert context_manager.get_current_state() is active_state
    publish.assert_not_called()


def test_project_closed_fallback_save_failure_retains_dirty_recovery_state(
    tmp_path: Path,
    monkeypatch,
):
    manager, context_manager = _manager_with_context()
    session_id = manager.create_session(str(tmp_path))
    context_manager.add_user_message("unsaved")
    manager.mark_dirty()
    active_state = context_manager.get_current_state()
    publish = MagicMock()
    monkeypatch.setattr(manager, "save_current_session", lambda **kwargs: False)
    monkeypatch.setattr(manager, "_publish_session_changed_event", publish)

    manager._on_project_closed({"path": str(tmp_path)})

    assert manager.get_current_session_id() == session_id
    assert manager.get_project_root() == os.path.normcase(
        os.path.abspath(str(tmp_path))
    )
    assert manager._is_dirty is True
    assert context_manager.get_current_state() is active_state
    publish.assert_not_called()


def test_atomic_index_replace_failure_preserves_previous_file(
    tmp_path: Path,
    monkeypatch,
):
    assert context_service.update_session_index(
        str(tmp_path),
        "session-a",
        {"name": "Original", "created_at": "now", "updated_at": "now"},
        set_current=True,
    )
    index_path = _index_file(tmp_path)
    original_bytes = index_path.read_bytes()

    def _fail_replace(source, destination):
        del source, destination
        raise PermissionError("injected replace failure")

    monkeypatch.setattr(context_service.os, "replace", _fail_replace)

    assert context_service.update_session_index(
        str(tmp_path),
        "session-a",
        {"name": "Must not partially replace"},
    ) is False
    assert index_path.read_bytes() == original_bytes
    assert list(index_path.parent.glob(f".{index_path.name}.*.tmp")) == []


def test_conditional_session_metadata_replace_rejects_stale_expected_entry(
    tmp_path: Path,
):
    assert context_service.update_session_index(
        str(tmp_path),
        "session-a",
        {"name": "Initial", "working_context_summary": "before"},
        set_current=True,
    )
    expected = context_service.get_session_metadata(str(tmp_path), "session-a")
    assert expected is not None

    # Model a same-session update landing after rollback confirmation but
    # before its metadata merge.  The compare and replacement share the
    # context-service lock, so the stale plan cannot overwrite this update.
    assert context_service.update_session_index(
        str(tmp_path),
        "session-a",
        {"working_context_summary": "concurrent update"},
    )

    with pytest.raises(context_service.SessionMetadataConflictError):
        context_service.replace_session_metadata(
            str(tmp_path),
            "session-a",
            {"session_id": "session-a", "working_context_summary": "target"},
            expected_metadata=expected,
        )

    actual = context_service.get_session_metadata(str(tmp_path), "session-a")
    assert actual is not None
    assert actual["working_context_summary"] == "concurrent update"
    assert context_service.get_current_session_id(str(tmp_path)) == "session-a"
