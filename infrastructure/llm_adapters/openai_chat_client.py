"""One pure-async transport for curated OpenAI Chat-compatible providers."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Mapping, NoReturn, Optional, Sequence

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
from infrastructure.llm_adapters.sse import SSEEvent, iter_sse_events


@dataclass(frozen=True, slots=True)
class _ProviderPolicy:
    thinking_style: str
    require_done: bool = False
    preserve_thinking: Optional[bool] = None


_GENERIC_POLICY = _ProviderPolicy(thinking_style="none")
_PROVIDER_POLICIES: dict[str, _ProviderPolicy] = {
    "qwen": _ProviderPolicy(
        thinking_style="enable_thinking",
        require_done=True,
        preserve_thinking=False,
    ),
    "deepseek": _ProviderPolicy(thinking_style="thinking", require_done=True),
    "zhipu": _ProviderPolicy(thinking_style="thinking"),
    "kimi": _ProviderPolicy(thinking_style="reasoning_effort", require_done=True),
    "opencode": _ProviderPolicy(thinking_style="reasoning_effort"),
    "siliconflow": _ProviderPolicy(thinking_style="enable_thinking"),
}


class OpenAIChatClient(BaseLLMClient):
    """Async OpenAI Chat Completions client with explicit provider policies."""

    CHAT_ENDPOINT = "chat/completions"

    def __init__(
        self,
        provider_id: str,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60,
    ) -> None:
        super().__init__(provider_id, api_key, base_url, model, timeout)
        if not self.base_url:
            raise ValueError("base_url is required")
        if not self.model:
            raise ValueError("model is required")

        # A trailing slash plus a relative endpoint is intentional: a leading
        # slash would reset provider base paths such as /compatible-mode/v1.
        normalized_base_url = f"{self.base_url.rstrip('/')}/"
        self._client = httpx.AsyncClient(
            base_url=normalized_base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(self.timeout, connect=min(10.0, self.timeout)),
        )
        self._closed = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._client.aclose()

    async def __aenter__(self) -> "OpenAIChatClient":
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()

    def build_request_body(
        self,
        messages: Sequence[CanonicalMessage],
        model: Optional[str] = None,
        tools: Optional[Sequence[CanonicalTool]] = None,
        thinking: bool = False,
        *,
        reasoning_effort: Optional[str] = None,
    ) -> dict[str, Any]:
        """Translate the canonical request into this provider's wire shape."""
        selected_model = (model or self.model).strip()
        if not selected_model:
            raise APIError("Model is required")

        normalized_tools = self._normalize_tools(tools)
        body: dict[str, Any] = {
            "model": selected_model,
            "messages": self._normalize_messages(messages),
            "stream": True,
        }
        if normalized_tools:
            body["tools"] = normalized_tools

        policy = _PROVIDER_POLICIES.get(self.provider_id, _GENERIC_POLICY)
        if policy.thinking_style == "enable_thinking":
            body["enable_thinking"] = bool(thinking)
            if policy.preserve_thinking is not None:
                body["preserve_thinking"] = (
                    selected_model == "qwen3.8-max"
                    if self.provider_id == "qwen"
                    else policy.preserve_thinking
                )
        elif policy.thinking_style == "thinking":
            requires_thinking = (
                self.provider_id == "zhipu" and selected_model == "glm-5.3"
            )
            thinking_config: dict[str, Any] = {
                "type": "enabled" if thinking or requires_thinking else "disabled",
            }
            if (
                self.provider_id == "zhipu"
                and (thinking or requires_thinking)
                and normalized_tools
            ):
                thinking_config["clear_thinking"] = False
            body["thinking"] = thinking_config
            if requires_thinking:
                body["reasoning_effort"] = (
                    reasoning_effort or ("high" if thinking else "low")
                ).strip()
            if self.provider_id == "deepseek" and thinking:
                body["reasoning_effort"] = (reasoning_effort or "high").strip()
        elif policy.thinking_style == "reasoning_effort":
            # Kimi K3 always reasons and defaults to max; map the portable
            # boolean to a useful low/high budget. OpenCode custom models only
            # receive the field when the user explicitly enables thinking.
            if self.provider_id == "kimi":
                body["reasoning_effort"] = (
                    reasoning_effort or ("high" if thinking else "low")
                ).strip()
            elif thinking:
                body["reasoning_effort"] = (reasoning_effort or "high").strip()

        return body

    async def chat_stream(
        self,
        messages: Sequence[CanonicalMessage],
        model: Optional[str] = None,
        tools: Optional[Sequence[CanonicalTool]] = None,
        thinking: bool = False,
        *,
        reasoning_effort: Optional[str] = None,
    ) -> AsyncIterator[StreamChunk]:
        if self._closed:
            raise APIError("LLM client is closed")

        request_body = self.build_request_body(
            messages=messages,
            model=model,
            tools=tools,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
        )
        policy = _PROVIDER_POLICIES.get(self.provider_id, _GENERIC_POLICY)
        tool_calls: dict[int, dict[int, dict[str, Any]]] = {}
        seen_indexes: set[int] = set()
        terminal_indexes: set[int] = set()
        saw_done = False

        try:
            async with self._client.stream(
                "POST",
                self.CHAT_ENDPOINT,
                json=request_body,
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    await response.aread()
                    self._raise_http_error(response)

                async for event in iter_sse_events(response.aiter_text()):
                    if event.data.strip() == "[DONE]":
                        saw_done = True
                        if not terminal_indexes:
                            if not seen_indexes:
                                raise ResponseParseError(
                                    f"{self.provider_id} stream ended without a response choice"
                                )
                            for index in sorted(seen_indexes):
                                yield StreamChunk(
                                    is_finished=True,
                                    finish_reason="tool_calls" if tool_calls.get(index) else "stop",
                                    tool_calls=self._finalize_tool_calls(tool_calls.get(index, {})),
                                    index=index,
                                )
                                terminal_indexes.add(index)
                        break

                    payload = self._decode_event(event)
                    if "error" in payload:
                        self._raise_payload_error(payload["error"])

                    usage = self._normalize_usage(payload.get("usage"))
                    choices = payload.get("choices")
                    if not isinstance(choices, list) or not choices:
                        if usage is not None:
                            yield StreamChunk(usage=usage)
                        continue

                    for fallback_index, raw_choice in enumerate(choices):
                        if not isinstance(raw_choice, Mapping):
                            raise ResponseParseError("Provider returned a non-object choice")
                        index = raw_choice.get("index", fallback_index)
                        if not isinstance(index, int):
                            raise ResponseParseError("Provider returned a non-integer choice index")
                        seen_indexes.add(index)

                        raw_delta = raw_choice.get("delta")
                        if not isinstance(raw_delta, Mapping):
                            raw_delta = raw_choice.get("message")
                        if not isinstance(raw_delta, Mapping):
                            raw_delta = {}

                        self._merge_tool_call_deltas(
                            tool_calls.setdefault(index, {}),
                            raw_delta.get("tool_calls"),
                        )
                        finish_reason = raw_choice.get("finish_reason")
                        if finish_reason is not None:
                            finish_reason = str(finish_reason)
                            terminal_indexes.add(index)

                        content = self._extract_text(raw_delta.get("content"))
                        reasoning = self._extract_text(
                            raw_delta.get("reasoning_content")
                        )
                        if reasoning is None:
                            reasoning = self._extract_text(raw_delta.get("reasoning"))

                        if (
                            content is not None
                            or reasoning is not None
                            or finish_reason is not None
                            or usage is not None
                        ):
                            yield StreamChunk(
                                content=content,
                                reasoning_content=reasoning,
                                is_finished=finish_reason is not None,
                                usage=usage,
                                tool_calls=(
                                    self._finalize_tool_calls(tool_calls[index])
                                    if finish_reason is not None
                                    else None
                                ),
                                finish_reason=finish_reason,
                                index=index,
                            )
        except (APIError, ResponseParseError):
            raise
        except httpx.TimeoutException as exc:
            raise APIError(f"Request timeout: {exc}") from exc
        except httpx.RequestError as exc:
            raise APIError(f"Request error: {exc}") from exc

        if policy.require_done and not saw_done:
            raise ResponseParseError(
                f"{self.provider_id} stream ended before the [DONE] event"
            )
        if not terminal_indexes:
            raise ResponseParseError(
                f"{self.provider_id} stream ended before a terminal frame"
            )

    @staticmethod
    def _normalize_messages(
        messages: Sequence[CanonicalMessage],
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for raw_message in messages:
            if not isinstance(raw_message, Mapping):
                raise APIError("Each chat message must be an object")
            role = str(raw_message.get("role", "")).strip()
            if role not in {"system", "developer", "user", "assistant", "tool"}:
                raise APIError(f"Unsupported chat message role: {role or '<empty>'}")

            message: dict[str, Any] = {
                "role": role,
                "content": OpenAIChatClient._normalize_content(
                    raw_message.get("content", "")
                ),
            }
            if role == "assistant":
                if "reasoning_content" in raw_message:
                    message["reasoning_content"] = copy.deepcopy(
                        raw_message["reasoning_content"]
                    )
                if "tool_calls" in raw_message:
                    message["tool_calls"] = OpenAIChatClient._normalize_tool_calls(
                        raw_message["tool_calls"]
                    )
            if role == "tool":
                tool_call_id = str(raw_message.get("tool_call_id", "")).strip()
                if not tool_call_id:
                    raise APIError("Tool message is missing tool_call_id")
                message["tool_call_id"] = tool_call_id
                if raw_message.get("name"):
                    message["name"] = str(raw_message["name"])
            elif raw_message.get("name"):
                message["name"] = str(raw_message["name"])
            normalized.append(message)
        return normalized

    @staticmethod
    def _normalize_content(content: Any) -> Any:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if not isinstance(content, Sequence) or isinstance(content, (bytes, bytearray)):
            return str(content)

        parts: list[dict[str, Any]] = []
        for raw_part in content:
            if not isinstance(raw_part, Mapping):
                raise APIError("Each multimodal content part must be an object")
            part_type = str(raw_part.get("type", "")).strip()
            if part_type == "text":
                parts.append({"type": "text", "text": str(raw_part.get("text", ""))})
                continue
            if part_type not in {"image", "image_url"}:
                raise APIError(f"Unsupported content part type: {part_type or '<empty>'}")

            image_value = raw_part.get("image_url")
            if isinstance(image_value, Mapping):
                url = str(image_value.get("url", "")).strip()
                detail = image_value.get("detail")
            elif isinstance(image_value, str):
                url = image_value.strip()
                detail = raw_part.get("detail")
            else:
                url = str(raw_part.get("url", "")).strip()
                detail = raw_part.get("detail")
            if not url:
                raise APIError("Image content is missing a URL")
            normalized_image: dict[str, Any] = {"url": url}
            if detail is not None:
                normalized_image["detail"] = str(detail)
            parts.append({"type": "image_url", "image_url": normalized_image})
        return parts

    @staticmethod
    def _normalize_tools(
        tools: Optional[Sequence[CanonicalTool]],
    ) -> list[dict[str, Any]]:
        if not tools:
            return []
        normalized: list[dict[str, Any]] = []
        for raw_tool in tools:
            if not isinstance(raw_tool, Mapping):
                raise APIError("Each tool definition must be an object")
            tool_type = str(raw_tool.get("type", "function"))
            function = raw_tool.get("function")
            if tool_type != "function" or not isinstance(function, Mapping):
                raise APIError("Only canonical function tools are supported")
            name = str(function.get("name", "")).strip()
            if not name:
                raise APIError("Tool definition is missing function.name")
            normalized_function = copy.deepcopy(dict(function))
            normalized_function["name"] = name
            normalized.append({"type": "function", "function": normalized_function})
        return normalized

    @staticmethod
    def _normalize_tool_calls(raw_calls: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_calls, Sequence) or isinstance(raw_calls, (str, bytes)):
            raise APIError("assistant.tool_calls must be a list")
        normalized: list[dict[str, Any]] = []
        for raw_call in raw_calls:
            if not isinstance(raw_call, Mapping):
                raise APIError("Each assistant tool call must be an object")
            function = raw_call.get("function")
            if not isinstance(function, Mapping):
                raise APIError("Assistant tool call is missing function")
            arguments = function.get("arguments", "")
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
            call: dict[str, Any] = {
                "id": str(raw_call.get("id", "")),
                "type": str(raw_call.get("type", "function")),
                "function": {
                    "name": str(function.get("name", "")),
                    "arguments": arguments,
                },
            }
            normalized.append(call)
        return normalized

    @staticmethod
    def _merge_tool_call_deltas(
        accumulator: dict[int, dict[str, Any]],
        raw_deltas: Any,
    ) -> None:
        if not isinstance(raw_deltas, list):
            return
        for fallback_index, raw_delta in enumerate(raw_deltas):
            if not isinstance(raw_delta, Mapping):
                continue
            index = raw_delta.get("index", fallback_index)
            if not isinstance(index, int):
                index = fallback_index
            current = accumulator.setdefault(
                index,
                {
                    "index": index,
                    "id": "",
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                },
            )
            if raw_delta.get("id"):
                current["id"] = str(raw_delta["id"])
            if raw_delta.get("type"):
                current["type"] = str(raw_delta["type"])
            function_delta = raw_delta.get("function")
            if not isinstance(function_delta, Mapping):
                continue
            name = function_delta.get("name")
            if name:
                current["function"]["name"] += str(name)
            arguments = function_delta.get("arguments")
            if arguments is not None:
                if not isinstance(arguments, str):
                    arguments = json.dumps(
                        arguments,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                current["function"]["arguments"] += arguments

    @staticmethod
    def _finalize_tool_calls(
        accumulator: Mapping[int, dict[str, Any]],
    ) -> Optional[list[dict[str, Any]]]:
        if not accumulator:
            return None
        return [copy.deepcopy(accumulator[index]) for index in sorted(accumulator)]

    @staticmethod
    def _extract_text(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            fragments: list[str] = []
            for item in value:
                if isinstance(item, str):
                    fragments.append(item)
                elif isinstance(item, Mapping) and item.get("type") == "text":
                    fragments.append(str(item.get("text", "")))
            return "".join(fragments) or None
        return str(value)

    @staticmethod
    def _normalize_usage(value: Any) -> Optional[dict[str, Any]]:
        return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else None

    @staticmethod
    def _decode_event(event: SSEEvent) -> dict[str, Any]:
        try:
            payload = json.loads(event.data)
        except json.JSONDecodeError as exc:
            raise ResponseParseError(
                f"Invalid SSE JSON payload: {exc.msg}"
            ) from exc
        if not isinstance(payload, dict):
            raise ResponseParseError("SSE payload must be a JSON object")
        if event.event == "error" and "error" not in payload:
            return {"error": payload}
        return payload

    def _raise_http_error(self, response: httpx.Response) -> NoReturn:
        message = self._error_message(response)
        status_code = response.status_code
        if status_code in {401, 403}:
            raise AuthError(message, status_code=status_code)
        if status_code == 429:
            raise RateLimitError(
                message,
                retry_after=self._retry_after(response.headers.get("Retry-After")),
                status_code=status_code,
            )
        if status_code in {400, 413, 422} and self._is_context_error(message):
            raise ContextOverflowError(message, status_code=status_code)
        raise APIError(message, status_code=status_code)

    def _raise_payload_error(self, error: Any) -> NoReturn:
        if isinstance(error, Mapping):
            message = str(error.get("message") or error.get("msg") or error)
            code = str(error.get("code") or error.get("type") or "").casefold()
        else:
            message = str(error)
            code = ""
        haystack = f"{code} {message}".casefold()
        if any(token in haystack for token in ("auth", "api_key", "unauthorized")):
            raise AuthError(message)
        if "rate" in haystack and "limit" in haystack:
            raise RateLimitError(message)
        if self._is_context_error(haystack):
            raise ContextOverflowError(message)
        raise APIError(message)

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, Mapping):
            error = payload.get("error", payload)
            if isinstance(error, Mapping):
                message = error.get("message") or error.get("msg")
                if message:
                    return str(message)
            if isinstance(error, str):
                return error
        text = response.text.strip()
        return text[:500] if text else f"Provider HTTP {response.status_code}"

    @staticmethod
    def _retry_after(value: Optional[str]) -> Optional[int]:
        if not value:
            return None
        try:
            return max(0, int(value))
        except ValueError:
            return None

    @staticmethod
    def _is_context_error(message: str) -> bool:
        normalized = message.casefold().replace("-", "_").replace(" ", "_")
        return any(
            token in normalized
            for token in (
                "context_length",
                "context_window",
                "maximum_context",
                "max_tokens",
                "too_many_tokens",
            )
        )


__all__ = ["OpenAIChatClient"]
