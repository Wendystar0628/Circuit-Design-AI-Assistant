from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PyQt6.QtWidgets import QFileDialog, QWidget

from domain.llm.session_state_manager import SessionInfo


class ConversationSessionSupport:
    def __init__(self):
        self._session_state_manager = None

    @property
    def session_state_manager(self):
        if self._session_state_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE_MANAGER

                self._session_state_manager = ServiceLocator.get_optional(
                    SVC_SESSION_STATE_MANAGER
                )
            except Exception:
                pass
        return self._session_state_manager

    def get_project_root(self) -> str:
        manager = self.session_state_manager
        if manager is None:
            return ""
        try:
            return str(manager.get_project_root() or "")
        except Exception:
            return ""

    def get_current_session_id(self) -> str:
        manager = self.session_state_manager
        if manager is None:
            return ""
        try:
            return str(manager.get_current_session_id() or "")
        except Exception:
            return ""

    def get_current_session_name(self) -> str:
        manager = self.session_state_manager
        if manager is None:
            return ""
        try:
            return str(manager.get_current_session_name() or "")
        except Exception:
            return ""

    def ensure_current_session_persisted(self) -> bool:
        manager = self.session_state_manager
        if manager is None:
            return False
        try:
            return bool(manager.ensure_current_session_persisted(self.get_project_root()))
        except Exception:
            return False

    def list_sessions(self) -> List[SessionInfo]:
        manager = self.session_state_manager
        project_root = self.get_project_root()
        if manager is None or not project_root:
            return []
        try:
            sessions = manager.get_all_sessions(project_root)
        except Exception:
            return []
        return list(sessions or [])

    def get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        manager = self.session_state_manager
        project_root = self.get_project_root()
        if manager is None or not project_root or not session_id:
            return []
        try:
            messages = manager.get_session_messages(
                session_id=session_id,
                project_root=project_root,
            )
        except Exception:
            return []
        return list(messages or [])

    def open_session(self, session_id: str) -> bool:
        manager = self.session_state_manager
        project_root = self.get_project_root()
        if manager is None or not project_root or not session_id:
            return False
        try:
            manager.ensure_current_session_persisted(project_root)
            new_state = manager.switch_session(
                project_root=project_root,
                session_id=session_id,
                sync_to_context_manager=True,
            )
        except Exception:
            return False
        return new_state is not None

    def delete_session(self, session_id: str) -> bool:
        manager = self.session_state_manager
        project_root = self.get_project_root()
        if manager is None or not project_root or not session_id:
            return False
        try:
            return bool(
                manager.delete_session(
                    project_root=project_root,
                    session_id=session_id,
                )
            )
        except Exception:
            return False

    def rename_session(self, session_id: str, new_name: str) -> bool:
        manager = self.session_state_manager
        project_root = self.get_project_root()
        normalized_name = str(new_name or "").strip()
        if manager is None or not project_root or not session_id or not normalized_name:
            return False
        try:
            return bool(
                manager.rename_session(
                    session_id=session_id,
                    new_name=normalized_name,
                    project_root=project_root,
                )
            )
        except Exception:
            return False

    def rename_current_session(self, new_name: str) -> bool:
        return self.rename_session(self.get_current_session_id(), new_name)

    def export_session(
        self,
        session_id: str,
        export_format: str,
        *,
        parent: Optional[QWidget],
        dialog_title: str,
    ) -> Tuple[bool, str]:
        messages = self.get_session_messages(session_id)
        if not session_id:
            return False, ""
        normalized_format = self.normalize_export_format(export_format)
        if not normalized_format:
            return False, ""
        file_path, _ = QFileDialog.getSaveFileName(
            parent,
            dialog_title,
            self.build_default_export_filename(session_id, normalized_format),
            self.export_file_filter(normalized_format),
        )
        if not file_path:
            return False, ""
        try:
            content = self.format_export_content(messages, normalized_format)
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write(content)
            return True, file_path
        except Exception:
            return False, ""

    @staticmethod
    def normalize_export_format(export_format: str) -> str:
        normalized = str(export_format or "").strip().lower()
        return normalized if normalized in {"json", "txt", "md"} else ""

    @staticmethod
    def export_file_filter(export_format: str) -> str:
        return {
            "json": "JSON Files (*.json)",
            "txt": "Text Files (*.txt)",
            "md": "Markdown Files (*.md)",
        }.get(export_format, "All Files (*.*)")

    @staticmethod
    def build_default_export_filename(session_id: str, export_format: str) -> str:
        return f"conversation_{str(session_id or '')[:8]}.{export_format}"

    @classmethod
    def format_export_content(
        cls,
        messages: Sequence[Dict[str, Any]],
        export_format: str,
    ) -> str:
        normalized_format = cls.normalize_export_format(export_format)
        if normalized_format == "json":
            return json.dumps(list(messages or []), ensure_ascii=False, indent=2)
        if normalized_format == "txt":
            lines: List[str] = []
            for message in messages or []:
                role = str(message.get("type", "unknown") or "unknown").upper()
                timestamp = cls._message_timestamp(message)
                lines.append(f"[{role}] {timestamp}")
                lines.append(cls._message_content(message))
                lines.append("")
            return "\n".join(lines)
        if normalized_format == "md":
            lines = ["# Conversation Export", ""]
            for message in messages or []:
                role = str(message.get("type", "unknown") or "unknown")
                timestamp = cls._message_timestamp(message)
                if role == "user":
                    lines.append(f"## 👤 User ({timestamp})")
                elif role == "assistant":
                    lines.append(f"## 🤖 Assistant ({timestamp})")
                else:
                    lines.append(f"## ⚙️ System ({timestamp})")
                lines.append("")
                lines.append(cls._message_content(message))
                lines.append("")
            return "\n".join(lines)
        return ""

    @staticmethod
    def _message_timestamp(message: Dict[str, Any]) -> str:
        additional_kwargs = message.get("additional_kwargs", {})
        if isinstance(additional_kwargs, dict):
            metadata = additional_kwargs.get("metadata", {})
            if isinstance(metadata, dict):
                timestamp = metadata.get("timestamp", "")
                if timestamp:
                    return str(timestamp)
            timestamp = additional_kwargs.get("timestamp", "")
            if timestamp:
                return str(timestamp)
        return str(message.get("timestamp", "") or "")

    @staticmethod
    def _message_content(message: Dict[str, Any]) -> str:
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content
            )
        return str(content or "")


__all__ = ["ConversationSessionSupport"]
