from typing import Optional

from infrastructure.config.settings import DEFAULT_TIMEOUT
from infrastructure.llm_adapters.model_configs.qwen_models import QWEN_PROVIDER
from infrastructure.llm_adapters.openai_compatible_client import OpenAICompatibleClient


class QwenClient(OpenAICompatibleClient):
    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        super().__init__(
            provider_id=QWEN_PROVIDER.id,
            api_key=api_key,
            base_url=base_url or QWEN_PROVIDER.base_url,
            model=model or QWEN_PROVIDER.default_model,
            timeout=timeout,
            auth_header=QWEN_PROVIDER.auth_header,
            auth_prefix=QWEN_PROVIDER.auth_prefix,
        )


__all__ = ["QwenClient"]
