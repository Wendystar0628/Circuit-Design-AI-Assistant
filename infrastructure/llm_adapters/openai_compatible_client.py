import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from infrastructure.llm_adapters.base_client import (
    APIError,
    AuthError,
    BaseLLMClient,
    ChatResponse,
    ContextOverflowError,
    ModelInfo,
    RateLimitError,
    ResponseParseError,
    StreamChunk,
)


_DEFAULT_CONTEXT_LIMIT = 128_000


class OpenAICompatibleClient(BaseLLMClient):
    CHAT_ENDPOINT = "/chat/completions"

    def __init__(
        self,
        provider_id: str,
        api_key: str,
        base_url: str,
        model: str,
        timeout: int = 60,
        auth_header: str = "Authorization",
        auth_prefix: str = "Bearer",
    ):
        super().__init__(api_key=api_key, base_url=base_url, model=model, timeout=timeout)
        self.provider_id = provider_id
        self.auth_header = auth_header
        self.auth_prefix = auth_prefix
        self._logger = logging.getLogger(__name__)
        self._sync_client: Optional[httpx.Client] = None

    def _get_headers(self) -> Dict[str, str]:
        auth_value = self.api_key
        if self.auth_prefix:
            auth_value = f"{self.auth_prefix} {self.api_key}"
        return {
            "Content-Type": "application/json",
            self.auth_header: auth_value,
        }

    def _get_sync_client(self) -> httpx.Client:
        if self._sync_client is None:
            self._sync_client = httpx.Client(
                base_url=self.base_url,
                headers=self._get_headers(),
                timeout=httpx.Timeout(self.timeout, connect=10.0),
            )
        return self._sync_client

    def _create_async_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._get_headers(),
            timeout=httpx.Timeout(self.timeout, connect=10.0),
        )

    def __del__(self):
        if self._sync_client:
            try:
                self._sync_client.close()
            except Exception:
                pass

    async def close(self) -> None:
        if self._sync_client is not None:
            self._sync_client.close()
            self._sync_client = None

    def _build_request_body(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str],
        stream: bool,
        tools: Optional[List[Dict[str, Any]]],
        thinking: bool,
    ) -> Dict[str, Any]:
        """Build an OpenAI-compatible request body.

        Deliberately **no** ``**kwargs`` fallthrough: any new wire
        parameter must be added as an explicit named argument so
        unknown fields cannot silently leak into the request payload
        and break the provider's schema (the previous design let
        ``stop_requested`` bleed all the way into the JSON body).
        """
        use_model = model or self.model
        if not use_model:
            raise APIError("Model is required")

        actual_model = self._resolve_model_for_messages(use_model, messages)

        request_body: Dict[str, Any] = {
            "model": actual_model,
            "messages": messages,
            "stream": stream,
        }
        if tools:
            request_body["tools"] = tools

        if thinking and self.supports_thinking(actual_model):
            request_body.setdefault("temperature", 0.6)

        if self.supports_thinking(actual_model):
            if self.provider_id == "qwen":
                request_body["enable_thinking"] = bool(thinking)
            elif self.provider_id == "deepseek":
                request_body["thinking"] = {
                    "type": "enabled" if thinking else "disabled"
                }
                # DeepSeek V4+ 支持 reasoning_effort 参数控制推理强度
                if thinking:
                    reasoning_effort = self._resolve_reasoning_effort(actual_model)
                    if reasoning_effort:
                        request_body["reasoning_effort"] = reasoning_effort

        tool_names = []
        for tool in request_body.get("tools", []) or []:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") == "function":
                function_def = tool.get("function", {})
                tool_names.append(str(function_def.get("name", "") or ""))
            else:
                tool_names.append(str(tool.get("type", "") or ""))

        self._logger.debug(
            f"Built request: provider={self.provider_id}, model={actual_model}, stream={stream}, "
            f"thinking={thinking}, tool_count={len(tool_names)}, tools={tool_names}"
        )

        return request_body

    def _resolve_model_for_messages(
        self,
        model_name: str,
        messages: List[Dict[str, Any]],
    ) -> str:
        try:
            from shared.model_registry import ModelRegistry

            has_images = any(self._message_contains_images(message) for message in messages)
            if not has_images:
                return model_name

            ModelRegistry.initialize()
            resolved_model_id = ModelRegistry.resolve_model_for_content(
                f"{self.provider_id}:{model_name}",
                has_images=True,
            )
            if not isinstance(resolved_model_id, str) or not resolved_model_id:
                return model_name
            return resolved_model_id.split(":", 1)[-1]
        except Exception:
            return model_name

    def _resolve_reasoning_effort(self, model_name: str) -> Optional[str]:
        """Resolve the ``reasoning_effort`` value for a DeepSeek V4+ model.

        Looks up the model config to get the configured reasoning_effort.
        Falls back to ``"high"`` for DeepSeek V4+ models when the config
        does not specify an explicit value.

        Returns ``None`` for non-DeepSeek providers or models that don't
        support thinking — the parameter should then be omitted from the
        request body entirely.
        """
        if self.provider_id != "deepseek":
            return None
        try:
            from shared.model_registry import ModelRegistry

            ModelRegistry.initialize()
            model_config = ModelRegistry.get_model(f"{self.provider_id}:{model_name}")
            if model_config is not None:
                # Use the configured reasoning_effort if explicitly set
                if model_config.reasoning_effort:
                    return model_config.reasoning_effort
                # Default to "high" for any DeepSeek model that supports thinking
                if model_config.supports_thinking:
                    return "high"
        except Exception:
            pass
        # Sensible default for DeepSeek thinking mode
        return "high"

    def _message_contains_images(self, message: Dict[str, Any]) -> bool:
        content = message.get("content")
        if not isinstance(content, list):
            return False

        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "image_url":
                return True
        return False

    def _extract_text(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts: List[str] = []
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                    continue
                text_value = item.get("text")
                if isinstance(text_value, dict) and isinstance(text_value.get("value"), str):
                    parts.append(text_value["value"])
            return "".join(parts) if parts else None
        return str(value)

    def _handle_http_error(self, response: httpx.Response) -> None:
        message = response.text[:500]
        status = response.status_code
        if status in (401, 403):
            raise AuthError(message or "Authentication failed")
        if status == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimitError(message or "Rate limit exceeded", int(retry_after) if retry_after and retry_after.isdigit() else None)
        lowered = message.lower()
        if "context" in lowered and ("limit" in lowered or "length" in lowered):
            raise ContextOverflowError(message)
        raise APIError(message or f"HTTP {status}", status_code=status)

    def _raise_stream_payload_error(self, payload: Dict[str, Any]) -> None:
        """Raise a typed client error carried inside a successful SSE response."""
        error = payload.get("error")
        if isinstance(error, str):
            error_code = ""
            error_message = error or "Unknown API error"
        elif isinstance(error, dict):
            error_code = str(error.get("code") or error.get("type") or "")
            error_message = str(error.get("message") or "Unknown API error")
        else:
            raise ResponseParseError(
                f"Malformed {self.provider_id} streaming error payload"
            )

        prefix = f"{self.provider_id} stream API error"
        detail = f" [{error_code}]" if error_code else ""
        message = f"{prefix}{detail}: {error_message}"
        classification = f"{error_code} {error_message}".lower()

        if any(marker in classification for marker in ("auth", "unauthorized", "api key", "permission")):
            raise AuthError(message)
        if "rate" in classification or "quota" in classification:
            raise RateLimitError(message)
        if "context" in classification and any(
            marker in classification for marker in ("limit", "length", "overflow", "exceed", "token")
        ):
            raise ContextOverflowError(message)
        raise APIError(message)

    def _parse_chat_response(self, payload: Dict[str, Any]) -> ChatResponse:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ResponseParseError("Missing choices in response")

        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        content = self._extract_text(message.get("content")) or ""
        reasoning_content = self._extract_text(message.get("reasoning_content"))
        if reasoning_content is None:
            reasoning_content = self._extract_text(message.get("reasoning"))

        tool_calls = message.get("tool_calls")
        return ChatResponse(
            content=content,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls if isinstance(tool_calls, list) else None,
            usage=payload.get("usage") if isinstance(payload.get("usage"), dict) else None,
            finish_reason=choice.get("finish_reason"),
            metadata=self._parse_metadata(payload),
        )

    def _parse_metadata(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        metadata: Dict[str, Any] = {}

        web_search = payload.get("web_search")
        if isinstance(web_search, list):
            metadata["web_search_results"] = [
                item for item in web_search if isinstance(item, dict)
            ]

        search_info = payload.get("search_info")
        if isinstance(search_info, dict):
            raw_results = search_info.get("search_results")
            if isinstance(raw_results, list):
                metadata["web_search_results"] = [
                    item for item in raw_results if isinstance(item, dict)
                ]

        return metadata or None

    def chat(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        streaming: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
        thinking: bool = False,
    ) -> ChatResponse:
        request_body = self._build_request_body(messages, model, False, tools, thinking)
        client = self._get_sync_client()
        try:
            response = client.post(self.CHAT_ENDPOINT, json=request_body)
            if response.status_code != 200:
                self._handle_http_error(response)
            return self._parse_chat_response(response.json())
        except httpx.TimeoutException as exc:
            raise APIError(f"Request timeout: {exc}") from exc
        except httpx.RequestError as exc:
            raise APIError(f"Request error: {exc}") from exc

    def _merge_tool_call_delta(
        self,
        accumulator: Dict[int, Dict[str, Any]],
        tool_call_deltas: Any,
    ) -> None:
        if not isinstance(tool_call_deltas, list):
            return
        for delta in tool_call_deltas:
            if not isinstance(delta, dict):
                continue
            index = delta.get("index", 0)
            if not isinstance(index, int):
                index = 0
            current = accumulator.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            if delta.get("id"):
                current["id"] = delta["id"]
            if delta.get("type"):
                current["type"] = delta["type"]
            function_delta = delta.get("function") if isinstance(delta.get("function"), dict) else {}
            if function_delta.get("name"):
                current["function"]["name"] += function_delta["name"]
            if function_delta.get("arguments"):
                current["function"]["arguments"] += function_delta["arguments"]

    def _finalize_tool_calls(self, accumulator: Dict[int, Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
        if not accumulator:
            return None
        return [accumulator[index] for index in sorted(accumulator.keys())]

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        thinking: bool = False,
    ) -> AsyncIterator[StreamChunk]:
        """Stream chat chunks from an OpenAI-compatible endpoint.

        This method is **stop-agnostic** — see
        ``BaseLLMClient.chat_stream`` for the cancellation contract.
        The caller cancels the owning ``asyncio.Task``; the resulting
        ``CancelledError`` unwinds through the ``async with`` stack
        below via normal exception propagation, and httpx cleans up
        the connection under ``AsyncShieldCancellation``.
        """
        request_body = self._build_request_body(messages, model, True, tools, thinking)
        accumulated_tool_calls: Dict[int, Dict[str, Any]] = {}
        terminal_frame_observed = False
        try:
            async with self._create_async_client() as client:
                async with client.stream("POST", self.CHAT_ENDPOINT, json=request_body) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        error_response = httpx.Response(
                            status_code=response.status_code,
                            headers=response.headers,
                            request=response.request,
                            content=body,
                        )
                        self._handle_http_error(error_response)

                    async for line in response.aiter_lines():
                        stream_chunk = self._parse_sse_line(line, accumulated_tool_calls)
                        if stream_chunk is not None:
                            if stream_chunk.is_finished:
                                terminal_frame_observed = True
                            yield stream_chunk
                    if not terminal_frame_observed:
                        raise ResponseParseError(
                            f"{self.provider_id} stream ended before a terminal frame"
                        )
        except httpx.TimeoutException as exc:
            raise APIError(f"Stream timeout: {exc}") from exc
        except httpx.RequestError as exc:
            raise APIError(f"Stream error: {exc}") from exc

    def _parse_sse_line(
        self,
        line: str,
        accumulated_tool_calls: Dict[int, Dict[str, Any]],
    ) -> Optional[StreamChunk]:
        """Parse a single SSE ``data: ...`` line into a ``StreamChunk``.

        Returns ``None`` for lines that don't carry a streamable
        delta (keep-alives, empty lines, non-``data:`` comments).
        Tool-call deltas are accumulated into ``accumulated_tool_calls``
        so the caller sees a complete ``tool_calls`` list on the
        finish-reason chunk.
        """
        if not line:
            return None
        if not line.startswith("data:"):
            return None
        payload_text = line[5:].strip()
        if not payload_text:
            return None
        if payload_text == "[DONE]":
            return StreamChunk(
                is_finished=True,
                tool_calls=self._finalize_tool_calls(accumulated_tool_calls),
            )
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise ResponseParseError(f"Invalid streaming payload: {exc}") from exc

        if not isinstance(payload, dict):
            raise ResponseParseError("Streaming payload must be a JSON object")
        if "error" in payload:
            self._raise_stream_payload_error(payload)

        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            if usage is not None:
                return StreamChunk(usage=usage)
            return None
        choice = choices[0]
        delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
        self._merge_tool_call_delta(accumulated_tool_calls, delta.get("tool_calls"))

        content = self._extract_text(delta.get("content"))
        reasoning_content = self._extract_text(delta.get("reasoning_content"))
        if reasoning_content is None:
            reasoning_content = self._extract_text(delta.get("reasoning"))

        finish_reason = choice.get("finish_reason")
        if not (content or reasoning_content or finish_reason or usage):
            return None
        return StreamChunk(
            content=content,
            reasoning_content=reasoning_content,
            is_finished=bool(finish_reason),
            usage=usage,
            tool_calls=self._finalize_tool_calls(accumulated_tool_calls) if finish_reason else None,
            finish_reason=finish_reason,
        )

    def get_model_info(self, model: Optional[str] = None) -> ModelInfo:
        use_model = model or self.model
        try:
            from shared.model_registry import ModelRegistry
            model_config = ModelRegistry.get_model(f"{self.provider_id}:{use_model}")
            if model_config:
                return ModelInfo(
                    name=model_config.name,
                    context_limit=model_config.context_limit,
                    supports_vision=model_config.supports_vision,
                    supports_tools=model_config.supports_tools,
                    supports_thinking=model_config.supports_thinking,
                )
        except Exception:
            pass
        return ModelInfo(
            name=use_model or "",
            context_limit=_DEFAULT_CONTEXT_LIMIT,
            supports_vision=False,
            supports_tools=True,
            supports_thinking=False,
        )


__all__ = ["OpenAICompatibleClient"]
