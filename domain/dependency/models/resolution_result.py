# Resolution Result Data Class
"""
依赖解析结果数据类

职责：
- 记录依赖解析尝试的结果
- 标识解析来源
- 支持用户确认流程
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ResolutionSource(Enum):
    """解析来源"""
    PROJECT_LOCAL = "project_local"      # 项目内路径修正
    GLOBAL_LIBRARY = "global_library"    # 全局库目录
    MARKETPLACE = "marketplace"          # 元器件商城（嘉立创）
    PUBLIC_LIBRARY = "public_library"    # 公开模型库
    USER_SPECIFIED = "user_specified"    # 用户手动指定


@dataclass
class ResolutionResult:
    """
    依赖解析结果
    
    记录单次解析尝试的结果
    """
    # 关联的依赖项 ID
    dependency_id: str
    
    # 是否成功
    success: bool
    
    # 解析来源
    source: ResolutionSource
    
    # 解析后的路径（若成功）
    resolved_path: Optional[str] = None
    
    # 是否需要用户确认
    requires_confirmation: bool = False
    
    # 确认提示信息
    confirmation_message: Optional[str] = None
    
    # 错误信息（若失败）
    error_message: Optional[str] = None
    
    # 元数据（如商城元器件 ID、下载 URL 等）
    metadata: Optional[dict] = None
    
    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "dependency_id": self.dependency_id,
            "success": self.success,
            "source": self.source.value,
            "resolved_path": self.resolved_path,
            "requires_confirmation": self.requires_confirmation,
            "confirmation_message": self.confirmation_message,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ResolutionResult":
        """从字典反序列化"""
        return cls(
            dependency_id=data["dependency_id"],
            success=data["success"],
            source=ResolutionSource(data["source"]),
            resolved_path=data.get("resolved_path"),
            requires_confirmation=data.get("requires_confirmation", False),
            confirmation_message=data.get("confirmation_message"),
            error_message=data.get("error_message"),
            metadata=data.get("metadata"),
        )
    
    @classmethod
    def create_success(
        cls,
        dependency_id: str,
        source: ResolutionSource,
        resolved_path: str,
        requires_confirmation: bool = False,
        confirmation_message: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> "ResolutionResult":
        """创建成功结果"""
        return cls(
            dependency_id=dependency_id,
            success=True,
            source=source,
            resolved_path=resolved_path,
            requires_confirmation=requires_confirmation,
            confirmation_message=confirmation_message,
            metadata=metadata,
        )
    
    @classmethod
    def create_failure(
        cls,
        dependency_id: str,
        source: ResolutionSource,
        error_message: str,
    ) -> "ResolutionResult":
        """创建失败结果"""
        return cls(
            dependency_id=dependency_id,
            success=False,
            source=source,
            error_message=error_message,
        )


__all__ = [
    "ResolutionResult",
    "ResolutionSource",
]
