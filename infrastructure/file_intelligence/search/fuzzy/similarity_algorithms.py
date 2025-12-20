# Similarity Algorithms - Fuzzy Matching Algorithm Wrapper
"""
相似度算法封装层

职责：
- 封装底层相似度算法库（rapidfuzz）
- 提供统一的算法调用接口

依赖：rapidfuzz>=3.0.0
安装：pip install rapidfuzz

被调用方：fuzzy_matcher.py, match_scorer.py
"""

from typing import Callable

from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler, Levenshtein


class SimilarityAlgorithms:
    """
    相似度算法封装类
    
    封装 rapidfuzz 库的核心算法，提供统一接口。
    """
    
    @staticmethod
    def levenshtein_ratio(s1: str, s2: str) -> float:
        """
        Levenshtein 编辑距离相似度
        
        计算两个字符串的编辑距离相似度（0-1）。
        适用于：参数名匹配、精确度要求高的场景。
        
        Args:
            s1: 第一个字符串
            s2: 第二个字符串
            
        Returns:
            float: 相似度（0.0-1.0）
        """
        if not s1 and not s2:
            return 1.0
        if not s1 or not s2:
            return 0.0
        
        return Levenshtein.normalized_similarity(s1, s2)
    
    @staticmethod
    def jaro_winkler_ratio(s1: str, s2: str, prefix_weight: float = 0.1) -> float:
        """
        Jaro-Winkler 相似度
        
        对前缀匹配更敏感，适用于文件名匹配。
        
        Args:
            s1: 第一个字符串
            s2: 第二个字符串
            prefix_weight: 前缀权重（默认 0.1）
            
        Returns:
            float: 相似度（0.0-1.0）
        """
        if not s1 and not s2:
            return 1.0
        if not s1 or not s2:
            return 0.0
        
        return JaroWinkler.similarity(s1, s2, prefix_weight=prefix_weight)
    
    @staticmethod
    def partial_ratio(s1: str, s2: str) -> float:
        """
        部分匹配相似度
        
        在长文本中查找短文本的最佳匹配位置。
        适用于：代码内容匹配、长文本搜索。
        
        Args:
            s1: 查询字符串（通常较短）
            s2: 目标字符串（通常较长）
            
        Returns:
            float: 相似度（0.0-1.0）
        """
        if not s1 and not s2:
            return 1.0
        if not s1 or not s2:
            return 0.0
        
        return fuzz.partial_ratio(s1, s2) / 100.0
    
    @staticmethod
    def token_sort_ratio(s1: str, s2: str) -> float:
        """
        词序无关相似度
        
        将字符串按词分割、排序后比较。
        适用于：词序可能变化的场景。
        
        Args:
            s1: 第一个字符串
            s2: 第二个字符串
            
        Returns:
            float: 相似度（0.0-1.0）
        """
        if not s1 and not s2:
            return 1.0
        if not s1 or not s2:
            return 0.0
        
        return fuzz.token_sort_ratio(s1, s2) / 100.0
    
    @staticmethod
    def token_set_ratio(s1: str, s2: str) -> float:
        """
        词集合相似度
        
        忽略重复词，只比较词集合。
        适用于：关键词匹配、标签匹配。
        
        Args:
            s1: 第一个字符串
            s2: 第二个字符串
            
        Returns:
            float: 相似度（0.0-1.0）
        """
        if not s1 and not s2:
            return 1.0
        if not s1 or not s2:
            return 0.0
        
        return fuzz.token_set_ratio(s1, s2) / 100.0
    
    @staticmethod
    def get_algorithm(name: str) -> Callable[[str, str], float]:
        """
        根据名称获取算法函数
        
        Args:
            name: 算法名称（levenshtein/jaro_winkler/partial/token_sort/token_set）
            
        Returns:
            Callable: 算法函数
        """
        algorithms = {
            'levenshtein': SimilarityAlgorithms.levenshtein_ratio,
            'jaro_winkler': SimilarityAlgorithms.jaro_winkler_ratio,
            'partial': SimilarityAlgorithms.partial_ratio,
            'token_sort': SimilarityAlgorithms.token_sort_ratio,
            'token_set': SimilarityAlgorithms.token_set_ratio,
        }
        return algorithms.get(name, SimilarityAlgorithms.levenshtein_ratio)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    'SimilarityAlgorithms',
]
