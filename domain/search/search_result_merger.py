# Search Result Merger
"""
搜索结果融合器

职责：
- 合并精确搜索和语义搜索的结果
- 去重（同一文件同一位置的结果合并）
- 按相关性排序（精确匹配优先，语义匹配次之）
- 结果标注来源

设计原则：
- 精确匹配优先（通常更有价值）
- 保持两种结果的独立分组（让 LLM 自己判断）
- 去重基于文件路径 + 行号
"""

from typing import Dict, List, Set, Tuple

from domain.search.models.unified_search_result import (
    ExactMatchResult,
    SemanticMatchResult,
)


class SearchResultMerger:
    """
    搜索结果融合器
    
    负责合并、去重、排序来自不同搜索引擎的结果。
    """
    
    def merge_exact_results(
        self,
        results: List[ExactMatchResult]
    ) -> List[ExactMatchResult]:
        """
        合并精确搜索结果（去重）
        
        去重规则：
        - 同一文件 + 同一行号 = 重复
        - 保留分数最高的结果
        
        Args:
            results: 精确匹配结果列表
            
        Returns:
            List[ExactMatchResult]: 去重后的结果
        """
        if not results:
            return []
        
        # 使用 (file_path, line_number) 作为去重键
        seen: Dict[Tuple[str, int], ExactMatchResult] = {}
        
        for result in results:
            key = (result.file_path, result.line_number or 0)
            
            if key not in seen:
                seen[key] = result
            elif result.score > seen[key].score:
                # 保留分数更高的结果
                seen[key] = result
        
        # 按分数排序
        merged = list(seen.values())
        merged.sort(key=lambda r: r.score, reverse=True)
        
        return merged
    
    def merge_semantic_results(
        self,
        results: List[SemanticMatchResult]
    ) -> List[SemanticMatchResult]:
        """
        合并语义搜索结果（去重）
        
        去重规则：
        - 同一 chunk_id = 重复
        - 同一 source + 内容相似度 > 0.9 = 重复
        - 保留分数最高的结果
        
        Args:
            results: 语义匹配结果列表
            
        Returns:
            List[SemanticMatchResult]: 去重后的结果
        """
        if not results:
            return []
        
        # 使用 chunk_id 或 source 作为去重键
        seen: Dict[str, SemanticMatchResult] = {}
        
        for result in results:
            # 优先使用 chunk_id，否则使用 source
            key = result.chunk_id if result.chunk_id else result.source
            
            if key not in seen:
                seen[key] = result
            elif result.score > seen[key].score:
                # 保留分数更高的结果
                seen[key] = result
        
        # 按分数排序
        merged = list(seen.values())
        merged.sort(key=lambda r: r.score, reverse=True)
        
        return merged
    
    def deduplicate_across_sources(
        self,
        exact_results: List[ExactMatchResult],
        semantic_results: List[SemanticMatchResult]
    ) -> Tuple[List[ExactMatchResult], List[SemanticMatchResult]]:
        """
        跨来源去重
        
        如果精确搜索和语义搜索返回了同一文件的结果，
        在语义结果中移除该文件（精确匹配优先）。
        
        Args:
            exact_results: 精确匹配结果
            semantic_results: 语义匹配结果
            
        Returns:
            Tuple: (精确结果, 去重后的语义结果)
        """
        if not exact_results or not semantic_results:
            return exact_results, semantic_results
        
        # 收集精确匹配的文件路径
        exact_files: Set[str] = {r.file_path for r in exact_results}
        
        # 过滤语义结果中与精确匹配重复的文件
        filtered_semantic = [
            r for r in semantic_results
            if r.source not in exact_files
        ]
        
        return exact_results, filtered_semantic
    
    def sort_by_relevance(
        self,
        exact_results: List[ExactMatchResult],
        semantic_results: List[SemanticMatchResult]
    ) -> Tuple[List[ExactMatchResult], List[SemanticMatchResult]]:
        """
        按相关性排序
        
        精确匹配内部排序：
        1. 完全匹配 > 前缀匹配 > 包含匹配
        2. 同类型按分数排序
        
        语义匹配内部排序：
        1. 按相关性分数排序
        
        Args:
            exact_results: 精确匹配结果
            semantic_results: 语义匹配结果
            
        Returns:
            Tuple: (排序后的精确结果, 排序后的语义结果)
        """
        # 精确结果排序
        sorted_exact = sorted(
            exact_results,
            key=lambda r: (
                # 匹配类型优先级：symbol > content > name
                {"symbol": 3, "content": 2, "name": 1}.get(r.match_type, 0),
                r.score
            ),
            reverse=True
        )
        
        # 语义结果排序
        sorted_semantic = sorted(
            semantic_results,
            key=lambda r: r.score,
            reverse=True
        )
        
        return sorted_exact, sorted_semantic


# ============================================================
# 模块导出
# ============================================================

__all__ = ["SearchResultMerger"]
