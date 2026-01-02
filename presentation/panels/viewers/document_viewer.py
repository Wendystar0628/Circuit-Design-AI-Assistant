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

from PyQt6.QtWidgets import QTextEdit


class DocumentViewer(QTextEdit):
    """
    文档预览组件
    
    功能：
    - Markdown 渲染预览
    - Word 文档文本提取预览
    - PDF 文本提取预览
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 设置只读
        self.setReadOnly(True)
        
        # 设置样式
        self.setStyleSheet("""
            QTextEdit {
                background-color: #ffffff;
                color: #333333;
                border: none;
                padding: 20px;
                font-family: "Segoe UI", "SF Pro Display", "Roboto", "Microsoft YaHei UI", sans-serif;
                font-size: 14px;
                line-height: 1.6;
            }
        """)
    
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
            
            # 尝试使用 markdown 库渲染
            try:
                import markdown
                html = markdown.markdown(
                    content,
                    extensions=['tables', 'fenced_code', 'codehilite']
                )
                self.setHtml(self._wrap_html(html))
            except ImportError:
                # 如果没有 markdown 库，显示原始文本
                self.setPlainText(content)
            
            return True
        except Exception as e:
            self.setPlainText(f"Failed to load Markdown: {e}")
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
            doc = Document(path)
            
            # 提取段落文本
            paragraphs = []
            for para in doc.paragraphs:
                if para.text.strip():
                    paragraphs.append(f"<p>{para.text}</p>")
            
            html = "\n".join(paragraphs)
            self.setHtml(self._wrap_html(html))
            return True
        except ImportError:
            self.setPlainText("python-docx library not installed.\nInstall with: pip install python-docx")
            return False
        except Exception as e:
            self.setPlainText(f"Failed to load Word document: {e}")
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
            import fitz  # PyMuPDF
            doc = fitz.open(path)
            
            # 提取所有页面的文本
            text_parts = []
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text()
                if text.strip():
                    text_parts.append(f"<h3>Page {page_num + 1}</h3>")
                    text_parts.append(f"<pre>{text}</pre>")
            
            doc.close()
            
            html = "\n".join(text_parts)
            self.setHtml(self._wrap_html(html))
            return True
        except ImportError:
            self.setPlainText("PyMuPDF library not installed.\nInstall with: pip install PyMuPDF")
            return False
        except Exception as e:
            self.setPlainText(f"Failed to load PDF: {e}")
            return False
    
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
            body {{ font-family: "Segoe UI", "SF Pro Display", "Roboto", "Microsoft YaHei UI", sans-serif; line-height: 1.6; }}
            h1, h2, h3 {{ color: #333; }}
            code {{ background-color: #f5f5f5; padding: 2px 5px; border-radius: 3px; font-family: "JetBrains Mono", "Cascadia Code", "SF Mono", monospace; }}
            pre {{ background-color: #f5f5f5; padding: 10px; border-radius: 5px; overflow-x: auto; font-family: "JetBrains Mono", "Cascadia Code", "SF Mono", monospace; }}
            table {{ border-collapse: collapse; width: 100%; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f5f5f5; }}
        </style>
        </head>
        <body>
        {content}
        </body>
        </html>
        """


__all__ = ["DocumentViewer"]
