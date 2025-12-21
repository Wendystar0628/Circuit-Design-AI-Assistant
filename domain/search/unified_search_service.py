# Unified Search Service - Search System Facade
"""
统一搜索服务 - 搜索系统门面

架构定位：
- 作为搜索系统的统一入口
- 对 LLM 工具层只暴露一个 search_project 接口
- 协调 FileSearchService（精确搜索）和 RAGService（语义搜索）

职责：
- 接收搜索请求，根据 scope 参数决定搜索策略
- 并行调用精确搜索和语义搜索引擎
- 融合搜索结果，管理 Token 预算
- 返回结构化的统一搜索结果

被调用方：
- search_project 工具（阶段6）
- ContextRetriever（阶段3）

设计原则：
- 消除 LLM 的搜索工具选择困惑
- 精确搜索和语义搜索是互补的
- Token 预算管理，防止上下文溢出

使用示例：
    from shared.service_locator import ServiceLocator
    from shared.service_names import SVC_UNIFIED_SEARCH_SERVICE
    
    search_service = ServiceLocator.get(SVC_UNIFIED_SEARCH_SERVICE)
    
    # 统一搜索（默认全部）
    result = search_service.search("R1 10K")
    
    # 仅代码搜索
    result = search_service.search("SUBCKT", scope=SearchScope.CODE)
    
    # 仅文档搜索
    result = search_service.search("low-pass filter", scope=SearchScope.DOCS)
"""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.search.models.unified_search_result import (
    UnifiedSearchResult,
    ExactMatchResult,
    SemanticMatchResult,
    SearchScope,
    TokenBudgetConfig,
)
from domain.search.search_result_merger import SearchResultMerger
from domain.search.token_budget_allocator import TokenBudgetAllocator


class UnifiedSearchService:
    """
    统一搜索服务
    
    作为搜索系统的门面，协调精确搜索和语义搜索，
    提供统一的搜索接口给 LLM 工具层。
    """
    
    def __init__(
        self,
        token_budget_config: TokenBudgetConfig = None
    ):
        """
        初始化统一搜索服务
        
        Args:
            token_budget_config: Token 预算配置
        """
        self._token_config = token_budget_config or TokenBudgetConfig()
        self._merger = SearchResultMerger()
        self._allocator = TokenBudgetAllocator(self._token_config)
        
        # 延迟获取的服务
        self._file_search_service = None
        self._rag_service = None
        self._logger = None
    
    # ============================================================
    # 延迟获取服务
    # ============================================================
    
    @property
    def file_search_service(self):
        """延迟获取文件搜索服务"""
        if self._file_search_service is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_FILE_SEARCH_SERVICE
                self._file_search_service = ServiceLocator.get_optional(
                    SVC_FILE_SEARCH_SERVICE
                )
            except Exception:
                pass
        return self._file_search_service
    
    @property
    def rag_service(self):
        """延迟获取 RAG 服务"""
        if self._rag_service is None:
            try:
                from domain.services import rag_service
                self._rag_service = rag_service
            except Exception:
                pass
        return self._rag_service
    
    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("unified_search_service")
            except Exception:
                pass
        return self._logger
    
    # ============================================================
    # 主搜索接口
    # ============================================================
    
    def search(
        self,
        query: str,
        scope: SearchScope = SearchScope.ALL,
        max_results: int = 20,
        file_types: List[str] = None,
        token_budget: int = None
    ) -> UnifiedSearchResult:
        """
        统一搜索入口
        
        根据 scope 参数决定搜索策略：
        - ALL: 并行执行精确搜索和语义搜索
        - CODE/EXACT: 仅执行精确搜索
        - DOCS/SEMANTIC: 仅执行语义搜索
        
        Args:
            query: 搜索查询
            scope: 搜索范围
            max_results: 每种搜索的最大结果数
            file_types: 限定文件类型（仅精确搜索有效）
            token_budget: 自定义 Token 预算（覆盖默认配置）
            
        Returns:
            UnifiedSearchResult: 统一搜索结果
        """
        start_time = time.time()
        
        if not query or not query.strip():
            return UnifiedSearchResult(query=query, scope=scope)
        
        # 更新 Token 预算
        if token_budget:
            self._allocator.config.total_budget = token_budget
        
        # 根据 scope 执行搜索
        exact_results: List[ExactMatchResult] = []
        semantic_results: List[SemanticMatchResult] = []
        total_exact = 0
        total_semantic = 0
        
        if scope in (SearchScope.ALL, SearchScope.CODE, SearchScope.EXACT):
            exact_results, total_exact = self._search_exact(
                query, max_results, file_types
            )
        
        if scope in (SearchScope.ALL, SearchScope.DOCS, SearchScope.SEMANTIC):
            semantic_results, total_semantic = self._search_semantic(
                query, max_results
            )
        
        # 融合结果
        exact_results, semantic_results = self._merger.deduplicate_across_sources(
            exact_results, semantic_results
        )
        exact_results, semantic_results = self._merger.sort_by_relevance(
            exact_results, semantic_results
        )
        
        # 分配 Token 预算
        exact_results, exact_tokens = self._allocator.allocate_exact_results(
            exact_results
        )
        semantic_results, semantic_tokens = self._allocator.allocate_semantic_results(
            semantic_results
        )
        
        # 构建结果
        search_time = (time.time() - start_time) * 1000
        
        result = UnifiedSearchResult(
            query=query,
            scope=scope,
            exact_matches=exact_results,
            semantic_matches=semantic_results,
            total_exact_count=total_exact,
            total_semantic_count=total_semantic,
            exact_tokens_used=exact_tokens,
            semantic_tokens_used=semantic_tokens,
            search_time_ms=search_time,
        )
        
        if self.logger:
            self.logger.debug(
                f"统一搜索完成: query='{query}', scope={scope.value}, "
                f"exact={len(exact_results)}/{total_exact}, "
                f"semantic={len(semantic_results)}/{total_semantic}, "
                f"tokens={result.total_tokens_used}, "
                f"time={search_time:.0f}ms"
            )
        
        return result
    
    # ============================================================
    # 内部搜索方法
    # ============================================================
    
    def _search_exact(
        self,
        query: str,
        max_results: int,
        file_types: List[str] = None
    ) -> tuple:
        """
        执行精确搜索
        
        调用 FileSearchService 进行内容搜索和符号搜索。
        
        Returns:
            Tuple[List[ExactMatchResult], int]: (结果列表, 总数)
        """
        if not self.file_search_service:
            return [], 0
        
        results: List[ExactMatchResult] = []
        
        try:
            # 内容搜索
            content_results = self.file_search_service.search_by_content(
                query,
                file_types=file_types,
                max_results=max_results,
            )
            
            for r in content_results:
                for match in r.matches[:3]:  # 每个文件最多取3个匹配
                    results.append(ExactMatchResult(
                        file_path=r.relative_path,
                        file_name=r.file_name,
                        match_type="content",
                        score=r.score,
                        line_number=match.line_number,
                        line_content=match.line_content,
                        context_before=match.context_before if hasattr(match, 'context_before') else [],
                        context_after=match.context_after if hasattr(match, 'context_after') else [],
                    ))
            
            # 符号搜索（如果查询看起来像符号名）
            if self._looks_like_symbol(query):
                symbol_results = self.file_search_service.search_symbols(
                    query,
                    file_types=file_types,
                    max_results=max_results // 2,
                )
                
                for r in symbol_results:
                    symbols = r.metadata.get("symbols", [])
                    for symbol in symbols[:2]:  # 每个文件最多取2个符号
                        results.append(ExactMatchResult(
                            file_path=r.relative_path,
                            file_name=r.file_name,
                            match_type="symbol",
                            score=r.score,
                            line_number=symbol.get("line"),
                            line_content=f"{symbol.get('type')}: {symbol.get('name')}",
                            symbol_info=symbol,
                        ))
            
        except Exception as e:
            if self.logger:
                self.logger.warning(f"精确搜索失败: {e}")
        
        # 去重
        results = self._merger.merge_exact_results(results)
        total = len(results)
        
        return results[:max_results], total
    
    def _search_semantic(
        self,
        query: str,
        max_results: int
    ) -> tuple:
        """
        执行语义搜索
        
        调用 RAGService 进行向量检索。
        
        Returns:
            Tuple[List[SemanticMatchResult], int]: (结果列表, 总数)
        """
        if not self.rag_service:
            return [], 0
        
        results: List[SemanticMatchResult] = []
        
        try:
            # 检查索引是否就绪
            if not self.rag_service.is_index_ready():
                return [], 0
            
            # 执行检索
            rag_results = self.rag_service.retrieve(
                query,
                top_k=max_results,
            )
            
            for r in rag_results:
                results.append(SemanticMatchResult(
                    content=r.content,
                    source=r.source,
                    score=r.score,
                    chunk_id=r.chunk_id,
                    metadata=r.metadata,
                ))
            
        except Exception as e:
            if self.logger:
                self.logger.warning(f"语义搜索失败: {e}")
        
        # 去重
        results = self._merger.merge_semantic_results(results)
        total = len(results)
        
        return results[:max_results], total
    
    def _looks_like_symbol(self, query: str) -> bool:
        """
        判断查询是否看起来像符号名
        
        符号名特征：
        - 不包含空格
        - 以字母或下划线开头
        - 只包含字母、数字、下划线
        """
        if not query or " " in query:
            return False
        
        if not (query[0].isalpha() or query[0] == "_"):
            return False
        
        return all(c.isalnum() or c == "_" for c in query)
    
    # ============================================================
    # 便捷方法
    # ============================================================
    
    def search_code(
        self,
        query: str,
        file_types: List[str] = None,
        max_results: int = 20
    ) -> UnifiedSearchResult:
        """
        搜索代码文件（仅精确搜索）
        
        Args:
            query: 搜索查询
            file_types: 限定文件类型
            max_results: 最大结果数
            
        Returns:
            UnifiedSearchResult: 搜索结果
        """
        return self.search(
            query,
            scope=SearchScope.CODE,
            max_results=max_results,
            file_types=file_types,
        )
    
    def search_docs(
        self,
        query: str,
        max_results: int = 20
    ) -> UnifiedSearchResult:
        """
        搜索文档（仅语义搜索）
        
        Args:
            query: 搜索查询
            max_results: 最大结果数
            
        Returns:
            UnifiedSearchResult: 搜索结果
        """
        return self.search(
            query,
            scope=SearchScope.DOCS,
            max_results=max_results,
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取搜索服务统计信息
        
        Returns:
            Dict: 统计信息
        """
        stats = {
            "token_budget": {
                "total": self._token_config.total_budget,
                "exact_ratio": self._token_config.exact_ratio,
                "semantic_ratio": self._token_config.semantic_ratio,
            },
            "file_search_available": self.file_search_service is not None,
            "rag_available": self.rag_service is not None,
        }
        
        if self.file_search_service:
            stats["file_index"] = self.file_search_service.get_index_stats()
        
        if self.rag_service:
            stats["rag_index"] = self.rag_service.get_index_status()
        
        return stats


# ============================================================
# 模块导出
# ============================================================

__all__ = ["UnifiedSearchService"]
