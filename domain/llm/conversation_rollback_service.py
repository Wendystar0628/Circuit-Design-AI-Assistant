import asyncio
import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

from domain.llm.message_helpers import (
    get_serialized_message_id,
    get_serialized_message_timestamp,
)
from domain.services import context_service, snapshot_service
from shared.constants import SYSTEM_DIR


@dataclass(frozen=True)
class RollbackMessageSummary:
    message_id: str
    role: str
    timestamp: str
    content_preview: str


@dataclass(frozen=True)
class ConversationRollbackPreview:
    session_id: str
    snapshot_id: str
    anchor_message_id: str
    anchor_timestamp: str
    anchor_label: str
    current_message_count: int
    target_message_count: int
    removed_message_count: int
    removed_messages: List[RollbackMessageSummary]
    changed_files: List[snapshot_service.SnapshotFileChange]
    changed_file_count: int
    total_added_lines: int
    total_deleted_lines: int


class ConversationRollbackService:
    def __init__(self):
        self._lock = threading.RLock()
        self._logger = None
        self._event_bus = None
        self._file_watcher = None
        self._session_state_manager = None

    @property
    def logger(self):
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("conversation_rollback_service")
            except Exception:
                pass
        return self._logger

    @property
    def event_bus(self):
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus

    @property
    def session_state_manager(self):
        if self._session_state_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE_MANAGER
                self._session_state_manager = ServiceLocator.get_optional(SVC_SESSION_STATE_MANAGER)
            except Exception:
                pass
        return self._session_state_manager

    @property
    def file_watcher(self):
        if self._file_watcher is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_FILE_WATCHER
                self._file_watcher = ServiceLocator.get_optional(SVC_FILE_WATCHER)
            except Exception:
                pass
        return self._file_watcher

    def get_available_anchor_ids(self) -> set[str]:
        session_state_manager = self.session_state_manager
        if session_state_manager is None:
            return set()

        session_id = session_state_manager.get_current_session_id()
        project_root = session_state_manager.get_project_root()
        if not session_id or not project_root:
            return set()

        checkpoints = context_service.load_rollback_checkpoints(project_root, session_id)
        return {
            str(item.get("anchor_message_id", "") or "")
            for item in checkpoints
            if item.get("anchor_message_id")
        }

    async def preview_rollback_to_anchor(
        self,
        anchor_message_id: str,
    ) -> ConversationRollbackPreview:
        if not anchor_message_id:
            raise ValueError("Invalid rollback anchor")

        session_state_manager, session_id, project_root = self._require_active_session()

        persisted = await asyncio.to_thread(
            session_state_manager.save_current_session,
            project_root=project_root,
        )
        if not persisted:
            raise RuntimeError("Failed to persist current conversation state before rollback preview")

        checkpoint = self._get_checkpoint(project_root, session_id, anchor_message_id)
        return await asyncio.to_thread(
            self._build_preview,
            project_root,
            session_id,
            anchor_message_id,
            checkpoint,
        )

    async def capture_user_turn_checkpoint(
        self,
        *,
        anchor_message_id: str,
        anchor_timestamp: str,
    ) -> Dict[str, Any]:
        session_state_manager, session_id, project_root = self._require_active_session()

        session_state_manager.save_current_session(project_root=project_root)

        snapshot_id = self._generate_snapshot_id(session_id, anchor_message_id)
        await snapshot_service.create_snapshot_async(project_root, snapshot_id)

        checkpoint = {
            "anchor_message_id": anchor_message_id,
            "anchor_timestamp": anchor_timestamp,
            "session_id": session_id,
            "snapshot_id": snapshot_id,
            "created_at": datetime.now().isoformat(),
        }
        context_service.append_rollback_checkpoint(project_root, session_id, checkpoint)
        self._cleanup_hidden_snapshots(project_root, session_id)

        if self.logger:
            self.logger.info(
                f"Captured rollback checkpoint: session_id={session_id}, "
                f"anchor_message_id={anchor_message_id}, snapshot_id={snapshot_id}"
            )

        return checkpoint

    async def rollback_to_anchor(self, anchor_message_id: str) -> Dict[str, Any]:
        if not anchor_message_id:
            return {"success": False, "message": "Invalid rollback anchor"}

        try:
            session_state_manager, session_id, project_root = self._require_active_session()
            persisted = await asyncio.to_thread(
                session_state_manager.save_current_session,
                project_root=project_root,
            )
            if not persisted:
                return {
                    "success": False,
                    "message": "Failed to persist current conversation state before rollback",
                }
            checkpoint = self._get_checkpoint(project_root, session_id, anchor_message_id)
            snapshot_id = str(checkpoint.get("snapshot_id", "") or "")
        except Exception as exc:
            return {"success": False, "message": str(exc)}

        watcher_was_running = False
        file_watcher = self.file_watcher
        try:
            if file_watcher is not None:
                try:
                    watcher_was_running = bool(getattr(file_watcher, "is_watching", False))
                    if watcher_was_running:
                        file_watcher.stop_watching()
                except Exception as exc:
                    if self.logger:
                        self.logger.warning(f"Failed to stop file watcher before rollback: {exc}")

            await snapshot_service.restore_snapshot_async(
                project_root,
                snapshot_id,
                backup_current=True,
            )
            session_state_manager.reload_current_session(
                project_root=project_root,
                action="rollback",
            )
            self._publish_workspace_sync_required(
                project_root=project_root,
                reason="rollback",
            )
            self._cleanup_hidden_snapshots(project_root, session_id)

            if self.logger:
                self.logger.info(
                    f"Rollback completed: session_id={session_id}, "
                    f"anchor_message_id={anchor_message_id}, snapshot_id={snapshot_id}"
                )

            return {
                "success": True,
                "message": "",
                "session_id": session_id,
                "snapshot_id": snapshot_id,
                "anchor_message_id": anchor_message_id,
            }
        except Exception as e:
            if self.logger:
                self.logger.error(
                    f"Rollback failed: session_id={session_id}, "
                    f"anchor_message_id={anchor_message_id}, error={e}"
                )
            return {"success": False, "message": str(e)}
        finally:
            if file_watcher is not None and watcher_was_running:
                try:
                    file_watcher.start_watching(project_root)
                except Exception as exc:
                    if self.logger:
                        self.logger.warning(f"Failed to restart file watcher after rollback: {exc}")

    def _publish_workspace_sync_required(self, *, project_root: str, reason: str) -> None:
        if self.event_bus is None:
            return
        try:
            from shared.event_types import EVENT_WORKSPACE_SYNC_REQUIRED

            self.event_bus.publish(
                EVENT_WORKSPACE_SYNC_REQUIRED,
                {
                    "project_root": str(project_root or ""),
                    "reason": str(reason or ""),
                },
                source="conversation_rollback_service",
            )
        except Exception as exc:
            if self.logger:
                self.logger.warning(f"Failed to publish workspace sync event: {exc}")

    def _require_active_session(self) -> tuple[Any, str, str]:
        with self._lock:
            session_state_manager = self.session_state_manager
            if session_state_manager is None:
                raise RuntimeError("SessionStateManager not available")

        try:
            session_state_manager.ensure_active_session()
        except Exception as exc:
            raise RuntimeError(f"Active session is not ready: {exc}") from exc

        with self._lock:
            session_id = session_state_manager.get_current_session_id()
            project_root = session_state_manager.get_project_root()
            if not session_id or not project_root:
                raise RuntimeError("No active conversation session")

            return session_state_manager, session_id, project_root

    def _get_checkpoint(
        self,
        project_root: str,
        session_id: str,
        anchor_message_id: str,
    ) -> Dict[str, Any]:
        checkpoints = context_service.load_rollback_checkpoints(project_root, session_id)
        checkpoint = next(
            (item for item in checkpoints if item.get("anchor_message_id") == anchor_message_id),
            None,
        )
        if checkpoint is None:
            raise RuntimeError("Rollback checkpoint not found")

        snapshot_id = str(checkpoint.get("snapshot_id", "") or "")
        if not snapshot_id:
            raise RuntimeError("Rollback snapshot is missing")

        return checkpoint

    def _build_preview(
        self,
        project_root: str,
        session_id: str,
        anchor_message_id: str,
        checkpoint: Dict[str, Any],
    ) -> ConversationRollbackPreview:
        snapshot_id = str(checkpoint.get("snapshot_id", "") or "")
        current_messages = context_service.load_messages(project_root, session_id)
        target_messages = self._load_snapshot_session_messages(
            project_root,
            snapshot_id,
            session_id,
        )
        restore_preview = snapshot_service.preview_restore_snapshot(project_root, snapshot_id)
        changed_files = self._build_visible_workspace_changes(
            restore_preview.changed_files
        )
        removed_messages = self._build_removed_messages(current_messages, target_messages)
        anchor_message = next(
            (
                message
                for message in current_messages
                if get_serialized_message_id(message) == anchor_message_id
            ),
            None,
        )

        return ConversationRollbackPreview(
            session_id=session_id,
            snapshot_id=snapshot_id,
            anchor_message_id=anchor_message_id,
            anchor_timestamp=str(checkpoint.get("anchor_timestamp", "") or ""),
            anchor_label=self._build_anchor_label(anchor_message_id, checkpoint, anchor_message, removed_messages),
            current_message_count=len(current_messages),
            target_message_count=len(target_messages),
            removed_message_count=len(removed_messages),
            removed_messages=removed_messages,
            changed_files=changed_files,
            changed_file_count=len(changed_files),
            total_added_lines=sum(change.added_lines for change in changed_files),
            total_deleted_lines=sum(change.deleted_lines for change in changed_files),
        )

    def _load_snapshot_session_messages(
        self,
        project_root: str,
        snapshot_id: str,
        session_id: str,
    ) -> List[Dict[str, Any]]:
        snapshot_session_file = (
            Path(project_root).resolve()
            / snapshot_service.SNAPSHOTS_DIR
            / snapshot_id
            / context_service.CONVERSATIONS_DIR
            / f"{session_id}.json"
        )
        if not snapshot_session_file.exists():
            raise RuntimeError("Rollback session snapshot file is missing")

        try:
            payload = json.loads(snapshot_session_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Failed to read rollback session snapshot: {exc}") from exc

        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            raise RuntimeError("Rollback session snapshot is invalid")
        return messages

    def _build_removed_messages(
        self,
        current_messages: List[Dict[str, Any]],
        target_messages: List[Dict[str, Any]],
    ) -> List[RollbackMessageSummary]:
        prefix_length = 0
        max_prefix = min(len(current_messages), len(target_messages))
        while prefix_length < max_prefix:
            if self._message_signature(current_messages[prefix_length]) != self._message_signature(target_messages[prefix_length]):
                break
            prefix_length += 1

        return [
            RollbackMessageSummary(
                message_id=get_serialized_message_id(message),
                role=str(message.get("type", "") or ""),
                timestamp=get_serialized_message_timestamp(message),
                content_preview=self._build_message_preview(message),
            )
            for message in current_messages[prefix_length:]
        ]

    def _build_anchor_label(
        self,
        anchor_message_id: str,
        checkpoint: Dict[str, Any],
        anchor_message: Optional[Dict[str, Any]],
        removed_messages: List[RollbackMessageSummary],
    ) -> str:
        if anchor_message is not None:
            preview = self._build_message_preview(anchor_message)
            if preview:
                return preview

        if removed_messages:
            preview = removed_messages[0].content_preview
            if preview:
                return preview

        timestamp = str(checkpoint.get("anchor_timestamp", "") or "")
        if timestamp:
            return timestamp

        short_id = anchor_message_id[:8] if anchor_message_id else ""
        return short_id or "rollback"

    def _build_message_preview(self, message: Dict[str, Any], limit: int = 120) -> str:
        content = message.get("content", "")
        if isinstance(content, list):
            normalized = " ".join(str(item) for item in content)
        elif isinstance(content, str):
            normalized = content
        else:
            normalized = str(content or "")

        normalized = " ".join(normalized.split())
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit]}..."

    def _message_signature(self, message: Dict[str, Any]) -> tuple[str, str, str]:
        return (
            get_serialized_message_id(message),
            str(message.get("type", "") or ""),
            self._build_message_preview(message, limit=400),
        )

    def _build_visible_workspace_changes(
        self,
        changes: List[snapshot_service.SnapshotFileChange],
    ) -> List[snapshot_service.SnapshotFileChange]:
        return [
            change
            for change in (changes or [])
            if self._is_visible_workspace_path(change.relative_path)
        ]

    def _is_visible_workspace_path(self, relative_path: str) -> bool:
        return not self._is_system_managed_path(relative_path)

    def _is_system_managed_path(self, relative_path: str) -> bool:
        normalized_path = str(relative_path or "").replace("\\", "/").strip("/")
        if not normalized_path:
            return False
        return bool(PurePosixPath(normalized_path).parts) and PurePosixPath(normalized_path).parts[0] == SYSTEM_DIR

    def _cleanup_hidden_snapshots(self, project_root: str, session_id: str) -> None:
        snapshots_dir = Path(snapshot_service.get_snapshots_dir(project_root))
        if not snapshots_dir.exists():
            return

        session_prefix = self._get_session_snapshot_prefix(session_id)

        active_snapshot_ids = {
            str(item.get("snapshot_id", "") or "")
            for item in context_service.load_rollback_checkpoints(project_root, session_id)
        }

        for snapshot_dir in snapshots_dir.iterdir():
            if not snapshot_dir.is_dir():
                continue
            snapshot_id = snapshot_dir.name
            if not snapshot_id.startswith(session_prefix):
                continue
            if snapshot_id in active_snapshot_ids:
                continue
            try:
                snapshot_service.delete_snapshot(project_root, snapshot_id)
            except Exception:
                pass

    def _generate_snapshot_id(self, session_id: str, anchor_message_id: str) -> str:
        session_prefix = self._get_session_snapshot_prefix(session_id)
        safe_anchor = "".join(ch for ch in anchor_message_id if ch.isalnum())[:12] or "anchor"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{session_prefix}{timestamp}_{safe_anchor}"

    def _get_session_snapshot_prefix(self, session_id: str) -> str:
        safe_session = "".join(ch for ch in session_id if ch.isalnum())[:16] or "session"
        return f"_conv_turn_{safe_session}_"


__all__ = [
    "RollbackMessageSummary",
    "ConversationRollbackPreview",
    "ConversationRollbackService",
]
