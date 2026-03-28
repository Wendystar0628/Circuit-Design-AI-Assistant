# Find Files Tool - 文件查找工具
"""
文件查找工具（Python 原生实现）

职责：
- 按 glob 文件名模式在目录树中查找文件
- 跳过常见构建/缓存目录（.git、__pycache__ 等）
- 返回相对于搜索根目录的路径列表

参考来源：
- pi-mono: packages/coding-agent/src/core/tools/find.ts
  - 参数设计：pattern, path, limit
  - 输出：相对路径列表，每行一个

使用示例：
    tool = FindFilesTool()
    result = await tool.execute(
        tool_call_id="call_456",
        params={"pattern": "*.cir", "path": "circuits"},
        context=ToolContext(project_root="/project"),
    )
"""

import asyncio
import fnmatch
import os
from typing import Any, Dict, List, Optional, Set

from domain.llm.agent.types import BaseTool, ToolContext, ToolResult
from domain.llm.agent.utils.path_utils import resolve_to_cwd, is_path_within


# ============================================================
# 常量
# ============================================================

_DEFAULT_LIMIT = 200

_IGNORED_DIRS: Set[str] = {
    ".git", "__pycache__", ".pytest_cache", "node_modules",
    ".venv", "venv", "env", ".env", "dist", "build",
    ".idea", ".vscode", ".mypy_cache", ".tox", "htmlcov",
    ".eggs", "vendor", ".circuit_ai",
}


# ============================================================
# 工具实现
# ============================================================

class FindFilesTool(BaseTool):
    """
    文件查找工具

    对应 pi-mono 的 find 工具（find.ts）。
    使用 Python 内置 fnmatch 实现，无需外部工具（fd）。

    功能特点：
    - 支持 glob 文件名模式（如 *.cir、test_*.py、config.*）
    - 跳过 .git、__pycache__、node_modules 等常见无关目录
    - 结果为相对于搜索根目录的 POSIX 路径（/ 分隔符）
    - 支持 limit 限制返回数量
    """

    @property
    def name(self) -> str:
        return "find_files"

    @property
    def label(self) -> str:
        return "Find Files"

    @property
    def description(self) -> str:
        return (
            f"Find files by filename glob pattern. Returns matching file paths "
            f"relative to the search directory. "
            f"Skips common build/cache directories (.git, __pycache__, etc.). "
            f"Output limited to {_DEFAULT_LIMIT} results."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": (
                        "Filename glob pattern to match, e.g. '*.cir', '*.py', "
                        "'test_*', '*.sp'. Matches filename only, not full path."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search in (default: project root)",
                },
                "limit": {
                    "type": "integer",
                    "description": f"Maximum number of results to return (default: {_DEFAULT_LIMIT})",
                },
            },
            "required": ["pattern"],
        }

    @property
    def prompt_snippet(self) -> Optional[str]:
        return "Find files by filename glob pattern (e.g. '*.cir', '*.py')"

    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        return [
            "Use find_files to locate SPICE netlists (*.cir, *.sp) or Python files (*.py).",
            "Use find_files before read_file to confirm the file path.",
            "Use path parameter to narrow search to a specific subdirectory.",
        ]

    async def execute(
        self,
        tool_call_id: str,
        params: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        pattern = params.get("pattern", "")
        search_path_raw = params.get("path", "")
        limit = max(1, int(params.get("limit", _DEFAULT_LIMIT)))

        if not pattern:
            return ToolResult(content="Error: 'pattern' parameter is required", is_error=True)

        # ---- 解析搜索路径 ----
        if search_path_raw:
            abs_search = resolve_to_cwd(search_path_raw, context.project_root)
            if not is_path_within(abs_search, context.project_root):
                return ToolResult(
                    content=f"Error: path '{search_path_raw}' is outside the project directory",
                    is_error=True,
                )
            if not os.path.exists(abs_search):
                return ToolResult(
                    content=f"Error: path not found: '{search_path_raw}'",
                    is_error=True,
                )
            if not os.path.isdir(abs_search):
                return ToolResult(
                    content=f"Error: '{search_path_raw}' is not a directory",
                    is_error=True,
                )
        else:
            abs_search = context.project_root

        # ---- 在线程池中执行阻塞查找 ----
        try:
            results = await asyncio.to_thread(
                _run_find,
                abs_search,
                context.project_root,
                pattern,
                limit,
            )
        except Exception as e:
            return ToolResult(content=f"Error during file search: {e}", is_error=True)

        if not results["paths"]:
            return ToolResult(
                content=f"No files found matching pattern '{pattern}'.",
                details={"pattern": pattern, "count": 0},
            )

        output = "\n".join(results["paths"])

        if results["limit_reached"]:
            output += (
                f"\n\n[Result limit ({limit}) reached. "
                f"Use a more specific pattern or increase the limit.]"
            )

        return ToolResult(
            content=output,
            details={"pattern": pattern, "count": len(results["paths"])},
        )


# ============================================================
# 内部阻塞查找实现（在线程池中执行）
# ============================================================

def _run_find(
    abs_search: str,
    project_root: str,
    pattern: str,
    limit: int,
) -> Dict[str, Any]:
    """
    阻塞式文件查找，运行在 asyncio.to_thread() 中。

    遍历目录树，按 fnmatch 模式匹配文件名。
    """
    paths: List[str] = []
    limit_reached = False

    for dirpath, dirnames, filenames in os.walk(abs_search):
        # 原地修剪：跳过忽略目录和隐藏目录
        dirnames[:] = [
            d for d in dirnames
            if d not in _IGNORED_DIRS and not d.startswith(".")
        ]

        for fname in filenames:
            if fnmatch.fnmatch(fname, pattern):
                fpath = os.path.join(dirpath, fname)
                try:
                    rel = os.path.relpath(fpath, project_root).replace("\\", "/")
                except ValueError:
                    rel = fpath.replace("\\", "/")
                paths.append(rel)

                if len(paths) >= limit:
                    limit_reached = True
                    break

        if limit_reached:
            break

    return {"paths": paths, "limit_reached": limit_reached}


# ============================================================
# 模块导出
# ============================================================

__all__ = ["FindFilesTool"]
