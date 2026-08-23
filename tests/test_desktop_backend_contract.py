from __future__ import annotations

import asyncio
import ast
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from application.runtime import ApplicationRuntime, ProjectIdentity
from desktop_backend.app import API_VERSION, SimulationStartRequest, create_app
from shared.event_types import EVENT_FILE_CHANGED
from shared.file_change import FileChange


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOKEN = "a" * 64
RENDERER_ORIGIN = "http://localhost:5173"


class _FakeRuntime:
    """Enough lifecycle for adapter tests without starting the real services."""

    project = None

    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


def _route_inventory() -> set[tuple[str, str]]:
    app = create_app(TOKEN, RENDERER_ORIGIN, runtime=_FakeRuntime())
    inventory: set[tuple[str, str]] = set()
    for route in app.routes:
        if not route.path.startswith("/api/v1"):
            continue
        methods = getattr(route, "methods", None)
        if methods is None:
            inventory.add(("WS", route.path))
            continue
        inventory.update(
            (method, route.path)
            for method in methods
            if method not in {"HEAD", "OPTIONS"}
        )
    return inventory


def test_api_v1_route_inventory_is_one_modern_contract() -> None:
    expected = {
        ("GET", "/api/v1/app/state"),
        ("WS", "/api/v1/events"),
        ("GET", "/api/v1/project"),
        ("POST", "/api/v1/project/open"),
        ("POST", "/api/v1/project/close"),
        ("GET", "/api/v1/project/recent"),
        ("GET", "/api/v1/projects/{project_id}/workspace/tree"),
        ("POST", "/api/v1/projects/{project_id}/workspace/entries"),
        ("POST", "/api/v1/projects/{project_id}/workspace/moves"),
        (
            "DELETE",
            "/api/v1/projects/{project_id}/workspace/entries/{path:path}",
        ),
        ("GET", "/api/v1/projects/{project_id}/files/{path:path}"),
        ("PUT", "/api/v1/projects/{project_id}/files/{path:path}"),
        ("GET", "/api/v1/projects/{project_id}/assets/{path:path}"),
        ("GET", "/api/v1/projects/{project_id}/conversations"),
        ("POST", "/api/v1/projects/{project_id}/conversations"),
        ("GET", "/api/v1/projects/{project_id}/conversations/{session_id}"),
        ("PUT", "/api/v1/projects/{project_id}/conversations/{session_id}"),
        ("DELETE", "/api/v1/projects/{project_id}/conversations/{session_id}"),
        (
            "POST",
            "/api/v1/projects/{project_id}/conversations/{session_id}/activate",
        ),
        (
            "POST",
            "/api/v1/projects/{project_id}/conversations/{session_id}/runs",
        ),
        (
            "POST",
            "/api/v1/projects/{project_id}/conversations/{session_id}/runs/{run_id}/cancel",
        ),
        (
            "POST",
            "/api/v1/projects/{project_id}/conversations/{session_id}/compression-preview",
        ),
        (
            "POST",
            "/api/v1/projects/{project_id}/conversations/{session_id}/compressions",
        ),
        (
            "POST",
            "/api/v1/projects/{project_id}/conversations/{session_id}/rollback-preview",
        ),
        (
            "POST",
            "/api/v1/projects/{project_id}/conversations/{session_id}/rollbacks",
        ),
        (
            "POST",
            "/api/v1/projects/{project_id}/conversations/{session_id}/exports",
        ),
        ("GET", "/api/v1/projects/{project_id}/pending-edits"),
        ("POST", "/api/v1/projects/{project_id}/pending-edits/accept"),
        ("POST", "/api/v1/projects/{project_id}/pending-edits/reject"),
        ("POST", "/api/v1/projects/{project_id}/attachments/import"),
        ("POST", "/api/v1/projects/{project_id}/attachments/preview"),
        ("POST", "/api/v1/projects/{project_id}/rag/indexes"),
        ("DELETE", "/api/v1/projects/{project_id}/rag/index"),
        ("POST", "/api/v1/projects/{project_id}/rag/searches"),
        ("GET", "/api/v1/projects/{project_id}/simulations"),
        ("POST", "/api/v1/projects/{project_id}/simulations"),
        ("GET", "/api/v1/projects/{project_id}/simulations/jobs/{job_id}"),
        (
            "POST",
            "/api/v1/projects/{project_id}/simulations/jobs/{job_id}/cancel",
        ),
        ("GET", "/api/v1/projects/{project_id}/simulation-results"),
        (
            "GET",
            "/api/v1/projects/{project_id}/simulation-results/{result_id}",
        ),
        (
            "GET",
            "/api/v1/projects/{project_id}/simulation-results/{result_id}/surface-data",
        ),
        (
            "DELETE",
            "/api/v1/projects/{project_id}/simulation-results/{result_id}",
        ),
        (
            "POST",
            "/api/v1/projects/{project_id}/simulation-results/{result_id}/exports",
        ),
        ("GET", "/api/v1/preferences"),
        ("PUT", "/api/v1/preferences"),
        ("GET", "/api/v1/model-config"),
        ("PUT", "/api/v1/model-config/chat"),
        ("PUT", "/api/v1/model-config/embedding"),
        ("POST", "/api/v1/model-config/chat/test"),
        ("POST", "/api/v1/model-config/embedding/test"),
        ("GET", "/api/v1/about"),
    }

    inventory = _route_inventory()

    assert inventory == expected
    paths = {path for _, path in inventory}
    assert not any(
        path == "/api/v1/conversation"
        or path.startswith("/api/v1/conversation/")
        for path in paths
    )
    assert not any("/workspace/open-entry" in path for path in paths)


def test_model_config_routes_are_section_scoped_and_preserve_api_key_tri_state() -> None:
    runtime = _FakeRuntime()
    received: list[tuple[str, dict[str, Any]]] = []

    async def save_chat(payload: dict[str, Any]) -> dict[str, Any]:
        received.append(("save_chat", payload))
        return {"section": "chat"}

    async def save_embedding(payload: dict[str, Any]) -> dict[str, Any]:
        received.append(("save_embedding", payload))
        return {"section": "embedding"}

    async def test_chat(payload: dict[str, Any]) -> dict[str, Any]:
        received.append(("test_chat", payload))
        return {"section": "chat", "status": "verified"}

    async def test_embedding(payload: dict[str, Any]) -> dict[str, Any]:
        received.append(("test_embedding", payload))
        return {"section": "embedding", "status": "verified"}

    runtime.save_chat_model_config = save_chat
    runtime.save_embedding_model_config = save_embedding
    runtime.test_chat_model_config = test_chat
    runtime.test_embedding_model_config = test_embedding
    app = create_app(TOKEN, RENDERER_ORIGIN, runtime=runtime)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    chat_payload = {
        "provider": "opencode",
        "model": "anthropic/claude-sonnet-5",
        "api_protocol": "anthropic_messages",
        "base_url": "",
        "timeout": 60,
        "enable_thinking": True,
    }
    embedding_payload = {
        "provider": "zhipu",
        "model": "embedding-3",
        "base_url": "",
        "timeout": 30,
        "batch_size": 16,
    }

    with TestClient(app) as client:
        saved_chat = client.put(
            "/api/v1/model-config/chat",
            headers=headers,
            json=chat_payload,
        )
        cleared_embedding_key = client.put(
            "/api/v1/model-config/embedding",
            headers=headers,
            json={**embedding_payload, "api_key": None},
        )
        tested_chat = client.post(
            "/api/v1/model-config/chat/test",
            headers=headers,
            json={**chat_payload, "api_key": "draft-key"},
        )
        tested_embedding = client.post(
            "/api/v1/model-config/embedding/test",
            headers=headers,
            json=embedding_payload,
        )

    assert saved_chat.json() == {"section": "chat"}
    assert cleared_embedding_key.json() == {"section": "embedding"}
    assert tested_chat.json() == {"section": "chat", "status": "verified"}
    assert tested_embedding.json() == {
        "section": "embedding",
        "status": "verified",
    }
    assert "api_key" not in received[0][1]
    assert received[1][1]["api_key"] is None
    assert received[2][1]["api_key"] == "draft-key"
    assert "api_key" not in received[3][1]


def test_health_is_public_but_api_and_websocket_require_the_sidecar_token() -> None:
    runtime = _FakeRuntime()
    app = create_app(TOKEN, RENDERER_ORIGIN, runtime=runtime)

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json() == {
            "status": "ok",
            "api_version": API_VERSION,
            "pid": os.getpid(),
        }

        assert client.get("/api/v1/project").status_code == 401
        assert (
            client.get(
                "/api/v1/project",
                headers={"Authorization": "Basic invalid"},
            ).status_code
            == 401
        )
        authorized = client.get(
            "/api/v1/project",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert authorized.status_code == 200
        assert authorized.json() == {"project": None}

        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect("/api/v1/events?token=wrong"):
                pass
        assert rejected.value.code == 4401

        with client.websocket_connect(f"/api/v1/events?token={TOKEN}") as socket:
            hello = socket.receive_json()
        assert set(hello) == {"type", "api_version", "connection_id"}
        assert hello["type"] == "hello"
        assert hello["api_version"] == API_VERSION
        assert isinstance(hello["connection_id"], str) and hello["connection_id"]

    assert runtime.started is True
    assert runtime.stopped is True


def test_http_api_allows_only_the_exact_renderer_origin() -> None:
    app = create_app(TOKEN, RENDERER_ORIGIN, runtime=_FakeRuntime())

    with TestClient(app) as client:
        preflight = client.options(
            "/api/v1/app/state",
            headers={
                "Origin": RENDERER_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == RENDERER_ORIGIN
        assert "authorization" in preflight.headers["access-control-allow-headers"].lower()

        mutation_preflight = client.options(
            "/api/v1/project/open",
            headers={
                "Origin": RENDERER_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert mutation_preflight.status_code == 200
        assert mutation_preflight.headers["access-control-allow-origin"] == RENDERER_ORIGIN
        assert "POST" in mutation_preflight.headers["access-control-allow-methods"]
        allowed_headers = mutation_preflight.headers["access-control-allow-headers"].lower()
        assert "authorization" in allowed_headers
        assert "content-type" in allowed_headers

        authorized = client.get(
            "/api/v1/app/state",
            headers={
                "Origin": RENDERER_ORIGIN,
                "Authorization": f"Bearer {TOKEN}",
            },
        )
        assert authorized.status_code == 200
        assert authorized.headers["access-control-allow-origin"] == RENDERER_ORIGIN

        rejected_origin = client.options(
            "/api/v1/app/state",
            headers={
                "Origin": "https://example.invalid",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert rejected_origin.status_code == 400
        assert "access-control-allow-origin" not in rejected_origin.headers


def test_packaged_renderer_null_origin_is_supported_without_wildcard_cors() -> None:
    app = create_app(TOKEN, "null", runtime=_FakeRuntime())

    with TestClient(app) as client:
        preflight = client.options(
            "/api/v1/preferences",
            headers={
                "Origin": "null",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "null"


@pytest.mark.parametrize(
    "origin",
    [
        "https://example.invalid:443",
        "http://localhost",
        "http://localhost:5173/path",
        "http://user:secret@localhost:5173",
        "http://localhost:5173?query=1",
    ],
)
def test_sidecar_rejects_non_renderer_origins(origin: str) -> None:
    with pytest.raises(ValueError, match="Renderer origin"):
        create_app(TOKEN, origin, runtime=_FakeRuntime())


def test_headless_runtime_and_fastapi_adapter_have_no_desktop_ui_imports() -> None:
    source_paths = [PROJECT_ROOT / "application" / "runtime.py"]
    source_paths.extend(sorted((PROJECT_ROOT / "desktop_backend").glob("*.py")))
    forbidden_modules = (
        "PyQt5",
        "PyQt6",
        "qasync",
        "presentation",
        "shared.async_runtime",
        "domain.llm.llm_executor",
    )

    for source_path in source_paths:
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(source_path))
        imported_modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)

        for forbidden in forbidden_modules:
            assert not any(
                module == forbidden or module.startswith(f"{forbidden}.")
                for module in imported_modules
            ), f"{source_path} imports removed desktop dependency {forbidden}"

        assert "llm_executor" not in source
        assert "PyQt" not in source
        assert "qasync" not in source
        assert "shared.async_runtime" not in source


@pytest.mark.parametrize(
    ("stored_role", "wire_role"),
    [
        ("human", "user"),
        ("ai", "assistant"),
        ("system", "system"),
        ("tool", "tool"),
    ],
)
def test_conversation_message_dto_is_the_raw_react_contract(
    stored_role: str,
    wire_role: str,
) -> None:
    message = {
        "type": stored_role,
        "content": "raw **markdown**",
        "additional_kwargs": {
            "timestamp": "2026-08-24T00:00:00+00:00",
            "metadata": {"id": "message-1"},
            "reasoning_content": "raw reasoning",
            "operations": ["read", "simulate"],
            "attachments": [
                {
                    "type": "image",
                    "path": ".circuit_ai/attachments/image.png",
                    "name": "image.png",
                    "mime_type": "image/png",
                    "size": 42,
                    "placement": "gallery",
                    "reference_id": "attachment-1",
                    "inline_marker": "",
                }
            ],
            "agent_steps": [
                {
                    "step_index": 1,
                    "step_id": "step-1",
                    "content": "raw step",
                    "content_html": "<b>removed</b>",
                    "reasoning_content": "raw step reasoning",
                    "reasoning_content_html": "<i>removed</i>",
                    "tool_calls": [
                        {
                            "tool_call_id": "tool-1",
                            "tool_name": "read_file",
                            "arguments": {"path": "main.cir"},
                            "result_content": "ok",
                            "status": "completed",
                            "details": {},
                        }
                    ],
                    "is_complete": True,
                    "is_partial": False,
                    "stop_reason": "",
                }
            ],
            "is_partial": True,
            "stop_reason": "user_stop",
        },
    }

    dto = ApplicationRuntime._conversation_message_dto(message, {"message-1"})

    assert set(dto) == {
        "id",
        "role",
        "content",
        "reasoning_content",
        "attachments",
        "agent_steps",
        "status_summary",
        "can_rollback",
        "is_partial",
        "stop_reason",
    }
    assert dto["id"] == "message-1"
    assert dto["role"] == wire_role
    assert dto["content"] == "raw **markdown**"
    assert dto["reasoning_content"] == "raw reasoning"
    assert dto["status_summary"] == "read · simulate"
    assert dto["can_rollback"] is (wire_role == "user")
    assert set(dto["attachments"][0]) == {
        "type",
        "path",
        "name",
        "mime_type",
        "size",
        "placement",
        "reference_id",
        "inline_marker",
    }
    assert set(dto["agent_steps"][0]) == {
        "step_index",
        "step_id",
        "content",
        "reasoning_content",
        "tool_calls",
        "is_complete",
        "is_partial",
        "stop_reason",
    }
    assert set(dto["agent_steps"][0]["tool_calls"][0]) == {
        "tool_call_id",
        "tool_name",
        "arguments",
        "result_content",
        "status",
        "details",
    }

    history_dto = ApplicationRuntime._conversation_history_message_dto(message)
    assert set(history_dto) == {
        "role",
        "content",
        "reasoning_content",
        "timestamp",
        "message_id",
        "attachments",
        "is_partial",
        "stop_reason",
    }
    assert history_dto["role"] == wire_role
    assert history_dto["message_id"] == "message-1"
    assert history_dto["timestamp"] == "2026-08-24T00:00:00+00:00"


def test_conversation_message_dto_has_the_same_instance_and_class_contract() -> None:
    message = {
        "type": "human",
        "content": "run the circuit",
        "additional_kwargs": {"metadata": {"id": "message-1"}},
    }

    assert ApplicationRuntime()._conversation_message_dto(
        message,
        {"message-1"},
    ) == ApplicationRuntime._conversation_message_dto(
        message,
        {"message-1"},
    )


def test_conversation_run_captures_rollback_anchor_before_starting() -> None:
    class FakeContextManager:
        def __init__(self) -> None:
            self.state: dict[str, Any] = {"messages": []}

        def get_current_state(self) -> dict[str, Any]:
            return self.state

        def add_user_message(
            self,
            content: str,
            *,
            attachments: list[Any],
            timestamp: str,
            message_id: str,
        ) -> None:
            self.state = {
                "messages": [
                    {
                        "content": content,
                        "attachments": attachments,
                        "timestamp": timestamp,
                        "message_id": message_id,
                    }
                ]
            }

        def sync_state(self, state: dict[str, Any]) -> None:
            self.state = state

    class FakeSessionManager:
        def __init__(self) -> None:
            self.save_count = 0

        def get_current_session_id(self) -> str:
            return "session-1"

        def mark_dirty(self) -> None:
            return None

        def save_current_session(self, **_kwargs: Any) -> bool:
            self.save_count += 1
            return True

    class FakeRollbackService:
        def __init__(self, context: FakeContextManager, *, fail: bool = False) -> None:
            self.context = context
            self.fail = fail
            self.captures: list[tuple[str, str]] = []

        async def capture_user_turn_checkpoint(
            self,
            *,
            anchor_message_id: str,
            anchor_timestamp: str,
        ) -> None:
            assert self.context.state["messages"][0]["message_id"] == anchor_message_id
            self.captures.append((anchor_message_id, anchor_timestamp))
            if self.fail:
                raise RuntimeError("snapshot failed")

    async def scenario() -> None:
        runtime = ApplicationRuntime()
        runtime._project = ProjectIdentity("project-1", str(PROJECT_ROOT), PROJECT_ROOT.name, 1)
        runtime._active_context_id = "context-1"
        runtime.llm_client = object()
        context = FakeContextManager()
        session = FakeSessionManager()
        rollback = FakeRollbackService(context)
        runtime.context_manager = context
        runtime.session_state_manager = session
        runtime.conversation_rollback_service = rollback
        runtime.conversation_state = lambda _project_id: {
            "context_id": "context-1",
            "session": {"id": "session-1"},
        }
        release_run = asyncio.Event()

        async def run_stub(*_args: Any) -> None:
            await release_run.wait()

        runtime._run_conversation = run_stub
        accepted = await runtime.send_message(
            "project-1",
            "context-1",
            "simulate this",
        )
        assert accepted["run_id"]
        assert len(rollback.captures) == 1
        anchor_id, anchor_timestamp = rollback.captures[0]
        assert context.state["messages"][0] == {
            "content": "simulate this",
            "attachments": [],
            "timestamp": anchor_timestamp,
            "message_id": anchor_id,
        }
        assert runtime._active_conversation_task is not None
        runtime._active_conversation_task.cancel()
        await asyncio.gather(runtime._active_conversation_task, return_exceptions=True)

        failed_runtime = ApplicationRuntime()
        failed_runtime._project = runtime._project
        failed_runtime._active_context_id = "context-1"
        failed_runtime.llm_client = object()
        failed_context = FakeContextManager()
        failed_session = FakeSessionManager()
        failed_runtime.context_manager = failed_context
        failed_runtime.session_state_manager = failed_session
        failed_runtime.conversation_rollback_service = FakeRollbackService(
            failed_context,
            fail=True,
        )
        failed_runtime.conversation_state = runtime.conversation_state

        with pytest.raises(RuntimeError, match="snapshot failed"):
            await failed_runtime.send_message(
                "project-1",
                "context-1",
                "must not run",
            )
        assert failed_context.state == {"messages": []}
        assert failed_session.save_count == 1
        assert failed_runtime._active_run_id is None
        assert failed_runtime._active_conversation_task is None

    asyncio.run(scenario())


def test_agent_run_uses_role_wire_messages_and_persists_raw_steps() -> None:
    from domain.llm.message_helpers import create_human_message
    from infrastructure.llm_adapters.base_client import StreamChunk

    class FakeClient:
        def __init__(self) -> None:
            self.messages: list[dict[str, Any]] = []

        async def chat_stream(self, *, messages: list[dict[str, Any]], **_kwargs: Any):
            self.messages = messages
            yield StreamChunk(
                content="raw **answer**",
                is_finished=True,
                finish_reason="stop",
            )

    class FakeContextManager:
        def __init__(self) -> None:
            self.assistant: tuple[str, dict[str, Any]] | None = None

        def get_working_messages(self) -> list[Any]:
            return [
                create_human_message(
                    "raw **question**",
                    message_id="user-1",
                )
            ]

        def add_assistant_message(self, content: str, **kwargs: Any) -> None:
            self.assistant = (content, kwargs)

    class FakeSessionManager:
        def get_current_session_id(self) -> str:
            return "session-1"

        def mark_dirty(self) -> None:
            return None

        def save_current_session(self, **_kwargs: Any) -> bool:
            return True

    async def scenario() -> None:
        runtime = ApplicationRuntime()
        project = ProjectIdentity("project-1", str(PROJECT_ROOT), PROJECT_ROOT.name, 1)
        runtime._project = project
        runtime._active_context_id = "context-1"
        runtime._active_run_id = "run-1"
        client = FakeClient()
        context = FakeContextManager()
        runtime.llm_client = client
        runtime.context_manager = context
        runtime.session_state_manager = FakeSessionManager()
        runtime.llm_runtime_config_manager = SimpleNamespace(
            resolve_active_config=lambda: SimpleNamespace(
                model="test-model",
                enable_thinking=False,
            )
        )
        runtime.rag_manager = None
        runtime.simulation_job_manager = None
        runtime.simulation_result_repository = None
        runtime.pending_workspace_edit_service = None
        runtime.conversation_state = lambda _project_id: {
            "project_id": "project-1",
            "context_id": "context-1",
            "active_run_id": "",
            "session": {"id": "session-1"},
        }

        await runtime._run_conversation(project, "context-1", "run-1", None)

        assert client.messages[0]["role"] == "system"
        assert client.messages[1] == {
            "role": "user",
            "content": "raw **question**",
        }
        assert context.assistant is not None
        content, metadata = context.assistant
        assert content == "raw **answer**"
        assert metadata["agent_steps"] == [
            {
                "step_index": 1,
                "step_id": "run-1:step:1",
                "content": "raw **answer**",
                "reasoning_content": "",
                "tool_calls": [],
                "is_complete": True,
                "is_partial": False,
                "stop_reason": "",
            }
        ]

    asyncio.run(scenario())


def test_model_config_exposes_flagship_catalog_and_custom_aggregators() -> None:
    runtime = ApplicationRuntime()
    runtime.llm_runtime_config_manager = SimpleNamespace(
        resolve_active_config=lambda: SimpleNamespace(
            provider="zhipu",
            model="glm-5.3",
            api_protocol="openai_chat",
            base_url="",
            effective_base_url="https://open.bigmodel.cn/api/paas/v4",
            timeout=60,
            enable_thinking=False,
            has_api_key=False,
        )
    )
    runtime.config_manager = SimpleNamespace(
        get=lambda _key, default=None: default
    )
    runtime.credential_manager = SimpleNamespace(
        get_credential=lambda *_args: None,
        has_credential=lambda *_args: False,
    )

    config = runtime.model_config()

    chat_providers = config["providers"]["chat"]
    assert [provider["id"] for provider in chat_providers] == [
        "openai",
        "anthropic",
        "gemini",
        "xai",
        "deepseek",
        "qwen",
        "zhipu",
        "kimi",
        "opencode",
        "siliconflow",
    ]
    for provider in chat_providers:
        model_ids = {model["id"] for model in provider["models"]}
        assert all(not model_id.startswith(f"{provider['id']}:") for model_id in model_ids)
        if provider["allow_custom_model"]:
            assert provider["default_model"] == ""
            assert provider["models"] == []
        else:
            assert provider["default_model"] in model_ids
            assert all(
                set(model) == {
                    "id",
                    "label",
                    "role",
                    "generation",
                    "status",
                    "protocol",
                    "capabilities",
                    "description",
                }
                for model in provider["models"]
            )

    opencode = next(provider for provider in chat_providers if provider["id"] == "opencode")
    assert [item["id"] for item in opencode["protocol_options"]] == [
        "openai_responses",
        "openai_chat",
        "anthropic_messages",
        "gemini_generate_content",
    ]
    siliconflow = next(
        provider for provider in chat_providers if provider["id"] == "siliconflow"
    )
    assert [item["id"] for item in siliconflow["protocol_options"]] == [
        "openai_chat"
    ]

    assert config["chat"] == {
        "provider": "zhipu",
        "model": "glm-5.3",
        "api_protocol": "openai_chat",
        "base_url": "",
        "effective_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "timeout": 60,
        "enable_thinking": False,
        "has_api_key": False,
    }
    embedding_provider = next(
        provider
        for provider in config["providers"]["embedding"]
        if provider["id"] == config["embedding"]["provider"]
    )
    assert config["embedding"]["model"] == embedding_provider["default_model"]
    assert config["embedding"]["base_url"] == ""
    assert (
        config["embedding"]["effective_base_url"]
        == embedding_provider["default_base_url"]
    )


def test_rag_clear_passes_exact_project_and_index_identity() -> None:
    class FakeRagManager:
        is_available = True
        generation = 9

        def __init__(self) -> None:
            self.cleared_with: dict[str, Any] | None = None

        async def clear_index_async(self, **identity: Any) -> None:
            self.cleared_with = identity

    async def scenario() -> None:
        runtime = ApplicationRuntime()
        runtime._project = ProjectIdentity(
            "project-1",
            str(PROJECT_ROOT),
            PROJECT_ROOT.name,
            1,
        )
        runtime.require_context = lambda _project_id, _context_id: {}
        rag = FakeRagManager()
        runtime.rag_manager = rag

        await runtime.clear_rag_index("project-1", "context-1")

        assert rag.cleared_with == {
            "expected_generation": 9,
            "expected_project_root": str(PROJECT_ROOT),
        }

    asyncio.run(scenario())


def test_rag_snapshot_exposes_cached_stats_and_files_without_html_projection() -> None:
    from domain.rag.rag_manager import FileIndexInfo, IndexStats, IndexStatus

    runtime = ApplicationRuntime()
    runtime.rag_manager = SimpleNamespace(
        get_index_status=lambda: IndexStatus(
            available=True,
            indexing=False,
            stats=IndexStats(
                total_files=2,
                processed=1,
                failed=1,
                total_chunks=7,
                storage_size_mb=1.25,
            ),
            files=[
                FileIndexInfo(
                    relative_path="docs/design.md",
                    status="processed",
                    chunks_count=7,
                    indexed_at="2026-08-24T00:00:00+00:00",
                ),
                FileIndexInfo(
                    relative_path="docs/broken.pdf",
                    status="failed",
                    error="extract failed",
                ),
            ],
        ),
        init_error=None,
        index_error=None,
    )

    state = runtime._conversation_rag_state()

    assert state["status"] == {
        "phase": "ready",
        "label": "Ready",
        "tone": "success",
    }
    assert state["stats"]["total_files"] == 2
    assert state["stats"]["total_chunks"] == 7
    assert state["actions"]["can_search"] is True
    assert state["files"][0]["relative_path"] == "docs/design.md"
    assert "path" not in state["files"][0]
    assert state["files"][0]["status_label"] == "Processed"
    assert state["files"][1]["tooltip"] == "extract failed"


def test_historical_result_job_lookup_is_scoped_to_the_current_project() -> None:
    runtime = ApplicationRuntime()
    result_path = "simulation_results/shared/result.json"
    runtime.simulation_job_manager = SimpleNamespace(
        list=lambda: [
            SimpleNamespace(
                project_root=r"C:\\old-project",
                result_path=result_path,
                job_id="old-job",
            ),
            SimpleNamespace(
                project_root=r"C:\\current-project",
                result_path=result_path,
                job_id="current-job",
            ),
        ]
    )
    project = ProjectIdentity(
        "project-1",
        r"C:\\current-project",
        "current-project",
        1,
    )

    assert runtime._job_for_result(project, result_path) == "current-job"


def test_failed_simulation_surface_uses_an_empty_metrics_collection() -> None:
    runtime = ApplicationRuntime()
    result = SimpleNamespace(
        file_path="failed.cir",
        source_digest="",
        to_dict=lambda: {
            "data": None,
            "measurements": None,
            "raw_output": "ngspice failed",
        },
    )
    runtime._result_record = lambda project_id, result_id: (  # type: ignore[method-assign]
        ProjectIdentity(project_id, r"C:\\project", "project", 1),
        "simulation_results/failed/result.json",
        result,
    )
    runtime.simulation_result_repository = SimpleNamespace(
        resolve_circuit_path=lambda _root, _path: None,
    )

    surface = runtime.get_simulation_surface("project-1", "result-1")

    assert surface["metrics"] == []
    assert surface["output_log"] == "ngspice failed"


def _file_change_event(change: FileChange) -> dict[str, Any]:
    return {"type": EVENT_FILE_CHANGED, "data": change.to_payload()}


def _file_change(
    root: Path,
    operation: str,
    path: Path,
    *,
    generation: int = 7,
    destination: Path | None = None,
    is_directory: bool = False,
) -> FileChange:
    return FileChange(
        operation=operation,
        path=str(path),
        dest_path=str(destination) if destination is not None else "",
        is_directory=is_directory,
        origin="contract-test",
        project_root=str(root),
        generation=generation,
        revision="missing" if operation == "delete" else "revision-1",
    )


def _runtime_for_file_events(
    root: Path,
) -> tuple[ApplicationRuntime, list[tuple[str, str, dict[str, Any], dict[str, Any]]]]:
    emitted: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
    runtime = ApplicationRuntime(
        emit_event=lambda event_type, project_id, payload, identity: emitted.append(
            (event_type, project_id, payload, identity)
        )
    )
    runtime._project = ProjectIdentity("project-1", str(root), root.name, 7)
    runtime.file_manager = SimpleNamespace(project_generation=7)
    return runtime, emitted


def test_canonical_file_changes_map_to_workspace_events_and_rebind_documents(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    nested = source / "nested"
    nested.mkdir(parents=True)
    child = source / "child.txt"
    leaf = nested / "leaf.txt"
    child.write_text("child", encoding="utf-8")
    leaf.write_text("leaf", encoding="utf-8")
    runtime, emitted = _runtime_for_file_events(tmp_path)
    child_document = runtime.read_document("project-1", "source/child.txt")
    leaf_document = runtime.read_document("project-1", "source/nested/leaf.txt")

    created = tmp_path / "created.cir"
    runtime._on_file_change_event(
        _file_change_event(_file_change(tmp_path, "create", created))
    )
    runtime._on_file_change_event(
        _file_change_event(_file_change(tmp_path, "update", created))
    )

    destination = tmp_path / "renamed"
    runtime._on_file_change_event(
        _file_change_event(
            _file_change(
                tmp_path,
                "move",
                source,
                destination=destination,
                is_directory=True,
            )
        )
    )

    assert [event[0] for event in emitted] == [
        "workspace.entry_created",
        "workspace.entry_updated",
        "workspace.entry_moved",
    ]
    assert emitted[0][2] == {"path": "created.cir", "is_directory": False}
    assert emitted[2][2] == {
        "source_path": "source",
        "destination_path": "renamed",
        "is_directory": True,
    }
    assert set(runtime._documents) == {
        "renamed/child.txt",
        "renamed/nested/leaf.txt",
    }
    assert (
        runtime._documents_by_id[child_document["document_id"]].path
        == "renamed/child.txt"
    )
    assert (
        runtime._documents_by_id[leaf_document["document_id"]].path
        == "renamed/nested/leaf.txt"
    )

    runtime._on_file_change_event(
        _file_change_event(
            _file_change(
                tmp_path,
                "delete",
                destination,
                is_directory=True,
            )
        )
    )
    assert emitted[-1][0] == "workspace.entry_deleted"
    assert emitted[-1][2] == {"path": "renamed", "is_directory": True}
    assert runtime._documents == {}
    assert runtime._documents_by_id == {}


def test_document_revision_hashes_exact_disk_bytes_across_crlf(tmp_path: Path) -> None:
    document_path = tmp_path / "main.cir"
    document_path.write_bytes(b"V1 in 0 DC 1\r\n.op\r\n.end\r\n")
    runtime, _emitted = _runtime_for_file_events(tmp_path)

    def write_file(path: Path, content: str) -> bool:
        path.write_bytes(content.encode("utf-8"))
        return True

    runtime.file_manager.write_file = write_file
    document = runtime.read_document("project-1", "main.cir")
    assert document["content"] == "V1 in 0 DC 1\r\n.op\r\n.end\r\n"

    saved = runtime.write_document(
        "project-1",
        "main.cir",
        document["document_id"],
        document["revision"],
        "V1 in 0 DC 2\n.op\n.end\n",
    )
    assert saved["revision"] == document["revision"] + 1


def test_file_changes_with_wrong_root_or_generation_fail_closed(
    tmp_path: Path,
) -> None:
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("tracked", encoding="utf-8")
    foreign_root = tmp_path / "foreign"
    foreign_root.mkdir()
    runtime, emitted = _runtime_for_file_events(tmp_path)
    document = runtime.read_document("project-1", "tracked.txt")
    original_paths = set(runtime._documents)

    runtime._on_file_change_event(
        _file_change_event(
            _file_change(foreign_root, "delete", foreign_root / "tracked.txt")
        )
    )
    runtime._on_file_change_event(
        _file_change_event(
            _file_change(tmp_path, "delete", tracked, generation=8)
        )
    )
    runtime.file_manager.project_generation = 8
    runtime._on_file_change_event(
        _file_change_event(_file_change(tmp_path, "delete", tracked))
    )

    assert emitted == []
    assert set(runtime._documents) == original_paths
    assert document["document_id"] in runtime._documents_by_id


def test_attachment_preview_simulation_start_and_one_file_health_contracts() -> None:
    image_preview = (
        PROJECT_ROOT
        / "frontend"
        / "desktop"
        / "src"
        / "renderer"
        / "src"
        / "features"
        / "conversation"
        / "components"
        / "ImagePreviewOverlay.tsx"
    ).read_text(encoding="utf-8")
    assert "api.getBlob(overlay.source_url)" in image_preview
    assert "src={overlay.source_url}" not in image_preview

    assert set(SimulationStartRequest.model_fields) == {"circuit_path"}

    electron_main = (
        PROJECT_ROOT / "frontend" / "desktop" / "src" / "main" / "index.ts"
    ).read_text(encoding="utf-8")
    wait_start = electron_main.index("async function waitForBackend(")
    wait_end = electron_main.index("async function startBackend(", wait_start)
    wait_for_backend = electron_main[wait_start:wait_end]
    assert "health.status === 'ok'" in wait_for_backend
    assert "health.api_version === 'v1'" in wait_for_backend
    assert "health.pid" not in wait_for_backend
    assert "processHandle.pid" not in wait_for_backend


def test_tool_execution_end_wire_has_one_status_authority() -> None:
    runtime_source = (PROJECT_ROOT / "application" / "runtime.py").read_text(
        encoding="utf-8"
    )
    callback_start = runtime_source.index(
        "async def on_event(event_type: str, payload: Dict[str, Any])"
    )
    callback_end = runtime_source.index(
        "result = await loop.run(messages, on_event=on_event)", callback_start
    )
    callback_source = runtime_source[callback_start:callback_end]
    assert 'event_type == "tool_execution_end"' in callback_source
    assert 'wire_payload.pop("is_error", False)' in callback_source
    assert '"failed"' in callback_source
    assert '"completed"' in callback_source

    controller_source = (
        PROJECT_ROOT
        / "frontend"
        / "desktop"
        / "src"
        / "renderer"
        / "src"
        / "features"
        / "conversation"
        / "useConversationController.ts"
    ).read_text(encoding="utf-8")
    event_start = controller_source.index(
        "event.type === 'conversation.tool_execution_end'"
    )
    event_end = controller_source.index(
        "event.type === 'conversation.completed'", event_start
    )
    event_source = controller_source[event_start:event_end]
    assert "payload.status === 'failed'" in event_source
    assert "payload.is_error" not in event_source
