# Location Types - Location Result Data Structures
"""
定位结果数据类型

用于跳转定义、查找引用等功能的返回值
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class LocationScope(Enum):
    """定位范围"""
    CURRENT_FILE = "current_file"      # 当前文件
    INCLUDE_FILES = "include_files"    # include 引用的文件
    PROJECT = "project"                # 整个项目


@dataclass
class LocationResult:
    """
    定位结果
    
    Attributes:
        file_path: 文件路径（相对路径）
        absolute_path: 文件绝对路径
        line: 行号（从 1 开始）
        column: 列号（从 0 开始）
        symbol_name: 符号名称
        symbol_type: 符号类型（subcircuit/parameter/class/function 等）
        preview: 代码预览（定义行内容）
        scope: 定位范围（在哪个范围找到的）
        confidence: 置信度（0.0-1.0）
    """
    file_path: str
    absolute_path: str
    line: int
    column: int = 0
    symbol_name: str = ""
    symbol_type: str = ""
    preview: str = ""
    scope: LocationScope = LocationScope.CURRENT_FILE
    confidence: float = 1.0
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "file_path": self.file_path,
            "absolute_path": self.absolute_path,
            "line": self.line,
            "column": self.column,
            "symbol_name": self.symbol_name,
            "symbol_type": self.symbol_type,
            "preview": self.preview,
            "scope": self.scope.value,
            "confidence": self.confidence,
        }


@dataclass
class ReferenceResult:
    """
    引用查找结果
    
    Attributes:
        file_path: 文件路径
        absolute_path: 文件绝对路径
        line: 行号
        column: 列号
        line_content: 行内容
        is_definition: 是否是定义位置
        context_type: 上下文类型（definition/usage/comment）
    """
    file_path: str
    absolute_path: str
    line: int
    column: int = 0
    line_content: str = ""
    is_definition: bool = False
    context_type: str = "usage"
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "file_path": self.file_path,
            "absolute_path": self.absolute_path,
            "line": self.line,
            "column": self.column,
            "line_content": self.line_content,
            "is_definition": self.is_definition,
            "context_type": self.context_type,
        }


@dataclass
class LocationContext:
    """
    定位上下文
    
    用于传递定位请求的上下文信息
    """
    file_path: str                          # 当前文件路径
    line: int = 0                           # 当前行号
    column: int = 0                         # 当前列号
    symbol_name: Optional[str] = None       # 要查找的符号名（可选）
    include_files: List[str] = field(default_factory=list)  # include 的文件列表


__all__ = [
    "LocationScope",
    "LocationResult",
    "ReferenceResult",
    "LocationContext",
]
