# Embedder - Local Sentence Embedding Model Wrapper
"""
本地 Embedding 模型封装

使用 sentence-transformers 库在本地生成文本向量，无需网络调用。
模型首次使用时懒加载，之后常驻内存。

默认模型：all-MiniLM-L6-v2（384 维，模型约 90MB，~0.5ms/chunk）
"""

import logging
import threading
from typing import List, Optional

logger = logging.getLogger(__name__)

_BATCH_SIZE = 64


class Embedder:
    """
    线程安全的本地 Embedding 模型单例

    懒加载：第一次调用 embed_texts() 时才真正加载模型权重，
    不阻塞应用启动流程。
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None
        self._model_lock = threading.Lock()

    # ============================================================
    # 内部：模型加载
    # ============================================================

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        with self._model_lock:
            if self._model is not None:
                return
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(f"Loading embedding model: {self._model_name}")
                self._model = SentenceTransformer(self._model_name)
                logger.info(
                    f"Embedding model loaded: {self._model_name} "
                    f"(dim={self._model.get_sentence_embedding_dimension()})"
                )
            except ImportError as exc:
                raise ImportError(
                    "sentence-transformers is not installed. "
                    "Run: pip install sentence-transformers"
                ) from exc
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to load embedding model '{self._model_name}': {exc}"
                ) from exc

    # ============================================================
    # 公共接口
    # ============================================================

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        批量生成文本向量

        Args:
            texts: 文本列表

        Returns:
            与输入等长的 float 列表列表（每项为 384 维向量）
        """
        if not texts:
            return []

        self._ensure_model()

        results: List[List[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            embeddings = self._model.encode(
                batch,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            results.extend(embeddings.tolist())

        return results

    def embed_single(self, text: str) -> List[float]:
        """生成单条文本向量"""
        result = self.embed_texts([text])
        return result[0] if result else []

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def model_name(self) -> str:
        return self._model_name


__all__ = ["Embedder"]
