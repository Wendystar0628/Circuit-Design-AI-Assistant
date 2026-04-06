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
        self._client: Optional[httpx.AsyncClient] = None
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

    async def _get_async_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._get_headers(),
                timeout=httpx.Timeout(self.timeout, connect=10.0),
            )
        return self._client

    def __del__(self):
        if self._sync_client:
            try:
                self._sync_client.close()
            except Exception:
                pass

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
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
        **kwargs,
    ) -> Dict[str, Any]:
        use_model = model or self.model
        if not use_model:
            raise APIError("Model is required")

        request_body: Dict[str, Any] = {
            "model": use_model,
            "messages": messages,
            "stream": stream,
        }
        if tools:
            request_body["tools"] = tools

        for key, value in kwargs.items():
            if value is not None:
                request_body[key] = value

        if thinking and self.supports_thinking(use_model):
            request_body.setdefault("temperature", 0.6)

        return request_body

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
        )

    def chat(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        streaming: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
        thinking: bool = False,
        **kwargs,
    ) -> ChatResponse:
        request_body = self._build_request_body(messages, model, False, tools, thinking, **kwargs)
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
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        request_body = self._build_request_body(messages, model, True, tools, thinking, **kwargs)
        client = await self._get_async_client()
        response: Optional[httpx.Response] = None
        accumulated_tool_calls: Dict[int, Dict[str, Any]] = {}
        try:
            response = await client.send(
                client.build_request("POST", self.CHAT_ENDPOINT, json=request_body),
                stream=True,
            )
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
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue
                payload_text = line[5:].strip()
                if not payload_text:
                    continue
                if payload_text == "[DONE]":
                    yield StreamChunk(
                        is_finished=True,
                        tool_calls=self._finalize_tool_calls(accumulated_tool_calls),
                    )
                    break
                try:
                    payload = json.loads(payload_text)
                except json.JSONDecodeError as exc:
                    raise ResponseParseError(f"Invalid streaming payload: {exc}") from exc

                choices = payload.get("choices")
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                    continue
                choice = choices[0]
                delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
                self._merge_tool_call_delta(accumulated_tool_calls, delta.get("tool_calls"))

                content = self._extract_text(delta.get("content"))
                reasoning_content = self._extract_text(delta.get("reasoning_content"))
                if reasoning_content is None:
                    reasoning_content = self._extract_text(delta.get("reasoning"))

                finish_reason = choice.get("finish_reason")
                usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
                if content or reasoning_content or finish_reason or usage:
                    yield StreamChunk(
                        content=content,
                        reasoning_content=reasoning_content,
                        is_finished=bool(finish_reason),
                        usage=usage,
                        tool_calls=self._finalize_tool_calls(accumulated_tool_calls) if finish_reason else None,
                        finish_reason=finish_reason,
                    )
        except httpx.TimeoutException as exc:
            raise APIError(f"Stream timeout: {exc}") from exc
        except httpx.RequestError as exc:
            raise APIError(f"Stream error: {exc}") from exc
        finally:
            if response is not None:
                await response.aclose()

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
