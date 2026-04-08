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

from typing import Any, Dict, Optional, Set, Tuple

from PyQt6.QtWidgets import QPlainTextEdit, QTextEdit
from PyQt6.QtCore import Qt, pyqtSignal, QRect
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QTextCursor, QTextFormat, QSyntaxHighlighter
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

        self.setUndoRedoEnabled(False)
        
        # 语法高亮器
        self._highlighter: Optional[QSyntaxHighlighter] = None
        
        # 文件路径
        self._file_path: Optional[str] = None

        # 待确认 diff 可视状态
        self._pending_file_state: Optional[Dict[str, Any]] = None
        self._added_line_numbers: Set[int] = set()
        self._deleted_anchor_lines: Set[int] = set()
        
        # 是否已修改
        self._is_modified = False
        
        # 设置字体
        self._setup_font()
        
        # 设置样式
        self._setup_style()
        
        # 连接信号
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._refresh_extra_selections)
        self.textChanged.connect(self._on_text_changed)
        
        # 初始化
        self._update_line_number_area_width(0)
        self._refresh_extra_selections()
    
    def _setup_font(self):
        """设置编程字体"""
        font = QFont()
        # 设置字体提示为等宽字体，但不使用 setFixedPitch 避免回退到 Fixedsys
        font.setStyleHint(QFont.StyleHint.Monospace, QFont.StyleStrategy.PreferAntialias)
        
        # 尝试使用现代编程字体，按优先级排序
        font_found = False
        for font_name in ["JetBrains Mono", "Cascadia Code", "Fira Code", "SF Mono", "Consolas", "Courier New"]:
            font.setFamily(font_name)
            if font.exactMatch():
                font_found = True
                break
        
        # 如果没有找到任何字体，使用系统默认等宽字体
        if not font_found:
            font.setFamily("monospace")
        
        font.setPointSize(11)
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
        
        space = 18 + self.fontMetrics().horizontalAdvance('9') * digits
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
                line_number = block_number + 1
                line_height = max(1, bottom - top)
                line_rect = QRect(0, top, self._line_number_area.width() - 1, line_height)
                line_bg = self._line_background_color(line_number)
                if line_bg is not None:
                    painter.fillRect(line_rect, line_bg)
                if line_number in self._added_line_numbers and line_number in self._deleted_anchor_lines:
                    painter.fillRect(0, top, 2, line_height, QColor("#ef4444"))
                    painter.fillRect(2, top, 2, line_height, QColor("#22c55e"))
                elif line_number in self._added_line_numbers:
                    painter.fillRect(0, top, 4, line_height, QColor("#22c55e"))
                elif line_number in self._deleted_anchor_lines:
                    painter.fillRect(0, top, 4, line_height, QColor("#ef4444"))
                number = str(block_number + 1)
                painter.drawText(
                    6, top,
                    self._line_number_area.width() - 11,
                    line_height,
                    Qt.AlignmentFlag.AlignRight,
                    number
                )
            
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1
    
    def _line_background_color(self, line_number: int, current: bool = False) -> Optional[QColor]:
        if line_number in self._added_line_numbers:
            return QColor("#dcfce7" if current else "#ecfdf5")
        if line_number in self._deleted_anchor_lines:
            return QColor("#fee2e2" if current else "#fef2f2")
        if current:
            return QColor("#f0f7ff")
        return None

    def _build_full_width_selection(
        self,
        line_number: int,
        color: QColor,
    ) -> Optional[QTextEdit.ExtraSelection]:
        block = self.document().findBlockByNumber(line_number - 1)
        if not block.isValid():
            return None
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(color)
        selection.format.setProperty(
            QTextFormat.Property.FullWidthSelection, True
        )
        cursor = QTextCursor(block)
        cursor.clearSelection()
        selection.cursor = cursor
        return selection

    def _refresh_extra_selections(self):
        """刷新当前行与 pending diff 的可视高亮"""
        extra_selections = []

        for line_number in sorted(self._deleted_anchor_lines - self._added_line_numbers):
            selection = self._build_full_width_selection(line_number, QColor("#fef2f2"))
            if selection is not None:
                extra_selections.append(selection)

        for line_number in sorted(self._added_line_numbers):
            selection = self._build_full_width_selection(line_number, QColor("#ecfdf5"))
            if selection is not None:
                extra_selections.append(selection)

        current_line_number = self.textCursor().blockNumber() + 1
        current_line_color = self._line_background_color(current_line_number, current=True)
        if current_line_color is not None:
            selection = self._build_full_width_selection(current_line_number, current_line_color)
            if selection is not None:
                extra_selections.append(selection)

        self.setExtraSelections(extra_selections)
    
    def _on_text_changed(self):
        """文本变化处理"""
        if not self._is_modified:
            self._is_modified = True
            # 发出修改状态变化信号
            self.modification_changed.emit(True)
        self._refresh_extra_selections()
    
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

    def set_pending_file_state(self, file_state: Optional[Dict[str, Any]]):
        self._pending_file_state = file_state if isinstance(file_state, dict) else None
        self._added_line_numbers = set()
        self._deleted_anchor_lines = set()
        max_line_number = max(1, self.blockCount())
        if isinstance(self._pending_file_state, dict):
            for hunk in self._pending_file_state.get("hunks", []) or []:
                if not isinstance(hunk, dict):
                    continue
                if int(hunk.get("deleted_lines", 0) or 0) > 0:
                    anchor_line = max(1, int(hunk.get("new_start", 0) or 0) + 1)
                    anchor_line = min(anchor_line, max_line_number)
                    self._deleted_anchor_lines.add(anchor_line)
                for line in hunk.get("lines", []) or []:
                    if not isinstance(line, dict):
                        continue
                    if str(line.get("kind", "") or "") != "added":
                        continue
                    line_number = line.get("new_line_number")
                    if line_number is None:
                        continue
                    self._added_line_numbers.add(int(line_number))
        self._line_number_area.update()
        self.viewport().update()
        self._refresh_extra_selections()
    
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
        self._refresh_extra_selections()
    
    def get_cursor_position(self) -> Tuple[int, int]:
        """获取光标位置（行号，列号）"""
        cursor = self.textCursor()
        return cursor.blockNumber() + 1, cursor.columnNumber() + 1


__all__ = ["CodeEditor"]
