# Embedder - Zhipu AI Embedding via REST API
"""
文本向量化模块

使用智谱 embedding-3 API 生成文本向量，与对话模型共用同一 API Key。

接口：POST https://open.bigmodel.cn/api/paas/v4/embeddings
模型：embedding-3（2048 维）
认证：Bearer {zhipu_api_key}（从 CredentialManager 获取）
"""

import logging
from typing import List

import httpx

from infrastructure.config.settings import (
    CONFIG_EMBEDDING_BASE_URL,
    CONFIG_EMBEDDING_BATCH_SIZE,
    CONFIG_EMBEDDING_TIMEOUT,
    CONFIG_EMBEDDING_PROVIDER,
)

logger = logging.getLogger(__name__)

_BATCH_SIZE = 32      # 每批最多 32 条（API 限制）
_TIMEOUT = 30.0       # 单次请求超时秒数


class Embedder:
    """
    智谱 embedding-3 向量化器

    使用独立的 embedding 配置与 embedding 凭证。
    使用 httpx 同步调用（在 RAGWorkerThread 内执行，不阻塞 Qt 主线程）。
    """

    def _get_embedding_config(self) -> tuple[str, str, str, int, int]:
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_CONFIG_MANAGER
            from shared.embedding_model_registry import EmbeddingModelRegistry

            config_manager = ServiceLocator.get_optional(SVC_CONFIG_MANAGER)
            current_model = EmbeddingModelRegistry.get_current_model()
            provider_id = current_model.provider if current_model else "zhipu"
            model_name = current_model.name if current_model else "embedding-3"

            provider = EmbeddingModelRegistry.get_provider(provider_id)
            default_base_url = provider.base_url if provider else "https://open.bigmodel.cn/api/paas/v4/embeddings"

            if config_manager:
                configured_provider = config_manager.get(CONFIG_EMBEDDING_PROVIDER, provider_id)
                if configured_provider != "zhipu":
                    raise RuntimeError("Only Zhipu embedding is currently supported.")

                base_url = config_manager.get(CONFIG_EMBEDDING_BASE_URL, "") or default_base_url
                timeout = int(config_manager.get(CONFIG_EMBEDDING_TIMEOUT, _TIMEOUT))
                batch_size = int(config_manager.get(CONFIG_EMBEDDING_BATCH_SIZE, _BATCH_SIZE))
                return configured_provider, model_name, base_url, max(batch_size, 1), max(timeout, 1)

            return provider_id, model_name, default_base_url, _BATCH_SIZE, int(_TIMEOUT)
        except RuntimeError:
            raise
        except Exception as exc:
            logger.debug(f"Embedding config unavailable, fallback to default: {exc}")
            return "zhipu", "embedding-3", "https://open.bigmodel.cn/api/paas/v4/embeddings", _BATCH_SIZE, int(_TIMEOUT)

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
        _, model_name, _, _, _ = self._get_embedding_config()
        return model_name


__all__ = ["Embedder"]
