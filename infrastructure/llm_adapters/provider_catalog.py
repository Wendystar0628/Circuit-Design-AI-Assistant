"""Immutable provider and model catalog for the desktop LLM configuration UI.

The catalog is deliberately static and side-effect free.  It has no registry
lifecycle, mutation API, compatibility aliases, or hidden fallback models.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping, TypeAlias, cast


ProtocolName: TypeAlias = Literal[
    "openai_responses",
    "openai_chat",
    "anthropic_messages",
    "gemini_generate_content",
]
ModelRole: TypeAlias = Literal[
    "current_performance",
    "current_speed",
    "previous_performance",
    "previous_speed",
]
ModelGeneration: TypeAlias = Literal["current", "previous"]
ModelStatus: TypeAlias = Literal["stable", "preview"]


PROTOCOL_NAMES: tuple[ProtocolName, ...] = (
    "openai_responses",
    "openai_chat",
    "anthropic_messages",
    "gemini_generate_content",
)


@dataclass(frozen=True, slots=True)
class ProviderCatalogEntry:
    id: str
    label: str
    default_base_url: str
    default_model: str
    allow_custom_model: bool
    protocol_options: tuple[ProtocolName, ...]
    docs_url: str


@dataclass(frozen=True, slots=True)
class ModelCatalogEntry:
    id: str
    label: str
    role: ModelRole
    generation: ModelGeneration
    status: ModelStatus
    protocol: ProtocolName
    tools: bool
    vision: bool
    thinking: bool
    streaming: bool
    context_limit: int
    # Vendor-published standalone or mode-safe input ceiling, when one exists.
    max_input_tokens: int | None
    # Vendor-published hard generation ceiling; ``None`` means not specified.
    max_output_tokens: int | None
    # Mainline generation budget reserved by this application for compression.
    output_reserve_tokens: int
    description: str


@dataclass(frozen=True, slots=True)
class ResolvedProviderSelection:
    provider: ProviderCatalogEntry
    model_id: str
    protocol: ProtocolName
    model: ModelCatalogEntry | None


_CONSERVATIVE_CONTEXT_LIMIT = 128_000
_DEFAULT_OUTPUT_RESERVE_TOKENS = 32_768


PROVIDERS: tuple[ProviderCatalogEntry, ...] = (
    ProviderCatalogEntry(
        id="openai",
        label="OpenAI",
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-5.6-sol",
        allow_custom_model=False,
        protocol_options=("openai_responses",),
        docs_url="https://platform.openai.com/docs/api-reference/responses",
    ),
    ProviderCatalogEntry(
        id="anthropic",
        label="Anthropic",
        default_base_url="https://api.anthropic.com/v1",
        default_model="claude-fable-5",
        allow_custom_model=False,
        protocol_options=("anthropic_messages",),
        docs_url="https://docs.anthropic.com/en/api/messages",
    ),
    ProviderCatalogEntry(
        id="gemini",
        label="Google Gemini",
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        default_model="gemini-3.1-pro-preview",
        allow_custom_model=False,
        protocol_options=("gemini_generate_content",),
        docs_url="https://ai.google.dev/api/generate-content",
    ),
    ProviderCatalogEntry(
        id="xai",
        label="xAI",
        default_base_url="https://api.x.ai/v1",
        default_model="grok-4.6",
        allow_custom_model=False,
        protocol_options=("openai_responses",),
        docs_url="https://docs.x.ai/docs/api-reference/responses",
    ),
    ProviderCatalogEntry(
        id="deepseek",
        label="DeepSeek",
        default_base_url="https://api.deepseek.com",
        default_model="deepseek-v4-pro",
        allow_custom_model=False,
        protocol_options=("openai_chat",),
        docs_url="https://api-docs.deepseek.com/api/create-chat-completion",
    ),
    ProviderCatalogEntry(
        id="qwen",
        label="Alibaba Qwen",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen3.8-max",
        allow_custom_model=False,
        protocol_options=("openai_chat",),
        docs_url=(
            "https://help.aliyun.com/zh/model-studio/"
            "compatibility-of-openai-with-dashscope"
        ),
    ),
    ProviderCatalogEntry(
        id="zhipu",
        label="Zhipu GLM",
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-5.3",
        allow_custom_model=False,
        protocol_options=("openai_chat",),
        docs_url=(
            "https://docs.bigmodel.cn/api-reference/"
            "%E6%A8%A1%E5%9E%8B-api/%E5%AF%B9%E8%AF%9D%E8%A1%A5%E5%85%A8"
        ),
    ),
    ProviderCatalogEntry(
        id="kimi",
        label="Moonshot Kimi",
        default_base_url="https://api.moonshot.cn/v1",
        default_model="kimi-k3",
        allow_custom_model=False,
        protocol_options=("openai_chat",),
        docs_url="https://platform.kimi.com/docs/api/chat",
    ),
    ProviderCatalogEntry(
        id="opencode",
        label="OpenCode Zen",
        default_base_url="https://opencode.ai/zen/v1",
        default_model="",
        allow_custom_model=True,
        protocol_options=PROTOCOL_NAMES,
        docs_url="https://opencode.ai/docs/zen/",
    ),
    ProviderCatalogEntry(
        id="siliconflow",
        label="SiliconFlow",
        default_base_url="https://api.siliconflow.cn/v1",
        default_model="",
        allow_custom_model=True,
        protocol_options=("openai_chat",),
        docs_url=(
            "https://docs.siliconflow.cn/cn/api-reference/"
            "chat-completions/chat-completions"
        ),
    ),
)


_OPENAI_MODELS: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry(
        id="gpt-5.6-sol",
        label="GPT-5.6 Sol",
        role="current_performance",
        generation="current",
        status="stable",
        protocol="openai_responses",
        tools=True,
        vision=True,
        thinking=True,
        streaming=True,
        context_limit=1_050_000,
        max_input_tokens=None,
        max_output_tokens=128_000,
        output_reserve_tokens=32_768,
        description="Current OpenAI performance flagship for complex agentic work.",
    ),
    ModelCatalogEntry(
        id="gpt-5.6-luna",
        label="GPT-5.6 Luna",
        role="current_speed",
        generation="current",
        status="stable",
        protocol="openai_responses",
        tools=True,
        vision=True,
        thinking=True,
        streaming=True,
        context_limit=1_050_000,
        max_input_tokens=None,
        max_output_tokens=128_000,
        output_reserve_tokens=32_768,
        description="Current OpenAI speed flagship for responsive agentic work.",
    ),
    ModelCatalogEntry(
        id="gpt-5.5-pro",
        label="GPT-5.5 Pro",
        role="previous_performance",
        generation="previous",
        status="stable",
        protocol="openai_responses",
        tools=True,
        vision=True,
        thinking=True,
        streaming=False,
        context_limit=1_050_000,
        max_input_tokens=None,
        max_output_tokens=128_000,
        output_reserve_tokens=32_768,
        description="Previous OpenAI performance flagship.",
    ),
)


_ANTHROPIC_MODELS: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry(
        id="claude-fable-5",
        label="Claude Fable 5",
        role="current_performance",
        generation="current",
        status="stable",
        protocol="anthropic_messages",
        tools=True,
        vision=True,
        thinking=True,
        streaming=True,
        context_limit=1_000_000,
        max_input_tokens=None,
        max_output_tokens=128_000,
        output_reserve_tokens=8_192,
        description="Current highest-capability Anthropic performance flagship.",
    ),
    ModelCatalogEntry(
        id="claude-sonnet-5",
        label="Claude Sonnet 5",
        role="current_speed",
        generation="current",
        status="stable",
        protocol="anthropic_messages",
        tools=True,
        vision=True,
        thinking=True,
        streaming=True,
        context_limit=1_000_000,
        max_input_tokens=None,
        max_output_tokens=128_000,
        output_reserve_tokens=8_192,
        description="Current Anthropic speed flagship.",
    ),
    ModelCatalogEntry(
        id="claude-opus-4-8",
        label="Claude Opus 4.8",
        role="previous_performance",
        generation="previous",
        status="stable",
        protocol="anthropic_messages",
        tools=True,
        vision=True,
        thinking=True,
        streaming=True,
        context_limit=1_000_000,
        max_input_tokens=None,
        max_output_tokens=128_000,
        output_reserve_tokens=8_192,
        description="Previous Anthropic performance flagship.",
    ),
    ModelCatalogEntry(
        id="claude-sonnet-4-6",
        label="Claude Sonnet 4.6",
        role="previous_speed",
        generation="previous",
        status="stable",
        protocol="anthropic_messages",
        tools=True,
        vision=True,
        thinking=True,
        streaming=True,
        context_limit=1_000_000,
        max_input_tokens=None,
        max_output_tokens=128_000,
        output_reserve_tokens=8_192,
        description="Previous Anthropic speed flagship.",
    ),
)


_GEMINI_MODELS: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry(
        id="gemini-3.1-pro-preview",
        label="Gemini 3.1 Pro Preview",
        role="current_performance",
        generation="current",
        status="preview",
        protocol="gemini_generate_content",
        tools=True,
        vision=True,
        thinking=True,
        streaming=True,
        context_limit=1_048_576,
        max_input_tokens=1_048_576,
        max_output_tokens=65_536,
        output_reserve_tokens=32_768,
        description="Current Gemini performance model; preview service status.",
    ),
    ModelCatalogEntry(
        id="gemini-3.7-flash",
        label="Gemini 3.7 Flash",
        role="current_speed",
        generation="current",
        status="stable",
        protocol="gemini_generate_content",
        tools=True,
        vision=True,
        thinking=True,
        streaming=True,
        context_limit=1_048_576,
        max_input_tokens=1_048_576,
        max_output_tokens=65_536,
        output_reserve_tokens=32_768,
        description="Current stable Gemini speed flagship.",
    ),
    ModelCatalogEntry(
        id="gemini-2.5-pro",
        label="Gemini 2.5 Pro",
        role="previous_performance",
        generation="previous",
        status="stable",
        protocol="gemini_generate_content",
        tools=True,
        vision=True,
        thinking=True,
        streaming=True,
        context_limit=1_048_576,
        max_input_tokens=1_048_576,
        max_output_tokens=65_536,
        output_reserve_tokens=32_768,
        description="Previous stable Gemini performance flagship.",
    ),
    ModelCatalogEntry(
        id="gemini-3.6-flash",
        label="Gemini 3.6 Flash",
        role="previous_speed",
        generation="previous",
        status="stable",
        protocol="gemini_generate_content",
        tools=True,
        vision=True,
        thinking=True,
        streaming=True,
        context_limit=1_048_576,
        max_input_tokens=1_048_576,
        max_output_tokens=65_536,
        output_reserve_tokens=32_768,
        description="Previous stable Gemini speed flagship.",
    ),
)


_XAI_MODELS: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry(
        id="grok-4.6",
        label="Grok 4.6",
        role="current_performance",
        generation="current",
        status="stable",
        protocol="openai_responses",
        tools=True,
        vision=True,
        thinking=True,
        streaming=True,
        context_limit=500_000,
        max_input_tokens=None,
        max_output_tokens=None,
        output_reserve_tokens=_DEFAULT_OUTPUT_RESERVE_TOKENS,
        description="Current xAI performance flagship.",
    ),
    ModelCatalogEntry(
        id="grok-4.5",
        label="Grok 4.5",
        role="previous_performance",
        generation="previous",
        status="stable",
        protocol="openai_responses",
        tools=True,
        vision=True,
        thinking=True,
        streaming=True,
        context_limit=500_000,
        max_input_tokens=None,
        max_output_tokens=None,
        output_reserve_tokens=_DEFAULT_OUTPUT_RESERVE_TOKENS,
        description="Previous xAI performance flagship.",
    ),
)


_DEEPSEEK_MODELS: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry(
        id="deepseek-v4-pro",
        label="DeepSeek V4 Pro",
        role="current_performance",
        generation="current",
        status="stable",
        protocol="openai_chat",
        tools=True,
        vision=False,
        thinking=True,
        streaming=True,
        context_limit=1_000_000,
        max_input_tokens=None,
        max_output_tokens=384_000,
        output_reserve_tokens=32_768,
        description="Current stable DeepSeek V4 performance flagship.",
    ),
    ModelCatalogEntry(
        id="deepseek-v4-flash",
        label="DeepSeek V4 Flash",
        role="current_speed",
        generation="current",
        status="preview",
        protocol="openai_chat",
        tools=True,
        vision=False,
        thinking=True,
        streaming=True,
        context_limit=1_000_000,
        max_input_tokens=None,
        max_output_tokens=384_000,
        output_reserve_tokens=32_768,
        description="Current DeepSeek V4 speed model; preview service status.",
    ),
)


_QWEN_MODELS: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry(
        id="qwen3.8-max",
        label="Qwen3.8-Max",
        role="current_performance",
        generation="current",
        status="stable",
        protocol="openai_chat",
        tools=True,
        vision=True,
        thinking=True,
        streaming=True,
        context_limit=1_000_000,
        max_input_tokens=983_616,
        max_output_tokens=131_072,
        output_reserve_tokens=32_768,
        description="Current Qwen performance flagship on the Beijing endpoint.",
    ),
    ModelCatalogEntry(
        id="qwen3.7-flash",
        label="Qwen3.7-Flash",
        role="current_speed",
        generation="current",
        status="stable",
        protocol="openai_chat",
        tools=True,
        vision=True,
        thinking=True,
        streaming=True,
        context_limit=1_000_000,
        max_input_tokens=983_616,
        max_output_tokens=131_072,
        output_reserve_tokens=32_768,
        description="Current Qwen speed flagship on the Beijing endpoint.",
    ),
    ModelCatalogEntry(
        id="qwen3.7-max",
        label="Qwen3.7-Max",
        role="previous_performance",
        generation="previous",
        status="stable",
        protocol="openai_chat",
        tools=True,
        vision=True,
        thinking=True,
        streaming=True,
        context_limit=1_000_000,
        max_input_tokens=983_616,
        max_output_tokens=131_072,
        output_reserve_tokens=32_768,
        description="Previous Qwen performance flagship on the Beijing endpoint.",
    ),
    ModelCatalogEntry(
        id="qwen3.6-flash",
        label="Qwen3.6-Flash",
        role="previous_speed",
        generation="previous",
        status="stable",
        protocol="openai_chat",
        tools=True,
        vision=True,
        thinking=True,
        streaming=True,
        context_limit=1_000_000,
        max_input_tokens=983_616,
        max_output_tokens=65_536,
        output_reserve_tokens=32_768,
        description="Previous Qwen speed flagship on the Beijing endpoint.",
    ),
)


_ZHIPU_MODELS: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry(
        id="glm-5.3",
        label="GLM-5.3",
        role="current_performance",
        generation="current",
        status="stable",
        protocol="openai_chat",
        tools=True,
        vision=False,
        thinking=True,
        streaming=True,
        context_limit=1_000_000,
        max_input_tokens=None,
        max_output_tokens=131_072,
        output_reserve_tokens=32_768,
        description="Current Zhipu GLM performance flagship.",
    ),
    ModelCatalogEntry(
        id="glm-5.2",
        label="GLM-5.2",
        role="previous_performance",
        generation="previous",
        status="stable",
        protocol="openai_chat",
        tools=True,
        vision=False,
        thinking=True,
        streaming=True,
        context_limit=1_000_000,
        max_input_tokens=None,
        max_output_tokens=131_072,
        output_reserve_tokens=32_768,
        description="Previous Zhipu GLM performance flagship.",
    ),
)


_KIMI_MODELS: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry(
        id="kimi-k3",
        label="Kimi K3",
        role="current_performance",
        generation="current",
        status="stable",
        protocol="openai_chat",
        tools=True,
        vision=True,
        thinking=True,
        streaming=True,
        context_limit=1_048_576,
        max_input_tokens=None,
        max_output_tokens=1_048_576,
        output_reserve_tokens=131_072,
        description="Current Moonshot Kimi performance flagship.",
    ),
)


MODELS_BY_PROVIDER: Mapping[str, tuple[ModelCatalogEntry, ...]] = MappingProxyType(
    {
        "openai": _OPENAI_MODELS,
        "anthropic": _ANTHROPIC_MODELS,
        "gemini": _GEMINI_MODELS,
        "xai": _XAI_MODELS,
        "deepseek": _DEEPSEEK_MODELS,
        "qwen": _QWEN_MODELS,
        "zhipu": _ZHIPU_MODELS,
        "kimi": _KIMI_MODELS,
        "opencode": (),
        "siliconflow": (),
    }
)

PROVIDERS_BY_ID: Mapping[str, ProviderCatalogEntry] = MappingProxyType(
    {provider.id: provider for provider in PROVIDERS}
)

_MODELS_BY_ID: Mapping[str, Mapping[str, ModelCatalogEntry]] = MappingProxyType(
    {
        provider_id: MappingProxyType({model.id: model for model in models})
        for provider_id, models in MODELS_BY_PROVIDER.items()
    }
)


def list_providers() -> tuple[ProviderCatalogEntry, ...]:
    """Return every supported provider in deterministic UI order."""

    return PROVIDERS


def get_provider(provider_id: str) -> ProviderCatalogEntry | None:
    """Return one provider by its exact ID, or ``None`` when it is unknown."""

    return PROVIDERS_BY_ID.get(str(provider_id or "").strip())


def list_models(provider_id: str) -> tuple[ModelCatalogEntry, ...]:
    """Return the immutable curated model tuple for a provider."""

    return MODELS_BY_PROVIDER.get(str(provider_id or "").strip(), ())


def get_model(provider_id: str, model_id: str) -> ModelCatalogEntry | None:
    """Return one curated model by exact provider and model IDs."""

    normalized_provider = str(provider_id or "").strip()
    normalized_model = str(model_id or "").strip()
    provider_models = _MODELS_BY_ID.get(normalized_provider)
    if provider_models is None:
        return None
    return provider_models.get(normalized_model)


def validate_selection(
    provider_id: str,
    model_id: str,
    protocol: str | None = None,
) -> None:
    """Validate an explicit selection intended for persistent configuration.

    Curated providers require exact catalog membership.  Aggregators accept any
    non-empty model ID.  OpenCode additionally requires an explicit supported
    protocol because it exposes more than one wire protocol.

    Raises:
        ValueError: if the provider, model, or protocol is invalid.
    """

    _resolve_selection(
        provider_id=provider_id,
        model_id=model_id,
        protocol=protocol,
        allow_default_model=False,
    )


def resolve_selection(
    provider_id: str,
    model_id: str = "",
    protocol: str | None = None,
) -> ResolvedProviderSelection:
    """Resolve a runtime selection, using a curated provider default if needed."""

    return _resolve_selection(
        provider_id=provider_id,
        model_id=model_id,
        protocol=protocol,
        allow_default_model=True,
    )


def _resolve_selection(
    *,
    provider_id: str,
    model_id: str,
    protocol: str | None,
    allow_default_model: bool,
) -> ResolvedProviderSelection:
    normalized_provider = str(provider_id or "").strip()
    provider = get_provider(normalized_provider)
    if provider is None:
        raise ValueError(f"Unknown provider: {normalized_provider or '<empty>'}")

    normalized_model = str(model_id or "").strip()
    if not normalized_model and allow_default_model:
        normalized_model = provider.default_model
    if not normalized_model:
        raise ValueError(f"Model is required for provider: {provider.id}")

    normalized_protocol = str(protocol or "").strip()
    model: ModelCatalogEntry | None

    if provider.allow_custom_model:
        model = None
        if not normalized_protocol:
            if len(provider.protocol_options) == 1:
                normalized_protocol = provider.protocol_options[0]
            else:
                raise ValueError(f"Protocol is required for provider: {provider.id}")
    else:
        model = get_model(provider.id, normalized_model)
        if model is None:
            raise ValueError(
                f"Unknown model for provider {provider.id}: {normalized_model}"
            )
        if not normalized_protocol:
            normalized_protocol = model.protocol
        elif normalized_protocol != model.protocol:
            raise ValueError(
                f"Model {normalized_model} requires protocol: {model.protocol}"
            )

    if normalized_protocol not in provider.protocol_options:
        raise ValueError(
            f"Unsupported protocol for provider {provider.id}: "
            f"{normalized_protocol or '<empty>'}"
        )

    return ResolvedProviderSelection(
        provider=provider,
        model_id=normalized_model,
        protocol=cast(ProtocolName, normalized_protocol),
        model=model,
    )


__all__ = [
    "MODELS_BY_PROVIDER",
    "PROTOCOL_NAMES",
    "PROVIDERS",
    "PROVIDERS_BY_ID",
    "ModelCatalogEntry",
    "ModelGeneration",
    "ModelRole",
    "ModelStatus",
    "ProtocolName",
    "ProviderCatalogEntry",
    "ResolvedProviderSelection",
    "get_model",
    "get_provider",
    "list_models",
    "list_providers",
    "resolve_selection",
    "validate_selection",
]
