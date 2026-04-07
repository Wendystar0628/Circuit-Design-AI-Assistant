import base64
import mimetypes
import os
from typing import Any, Dict, Iterable, List, Optional

from langchain_core.messages import BaseMessage

from domain.llm.message_helpers import get_attachments, get_reasoning_content, get_role
from domain.llm.message_types import Attachment
from domain.rag.file_extractor import extract_attachment_text, resolve_attachment_type


class LLMMessageBuilder:
    def build_messages(self, messages: Iterable[BaseMessage]) -> List[Dict[str, Any]]:
        return [self.build_message(message) for message in messages]

    def build_message(self, message: BaseMessage) -> Dict[str, Any]:
        role = get_role(message)
        payload: Dict[str, Any] = {
            "role": role,
        }

        reasoning_content = get_reasoning_content(message)
        if reasoning_content:
            payload["reasoning_content"] = reasoning_content

        if role == "user":
            content = message.content if isinstance(message.content, str) else ""
            attachments = self._normalize_attachments(get_attachments(message))
            payload["content"] = self._build_user_content(content, attachments)
            return payload

        content = message.content
        if isinstance(content, (str, list)):
            payload["content"] = content
        else:
            payload["content"] = str(content or "")

        tool_call_id = getattr(message, "tool_call_id", "")
        if tool_call_id:
            payload["tool_call_id"] = tool_call_id

        tool_name = getattr(message, "name", "")
        if role == "tool" and tool_name:
            payload["name"] = tool_name

        return payload

    def _build_user_content(
        self,
        content: str,
        attachments: List[Attachment],
    ) -> str | List[Dict[str, Any]]:
        if not attachments:
            return content

        text_segments: List[str] = []
        image_parts: List[Dict[str, Any]] = []

        stripped_content = content.strip()
        if stripped_content:
            text_segments.append(stripped_content)

        for attachment in attachments:
            if attachment.type == "image":
                image_part = self._build_image_part(attachment)
                if image_part:
                    image_parts.append(image_part)
                else:
                    text_segments.append(f"[图片附件不可用: {attachment.name}]")
                continue

            file_text = self._build_file_text(attachment)
            if file_text:
                text_segments.append(file_text)

        merged_text = "\n\n".join(segment for segment in text_segments if segment).strip()
        if image_parts:
            parts: List[Dict[str, Any]] = [
                {"type": "text", "text": merged_text or "请分析我附加的图片。"}
            ]
            parts.extend(image_parts)
            return parts

        return merged_text

    def _build_file_text(self, attachment: Attachment) -> str:
        if not attachment.path or not os.path.isfile(attachment.path):
            return f"[附件不可用: {attachment.name}]"

        extracted = extract_attachment_text(attachment.path).strip()
        if extracted:
            return f"[附件 {attachment.name}]\n{extracted}"

        return f"[已附加文件 {attachment.name}，但当前无法提取可发送文本内容]"

    def _build_image_part(self, attachment: Attachment) -> Optional[Dict[str, Any]]:
        if not attachment.path or not os.path.isfile(attachment.path):
            return None

        mime_type = attachment.mime_type or self._guess_mime_type(attachment.path, attachment.type)
        try:
            with open(attachment.path, "rb") as file:
                image_data = base64.b64encode(file.read()).decode("ascii")
        except Exception:
            return None

        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime_type};base64,{image_data}",
            },
        }

    def _normalize_attachments(self, attachments: List[Attachment]) -> List[Attachment]:
        normalized: List[Attachment] = []
        for attachment in attachments or []:
            resolved_type = resolve_attachment_type(
                attachment.path,
                attachment.mime_type,
            )
            normalized.append(
                Attachment(
                    type=resolved_type,
                    path=attachment.path,
                    name=attachment.name,
                    mime_type=attachment.mime_type or self._guess_mime_type(attachment.path, resolved_type),
                    size=self._resolve_size(attachment.path, attachment.size),
                )
            )
        return normalized

    def _resolve_size(self, path: str, size: Any) -> int:
        try:
            resolved = int(size or 0)
        except Exception:
            resolved = 0

        if resolved > 0:
            return resolved

        if path and os.path.isfile(path):
            try:
                return os.path.getsize(path)
            except Exception:
                return 0

        return 0

    def _guess_mime_type(self, path: str, attachment_type: str) -> str:
        guessed, _ = mimetypes.guess_type(path)
        if guessed:
            return guessed
        if attachment_type == "image":
            return "image/png"
        return "application/octet-stream"


__all__ = ["LLMMessageBuilder"]
