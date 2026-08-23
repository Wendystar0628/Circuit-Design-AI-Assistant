from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from application.runtime import ApplicationRuntime, RuntimeErrorResponse
from infrastructure.llm_adapters.client_factory import LLMClientFactory
from shared.service_locator import ServiceLocator
from shared.service_names import SVC_LLM_CLIENT


class _ClosableClient:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def test_refresh_failure_keeps_the_working_client(monkeypatch) -> None:
    async def scenario() -> None:
        runtime = ApplicationRuntime()
        previous = _ClosableClient()
        runtime.llm_client = previous
        runtime.llm_runtime_config_manager = SimpleNamespace(
            resolve_active_config=lambda: SimpleNamespace(
                is_configured=True,
                api_key="test-key",
                provider="siliconflow",
                effective_base_url="https://gateway.example/v1",
                model="vendor/model",
                timeout=60,
                api_protocol="openai_chat",
            )
        )
        ServiceLocator.register(SVC_LLM_CLIENT, previous)

        def fail_create(**_kwargs):
            raise ValueError("candidate failed")

        monkeypatch.setattr(LLMClientFactory, "create_client", fail_create)
        try:
            with pytest.raises(ValueError, match="candidate failed"):
                await runtime.refresh_llm()
            assert runtime.llm_client is previous
            assert ServiceLocator.get(SVC_LLM_CLIENT) is previous
            assert previous.closed is False
        finally:
            ServiceLocator.clear()

    asyncio.run(scenario())


def test_startup_llm_failure_is_nonfatal() -> None:
    async def scenario() -> None:
        runtime = ApplicationRuntime()

        async def fail_refresh() -> bool:
            raise ValueError("invalid saved endpoint")

        runtime.refresh_llm = fail_refresh  # type: ignore[method-assign]
        await runtime._initialize_llm_client()

    asyncio.run(scenario())


def test_chat_config_change_is_rejected_during_an_active_run() -> None:
    async def scenario() -> None:
        runtime = ApplicationRuntime()
        blocker = asyncio.Event()
        task = asyncio.create_task(blocker.wait())
        runtime._active_conversation_task = task
        try:
            with pytest.raises(RuntimeErrorResponse) as captured:
                await runtime.save_chat_model_config({})
            assert captured.value.status_code == 409
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_chat_persistence_failure_returns_500_and_keeps_old_client() -> None:
    async def scenario() -> None:
        runtime = ApplicationRuntime()
        previous = _ClosableClient()
        runtime.llm_client = previous
        runtime.credential_manager = SimpleNamespace(
            get_credential=lambda *_args: {"api_key": "saved-test-key"}
        )

        def fail_save(**_kwargs):
            raise RuntimeError("Failed to persist the LLM configuration")

        runtime.llm_runtime_config_manager = SimpleNamespace(
            save_active_chat_config=fail_save
        )

        with pytest.raises(RuntimeErrorResponse) as captured:
            await runtime.save_chat_model_config(
                {
                    "provider": "openai",
                    "model": "gpt-5.6-sol",
                    "api_protocol": "openai_responses",
                    "base_url": "",
                    "timeout": 60,
                    "enable_thinking": False,
                }
            )

        assert captured.value.status_code == 500
        assert runtime.llm_client is previous
        assert previous.closed is False

    asyncio.run(scenario())
