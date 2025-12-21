# Unified Search Models
"""
统一搜索数据模型

包含：
- UnifiedSearchResult: 统一搜索结果
- SearchScope: 搜索范围枚举
- TokenBudgetConfig: Token 预算配置
"""

from domain.search.models.unified_search_result import (
    UnifiedSearchResult,
    ExactMatchResult,
    SemanticMatchResult,
    SearchScope,
    TokenBudgetConfig,
)


__all__ = [
    "UnifiedSearchResult",
    "ExactMatchResult",
    "SemanticMatchResult",
    "SearchScope",
    "TokenBudgetConfig",
]
