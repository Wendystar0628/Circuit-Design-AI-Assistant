# Line Number Area Component
"""
行号区域组件

专注于代码编辑器的行号显示。

视觉设计：
- 背景色：#f8f9fa（浅灰白）
- 右侧分隔线：#e0e0e0
- 行号文字颜色：#999999
- 最少显示 3 位数字宽度
"""

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import QSize

if TYPE_CHECKING:
    from .code_editor import CodeEditor


class LineNumberArea(QWidget):
    """
    行号区域组件
    
    显示代码编辑器的行号，委托给编辑器进行实际绘制。
    """
    
    def __init__(self, editor: 'CodeEditor'):
        super().__init__(editor)
        self._editor = editor
    
    def sizeHint(self) -> QSize:
        """返回行号区域的推荐尺寸"""
        return QSize(self._editor.line_number_area_width(), 0)
    
    def paintEvent(self, event):
        """绘制事件，委托给编辑器处理"""
        self._editor.line_number_area_paint_event(event)


__all__ = ["LineNumberArea"]
