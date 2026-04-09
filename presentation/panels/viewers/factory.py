from typing import Optional

from PyQt6.QtWidgets import QWidget

from shared.workspace_file_types import (
    is_markdown_extension,
    is_pdf_extension,
    is_tabular_extension,
    is_word_extension,
)

from .docx_viewer import DocxViewer
from .markdown_viewer import MarkdownViewer
from .pdf_viewer import PdfViewer
from .tabular_viewer import TabularViewer


def create_document_viewer(path: str, ext: str) -> Optional[QWidget]:
    if is_markdown_extension(ext):
        viewer = MarkdownViewer()
        viewer.load_markdown(path)
        return viewer
    if is_word_extension(ext):
        viewer = DocxViewer()
        viewer.load_docx(path)
        return viewer
    if is_pdf_extension(ext):
        viewer = PdfViewer()
        viewer.load_pdf(path)
        return viewer
    if is_tabular_extension(ext):
        viewer = TabularViewer()
        viewer.load_file(path)
        return viewer
    return None


__all__ = ["create_document_viewer"]
