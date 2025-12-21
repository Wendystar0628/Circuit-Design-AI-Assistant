# Local Resolver
"""
本地路径解析器

职责：
- 在项目内搜索缺失的依赖文件
- 在全局库目录搜索
- 自动处理，无需用户确认
"""

from pathlib import Path
from typing import List, Optional

from domain.dependency.models.dependency_item import DependencyItem
from domain.dependency.models.resolution_result import (
    ResolutionResult,
    ResolutionSource,
)
from domain.dependency.resolver.resolution_strategy import ResolutionStrategy


class LocalResolver(ResolutionStrategy):
    """
    本地路径解析器
    
    在本地文件系统中搜索缺失的依赖
    """
    
    # 项目内常见的库目录
    PROJECT_LIB_DIRS = [
        "subcircuits",
        "models",
        "lib",
        "libraries",
        "parameters",
        "spice_models",
    ]
    
    # 全局库目录（相对于用户目录）
    GLOBAL_LIB_DIRS = [
        ".circuit_design_ai/spice_models",
        ".circuit_design_ai/libraries",
    ]
    
    def __init__(self):
        """初始化本地解析器"""
        self._home_dir = Path.home()
    
    def get_name(self) -> str:
        return "local_resolver"
    
    def can_resolve(self, dependency: DependencyItem) -> bool:
        """本地解析器总是可以尝试"""
        return True
    
    def resolve(self, dependency: DependencyItem, project_root: str) -> ResolutionResult:
        """
        尝试在本地解析依赖
        
        搜索顺序：
        1. 项目内常见库目录
        2. 全局库目录
        """
        project_path = Path(project_root)
        filename = Path(dependency.raw_path).name
        
        # 策略1：在项目内搜索
        for lib_dir in self.PROJECT_LIB_DIRS:
            search_path = project_path / lib_dir / filename
            if search_path.exists():
                return ResolutionResult.create_success(
                    dependency_id=dependency.id,
                    source=ResolutionSource.PROJECT_LOCAL,
                    resolved_path=str(search_path.resolve()),
                    requires_confirmation=False,
                )
        
        # 策略2：在全局库目录搜索
        for lib_dir in self.GLOBAL_LIB_DIRS:
            search_path = self._home_dir / lib_dir / filename
            if search_path.exists():
                return ResolutionResult.create_success(
                    dependency_id=dependency.id,
                    source=ResolutionSource.GLOBAL_LIBRARY,
                    resolved_path=str(search_path.resolve()),
                    requires_confirmation=True,  # 全局库需要确认
                    confirmation_message=f"在全局库中找到 {filename}，是否使用？",
                )
        
        # 未找到
        return ResolutionResult.create_failure(
            dependency_id=dependency.id,
            source=ResolutionSource.PROJECT_LOCAL,
            error_message=f"在本地未找到 {filename}",
        )
    
    @property
    def requires_confirmation(self) -> bool:
        """项目内解析不需要确认，全局库需要"""
        return False  # 由具体结果决定
    
    @property
    def requires_network(self) -> bool:
        return False


__all__ = ["LocalResolver"]
