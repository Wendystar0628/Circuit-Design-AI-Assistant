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

from .factory import create_document_viewer
from .image_viewer import ImageViewer

__all__ = [
    "ImageViewer",
    "create_document_viewer",
]
