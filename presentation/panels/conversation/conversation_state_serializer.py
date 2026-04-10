from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from domain.llm.attachment_references import (
    build_attachment_marker_for,
    is_inline_attachment,
    normalize_attachments,
)
from domain.llm.conversation_rollback_service import ConversationRollbackPreview
from domain.llm.message_types import Attachment
from domain.llm.session_state_manager import SessionInfo
from presentation.panels.conversation.conversation_rich_text_support import (
    ConversationRichTextSupport,
)
from presentation.panels.conversation.conversation_view_model import (
    AgentStep,
    AgentStepToolCall,
    DisplayMessage,
    SuggestionItem,
)


class ConversationStateSerializer:
    """Serialize authoritative conversation state into frontend-facing payloads."""

    def serialize_main_state(
        self,
        *,
        session_id: str,
        session_name: str,
        messages: Sequence[DisplayMessage],
        runtime_steps: Sequence[AgentStep],
        usage_info: Optional[Dict[str, Any]] = None,
        pending_workspace_edit_summary: Optional[Dict[str, Any]] = None,
        model_display_name: str = "",
        action_mode: str = "send",
        action_status: str = "",
        draft_attachments: Optional[Sequence[Attachment]] = None,
        clear_draft_nonce: int = 0,
        history_overlay: Optional[Dict[str, Any]] = None,
        rollback_overlay: Optional[Dict[str, Any]] = None,
        confirm_dialog: Optional[Dict[str, Any]] = None,
        notice_dialog: Optional[Dict[str, Any]] = None,
        is_loading: bool = False,
        can_send: bool = True,
        send_in_progress: bool = False,
        rollback_in_progress: bool = False,
        active_surface: str = "conversation",
        rag_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        usage_snapshot = self.serialize_usage_info(usage_info)
        pending_summary = self.serialize_pending_workspace_edit_summary(
            pending_workspace_edit_summary
        )
        serialized_messages = [
            self.serialize_display_message(message) for message in (messages or [])
        ]
        serialized_runtime_steps = [
            self.serialize_agent_step(step) for step in (runtime_steps or [])
        ]
        has_pending_workspace_edits = bool(pending_summary.get("file_count", 0))

        return {
            "ui": {
                "active_surface": self.serialize_active_surface(active_surface),
            },
            "session": {
                "id": str(session_id or ""),
                "name": str(session_name or ""),
            },
            "conversation": {
                "messages": serialized_messages,
                "runtime_steps": serialized_runtime_steps,
                "message_count": len(serialized_messages),
                "is_loading": bool(is_loading),
                "can_send": bool(can_send),
            },
            "composer": {
                "usage": usage_snapshot,
                "compress_button_state": usage_snapshot.get("state", "normal"),
                "model_display_name": str(model_display_name or ""),
                "action_mode": str(action_mode or "send"),
                "action_status": str(action_status or ""),
                "draft_attachments": [
                    self.serialize_attachment(attachment)
                    for attachment in normalize_attachments(draft_attachments or [])
                ],
                "clear_draft_nonce": max(0, int(clear_draft_nonce or 0)),
                "pending_workspace_edit_summary": pending_summary,
            },
            "view_flags": {
                "has_messages": bool(serialized_messages),
                "has_runtime_steps": bool(serialized_runtime_steps),
                "has_pending_workspace_edits": has_pending_workspace_edits,
                "is_busy": bool(send_in_progress or rollback_in_progress or is_loading),
                "send_in_progress": bool(send_in_progress),
                "rollback_in_progress": bool(rollback_in_progress),
            },
            "overlays": {
                "history": self.serialize_history_overlay_state(history_overlay),
                "rollback": self.serialize_rollback_overlay_state(rollback_overlay),
                "confirm": self.serialize_confirm_dialog_state(confirm_dialog),
                "notice": self.serialize_notice_dialog_state(notice_dialog),
            },
            "rag": self.serialize_rag_state(rag_state),
        }

    def serialize_active_surface(self, active_surface: str) -> str:
        normalized_surface = str(active_surface or "conversation")
        return normalized_surface if normalized_surface in {"conversation", "rag"} else "conversation"

    def serialize_rag_state(self, rag_state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        data = rag_state if isinstance(rag_state, dict) else {}
        status = data.get("status", {}) if isinstance(data.get("status", {}), dict) else {}
        stats = data.get("stats", {}) if isinstance(data.get("stats", {}), dict) else {}
        progress = data.get("progress", {}) if isinstance(data.get("progress", {}), dict) else {}
        actions = data.get("actions", {}) if isinstance(data.get("actions", {}), dict) else {}
        search = data.get("search", {}) if isinstance(data.get("search", {}), dict) else {}
        info = data.get("info", {}) if isinstance(data.get("info", {}), dict) else {}

        serialized_files: List[Dict[str, Any]] = []
        for item in data.get("files", []) or []:
            if not isinstance(item, dict):
                continue
            serialized_files.append(
                {
                    "path": str(item.get("path", "") or ""),
                    "relative_path": str(item.get("relative_path", "") or ""),
                    "status": str(item.get("status", "pending") or "pending"),
                    "status_label": str(item.get("status_label", "") or ""),
                    "chunks_count": max(0, int(item.get("chunks_count", 0) or 0)),
                    "indexed_at": str(item.get("indexed_at", "") or ""),
                    "tooltip": str(item.get("tooltip", "") or ""),
                }
            )

        return {
            "status": {
                "phase": str(status.get("phase", "idle") or "idle"),
                "label": str(status.get("label", "") or ""),
                "tone": str(status.get("tone", "neutral") or "neutral"),
            },
            "stats": {
                "total_files": max(0, int(stats.get("total_files", 0) or 0)),
                "processed": max(0, int(stats.get("processed", 0) or 0)),
                "failed": max(0, int(stats.get("failed", 0) or 0)),
                "excluded": max(0, int(stats.get("excluded", 0) or 0)),
                "total_chunks": max(0, int(stats.get("total_chunks", 0) or 0)),
                "total_entities": max(0, int(stats.get("total_entities", 0) or 0)),
                "total_relations": max(0, int(stats.get("total_relations", 0) or 0)),
                "storage_size_mb": max(0.0, float(stats.get("storage_size_mb", 0.0) or 0.0)),
            },
            "progress": {
                "is_visible": bool(progress.get("is_visible", False)),
                "processed": max(0, int(progress.get("processed", 0) or 0)),
                "total": max(0, int(progress.get("total", 0) or 0)),
                "current_file": str(progress.get("current_file", "") or ""),
            },
            "actions": {
                "can_reindex": bool(actions.get("can_reindex", False)),
                "can_clear": bool(actions.get("can_clear", False)),
                "can_search": bool(actions.get("can_search", False)),
                "is_indexing": bool(actions.get("is_indexing", False)),
            },
            "files": serialized_files,
            "search": {
                "is_running": bool(search.get("is_running", False)),
                "result_text": str(search.get("result_text", "") or ""),
            },
            "info": {
                "message": str(info.get("message", "") or ""),
                "tone": str(info.get("tone", "neutral") or "neutral"),
            },
        }

    def serialize_usage_info(self, usage_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        data = usage_info if isinstance(usage_info, dict) else {}
        return {
            "ratio": max(0.0, min(1.0, float(data.get("ratio", 0.0) or 0.0))),
            "current_tokens": max(0, int(data.get("current_tokens", 0) or 0)),
            "max_tokens": max(0, int(data.get("max_tokens", 0) or 0)),
            "input_limit": max(0, int(data.get("input_limit", 0) or 0)),
            "output_reserve": max(0, int(data.get("output_reserve", 0) or 0)),
            "state": str(data.get("state", "normal") or "normal"),
            "message_count": max(0, int(data.get("message_count", 0) or 0)),
        }

    def serialize_pending_workspace_edit_summary(
        self,
        summary_state: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        data = summary_state if isinstance(summary_state, dict) else {}
        files: List[Dict[str, Any]] = []
        for item in data.get("files", []) or []:
            if not isinstance(item, dict):
                continue
            file_path = str(item.get("path", "") or "")
            if not file_path:
                continue
            files.append(
                {
                    "path": file_path,
                    "relative_path": str(item.get("relative_path", file_path) or file_path),
                    "added_lines": max(0, int(item.get("added_lines", 0) or 0)),
                    "deleted_lines": max(0, int(item.get("deleted_lines", 0) or 0)),
                }
            )

        return {
            "file_count": len(files),
            "added_lines": max(
                0,
                int(
                    data.get(
                        "added_lines",
                        sum(int(item["added_lines"]) for item in files),
                    )
                    or 0
                ),
            ),
            "deleted_lines": max(
                0,
                int(
                    data.get(
                        "deleted_lines",
                        sum(int(item["deleted_lines"]) for item in files),
                    )
                    or 0
                ),
            ),
            "files": files,
        }

    def serialize_attachment(self, attachment: Attachment) -> Dict[str, Any]:
        if isinstance(attachment, Attachment):
            normalized_attachment = normalize_attachments([attachment])[0]
            payload = normalized_attachment.to_dict()
            payload["inline_marker"] = (
                build_attachment_marker_for(normalized_attachment)
                if is_inline_attachment(normalized_attachment)
                else ""
            )
            return payload
        if isinstance(attachment, dict):
            normalized_attachment = normalize_attachments([Attachment.from_dict(attachment)])[0]
            payload = normalized_attachment.to_dict()
            payload["inline_marker"] = (
                build_attachment_marker_for(normalized_attachment)
                if is_inline_attachment(normalized_attachment)
                else ""
            )
            return payload
        return Attachment(type="file", path="", name="").to_dict()

    def serialize_suggestion(self, suggestion: SuggestionItem) -> Dict[str, Any]:
        return {
            "id": str(suggestion.id or ""),
            "label": str(suggestion.label or ""),
            "value": str(suggestion.value or ""),
            "description": str(suggestion.description or ""),
            "is_recommended": bool(suggestion.is_recommended),
        }

    def serialize_tool_call(self, tool_call: AgentStepToolCall) -> Dict[str, Any]:
        return {
            "tool_call_id": str(tool_call.tool_call_id or ""),
            "tool_name": str(tool_call.tool_name or ""),
            "arguments": dict(tool_call.arguments or {}),
            "result_content": str(tool_call.result_content or ""),
            "is_error": bool(tool_call.is_error),
            "details": dict(tool_call.details or {}),
        }

    def serialize_agent_step(self, step: AgentStep) -> Dict[str, Any]:
        content = str(step.content or "")
        reasoning_content = str(step.reasoning_content or "")
        return {
            "step_index": max(1, int(step.step_index or 1)),
            "step_id": str(step.step_id or ""),
            "content": content,
            "content_html": ConversationRichTextSupport.render_markdown_html(content),
            "reasoning_content": reasoning_content,
            "reasoning_content_html": ConversationRichTextSupport.render_markdown_html(reasoning_content),
            "tool_calls": [
                self.serialize_tool_call(tool_call) for tool_call in (step.tool_calls or [])
            ],
            "web_search_query": str(step.web_search_query or ""),
            "web_search_results": list(step.web_search_results or []),
            "web_search_message": str(step.web_search_message or ""),
            "web_search_state": str(step.web_search_state or "idle"),
            "is_complete": bool(step.is_complete),
            "is_partial": bool(step.is_partial),
            "stop_reason": str(step.stop_reason or ""),
        }

    def serialize_display_message(self, message: DisplayMessage) -> Dict[str, Any]:
        attachments = normalize_attachments(message.attachments or [])
        content = str(message.content or "")
        role = str(message.role or "assistant")
        if role == "user":
            content_html = ConversationRichTextSupport.render_user_content_html(
                content,
                attachments,
            )
        else:
            content_html = ConversationRichTextSupport.render_markdown_html(content)
        return {
            "id": str(message.id or ""),
            "role": role,
            "content": content,
            "content_html": content_html,
            "attachments": [
                self.serialize_attachment(attachment)
                for attachment in attachments
            ],
            "agent_steps": [
                self.serialize_agent_step(step) for step in (message.agent_steps or [])
            ],
            "suggestions": [
                self.serialize_suggestion(suggestion)
                for suggestion in (message.suggestions or [])
            ],
            "status_summary": str(message.status_summary or ""),
            "suggestion_state": str(message.suggestion_state or ""),
            "selected_suggestion_id": str(message.selected_suggestion_id or ""),
            "can_rollback": bool(message.can_rollback),
        }

    def serialize_history_state(
        self,
        *,
        sessions: Sequence[SessionInfo],
        current_session_id: str,
        selected_session_id: str = "",
        preview_messages: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return {
            "current_session_id": str(current_session_id or ""),
            "selected_session_id": str(selected_session_id or current_session_id or ""),
            "sessions": [
                self.serialize_session_info(session) for session in (sessions or [])
            ],
            "preview_messages": [
                self.serialize_session_message(message)
                for message in (preview_messages or [])
            ],
        }

    def serialize_history_overlay_state(
        self,
        history_state: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        data = history_state if isinstance(history_state, dict) else {}
        export_dialog = (
            data.get("export_dialog", {})
            if isinstance(data.get("export_dialog", {}), dict)
            else {}
        )
        overlay_state = self.serialize_history_state(
            sessions=data.get("sessions", []),
            current_session_id=str(data.get("current_session_id", "") or ""),
            selected_session_id=str(data.get("selected_session_id", "") or ""),
            preview_messages=data.get("preview_messages", []),
        )
        overlay_state.update(
            {
                "is_open": bool(data.get("is_open", False)),
                "is_loading": bool(data.get("is_loading", False)),
                "error_message": str(data.get("error_message", "") or ""),
                "export_dialog": {
                    "is_open": bool(export_dialog.get("is_open", False)),
                    "session_id": str(export_dialog.get("session_id", "") or ""),
                    "export_format": str(export_dialog.get("export_format", "md") or "md"),
                    "file_path": str(export_dialog.get("file_path", "") or ""),
                },
            }
        )
        return overlay_state

    def serialize_session_info(self, session: SessionInfo) -> Dict[str, Any]:
        return {
            "session_id": str(session.session_id or ""),
            "name": str(session.name or ""),
            "created_at": str(session.created_at or ""),
            "updated_at": str(session.updated_at or ""),
            "message_count": max(0, int(session.message_count or 0)),
            "preview": str(session.preview or ""),
            "has_partial_response": bool(session.has_partial_response),
        }

    def serialize_session_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        data = message if isinstance(message, dict) else {}
        metadata = (
            data.get("additional_kwargs", {})
            if isinstance(data.get("additional_kwargs", {}), dict)
            else {}
        )
        message_metadata = (
            metadata.get("metadata", {})
            if isinstance(metadata.get("metadata", {}), dict)
            else {}
        )
        attachments = data.get("attachments", [])
        return {
            "role": str(data.get("type", data.get("role", "")) or ""),
            "content": str(data.get("content", "") or ""),
            "timestamp": str(message_metadata.get("timestamp", "") or ""),
            "message_id": str(message_metadata.get("id", "") or ""),
            "attachments": [
                self.serialize_attachment(attachment)
                for attachment in (attachments if isinstance(attachments, list) else [])
            ],
        }

    def serialize_rollback_preview(
        self,
        preview: Optional[ConversationRollbackPreview],
    ) -> Dict[str, Any]:
        if preview is None:
            return {
                "session_id": "",
                "snapshot_id": "",
                "anchor_message_id": "",
                "anchor_timestamp": "",
                "anchor_label": "",
                "current_message_count": 0,
                "target_message_count": 0,
                "removed_message_count": 0,
                "removed_messages": [],
                "changed_files": [],
                "changed_file_count": 0,
                "total_added_lines": 0,
                "total_deleted_lines": 0,
                "workspace_changed_files": [],
                "workspace_changed_file_count": 0,
                "workspace_total_added_lines": 0,
                "workspace_total_deleted_lines": 0,
            }

        return {
            "session_id": str(preview.session_id or ""),
            "snapshot_id": str(preview.snapshot_id or ""),
            "anchor_message_id": str(preview.anchor_message_id or ""),
            "anchor_timestamp": str(preview.anchor_timestamp or ""),
            "anchor_label": str(preview.anchor_label or ""),
            "current_message_count": max(0, int(preview.current_message_count or 0)),
            "target_message_count": max(0, int(preview.target_message_count or 0)),
            "removed_message_count": max(0, int(preview.removed_message_count or 0)),
            "removed_messages": [
                {
                    "message_id": str(message.message_id or ""),
                    "role": str(message.role or ""),
                    "timestamp": str(message.timestamp or ""),
                    "content_preview": str(message.content_preview or ""),
                }
                for message in (preview.removed_messages or [])
            ],
            "changed_files": [
                self._serialize_snapshot_file_change(change)
                for change in (preview.changed_files or [])
            ],
            "changed_file_count": max(0, int(preview.changed_file_count or 0)),
            "total_added_lines": max(0, int(preview.total_added_lines or 0)),
            "total_deleted_lines": max(0, int(preview.total_deleted_lines or 0)),
            "workspace_changed_files": [
                self._serialize_snapshot_file_change(change)
                for change in (preview.workspace_changed_files or [])
            ],
            "workspace_changed_file_count": max(
                0, int(preview.workspace_changed_file_count or 0)
            ),
            "workspace_total_added_lines": max(
                0, int(preview.workspace_total_added_lines or 0)
            ),
            "workspace_total_deleted_lines": max(
                0, int(preview.workspace_total_deleted_lines or 0)
            ),
        }

    def serialize_rollback_overlay_state(
        self,
        rollback_state: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        data = rollback_state if isinstance(rollback_state, dict) else {}
        return {
            "is_open": bool(data.get("is_open", False)),
            "is_loading": bool(data.get("is_loading", False)),
            "error_message": str(data.get("error_message", "") or ""),
            "target_message_id": str(data.get("target_message_id", "") or ""),
            "preview": self.serialize_rollback_preview(data.get("preview")),
        }

    def serialize_confirm_dialog_state(
        self,
        confirm_state: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        data = confirm_state if isinstance(confirm_state, dict) else {}
        payload = data.get("payload", {})
        return {
            "is_open": bool(data.get("is_open", False)),
            "kind": str(data.get("kind", "") or ""),
            "title": str(data.get("title", "") or ""),
            "message": str(data.get("message", "") or ""),
            "confirm_label": str(data.get("confirm_label", "") or ""),
            "cancel_label": str(data.get("cancel_label", "") or ""),
            "tone": str(data.get("tone", "normal") or "normal"),
            "payload": dict(payload) if isinstance(payload, dict) else {},
        }

    def serialize_notice_dialog_state(
        self,
        notice_state: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        data = notice_state if isinstance(notice_state, dict) else {}
        return {
            "is_open": bool(data.get("is_open", False)),
            "title": str(data.get("title", "") or ""),
            "message": str(data.get("message", "") or ""),
            "tone": str(data.get("tone", "info") or "info"),
        }

    def _serialize_snapshot_file_change(self, change: Any) -> Dict[str, Any]:
        return {
            "relative_path": str(getattr(change, "relative_path", "") or ""),
            "change_type": str(getattr(change, "change_type", "") or ""),
            "summary": str(getattr(change, "summary", "") or ""),
            "added_lines": max(0, int(getattr(change, "added_lines", 0) or 0)),
            "deleted_lines": max(0, int(getattr(change, "deleted_lines", 0) or 0)),
            "diff_preview": str(getattr(change, "diff_preview", "") or ""),
            "is_text": bool(getattr(change, "is_text", False)),
        }


__all__ = ["ConversationStateSerializer"]
