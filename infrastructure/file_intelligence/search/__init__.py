# File Intelligence Search Module
"""
智能搜索模块

包含：
- file_search_service.py: 文件搜索服务门面类
- content_searcher.py: 文件内容搜索（后续实现）
- fuzzy/: 模糊匹配子模块（后续实现）
"""

from infrastructure.file_intelligence.search.file_search_service import (
    FileSearchService,
)

__all__ = [
    "FileSearchService",
]
