from __future__ import annotations

import pytest

import infrastructure.llm_adapters as adapters
from infrastructure.llm_adapters.anthropic_client import AnthropicClient
from infrastructure.llm_adapters.client_factory import LLMClientFactory
from infrastructure.llm_adapters.gemini_client import GeminiClient
from infrastructure.llm_adapters.openai_chat_client import OpenAIChatClient
from infrastructure.llm_adapters.openai_responses_client import OpenAIResponsesClient
from infrastructure.llm_adapters.provider_catalog import get_provider


@pytest.mark.parametrize(
    ("provider_id", "model", "api_protocol", "client_type"),
    [
        ("openai", None, None, OpenAIResponsesClient),
        ("anthropic", None, None, AnthropicClient),
        ("gemini", None, None, GeminiClient),
        ("xai", None, None, OpenAIResponsesClient),
        ("deepseek", None, None, OpenAIChatClient),
        ("qwen", None, None, OpenAIChatClient),
        ("zhipu", None, None, OpenAIChatClient),
        ("kimi", None, None, OpenAIChatClient),
        ("opencode", "vendor/custom-model", "openai_responses", OpenAIResponsesClient),
        ("siliconflow", "vendor/custom-model", None, OpenAIChatClient),
    ],
)
def test_factory_dispatches_all_ten_providers(
    provider_id: str,
    model: str | None,
    api_protocol: str | None,
    client_type: type,
) -> None:
    provider = get_provider(provider_id)
    assert provider is not None

    client = LLMClientFactory.create_client(
        provider_id=provider_id,
        api_key="test-key",
        model=model,
        timeout=37,
        api_protocol=api_protocol,
    )

    assert isinstance(client, client_type)
    assert client.provider_id == provider_id
    assert client.model == (model or provider.default_model)
    assert client.base_url.rstrip("/") == provider.default_base_url.rstrip("/")
    assert client.timeout == 37.0


@pytest.mark.parametrize(
    ("provider_id", "retired_model"),
    [
        ("openai", "gpt-4o"),
        ("anthropic", "claude-3-7-sonnet-latest"),
        ("gemini", "gemini-1.5-pro"),
        ("xai", "grok-4.3"),
        ("deepseek", "deepseek-chat"),
        ("qwen", "qwen3-max"),
        ("zhipu", "glm-4.6v"),
        ("kimi", "moonshot-v1-128k"),
    ],
)
def test_factory_rejects_non_curated_legacy_model_ids(
    provider_id: str,
    retired_model: str,
) -> None:
    with pytest.raises(ValueError, match="Unknown model"):
        LLMClientFactory.create_client(
            provider_id=provider_id,
            api_key="test-key",
            model=retired_model,
        )


def test_factory_rejects_protocol_override_for_curated_model() -> None:
    with pytest.raises(ValueError, match="requires protocol"):
        LLMClientFactory.create_client(
            provider_id="xai",
            api_key="test-key",
            model="grok-4.6",
            api_protocol="openai_chat",
        )


@pytest.mark.parametrize(
    ("protocol", "client_type"),
    [
        ("openai_responses", OpenAIResponsesClient),
        ("openai_chat", OpenAIChatClient),
        ("anthropic_messages", AnthropicClient),
        ("gemini_generate_content", GeminiClient),
    ],
)
def test_opencode_requires_and_dispatches_explicit_protocol(
    protocol: str,
    client_type: type,
) -> None:
    client = LLMClientFactory.create_client(
        provider_id="opencode",
        api_key="test-key",
        model="vendor/custom-model",
        api_protocol=protocol,
    )

    assert isinstance(client, client_type)
    assert client.model == "vendor/custom-model"


@pytest.mark.parametrize(
    ("model", "protocol"),
    [
        ("vendor/custom-model", None),
        ("vendor/custom-model", "unsupported"),
        ("", "openai_chat"),
        ("   ", "openai_chat"),
    ],
)
def test_opencode_rejects_missing_or_invalid_custom_selection(
    model: str,
    protocol: str | None,
) -> None:
    with pytest.raises(ValueError):
        LLMClientFactory.create_client(
            provider_id="opencode",
            api_key="test-key",
            model=model,
            api_protocol=protocol,
        )


def test_siliconflow_accepts_custom_model_and_is_fixed_to_openai_chat() -> None:
    implicit = LLMClientFactory.create_client(
        provider_id="siliconflow",
        api_key="test-key",
        model="vendor/custom-model",
    )
    explicit = LLMClientFactory.create_client(
        provider_id="siliconflow",
        api_key="test-key",
        model="vendor/custom-model",
        api_protocol="openai_chat",
    )

    assert isinstance(implicit, OpenAIChatClient)
    assert isinstance(explicit, OpenAIChatClient)


@pytest.mark.parametrize("model", [None, "", "   "])
def test_siliconflow_rejects_empty_custom_model(model: str | None) -> None:
    with pytest.raises(ValueError, match="Model is required"):
        LLMClientFactory.create_client(
            provider_id="siliconflow",
            api_key="test-key",
            model=model,
        )


def test_siliconflow_rejects_protocol_override() -> None:
    with pytest.raises(ValueError, match="Unsupported protocol"):
        LLMClientFactory.create_client(
            provider_id="siliconflow",
            api_key="test-key",
            model="vendor/custom-model",
            api_protocol="openai_responses",
        )


def test_factory_uses_non_empty_base_url_override() -> None:
    client = LLMClientFactory.create_client(
        provider_id="openai",
        api_key="test-key",
        base_url="  https://gateway.example/v1  ",
    )

    assert client.base_url == "https://gateway.example/v1"


@pytest.mark.parametrize(
    "base_url",
    [
        "gateway.example/v1",
        "ftp://gateway.example/v1",
        "https:///v1",
        "https://user:secret@gateway.example/v1",
        "https://bad host.example/v1",
        "http://[::1",
        "https://gateway.example/v1?token=secret",
        "https://gateway.example/v1#fragment",
    ],
)
def test_factory_rejects_unsafe_or_malformed_base_url(base_url: str) -> None:
    with pytest.raises(ValueError, match="Base URL"):
        LLMClientFactory.create_client(
            provider_id="siliconflow",
            api_key="test-key",
            base_url=base_url,
            model="vendor/custom-model",
            api_protocol="openai_chat",
        )


def test_factory_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        LLMClientFactory.create_client(
            provider_id="legacy-provider",
            api_key="test-key",
        )


def test_package_exports_only_the_new_protocol_clients() -> None:
    assert adapters.OpenAIResponsesClient is OpenAIResponsesClient
    assert adapters.OpenAIChatClient is OpenAIChatClient
    assert adapters.AnthropicClient is AnthropicClient
    assert adapters.GeminiClient is GeminiClient

    for legacy_name in (
        "OpenAICompatibleClient",
        "ZhipuClient",
        "DeepSeekClient",
        "QwenClient",
    ):
        assert legacy_name not in adapters.__all__
        assert not hasattr(adapters, legacy_name)
