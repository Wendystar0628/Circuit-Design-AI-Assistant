from types import SimpleNamespace

from domain.llm.token_counter import (
    get_model_context_limit,
    get_model_input_limit,
    get_model_output_limit,
    get_model_output_reserve,
)
from domain.llm.token_monitor import TokenMonitor
from shared.service_locator import ServiceLocator
from shared.service_names import SVC_LLM_RUNTIME_CONFIG_MANAGER


class _RuntimeConfigManagerStub:
    def resolve_active_config(self):
        return SimpleNamespace(provider="openai", model="gpt-5.6-sol")


def test_default_token_budget_uses_the_registered_active_model() -> None:
    previous = ServiceLocator.get_optional(SVC_LLM_RUNTIME_CONFIG_MANAGER)
    ServiceLocator.register(
        SVC_LLM_RUNTIME_CONFIG_MANAGER,
        _RuntimeConfigManagerStub(),
    )
    try:
        assert get_model_context_limit() == 1_050_000
        assert get_model_output_limit() == 128_000
        assert get_model_output_reserve() == 32_768
        assert get_model_input_limit() == 1_017_232
    finally:
        ServiceLocator.unregister(SVC_LLM_RUNTIME_CONFIG_MANAGER)
        if previous is not None:
            ServiceLocator.register(SVC_LLM_RUNTIME_CONFIG_MANAGER, previous)


def test_explicit_model_input_limit_is_not_reduced_by_output_limit() -> None:
    assert get_model_context_limit("gemini-3.7-flash", "gemini") == 1_048_576
    assert get_model_output_limit("gemini-3.7-flash", "gemini") == 65_536
    assert get_model_output_reserve("gemini-3.7-flash", "gemini") == 32_768
    assert get_model_input_limit("gemini-3.7-flash", "gemini") == 1_048_576


def test_hard_output_limit_and_runtime_reserve_are_distinct() -> None:
    assert get_model_output_limit("kimi-k3", "kimi") == 1_048_576
    assert get_model_output_reserve("kimi-k3", "kimi") == 131_072
    assert get_model_input_limit("kimi-k3", "kimi") == 917_504

    assert get_model_output_limit("grok-4.6", "xai") is None
    assert get_model_output_reserve("grok-4.6", "xai") == 32_768
    assert get_model_input_limit("grok-4.6", "xai") == 467_232


def test_mode_safe_qwen_input_limit_uses_vendor_ceiling() -> None:
    assert get_model_input_limit("qwen3.8-max", "qwen") == 983_616
    assert get_model_output_limit("qwen3.8-max", "qwen") == 131_072
    assert get_model_output_reserve("qwen3.8-max", "qwen") == 32_768


def test_token_monitor_reports_runtime_reserve_not_hard_output_limit() -> None:
    usage = TokenMonitor().calculate_usage(
        {"messages": []},
        model="kimi-k3",
        provider="kimi",
    )

    assert usage["context_limit"] == 1_048_576
    assert usage["output_reserve"] == 131_072
    assert usage["input_limit"] == 917_504
