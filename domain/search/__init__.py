# Domain Search Layer - Unified Search Facade
"""
领域搜索层 - 统一搜索门面

架构定位：
- 项目级搜索：UnifiedSearchService 对 LLM 工具层暴露 search_project 接口
- 单文件搜索：InFileSearchService 对 FileContentLocator 暴露 search 接口
- 协调 FileSearchService（精确搜索）和 RAGService（语义搜索）
- 负责搜索结果融合和 Token 预算管理

包含：
- unified_search_service: 项目级统一搜索门面
- in_file_search_service: 单文件搜索服务（分层降级策略）
- search_result_merger: 搜索结果融合器
- token_budget_allocator: Token 预算分配器
- models/: 搜索结果数据类

设计原则：
- 消除 LLM 的搜索工具选择困惑
- 精确搜索和语义搜索并行执行，结果融合
- 单文件搜索支持分层降级（精确搜索始终可用，语义搜索按需启用）
- Token 预算管理，防止上下文溢出
"""

from domain.search.unified_search_service import UnifiedSearchService
from domain.search.in_file_search_service import InFileSearchService
from domain.search.search_result_merger import SearchResultMerger
from domain.search.token_budget_allocator import TokenBudgetAllocator
from domain.search.models import (
    UnifiedSearchResult,
    SearchScope,
    TokenBudgetConfig,
)
from domain.search.models.in_file_search_types import (
    InFileSearchOptions,
    InFileSearchResult,
    InFileMatch,
)


__all__ = [
    # 核心服务
    "UnifiedSearchService",
    "InFileSearchService",
    "SearchResultMerger",
    "TokenBudgetAllocator",
    # 项目搜索数据模型
    "UnifiedSearchResult",
    "SearchScope",
    "TokenBudgetConfig",
    # 单文件搜索数据模型
    "InFileSearchOptions",
    "InFileSearchResult",
    "InFileMatch",
]
