# Document Viewer Component
"""
文档预览组件导出模块。

当前文档预览已拆分为按类型分职责的实现：
- MarkdownViewer
- PdfViewer
- DocxViewer

旧的单体 DocumentViewer 设计已移除。
"""
from .docx_viewer import DocxViewer
from .markdown_viewer import MarkdownViewer
from .pdf_viewer import PdfViewer

__all__ = [
    "DocxViewer",
    "MarkdownViewer",
    "PdfViewer",
]
