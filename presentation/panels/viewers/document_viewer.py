# Document Viewer Component
"""
文档预览组件

专注于文档文件的只读预览（Markdown、Word、PDF）。

功能：
- Markdown 渲染预览（使用 markdown 库）
- Word 文档文本提取预览（使用 python-docx）
- PDF 文本提取预览（使用 PyMuPDF）

支持格式：.md、.markdown、.docx、.pdf

视觉设计：
- 只读模式
- 背景色：#ffffff（纯白）
- 内边距：20px
- 使用系统 UI 字体
"""

import csv
import html
import os

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

try:
    from PyQt6.QtWebEngineCore import QWebEngineSettings
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except ImportError:
    QWebEngineSettings = None
    QWebEngineView = None
    WEBENGINE_AVAILABLE = False


class DocumentViewer(QWidget):
    """
    文档预览组件
    
    功能：
    - Markdown 渲染预览
    - Word 文档文本提取预览
    - PDF 文本提取预览
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._web_view = None
        self._fallback_label = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if not WEBENGINE_AVAILABLE:
            fallback = QLabel("请安装 PyQt6-WebEngine", self)
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            layout.addWidget(fallback)
            self._fallback_label = fallback
            return
        self._web_view = QWebEngineView(self)
        settings = self._web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        if hasattr(QWebEngineSettings.WebAttribute, "PdfViewerEnabled"):
            settings.setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled, True)
        layout.addWidget(self._web_view)
    
    def load_markdown(self, path: str) -> bool:
        """
        加载 Markdown 文件
        
        Args:
            path: Markdown 文件路径
            
        Returns:
            bool: 是否加载成功
        """
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            try:
                import markdown
                html_content = markdown.markdown(
                    content,
                    extensions=['tables', 'fenced_code', 'codehilite']
                )
                self._show_html(html_content, os.path.dirname(path))
            except ImportError:
                self._show_html(f"<pre>{html.escape(content)}</pre>", os.path.dirname(path))
            return True
        except Exception as e:
            self._show_error(f"Failed to load Markdown: {e}")
            return False
    
    def load_word(self, path: str) -> bool:
        """
        加载 Word 文档
        
        Args:
            path: Word 文档路径
            
        Returns:
            bool: 是否加载成功
        """
        try:
            from docx import Document
            from docx.document import Document as DocxDocument
            from docx.oxml.table import CT_Tbl
            from docx.oxml.text.paragraph import CT_P
            from docx.table import Table
            from docx.text.paragraph import Paragraph

            def iter_block_items(parent):
                parent_element = parent.element.body if isinstance(parent, DocxDocument) else parent._element
                for child in parent_element.iterchildren():
                    if isinstance(child, CT_P):
                        yield Paragraph(child, parent)
                    elif isinstance(child, CT_Tbl):
                        yield Table(child, parent)

            def render_runs(runs):
                parts = []
                for run in runs:
                    text = html.escape(str(run.text or ""))
                    if not text:
                        continue
                    if run.bold:
                        text = f"<strong>{text}</strong>"
                    if run.italic:
                        text = f"<em>{text}</em>"
                    if run.underline:
                        text = f"<u>{text}</u>"
                    parts.append(text)
                return "".join(parts)

            def render_paragraph(paragraph):
                content = render_runs(paragraph.runs) or html.escape(str(paragraph.text or ""))
                if not content.strip():
                    return ""
                style_name = str(getattr(getattr(paragraph, "style", None), "name", "") or "").lower()
                if style_name.startswith("heading"):
                    digits = "".join(ch for ch in style_name if ch.isdigit())
                    level = min(max(int(digits or 2), 1), 6)
                    return f"<h{level}>{content}</h{level}>"
                return f"<p>{content}</p>"

            def render_table(table):
                rows = []
                for row_index, row in enumerate(table.rows):
                    tag = "th" if row_index == 0 else "td"
                    cells = []
                    for cell in row.cells:
                        cell_text = html.escape(cell.text or "")
                        cells.append(f"<{tag}>{cell_text}</{tag}>")
                    rows.append(f"<tr>{''.join(cells)}</tr>")
                return f"<table>{''.join(rows)}</table>"

            doc = Document(path)
            blocks = []
            for block in iter_block_items(doc):
                if block.__class__.__name__ == "Paragraph":
                    rendered = render_paragraph(block)
                else:
                    rendered = render_table(block)
                if rendered:
                    blocks.append(rendered)

            self._show_html("\n".join(blocks), os.path.dirname(path))
            return True
        except ImportError:
            self._show_error("python-docx library not installed.\nInstall with: pip install python-docx")
            return False
        except Exception as e:
            self._show_error(f"Failed to load Word document: {e}")
            return False
    
    def load_pdf(self, path: str) -> bool:
        """
        加载 PDF 文档
        
        Args:
            path: PDF 文档路径
            
        Returns:
            bool: 是否加载成功
        """
        try:
            if self._web_view is None:
                self._show_error("PyQt6-WebEngine is unavailable")
                return False
            self._web_view.setUrl(QUrl.fromLocalFile(os.path.abspath(path)))
            return True
        except Exception as e:
            self._show_error(f"Failed to load PDF: {e}")
            return False

    def load_csv(self, path: str) -> bool:
        try:
            with open(path, 'r', encoding='utf-8', newline='') as f:
                sample = f.read(4096)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
                except csv.Error:
                    dialect = csv.excel
                rows = list(csv.reader(f, dialect))
            if not rows:
                self._show_html("<div class='empty'>No tabular data.</div>", os.path.dirname(path))
                return True
            header = rows[0]
            body_rows = rows[1:]
            head_html = "".join(f"<th>{html.escape(cell)}</th>" for cell in header)
            body_html = []
            for row in body_rows:
                cells = "".join(f"<td>{html.escape(cell)}</td>" for cell in row)
                body_html.append(f"<tr>{cells}</tr>")
            table_html = (
                "<div class='table-shell'><table class='data-table'>"
                f"<thead><tr>{head_html}</tr></thead>"
                f"<tbody>{''.join(body_html)}</tbody>"
                "</table></div>"
            )
            self._show_html(table_html, os.path.dirname(path))
            return True
        except Exception as e:
            self._show_error(f"Failed to load CSV: {e}")
            return False

    def _show_error(self, message: str) -> None:
        self._show_html(f"<div class='error'>{html.escape(str(message or ''))}</div>")

    def _show_html(self, content: str, base_path: str = "") -> None:
        if self._web_view is None:
            if self._fallback_label is not None:
                self._fallback_label.setText(str(content or ""))
            return
        base_url = QUrl.fromLocalFile(os.path.abspath(base_path) + os.sep) if base_path else QUrl()
        self._web_view.setHtml(self._wrap_html(content), base_url)
    
    def _wrap_html(self, content: str) -> str:
        """
        包装 HTML 内容
        
        Args:
            content: HTML 内容
            
        Returns:
            str: 包装后的完整 HTML
        """
        return f"""
        <html>
        <head>
        <style>
            html, body {{ margin: 0; padding: 0; background: #ffffff; color: #1f2937; }}
            body {{ font-family: "Segoe UI", "SF Pro Display", "Roboto", "Microsoft YaHei UI", sans-serif; line-height: 1.6; }}
            .doc-root {{ padding: 24px; box-sizing: border-box; }}
            h1, h2, h3, h4, h5, h6 {{ color: #111827; margin: 1.2em 0 0.6em; }}
            p {{ margin: 0.75em 0; }}
            code {{ background-color: #f3f4f6; padding: 2px 5px; border-radius: 4px; font-family: "JetBrains Mono", "Cascadia Code", "SF Mono", monospace; }}
            pre {{ background-color: #f8fafc; padding: 12px; border-radius: 8px; overflow-x: auto; border: 1px solid #e5e7eb; font-family: "JetBrains Mono", "Cascadia Code", "SF Mono", monospace; }}
            table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
            th, td {{ border: 1px solid #e5e7eb; padding: 8px 10px; text-align: left; vertical-align: top; }}
            th {{ background-color: #f8fafc; font-weight: 600; }}
            .table-shell {{ overflow: auto; border: 1px solid #e5e7eb; border-radius: 10px; background: #ffffff; }}
            .data-table thead th {{ position: sticky; top: 0; background: #f8fafc; z-index: 1; }}
            .error {{ color: #991b1b; background: #fff1f2; border: 1px solid #fecdd3; border-radius: 10px; padding: 14px 16px; white-space: pre-wrap; }}
            .empty {{ color: #64748b; padding: 16px; }}
        </style>
        </head>
        <body>
        <div class="doc-root">{content}</div>
        </body>
        </html>
        """


__all__ = ["DocumentViewer"]
