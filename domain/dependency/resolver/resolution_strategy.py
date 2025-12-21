# Resolution Strategy Base Class
"""
解析策略基类

职责：
- 定义解析策略的统一接口
- 支持策略链模式
"""

from abc import ABC, abstractmethod
from typing import Optional

from domain.dependency.models.dependency_item import DependencyItem
from domain.dependency.models.resolution_result import ResolutionResult


class ResolutionStrategy(ABC):
    """
    解析策略抽象基类
    
    定义依赖解析的统一接口
    """
    
    @abstractmethod
    def get_name(self) -> str:
        """获取策略名称"""
        pass
    
    @abstractmethod
    def can_resolve(self, dependency: DependencyItem) -> bool:
        """
        判断是否能够解析该依赖
        
        Args:
            dependency: 依赖项
            
        Returns:
            bool: 是否能够解析
        """
        pass
    
    @abstractmethod
    def resolve(self, dependency: DependencyItem, project_root: str) -> ResolutionResult:
        """
        尝试解析依赖
        
        Args:
            dependency: 依赖项
            project_root: 项目根目录
            
        Returns:
            ResolutionResult: 解析结果
        """
        pass
    
    @property
    def requires_confirmation(self) -> bool:
        """是否需要用户确认"""
        return False
    
    @property
    def requires_network(self) -> bool:
        """是否需要网络连接"""
        return False


__all__ = ["ResolutionStrategy"]
