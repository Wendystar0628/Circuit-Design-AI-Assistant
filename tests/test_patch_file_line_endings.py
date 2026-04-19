import asyncio
from pathlib import Path

from application.pending_workspace_edit_service import PendingWorkspaceEditService
from domain.llm.agent.tools.patch_file import PatchFileTool
from domain.llm.agent.types import ToolContext
from infrastructure.persistence.file_manager import FileManager
from shared.service_locator import ServiceLocator
from shared.service_names import (
    SVC_FILE_MANAGER,
    SVC_SESSION_STATE_MANAGER,
)


class _SessionStateManager:
    def __init__(self, project_root: str):
        self._project_root = project_root

    def get_project_root(self) -> str:
        return self._project_root


def _register_services(project_root: Path) -> PendingWorkspaceEditService:
    """PendingWorkspaceEditService 自身仍通过 ServiceLocator 拿其上游
    依赖（file_manager、session_state_manager）——那是 application 层
    拿同层服务的合理用法。此处只构造服务并返回给测试用例，
    测试通过 ToolContext 显式把它注入给 PatchFileTool，
    **不再**把 SVC_PENDING_WORKSPACE_EDIT_SERVICE 注册到 locator，
    因为 tool 层已经根除了对 ServiceLocator 的依赖。
    """
    file_manager = FileManager()
    file_manager.set_work_dir(project_root)
    ServiceLocator.register(SVC_FILE_MANAGER, file_manager)
    ServiceLocator.register(
        SVC_SESSION_STATE_MANAGER,
        _SessionStateManager(str(project_root)),
    )
    return PendingWorkspaceEditService()


def test_patch_file_preserves_crlf_without_inserting_blank_lines(tmp_path: Path):
    ServiceLocator.clear()
    try:
        file_path = tmp_path / "main.py"
        file_path.write_bytes(b"a\r\nb\r\nc\r\n")
        pending_edit_service = _register_services(tmp_path)

        tool = PatchFileTool()
        result = asyncio.run(
            tool.execute(
                tool_call_id="call-crlf",
                params={
                    "path": str(file_path),
                    "old_text": "b",
                    "new_text": "B",
                },
                context=ToolContext(
                    project_root=str(tmp_path),
                    pending_workspace_edit_service=pending_edit_service,
                ),
            )
        )

        assert result.is_error is False
        updated_bytes = file_path.read_bytes()
        assert updated_bytes == b"a\r\nB\r\nc\r\n"
        assert b"\r\r\n" not in updated_bytes
    finally:
        ServiceLocator.clear()
