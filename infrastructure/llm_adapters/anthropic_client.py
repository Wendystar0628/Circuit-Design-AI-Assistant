"""Native async adapter for Anthropic's Messages API."""

from __future__ import annotations

import base64
import json
import re
from copy import deepcopy
from typing import Any, AsyncIterator, Mapping, Optional, Sequence

import httpx

from infrastructure.llm_adapters.base_client import (
    APIError,
    AuthError,
    BaseLLMClient,
    CanonicalMessage,
    CanonicalTool,
    ContextOverflowError,
    RateLimitError,
    ResponseParseError,
    StreamChunk,
)


_RUNTIME_MAX_TOKENS = 8192
_ANTHROPIC_FABLE_5_MODEL = "claude-fable-5"
_ANTHROPIC_DISABLEABLE_ADAPTIVE_MODELS = {"claude-sonnet-5"}
_DATA_IMAGE_RE = re.compile(
    r"^data:(?P<media_type>[^;,]+);base64,(?P<data>.+)$",
    re.DOTALL,
)
_SUPPORTED_IMAGE_MEDIA_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}
_USAGE_FIELDS = {
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
}


class AnthropicClient(BaseLLMClient):
    """Anthropic Messages client with no OpenAI-compatible wire layer."""

    DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
    MESSAGES_ENDPOINT = "/messages"
    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(
        self,
        provider_id: str,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60,
    ) -> None:
        super().__init__(
            provider_id=provider_id,
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=timeout,
        )
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout))

    async def close(self) -> None:
        if not self._http.is_closed:
            await self._http.aclose()

    async def chat_stream(
        self,
        messages: Sequence[CanonicalMessage],
        model: Optional[str] = None,
        tools: Optional[Sequence[CanonicalTool]] = None,
        thinking: bool = False,
        *,
        reasoning_effort: Optional[str] = None,
    ) -> AsyncIterator[StreamChunk]:
        # The UI exposes one stable thinking switch. Fable 5 maps that switch
        # to its native effort control in _build_request_body; other Claude
        # models continue to use their documented thinking toggle only.
        del reasoning_effort

        request_body = self._build_request_body(
            messages=messages,
            model=model,
            tools=tools,
            thinking=thinking,
        )
        terminal_observed = False
        raw_usage: dict[str, int] = {}
        blocks: dict[int, dict[str, Any]] = {}
        open_blocks: set[int] = set()
        input_json_fragments: dict[int, list[str]] = {}
        stop_reason: Optional[str] = None

        try:
            async with self._http.stream(
                "POST",
                self._messages_url(),
                headers=self._headers(),
                json=request_body,
            ) as response:
                if response.status_code != 200:
                    await response.aread()
                    self._raise_http_error(response)

                async for event_name, payload_text in self._iter_sse_events(response):
                    payload = self._decode_sse_payload(payload_text)
                    payload_type = str(payload.get("type") or event_name or "")

                    if event_name == "error" or payload_type == "error":
                        self._raise_payload_error(payload)

                    if payload_type == "ping":
                        continue

                    if payload_type == "message_start":
                        message = payload.get("message")
                        if not isinstance(message, Mapping):
                            raise ResponseParseError(
                                "Anthropic message_start is missing its message object"
                            )
                        self._merge_usage(raw_usage, message.get("usage"))
                        continue

                    if payload_type == "content_block_start":
                        index = self._event_index(payload)
                        content_block = payload.get("content_block")
                        if not isinstance(content_block, Mapping):
                            raise ResponseParseError(
                                "Anthropic content_block_start is missing content_block"
                            )
                        if index in blocks:
                            raise ResponseParseError(
                                f"Anthropic content block {index} started more than once"
                            )
                        block = deepcopy(dict(content_block))
                        blocks[index] = block
                        open_blocks.add(index)
                        if block.get("type") == "tool_use":
                            input_json_fragments[index] = []

                        initial_text = block.get("text")
                        if block.get("type") == "text" and isinstance(initial_text, str) and initial_text:
                            yield StreamChunk(content=initial_text)
                        initial_thinking = block.get("thinking")
                        if (
                            block.get("type") == "thinking"
                            and isinstance(initial_thinking, str)
                            and initial_thinking
                        ):
                            yield StreamChunk(reasoning_content=initial_thinking)
                        continue

                    if payload_type == "content_block_delta":
                        index = self._event_index(payload)
                        if index not in open_blocks or index not in blocks:
                            raise ResponseParseError(
                                f"Anthropic delta referenced unopened content block {index}"
                            )
                        delta = payload.get("delta")
                        if not isinstance(delta, Mapping):
                            raise ResponseParseError(
                                "Anthropic content_block_delta is missing delta"
                            )
                        delta_type = delta.get("type")
                        block = blocks[index]

                        if delta_type == "text_delta":
                            text = delta.get("text")
                            if not isinstance(text, str):
                                raise ResponseParseError(
                                    "Anthropic text_delta.text must be a string"
                                )
                            block["text"] = str(block.get("text") or "") + text
                            if text:
                                yield StreamChunk(content=text)
                            continue

                        if delta_type == "thinking_delta":
                            thinking_text = delta.get("thinking")
                            if not isinstance(thinking_text, str):
                                raise ResponseParseError(
                                    "Anthropic thinking_delta.thinking must be a string"
                                )
                            block["thinking"] = (
                                str(block.get("thinking") or "") + thinking_text
                            )
                            if thinking_text:
                                yield StreamChunk(reasoning_content=thinking_text)
                            continue

                        if delta_type == "signature_delta":
                            signature = delta.get("signature")
                            if not isinstance(signature, str):
                                raise ResponseParseError(
                                    "Anthropic signature_delta.signature must be a string"
                                )
                            block["signature"] = (
                                str(block.get("signature") or "") + signature
                            )
                            continue

                        if delta_type == "input_json_delta":
                            partial_json = delta.get("partial_json")
                            if not isinstance(partial_json, str):
                                raise ResponseParseError(
                                    "Anthropic input_json_delta.partial_json must be a string"
                                )
                            input_json_fragments.setdefault(index, []).append(partial_json)
                            continue

                        if delta_type == "citations_delta":
                            citation = delta.get("citation")
                            if not isinstance(citation, Mapping):
                                raise ResponseParseError(
                                    "Anthropic citations_delta.citation must be an object"
                                )
                            citations = block.setdefault("citations", [])
                            if not isinstance(citations, list):
                                raise ResponseParseError(
                                    "Anthropic text block citations must be a list"
                                )
                            citations.append(deepcopy(dict(citation)))
                            continue

                        # Anthropic may add forward-compatible event/delta types.
                        # Unknown deltas are non-textual to this canonical API and
                        # are therefore ignored rather than terminating a stream.
                        continue

                    if payload_type == "content_block_stop":
                        index = self._event_index(payload)
                        if index not in open_blocks or index not in blocks:
                            raise ResponseParseError(
                                f"Anthropic content block {index} stopped before it started"
                            )
                        if blocks[index].get("type") == "tool_use":
                            fragments = "".join(input_json_fragments.pop(index, []))
                            if fragments:
                                try:
                                    tool_input = json.loads(fragments)
                                except json.JSONDecodeError as exc:
                                    raise ResponseParseError(
                                        f"Invalid Anthropic tool input JSON for block {index}: {exc}"
                                    ) from exc
                                if not isinstance(tool_input, dict):
                                    raise ResponseParseError(
                                        "Anthropic tool_use input must decode to an object"
                                    )
                                blocks[index]["input"] = tool_input
                        open_blocks.remove(index)
                        continue

                    if payload_type == "message_delta":
                        delta = payload.get("delta")
                        if not isinstance(delta, Mapping):
                            raise ResponseParseError(
                                "Anthropic message_delta is missing delta"
                            )
                        raw_stop_reason = delta.get("stop_reason")
                        if raw_stop_reason is not None:
                            stop_reason = str(raw_stop_reason)
                        self._merge_usage(raw_usage, payload.get("usage"))
                        continue

                    if payload_type == "message_stop":
                        if open_blocks:
                            raise ResponseParseError(
                                "Anthropic message_stop arrived before all content blocks stopped"
                            )
                        terminal_observed = True
                        ordered_blocks = [blocks[index] for index in sorted(blocks)]
                        yield StreamChunk(
                            is_finished=True,
                            usage=self._normalize_usage(raw_usage),
                            tool_calls=self._tool_calls_from_blocks(ordered_blocks),
                            finish_reason=self._normalize_stop_reason(stop_reason),
                            provider_state={
                                "protocol": "anthropic_messages",
                                "content": deepcopy(ordered_blocks),
                            },
                        )
                        return

                if not terminal_observed:
                    raise ResponseParseError(
                        "Anthropic stream ended before the required message_stop event"
                    )
        except httpx.TimeoutException as exc:
            raise APIError(f"Anthropic request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise APIError(f"Anthropic request failed: {exc}") from exc

    def _messages_url(self) -> str:
        if not self.base_url:
            raise APIError("Anthropic base URL is required")
        return f"{self.base_url.rstrip('/')}{self.MESSAGES_ENDPOINT}"

    def _headers(self) -> dict[str, str]:
        return {
            "accept": "text/event-stream",
            "anthropic-version": self.ANTHROPIC_VERSION,
            "content-type": "application/json",
            "x-api-key": self.api_key,
        }

    def _build_request_body(
        self,
        messages: Sequence[CanonicalMessage],
        model: Optional[str],
        tools: Optional[Sequence[CanonicalTool]],
        thinking: bool,
    ) -> dict[str, Any]:
        use_model = (model or self.model).strip()
        if not use_model:
            raise APIError("Anthropic model is required")

        native_messages, system = self._convert_messages(messages)
        body: dict[str, Any] = {
            "model": use_model,
            "max_tokens": self._request_max_tokens(use_model),
            "messages": native_messages,
            "stream": True,
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [self._convert_tool(tool) for tool in tools]
        thinking_config = self._thinking_config(use_model, thinking)
        if thinking_config is not None:
            body["thinking"] = thinking_config
        if (
            self.provider_id == "anthropic"
            and use_model == _ANTHROPIC_FABLE_5_MODEL
        ):
            body["output_config"] = {
                "effort": "high" if thinking else "low",
            }
        return body

    def _thinking_config(
        self,
        model: str,
        thinking: bool,
    ) -> Optional[dict[str, str]]:
        if (
            self.provider_id == "anthropic"
            and model == _ANTHROPIC_FABLE_5_MODEL
        ):
            return {
                "type": "adaptive",
                "display": "summarized" if thinking else "omitted",
            }
        if thinking:
            return {"type": "adaptive", "display": "summarized"}
        if (
            self.provider_id == "anthropic"
            and model in _ANTHROPIC_DISABLEABLE_ADAPTIVE_MODELS
        ):
            return {"type": "disabled"}
        return None

    def _request_max_tokens(self, model: str) -> int:
        """Choose a useful generation budget without requesting the model cap."""
        from infrastructure.llm_adapters.provider_catalog import get_model

        model_spec = get_model(self.provider_id, model)
        if model_spec is None:
            return _RUNTIME_MAX_TOKENS
        return min(int(model_spec.max_output_tokens), _RUNTIME_MAX_TOKENS)

    def _convert_messages(
        self,
        messages: Sequence[CanonicalMessage],
    ) -> tuple[list[dict[str, Any]], Optional[str]]:
        native_messages: list[dict[str, Any]] = []
        system_parts: list[str] = []
        index = 0

        while index < len(messages):
            message = messages[index]
            if not isinstance(message, Mapping):
                raise APIError(f"Canonical message {index} must be an object")
            role = str(message.get("role") or "")

            if role == "system":
                system_text = self._system_text(message.get("content"))
                if system_text:
                    system_parts.append(system_text)
                index += 1
                continue

            if role == "tool":
                tool_results: list[dict[str, Any]] = []
                while index < len(messages):
                    tool_message = messages[index]
                    if not isinstance(tool_message, Mapping):
                        raise APIError(f"Canonical message {index} must be an object")
                    if str(tool_message.get("role") or "") != "tool":
                        break
                    tool_results.append(self._convert_tool_result(tool_message, index))
                    index += 1
                native_messages.append({"role": "user", "content": tool_results})
                continue

            if role == "user":
                native_messages.append(
                    {
                        "role": "user",
                        "content": self._convert_content(
                            message.get("content"), allow_images=True
                        ),
                    }
                )
                index += 1
                continue

            if role == "assistant":
                native_messages.append(
                    {
                        "role": "assistant",
                        "content": self._convert_assistant_content(message),
                    }
                )
                index += 1
                continue

            raise APIError(f"Unsupported canonical message role: {role!r}")

        if not native_messages:
            raise APIError("Anthropic Messages requires at least one non-system message")
        system = "\n\n".join(system_parts) if system_parts else None
        return native_messages, system

    def _convert_assistant_content(
        self,
        message: Mapping[str, Any],
    ) -> str | list[dict[str, Any]]:
        provider_state = message.get("provider_state")
        if provider_state is not None:
            if not isinstance(provider_state, Mapping):
                raise APIError("Anthropic provider_state must be an object")
            if provider_state.get("protocol") != "anthropic_messages":
                raise APIError(
                    "Anthropic provider_state protocol must be 'anthropic_messages'"
                )
            content = provider_state.get("content")
            if not isinstance(content, list) or not all(
                isinstance(block, Mapping) for block in content
            ):
                raise APIError("Anthropic provider_state.content must be a block list")
            return deepcopy(content)

        converted = self._convert_content(message.get("content"), allow_images=False)
        if isinstance(converted, str):
            blocks: list[dict[str, Any]] = []
            if converted:
                blocks.append({"type": "text", "text": converted})
        else:
            blocks = converted

        tool_calls = message.get("tool_calls")
        if tool_calls is not None:
            if not isinstance(tool_calls, Sequence) or isinstance(
                tool_calls, (str, bytes, bytearray)
            ):
                raise APIError("Canonical assistant tool_calls must be a list")
            for tool_call in tool_calls:
                blocks.append(self._convert_assistant_tool_call(tool_call))
        return blocks

    def _convert_assistant_tool_call(self, tool_call: Any) -> dict[str, Any]:
        if not isinstance(tool_call, Mapping):
            raise APIError("Canonical assistant tool call must be an object")
        function = tool_call.get("function")
        if not isinstance(function, Mapping):
            raise APIError("Canonical assistant tool call is missing function")
        tool_use_id = str(tool_call.get("id") or "")
        name = str(function.get("name") or "")
        if not tool_use_id or not name:
            raise APIError("Canonical assistant tool call requires id and name")

        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError as exc:
                raise APIError(
                    f"Canonical tool arguments for {name!r} are not valid JSON"
                ) from exc
        if not isinstance(arguments, Mapping):
            raise APIError("Anthropic tool_use input must be an object")
        return {
            "type": "tool_use",
            "id": tool_use_id,
            "name": name,
            "input": deepcopy(dict(arguments)),
        }

    def _convert_tool_result(
        self,
        message: Mapping[str, Any],
        index: int,
    ) -> dict[str, Any]:
        tool_use_id = str(message.get("tool_call_id") or "")
        if not tool_use_id:
            raise APIError(f"Canonical tool message {index} requires tool_call_id")
        result: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": self._convert_content(
                message.get("content"), allow_images=True
            ),
        }
        if "is_error" in message:
            result["is_error"] = bool(message.get("is_error"))
        # Anthropic's tool_result has no name field. The authoritative name is
        # retained on its preceding assistant tool_use block.
        return result

    def _convert_content(
        self,
        content: Any,
        *,
        allow_images: bool,
    ) -> str | list[dict[str, Any]]:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if not isinstance(content, Sequence) or isinstance(
            content, (bytes, bytearray)
        ):
            raise APIError("Canonical message content must be text or a block list")

        blocks: list[dict[str, Any]] = []
        for part in content:
            if isinstance(part, str):
                blocks.append({"type": "text", "text": part})
                continue
            if not isinstance(part, Mapping):
                raise APIError("Canonical content block must be an object")
            part_type = part.get("type")
            if part_type == "text":
                text = part.get("text")
                if not isinstance(text, str):
                    raise APIError("Canonical text block requires string text")
                blocks.append({"type": "text", "text": text})
                continue
            if part_type == "image_url" and allow_images:
                blocks.append(self._convert_image(part))
                continue
            raise APIError(f"Unsupported canonical content block type: {part_type!r}")
        return blocks

    def _convert_image(self, part: Mapping[str, Any]) -> dict[str, Any]:
        image_url = part.get("image_url")
        if not isinstance(image_url, Mapping):
            raise APIError("Canonical image_url block is missing image_url")
        url = image_url.get("url")
        if not isinstance(url, str) or not url:
            raise APIError("Canonical image_url.url must be a non-empty string")

        match = _DATA_IMAGE_RE.match(url)
        if match is None:
            return {
                "type": "image",
                "source": {"type": "url", "url": url},
            }

        media_type = match.group("media_type").casefold()
        data = match.group("data")
        if media_type not in _SUPPORTED_IMAGE_MEDIA_TYPES:
            raise APIError(f"Unsupported Anthropic image media type: {media_type}")
        try:
            base64.b64decode(data, validate=True)
        except (ValueError, TypeError) as exc:
            raise APIError("Canonical image data is not valid base64") from exc
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": data,
            },
        }

    def _convert_tool(self, tool: CanonicalTool) -> dict[str, Any]:
        if not isinstance(tool, Mapping) or tool.get("type") != "function":
            raise APIError("Anthropic tools must use the canonical function schema")
        function = tool.get("function")
        if not isinstance(function, Mapping):
            raise APIError("Canonical tool is missing its function definition")
        name = str(function.get("name") or "")
        parameters = function.get("parameters")
        if not name or not isinstance(parameters, Mapping):
            raise APIError("Canonical tool requires name and object parameters")

        native: dict[str, Any] = {
            "name": name,
            "input_schema": deepcopy(dict(parameters)),
        }
        description = function.get("description")
        if isinstance(description, str) and description:
            native["description"] = description
        strict = function.get("strict")
        if isinstance(strict, bool):
            native["strict"] = strict
        return native

    def _system_text(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if not isinstance(content, Sequence) or isinstance(
            content, (bytes, bytearray)
        ):
            raise APIError("Canonical system content must be text or text blocks")
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
                continue
            if not isinstance(part, Mapping) or part.get("type") != "text":
                raise APIError("Anthropic system content only supports text blocks")
            text = part.get("text")
            if not isinstance(text, str):
                raise APIError("Canonical system text block requires string text")
            parts.append(text)
        return "".join(parts)

    async def _iter_sse_events(
        self,
        response: httpx.Response,
    ) -> AsyncIterator[tuple[str, str]]:
        event_name = ""
        data_lines: list[str] = []
        async for line in response.aiter_lines():
            if line == "":
                if data_lines:
                    yield event_name, "\n".join(data_lines)
                event_name = ""
                data_lines = []
                continue
            if line.startswith(":"):
                continue
            field, separator, value = line.partition(":")
            if separator and value.startswith(" "):
                value = value[1:]
            if field == "event":
                event_name = value
            elif field == "data":
                data_lines.append(value)

        if data_lines:
            yield event_name, "\n".join(data_lines)

    def _decode_sse_payload(self, payload_text: str) -> dict[str, Any]:
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise ResponseParseError(f"Invalid Anthropic SSE JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ResponseParseError("Anthropic SSE payload must be an object")
        return payload

    def _event_index(self, payload: Mapping[str, Any]) -> int:
        index = payload.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise ResponseParseError("Anthropic content event requires a non-negative index")
        return index

    def _tool_calls_from_blocks(
        self,
        blocks: Sequence[Mapping[str, Any]],
    ) -> Optional[list[dict[str, Any]]]:
        tool_calls: list[dict[str, Any]] = []
        for index, block in enumerate(blocks):
            if block.get("type") != "tool_use":
                continue
            tool_use_id = block.get("id")
            name = block.get("name")
            tool_input = block.get("input")
            if not isinstance(tool_use_id, str) or not isinstance(name, str):
                raise ResponseParseError("Anthropic tool_use requires string id and name")
            if not isinstance(tool_input, Mapping):
                raise ResponseParseError("Anthropic tool_use input must be an object")
            tool_calls.append(
                {
                    "id": tool_use_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": deepcopy(dict(tool_input)),
                    },
                    "index": index,
                }
            )
        return tool_calls or None

    def _merge_usage(self, accumulator: dict[str, int], usage: Any) -> None:
        if not isinstance(usage, Mapping):
            return
        for field in _USAGE_FIELDS:
            value = usage.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                accumulator[field] = value

    def _normalize_usage(self, usage: Mapping[str, int]) -> Optional[dict[str, int]]:
        if not usage:
            return None
        input_tokens = int(usage.get("input_tokens", 0))
        cache_creation = int(usage.get("cache_creation_input_tokens", 0))
        cache_read = int(usage.get("cache_read_input_tokens", 0))
        output_tokens = int(usage.get("output_tokens", 0))
        prompt_tokens = input_tokens + cache_creation + cache_read
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": prompt_tokens + output_tokens,
            "cached_tokens": cache_read,
        }

    def _normalize_stop_reason(self, stop_reason: Optional[str]) -> Optional[str]:
        return {
            "end_turn": "stop",
            "stop_sequence": "stop",
            "tool_use": "tool_calls",
            "max_tokens": "max_tokens",
            "model_context_window_exceeded": "max_tokens",
            "refusal": "safety",
        }.get(stop_reason, stop_reason)

    def _raise_http_error(self, response: httpx.Response) -> None:
        status = response.status_code
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            payload = None

        if isinstance(payload, dict):
            self._raise_payload_error(payload, status_code=status, response=response)

        message = response.text[:500] or f"Anthropic HTTP {status}"
        if status in (401, 403):
            raise AuthError(message, status_code=status)
        if status == 429:
            raise RateLimitError(
                message,
                retry_after=self._retry_after(response),
                status_code=status,
            )
        if self._looks_like_context_overflow(message):
            raise ContextOverflowError(message, status_code=status)
        raise APIError(message, status_code=status)

    def _raise_payload_error(
        self,
        payload: Mapping[str, Any],
        *,
        status_code: Optional[int] = None,
        response: Optional[httpx.Response] = None,
    ) -> None:
        error = payload.get("error")
        if not isinstance(error, Mapping):
            raise ResponseParseError("Malformed Anthropic error payload")
        error_type = str(error.get("type") or "")
        error_message = str(error.get("message") or "Unknown Anthropic API error")
        request_id = str(payload.get("request_id") or "")
        detail = f" [{error_type}]" if error_type else ""
        request_detail = f" ({request_id})" if request_id else ""
        message = f"Anthropic API error{detail}{request_detail}: {error_message}"

        if status_code in (401, 403) or error_type in {
            "authentication_error",
            "permission_error",
        }:
            raise AuthError(message, status_code=status_code)
        if status_code == 429 or error_type == "rate_limit_error":
            raise RateLimitError(
                message,
                retry_after=self._retry_after(response),
                status_code=status_code or 429,
            )
        if self._looks_like_context_overflow(error_message):
            raise ContextOverflowError(message, status_code=status_code or 400)
        raise APIError(message, status_code=status_code)

    def _retry_after(self, response: Optional[httpx.Response]) -> Optional[int]:
        if response is None:
            return None
        retry_after = response.headers.get("retry-after")
        if retry_after and retry_after.isdigit():
            return int(retry_after)
        return None

    def _looks_like_context_overflow(self, message: str) -> bool:
        lowered = message.casefold()
        if "prompt is too long" in lowered:
            return True
        return "context" in lowered and any(
            marker in lowered
            for marker in ("exceed", "length", "limit", "long", "token", "window")
        )


__all__ = ["AnthropicClient"]
