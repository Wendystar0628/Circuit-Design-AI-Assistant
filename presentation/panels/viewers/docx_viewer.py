import base64
import os

from .web_document_viewer import WebDocumentViewer

_DOCX_STYLES = """
    .viewer-docx {
        font-size: 15px;
    }

    .viewer-docx p {
        text-align: left;
    }

    .viewer-docx img {
        display: block;
        margin: 1rem auto;
        border-radius: 8px;
    }

    .viewer-docx table {
        table-layout: auto;
    }

    .viewer-docx th {
        white-space: nowrap;
    }

    .viewer-docx .docx-empty {
        color: #64748b;
        text-align: center;
        padding: 2rem 0;
    }
"""


class DocxViewer(WebDocumentViewer):
    def load_docx(self, path: str) -> bool:
        try:
            import mammoth
        except ImportError:
            self.show_error("mammoth library not installed.\nInstall with: pip install mammoth")
            return False

        try:
            with open(path, "rb") as docx_file:
                result = mammoth.convert_to_html(
                    docx_file,
                    convert_image=mammoth.images.img_element(self._convert_image),
                )
            body = result.value.strip() or "<div class='docx-empty'>文档为空。</div>"
            body_html = (
                "<div class='viewer-shell'>"
                f"<article class='viewer-page viewer-docx'>{body}</article>"
                "</div>"
            )
            return self.load_html_document(
                title=os.path.basename(path),
                body_html=body_html,
                extra_styles=_DOCX_STYLES,
            )
        except Exception as e:
            self.show_error(f"Failed to load Word document: {e}")
            return False

    @staticmethod
    def _convert_image(image):
        with image.open() as image_bytes:
            encoded = base64.b64encode(image_bytes.read()).decode("ascii")
        return {
            "src": f"data:{image.content_type};base64,{encoded}",
        }


__all__ = ["DocxViewer"]
