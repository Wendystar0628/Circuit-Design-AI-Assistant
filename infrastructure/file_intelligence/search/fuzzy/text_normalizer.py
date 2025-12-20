# Text Normalizer - Text Preprocessing for Fuzzy Matching
"""
文本规范化器

职责：
- 文本预处理，确保匹配前文本格式一致
- 支持空白字符、大小写、Unicode 规范化
- 提取词元（驼峰、下划线分割）

被调用方：fuzzy_matcher.py, patch_strategies.py
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class NormalizeOptions:
    """规范化选项"""
    ignore_whitespace: bool = True
    ignore_case: bool = True
    ignore_empty_lines: bool = True
    strip_comments: bool = False
    normalize_unicode: bool = True


class TextNormalizer:
    """
    文本规范化器
    
    提供文本预处理功能，确保匹配前文本格式一致。
    """
    
    # 注释模式（按语言）
    COMMENT_PATTERNS = {
        'python': r'#.*$',
        'spice': r'^\s*\*.*$|;.*$',  # SPICE: 行首*是注释，;后是行内注释
        'c': r'//.*$|/\*[\s\S]*?\*/',
        'json': None,  # JSON 不支持注释
    }
    
    # 驼峰分割模式
    CAMEL_CASE_PATTERN = re.compile(
        r'(?<=[a-z])(?=[A-Z])|'  # camelCase
        r'(?<=[A-Z])(?=[A-Z][a-z])|'  # XMLParser -> XML Parser
        r'(?<=[a-zA-Z])(?=[0-9])|'  # name2 -> name 2
        r'(?<=[0-9])(?=[a-zA-Z])'  # 2name -> 2 name
    )
    
    @staticmethod
    def normalize_whitespace(text: str) -> str:
        """
        规范化空白字符
        
        - 连续空格 → 单空格
        - 移除行尾空格
        - 统一换行符为 \n
        
        Args:
            text: 输入文本
            
        Returns:
            str: 规范化后的文本
        """
        # 统一换行符
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        # 移除行尾空格
        lines = [line.rstrip() for line in text.split('\n')]
        # 连续空格 → 单空格
        lines = [re.sub(r'[ \t]+', ' ', line) for line in lines]
        return '\n'.join(lines)
    
    @staticmethod
    def normalize_case(text: str, case_sensitive: bool = False) -> str:
        """
        大小写规范化
        
        Args:
            text: 输入文本
            case_sensitive: 是否区分大小写
            
        Returns:
            str: 规范化后的文本
        """
        if case_sensitive:
            return text
        return text.lower()
    
    @staticmethod
    def normalize_unicode(text: str) -> str:
        """
        Unicode 规范化（NFC 形式）
        
        确保相同字符的不同 Unicode 表示被统一。
        
        Args:
            text: 输入文本
            
        Returns:
            str: 规范化后的文本
        """
        return unicodedata.normalize('NFC', text)
    
    @staticmethod
    def remove_comments(text: str, language: str = 'python') -> str:
        """
        移除注释
        
        Args:
            text: 输入文本
            language: 语言类型（python/spice/c/json）
            
        Returns:
            str: 移除注释后的文本
        """
        pattern = TextNormalizer.COMMENT_PATTERNS.get(language)
        if pattern is None:
            return text
        
        return re.sub(pattern, '', text, flags=re.MULTILINE)
    
    @staticmethod
    def remove_empty_lines(text: str) -> str:
        """
        移除空行
        
        Args:
            text: 输入文本
            
        Returns:
            str: 移除空行后的文本
        """
        lines = [line for line in text.split('\n') if line.strip()]
        return '\n'.join(lines)
    
    @staticmethod
    def extract_tokens(text: str) -> List[str]:
        """
        提取词元
        
        按驼峰、下划线、空格分割文本为词元列表。
        
        Args:
            text: 输入文本
            
        Returns:
            List[str]: 词元列表
        """
        # 先按驼峰分割
        text = TextNormalizer.CAMEL_CASE_PATTERN.sub(' ', text)
        # 再按下划线和空格分割
        tokens = re.split(r'[_\s]+', text)
        # 过滤空字符串
        return [t.lower() for t in tokens if t]
    
    @staticmethod
    def normalize_for_matching(
        text: str,
        options: Optional[NormalizeOptions] = None
    ) -> str:
        """
        综合规范化入口
        
        根据选项对文本进行综合规范化处理。
        
        Args:
            text: 输入文本
            options: 规范化选项
            
        Returns:
            str: 规范化后的文本
        """
        if options is None:
            options = NormalizeOptions()
        
        result = text
        
        # Unicode 规范化
        if options.normalize_unicode:
            result = TextNormalizer.normalize_unicode(result)
        
        # 移除注释（如果需要）
        if options.strip_comments:
            result = TextNormalizer.remove_comments(result)
        
        # 空白字符规范化
        if options.ignore_whitespace:
            result = TextNormalizer.normalize_whitespace(result)
        
        # 移除空行
        if options.ignore_empty_lines:
            result = TextNormalizer.remove_empty_lines(result)
        
        # 大小写规范化
        if options.ignore_case:
            result = TextNormalizer.normalize_case(result, case_sensitive=False)
        
        return result
    
    @staticmethod
    def get_token_string(text: str) -> str:
        """
        获取词元字符串（用于词序无关匹配）
        
        Args:
            text: 输入文本
            
        Returns:
            str: 空格分隔的词元字符串
        """
        tokens = TextNormalizer.extract_tokens(text)
        return ' '.join(sorted(tokens))


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    'TextNormalizer',
    'NormalizeOptions',
]
