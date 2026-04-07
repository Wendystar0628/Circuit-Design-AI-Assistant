import re
import uuid
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional
from urllib.parse import quote, unquote

from domain.llm.message_types import Attachment

INLINE_ATTACHMENT_PLACEMENT = "inline"
GALLERY_ATTACHMENT_PLACEMENT = "gallery"
INLINE_ATTACHMENT_PATTERN = re.compile(r"\[\[attachment:([A-Za-z0-9_-]+)\|([^\]]*)\]\]")


@dataclass(frozen=True)
class AttachmentContentSegment:
    kind: str
    text: str = ""
    attachment: Optional[Attachment] = None
    label: str = ""


def ensure_attachment_reference_id(reference_id: str = "") -> str:
    return (reference_id or "").strip() or uuid.uuid4().hex


def normalize_attachment(attachment: Attachment) -> Attachment:
    placement = (attachment.placement or "").strip().lower()
    if placement not in {INLINE_ATTACHMENT_PLACEMENT, GALLERY_ATTACHMENT_PLACEMENT}:
        placement = GALLERY_ATTACHMENT_PLACEMENT
    reference_id = attachment.reference_id or ""
    if placement == INLINE_ATTACHMENT_PLACEMENT:
        reference_id = ensure_attachment_reference_id(reference_id)
    return Attachment(
        type=attachment.type,
        path=attachment.path,
        name=attachment.name,
        mime_type=attachment.mime_type,
        size=attachment.size,
        placement=placement,
        reference_id=reference_id,
    )


def normalize_attachments(attachments: Iterable[Attachment]) -> List[Attachment]:
    return [normalize_attachment(attachment) for attachment in attachments or [] if isinstance(attachment, Attachment)]


def is_inline_attachment(attachment: Attachment) -> bool:
    return normalize_attachment(attachment).placement == INLINE_ATTACHMENT_PLACEMENT


def is_gallery_attachment(attachment: Attachment) -> bool:
    return normalize_attachment(attachment).placement == GALLERY_ATTACHMENT_PLACEMENT


def build_inline_attachment_marker(reference_id: str, name: str) -> str:
    return f"[[attachment:{ensure_attachment_reference_id(reference_id)}|{quote(name or '', safe='')}]]"


def build_attachment_marker_for(attachment: Attachment) -> str:
    normalized = normalize_attachment(attachment)
    if normalized.placement != INLINE_ATTACHMENT_PLACEMENT:
        raise ValueError("Only inline attachments can be serialized as inline markers")
    return build_inline_attachment_marker(normalized.reference_id, normalized.name)


def parse_attachment_content(content: str, attachments: Iterable[Attachment]) -> List[AttachmentContentSegment]:
    text = content or ""
    normalized = normalize_attachments(attachments)
    attachment_by_reference = {
        attachment.reference_id: attachment
        for attachment in normalized
        if attachment.reference_id
    }
    segments: List[AttachmentContentSegment] = []
    cursor = 0
    for match in INLINE_ATTACHMENT_PATTERN.finditer(text):
        start, end = match.span()
        if start > cursor:
            segments.append(AttachmentContentSegment(kind="text", text=text[cursor:start]))
        reference_id = match.group(1)
        label = unquote(match.group(2) or "")
        attachment = attachment_by_reference.get(reference_id)
        if attachment is not None:
            segments.append(
                AttachmentContentSegment(
                    kind="attachment",
                    attachment=attachment,
                    label=attachment.name or label,
                )
            )
        else:
            segments.append(AttachmentContentSegment(kind="text", text=label or ""))
        cursor = end
    if cursor < len(text):
        segments.append(AttachmentContentSegment(kind="text", text=text[cursor:]))
    if not segments:
        segments.append(AttachmentContentSegment(kind="text", text=text))
    return segments


def replace_inline_attachment_markers(
    content: str,
    attachments: Iterable[Attachment],
    replacement_for_attachment: Callable[[Attachment], str],
    replacement_for_missing: Optional[Callable[[str, str], str]] = None,
) -> str:
    normalized = normalize_attachments(attachments)
    attachment_by_reference = {
        attachment.reference_id: attachment
        for attachment in normalized
        if attachment.reference_id
    }

    def _replace(match: re.Match[str]) -> str:
        reference_id = match.group(1)
        label = unquote(match.group(2) or "")
        attachment = attachment_by_reference.get(reference_id)
        if attachment is not None:
            return replacement_for_attachment(attachment)
        if replacement_for_missing is not None:
            return replacement_for_missing(reference_id, label)
        return label

    return INLINE_ATTACHMENT_PATTERN.sub(_replace, content or "")


def extract_inline_reference_ids(content: str) -> List[str]:
    return [match.group(1) for match in INLINE_ATTACHMENT_PATTERN.finditer(content or "")]


__all__ = [
    "AttachmentContentSegment",
    "INLINE_ATTACHMENT_PATTERN",
    "INLINE_ATTACHMENT_PLACEMENT",
    "GALLERY_ATTACHMENT_PLACEMENT",
    "ensure_attachment_reference_id",
    "normalize_attachment",
    "normalize_attachments",
    "is_inline_attachment",
    "is_gallery_attachment",
    "build_inline_attachment_marker",
    "build_attachment_marker_for",
    "parse_attachment_content",
    "replace_inline_attachment_markers",
    "extract_inline_reference_ids",
]
