from __future__ import annotations

import html
from typing import Iterable

from domain.llm.attachment_references import normalize_attachments, replace_inline_attachment_markers
from domain.llm.message_types import Attachment
from infrastructure.utils.markdown_renderer import render_markdown


class ConversationRichTextSupport:
    @staticmethod
    def render_markdown_html(text: str) -> str:
        if not text:
            return ""
        try:
            return render_markdown(text)
        except Exception:
            return html.escape(text).replace("\n", "<br>")

    @classmethod
    def render_user_content_html(
        cls,
        content: str,
        attachments: Iterable[Attachment],
    ) -> str:
        replaced = replace_inline_attachment_markers(
            content,
            normalize_attachments(attachments),
            cls._render_inline_attachment_html,
            lambda _reference_id, label: cls._escape_html(label),
        )
        return cls.render_markdown_html(replaced)

    @staticmethod
    def _render_inline_attachment_html(attachment: Attachment) -> str:
        path = str(attachment.path or "")
        name = str(attachment.name or "未命名文件")
        title = ConversationRichTextSupport._escape_attr(path or name)
        return (
            f'<span class="cai-inline-attachment" '
            f'data-cai-action="open-file" '
            f'data-cai-path="{ConversationRichTextSupport._escape_attr(path)}" '
            f'title="{title}">'
            f'<span class="cai-inline-attachment__label">{ConversationRichTextSupport._escape_html(name)}</span>'
            f'</span>'
        )

    @staticmethod
    def _escape_html(value: str) -> str:
        return html.escape(str(value or ""))

    @staticmethod
    def _escape_attr(value: str) -> str:
        escaped = html.escape(str(value or ""), quote=True)
        return escaped.replace("`", "&#96;")


__all__ = ["ConversationRichTextSupport"]
