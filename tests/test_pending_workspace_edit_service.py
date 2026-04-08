from pathlib import Path

import pytest

from application.pending_workspace_edit_service import PendingWorkspaceEditService
from infrastructure.persistence.file_manager import FileManager
from shared.service_locator import ServiceLocator
from shared.service_names import SVC_FILE_MANAGER, SVC_SESSION_STATE_MANAGER


class _SessionStateManager:
    def __init__(self, project_root: str):
        self._project_root = project_root

    def get_project_root(self) -> str:
        return self._project_root


@pytest.fixture(autouse=True)
def clear_services():
    ServiceLocator.clear()
    yield
    ServiceLocator.clear()


def _create_service(project_root: Path) -> PendingWorkspaceEditService:
    file_manager = FileManager()
    file_manager.set_work_dir(project_root)
    ServiceLocator.register(SVC_FILE_MANAGER, file_manager)
    ServiceLocator.register(
        SVC_SESSION_STATE_MANAGER,
        _SessionStateManager(str(project_root)),
    )
    return PendingWorkspaceEditService()


def test_reject_hunk_restores_original_file_and_clears_pending_state(tmp_path: Path):
    file_path = tmp_path / "main.py"
    file_path.write_text("a\nb\nc\n", encoding="utf-8")
    service = _create_service(tmp_path)

    state = service.record_agent_edit(
        str(file_path),
        "a\nB\nc\n",
        tool_name="patch_file",
        tool_call_id="call-1",
    )

    assert state["file_count"] == 1
    hunk_id = state["files"][0]["hunks"][0]["id"]

    updated_state = service.reject_hunk(str(file_path), hunk_id)

    assert file_path.read_text(encoding="utf-8") == "a\nb\nc\n"
    assert updated_state["file_count"] == 0
    assert service.get_state()["file_count"] == 0


def test_accept_hunk_keeps_saved_file_and_clears_pending_state(tmp_path: Path):
    file_path = tmp_path / "main.py"
    file_path.write_text("a\nb\nc\n", encoding="utf-8")
    service = _create_service(tmp_path)

    state = service.record_agent_edit(
        str(file_path),
        "a\nB\nc\n",
        tool_name="patch_file",
        tool_call_id="call-2",
    )

    assert state["file_count"] == 1
    hunk_id = state["files"][0]["hunks"][0]["id"]

    updated_state = service.accept_hunk(str(file_path), hunk_id)

    assert file_path.read_text(encoding="utf-8") == "a\nB\nc\n"
    assert updated_state["file_count"] == 0
    assert service.get_state()["file_count"] == 0


def test_reject_file_edits_removes_new_file_when_baseline_absent(tmp_path: Path):
    file_path = tmp_path / "new_file.py"
    service = _create_service(tmp_path)

    state = service.record_agent_edit(
        str(file_path),
        "print('hello')\n",
        tool_name="rewrite_file",
        tool_call_id="call-3",
    )

    assert file_path.exists()
    assert state["file_count"] == 1

    updated_state = service.reject_file_edits(str(file_path))

    assert not file_path.exists()
    assert updated_state["file_count"] == 0
    assert service.get_state()["file_count"] == 0
