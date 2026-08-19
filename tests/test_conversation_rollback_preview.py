import asyncio
import copy
import json
import os
from pathlib import Path

import pytest

from domain.llm.context_manager import ContextManager
from domain.llm.conversation_rollback_service import ConversationRollbackService
from domain.llm.session_state_manager import SessionStateManager
from domain.llm.working_context_builder import (
    WORKING_CONTEXT_COMPRESSED_COUNT_KEY,
    WORKING_CONTEXT_KEEP_RECENT_KEY,
    WORKING_CONTEXT_SUMMARY_KEY,
)
from domain.services import context_service, snapshot_service
from presentation.panels.conversation.conversation_view_model import ConversationViewModel
from shared.constants import SYSTEM_DIR
from shared.event_bus import EventBus
from shared.event_types import EVENT_STATE_PROJECT_OPENED
from shared.service_locator import ServiceLocator
from shared.service_names import (
    SVC_CONTEXT_MANAGER,
    SVC_EVENT_BUS,
    SVC_FILE_MANAGER,
    SVC_FILE_WATCHER,
    SVC_SESSION_STATE_MANAGER,
)


@pytest.fixture(autouse=True)
def clear_services():
    ServiceLocator.clear()
    yield
    ServiceLocator.clear()


class _FakeFileWatcher:
    def __init__(self):
        self.is_watching = False
        self.watch_path = None
        self.stop_count = 0
        self.start_calls = []

    def stop_watching(self):
        self.is_watching = False
        self.watch_path = None
        self.stop_count += 1

    def start_watching(self, project_root: str):
        self.is_watching = True
        self.watch_path = project_root
        self.start_calls.append(project_root)


class _FakeFileManager:
    def __init__(self, generation: int = 1):
        self.project_generation = generation


def _build_environment(tmp_path: Path):
    manager = SessionStateManager()
    context_manager = ContextManager()
    file_watcher = _FakeFileWatcher()

    manager._context_manager = context_manager
    manager._generate_session_id = lambda: "session-preview"

    session_id = manager.create_session(str(tmp_path))

    ServiceLocator.register(SVC_CONTEXT_MANAGER, context_manager)
    ServiceLocator.register(SVC_SESSION_STATE_MANAGER, manager)
    ServiceLocator.register(SVC_FILE_WATCHER, file_watcher)

    return manager, context_manager, file_watcher, session_id


def _prepare_checkpointed_conversation(tmp_path: Path):
    manager, context_manager, file_watcher, session_id = _build_environment(tmp_path)
    rollback_service = ConversationRollbackService()

    workspace_file = tmp_path / "design.txt"
    workspace_file.write_text("base-1\nbase-2\nbase-3\n", encoding="utf-8")
    pending_edits_path = tmp_path / ".circuit_ai" / "pending_workspace_edits.json"
    pending_edits_path.parent.mkdir(parents=True, exist_ok=True)
    pending_edits_base = {
        "files": [{"path": "design.txt", "added_lines": 1}],
        "updated": "before-anchor",
    }
    pending_edits_path.write_text(json.dumps(pending_edits_base), encoding="utf-8")

    context_manager.add_user_message(
        "base question",
        timestamp="2026-04-08T19:00:00",
        message_id="base-user",
    )
    context_manager.add_assistant_message(
        "base answer",
        timestamp="2026-04-08T19:00:10",
        message_id="base-assistant",
    )
    metadata_before_anchor = {
        WORKING_CONTEXT_SUMMARY_KEY: "summary before anchor",
        WORKING_CONTEXT_COMPRESSED_COUNT_KEY: 1,
        WORKING_CONTEXT_KEEP_RECENT_KEY: 1,
        "circuit_file_path": "before-anchor.cir",
        "last_metrics": {"gain": 10.0},
        "error_context": "before-anchor error context",
    }
    context_manager.get_current_state().update(copy.deepcopy(metadata_before_anchor))
    manager.mark_dirty()

    asyncio.run(
        rollback_service.capture_user_turn_checkpoint(
            anchor_message_id="anchor-user",
            anchor_timestamp="2026-04-08T19:01:00",
        )
    )

    workspace_file.write_text("base-1\nchanged-2\n", encoding="utf-8")
    new_workspace_file = tmp_path / "after-anchor.txt"
    new_workspace_file.write_text("temp-1\ntemp-2\n", encoding="utf-8")
    pending_edits_path.write_text(
        json.dumps({"files": [], "updated": "after-anchor"}),
        encoding="utf-8",
    )
    pending_edits_after_anchor = {"files": [], "updated": "after-anchor"}

    long_user_message = "anchor " + "very long message " * 20
    context_manager.add_user_message(
        long_user_message,
        timestamp="2026-04-08T19:01:00",
        message_id="anchor-user",
    )
    context_manager.add_assistant_message(
        "assistant after anchor",
        timestamp="2026-04-08T19:01:10",
        message_id="after-assistant",
    )
    metadata_after_anchor = {
        WORKING_CONTEXT_SUMMARY_KEY: "summary after anchor",
        WORKING_CONTEXT_COMPRESSED_COUNT_KEY: 3,
        WORKING_CONTEXT_KEEP_RECENT_KEY: 2,
        "circuit_file_path": "after-anchor.cir",
        "last_metrics": {"gain": 20.0},
        "error_context": "after-anchor error context",
    }
    context_manager.get_current_state().update(copy.deepcopy(metadata_after_anchor))
    manager.mark_dirty()

    return {
        "manager": manager,
        "context_manager": context_manager,
        "file_watcher": file_watcher,
        "rollback_service": rollback_service,
        "session_id": session_id,
        "workspace_file": workspace_file,
        "new_workspace_file": new_workspace_file,
        "pending_edits_path": pending_edits_path,
        "pending_edits_base": pending_edits_base,
        "pending_edits_after_anchor": pending_edits_after_anchor,
        "long_user_message": long_user_message,
        "metadata_before_anchor": metadata_before_anchor,
        "metadata_after_anchor": metadata_after_anchor,
    }


def test_preview_rollback_to_anchor_exposes_workspace_changes_and_message_truncation(tmp_path: Path):
    env = _prepare_checkpointed_conversation(tmp_path)

    preview = asyncio.run(
        env["rollback_service"].preview_rollback_to_anchor("anchor-user")
    )

    workspace_paths = [change.relative_path for change in preview.changed_files]

    assert preview.removed_message_count == 2
    assert preview.removed_messages[0].message_id == "anchor-user"
    assert preview.removed_messages[0].content_preview.endswith("...")
    assert len(preview.removed_messages[0].content_preview) <= 123
    assert preview.anchor_label == preview.removed_messages[0].content_preview

    current_session_path = (
        f"{context_service.CONVERSATIONS_DIR}/{env['session_id']}.json"
    )
    current_rollback_path = (
        f"{context_service.CONVERSATIONS_DIR}/{env['session_id']}"
        f"{context_service.ROLLBACK_CHECKPOINTS_SUFFIX}"
    )
    current_metadata_path = (
        f"{context_service.CONVERSATIONS_DIR}/"
        f"{context_service.SESSIONS_INDEX_FILE}"
    )
    assert preview.changed_file_count == 5
    assert workspace_paths == [
        current_session_path,
        current_rollback_path,
        current_metadata_path,
        "after-anchor.txt",
        "design.txt",
    ]
    # Internal files that really will change are explicit in the confirmation
    # preview; no hidden .circuit_ai side effects are filtered away.
    assert all(
        path in {
            current_session_path,
            current_rollback_path,
            current_metadata_path,
        }
        for path in workspace_paths
        if path.startswith(f"{SYSTEM_DIR}/")
    )
    assert ".circuit_ai/pending_workspace_edits.json" not in workspace_paths


def test_rollback_to_anchor_restores_workspace_and_session_state(tmp_path: Path):
    env = _prepare_checkpointed_conversation(tmp_path)
    env["file_watcher"].is_watching = True
    preview = asyncio.run(
        env["rollback_service"].preview_rollback_to_anchor("anchor-user")
    )

    result = asyncio.run(
        env["rollback_service"].rollback_to_anchor(
            "anchor-user",
            expected_operation_token=preview.operation_token,
        )
    )

    assert result["success"] is True
    assert env["workspace_file"].read_text(encoding="utf-8") == "base-1\nbase-2\nbase-3\n"
    assert not env["new_workspace_file"].exists()
    # Pending edits are project-global state rather than current-session state,
    # so a conversation rollback must not time-travel them invisibly.
    assert json.loads(env["pending_edits_path"].read_text(encoding="utf-8")) == env["pending_edits_after_anchor"]

    persisted_messages = context_service.load_messages(str(tmp_path), env["session_id"])
    persisted_ids = [
        msg.get("additional_kwargs", {}).get("metadata", {}).get("id", "")
        for msg in persisted_messages
    ]
    assert persisted_ids == ["base-user", "base-assistant"]

    runtime_messages = env["context_manager"].get_display_messages()
    assert len(runtime_messages) == 2
    assert [getattr(message, "content", "") for message in runtime_messages] == [
        "base question",
        "base answer",
    ]

    persisted_metadata = context_service.get_session_metadata(
        str(tmp_path), env["session_id"]
    )
    assert persisted_metadata is not None
    runtime_state = env["context_manager"].get_current_state()
    for key, expected_value in env["metadata_before_anchor"].items():
        assert persisted_metadata[key] == expected_value
        assert runtime_state[key] == expected_value

    assert env["file_watcher"].stop_count == 1
    assert [os.path.normcase(path) for path in env["file_watcher"].start_calls] == [
        os.path.normcase(str(tmp_path.resolve()))
    ]


def test_rollback_confirmation_rejects_workspace_changes_after_preview(
    tmp_path: Path,
):
    env = _prepare_checkpointed_conversation(tmp_path)
    env["file_watcher"].is_watching = True
    preview = asyncio.run(
        env["rollback_service"].preview_rollback_to_anchor("anchor-user")
    )

    # Cover both a changed path already present in the preview and a new path
    # that was not part of the original restore plan.
    external_content = "external edit after preview\n"
    env["workspace_file"].write_text(external_content, encoding="utf-8")
    unplanned_file = tmp_path / "created-after-preview.txt"
    unplanned_file.write_text("must remain untouched\n", encoding="utf-8")

    result = asyncio.run(
        env["rollback_service"].rollback_to_anchor(
            "anchor-user",
            expected_operation_token=preview.operation_token,
        )
    )

    assert result["success"] is False
    assert result["plan_changed"] is True
    assert env["workspace_file"].read_text(encoding="utf-8") == external_content
    assert unplanned_file.read_text(encoding="utf-8") == "must remain untouched\n"
    assert env["file_watcher"].stop_count == 0
    assert env["file_watcher"].start_calls == []


def test_project_switch_during_restore_cannot_commit_or_rebind_watcher(
    tmp_path: Path,
    monkeypatch,
):
    env = _prepare_checkpointed_conversation(tmp_path)
    manager = env["manager"]
    rollback_service = env["rollback_service"]
    file_watcher = env["file_watcher"]
    project_a = str(tmp_path.resolve())
    project_b_path = tmp_path.parent / f"{tmp_path.name}-project-b"
    project_b_path.mkdir()
    project_b = str(project_b_path.resolve())

    file_manager = _FakeFileManager(generation=7)
    ServiceLocator.register(SVC_FILE_MANAGER, file_manager)
    file_watcher.is_watching = True
    file_watcher.watch_path = project_a
    preview = asyncio.run(
        rollback_service.preview_rollback_to_anchor("anchor-user")
    )

    restore_started = asyncio.Event()
    allow_restore_to_return = asyncio.Event()
    reload_calls = []
    workspace_sync_calls = []

    async def blocked_restore(*args, **kwargs):
        del args, kwargs
        restore_started.set()
        await allow_restore_to_return.wait()

    monkeypatch.setattr(
        "domain.llm.conversation_rollback_service.snapshot_service.restore_snapshot_async",
        blocked_restore,
    )
    monkeypatch.setattr(
        manager,
        "reload_current_session",
        lambda *args, **kwargs: reload_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        rollback_service,
        "_publish_workspace_sync_required",
        lambda **kwargs: workspace_sync_calls.append(kwargs),
    )

    async def scenario():
        task = asyncio.create_task(
            rollback_service.rollback_to_anchor(
                "anchor-user",
                expected_operation_token=preview.operation_token,
            )
        )
        await restore_started.wait()

        # Model the ProjectService transition while the blocking disk restore
        # still owns project A.  The new project may even install a replacement
        # watcher before the old restore coroutine resumes.
        manager._generate_session_id = lambda: "session-project-b"
        manager.create_session(project_b)
        file_manager.project_generation += 1
        file_watcher.start_watching(project_b)

        allow_restore_to_return.set()
        return await task

    result = asyncio.run(scenario())

    assert result["success"] is False
    assert result["invalidated"] is True
    assert manager.get_current_session_id() == "session-project-b"
    assert os.path.normcase(manager.get_project_root()) == os.path.normcase(project_b)
    assert reload_calls == []
    assert workspace_sync_calls == []
    assert file_watcher.is_watching is True
    assert os.path.normcase(file_watcher.watch_path) == os.path.normcase(project_b)
    assert [os.path.normcase(path) for path in file_watcher.start_calls] == [
        os.path.normcase(project_b)
    ]


def test_rollback_owner_rejects_same_project_after_generation_rebind(tmp_path: Path):
    manager, _, _, session_id = _build_environment(tmp_path)
    file_manager = _FakeFileManager(generation=11)
    ServiceLocator.register(SVC_FILE_MANAGER, file_manager)
    service = ConversationRollbackService()

    owner = service._capture_owner(
        manager,
        session_id=session_id,
        project_root=str(tmp_path),
    )
    file_manager.project_generation = 12

    assert service._is_owner_current(owner, manager) is False


def test_conversation_rollback_preserves_other_sessions_and_global_index(tmp_path: Path):
    env = _prepare_checkpointed_conversation(tmp_path)

    other_session_id = "session-created-after-checkpoint"
    other_messages = [{"type": "user", "content": "must survive rollback"}]
    other_checkpoints = [{"anchor_message_id": "other-anchor", "snapshot_id": "other"}]
    context_service.save_messages(str(tmp_path), other_session_id, other_messages)
    context_service.save_rollback_checkpoints(
        str(tmp_path),
        other_session_id,
        other_checkpoints,
    )
    context_service.update_session_index(
        str(tmp_path),
        other_session_id,
        {"name": "Created after checkpoint", "marker": "keep-me"},
    )

    preview = asyncio.run(
        env["rollback_service"].preview_rollback_to_anchor("anchor-user")
    )
    preview_paths = {change.relative_path for change in preview.changed_files}
    assert f"{context_service.CONVERSATIONS_DIR}/{other_session_id}.json" not in preview_paths
    assert (
        f"{context_service.CONVERSATIONS_DIR}/{other_session_id}"
        f"{context_service.ROLLBACK_CHECKPOINTS_SUFFIX}"
    ) not in preview_paths
    # The confirmation exposes a logical current-session entry replacement in
    # sessions.json, while the transaction preserves all unrelated entries.
    assert (
        f"{context_service.CONVERSATIONS_DIR}/{context_service.SESSIONS_INDEX_FILE}"
        in preview_paths
    )

    result = asyncio.run(
        env["rollback_service"].rollback_to_anchor(
            "anchor-user",
            expected_operation_token=preview.operation_token,
        )
    )

    assert result["success"] is True
    assert context_service.load_messages(str(tmp_path), other_session_id) == other_messages
    assert (
        context_service.load_rollback_checkpoints(str(tmp_path), other_session_id)
        == other_checkpoints
    )
    other_metadata = context_service.get_session_metadata(str(tmp_path), other_session_id)
    assert other_metadata is not None
    assert other_metadata["marker"] == "keep-me"
    assert context_service.get_current_session_id(str(tmp_path)) == env["session_id"]


def test_session_metadata_commit_failure_restores_preconfirm_state(
    tmp_path: Path,
    monkeypatch,
):
    env = _prepare_checkpointed_conversation(tmp_path)
    preview = asyncio.run(
        env["rollback_service"].preview_rollback_to_anchor("anchor-user")
    )
    live_metadata = copy.deepcopy(
        context_service.get_session_metadata(str(tmp_path), env["session_id"])
    )
    live_message_ids = [
        message.id for message in env["context_manager"].get_display_messages()
    ]
    live_workspace = env["workspace_file"].read_text(encoding="utf-8")

    monkeypatch.setattr(
        context_service,
        "replace_session_metadata",
        lambda *args, **kwargs: False,
    )

    result = asyncio.run(
        env["rollback_service"].rollback_to_anchor(
            "anchor-user",
            expected_operation_token=preview.operation_token,
        )
    )

    assert result["success"] is False
    assert "persist rollback session metadata" in result["message"]
    assert env["workspace_file"].read_text(encoding="utf-8") == live_workspace
    assert env["new_workspace_file"].exists()
    assert [
        message.id for message in env["context_manager"].get_display_messages()
    ] == live_message_ids
    assert (
        context_service.get_session_metadata(str(tmp_path), env["session_id"])
        == live_metadata
    )
    runtime_state = env["context_manager"].get_current_state()
    for key, expected_value in env["metadata_after_anchor"].items():
        assert runtime_state[key] == expected_value


def test_reload_failure_after_metadata_commit_recovers_files_and_metadata(
    tmp_path: Path,
    monkeypatch,
):
    env = _prepare_checkpointed_conversation(tmp_path)
    preview = asyncio.run(
        env["rollback_service"].preview_rollback_to_anchor("anchor-user")
    )
    live_metadata = copy.deepcopy(
        context_service.get_session_metadata(str(tmp_path), env["session_id"])
    )
    live_workspace = env["workspace_file"].read_text(encoding="utf-8")
    original_reload = env["manager"].reload_current_session
    reload_calls = 0

    def fail_first_reload(*args, **kwargs):
        nonlocal reload_calls
        reload_calls += 1
        if reload_calls == 1:
            raise RuntimeError("reload failed after metadata commit")
        return original_reload(*args, **kwargs)

    monkeypatch.setattr(
        env["manager"],
        "reload_current_session",
        fail_first_reload,
    )

    result = asyncio.run(
        env["rollback_service"].rollback_to_anchor(
            "anchor-user",
            expected_operation_token=preview.operation_token,
        )
    )

    assert result["success"] is False
    assert "reload failed after metadata commit" in result["message"]
    assert reload_calls == 2
    assert env["workspace_file"].read_text(encoding="utf-8") == live_workspace
    assert env["new_workspace_file"].exists()
    assert (
        context_service.get_session_metadata(str(tmp_path), env["session_id"])
        == live_metadata
    )
    runtime_state = env["context_manager"].get_current_state()
    for key, expected_value in env["metadata_after_anchor"].items():
        assert runtime_state[key] == expected_value


def test_concurrent_metadata_change_during_commit_fails_closed_and_recovers_files(
    tmp_path: Path,
    monkeypatch,
):
    env = _prepare_checkpointed_conversation(tmp_path)
    preview = asyncio.run(
        env["rollback_service"].preview_rollback_to_anchor("anchor-user")
    )
    live_workspace = env["workspace_file"].read_text(encoding="utf-8")
    original_replace = context_service.replace_session_metadata
    replacement_calls = 0

    def inject_concurrent_change(*args, **kwargs):
        nonlocal replacement_calls
        replacement_calls += 1
        assert context_service.update_session_index(
            str(tmp_path),
            env["session_id"],
            {WORKING_CONTEXT_SUMMARY_KEY: "concurrent summary"},
        )
        return original_replace(*args, **kwargs)

    monkeypatch.setattr(
        context_service,
        "replace_session_metadata",
        inject_concurrent_change,
    )

    result = asyncio.run(
        env["rollback_service"].rollback_to_anchor(
            "anchor-user",
            expected_operation_token=preview.operation_token,
        )
    )

    assert result["success"] is False
    assert result["plan_changed"] is True
    assert replacement_calls == 1
    assert env["workspace_file"].read_text(encoding="utf-8") == live_workspace
    assert env["new_workspace_file"].exists()
    actual_metadata = context_service.get_session_metadata(
        str(tmp_path), env["session_id"]
    )
    assert actual_metadata is not None
    assert actual_metadata[WORKING_CONTEXT_SUMMARY_KEY] == "concurrent summary"
    assert (
        env["context_manager"].get_current_state()[WORKING_CONTEXT_SUMMARY_KEY]
        == "concurrent summary"
    )


def test_watcher_stop_failure_does_not_restore_over_new_workspace_edit(
    tmp_path: Path,
    monkeypatch,
):
    env = _prepare_checkpointed_conversation(tmp_path)
    env["file_watcher"].is_watching = True
    env["file_watcher"].watch_path = str(tmp_path)
    preview = asyncio.run(
        env["rollback_service"].preview_rollback_to_anchor("anchor-user")
    )
    late_edit = "edit made after safety snapshot but before target restore\n"

    def fail_stop():
        env["workspace_file"].write_text(late_edit, encoding="utf-8")
        raise RuntimeError("watcher stop failed")

    restore_calls = []
    original_restore = snapshot_service.restore_snapshot_async

    async def record_restore(*args, **kwargs):
        restore_calls.append((args, kwargs))
        return await original_restore(*args, **kwargs)

    monkeypatch.setattr(env["file_watcher"], "stop_watching", fail_stop)
    monkeypatch.setattr(snapshot_service, "restore_snapshot_async", record_restore)

    result = asyncio.run(
        env["rollback_service"].rollback_to_anchor(
            "anchor-user",
            expected_operation_token=preview.operation_token,
        )
    )

    assert result["success"] is False
    assert "watcher stop failed" in result["message"]
    assert env["workspace_file"].read_text(encoding="utf-8") == late_edit
    assert restore_calls == []


def test_view_model_rollback_emits_single_display_refresh_signal(tmp_path: Path):
    env = _prepare_checkpointed_conversation(tmp_path)

    view_model = ConversationViewModel()
    view_model._context_manager = env["context_manager"]
    view_model._session_state_manager = env["manager"]
    view_model._conversation_rollback_service = env["rollback_service"]

    refresh_events: list[str] = []
    view_model.display_state_changed.connect(lambda: refresh_events.append("refresh"))

    view_model.load_messages()
    refresh_events.clear()

    preview = asyncio.run(view_model.preview_rollback_to_message("anchor-user"))[0]
    assert preview is not None
    success, error_message = asyncio.run(
        view_model.rollback_to_message("anchor-user", preview.operation_token)
    )

    assert success is True, error_message
    assert refresh_events == ["refresh"]
    assert [message.id for message in view_model.messages] == ["base-user", "base-assistant"]


def test_project_open_event_ensures_active_session_and_syncs_context(tmp_path: Path):
    event_bus = EventBus()
    context_manager = ContextManager()

    ServiceLocator.register(SVC_EVENT_BUS, event_bus)
    ServiceLocator.register(SVC_CONTEXT_MANAGER, context_manager)

    manager = SessionStateManager()
    manager._generate_session_id = lambda: "session-opened"
    ServiceLocator.register(SVC_SESSION_STATE_MANAGER, manager)

    event_bus.publish(
        EVENT_STATE_PROJECT_OPENED,
        {"path": str(tmp_path)},
        source="test",
    )

    assert manager.get_current_session_id() == "session-opened"
    assert os.path.normcase(manager.get_project_root()) == os.path.normcase(str(tmp_path.resolve()))

    current_state = context_manager.get_current_state()
    assert current_state.get("session_id", "") == "session-opened"
    assert os.path.normcase(current_state.get("project_root", "")) == os.path.normcase(
        str(tmp_path.resolve())
    )
    assert current_state.get("messages", []) == []


def test_capture_user_turn_checkpoint_uses_project_opened_active_session(tmp_path: Path):
    event_bus = EventBus()
    context_manager = ContextManager()
    file_watcher = _FakeFileWatcher()

    ServiceLocator.register(SVC_EVENT_BUS, event_bus)
    ServiceLocator.register(SVC_CONTEXT_MANAGER, context_manager)
    ServiceLocator.register(SVC_FILE_WATCHER, file_watcher)

    manager = SessionStateManager()
    manager._generate_session_id = lambda: "session-capture"
    ServiceLocator.register(SVC_SESSION_STATE_MANAGER, manager)

    rollback_service = ConversationRollbackService()

    event_bus.publish(
        EVENT_STATE_PROJECT_OPENED,
        {"path": str(tmp_path)},
        source="test",
    )

    checkpoint = asyncio.run(
        rollback_service.capture_user_turn_checkpoint(
            anchor_message_id="anchor-user",
            anchor_timestamp="2026-04-10T16:51:49",
        )
    )

    checkpoints = context_service.load_rollback_checkpoints(
        str(tmp_path),
        manager.get_current_session_id(),
    )

    assert checkpoint["session_id"] == "session-capture"
    assert checkpoint["anchor_message_id"] == "anchor-user"
    assert len(checkpoints) == 1
    assert checkpoints[0]["anchor_message_id"] == "anchor-user"


def test_checkpoint_capture_stops_before_snapshot_when_session_save_fails(
    tmp_path: Path,
    monkeypatch,
):
    manager, _, _, _ = _build_environment(tmp_path)
    service = ConversationRollbackService()
    snapshot_calls = []

    monkeypatch.setattr(manager, "save_current_session", lambda **kwargs: False)

    async def forbidden_snapshot(*args, **kwargs):
        snapshot_calls.append((args, kwargs))

    monkeypatch.setattr(snapshot_service, "create_snapshot_async", forbidden_snapshot)

    with pytest.raises(RuntimeError, match="persist current conversation"):
        asyncio.run(
            service.capture_user_turn_checkpoint(
                anchor_message_id="anchor-save-failed",
                anchor_timestamp="2026-04-10T16:51:49",
            )
        )

    assert snapshot_calls == []
    assert context_service.load_rollback_checkpoints(
        str(tmp_path), manager.get_current_session_id()
    ) == []


def test_project_switch_during_checkpoint_capture_cannot_register_stale_anchor(
    tmp_path: Path,
    monkeypatch,
):
    manager, _, _, session_a = _build_environment(tmp_path)
    service = ConversationRollbackService()
    file_manager = _FakeFileManager(generation=21)
    ServiceLocator.register(SVC_FILE_MANAGER, file_manager)
    project_b_path = tmp_path.parent / f"{tmp_path.name}-checkpoint-project-b"
    project_b_path.mkdir()
    project_b = str(project_b_path.resolve())
    original_create_snapshot = snapshot_service.create_snapshot_async

    async def scenario():
        snapshot_created = asyncio.Event()
        allow_return = asyncio.Event()

        async def blocked_snapshot(project_root, snapshot_id, **kwargs):
            result = await original_create_snapshot(
                project_root,
                snapshot_id,
                **kwargs,
            )
            snapshot_created.set()
            await allow_return.wait()
            return result

        monkeypatch.setattr(
            snapshot_service,
            "create_snapshot_async",
            blocked_snapshot,
        )
        task = asyncio.create_task(
            service.capture_user_turn_checkpoint(
                anchor_message_id="anchor-project-a",
                anchor_timestamp="2026-04-10T16:51:49",
            )
        )
        await snapshot_created.wait()

        manager._generate_session_id = lambda: "session-checkpoint-project-b"
        manager.create_session(project_b)
        file_manager.project_generation += 1
        allow_return.set()

        with pytest.raises(RuntimeError, match="changed during checkpoint"):
            await task

    asyncio.run(scenario())

    assert manager.get_current_session_id() == "session-checkpoint-project-b"
    assert os.path.normcase(manager.get_project_root()) == os.path.normcase(project_b)
    assert context_service.load_rollback_checkpoints(str(tmp_path), session_a) == []
    snapshots_dir = Path(tmp_path) / snapshot_service.SNAPSHOTS_DIR
    assert not snapshots_dir.exists() or not any(snapshots_dir.iterdir())


def test_checkpoint_persistence_failure_removes_its_unique_snapshot(
    tmp_path: Path,
    monkeypatch,
):
    manager, _, _, session_id = _build_environment(tmp_path)
    service = ConversationRollbackService()
    monkeypatch.setattr(
        context_service,
        "append_rollback_checkpoint",
        lambda *args, **kwargs: False,
    )

    with pytest.raises(RuntimeError, match="persist rollback checkpoint"):
        asyncio.run(
            service.capture_user_turn_checkpoint(
                anchor_message_id="anchor-checkpoint-failed",
                anchor_timestamp="2026-04-10T16:51:49",
            )
        )

    assert context_service.load_rollback_checkpoints(
        str(tmp_path), session_id
    ) == []
    snapshots_dir = Path(tmp_path) / snapshot_service.SNAPSHOTS_DIR
    assert not snapshots_dir.exists() or not any(snapshots_dir.iterdir())
    assert manager.get_current_session_id() == session_id


def test_checkpoint_snapshot_prefix_uses_full_session_identity():
    service = ConversationRollbackService()
    shared_prefix = "20260820_123456_123456_"

    assert service._get_session_snapshot_prefix(
        f"{shared_prefix}aaaaaaaa"
    ) != service._get_session_snapshot_prefix(
        f"{shared_prefix}bbbbbbbb"
    )


@pytest.mark.parametrize(
    "invalid_snapshot_id",
    ["../../outside-snapshot", ".", "..", "name.with-dot", "含中文"],
)
@pytest.mark.parametrize(
    "loader_name",
    ["_load_snapshot_session_messages", "_load_snapshot_session_metadata"],
)
def test_snapshot_session_readers_reject_noncanonical_checkpoint_identity(
    tmp_path: Path,
    invalid_snapshot_id: str,
    loader_name: str,
):
    service = ConversationRollbackService()
    loader = getattr(service, loader_name)

    with pytest.raises(RuntimeError, match="Invalid rollback snapshot ID"):
        loader(
            str(tmp_path),
            invalid_snapshot_id,
            "session-preview",
        )

    with pytest.raises(RuntimeError, match="Invalid conversation session ID"):
        loader(
            str(tmp_path),
            "safe-snapshot",
            "../outside-session",
        )
