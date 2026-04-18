"""Regression tests for ``AgentLoop._stream_llm_response``.

Design invariants exercised here:

- The LLM client's ``chat_stream`` **must not** receive a
  ``stop_requested`` kwarg. Stop semantics are owned by the consumer
  (``AgentLoop``) and propagated to the SDK layer only via
  ``aclose()`` on the async generator.
- On a stop request, the consumer ``break``s out of its ``async for``
  loop; the ``aclosing`` wrapper must call ``aclose()`` on the
  underlying stream **on the current await chain**, not in GC.
- After the stream is closed deterministically, a ``CancelledError``
  is raised so ``AgentLoop.run`` unwinds cleanly.
"""

from __future__ import annotations

import asyncio
from typing import List

import pytest

from infrastructure.llm_adapters.base_client import StreamChunk
from domain.llm.agent.agent_loop import AgentLoop


class _RecordingStreamClient:
    """Fake LLM client whose ``chat_stream`` yields chunks forever and
    records how ``aclose()`` is exercised.
    """

    def __init__(self) -> None:
        self.received_kwargs: dict = {}
        self.gen_aclose_called: bool = False
        self.yields: List[StreamChunk] = [
            StreamChunk(content="part-1"),
            StreamChunk(content="part-2"),
            StreamChunk(content="part-3"),
        ]

    async def chat_stream(self, **kwargs):
        self.received_kwargs = kwargs
        try:
            for chunk in self.yields:
                yield chunk
            # Keep the stream alive so only an explicit aclose() can
            # terminate it; this mirrors a slow LLM that is still
            # streaming when the user hits "stop".
            while True:
                await asyncio.sleep(0)
                yield StreamChunk(content="")
        finally:
            self.gen_aclose_called = True


class _FakeRegistry:
    def get_all_openai_schemas(self):
        return []


def test_agent_loop_does_not_leak_stop_requested_into_chat_stream_kwargs():
    """The SDK boundary is stop-agnostic. Any kwargs reaching
    ``chat_stream`` must not mention ``stop_requested``.
    """

    client = _RecordingStreamClient()
    # Stop signals arriving mid-stream; initial state is "running" so
    # the pre-stream guard doesn't short-circuit the call.
    stop_state = {"requested": False}
    loop_obj = AgentLoop(
        client=client,
        registry=_FakeRegistry(),
        context=None,
        model="test-model",
        stop_requested=lambda: stop_state["requested"],
    )

    async def _on_event(event_type, data):
        if event_type == "stream_chunk":
            stop_state["requested"] = True

    async def _run():
        try:
            await loop_obj._stream_llm_response([], [], _on_event, step_index=1)
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())

    assert "stop_requested" not in client.received_kwargs, (
        "AgentLoop must not forward stop_requested into chat_stream kwargs; "
        f"leaked keys: {sorted(client.received_kwargs.keys())}"
    )


def test_agent_loop_closes_stream_deterministically_when_stop_requested():
    """On stop, ``AgentLoop`` must ``aclose()`` the underlying
    generator synchronously (observed through ``finally``), then
    propagate ``CancelledError`` so the outer loop can unwind.
    """

    client = _RecordingStreamClient()

    stop_state = {"requested": False}

    def _stop_requested() -> bool:
        return stop_state["requested"]

    loop_obj = AgentLoop(
        client=client,
        registry=_FakeRegistry(),
        context=None,
        model="test-model",
        stop_requested=_stop_requested,
    )

    # Flip the flag once the first content chunk has been observed.
    async def _on_event(event_type, data):
        if event_type == "stream_chunk" and data.get("chunk_type") == "content":
            stop_state["requested"] = True

    async def _run():
        await loop_obj._stream_llm_response([], [], _on_event, step_index=1)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run())

    assert client.gen_aclose_called is True, (
        "AgentLoop must close chat_stream via aclose(); relying on GC "
        "causes 'RuntimeError: no running event loop' in production."
    )
