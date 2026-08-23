import asyncio
import copy
import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.llm.message_helpers import (
    get_serialized_message_id,
    get_serialized_message_timestamp,
)
from domain.llm.working_context_builder import (
    WORKING_CONTEXT_COMPRESSED_COUNT_KEY,
    WORKING_CONTEXT_KEEP_RECENT_KEY,
    WORKING_CONTEXT_SUMMARY_KEY,
)
from domain.services import context_service, snapshot_service
from shared.constants import SYSTEM_DIR


MAX_ROLLBACK_CHECKPOINTS = 20


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
    operation_token: str


@dataclass(frozen=True)
class _RollbackOwner:
    """Project/session identity that owns one asynchronous restore."""

    project_root: str
    session_id: str
    file_generation: Optional[int]


@dataclass(frozen=True)
class _RollbackPlan:
    """Immutable inputs approved by one rollback confirmation."""

    preview: ConversationRollbackPreview
    live_metadata: Dict[str, Any]
    target_metadata: Dict[str, Any]


class ConversationRollbackService:
    def __init__(self):
        self._lock = threading.RLock()
        self._logger = None
        self._event_bus = None
        self._file_manager = None
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

    @property
    def file_manager(self):
        if self._file_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_FILE_MANAGER
                self._file_manager = ServiceLocator.get_optional(SVC_FILE_MANAGER)
            except Exception:
                pass
        return self._file_manager

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
        owner = self._capture_owner(
            session_state_manager,
            session_id=session_id,
            project_root=project_root,
        )

        # Saving on the owning event-loop turn is intentional.  Deferring this
        # call to a worker lets a project switch occur before the worker reads
        # SessionStateManager, which can write the new session into the old
        # project root.
        persisted = session_state_manager.save_current_session(
            project_root=project_root,
            expected_session_id=session_id,
        )
        if not persisted:
            raise RuntimeError("Failed to persist current conversation state before rollback preview")
        if not self._is_owner_current(owner, session_state_manager):
            raise RuntimeError("Project or conversation changed during rollback preview")

        checkpoint = self._get_checkpoint(project_root, session_id, anchor_message_id)
        runtime_messages = session_state_manager.get_session_messages(
            session_id,
            project_root=project_root,
        )
        runtime_metadata = self._get_runtime_metadata_state(session_state_manager)
        plan = await asyncio.to_thread(
            self._build_plan,
            project_root,
            session_id,
            anchor_message_id,
            checkpoint,
            owner,
            runtime_messages,
            runtime_metadata,
        )
        if not self._is_owner_current(owner, session_state_manager):
            raise RuntimeError("Project or conversation changed during rollback preview")
        return plan.preview

    async def capture_user_turn_checkpoint(
        self,
        *,
        anchor_message_id: str,
        anchor_timestamp: str,
    ) -> Dict[str, Any]:
        session_state_manager, session_id, project_root = self._require_active_session()
        owner = self._capture_owner(
            session_state_manager,
            session_id=session_id,
            project_root=project_root,
        )

        persisted = session_state_manager.save_current_session(
            project_root=project_root,
            expected_session_id=session_id,
        )
        if not persisted:
            raise RuntimeError(
                "Failed to persist current conversation before checkpoint"
            )
        if not self._is_owner_current(owner, session_state_manager):
            raise RuntimeError(
                "Project or conversation changed before checkpoint capture"
            )

        snapshot_id = self._generate_snapshot_id(session_id, anchor_message_id)
        snapshot_created = False
        checkpoint_committed = False
        try:
            await snapshot_service.create_snapshot_async(project_root, snapshot_id)
            snapshot_created = True
            if not self._is_owner_current(owner, session_state_manager):
                raise RuntimeError(
                    "Project or conversation changed during checkpoint capture"
                )

            checkpoint = {
                "anchor_message_id": anchor_message_id,
                "anchor_timestamp": anchor_timestamp,
                "session_id": session_id,
                "snapshot_id": snapshot_id,
                "created_at": datetime.now().isoformat(),
            }
            evicted_checkpoints = context_service.append_rollback_checkpoint(
                project_root,
                session_id,
                checkpoint,
                keep_count=MAX_ROLLBACK_CHECKPOINTS,
            )
            if evicted_checkpoints is False:
                raise RuntimeError("Failed to persist rollback checkpoint")
            checkpoint_committed = True

            owned_prefix = self._get_session_snapshot_prefix(session_id)
            for evicted_checkpoint in evicted_checkpoints:
                evicted_snapshot_id = str(
                    evicted_checkpoint.get("snapshot_id", "") or ""
                )
                if evicted_snapshot_id.startswith(owned_prefix):
                    self._delete_owned_snapshot(project_root, evicted_snapshot_id)
        except BaseException:
            if snapshot_created and not checkpoint_committed:
                self._delete_owned_snapshot(project_root, snapshot_id)
            raise

        self._cleanup_hidden_snapshots(project_root, session_id)

        if self.logger:
            self.logger.info(
                f"Captured rollback checkpoint: session_id={session_id}, "
                f"anchor_message_id={anchor_message_id}, snapshot_id={snapshot_id}"
            )

        return checkpoint

    async def rollback_to_anchor(
        self,
        anchor_message_id: str,
        *,
        expected_operation_token: str,
    ) -> Dict[str, Any]:
        if not anchor_message_id:
            return {"success": False, "message": "Invalid rollback anchor"}

        try:
            session_state_manager, session_id, project_root = self._require_active_session()
            owner = self._capture_owner(
                session_state_manager,
                session_id=session_id,
                project_root=project_root,
            )
            checkpoint = self._get_checkpoint(
                project_root,
                session_id,
                anchor_message_id,
            )
            runtime_messages = session_state_manager.get_session_messages(
                session_id,
                project_root=project_root,
            )
            runtime_metadata = self._get_runtime_metadata_state(
                session_state_manager
            )
            current_plan = await asyncio.to_thread(
                self._build_plan,
                project_root,
                session_id,
                anchor_message_id,
                checkpoint,
                owner,
                runtime_messages,
                runtime_metadata,
            )
            if not self._is_owner_current(owner, session_state_manager):
                return self._invalidated_result(owner)
            if current_plan.preview.operation_token != expected_operation_token:
                return {
                    "success": False,
                    "plan_changed": True,
                    "message": (
                        "Workspace or conversation changed after rollback preview; "
                        "open a new preview before confirming"
                    ),
                }
            snapshot_id = str(checkpoint.get("snapshot_id", "") or "")
        except Exception as exc:
            return {"success": False, "message": str(exc)}

        watcher_was_running = False
        file_watcher = self.file_watcher
        restore_scope = self._build_session_restore_scope(session_id)
        safety_snapshot_id = self._generate_restore_safety_snapshot_id(session_id)
        safety_snapshot_created = False
        transaction_settled = False
        target_mutation_started = False
        committed_metadata: Optional[Dict[str, Any]] = None
        try:
            # Keep the safety snapshot until the session file, its exact
            # metadata entry, and the in-memory ContextManager state all agree.
            # SnapshotService's normal internal backup ends before the metadata
            # merge, so it cannot provide this cross-file transaction boundary.
            await snapshot_service.create_snapshot_async(
                project_root,
                safety_snapshot_id,
            )
            safety_snapshot_created = True

            if not self._is_owner_current(owner, session_state_manager):
                transaction_settled = True  # target was never mutated
                return self._invalidated_result(owner)

            # Snapshot creation can be slow.  Revalidate the complete plan
            # immediately before stopping the watcher or touching a target.
            runtime_messages = session_state_manager.get_session_messages(
                session_id,
                project_root=project_root,
            )
            runtime_metadata = self._get_runtime_metadata_state(
                session_state_manager
            )
            confirmed_plan = await asyncio.to_thread(
                self._build_plan,
                project_root,
                session_id,
                anchor_message_id,
                checkpoint,
                owner,
                runtime_messages,
                runtime_metadata,
            )
            if not self._is_owner_current(owner, session_state_manager):
                transaction_settled = True
                return self._invalidated_result(owner)
            if confirmed_plan.preview.operation_token != expected_operation_token:
                transaction_settled = True
                return self._plan_changed_result()

            if file_watcher is not None:
                watcher_was_running = bool(
                    getattr(file_watcher, "is_watching", False)
                ) and self._watcher_matches_owner(file_watcher, owner)
                if watcher_was_running:
                    file_watcher.stop_watching()

            # From this point an exception may mean a partially applied
            # filesystem restore, so recovery becomes mandatory.  Failures
            # before this boundary must never rewrite an untouched workspace.
            target_mutation_started = True
            await snapshot_service.restore_snapshot_async(
                project_root,
                snapshot_id,
                backup_current=False,
                scope=restore_scope,
            )
            if not self._is_owner_current(owner, session_state_manager):
                recovery_error = await self._recover_rollback_transaction(
                    project_root=project_root,
                    session_id=session_id,
                    safety_snapshot_id=safety_snapshot_id,
                    restore_scope=restore_scope,
                    session_state_manager=session_state_manager,
                    owner=owner,
                    committed_metadata=None,
                )
                transaction_settled = recovery_error is None
                result = self._invalidated_result(owner)
                if recovery_error:
                    result.update(self._recovery_failure_details(
                        project_root,
                        safety_snapshot_id,
                        recovery_error,
                    ))
                return result

            # The project-wide index is outside SnapshotRestoreScope.  Refuse
            # to overwrite a concurrent metadata edit that happened while the
            # filesystem restore was running.
            live_metadata = context_service.get_session_metadata(
                project_root,
                session_id,
            )
            if live_metadata != confirmed_plan.live_metadata:
                recovery_error = await self._recover_rollback_transaction(
                    project_root=project_root,
                    session_id=session_id,
                    safety_snapshot_id=safety_snapshot_id,
                    restore_scope=restore_scope,
                    session_state_manager=session_state_manager,
                    owner=owner,
                    committed_metadata=None,
                )
                transaction_settled = recovery_error is None
                result = self._plan_changed_result()
                if recovery_error:
                    result.update(self._recovery_failure_details(
                        project_root,
                        safety_snapshot_id,
                        recovery_error,
                    ))
                return result

            if not context_service.replace_session_metadata(
                project_root,
                session_id,
                confirmed_plan.target_metadata,
                expected_metadata=confirmed_plan.live_metadata,
            ):
                raise RuntimeError(
                    "Failed to persist rollback session metadata"
                )
            committed_metadata = copy.deepcopy(confirmed_plan.target_metadata)

            if not self._is_owner_current(owner, session_state_manager):
                recovery_error = await self._recover_rollback_transaction(
                    project_root=project_root,
                    session_id=session_id,
                    safety_snapshot_id=safety_snapshot_id,
                    restore_scope=restore_scope,
                    session_state_manager=session_state_manager,
                    owner=owner,
                    committed_metadata=committed_metadata,
                )
                transaction_settled = recovery_error is None
                result = self._invalidated_result(owner)
                if recovery_error:
                    result.update(self._recovery_failure_details(
                        project_root,
                        safety_snapshot_id,
                        recovery_error,
                    ))
                return result

            session_state_manager.reload_current_session(
                project_root=project_root,
                action="rollback",
            )
            transaction_settled = True

            self._publish_workspace_sync_required(
                project_root=project_root,
                reason="rollback",
            )
            try:
                self._cleanup_hidden_snapshots(project_root, session_id)
            except Exception as cleanup_error:
                if self.logger:
                    self.logger.warning(
                        "Rollback committed but old checkpoint cleanup failed: "
                        f"{cleanup_error}"
                    )

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
            recovery_error = None
            if safety_snapshot_created and not transaction_settled:
                if target_mutation_started:
                    recovery_error = await self._recover_rollback_transaction(
                        project_root=project_root,
                        session_id=session_id,
                        safety_snapshot_id=safety_snapshot_id,
                        restore_scope=restore_scope,
                        session_state_manager=session_state_manager,
                        owner=owner,
                        committed_metadata=committed_metadata,
                    )
                    transaction_settled = recovery_error is None
                else:
                    # The target was never touched.  Deleting our private
                    # safety snapshot is the only cleanup authorized here.
                    transaction_settled = True
            if self.logger:
                self.logger.error(
                    f"Rollback failed: session_id={session_id}, "
                    f"anchor_message_id={anchor_message_id}, error={e}"
                )
            if isinstance(e, context_service.SessionMetadataConflictError):
                result = self._plan_changed_result()
            else:
                result = {"success": False, "message": str(e)}
            if recovery_error:
                result.update(self._recovery_failure_details(
                    project_root,
                    safety_snapshot_id,
                    recovery_error,
                ))
            return result
        finally:
            if safety_snapshot_created and transaction_settled:
                self._delete_owned_snapshot(project_root, safety_snapshot_id)
            if file_watcher is not None and watcher_was_running:
                try:
                    # A project transition may have installed a new watcher
                    # while the snapshot restore was running.  Never stop or
                    # replace that watcher with the stale restore owner.
                    if self._is_owner_current(owner, session_state_manager):
                        current_watch_path = str(
                            getattr(file_watcher, "watch_path", "") or ""
                        )
                        is_watching = bool(
                            getattr(file_watcher, "is_watching", False)
                        )
                        if not is_watching:
                            file_watcher.start_watching(project_root)
                        elif (
                            current_watch_path
                            and self._normalize_project_root(current_watch_path)
                            != owner.project_root
                            and self.logger
                        ):
                            self.logger.warning(
                                "Rollback did not replace a watcher owned by "
                                f"another project: {current_watch_path}"
                            )
                except Exception as exc:
                    if self.logger:
                        self.logger.warning(f"Failed to restart file watcher after rollback: {exc}")

    def _capture_owner(
        self,
        session_state_manager: Any,
        *,
        session_id: str,
        project_root: str,
    ) -> _RollbackOwner:
        del session_state_manager  # retained in the signature for call-site clarity
        generation: Optional[int] = None
        file_manager = self.file_manager
        if file_manager is not None:
            try:
                generation = int(file_manager.project_generation)
            except Exception:
                generation = None
        return _RollbackOwner(
            project_root=self._normalize_project_root(project_root),
            session_id=str(session_id or ""),
            file_generation=generation,
        )

    def _is_owner_current(
        self,
        owner: _RollbackOwner,
        session_state_manager: Any,
    ) -> bool:
        try:
            current_root = self._normalize_project_root(
                session_state_manager.get_project_root()
            )
            current_session = str(
                session_state_manager.get_current_session_id() or ""
            )
        except Exception:
            return False

        if (
            current_root != owner.project_root
            or current_session != owner.session_id
        ):
            return False

        if owner.file_generation is not None:
            file_manager = self.file_manager
            if file_manager is None:
                return False
            try:
                if int(file_manager.project_generation) != owner.file_generation:
                    return False
            except Exception:
                return False
        return True

    @staticmethod
    def _normalize_project_root(project_root: str) -> str:
        if not project_root:
            return ""
        return os.path.normcase(
            os.path.realpath(os.path.abspath(os.fspath(project_root)))
        )

    @staticmethod
    def _require_safe_snapshot_id(snapshot_id: str) -> str:
        """Require the exact canonical ID used by rollback-owned snapshots."""

        value = str(snapshot_id or "")
        if not value or any(
            not (
                character.isascii()
                and (character.isalnum() or character in "_-")
            )
            for character in value
        ):
            raise RuntimeError("Invalid rollback snapshot ID")
        return value

    def _watcher_matches_owner(
        self,
        file_watcher: Any,
        owner: _RollbackOwner,
    ) -> bool:
        watch_path = str(getattr(file_watcher, "watch_path", "") or "")
        # Some lightweight/test watchers do not expose their bound path.  The
        # authoritative session + FileManager identity still protects the
        # commit/restart path in that case.
        if not watch_path:
            return True
        return self._normalize_project_root(watch_path) == owner.project_root

    @staticmethod
    def _invalidated_result(owner: _RollbackOwner) -> Dict[str, Any]:
        return {
            "success": False,
            "invalidated": True,
            "message": "Project or conversation changed during rollback",
            "session_id": owner.session_id,
        }

    @staticmethod
    def _plan_changed_result() -> Dict[str, Any]:
        return {
            "success": False,
            "plan_changed": True,
            "message": (
                "Workspace or conversation changed after rollback preview; "
                "open a new preview before confirming"
            ),
        }

    async def _recover_rollback_transaction(
        self,
        *,
        project_root: str,
        session_id: str,
        safety_snapshot_id: str,
        restore_scope: snapshot_service.SnapshotRestoreScope,
        session_state_manager: Any,
        owner: _RollbackOwner,
        committed_metadata: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        """Restore the pre-confirm filesystem and metadata after a failed commit.

        The safety snapshot is intentionally retained when recovery itself
        fails, matching SnapshotService's double-failure contract.
        """

        try:
            await snapshot_service.restore_snapshot_async(
                project_root,
                safety_snapshot_id,
                backup_current=False,
                scope=restore_scope,
            )
        except Exception as exc:
            return f"failed to restore the safety snapshot: {exc}"

        if committed_metadata is not None:
            try:
                previous_metadata = self._load_snapshot_session_metadata(
                    project_root,
                    safety_snapshot_id,
                    session_id,
                )
                if not context_service.replace_session_metadata(
                    project_root,
                    session_id,
                    previous_metadata,
                    expected_metadata=committed_metadata,
                ):
                    return "failed to restore the previous session metadata"
            except Exception as exc:
                return f"failed to restore the previous session metadata: {exc}"

        if self._is_owner_current(owner, session_state_manager):
            try:
                session_state_manager.reload_current_session(
                    project_root=project_root,
                    action="rollback_recovery",
                )
            except Exception as exc:
                return f"failed to reload the recovered conversation: {exc}"
        return None

    @staticmethod
    def _recovery_failure_details(
        project_root: str,
        safety_snapshot_id: str,
        recovery_error: str,
    ) -> Dict[str, Any]:
        safety_path = (
            Path(project_root).resolve()
            / snapshot_service.SNAPSHOTS_DIR
            / safety_snapshot_id
        )
        return {
            "success": False,
            "recovery_failed": True,
            "safety_snapshot_path": str(safety_path),
            "message": (
                "Automatic rollback recovery failed; the safety snapshot was "
                f"preserved at {safety_path}: {recovery_error}"
            ),
        }

    @staticmethod
    def _get_runtime_metadata_state(
        session_state_manager: Any,
    ) -> Dict[str, Any]:
        """Capture unsaved persisted fields so confirm detects live changes."""

        context_manager = getattr(session_state_manager, "context_manager", None)
        if context_manager is None:
            return {}
        try:
            state = context_manager.get_current_state() or {}
        except Exception:
            return {}
        if not isinstance(state, dict):
            return {}
        defaults = {
            WORKING_CONTEXT_SUMMARY_KEY: "",
            WORKING_CONTEXT_COMPRESSED_COUNT_KEY: 0,
            WORKING_CONTEXT_KEEP_RECENT_KEY: 0,
            "circuit_file_path": "",
            "last_metrics": {},
            "error_context": "",
        }
        return {
            key: copy.deepcopy(state.get(key, default))
            for key, default in defaults.items()
        }

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

        self._require_safe_snapshot_id(snapshot_id)

        return checkpoint

    def _build_plan(
        self,
        project_root: str,
        session_id: str,
        anchor_message_id: str,
        checkpoint: Dict[str, Any],
        owner: _RollbackOwner,
        runtime_messages: List[Dict[str, Any]],
        runtime_metadata: Dict[str, Any],
    ) -> _RollbackPlan:
        snapshot_id = str(checkpoint.get("snapshot_id", "") or "")
        # SnapshotService validates the complete source tree for symlinks,
        # junctions, and reparse points.  Do that before directly opening any
        # session file inside the snapshot.
        restore_preview = snapshot_service.preview_restore_snapshot(
            project_root,
            snapshot_id,
            scope=self._build_session_restore_scope(session_id),
        )
        current_messages = context_service.load_messages(project_root, session_id)
        target_messages = self._load_snapshot_session_messages(
            project_root,
            snapshot_id,
            session_id,
        )
        live_metadata = context_service.get_session_metadata(
            project_root,
            session_id,
        )
        if live_metadata is None:
            raise RuntimeError("Current rollback session metadata is missing")
        live_metadata = copy.deepcopy(live_metadata)
        target_metadata = self._load_snapshot_session_metadata(
            project_root,
            snapshot_id,
            session_id,
        )

        changed_files = list(restore_preview.changed_files)
        metadata_change = self._build_session_metadata_change(
            session_id=session_id,
            live_metadata=live_metadata,
            target_metadata=target_metadata,
        )
        if metadata_change is not None:
            changed_files.append(metadata_change)
            changed_files.sort(key=lambda change: change.relative_path)
        removed_messages = self._build_removed_messages(current_messages, target_messages)
        anchor_message = next(
            (
                message
                for message in current_messages
                if get_serialized_message_id(message) == anchor_message_id
            ),
            None,
        )

        preview = ConversationRollbackPreview(
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
            operation_token=self._build_operation_token(
                owner=owner,
                snapshot_id=snapshot_id,
                anchor_message_id=anchor_message_id,
                runtime_messages=runtime_messages,
                runtime_metadata=runtime_metadata,
                live_metadata=live_metadata,
                target_metadata=target_metadata,
                changed_files=changed_files,
            ),
        )
        return _RollbackPlan(
            preview=preview,
            live_metadata=live_metadata,
            target_metadata=target_metadata,
        )

    @staticmethod
    def _build_operation_token(
        *,
        owner: _RollbackOwner,
        snapshot_id: str,
        anchor_message_id: str,
        runtime_messages: List[Dict[str, Any]],
        runtime_metadata: Dict[str, Any],
        live_metadata: Dict[str, Any],
        target_metadata: Dict[str, Any],
        changed_files: List[snapshot_service.SnapshotFileChange],
    ) -> str:
        """Fingerprint the complete scoped restore plan and its owner."""
        payload = {
            "version": 2,
            "project_root": owner.project_root,
            "session_id": owner.session_id,
            "file_generation": owner.file_generation,
            "snapshot_id": snapshot_id,
            "anchor_message_id": anchor_message_id,
            "runtime_messages": runtime_messages,
            "runtime_metadata": runtime_metadata,
            "live_metadata": live_metadata,
            "target_metadata": target_metadata,
            "changes": [
                {
                    "relative_path": change.relative_path,
                    "change_type": change.change_type,
                    "current_revision": change.current_revision,
                    "snapshot_revision": change.snapshot_revision,
                }
                for change in changed_files
            ],
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _load_snapshot_session_messages(
        self,
        project_root: str,
        snapshot_id: str,
        session_id: str,
    ) -> List[Dict[str, Any]]:
        if not session_id or Path(session_id).name != session_id:
            raise RuntimeError("Invalid conversation session ID")
        self._require_safe_snapshot_id(snapshot_id)

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

    def _load_snapshot_session_metadata(
        self,
        project_root: str,
        snapshot_id: str,
        session_id: str,
    ) -> Dict[str, Any]:
        """Load the one session-index entry captured by a snapshot.

        Callers must validate the complete snapshot tree through
        ``preview_restore_snapshot`` or ``restore_snapshot_async`` before this
        direct read.  The rollback plan does the former, while recovery does
        the latter before reading its service-owned safety snapshot.
        """

        if not session_id or Path(session_id).name != session_id:
            raise RuntimeError("Invalid conversation session ID")
        self._require_safe_snapshot_id(snapshot_id)

        snapshot_index_file = (
            Path(project_root).resolve()
            / snapshot_service.SNAPSHOTS_DIR
            / snapshot_id
            / context_service.CONVERSATIONS_DIR
            / context_service.SESSIONS_INDEX_FILE
        )
        if not snapshot_index_file.exists():
            raise RuntimeError("Rollback session metadata snapshot is missing")

        try:
            payload = json.loads(snapshot_index_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(
                f"Failed to read rollback session metadata snapshot: {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise RuntimeError("Rollback session metadata snapshot is invalid")
        sessions = payload.get("sessions")
        if not isinstance(sessions, list) or not all(
            isinstance(item, dict) for item in sessions
        ):
            raise RuntimeError("Rollback session metadata snapshot is invalid")

        matches = [
            item for item in sessions
            if item.get("session_id") == session_id
        ]
        if len(matches) != 1:
            raise RuntimeError(
                "Rollback session metadata snapshot must contain exactly one "
                f"entry for {session_id!r}; found {len(matches)}"
            )
        return copy.deepcopy(matches[0])

    @staticmethod
    def _build_session_metadata_change(
        *,
        session_id: str,
        live_metadata: Dict[str, Any],
        target_metadata: Dict[str, Any],
    ) -> Optional[snapshot_service.SnapshotFileChange]:
        """Expose the exact per-session metadata merge in confirmation UI."""

        if live_metadata == target_metadata:
            return None

        current_text = json.dumps(
            live_metadata,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        )
        target_text = json.dumps(
            target_metadata,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        )

        def revision(value: Dict[str, Any]) -> str:
            canonical = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"

        changed_keys = sorted(
            key
            for key in set(live_metadata) | set(target_metadata)
            if live_metadata.get(key) != target_metadata.get(key)
        )
        changed_label = ", ".join(changed_keys[:6])
        if len(changed_keys) > 6:
            changed_label = f"{changed_label}, ..."

        conversations_dir = (
            context_service.CONVERSATIONS_DIR.replace("\\", "/").strip("/")
        )
        return snapshot_service.SnapshotFileChange(
            relative_path=(
                f"{conversations_dir}/{context_service.SESSIONS_INDEX_FILE}"
            ),
            change_type="modified",
            summary=(
                f"Restore metadata for session {session_id} only"
                + (f" ({changed_label})" if changed_label else "")
            ),
            # This is one logical entry replacement, not a whole-file restore.
            # Line counts communicate that a persisted state record changes
            # without pretending unrelated sessions are rewritten from history.
            added_lines=len(target_text.splitlines()),
            deleted_lines=len(current_text.splitlines()),
            diff_preview="",
            is_text=True,
            current_revision=revision(live_metadata),
            snapshot_revision=revision(target_metadata),
        )

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

    def _build_session_restore_scope(
        self,
        session_id: str,
    ) -> snapshot_service.SnapshotRestoreScope:
        # Session IDs are filenames in context_service.  Reject path-like IDs
        # before constructing a restore allowlist so the scope cannot escape
        # the conversations directory.
        if not session_id or Path(session_id).name != session_id:
            raise RuntimeError("Invalid conversation session ID")

        conversations_dir = context_service.CONVERSATIONS_DIR.replace("\\", "/").strip("/")
        return snapshot_service.SnapshotRestoreScope(
            protected_roots=(SYSTEM_DIR,),
            allowed_paths=(
                f"{conversations_dir}/{session_id}.json",
                (
                    f"{conversations_dir}/{session_id}"
                    f"{context_service.ROLLBACK_CHECKPOINTS_SUFFIX}"
                ),
            ),
        )

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

    def _delete_owned_snapshot(self, project_root: str, snapshot_id: str) -> None:
        """Best-effort cleanup for a unique snapshot created by this call."""
        try:
            snapshot_service.delete_snapshot(project_root, snapshot_id)
        except Exception as exc:
            if self.logger:
                self.logger.warning(
                    "Failed to clean orphan rollback snapshot "
                    f"{snapshot_id}: {exc}"
                )

    def _generate_snapshot_id(self, session_id: str, anchor_message_id: str) -> str:
        session_prefix = self._get_session_snapshot_prefix(session_id)
        safe_anchor = "".join(ch for ch in anchor_message_id if ch.isalnum())[:12] or "anchor"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return f"{session_prefix}{timestamp}_{safe_anchor}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _generate_restore_safety_snapshot_id(session_id: str) -> str:
        session_identity = hashlib.sha256(
            str(session_id or "session").encode("utf-8")
        ).hexdigest()[:24]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return (
            f"_conv_restore_backup_{session_identity}_{timestamp}_"
            f"{uuid.uuid4().hex[:8]}"
        )

    def _get_session_snapshot_prefix(self, session_id: str) -> str:
        # Cleanup ownership must not depend on a truncated session ID: generated
        # IDs share a long timestamp prefix, so truncation could make one
        # session delete another session's rollback snapshots.
        session_identity = hashlib.sha256(
            str(session_id or "session").encode("utf-8")
        ).hexdigest()[:24]
        return f"_conv_turn_{session_identity}_"


__all__ = [
    "RollbackMessageSummary",
    "ConversationRollbackPreview",
    "ConversationRollbackService",
]
