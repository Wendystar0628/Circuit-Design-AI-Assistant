# Read File Tool - 读取文件内容工具
"""
读取文件内容工具

职责：
- 读取指定路径的文件内容
- 支持 offset/limit 行号范围读取
- 对超长内容自动截断，附加续读提示
- 每行带行号前缀，方便 LLM 后续引用

参考来源：
- pi-mono: packages/coding-agent/src/core/tools/read.ts
  - readSchema: path, offset, limit 参数定义
  - execute(): 文件读取、offset/limit 切片、truncateHead 截断、行号显示、续读提示
- pi-mono: packages/coding-agent/src/core/tools/truncate.ts
  - truncateHead(): 行数/字节数双维度截断

使用示例：
    tool = ReadFileTool()
    result = await tool.execute(
        tool_call_id="call_123",
        params={"path": "src/main.cir", "offset": 1, "limit": 100},
        context=ToolContext(project_root="/project"),
    )
"""

import os
from typing import Any, Dict, List, Optional

from domain.llm.agent.types import BaseTool, ToolContext, ToolResult
from domain.llm.agent.utils.path_utils import resolve_read_path, is_path_within
from domain.llm.agent.utils.truncate import (
    truncate_head,
    format_size,
    DEFAULT_MAX_LINES,
    DEFAULT_MAX_BYTES,
)


class ReadFileTool(BaseTool):
    """
    读取文件内容工具
    
    对应 pi-mono 的 read 工具（read.ts）。
    读取文本文件内容，支持行号范围和自动截断。
    
    功能特点：
    - 支持 offset（起始行号，1-indexed）和 limit（最大行数）参数
    - 输出自动截断到 2000 行或 50KB（先触及哪个限制就在哪里截断）
    - 截断时追加续读提示（告诉 LLM 如何用 offset 继续读取）
    - 每行带行号前缀（方便 LLM 后续用行号引用代码）
    - 路径安全校验（禁止读取项目目录外的文件）
    """
    
    @property
    def name(self) -> str:
        return "read_file"
    
    @property
    def label(self) -> str:
        return "Read File"
    
    @property
    def description(self) -> str:
        return (
            f"Read the contents of a text file. "
            f"Output is truncated to {DEFAULT_MAX_LINES} lines or "
            f"{DEFAULT_MAX_BYTES // 1024}KB (whichever is hit first). "
            f"Use offset/limit for large files. "
            f"When you need the full file, continue with offset until complete."
        )
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read (relative to project root or absolute)",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-indexed)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read",
                },
            },
            "required": ["path"],
        }
    
    @property
    def prompt_snippet(self) -> Optional[str]:
        return "Read file contents, supports line range and auto-truncation"
    
    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        return [
            "Use read_file to examine files before making changes.",
            "For large files, use offset and limit to read specific sections.",
        ]
    
    async def execute(
        self,
        tool_call_id: str,
        params: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """
        执行文件读取
        
        核心流程（对照 pi-mono read.ts 第 186-237 行）：
        1. 路径解析 + 安全校验
        2. 文件存在性检查
        3. 读取文件全部内容
        4. 按 offset/limit 切片
        5. 截断（truncate_head）
        6. 构建带行号的输出 + 续读提示
        """
        path = params.get("path", "")
        offset = params.get("offset")
        limit = params.get("limit")
        
        # 参数校验
        if not path:
            return ToolResult(content="Error: 'path' parameter is required", is_error=True)
        
        if offset is not None and (not isinstance(offset, int) or offset < 1):
            return ToolResult(
                content=f"Error: 'offset' must be a positive integer (1-indexed), got {offset}",
                is_error=True,
            )
        
        if limit is not None and (not isinstance(limit, int) or limit < 1):
            return ToolResult(
                content=f"Error: 'limit' must be a positive integer, got {limit}",
                is_error=True,
            )
        
        # 1. 路径解析
        abs_path = resolve_read_path(path, context.project_root)
        
        # 2. 安全校验
        if not is_path_within(abs_path, context.project_root):
            return ToolResult(
                content=(
                    f"Error: Access denied. Path '{path}' resolves to '{abs_path}' "
                    f"which is outside the project directory."
                ),
                is_error=True,
            )
        
        # 3. 文件存在性检查
        if not os.path.exists(abs_path):
            return ToolResult(
                content=f"Error: File not found: '{abs_path}'",
                is_error=True,
            )
        
        if not os.path.isfile(abs_path):
            return ToolResult(
                content=f"Error: Path is not a file: '{abs_path}'",
                is_error=True,
            )
        
        # 4. 读取文件
        try:
            with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
                text_content = f.read()
        except PermissionError:
            return ToolResult(
                content=f"Error: Permission denied reading file: '{abs_path}'",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(
                content=f"Error reading file '{abs_path}': {e}",
                is_error=True,
            )
        
        # 5. 按行切分
        all_lines = text_content.split('\n')
        total_file_lines = len(all_lines)
        
        # 6. 应用 offset（从 1-indexed 转为 0-indexed）
        start_line = (offset - 1) if offset else 0
        start_line_display = start_line + 1  # 用于显示的 1-indexed
        
        # offset 超出文件总行数 → 返回错误（对应 read.ts 第 195-197 行）
        if start_line >= total_file_lines:
            return ToolResult(
                content=(
                    f"Error: Offset {offset} is beyond end of file "
                    f"({total_file_lines} lines total)"
                ),
                is_error=True,
            )
        
        # 7. 应用 limit 切片
        user_limited_lines = None
        if limit is not None:
            end_line = min(start_line + limit, total_file_lines)
            selected_content = '\n'.join(all_lines[start_line:end_line])
            user_limited_lines = end_line - start_line
        else:
            selected_content = '\n'.join(all_lines[start_line:])
        
        # 8. 截断（对应 read.ts 第 209 行: truncateHead）
        truncation = truncate_head(
            selected_content,
            max_lines=context.max_read_lines,
            max_bytes=DEFAULT_MAX_BYTES,
        )
        
        # 9. 构建输出文本
        details = None
        
        if truncation.first_line_exceeds_limit:
            # 首行超过字节限制（对应 read.ts 第 211-215 行）
            first_line_size = format_size(len(all_lines[start_line].encode('utf-8')))
            output_text = (
                f"[Line {start_line_display} is {first_line_size}, "
                f"exceeds {format_size(DEFAULT_MAX_BYTES)} limit. "
                f"The file content is too large for a single line.]"
            )
            details = {"truncation": _truncation_to_dict(truncation)}
            
        elif truncation.truncated:
            # 发生截断 → 添加行号 + 续读提示（对应 read.ts 第 216-226 行）
            end_line_display = start_line_display + truncation.output_lines - 1
            next_offset = end_line_display + 1
            
            numbered_text = _add_line_numbers(
                truncation.content, start_line_display
            )
            
            if truncation.truncated_by == "lines":
                numbered_text += (
                    f"\n\n[Showing lines {start_line_display}-{end_line_display} "
                    f"of {total_file_lines}. Use offset={next_offset} to continue.]"
                )
            else:
                numbered_text += (
                    f"\n\n[Showing lines {start_line_display}-{end_line_display} "
                    f"of {total_file_lines} ({format_size(DEFAULT_MAX_BYTES)} limit). "
                    f"Use offset={next_offset} to continue.]"
                )
            
            output_text = numbered_text
            details = {"truncation": _truncation_to_dict(truncation)}
            
        elif user_limited_lines is not None and start_line + user_limited_lines < total_file_lines:
            # 用户指定 limit 但文件还有更多内容（对应 read.ts 第 227-231 行）
            remaining = total_file_lines - (start_line + user_limited_lines)
            next_offset = start_line + user_limited_lines + 1
            
            numbered_text = _add_line_numbers(
                truncation.content, start_line_display
            )
            numbered_text += (
                f"\n\n[{remaining} more lines in file. "
                f"Use offset={next_offset} to continue.]"
            )
            output_text = numbered_text
            
        else:
            # 无截断，完整输出
            output_text = _add_line_numbers(
                truncation.content, start_line_display
            )
        
        return ToolResult(
            content=output_text,
            is_error=False,
            details=details,
        )


# ============================================================
# 内部辅助函数
# ============================================================

def _add_line_numbers(content: str, start_line: int = 1) -> str:
    """
    给内容添加行号前缀
    
    格式：右对齐行号 + tab，例如：
        1\tfirst line
        2\tsecond line
      100\thundredth line
    
    Args:
        content: 文本内容
        start_line: 起始行号（1-indexed）
        
    Returns:
        带行号的文本
    """
    lines = content.split('\n')
    end_line = start_line + len(lines) - 1
    width = len(str(end_line))
    
    numbered = []
    for i, line in enumerate(lines):
        line_num = start_line + i
        numbered.append(f"{line_num:>{width}}\t{line}")
    
    return '\n'.join(numbered)


def _truncation_to_dict(truncation) -> Dict[str, Any]:
    """将 TruncationResult 转为字典（供 details 使用）"""
    return {
        "truncated": truncation.truncated,
        "truncated_by": truncation.truncated_by,
        "total_lines": truncation.total_lines,
        "total_bytes": truncation.total_bytes,
        "output_lines": truncation.output_lines,
        "output_bytes": truncation.output_bytes,
        "first_line_exceeds_limit": truncation.first_line_exceeds_limit,
        "max_lines": truncation.max_lines,
        "max_bytes": truncation.max_bytes,
    }


# ============================================================
# 模块导出
# ============================================================

__all__ = ["ReadFileTool"]
