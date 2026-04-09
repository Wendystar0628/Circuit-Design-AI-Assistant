import html
import os

from infrastructure.utils.markdown_renderer import render_markdown
from .web_document_viewer import WebDocumentViewer

_MARKDOWN_STYLES = """
    .viewer-markdown {
        font-size: 15px;
    }

    .viewer-markdown a {
        color: #2563eb;
        text-decoration: none;
    }

    .viewer-markdown a:hover {
        text-decoration: underline;
    }

    .viewer-markdown hr {
        border: 0;
        border-top: 1px solid #dbe3ef;
        margin: 2rem 0;
    }

    .viewer-markdown .katex-display {
        overflow-x: auto;
        overflow-y: hidden;
        margin: 1.25rem 0;
    }
"""


class MarkdownViewer(WebDocumentViewer):
    def load_markdown(self, path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            self.show_error(f"Failed to load Markdown: {e}")
            return False

        try:
            rendered_html = render_markdown(content)
        except Exception:
            rendered_html = f"<pre>{html.escape(content)}</pre>"

        katex_css = ""
        katex_js = ""
        auto_render_js = ""
        try:
            from infrastructure.utils.markdown_renderer import _load_katex_resources
            katex_css, katex_js, auto_render_js = _load_katex_resources()
        except Exception:
            pass

        extra_head_html = f"<style>{katex_css}</style>" if katex_css else ""
        extra_body_html = ""
        if katex_js and auto_render_js:
            extra_body_html = f"""
<script>{katex_js}</script>
<script>{auto_render_js}</script>
<script>
    document.addEventListener('DOMContentLoaded', function() {{
        if (typeof renderMathInElement !== 'undefined') {{
            renderMathInElement(document.body, {{
                delimiters: [
                    {{ left: '$$', right: '$$', display: true }},
                    {{ left: '$', right: '$', display: false }}
                ],
                throwOnError: false
            }});
        }}
    }});
</script>
"""

        body_html = (
            "<div class='viewer-shell'>"
            f"<article class='viewer-page viewer-markdown'>{rendered_html}</article>"
            "</div>"
        )
        return self.load_html_document(
            title=os.path.basename(path),
            body_html=body_html,
            base_path=os.path.dirname(path),
            extra_styles=_MARKDOWN_STYLES,
            extra_head_html=extra_head_html,
            extra_body_html=extra_body_html,
        )


__all__ = ["MarkdownViewer"]
