# File Exceptions - File Operation Exception Classes
"""
文件操作异常类定义

职责：
- 集中定义文件操作相关的异常类
- 供 file_manager.py 和外部调用方使用

使用示例：
    from infrastructure.persistence.file_exceptions import (
        FileManagerError,
        SearchNotFoundError,
        FileLockTimeoutError,
    )
    
    try:
        file_manager.patch_file(path, search, replace)
    except SearchNotFoundError as e:
        print(f"搜索内容未找到: {e.search_preview}")
    except FileLockTimeoutError as e:
        print(f"文件锁超时: {e.path}")
"""

from typing import List


class FileManagerError(Exception):
    """文件管理器基础异常"""
    pass


class PathSecurityError(FileManagerError):
    """路径安全校验失败"""
    
    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"路径安全校验失败: {path} - {reason}")


class FileExistsError(FileManagerError):
    """文件已存在且内容不同"""
    
    def __init__(self, path: str):
        self.path = path
        super().__init__(
            f"文件已存在且内容不同: {path}\n"
            f"如需覆盖，请使用 update_file() 方法"
        )


class DirectoryCreationError(FileManagerError):
    """目录创建失败"""
    
    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"目录创建失败: {path} - {reason}")


class SearchNotFoundError(FileManagerError):
    """搜索内容未找到"""
    
    def __init__(self, path: str, search_preview: str):
        self.path = path
        self.search_preview = search_preview
        super().__init__(
            f"搜索内容未找到: {path}\n"
            f"搜索内容摘要: {search_preview[:100]}..."
        )


class MultipleMatchError(FileManagerError):
    """搜索内容匹配多处"""
    
    def __init__(self, path: str, match_count: int, positions: List[int]):
        self.path = path
        self.match_count = match_count
        self.positions = positions
        super().__init__(
            f"搜索内容匹配 {match_count} 处: {path}\n"
            f"匹配位置: {positions}\n"
            f"请指定 occurrence 参数或使用更精确的搜索内容"
        )


class LineRangeError(FileManagerError):
    """行号范围错误"""
    
    def __init__(self, path: str, start_line: int, end_line: int, total_lines: int):
        self.path = path
        self.start_line = start_line
        self.end_line = end_line
        self.total_lines = total_lines
        super().__init__(
            f"行号范围错误: {path}\n"
            f"请求范围: {start_line}-{end_line}, 文件总行数: {total_lines}"
        )


class FileLockTimeoutError(FileManagerError):
    """文件锁获取超时"""
    
    def __init__(self, path: str, timeout: float):
        self.path = path
        self.timeout = timeout
        super().__init__(f"文件锁获取超时 ({timeout}s): {path}")


class FileOperationError(FileManagerError):
    """文件操作失败"""
    
    def __init__(self, operation: str, path: str, reason: str):
        self.operation = operation
        self.path = path
        self.reason = reason
        super().__init__(f"文件操作失败 [{operation}]: {path} - {reason}")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "FileManagerError",
    "PathSecurityError",
    "FileExistsError",
    "DirectoryCreationError",
    "SearchNotFoundError",
    "MultipleMatchError",
    "LineRangeError",
    "FileLockTimeoutError",
    "FileOperationError",
]
