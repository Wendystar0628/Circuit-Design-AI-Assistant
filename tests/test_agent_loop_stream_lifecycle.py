"""Regression tests for ``AgentLoop._stream_llm_response`` under the
cancel-event streaming protocol.

Authoritative invariants:

- ``AgentLoop`` MUST pass an ``asyncio.Event`` as ``cancel_event`` to
  ``chat_stream``. When ``stop_requested()`` first returns True, the
  loop must ``.set()`` that event and continue iterating until the
  generator ends naturally, then raise ``CancelledError`` via
  ``_raise_if_stop_requested``.

- ``AgentLoop`` MUST NOT wrap the generator in ``aclosing`` or call
  ``aclose()`` on it directly — doing so re-introduces the
  GeneratorExit injection path that crashes httpx/httpcore under
  qasync.

- Any content yielded before stop is accumulated into ``TurnResult``
  so the downstream UI can surface it as partial response.
"""

from __future__ import annotations

import asyncio
from typing import List

import pytest

from infrastructure.llm_adapters.base_client import StreamChunk
from domain.llm.agent.agent_loop import AgentLoop


class _FakeClient:
    """Fake LLM client whose ``chat_stream`` observes ``cancel_event``
    and ends the stream cooperatively, just like a real provider.
    """

    def __init__(self, yields: List[StreamChunk], *, keep_alive_after_yields: bool = True):
        self.yields = yields
        self._keep_alive = keep_alive_after_yields
        self.received_cancel_event: asyncio.Event | None = None

    async def chat_stream(self, *, messages, model, tools, thinking, cancel_event):
        self.received_cancel_event = cancel_event
        for chunk in self.yields:
            if cancel_event is not None and cancel_event.is_set():
                return
            yield chunk
        if self._keep_alive and cancel_event is not None:
            await cancel_event.wait()


class _FakeRegistry:
    def get_all_openai_schemas(self):
        return []


def test_agent_loop_forwards_cancel_event_and_never_receives_stop_kwargs():
    """Contract: the SDK boundary receives exactly one cancel primitive
    (``cancel_event``) and nothing else stop-related."""
    client = _FakeClient([StreamChunk(content="part-1"), StreamChunk(content="part-2")])

    loop_obj = AgentLoop(
        client=client,
        registry=_FakeRegistry(),
        context=None,
        model="test-model",
        stop_requested=lambda: False,
    )

    async def run():
        await loop_obj._stream_llm_response([], [], None, step_index=1)

    asyncio.run(run())
    assert isinstance(client.received_cancel_event, asyncio.Event)
    assert not client.received_cancel_event.is_set()


def test_agent_loop_sets_cancel_event_on_stop_and_raises_cancelled_error():
    """When ``stop_requested`` fires mid-stream, ``AgentLoop`` must
    set ``cancel_event`` (telling the provider to close its HTTP
    response) and, once the generator ends, raise ``CancelledError``
    so ``LLMExecutor`` can complete the stop handshake."""
    stop_state = {"requested": False}

    def _stop_requested() -> bool:
        return stop_state["requested"]

    client = _FakeClient([
        StreamChunk(content="alpha"),
        StreamChunk(content="beta"),
    ])

    loop_obj = AgentLoop(
        client=client,
        registry=_FakeRegistry(),
        context=None,
        model="test-model",
        stop_requested=_stop_requested,
    )

    async def _on_event(event_type, data):
        # Flip the stop flag after observing the first content chunk.
        if (
            event_type == "stream_chunk"
            and data.get("chunk_type") == "content"
            and data.get("text") == "alpha"
        ):
            stop_state["requested"] = True

    async def run():
        await loop_obj._stream_llm_response([], [], _on_event, step_index=1)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())

    assert client.received_cancel_event is not None
    assert client.received_cancel_event.is_set(), (
        "AgentLoop must signal stop via cancel_event so the provider "
        "closes its HTTP response on the active await chain."
    )


def test_agent_loop_accumulates_partial_content_before_stop():
    """Already-streamed content must be preserved in ``TurnResult``
    so the UI can persist it as partial response on stop."""
    stop_state = {"requested": False}

    def _stop_requested() -> bool:
        return stop_state["requested"]

    client = _FakeClient([
        StreamChunk(content="alpha"),
        StreamChunk(content="beta"),
    ])

    loop_obj = AgentLoop(
        client=client,
        registry=_FakeRegistry(),
        context=None,
        model="test-model",
        stop_requested=_stop_requested,
    )

    captured = {"text": ""}

    async def _on_event(event_type, data):
        if event_type == "stream_chunk" and data.get("chunk_type") == "content":
            captured["text"] += data.get("text", "")
            if captured["text"] == "alphabeta":
                stop_state["requested"] = True

    async def run():
        await loop_obj._stream_llm_response([], [], _on_event, step_index=1)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())

    # Both chunks were emitted before stop fired, so the UI layer
    # observed the full "alphabeta" before the cancel signal.
    assert captured["text"] == "alphabeta"
