# RewriteFileTool - 整体写入文件工具
"""
整体写入文件工具

职责：
- 创建新文件或完整覆盖已有文件
- 自动创建父目录
- 文件互斥队列保护

参考来源：
- pi-mono: packages/coding-agent/src/core/tools/write.ts

使用示例：
    tool = RewriteFileTool()
    result = await tool.execute(
        tool_call_id="call_789",
        params={"path": "src/new.cir", "content": "* New Circuit\\n.end"},
        context=ToolContext(project_root="/project"),
    )
"""

from typing import Any, Dict, List, Optional

from domain.llm.agent.types import BaseTool, ToolContext, ToolResult
from domain.llm.agent.utils.path_utils import validate_file_path
from domain.llm.agent.utils.file_mutex import with_file_mutex
from shared.service_locator import ServiceLocator
from shared.service_names import SVC_PENDING_WORKSPACE_EDIT_SERVICE


class RewriteFileTool(BaseTool):
    """
    整体写入文件工具

    对应 pi-mono 的 write 工具。
    用于创建新文件或完整覆盖已有文件。
    对于大文件的局部修改，应使用 patch_file。
    """

    @property
    def name(self) -> str:
        return "rewrite_file"

    @property
    def description(self) -> str:
        return (
            "Write content to a file. Creates the file if it doesn't exist, "
            "overwrites if it does. Automatically creates parent directories. "
            "Use this for new files or complete rewrites only. "
            "For surgical edits to existing files, use patch_file instead."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "File path (relative to project root or absolute)"
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "Complete content to write to the file",
                },
            },
            "required": ["path", "content"],
        }

    @property
    def prompt_snippet(self) -> Optional[str]:
        return "Create or overwrite files (new files or complete rewrites)"

    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        return [
            "Use rewrite_file only for new files or complete rewrites.",
            "For partial edits to existing files, use patch_file instead.",
        ]

    async def execute(
        self,
        tool_call_id: str,
        params: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """
        执行文件写入

        核心流程（对照 pi-mono write.ts 第 194-240 行）：
        1. 路径解析 + 安全校验（不要求文件已存在）
        2. 文件互斥队列保护
        3. 创建父目录
        4. 写入文件
        """
        path = params.get("path", "")
        content = params.get("content", "")

        # 参数校验
        if not path:
            return ToolResult(
                content="Error: 'path' parameter is required", is_error=True
            )

        # 路径解析 + 安全校验（must_exist=False：允许创建新文件）
        abs_path, error = validate_file_path(
            path, context.project_root, must_exist=False
        )
        if error:
            return ToolResult(content=f"Error: {error}", is_error=True)

        # 文件互斥队列保护
        async with with_file_mutex(abs_path):
            return await self._execute_write(abs_path, path, content, tool_call_id)

    async def _execute_write(
        self,
        abs_path: str,
        display_path: str,
        content: str,
        tool_call_id: str,
    ) -> ToolResult:
        """
        实际写入逻辑

        Args:
            abs_path: 绝对路径
            display_path: 显示路径（LLM 传入的原始路径）
            content: 写入内容
        """
        try:
            pending_workspace_edit_service = ServiceLocator.get_optional(
                SVC_PENDING_WORKSPACE_EDIT_SERVICE
            )
            if pending_workspace_edit_service is None:
                return ToolResult(
                    content="Error: PendingWorkspaceEditService not available",
                    is_error=True,
                )

            pending_workspace_edit_service.record_agent_edit(
                abs_path,
                content,
                tool_name=self.name,
                tool_call_id=tool_call_id,
            )

            byte_count = len(content.encode("utf-8"))
            line_count = content.count("\n") + (1 if content else 0)

            return ToolResult(
                content=f"Successfully wrote {byte_count} bytes to {display_path}",
                details={
                    "bytes": byte_count,
                    "lines": line_count,
                    "path": abs_path,
                },
            )
        except PermissionError:
            return ToolResult(
                content=f"Error: Permission denied writing to '{display_path}'",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(
                content=f"Error writing file '{display_path}': {e}",
                is_error=True,
            )


__all__ = ["RewriteFileTool"]
