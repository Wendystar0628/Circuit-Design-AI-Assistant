# Agent Utils - Agent 工具函数包
"""
Agent 工具函数模块

提供工具实现所需的通用工具函数：
- path_utils : 路径解析、安全校验
- truncate   : 内容截断（行数/字节数限制）
- edit_diff  : 行尾归一化、模糊匹配、diff 生成（后续实现）
- file_mutex : 文件写入互斥队列（后续实现）
"""

from domain.llm.agent.utils.path_utils import (
    expand_path,
    resolve_to_cwd,
    resolve_read_path,
    is_path_within,
)

from domain.llm.agent.utils.truncate import (
    truncate_head,
    format_size,
    TruncationResult,
    DEFAULT_MAX_LINES,
    DEFAULT_MAX_BYTES,
)


__all__ = [
    # path_utils
    "expand_path",
    "resolve_to_cwd",
    "resolve_read_path",
    "is_path_within",
    # truncate
    "truncate_head",
    "format_size",
    "TruncationResult",
    "DEFAULT_MAX_LINES",
    "DEFAULT_MAX_BYTES",
]
