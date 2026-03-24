# Truncate Utils - 内容截断工具函数
"""
内容截断工具函数

职责：
- 对工具输出内容按行数和字节数两个维度截断
- 保证截断粒度为完整行（不在行中间截断）
- 返回结构化的截断结果（供 UI 显示截断提示）

参考来源：
- pi-mono: packages/coding-agent/src/core/tools/truncate.ts
  - DEFAULT_MAX_LINES = 2000, DEFAULT_MAX_BYTES = 50 * 1024
  - TruncationResult 结构
  - truncateHead(): 从头截断，保留前 N 行/字节

设计说明：
- Python 中使用 len(s.encode('utf-8')) 替代 Node.js 的 Buffer.byteLength
- 截断逻辑与 pi-mono 完全一致：两个维度独立，先触及哪个就在哪里截断
"""

from dataclasses import dataclass
from typing import Optional


# ============================================================
# 常量
# ============================================================

DEFAULT_MAX_LINES = 2000
DEFAULT_MAX_BYTES = 50 * 1024  # 50KB
GREP_MAX_LINE_LENGTH = 500


# ============================================================
# 截断结果
# ============================================================

@dataclass
class TruncationResult:
    """
    截断结果
    
    对应 pi-mono 的 TruncationResult 接口。
    
    Attributes:
        content: 截断后的内容
        truncated: 是否发生了截断
        truncated_by: 触发截断的维度（"lines" | "bytes" | None）
        total_lines: 原始内容总行数
        total_bytes: 原始内容总字节数
        output_lines: 截断后的行数
        output_bytes: 截断后的字节数
        last_line_partial: 最后一行是否被部分截断（仅 tail 截断）
        first_line_exceeds_limit: 首行是否超过字节限制（仅 head 截断）
        max_lines: 应用的最大行数限制
        max_bytes: 应用的最大字节数限制
    """
    content: str
    truncated: bool
    truncated_by: Optional[str]  # "lines" | "bytes" | None
    total_lines: int
    total_bytes: int
    output_lines: int
    output_bytes: int
    last_line_partial: bool = False
    first_line_exceeds_limit: bool = False
    max_lines: int = DEFAULT_MAX_LINES
    max_bytes: int = DEFAULT_MAX_BYTES


# ============================================================
# 截断函数
# ============================================================

def truncate_head(
    content: str,
    max_lines: int = DEFAULT_MAX_LINES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> TruncationResult:
    """
    从头截断内容（保留前 N 行/字节）
    
    适用于文件读取场景——用户希望看到文件开头。
    
    对应 pi-mono truncateHead()：
    - 两个维度独立检查（行数、字节数），先触及哪个就在哪里截断
    - 不在行中间截断，始终保持完整行
    - 如果首行就超过字节限制，返回空内容并标记 first_line_exceeds_limit
    
    Args:
        content: 原始内容
        max_lines: 最大行数（默认 2000）
        max_bytes: 最大字节数（默认 50KB）
        
    Returns:
        TruncationResult
    """
    total_bytes = len(content.encode('utf-8'))
    lines = content.split('\n')
    total_lines = len(lines)
    
    # 无需截断
    if total_lines <= max_lines and total_bytes <= max_bytes:
        return TruncationResult(
            content=content,
            truncated=False,
            truncated_by=None,
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=total_lines,
            output_bytes=total_bytes,
            max_lines=max_lines,
            max_bytes=max_bytes,
        )
    
    # 检查首行是否超过字节限制
    first_line_bytes = len(lines[0].encode('utf-8'))
    if first_line_bytes > max_bytes:
        return TruncationResult(
            content="",
            truncated=True,
            truncated_by="bytes",
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=0,
            output_bytes=0,
            first_line_exceeds_limit=True,
            max_lines=max_lines,
            max_bytes=max_bytes,
        )
    
    # 逐行累积，直到触及行数或字节数限制
    output_lines_arr = []
    output_bytes_count = 0
    truncated_by = "lines"
    
    for i, line in enumerate(lines):
        if i >= max_lines:
            break
        
        # +1 for newline separator (except first line)
        line_bytes = len(line.encode('utf-8')) + (1 if i > 0 else 0)
        
        if output_bytes_count + line_bytes > max_bytes:
            truncated_by = "bytes"
            break
        
        output_lines_arr.append(line)
        output_bytes_count += line_bytes
    
    # 如果因行数限制退出且字节数仍在限制内
    if len(output_lines_arr) >= max_lines and output_bytes_count <= max_bytes:
        truncated_by = "lines"
    
    output_content = '\n'.join(output_lines_arr)
    final_output_bytes = len(output_content.encode('utf-8'))
    
    return TruncationResult(
        content=output_content,
        truncated=True,
        truncated_by=truncated_by,
        total_lines=total_lines,
        total_bytes=total_bytes,
        output_lines=len(output_lines_arr),
        output_bytes=final_output_bytes,
        max_lines=max_lines,
        max_bytes=max_bytes,
    )


def truncate_line(
    line: str,
    max_chars: int = GREP_MAX_LINE_LENGTH,
) -> tuple:
    """
    截断单行内容（用于 grep 匹配行）
    
    Args:
        line: 原始行内容
        max_chars: 最大字符数（默认 500）
        
    Returns:
        (text, was_truncated) 元组
    """
    if len(line) <= max_chars:
        return line, False
    return f"{line[:max_chars]}... [truncated]", True


# ============================================================
# 格式化辅助
# ============================================================

def format_size(byte_count: int) -> str:
    """
    格式化字节数为人类可读的大小
    
    对应 pi-mono formatSize()
    
    Args:
        byte_count: 字节数
        
    Returns:
        格式化字符串，如 "50.0KB"、"1.2MB"
    """
    if byte_count < 1024:
        return f"{byte_count}B"
    elif byte_count < 1024 * 1024:
        return f"{byte_count / 1024:.1f}KB"
    else:
        return f"{byte_count / (1024 * 1024):.1f}MB"


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "DEFAULT_MAX_LINES",
    "DEFAULT_MAX_BYTES",
    "GREP_MAX_LINE_LENGTH",
    "TruncationResult",
    "truncate_head",
    "truncate_line",
    "format_size",
]
