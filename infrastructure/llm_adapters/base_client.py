"""Canonical asynchronous contract for chat-completion providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Mapping, Optional, Sequence


class LLMError(Exception):
    """Base error raised by the LLM transport boundary."""


class APIError(LLMError):
    """The provider rejected a request or the request could not be sent."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class AuthError(APIError):
    """The provider rejected the configured credential."""


class RateLimitError(APIError):
    """The provider rate-limited the request."""

    def __init__(
        self,
        message: str,
        retry_after: Optional[int] = None,
        status_code: Optional[int] = 429,
    ):
        super().__init__(message, status_code=status_code)
        self.retry_after = retry_after


class ContextOverflowError(APIError):
    """The request exceeded the provider's context window."""

    def __init__(
        self,
        message: str,
        max_tokens: Optional[int] = None,
        status_code: Optional[int] = 400,
    ):
        super().__init__(message, status_code=status_code)
        self.max_tokens = max_tokens


class ResponseParseError(LLMError):
    """The provider returned a malformed or incomplete response."""


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """Small capability view consumed by context and attachment code."""

    name: str
    context_limit: int
    supports_vision: bool = False
    supports_tools: bool = False
    supports_thinking: bool = False


@dataclass(slots=True)
class ChatResponse:
    """One fully collected assistant response."""

    content: str = ""
    reasoning_content: Optional[str] = None
    tool_calls: Optional[list[dict[str, Any]]] = None
    usage: Optional[dict[str, Any]] = None
    finish_reason: Optional[str] = None
    index: int = 0
    provider_state: Any = None
    metadata: Optional[dict[str, Any]] = None


@dataclass(slots=True)
class StreamChunk:
    """One canonical delta from a provider stream.

    ``provider_state`` is opaque by design. The provider can require the value
    to be returned unchanged on a later assistant message; core code must not
    interpret or rewrite it.
    """

    content: Optional[str] = None
    reasoning_content: Optional[str] = None
    is_finished: bool = False
    usage: Optional[dict[str, Any]] = None
    tool_calls: Optional[list[dict[str, Any]]] = None
    finish_reason: Optional[str] = None
    index: int = 0
    provider_state: Any = None


CanonicalMessage = Mapping[str, Any]
CanonicalTool = Mapping[str, Any]


class BaseLLMClient(ABC):
    """Pure-async LLM client boundary.

    Streaming is the sole transport path. ``complete`` collects that exact
    stream so request construction, error handling, and connection lifecycle
    cannot diverge between streaming and non-streaming callers.
    """

    def __init__(
        self,
        provider_id: str,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60,
    ) -> None:
        self.provider_id = provider_id.strip().casefold()
        self.api_key = api_key.strip()
        self.base_url = base_url.strip()
        self.model = model.strip()
        self.timeout = float(timeout)

    @abstractmethod
    async def chat_stream(
        self,
        messages: Sequence[CanonicalMessage],
        model: Optional[str] = None,
        tools: Optional[Sequence[CanonicalTool]] = None,
        thinking: bool = False,
        *,
        reasoning_effort: Optional[str] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Yield canonical deltas through the provider's terminal marker."""
        if False:  # pragma: no cover - defines an abstract async generator
            yield StreamChunk()

    async def complete(
        self,
        messages: Sequence[CanonicalMessage],
        model: Optional[str] = None,
        tools: Optional[Sequence[CanonicalTool]] = None,
        thinking: bool = False,
        *,
        reasoning_effort: Optional[str] = None,
    ) -> ChatResponse:
        """Collect ``chat_stream`` into one response without another wire path."""
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: Optional[list[dict[str, Any]]] = None
        usage: Optional[dict[str, Any]] = None
        finish_reason: Optional[str] = None
        provider_state: Any = None
        selected_index: Optional[int] = None

        async for chunk in self.chat_stream(
            messages=messages,
            model=model,
            tools=tools,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
        ):
            if selected_index is None:
                selected_index = chunk.index
            if chunk.index != selected_index:
                continue
            if chunk.content:
                content_parts.append(chunk.content)
            if chunk.reasoning_content:
                reasoning_parts.append(chunk.reasoning_content)
            if chunk.tool_calls is not None:
                tool_calls = chunk.tool_calls
            if chunk.usage is not None:
                usage = chunk.usage
            if chunk.finish_reason is not None:
                finish_reason = chunk.finish_reason
            if chunk.provider_state is not None:
                provider_state = chunk.provider_state

        return ChatResponse(
            content="".join(content_parts),
            reasoning_content="".join(reasoning_parts) or None,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=finish_reason,
            index=selected_index or 0,
            provider_state=provider_state,
        )

    def get_model_info(self, model: Optional[str] = None) -> ModelInfo:
        """Read capability metadata from the new static provider catalog.

        Catalog construction is owned outside the HTTP client. The conservative
        fallback keeps a custom OpenAI-compatible endpoint usable without
        claiming capabilities it did not declare.
        """
        model_name = (model or self.model).strip()
        try:
            from infrastructure.llm_adapters.provider_catalog import get_model

            spec = get_model(self.provider_id, model_name)
        except (ImportError, LookupError, ValueError):
            spec = None

        if spec is None:
            return ModelInfo(name=model_name, context_limit=128_000)
        return ModelInfo(
            name=str(spec.id),
            context_limit=int(spec.context_limit),
            supports_vision=bool(spec.vision),
            supports_tools=bool(spec.tools),
            supports_thinking=bool(spec.thinking),
        )

    async def close(self) -> None:
        """Release async transport resources owned by this client."""


__all__ = [
    "APIError",
    "AuthError",
    "BaseLLMClient",
    "CanonicalMessage",
    "CanonicalTool",
    "ChatResponse",
    "ContextOverflowError",
    "LLMError",
    "ModelInfo",
    "RateLimitError",
    "ResponseParseError",
    "StreamChunk",
]
