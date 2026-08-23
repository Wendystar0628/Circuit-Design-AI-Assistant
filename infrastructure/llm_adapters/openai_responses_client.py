"""Async adapter for providers exposing the OpenAI Responses protocol.

The Responses API is not Chat Completions with a different URL.  In
particular, function definitions are flat, input images use ``input_image``,
and a tool continuation must return the provider's output items (including
reasoning items) together with ``function_call_output`` items.  This adapter
keeps that protocol boundary explicit instead of translating Responses into
Chat Completions-shaped wire data.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Tuple

import httpx

from infrastructure.llm_adapters.base_client import (
    APIError,
    AuthError,
    BaseLLMClient,
    ContextOverflowError,
    RateLimitError,
    ResponseParseError,
    StreamChunk,
)


class OpenAIResponsesClient(BaseLLMClient):
    """Pure-async OpenAI Responses client used by OpenAI, xAI, and OpenCode."""

    RESPONSES_ENDPOINT = "responses"
    PROTOCOL = "openai_responses"

    def __init__(
        self,
        provider_id: str,
        api_key: str,
        base_url: str,
        model: str,
        timeout: int = 60,
    ):
        super().__init__(
            provider_id=provider_id,
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=timeout,
        )

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _create_async_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._get_headers(),
            timeout=httpx.Timeout(self.timeout, connect=10.0),
        )

    async def close(self) -> None:
        """No-op: each streamed request owns and closes its async client."""

    def _build_request_body(
        self,
        messages: Sequence[Dict[str, Any]],
        model: Optional[str],
        tools: Optional[Sequence[Dict[str, Any]]],
        thinking: bool,
        reasoning_effort: Optional[str],
        *,
        stream: bool,
    ) -> Dict[str, Any]:
        use_model = model or self.model
        if not use_model:
            raise APIError("Model is required")

        instructions, response_input = self._build_response_input(messages)
        body: Dict[str, Any] = {
            "model": use_model,
            "input": response_input,
            "stream": stream,
        }
        resolved_effort = self._reasoning_effort(
            use_model,
            thinking=thinking,
            requested=reasoning_effort,
        )
        if resolved_effort is not None:
            body["reasoning"] = {"effort": resolved_effort}
        if instructions:
            body["instructions"] = instructions
        if tools:
            body["tools"] = self._flatten_function_tools(tools)
        if self.provider_id == "xai":
            # This application replays response.output locally instead of
            # chaining via previous_response_id. xAI requires the encrypted
            # reasoning item to make that stateless continuation lossless.
            body["store"] = False
            body["include"] = ["reasoning.encrypted_content"]
        return body

    def _reasoning_effort(
        self,
        model: str,
        *,
        thinking: bool,
        requested: Optional[str],
    ) -> Optional[str]:
        normalized = str(requested or "").strip().casefold()
        if self.provider_id == "opencode":
            # OpenCode is an aggregation platform and accepts arbitrary model
            # IDs.  With no capability catalog for that user-selected model,
            # omitting reasoning is the only safe default for a normal turn.
            return normalized or ("high" if thinking else None)
        if model == "gpt-5.5-pro":
            if normalized:
                if normalized not in {"medium", "high", "xhigh"}:
                    raise APIError(
                        "gpt-5.5-pro reasoning effort must be medium, high, or xhigh"
                    )
                return normalized
            return "high" if thinking else "medium"
        return normalized or ("high" if thinking else "low")

    def _model_supports_streaming(self, model: str) -> bool:
        try:
            from infrastructure.llm_adapters.provider_catalog import get_model

            spec = get_model(self.provider_id, model)
        except ImportError:
            spec = None
        return bool(spec.streaming) if spec is not None else True

    def _build_response_input(
        self,
        messages: Sequence[Dict[str, Any]],
    ) -> Tuple[str, List[Dict[str, Any]]]:
        instructions: List[str] = []
        response_input: List[Dict[str, Any]] = []

        for message in messages:
            if not isinstance(message, dict):
                raise ResponseParseError("Canonical messages must be objects")

            role = str(message.get("role") or "")
            if role in {"system", "developer"}:
                text = self._content_as_text(message.get("content"))
                if text:
                    instructions.append(text)
                continue

            if role == "assistant":
                provider_state = message.get("provider_state")
                if provider_state is not None:
                    response_input.extend(self._assistant_output_from_state(provider_state))
                    continue
                if message.get("tool_calls"):
                    raise ResponseParseError(
                        "OpenAI Responses tool continuation is missing assistant provider_state"
                    )
                response_input.append(
                    {
                        "role": "assistant",
                        "content": self._message_content_parts(message.get("content")),
                    }
                )
                continue

            if role == "tool":
                call_id = str(message.get("tool_call_id") or "")
                if not call_id:
                    raise ResponseParseError("Tool message is missing tool_call_id")
                response_input.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": self._content_as_text(message.get("content")),
                    }
                )
                continue

            if role == "user":
                response_input.append(
                    {
                        "role": "user",
                        "content": self._message_content_parts(message.get("content")),
                    }
                )
                continue

            raise ResponseParseError(f"Unsupported canonical message role: {role!r}")

        return "\n\n".join(instructions), response_input

    def _assistant_output_from_state(self, provider_state: Any) -> List[Dict[str, Any]]:
        if not isinstance(provider_state, dict):
            raise ResponseParseError("Assistant provider_state must be an object")
        if provider_state.get("protocol") != self.PROTOCOL:
            raise ResponseParseError(
                "Assistant provider_state protocol does not match openai_responses"
            )
        output = provider_state.get("assistant_output")
        if not isinstance(output, list) or not all(isinstance(item, dict) for item in output):
            raise ResponseParseError(
                "OpenAI Responses provider_state must contain assistant_output items"
            )
        # Do not normalize, filter, or reconstruct these items. Reasoning models
        # require the exact output items in the next request's input.
        return output

    def _message_content_parts(self, content: Any) -> List[Dict[str, Any]]:
        if isinstance(content, str):
            return [{"type": "input_text", "text": content}]
        if content is None:
            return [{"type": "input_text", "text": ""}]
        if not isinstance(content, list):
            return [{"type": "input_text", "text": str(content)}]

        parts: List[Dict[str, Any]] = []
        for part in content:
            if isinstance(part, str):
                parts.append({"type": "input_text", "text": part})
                continue
            if not isinstance(part, dict):
                raise ResponseParseError("Canonical message content parts must be objects")

            part_type = part.get("type")
            if part_type in {"text", "input_text"}:
                text = part.get("text")
                if not isinstance(text, str):
                    raise ResponseParseError("Text content part is missing text")
                parts.append({"type": "input_text", "text": text})
                continue

            if part_type in {"image_url", "input_image"}:
                parts.append(self._image_content_part(part))
                continue

            raise ResponseParseError(
                f"Unsupported canonical content part type: {part_type!r}"
            )

        return parts or [{"type": "input_text", "text": ""}]

    def _image_content_part(self, part: Dict[str, Any]) -> Dict[str, Any]:
        raw_image = part.get("image_url")
        detail = part.get("detail")
        if isinstance(raw_image, dict):
            image_url = raw_image.get("url")
            detail = detail or raw_image.get("detail")
        else:
            image_url = raw_image

        result: Dict[str, Any] = {"type": "input_image"}
        if isinstance(image_url, str) and image_url:
            result["image_url"] = image_url
        elif isinstance(part.get("file_id"), str) and part["file_id"]:
            result["file_id"] = part["file_id"]
        else:
            raise ResponseParseError("Image content part is missing image_url or file_id")
        if isinstance(detail, str) and detail:
            result["detail"] = detail
        return result

    def _content_as_text(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return str(content)

        fragments: List[str] = []
        for part in content:
            if isinstance(part, str):
                fragments.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                fragments.append(part["text"])
        return "".join(fragments)

    def _flatten_function_tools(
        self,
        tools: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        flattened: List[Dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict) or tool.get("type") != "function":
                raise ResponseParseError("OpenAI Responses adapter accepts function tools only")
            function = tool.get("function")
            if not isinstance(function, dict):
                raise ResponseParseError("Function tool is missing its function schema")
            name = function.get("name")
            parameters = function.get("parameters")
            if not isinstance(name, str) or not name:
                raise ResponseParseError("Function tool is missing function.name")
            if not isinstance(parameters, dict):
                raise ResponseParseError(
                    f"Function tool {name!r} is missing function.parameters"
                )

            wire_tool: Dict[str, Any] = {
                "type": "function",
                "name": name,
                "parameters": parameters,
            }
            description = function.get("description")
            if isinstance(description, str) and description:
                wire_tool["description"] = description
            if isinstance(function.get("strict"), bool):
                wire_tool["strict"] = function["strict"]
            flattened.append(wire_tool)
        return flattened

    def _completed_result(
        self,
        response_payload: Dict[str, Any],
        function_items: Dict[int, Dict[str, Any]],
    ) -> Tuple[
        List[Dict[str, Any]],
        Optional[List[Dict[str, Any]]],
        Optional[Dict[str, Any]],
        Dict[str, Any],
    ]:
        output = response_payload.get("output")
        if not isinstance(output, list) or not all(
            isinstance(item, dict) for item in output
        ):
            raise ResponseParseError("Completed response is missing response.output items")

        usage = response_payload.get("usage")
        if usage is not None and not isinstance(usage, dict):
            raise ResponseParseError("Completed response contains malformed usage")

        tool_calls = self._canonical_tool_calls(output, function_items)
        provider_state = {
            "protocol": self.PROTOCOL,
            "assistant_output": output,
        }
        return output, tool_calls, self._normalize_usage(usage), provider_state

    @staticmethod
    def _visible_output(output: List[Dict[str, Any]]) -> Tuple[str, str]:
        content_parts: List[str] = []
        reasoning_parts: List[str] = []

        for item in output:
            item_type = item.get("type")
            if item_type == "message":
                content = item.get("content")
                if not isinstance(content, list):
                    raise ResponseParseError(
                        "Completed Responses message output is missing content"
                    )
                for part in content:
                    if not isinstance(part, dict):
                        raise ResponseParseError(
                            "Completed Responses message content must contain objects"
                        )
                    if part.get("type") == "output_text":
                        text = part.get("text")
                    elif part.get("type") == "refusal":
                        text = part.get("refusal")
                    else:
                        continue
                    if not isinstance(text, str):
                        raise ResponseParseError(
                            "Completed Responses message content is missing text"
                        )
                    content_parts.append(text)
                continue

            if item_type != "reasoning":
                continue
            for field in ("summary", "content"):
                blocks = item.get(field)
                if blocks is None:
                    continue
                if not isinstance(blocks, list):
                    raise ResponseParseError(
                        f"Completed Responses reasoning.{field} must be a list"
                    )
                for block in blocks:
                    if not isinstance(block, dict):
                        raise ResponseParseError(
                            f"Completed Responses reasoning.{field} must contain objects"
                        )
                    text = block.get("text")
                    if isinstance(text, str):
                        reasoning_parts.append(text)

        return "".join(content_parts), "".join(reasoning_parts)

    async def chat_stream(
        self,
        messages: Sequence[Dict[str, Any]],
        model: Optional[str] = None,
        tools: Optional[Sequence[Dict[str, Any]]] = None,
        thinking: bool = False,
        *,
        reasoning_effort: Optional[str] = None,
    ) -> AsyncIterator[StreamChunk]:
        use_model = model or self.model
        if not use_model:
            raise APIError("Model is required")
        supports_streaming = self._model_supports_streaming(use_model)
        body = self._build_request_body(
            messages,
            use_model,
            tools,
            thinking,
            reasoning_effort,
            stream=supports_streaming,
        )
        function_items: Dict[int, Dict[str, Any]] = {}

        try:
            async with self._create_async_client() as client:
                if not supports_streaming:
                    response = await client.post(
                        self.RESPONSES_ENDPOINT,
                        json=body,
                    )
                    if response.status_code < 200 or response.status_code >= 300:
                        await self._raise_http_error(response)
                    response_payload = self._decode_json_response(response)
                    status = response_payload.get("status")
                    if status == "failed" or response_payload.get("error") is not None:
                        self._raise_payload_error(
                            response_payload,
                            prefix=f"{self.provider_id} Responses request failed",
                        )
                    if status == "incomplete":
                        details = response_payload.get("incomplete_details")
                        reason = (
                            details.get("reason") if isinstance(details, dict) else None
                        )
                        raise APIError(
                            f"{self.provider_id} Responses request ended incomplete"
                            + (f": {reason}" if reason else "")
                        )
                    if status != "completed":
                        raise ResponseParseError(
                            "Non-streaming Responses request ended without completed status"
                        )

                    output, tool_calls, usage, provider_state = self._completed_result(
                        response_payload,
                        function_items,
                    )
                    content, reasoning_content = self._visible_output(output)
                    if content or reasoning_content:
                        yield StreamChunk(
                            content=content or None,
                            reasoning_content=reasoning_content or None,
                        )
                    yield self._terminal_chunk(
                        tool_calls=tool_calls,
                        usage=usage,
                        finish_reason="tool_calls" if tool_calls else "stop",
                        provider_state=provider_state,
                    )
                    return

                async with client.stream(
                    "POST",
                    self.RESPONSES_ENDPOINT,
                    json=body,
                ) as response:
                    if response.status_code < 200 or response.status_code >= 300:
                        await self._raise_http_error(response)

                    async for event_name, data in self._iter_sse_events(response):
                        event = self._decode_sse_event(event_name, data)
                        event_type = str(event.get("type") or event_name or "")

                        if event_type == "response.output_text.delta":
                            delta = event.get("delta")
                            if not isinstance(delta, str):
                                raise ResponseParseError(
                                    "response.output_text.delta is missing a string delta"
                                )
                            if delta:
                                yield StreamChunk(content=delta)
                            continue

                        if event_type == "response.refusal.delta":
                            delta = event.get("delta")
                            if not isinstance(delta, str):
                                raise ResponseParseError(
                                    "response.refusal.delta is missing a string delta"
                                )
                            if delta:
                                # Canonical StreamChunk has no separate refusal
                                # lane. Preserve the provider's explanation as
                                # visible assistant content instead of turning a
                                # valid safety response into an empty terminal.
                                yield StreamChunk(content=delta)
                            continue

                        if event_type in {
                            "response.reasoning_text.delta",
                            "response.reasoning_summary_text.delta",
                        }:
                            delta = event.get("delta")
                            if not isinstance(delta, str):
                                raise ResponseParseError(
                                    f"{event_type} is missing a string delta"
                                )
                            if delta:
                                yield StreamChunk(reasoning_content=delta)
                            continue

                        if event_type == "response.output_item.added":
                            self._record_output_item(function_items, event)
                            continue

                        if event_type == "response.function_call_arguments.delta":
                            self._record_function_arguments_delta(function_items, event)
                            continue

                        if event_type == "response.function_call_arguments.done":
                            self._record_function_arguments_done(function_items, event)
                            continue

                        if event_type == "response.output_item.done":
                            self._record_output_item(function_items, event)
                            continue

                        if event_type == "response.completed":
                            response_payload = self._response_payload(event, "completed")
                            _, tool_calls, usage, provider_state = (
                                self._completed_result(
                                    response_payload,
                                    function_items,
                                )
                            )
                            yield self._terminal_chunk(
                                tool_calls=tool_calls,
                                usage=usage,
                                finish_reason="tool_calls" if tool_calls else "stop",
                                provider_state=provider_state,
                            )
                            return

                        if event_type == "response.failed":
                            response_payload = self._response_payload(event, "failed")
                            self._raise_payload_error(
                                response_payload,
                                prefix=f"{self.provider_id} Responses request failed",
                            )

                        if event_type == "response.incomplete":
                            response_payload = self._response_payload(event, "incomplete")
                            details = response_payload.get("incomplete_details")
                            reason = details.get("reason") if isinstance(details, dict) else None
                            raise APIError(
                                f"{self.provider_id} Responses request ended incomplete"
                                + (f": {reason}" if reason else "")
                            )

                        if event_type == "error":
                            self._raise_payload_error(
                                event,
                                prefix=f"{self.provider_id} Responses stream error",
                            )

                    raise ResponseParseError(
                        f"{self.provider_id} Responses stream ended before response.completed"
                    )
        except httpx.TimeoutException as exc:
            raise APIError(f"Responses stream timeout: {exc}") from exc
        except httpx.RequestError as exc:
            raise APIError(f"Responses stream error: {exc}") from exc

    async def _iter_sse_events(
        self,
        response: httpx.Response,
    ) -> AsyncIterator[Tuple[Optional[str], str]]:
        event_name: Optional[str] = None
        data_lines: List[str] = []

        async for raw_line in response.aiter_lines():
            line = raw_line.rstrip("\r")
            if not line:
                if data_lines:
                    yield event_name, "\n".join(data_lines)
                event_name = None
                data_lines = []
                continue
            if line.startswith(":"):
                continue

            field, separator, value = line.partition(":")
            if not separator:
                value = ""
            elif value.startswith(" "):
                value = value[1:]
            if field == "event":
                event_name = value
            elif field == "data":
                data_lines.append(value)

        if data_lines:
            yield event_name, "\n".join(data_lines)

    def _decode_sse_event(
        self,
        event_name: Optional[str],
        data: str,
    ) -> Dict[str, Any]:
        if data.strip() == "[DONE]":
            raise ResponseParseError(
                "OpenAI Responses streams must terminate with response.completed, not [DONE]"
            )
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ResponseParseError(f"Invalid Responses SSE payload: {exc}") from exc
        if not isinstance(payload, dict):
            raise ResponseParseError("Responses SSE payload must be a JSON object")
        if not payload.get("type") and not event_name:
            raise ResponseParseError("Responses SSE event is missing its event type")
        return payload

    @staticmethod
    def _decode_json_response(response: httpx.Response) -> Dict[str, Any]:
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ResponseParseError(
                f"Invalid non-streaming Responses payload: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise ResponseParseError(
                "Non-streaming Responses payload must be a JSON object"
            )
        return payload

    def _record_output_item(
        self,
        accumulator: Dict[int, Dict[str, Any]],
        event: Dict[str, Any],
    ) -> None:
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "function_call":
            return
        index = self._output_index(event, len(accumulator))
        current = accumulator.setdefault(
            index,
            {"item_id": "", "call_id": "", "name": "", "arguments": ""},
        )
        if item.get("id"):
            current["item_id"] = str(item["id"])
        if item.get("call_id"):
            current["call_id"] = str(item["call_id"])
        if item.get("name"):
            current["name"] = str(item["name"])
        if isinstance(item.get("arguments"), str):
            current["arguments"] = item["arguments"]

    def _record_function_arguments_delta(
        self,
        accumulator: Dict[int, Dict[str, Any]],
        event: Dict[str, Any],
    ) -> None:
        delta = event.get("delta")
        if not isinstance(delta, str):
            raise ResponseParseError(
                "response.function_call_arguments.delta is missing a string delta"
            )
        current = self._function_item_for_event(accumulator, event)
        current["arguments"] += delta

    def _record_function_arguments_done(
        self,
        accumulator: Dict[int, Dict[str, Any]],
        event: Dict[str, Any],
    ) -> None:
        arguments = event.get("arguments")
        if not isinstance(arguments, str):
            raise ResponseParseError(
                "response.function_call_arguments.done is missing arguments"
            )
        current = self._function_item_for_event(accumulator, event)
        current["arguments"] = arguments
        if event.get("name"):
            current["name"] = str(event["name"])

    def _function_item_for_event(
        self,
        accumulator: Dict[int, Dict[str, Any]],
        event: Dict[str, Any],
    ) -> Dict[str, Any]:
        item_id = str(event.get("item_id") or "")
        for current in accumulator.values():
            if item_id and current.get("item_id") == item_id:
                return current
        index = self._output_index(event, len(accumulator))
        return accumulator.setdefault(
            index,
            {
                "item_id": item_id,
                "call_id": "",
                "name": "",
                "arguments": "",
            },
        )

    @staticmethod
    def _output_index(event: Dict[str, Any], default: int) -> int:
        index = event.get("output_index")
        return index if isinstance(index, int) and index >= 0 else default

    def _canonical_tool_calls(
        self,
        output: List[Dict[str, Any]],
        streamed: Dict[int, Dict[str, Any]],
    ) -> Optional[List[Dict[str, Any]]]:
        calls: List[Dict[str, Any]] = []
        for index, item in enumerate(output):
            if item.get("type") != "function_call":
                continue
            streamed_item = streamed.get(index, {})
            call_id = str(item.get("call_id") or streamed_item.get("call_id") or "")
            name = str(item.get("name") or streamed_item.get("name") or "")
            arguments = item.get("arguments")
            if not isinstance(arguments, str):
                arguments = streamed_item.get("arguments")
            if not call_id or not name or not isinstance(arguments, str):
                raise ResponseParseError(
                    "Completed Responses function_call is missing call_id, name, or arguments"
                )
            calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": arguments,
                    },
                }
            )
        return calls or None

    def _terminal_chunk(
        self,
        *,
        tool_calls: Optional[List[Dict[str, Any]]],
        usage: Optional[Dict[str, Any]],
        finish_reason: str,
        provider_state: Dict[str, Any],
    ) -> StreamChunk:
        return StreamChunk(
            is_finished=True,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=finish_reason,
            provider_state=provider_state,
        )

    @staticmethod
    def _normalize_usage(usage: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(usage, dict):
            return None

        normalized: Dict[str, Any] = {}
        for source, target in (
            ("input_tokens", "prompt_tokens"),
            ("output_tokens", "completion_tokens"),
            ("total_tokens", "total_tokens"),
        ):
            value = usage.get(source)
            if isinstance(value, int) and not isinstance(value, bool):
                normalized[target] = value

        input_details = usage.get("input_tokens_details")
        if isinstance(input_details, dict):
            cached_tokens = input_details.get("cached_tokens")
            if isinstance(cached_tokens, int) and not isinstance(cached_tokens, bool):
                normalized["cached_tokens"] = cached_tokens
            cache_write_tokens = input_details.get("cache_write_tokens")
            if isinstance(cache_write_tokens, int) and not isinstance(
                cache_write_tokens, bool
            ):
                normalized["cache_write_tokens"] = cache_write_tokens

        output_details = usage.get("output_tokens_details")
        if isinstance(output_details, dict):
            reasoning_tokens = output_details.get("reasoning_tokens")
            if isinstance(reasoning_tokens, int) and not isinstance(reasoning_tokens, bool):
                normalized["reasoning_tokens"] = reasoning_tokens

        return normalized or None

    @staticmethod
    def _response_payload(event: Dict[str, Any], expected_status: str) -> Dict[str, Any]:
        response = event.get("response")
        if not isinstance(response, dict):
            raise ResponseParseError(f"response.{expected_status} is missing response")
        status = response.get("status")
        if status is not None and status != expected_status:
            raise ResponseParseError(
                f"response.{expected_status} carried unexpected status {status!r}"
            )
        return response

    async def _raise_http_error(self, response: httpx.Response) -> None:
        body = await response.aread()
        text = body.decode("utf-8", errors="replace")[:1000]
        payload: Any = None
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            pass

        message = text or f"HTTP {response.status_code}"
        error_code = ""
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                error_code = str(error.get("code") or error.get("type") or "")
                message = str(error.get("message") or message)
            elif isinstance(error, str):
                message = error

        status = response.status_code
        classification = f"{error_code} {message}".lower()
        if status in {401, 403}:
            raise AuthError(message)
        if status == 429:
            retry_after = response.headers.get("Retry-After")
            retry_seconds = int(retry_after) if retry_after and retry_after.isdigit() else None
            raise RateLimitError(message, retry_after=retry_seconds)
        if self._is_context_error(classification):
            raise ContextOverflowError(message)
        raise APIError(message, status_code=status)

    def _raise_payload_error(self, payload: Dict[str, Any], *, prefix: str) -> None:
        error: Any = payload.get("error")
        if error is None and isinstance(payload.get("response"), dict):
            error = payload["response"].get("error")

        if isinstance(error, dict):
            code = str(error.get("code") or error.get("type") or "")
            detail = str(error.get("message") or "Unknown provider error")
        elif isinstance(error, str):
            code = ""
            detail = error
        else:
            code = str(payload.get("code") or "")
            detail = str(payload.get("message") or "Unknown provider error")

        message = f"{prefix}{f' [{code}]' if code else ''}: {detail}"
        classification = f"{code} {detail}".lower()
        if any(
            marker in classification
            for marker in ("authentication", "unauthorized", "invalid_api_key", "api key", "permission")
        ):
            raise AuthError(message)
        if "rate" in classification or "quota" in classification:
            raise RateLimitError(message)
        if self._is_context_error(classification):
            raise ContextOverflowError(message)
        raise APIError(message)

    @staticmethod
    def _is_context_error(classification: str) -> bool:
        return any(
            marker in classification
            for marker in (
                "context_length_exceeded",
                "context_window_exceeded",
                "prompt_too_long",
                "context limit",
                "context length",
            )
        )


__all__ = ["OpenAIResponsesClient"]
