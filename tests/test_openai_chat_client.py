import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from infrastructure.llm_adapters.base_client import (
    APIError,
    AuthError,
    BaseLLMClient,
    ContextOverflowError,
    RateLimitError,
    ResponseParseError,
)
from infrastructure.llm_adapters.openai_chat_client import OpenAIChatClient
from infrastructure.llm_adapters.sse import iter_sse_events


class _SplitByteStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[str]):
        self.chunks = [chunk.encode("utf-8") for chunk in chunks]
        self.consumed = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.consumed += 1
            yield chunk

    async def aclose(self) -> None:
        return None


async def _install_transport(
    client: OpenAIChatClient,
    handler,
) -> None:
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url=f"{client.base_url.rstrip('/')}/",
        headers={"Authorization": f"Bearer {client.api_key}"},
        transport=httpx.MockTransport(handler),
        timeout=client.timeout,
    )


def _sse(payload: dict[str, Any] | str) -> str:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return f"data: {data}\n\n"


def _function_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read one project file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }


@pytest.mark.parametrize(
    ("provider_id", "thinking", "effort", "expected", "absent"),
    [
        (
            "qwen",
            True,
            None,
            {"enable_thinking": True, "preserve_thinking": False},
            {"thinking", "reasoning_effort"},
        ),
        (
            "deepseek",
            True,
            "max",
            {"thinking": {"type": "enabled"}, "reasoning_effort": "max"},
            {"enable_thinking", "preserve_thinking"},
        ),
        (
            "kimi",
            True,
            "high",
            {"reasoning_effort": "high"},
            {"thinking", "enable_thinking", "preserve_thinking"},
        ),
        (
            "opencode",
            True,
            None,
            {"reasoning_effort": "high"},
            {"thinking", "enable_thinking", "preserve_thinking"},
        ),
        (
            "siliconflow",
            True,
            None,
            {"enable_thinking": True},
            {"thinking", "reasoning_effort", "preserve_thinking"},
        ),
        (
            "custom",
            True,
            "max",
            {},
            {"thinking", "enable_thinking", "reasoning_effort", "preserve_thinking"},
        ),
    ],
)
def test_provider_policy_emits_only_explicit_wire_fields(
    provider_id: str,
    thinking: bool,
    effort: str | None,
    expected: dict[str, Any],
    absent: set[str],
) -> None:
    client = OpenAIChatClient(
        provider_id,
        "secret",
        "https://provider.test/v1",
        "curated-model",
    )
    body = client.build_request_body(
        [{"role": "user", "content": "hello"}],
        thinking=thinking,
        reasoning_effort=effort,
    )

    for key, value in expected.items():
        assert body[key] == value
    for key in absent:
        assert key not in body
    asyncio.run(client.close())


def test_zhipu_tool_thinking_uses_preserved_interleaved_state() -> None:
    client = OpenAIChatClient(
        "zhipu",
        "secret",
        "https://provider.test/v4",
        "glm",
    )
    body = client.build_request_body(
        [{"role": "user", "content": "inspect"}],
        tools=[_function_tool()],
        thinking=True,
    )
    assert body["thinking"] == {"type": "enabled", "clear_thinking": False}
    assert "enable_thinking" not in body
    assert "reasoning_effort" not in body
    asyncio.run(client.close())


@pytest.mark.parametrize(
    ("provider_id", "model", "thinking", "expected"),
    [
        (
            "zhipu",
            "glm-5.3",
            False,
            {"thinking": {"type": "enabled"}, "reasoning_effort": "low"},
        ),
        (
            "zhipu",
            "glm-5.3",
            True,
            {"thinking": {"type": "enabled"}, "reasoning_effort": "high"},
        ),
        ("kimi", "kimi-k3", False, {"reasoning_effort": "low"}),
        ("kimi", "kimi-k3", True, {"reasoning_effort": "high"}),
    ],
)
def test_always_reasoning_models_map_the_toggle_to_low_or_high_effort(
    provider_id: str,
    model: str,
    thinking: bool,
    expected: dict[str, Any],
) -> None:
    client = OpenAIChatClient(
        provider_id,
        "secret",
        "https://provider.test/v1",
        model,
    )

    body = client.build_request_body(
        [{"role": "user", "content": "hello"}],
        thinking=thinking,
    )

    for key, value in expected.items():
        assert body[key] == value
    asyncio.run(client.close())


@pytest.mark.parametrize(
    ("model", "expected"),
    [("qwen3.8-max", True), ("qwen3.7-flash", False)],
)
def test_qwen_preserves_reasoning_only_for_the_current_max_model(
    model: str,
    expected: bool,
) -> None:
    client = OpenAIChatClient(
        "qwen",
        "secret",
        "https://provider.test/v1",
        model,
    )

    body = client.build_request_body(
        [{"role": "user", "content": "hello"}],
        thinking=True,
    )

    assert body["preserve_thinking"] is expected
    assert "reasoning_effort" not in body
    asyncio.run(client.close())


def test_canonical_messages_keep_images_and_only_standard_continuation_fields() -> None:
    client = OpenAIChatClient(
        "qwen",
        "secret",
        "https://provider.test/v1",
        "vision-model",
    )
    body = client.build_request_body(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "inspect"},
                    {
                        "type": "image",
                        "url": "data:image/png;base64,AAAA",
                        "detail": "high",
                    },
                ],
            },
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "unmodified reasoning",
                "tool_calls": [
                    {
                        "index": 2,
                        "id": "call-2",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": {"path": "main.cir"},
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-2",
                "name": "read_file",
                "content": "R1 in out 1k",
            },
        ]
    )

    image = body["messages"][0]["content"][1]
    assert image == {
        "type": "image_url",
        "image_url": {
            "url": "data:image/png;base64,AAAA",
            "detail": "high",
        },
    }
    assistant = body["messages"][1]
    assert assistant["reasoning_content"] == "unmodified reasoning"
    assert "provider_state" not in assistant
    assert "index" not in assistant["tool_calls"][0]
    assert assistant["tool_calls"][0]["function"]["arguments"] == '{"path":"main.cir"}'
    asyncio.run(client.close())


def test_complete_accumulates_reasoning_multiple_tools_and_usage() -> None:
    chunks = [
        _sse(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "reasoning_content": "plan ",
                        },
                        "finish_reason": None,
                    }
                ]
            }
        ),
        _sse(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-a",
                                    "type": "function",
                                    "function": {"name": "read_file", "arguments": '{"path":'},
                                },
                                {
                                    "index": 1,
                                    "id": "call-b",
                                    "type": "function",
                                    "function": {"name": "grep_search", "arguments": '{"query":'},
                                },
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            }
        ),
        _sse(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "content": "answer",
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": '"main.cir"}'}},
                                {"index": 1, "function": {"arguments": '"V(out)"}'}},
                            ],
                        },
                        "finish_reason": None,
                    }
                ]
            }
        ),
        _sse(
            {
                "choices": [
                    {"index": 0, "delta": {}, "finish_reason": "tool_calls"}
                ]
            }
        ),
        _sse(
            {
                "choices": [],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        ),
        _sse("[DONE]"),
    ]
    stream = _SplitByteStream(chunks)
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            stream=stream,
        )

    async def scenario():
        client = OpenAIChatClient(
            "deepseek",
            "secret",
            "https://provider.test/compatible-mode/v1",
            "deepseek-v4-pro",
        )
        await _install_transport(client, handler)
        try:
            return await client.complete(
                [{"role": "user", "content": "inspect"}],
                tools=[_function_tool()],
                thinking=True,
            )
        finally:
            await client.close()

    response = asyncio.run(scenario())

    assert captured["url"] == "https://provider.test/compatible-mode/v1/chat/completions"
    assert captured["body"]["thinking"] == {"type": "enabled"}
    assert response.reasoning_content == "plan "
    assert response.content == "answer"
    assert response.finish_reason == "tool_calls"
    assert response.provider_state is None
    assert response.usage == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }
    assert response.tool_calls == [
        {
            "index": 0,
            "id": "call-a",
            "type": "function",
            "function": {"name": "read_file", "arguments": '{"path":"main.cir"}'},
        },
        {
            "index": 1,
            "id": "call-b",
            "type": "function",
            "function": {"name": "grep_search", "arguments": '{"query":"V(out)"}'},
        },
    ]
    assert stream.consumed == len(chunks), "client returned before consuming [DONE]"


@pytest.mark.parametrize("provider_id", ["kimi", "deepseek", "qwen"])
def test_done_required_providers_reject_eof_after_finish_reason(provider_id: str) -> None:
    stream = _SplitByteStream(
        [
            _sse(
                {
                    "choices": [
                        {"index": 0, "delta": {"content": "partial"}, "finish_reason": "stop"}
                    ]
                }
            )
        ]
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    async def scenario() -> None:
        client = OpenAIChatClient(
            provider_id,
            "secret",
            "https://provider.test/v1",
            "model",
        )
        await _install_transport(client, handler)
        try:
            async for _chunk in client.chat_stream(
                [{"role": "user", "content": "hello"}]
            ):
                pass
        finally:
            await client.close()

    with pytest.raises(ResponseParseError, match=r"\[DONE\]"):
        asyncio.run(scenario())


@pytest.mark.parametrize(
    ("status", "payload", "headers", "error_type"),
    [
        (401, {"error": {"message": "invalid key"}}, {}, AuthError),
        (429, {"error": {"message": "rate limited"}}, {"Retry-After": "7"}, RateLimitError),
        (
            400,
            {"error": {"message": "maximum context length exceeded"}},
            {},
            ContextOverflowError,
        ),
        (500, {"error": {"message": "provider unavailable"}}, {}, APIError),
    ],
)
def test_http_errors_map_to_canonical_exceptions(
    status: int,
    payload: dict[str, Any],
    headers: dict[str, str],
    error_type: type[Exception],
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload, headers=headers)

    async def scenario() -> None:
        client = OpenAIChatClient(
            "qwen",
            "secret",
            "https://provider.test/v1",
            "model",
        )
        await _install_transport(client, handler)
        try:
            async for _chunk in client.chat_stream(
                [{"role": "user", "content": "hello"}]
            ):
                pass
        finally:
            await client.close()

    with pytest.raises(error_type) as raised:
        asyncio.run(scenario())
    if status == 429:
        assert raised.value.retry_after == 7


def test_sse_parser_dispatches_only_complete_multiline_events() -> None:
    async def source():
        yield ": keep-alive\r\ndata: {\"part\":"
        yield " 1}\r\ndata: tail\r\n"
        yield "\r\ndata: [DONE]\n\n"

    async def scenario():
        return [event async for event in iter_sse_events(source())]

    events = asyncio.run(scenario())
    assert [event.data for event in events] == ['{"part": 1}\ntail', "[DONE]"]


def test_contract_is_pure_async_without_legacy_chat_or_destructor() -> None:
    assert not hasattr(BaseLLMClient, "chat")
    assert "__del__" not in OpenAIChatClient.__dict__
