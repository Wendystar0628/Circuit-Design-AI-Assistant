# List Directory Tool - 目录列表工具
"""
目录列表工具

职责：
- 列出目录内容，目录条目以 / 结尾
- 按字母顺序排序，包含隐藏文件
- 支持 limit 参数限制返回数量

参考来源：
- pi-mono: packages/coding-agent/src/core/tools/ls.ts
  - 参数设计：path, limit
  - 输出格式：每行一个条目，目录以 / 结尾，字母排序

使用示例：
    tool = ListDirectoryTool()
    result = await tool.execute(
        tool_call_id="call_789",
        params={"path": "circuits"},
        context=ToolContext(project_root="/project"),
    )
"""

import os
from typing import Any, Dict, List, Optional

from domain.llm.agent.types import BaseTool, ToolContext, ToolResult
from domain.llm.agent.utils.path_utils import resolve_to_cwd, is_path_within


# ============================================================
# 常量
# ============================================================

_DEFAULT_LIMIT = 200


# ============================================================
# 工具实现
# ============================================================

class ListDirectoryTool(BaseTool):
    """
    目录列表工具

    对应 pi-mono 的 ls 工具（ls.ts）。
    列出目录内容，目录条目以 / 结尾，结果按字母顺序排序。

    功能特点：
    - 包含隐藏文件（以 . 开头的文件/目录）
    - 目录条目以 / 结尾，文件条目无后缀
    - 按字母顺序（大小写不敏感）排序
    - 支持 limit 限制返回数量
    """

    @property
    def name(self) -> str:
        return "list_directory"

    @property
    def label(self) -> str:
        return "List Directory"

    @property
    def description(self) -> str:
        return (
            f"List the contents of a directory. Entries are sorted alphabetically; "
            f"directories have a trailing '/'. Includes dotfiles. "
            f"Output limited to {_DEFAULT_LIMIT} entries."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory to list (default: project root)",
                },
                "limit": {
                    "type": "integer",
                    "description": f"Maximum number of entries to return (default: {_DEFAULT_LIMIT})",
                },
            },
            "required": [],
        }

    @property
    def prompt_snippet(self) -> Optional[str]:
        return "List directory contents (sorted alphabetically, directories marked with /)"

    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        return [
            "Use list_directory to see the direct contents of a folder.",
            "Directories are marked with a trailing '/'; the listing is sorted alphabetically.",
        ]

    async def execute(
        self,
        tool_call_id: str,
        params: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        path_raw = params.get("path", "")
        limit = max(1, int(params.get("limit", _DEFAULT_LIMIT)))

        # ---- 解析目录路径 ----
        if path_raw:
            abs_path = resolve_to_cwd(path_raw, context.project_root)
            if not is_path_within(abs_path, context.project_root):
                return ToolResult(
                    content=f"Error: path '{path_raw}' is outside the project directory",
                    is_error=True,
                )
        else:
            abs_path = context.project_root

        if not os.path.exists(abs_path):
            return ToolResult(
                content=f"Error: path not found: '{abs_path}'",
                is_error=True,
            )
        if not os.path.isdir(abs_path):
            return ToolResult(
                content=f"Error: '{abs_path}' is not a directory",
                is_error=True,
            )

        # ---- 执行列目录 ----
        try:
            result = _list_dir(abs_path, limit)
        except Exception as e:
            return ToolResult(content=f"Error listing directory: {e}", is_error=True)

        if not result["items"]:
            return ToolResult(
                content="(empty directory)",
                details={"path": abs_path, "count": 0},
            )

        output = "\n".join(result["items"])
        if result["limit_reached"]:
            output += (
                f"\n\n[Entry limit ({limit}) reached. "
                f"Use limit parameter for more results.]"
            )

        return ToolResult(
            content=output,
            details={"path": abs_path, "count": len(result["items"])},
        )


# ============================================================
# 内部实现
# ============================================================

def _list_dir(abs_path: str, limit: int) -> Dict[str, Any]:
    """列出目录内容，返回排序后的条目列表。"""
    try:
        raw_entries = os.listdir(abs_path)
    except PermissionError:
        raise RuntimeError(f"Permission denied reading directory: {abs_path}")

    # 字母排序（大小写不敏感）
    raw_entries.sort(key=lambda x: x.lower())

    items: List[str] = []
    limit_reached = False

    for entry in raw_entries:
        if len(items) >= limit:
            limit_reached = True
            break

        full = os.path.join(abs_path, entry)
        try:
            suffix = "/" if os.path.isdir(full) else ""
        except OSError:
            suffix = ""

        items.append(entry + suffix)

    return {"items": items, "limit_reached": limit_reached}


# ============================================================
# 模块导出
# ============================================================

__all__ = ["ListDirectoryTool"]
