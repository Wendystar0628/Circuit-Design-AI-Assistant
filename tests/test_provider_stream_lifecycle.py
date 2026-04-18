"""Regression tests for the cancel-event-driven streaming contract.

These tests pin the architectural invariants:

1. ``chat_stream`` must NEVER be interrupted through async-generator
   ``aclose()``. Stop is communicated via ``cancel_event.set()``,
   which triggers a watcher inside ``chat_stream`` that closes the
   underlying HTTP response. The ``async for`` at the call site then
   ends naturally (with an ``httpx.HTTPError`` that the producer
   swallows), and ``async with client.stream(...)`` unwinds through
   its normal ``__aexit__``.

2. Under qasync + anyio + httpcore the aclose path is broken
   (``HTTP11ConnectionByteStream.__aiter__``'s
   ``except BaseException: await self.aclose()`` re-enters an anyio
   lock and dies with ``no running event loop``). The tests exercise
   the event-driven path to guarantee we never regress into
   aclose-based cancellation.
"""

import asyncio

import httpx
import pytest

from infrastructure.llm_adapters.base_client import StreamChunk
from infrastructure.llm_adapters.openai_compatible_client import OpenAICompatibleClient
from infrastructure.llm_adapters.zhipu.zhipu_stream_handler import ZhipuStreamHandler


# ---------------------------------------------------------------
# Zhipu stream handler: single-layer drain check.
# ---------------------------------------------------------------


class _FakeZhipuResponse:
    def __init__(self, chunks, *, block_after_chunks: bool = False):
        self._chunks = list(chunks)
        self._block_after_chunks = block_after_chunks
        self.closed = asyncio.Event()

    async def aiter_text(self):
        for chunk in self._chunks:
            if self.closed.is_set():
                raise httpx.StreamError("response closed")
            yield chunk
        if self._block_after_chunks:
            # Emulate a still-open SSE; only a real close should end us.
            await self.closed.wait()
            raise httpx.StreamError("response closed")


def test_zhipu_stream_handler_drains_normal_completion():
    response = _FakeZhipuResponse([
        'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":null}]}\n',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":1}}\n',
        'data: [DONE]\n',
    ])

    async def collect():
        handler = ZhipuStreamHandler()
        chunks = []
        async for chunk in handler.iterate_response(response):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(collect())
    assert any(c.content == "hello" for c in chunks)
    assert any(c.is_finished for c in chunks)


# ---------------------------------------------------------------
# OpenAI-compatible provider (Qwen / DeepSeek) — end-to-end cancel
# contract.
# ---------------------------------------------------------------


class _FakeSSEResponse:
    """Minimal ``httpx.Response`` stand-in that respects ``aclose()``.

    ``aiter_lines()`` is an async generator that yields queued lines,
    then awaits an internal event for more, then raises
    ``httpx.StreamError`` once ``aclose()`` is invoked — mirroring the
    production behaviour we rely on for cancellation.
    """

    def __init__(self, prelude, *, live: bool = False):
        self.status_code = 200
        self.headers = {}
        self.request = None
        self._prelude = list(prelude)
        self._live = live
        self._close_event = asyncio.Event()
        self.closed = False
        self.aiter_closed = False

    async def aread(self):
        return b""

    async def aclose(self):
        self.closed = True
        self._close_event.set()

    async def aiter_lines(self):
        try:
            for line in self._prelude:
                if self._close_event.is_set():
                    raise httpx.StreamError("response closed")
                yield line
            if self._live:
                # Block until aclose() fires, then surface an httpx
                # error — exactly what real httpx does when the
                # caller closes a streaming response mid-read.
                await self._close_event.wait()
                raise httpx.StreamError("response closed")
        finally:
            self.aiter_closed = True


class _FakeResponseCtx:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, exc_type, exc, tb):
        # Emulate httpx: async-with exit always finalises the stream.
        if not self._response.closed:
            await self._response.aclose()
        return False


class _FakeAsyncClientCtx:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url, json=None):
        return _FakeResponseCtx(self._response)


def _make_client(response) -> OpenAICompatibleClient:
    client = OpenAICompatibleClient(
        provider_id="qwen",
        api_key="fake-key",
        base_url="https://example.test/v1",
        model="fake-model",
    )
    client._create_async_client = lambda: _FakeAsyncClientCtx(response)
    return client


def test_openai_compatible_stream_drains_sse_on_normal_finish():
    response = _FakeSSEResponse([
        'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
        'data: [DONE]',
    ])

    async def run():
        client = _make_client(response)
        chunks = []
        async for chunk in client.chat_stream(
            messages=[{"role": "user", "content": "ping"}],
            model="fake-model",
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(run())

    assert response.closed is True, "async-with exit must finalise the response"
    assert any(chunk.content == "hi" for chunk in chunks)
    assert any(chunk.is_finished for chunk in chunks)


def test_openai_compatible_stream_cancel_event_closes_response_and_returns_cleanly():
    """Core regression: when ``cancel_event`` fires mid-stream, the
    watcher must close the response and ``chat_stream`` must exit
    via ``StopAsyncIteration`` (not by raising). This is the
    behaviour that lets ``async with client.stream(...)`` unwind
    through its standard ``__aexit__`` instead of through the
    GeneratorExit-based aclose path that crashes under qasync.
    """
    response = _FakeSSEResponse(
        [
            'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}',
        ],
        live=True,
    )

    async def scenario():
        client = _make_client(response)
        cancel_event = asyncio.Event()
        received = []
        stream = client.chat_stream(
            messages=[{"role": "user", "content": "ping"}],
            model="fake-model",
            cancel_event=cancel_event,
        )
        async for chunk in stream:
            received.append(chunk)
            if chunk.content == "partial":
                cancel_event.set()  # User clicks stop.
        return received

    received = asyncio.run(scenario())

    assert any(c.content == "partial" for c in received)
    assert response.closed is True
    assert response.aiter_closed is True


def test_openai_compatible_stream_rejects_unknown_kwargs_loudly():
    """SDK boundary is closed: passing a legacy ``stop_requested``
    kwarg must raise ``TypeError`` at the call site, never silently
    leak into the wire request body."""
    response = _FakeSSEResponse([
        'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}]}',
        'data: [DONE]',
    ])

    async def run():
        client = _make_client(response)
        async for _ in client.chat_stream(  # type: ignore[call-arg]
            messages=[{"role": "user", "content": "ping"}],
            model="fake-model",
            stop_requested=lambda: True,
        ):
            pass

    with pytest.raises(TypeError) as excinfo:
        asyncio.run(run())

    assert "stop_requested" in str(excinfo.value)


def test_openai_compatible_stream_never_triggers_aclose_on_generator():
    """Defensive contract: the producer must never swallow a
    ``GeneratorExit`` by itself. The only way to stop it is via
    ``cancel_event`` + watcher. This test verifies that if a caller
    accidentally calls ``aclose()`` on the chat_stream generator,
    the underlying response IS closed (via async-with exit), but
    we do not rely on that code path for correctness."""
    response = _FakeSSEResponse(
        [
            'data: {"choices":[{"delta":{"content":"x"},"finish_reason":null}]}',
        ],
        live=True,
    )

    async def run():
        client = _make_client(response)
        stream = client.chat_stream(
            messages=[{"role": "user", "content": "ping"}],
            model="fake-model",
        )
        # Advance once, then call aclose — this IS technically
        # legal (Python async gen protocol). The fake httpx stack
        # still finalises correctly because our fake cooperates with
        # close. The real bug lives in httpcore, not in this layer.
        await stream.__anext__()
        await stream.aclose()

    asyncio.run(run())
    assert response.closed is True
