"""Native Google Gemini ``GenerateContent`` transport adapter.

The adapter deliberately speaks Gemini's REST schema instead of translating
the stream through an OpenAI-compatible facade.  In particular, native model
``Content.parts`` are retained as opaque provider state so thought signatures
and function-call identifiers can be replayed unchanged after tool execution.
"""

from __future__ import annotations

import base64
import binascii
from copy import deepcopy
import json
import re
from typing import Any, AsyncIterator, Mapping, Optional, Sequence
from urllib.parse import quote

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


_PROTOCOL = "gemini_generate_content"
_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_THINKING_LEVEL_MODELS = frozenset(
    {
        "gemini-3.1-pro",
        "gemini-3.1-pro-preview",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
    }
)
_THINKING_BUDGETS = {
    "gemini-2.5-pro": {False: 1_024, True: 24_576},
}
_DATA_IMAGE_RE = re.compile(
    r"^data:(?P<mime>image/[A-Za-z0-9.+-]+);base64,(?P<data>.+)$",
    re.DOTALL,
)

_USAGE_FIELDS = {
    "promptTokenCount": "prompt_tokens",
    "candidatesTokenCount": "completion_tokens",
    "totalTokenCount": "total_tokens",
    "cachedContentTokenCount": "cached_tokens",
    "thoughtsTokenCount": "reasoning_tokens",
    "toolUsePromptTokenCount": "tool_use_prompt_tokens",
}


class GeminiClient(BaseLLMClient):
    """Pure-async client for Gemini's native streaming REST endpoint."""

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
        if not self.api_key:
            raise AuthError("Gemini API key is required")
        if not self.base_url:
            raise APIError("Gemini base URL is required")
        if not self.model:
            raise APIError("Gemini model is required")

        # Keep a custom API prefix intact.  The trailing slash matters to
        # httpx URL joining when the prefix itself contains a path such as v1.
        self.base_url = self.base_url.rstrip("/") + "/"

    def _get_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

    def _create_async_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._get_headers(),
            timeout=httpx.Timeout(self.timeout, connect=10.0),
        )

    def _normalize_model(self, model: str) -> str:
        model_id = model.strip()
        if model_id.startswith("models/"):
            model_id = model_id[len("models/") :]
        if not model_id:
            raise APIError(f"Invalid Gemini model ID: {model!r}")
        if self.provider_id == "gemini":
            if not _MODEL_ID_RE.fullmatch(model_id):
                raise APIError(f"Invalid Gemini model ID: {model!r}")
            return model_id

        # A custom protocol selection owns its model namespace.  Preserve path
        # separators such as ``vendor/custom-model`` and only URL-escape bytes
        # that could alter the GenerateContent endpoint itself.
        return quote(model_id, safe="/-._~")

    @staticmethod
    def _text_part(value: Any, *, location: str) -> dict[str, str]:
        if not isinstance(value, str):
            raise APIError(f"{location} text must be a string")
        return {"text": value}

    @staticmethod
    def _image_part(item: Mapping[str, Any], *, location: str) -> dict[str, Any]:
        image_value = item.get("image_url")
        if isinstance(image_value, Mapping):
            image_url = image_value.get("url")
        else:
            image_url = image_value
        if not isinstance(image_url, str):
            raise APIError(f"{location} image_url.url must be a data URI")

        match = _DATA_IMAGE_RE.fullmatch(image_url)
        if match is None:
            raise APIError(
                f"{location} image must be an inline base64 image data URI"
            )
        encoded = match.group("data")
        try:
            base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise APIError(f"{location} image contains invalid base64 data") from exc

        return {
            "inlineData": {
                "mimeType": match.group("mime"),
                "data": encoded,
            }
        }

    def _canonical_parts(
        self,
        content: Any,
        *,
        location: str,
        allow_images: bool,
    ) -> list[dict[str, Any]]:
        if isinstance(content, str):
            return [self._text_part(content, location=location)]
        if not isinstance(content, Sequence) or isinstance(
            content, (bytes, bytearray)
        ):
            raise APIError(f"{location} content must be text or a content-part list")

        parts: list[dict[str, Any]] = []
        for index, item in enumerate(content):
            item_location = f"{location} content[{index}]"
            if isinstance(item, str):
                parts.append(self._text_part(item, location=item_location))
                continue
            if not isinstance(item, Mapping):
                raise APIError(f"{item_location} must be an object")

            item_type = item.get("type")
            if item_type == "text":
                parts.append(self._text_part(item.get("text"), location=item_location))
            elif item_type == "image_url" and allow_images:
                parts.append(self._image_part(item, location=item_location))
            else:
                raise APIError(
                    f"Unsupported {item_location} type for Gemini: {item_type!r}"
                )
        if not parts:
            raise APIError(f"{location} content must contain at least one part")
        return parts

    @staticmethod
    def _native_assistant_content(message: CanonicalMessage) -> dict[str, Any]:
        state = message.get("provider_state")
        if not isinstance(state, Mapping) or state.get("protocol") != _PROTOCOL:
            raise APIError(
                "Gemini assistant tool calls require native provider_state"
            )

        content = state.get("content")
        if not isinstance(content, Mapping) or content.get("role") != "model":
            raise APIError("Malformed Gemini provider_state content")
        parts = content.get("parts")
        if not isinstance(parts, list) or not all(
            isinstance(part, Mapping) for part in parts
        ):
            raise APIError("Malformed Gemini provider_state parts")
        return deepcopy(dict(content))

    @staticmethod
    def _pending_function_calls(
        native_content: Mapping[str, Any],
    ) -> list[dict[str, Optional[str]]]:
        pending: list[dict[str, Optional[str]]] = []
        for part in native_content.get("parts", []):
            function_call = part.get("functionCall")
            if not isinstance(function_call, Mapping):
                continue
            name = function_call.get("name")
            if not isinstance(name, str) or not name:
                raise APIError("Gemini provider_state contains an invalid functionCall")
            native_id = function_call.get("id")
            if native_id is not None and (
                not isinstance(native_id, str) or not native_id
            ):
                raise APIError("Gemini provider_state contains an invalid functionCall.id")
            internal_id = native_id or f"gemini-call-{len(pending)}"
            pending.append(
                {
                    "name": name,
                    "native_id": native_id,
                    "internal_id": internal_id,
                }
            )
        return pending

    @staticmethod
    def _function_response_part(
        message: CanonicalMessage,
        expected: Mapping[str, Optional[str]],
    ) -> dict[str, Any]:
        tool_call_id = message.get("tool_call_id")
        if tool_call_id != expected["internal_id"]:
            raise APIError(
                "Gemini tool result does not match the preceding functionCall ID"
            )
        supplied_name = message.get("name")
        if supplied_name not in (None, "", expected["name"]):
            raise APIError(
                "Gemini tool result name does not match the preceding functionCall"
            )

        function_response: dict[str, Any] = {
            "name": expected["name"],
            "response": {"result": deepcopy(message.get("content", ""))},
        }
        if expected["native_id"] is not None:
            function_response["id"] = expected["native_id"]
        return {"functionResponse": function_response}

    def _build_contents(
        self,
        messages: Sequence[CanonicalMessage],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        system_parts: list[dict[str, Any]] = []
        contents: list[dict[str, Any]] = []
        pending: Optional[list[dict[str, Optional[str]]]] = None
        pending_index = 0
        response_parts: list[dict[str, Any]] = []

        def finish_tool_responses() -> None:
            nonlocal pending, pending_index, response_parts
            if pending is None:
                return
            if pending_index != len(pending):
                raise APIError(
                    "Gemini functionCall history is missing one or more tool results"
                )
            if response_parts:
                contents.append({"role": "user", "parts": response_parts})
            pending = None
            pending_index = 0
            response_parts = []

        for message_index, message in enumerate(messages):
            if not isinstance(message, Mapping):
                raise APIError(f"messages[{message_index}] must be an object")
            role = message.get("role")

            if role == "system":
                system_parts.extend(
                    self._canonical_parts(
                        message.get("content"),
                        location=f"messages[{message_index}]",
                        allow_images=False,
                    )
                )
                continue

            if role == "tool":
                if pending is None or pending_index >= len(pending):
                    raise APIError(
                        "Gemini tool result has no matching preceding functionCall"
                    )
                response_parts.append(
                    self._function_response_part(message, pending[pending_index])
                )
                pending_index += 1
                continue

            finish_tool_responses()

            if role == "user":
                contents.append(
                    {
                        "role": "user",
                        "parts": self._canonical_parts(
                            message.get("content"),
                            location=f"messages[{message_index}]",
                            allow_images=True,
                        ),
                    }
                )
                continue

            if role == "assistant":
                if message.get("provider_state") is not None:
                    native_content = self._native_assistant_content(message)
                    contents.append(native_content)
                    native_calls = self._pending_function_calls(native_content)
                    if native_calls:
                        pending = native_calls
                    continue

                if message.get("tool_calls"):
                    raise APIError(
                        "Gemini assistant tool calls cannot be reconstructed without "
                        "native provider_state"
                    )
                contents.append(
                    {
                        "role": "model",
                        "parts": self._canonical_parts(
                            message.get("content"),
                            location=f"messages[{message_index}]",
                            allow_images=False,
                        ),
                    }
                )
                continue

            raise APIError(f"Unsupported messages[{message_index}] role: {role!r}")

        finish_tool_responses()
        if not contents:
            raise APIError("Gemini request requires at least one non-system message")
        return system_parts, contents

    @staticmethod
    def _build_tools(tools: Sequence[CanonicalTool]) -> list[dict[str, Any]]:
        declarations: list[dict[str, Any]] = []
        for index, tool in enumerate(tools):
            if not isinstance(tool, Mapping) or tool.get("type") != "function":
                raise APIError(f"tools[{index}] must be a canonical function tool")
            function = tool.get("function")
            if not isinstance(function, Mapping):
                raise APIError(f"tools[{index}].function must be an object")
            name = function.get("name")
            if not isinstance(name, str) or not name:
                raise APIError(f"tools[{index}].function.name is required")

            declaration: dict[str, Any] = {"name": name}
            description = function.get("description")
            if description is not None:
                if not isinstance(description, str):
                    raise APIError(
                        f"tools[{index}].function.description must be a string"
                    )
                declaration["description"] = description
            parameters = function.get("parameters")
            if parameters is not None:
                if not isinstance(parameters, Mapping):
                    raise APIError(
                        f"tools[{index}].function.parameters must be an object"
                    )
                declaration["parameters"] = deepcopy(dict(parameters))
            declarations.append(declaration)
        return [{"functionDeclarations": declarations}]

    def _build_request_body(
        self,
        messages: Sequence[CanonicalMessage],
        *,
        tools: Optional[Sequence[CanonicalTool]],
        thinking: bool,
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        system_parts, contents = self._build_contents(messages)
        body: dict[str, Any] = {"contents": contents}
        if system_parts:
            body["systemInstruction"] = {"parts": system_parts}
        if tools:
            body["tools"] = self._build_tools(tools)
        thinking_config = self._thinking_config(
            self._normalize_model(model or self.model),
            thinking=thinking,
        )
        if thinking_config is not None:
            body["generationConfig"] = {"thinkingConfig": thinking_config}
        return body

    def _thinking_config(
        self,
        model_id: str,
        *,
        thinking: bool,
    ) -> Optional[dict[str, Any]]:
        # OpenCode/custom Gemini-protocol endpoints own arbitrary model IDs.
        # Do not infer Google's model-family-specific budgets from those IDs.
        if self.provider_id != "gemini":
            if not thinking:
                return None
            return {"thinkingLevel": "high", "includeThoughts": True}

        if model_id in _THINKING_LEVEL_MODELS:
            config: dict[str, Any] = {
                "thinkingLevel": "high" if thinking else "low"
            }
            if thinking:
                config["includeThoughts"] = True
            return config

        budget_by_mode = _THINKING_BUDGETS.get(model_id)
        if budget_by_mode is not None:
            config = {"thinkingBudget": budget_by_mode[thinking]}
            if thinking:
                config["includeThoughts"] = True
            return config

        raise APIError(
            f"No explicit Gemini thinking contract is defined for model {model_id!r}"
        )

    @staticmethod
    def _usage(usage_metadata: Any) -> Optional[dict[str, int]]:
        if not isinstance(usage_metadata, Mapping):
            return None
        usage = {
            target: value
            for source, target in _USAGE_FIELDS.items()
            if isinstance((value := usage_metadata.get(source)), int)
            and not isinstance(value, bool)
        }
        return usage or None

    @staticmethod
    def _error_details(error: Any) -> tuple[Optional[int], str, str]:
        if isinstance(error, Mapping):
            raw_code = error.get("code")
            code = raw_code if isinstance(raw_code, int) else None
            status = str(error.get("status") or error.get("type") or "")
            message = str(error.get("message") or "Unknown Gemini API error")
            return code, status, message
        if isinstance(error, str):
            return None, "", error
        return None, "", "Malformed Gemini API error"

    @classmethod
    def _raise_provider_error(
        cls,
        error: Any,
        *,
        http_status: Optional[int] = None,
        retry_after: Optional[int] = None,
    ) -> None:
        error_code, error_status, detail = cls._error_details(error)
        status_code = http_status or error_code
        label = f" [{error_status}]" if error_status else ""
        message = f"Gemini API error{label}: {detail}"
        classification = f"{error_status} {detail}".casefold()

        if status_code in (401, 403) or any(
            marker in classification
            for marker in ("api key", "api_key", "unauthenticated", "permission_denied")
        ):
            raise AuthError(message, status_code=status_code)
        if status_code == 429 or any(
            marker in classification
            for marker in ("resource_exhausted", "rate limit", "quota")
        ):
            raise RateLimitError(
                message,
                retry_after=retry_after,
                status_code=status_code or 429,
            )
        if "context" in classification and any(
            marker in classification
            for marker in ("token", "length", "limit", "overflow", "exceed")
        ):
            raise ContextOverflowError(message, status_code=status_code or 400)
        raise APIError(message, status_code=status_code)

    @classmethod
    async def _raise_http_error(cls, response: Any) -> None:
        body = await response.aread()
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            payload = None

        error: Any = None
        if isinstance(payload, Mapping):
            error = payload.get("error")
        if error is None:
            text = body.decode("utf-8", errors="replace").strip()
            error = text[:500] or f"HTTP {response.status_code}"

        retry_after_value = response.headers.get("Retry-After")
        retry_after = (
            int(retry_after_value)
            if isinstance(retry_after_value, str) and retry_after_value.isdigit()
            else None
        )
        cls._raise_provider_error(
            error,
            http_status=response.status_code,
            retry_after=retry_after,
        )

    @staticmethod
    def _decode_sse_data(data_lines: list[str]) -> Mapping[str, Any]:
        payload_text = "\n".join(data_lines)
        if payload_text.strip() == "[DONE]":
            raise ResponseParseError("Gemini stream emitted unsupported [DONE] marker")
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise ResponseParseError(f"Invalid Gemini SSE payload: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise ResponseParseError("Gemini SSE payload must be a JSON object")
        return payload

    @classmethod
    async def _iter_sse_payloads(cls, response: Any) -> AsyncIterator[Mapping[str, Any]]:
        data_lines: list[str] = []
        async for line in response.aiter_lines():
            if line == "":
                if data_lines:
                    yield cls._decode_sse_data(data_lines)
                    data_lines = []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                value = line[5:]
                if value.startswith(" "):
                    value = value[1:]
                data_lines.append(value)
        # A clean transport EOF terminates Gemini streams.  The last SSE event
        # need not be followed by an extra blank line.
        if data_lines:
            yield cls._decode_sse_data(data_lines)

    @staticmethod
    def _blocked_prompt(payload: Mapping[str, Any]) -> Optional[str]:
        feedback = payload.get("promptFeedback")
        if not isinstance(feedback, Mapping):
            return None
        reason = str(feedback.get("blockReason") or "").strip()
        if reason and reason not in {"BLOCK_REASON_UNSPECIFIED", "UNSPECIFIED"}:
            detail = str(feedback.get("blockReasonMessage") or "").strip()
            return f"{reason}: {detail}" if detail else reason
        return None

    @staticmethod
    def _candidate(payload: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        candidates = payload.get("candidates")
        if candidates is None:
            return None
        if not isinstance(candidates, list):
            raise ResponseParseError("Gemini candidates must be a list")
        if not candidates:
            return None
        candidate = candidates[0]
        if not isinstance(candidate, Mapping):
            raise ResponseParseError("Gemini candidate must be an object")
        return candidate

    @staticmethod
    def _candidate_parts(candidate: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        content = candidate.get("content")
        if content is None:
            return []
        if not isinstance(content, Mapping):
            raise ResponseParseError("Gemini candidate content must be an object")
        role = content.get("role")
        if role not in (None, "model"):
            raise ResponseParseError("Gemini candidate content role must be 'model'")
        parts = content.get("parts")
        if parts is None:
            return []
        if not isinstance(parts, list) or not all(
            isinstance(part, Mapping) for part in parts
        ):
            raise ResponseParseError("Gemini candidate parts must be a list of objects")
        return parts

    @staticmethod
    def _part_deltas(
        parts: Sequence[Mapping[str, Any]],
        tool_calls: list[dict[str, Any]],
    ) -> tuple[Optional[str], Optional[str]]:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        for part in parts:
            text = part.get("text")
            if text is not None:
                if not isinstance(text, str):
                    raise ResponseParseError("Gemini text part must contain a string")
                if part.get("thought") is True:
                    reasoning_parts.append(text)
                else:
                    content_parts.append(text)

            function_call = part.get("functionCall")
            if function_call is None:
                continue
            if not isinstance(function_call, Mapping):
                raise ResponseParseError("Gemini functionCall must be an object")
            name = function_call.get("name")
            arguments = function_call.get("args", {})
            native_id = function_call.get("id")
            if not isinstance(name, str) or not name:
                raise ResponseParseError("Gemini functionCall.name is required")
            if not isinstance(arguments, Mapping):
                raise ResponseParseError("Gemini functionCall.args must be an object")
            if native_id is not None and (
                not isinstance(native_id, str) or not native_id
            ):
                raise ResponseParseError("Gemini functionCall.id must be a string")
            tool_calls.append(
                {
                    "id": native_id or f"gemini-call-{len(tool_calls)}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": deepcopy(dict(arguments)),
                    },
                }
            )
        return "".join(content_parts) or None, "".join(reasoning_parts) or None

    async def chat_stream(
        self,
        messages: Sequence[CanonicalMessage],
        model: Optional[str] = None,
        tools: Optional[Sequence[CanonicalTool]] = None,
        thinking: bool = False,
        *,
        reasoning_effort: Optional[str] = None,
    ) -> AsyncIterator[StreamChunk]:
        del reasoning_effort  # Gemini reasoning is enabled by thinkingConfig.

        selected_model = model or self.model
        model_id = self._normalize_model(selected_model)
        endpoint = f"models/{model_id}:streamGenerateContent?alt=sse"
        request_body = self._build_request_body(
            messages,
            tools=tools,
            thinking=thinking,
            model=selected_model,
        )

        native_parts: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        latest_usage: Optional[dict[str, int]] = None
        terminal_observed = False
        visible_output_observed = False

        try:
            async with self._create_async_client() as client:
                async with client.stream("POST", endpoint, json=request_body) as response:
                    if not 200 <= response.status_code < 300:
                        await self._raise_http_error(response)

                    async for payload in self._iter_sse_payloads(response):
                        if "error" in payload:
                            self._raise_provider_error(payload.get("error"))
                        blocked = self._blocked_prompt(payload)
                        if blocked is not None:
                            raise APIError(f"Gemini prompt was blocked: {blocked}")

                        usage = self._usage(payload.get("usageMetadata"))
                        if usage is not None:
                            latest_usage = usage

                        candidate = self._candidate(payload)
                        if candidate is None:
                            if usage is not None and not terminal_observed:
                                yield StreamChunk(usage=usage)
                            continue

                        finish_reason_value = candidate.get("finishReason")
                        finish_reason = (
                            str(finish_reason_value).strip()
                            if finish_reason_value is not None
                            else ""
                        )
                        if finish_reason and finish_reason != "STOP":
                            detail = str(candidate.get("finishMessage") or "").strip()
                            suffix = f": {detail}" if detail else ""
                            raise APIError(
                                "Gemini response did not complete normally "
                                f"(finishReason={finish_reason}){suffix}"
                            )
                        if terminal_observed:
                            if finish_reason or self._candidate_parts(candidate):
                                raise ResponseParseError(
                                    "Gemini stream emitted candidate data after its terminal frame"
                                )
                            continue

                        parts = self._candidate_parts(candidate)
                        native_parts.extend(deepcopy([dict(part) for part in parts]))
                        content, reasoning = self._part_deltas(parts, tool_calls)
                        if content or tool_calls:
                            visible_output_observed = True

                        if content is not None or reasoning is not None:
                            yield StreamChunk(
                                content=content,
                                reasoning_content=reasoning,
                                usage=usage,
                            )
                        elif usage is not None and not finish_reason:
                            yield StreamChunk(usage=usage)

                        if finish_reason == "STOP":
                            terminal_observed = True

            if not terminal_observed:
                raise ResponseParseError(
                    "Gemini stream ended before a STOP finishReason"
                )
            if not visible_output_observed:
                raise APIError(
                    "Gemini terminal response contained no assistant content or tool calls"
                )

            normalized_finish = "tool_calls" if tool_calls else "stop"
            yield StreamChunk(
                is_finished=True,
                usage=latest_usage,
                tool_calls=deepcopy(tool_calls) if tool_calls else None,
                finish_reason=normalized_finish,
                provider_state={
                    "protocol": _PROTOCOL,
                    "content": {
                        "role": "model",
                        "parts": deepcopy(native_parts),
                    },
                },
            )
        except httpx.TimeoutException as exc:
            raise APIError(f"Gemini stream timeout: {exc}") from exc
        except httpx.RequestError as exc:
            raise APIError(f"Gemini stream transport error: {exc}") from exc


__all__ = ["GeminiClient"]
