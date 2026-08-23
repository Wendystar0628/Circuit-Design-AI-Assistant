from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from infrastructure.config.settings import (
    CONFIG_ENABLE_THINKING,
    CONFIG_LLM_API_PROTOCOL,
    CONFIG_LLM_BASE_URL,
    CONFIG_LLM_MODEL,
    CONFIG_LLM_PROVIDER,
    CONFIG_LLM_TIMEOUT,
    CREDENTIAL_TYPE_LLM,
    DEFAULT_ENABLE_THINKING,
    DEFAULT_TIMEOUT,
)
from infrastructure.llm_adapters.provider_catalog import (
    get_model,
    get_provider,
    validate_selection,
)
from infrastructure.llm_adapters.base_url import validate_base_url


UNSET_API_KEY = object()


@dataclass(frozen=True, slots=True)
class ActiveLLMConfig:
    provider: str = ""
    model: str = ""
    api_protocol: str = ""
    model_id: str = ""
    display_name: str = ""
    base_url: str = ""
    effective_base_url: str = ""
    timeout: int = DEFAULT_TIMEOUT
    enable_thinking: bool = DEFAULT_ENABLE_THINKING
    api_key: str = ""
    updated_at: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.provider and self.model and self.api_protocol)

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)


class LLMRuntimeConfigManager:
    """Resolve and persist the one active chat connection.

    Provider and model validity comes exclusively from the immutable provider
    catalog. The two aggregator providers are the only places where arbitrary
    model IDs are accepted.
    """

    def __init__(self, config_manager: Any, credential_manager: Any):
        if config_manager is None or credential_manager is None:
            raise ValueError("LLM runtime config dependencies are required")
        self.config_manager = config_manager
        self.credential_manager = credential_manager

    def resolve_active_config(
        self,
        provider_id: Optional[str] = None,
        model_name: Optional[str] = None,
        api_protocol: Optional[str] = None,
    ) -> ActiveLLMConfig:
        provider_value = str(
            provider_id
            if provider_id is not None
            else self.config_manager.get(CONFIG_LLM_PROVIDER, "")
            or ""
        ).strip().lower()
        provider = get_provider(provider_value) if provider_value else None
        if provider is None:
            return ActiveLLMConfig()

        configured_model = str(
            model_name
            if model_name is not None
            else self.config_manager.get(CONFIG_LLM_MODEL, "")
            or ""
        ).strip()
        model_value = configured_model or provider.default_model
        model = get_model(provider.id, model_value) if model_value else None

        if not provider.allow_custom_model and model is None:
            # Old or retired IDs are not aliases. Discard them and select the
            # current provider default.
            model_value = provider.default_model
            model = get_model(provider.id, model_value) if model_value else None

        configured_protocol = str(
            api_protocol
            if api_protocol is not None
            else self.config_manager.get(CONFIG_LLM_API_PROTOCOL, "")
            or ""
        ).strip()
        if model is not None:
            protocol = model.protocol
        elif model_value:
            try:
                validate_selection(provider.id, model_value, configured_protocol or None)
            except ValueError:
                # Invalid or incomplete aggregator settings are not silently
                # repaired. OpenCode in particular needs an explicit protocol.
                protocol = ""
            else:
                protocol = configured_protocol or provider.protocol_options[0]
        else:
            protocol = ""

        base_url_override = str(
            self.config_manager.get(CONFIG_LLM_BASE_URL, "") or ""
        ).strip()
        effective_base_url = base_url_override or provider.default_base_url
        timeout = self._coerce_positive_int(
            self.config_manager.get(CONFIG_LLM_TIMEOUT, DEFAULT_TIMEOUT),
            DEFAULT_TIMEOUT,
        )

        enable_thinking = bool(
            self.config_manager.get(CONFIG_ENABLE_THINKING, DEFAULT_ENABLE_THINKING)
        )
        if model is not None and not model.thinking:
            enable_thinking = False

        credential = self.credential_manager.get_credential(
            CREDENTIAL_TYPE_LLM,
            provider.id,
        ) or {}
        api_key = str(credential.get("api_key", "") or "").strip()
        updated_at = str(credential.get("updated_at", "") or "").strip()

        return ActiveLLMConfig(
            provider=provider.id,
            model=model_value,
            api_protocol=protocol,
            model_id=f"{provider.id}:{model_value}" if model_value else "",
            display_name=model.label if model is not None else model_value,
            base_url=base_url_override,
            effective_base_url=effective_base_url,
            timeout=timeout,
            enable_thinking=enable_thinking,
            api_key=api_key,
            updated_at=updated_at,
        )

    def save_active_chat_config(
        self,
        *,
        provider_id: str,
        model_name: str,
        api_protocol: str,
        base_url: str,
        timeout: int,
        enable_thinking: bool,
        api_key: Any = UNSET_API_KEY,
    ) -> ActiveLLMConfig:
        provider_value = str(provider_id or "").strip().lower()
        provider = get_provider(provider_value)
        if provider is None:
            raise ValueError(f"Unsupported LLM provider: {provider_value or '<empty>'}")

        model_value = str(model_name or "").strip()
        if not model_value:
            raise ValueError("Model is required")
        requested_protocol = str(api_protocol or "").strip()
        validate_selection(provider.id, model_value, requested_protocol or None)
        model = get_model(provider.id, model_value)
        protocol = (
            model.protocol
            if model is not None
            else requested_protocol or provider.protocol_options[0]
        )

        thinking_value = bool(enable_thinking)
        if model is not None and not model.thinking:
            thinking_value = False

        base_url_value = str(base_url or "").strip()
        validate_base_url(base_url_value or provider.default_base_url)

        previous_credential = self.credential_manager.get_credential(
            CREDENTIAL_TYPE_LLM,
            provider.id,
        )
        credential_changed = api_key is not UNSET_API_KEY
        if api_key is not UNSET_API_KEY:
            if api_key is None:
                credential_saved = self.credential_manager.delete_credential(
                    CREDENTIAL_TYPE_LLM,
                    provider.id,
                )
            else:
                api_key_value = str(api_key or "").strip()
                if not api_key_value:
                    raise ValueError("API key cannot be blank; omit it to keep the saved key")
                credential_saved = self.credential_manager.set_llm_api_key(
                    provider.id,
                    api_key_value,
                )
            if not credential_saved:
                raise RuntimeError("Failed to persist the API key")

        updated = self.config_manager.update_many(
            {
                CONFIG_LLM_PROVIDER: provider.id,
                CONFIG_LLM_MODEL: model_value,
                CONFIG_LLM_API_PROTOCOL: protocol,
                CONFIG_LLM_BASE_URL: base_url_value,
                CONFIG_LLM_TIMEOUT: self._coerce_positive_int(
                    timeout,
                    DEFAULT_TIMEOUT,
                ),
                CONFIG_ENABLE_THINKING: thinking_value,
            }
        )
        if not updated:
            rollback_succeeded = True
            if credential_changed:
                previous_api_key = str(
                    (previous_credential or {}).get("api_key", "") or ""
                ).strip()
                if previous_api_key:
                    rollback_succeeded = self.credential_manager.set_llm_api_key(
                        provider.id,
                        previous_api_key,
                    )
                else:
                    rollback_succeeded = self.credential_manager.delete_credential(
                        CREDENTIAL_TYPE_LLM,
                        provider.id,
                    )
            if not rollback_succeeded:
                raise RuntimeError(
                    "Failed to persist the LLM configuration and restore the API key"
                )
            raise RuntimeError("Failed to persist the LLM configuration")

        return self.resolve_active_config()

    @staticmethod
    def _coerce_positive_int(value: Any, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default


__all__ = ["ActiveLLMConfig", "LLMRuntimeConfigManager", "UNSET_API_KEY"]
