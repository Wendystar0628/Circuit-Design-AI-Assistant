# Shared Constants Package
"""
共享常量包

包含：
- file_limits.py - 文件大小限制常量
"""

from shared.constants.file_limits import (
    READ_FILE_MAX_BYTES,
    READ_FILE_DEFAULT_TOKENS,
    ANALYZE_FILE_MAX_BYTES,
    LARGE_FILE_WARNING_LINES,
    LARGE_FILE_WARNING_BYTES,
    CHARS_PER_TOKEN_ESTIMATE,
)

__all__ = [
    "READ_FILE_MAX_BYTES",
    "READ_FILE_DEFAULT_TOKENS",
    "ANALYZE_FILE_MAX_BYTES",
    "LARGE_FILE_WARNING_LINES",
    "LARGE_FILE_WARNING_BYTES",
    "CHARS_PER_TOKEN_ESTIMATE",
]
