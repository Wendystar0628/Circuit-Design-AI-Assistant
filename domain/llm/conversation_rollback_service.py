import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from domain.services import context_service, snapshot_service


class ConversationRollbackService:
    def __init__(self):
        self._lock = threading.RLock()
        self._logger = None
        self._event_bus = None
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

    async def capture_user_turn_checkpoint(
        self,
        *,
        anchor_message_id: str,
        anchor_timestamp: str,
    ) -> Dict[str, Any]:
        with self._lock:
            session_state_manager = self.session_state_manager
            if session_state_manager is None:
                raise RuntimeError("SessionStateManager not available")

            session_id = session_state_manager.get_current_session_id()
            project_root = session_state_manager.get_project_root()
            if not session_id or not project_root:
                raise RuntimeError("Active session is not ready for rollback checkpoint capture")

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

        with self._lock:
            session_state_manager = self.session_state_manager
            if session_state_manager is None:
                return {"success": False, "message": "SessionStateManager not available"}

            session_id = session_state_manager.get_current_session_id()
            project_root = session_state_manager.get_project_root()
            if not session_id or not project_root:
                return {"success": False, "message": "No active conversation session"}

        checkpoints = context_service.load_rollback_checkpoints(project_root, session_id)
        checkpoint = next(
            (item for item in checkpoints if item.get("anchor_message_id") == anchor_message_id),
            None,
        )
        if checkpoint is None:
            return {"success": False, "message": "Rollback checkpoint not found"}

        snapshot_id = str(checkpoint.get("snapshot_id", "") or "")
        if not snapshot_id:
            return {"success": False, "message": "Rollback snapshot is missing"}

        try:
            await snapshot_service.restore_snapshot_async(
                project_root,
                snapshot_id,
                backup_current=True,
            )
            session_state_manager.reload_current_session(
                project_root=project_root,
                action="rollback",
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


__all__ = ["ConversationRollbackService"]
