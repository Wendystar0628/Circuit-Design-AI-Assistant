"""Focused contract tests for the native Gemini GenerateContent adapter."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from typing import Any

import pytest

from infrastructure.llm_adapters.base_client import (
    APIError,
    AuthError,
    ResponseParseError,
)
from infrastructure.llm_adapters.gemini_client import GeminiClient


class _FakeResponse:
    def __init__(
        self,
        lines: list[str],
        *,
        status_code: int = 200,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._lines = lines
        self._body = body
        self.closed = False

    async def aread(self) -> bytes:
        return self._body

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _ResponseContext:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response

    async def __aenter__(self) -> _FakeResponse:
        return self.response

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.response.closed = True
        return False


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def stream(self, method: str, url: str, *, json: dict[str, Any]):
        self.requests.append({"method": method, "url": url, "json": json})
        return _ResponseContext(self.response)


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}"


def _client(response: _FakeResponse) -> tuple[GeminiClient, _FakeAsyncClient]:
    client = GeminiClient(
        provider_id="gemini",
        api_key="test-key",
        base_url="https://proxy.example.test/custom/v1",
        model="gemini-3.7-flash",
    )
    fake_transport = _FakeAsyncClient(response)
    client._create_async_client = lambda: fake_transport  # type: ignore[method-assign]
    return client, fake_transport


def _collect(client: GeminiClient, messages, **kwargs):
    async def run():
        return [
            chunk
            async for chunk in client.chat_stream(messages=messages, **kwargs)
        ]

    return asyncio.run(run())


def test_streams_text_usage_and_terminal_native_state_at_eof():
    text_part = {"text": "Hello from Gemini"}
    response = _FakeResponse(
        [
            _sse(
                {
                    "candidates": [
                        {"content": {"role": "model", "parts": [text_part]}}
                    ]
                }
            ),
            "",
            # Deliberately no blank event terminator and no [DONE].  A clean
            # EOF after STOP is Gemini's successful transport completion.
            _sse(
                {
                    "candidates": [{"finishReason": "STOP"}],
                    "usageMetadata": {
                        "promptTokenCount": 3,
                        "candidatesTokenCount": 4,
                        "totalTokenCount": 7,
                        "cachedContentTokenCount": 1,
                        "thoughtsTokenCount": 2,
                    },
                }
            ),
        ]
    )
    client, transport = _client(response)

    chunks = _collect(
        client,
        [
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "Hello"},
        ],
    )

    assert "".join(chunk.content or "" for chunk in chunks) == "Hello from Gemini"
    terminal = chunks[-1]
    assert terminal.is_finished is True
    assert terminal.finish_reason == "stop"
    assert terminal.usage == {
        "prompt_tokens": 3,
        "completion_tokens": 4,
        "total_tokens": 7,
        "cached_tokens": 1,
        "reasoning_tokens": 2,
    }
    assert terminal.provider_state == {
        "protocol": "gemini_generate_content",
        "content": {"role": "model", "parts": [text_part]},
    }
    assert response.closed is True

    request = transport.requests[0]
    assert request["method"] == "POST"
    assert request["url"] == (
        "models/gemini-3.7-flash:streamGenerateContent?alt=sse"
    )
    assert request["json"] == {
        "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
        "systemInstruction": {"parts": [{"text": "You are concise."}]},
        "generationConfig": {
            "thinkingConfig": {"thinkingLevel": "low"}
        },
    }
    assert client.base_url == "https://proxy.example.test/custom/v1/"
    assert client._get_headers() == {
        "Content-Type": "application/json",
        "x-goog-api-key": "test-key",
    }


@pytest.mark.parametrize(
    ("provider_id", "model", "thinking", "expected_thinking_config"),
    [
        (
            "gemini",
            "gemini-3.1-pro-preview",
            False,
            {"thinkingLevel": "low"},
        ),
        (
            "gemini",
            "gemini-3.1-pro-preview",
            True,
            {"thinkingLevel": "high", "includeThoughts": True},
        ),
        ("gemini", "gemini-3.7-flash", False, {"thinkingLevel": "low"}),
        (
            "gemini",
            "gemini-3.7-flash",
            True,
            {"thinkingLevel": "high", "includeThoughts": True},
        ),
        ("gemini", "gemini-3.6-flash", False, {"thinkingLevel": "low"}),
        (
            "gemini",
            "gemini-3.6-flash",
            True,
            {"thinkingLevel": "high", "includeThoughts": True},
        ),
        ("gemini", "gemini-2.5-pro", False, {"thinkingBudget": 1_024}),
        (
            "gemini",
            "gemini-2.5-pro",
            True,
            {"thinkingBudget": 24_576, "includeThoughts": True},
        ),
        ("opencode", "vendor/custom-model", False, None),
        (
            "opencode",
            "vendor/custom-model",
            True,
            {"thinkingLevel": "high", "includeThoughts": True},
        ),
    ],
)
def test_builds_exact_thinking_request_for_model_contract(
    provider_id,
    model,
    thinking,
    expected_thinking_config,
):
    client = GeminiClient(
        provider_id=provider_id,
        api_key="test-key",
        base_url="https://proxy.example.test/custom/v1",
        model="gemini-3.7-flash",
    )

    body = client._build_request_body(
        [{"role": "user", "content": "Think carefully"}],
        tools=None,
        thinking=thinking,
        model=model,
    )

    expected_body = {
        "contents": [
            {"role": "user", "parts": [{"text": "Think carefully"}]}
        ]
    }
    if expected_thinking_config is not None:
        expected_body["generationConfig"] = {
            "thinkingConfig": expected_thinking_config
        }
    assert body == expected_body
    if provider_id == "opencode":
        assert client._normalize_model(model) == "vendor/custom-model"


def test_function_call_thought_signature_round_trips_in_native_order():
    native_parts = [
        {
            "text": "I should inspect the circuit.",
            "thought": True,
            "thoughtSignature": "thought-signature",
        },
        {
            "functionCall": {
                "id": "call-42",
                "name": "read_file",
                "args": {"path": "main.cir"},
            },
            "thoughtSignature": "function-signature",
        },
        {"text": "", "thoughtSignature": "ordered-empty-part-signature"},
    ]
    response = _FakeResponse(
        [
            _sse(
                {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": native_parts,
                            },
                            "finishReason": "STOP",
                        }
                    ]
                }
            )
        ]
    )
    client, _ = _client(response)

    chunks = _collect(
        client,
        [{"role": "user", "content": "Inspect main.cir"}],
        thinking=True,
    )

    assert "".join(chunk.reasoning_content or "" for chunk in chunks) == (
        "I should inspect the circuit."
    )
    terminal = chunks[-1]
    assert terminal.finish_reason == "tool_calls"
    assert terminal.tool_calls == [
        {
            "id": "call-42",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": {"path": "main.cir"},
            },
        }
    ]
    assert terminal.provider_state == {
        "protocol": "gemini_generate_content",
        "content": {"role": "model", "parts": native_parts},
    }

    provider_state = deepcopy(terminal.provider_state)
    request = client._build_request_body(
        [
            {"role": "user", "content": "Inspect main.cir"},
            {
                "role": "assistant",
                "content": "this lossy field must not replace native parts",
                "tool_calls": terminal.tool_calls,
                "provider_state": provider_state,
            },
            {
                "role": "tool",
                "tool_call_id": "call-42",
                "name": "read_file",
                "content": "* resistor network\n.end",
            },
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a project file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            }
        ],
        thinking=True,
    )

    assert request["contents"][1] == {
        "role": "model",
        "parts": native_parts,
    }
    assert request["contents"][2] == {
        "role": "user",
        "parts": [
            {
                "functionResponse": {
                    "name": "read_file",
                    "response": {"result": "* resistor network\n.end"},
                    "id": "call-42",
                }
            }
        ],
    }
    assert request["tools"] == [
        {
            "functionDeclarations": [
                {
                    "name": "read_file",
                    "description": "Read a project file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                }
            ]
        }
    ]
    assert request["generationConfig"] == {
        "thinkingConfig": {
            "thinkingLevel": "high",
            "includeThoughts": True,
        }
    }
    assert provider_state == terminal.provider_state


def test_converts_canonical_image_data_uri_to_inline_data():
    response = _FakeResponse([])
    client, _ = _client(response)

    body = client._build_request_body(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is shown?"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,iVBORw0KGgo="
                        },
                    },
                ],
            }
        ],
        tools=None,
        thinking=False,
    )

    assert body == {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": "What is shown?"},
                    {
                        "inlineData": {
                            "mimeType": "image/png",
                            "data": "iVBORw0KGgo=",
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "thinkingConfig": {"thinkingLevel": "low"}
        },
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"promptFeedback": {"blockReason": "SAFETY"}},
        {
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "partial"}]},
                    "finishReason": "SAFETY",
                }
            ]
        },
    ],
)
def test_blocked_2xx_stream_fails_closed(payload):
    response = _FakeResponse([_sse(payload)])
    client, _ = _client(response)

    with pytest.raises(APIError, match="blocked|SAFETY|normally"):
        _collect(client, [{"role": "user", "content": "unsafe prompt"}])
    assert response.closed is True


def test_top_level_2xx_error_is_not_treated_as_a_stream_chunk():
    response = _FakeResponse(
        [
            _sse(
                {
                    "error": {
                        "code": 400,
                        "status": "INVALID_ARGUMENT",
                        "message": "API key not valid",
                    }
                }
            )
        ]
    )
    client, _ = _client(response)

    with pytest.raises(AuthError, match="API key not valid"):
        _collect(client, [{"role": "user", "content": "hello"}])


def test_eof_without_stop_finish_reason_is_incomplete():
    response = _FakeResponse(
        [
            _sse(
                {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [{"text": "partial"}],
                            }
                        }
                    ]
                }
            )
        ]
    )
    client, _ = _client(response)

    with pytest.raises(ResponseParseError, match="before a STOP"):
        _collect(client, [{"role": "user", "content": "hello"}])
    assert response.closed is True
