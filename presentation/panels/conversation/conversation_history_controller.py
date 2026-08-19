from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from presentation.panels.conversation.conversation_session_support import ConversationSessionSupport


@dataclass(frozen=True)
class _SessionDeleteIdentity:
    """One-shot owner identity captured before delete confirmation."""

    support: Any
    manager: Any
    project_root: str
    session_id: str
    request_id: str


class ConversationHistoryController:
    def __init__(
        self,
        *,
        session_support: ConversationSessionSupport,
        get_text: Callable[[str, str], str],
        on_state_changed: Callable[[], None],
        on_notice_requested: Callable[..., None],
        on_confirm_requested: Callable[..., None],
        logger_getter: Callable[[], Any],
        can_mutate_session: Optional[Callable[[], Tuple[bool, str]]] = None,
    ) -> None:
        self._session_support = session_support
        self._get_text = get_text
        self._on_state_changed = on_state_changed
        self._on_notice_requested = on_notice_requested
        self._on_confirm_requested = on_confirm_requested
        self._logger_getter = logger_getter
        self._can_mutate_session = can_mutate_session or (lambda: (True, ""))
        self._state = self._create_history_overlay_state()
        self._pending_delete_identity: Optional[_SessionDeleteIdentity] = None

    @property
    def logger(self):
        try:
            return self._logger_getter()
        except Exception:
            return None

    @property
    def state(self) -> Dict[str, Any]:
        return self._state

    def is_open(self) -> bool:
        return bool(self._state.get("is_open", False))

    def _notify_state_changed(self) -> None:
        self._on_state_changed()

    def _ensure_session_mutation_allowed(self) -> bool:
        try:
            allowed, message = self._can_mutate_session()
        except Exception as exc:
            allowed, message = False, str(exc)
        if allowed:
            return True
        self._on_notice_requested(
            message
            or self._get_text(
                "dialog.history.generation_active",
                "当前回答仍在生成，请先停止并等待生成结束",
            ),
            title=self._get_text("dialog.warning.title", "警告"),
            tone="error",
        )
        return False

    def _create_history_export_dialog_state(
        self,
        session_id: str = "",
        export_format: str = "md",
        file_path: str = "",
        *,
        is_open: bool = False,
    ) -> Dict[str, Any]:
        normalized_session_id = str(session_id or "")
        normalized_format = self._session_support.normalize_export_format(export_format) or "md"
        normalized_path = ""
        if normalized_session_id:
            normalized_path = self._session_support.normalize_export_file_path(
                file_path
                or self._session_support.build_default_export_path(
                    normalized_session_id,
                    normalized_format,
                ),
                normalized_format,
            )
        return {
            "is_open": bool(is_open and normalized_session_id),
            "session_id": normalized_session_id,
            "export_format": normalized_format,
            "file_path": normalized_path,
        }

    def _set_history_export_dialog_state(
        self,
        session_id: str = "",
        export_format: str = "md",
        file_path: str = "",
        *,
        is_open: bool = False,
    ) -> None:
        self._state["export_dialog"] = self._create_history_export_dialog_state(
            session_id,
            export_format,
            file_path,
            is_open=is_open,
        )

    def _clear_history_export_dialog_state(self) -> None:
        self._set_history_export_dialog_state()

    def _current_history_export_dialog_state(self) -> Dict[str, Any]:
        dialog_state = self._state.get("export_dialog", {})
        return dialog_state if isinstance(dialog_state, dict) else {}

    def _create_history_overlay_state(self) -> Dict[str, Any]:
        return {
            "is_open": False,
            "is_loading": False,
            "error_message": "",
            "current_session_id": "",
            "selected_session_id": "",
            "sessions": [],
            "preview_messages": [],
            "export_dialog": self._create_history_export_dialog_state(),
        }

    def close(self) -> None:
        self._pending_delete_identity = None
        self._state = self._create_history_overlay_state()
        self._notify_state_changed()

    def refresh(self, preferred_session_id: str = "") -> None:
        # A project/session refresh invalidates any confirmation opened for the
        # previous overlay contents.  Confirmation tokens are deliberately
        # one-shot and never retargeted by session ID alone.
        self._pending_delete_identity = None
        self._session_support.ensure_current_session_persisted()
        sessions = self._session_support.list_sessions()
        current_session_id = self._session_support.get_current_session_id()
        selected_session_id = str(
            preferred_session_id
            or self._state.get("selected_session_id", "")
            or current_session_id
        )
        available_session_ids = {
            str(getattr(session, "session_id", "") or "") for session in sessions
        }
        if not selected_session_id or selected_session_id not in available_session_ids:
            selected_session_id = current_session_id
        if (not selected_session_id or selected_session_id not in available_session_ids) and sessions:
            selected_session_id = str(getattr(sessions[0], "session_id", "") or "")
        preview_messages = (
            self._session_support.get_session_messages(selected_session_id)
            if selected_session_id
            else []
        )
        self._state = {
            "is_open": True,
            "is_loading": False,
            "error_message": "",
            "current_session_id": current_session_id,
            "selected_session_id": selected_session_id,
            "sessions": sessions,
            "preview_messages": preview_messages,
            "export_dialog": self._create_history_export_dialog_state(),
        }
        self._notify_state_changed()

    def open_session(self, session_id: str) -> bool:
        if not session_id:
            return False
        if not self._ensure_session_mutation_allowed():
            return False
        success = self._session_support.open_session(session_id)
        if success:
            self.close()
            return True
        self._on_notice_requested(
            self._get_text("dialog.history.open_failed", "打开会话失败"),
            title=self._get_text("dialog.error.title", "错误"),
            tone="error",
        )
        return False

    def open_export_dialog(self, session_id: str = "") -> None:
        normalized_session_id = str(
            session_id
            or self._state.get("selected_session_id", "")
            or self._state.get("current_session_id", "")
            or ""
        )
        if not normalized_session_id:
            return
        self._set_history_export_dialog_state(
            normalized_session_id,
            is_open=True,
        )
        self._notify_state_changed()

    def close_export_dialog(self) -> None:
        if not self._state.get("is_open", False):
            return
        self._clear_history_export_dialog_state()
        self._notify_state_changed()

    def change_export_format(self, export_format: str) -> None:
        dialog_state = self._current_history_export_dialog_state()
        session_id = str(dialog_state.get("session_id", "") or "")
        normalized_format = self._session_support.normalize_export_format(export_format)
        if not session_id or not normalized_format:
            return
        self._set_history_export_dialog_state(
            session_id,
            normalized_format,
            str(dialog_state.get("file_path", "") or ""),
            is_open=bool(dialog_state.get("is_open", False)),
        )
        self._notify_state_changed()

    def pick_export_path(self, parent: Any) -> None:
        dialog_state = self._current_history_export_dialog_state()
        session_id = str(dialog_state.get("session_id", "") or "")
        export_format = self._session_support.normalize_export_format(
            str(dialog_state.get("export_format", "") or "")
        )
        if not session_id or not export_format:
            return
        selected_path = self._session_support.choose_export_file_path(
            session_id,
            export_format,
            parent=parent,
            dialog_title=self._get_text("dialog.export.title", "选择导出路径"),
            initial_path=str(dialog_state.get("file_path", "") or ""),
        )
        if not selected_path:
            return
        self._set_history_export_dialog_state(
            session_id,
            export_format,
            selected_path,
            is_open=True,
        )
        self._notify_state_changed()

    def export_session(self, session_id: str, export_format: str, file_path: str) -> None:
        normalized_format = self._session_support.normalize_export_format(export_format)
        normalized_path = self._session_support.normalize_export_file_path(
            file_path,
            normalized_format,
        )
        if not session_id or not normalized_format or not normalized_path:
            self._on_notice_requested(
                self._get_text("dialog.export.failed", "导出会话失败"),
                title=self._get_text("dialog.error.title", "错误"),
                tone="error",
            )
            return
        success, export_path = self._session_support.export_session_to_path(
            session_id,
            normalized_format,
            normalized_path,
        )
        if success:
            self._clear_history_export_dialog_state()
            self._notify_state_changed()
            self._on_notice_requested(
                self._get_text("dialog.export.success", "会话导出成功"),
                title=self._get_text("dialog.info.title", "提示"),
                tone="success",
            )
            if self.logger:
                self.logger.info(f"Session exported to: {export_path}")
            return
        self._on_notice_requested(
            self._get_text("dialog.export.failed", "导出会话失败"),
            title=self._get_text("dialog.error.title", "错误"),
            tone="error",
        )

    def request_delete_session(self, session_id: str) -> None:
        if not session_id:
            return
        if not self._ensure_session_mutation_allowed():
            return
        project_root = self._normalize_project_root(
            self._session_support.get_project_root()
        )
        if not project_root:
            return
        identity = _SessionDeleteIdentity(
            support=self._session_support,
            manager=getattr(self._session_support, "session_state_manager", None),
            project_root=project_root,
            session_id=str(session_id),
            request_id=uuid.uuid4().hex,
        )
        self._pending_delete_identity = identity
        self._on_confirm_requested(
            kind="history_delete",
            title=self._get_text("dialog.warning.title", "警告"),
            message=self._get_text(
                "dialog.history.delete_confirm",
                "确定删除这个会话吗？此操作无法撤销。",
            ),
            confirm_label=self._get_text("btn.delete", "删除"),
            cancel_label=self._get_text("btn.cancel", "取消"),
            tone="danger",
            payload={
                "session_id": identity.session_id,
                "request_id": identity.request_id,
            },
        )

    def handle_confirm_acceptance(self, kind: str, payload: Any) -> bool:
        if str(kind or "") != "history_delete":
            return False
        identity = self._pending_delete_identity
        self._pending_delete_identity = None
        request_id = str(payload.get("request_id", "") or "") if isinstance(payload, dict) else ""
        session_id = str(payload.get("session_id", "") or "") if isinstance(payload, dict) else ""
        if (
            identity is None
            or not request_id
            or request_id != identity.request_id
            or session_id != identity.session_id
            or self._session_support is not identity.support
            or getattr(self._session_support, "session_state_manager", None)
            is not identity.manager
            or self._normalize_project_root(
                self._session_support.get_project_root()
            )
            != identity.project_root
        ):
            return True
        # The state can change between opening and accepting the confirmation
        # dialog, so enforce the single-flight boundary again at commit time.
        if not self._ensure_session_mutation_allowed():
            return True
        success = self._session_support.delete_session(
            identity.session_id,
            project_root=identity.project_root,
        )
        if success:
            self.refresh()
            return True
        self._on_notice_requested(
            self._get_text("dialog.history.delete_failed", "删除会话失败"),
            title=self._get_text("dialog.error.title", "错误"),
            tone="error",
        )
        return True

    @staticmethod
    def _normalize_project_root(project_root: str) -> str:
        if not project_root:
            return ""
        return os.path.normcase(
            os.path.realpath(os.path.abspath(os.fspath(project_root)))
        )


__all__ = ["ConversationHistoryController"]
