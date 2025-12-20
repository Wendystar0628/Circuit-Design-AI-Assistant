# File Intelligence Search Module
"""
智能搜索模块

包含：
- file_search_service.py: 文件搜索服务门面类
- content_searcher.py: 文件内容搜索
- fuzzy/: 模糊匹配子模块
"""

from infrastructure.file_intelligence.search.content_searcher import (
    ContentSearcher,
    ContentSearchOptions,
)
from infrastructure.file_intelligence.search.file_search_service import (
    FileSearchService,
)
from infrastructure.file_intelligence.search.fuzzy import (
    FuzzyMatcher,
    MatchOptions,
    MatchResult,
)

__all__ = [
    "FileSearchService",
    "ContentSearcher",
    "ContentSearchOptions",
    "FuzzyMatcher",
    "MatchOptions",
    "MatchResult",
]
