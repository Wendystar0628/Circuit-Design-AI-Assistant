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

logger = logging.getLogger(__name__)

_ZHIPU_EMBEDDING_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"
_ZHIPU_EMBEDDING_MODEL = "embedding-3"
_BATCH_SIZE = 32      # 每批最多 32 条（API 限制）
_TIMEOUT = 30.0       # 单次请求超时秒数


class Embedder:
    """
    智谱 embedding-3 向量化器

    与对话模型共用同一 API Key，无需额外配置。
    使用 httpx 同步调用（在 RAGWorkerThread 内执行，不阻塞 Qt 主线程）。
    """

    def __init__(self):
        self._api_key: str = ""

    # ============================================================
    # 内部
    # ============================================================

    def _get_api_key(self) -> str:
        if self._api_key:
            return self._api_key
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_CREDENTIAL_MANAGER
            cm = ServiceLocator.get_optional(SVC_CREDENTIAL_MANAGER)
            if cm:
                credential = cm.get_credential("llm", "zhipu")
                if credential:
                    key = credential.get("api_key", "") if isinstance(credential, dict) else str(credential)
                    if key:
                        self._api_key = key
                        return self._api_key
        except Exception as exc:
            logger.debug(f"CredentialManager unavailable: {exc}")
        raise RuntimeError(
            "Zhipu API key not configured. "
            "Please set it in Settings → Model Configuration."
        )

    def _call_api(self, batch: List[str]) -> List[List[float]]:
        api_key = self._get_api_key()
        resp = httpx.post(
            _ZHIPU_EMBEDDING_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"input": batch, "model": _ZHIPU_EMBEDDING_MODEL},
            timeout=_TIMEOUT,
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

        results: List[List[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            results.extend(self._call_api(batch))

        return results

    def embed_single(self, text: str) -> List[float]:
        """生成单条文本向量"""
        result = self.embed_texts([text])
        return result[0] if result else []

    @property
    def model_name(self) -> str:
        return _ZHIPU_EMBEDDING_MODEL


__all__ = ["Embedder"]
