# Fuzzy Matching Module
"""
模糊匹配子模块

包含：
- similarity_algorithms.py: 相似度算法封装层
- text_normalizer.py: 文本规范化器
- match_scorer.py: 匹配评分器
- fuzzy_matcher.py: 模糊匹配器门面类
"""

from infrastructure.file_intelligence.search.fuzzy.fuzzy_matcher import (
    FuzzyMatcher,
    MatchOptions,
    MatchResult,
)
from infrastructure.file_intelligence.search.fuzzy.match_scorer import (
    MatchScorer,
    ScoringWeights,
)
from infrastructure.file_intelligence.search.fuzzy.similarity_algorithms import (
    SimilarityAlgorithms,
)
from infrastructure.file_intelligence.search.fuzzy.text_normalizer import (
    NormalizeOptions,
    TextNormalizer,
)

__all__ = [
    "FuzzyMatcher",
    "MatchOptions",
    "MatchResult",
    "MatchScorer",
    "ScoringWeights",
    "SimilarityAlgorithms",
    "TextNormalizer",
    "NormalizeOptions",
]
