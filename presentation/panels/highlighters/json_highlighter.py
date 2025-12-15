# JSON Syntax Highlighter
"""
JSON 文件语法高亮器

高亮规则：
- 键名：浅蓝
- 字符串值：橙色
- 数值：浅绿
- 布尔值/null：蓝色
"""

import re
from typing import List, Tuple

from PyQt6.QtGui import (
    QSyntaxHighlighter, QTextCharFormat, QTextDocument, QColor
)


class JsonHighlighter(QSyntaxHighlighter):
    """
    JSON 文件语法高亮器
    
    高亮规则：
    - 键名：浅蓝
    - 字符串值：橙色
    - 数值：浅绿
    - 布尔值/null：蓝色
    """
    
    def __init__(self, document: QTextDocument):
        super().__init__(document)
        self._rules: List[Tuple[re.Pattern, QTextCharFormat]] = []
        self._setup_rules()
    
    def _setup_rules(self):
        """设置高亮规则"""
        # 键名格式（引号内，后跟冒号）
        key_format = QTextCharFormat()
        key_format.setForeground(QColor("#9cdcfe"))
        self._rules.append((
            re.compile(r'"[^"]*"\s*:'),
            key_format
        ))
        
        # 字符串值格式
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#ce9178"))
        self._rules.append((
            re.compile(r':\s*"[^"]*"'),
            string_format
        ))
        
        # 数值格式
        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#b5cea8"))
        self._rules.append((
            re.compile(r':\s*-?\d+\.?\d*([eE][+-]?\d+)?'),
            number_format
        ))
        
        # 布尔值和 null 格式
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#569cd6"))
        self._rules.append((
            re.compile(r'\b(true|false|null)\b'),
            keyword_format
        ))
    
    def highlightBlock(self, text: str):
        """高亮文本块"""
        for pattern, fmt in self._rules:
            for match in pattern.finditer(text):
                start = match.start()
                length = match.end() - start
                self.setFormat(start, length, fmt)


__all__ = ["JsonHighlighter"]
