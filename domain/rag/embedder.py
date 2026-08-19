# Embedder - Zhipu AI Embedding via REST API
"""
文本向量化模块

使用智谱 embedding-3 API 生成文本向量，与对话模型共用同一 API Key。

接口：POST https://open.bigmodel.cn/api/paas/v4/embeddings
模型：embedding-3（2048 维）
认证：Bearer {zhipu_api_key}（从 CredentialManager 获取）
"""

import logging
from dataclasses import dataclass
from typing import List

import httpx

from infrastructure.config.settings import (
    CONFIG_EMBEDDING_BASE_URL,
    CONFIG_EMBEDDING_BATCH_SIZE,
    CONFIG_EMBEDDING_MODEL,
    CONFIG_EMBEDDING_TIMEOUT,
    CONFIG_EMBEDDING_PROVIDER,
)

logger = logging.getLogger(__name__)

_BATCH_SIZE = 32      # 每批最多 32 条（API 限制）
_TIMEOUT = 30.0       # 单次请求超时秒数


@dataclass(frozen=True)
class EmbeddingRuntimeConfig:
    """A task-stable embedding configuration.

    RAG jobs may outlive a settings-panel change.  Resolving the model for
    every HTTP batch can otherwise mix vector dimensions in one index run.
    """

    provider_id: str
    model_name: str
    base_url: str
    batch_size: int
    timeout: int
    dimensions: int


class Embedder:
    """
    智谱 embedding-3 向量化器

    使用独立的 embedding 配置与 embedding 凭证。
    使用 httpx 同步调用（在 RAGWorkerThread 内执行，不阻塞 Qt 主线程）。
    """

    def __init__(self, config: EmbeddingRuntimeConfig | None = None):
        # Freeze once per project/runtime.  A later reindex creates a new
        # Embedder and compares its signature before touching the collection.
        self._config = config or self.resolve_runtime_config()

    @classmethod
    def resolve_runtime_config(cls) -> EmbeddingRuntimeConfig:
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_CONFIG_MANAGER
            from shared.embedding_model_registry import EmbeddingModelRegistry

            config_manager = ServiceLocator.get_optional(SVC_CONFIG_MANAGER)
            EmbeddingModelRegistry.initialize()

            provider_id = ""
            if config_manager:
                provider_id = str(config_manager.get(CONFIG_EMBEDDING_PROVIDER, "") or "").strip()

            if not provider_id:
                default_provider = EmbeddingModelRegistry.get_default_provider()
                provider_id = default_provider.id if default_provider else "zhipu"

            if provider_id != "zhipu":
                raise RuntimeError("Only Zhipu embedding is currently supported.")

            provider = EmbeddingModelRegistry.get_provider(provider_id)
            default_model = EmbeddingModelRegistry.get_default_model(provider_id)
            model_name = default_model.name if default_model else "embedding-3"
            default_base_url = provider.base_url if provider else "https://open.bigmodel.cn/api/paas/v4/embeddings"

            if config_manager:
                configured_provider = config_manager.get(CONFIG_EMBEDDING_PROVIDER, provider_id)
                if configured_provider != "zhipu":
                    raise RuntimeError("Only Zhipu embedding is currently supported.")

                configured_model = str(config_manager.get(CONFIG_EMBEDDING_MODEL, "") or "").strip()
                if configured_model:
                    configured_model_config = EmbeddingModelRegistry.get_model_by_name(configured_provider, configured_model)
                    if configured_model_config:
                        model_name = configured_model_config.name

                base_url = config_manager.get(CONFIG_EMBEDDING_BASE_URL, "") or default_base_url
                timeout = int(config_manager.get(CONFIG_EMBEDDING_TIMEOUT, _TIMEOUT))
                batch_size = int(config_manager.get(CONFIG_EMBEDDING_BATCH_SIZE, _BATCH_SIZE))
                model_config = EmbeddingModelRegistry.get_model_by_name(
                    configured_provider, model_name
                )
                return EmbeddingRuntimeConfig(
                    provider_id=configured_provider,
                    model_name=model_name,
                    base_url=str(base_url),
                    batch_size=max(batch_size, 1),
                    timeout=max(timeout, 1),
                    dimensions=int(getattr(model_config, "dimensions", 0) or 0),
                )

            model_config = EmbeddingModelRegistry.get_model_by_name(provider_id, model_name)
            return EmbeddingRuntimeConfig(
                provider_id=provider_id,
                model_name=model_name,
                base_url=str(default_base_url),
                batch_size=_BATCH_SIZE,
                timeout=int(_TIMEOUT),
                dimensions=int(getattr(model_config, "dimensions", 0) or 0),
            )
        except RuntimeError:
            raise
        except Exception as exc:
            try:
                from shared.embedding_model_registry import EmbeddingModelRegistry

                EmbeddingModelRegistry.initialize()
                default_provider = EmbeddingModelRegistry.get_default_provider()
                provider_id = default_provider.id if default_provider else "zhipu"
                provider = EmbeddingModelRegistry.get_provider(provider_id)
                default_model = EmbeddingModelRegistry.get_default_model(provider_id)
                model_name = default_model.name if default_model else "embedding-3"
                base_url = provider.base_url if provider else "https://open.bigmodel.cn/api/paas/v4/embeddings"
                logger.debug(f"Embedding config unavailable, fallback to registry default: {exc}")
                model_config = EmbeddingModelRegistry.get_model_by_name(provider_id, model_name)
                return EmbeddingRuntimeConfig(
                    provider_id=provider_id,
                    model_name=model_name,
                    base_url=str(base_url),
                    batch_size=_BATCH_SIZE,
                    timeout=int(_TIMEOUT),
                    dimensions=int(getattr(model_config, "dimensions", 0) or 0),
                )
            except Exception:
                pass
            logger.debug(f"Embedding config unavailable, fallback to default: {exc}")
            return EmbeddingRuntimeConfig(
                provider_id="zhipu",
                model_name="embedding-3",
                base_url="https://open.bigmodel.cn/api/paas/v4/embeddings",
                batch_size=_BATCH_SIZE,
                timeout=int(_TIMEOUT),
                dimensions=2048,
            )

    def _get_embedding_config(self) -> tuple[str, str, str, int, int]:
        config = self._config
        return (
            config.provider_id,
            config.model_name,
            config.base_url,
            config.batch_size,
            config.timeout,
        )

    # ============================================================
    # 内部
    # ============================================================

    def _get_api_key(self) -> str:
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_CREDENTIAL_MANAGER
            cm = ServiceLocator.get_optional(SVC_CREDENTIAL_MANAGER)
            if cm:
                credential = cm.get_credential("embedding", "zhipu")
                if credential:
                    key = credential.get("api_key", "") if isinstance(credential, dict) else str(credential)
                    key = key.strip()
                    if key:
                        return key
        except Exception as exc:
            logger.debug(f"CredentialManager unavailable: {exc}")
        raise RuntimeError(
            "Zhipu embedding API key not configured. "
            "Please set it in Settings → Model Configuration."
        )

    def _call_api(self, batch: List[str]) -> List[List[float]]:
        provider_id, model_name, base_url, _, timeout = self._get_embedding_config()
        if provider_id != "zhipu":
            raise RuntimeError("Only Zhipu embedding is currently supported.")

        api_key = self._get_api_key()
        resp = httpx.post(
            base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"input": batch, "model": model_name},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        items = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in items]

    # ============================================================
    # 公共接口
    # ============================================================

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        批量生成文本向量

        Args:
            texts: 文本列表

        Returns:
            与输入等长的 float 列表列表（每项为 2048 维向量）
        """
        if not texts:
            return []

        _, _, _, batch_size, _ = self._get_embedding_config()
        results: List[List[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            results.extend(self._call_api(batch))

        return results

    def embed_single(self, text: str) -> List[float]:
        """生成单条文本向量"""
        result = self.embed_texts([text])
        return result[0] if result else []

    @property
    def model_name(self) -> str:
        return self._config.model_name

    @property
    def provider_id(self) -> str:
        return self._config.provider_id

    @property
    def dimensions(self) -> int:
        return self._config.dimensions

    @property
    def runtime_config(self) -> EmbeddingRuntimeConfig:
        return self._config


__all__ = ["Embedder", "EmbeddingRuntimeConfig"]
