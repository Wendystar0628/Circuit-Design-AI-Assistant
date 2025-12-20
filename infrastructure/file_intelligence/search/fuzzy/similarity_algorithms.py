# Similarity Algorithms - Fuzzy Matching Algorithm Wrapper
"""
相似度算法封装层

职责：
- 封装底层相似度算法库（rapidfuzz）
- 提供统一的算法调用接口
- 支持降级到标准库实现

被调用方：fuzzy_matcher.py, match_scorer.py
"""

from typing import Callable, List, Tuple

# 尝试导入 rapidfuzz，失败则使用标准库降级
try:
    from rapidfuzz import fuzz
    from rapidfuzz.distance import Levenshtein, JaroWinkler
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False
    from difflib import SequenceMatcher


class SimilarityAlgorithms:
    """
    相似度算法封装类
    
    封装 rapidfuzz 库的核心算法，提供统一接口。
    若 rapidfuzz 不可用，自动降级到标准库实现。
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
        
        if RAPIDFUZZ_AVAILABLE:
            return Levenshtein.normalized_similarity(s1, s2)
        else:
            return SequenceMatcher(None, s1, s2).ratio()
    
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
        
        if RAPIDFUZZ_AVAILABLE:
            return JaroWinkler.similarity(s1, s2, prefix_weight=prefix_weight)
        else:
            # 降级实现：使用 SequenceMatcher + 前缀加权
            base_ratio = SequenceMatcher(None, s1, s2).ratio()
            # 计算公共前缀长度（最多4个字符）
            prefix_len = 0
            for i in range(min(len(s1), len(s2), 4)):
                if s1[i] == s2[i]:
                    prefix_len += 1
                else:
                    break
            return base_ratio + prefix_len * prefix_weight * (1 - base_ratio)
    
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
        
        if RAPIDFUZZ_AVAILABLE:
            return fuzz.partial_ratio(s1, s2) / 100.0
        else:
            # 降级实现：滑动窗口匹配
            shorter, longer = (s1, s2) if len(s1) <= len(s2) else (s2, s1)
            if len(shorter) == 0:
                return 0.0
            
            best_ratio = 0.0
            for i in range(len(longer) - len(shorter) + 1):
                window = longer[i:i + len(shorter)]
                ratio = SequenceMatcher(None, shorter, window).ratio()
                best_ratio = max(best_ratio, ratio)
            
            return best_ratio
    
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
        
        if RAPIDFUZZ_AVAILABLE:
            return fuzz.token_sort_ratio(s1, s2) / 100.0
        else:
            # 降级实现：排序后比较
            sorted1 = ' '.join(sorted(s1.lower().split()))
            sorted2 = ' '.join(sorted(s2.lower().split()))
            return SequenceMatcher(None, sorted1, sorted2).ratio()
    
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
        
        if RAPIDFUZZ_AVAILABLE:
            return fuzz.token_set_ratio(s1, s2) / 100.0
        else:
            # 降级实现：集合比较
            set1 = set(s1.lower().split())
            set2 = set(s2.lower().split())
            if not set1 and not set2:
                return 1.0
            intersection = set1 & set2
            union = set1 | set2
            return len(intersection) / len(union) if union else 0.0
    
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
    
    @staticmethod
    def is_rapidfuzz_available() -> bool:
        """检查 rapidfuzz 是否可用"""
        return RAPIDFUZZ_AVAILABLE


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    'SimilarityAlgorithms',
    'RAPIDFUZZ_AVAILABLE',
]
