"""FastAPI adapter for the headless application runtime."""

from __future__ import annotations

import asyncio
import os
import platform
import secrets
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Any, AsyncIterator, Dict, Literal, Optional
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from application.runtime import ApplicationRuntime, RuntimeErrorResponse


API_VERSION = "v1"
APP_VERSION = "0.1.0"
_LOOPBACK_RENDERER_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_renderer_origin(origin: str) -> str:
    """Return the one browser origin allowed to call this sidecar."""

    if origin == "null":
        # Chromium serializes the origin of a packaged file:// renderer as null.
        return origin
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Renderer origin is invalid") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in _LOOPBACK_RENDERER_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or port is None
    ):
        raise ValueError("Renderer origin must be null or a loopback HTTP origin with a port")
    return origin


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectOpenRequest(StrictModel):
    path: str


class ProjectCloseRequest(StrictModel):
    project_id: str


class DocumentSaveRequest(StrictModel):
    document_id: str
    base_revision: int = Field(ge=1)
    content: str


class EntryCreateRequest(StrictModel):
    parent_path: str = ""
    name: str
    kind: Literal["file", "directory"]


class EntryMoveRequest(StrictModel):
    source_path: str
    destination_path: str


class ConversationRunRequest(StrictModel):
    context_id: str
    text: str
    attachment_ids: list[str] = Field(default_factory=list)
    client_request_id: str


class ContextRequest(StrictModel):
    context_id: str


class ConversationRenameRequest(ContextRequest):
    name: str


class PendingEditActionRequest(StrictModel):
    pass


class RagSearchRequest(ContextRequest):
    query: str


class CompressionRequest(ContextRequest):
    keep_recent: int = Field(ge=2, le=20)


class RollbackPreviewRequest(ContextRequest):
    message_id: str


class RollbackRequest(ContextRequest):
    operation_token: str


class ConversationExportRequest(ContextRequest):
    format: Literal["md", "json", "txt"]
    path: str


class AttachmentImportRequest(ContextRequest):
    paths: list[str]
    kind: Literal["image", "file"]


class AttachmentPreviewRequest(ContextRequest):
    path: str


class SimulationStartRequest(StrictModel):
    circuit_path: str


class ExportRequest(StrictModel):
    format: Literal["csv", "json"]
    surface: Literal["data"]


class PreferencesRequest(StrictModel):
    language: Literal["en_US", "zh_CN"]
    theme: Literal["system", "light", "dark"]


class ModelConfigRequest(StrictModel):
    chat: Dict[str, Any]
    embedding: Dict[str, Any]


class ModelTestRequest(StrictModel):
    section: Literal["chat", "embedding"]
    config: Dict[str, Any]


class EventHub:
    """Thread-safe fan-out into the Uvicorn event loop."""

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._subscribers: set[asyncio.Queue[Dict[str, Any]]] = set()
        self._sequence = 0
        self._lock = threading.Lock()

    def attach(self) -> None:
        self._loop = asyncio.get_running_loop()

    def publish(self, event_type: str, project_id: str, payload: Dict[str, Any], identity: Dict[str, Any]) -> None:
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
        envelope: Dict[str, Any] = {
            "type": event_type,
            "sequence": sequence,
            "occurred_at": _utcnow(),
            "project_id": project_id,
            "payload": payload,
        }
        envelope.update(identity)
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._broadcast, envelope)

    def _broadcast(self, envelope: Dict[str, Any]) -> None:
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(envelope)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[Dict[str, Any]]]:
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)


def create_app(
    token: str,
    renderer_origin: str,
    *,
    runtime: Optional[ApplicationRuntime] = None,
) -> FastAPI:
    if not isinstance(token, str) or not token:
        raise ValueError("A non-empty sidecar token is required")
    allowed_renderer_origin = _validate_renderer_origin(renderer_origin)

    hub = EventHub()
    app_runtime = runtime or ApplicationRuntime(emit_event=hub.publish)
    if runtime is not None:
        app_runtime._emit_event = hub.publish  # type: ignore[attr-defined]

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        hub.attach()
        await app_runtime.start()
        try:
            yield
        finally:
            await app_runtime.stop()

    app = FastAPI(
        title="Circuit Design AI Desktop Backend",
        version=APP_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[allowed_renderer_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
        max_age=600,
    )
    app.state.runtime = app_runtime
    app.state.event_hub = hub

    async def require_token(authorization: Annotated[Optional[str], Header()] = None) -> None:
        scheme, separator, credential = (authorization or "").partition(" ")
        if not (
            separator
            and scheme.casefold() == "bearer"
            and credential
            and secrets.compare_digest(credential, token)
        ):
            raise HTTPException(status_code=401, detail="Invalid bearer token")

    protected = [Depends(require_token)]

    @app.exception_handler(RuntimeErrorResponse)
    async def runtime_error_handler(_request, exc: RuntimeErrorResponse) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {"status": "ok", "api_version": API_VERSION, "pid": os.getpid()}

    @app.get("/api/v1/app/state", dependencies=protected)
    async def app_state() -> Dict[str, Any]:
        project = app_runtime.project
        return {"api_version": API_VERSION, "project": project.to_dict() if project else None, "ready": True}

    @app.websocket("/api/v1/events")
    async def events(websocket: WebSocket, token_query: Annotated[Optional[str], Query(alias="token")] = None) -> None:
        if not token_query or not secrets.compare_digest(token_query, token):
            await websocket.close(code=4401, reason="Invalid token")
            return
        await websocket.accept()
        await websocket.send_json({"type": "hello", "api_version": API_VERSION, "connection_id": secrets.token_urlsafe(18)})
        try:
            async with hub.subscribe() as queue:
                while True:
                    await websocket.send_json(await queue.get())
        except WebSocketDisconnect:
            return

    # Project and workspace
    @app.get("/api/v1/project", dependencies=protected)
    async def current_project() -> Dict[str, Any]:
        project = app_runtime.project
        return {"project": project.to_dict() if project else None}

    @app.post("/api/v1/project/open", dependencies=protected)
    async def open_project(request: ProjectOpenRequest) -> Dict[str, Any]:
        return {"project": app_runtime.open_project(request.path).to_dict()}

    @app.post("/api/v1/project/close", status_code=204, dependencies=protected)
    async def close_project(request: ProjectCloseRequest) -> Response:
        app_runtime.close_project(request.project_id)
        return Response(status_code=204)

    @app.get("/api/v1/project/recent", dependencies=protected)
    async def recent_projects() -> Dict[str, Any]:
        return {"projects": app_runtime.project_service.get_recent_projects()}

    @app.get("/api/v1/projects/{project_id}/workspace/tree", dependencies=protected)
    async def workspace_tree(project_id: str, path: str = "", depth: int = 1) -> Dict[str, Any]:
        return app_runtime.workspace_tree(project_id, path, depth)

    @app.post("/api/v1/projects/{project_id}/workspace/entries", status_code=204, dependencies=protected)
    async def create_entry(project_id: str, request: EntryCreateRequest) -> Response:
        app_runtime.create_entry(project_id, request.parent_path, request.name, request.kind)
        return Response(status_code=204)

    @app.post("/api/v1/projects/{project_id}/workspace/moves", status_code=204, dependencies=protected)
    async def move_entry(project_id: str, request: EntryMoveRequest) -> Response:
        app_runtime.move_entry(project_id, request.source_path, request.destination_path)
        return Response(status_code=204)

    @app.delete("/api/v1/projects/{project_id}/workspace/entries/{path:path}", status_code=204, dependencies=protected)
    async def delete_entry(project_id: str, path: str) -> Response:
        app_runtime.delete_entry(project_id, path)
        return Response(status_code=204)

    @app.get("/api/v1/projects/{project_id}/files/{path:path}", dependencies=protected)
    async def read_file(project_id: str, path: str) -> Dict[str, Any]:
        return app_runtime.read_document(project_id, path)

    @app.put("/api/v1/projects/{project_id}/files/{path:path}", dependencies=protected)
    async def write_file(project_id: str, path: str, request: DocumentSaveRequest) -> Dict[str, Any]:
        return app_runtime.write_document(project_id, path, request.document_id, request.base_revision, request.content)

    @app.get("/api/v1/projects/{project_id}/assets/{path:path}", dependencies=protected)
    async def read_asset(project_id: str, path: str) -> FileResponse:
        asset = app_runtime.resolve_project_path(project_id, path, must_exist=True)
        if not asset.is_file():
            raise RuntimeErrorResponse(422, "Asset path must identify a file")
        return FileResponse(asset)

    # Conversation resources.  Session ids identify collection items;
    # context/run ids reject stale renderer actions.
    @app.get("/api/v1/projects/{project_id}/conversations", dependencies=protected)
    async def conversations(project_id: str) -> Dict[str, Any]:
        collection = app_runtime.list_sessions(project_id)
        return {"active": app_runtime.conversation_state(project_id), "items": collection["items"]}

    @app.post("/api/v1/projects/{project_id}/conversations", dependencies=protected)
    async def create_conversation(project_id: str, request: ContextRequest) -> Dict[str, Any]:
        current = app_runtime.conversation_state(project_id)
        if request.context_id != current["context_id"]:
            raise RuntimeErrorResponse(409, "Stale or foreign context_id")
        return {"state": app_runtime.create_session(project_id)}

    @app.get("/api/v1/projects/{project_id}/conversations/{session_id}", dependencies=protected)
    async def conversation_item(project_id: str, session_id: str) -> Dict[str, Any]:
        return {
            "project_id": project_id,
            "session_id": session_id,
            "messages": app_runtime.conversation_messages(project_id, session_id),
        }

    @app.put("/api/v1/projects/{project_id}/conversations/{session_id}", dependencies=protected)
    async def rename_conversation(project_id: str, session_id: str, request: ConversationRenameRequest) -> Dict[str, Any]:
        current = app_runtime.conversation_state(project_id)
        if request.context_id != current["context_id"]:
            raise RuntimeErrorResponse(409, "Stale or foreign context_id")
        app_runtime.rename_session(project_id, session_id, request.name)
        return {"state": app_runtime.conversation_state(project_id)}

    @app.delete("/api/v1/projects/{project_id}/conversations/{session_id}", dependencies=protected)
    async def delete_conversation(project_id: str, session_id: str, request: ContextRequest) -> Dict[str, Any]:
        current = app_runtime.conversation_state(project_id)
        if request.context_id != current["context_id"]:
            raise RuntimeErrorResponse(409, "Stale or foreign context_id")
        return {"state": app_runtime.delete_session(project_id, session_id)}

    @app.post("/api/v1/projects/{project_id}/conversations/{session_id}/activate", dependencies=protected)
    async def activate_conversation(project_id: str, session_id: str, request: ContextRequest) -> Dict[str, Any]:
        current = app_runtime.conversation_state(project_id)
        if request.context_id != current["context_id"]:
            raise RuntimeErrorResponse(409, "Stale or foreign context_id")
        return {"state": app_runtime.switch_session(project_id, session_id)}

    @app.post("/api/v1/projects/{project_id}/conversations/{session_id}/runs", status_code=202, dependencies=protected)
    async def start_conversation_run(project_id: str, session_id: str, request: ConversationRunRequest) -> Dict[str, Any]:
        current = app_runtime.conversation_state(project_id)
        if current["session"]["id"] != session_id:
            raise RuntimeErrorResponse(409, "Stale or foreign session_id")
        return await app_runtime.send_message(
            project_id,
            request.context_id,
            request.text,
            attachment_ids=request.attachment_ids,
        )

    @app.post("/api/v1/projects/{project_id}/conversations/{session_id}/runs/{run_id}/cancel", status_code=204, dependencies=protected)
    async def cancel_conversation_run(project_id: str, session_id: str, run_id: str, request: ContextRequest) -> Response:
        current = app_runtime.conversation_state(project_id)
        if current["session"]["id"] != session_id:
            raise RuntimeErrorResponse(409, "Stale or foreign session_id")
        await app_runtime.stop_conversation(project_id, request.context_id, run_id)
        return Response(status_code=204)

    @app.post("/api/v1/projects/{project_id}/conversations/{session_id}/compression-preview", dependencies=protected)
    async def compression_preview(project_id: str, session_id: str, request: CompressionRequest) -> Dict[str, Any]:
        current = app_runtime.require_context(project_id, request.context_id)
        if current["session"]["id"] != session_id:
            raise RuntimeErrorResponse(409, "Stale or foreign session_id")
        return app_runtime.compression_preview(project_id, request.context_id, request.keep_recent)

    @app.post("/api/v1/projects/{project_id}/conversations/{session_id}/compressions", status_code=204, dependencies=protected)
    async def apply_compression(project_id: str, session_id: str, request: CompressionRequest) -> Response:
        current = app_runtime.require_context(project_id, request.context_id)
        if current["session"]["id"] != session_id:
            raise RuntimeErrorResponse(409, "Stale or foreign session_id")
        await app_runtime.apply_compression(project_id, request.context_id, request.keep_recent)
        return Response(status_code=204)

    @app.post("/api/v1/projects/{project_id}/conversations/{session_id}/rollback-preview", dependencies=protected)
    async def rollback_preview(project_id: str, session_id: str, request: RollbackPreviewRequest) -> Dict[str, Any]:
        current = app_runtime.require_context(project_id, request.context_id)
        if current["session"]["id"] != session_id:
            raise RuntimeErrorResponse(409, "Stale or foreign session_id")
        return await app_runtime.rollback_preview(project_id, request.context_id, request.message_id)

    @app.post("/api/v1/projects/{project_id}/conversations/{session_id}/rollbacks", dependencies=protected)
    async def apply_rollback(project_id: str, session_id: str, request: RollbackRequest) -> Dict[str, Any]:
        current = app_runtime.require_context(project_id, request.context_id)
        if current["session"]["id"] != session_id:
            raise RuntimeErrorResponse(409, "Stale or foreign session_id")
        return await app_runtime.apply_rollback(project_id, request.context_id, request.operation_token)

    @app.post("/api/v1/projects/{project_id}/conversations/{session_id}/exports", status_code=204, dependencies=protected)
    async def export_conversation(project_id: str, session_id: str, request: ConversationExportRequest) -> Response:
        app_runtime.export_conversation(
            project_id,
            request.context_id,
            session_id,
            request.format,
            request.path,
        )
        return Response(status_code=204)

    @app.get("/api/v1/projects/{project_id}/pending-edits", dependencies=protected)
    async def pending_edits(project_id: str) -> Dict[str, Any]:
        return app_runtime.pending_edits(project_id)

    @app.post("/api/v1/projects/{project_id}/pending-edits/accept", dependencies=protected)
    async def accept_pending_edits(project_id: str, request: PendingEditActionRequest) -> Dict[str, Any]:
        del request
        return app_runtime.resolve_pending_edits(project_id, "accept")

    @app.post("/api/v1/projects/{project_id}/pending-edits/reject", dependencies=protected)
    async def reject_pending_edits(project_id: str, request: PendingEditActionRequest) -> Dict[str, Any]:
        del request
        return app_runtime.resolve_pending_edits(project_id, "reject")

    @app.post("/api/v1/projects/{project_id}/attachments/import", dependencies=protected)
    async def import_attachments(project_id: str, request: AttachmentImportRequest) -> Dict[str, Any]:
        return app_runtime.import_attachments(
            project_id,
            request.context_id,
            request.paths,
            request.kind,
        )

    @app.post("/api/v1/projects/{project_id}/attachments/preview", dependencies=protected)
    async def preview_attachment(project_id: str, request: AttachmentPreviewRequest) -> Dict[str, Any]:
        return app_runtime.attachment_preview(project_id, request.context_id, request.path)

    @app.post("/api/v1/projects/{project_id}/rag/indexes", status_code=202, dependencies=protected)
    async def build_rag_index(project_id: str, request: ContextRequest) -> Dict[str, Any]:
        app_runtime.require_context(project_id, request.context_id)
        return await app_runtime.rag_action(project_id, "index")

    @app.delete("/api/v1/projects/{project_id}/rag/index", status_code=204, dependencies=protected)
    async def clear_rag_index(project_id: str, request: ContextRequest) -> Response:
        await app_runtime.clear_rag_index(project_id, request.context_id)
        return Response(status_code=204)

    @app.post("/api/v1/projects/{project_id}/rag/searches", dependencies=protected)
    async def search_rag(project_id: str, request: RagSearchRequest) -> Dict[str, Any]:
        app_runtime.require_context(project_id, request.context_id)
        result = await app_runtime.rag_action(project_id, "query", request.query)
        return {
            "context_id": request.context_id,
            "result_text": result["result_text"],
        }

    # Simulation
    @app.get("/api/v1/projects/{project_id}/simulations", dependencies=protected)
    async def simulation_snapshot(project_id: str) -> Dict[str, Any]:
        return app_runtime.simulation_snapshot(project_id)

    @app.post("/api/v1/projects/{project_id}/simulations", status_code=202, dependencies=protected)
    async def start_simulation(project_id: str, request: SimulationStartRequest) -> Dict[str, Any]:
        return app_runtime.start_simulation(project_id, request.circuit_path)

    @app.get("/api/v1/projects/{project_id}/simulations/jobs/{job_id}", dependencies=protected)
    async def simulation_job(project_id: str, job_id: str) -> Dict[str, Any]:
        return app_runtime.simulation_job(project_id, job_id)

    @app.post("/api/v1/projects/{project_id}/simulations/jobs/{job_id}/cancel", dependencies=protected)
    async def cancel_simulation(project_id: str, job_id: str) -> Dict[str, Any]:
        return app_runtime.cancel_simulation(project_id, job_id)

    @app.get("/api/v1/projects/{project_id}/simulation-results", dependencies=protected)
    async def simulation_results(project_id: str) -> Dict[str, Any]:
        return app_runtime.list_simulation_results(project_id)

    @app.get("/api/v1/projects/{project_id}/simulation-results/{result_id}", dependencies=protected)
    async def simulation_result(project_id: str, result_id: str) -> Dict[str, Any]:
        return app_runtime.get_simulation_result(project_id, result_id)

    @app.get("/api/v1/projects/{project_id}/simulation-results/{result_id}/surface-data", dependencies=protected)
    async def simulation_surface(project_id: str, result_id: str) -> Dict[str, Any]:
        return app_runtime.get_simulation_surface(project_id, result_id)

    @app.delete("/api/v1/projects/{project_id}/simulation-results/{result_id}", dependencies=protected)
    async def delete_simulation_result(project_id: str, result_id: str) -> Dict[str, Any]:
        return app_runtime.delete_simulation_result(project_id, result_id)

    @app.post("/api/v1/projects/{project_id}/simulation-results/{result_id}/exports", dependencies=protected)
    async def export_simulation_result(project_id: str, result_id: str, request: ExportRequest) -> Dict[str, Any]:
        return app_runtime.export_simulation_result(project_id, result_id, request.format, request.surface)

    # Global settings
    @app.get("/api/v1/preferences", dependencies=protected)
    async def preferences() -> Dict[str, str]:
        return {
            "language": str(app_runtime.config_manager.get("language", "en_US") or "en_US"),
            "theme": str(app_runtime.config_manager.get("theme", "system") or "system"),
        }

    @app.put("/api/v1/preferences", dependencies=protected)
    async def save_preferences(request: PreferencesRequest) -> Dict[str, str]:
        app_runtime.config_manager.set("language", request.language, save=False)
        app_runtime.config_manager.set("theme", request.theme, save=False)
        app_runtime.config_manager.save_config()
        return request.model_dump()

    @app.get("/api/v1/model-config", dependencies=protected)
    async def model_config() -> Dict[str, Any]:
        return app_runtime.model_config()

    @app.put("/api/v1/model-config", dependencies=protected)
    async def save_model_config(request: ModelConfigRequest) -> Dict[str, Any]:
        return await app_runtime.save_model_config(request.model_dump())

    @app.post("/api/v1/model-config/test", dependencies=protected)
    async def test_model_config(request: ModelTestRequest) -> Dict[str, Any]:
        return await app_runtime.test_model_config(request.section, request.config)

    @app.get("/api/v1/about", dependencies=protected)
    async def about() -> Dict[str, str]:
        return {
            "name": "Circuit Design AI",
            "version": APP_VERSION,
            "api_version": API_VERSION,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        }

    return app


__all__ = ["API_VERSION", "APP_VERSION", "EventHub", "create_app"]
