import html
import os
from typing import Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

try:
    from PyQt6.QtWebEngineCore import QWebEngineSettings
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except ImportError:
    QWebEngineSettings = None
    QWebEngineView = None
    WEBENGINE_AVAILABLE = False

from presentation.core.web_resource_host import configure_app_web_view

_COMMON_STYLES = """
    :root {
        color-scheme: light;
    }

    * {
        box-sizing: border-box;
    }

    html, body {
        margin: 0;
        padding: 0;
        min-height: 100%;
    }

    body {
        font-family: "Segoe UI", "SF Pro Display", "Microsoft YaHei UI", sans-serif;
        color: #0f172a;
        background: #eef2f7;
    }

    .viewer-shell {
        min-height: 100vh;
        padding: 24px;
    }

    .viewer-page {
        width: min(100%, 1024px);
        margin: 0 auto;
        background: #ffffff;
        border: 1px solid #dbe3ef;
        border-radius: 16px;
        box-shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
        padding: 40px 48px;
    }

    .viewer-page h1,
    .viewer-page h2,
    .viewer-page h3,
    .viewer-page h4,
    .viewer-page h5,
    .viewer-page h6 {
        color: #0f172a;
        line-height: 1.25;
        margin: 1.25em 0 0.6em;
    }

    .viewer-page h1 {
        font-size: 2rem;
    }

    .viewer-page h2 {
        font-size: 1.6rem;
    }

    .viewer-page h3 {
        font-size: 1.3rem;
    }

    .viewer-page p,
    .viewer-page li {
        line-height: 1.75;
        font-size: 15px;
    }

    .viewer-page p {
        margin: 0 0 1em;
    }

    .viewer-page ul,
    .viewer-page ol {
        margin: 0 0 1em 1.5em;
        padding: 0;
    }

    .viewer-page img {
        max-width: 100%;
        height: auto;
    }

    .viewer-page table {
        width: 100%;
        border-collapse: collapse;
        margin: 1.25rem 0;
    }

    .viewer-page th,
    .viewer-page td {
        border: 1px solid #dbe3ef;
        padding: 10px 12px;
        text-align: left;
        vertical-align: top;
    }

    .viewer-page th {
        background: #f8fafc;
        font-weight: 600;
    }

    .viewer-page blockquote {
        margin: 1.25rem 0;
        padding: 0.75rem 1rem;
        border-left: 4px solid #cbd5e1;
        background: #f8fafc;
        color: #334155;
    }

    .viewer-page pre {
        overflow-x: auto;
        border-radius: 10px;
        background: #0f172a;
        color: #e2e8f0;
        padding: 14px 16px;
    }

    .viewer-page code {
        font-family: "JetBrains Mono", "Cascadia Code", "SF Mono", monospace;
    }

    .viewer-page :not(pre) > code {
        border-radius: 6px;
        background: #f1f5f9;
        color: #0f172a;
        padding: 2px 6px;
    }

    .error-shell {
        min-height: 100vh;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 24px;
    }

    .error-card {
        width: min(100%, 720px);
        background: #ffffff;
        border: 1px solid #fecdd3;
        border-radius: 16px;
        box-shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
        padding: 24px;
    }

    .error-card h1 {
        margin: 0 0 12px;
        font-size: 20px;
        color: #be123c;
    }

    .error-card pre {
        margin: 0;
        white-space: pre-wrap;
        word-break: break-word;
        background: #fff1f2;
        border-radius: 12px;
        padding: 16px;
        color: #881337;
        overflow: auto;
    }

    @media (max-width: 960px) {
        .viewer-shell {
            padding: 16px;
        }

        .viewer-page {
            padding: 24px 20px;
            border-radius: 12px;
        }
    }
"""


class WebDocumentViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._web_view = None
        self._fallback_label = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if not WEBENGINE_AVAILABLE:
            fallback = QLabel("请安装 PyQt6-WebEngine", self)
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            layout.addWidget(fallback)
            self._fallback_label = fallback
            return

        self._web_view = QWebEngineView(self)
        configure_app_web_view(self._web_view)
        settings = self._web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        layout.addWidget(self._web_view)

    @property
    def web_view(self) -> Optional[QWebEngineView]:
        return self._web_view

    def load_full_html(self, html_text: str, base_path: str = "") -> bool:
        if self._web_view is None:
            if self._fallback_label is not None:
                self._fallback_label.setText(str(html_text or ""))
            return False
        base_url = QUrl.fromLocalFile(os.path.abspath(base_path) + os.sep) if base_path else QUrl()
        self._web_view.setHtml(html_text, base_url)
        return True

    def load_html_document(
        self,
        *,
        title: str,
        body_html: str,
        base_path: str = "",
        extra_styles: str = "",
        extra_head_html: str = "",
        extra_body_html: str = "",
    ) -> bool:
        return self.load_full_html(
            self._build_html_document(
                title=title,
                body_html=body_html,
                extra_styles=extra_styles,
                extra_head_html=extra_head_html,
                extra_body_html=extra_body_html,
            ),
            base_path=base_path,
        )

    def show_error(self, message: str, title: str = "预览失败") -> None:
        error_html = (
            "<div class='error-shell'>"
            "<section class='error-card'>"
            f"<h1>{html.escape(title)}</h1>"
            f"<pre>{html.escape(str(message or ''))}</pre>"
            "</section>"
            "</div>"
        )
        self.load_html_document(title=title, body_html=error_html)

    def _build_html_document(
        self,
        *,
        title: str,
        body_html: str,
        extra_styles: str = "",
        extra_head_html: str = "",
        extra_body_html: str = "",
    ) -> str:
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset=\"UTF-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
    <title>{html.escape(title or '')}</title>
    <style>{_COMMON_STYLES}</style>
    <style>{extra_styles}</style>
    {extra_head_html}
</head>
<body>
    {body_html}
    {extra_body_html}
</body>
</html>
"""


__all__ = ["WebDocumentViewer", "WEBENGINE_AVAILABLE"]
