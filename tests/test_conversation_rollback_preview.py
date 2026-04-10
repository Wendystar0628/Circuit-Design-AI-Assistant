import asyncio
import os
from pathlib import Path

import pytest

from domain.llm.context_manager import ContextManager
from domain.llm.conversation_rollback_service import ConversationRollbackService
from domain.llm.session_state_manager import SessionStateManager
from domain.services import context_service
from presentation.panels.conversation.conversation_view_model import ConversationViewModel
from shared.constants import SYSTEM_DIR
from shared.event_bus import EventBus
from shared.event_types import EVENT_STATE_PROJECT_OPENED
from shared.service_locator import ServiceLocator
from shared.service_names import (
    SVC_CONTEXT_MANAGER,
    SVC_EVENT_BUS,
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
        self.stop_count = 0
        self.start_calls = []

    def stop_watching(self):
        self.is_watching = False
        self.stop_count += 1

    def start_watching(self, project_root: str):
        self.is_watching = True
        self.start_calls.append(project_root)


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
    manager.mark_dirty()

    return {
        "manager": manager,
        "context_manager": context_manager,
        "file_watcher": file_watcher,
        "rollback_service": rollback_service,
        "session_id": session_id,
        "workspace_file": workspace_file,
        "new_workspace_file": new_workspace_file,
        "long_user_message": long_user_message,
    }


def test_preview_rollback_to_anchor_exposes_workspace_changes_and_message_truncation(tmp_path: Path):
    env = _prepare_checkpointed_conversation(tmp_path)
    metadata_path = tmp_path / ".circuit_ai" / "pending_workspace_edits.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text('{"files": []}', encoding="utf-8")
    design_goals_path = tmp_path / ".circuit_ai" / "design_goals.json"
    design_goals_path.parent.mkdir(parents=True, exist_ok=True)
    design_goals_path.write_text('{"target": "narrow-band"}', encoding="utf-8")

    preview = asyncio.run(
        env["rollback_service"].preview_rollback_to_anchor("anchor-user")
    )

    workspace_paths = [change.relative_path for change in preview.workspace_changed_files]

    assert preview.removed_message_count == 2
    assert preview.removed_messages[0].message_id == "anchor-user"
    assert preview.removed_messages[0].content_preview.endswith("...")
    assert len(preview.removed_messages[0].content_preview) <= 123
    assert preview.anchor_label == preview.removed_messages[0].content_preview

    assert preview.workspace_changed_file_count == 2
    assert workspace_paths == ["after-anchor.txt", "design.txt"]
    assert all(
        not path.startswith(f"{context_service.CONVERSATIONS_DIR}/")
        for path in workspace_paths
    )
    assert all(
        not path.startswith(f"{SYSTEM_DIR}/")
        for path in workspace_paths
    )
    assert ".circuit_ai/pending_workspace_edits.json" not in workspace_paths
    assert ".circuit_ai/design_goals.json" not in workspace_paths
    assert any(
        change.relative_path.startswith(f"{context_service.CONVERSATIONS_DIR}/")
        for change in preview.changed_files
    )
    assert any(
        change.relative_path == ".circuit_ai/pending_workspace_edits.json"
        for change in preview.changed_files
    )
    assert any(
        change.relative_path == ".circuit_ai/design_goals.json"
        for change in preview.changed_files
    )


def test_rollback_to_anchor_restores_workspace_and_session_state(tmp_path: Path):
    env = _prepare_checkpointed_conversation(tmp_path)
    env["file_watcher"].is_watching = True

    result = asyncio.run(
        env["rollback_service"].rollback_to_anchor("anchor-user")
    )

    assert result["success"] is True
    assert env["workspace_file"].read_text(encoding="utf-8") == "base-1\nbase-2\nbase-3\n"
    assert not env["new_workspace_file"].exists()

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

    assert env["file_watcher"].stop_count == 1
    assert [os.path.normcase(path) for path in env["file_watcher"].start_calls] == [
        os.path.normcase(str(tmp_path.resolve()))
    ]


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

    success, error_message = asyncio.run(view_model.rollback_to_message("anchor-user"))

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
