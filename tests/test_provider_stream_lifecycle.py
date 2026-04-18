"""Regression tests for the stop-agnostic streaming contract.

Authoritative invariants:

1. ``chat_stream`` is **stop-agnostic**: the SDK boundary accepts
   exactly one cancellation primitive — ``asyncio.Task.cancel()``
   on the owning task. Any other stop kwarg (``cancel_event``,
   ``stop_requested``, ...) MUST be rejected at the boundary,
   never silently forwarded to the wire.

2. Cancellation travels through ``CancelledError`` raised at the
   deepest ``await`` (httpx ``socket.recv``), unwinds through the
   ``async with client.stream(...)`` context, and lets httpx's
   ``AsyncShieldCancellation`` close the response synchronously.
   No ``aclose()`` side-channel is required in the producer.
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


@pytest.mark.parametrize("legacy_kwarg", ["cancel_event", "stop_requested"])
def test_openai_compatible_stream_rejects_legacy_stop_kwargs_loudly(legacy_kwarg):
    """SDK boundary is closed: any legacy stop kwarg
    (``cancel_event``, ``stop_requested``, ...) must raise
    ``TypeError`` at the call site, never silently leak into the
    wire request body. Cancel travels exclusively via
    ``asyncio.Task.cancel()``.
    """
    response = _FakeSSEResponse([
        'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}]}',
        'data: [DONE]',
    ])

    async def run():
        client = _make_client(response)
        kwargs = {legacy_kwarg: (asyncio.Event() if legacy_kwarg == "cancel_event" else (lambda: True))}
        async for _ in client.chat_stream(  # type: ignore[call-arg]
            messages=[{"role": "user", "content": "ping"}],
            model="fake-model",
            **kwargs,
        ):
            pass

    with pytest.raises(TypeError) as excinfo:
        asyncio.run(run())

    assert legacy_kwarg in str(excinfo.value)


def test_openai_compatible_stream_cancel_unwinds_through_async_with_exit():
    """Authoritative cancel path: when the owning task is cancelled,
    ``CancelledError`` unwinds through the ``async with client.stream``
    context and httpx finalises the underlying response via its
    normal ``__aexit__`` — no producer-side ``aclose`` required.
    """
    response = _FakeSSEResponse(
        [
            'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}',
        ],
        live=True,
    )

    async def scenario():
        client = _make_client(response)
        received: list = []

        async def consume():
            async for chunk in client.chat_stream(
                messages=[{"role": "user", "content": "ping"}],
                model="fake-model",
            ):
                received.append(chunk)

        task = asyncio.create_task(consume())
        # Let the consumer pull the first chunk, then cancel the
        # owning task — mirrors ``LLMExecutor.request_stop``.
        while not received:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return received

    received = asyncio.run(scenario())

    assert any(c.content == "partial" for c in received)
    assert response.closed is True, "async-with __aexit__ must finalise the response"
    assert response.aiter_closed is True
