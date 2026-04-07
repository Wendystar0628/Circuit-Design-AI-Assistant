from infrastructure.llm_adapters.base_client import StreamChunk
from domain.llm.agent.agent_loop import AgentLoop


class _FakeStream:
    def __init__(self):
        self._index = 0
        self.drained = False
        self.aclose_called = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index == 0:
            self._index += 1
            return StreamChunk(content="hello")
        if self._index == 1:
            self._index += 1
            return StreamChunk(is_finished=True, finish_reason="stop")
        self.drained = True
        raise StopAsyncIteration

    async def aclose(self):
        self.aclose_called = True


class _FakeClient:
    def __init__(self, stream):
        self.stream = stream

    async def chat_stream(self, **kwargs):
        async for chunk in self.stream:
            yield chunk


class _StopAwareClient:
    def __init__(self):
        self.aclose_called = False
        self.stop_callback_seen = False

    async def chat_stream(self, **kwargs):
        stop_requested = kwargs.get("stop_requested")
        self.stop_callback_seen = callable(stop_requested)
        yield StreamChunk(content="partial")
        if callable(stop_requested) and stop_requested():
            return
        yield StreamChunk(is_finished=True, finish_reason="stop")


class _FakeRegistry:
    def get_all_openai_schemas(self):
        return []


def _noop_stop_requested():
    return False


async def _run_stream_once(stream):
    loop = AgentLoop(
        client=_FakeClient(stream),
        registry=_FakeRegistry(),
        context=None,
        model="test-model",
        stop_requested=_noop_stop_requested,
    )
    result = await loop._stream_llm_response([], [], None)
    return result


def test_agent_loop_allows_stream_generator_to_finish_naturally():
    import asyncio

    stream = _FakeStream()
    result = asyncio.run(_run_stream_once(stream))

    assert result.content == "hello"
    assert result.finish_reason == "stop"
    assert stream.drained is True
    assert stream.aclose_called is False


def test_agent_loop_stop_request_allows_provider_stream_to_exit_gracefully():
    import asyncio

    stop_state = {"requested": False}

    def _stop_requested():
        return stop_state["requested"]

    client = _StopAwareClient()
    loop = AgentLoop(
        client=client,
        registry=_FakeRegistry(),
        context=None,
        model="test-model",
        stop_requested=_stop_requested,
    )

    async def _on_event(event_type, data):
        if event_type == "stream_chunk" and data.get("chunk_type") == "content":
            stop_state["requested"] = True

    async def _run():
        await loop._stream_llm_response([], [], _on_event)

    try:
        asyncio.run(_run())
        raised = False
    except asyncio.CancelledError:
        raised = True

    assert raised is True
    assert client.stop_callback_seen is True
