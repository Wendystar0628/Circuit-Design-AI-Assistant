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
