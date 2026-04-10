from __future__ import annotations

from typing import Any, Callable, Dict, List


class ModelConfigStateSerializer:
    def __init__(self, get_text: Callable[[str, str], str]):
        self._get_text = get_text

    def serialize(
        self,
        *,
        draft: Any,
        chat_providers: List[Any],
        embedding_providers: List[Any],
        chat_models: List[str],
        embedding_models: List[str],
        chat_provider: Any,
        embedding_provider: Any,
        supports_thinking: bool,
        status_state: str,
        status_text: str,
    ) -> Dict[str, Any]:
        return {
            "surface": {
                "title": self._get_text("dialog.model_config.title", "Model Configuration"),
                "activeTab": draft.active_tab,
                "tabs": [
                    {
                        "id": "chat",
                        "label": self._get_text("dialog.model_config.tab.chat", "Chat Model"),
                    },
                    {
                        "id": "embedding",
                        "label": self._get_text("dialog.model_config.tab.embedding", "Embedding Model"),
                    },
                ],
                "actions": {
                    "test": self._get_text("dialog.model_config.test_connection", "Test Connection"),
                    "save": self._get_text("btn.save", "Save"),
                    "cancel": self._get_text("btn.cancel", "Cancel"),
                },
                "status": {
                    "state": status_state,
                    "text": status_text,
                },
                "messages": {
                    "bridgeUnavailable": self._get_text(
                        "dialog.model_config.bridge_unavailable",
                        "Qt bridge unavailable",
                    ),
                },
            },
            "chat": {
                "provider": draft.chat_provider,
                "providerOptions": [
                    {
                        "value": provider.id,
                        "label": provider.display_name,
                    }
                    for provider in chat_providers
                ],
                "model": draft.chat_model,
                "modelOptions": [
                    {"value": model_name, "label": model_name}
                    for model_name in chat_models
                ],
                "apiKey": draft.chat_api_key,
                "baseUrl": draft.chat_base_url,
                "baseUrlPlaceholder": chat_provider.base_url if chat_provider else "",
                "timeout": draft.chat_timeout,
                "streaming": draft.chat_streaming,
                "enableThinking": draft.chat_enable_thinking,
                "thinkingTimeout": draft.chat_thinking_timeout,
                "supportsThinking": supports_thinking,
                "labels": {
                    "provider": self._get_text("dialog.model_config.provider", "Provider"),
                    "model": self._get_text("dialog.model_config.model", "Model"),
                    "apiKey": self._get_text("dialog.model_config.api_key", "API Key"),
                    "baseUrl": self._get_text("dialog.model_config.base_url", "Base URL"),
                    "timeout": self._get_text("dialog.model_config.timeout", "Timeout"),
                    "streaming": self._get_text("dialog.model_config.streaming", "Streaming"),
                    "enableThinking": self._get_text(
                        "dialog.model_config.deep_think",
                        "Deep Thinking",
                    ),
                    "thinkingTimeout": self._get_text(
                        "dialog.model_config.thinking_timeout",
                        "Thinking Timeout",
                    ),
                    "featuresTitle": self._get_text(
                        "dialog.model_config.group.features",
                        "Provider Features",
                    ),
                    "enabled": self._get_text(
                        "dialog.model_config.toggle.enabled",
                        "Enabled",
                    ),
                    "disabled": self._get_text(
                        "dialog.model_config.toggle.disabled",
                        "Disabled",
                    ),
                    "notSupported": self._get_text(
                        "dialog.model_config.not_supported",
                        "Not supported",
                    ),
                },
            },
            "embedding": {
                "provider": draft.embedding_provider,
                "providerOptions": [
                    {
                        "value": provider.id,
                        "label": provider.display_name,
                    }
                    for provider in embedding_providers
                ],
                "model": draft.embedding_model,
                "modelOptions": [
                    {"value": model_name, "label": model_name}
                    for model_name in embedding_models
                ],
                "apiKey": draft.embedding_api_key,
                "baseUrl": draft.embedding_base_url,
                "baseUrlPlaceholder": embedding_provider.base_url if embedding_provider else "",
                "timeout": draft.embedding_timeout,
                "batchSize": draft.embedding_batch_size,
                "requiresApiKey": bool(getattr(embedding_provider, "requires_api_key", False)) if embedding_provider else False,
                "labels": {
                    "provider": self._get_text(
                        "dialog.model_config.embedding_provider",
                        "Provider",
                    ),
                    "model": self._get_text(
                        "dialog.model_config.embedding_model",
                        "Model",
                    ),
                    "apiKey": self._get_text(
                        "dialog.model_config.embedding_api_key",
                        "API Key",
                    ),
                    "baseUrl": self._get_text(
                        "dialog.model_config.embedding_base_url",
                        "Base URL",
                    ),
                    "timeout": self._get_text(
                        "dialog.model_config.embedding_timeout",
                        "Timeout",
                    ),
                    "batchSize": self._get_text(
                        "dialog.model_config.embedding_batch_size",
                        "Batch Size",
                    ),
                },
            },
        }


__all__ = ["ModelConfigStateSerializer"]
