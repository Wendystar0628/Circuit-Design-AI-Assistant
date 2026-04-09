import asyncio
from pathlib import Path

from application.pending_workspace_edit_service import PendingWorkspaceEditService
from domain.llm.agent.tools.patch_file import PatchFileTool
from domain.llm.agent.types import ToolContext
from infrastructure.persistence.file_manager import FileManager
from shared.service_locator import ServiceLocator
from shared.service_names import (
    SVC_FILE_MANAGER,
    SVC_PENDING_WORKSPACE_EDIT_SERVICE,
    SVC_SESSION_STATE_MANAGER,
)


class _SessionStateManager:
    def __init__(self, project_root: str):
        self._project_root = project_root

    def get_project_root(self) -> str:
        return self._project_root


def _register_services(project_root: Path) -> PendingWorkspaceEditService:
    file_manager = FileManager()
    file_manager.set_work_dir(project_root)
    ServiceLocator.register(SVC_FILE_MANAGER, file_manager)
    ServiceLocator.register(
        SVC_SESSION_STATE_MANAGER,
        _SessionStateManager(str(project_root)),
    )
    service = PendingWorkspaceEditService()
    ServiceLocator.register(SVC_PENDING_WORKSPACE_EDIT_SERVICE, service)
    return service


def test_patch_file_preserves_crlf_without_inserting_blank_lines(tmp_path: Path):
    ServiceLocator.clear()
    try:
        file_path = tmp_path / "main.py"
        file_path.write_bytes(b"a\r\nb\r\nc\r\n")
        _register_services(tmp_path)

        tool = PatchFileTool()
        result = asyncio.run(
            tool.execute(
                tool_call_id="call-crlf",
                params={
                    "path": str(file_path),
                    "old_text": "b",
                    "new_text": "B",
                },
                context=ToolContext(project_root=str(tmp_path)),
            )
        )

        assert result.is_error is False
        updated_bytes = file_path.read_bytes()
        assert updated_bytes == b"a\r\nB\r\nc\r\n"
        assert b"\r\r\n" not in updated_bytes
    finally:
        ServiceLocator.clear()
