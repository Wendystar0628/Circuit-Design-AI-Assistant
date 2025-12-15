# Syntax Highlighters Package
"""
语法高亮器包

包含各种文件类型的语法高亮器：
- SpiceHighlighter: SPICE 文件语法高亮
- JsonHighlighter: JSON 文件语法高亮
- PythonHighlighter: Python 文件语法高亮
"""

from .spice_highlighter import SpiceHighlighter
from .json_highlighter import JsonHighlighter
from .python_highlighter import PythonHighlighter

__all__ = [
    "SpiceHighlighter",
    "JsonHighlighter",
    "PythonHighlighter",
]
