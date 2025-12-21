# Dependency Item Data Class
"""
依赖项数据类

职责：
- 定义单个依赖项的数据结构
- 记录依赖的来源文件、行号、引用路径
- 跟踪依赖的解析状态
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DependencyType(Enum):
    """依赖类型"""
    INCLUDE = "include"      # .include 语句引用
    LIB = "lib"              # .lib 语句引用
    MODEL = "model"          # .model 引用（内联或外部）
    SUBCIRCUIT = "subcircuit"  # 子电路引用


class DependencyStatus(Enum):
    """依赖状态"""
    RESOLVED = "resolved"              # 已解析（文件存在）
    MISSING = "missing"                # 缺失（文件不存在）
    PENDING_CONFIRMATION = "pending"   # 待用户确认（外部源可下载）
    RESOLVING = "resolving"            # 正在解析中
    ERROR = "error"                    # 解析错误


@dataclass
class DependencyItem:
    """
    依赖项数据类
    
    记录电路文件中的单个依赖引用信息
    """
    # 唯一标识
    id: str
    
    # 依赖类型
    dep_type: DependencyType
    
    # 原始引用路径（.include 语句中的路径字符串）
    raw_path: str
    
    # 来源文件路径（包含此依赖引用的电路文件）
    source_file: str
    
    # 来源行号
    source_line: int
    
    # 当前状态
    status: DependencyStatus = DependencyStatus.MISSING
    
    # 解析后的绝对路径（若已解析）
    resolved_path: Optional[str] = None
    
    # 解析来源（若已解析）
    resolution_source: Optional[str] = None
    
    # 错误信息（若状态为 ERROR）
    error_message: Optional[str] = None
    
    # 可用的解析建议列表
    suggestions: list = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "id": self.id,
            "dep_type": self.dep_type.value,
            "raw_path": self.raw_path,
            "source_file": self.source_file,
            "source_line": self.source_line,
            "status": self.status.value,
            "resolved_path": self.resolved_path,
            "resolution_source": self.resolution_source,
            "error_message": self.error_message,
            "suggestions": self.suggestions,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "DependencyItem":
        """从字典反序列化"""
        return cls(
            id=data["id"],
            dep_type=DependencyType(data["dep_type"]),
            raw_path=data["raw_path"],
            source_file=data["source_file"],
            source_line=data["source_line"],
            status=DependencyStatus(data.get("status", "missing")),
            resolved_path=data.get("resolved_path"),
            resolution_source=data.get("resolution_source"),
            error_message=data.get("error_message"),
            suggestions=data.get("suggestions", []),
        )
    
    def is_resolved(self) -> bool:
        """判断是否已解析"""
        return self.status == DependencyStatus.RESOLVED
    
    def is_missing(self) -> bool:
        """判断是否缺失"""
        return self.status == DependencyStatus.MISSING


__all__ = [
    "DependencyItem",
    "DependencyStatus",
    "DependencyType",
]
