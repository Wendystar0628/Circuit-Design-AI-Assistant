from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from infrastructure.config.settings import (
    CONFIG_ENABLE_THINKING,
    CONFIG_LLM_BASE_URL,
    CONFIG_LLM_MODEL,
    CONFIG_LLM_PROVIDER,
    CONFIG_LLM_STREAMING,
    CONFIG_LLM_TIMEOUT,
    CONFIG_THINKING_TIMEOUT,
    CREDENTIAL_TYPE_LLM,
    DEFAULT_ENABLE_THINKING,
    DEFAULT_STREAMING,
    DEFAULT_THINKING_TIMEOUT,
    DEFAULT_TIMEOUT,
)
from shared.model_registry import ModelRegistry


_LLM_RUNTIME_UPDATED_AT_KEY = "llm_runtime_updated_at"


@dataclass(frozen=True)
class ActiveLLMConfig:
    provider: str = ""
    model: str = ""
    model_id: str = ""
    display_name: str = ""
    base_url: str = ""
    timeout: int = DEFAULT_TIMEOUT
    streaming: bool = DEFAULT_STREAMING
    enable_thinking: bool = DEFAULT_ENABLE_THINKING
    thinking_timeout: int = DEFAULT_THINKING_TIMEOUT
    api_key: str = ""
    updated_at: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.provider and self.model)

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)


class LLMRuntimeConfigManager:
    def __init__(self, config_manager: Optional[Any] = None, credential_manager: Optional[Any] = None):
        self._config_manager = config_manager
        self._credential_manager = credential_manager

    @property
    def config_manager(self):
        if self._config_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CONFIG_MANAGER

                self._config_manager = ServiceLocator.get_optional(SVC_CONFIG_MANAGER)
            except Exception:
                self._config_manager = None
        return self._config_manager

    @property
    def credential_manager(self):
        if self._credential_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CREDENTIAL_MANAGER

                self._credential_manager = ServiceLocator.get_optional(SVC_CREDENTIAL_MANAGER)
            except Exception:
                self._credential_manager = None
        return self._credential_manager

    def resolve_active_config(
        self,
        provider_id: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> ActiveLLMConfig:
        ModelRegistry.initialize()

        config_manager = self.config_manager
        credential_manager = self.credential_manager

        provider_value = (provider_id or "").strip()
        if not provider_value and config_manager:
            provider_value = str(config_manager.get(CONFIG_LLM_PROVIDER, "") or "").strip()

        provider_config = ModelRegistry.get_provider(provider_value) if provider_value else None
        if provider_value and provider_config is None:
            provider_value = ""

        model_value = (model_name or "").strip()
        if not provider_value:
            model_value = ""
        elif not model_value and config_manager:
            model_value = str(config_manager.get(CONFIG_LLM_MODEL, "") or "").strip()
        if not model_value and provider_config:
            model_value = provider_config.default_model

        model_config = None
        if provider_value and model_value:
            model_config = ModelRegistry.get_model_by_name(provider_value, model_value)
            if model_config is None and provider_config and provider_config.default_model:
                fallback_model = provider_config.default_model
                fallback_model_config = ModelRegistry.get_model_by_name(provider_value, fallback_model)
                if fallback_model_config is not None:
                    model_value = fallback_model
                    model_config = fallback_model_config

        base_url = ""
        if provider_value and config_manager:
            base_url = str(config_manager.get(CONFIG_LLM_BASE_URL, "") or "").strip()
        if not base_url and provider_config:
            base_url = provider_config.base_url

        timeout = DEFAULT_TIMEOUT
        if config_manager:
            timeout = self._coerce_positive_int(
                config_manager.get(CONFIG_LLM_TIMEOUT, DEFAULT_TIMEOUT),
                DEFAULT_TIMEOUT,
            )

        streaming = DEFAULT_STREAMING
        if config_manager:
            streaming = bool(config_manager.get(CONFIG_LLM_STREAMING, DEFAULT_STREAMING))

        enable_thinking = DEFAULT_ENABLE_THINKING
        if config_manager:
            enable_thinking = bool(config_manager.get(CONFIG_ENABLE_THINKING, DEFAULT_ENABLE_THINKING))

        thinking_timeout = DEFAULT_THINKING_TIMEOUT
        if config_manager:
            thinking_timeout = self._coerce_positive_int(
                config_manager.get(CONFIG_THINKING_TIMEOUT, DEFAULT_THINKING_TIMEOUT),
                DEFAULT_THINKING_TIMEOUT,
            )

        api_key = ""
        updated_at = ""
        if credential_manager and provider_value:
            credential = credential_manager.get_credential(CREDENTIAL_TYPE_LLM, provider_value) or {}
            if isinstance(credential, dict):
                api_key = str(credential.get("api_key", "") or "").strip()
                updated_at = str(credential.get("updated_at", "") or "").strip()

        display_name = ""
        if model_config is not None:
            display_name = model_config.display_name
        elif model_value:
            display_name = model_value

        model_id = f"{provider_value}:{model_value}" if provider_value and model_value else ""

        return ActiveLLMConfig(
            provider=provider_value,
            model=model_value,
            model_id=model_id,
            display_name=display_name,
            base_url=base_url,
            timeout=timeout,
            streaming=streaming,
            enable_thinking=enable_thinking,
            thinking_timeout=thinking_timeout,
            api_key=api_key,
            updated_at=updated_at,
        )

    def save_active_chat_config(
        self,
        provider_id: str,
        model_name: str,
        base_url: str,
        timeout: int,
        streaming: bool,
        enable_thinking: bool,
        thinking_timeout: int,
        api_key: str,
    ) -> ActiveLLMConfig:
        config_manager = self.config_manager
        credential_manager = self.credential_manager
        if config_manager is None or credential_manager is None:
            raise RuntimeError("LLM runtime config dependencies are unavailable")

        ModelRegistry.initialize()

        provider_value = str(provider_id or "").strip()
        provider_config = ModelRegistry.get_provider(provider_value) if provider_value else None

        model_value = str(model_name or "").strip()
        if not model_value and provider_config:
            model_value = provider_config.default_model

        if provider_value and model_value and provider_config is not None:
            model_config = ModelRegistry.get_model_by_name(provider_value, model_value)
            if model_config is None and provider_config.default_model:
                fallback_model = provider_config.default_model
                if ModelRegistry.get_model_by_name(provider_value, fallback_model) is not None:
                    model_value = fallback_model

        base_url_value = str(base_url or "").strip()
        if not base_url_value and provider_config:
            base_url_value = provider_config.base_url

        timeout_value = self._coerce_positive_int(timeout, DEFAULT_TIMEOUT)
        thinking_timeout_value = self._coerce_positive_int(thinking_timeout, DEFAULT_THINKING_TIMEOUT)
        updated_at = datetime.now().isoformat()

        config_manager.set(CONFIG_LLM_PROVIDER, provider_value, save=False)
        config_manager.set(CONFIG_LLM_MODEL, model_value, save=False)
        config_manager.set(CONFIG_LLM_BASE_URL, base_url_value, save=False)
        config_manager.set(CONFIG_LLM_TIMEOUT, timeout_value, save=False)
        config_manager.set(CONFIG_LLM_STREAMING, bool(streaming), save=False)
        config_manager.set(CONFIG_ENABLE_THINKING, bool(enable_thinking), save=False)
        config_manager.set(CONFIG_THINKING_TIMEOUT, thinking_timeout_value, save=False)
        config_manager.set(_LLM_RUNTIME_UPDATED_AT_KEY, updated_at, save=False)
        config_saved = config_manager.save_config()

        api_key_value = str(api_key or "").strip()
        if api_key_value:
            credential_saved = credential_manager.set_llm_api_key(provider_value, api_key_value)
        else:
            credential_saved = credential_manager.delete_credential(CREDENTIAL_TYPE_LLM, provider_value)

        if not config_saved or not credential_saved:
            raise RuntimeError("Failed to persist LLM runtime config")

        return self.resolve_active_config(provider_id=provider_value, model_name=model_value)

    @staticmethod
    def _coerce_positive_int(value: Any, default: int) -> int:
        try:
            parsed = int(value)
            return parsed if parsed > 0 else default
        except Exception:
            return default


__all__ = ["LLMRuntimeConfigManager", "ActiveLLMConfig"]
