# Dependency Models
"""
依赖健康检查数据模型

包含：
- DependencyItem: 依赖项数据类
- HealthReport: 健康报告数据类
- ResolutionResult: 解析结果数据类
"""

from domain.dependency.models.dependency_item import (
    DependencyItem,
    DependencyStatus,
    DependencyType,
)
from domain.dependency.models.health_report import HealthReport
from domain.dependency.models.resolution_result import (
    ResolutionResult,
    ResolutionSource,
)

__all__ = [
    "DependencyItem",
    "DependencyStatus",
    "DependencyType",
    "HealthReport",
    "ResolutionResult",
    "ResolutionSource",
]
