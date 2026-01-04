# Prompt Content Editor
"""
模板内容编辑器组件 - 提供模板内容编辑功能

职责：
- 基于 QPlainTextEdit 的模板内容编辑
- 变量占位符语法高亮
- 支持变量插入
"""

import re
from typing import Optional

from PyQt6.QtWidgets import QPlainTextEdit, QWidget
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import (
    QSyntaxHighlighter, QTextCharFormat, QColor,
    QFont, QTextDocument, QTextCursor
)


class VariableHighlighter(QSyntaxHighlighter):
    """变量占位符语法高亮器"""
    
    # 匹配 {variable_name} 或 {nested.variable}
    VARIABLE_PATTERN = re.compile(r'\{([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)\}')
    
    def __init__(self, document: QTextDocument):
        super().__init__(document)
        
        # 变量格式
        self._variable_format = QTextCharFormat()
        self._variable_format.setForeground(QColor("#0066CC"))
        self._variable_format.setFontWeight(QFont.Weight.Bold)
        
        # 无效变量格式（未闭合的大括号）
        self._invalid_format = QTextCharFormat()
        self._invalid_format.setForeground(QColor("#CC0000"))
        self._invalid_format.setUnderlineStyle(
            QTextCharFormat.UnderlineStyle.WaveUnderline
        )
        self._invalid_format.setUnderlineColor(QColor("#CC0000"))
    
    def highlightBlock(self, text: str) -> None:
        """高亮文本块"""
        # 高亮有效变量
        for match in self.VARIABLE_PATTERN.finditer(text):
            self.setFormat(
                match.start(),
                match.end() - match.start(),
                self._variable_format
            )
        
        # 检测未闭合的大括号
        self._highlight_invalid_braces(text)
    
    def _highlight_invalid_braces(self, text: str) -> None:
        """高亮未闭合的大括号"""
        stack = []
        for i, char in enumerate(text):
            if char == '{':
                stack.append(i)
            elif char == '}':
                if stack:
                    stack.pop()
                else:
                    # 多余的闭合括号
                    self.setFormat(i, 1, self._invalid_format)
        
        # 未闭合的开括号
        for pos in stack:
            self.setFormat(pos, 1, self._invalid_format)


class PromptContentEditor(QPlainTextEdit):
    """
    模板内容编辑器
    
    Signals:
        content_changed(str): 内容变化
    """
    
    content_changed = pyqtSignal(str)
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._setup_ui()
        self._highlighter = VariableHighlighter(self.document())
        self._highlight_enabled = True
        
        # 连接文本变化信号
        self.textChanged.connect(self._on_text_changed)
    
    def _setup_ui(self) -> None:
        """初始化 UI"""
        # 设置字体
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        
        # 设置制表符宽度
        self.setTabStopDistance(
            self.fontMetrics().horizontalAdvance(' ') * 4
        )
        
        # 设置换行模式
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        
        # 设置占位文本
        self.setPlaceholderText(
            self._get_text(
                "dialog.prompt_editor.content_placeholder",
                "在此编辑模板内容...\n使用 {variable_name} 格式插入变量"
            )
        )
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_I18N_MANAGER
            i18n = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            if i18n:
                return i18n.get_text(key, default)
        except Exception:
            pass
        return default
    
    def _on_text_changed(self) -> None:
        """文本变化处理"""
        self.content_changed.emit(self.toPlainText())
    
    def insert_variable(self, variable: str) -> None:
        """
        在光标位置插入变量
        
        Args:
            variable: 变量文本（如 "{var_name}"）
        """
        cursor = self.textCursor()
        cursor.insertText(variable)
        self.setTextCursor(cursor)
        self.setFocus()
    
    def set_content(self, content: str) -> None:
        """
        设置内容（不触发 content_changed 信号）
        
        Args:
            content: 模板内容
        """
        self.blockSignals(True)
        self.setPlainText(content)
        self.blockSignals(False)
    
    def get_content(self) -> str:
        """获取当前内容"""
        return self.toPlainText()
    
    def set_readonly(self, readonly: bool) -> None:
        """设置只读状态"""
        self.setReadOnly(readonly)
        if readonly:
            self.setStyleSheet("background-color: #f5f5f5;")
        else:
            self.setStyleSheet("")
    
    def set_variable_highlight_enabled(self, enabled: bool) -> None:
        """
        设置是否启用变量高亮
        
        Args:
            enabled: 是否启用
        """
        self._highlight_enabled = enabled
        if enabled:
            self._highlighter = VariableHighlighter(self.document())
        else:
            # 移除高亮器
            if self._highlighter:
                self._highlighter.setDocument(None)
                self._highlighter = None
            # 刷新显示
            self.setPlainText(self.toPlainText())


__all__ = [
    "PromptContentEditor",
    "VariableHighlighter",
]
