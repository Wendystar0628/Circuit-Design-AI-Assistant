import asyncio
from contextlib import aclosing

from infrastructure.llm_adapters.base_client import StreamChunk
from infrastructure.llm_adapters.zhipu.zhipu_stream_handler import ZhipuStreamHandler


class _FakeResponse:
    """Minimal stand-in for ``httpx.Response`` in stream tests.

    ``aiter_text`` is implemented as an async generator so the
    production ``aclosing`` wrappers exercise the real Python
    async-generator close protocol. ``aiter_closed`` lets the tests
    assert that the inner stream was torn down deterministically
    rather than relying on GC.
    """

    def __init__(self, chunks, *, infinite: bool = False):
        self._chunks = list(chunks)
        self._infinite = infinite
        self.drained = False
        self.aiter_closed = False

    async def aiter_text(self):
        try:
            for chunk in self._chunks:
                yield chunk
            if self._infinite:
                # Simulate a live SSE stream the caller must cancel.
                while True:
                    yield ""
            self.drained = True
        finally:
            self.aiter_closed = True


async def _collect_chunks(response):
    handler = ZhipuStreamHandler()
    result = []
    async for chunk in handler.create_stream_iterator(response):
        result.append(chunk)
    return result


def test_zhipu_stream_handler_drains_http_response_after_finish_marker():
    response = _FakeResponse([
        'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":null}]}\n',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":1}}\n',
        'data: [DONE]\n',
    ])

    chunks = asyncio.run(_collect_chunks(response))

    assert response.drained is True
    assert response.aiter_closed is True
    assert any(chunk.content == 'hello' for chunk in chunks)
    assert any(chunk.is_finished for chunk in chunks)


def test_zhipu_stream_handler_closes_inner_aiter_when_consumer_aborts_mid_stream():
    """Regression: when the consumer (agent_loop) aborts the stream
    via ``aclose()``, the nested ``response.aiter_text()`` async gen
    must be closed synchronously on the current await chain.

    Before the fix, the inner gen was left dangling and its cleanup
    coroutine was run from GC after the event loop had stopped,
    yielding ``RuntimeError: no running event loop``.
    """

    response = _FakeResponse(
        [
            'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}\n',
        ],
        infinite=True,
    )

    async def scenario():
        handler = ZhipuStreamHandler()
        async with aclosing(handler.create_stream_iterator(response)) as stream:
            async for chunk in stream:
                if chunk.content == "partial":
                    break  # Simulate user clicking the stop button.
        return response.aiter_closed

    closed_deterministically = asyncio.run(scenario())
    assert closed_deterministically is True
