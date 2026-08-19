import asyncio
import copy
import os
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.messages import AIMessage

from domain.llm.context_compressor import ContextCompressor
from domain.llm.context_compression_service import _CompressionLLMAdapter
from domain.llm.llm_executor import LLMExecutor
from presentation.panels.conversation.conversation_view_model import ConversationViewModel
from shared.event_types import EVENT_CONTEXT_COMPRESS_COMPLETE, EVENT_SESSION_CHANGED


class _StrictCompressionClient:
    def __init__(
        self,
        *,
        content="真实模型摘要",
        finish_reason=None,
    ):
        self.calls = []
        self.content = content
        self.finish_reason = finish_reason

    def chat(self, *, messages, model, streaming, tools, thinking):
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "streaming": streaming,
                "tools": tools,
                "thinking": thinking,
            }
        )
        return SimpleNamespace(
            content=self.content,
            usage={"prompt_tokens": 12, "completion_tokens": 4},
            finish_reason=self.finish_reason,
        )


def test_compression_adapter_calls_strict_base_client_contract():
    client = _StrictCompressionClient()
    adapter = _CompressionLLMAdapter(client, "summary-model")

    result = asyncio.run(
        adapter.generate(
            "请压缩历史",
            max_tokens=321,
            temperature=0.1,
        )
    )

    assert result == {
        "content": "真实模型摘要",
        "usage": {"prompt_tokens": 12, "completion_tokens": 4},
        "finish_reason": None,
    }
    assert client.calls == [
        {
            "messages": [{"role": "user", "content": "请压缩历史"}],
            "model": "summary-model",
            "streaming": False,
            "tools": None,
            "thinking": False,
        }
    ]


def _compression_state():
    return {
        "messages": [
            HumanMessage(content="设计增益为十的放大器"),
            AIMessage(content="先计算反馈电阻"),
            HumanMessage(content="继续优化带宽"),
        ],
        "working_context_summary": "",
        "working_context_compressed_count": 0,
        "working_context_keep_recent": 0,
    }


@pytest.mark.parametrize(
    "finish_reason",
    [
        "length",
        "max_tokens",
        "content_filter",
        "blocked",
        "safety",
        "unexpected_provider_reason",
    ],
)
def test_unusable_provider_summary_finish_reason_uses_simple_fallback(
    finish_reason,
):
    client = _StrictCompressionClient(
        content="PARTIAL PROVIDER SUMMARY",
        finish_reason=finish_reason,
    )
    result = asyncio.run(
        ContextCompressor().compress(
            _compression_state(),
            _CompressionLLMAdapter(client, "summary-model"),
            keep_recent=1,
            context_limit=128000,
            model="default",
        )
    )

    assert result["status"] == "completed"
    compressed_state = result["state"]
    assert compressed_state["working_context_compressed_count"] == 2
    assert compressed_state["working_context_summary"] != "PARTIAL PROVIDER SUMMARY"
    assert "设计增益为十" in compressed_state["working_context_summary"]


@pytest.mark.parametrize("finish_reason", [None, "", "stop", "end_turn"])
def test_normal_provider_summary_finish_reason_keeps_model_summary(
    finish_reason,
):
    client = _StrictCompressionClient(
        content="COMPLETE PROVIDER SUMMARY",
        finish_reason=finish_reason,
    )
    result = asyncio.run(
        ContextCompressor().compress(
            _compression_state(),
            _CompressionLLMAdapter(client, "summary-model"),
            keep_recent=1,
            context_limit=128000,
            model="default",
        )
    )

    assert result["status"] == "completed"
    assert result["state"]["working_context_summary"] == "COMPLETE PROVIDER SUMMARY"
    assert result["state"]["working_context_compressed_count"] == 2


def test_unusable_finish_reason_and_empty_fallback_does_not_advance_state(
    monkeypatch,
):
    client = _StrictCompressionClient(
        content="PARTIAL PROVIDER SUMMARY",
        finish_reason="length",
    )
    state = _compression_state()
    compressor = ContextCompressor()
    monkeypatch.setattr(compressor, "_generate_simple_summary", lambda messages: "")

    result = asyncio.run(
        compressor.compress(
            state,
            _CompressionLLMAdapter(client, "summary-model"),
            keep_recent=1,
            context_limit=128000,
            model="default",
        )
    )

    assert result["status"] == "failed"
    assert result["state"] is state
    assert state["working_context_summary"] == ""
    assert state["working_context_compressed_count"] == 0


def test_executor_preserves_summary_when_prepending_agent_prompt(monkeypatch):
    from domain.llm.agent import agent_loop, agent_prompt_builder, tool_factory

    captured = {}

    class _Registry:
        @staticmethod
        def get_names():
            return []

    class _CapturingLoop:
        def __init__(self, **kwargs):
            del kwargs

        async def run(self, messages, on_event):
            del on_event
            captured["messages"] = messages
            return SimpleNamespace(
                is_error=False,
                error_message="",
                content="done",
                reasoning_content="",
                usage={},
                total_turns=1,
                tool_calls_count=0,
            )

    monkeypatch.setattr(agent_loop, "AgentLoop", _CapturingLoop)
    monkeypatch.setattr(tool_factory, "create_default_tools", lambda: _Registry())
    monkeypatch.setattr(
        agent_prompt_builder,
        "build_agent_system_prompt",
        lambda **kwargs: "AGENT SYSTEM PROMPT",
    )

    executor = LLMExecutor()
    monkeypatch.setattr(executor, "_get_llm_client", lambda model: object())
    monkeypatch.setattr(executor, "_get_project_root", lambda: "E:/demo")
    monkeypatch.setattr(executor, "_get_active_circuit_file", lambda: None)
    monkeypatch.setattr(executor, "_get_rag_query_service", lambda: None)
    monkeypatch.setattr(executor, "_get_sim_job_manager", lambda: None)
    monkeypatch.setattr(executor, "_get_sim_result_repository", lambda: None)
    monkeypatch.setattr(
        executor,
        "_get_pending_workspace_edit_service",
        lambda: None,
    )

    source_messages = [
        {
            "role": "system",
            "content": "以下摘要覆盖了更早的 8 条历史对话。\n\n放大倍数必须为 10。",
        },
        {"role": "user", "content": "继续优化。"},
    ]

    async def scenario():
        await executor.execute_agent("task-summary", source_messages, "model")

    asyncio.run(scenario())

    outbound = captured["messages"]
    assert outbound[0] == {
        "role": "system",
        "content": "AGENT SYSTEM PROMPT",
    }
    assert outbound[1] == source_messages[0]
    assert outbound[2] == source_messages[1]
    assert source_messages[0]["content"].startswith("以下摘要覆盖了")
    assert len(source_messages) == 2


class _CompressionEventBus:
    def __init__(self):
        self.handlers = {}
        self.published = []

    def subscribe(self, event_type, handler):
        self.handlers.setdefault(event_type, []).append(handler)

    def publish(self, event_type, payload=None, source=None):
        self.published.append((event_type, payload, source))
        envelope = {
            "type": event_type,
            "data": payload,
            "source": source,
        }
        for handler in list(self.handlers.get(event_type, [])):
            handler(envelope)


class _CompressionContextManager:
    def __init__(self, state):
        self.state = state
        self.synced_states = []

    def get_current_state(self):
        return self.state

    def sync_state(self, state):
        self.synced_states.append(state)
        self.state = state

    def calculate_usage(self, state, model, provider=None):
        del model, provider
        message_count = len(state.get("messages", []))
        return {
            "input_limit": 1000,
            "context_limit": 1200,
            "output_reserve": 200,
            "history_message_count": message_count,
            "working_message_count": message_count,
            "total_tokens": 900,
            "message_tokens": 900,
            "summary_tokens": 0,
            "available": 100,
            "usage_ratio": 0.9,
        }

    def classify_messages(self, state):
        del state
        return {}


class _CompressionSessionManager:
    def __init__(self, project_root, session_id, *, save_result=True, on_save=None):
        self.project_root = project_root
        self.session_id = session_id
        self.save_result = save_result
        self.on_save = on_save
        self.mark_dirty_calls = 0
        self.save_calls = 0
        self.saved_candidates = []

    def get_project_root(self):
        return self.project_root

    def get_current_session_id(self):
        return self.session_id

    def mark_dirty(self):
        self.mark_dirty_calls += 1

    def save_current_session(
        self,
        state=None,
        project_root=None,
        *,
        expected_session_id=None,
    ):
        self.save_calls += 1
        self.saved_candidates.append(
            {
                "state": state,
                "project_root": project_root,
                "expected_session_id": expected_session_id,
            }
        )
        if self.on_save is not None:
            self.on_save()
        return self.save_result


class _ImmediateCompletedCompressor:
    async def compress(self, state, adapter, **kwargs):
        del adapter, kwargs
        new_state = copy.deepcopy(state)
        new_state["working_context_summary"] = "durable summary candidate"
        new_state["working_context_compressed_count"] = 1
        return {"status": "completed", "state": new_state}


def _configure_compression_service(monkeypatch, context, sessions, event_bus):
    from domain.llm.context_compression_service import ContextCompressionService

    service = ContextCompressionService()
    service._context_manager = context
    service._session_state_manager = sessions
    service._event_bus = event_bus
    service._compressor = _ImmediateCompletedCompressor()
    monkeypatch.setattr(
        type(service),
        "llm_client",
        property(lambda self: object()),
    )
    monkeypatch.setattr(
        service,
        "_resolve_model",
        lambda: {
            "provider": "test",
            "model": "model",
            "model_id": "test:model",
        },
    )
    return service


def test_compression_save_failure_keeps_old_runtime_dirty_and_never_completes(
    monkeypatch,
):
    state = {
        "project_root": "E:/project-a",
        "session_id": "session-a",
        "messages": [HumanMessage(content="original runtime context")],
        "working_context_summary": "",
        "working_context_compressed_count": 0,
        "working_context_keep_recent": 1,
    }
    context = _CompressionContextManager(state)
    sessions = _CompressionSessionManager(
        "E:/project-a",
        "session-a",
        save_result=False,
    )
    bus = _CompressionEventBus()
    service = _configure_compression_service(monkeypatch, context, sessions, bus)

    result = asyncio.run(service.apply_manual_compression())

    assert result["status"] == "failed"
    assert context.state is state
    assert context.synced_states == []
    assert sessions.save_calls == 1
    assert sessions.mark_dirty_calls >= 1
    candidate = sessions.saved_candidates[0]
    assert candidate["state"]["working_context_summary"] == "durable summary candidate"
    assert candidate["project_root"] == os.path.normcase(
        os.path.abspath("E:/project-a")
    )
    assert candidate["expected_session_id"] == "session-a"
    assert not any(
        payload.get("status") in {"completed", "suggest_new_conversation"}
        for event_type, payload, _source in bus.published
        if event_type == EVENT_CONTEXT_COMPRESS_COMPLETE
    )


def test_session_switch_during_compression_persist_never_installs_old_candidate(
    monkeypatch,
):
    state_a = {
        "project_root": "E:/project-a",
        "session_id": "session-a",
        "messages": [HumanMessage(content="same message")],
        "working_context_summary": "",
        "working_context_compressed_count": 0,
        "working_context_keep_recent": 1,
    }
    state_b = {
        **state_a,
        "session_id": "session-b",
        "messages": list(state_a["messages"]),
    }
    context = _CompressionContextManager(state_a)
    sessions = _CompressionSessionManager(
        "E:/project-a",
        "session-a",
        save_result=False,
    )

    def _switch_during_save():
        sessions.session_id = "session-b"
        context.state = state_b

    sessions.on_save = _switch_during_save
    bus = _CompressionEventBus()
    service = _configure_compression_service(monkeypatch, context, sessions, bus)

    result = asyncio.run(service.apply_manual_compression())

    assert result["status"] == "invalidated"
    assert context.state is state_b
    assert context.synced_states == []
    assert sessions.save_calls == 1
    assert sessions.mark_dirty_calls == 0
    assert sessions.saved_candidates[0]["expected_session_id"] == "session-a"
    assert not any(
        event_type == EVENT_CONTEXT_COMPRESS_COMPLETE
        for event_type, _payload, _source in bus.published
    )


def test_identical_new_session_invalidates_old_compression_without_side_effects(
    monkeypatch,
):
    from domain.llm.context_compression_service import ContextCompressionService

    started = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()

    class _UncooperativeCompressor:
        async def compress(self, state, adapter, **kwargs):
            del adapter, kwargs
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                # Model transports running in a worker thread cannot actually
                # stop their underlying call.  Simulate a late result despite
                # the service's cancellation request.
                cancelled.set()
                await release.wait()
            new_state = copy.deepcopy(state)
            new_state["working_context_summary"] = "old-session-summary"
            new_state["working_context_compressed_count"] = 1
            return {"status": "completed", "state": new_state}

    async def scenario():
        bus = _CompressionEventBus()
        messages = [HumanMessage(content="两边完全相同的消息")]
        state_a = {
            "project_root": "E:/project-a",
            "session_id": "session-a",
            "messages": messages,
            "working_context_summary": "",
            "working_context_compressed_count": 0,
            "working_context_keep_recent": 1,
        }
        context = _CompressionContextManager(state_a)
        sessions = _CompressionSessionManager("E:/project-a", "session-a")
        service = ContextCompressionService()
        service._context_manager = context
        service._session_state_manager = sessions
        service._event_bus = bus
        service._compressor = _UncooperativeCompressor()
        monkeypatch.setattr(
            type(service),
            "llm_client",
            property(lambda self: object()),
        )
        monkeypatch.setattr(
            service,
            "_resolve_model",
            lambda: {
                "provider": "test",
                "model": "model",
                "model_id": "test:model",
            },
        )

        task = asyncio.create_task(service.apply_manual_compression())
        await started.wait()
        assert service.is_compressing is True

        # Switch to a different session with byte-for-byte identical messages.
        # A content-only signature cannot distinguish this transition.
        sessions.session_id = "session-b"
        context.state = {
            **state_a,
            "session_id": "session-b",
            "messages": list(messages),
        }
        bus.publish(
            EVENT_SESSION_CHANGED,
            {
                "action": "switch",
                "project_root": "E:/project-a",
                "previous_session_id": "session-a",
                "session_id": "session-b",
            },
            source="test",
        )
        await cancelled.wait()
        release.set()
        result = await task

        assert result["status"] == "invalidated"
        assert context.synced_states == []
        assert sessions.mark_dirty_calls == 0
        assert sessions.save_calls == 0
        assert not any(
            event_type == EVENT_CONTEXT_COMPRESS_COMPLETE
            for event_type, _payload, _source in bus.published
        )
        assert context.state["session_id"] == "session-b"

    asyncio.run(scenario())


def test_session_mutation_guard_includes_context_compression(monkeypatch):
    view_model = ConversationViewModel()
    view_model._context_compression_service = SimpleNamespace(is_compressing=True)
    monkeypatch.setattr(view_model, "_get_llm_executor", lambda: None)

    allowed, reason = view_model.can_change_session()

    assert allowed is False
    assert "压缩" in reason


@pytest.mark.parametrize("empty_content", ["", "  \n\t  "])
def test_empty_provider_summary_uses_nonempty_fallback_without_losing_history(
    empty_content,
):
    class _EmptyWorker:
        async def generate(self, **kwargs):
            del kwargs
            return {"content": empty_content}

    state = {
        "messages": [
            HumanMessage(content="设计增益为十的放大器"),
            AIMessage(content="先计算反馈电阻"),
            HumanMessage(content="继续优化带宽"),
        ],
        "working_context_summary": "",
        "working_context_compressed_count": 0,
        "working_context_keep_recent": 0,
    }

    result = asyncio.run(
        ContextCompressor().compress(
            state,
            _EmptyWorker(),
            keep_recent=1,
            context_limit=128000,
            model="default",
        )
    )

    assert result["status"] == "completed"
    compressed_state = result["state"]
    assert compressed_state["working_context_summary"].strip()
    assert compressed_state["working_context_compressed_count"] == 2
    assert "设计增益为十" in compressed_state["working_context_summary"]
    assert compressed_state["messages"] == state["messages"]


def test_empty_provider_and_empty_fallback_fail_without_advancing_state(monkeypatch):
    class _EmptyWorker:
        async def generate(self, **kwargs):
            del kwargs
            return {"content": " \n "}

    state = {
        "messages": [
            HumanMessage(content="first"),
            AIMessage(content="second"),
            HumanMessage(content="third"),
        ],
        "working_context_summary": "",
        "working_context_compressed_count": 0,
        "working_context_keep_recent": 0,
    }
    compressor = ContextCompressor()
    monkeypatch.setattr(compressor, "_generate_simple_summary", lambda messages: "  ")

    result = asyncio.run(
        compressor.compress(
            state,
            _EmptyWorker(),
            keep_recent=1,
            context_limit=128000,
            model="default",
        )
    )

    assert result["status"] == "failed"
    assert result["state"] is state
    assert state["working_context_summary"] == ""
    assert state["working_context_compressed_count"] == 0
