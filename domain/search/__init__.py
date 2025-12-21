# Domain Search Layer - Unified Search Facade
"""
领域搜索层 - 统一搜索门面

架构定位：
- 作为搜索系统的统一入口，对 LLM 工具层只暴露一个 search_project 接口
- 协调 FileSearchService（精确搜索）和 RAGService（语义搜索）
- 负责搜索结果融合和 Token 预算管理

包含：
- unified_search_service: 统一搜索门面
- search_result_merger: 搜索结果融合器
- token_budget_allocator: Token 预算分配器
- models/: 统一搜索结果数据类

设计原则：
- 消除 LLM 的搜索工具选择困惑
- 精确搜索和语义搜索并行执行，结果融合
- Token 预算管理，防止上下文溢出
"""

from domain.search.unified_search_service import UnifiedSearchService
from domain.search.search_result_merger import SearchResultMerger
from domain.search.token_budget_allocator import TokenBudgetAllocator
from domain.search.models import (
    UnifiedSearchResult,
    SearchScope,
    TokenBudgetConfig,
)


__all__ = [
    # 核心服务
    "UnifiedSearchService",
    "SearchResultMerger",
    "TokenBudgetAllocator",
    # 数据模型
    "UnifiedSearchResult",
    "SearchScope",
    "TokenBudgetConfig",
]
