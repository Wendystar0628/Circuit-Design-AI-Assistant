from __future__ import annotations

import mimetypes
import os
from typing import Any, Dict

from domain.llm.attachment_references import (
    GALLERY_ATTACHMENT_PLACEMENT,
    INLINE_ATTACHMENT_PLACEMENT,
    ensure_attachment_reference_id,
    normalize_attachment,
)
from domain.llm.message_types import Attachment
from domain.rag.file_extractor import resolve_attachment_type

MAX_IMAGE_SIZE_MB = 10


class ConversationAttachmentError(ValueError):
    pass


class ConversationAttachmentSupport:
    @staticmethod
    def build_attachment_from_path(path: str) -> Attachment:
        normalized_path = str(path or "").strip()
        if not normalized_path or not os.path.isfile(normalized_path):
            raise ConversationAttachmentError(f"File not found: {normalized_path}")

        mime_type, _ = mimetypes.guess_type(normalized_path)
        resolved_type = resolve_attachment_type(normalized_path, mime_type or "")
        file_size = os.path.getsize(normalized_path)

        if resolved_type == "image" and file_size > MAX_IMAGE_SIZE_MB * 1024 * 1024:
            raise ConversationAttachmentError(
                f"Image size exceeds {MAX_IMAGE_SIZE_MB}MB limit"
            )

        placement = (
            GALLERY_ATTACHMENT_PLACEMENT
            if resolved_type == "image"
            else INLINE_ATTACHMENT_PLACEMENT
        )
        reference_id = "" if placement == GALLERY_ATTACHMENT_PLACEMENT else ensure_attachment_reference_id()
        return Attachment(
            type=resolved_type,
            path=normalized_path,
            name=os.path.basename(normalized_path),
            mime_type=mime_type or (
                "image/png" if resolved_type == "image" else "application/octet-stream"
            ),
            size=file_size,
            placement=placement,
            reference_id=reference_id,
        )

    @staticmethod
    def normalize_attachment_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return Attachment(type="file", path="", name="").to_dict()
        return normalize_attachment(Attachment.from_dict(payload)).to_dict()

    @staticmethod
    def attachment_from_payload(payload: Dict[str, Any]) -> Attachment:
        if not isinstance(payload, dict):
            raise ConversationAttachmentError("Invalid attachment payload")
        return normalize_attachment(Attachment.from_dict(payload))


__all__ = [
    "ConversationAttachmentError",
    "ConversationAttachmentSupport",
    "MAX_IMAGE_SIZE_MB",
]
