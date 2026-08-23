"""Contract tests for the native Anthropic Messages adapter."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

import httpx
import pytest

from infrastructure.llm_adapters.anthropic_client import AnthropicClient
from infrastructure.llm_adapters.base_client import APIError, ResponseParseError


def _sse(*events: tuple[str, dict[str, Any]]) -> str:
    return "".join(
        f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
        for event_name, payload in events
    )


async def _install_transport(
    client: AnthropicClient,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    await client.close()
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _client() -> AnthropicClient:
    return AnthropicClient(
        provider_id="anthropic",
        api_key="test-key",
        base_url="https://api.anthropic.com/v1/",
        model="claude-sonnet-5",
    )


def test_complete_uses_native_messages_headers_images_usage_and_text() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        stream = _sse(
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_1",
                        "type": "message",
                        "role": "assistant",
                        "content": [],
                        "model": "claude-sonnet-5",
                        "stop_reason": None,
                        "usage": {
                            "input_tokens": 2,
                            "cache_creation_input_tokens": 1,
                            "cache_read_input_tokens": 3,
                            "output_tokens": 0,
                        },
                    },
                },
            ),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Hello"},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 4},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=stream,
        )

    async def run():
        client = _client()
        await _install_transport(client, handler)
        try:
            return await client.complete(
                messages=[
                    {"role": "system", "content": "Be precise."},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Inspect this."},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/png;base64,QUJD"
                                },
                            },
                        ],
                    },
                ],
                thinking=False,
            )
        finally:
            await client.close()

    response = asyncio.run(run())

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "test-key"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    body = captured["body"]
    assert body["system"] == "Be precise."
    assert body["model"] == "claude-sonnet-5"
    assert body["max_tokens"] == 8192
    assert body["stream"] is True
    assert body["thinking"] == {"type": "disabled"}
    assert body["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Inspect this."},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "QUJD",
                    },
                },
            ],
        }
    ]
    assert response.content == "Hello"
    assert response.finish_reason == "stop"
    assert response.usage == {
        "prompt_tokens": 6,
        "completion_tokens": 4,
        "total_tokens": 10,
        "cached_tokens": 3,
    }
    assert response.provider_state == {
        "protocol": "anthropic_messages",
        "content": [{"type": "text", "text": "Hello"}],
    }


def test_tools_thinking_signature_and_error_results_round_trip_unchanged() -> None:
    requests: list[dict[str, Any]] = []

    first_stream = _sse(
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "content": [],
                    "usage": {"input_tokens": 10, "output_tokens": 0},
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "thinking",
                    "thinking": "",
                    "signature": "",
                },
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "plan"},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "sig-1"},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {
                    "type": "redacted_thinking",
                    "data": "opaque-data",
                },
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 1}),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 2,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_read",
                    "name": "read_file",
                    "input": {},
                },
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 2,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"path":',
                },
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 2,
                "delta": {"type": "input_json_delta", "partial_json": '"a.cir"}'},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 2}),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 3,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_grep",
                    "name": "grep_search",
                    "input": {},
                },
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 3,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"query":"V(out)"}',
                },
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 3}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {"output_tokens": 12},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    )
    second_stream = _sse(
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "content": [],
                    "usage": {"input_tokens": 20, "output_tokens": 0},
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Recovered"},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 2},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        content = first_stream if len(requests) == 1 else second_stream
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=content,
        )

    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "grep_search",
                "description": "Search text",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
    ]

    async def run():
        client = _client()
        await _install_transport(client, handler)
        try:
            first_chunks = [
                chunk
                async for chunk in client.chat_stream(
                    messages=[{"role": "user", "content": "Inspect"}],
                    tools=tools,
                    thinking=True,
                )
            ]
            final = first_chunks[-1]
            second = await client.complete(
                messages=[
                    {"role": "user", "content": "Inspect"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": final.tool_calls,
                        "provider_state": final.provider_state,
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "toolu_read",
                        "name": "read_file",
                        "content": "file contents",
                        "is_error": False,
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "toolu_grep",
                        "name": "grep_search",
                        "content": "search failed",
                        "is_error": True,
                    },
                    {"role": "system", "content": "Recover from tool errors."},
                ],
                tools=tools,
                thinking=True,
            )
            return first_chunks, final, second
        finally:
            await client.close()

    first_chunks, final, second = asyncio.run(run())

    assert "".join(chunk.reasoning_content or "" for chunk in first_chunks) == "plan"
    assert final.finish_reason == "tool_calls"
    assert final.tool_calls == [
        {
            "id": "toolu_read",
            "type": "function",
            "function": {"name": "read_file", "arguments": {"path": "a.cir"}},
            "index": 2,
        },
        {
            "id": "toolu_grep",
            "type": "function",
            "function": {"name": "grep_search", "arguments": {"query": "V(out)"}},
            "index": 3,
        },
    ]
    expected_native_blocks = [
        {"type": "thinking", "thinking": "plan", "signature": "sig-1"},
        {"type": "redacted_thinking", "data": "opaque-data"},
        {
            "type": "tool_use",
            "id": "toolu_read",
            "name": "read_file",
            "input": {"path": "a.cir"},
        },
        {
            "type": "tool_use",
            "id": "toolu_grep",
            "name": "grep_search",
            "input": {"query": "V(out)"},
        },
    ]
    assert final.provider_state == {
        "protocol": "anthropic_messages",
        "content": expected_native_blocks,
    }

    first_request, continuation_request = requests
    assert first_request["thinking"] == {
        "type": "adaptive",
        "display": "summarized",
    }
    assert first_request["tools"][0] == {
        "name": "read_file",
        "description": "Read a file",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    }
    assert continuation_request["thinking"] == {
        "type": "adaptive",
        "display": "summarized",
    }
    assert continuation_request["system"] == "Recover from tool errors."
    assert continuation_request["messages"][1] == {
        "role": "assistant",
        "content": expected_native_blocks,
    }
    assert continuation_request["messages"][2] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_read",
                "content": "file contents",
                "is_error": False,
            },
            {
                "type": "tool_result",
                "tool_use_id": "toolu_grep",
                "content": "search failed",
                "is_error": True,
            },
        ],
    }
    assert all(
        "name" not in block
        for block in continuation_request["messages"][2]["content"]
    )
    assert second.content == "Recovered"


def test_provider_state_protocol_is_validated_before_content_is_read() -> None:
    client = _client()
    try:
        with pytest.raises(APIError, match="protocol"):
            client._build_request_body(
                messages=[
                    {"role": "user", "content": "hello"},
                    {
                        "role": "assistant",
                        "provider_state": {
                            "protocol": "openai_chat",
                            "content": [{"type": "text", "text": "wrong"}],
                        },
                    },
                ],
                model=None,
                tools=None,
                thinking=False,
            )
    finally:
        asyncio.run(client.close())


def test_sonnet_5_explicitly_disables_default_thinking() -> None:
    client = AnthropicClient(
        provider_id="anthropic",
        api_key="test-key",
        base_url="https://api.anthropic.com/v1",
        model="claude-sonnet-5",
    )
    try:
        body = client._build_request_body(
            messages=[{"role": "user", "content": "hello"}],
            model=None,
            tools=None,
            thinking=False,
        )
        assert body["thinking"] == {"type": "disabled"}
    finally:
        asyncio.run(client.close())


@pytest.mark.parametrize(
    ("thinking", "display", "effort"),
    [
        (False, "omitted", "low"),
        (True, "summarized", "high"),
    ],
)
def test_fable_5_always_uses_adaptive_thinking_and_maps_effort(
    thinking: bool,
    display: str,
    effort: str,
) -> None:
    client = AnthropicClient(
        provider_id="anthropic",
        api_key="test-key",
        base_url="https://api.anthropic.com/v1",
        model="claude-fable-5",
    )
    try:
        body = client._build_request_body(
            messages=[{"role": "user", "content": "hello"}],
            model=None,
            tools=None,
            thinking=thinking,
        )
        assert body["thinking"] == {
            "type": "adaptive",
            "display": display,
        }
        assert body["output_config"] == {"effort": effort}
    finally:
        asyncio.run(client.close())


@pytest.mark.parametrize("model", ["claude-opus-4-8", "claude-sonnet-4-6"])
def test_previous_claude_models_omit_thinking_when_disabled(model: str) -> None:
    client = AnthropicClient(
        provider_id="anthropic",
        api_key="test-key",
        base_url="https://api.anthropic.com/v1",
        model=model,
    )
    try:
        disabled_body = client._build_request_body(
            messages=[{"role": "user", "content": "hello"}],
            model=None,
            tools=None,
            thinking=False,
        )
        enabled_body = client._build_request_body(
            messages=[{"role": "user", "content": "hello"}],
            model=None,
            tools=None,
            thinking=True,
        )
        assert "thinking" not in disabled_body
        assert enabled_body["thinking"] == {
            "type": "adaptive",
            "display": "summarized",
        }
    finally:
        asyncio.run(client.close())


def test_opencode_messages_does_not_infer_native_fable_contract() -> None:
    client = AnthropicClient(
        provider_id="opencode",
        api_key="test-key",
        base_url="https://gateway.example.test/zen/v1/",
        model="claude-fable-5",
    )
    try:
        body = client._build_request_body(
            messages=[{"role": "user", "content": "hello"}],
            model=None,
            tools=None,
            thinking=False,
        )
        assert client._messages_url() == "https://gateway.example.test/zen/v1/messages"
        assert body["model"] == "claude-fable-5"
        assert body["max_tokens"] == 8192
        assert "thinking" not in body
        assert "output_config" not in body
        enabled_body = client._build_request_body(
            messages=[{"role": "user", "content": "hello"}],
            model=None,
            tools=None,
            thinking=True,
        )
        assert enabled_body["thinking"] == {
            "type": "adaptive",
            "display": "summarized",
        }
        assert "output_config" not in enabled_body
    finally:
        asyncio.run(client.close())


def test_sse_event_error_raises_api_error_even_after_http_200() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse(
                (
                    "error",
                    {
                        "type": "error",
                        "error": {
                            "type": "overloaded_error",
                            "message": "provider overloaded",
                        },
                        "request_id": "req_error",
                    },
                )
            ),
        )

    async def run() -> None:
        client = _client()
        await _install_transport(client, handler)
        try:
            async for _ in client.chat_stream(
                messages=[{"role": "user", "content": "hello"}]
            ):
                pass
        finally:
            await client.close()

    with pytest.raises(APIError, match="provider overloaded"):
        asyncio.run(run())


def test_stream_eof_without_message_stop_is_a_parse_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse(
                (
                    "message_start",
                    {
                        "type": "message_start",
                        "message": {
                            "content": [],
                            "usage": {"input_tokens": 1, "output_tokens": 0},
                        },
                    },
                ),
                (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "text", "text": ""},
                    },
                ),
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": "partial"},
                    },
                ),
                (
                    "content_block_stop",
                    {"type": "content_block_stop", "index": 0},
                ),
            ),
        )

    received = []

    async def run() -> None:
        client = _client()
        await _install_transport(client, handler)
        try:
            async for chunk in client.chat_stream(
                messages=[{"role": "user", "content": "hello"}]
            ):
                received.append(chunk)
        finally:
            await client.close()

    with pytest.raises(ResponseParseError, match="message_stop"):
        asyncio.run(run())
    assert "".join(chunk.content or "" for chunk in received) == "partial"
    assert not any(chunk.is_finished for chunk in received)
