# File Intelligence Location Module
"""
智能定位模块

职责：
- 提供符号定位和导航功能
- 支持跳转定义、查找引用
- 多级定位策略：当前文件 → include 文件 → 整个项目
"""

from infrastructure.file_intelligence.location.location_types import (
    LocationResult,
    ReferenceResult,
    LocationScope,
)
from infrastructure.file_intelligence.location.location_service import LocationService
from infrastructure.file_intelligence.location.symbol_locator import SymbolLocator
from infrastructure.file_intelligence.location.reference_finder import ReferenceFinder

__all__ = [
    "LocationResult",
    "ReferenceResult",
    "LocationScope",
    "LocationService",
    "SymbolLocator",
    "ReferenceFinder",
]
