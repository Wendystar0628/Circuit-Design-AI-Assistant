# Unified Search Models
"""
搜索数据模型

包含：
- 项目搜索模型：UnifiedSearchResult, SearchScope, TokenBudgetConfig
- 单文件搜索模型：InFileSearchOptions, InFileSearchResult, InFileMatch
"""

from domain.search.models.unified_search_result import (
    UnifiedSearchResult,
    ExactMatchResult,
    SemanticMatchResult,
    SearchScope,
    TokenBudgetConfig,
)
from domain.search.models.in_file_search_types import (
    InFileSearchOptions,
    InFileSearchResult,
    InFileMatch,
)


__all__ = [
    # 项目搜索模型
    "UnifiedSearchResult",
    "ExactMatchResult",
    "SemanticMatchResult",
    "SearchScope",
    "TokenBudgetConfig",
    # 单文件搜索模型
    "InFileSearchOptions",
    "InFileSearchResult",
    "InFileMatch",
]
