# Grep Search Tool - 文件内容搜索工具
"""
文件内容搜索工具（Python 原生实现）

职责：
- 使用 Python re 模块在文件内容中搜索正则或字面模式
- 支持 glob 文件过滤、大小写忽略、上下文行、结果数量限制
- 跳过二进制文件和常见构建/缓存目录
- 输出格式：filepath:line_num: content（与 ripgrep 风格一致）

参考来源：
- pi-mono: packages/coding-agent/src/core/tools/grep.ts
  - 参数设计：pattern, path, glob, ignoreCase, literal, context, limit
  - 输出格式：file:line: content 和上下文分隔符 --

使用示例：
    tool = GrepSearchTool()
    result = await tool.execute(
        tool_call_id="call_123",
        params={"pattern": "R1", "glob": "*.cir", "context_lines": 2},
        context=ToolContext(project_root="/project"),
    )
"""

import asyncio
import fnmatch
import os
import re
from typing import Any, Dict, List, Optional, Set

from domain.llm.agent.types import BaseTool, ToolContext, ToolResult
from domain.llm.agent.utils.path_utils import resolve_to_cwd, is_path_within
from domain.llm.agent.utils.truncate import (
    truncate_head,
    truncate_line,
    DEFAULT_MAX_BYTES,
)


# ============================================================
# 常量
# ============================================================

_DEFAULT_LIMIT = 50

_IGNORED_DIRS: Set[str] = {
    ".git", "__pycache__", ".pytest_cache", "node_modules",
    ".venv", "venv", "env", ".env", "dist", "build",
    ".idea", ".vscode", ".mypy_cache", ".tox", "htmlcov",
    ".eggs", "vendor", ".circuit_ai",
}


# ============================================================
# 工具实现
# ============================================================

class GrepSearchTool(BaseTool):
    """
    文件内容搜索工具

    对应 pi-mono 的 grep 工具（grep.ts）。
    使用 Python 内置 re 模块实现，无需外部工具（ripgrep）。

    功能特点：
    - 支持正则表达式和字面字符串两种搜索模式
    - 支持按 glob 模式过滤目标文件（如 *.cir, *.py）
    - 支持上下文行（匹配行前后 N 行）
    - 跳过二进制文件，跳过 .git/__pycache__ 等目录
    - 输出按 file:line: content 格式排列，便于 LLM 定位
    """

    @property
    def name(self) -> str:
        return "grep_search"

    @property
    def label(self) -> str:
        return "Grep Search"

    @property
    def description(self) -> str:
        return (
            f"Search file contents for a pattern. Returns matching lines with file "
            f"paths and line numbers. Supports regex or literal strings. "
            f"Output limited to {_DEFAULT_LIMIT} matches. "
            f"Skips binary files and common build/cache directories."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": (
                        "Search pattern. Treated as regex by default; "
                        "use fixed_strings=true for literal text."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": "Directory or file to search (default: project root)",
                },
                "glob": {
                    "type": "string",
                    "description": (
                        "Filter files by glob pattern, e.g. '*.py', '*.cir', '*.txt'. "
                        "Applies only when searching a directory."
                    ),
                },
                "ignore_case": {
                    "type": "boolean",
                    "description": "Case-insensitive search (default: false)",
                },
                "fixed_strings": {
                    "type": "boolean",
                    "description": "Treat pattern as literal string, not regex (default: false)",
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Lines of context before and after each match (default: 0)",
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        f"Maximum number of matches to return (default: {_DEFAULT_LIMIT}). "
                        f"Increase if you need more results."
                    ),
                },
            },
            "required": ["pattern"],
        }

    @property
    def prompt_snippet(self) -> Optional[str]:
        return "Search file contents for regex patterns or literal strings"

    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        return [
            "Use grep_search to find where a component, function, or value appears across files.",
            "Use glob='*.cir' or glob='*.sp' to search only SPICE netlist files.",
            "Use fixed_strings=true when searching for literal text containing regex special chars.",
            "Use context_lines=2 to see surrounding lines for better understanding.",
        ]

    async def execute(
        self,
        tool_call_id: str,
        params: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        pattern = params.get("pattern", "")
        search_path_raw = params.get("path", "")
        glob_pattern = params.get("glob") or None
        ignore_case = bool(params.get("ignore_case", False))
        fixed_strings = bool(params.get("fixed_strings", False))
        context_lines = max(0, int(params.get("context_lines", 0)))
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
        else:
            abs_search = context.project_root

        # ---- 编译正则 ----
        try:
            flags = re.IGNORECASE if ignore_case else 0
            compiled = re.compile(
                re.escape(pattern) if fixed_strings else pattern,
                flags,
            )
        except re.error as e:
            return ToolResult(
                content=f"Error: invalid regex pattern '{pattern}': {e}",
                is_error=True,
            )

        # ---- 在线程池中执行阻塞搜索 ----
        try:
            results = await asyncio.to_thread(
                _run_grep,
                abs_search,
                context.project_root,
                compiled,
                glob_pattern,
                context_lines,
                limit,
            )
        except Exception as e:
            return ToolResult(content=f"Error during search: {e}", is_error=True)

        if not results["output_lines"]:
            return ToolResult(
                content="No matches found.",
                details={"query": pattern, "matches": 0},
            )

        raw_output = "\n".join(results["output_lines"])

        # ---- 字节截断保护 ----
        trunc = truncate_head(raw_output, max_lines=10000, max_bytes=DEFAULT_MAX_BYTES)
        output = trunc.content

        notices = []
        if results["limit_reached"]:
            notices.append(
                f"Match limit ({limit}) reached. Refine the pattern or increase limit."
            )
        if results["lines_truncated"]:
            notices.append("Some long lines were truncated to 500 chars.")
        if trunc.truncated:
            notices.append("Output truncated due to size limit.")
        if notices:
            output += f"\n\n[{' '.join(notices)}]"

        return ToolResult(
            content=output,
            details={
                "query": pattern,
                "match_count": results["match_count"],
                "files_searched": results["files_searched"],
            },
        )


# ============================================================
# 内部阻塞搜索实现（在线程池中执行）
# ============================================================

def _run_grep(
    abs_search: str,
    project_root: str,
    compiled: re.Pattern,
    glob_pattern: Optional[str],
    context_lines: int,
    limit: int,
) -> Dict[str, Any]:
    """
    阻塞式 grep 实现，运行在 asyncio.to_thread() 中。

    遍历文件树，对每个文本文件的每行进行正则匹配。
    """
    output_lines: List[str] = []
    match_count = 0
    files_searched = 0
    limit_reached = False
    lines_truncated = False

    # ---- 收集待搜索文件 ----
    if os.path.isfile(abs_search):
        candidate_files = [abs_search]
    else:
        candidate_files = []
        for dirpath, dirnames, filenames in os.walk(abs_search):
            # 原地修剪：跳过忽略目录和隐藏目录
            dirnames[:] = [
                d for d in dirnames
                if d not in _IGNORED_DIRS and not d.startswith(".")
            ]
            for fname in filenames:
                if glob_pattern and not fnmatch.fnmatch(fname, glob_pattern):
                    continue
                candidate_files.append(os.path.join(dirpath, fname))

    # ---- 逐文件搜索 ----
    for fpath in candidate_files:
        if limit_reached:
            break

        # 跳过二进制文件
        try:
            with open(fpath, "r", encoding="utf-8", errors="strict") as f:
                file_lines = f.readlines()
        except (UnicodeDecodeError, PermissionError):
            continue
        except Exception:
            continue

        files_searched += 1

        # 计算相对路径
        try:
            rel_path = os.path.relpath(fpath, project_root).replace("\\", "/")
        except ValueError:
            rel_path = fpath.replace("\\", "/")

        # 逐行匹配
        for line_idx, raw_line in enumerate(file_lines):
            if limit_reached:
                break

            line_content = raw_line.rstrip("\n").rstrip("\r")

            if not compiled.search(line_content):
                continue

            match_count += 1
            if match_count > limit:
                limit_reached = True
                match_count = limit
                break

            # ---- 上下文行 ----
            ctx_start = max(0, line_idx - context_lines)
            ctx_end = min(len(file_lines), line_idx + context_lines + 1)

            for ctx_idx in range(ctx_start, ctx_end):
                ctx_raw = file_lines[ctx_idx].rstrip("\n").rstrip("\r")
                ctx_text, was_trunc = truncate_line(ctx_raw)
                if was_trunc:
                    lines_truncated = True

                line_num = ctx_idx + 1
                if ctx_idx == line_idx:
                    output_lines.append(f"{rel_path}:{line_num}: {ctx_text}")
                else:
                    output_lines.append(f"{rel_path}-{line_num}- {ctx_text}")

            # 上下文块之间的分隔符
            if context_lines > 0:
                output_lines.append("--")

    return {
        "output_lines": output_lines,
        "match_count": match_count,
        "files_searched": files_searched,
        "limit_reached": limit_reached,
        "lines_truncated": lines_truncated,
    }


# ============================================================
# 模块导出
# ============================================================

__all__ = ["GrepSearchTool"]
