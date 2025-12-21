# In-File Search Service - Single File Search with Graceful Degradation
"""
单文件搜索服务 - 分层降级策略

架构定位：
- 在单个文件内执行搜索，支持分层降级策略
- 被 FileContentLocator（阶段六）调用
- 协调 FileSearchService（精确搜索）和 RAGService（语义搜索）

核心设计：分层降级策略
- 精确搜索：始终执行（基础能力）
- 语义搜索：仅当文件已索引时执行（增强能力）
- 用户不会因为索引未就绪而完全无法定位内容

职责边界：
- 单文件搜索：在指定文件内搜索内容
- 不负责项目级搜索（由 UnifiedSearchService 负责）

被调用方：
- FileContentLocator（阶段六）：语义定位读取

设计原则：
- 精确搜索是基础能力，始终可用
- 语义搜索是增强能力，按需启用
- 结果融合去重，按分数排序

使用示例：
    from shared.service_locator import ServiceLocator
    from shared.service_names import SVC_IN_FILE_SEARCH_SERVICE
    
    search_service = ServiceLocator.get(SVC_IN_FILE_SEARCH_SERVICE)
    
    # 单文件搜索
    result = search_service.search("amplifier.cir", "gain stage")
    
    # 检查语义搜索是否可用
    if result.semantic_available:
        print("语义搜索已启用")
    else:
        print("仅使用精确搜索（文件未索引）")
"""

import time
from typing import List, Optional

from domain.search.models.in_file_search_types import (
    InFileSearchOptions,
    InFileSearchResult,
    InFileMatch,
)


class InFileSearchService:
    """
    单文件搜索服务
    
    实现分层降级策略：
    - 精确搜索：始终执行
    - 语义搜索：仅当文件已索引时执行
    """
    
    def __init__(self):
        """初始化单文件搜索服务"""
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
                self._logger = get_logger("in_file_search_service")
            except Exception:
                pass
        return self._logger
    
    # ============================================================
    # 主搜索接口
    # ============================================================
    
    def search(
        self,
        file_path: str,
        query: str,
        options: InFileSearchOptions = None
    ) -> InFileSearchResult:
        """
        在单个文件内搜索
        
        执行分层降级策略：
        1. 精确搜索：始终执行
        2. 语义搜索：仅当文件已索引时执行
        
        Args:
            file_path: 文件路径（相对路径）
            query: 搜索查询
            options: 搜索选项
            
        Returns:
            InFileSearchResult: 搜索结果
        """
        start_time = time.time()
        options = options or InFileSearchOptions()
        
        if not query or not query.strip():
            return InFileSearchResult(
                file_path=file_path,
                query=query,
                semantic_available=False,
            )
        
        exact_matches: List[InFileMatch] = []
        semantic_matches: List[InFileMatch] = []
        semantic_available = False
        
        # 1. 精确搜索（始终执行）
        if options.include_exact:
            exact_matches = self._search_exact(file_path, query, options)
        
        # 2. 检查文件是否已索引
        if options.include_semantic:
            semantic_available = self.is_file_indexed(file_path)
            
            # 3. 语义搜索（仅当文件已索引时执行）
            if semantic_available:
                semantic_matches = self._search_semantic(file_path, query, options)
        
        # 4. 融合结果
        merged_matches = self._merge_matches(
            exact_matches, semantic_matches, options
        )
        
        # 5. 构建结果
        search_time = (time.time() - start_time) * 1000
        
        result = InFileSearchResult(
            file_path=file_path,
            query=query,
            matches=merged_matches,
            search_time_ms=search_time,
            exact_count=len(exact_matches),
            semantic_count=len(semantic_matches),
            semantic_available=semantic_available,
        )
        
        if self.logger:
            self.logger.debug(
                f"单文件搜索完成: file='{file_path}', query='{query}', "
                f"exact={len(exact_matches)}, semantic={len(semantic_matches)}, "
                f"semantic_available={semantic_available}, "
                f"time={search_time:.0f}ms"
            )
        
        return result
    
    def is_file_indexed(self, file_path: str) -> bool:
        """
        检查文件是否已被索引
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 文件是否已被索引
        """
        if not self.rag_service:
            return False
        
        try:
            return self.rag_service.has_indexed_file(file_path)
        except Exception as e:
            if self.logger:
                self.logger.warning(f"检查文件索引状态失败: {e}")
            return False
    
    # ============================================================
    # 内部搜索方法
    # ============================================================
    
    def _search_exact(
        self,
        file_path: str,
        query: str,
        options: InFileSearchOptions
    ) -> List[InFileMatch]:
        """
        执行精确搜索
        
        调用 FileSearchService 在单个文件内搜索。
        
        Returns:
            List[InFileMatch]: 匹配结果列表
        """
        if not self.file_search_service:
            return []
        
        results: List[InFileMatch] = []
        
        try:
            # TODO: 调用 FileSearchService.search_in_file()
            # 当前返回空列表，完整实现在阶段五
            pass
            
        except Exception as e:
            if self.logger:
                self.logger.warning(f"精确搜索失败: {e}")
        
        return results
    
    def _search_semantic(
        self,
        file_path: str,
        query: str,
        options: InFileSearchOptions
    ) -> List[InFileMatch]:
        """
        执行语义搜索
        
        调用 RAGService 在单个文件的已索引分块中搜索。
        
        Returns:
            List[InFileMatch]: 匹配结果列表
        """
        if not self.rag_service:
            return []
        
        results: List[InFileMatch] = []
        
        try:
            rag_results = self.rag_service.retrieve_from_file(
                file_path,
                query,
                top_k=options.max_results,
            )
            
            for r in rag_results:
                if r.score >= options.min_score:
                    results.append(InFileMatch(
                        start_line=r.start_line,
                        end_line=r.end_line,
                        score=r.score,
                        match_type="semantic",
                        matched_text=r.content,
                    ))
            
        except Exception as e:
            if self.logger:
                self.logger.warning(f"语义搜索失败: {e}")
        
        return results
    
    def _merge_matches(
        self,
        exact_matches: List[InFileMatch],
        semantic_matches: List[InFileMatch],
        options: InFileSearchOptions
    ) -> List[InFileMatch]:
        """
        融合精确搜索和语义搜索的结果
        
        - 去重：同一行号范围的结果视为重复
        - 排序：按分数降序
        - 合并：重叠的行号范围合并
        
        Returns:
            List[InFileMatch]: 融合后的结果列表
        """
        all_matches = exact_matches + semantic_matches
        
        if not all_matches:
            return []
        
        # 按分数降序排序
        all_matches.sort(key=lambda m: m.score, reverse=True)
        
        # 去重和合并重叠范围
        merged: List[InFileMatch] = []
        
        for match in all_matches:
            # 检查是否与已有结果重叠
            overlapped = False
            for i, existing in enumerate(merged):
                if self._ranges_overlap(
                    match.start_line, match.end_line,
                    existing.start_line, existing.end_line
                ):
                    # 合并范围
                    merged[i] = self._merge_two_matches(existing, match)
                    overlapped = True
                    break
            
            if not overlapped:
                merged.append(match)
        
        # 限制结果数量
        return merged[:options.max_results]
    
    def _ranges_overlap(
        self,
        start1: int, end1: int,
        start2: int, end2: int,
        gap: int = 3
    ) -> bool:
        """
        检查两个行号范围是否重叠或相邻
        
        Args:
            gap: 允许的间隔行数（默认 3 行）
        """
        return not (end1 + gap < start2 or end2 + gap < start1)
    
    def _merge_two_matches(
        self,
        match1: InFileMatch,
        match2: InFileMatch
    ) -> InFileMatch:
        """
        合并两个匹配结果
        
        - 行号范围取并集
        - 分数取最高值
        - 匹配类型标记为 "merged"
        """
        return InFileMatch(
            start_line=min(match1.start_line, match2.start_line),
            end_line=max(match1.end_line, match2.end_line),
            score=max(match1.score, match2.score),
            match_type="merged",
            matched_text=match1.matched_text or match2.matched_text,
            context_before=match1.context_before or match2.context_before,
            context_after=match1.context_after or match2.context_after,
        )


# ============================================================
# 模块导出
# ============================================================

__all__ = ["InFileSearchService"]
