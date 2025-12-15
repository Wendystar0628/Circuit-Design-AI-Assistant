# Python Syntax Highlighter
"""
Python 文件语法高亮器

高亮规则：
- 关键字（def、class、if、for 等）：蓝色
- 内置函数（print、len、range 等）：黄色
- 字符串：橙色
- 注释（# 开头）：绿色
- 数值：浅绿
- 装饰器（@ 开头）：紫色
"""

import re
from typing import List, Tuple

from PyQt6.QtGui import (
    QSyntaxHighlighter, QTextCharFormat, QTextDocument, QColor, QFont
)


class PythonHighlighter(QSyntaxHighlighter):
    """
    Python 文件语法高亮器
    
    高亮规则：
    - 关键字：蓝色
    - 内置函数：黄色
    - 字符串：橙色
    - 注释：绿色
    - 数值：浅绿
    - 装饰器：紫色
    """
    
    # Python 关键字
    KEYWORDS = [
        'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await',
        'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except',
        'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is',
        'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try',
        'while', 'with', 'yield'
    ]
    
    # Python 内置函数
    BUILTINS = [
        'abs', 'all', 'any', 'bin', 'bool', 'bytearray', 'bytes', 'callable',
        'chr', 'classmethod', 'compile', 'complex', 'delattr', 'dict', 'dir',
        'divmod', 'enumerate', 'eval', 'exec', 'filter', 'float', 'format',
        'frozenset', 'getattr', 'globals', 'hasattr', 'hash', 'help', 'hex',
        'id', 'input', 'int', 'isinstance', 'issubclass', 'iter', 'len',
        'list', 'locals', 'map', 'max', 'memoryview', 'min', 'next', 'object',
        'oct', 'open', 'ord', 'pow', 'print', 'property', 'range', 'repr',
        'reversed', 'round', 'set', 'setattr', 'slice', 'sorted', 'staticmethod',
        'str', 'sum', 'super', 'tuple', 'type', 'vars', 'zip'
    ]
    
    def __init__(self, document: QTextDocument):
        super().__init__(document)
        self._rules: List[Tuple[re.Pattern, QTextCharFormat]] = []
        self._setup_rules()
    
    def _setup_rules(self):
        """设置高亮规则"""
        # 关键字格式
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#569cd6"))
        keyword_format.setFontWeight(QFont.Weight.Bold)
        keywords_pattern = r'\b(' + '|'.join(self.KEYWORDS) + r')\b'
        self._rules.append((
            re.compile(keywords_pattern),
            keyword_format
        ))
        
        # 内置函数格式
        builtin_format = QTextCharFormat()
        builtin_format.setForeground(QColor("#dcdcaa"))
        builtins_pattern = r'\b(' + '|'.join(self.BUILTINS) + r')\b'
        self._rules.append((
            re.compile(builtins_pattern),
            builtin_format
        ))
        
        # 装饰器格式（@ 开头）
        decorator_format = QTextCharFormat()
        decorator_format.setForeground(QColor("#c586c0"))
        self._rules.append((
            re.compile(r'@\w+'),
            decorator_format
        ))
        
        # 类名和函数名格式（def/class 后面的名称）
        def_format = QTextCharFormat()
        def_format.setForeground(QColor("#4ec9b0"))
        self._rules.append((
            re.compile(r'\bdef\s+(\w+)'),
            def_format
        ))
        self._rules.append((
            re.compile(r'\bclass\s+(\w+)'),
            def_format
        ))
        
        # 数值格式
        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#b5cea8"))
        self._rules.append((
            re.compile(r'\b\d+\.?\d*([eE][+-]?\d+)?\b'),
            number_format
        ))
        
        # 字符串格式（单引号、双引号）
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#ce9178"))
        # 双引号字符串
        self._rules.append((
            re.compile(r'"[^"\\]*(\\.[^"\\]*)*"'),
            string_format
        ))
        # 单引号字符串
        self._rules.append((
            re.compile(r"'[^'\\]*(\\.[^'\\]*)*'"),
            string_format
        ))
        # 三引号字符串（简化处理，不跨行）
        self._rules.append((
            re.compile(r'"""[^"]*"""'),
            string_format
        ))
        self._rules.append((
            re.compile(r"'''[^']*'''"),
            string_format
        ))
        
        # 注释格式（# 开头）
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#6a9955"))
        self._rules.append((
            re.compile(r'#.*$', re.MULTILINE),
            comment_format
        ))
    
    def highlightBlock(self, text: str):
        """高亮文本块"""
        for pattern, fmt in self._rules:
            for match in pattern.finditer(text):
                start = match.start()
                length = match.end() - start
                self.setFormat(start, length, fmt)


__all__ = ["PythonHighlighter"]
