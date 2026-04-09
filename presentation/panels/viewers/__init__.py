# File Viewers Package
"""
文件预览器包

包含各种文件类型的预览组件：
- ImageViewer: 图片预览组件
- MarkdownViewer: Markdown 预览组件
- PdfViewer: PDF 预览组件
- DocxViewer: Word 文档预览组件
- TabularViewer: CSV/TSV 表格预览组件
"""

from .docx_viewer import DocxViewer
from .image_viewer import ImageViewer
from .markdown_viewer import MarkdownViewer
from .pdf_viewer import PdfViewer
from .tabular_viewer import TabularViewer

__all__ = [
    "DocxViewer",
    "ImageViewer",
    "MarkdownViewer",
    "PdfViewer",
    "TabularViewer",
]
