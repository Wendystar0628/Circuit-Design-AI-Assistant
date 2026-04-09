import base64
import html
import os

from .web_document_viewer import WebDocumentViewer

_DOCX_STYLES = """
    .viewer-docx {
        font-size: 15px;
    }

    .viewer-docx h1,
    .viewer-docx h2,
    .viewer-docx h3,
    .viewer-docx h4,
    .viewer-docx h5,
    .viewer-docx h6 {
        page-break-after: avoid;
    }

    .viewer-docx p,
    .viewer-docx li {
        orphans: 3;
        widows: 3;
    }

    .viewer-docx img {
        display: block;
        margin: 1rem auto;
        border-radius: 8px;
        max-width: 100%;
        height: auto;
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

_RELATIONSHIP_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_DRAWINGML_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


class DocxViewer(WebDocumentViewer):
    def load_docx(self, path: str) -> bool:
        try:
            from docx import Document
        except ImportError:
            self.show_error("python-docx 未安装，无法预览 DOCX。")
            return False

        try:
            document = Document(path)
            body = _DocxHtmlRenderer(document).render() or "<div class='docx-empty'>文档为空。</div>"
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
            self.show_error(f"DOCX 加载失败：{e}")
            return False


class _DocxHtmlRenderer:
    def __init__(self, document):
        self._document = document

    def render(self) -> str:
        return self._render_parent(self._document)

    def _render_parent(self, parent) -> str:
        parts: list[str] = []
        active_list: str | None = None
        for block in self._iter_block_items(parent):
            if block.__class__.__name__ == "Paragraph":
                list_tag = self._list_tag_for_paragraph(block)
                if list_tag:
                    if active_list != list_tag:
                        if active_list is not None:
                            parts.append(f"</{active_list}>")
                        parts.append(f"<{list_tag}>")
                        active_list = list_tag
                    parts.append(self._render_list_item(block))
                    continue

                if active_list is not None:
                    parts.append(f"</{active_list}>")
                    active_list = None
                paragraph_html = self._render_paragraph(block)
                if paragraph_html:
                    parts.append(paragraph_html)
                continue

            if active_list is not None:
                parts.append(f"</{active_list}>")
                active_list = None
            parts.append(self._render_table(block))

        if active_list is not None:
            parts.append(f"</{active_list}>")
        return "".join(parts)

    def _iter_block_items(self, parent):
        from docx.document import Document as DocxDocument
        from docx.oxml.table import CT_Tbl
        from docx.oxml.text.paragraph import CT_P
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        parent_element = parent.element.body if isinstance(parent, DocxDocument) else parent._element
        for child in parent_element.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, parent)
            elif isinstance(child, CT_Tbl):
                yield Table(child, parent)

    def _render_paragraph(self, paragraph) -> str:
        content = self._render_paragraph_content(paragraph)
        if not content.strip():
            return ""

        tag = self._block_tag_for_paragraph(paragraph)
        style_attr = self._style_attr(self._paragraph_styles(paragraph))
        return f"<{tag}{style_attr}>{content}</{tag}>"

    def _render_list_item(self, paragraph) -> str:
        content = self._render_paragraph_content(paragraph)
        if not content.strip():
            return ""
        style_attr = self._style_attr(self._paragraph_styles(paragraph))
        return f"<li{style_attr}>{content}</li>"

    def _render_paragraph_content(self, paragraph) -> str:
        parts: list[str] = []
        for run in paragraph.runs:
            rendered = self._render_run(run, paragraph.part)
            if rendered:
                parts.append(rendered)
        if not parts:
            text = html.escape(paragraph.text or "")
            return text.replace("\n", "<br>")
        return "".join(parts)

    def _render_run(self, run, part) -> str:
        chunks: list[str] = []
        for child in run._element:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "t":
                chunks.append(html.escape(child.text or ""))
            elif tag in {"tab"}:
                chunks.append("&emsp;")
            elif tag in {"br", "cr"}:
                chunks.append("<br>")
            elif tag == "drawing":
                chunks.append(self._render_drawing(child, part))
        content = "".join(chunks)
        if not content:
            return ""

        styles: list[str] = []
        color = getattr(getattr(getattr(run.font, "color", None), "rgb", None), "__str__", None)
        if color is not None and getattr(run.font.color, "rgb", None) is not None:
            styles.append(f"color: #{run.font.color.rgb}")
        if getattr(run.font, "size", None) is not None and getattr(run.font.size, "pt", None) is not None:
            styles.append(f"font-size: {run.font.size.pt:.2f}pt")
        if run.bold:
            content = f"<strong>{content}</strong>"
        if run.italic:
            content = f"<em>{content}</em>"
        if run.underline:
            content = f"<span style='text-decoration: underline;'>{content}</span>"
        if styles:
            content = f"<span style='{'; '.join(styles)}'>{content}</span>"
        return content

    def _render_drawing(self, drawing_element, part) -> str:
        images: list[str] = []
        for element in drawing_element.iter():
            if element.tag != f"{_DRAWINGML_NS}blip":
                continue
            rel_id = element.get(f"{_RELATIONSHIP_NS}embed") or element.get(f"{_RELATIONSHIP_NS}link")
            if not rel_id:
                continue
            image_part = part.related_parts.get(rel_id)
            if image_part is None:
                continue
            encoded = base64.b64encode(image_part.blob).decode("ascii")
            images.append(f"<img src='data:{image_part.content_type};base64,{encoded}' alt='' />")
        return "".join(images)

    def _render_table(self, table) -> str:
        rows_html: list[str] = []
        for row_index, row in enumerate(table.rows):
            cell_tag = "th" if row_index == 0 else "td"
            cells_html: list[str] = []
            for cell in row.cells:
                cell_content = self._render_parent(cell).strip() or "&nbsp;"
                cells_html.append(f"<{cell_tag}>{cell_content}</{cell_tag}>")
            rows_html.append(f"<tr>{''.join(cells_html)}</tr>")
        return f"<table><tbody>{''.join(rows_html)}</tbody></table>"

    def _block_tag_for_paragraph(self, paragraph) -> str:
        style_name = self._style_name(paragraph)
        if style_name.startswith("heading"):
            digits = "".join(ch for ch in style_name if ch.isdigit())
            level = min(max(int(digits or 1), 1), 6)
            return f"h{level}"
        return "p"

    def _list_tag_for_paragraph(self, paragraph) -> str | None:
        style_name = self._style_name(paragraph)
        if "list bullet" in style_name or style_name.endswith("bullet"):
            return "ul"
        if "list number" in style_name or style_name.endswith("number"):
            return "ol"
        p_pr = getattr(paragraph._p, "pPr", None)
        if p_pr is not None and getattr(p_pr, "numPr", None) is not None:
            return "ol"
        return None

    def _style_name(self, paragraph) -> str:
        return str(getattr(getattr(paragraph, "style", None), "name", "") or "").strip().lower()

    def _paragraph_styles(self, paragraph) -> list[str]:
        styles: list[str] = []
        alignment = getattr(paragraph, "alignment", None)
        alignment_map = {
            0: "left",
            1: "center",
            2: "right",
            3: "justify",
            7: "left",
            8: "justify",
        }
        if alignment is not None:
            align_value = alignment_map.get(int(alignment), None)
            if align_value is not None:
                styles.append(f"text-align: {align_value}")

        paragraph_format = paragraph.paragraph_format
        left_indent = getattr(getattr(paragraph_format, "left_indent", None), "pt", None)
        first_line_indent = getattr(getattr(paragraph_format, "first_line_indent", None), "pt", None)
        space_before = getattr(getattr(paragraph_format, "space_before", None), "pt", None)
        space_after = getattr(getattr(paragraph_format, "space_after", None), "pt", None)
        if left_indent:
            styles.append(f"margin-left: {left_indent:.2f}pt")
        if first_line_indent:
            styles.append(f"text-indent: {first_line_indent:.2f}pt")
        if space_before:
            styles.append(f"margin-top: {space_before:.2f}pt")
        if space_after:
            styles.append(f"margin-bottom: {space_after:.2f}pt")
        return styles

    @staticmethod
    def _style_attr(styles: list[str]) -> str:
        if not styles:
            return ""
        return f" style=\"{'; '.join(styles)}\""


__all__ = ["DocxViewer"]
