import asyncio
import json
from typing import Any

import httpx
import pytest

from infrastructure.llm_adapters.base_client import (
    APIError,
    AuthError,
    ContextOverflowError,
    RateLimitError,
    ResponseParseError,
)
from infrastructure.llm_adapters.openai_responses_client import (
    OpenAIResponsesClient,
)


def _sse(event_type: str, payload: dict[str, Any]) -> str:
    return (
        f"event: {event_type}\n"
        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    )


def _stream_client(
    body: str,
    *,
    provider_id: str = "openai",
    base_url: str = "https://provider.test/custom/v1",
    model: str = "test-model",
    status_code: int = 200,
    response_headers: dict[str, str] | None = None,
):
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            status_code,
            headers=response_headers,
            content=body.encode("utf-8"),
            request=request,
        )

    client = OpenAIResponsesClient(
        provider_id=provider_id,
        api_key="secret-key",
        base_url=base_url,
        model=model,
    )
    transport = httpx.MockTransport(handler)
    client._create_async_client = lambda: httpx.AsyncClient(
        base_url=client.base_url,
        headers=client._get_headers(),
        transport=transport,
    )
    return client, captured


def _collect(client: OpenAIResponsesClient, **kwargs: Any):
    async def run():
        return [chunk async for chunk in client.chat_stream(**kwargs)]

    return asyncio.run(run())


def test_responses_stream_maps_messages_images_tools_text_usage_and_terminal_state():
    raw_output = [
        {
            "id": "msg_1",
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": "hello",
                    "annotations": [],
                }
            ],
        }
    ]
    usage = {
        "input_tokens": 7,
        "input_tokens_details": {"cached_tokens": 3, "cache_write_tokens": 2},
        "output_tokens": 2,
        "output_tokens_details": {"reasoning_tokens": 1},
        "total_tokens": 9,
    }
    stream = "".join(
        [
            _sse(
                "response.output_text.delta",
                {"type": "response.output_text.delta", "delta": "hel"},
            ),
            _sse(
                "response.output_text.delta",
                {"type": "response.output_text.delta", "delta": "lo"},
            ),
            _sse(
                "response.completed",
                {
                    "type": "response.completed",
                    "response": {
                        "status": "completed",
                        "output": raw_output,
                        "usage": usage,
                    },
                },
            ),
        ]
    )
    client, captured = _stream_client(stream)

    chunks = _collect(
        client,
        messages=[
            {"role": "system", "content": "Be precise."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "inspect"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,AAAA",
                            "detail": "high",
                        },
                    },
                ],
            },
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "Look something up",
                    "parameters": {
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                        "required": ["q"],
                    },
                    "strict": True,
                },
            }
        ],
        thinking=False,
    )

    assert "".join(chunk.content or "" for chunk in chunks) == "hello"
    terminal = chunks[-1]
    assert terminal.is_finished is True
    assert terminal.finish_reason == "stop"
    assert terminal.usage == {
        "prompt_tokens": 7,
        "completion_tokens": 2,
        "total_tokens": 9,
        "cached_tokens": 3,
        "cache_write_tokens": 2,
        "reasoning_tokens": 1,
    }
    assert terminal.provider_state == {
        "protocol": "openai_responses",
        "assistant_output": raw_output,
    }

    assert captured["url"] == "https://provider.test/custom/v1/responses"
    request_body = captured["body"]
    assert request_body["instructions"] == "Be precise."
    assert request_body["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "inspect"},
                {
                    "type": "input_image",
                    "image_url": "data:image/png;base64,AAAA",
                    "detail": "high",
                },
            ],
        }
    ]
    assert request_body["tools"] == [
        {
            "type": "function",
            "name": "lookup",
            "description": "Look something up",
            "parameters": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
            },
            "strict": True,
        }
    ]
    assert request_body["reasoning"] == {"effort": "low"}
    assert request_body["stream"] is True
    assert "messages" not in request_body
    assert "temperature" not in request_body
    assert "stream_options" not in request_body
    assert "thinking" not in request_body
    assert "store" not in request_body
    assert "include" not in request_body


def test_gpt_5_5_pro_uses_async_non_stream_wire_and_yields_canonical_chunks():
    raw_output = [
        {
            "id": "rs_pro",
            "type": "reasoning",
            "status": "completed",
            "summary": [
                {"type": "summary_text", "text": "Need the project data."}
            ],
        },
        {
            "id": "msg_pro",
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": "I will inspect it.",
                    "annotations": [],
                }
            ],
        },
        {
            "id": "fc_pro",
            "type": "function_call",
            "status": "completed",
            "call_id": "call_pro",
            "name": "read_file",
            "arguments": '{"path":"design.cir"}',
        },
    ]
    payload = {
        "id": "resp_pro",
        "object": "response",
        "status": "completed",
        "output": raw_output,
        "usage": {
            "input_tokens": 20,
            "output_tokens": 8,
            "total_tokens": 28,
        },
    }
    client, captured = _stream_client(
        json.dumps(payload),
        model="gpt-5.5-pro",
    )

    chunks = _collect(
        client,
        messages=[{"role": "user", "content": "inspect the project"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            }
        ],
        thinking=False,
    )

    assert captured["body"]["stream"] is False
    assert captured["body"]["reasoning"] == {"effort": "medium"}
    assert chunks[0].content == "I will inspect it."
    assert chunks[0].reasoning_content == "Need the project data."
    terminal = chunks[-1]
    assert terminal.is_finished is True
    assert terminal.finish_reason == "tool_calls"
    assert terminal.tool_calls == [
        {
            "id": "call_pro",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": '{"path":"design.cir"}',
            },
        }
    ]
    assert terminal.usage == {
        "prompt_tokens": 20,
        "completion_tokens": 8,
        "total_tokens": 28,
    }
    assert terminal.provider_state == {
        "protocol": "openai_responses",
        "assistant_output": raw_output,
    }

    high_effort_body = client._build_request_body(
        [{"role": "user", "content": "hard problem"}],
        model="gpt-5.5-pro",
        tools=None,
        thinking=True,
        reasoning_effort=None,
        stream=False,
    )
    assert high_effort_body["reasoning"] == {"effort": "high"}

    from infrastructure.llm_adapters.provider_catalog import get_model

    catalog_model = get_model("openai", "gpt-5.5-pro")
    assert catalog_model is not None
    assert catalog_model.streaming is False


def test_gpt_5_5_pro_rejects_unsupported_reasoning_effort_before_http():
    client, _ = _stream_client("", model="gpt-5.5-pro")

    with pytest.raises(APIError, match="medium, high, or xhigh"):
        client._build_request_body(
            [{"role": "user", "content": "hello"}],
            model="gpt-5.5-pro",
            tools=None,
            thinking=False,
            reasoning_effort="low",
            stream=False,
        )


def test_responses_tool_roundtrip_preserves_raw_output_and_returns_call_id():
    raw_reasoning = {
        "id": "rs_1",
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": "Need a lookup."}],
    }
    raw_call = {
        "id": "fc_1",
        "type": "function_call",
        "status": "completed",
        "call_id": "call_1",
        "name": "lookup",
        "arguments": '{"q":"value"}',
    }
    raw_output = [raw_reasoning, raw_call]
    stream = "".join(
        [
            _sse(
                "response.output_item.added",
                {
                    "type": "response.output_item.added",
                    "output_index": 1,
                    "item": {
                        "id": "fc_1",
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "lookup",
                        "arguments": "",
                    },
                },
            ),
            _sse(
                "response.function_call_arguments.delta",
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "fc_1",
                    "output_index": 1,
                    "delta": '{"q":',
                },
            ),
            _sse(
                "response.function_call_arguments.delta",
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "fc_1",
                    "output_index": 1,
                    "delta": '"value"}',
                },
            ),
            _sse(
                "response.function_call_arguments.done",
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": "fc_1",
                    "output_index": 1,
                    "name": "lookup",
                    "arguments": '{"q":"value"}',
                },
            ),
            _sse(
                "response.output_item.done",
                {
                    "type": "response.output_item.done",
                    "output_index": 1,
                    "item": raw_call,
                },
            ),
            _sse(
                "response.completed",
                {
                    "type": "response.completed",
                    "response": {
                        "status": "completed",
                        "output": raw_output,
                        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                    },
                },
            ),
        ]
    )
    client, _ = _stream_client(stream)
    chunks = _collect(
        client,
        messages=[{"role": "user", "content": "look it up"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        thinking=True,
    )

    terminal = chunks[-1]
    assert terminal.finish_reason == "tool_calls"
    assert terminal.tool_calls == [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "lookup",
                "arguments": '{"q":"value"}',
            },
        }
    ]
    assert terminal.provider_state["assistant_output"] == raw_output

    continuation = client._build_request_body(
        [
            {"role": "user", "content": "look it up"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": terminal.tool_calls,
                "provider_state": terminal.provider_state,
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "lookup result",
            },
        ],
        model=None,
        tools=None,
        thinking=True,
        reasoning_effort=None,
        stream=True,
    )
    assert continuation["reasoning"] == {"effort": "high"}
    assert continuation["input"] == [
        {
            "role": "user",
            "content": [{"type": "input_text", "text": "look it up"}],
        },
        raw_reasoning,
        raw_call,
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "lookup result",
        },
    ]


def test_xai_uses_the_same_responses_protocol_and_reasoning_events():
    raw_output = [
        {
            "id": "rs_xai",
            "type": "reasoning",
            "status": "completed",
            "summary": [],
            "encrypted_content": "opaque-xai-reasoning",
        },
        {
            "id": "msg_xai",
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "answer"}],
        }
    ]
    stream = "".join(
        [
            _sse(
                "response.reasoning_summary_text.delta",
                {
                    "type": "response.reasoning_summary_text.delta",
                    "delta": "summary ",
                },
            ),
            _sse(
                "response.reasoning_text.delta",
                {"type": "response.reasoning_text.delta", "delta": "detail"},
            ),
            _sse(
                "response.output_text.delta",
                {"type": "response.output_text.delta", "delta": "answer"},
            ),
            _sse(
                "response.completed",
                {
                    "type": "response.completed",
                    "response": {
                        "status": "completed",
                        "output": raw_output,
                        "usage": None,
                    },
                },
            ),
        ]
    )
    client, captured = _stream_client(
        stream,
        provider_id="xai",
        base_url="https://api.x.ai/v1",
    )

    chunks = _collect(
        client,
        messages=[{"role": "user", "content": "question"}],
        thinking=False,
        reasoning_effort="medium",
    )

    assert captured["url"] == "https://api.x.ai/v1/responses"
    assert captured["body"]["reasoning"] == {"effort": "medium"}
    assert captured["body"]["store"] is False
    assert captured["body"]["include"] == ["reasoning.encrypted_content"]
    assert "".join(chunk.reasoning_content or "" for chunk in chunks) == "summary detail"
    assert "".join(chunk.content or "" for chunk in chunks) == "answer"
    assert chunks[-1].provider_state["protocol"] == "openai_responses"
    assert chunks[-1].provider_state["assistant_output"][0]["encrypted_content"] == (
        "opaque-xai-reasoning"
    )


def test_opencode_zen_preserves_its_base_path_for_responses():
    stream = _sse(
        "response.completed",
        {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "output": [
                    {
                        "id": "msg_zen",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "ok"}],
                    }
                ],
                "usage": None,
            },
        },
    )
    client, captured = _stream_client(
        stream,
        provider_id="opencode",
        base_url="https://opencode.ai/zen/v1",
    )

    chunks = _collect(
        client,
        messages=[{"role": "user", "content": "hello"}],
    )

    assert captured["url"] == "https://opencode.ai/zen/v1/responses"
    assert "reasoning" not in captured["body"]
    assert "store" not in captured["body"]
    assert "include" not in captured["body"]
    assert chunks[-1].is_finished is True
    assert chunks[-1].provider_state["protocol"] == "openai_responses"

    thinking_body = client._build_request_body(
        [{"role": "user", "content": "hard problem"}],
        model=None,
        tools=None,
        thinking=True,
        reasoning_effort=None,
        stream=True,
    )
    assert thinking_body["reasoning"] == {"effort": "high"}

    explicit_body = client._build_request_body(
        [{"role": "user", "content": "custom effort"}],
        model=None,
        tools=None,
        thinking=False,
        reasoning_effort="medium",
        stream=True,
    )
    assert explicit_body["reasoning"] == {"effort": "medium"}


def test_responses_refusal_delta_remains_visible_content():
    refusal_text = "I cannot help with that request."
    raw_output = [
        {
            "id": "msg_refusal",
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "refusal", "refusal": refusal_text}],
        }
    ]
    stream = "".join(
        [
            _sse(
                "response.refusal.delta",
                {"type": "response.refusal.delta", "delta": refusal_text},
            ),
            _sse(
                "response.completed",
                {
                    "type": "response.completed",
                    "response": {
                        "status": "completed",
                        "output": raw_output,
                        "usage": None,
                    },
                },
            ),
        ]
    )
    client, _ = _stream_client(stream)

    chunks = _collect(
        client,
        messages=[{"role": "user", "content": "request"}],
    )

    assert "".join(chunk.content or "" for chunk in chunks) == refusal_text
    assert chunks[-1].finish_reason == "stop"


@pytest.mark.parametrize(
    ("status_code", "payload", "headers", "expected_error"),
    [
        (
            401,
            {"error": {"code": "invalid_api_key", "message": "bad key"}},
            None,
            AuthError,
        ),
        (
            429,
            {"error": {"code": "rate_limit_exceeded", "message": "slow down"}},
            {"Retry-After": "3"},
            RateLimitError,
        ),
        (
            400,
            {"error": {"code": "context_length_exceeded", "message": "too long"}},
            None,
            ContextOverflowError,
        ),
        (
            500,
            {"error": {"code": "server_error", "message": "unavailable"}},
            None,
            APIError,
        ),
    ],
)
def test_responses_http_errors_are_typed(
    status_code,
    payload,
    headers,
    expected_error,
):
    client, _ = _stream_client(
        json.dumps(payload),
        status_code=status_code,
        response_headers=headers,
    )

    with pytest.raises(expected_error):
        _collect(client, messages=[{"role": "user", "content": "hello"}])


@pytest.mark.parametrize(
    ("stream", "expected_message"),
    [
        (
            _sse(
                "response.failed",
                {
                    "type": "response.failed",
                    "response": {
                        "status": "failed",
                        "error": {"code": "server_error", "message": "generation failed"},
                    },
                },
            ),
            "generation failed",
        ),
        (
            _sse(
                "response.incomplete",
                {
                    "type": "response.incomplete",
                    "response": {
                        "status": "incomplete",
                        "incomplete_details": {"reason": "max_output_tokens"},
                    },
                },
            ),
            "max_output_tokens",
        ),
    ],
)
def test_responses_non_normal_terminal_events_raise(stream, expected_message):
    client, _ = _stream_client(stream)

    with pytest.raises(APIError, match=expected_message):
        _collect(client, messages=[{"role": "user", "content": "hello"}])


@pytest.mark.parametrize(
    ("payload", "expected_message"),
    [
        (
            {
                "status": "failed",
                "error": {"code": "server_error", "message": "wire failed"},
            },
            "wire failed",
        ),
        (
            {
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
            },
            "max_output_tokens",
        ),
    ],
)
def test_non_streaming_responses_non_normal_statuses_raise(payload, expected_message):
    client, captured = _stream_client(
        json.dumps(payload),
        model="gpt-5.5-pro",
    )

    with pytest.raises(APIError, match=expected_message):
        _collect(client, messages=[{"role": "user", "content": "hello"}])

    assert captured["body"]["stream"] is False


def test_responses_eof_and_chat_done_are_not_success_terminals():
    partial = _sse(
        "response.output_text.delta",
        {"type": "response.output_text.delta", "delta": "partial"},
    )
    client, _ = _stream_client(partial)
    with pytest.raises(ResponseParseError, match="before response.completed"):
        _collect(client, messages=[{"role": "user", "content": "hello"}])

    client, _ = _stream_client("data: [DONE]\n\n")
    with pytest.raises(ResponseParseError, match=r"not \[DONE\]"):
        _collect(client, messages=[{"role": "user", "content": "hello"}])


def test_responses_tool_continuation_requires_protocol_state():
    client, _ = _stream_client("")

    with pytest.raises(ResponseParseError, match="missing assistant provider_state"):
        client._build_request_body(
            [
                {"role": "user", "content": "hello"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "lookup", "arguments": "{}"},
                        }
                    ],
                },
            ],
            model=None,
            tools=None,
            thinking=False,
            reasoning_effort=None,
            stream=True,
        )
