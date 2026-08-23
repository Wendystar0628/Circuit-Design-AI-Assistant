"""Construct the one wire client selected by the static provider catalog."""

from __future__ import annotations

from typing import Optional

from infrastructure.llm_adapters.anthropic_client import AnthropicClient
from infrastructure.llm_adapters.base_client import BaseLLMClient
from infrastructure.llm_adapters.base_url import validate_base_url
from infrastructure.llm_adapters.gemini_client import GeminiClient
from infrastructure.llm_adapters.openai_chat_client import OpenAIChatClient
from infrastructure.llm_adapters.openai_responses_client import OpenAIResponsesClient
from infrastructure.llm_adapters.provider_catalog import resolve_selection


_PROTOCOL_CLIENTS: dict[str, type[BaseLLMClient]] = {
    "openai_responses": OpenAIResponsesClient,
    "openai_chat": OpenAIChatClient,
    "anthropic_messages": AnthropicClient,
    "gemini_generate_content": GeminiClient,
}


class LLMClientFactory:
    """Resolve provider policy before constructing a transport client."""

    @staticmethod
    def create_client(
        provider_id: str,
        api_key: str,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 60,
        api_protocol: Optional[str] = None,
    ) -> BaseLLMClient:
        normalized_provider = str(provider_id or "").strip().casefold()
        selection = resolve_selection(
            provider_id=normalized_provider,
            model_id=str(model or "").strip(),
            protocol=str(api_protocol or "").strip().casefold() or None,
        )
        selected_base_url = validate_base_url(
            str(base_url or "").strip() or selection.provider.default_base_url
        )

        client_class = _PROTOCOL_CLIENTS[selection.protocol]
        return client_class(
            provider_id=normalized_provider,
            api_key=api_key,
            base_url=selected_base_url,
            model=selection.model_id,
            timeout=timeout,
        )


__all__ = ["LLMClientFactory"]
