# LoadResult - Unified File Load Result
"""
统一文件加载结果数据类

职责：
- 定义文件加载操作的统一返回结构
- 明确区分"成功/文件缺失/解析错误"等状态
- 替代返回空字典或抛异常的做法

设计原则：
- 防御性读取：调用方通过检查 success 字段决定后续处理
- 类型安全：使用泛型支持不同类型的加载数据
- 错误码标准化：统一的错误码便于 UI 层处理

使用示例：
    from shared.models.load_result import LoadResult
    
    # 服务层返回 LoadResult
    result = simulation_service.load_sim_result(project_root, path)
    
    # 调用方检查结果
    if result.success:
        data = result.data
    elif result.error_code == LoadErrorCode.FILE_MISSING:
        # 显示文件缺失占位图
        pass
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, Optional, TypeVar

T = TypeVar("T")


class LoadErrorCode(Enum):
    """加载错误码枚举"""
    
    FILE_MISSING = "FILE_MISSING"
    """文件不存在（悬空指针场景）"""
    
    PARSE_ERROR = "PARSE_ERROR"
    """文件存在但解析失败"""
    
    PERMISSION_DENIED = "PERMISSION_DENIED"
    """文件存在但无读取权限"""
    
    PATH_EMPTY = "PATH_EMPTY"
    """路径为空字符串"""
    
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    """未知错误"""


@dataclass
class LoadResult(Generic[T]):
    """
    统一文件加载结果
    
    Attributes:
        success: 是否成功
        data: 加载的数据（成功时有值）
        error_code: 错误码（失败时有值）
        error_message: 错误消息（失败时有值）
        file_path: 尝试加载的文件路径
    """
    
    success: bool
    data: Optional[T]
    error_code: Optional[LoadErrorCode]
    error_message: Optional[str]
    file_path: str
    
    # ============================================================
    # 工厂方法
    # ============================================================
    
    @classmethod
    def ok(cls, data: T, file_path: str) -> "LoadResult[T]":
        """
        创建成功结果
        
        Args:
            data: 加载的数据
            file_path: 文件路径
            
        Returns:
            LoadResult: 成功结果
        """
        return cls(
            success=True,
            data=data,
            error_code=None,
            error_message=None,
            file_path=file_path,
        )
    
    @classmethod
    def file_missing(cls, file_path: str) -> "LoadResult[Any]":
        """
        创建文件缺失结果
        
        Args:
            file_path: 缺失的文件路径
            
        Returns:
            LoadResult: 文件缺失结果
        """
        return cls(
            success=False,
            data=None,
            error_code=LoadErrorCode.FILE_MISSING,
            error_message=f"文件不存在: {file_path}",
            file_path=file_path,
        )
    
    @classmethod
    def path_empty(cls) -> "LoadResult[Any]":
        """
        创建路径为空结果
        
        Returns:
            LoadResult: 路径为空结果
        """
        return cls(
            success=False,
            data=None,
            error_code=LoadErrorCode.PATH_EMPTY,
            error_message="文件路径为空",
            file_path="",
        )
    
    @classmethod
    def parse_error(cls, file_path: str, message: str) -> "LoadResult[Any]":
        """
        创建解析错误结果
        
        Args:
            file_path: 文件路径
            message: 错误消息
            
        Returns:
            LoadResult: 解析错误结果
        """
        return cls(
            success=False,
            data=None,
            error_code=LoadErrorCode.PARSE_ERROR,
            error_message=f"文件解析失败: {message}",
            file_path=file_path,
        )
    
    @classmethod
    def permission_denied(cls, file_path: str) -> "LoadResult[Any]":
        """
        创建权限拒绝结果
        
        Args:
            file_path: 文件路径
            
        Returns:
            LoadResult: 权限拒绝结果
        """
        return cls(
            success=False,
            data=None,
            error_code=LoadErrorCode.PERMISSION_DENIED,
            error_message=f"无读取权限: {file_path}",
            file_path=file_path,
        )
    
    @classmethod
    def unknown_error(cls, file_path: str, message: str) -> "LoadResult[Any]":
        """
        创建未知错误结果
        
        Args:
            file_path: 文件路径
            message: 错误消息
            
        Returns:
            LoadResult: 未知错误结果
        """
        return cls(
            success=False,
            data=None,
            error_code=LoadErrorCode.UNKNOWN_ERROR,
            error_message=message,
            file_path=file_path,
        )
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def is_file_missing(self) -> bool:
        """检查是否为文件缺失错误"""
        return self.error_code == LoadErrorCode.FILE_MISSING
    
    def get_data_or_default(self, default: T) -> T:
        """获取数据，失败时返回默认值"""
        return self.data if self.success and self.data is not None else default


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "LoadResult",
    "LoadErrorCode",
]
