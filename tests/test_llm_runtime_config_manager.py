from __future__ import annotations

from typing import Any

import pytest

from infrastructure.config.llm_runtime_config_manager import (
    LLMRuntimeConfigManager,
)


class _ConfigStore:
    def __init__(
        self,
        values: dict[str, Any] | None = None,
        *,
        fail_update: bool = False,
    ) -> None:
        self.values = dict(values or {})
        self.save_count = 0
        self.fail_update = fail_update

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def set(self, key: str, value: Any, *, save: bool = True) -> bool:
        self.values[key] = value
        if save:
            return self.save_config()
        return True

    def save_config(self) -> bool:
        self.save_count += 1
        return True

    def update_many(self, changes: dict[str, Any]) -> bool:
        self.save_count += 1
        if self.fail_update:
            return False
        self.values.update(changes)
        return True


class _CredentialStore:
    def __init__(self) -> None:
        self.keys: dict[tuple[str, str], str] = {
            ("llm", "openai"): "saved-key",
        }
        self.actions: list[tuple[str, str, str | None]] = []

    def get_credential(self, credential_type: str, provider: str) -> dict[str, str] | None:
        value = self.keys.get((credential_type, provider))
        return {"api_key": value, "updated_at": "now"} if value else None

    def set_llm_api_key(self, provider: str, api_key: str) -> bool:
        self.actions.append(("set", provider, api_key))
        self.keys[("llm", provider)] = api_key
        return True

    def delete_credential(self, credential_type: str, provider: str) -> bool:
        self.actions.append(("delete", provider, None))
        self.keys.pop((credential_type, provider), None)
        return True


def _save_chat(
    manager: LLMRuntimeConfigManager,
    *,
    provider: str,
    model: str,
    protocol: str,
    api_key: Any = ...,
):
    kwargs: dict[str, Any] = {
        "provider_id": provider,
        "model_name": model,
        "api_protocol": protocol,
        "base_url": "",
        "timeout": 60,
        "enable_thinking": True,
    }
    if api_key is not ...:
        kwargs["api_key"] = api_key
    return manager.save_active_chat_config(**kwargs)


def test_api_key_omission_keeps_null_deletes_and_string_replaces() -> None:
    config = _ConfigStore()
    credentials = _CredentialStore()
    manager = LLMRuntimeConfigManager(config, credentials)

    kept = _save_chat(
        manager,
        provider="openai",
        model="gpt-5.6-sol",
        protocol="openai_responses",
    )
    assert credentials.actions == []
    assert kept.api_key == "saved-key"

    deleted = _save_chat(
        manager,
        provider="openai",
        model="gpt-5.6-sol",
        protocol="openai_responses",
        api_key=None,
    )
    assert credentials.actions == [("delete", "openai", None)]
    assert deleted.api_key == ""

    replaced = _save_chat(
        manager,
        provider="openai",
        model="gpt-5.6-sol",
        protocol="openai_responses",
        api_key="new-key",
    )
    assert credentials.actions[-1] == ("set", "openai", "new-key")
    assert replaced.api_key == "new-key"


def test_opencode_accepts_custom_model_only_with_explicit_supported_protocol() -> None:
    manager = LLMRuntimeConfigManager(_ConfigStore(), _CredentialStore())

    active = _save_chat(
        manager,
        provider="opencode",
        model="anthropic/claude-sonnet-5",
        protocol="anthropic_messages",
    )

    assert active.provider == "opencode"
    assert active.model == "anthropic/claude-sonnet-5"
    assert active.api_protocol == "anthropic_messages"
    assert active.effective_base_url == "https://opencode.ai/zen/v1"

    with pytest.raises(ValueError, match="Protocol is required"):
        _save_chat(
            manager,
            provider="opencode",
            model="vendor/custom-model",
            protocol="",
        )
    with pytest.raises(ValueError, match="Unsupported protocol"):
        _save_chat(
            manager,
            provider="opencode",
            model="vendor/custom-model",
            protocol="legacy_chat",
        )


def test_siliconflow_accepts_custom_model_but_only_openai_chat_protocol() -> None:
    manager = LLMRuntimeConfigManager(_ConfigStore(), _CredentialStore())

    active = _save_chat(
        manager,
        provider="siliconflow",
        model="deepseek-ai/DeepSeek-V4",
        protocol="openai_chat",
    )

    assert active.provider == "siliconflow"
    assert active.model == "deepseek-ai/DeepSeek-V4"
    assert active.api_protocol == "openai_chat"
    assert active.effective_base_url == "https://api.siliconflow.cn/v1"

    with pytest.raises(ValueError, match="Unsupported protocol"):
        _save_chat(
            manager,
            provider="siliconflow",
            model="deepseek-ai/DeepSeek-V4",
            protocol="openai_responses",
        )


def test_curated_provider_rejects_retired_model_and_wrong_protocol() -> None:
    manager = LLMRuntimeConfigManager(_ConfigStore(), _CredentialStore())

    with pytest.raises(ValueError, match="Unknown model"):
        _save_chat(
            manager,
            provider="zhipu",
            model="glm-4.5",
            protocol="openai_chat",
        )
    with pytest.raises(ValueError, match="requires protocol"):
        _save_chat(
            manager,
            provider="zhipu",
            model="glm-5.3",
            protocol="openai_responses",
        )


@pytest.mark.parametrize("replacement", [None, "new-key"])
def test_config_failure_restores_previous_credential(replacement: str | None) -> None:
    config = _ConfigStore({"llm_provider": "openai"}, fail_update=True)
    credentials = _CredentialStore()
    manager = LLMRuntimeConfigManager(config, credentials)

    with pytest.raises(RuntimeError, match="Failed to persist the LLM configuration"):
        _save_chat(
            manager,
            provider="openai",
            model="gpt-5.6-sol",
            protocol="openai_responses",
            api_key=replacement,
        )

    assert config.values == {"llm_provider": "openai"}
    assert credentials.keys[("llm", "openai")] == "saved-key"


def test_invalid_base_url_is_rejected_before_credential_change() -> None:
    config = _ConfigStore()
    credentials = _CredentialStore()
    manager = LLMRuntimeConfigManager(config, credentials)

    with pytest.raises(ValueError, match="Base URL"):
        manager.save_active_chat_config(
            provider_id="siliconflow",
            model_name="vendor/custom-model",
            api_protocol="openai_chat",
            base_url="http://[::1",
            timeout=60,
            enable_thinking=False,
            api_key="new-key",
        )

    assert credentials.actions == []
    assert config.values == {}
