from dataclasses import FrozenInstanceError, fields

import pytest

from infrastructure.llm_adapters.provider_catalog import (
    MODELS_BY_PROVIDER,
    PROTOCOL_NAMES,
    PROVIDERS,
    PROVIDERS_BY_ID,
    ModelCatalogEntry,
    ProviderCatalogEntry,
    get_model,
    get_provider,
    list_models,
    list_providers,
    resolve_selection,
    validate_selection,
)


EXPECTED_PROVIDER_IDS = (
    "openai",
    "anthropic",
    "gemini",
    "xai",
    "deepseek",
    "qwen",
    "zhipu",
    "kimi",
    "opencode",
    "siliconflow",
)

EXPECTED_MODELS = {
    "openai": (
        "gpt-5.6-sol",
        "gpt-5.6-luna",
        "gpt-5.5-pro",
    ),
    "anthropic": (
        "claude-fable-5",
        "claude-sonnet-5",
        "claude-opus-4-8",
        "claude-sonnet-4-6",
    ),
    "gemini": (
        "gemini-3.1-pro-preview",
        "gemini-3.7-flash",
        "gemini-2.5-pro",
        "gemini-3.6-flash",
    ),
    "xai": (
        "grok-4.6",
        "grok-4.5",
    ),
    "deepseek": (
        "deepseek-v4-pro",
        "deepseek-v4-flash",
    ),
    "qwen": (
        "qwen3.8-max",
        "qwen3.7-flash",
        "qwen3.7-max",
        "qwen3.6-flash",
    ),
    "zhipu": (
        "glm-5.3",
        "glm-5.2",
    ),
    "kimi": ("kimi-k3",),
    "opencode": (),
    "siliconflow": (),
}


def test_catalog_has_exact_provider_and_model_shape() -> None:
    assert tuple(field.name for field in fields(ProviderCatalogEntry)) == (
        "id",
        "label",
        "default_base_url",
        "default_model",
        "allow_custom_model",
        "protocol_options",
        "docs_url",
    )
    assert tuple(field.name for field in fields(ModelCatalogEntry)) == (
        "id",
        "label",
        "role",
        "generation",
        "status",
        "protocol",
        "tools",
        "vision",
        "thinking",
        "streaming",
        "context_limit",
        "max_input_tokens",
        "max_output_tokens",
        "output_reserve_tokens",
        "description",
    )


def test_catalog_contains_exactly_ten_providers_in_ui_order() -> None:
    assert isinstance(PROVIDERS, tuple)
    assert list_providers() is PROVIDERS
    assert tuple(provider.id for provider in PROVIDERS) == EXPECTED_PROVIDER_IDS
    assert tuple(PROVIDERS_BY_ID) == EXPECTED_PROVIDER_IDS
    assert tuple(MODELS_BY_PROVIDER) == EXPECTED_PROVIDER_IDS


def test_provider_defaults_bases_and_protocol_options_are_exact() -> None:
    expected = {
        "openai": (
            "https://api.openai.com/v1",
            "gpt-5.6-sol",
            False,
            ("openai_responses",),
        ),
        "anthropic": (
            "https://api.anthropic.com/v1",
            "claude-fable-5",
            False,
            ("anthropic_messages",),
        ),
        "gemini": (
            "https://generativelanguage.googleapis.com/v1beta",
            "gemini-3.1-pro-preview",
            False,
            ("gemini_generate_content",),
        ),
        "xai": (
            "https://api.x.ai/v1",
            "grok-4.6",
            False,
            ("openai_responses",),
        ),
        "deepseek": (
            "https://api.deepseek.com",
            "deepseek-v4-pro",
            False,
            ("openai_chat",),
        ),
        "qwen": (
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "qwen3.8-max",
            False,
            ("openai_chat",),
        ),
        "zhipu": (
            "https://open.bigmodel.cn/api/paas/v4",
            "glm-5.3",
            False,
            ("openai_chat",),
        ),
        "kimi": (
            "https://api.moonshot.cn/v1",
            "kimi-k3",
            False,
            ("openai_chat",),
        ),
        "opencode": (
            "https://opencode.ai/zen/v1",
            "",
            True,
            PROTOCOL_NAMES,
        ),
        "siliconflow": (
            "https://api.siliconflow.cn/v1",
            "",
            True,
            ("openai_chat",),
        ),
    }

    for provider_id, values in expected.items():
        provider = get_provider(provider_id)
        assert provider is not None
        assert (
            provider.default_base_url,
            provider.default_model,
            provider.allow_custom_model,
            provider.protocol_options,
        ) == values
        assert provider.docs_url.startswith("https://")


def test_model_ids_are_exact_and_aggregators_have_no_static_models() -> None:
    for provider_id, expected_ids in EXPECTED_MODELS.items():
        models = list_models(provider_id)
        assert isinstance(models, tuple)
        assert tuple(model.id for model in models) == expected_ids


def test_each_provider_has_at_most_one_model_per_role() -> None:
    for provider_id, models in MODELS_BY_PROVIDER.items():
        roles = [model.role for model in models]
        assert len(roles) == len(set(roles)), provider_id


def test_generation_matches_current_or_previous_role() -> None:
    for models in MODELS_BY_PROVIDER.values():
        for model in models:
            expected_generation = (
                "current" if model.role.startswith("current_") else "previous"
            )
            assert model.generation == expected_generation
            assert model.status in {"stable", "preview"}
            assert model.protocol in PROTOCOL_NAMES
            assert model.context_limit > 0
            assert model.max_input_tokens is None or model.max_input_tokens > 0
            assert model.max_output_tokens is None or model.max_output_tokens > 0
            assert model.output_reserve_tokens > 0
            assert model.description


def test_only_explicit_models_are_preview() -> None:
    preview_models = {
        model.id
        for models in MODELS_BY_PROVIDER.values()
        for model in models
        if model.status == "preview"
    }
    assert preview_models == {
        "gemini-3.1-pro-preview",
        "deepseek-v4-flash",
    }


def test_known_context_and_output_limits_are_preserved() -> None:
    exact_limits = {
        "openai": {
            "gpt-5.6-sol": (1_050_000, 128_000),
            "gpt-5.6-luna": (1_050_000, 128_000),
            "gpt-5.5-pro": (1_050_000, 128_000),
        },
        "anthropic": {
            "claude-fable-5": (1_000_000, 128_000),
            "claude-sonnet-5": (1_000_000, 128_000),
            "claude-opus-4-8": (1_000_000, 128_000),
            "claude-sonnet-4-6": (1_000_000, 128_000),
        },
        "gemini": {
            "gemini-3.1-pro-preview": (1_048_576, 65_536),
            "gemini-3.7-flash": (1_048_576, 65_536),
            "gemini-2.5-pro": (1_048_576, 65_536),
            "gemini-3.6-flash": (1_048_576, 65_536),
        },
        "deepseek": {
            "deepseek-v4-pro": (1_000_000, 384_000),
            "deepseek-v4-flash": (1_000_000, 384_000),
        },
        "qwen": {
            "qwen3.8-max": (1_000_000, 131_072),
            "qwen3.7-flash": (1_000_000, 131_072),
            "qwen3.7-max": (1_000_000, 131_072),
            "qwen3.6-flash": (1_000_000, 65_536),
        },
        "zhipu": {
            "glm-5.3": (1_000_000, 131_072),
            "glm-5.2": (1_000_000, 131_072),
        },
        "kimi": {"kimi-k3": (1_048_576, 1_048_576)},
    }

    for provider_id, models in exact_limits.items():
        for model_id, limits in models.items():
            model = get_model(provider_id, model_id)
            assert model is not None
            assert (model.context_limit, model.max_output_tokens) == limits

    for model_id in ("grok-4.6", "grok-4.5"):
        model = get_model("xai", model_id)
        assert model is not None
        assert model.context_limit == 500_000
        assert model.max_output_tokens is None

    for model in list_models("gemini"):
        assert model.max_input_tokens == 1_048_576

    for model in list_models("qwen"):
        assert model.max_input_tokens == 983_616

    expected_reserves = {
        "openai": 32_768,
        "anthropic": 8_192,
        "gemini": 32_768,
        "xai": 32_768,
        "deepseek": 32_768,
        "qwen": 32_768,
        "zhipu": 32_768,
        "kimi": 131_072,
    }
    for provider_id, reserve in expected_reserves.items():
        for model in list_models(provider_id):
            assert model.output_reserve_tokens == reserve

    for provider_id in ("deepseek", "zhipu"):
        for model in list_models(provider_id):
            assert model.vision is False

    kimi = get_model("kimi", "kimi-k3")
    assert kimi is not None
    assert kimi.context_limit == 1_048_576
    assert kimi.vision is True


def test_catalog_is_immutable() -> None:
    provider = get_provider("openai")
    assert provider is not None

    with pytest.raises(FrozenInstanceError):
        provider.label = "mutated"  # type: ignore[misc]
    with pytest.raises(TypeError):
        PROVIDERS_BY_ID["mutated"] = provider  # type: ignore[index]
    with pytest.raises(TypeError):
        MODELS_BY_PROVIDER["openai"] = ()  # type: ignore[index]


def test_old_alias_preview_and_hidden_fallback_ids_are_absent() -> None:
    all_model_ids = {
        model.id for models in MODELS_BY_PROVIDER.values() for model in models
    }
    forbidden_ids = {
        "gpt-5.4",
        "gpt-5.5",
        "claude-opus-5",
        "gemini-3.1-pro",
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-v4-flash-preview",
        "qwen3-max",
        "qwen3.6-plus",
        "qwen3-vl-plus",
        "glm-5",
        "glm-5-turbo",
        "glm-4.6v",
        "glm-4.6v-flash",
        "kimi-k2.6",
        "kimi-k2.7-code",
        "kimi-k2.7-code-highspeed",
        "kimi-k2-0905-preview",
        "kimi-k2-turbo-preview",
        "kimi-latest",
        "kimi-thinking-preview",
    }
    assert all_model_ids.isdisjoint(forbidden_ids)


def test_get_and_list_return_none_or_empty_for_unknown_ids() -> None:
    assert get_provider("unknown") is None
    assert get_model("openai", "unknown") is None
    assert get_model("unknown", "gpt-5.6-sol") is None
    assert list_models("unknown") == ()


def test_curated_provider_requires_exact_catalog_model_and_protocol() -> None:
    assert validate_selection("openai", "gpt-5.6-sol") is None
    assert (
        validate_selection(
            "openai",
            "gpt-5.6-sol",
            protocol="openai_responses",
        )
        is None
    )

    with pytest.raises(ValueError, match="Unknown model"):
        validate_selection("openai", "my-custom-model")
    with pytest.raises(ValueError, match="Model is required"):
        validate_selection("openai", "")
    with pytest.raises(ValueError, match="requires protocol"):
        validate_selection("openai", "gpt-5.6-sol", protocol="openai_chat")


def test_runtime_resolution_uses_curated_default_model() -> None:
    resolved = resolve_selection("openai")
    assert resolved.provider.id == "openai"
    assert resolved.model_id == "gpt-5.6-sol"
    assert resolved.protocol == "openai_responses"
    assert resolved.model is get_model("openai", "gpt-5.6-sol")


@pytest.mark.parametrize("protocol", PROTOCOL_NAMES)
def test_opencode_accepts_nonempty_custom_model_with_explicit_protocol(
    protocol: str,
) -> None:
    assert validate_selection("opencode", "vendor/custom-model", protocol) is None
    resolved = resolve_selection("opencode", "vendor/custom-model", protocol)
    assert resolved.model_id == "vendor/custom-model"
    assert resolved.protocol == protocol
    assert resolved.model is None


def test_opencode_strictly_requires_a_supported_protocol() -> None:
    with pytest.raises(ValueError, match="Protocol is required"):
        validate_selection("opencode", "vendor/custom-model")
    with pytest.raises(ValueError, match="Unsupported protocol"):
        validate_selection("opencode", "vendor/custom-model", "legacy_chat")
    with pytest.raises(ValueError, match="Model is required"):
        validate_selection("opencode", "", "openai_chat")


def test_siliconflow_accepts_any_nonempty_model_and_resolves_openai_chat() -> None:
    model_id = "Pro/deepseek-ai/DeepSeek-V3.2"
    assert validate_selection("siliconflow", model_id) is None

    resolved = resolve_selection("siliconflow", model_id)
    assert resolved.model_id == model_id
    assert resolved.protocol == "openai_chat"
    assert resolved.model is None

    with pytest.raises(ValueError, match="Model is required"):
        validate_selection("siliconflow", "")
    with pytest.raises(ValueError, match="Unsupported protocol"):
        validate_selection("siliconflow", model_id, "openai_responses")
