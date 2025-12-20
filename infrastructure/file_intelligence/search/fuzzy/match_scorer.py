# Match Scorer - Fuzzy Match Scoring Strategies
"""
匹配评分器

职责：
- 实现多种匹配评分策略
- 计算综合匹配分数
- 提供匹配位置信息（用于高亮显示）

被调用方：fuzzy_matcher.py
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from infrastructure.file_intelligence.search.fuzzy.similarity_algorithms import (
    SimilarityAlgorithms,
)


@dataclass
class ScoringWeights:
    """评分权重配置"""
    subsequence_weight: float = 0.3
    word_boundary_weight: float = 0.3
    continuous_weight: float = 0.2
    similarity_weight: float = 0.2
    
    def __post_init__(self):
        # 确保权重和为 1.0
        total = (
            self.subsequence_weight +
            self.word_boundary_weight +
            self.continuous_weight +
            self.similarity_weight
        )
        if abs(total - 1.0) > 0.001:
            # 归一化
            self.subsequence_weight /= total
            self.word_boundary_weight /= total
            self.continuous_weight /= total
            self.similarity_weight /= total


@dataclass
class ScoreResult:
    """评分结果"""
    score: float
    matched_positions: List[int] = field(default_factory=list)
    match_type: str = "none"  # exact/prefix/subsequence/boundary/partial


class MatchScorer:
    """
    匹配评分器
    
    实现多种匹配评分策略，计算综合匹配分数。
    """
    
    # 单词边界分割模式
    WORD_BOUNDARY_PATTERN = re.compile(
        r'(?<=[a-z])(?=[A-Z])|'  # camelCase
        r'(?<=[A-Z])(?=[A-Z][a-z])|'  # XMLParser
        r'[_\-\s]+'  # 下划线、连字符、空格
    )
    
    @staticmethod
    def score_exact_match(query: str, target: str) -> ScoreResult:
        """
        精确匹配评分
        
        Args:
            query: 查询字符串
            target: 目标字符串
            
        Returns:
            ScoreResult: 评分结果
        """
        query_lower = query.lower()
        target_lower = target.lower()
        
        if query_lower == target_lower:
            return ScoreResult(
                score=1.0,
                matched_positions=list(range(len(target))),
                match_type="exact"
            )
        return ScoreResult(score=0.0, match_type="none")
    
    @staticmethod
    def score_prefix_match(query: str, target: str) -> ScoreResult:
        """
        前缀匹配评分
        
        Args:
            query: 查询字符串
            target: 目标字符串
            
        Returns:
            ScoreResult: 评分结果
        """
        query_lower = query.lower()
        target_lower = target.lower()
        
        if target_lower.startswith(query_lower):
            # 前缀匹配分数：查询长度 / 目标长度
            score = len(query) / len(target) if target else 0.0
            # 前缀匹配给予额外加成
            score = min(1.0, score + 0.3)
            return ScoreResult(
                score=score,
                matched_positions=list(range(len(query))),
                match_type="prefix"
            )
        return ScoreResult(score=0.0, match_type="none")
    
    @staticmethod
    def score_subsequence_match(query: str, target: str) -> ScoreResult:
        """
        子序列匹配评分
        
        检查 query 是否为 target 的子序列（如 'fm' 匹配 'file_manager'）。
        
        Args:
            query: 查询字符串
            target: 目标字符串
            
        Returns:
            ScoreResult: 评分结果
        """
        query_lower = query.lower()
        target_lower = target.lower()
        
        if not query_lower:
            return ScoreResult(score=0.0, match_type="none")
        
        positions = []
        query_idx = 0
        
        for target_idx, char in enumerate(target_lower):
            if query_idx < len(query_lower) and char == query_lower[query_idx]:
                positions.append(target_idx)
                query_idx += 1
        
        if query_idx == len(query_lower):
            # 计算分数：考虑匹配紧凑度
            if len(positions) > 1:
                # 匹配跨度
                span = positions[-1] - positions[0] + 1
                # 紧凑度：匹配字符数 / 跨度
                compactness = len(positions) / span
                # 覆盖率：匹配字符数 / 目标长度
                coverage = len(positions) / len(target)
                score = 0.5 * compactness + 0.5 * coverage
            else:
                score = 1.0 / len(target) if target else 0.0
            
            return ScoreResult(
                score=min(1.0, score),
                matched_positions=positions,
                match_type="subsequence"
            )
        
        return ScoreResult(score=0.0, match_type="none")
    
    @staticmethod
    def score_word_boundary_match(query: str, target: str) -> ScoreResult:
        """
        单词边界匹配评分
        
        检查 query 是否匹配 target 中各单词的首字母。
        如 'fs' 匹配 'FileSearch'，'fm' 匹配 'file_manager'。
        
        Args:
            query: 查询字符串
            target: 目标字符串
            
        Returns:
            ScoreResult: 评分结果
        """
        query_lower = query.lower()
        
        # 分割目标为单词
        words = MatchScorer.WORD_BOUNDARY_PATTERN.split(target)
        words = [w for w in words if w]
        
        if not words or not query_lower:
            return ScoreResult(score=0.0, match_type="none")
        
        # 获取每个单词的首字母及其在原字符串中的位置
        initials = []
        positions = []
        current_pos = 0
        
        for word in words:
            # 找到单词在原字符串中的位置
            word_pos = target.lower().find(word.lower(), current_pos)
            if word_pos >= 0:
                initials.append(word[0].lower())
                positions.append(word_pos)
                current_pos = word_pos + len(word)
        
        # 检查 query 是否匹配首字母序列
        initials_str = ''.join(initials)
        
        if query_lower == initials_str:
            # 完全匹配首字母
            return ScoreResult(
                score=0.9,
                matched_positions=positions,
                match_type="boundary"
            )
        elif initials_str.startswith(query_lower):
            # 部分匹配首字母
            score = len(query_lower) / len(initials_str) * 0.8
            return ScoreResult(
                score=score,
                matched_positions=positions[:len(query_lower)],
                match_type="boundary"
            )
        
        return ScoreResult(score=0.0, match_type="none")
    
    @staticmethod
    def score_continuous_match(query: str, target: str) -> ScoreResult:
        """
        连续字符匹配评分
        
        查找 query 在 target 中的最长连续匹配。
        
        Args:
            query: 查询字符串
            target: 目标字符串
            
        Returns:
            ScoreResult: 评分结果
        """
        query_lower = query.lower()
        target_lower = target.lower()
        
        if not query_lower or not target_lower:
            return ScoreResult(score=0.0, match_type="none")
        
        # 查找 query 在 target 中的位置
        pos = target_lower.find(query_lower)
        if pos >= 0:
            # 完全包含
            score = len(query) / len(target)
            # 位置加成：越靠前分数越高
            position_bonus = 1.0 - (pos / len(target)) * 0.2
            return ScoreResult(
                score=min(1.0, score * position_bonus + 0.3),
                matched_positions=list(range(pos, pos + len(query))),
                match_type="continuous"
            )
        
        return ScoreResult(score=0.0, match_type="none")
    
    @staticmethod
    def calculate_composite_score(
        query: str,
        target: str,
        weights: Optional[ScoringWeights] = None
    ) -> ScoreResult:
        """
        综合评分
        
        组合多种评分策略，计算加权综合分数。
        
        Args:
            query: 查询字符串
            target: 目标字符串
            weights: 评分权重配置
            
        Returns:
            ScoreResult: 评分结果
        """
        if weights is None:
            weights = ScoringWeights()
        
        # 精确匹配优先
        exact_result = MatchScorer.score_exact_match(query, target)
        if exact_result.score == 1.0:
            return exact_result
        
        # 前缀匹配次优先
        prefix_result = MatchScorer.score_prefix_match(query, target)
        if prefix_result.score > 0.8:
            return prefix_result
        
        # 计算各项分数
        subsequence_result = MatchScorer.score_subsequence_match(query, target)
        boundary_result = MatchScorer.score_word_boundary_match(query, target)
        continuous_result = MatchScorer.score_continuous_match(query, target)
        similarity_score = SimilarityAlgorithms.levenshtein_ratio(query, target)
        
        # 加权计算
        composite_score = (
            subsequence_result.score * weights.subsequence_weight +
            boundary_result.score * weights.word_boundary_weight +
            continuous_result.score * weights.continuous_weight +
            similarity_score * weights.similarity_weight
        )
        
        # 选择最佳匹配类型和位置
        best_result = max(
            [subsequence_result, boundary_result, continuous_result, prefix_result],
            key=lambda r: r.score
        )
        
        return ScoreResult(
            score=min(1.0, composite_score),
            matched_positions=best_result.matched_positions,
            match_type=best_result.match_type if best_result.score > 0 else "partial"
        )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    'MatchScorer',
    'ScoringWeights',
    'ScoreResult',
]
