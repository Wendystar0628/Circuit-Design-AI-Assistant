"""Headless lifecycle and application API for the desktop sidecar.

This module is the composition root for non-visual application services.  It
deliberately owns no web framework objects: FastAPI adapts these operations in
``desktop_backend`` while domain tools continue to use the same service graph.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import mimetypes
import os
import secrets
import shutil
import stat
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Iterable, Optional


EventEmitter = Callable[[str, str, Dict[str, Any], Dict[str, Any]], None]


class RuntimeErrorResponse(RuntimeError):
    """An expected API-facing runtime failure with an HTTP status."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class ProjectIdentity:
    project_id: str
    root: str
    name: str
    generation: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class _DocumentIdentity:
    document_id: str
    path: str
    revision: int
    digest: str


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _view_kind(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix in {".cir", ".sp", ".spice", ".py", ".js", ".ts", ".tsx", ".json", ".yaml", ".yml", ".toml", ".css", ".html", ".svg"}:
        return "code"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
        return "image"
    if suffix == ".pdf":
        return "pdf"
    return "text"


def _json_safe(value: Any) -> Any:
    """Convert domain values to strict JSON-compatible values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    if hasattr(value, "value"):
        return _json_safe(value.value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


class ApplicationRuntime:
    """Own the complete headless service lifecycle and current identities."""

    def __init__(self, emit_event: Optional[EventEmitter] = None) -> None:
        self._emit_event = emit_event
        self._started = False
        self._closing = False
        self._identity_lock = threading.RLock()
        self._project: Optional[ProjectIdentity] = None
        self._documents: Dict[str, _DocumentIdentity] = {}
        self._documents_by_id: Dict[str, _DocumentIdentity] = {}
        self._result_paths: Dict[str, str] = {}
        self._result_jobs: Dict[str, Optional[str]] = {}
        self._attachments: Dict[str, Dict[str, Any]] = {}
        self._active_conversation_task: Optional[asyncio.Task[None]] = None
        self._active_run_id: Optional[str] = None
        self._active_context_id: Optional[str] = None
        self.llm_client = None

        # Populated by start().  Keeping the attributes explicit makes partial
        # startup cleanup deterministic.
        self.event_bus = None
        self.credential_manager = None
        self.config_manager = None
        self.llm_runtime_config_manager = None
        self.file_manager = None
        self.file_search_service = None
        self.session_state = None
        self.session_state_projector = None
        self.context_manager = None
        self.session_state_manager = None
        self.project_service = None
        self.simulation_result_repository = None
        self.simulation_job_manager = None
        self.rag_manager = None
        self.document_watcher = None
        self.file_watcher = None
        self.pending_workspace_edit_service = None
        self.metric_target_service = None
        self.conversation_rollback_service = None
        self.context_compression_service = None
        self._bus_subscriptions: list[tuple[str, Callable[[Dict[str, Any]], None]]] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._started:
            return

        # Filesystem/log/native configuration belongs to this process-level
        # composition root.  In particular ngspice discovery must happen
        # before SpiceExecutor is imported or constructed.
        from infrastructure.config.settings import GLOBAL_CONFIG_DIR, GLOBAL_LOG_DIR
        from infrastructure.utils.logger import setup_logger
        from infrastructure.utils.model_config import configure_models
        from infrastructure.utils.ngspice_config import configure_ngspice

        GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        GLOBAL_LOG_DIR.mkdir(parents=True, exist_ok=True)
        setup_logger(log_dir=GLOBAL_LOG_DIR)
        configure_models()
        configure_ngspice()

        from application.session_state import SessionState
        from application.session_state_projector import SessionStateProjector
        from application.project_service import ProjectService
        from domain.llm.context_manager import ContextManager
        from domain.llm.session_state_manager import SessionStateManager
        from domain.rag.document_watcher import DocumentWatcher
        from domain.rag.rag_manager import RAGManager
        from domain.services.simulation_job_manager import SimulationJobManager
        from domain.services.simulation_service import SimulationService
        from domain.simulation.service.simulation_result_repository import (
            SimulationResultRepository,
        )
        from infrastructure.config.config_manager import ConfigManager
        from infrastructure.config.credential_manager import CredentialManager
        from infrastructure.config.llm_runtime_config_manager import (
            LLMRuntimeConfigManager,
        )
        from infrastructure.file_intelligence.search.file_search_service import (
            FileSearchService,
        )
        from infrastructure.persistence.file_manager import FileManager
        from shared.embedding_model_registry import EmbeddingModelRegistry
        from shared.event_bus import EventBus
        from shared.model_registry import ModelRegistry
        from shared.service_locator import ServiceLocator
        from shared.service_names import (
            SVC_CONFIG_MANAGER,
            SVC_CONTEXT_MANAGER,
            SVC_CREDENTIAL_MANAGER,
            SVC_EVENT_BUS,
            SVC_FILE_MANAGER,
            SVC_FILE_SEARCH_SERVICE,
            SVC_FILE_WATCHER,
            SVC_CONVERSATION_ROLLBACK_SERVICE,
            SVC_CONTEXT_COMPRESSION_SERVICE,
            SVC_LLM_RUNTIME_CONFIG_MANAGER,
            SVC_METRIC_TARGET_SERVICE,
            SVC_PENDING_WORKSPACE_EDIT_SERVICE,
            SVC_PROJECT_SERVICE,
            SVC_RAG_MANAGER,
            SVC_SESSION_STATE,
            SVC_SESSION_STATE_MANAGER,
            SVC_SESSION_STATE_PROJECTOR,
            SVC_SIMULATION_JOB_MANAGER,
        )

        ServiceLocator.clear()
        try:
            self.event_bus = EventBus()
            ServiceLocator.register(SVC_EVENT_BUS, self.event_bus)

            self.credential_manager = CredentialManager()
            self.credential_manager.load_credentials()
            ServiceLocator.register(SVC_CREDENTIAL_MANAGER, self.credential_manager)

            self.config_manager = ConfigManager()
            self.config_manager.load_config()
            ServiceLocator.register(SVC_CONFIG_MANAGER, self.config_manager)

            ModelRegistry.initialize()
            EmbeddingModelRegistry.initialize()
            self.llm_runtime_config_manager = LLMRuntimeConfigManager(
                self.config_manager,
                self.credential_manager,
            )
            ServiceLocator.register(
                SVC_LLM_RUNTIME_CONFIG_MANAGER,
                self.llm_runtime_config_manager,
            )

            self.file_manager = FileManager()
            self.file_manager.cleanup_temp_files()
            ServiceLocator.register(SVC_FILE_MANAGER, self.file_manager)
            self.file_search_service = FileSearchService()
            ServiceLocator.register(SVC_FILE_SEARCH_SERVICE, self.file_search_service)

            self.session_state = SessionState()
            ServiceLocator.register(SVC_SESSION_STATE, self.session_state)
            self.session_state_projector = SessionStateProjector(
                self.session_state,
                event_bus=self.event_bus,
            )
            ServiceLocator.register(
                SVC_SESSION_STATE_PROJECTOR,
                self.session_state_projector,
            )

            self.context_manager = ContextManager()
            ServiceLocator.register(SVC_CONTEXT_MANAGER, self.context_manager)
            self.session_state_manager = SessionStateManager()
            ServiceLocator.register(
                SVC_SESSION_STATE_MANAGER,
                self.session_state_manager,
            )
            from application.metric_target_service import MetricTargetService
            from application.pending_workspace_edit_service import (
                PendingWorkspaceEditService,
            )

            self.pending_workspace_edit_service = PendingWorkspaceEditService()
            ServiceLocator.register(
                SVC_PENDING_WORKSPACE_EDIT_SERVICE,
                self.pending_workspace_edit_service,
            )
            self.metric_target_service = MetricTargetService()
            ServiceLocator.register(
                SVC_METRIC_TARGET_SERVICE,
                self.metric_target_service,
            )
            from application.tasks.file_watch_task import FileWatchTask
            from domain.llm.context_compression_service import (
                ContextCompressionService,
            )
            from domain.llm.conversation_rollback_service import (
                ConversationRollbackService,
            )

            self.file_watcher = FileWatchTask()
            ServiceLocator.register(SVC_FILE_WATCHER, self.file_watcher)
            self.conversation_rollback_service = ConversationRollbackService()
            ServiceLocator.register(
                SVC_CONVERSATION_ROLLBACK_SERVICE,
                self.conversation_rollback_service,
            )
            self.context_compression_service = ContextCompressionService()
            ServiceLocator.register(
                SVC_CONTEXT_COMPRESSION_SERVICE,
                self.context_compression_service,
            )
            self.project_service = ProjectService()
            ServiceLocator.register(SVC_PROJECT_SERVICE, self.project_service)

            from domain.simulation.executor.spice_executor import SpiceExecutor

            self.simulation_result_repository = SimulationResultRepository()
            self.simulation_job_manager = SimulationJobManager(
                simulation_service=SimulationService(executor=SpiceExecutor()),
                result_repository=self.simulation_result_repository,
                event_bus=self.event_bus,
            )
            ServiceLocator.register(
                SVC_SIMULATION_JOB_MANAGER,
                self.simulation_job_manager,
            )

            self.rag_manager = RAGManager(event_bus=self.event_bus)
            self.document_watcher = DocumentWatcher(
                event_bus=self.event_bus,
                rag_manager=self.rag_manager,
                file_manager=self.file_manager,
            )
            self.rag_manager.attach_document_watcher(self.document_watcher)
            self.rag_manager.subscribe_lifecycle_events()
            self.document_watcher.start()
            self.session_state_projector.subscribe_rag_events()
            ServiceLocator.register(SVC_RAG_MANAGER, self.rag_manager)

            self._subscribe_domain_events()
            self._started = True
            await self.refresh_llm()
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        if self._closing:
            return
        self._closing = True
        try:
            task = self._active_conversation_task
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self._active_conversation_task = None
            self._active_run_id = None

            if self.context_compression_service is not None:
                await self.context_compression_service.shutdown()
            if self.simulation_job_manager is not None:
                self.simulation_job_manager.close(timeout=2.0)
            if self.project_service is not None and self.project_service.is_project_open():
                self.project_service.close_project()
            if self.file_watcher is not None:
                self.file_watcher.stop_watching()
            if self.session_state_projector is not None:
                self.session_state_projector.shutdown()
            if self.rag_manager is not None:
                self.rag_manager.stop()
            await self._close_llm_client()
            if self.event_bus is not None:
                self.event_bus.clear_all()
            from shared.service_locator import ServiceLocator

            ServiceLocator.clear()
            self._started = False
        finally:
            self._closing = False

    async def _close_llm_client(self) -> None:
        client = self.llm_client
        self.llm_client = None
        if client is None:
            return
        close = getattr(client, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    async def refresh_llm(self) -> bool:
        """Replace the active client on the current asyncio loop."""
        from shared.service_locator import ServiceLocator
        from shared.service_names import SVC_LLM_CLIENT

        await self._close_llm_client()
        ServiceLocator.unregister(SVC_LLM_CLIENT)
        if self.llm_runtime_config_manager is None:
            return False
        active = self.llm_runtime_config_manager.resolve_active_config()
        if not active.is_configured or not active.api_key:
            return False
        from infrastructure.llm_adapters import LLMClientFactory

        self.llm_client = LLMClientFactory.create_client(
            provider_id=active.provider,
            api_key=active.api_key,
            base_url=active.base_url or None,
            model=active.model or None,
            timeout=active.timeout,
        )
        ServiceLocator.register(SVC_LLM_CLIENT, self.llm_client)
        return True

    # ------------------------------------------------------------------
    # Current project and containment
    # ------------------------------------------------------------------

    @property
    def project(self) -> Optional[ProjectIdentity]:
        with self._identity_lock:
            return self._project

    def require_project(self, project_id: str) -> ProjectIdentity:
        project = self.project
        if project is None:
            raise RuntimeErrorResponse(409, "No project is open")
        if not project_id or not secrets.compare_digest(project.project_id, project_id):
            raise RuntimeErrorResponse(409, "Stale or foreign project_id")
        return project

    def open_project(self, raw_path: str) -> ProjectIdentity:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise RuntimeErrorResponse(422, "path is required")
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            raise RuntimeErrorResponse(422, "Project path must be absolute")
        try:
            candidate = candidate.resolve(strict=True)
        except OSError as exc:
            raise RuntimeErrorResponse(404, f"Project directory is unavailable: {exc}") from exc
        if not candidate.is_dir():
            raise RuntimeErrorResponse(422, "Project path must be an existing directory")
        if self._is_reparse_point(candidate):
            raise RuntimeErrorResponse(422, "Project root cannot be a link or reparse point")

        current = self.project
        if current is not None:
            if os.path.normcase(current.root) == os.path.normcase(str(candidate)):
                return current
            self._ensure_no_active_conversation()
            self.close_project(current.project_id)

        success, message = self.project_service.initialize_project(str(candidate))
        if not success:
            raise RuntimeErrorResponse(422, message)
        with self._identity_lock:
            self._project = ProjectIdentity(
                project_id=secrets.token_urlsafe(24),
                root=str(candidate),
                name=candidate.name,
                generation=int(self.file_manager.project_generation),
            )
            self._reset_project_handles()
            project = self._project
        self.emit("project.opened", {"project": project.to_dict()})
        return project

    def close_project(self, project_id: str) -> None:
        project = self.require_project(project_id)
        self._ensure_no_active_conversation()
        success, message = self.project_service.close_project()
        if not success:
            raise RuntimeErrorResponse(409, message)
        self.emit("project.closed", {"project_id": project.project_id})
        with self._identity_lock:
            self._project = None
            self._reset_project_handles()

    def _reset_project_handles(self) -> None:
        self._documents.clear()
        self._documents_by_id.clear()
        self._result_paths.clear()
        self._result_jobs.clear()
        self._attachments.clear()
        self._active_context_id = None

    def resolve_project_path(
        self,
        project_id: str,
        relative_path: str,
        *,
        must_exist: bool = False,
        allow_root: bool = False,
    ) -> Path:
        project = self.require_project(project_id)
        if not isinstance(relative_path, str):
            raise RuntimeErrorResponse(422, "path must be a string")
        normalized = relative_path.replace("\\", "/").strip("/")
        if not normalized:
            if allow_root:
                return Path(project.root)
            raise RuntimeErrorResponse(422, "path is required")
        portable = PurePosixPath(normalized)
        if (
            portable.is_absolute()
            or portable.as_posix() != normalized
            or any(part in {"", ".", ".."} or ":" in part for part in portable.parts)
        ):
            raise RuntimeErrorResponse(422, "path must be a safe project-relative path")

        root = Path(project.root).resolve(strict=True)
        candidate = root.joinpath(*portable.parts)
        self._reject_reparse_components(root, candidate)
        resolved = candidate.resolve(strict=must_exist)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise RuntimeErrorResponse(422, "path escapes the current project") from exc
        if must_exist and not resolved.exists():
            raise RuntimeErrorResponse(404, "Workspace entry does not exist")
        return resolved

    @classmethod
    def _reject_reparse_components(cls, root: Path, candidate: Path) -> None:
        current = root
        try:
            parts = candidate.relative_to(root).parts
        except ValueError as exc:
            raise RuntimeErrorResponse(422, "path escapes the current project") from exc
        if cls._is_reparse_point(root):
            raise RuntimeErrorResponse(422, "Project root cannot be a link or reparse point")
        for part in parts:
            current = current / part
            if current.exists() and cls._is_reparse_point(current):
                raise RuntimeErrorResponse(422, "Linked workspace paths are not allowed")

    @staticmethod
    def _is_reparse_point(path: Path) -> bool:
        if path.is_symlink():
            return True
        try:
            attributes = path.stat(follow_symlinks=False).st_file_attributes
        except (AttributeError, OSError):
            return False
        return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)

    # ------------------------------------------------------------------
    # Workspace
    # ------------------------------------------------------------------

    def workspace_tree(self, project_id: str, path: str = "", depth: int = 1) -> Dict[str, Any]:
        base = self.resolve_project_path(project_id, path, must_exist=True, allow_root=True)
        if not base.is_dir():
            raise RuntimeErrorResponse(422, "tree path must identify a directory")
        root = Path(self.require_project(project_id).root)
        depth = max(1, min(int(depth), 4))

        def build(directory: Path, remaining: int) -> list[Dict[str, Any]]:
            entries: list[Dict[str, Any]] = []
            for item in sorted(directory.iterdir(), key=lambda value: (not value.is_dir(), value.name.casefold())):
                if self._is_reparse_point(item) or item.name == ".circuit_ai":
                    continue
                relative = item.relative_to(root).as_posix()
                is_directory = item.is_dir()
                has_children = False
                if is_directory:
                    try:
                        has_children = any(
                            child.name != ".circuit_ai" and not self._is_reparse_point(child)
                            for child in item.iterdir()
                        )
                    except OSError:
                        has_children = False
                entry: Dict[str, Any] = {
                    "path": relative,
                    "name": item.name,
                    "kind": "directory" if is_directory else "file",
                    "has_children": has_children,
                    "view_kind": "text" if is_directory else _view_kind(item),
                    "is_dirty": False,
                }
                if is_directory and remaining > 1:
                    entry["children"] = build(item, remaining - 1)
                entries.append(entry)
            return entries

        return {
            "project_id": project_id,
            "revision": self.require_project(project_id).generation,
            "entries": build(base, depth),
        }

    def read_document(self, project_id: str, path: str) -> Dict[str, Any]:
        file_path = self.resolve_project_path(project_id, path, must_exist=True)
        if not file_path.is_file():
            raise RuntimeErrorResponse(422, "path must identify a file")
        view_kind = _view_kind(file_path)
        raw = file_path.read_bytes()
        if view_kind in {"image", "pdf"}:
            content: Optional[str] = None
        else:
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RuntimeErrorResponse(415, "File is not UTF-8 text") from exc
        identity = self._document_identity(path, _digest_bytes(raw))
        return {
            "project_id": project_id,
            "document_id": identity.document_id,
            "path": path,
            "name": file_path.name,
            "view_kind": view_kind,
            "revision": identity.revision,
            "content": content,
            "mime_type": mimetypes.guess_type(file_path.name)[0] or "text/plain",
            "readonly": not os.access(file_path, os.W_OK),
        }

    def _document_identity(self, path: str, digest: str) -> _DocumentIdentity:
        identity = self._documents.get(path)
        if identity is None:
            identity = _DocumentIdentity(secrets.token_urlsafe(18), path, 1, digest)
            self._documents[path] = identity
            self._documents_by_id[identity.document_id] = identity
        elif identity.digest != digest:
            identity.revision += 1
            identity.digest = digest
        return identity

    def document_path(self, project_id: str, document_id: str) -> str:
        self.require_project(project_id)
        identity = self._documents_by_id.get(document_id)
        if identity is None:
            raise RuntimeErrorResponse(409, "Stale or foreign document_id")
        return identity.path

    def write_document(
        self,
        project_id: str,
        path: str,
        document_id: str,
        base_revision: int,
        content: str,
    ) -> Dict[str, Any]:
        file_path = self.resolve_project_path(project_id, path, must_exist=True)
        if not file_path.is_file():
            raise RuntimeErrorResponse(422, "path must identify a file")
        identity = self._documents_by_id.get(document_id)
        if identity is None or identity.path != path:
            raise RuntimeErrorResponse(409, "Stale or foreign document_id")
        current_digest = _digest_bytes(file_path.read_bytes())
        identity = self._document_identity(path, current_digest)
        if base_revision != identity.revision:
            raise RuntimeErrorResponse(409, "Document revision conflict")
        encoded = content.encode("utf-8")
        # FileManager owns atomic disk writes and the canonical FileChange
        # event consumed by RAG and file search.
        self.file_manager.write_file(file_path, content)
        identity.revision += 1
        identity.digest = _digest_bytes(encoded)
        return {
            "project_id": project_id,
            "document_id": identity.document_id,
            "path": path,
            "revision": identity.revision,
        }

    def create_entry(self, project_id: str, parent_path: str, name: str, kind: str) -> None:
        if not isinstance(name, str) or not name.strip() or name in {".", ".."} or any(char in name for char in "/\\:"):
            raise RuntimeErrorResponse(422, "name must be one safe path segment")
        parent = self.resolve_project_path(project_id, parent_path, must_exist=True, allow_root=True)
        if not parent.is_dir():
            raise RuntimeErrorResponse(422, "parent_path must identify a directory")
        target_relative = (PurePosixPath(parent_path) / name).as_posix() if parent_path else name
        target = self.resolve_project_path(project_id, target_relative)
        if target.exists():
            raise RuntimeErrorResponse(409, "Workspace entry already exists")
        if kind == "directory":
            target.mkdir()
            self._publish_file_change(project_id, target_relative, "create", is_directory=True)
        elif kind == "file":
            self.file_manager.create_file(target, "")
        else:
            raise RuntimeErrorResponse(422, "kind must be 'file' or 'directory'")

    def move_entry(self, project_id: str, source_path: str, destination_path: str) -> None:
        source = self.resolve_project_path(project_id, source_path, must_exist=True)
        destination = self.resolve_project_path(project_id, destination_path)
        if destination.exists():
            raise RuntimeErrorResponse(409, "Destination already exists")
        if not destination.parent.is_dir():
            raise RuntimeErrorResponse(422, "Destination parent does not exist")
        if source.is_dir():
            try:
                destination.relative_to(source)
            except ValueError:
                pass
            else:
                raise RuntimeErrorResponse(422, "Cannot move a directory inside itself")
        self.file_manager.move_file(source, destination)

    def delete_entry(self, project_id: str, path: str) -> None:
        target = self.resolve_project_path(project_id, path, must_exist=True)
        if target.is_dir():
            shutil.rmtree(target)
            self._publish_file_change(project_id, path, "delete", is_directory=True)
        else:
            self.file_manager.delete_file(target)

    def _publish_file_change(
        self,
        project_id: str,
        path: str,
        operation: str,
        *,
        dest_path: str = "",
        is_directory: bool = False,
    ) -> None:
        if self.event_bus is not None:
            from shared.event_types import EVENT_FILE_CHANGED
            from shared.file_change import FileChange

            absolute = self.resolve_project_path(project_id, path, allow_root=False)
            destination = (
                self.resolve_project_path(project_id, dest_path, allow_root=False)
                if dest_path
                else None
            )
            change = FileChange(
                operation=operation,
                path=str(absolute),
                dest_path=str(destination or ""),
                is_directory=is_directory,
                origin="desktop_backend",
                project_root=self.require_project(project_id).root,
                generation=int(self.file_manager.project_generation),
                revision="missing" if operation == "delete" else self._path_revision(absolute),
            )
            self.event_bus.publish(
                EVENT_FILE_CHANGED,
                change.to_payload(),
                source="desktop_backend",
            )

    @staticmethod
    def _path_revision(path: Path) -> str:
        if path.is_file():
            return _digest_bytes(path.read_bytes())
        if path.is_dir():
            return hashlib.sha256(
                "\n".join(sorted(item.name for item in path.iterdir())).encode("utf-8")
            ).hexdigest()
        return "missing"

    # ------------------------------------------------------------------
    # Conversation
    # ------------------------------------------------------------------

    def conversation_state(self, project_id: str) -> Dict[str, Any]:
        self.require_project(project_id)
        session_id = self.session_state_manager.get_current_session_id()
        context_id = self._context_for_session(session_id)
        from domain.llm.message_helpers import messages_to_dicts

        rollback_anchors = self.conversation_rollback_service.get_available_anchor_ids()
        messages = [
            self._conversation_message_dto(message, rollback_anchors)
            for message in messages_to_dicts(self.context_manager.get_display_messages())
        ]
        active = self.llm_runtime_config_manager.resolve_active_config()
        pending_summary = self.pending_workspace_edit_service.get_summary_state()
        is_generating = bool(
            self._active_conversation_task
            and not self._active_conversation_task.done()
        )
        return {
            "project_id": project_id,
            "context_id": context_id,
            "active_run_id": self._active_run_id or "",
            "ui": {"active_surface": "conversation"},
            "ui_text": {},
            "session": {
                "id": session_id,
                "name": self.session_state_manager.get_current_session_name(),
            },
            "conversation": {
                "messages": _json_safe(messages),
                "runtime_steps": [],
                "message_count": len(messages),
                "is_loading": is_generating,
                "can_send": bool(self.llm_client) and not is_generating,
            },
            "composer": {
                "usage": {
                    "ratio": 0,
                    "current_tokens": 0,
                    "max_tokens": 0,
                    "input_limit": 0,
                    "output_reserve": 0,
                    "state": "normal",
                    "message_count": len(messages),
                },
                "compress_button_state": "normal",
                "model_display_name": active.display_name,
                "action_mode": "stop" if is_generating else ("send" if self.llm_client else "unavailable"),
                "action_status": "",
                "clear_draft_nonce": 0,
                "pending_workspace_edit_summary": _json_safe(pending_summary),
            },
            "view_flags": {
                "has_messages": bool(messages),
                "has_runtime_steps": False,
                "has_pending_workspace_edits": bool(pending_summary.get("file_count", 0)),
                "is_busy": is_generating,
                "send_in_progress": is_generating,
                "rollback_in_progress": False,
            },
            "overlays": {},
            "rag": self._conversation_rag_state(),
        }

    @staticmethod
    def _conversation_role(value: Any) -> str:
        return {
            "human": "user",
            "user": "user",
            "ai": "assistant",
            "assistant": "assistant",
            "system": "system",
            "tool": "tool",
        }.get(str(value or "").casefold(), "assistant")

    @staticmethod
    def _conversation_attachment_dto(value: Any) -> Dict[str, Any]:
        attachment = _json_safe(value)
        if not isinstance(attachment, dict):
            attachment = {}
        return {
            "type": str(attachment.get("type", "file") or "file"),
            "path": str(attachment.get("path", "") or ""),
            "name": str(attachment.get("name", "") or ""),
            "mime_type": str(attachment.get("mime_type", "") or ""),
            "size": int(attachment.get("size", 0) or 0),
            "placement": str(attachment.get("placement", "gallery") or "gallery"),
            "reference_id": str(attachment.get("reference_id", "") or ""),
            "inline_marker": str(attachment.get("inline_marker", "") or ""),
        }

    @staticmethod
    def _conversation_agent_step_dto(value: Any) -> Dict[str, Any]:
        step = _json_safe(value)
        if not isinstance(step, dict):
            step = {}
        raw_tool_calls = step.get("tool_calls", [])
        tool_calls: list[Dict[str, Any]] = []
        if isinstance(raw_tool_calls, list):
            for raw_tool_call in raw_tool_calls:
                tool_call = _json_safe(raw_tool_call)
                if not isinstance(tool_call, dict):
                    continue
                tool_calls.append(
                    {
                        "tool_call_id": str(tool_call.get("tool_call_id", "") or ""),
                        "tool_name": str(tool_call.get("tool_name", "") or ""),
                        "arguments": (
                            tool_call.get("arguments", {})
                            if isinstance(tool_call.get("arguments"), dict)
                            else {}
                        ),
                        "result_content": str(tool_call.get("result_content", "") or ""),
                        "status": str(tool_call.get("status", "running") or "running"),
                        "details": (
                            tool_call.get("details", {})
                            if isinstance(tool_call.get("details"), dict)
                            else {}
                        ),
                    }
                )
        web_results = step.get("web_search_results", [])
        return {
            "step_index": int(step.get("step_index", 1) or 1),
            "step_id": str(step.get("step_id", "") or ""),
            "content": str(step.get("content", "") or ""),
            "reasoning_content": str(step.get("reasoning_content", "") or ""),
            "tool_calls": tool_calls,
            "web_search_query": str(step.get("web_search_query", "") or ""),
            "web_search_results": web_results if isinstance(web_results, list) else [],
            "web_search_message": str(step.get("web_search_message", "") or ""),
            "web_search_state": str(step.get("web_search_state", "idle") or "idle"),
            "is_complete": bool(step.get("is_complete", False)),
            "is_partial": bool(step.get("is_partial", False)),
            "stop_reason": str(step.get("stop_reason", "") or ""),
        }

    @staticmethod
    def _conversation_message_dto(
        message: Dict[str, Any],
        rollback_anchors: set[str],
    ) -> Dict[str, Any]:
        from domain.llm.message_helpers import get_serialized_message_id

        kwargs = message.get("additional_kwargs", {})
        if not isinstance(kwargs, dict):
            kwargs = {}
        role = ApplicationRuntime._conversation_role(message.get("type"))
        message_id = get_serialized_message_id(message)
        operations = kwargs.get("operations", [])
        status_summary = " · ".join(str(item) for item in operations) if isinstance(operations, list) else ""
        attachments = kwargs.get("attachments", [])
        agent_steps = kwargs.get("agent_steps", [])
        return {
            "id": message_id,
            "role": role,
            "content": str(message.get("content", "") or ""),
            "reasoning_content": str(kwargs.get("reasoning_content", "") or ""),
            "attachments": [
                ApplicationRuntime._conversation_attachment_dto(item)
                for item in attachments
            ] if isinstance(attachments, list) else [],
            "agent_steps": [
                ApplicationRuntime._conversation_agent_step_dto(item)
                for item in agent_steps
            ] if isinstance(agent_steps, list) else [],
            "status_summary": status_summary,
            "can_rollback": bool(role == "user" and message_id in rollback_anchors),
            "is_partial": bool(kwargs.get("is_partial", False)),
            "stop_reason": str(kwargs.get("stop_reason", "") or ""),
        }

    @staticmethod
    def _conversation_history_message_dto(message: Dict[str, Any]) -> Dict[str, Any]:
        from domain.llm.message_helpers import (
            get_serialized_message_id,
            get_serialized_message_timestamp,
        )

        kwargs = message.get("additional_kwargs", {})
        if not isinstance(kwargs, dict):
            kwargs = {}
        attachments = kwargs.get("attachments", [])
        return {
            "role": ApplicationRuntime._conversation_role(message.get("type")),
            "content": str(message.get("content", "") or ""),
            "reasoning_content": str(kwargs.get("reasoning_content", "") or ""),
            "timestamp": get_serialized_message_timestamp(message),
            "message_id": get_serialized_message_id(message),
            "attachments": [
                ApplicationRuntime._conversation_attachment_dto(item)
                for item in attachments
            ] if isinstance(attachments, list) else [],
            "is_partial": bool(kwargs.get("is_partial", False)),
            "stop_reason": str(kwargs.get("stop_reason", "") or ""),
        }

    def conversation_messages(self, project_id: str, session_id: str) -> list[Dict[str, Any]]:
        project = self.require_project(project_id)
        self._require_session(project, session_id)
        messages = self.session_state_manager.get_session_messages(
            session_id,
            project_root=project.root,
        )
        return [
            self._conversation_history_message_dto(message)
            for message in messages
        ]

    def _conversation_rag_state(self) -> Dict[str, Any]:
        try:
            index_status = self.rag_manager.get_index_status()
            available = bool(index_status.available)
            indexing = bool(index_status.indexing)
            stats = _json_safe(asdict(index_status.stats))
            files = [
                {
                    "relative_path": file.relative_path,
                    "status": file.status,
                    "status_label": file.status.replace("_", " ").title(),
                    "chunks_count": file.chunks_count,
                    "indexed_at": file.indexed_at,
                    "tooltip": file.error or file.exclude_reason or "",
                }
                for file in index_status.files
            ]
        except Exception as exc:
            available = False
            indexing = False
            stats = {}
            files = []
            status_error = str(exc)
        else:
            status_error = str(
                self.rag_manager.index_error
                or self.rag_manager.init_error
                or ""
            )
        phase = "error" if status_error else (
            "indexing" if indexing else ("ready" if available else "unavailable")
        )
        return {
            "status": {
                "phase": phase,
                "label": {
                    "error": "Index unavailable",
                    "indexing": "Indexing",
                    "ready": "Ready",
                    "unavailable": "Unavailable",
                }[phase],
                "tone": "error" if phase == "error" else (
                    "info" if phase == "indexing" else (
                        "success" if phase == "ready" else "neutral"
                    )
                ),
            },
            "progress": {
                "is_visible": indexing,
                "processed": int(stats.get("processed", 0) or 0),
                "total": int(stats.get("total_files", 0) or 0),
                "current_file": "",
            },
            "stats": stats,
            "actions": {
                "can_reindex": available and not indexing,
                "can_clear": available and not indexing,
                "can_search": available and not indexing,
                "is_indexing": indexing,
            },
            "search": {"is_running": False, "result_text": ""},
            "files": files,
            "info": {
                "message": status_error,
                "tone": "error" if status_error else "neutral",
            },
        }

    def _context_for_session(self, session_id: str) -> str:
        expected_prefix = f"{session_id}:"
        if not self._active_context_id or not self._active_context_id.startswith(expected_prefix):
            self._active_context_id = f"{session_id}:{secrets.token_urlsafe(18)}"
        return self._active_context_id

    def require_context(self, project_id: str, context_id: str) -> Dict[str, Any]:
        state = self.conversation_state(project_id)
        if not context_id or not secrets.compare_digest(state["context_id"], context_id):
            raise RuntimeErrorResponse(409, "Stale or foreign context_id")
        return state

    def list_sessions(self, project_id: str) -> Dict[str, Any]:
        project = self.require_project(project_id)
        sessions = self.session_state_manager.get_all_sessions(project.root)
        return {
            "project_id": project_id,
            "current_session_id": self.session_state_manager.get_current_session_id(),
            "items": [_json_safe(asdict(item)) for item in sessions],
        }

    def _require_session(self, project: ProjectIdentity, session_id: str) -> None:
        if not session_id or not any(
            item.session_id == session_id
            for item in self.session_state_manager.get_all_sessions(project.root)
        ):
            raise RuntimeErrorResponse(404, "Conversation was not found")

    def create_session(self, project_id: str) -> Dict[str, Any]:
        project = self.require_project(project_id)
        self._ensure_no_active_conversation()
        session_id = self.session_state_manager.create_session(project.root)
        self._active_context_id = None
        return self.conversation_state(project_id) | {"session_id": session_id}

    def switch_session(self, project_id: str, session_id: str) -> Dict[str, Any]:
        project = self.require_project(project_id)
        self._ensure_no_active_conversation()
        self.session_state_manager.switch_session(project.root, session_id)
        self._active_context_id = None
        return self.conversation_state(project_id)

    def rename_session(self, project_id: str, session_id: str, name: str) -> None:
        project = self.require_project(project_id)
        if not name.strip():
            raise RuntimeErrorResponse(422, "name is required")
        if not self.session_state_manager.rename_session(session_id, name.strip(), project.root):
            raise RuntimeErrorResponse(404, "Session was not found")

    def delete_session(self, project_id: str, session_id: str) -> Dict[str, Any]:
        project = self.require_project(project_id)
        self._ensure_no_active_conversation()
        if not self.session_state_manager.delete_session(project.root, session_id):
            raise RuntimeErrorResponse(404, "Session was not found")
        self._active_context_id = None
        return self.conversation_state(project_id)

    async def send_message(
        self,
        project_id: str,
        context_id: str,
        content: str,
        *,
        current_file: Optional[str] = None,
        attachment_ids: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        project = self.require_project(project_id)
        state = self.conversation_state(project_id)
        if context_id != state["context_id"]:
            raise RuntimeErrorResponse(409, "Stale or foreign context_id")
        if not content.strip():
            raise RuntimeErrorResponse(422, "content is required")
        self._ensure_no_active_conversation()
        if self.llm_client is None:
            raise RuntimeErrorResponse(409, "No configured chat model is available")

        resolved_current_file: Optional[str] = None
        if current_file:
            resolved_current_file = str(
                self.resolve_project_path(project_id, current_file, must_exist=True)
            )
        from domain.llm.message_types import Attachment

        attachments = []
        for reference_id in attachment_ids or []:
            stored = self._attachments.get(reference_id)
            if stored is None:
                raise RuntimeErrorResponse(409, "Stale or foreign attachment reference")
            attachments.append(Attachment.from_dict(stored))
        message_id = secrets.token_hex(16)
        timestamp = _utcnow()
        previous_state = self.context_manager.get_current_state()
        self.context_manager.add_user_message(
            content.strip(),
            attachments=attachments,
            timestamp=timestamp,
            message_id=message_id,
        )
        self.session_state_manager.mark_dirty()
        try:
            await self.conversation_rollback_service.capture_user_turn_checkpoint(
                anchor_message_id=message_id,
                anchor_timestamp=timestamp,
            )
        except Exception:
            self.context_manager.sync_state(previous_state)
            self.session_state_manager.mark_dirty()
            self.session_state_manager.save_current_session(
                project_root=project.root,
                expected_session_id=self.session_state_manager.get_current_session_id(),
            )
            raise
        run_id = f"run_{secrets.token_hex(16)}"
        self._active_run_id = run_id
        self._active_conversation_task = asyncio.create_task(
            self._run_conversation(
                project,
                context_id,
                run_id,
                resolved_current_file,
            ),
            name=f"conversation-{run_id}",
        )
        self.emit(
            "conversation.state",
            {},
            project_id=project_id,
            identity={
                "context_id": context_id,
                "state": self.conversation_state(project_id),
            },
        )
        return {
            "project_id": project_id,
            "context_id": context_id,
            "run_id": run_id,
            "accepted": True,
        }

    async def _run_conversation(
        self,
        project: ProjectIdentity,
        context_id: str,
        run_id: str,
        current_file: Optional[str],
    ) -> None:
        from domain.llm.agent.agent_loop import AgentLoop
        from domain.llm.agent.agent_prompt_builder import build_agent_system_prompt
        from domain.llm.agent.tool_factory import create_default_tools
        from domain.llm.agent.types import ToolContext
        from domain.llm.llm_message_builder import LLMMessageBuilder

        agent_steps: Dict[int, Dict[str, Any]] = {}

        def step_for(payload: Dict[str, Any]) -> Dict[str, Any]:
            try:
                step_index = max(1, int(payload.get("step_index", 1) or 1))
            except (TypeError, ValueError):
                step_index = 1
            return agent_steps.setdefault(
                step_index,
                {
                    "step_index": step_index,
                    "step_id": f"{run_id}:step:{step_index}",
                    "content": "",
                    "reasoning_content": "",
                    "tool_calls": [],
                    "web_search_query": "",
                    "web_search_results": [],
                    "web_search_message": "",
                    "web_search_state": "idle",
                    "is_complete": False,
                    "is_partial": False,
                    "stop_reason": "",
                },
            )

        def persisted_steps(*, partial: bool = False, stop_reason: str = "") -> list[Dict[str, Any]]:
            ordered = [agent_steps[index] for index in sorted(agent_steps)]
            for step in ordered:
                step["is_complete"] = True
            if partial and ordered:
                ordered[-1]["is_partial"] = True
                ordered[-1]["stop_reason"] = stop_reason
            return [self._conversation_agent_step_dto(step) for step in ordered]

        def persist_partial_assistant(stop_reason: str) -> None:
            steps = persisted_steps(partial=True, stop_reason=stop_reason)
            if not steps:
                return
            content = "\n\n".join(
                str(step.get("content", "") or "")
                for step in steps
                if step.get("content")
            )
            reasoning = "\n\n".join(
                str(step.get("reasoning_content", "") or "")
                for step in steps
                if step.get("reasoning_content")
            )
            self.context_manager.add_assistant_message(
                content,
                reasoning_content=reasoning,
                is_partial=True,
                stop_reason=stop_reason,
                agent_steps=steps,
            )
            self.session_state_manager.mark_dirty()
            self.session_state_manager.save_current_session(
                project_root=project.root,
                expected_session_id=self.session_state_manager.get_current_session_id(),
            )

        try:
            registry = create_default_tools()
            tool_context = ToolContext(
                project_root=project.root,
                current_file=current_file,
                rag_query_service=self.rag_manager,
                sim_job_manager=self.simulation_job_manager,
                sim_result_repository=self.simulation_result_repository,
                pending_workspace_edit_service=self.pending_workspace_edit_service,
            )
            active = self.llm_runtime_config_manager.resolve_active_config()
            loop = AgentLoop(
                client=self.llm_client,
                registry=registry,
                context=tool_context,
                model=active.model,
                thinking=active.enable_thinking,
            )
            working_messages = copy.deepcopy(
                self.context_manager.get_working_messages()
            )
            from domain.llm.message_types import Attachment

            for message in working_messages:
                kwargs = getattr(message, "additional_kwargs", None)
                if not isinstance(kwargs, dict):
                    continue
                resolved_attachments: list[Attachment] = []
                for value in kwargs.get("attachments", []):
                    attachment = (
                        value
                        if isinstance(value, Attachment)
                        else Attachment.from_dict(value)
                        if isinstance(value, dict)
                        else None
                    )
                    if attachment is None:
                        continue
                    try:
                        resolved_path = self.resolve_project_path(
                            project.project_id,
                            attachment.path,
                            must_exist=True,
                        )
                    except RuntimeErrorResponse:
                        resolved_path = None
                    resolved_attachments.append(
                        Attachment(
                            type=attachment.type,
                            path=str(resolved_path) if resolved_path is not None else "",
                            name=attachment.name,
                            mime_type=attachment.mime_type,
                            size=attachment.size,
                            placement=attachment.placement,
                            reference_id=attachment.reference_id,
                        )
                    )
                if resolved_attachments:
                    kwargs["attachments"] = resolved_attachments

            messages = LLMMessageBuilder().build_messages(working_messages)
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": build_agent_system_prompt(
                        registry,
                        project.root,
                        current_file,
                    ),
                },
            )

            async def on_event(event_type: str, payload: Dict[str, Any]) -> None:
                if not self._conversation_identity_matches(project, context_id, run_id):
                    return
                wire_payload = dict(payload)
                step = step_for(wire_payload)
                if event_type == "turn_start":
                    for previous_index, previous_step in agent_steps.items():
                        if previous_index < step["step_index"]:
                            previous_step["is_complete"] = True
                elif event_type == "stream_chunk":
                    chunk_type = str(wire_payload.get("chunk_type", "") or "")
                    text = str(wire_payload.get("text", "") or "")
                    if chunk_type == "content":
                        step["content"] += text
                    elif chunk_type == "reasoning":
                        step["reasoning_content"] += text
                elif event_type == "tool_execution_start":
                    step["tool_calls"].append(
                        {
                            "tool_call_id": str(wire_payload.get("tool_call_id", "") or ""),
                            "tool_name": str(wire_payload.get("tool_name", "") or ""),
                            "arguments": (
                                wire_payload.get("arguments", {})
                                if isinstance(wire_payload.get("arguments"), dict)
                                else {}
                            ),
                            "result_content": "",
                            "status": "running",
                            "details": {},
                        }
                    )
                if event_type == "tool_execution_end":
                    wire_payload["status"] = (
                        "failed" if bool(wire_payload.pop("is_error", False)) else "completed"
                    )
                    tool_call_id = str(wire_payload.get("tool_call_id", "") or "")
                    tool_call = next(
                        (
                            item
                            for item in step["tool_calls"]
                            if item.get("tool_call_id") == tool_call_id
                        ),
                        None,
                    )
                    if tool_call is None:
                        tool_call = {
                            "tool_call_id": tool_call_id,
                            "tool_name": str(wire_payload.get("tool_name", "") or ""),
                            "arguments": {},
                        }
                        step["tool_calls"].append(tool_call)
                    tool_call.update(
                        {
                            "result_content": str(wire_payload.get("result_content", "") or ""),
                            "status": wire_payload["status"],
                            "details": (
                                wire_payload.get("details", {})
                                if isinstance(wire_payload.get("details"), dict)
                                else {}
                            ),
                        }
                    )
                self.emit(
                    f"conversation.{event_type}",
                    {
                        "context_id": context_id,
                        "run_id": run_id,
                        **_json_safe(wire_payload),
                    },
                    project_id=project.project_id,
                    identity={"context_id": context_id, "run_id": run_id},
                )

            result = await loop.run(messages, on_event=on_event)
            if result.is_error:
                raise RuntimeError(result.error_message or "Conversation generation failed")
            if not self._conversation_identity_matches(project, context_id, run_id):
                return
            self.context_manager.add_assistant_message(
                result.content,
                reasoning_content=result.reasoning_content,
                usage=result.usage,
                agent_steps=persisted_steps(),
            )
            self.session_state_manager.mark_dirty()
            self.session_state_manager.save_current_session(
                project_root=project.root,
                expected_session_id=self.session_state_manager.get_current_session_id(),
            )
            self.emit(
                "conversation.completed",
                {
                    "context_id": context_id,
                    "run_id": run_id,
                    "content": result.content,
                    "reasoning_content": result.reasoning_content,
                    "usage": _json_safe(result.usage),
                },
                project_id=project.project_id,
                identity={"context_id": context_id, "run_id": run_id},
            )
        except asyncio.CancelledError:
            if self._conversation_identity_matches(project, context_id, run_id):
                persist_partial_assistant("user_requested")
            self.emit(
                "conversation.stopped",
                {"context_id": context_id, "run_id": run_id},
                project_id=project.project_id,
                identity={"context_id": context_id, "run_id": run_id},
            )
            raise
        except Exception as exc:
            if self._conversation_identity_matches(project, context_id, run_id):
                persist_partial_assistant("error")
            self.emit(
                "conversation.failed",
                {"context_id": context_id, "run_id": run_id, "error": str(exc)},
                project_id=project.project_id,
                identity={"context_id": context_id, "run_id": run_id},
            )
        finally:
            if self._active_run_id == run_id:
                self._active_run_id = None
            current = self.project
            if current is not None and current.project_id == project.project_id:
                state = self.conversation_state(project.project_id)
                self.emit(
                    "conversation.state",
                    {},
                    project_id=project.project_id,
                    identity={
                        "context_id": context_id,
                        "run_id": run_id,
                        "state": state,
                    },
                )

    def _conversation_identity_matches(
        self,
        project: ProjectIdentity,
        context_id: str,
        run_id: str,
    ) -> bool:
        current = self.project
        return bool(
            current
            and current.project_id == project.project_id
            and self._active_context_id == context_id
            and self._active_run_id == run_id
        )

    def _ensure_no_active_conversation(self) -> None:
        if self._active_conversation_task is not None and not self._active_conversation_task.done():
            raise RuntimeErrorResponse(409, "A conversation run is already active")

    async def stop_conversation(self, project_id: str, context_id: str, run_id: str) -> None:
        self.require_project(project_id)
        if context_id != self._active_context_id or run_id != self._active_run_id:
            raise RuntimeErrorResponse(409, "Stale or foreign conversation identity")
        task = self._active_conversation_task
        if task is None or task.done():
            raise RuntimeErrorResponse(409, "Conversation run is not active")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    def pending_edits(self, project_id: str) -> Dict[str, Any]:
        self.require_project(project_id)
        return {
            "project_id": project_id,
            "state": _json_safe(self.pending_workspace_edit_service.get_state()),
        }

    def resolve_pending_edits(
        self,
        project_id: str,
        action: str,
    ) -> Dict[str, Any]:
        self.require_project(project_id)
        if action == "accept":
            state = self.pending_workspace_edit_service.accept_all_edits()
        elif action == "reject":
            state = self.pending_workspace_edit_service.reject_all_edits()
        else:
            raise RuntimeErrorResponse(422, "Unknown pending-edit action")
        return {"project_id": project_id, "state": _json_safe(state)}

    def compression_preview(
        self,
        project_id: str,
        context_id: str,
        keep_recent: int,
    ) -> Dict[str, Any]:
        self.require_context(project_id, context_id)
        preview = self.context_compression_service.create_preview(keep_recent=keep_recent)
        return {
            "context_id": context_id,
            "overlay": {
                "is_open": True,
                "is_loading": False,
                "error_message": "",
                "keep_recent": keep_recent,
                "preview": preview,
            },
        }

    async def apply_compression(
        self,
        project_id: str,
        context_id: str,
        keep_recent: int,
    ) -> Dict[str, Any]:
        self.require_context(project_id, context_id)
        result = await self.context_compression_service.apply_manual_compression(
            keep_recent=keep_recent,
            source="desktop_backend",
        )
        if result.get("status") not in {"completed", "skipped"}:
            raise RuntimeErrorResponse(409, str(result.get("error") or "Context compression failed"))
        return {"state": self.conversation_state(project_id)}

    async def rollback_preview(
        self,
        project_id: str,
        context_id: str,
        message_id: str,
    ) -> Dict[str, Any]:
        self.require_context(project_id, context_id)
        preview = await self.conversation_rollback_service.preview_rollback_to_anchor(message_id)
        return {
            "context_id": context_id,
            "overlay": {
                "is_open": True,
                "is_loading": False,
                "error_message": "",
                "target_message_id": message_id,
                "preview": _json_safe(asdict(preview)),
            },
        }

    async def apply_rollback(
        self,
        project_id: str,
        context_id: str,
        operation_token: str,
    ) -> Dict[str, Any]:
        self.require_context(project_id, context_id)
        preview_message_id = ""
        # The signed token is generated from one concrete anchor.  Find the
        # current anchor whose preview reproduces it; no client-supplied path
        # or snapshot id is trusted.
        for message_id in self.conversation_rollback_service.get_available_anchor_ids():
            preview = await self.conversation_rollback_service.preview_rollback_to_anchor(message_id)
            if secrets.compare_digest(preview.operation_token, operation_token):
                preview_message_id = message_id
                break
        if not preview_message_id:
            raise RuntimeErrorResponse(409, "Rollback preview is stale")
        result = await self.conversation_rollback_service.rollback_to_anchor(
            preview_message_id,
            expected_operation_token=operation_token,
        )
        if not result.get("success"):
            raise RuntimeErrorResponse(409, str(result.get("message") or "Rollback failed"))
        self._active_context_id = None
        return {"state": self.conversation_state(project_id)}

    def export_conversation(
        self,
        project_id: str,
        context_id: str,
        session_id: str,
        export_format: str,
        destination: str,
    ) -> None:
        import json

        self.require_project(project_id)
        self.require_context(project_id, context_id)
        if export_format not in {"md", "json", "txt"}:
            raise RuntimeErrorResponse(422, "Unsupported conversation export format")
        target = Path(destination).expanduser()
        if not target.is_absolute():
            raise RuntimeErrorResponse(422, "Export destination must be absolute")
        messages = self.conversation_messages(project_id, session_id)
        if export_format == "json":
            content = json.dumps(messages, ensure_ascii=False, indent=2)
        elif export_format == "md":
            content = "\n\n".join(
                f"## {str(item.get('role', 'message')).title()}\n\n{item.get('content', '')}"
                for item in messages
            )
        else:
            content = "\n\n".join(
                f"{item.get('role', 'message')}: {item.get('content', '')}"
                for item in messages
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def import_attachments(
        self,
        project_id: str,
        context_id: str,
        paths: list[str],
        kind: str,
    ) -> Dict[str, Any]:
        project = self.require_project(project_id)
        self.require_context(project_id, context_id)
        if kind not in {"image", "file"}:
            raise RuntimeErrorResponse(422, "Attachment kind is invalid")
        storage = Path(project.root) / ".circuit_ai" / "attachments"
        storage.mkdir(parents=True, exist_ok=True)
        imported: list[Dict[str, Any]] = []
        for raw_path in paths:
            source = Path(raw_path).expanduser().resolve(strict=True)
            if not source.is_file() or self._is_reparse_point(source):
                raise RuntimeErrorResponse(422, "Attachment source must be a regular file")
            reference_id = secrets.token_urlsafe(18)
            destination = storage / f"{reference_id}-{source.name}"
            shutil.copy2(source, destination)
            relative = destination.relative_to(project.root).as_posix()
            attachment = {
                "type": kind,
                "path": relative,
                "name": source.name,
                "mime_type": mimetypes.guess_type(source.name)[0] or "application/octet-stream",
                "size": destination.stat().st_size,
                "placement": "gallery",
                "reference_id": reference_id,
                "inline_marker": "",
            }
            self._attachments[reference_id] = dict(attachment)
            imported.append(attachment)
        return {"context_id": context_id, "attachments": imported}

    def attachment_preview(
        self,
        project_id: str,
        context_id: str,
        path: str,
    ) -> Dict[str, Any]:
        self.require_context(project_id, context_id)
        image = self.resolve_project_path(project_id, path, must_exist=True)
        if not image.is_file() or _view_kind(image) != "image":
            raise RuntimeErrorResponse(422, "Preview path must identify an image")
        return {
            "context_id": context_id,
            "overlay": {
                "is_open": True,
                "file_name": image.name,
                "source_url": f"/api/v1/projects/{project_id}/assets/{path}",
                "error_message": "",
            },
        }

    # ------------------------------------------------------------------
    # Simulation
    # ------------------------------------------------------------------

    def start_simulation(self, project_id: str, circuit_path: str) -> Dict[str, Any]:
        from domain.simulation.models.simulation_job import JobOrigin

        project = self.require_project(project_id)
        circuit = self.resolve_project_path(project_id, circuit_path, must_exist=True)
        if not circuit.is_file():
            raise RuntimeErrorResponse(422, "circuit_path must identify a file")
        job = self.simulation_job_manager.submit(
            circuit_file=str(circuit),
            origin=JobOrigin.UI_EDITOR,
            project_root=project.root,
            session_id=self.session_state_manager.get_current_session_id(),
        )
        return {"project_id": project_id, "job": self._job_dict(job, project)}

    def simulation_snapshot(self, project_id: str) -> Dict[str, Any]:
        project = self.require_project(project_id)
        jobs = [
            self._job_dict(job, project)
            for job in self.simulation_job_manager.list()
            if os.path.normcase(job.project_root) == os.path.normcase(project.root)
        ]
        results = self._list_results(project)
        return {"project_id": project_id, "jobs": jobs, "results": results}

    def simulation_job(self, project_id: str, job_id: str) -> Dict[str, Any]:
        project = self.require_project(project_id)
        job = self.simulation_job_manager.query(job_id)
        if job is None or os.path.normcase(job.project_root) != os.path.normcase(project.root):
            raise RuntimeErrorResponse(404, "Simulation job was not found")
        return {"project_id": project_id, "job": self._job_dict(job, project)}

    def cancel_simulation(self, project_id: str, job_id: str) -> Dict[str, Any]:
        self.simulation_job(project_id, job_id)
        if not self.simulation_job_manager.request_cancel(job_id):
            raise RuntimeErrorResponse(409, "Simulation job is already terminal")
        return {"project_id": project_id, "job_id": job_id, "cancel_requested": True}

    def _job_dict(self, job: Any, project: ProjectIdentity) -> Dict[str, Any]:
        result_id = self._register_result(job.result_path, job.job_id) if job.result_path else None
        try:
            circuit_file = Path(job.circuit_file).relative_to(project.root).as_posix()
        except ValueError:
            circuit_file = ""
        return {
            "job_id": job.job_id,
            "origin": job.origin.value,
            "status": job.status.value,
            "circuit_file": circuit_file,
            "session_id": job.session_id,
            "version": job.version,
            "submitted_at": job.submitted_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "cancel_requested": job.cancel_requested,
            "result_id": result_id,
            "error_message": job.error_message,
        }

    def _list_results(self, project: ProjectIdentity) -> list[Dict[str, Any]]:
        results: list[Dict[str, Any]] = []
        for group in self.simulation_result_repository.list_by_circuit(project.root, per_circuit_limit=50):
            for summary in group.results:
                result_id = self._register_result(
                    summary.result_path,
                    self._job_for_result(project, summary.result_path),
                )
                results.append(
                    {
                        "result_id": result_id,
                        "job_id": self._result_jobs[result_id],
                        "result_path": summary.result_path,
                        "circuit_file": summary.circuit_file,
                        "analysis_type": summary.analysis_type,
                        "success": summary.success,
                        "timestamp": summary.timestamp,
                    }
                )
        results.sort(key=lambda item: (item["timestamp"], item["result_path"]), reverse=True)
        return results

    def _job_for_result(
        self,
        project: ProjectIdentity,
        result_path: str,
    ) -> Optional[str]:
        for job in self.simulation_job_manager.list():
            if (
                os.path.normcase(job.project_root) == os.path.normcase(project.root)
                and job.result_path == result_path
            ):
                return job.job_id
        return None

    def _register_result(self, result_path: str, job_id: Optional[str]) -> str:
        result_id = f"result_{hashlib.sha256(result_path.encode('utf-8')).hexdigest()[:32]}"
        self._result_paths[result_id] = result_path
        self._result_jobs[result_id] = job_id
        return result_id

    def _result_record(self, project_id: str, result_id: str) -> tuple[ProjectIdentity, str, Any]:
        project = self.require_project(project_id)
        if result_id not in self._result_paths:
            self._list_results(project)
        result_path = self._result_paths.get(result_id)
        if not result_path:
            raise RuntimeErrorResponse(404, "Simulation result was not found")
        loaded = self.simulation_result_repository.load(project.root, result_path)
        if not loaded.success or loaded.data is None:
            raise RuntimeErrorResponse(
                404,
                loaded.error_message or "Simulation result was not found",
            )
        return project, result_path, loaded.data

    def list_simulation_results(self, project_id: str) -> Dict[str, Any]:
        project = self.require_project(project_id)
        return {"project_id": project_id, "results": self._list_results(project)}

    def get_simulation_result(self, project_id: str, result_id: str) -> Dict[str, Any]:
        _project, result_path, result = self._result_record(project_id, result_id)
        return {
            "project_id": project_id,
            "job_id": self._result_jobs.get(result_id),
            "result_id": result_id,
            "result_path": result_path,
            "result": _json_safe(result.to_dict()),
        }

    def get_simulation_surface(self, project_id: str, result_id: str) -> Dict[str, Any]:
        project, _result_path, result = self._result_record(project_id, result_id)
        payload = result.to_dict()
        schematic = None
        circuit = self.simulation_result_repository.resolve_circuit_path(
            project.root,
            result.file_path,
        )
        if circuit is not None and result.source_digest:
            try:
                from domain.simulation.spice.parser import SpiceParser
                from domain.simulation.spice.schematic_builder import (
                    SpiceSchematicBuilder,
                )
                from domain.simulation.spice.source_closure import (
                    collect_spice_source_closure,
                )

                graph = collect_spice_source_closure(circuit)
                if secrets.compare_digest(graph.digest, result.source_digest):
                    document = SpiceParser().parse_source_graph(graph)
                    dependency_snapshots = {
                        blob.source_id: blob.source_text
                        for blob in graph.blobs
                        if blob.key != graph.main_key
                    }
                    schematic = SpiceSchematicBuilder().build_document(
                        document,
                        source_text=graph.main_blob.source_text,
                        dependency_snapshots=dependency_snapshots,
                    )
            except Exception:
                # A historical result remains browsable when its source graph
                # moved, changed, or no longer parses.  Never substitute the
                # current editor document for the verified historical input.
                schematic = None
        return {
            "project_id": project_id,
            "job_id": self._result_jobs.get(result_id),
            "result_id": result_id,
            "data": _json_safe(payload.get("data")),
            "metrics": _json_safe(payload.get("measurements") or []),
            "output_log": str(payload.get("raw_output", "") or ""),
            "schematic": _json_safe(schematic),
        }

    def delete_simulation_result(self, project_id: str, result_id: str) -> Dict[str, Any]:
        project, result_path, _result = self._result_record(project_id, result_id)
        if not self.simulation_result_repository.delete(project.root, result_path):
            raise RuntimeErrorResponse(500, "Simulation result could not be deleted")
        self._result_paths.pop(result_id, None)
        self._result_jobs.pop(result_id, None)
        return {"project_id": project_id, "result_id": result_id, "deleted": True}

    def export_simulation_result(
        self,
        project_id: str,
        result_id: str,
        export_format: str,
        surface: str,
    ) -> Dict[str, Any]:
        import csv
        import io
        import json

        project, _result_path, result = self._result_record(project_id, result_id)
        if export_format not in {"json", "csv"}:
            raise RuntimeErrorResponse(422, "Only json and csv data exports are supported")
        if surface != "data":
            raise RuntimeErrorResponse(422, "Only the authoritative data surface can be exported")
        result_payload = _json_safe(result.to_dict())
        export_dir = Path(project.root) / ".circuit_ai" / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"{result_id}.{export_format}"
        output_path = export_dir / file_name
        if export_format == "json":
            content = json.dumps(result_payload.get("data"), ensure_ascii=False, indent=2)
            mime_type = "application/json"
        else:
            buffer = io.StringIO(newline="")
            writer = csv.writer(buffer)
            data = result_payload.get("data") or {}
            axes = [(key, value) for key, value in data.items() if key in {"time", "frequency", "sweep"} and isinstance(value, list)]
            signals = data.get("signals") if isinstance(data, dict) else {}
            if not isinstance(signals, dict):
                signals = {}
            axis_name, axis_values = axes[0] if axes else ("index", [])
            length = max([len(axis_values), *(len(value) for value in signals.values() if isinstance(value, list))], default=0)
            writer.writerow([axis_name, *signals.keys()])
            for index in range(length):
                row = [axis_values[index] if index < len(axis_values) else index]
                for values in signals.values():
                    row.append(values[index] if isinstance(values, list) and index < len(values) else "")
                writer.writerow(row)
            content = buffer.getvalue()
            mime_type = "text/csv"
        output_path.write_text(content, encoding="utf-8", newline="")
        return {
            "project_id": project_id,
            "job_id": self._result_jobs.get(result_id),
            "result_id": result_id,
            "download_url": f"/api/v1/projects/{project_id}/assets/.circuit_ai/exports/{file_name}",
            "file_name": file_name,
            "mime_type": mime_type,
        }

    # ------------------------------------------------------------------
    # RAG and model configuration
    # ------------------------------------------------------------------

    def rag_status(self, project_id: str) -> Dict[str, Any]:
        self.require_project(project_id)
        state = self._conversation_rag_state()
        return {
            "project_id": project_id,
            **state,
        }

    async def rag_action(self, project_id: str, action: str, query: str = "", mode: str = "hybrid") -> Dict[str, Any]:
        self.require_project(project_id)
        if action == "index":
            if not self.rag_manager.is_available:
                raise RuntimeErrorResponse(409, "RAG index library is unavailable")
            self.rag_manager.trigger_index()
            return self.rag_status(project_id)
        if action == "query":
            if not query.strip():
                raise RuntimeErrorResponse(422, "query is required")
            del mode
            try:
                result = await self.rag_manager.query_async(query.strip())
            except Exception as exc:
                raise RuntimeErrorResponse(409, str(exc)) from exc
            return {
                "project_id": project_id,
                "query": query.strip(),
                "result_text": result.format_as_context(),
                "hits": [_json_safe(asdict(hit)) for hit in result.chunks],
            }
        raise RuntimeErrorResponse(422, "action must be 'index' or 'query'")

    async def clear_rag_index(self, project_id: str, context_id: str) -> None:
        project = self.require_project(project_id)
        self.require_context(project_id, context_id)
        if not self.rag_manager.is_available:
            raise RuntimeErrorResponse(409, "RAG index library is unavailable")
        generation = self.rag_manager.generation
        try:
            await self.rag_manager.clear_index_async(
                expected_generation=generation,
                expected_project_root=project.root,
            )
        except Exception as exc:
            raise RuntimeErrorResponse(409, str(exc)) from exc

    def model_config(self) -> Dict[str, Any]:
        from infrastructure.config.settings import (
            CONFIG_EMBEDDING_BASE_URL,
            CONFIG_EMBEDDING_BATCH_SIZE,
            CONFIG_EMBEDDING_MODEL,
            CONFIG_EMBEDDING_PROVIDER,
            CONFIG_EMBEDDING_TIMEOUT,
            CREDENTIAL_TYPE_EMBEDDING,
        )
        from shared.embedding_model_registry import EmbeddingModelRegistry
        from shared.model_registry import ModelRegistry

        ModelRegistry.initialize()
        EmbeddingModelRegistry.initialize()
        active = self.llm_runtime_config_manager.resolve_active_config()

        def provider_dict(provider: Any, models: Iterable[Any]) -> Dict[str, Any]:
            return {
                "id": provider.id,
                "label": provider.display_name,
                "default_base_url": provider.base_url,
                "default_model": provider.default_model,
                "requires_api_key": getattr(provider, "requires_api_key", True),
                "models": [
                    {
                        "id": model.name,
                        "label": model.display_name,
                        "supports_thinking": getattr(model, "supports_thinking", False),
                    }
                    for model in models
                ],
            }

        chat_providers = [
            provider_dict(provider, ModelRegistry.list_models(provider.id))
            for provider in ModelRegistry.list_implemented_providers()
        ]
        embedding_providers = [
            provider_dict(provider, EmbeddingModelRegistry.list_models(provider.id))
            for provider in EmbeddingModelRegistry.list_implemented_providers()
        ]
        embedding_provider = str(self.config_manager.get(CONFIG_EMBEDDING_PROVIDER, "") or "")
        embedding_provider_config = EmbeddingModelRegistry.get_provider(
            embedding_provider
        )
        if embedding_provider_config is None:
            embedding_provider_config = EmbeddingModelRegistry.get_default_provider()
            embedding_provider = (
                embedding_provider_config.id if embedding_provider_config else ""
            )
        embedding_model = str(self.config_manager.get(CONFIG_EMBEDDING_MODEL, "") or "")
        if (
            not embedding_model
            or EmbeddingModelRegistry.get_model_by_name(
                embedding_provider,
                embedding_model,
            ) is None
        ):
            embedding_model = (
                embedding_provider_config.default_model
                if embedding_provider_config
                else ""
            )
        configured_embedding_base_url = str(
            self.config_manager.get(CONFIG_EMBEDDING_BASE_URL, "") or ""
        )
        embedding_credential = self.credential_manager.get_credential(
            CREDENTIAL_TYPE_EMBEDDING,
            embedding_provider,
        ) or {}
        return {
            "providers": {"chat": chat_providers, "embedding": embedding_providers},
            "chat": {
                "provider": active.provider,
                "model": active.model,
                "base_url": active.base_url,
                "timeout": active.timeout,
                "streaming": active.streaming,
                "enable_thinking": active.enable_thinking,
                "thinking_timeout": active.thinking_timeout,
                "has_api_key": active.has_api_key,
            },
            "embedding": {
                "provider": embedding_provider,
                "model": embedding_model,
                "base_url": (
                    configured_embedding_base_url
                    or (
                        embedding_provider_config.base_url
                        if embedding_provider_config
                        else ""
                    )
                ),
                "timeout": int(self.config_manager.get(CONFIG_EMBEDDING_TIMEOUT, 60)),
                "batch_size": int(self.config_manager.get(CONFIG_EMBEDDING_BATCH_SIZE, 16)),
                "has_api_key": bool(embedding_credential.get("api_key")),
            },
        }

    async def save_model_config(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from infrastructure.config.settings import (
            CONFIG_EMBEDDING_BASE_URL,
            CONFIG_EMBEDDING_BATCH_SIZE,
            CONFIG_EMBEDDING_MODEL,
            CONFIG_EMBEDDING_PROVIDER,
            CONFIG_EMBEDDING_TIMEOUT,
            CREDENTIAL_TYPE_EMBEDDING,
        )

        chat = payload.get("chat") or {}
        provider_id = str(chat.get("provider", ""))
        from infrastructure.config.settings import CREDENTIAL_TYPE_LLM

        provider_credential = self.credential_manager.get_credential(
            CREDENTIAL_TYPE_LLM,
            provider_id,
        ) or {}
        api_key = chat.get("api_key", provider_credential.get("api_key", ""))
        if api_key is None:
            api_key = ""
        self.llm_runtime_config_manager.save_active_chat_config(
            provider_id=provider_id,
            model_name=str(chat.get("model", "")),
            base_url=str(chat.get("base_url", "")),
            timeout=int(chat.get("timeout", 60)),
            streaming=bool(chat.get("streaming", True)),
            enable_thinking=bool(chat.get("enable_thinking", False)),
            thinking_timeout=int(chat.get("thinking_timeout", 120)),
            api_key=str(api_key),
        )
        embedding = payload.get("embedding") or {}
        if embedding:
            provider = str(embedding.get("provider", ""))
            self.config_manager.set(CONFIG_EMBEDDING_PROVIDER, provider, save=False)
            self.config_manager.set(CONFIG_EMBEDDING_MODEL, str(embedding.get("model", "")), save=False)
            self.config_manager.set(CONFIG_EMBEDDING_BASE_URL, str(embedding.get("base_url", "")), save=False)
            self.config_manager.set(CONFIG_EMBEDDING_TIMEOUT, int(embedding.get("timeout", 60)), save=False)
            self.config_manager.set(CONFIG_EMBEDDING_BATCH_SIZE, int(embedding.get("batch_size", 16)), save=False)
            embedding_key = embedding.get("api_key", ...)
            if embedding_key is not ...:
                if embedding_key is None:
                    self.credential_manager.delete_credential(CREDENTIAL_TYPE_EMBEDDING, provider)
                else:
                    self.credential_manager.set_credential(
                        CREDENTIAL_TYPE_EMBEDDING,
                        provider,
                        {"api_key": str(embedding_key), "updated_at": _utcnow()},
                    )
            self.config_manager.save_config()
        await self.refresh_llm()
        if self.event_bus is not None:
            from shared.event_types import EVENT_LLM_CONFIG_CHANGED

            self.event_bus.publish(EVENT_LLM_CONFIG_CHANGED, {"source": "desktop_backend"})
        return self.model_config()

    async def test_model_config(
        self,
        section: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Make one real, minimal provider request without saving the draft."""
        verified_at = _utcnow()
        provider = str(config.get("provider", "") or "").strip()
        model = str(config.get("model", "") or "").strip()
        api_key_value = config.get("api_key", ...)
        credential_type = "llm" if section == "chat" else "embedding"
        if api_key_value is ...:
            credential = self.credential_manager.get_credential(
                credential_type,
                provider,
            ) or {}
            api_key = str(credential.get("api_key", "") or "").strip()
        elif api_key_value is None:
            api_key = ""
        else:
            api_key = str(api_key_value).strip()
        if not provider or not model or not api_key:
            raise RuntimeErrorResponse(422, "Provider, model, and API key are required")

        try:
            if section == "chat":
                from infrastructure.llm_adapters import LLMClientFactory

                client = LLMClientFactory.create_client(
                    provider_id=provider,
                    api_key=api_key,
                    base_url=str(config.get("base_url", "") or "") or None,
                    model=model,
                    timeout=int(config.get("timeout", 60)),
                )
                try:
                    response = await asyncio.to_thread(
                        client.chat,
                        messages=[{"role": "user", "content": "Reply with OK."}],
                        model=model,
                        streaming=False,
                        tools=None,
                        thinking=False,
                    )
                    if not str(getattr(response, "content", "") or "").strip():
                        raise RuntimeError("Provider returned an empty response")
                finally:
                    close = getattr(client, "close", None)
                    if close is not None:
                        closed = close()
                        if inspect.isawaitable(closed):
                            await closed
            elif section == "embedding":
                if provider != "zhipu":
                    raise RuntimeError("Only Zhipu embedding is implemented")
                import httpx

                base_url = str(config.get("base_url", "") or "").strip()
                if not base_url:
                    from shared.embedding_model_registry import EmbeddingModelRegistry

                    provider_info = EmbeddingModelRegistry.get_provider(provider)
                    base_url = provider_info.base_url if provider_info else ""
                async with httpx.AsyncClient(timeout=int(config.get("timeout", 30))) as client:
                    response = await client.post(
                        base_url,
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={"input": ["connection test"], "model": model},
                    )
                    response.raise_for_status()
                    payload = response.json()
                    vectors = payload.get("data", []) if isinstance(payload, dict) else []
                    if not vectors or not vectors[0].get("embedding"):
                        raise RuntimeError("Provider returned no embedding vector")
            else:
                raise RuntimeErrorResponse(422, "Unknown model-config section")
        except RuntimeErrorResponse:
            raise
        except Exception as exc:
            return {
                "section": section,
                "status": "failed",
                "message": str(exc),
                "verified_at": None,
            }
        return {
            "section": section,
            "status": "verified",
            "message": "Connection verified",
            "verified_at": verified_at,
        }

    # ------------------------------------------------------------------
    # Event projection
    # ------------------------------------------------------------------

    def emit(
        self,
        event_type: str,
        payload: Dict[str, Any],
        *,
        project_id: Optional[str] = None,
        identity: Optional[Dict[str, Any]] = None,
    ) -> None:
        emitter = self._emit_event
        if emitter is None:
            return
        project = self.project
        resolved_project_id = project_id or (project.project_id if project else "")
        emitter(event_type, resolved_project_id, _json_safe(payload), identity or {})

    def _subscribe_domain_events(self) -> None:
        from shared.event_types import (
            EVENT_FILE_CHANGED,
            EVENT_RAG_INDEX_COMPLETE,
            EVENT_RAG_INDEX_ERROR,
            EVENT_RAG_INDEX_PROGRESS,
            EVENT_RAG_INDEX_STARTED,
            EVENT_SIM_COMPLETE,
            EVENT_SIM_ERROR,
            EVENT_SIM_STARTED,
        )

        event_types = (
            EVENT_FILE_CHANGED,
            EVENT_SIM_STARTED,
            EVENT_SIM_COMPLETE,
            EVENT_SIM_ERROR,
            EVENT_RAG_INDEX_STARTED,
            EVENT_RAG_INDEX_PROGRESS,
            EVENT_RAG_INDEX_COMPLETE,
            EVENT_RAG_INDEX_ERROR,
        )
        for event_type in event_types:
            def handler(
                envelope: Dict[str, Any],
                subscribed_event_type: str = event_type,
            ) -> None:
                self._on_domain_event(subscribed_event_type, envelope)

            self.event_bus.subscribe(event_type, handler)
            self._bus_subscriptions.append((event_type, handler))

    def _on_domain_event(self, event_type: str, envelope: Dict[str, Any]) -> None:
        from shared.event_types import EVENT_FILE_CHANGED

        if event_type == EVENT_FILE_CHANGED:
            self._on_file_change_event(envelope)
            return

        payload = envelope.get("data", {}) if isinstance(envelope, dict) else {}
        if not isinstance(payload, dict):
            return
        project = self.project
        if project is None:
            return
        if event_type.startswith("sim_"):
            if os.path.normcase(str(payload.get("project_root", ""))) != os.path.normcase(project.root):
                return
            job_id = str(payload.get("job_id", "") or "")
            if not job_id:
                return
            result_path = str(payload.get("result_path", "") or "")
            result_id = self._register_result(result_path, job_id) if result_path else None
            mapped = {
                "sim_started": "simulation.started",
                "sim_complete": "simulation.completed",
                "sim_error": "simulation.cancelled" if payload.get("cancelled") else "simulation.failed",
            }[event_type]
            wire_payload = {
                key: _json_safe(value)
                for key, value in payload.items()
                if key not in {"project_root", "export_root"}
            }
            wire_payload["result_id"] = result_id
            self.emit(
                mapped,
                wire_payload,
                project_id=project.project_id,
                identity={"job_id": job_id, "result_id": result_id},
            )
            return
        self.emit(event_type, payload, project_id=project.project_id)

    def _on_file_change_event(self, envelope: Dict[str, Any]) -> None:
        """Project one canonical on-disk change into the renderer contract."""
        from shared.file_change import extract_file_change

        change = extract_file_change(envelope)
        project = self.project
        if change is None or project is None:
            return
        if (
            os.path.normcase(os.path.abspath(change.project_root))
            != os.path.normcase(os.path.abspath(project.root))
            or change.generation != project.generation
            or change.generation != int(self.file_manager.project_generation)
        ):
            return

        root = Path(project.root).resolve()

        def relative_path(raw_path: str) -> Optional[str]:
            try:
                relative = Path(raw_path).resolve().relative_to(root)
            except (OSError, ValueError):
                return None
            value = relative.as_posix()
            return value if value and value != "." else None

        source_path = relative_path(change.path)
        if source_path is None:
            return

        if change.operation == "move":
            destination_path = relative_path(change.dest_path)
            if destination_path is None:
                return
            self._rewrite_document_paths(source_path, destination_path)
            self.emit(
                "workspace.entry_moved",
                {
                    "source_path": source_path,
                    "destination_path": destination_path,
                    "is_directory": change.is_directory,
                },
                project_id=project.project_id,
            )
            return

        if change.operation == "delete":
            self._remove_document_paths(source_path)

        mapped_type = {
            "create": "workspace.entry_created",
            "update": "workspace.entry_updated",
            "delete": "workspace.entry_deleted",
        }.get(change.operation)
        if mapped_type is None:
            return
        self.emit(
            mapped_type,
            {"path": source_path, "is_directory": change.is_directory},
            project_id=project.project_id,
        )

    def _rewrite_document_paths(self, source_path: str, destination_path: str) -> None:
        moved = {
            path: identity
            for path, identity in tuple(self._documents.items())
            if path == source_path or path.startswith(f"{source_path}/")
        }
        for old_path, identity in moved.items():
            self._documents.pop(old_path, None)
            suffix = old_path[len(source_path):]
            new_path = f"{destination_path}{suffix}"
            identity.path = new_path
            self._documents[new_path] = identity

    def _remove_document_paths(self, path: str) -> None:
        removed = {
            candidate: identity
            for candidate, identity in tuple(self._documents.items())
            if candidate == path or candidate.startswith(f"{path}/")
        }
        for candidate, identity in removed.items():
            self._documents.pop(candidate, None)
            self._documents_by_id.pop(identity.document_id, None)


__all__ = ["ApplicationRuntime", "ProjectIdentity", "RuntimeErrorResponse"]
