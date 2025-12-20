# Fuzzy Matcher - Unified Fuzzy Matching Interface
"""
模糊匹配器门面类

职责：
- 模糊匹配子模块的统一入口
- 组合调用各子模块完成匹配
- 提供便捷的匹配方法

被调用方：file_search_service.py, patch_strategies.py, location_service.py
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from infrastructure.file_intelligence.search.fuzzy.match_scorer import (
    MatchScorer,
    ScoreResult,
    ScoringWeights,
)
from infrastructure.file_intelligence.search.fuzzy.similarity_algorithms import (
    SimilarityAlgorithms,
)
from infrastructure.file_intelligence.search.fuzzy.text_normalizer import (
    NormalizeOptions,
    TextNormalizer,
)


@dataclass
class MatchOptions:
    """匹配选项"""
    threshold: float = 0.6
    algorithm: str = "levenshtein"  # levenshtein/jaro_winkler/partial/token_sort/token_set
    normalize_options: Optional[NormalizeOptions] = None
    scoring_weights: Optional[ScoringWeights] = None
    
    def __post_init__(self):
        if self.normalize_options is None:
            self.normalize_options = NormalizeOptions()
        if self.scoring_weights is None:
            self.scoring_weights = ScoringWeights()


@dataclass
class MatchResult:
    """匹配结果"""
    target: str
    score: float
    matched_positions: List[int] = field(default_factory=list)
    match_type: str = "none"
    normalized_query: str = ""
    normalized_target: str = ""


class FuzzyMatcher:
    """
    模糊匹配器门面类
    
    提供统一的模糊匹配接口，组合调用各子模块完成匹配。
    """
    
    def __init__(self, options: Optional[MatchOptions] = None):
        """
        初始化模糊匹配器
        
        Args:
            options: 默认匹配选项
        """
        self._default_options = options or MatchOptions()
    
    def match(
        self,
        query: str,
        target: str,
        options: Optional[MatchOptions] = None
    ) -> MatchResult:
        """
        计算单个目标的匹配度
        
        Args:
            query: 查询字符串
            target: 目标字符串
            options: 匹配选项（可选，使用默认选项）
            
        Returns:
            MatchResult: 匹配结果
        """
        opts = options or self._default_options
        
        # 文本规范化
        normalized_query = TextNormalizer.normalize_for_matching(
            query, opts.normalize_options
        )
        normalized_target = TextNormalizer.normalize_for_matching(
            target, opts.normalize_options
        )
        
        # 计算综合评分
        score_result = MatchScorer.calculate_composite_score(
            normalized_query,
            normalized_target,
            opts.scoring_weights
        )
        
        # 使用指定算法计算相似度作为参考
        algorithm_fn = SimilarityAlgorithms.get_algorithm(opts.algorithm)
        algorithm_score = algorithm_fn(normalized_query, normalized_target)
        
        # 综合两种分数
        final_score = max(score_result.score, algorithm_score)
        
        return MatchResult(
            target=target,
            score=final_score,
            matched_positions=score_result.matched_positions,
            match_type=score_result.match_type,
            normalized_query=normalized_query,
            normalized_target=normalized_target,
        )
    
    def is_match(
        self,
        query: str,
        target: str,
        threshold: Optional[float] = None,
        options: Optional[MatchOptions] = None
    ) -> bool:
        """
        判断是否匹配（布尔结果）
        
        Args:
            query: 查询字符串
            target: 目标字符串
            threshold: 匹配阈值（可选）
            options: 匹配选项（可选）
            
        Returns:
            bool: 是否匹配
        """
        opts = options or self._default_options
        thresh = threshold if threshold is not None else opts.threshold
        
        result = self.match(query, target, opts)
        return result.score >= thresh
    
    def find_best_matches(
        self,
        query: str,
        candidates: List[str],
        top_k: int = 10,
        options: Optional[MatchOptions] = None
    ) -> List[MatchResult]:
        """
        从候选列表中找出最佳匹配
        
        Args:
            query: 查询字符串
            candidates: 候选字符串列表
            top_k: 返回前 k 个结果
            options: 匹配选项（可选）
            
        Returns:
            List[MatchResult]: 按分数降序排列的匹配结果
        """
        opts = options or self._default_options
        
        results = []
        for candidate in candidates:
            result = self.match(query, candidate, opts)
            if result.score >= opts.threshold:
                results.append(result)
        
        # 按分数降序排序
        results.sort(key=lambda r: r.score, reverse=True)
        
        return results[:top_k]

    def find_similar_content(
        self,
        query: str,
        content: str,
        threshold: float = 0.85,
        context_lines: int = 2
    ) -> List[Dict]:
        """
        在长文本中查找相似内容块
        
        用于 patch_file 的模糊匹配定位。
        
        Args:
            query: 查询内容（要查找的代码块）
            content: 目标内容（文件内容）
            threshold: 匹配阈值
            context_lines: 上下文行数
            
        Returns:
            List[Dict]: 匹配结果列表，每个包含：
                - start_line: 起始行号
                - end_line: 结束行号
                - matched_content: 匹配到的内容
                - score: 匹配分数
        """
        query_lines = query.strip().split('\n')
        content_lines = content.split('\n')
        
        if not query_lines or not content_lines:
            return []
        
        query_line_count = len(query_lines)
        results = []
        
        # 滑动窗口搜索
        for i in range(len(content_lines) - query_line_count + 1):
            window = content_lines[i:i + query_line_count]
            window_text = '\n'.join(window)
            query_text = '\n'.join(query_lines)
            
            # 规范化后比较
            normalized_query = TextNormalizer.normalize_for_matching(
                query_text,
                NormalizeOptions(ignore_whitespace=True, ignore_empty_lines=False)
            )
            normalized_window = TextNormalizer.normalize_for_matching(
                window_text,
                NormalizeOptions(ignore_whitespace=True, ignore_empty_lines=False)
            )
            
            # 计算相似度
            score = SimilarityAlgorithms.partial_ratio(
                normalized_query, normalized_window
            )
            
            if score >= threshold:
                results.append({
                    'start_line': i + 1,  # 1-based
                    'end_line': i + query_line_count,
                    'matched_content': window_text,
                    'score': score,
                })
        
        # 按分数降序排序
        results.sort(key=lambda r: r['score'], reverse=True)
        
        # 去除重叠的结果（保留分数最高的）
        filtered_results = []
        used_lines = set()
        
        for result in results:
            lines_range = set(range(result['start_line'], result['end_line'] + 1))
            if not lines_range & used_lines:
                filtered_results.append(result)
                used_lines.update(lines_range)
        
        return filtered_results
    
    def quick_filter(
        self,
        query: str,
        candidates: List[str],
        threshold: float = 0.3
    ) -> List[str]:
        """
        快速过滤候选列表
        
        使用简单算法快速筛选可能匹配的候选，用于大列表的预过滤。
        
        Args:
            query: 查询字符串
            candidates: 候选字符串列表
            threshold: 过滤阈值（较低）
            
        Returns:
            List[str]: 可能匹配的候选列表
        """
        query_lower = query.lower()
        query_chars = set(query_lower)
        
        filtered = []
        for candidate in candidates:
            candidate_lower = candidate.lower()
            
            # 快速检查：查询字符是否都在候选中
            if query_chars <= set(candidate_lower):
                filtered.append(candidate)
                continue
            
            # 子序列检查
            query_idx = 0
            for char in candidate_lower:
                if query_idx < len(query_lower) and char == query_lower[query_idx]:
                    query_idx += 1
            
            if query_idx == len(query_lower):
                filtered.append(candidate)
                continue
            
            # 简单相似度检查
            if SimilarityAlgorithms.jaro_winkler_ratio(query_lower, candidate_lower) >= threshold:
                filtered.append(candidate)
        
        return filtered


# ============================================================
# 便捷函数
# ============================================================

# 全局默认匹配器实例
_default_matcher: Optional[FuzzyMatcher] = None


def get_default_matcher() -> FuzzyMatcher:
    """获取默认匹配器实例"""
    global _default_matcher
    if _default_matcher is None:
        _default_matcher = FuzzyMatcher()
    return _default_matcher


def fuzzy_match(query: str, target: str, threshold: float = 0.6) -> bool:
    """
    便捷函数：判断是否模糊匹配
    
    Args:
        query: 查询字符串
        target: 目标字符串
        threshold: 匹配阈值
        
    Returns:
        bool: 是否匹配
    """
    return get_default_matcher().is_match(query, target, threshold)


def find_best_match(query: str, candidates: List[str]) -> Optional[str]:
    """
    便捷函数：找出最佳匹配
    
    Args:
        query: 查询字符串
        candidates: 候选列表
        
    Returns:
        Optional[str]: 最佳匹配，无匹配返回 None
    """
    results = get_default_matcher().find_best_matches(query, candidates, top_k=1)
    return results[0].target if results else None


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    'FuzzyMatcher',
    'MatchOptions',
    'MatchResult',
    'get_default_matcher',
    'fuzzy_match',
    'find_best_match',
]
