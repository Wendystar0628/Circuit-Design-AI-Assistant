# Code Editor Core Component
"""
代码编辑器核心组件

专注于代码编辑功能，包含：
- 行号显示
- 当前行高亮
- 语法高亮集成
- 修改状态管理

视觉设计：
- 编辑器背景：#ffffff（纯白）
- 当前行高亮：#f0f7ff（淡蓝白）
- 选中文本高亮：#e3f2fd（极浅蓝）
- 等宽编程字体（JetBrains Mono、Consolas、Fira Code）
- Tab 宽度：4 个空格
"""

from typing import Optional, Tuple

from PyQt6.QtWidgets import QPlainTextEdit, QTextEdit
from PyQt6.QtCore import Qt, pyqtSignal, QRect
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QTextFormat, QSyntaxHighlighter
)

from .line_number_area import LineNumberArea
from ..highlighters import SpiceHighlighter, JsonHighlighter, PythonHighlighter


class CodeEditor(QPlainTextEdit):
    """
    代码编辑器组件
    
    功能：
    - 行号显示
    - 当前行高亮
    - 语法高亮
    - 基本快捷键支持
    
    信号：
    - modification_changed(bool): 修改状态变化时发出
    """
    
    # 修改状态变化信号
    modification_changed = pyqtSignal(bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 行号区域
        self._line_number_area = LineNumberArea(self)
        
        # 语法高亮器
        self._highlighter: Optional[QSyntaxHighlighter] = None
        
        # 文件路径
        self._file_path: Optional[str] = None
        
        # 是否已修改
        self._is_modified = False
        
        # 设置字体
        self._setup_font()
        
        # 设置样式
        self._setup_style()
        
        # 连接信号
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self.textChanged.connect(self._on_text_changed)
        
        # 初始化
        self._update_line_number_area_width(0)
        self._highlight_current_line()
    
    def _setup_font(self):
        """设置编程字体"""
        font = QFont()
        # 尝试使用常见的编程字体
        for font_name in ["JetBrains Mono", "Consolas", "Fira Code", "Monaco", "Courier New"]:
            font.setFamily(font_name)
            if font.exactMatch():
                break
        font.setPointSize(11)
        font.setFixedPitch(True)
        self.setFont(font)
        
        # 设置 Tab 宽度为 4 个空格
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 4)
    
    def _setup_style(self):
        """设置编辑器样式"""
        self.setStyleSheet("""
            QPlainTextEdit {
                background-color: #ffffff;
                color: #333333;
                border: none;
                selection-background-color: #e3f2fd;
                selection-color: #333333;
            }
        """)

    def line_number_area_width(self) -> int:
        """计算行号区域宽度"""
        digits = 1
        max_num = max(1, self.blockCount())
        while max_num >= 10:
            max_num //= 10
            digits += 1
        
        # 最少显示 3 位数字的宽度
        digits = max(3, digits)
        
        space = 10 + self.fontMetrics().horizontalAdvance('9') * digits
        return space
    
    def _update_line_number_area_width(self, _):
        """更新行号区域宽度"""
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)
    
    def _update_line_number_area(self, rect: QRect, dy: int):
        """更新行号区域"""
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(
                0, rect.y(),
                self._line_number_area.width(), rect.height()
            )
        
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)
    
    def resizeEvent(self, event):
        """窗口大小变化"""
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(cr.left(), cr.top(),
                  self.line_number_area_width(), cr.height())
        )
    
    def line_number_area_paint_event(self, event):
        """绘制行号区域"""
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QColor("#f8f9fa"))
        
        # 绘制右侧分隔线
        painter.setPen(QColor("#e0e0e0"))
        painter.drawLine(
            self._line_number_area.width() - 1, event.rect().top(),
            self._line_number_area.width() - 1, event.rect().bottom()
        )
        
        # 绘制行号
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(
            self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        
        painter.setPen(QColor("#999999"))
        
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.drawText(
                    0, top,
                    self._line_number_area.width() - 5,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    number
                )
            
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1
    
    def _highlight_current_line(self):
        """高亮当前行"""
        extra_selections = []
        
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            line_color = QColor("#f0f7ff")
            selection.format.setBackground(line_color)
            selection.format.setProperty(
                QTextFormat.Property.FullWidthSelection, True
            )
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extra_selections.append(selection)
        
        self.setExtraSelections(extra_selections)
    
    def _on_text_changed(self):
        """文本变化处理"""
        if not self._is_modified:
            self._is_modified = True
            # 发出修改状态变化信号
            self.modification_changed.emit(True)
    
    def set_highlighter(self, file_ext: str):
        """根据文件扩展名设置语法高亮器"""
        # 移除旧的高亮器
        if self._highlighter:
            self._highlighter.setDocument(None)
            self._highlighter = None
        
        # 根据扩展名创建新的高亮器
        ext = file_ext.lower()
        if ext in {'.cir', '.sp', '.spice'}:
            self._highlighter = SpiceHighlighter(self.document())
        elif ext == '.json':
            self._highlighter = JsonHighlighter(self.document())
        elif ext == '.py':
            self._highlighter = PythonHighlighter(self.document())
    
    def get_file_path(self) -> Optional[str]:
        """获取文件路径"""
        return self._file_path
    
    def set_file_path(self, path: str):
        """设置文件路径"""
        self._file_path = path
    
    def is_modified(self) -> bool:
        """是否已修改"""
        return self._is_modified
    
    def set_modified(self, modified: bool):
        """设置修改状态"""
        old_modified = self._is_modified
        self._is_modified = modified
        # 状态变化时发出信号
        if old_modified != modified:
            self.modification_changed.emit(modified)
    
    def get_cursor_position(self) -> Tuple[int, int]:
        """获取光标位置（行号，列号）"""
        cursor = self.textCursor()
        return cursor.blockNumber() + 1, cursor.columnNumber() + 1


__all__ = ["CodeEditor"]
