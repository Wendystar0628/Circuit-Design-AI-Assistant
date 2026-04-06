from typing import Optional

from infrastructure.llm_adapters.base_client import BaseLLMClient
from infrastructure.llm_adapters.deepseek import DeepSeekClient
from infrastructure.llm_adapters.qwen import QwenClient
from infrastructure.llm_adapters.zhipu import ZhipuClient


class LLMClientFactory:
    @staticmethod
    def create_client(
        provider_id: str,
        api_key: str,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 60,
    ) -> BaseLLMClient:
        normalized_provider = (provider_id or "").strip().lower()
        if normalized_provider == "zhipu":
            return ZhipuClient(
                api_key=api_key,
                base_url=base_url if base_url else None,
                model=model if model else None,
                timeout=timeout,
            )
        if normalized_provider == "deepseek":
            return DeepSeekClient(
                api_key=api_key,
                base_url=base_url if base_url else None,
                model=model if model else None,
                timeout=timeout,
            )
        if normalized_provider == "qwen":
            return QwenClient(
                api_key=api_key,
                base_url=base_url if base_url else None,
                model=model if model else None,
                timeout=timeout,
            )
        raise ValueError(f"Unsupported LLM provider: {provider_id}")


__all__ = ["LLMClientFactory"]
