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

import fnmatch
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

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
_MAX_READ_ERROR_SUMMARIES = 3
_MAX_READ_ERROR_MESSAGE_CHARS = 160

_BINARY_MAGIC_PREFIXES = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"PK\x03\x04",
    b"\x1f\x8b",
    b"\x7fELF",
    b"MZ",
    b"%PDF-",
)

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

        # ---- 执行搜索 ----
        try:
            results = _run_grep(
                abs_search,
                context.project_root,
                compiled,
                glob_pattern,
                context_lines,
                limit,
            )
        except Exception as e:
            return ToolResult(content=f"Error during search: {e}", is_error=True)

        details = _build_result_details(pattern, results)
        if (
            results["files_searched"] == 0
            and results["read_error_count"] > 0
        ):
            return ToolResult(
                content=_format_no_readable_files_error(results),
                is_error=True,
                details=details,
            )

        incomplete_notice = _format_incomplete_notice(results)
        if not results["output_lines"]:
            content = "No matches found."
            if incomplete_notice:
                content = (
                    "No matches found in the files that were successfully scanned."
                    f"\n\n[{incomplete_notice}]"
                )
            return ToolResult(
                content=content,
                details=details,
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
        if incomplete_notice:
            notices.append(incomplete_notice)
        if notices:
            output += f"\n\n[{' '.join(notices)}]"

        return ToolResult(
            content=output,
            details=details,
        )


# ============================================================
# 内部搜索实现
# ============================================================

def _read_search_lines(
    file_path: str,
) -> Tuple[Optional[List[str]], bool, Optional[BaseException]]:
    """Read one supported text file without interpreting binary data as text.

    Returns ``(lines, is_binary, error)``.  Supported encodings deliberately
    stay small and deterministic: UTF-8 with/without BOM and UTF-16 with a BOM
    or an unambiguous NUL-byte layout.
    """
    try:
        with open(file_path, "rb") as file_obj:
            raw = file_obj.read()
    except Exception as exc:
        return None, False, exc

    encoding: Optional[str] = None
    if raw.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    else:
        encoding = _guess_bomless_utf16(raw)

    if encoding is None:
        if _looks_like_binary_bytes(raw):
            return None, True, None
        encoding = "utf-8"

    try:
        text = raw.decode(encoding, errors="strict")
    except UnicodeError:
        # If bytes did not satisfy the binary heuristic, surface an explicit
        # unsupported-encoding read error rather than claiming a complete
        # no-match result.
        return None, False, UnicodeDecodeError(
            "utf-8/utf-16",
            raw[:1],
            0,
            min(1, len(raw)),
            "unsupported text encoding",
        )

    if _looks_like_binary_text(text):
        return None, True, None
    return text.splitlines(keepends=True), False, None


def _guess_bomless_utf16(raw: bytes) -> Optional[str]:
    """Recognize the common ASCII-heavy UTF-16 LE/BE byte layout."""
    sample = raw[:4096]
    if len(sample) < 4 or len(sample) % 2:
        return None
    even = sample[0::2]
    odd = sample[1::2]
    if not even or not odd:
        return None
    even_nul_ratio = even.count(0) / len(even)
    odd_nul_ratio = odd.count(0) / len(odd)
    if odd_nul_ratio >= 0.6 and even_nul_ratio <= 0.2:
        return "utf-16-le"
    if even_nul_ratio >= 0.6 and odd_nul_ratio <= 0.2:
        return "utf-16-be"
    return None


def _looks_like_binary_bytes(raw: bytes) -> bool:
    if not raw:
        return False
    if any(raw.startswith(prefix) for prefix in _BINARY_MAGIC_PREFIXES):
        return True
    sample = raw[:4096]
    if b"\x00" in sample:
        return True
    allowed_controls = {8, 9, 10, 12, 13}
    control_count = sum(
        1 for byte in sample if byte < 32 and byte not in allowed_controls
    )
    return (control_count / len(sample)) > 0.05


def _looks_like_binary_text(text: str) -> bool:
    if not text:
        return False
    sample = text[:4096]
    disallowed_controls = sum(
        1
        for char in sample
        if ord(char) < 32 and char not in "\b\t\n\f\r"
    )
    return "\x00" in sample or (disallowed_controls / len(sample)) > 0.02


def _safe_relative_path(file_path: str, project_root: str) -> str:
    try:
        return os.path.relpath(file_path, project_root).replace("\\", "/")
    except ValueError:
        return str(file_path).replace("\\", "/")


def _safe_read_error(
    file_path: str,
    project_root: str,
    error: BaseException,
) -> Dict[str, str]:
    message = " ".join(str(error).split())
    if len(message) > _MAX_READ_ERROR_MESSAGE_CHARS:
        message = message[: _MAX_READ_ERROR_MESSAGE_CHARS - 3] + "..."
    return {
        "path": _safe_relative_path(file_path, project_root),
        "error_type": type(error).__name__,
        "message": message or "read failed",
    }


def _format_read_error_summaries(results: Dict[str, Any]) -> str:
    summaries = []
    for item in results["read_errors"][:_MAX_READ_ERROR_SUMMARIES]:
        summaries.append(
            f"{item['path']}: {item['error_type']}: {item['message']}"
        )
    hidden_count = results["read_error_count"] - len(summaries)
    if hidden_count > 0:
        summaries.append(f"and {hidden_count} more read error(s)")
    return "; ".join(summaries)


def _format_no_readable_files_error(results: Dict[str, Any]) -> str:
    candidate_count = results["candidate_count"]
    read_error_count = results["read_error_count"]
    skipped_binary = results["skipped_binary"]
    parts = [
        "Error: grep_search could not scan any readable text files",
        f"candidates={candidate_count}",
        f"read_errors={read_error_count}",
        f"skipped_binary={skipped_binary}",
    ]
    error_summary = _format_read_error_summaries(results)
    if error_summary:
        parts.append(f"errors: {error_summary}")
    return ". ".join(parts) + "."


def _format_incomplete_notice(results: Dict[str, Any]) -> str:
    if results["read_error_count"] <= 0 or results["files_searched"] <= 0:
        return ""
    notice = (
        "Warning: search incomplete; "
        f"{results['read_error_count']} candidate file(s) could not be read"
    )
    error_summary = _format_read_error_summaries(results)
    if error_summary:
        notice += f" ({error_summary})"
    return notice + "."


def _build_result_details(pattern: str, results: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "query": pattern,
        "matches": results["match_count"],
        "match_count": results["match_count"],
        "candidate_files": results["candidate_count"],
        "files_searched": results["files_searched"],
        "read_error_count": results["read_error_count"],
        "read_errors": list(results["read_errors"]),
        "skipped_binary": results["skipped_binary"],
        "incomplete": results["read_error_count"] > 0,
    }


def _run_grep(
    abs_search: str,
    project_root: str,
    compiled: re.Pattern,
    glob_pattern: Optional[str],
    context_lines: int,
    limit: int,
) -> Dict[str, Any]:
    """
    遍历文件树，对每个文本文件的每行进行正则匹配。
    """
    output_lines: List[str] = []
    match_count = 0
    files_searched = 0
    limit_reached = False
    lines_truncated = False
    read_errors: List[Dict[str, str]] = []
    skipped_binary = 0

    # ---- 收集待搜索文件 ----
    if os.path.isfile(abs_search):
        candidate_files = [abs_search]
    else:
        candidate_files = []

        def _on_walk_error(error: OSError) -> None:
            error_path = str(getattr(error, "filename", "") or abs_search)
            read_errors.append(_safe_read_error(error_path, project_root, error))

        for dirpath, dirnames, filenames in os.walk(
            abs_search,
            onerror=_on_walk_error,
        ):
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

        file_lines, is_binary, read_error = _read_search_lines(fpath)
        if is_binary:
            skipped_binary += 1
            continue
        if read_error is not None:
            read_errors.append(_safe_read_error(fpath, project_root, read_error))
            continue
        if file_lines is None:
            # Defensive guard: every non-binary failure should carry an error.
            read_errors.append(
                _safe_read_error(
                    fpath,
                    project_root,
                    OSError("file could not be read"),
                )
            )
            continue

        files_searched += 1

        # 计算相对路径
        rel_path = _safe_relative_path(fpath, project_root)

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
        "candidate_count": len(candidate_files),
        "read_error_count": len(read_errors),
        "read_errors": read_errors,
        "skipped_binary": skipped_binary,
        "limit_reached": limit_reached,
        "lines_truncated": lines_truncated,
    }


# ============================================================
# 模块导出
# ============================================================

__all__ = ["GrepSearchTool"]
