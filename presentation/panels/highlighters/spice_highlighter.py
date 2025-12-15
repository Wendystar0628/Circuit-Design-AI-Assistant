# SPICE Syntax Highlighter
"""
SPICE 文件语法高亮器

高亮规则：
- 注释（* 开头）：绿色
- 行内注释（; 后面）：绿色
- 指令（. 开头）：蓝色加粗
- 元件名（R、C、L、Q、M、D 等）：青色
- 数值和单位：浅绿
- 字符串（引号内）：橙色
"""

import re
from typing import List, Tuple

from PyQt6.QtGui import (
    QSyntaxHighlighter, QTextCharFormat, QTextDocument, QColor, QFont
)


class SpiceHighlighter(QSyntaxHighlighter):
    """
    SPICE 文件语法高亮器
    
    高亮规则：
    - 注释（* 开头）：绿色
    - 指令（. 开头）：蓝色
    - 元件名（R、C、L、Q、M、D 等）：青色
    - 数值和单位：浅绿
    - 节点名：黄色
    """
    
    def __init__(self, document: QTextDocument):
        super().__init__(document)
        self._rules: List[Tuple[re.Pattern, QTextCharFormat]] = []
        self._setup_rules()
    
    def _setup_rules(self):
        """设置高亮规则"""
        # 注释格式（* 开头的行）
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#6a9955"))
        self._rules.append((
            re.compile(r'^\*.*$', re.MULTILINE),
            comment_format
        ))
        
        # 行内注释（; 后面的内容）
        inline_comment_format = QTextCharFormat()
        inline_comment_format.setForeground(QColor("#6a9955"))
        self._rules.append((
            re.compile(r';.*$', re.MULTILINE),
            inline_comment_format
        ))
        
        # 指令格式（. 开头，如 .tran, .ac, .dc, .param, .subckt, .ends, .include, .lib）
        directive_format = QTextCharFormat()
        directive_format.setForeground(QColor("#569cd6"))
        directive_format.setFontWeight(QFont.Weight.Bold)
        self._rules.append((
            re.compile(r'^\s*\.[a-zA-Z]+', re.MULTILINE | re.IGNORECASE),
            directive_format
        ))
        
        # 元件名格式（R、C、L、Q、M、D、V、I、E、F、G、H、X 开头）
        component_format = QTextCharFormat()
        component_format.setForeground(QColor("#4ec9b0"))
        self._rules.append((
            re.compile(r'\b[RCLQMDVIFGHEX][a-zA-Z0-9_]*\b', re.IGNORECASE),
            component_format
        ))
        
        # 数值和单位格式
        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#b5cea8"))
        self._rules.append((
            re.compile(r'\b\d+\.?\d*[a-zA-Z]*\b'),
            number_format
        ))
        
        # 科学计数法
        self._rules.append((
            re.compile(r'\b\d+\.?\d*[eE][+-]?\d+\b'),
            number_format
        ))
        
        # 字符串格式（引号内）
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#ce9178"))
        self._rules.append((
            re.compile(r'"[^"]*"'),
            string_format
        ))
        self._rules.append((
            re.compile(r"'[^']*'"),
            string_format
        ))
    
    def highlightBlock(self, text: str):
        """高亮文本块"""
        for pattern, fmt in self._rules:
            for match in pattern.finditer(text):
                start = match.start()
                length = match.end() - start
                self.setFormat(start, length, fmt)


__all__ = ["SpiceHighlighter"]
