# Vector Store - ChromaDB-backed Persistent Vector Store
"""
ChromaDB 向量存储封装

职责：
- 封装 ChromaDB PersistentClient（嵌入式，无独立服务进程）
- 每个项目使用独立 Collection（基于项目路径 MD5 命名）
- 提供 chunk 级别的 upsert / delete / query 接口
- 定义 RAGQueryResult（向量检索结果）

存储路径：{project_root}/.circuit_ai/vector_store/
"""

import hashlib
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# 查询结果数据类
# ============================================================

@dataclass
class QueryHit:
    """单条检索命中"""
    content: str
    file_path: str
    score: float
    symbol_name: str = ""
    chunk_index: int = 0
    file_type: str = ""


class RAGQueryResult:
    """
    向量检索结果

    上层调用方：rag_search 工具、RAGManager。
    """

    def __init__(self, hits: Optional[List[QueryHit]] = None, error: str = ""):
        self.chunks: List[QueryHit] = hits or []
        self._error = error

    @property
    def is_empty(self) -> bool:
        return not self.chunks

    @property
    def chunks_count(self) -> int:
        return len(self.chunks)

    def format_as_context(self, max_tokens: int = 2000) -> str:
        """
        将检索结果格式化为可注入 Prompt 的上下文文本

        Args:
            max_tokens: 字符预算上限（粗估 1 token ≈ 4 字符）

        Returns:
            格式化的上下文字符串，无结果时返回空字符串
        """
        if self.is_empty:
            return ""

        budget = max_tokens * 4
        sections = []
        per_chunk = max(budget // max(len(self.chunks), 1), 200)

        for hit in self.chunks:
            if budget <= 0:
                break
            header = f"### {hit.file_path}"
            if hit.symbol_name and hit.symbol_name not in ("<header>", "<tail>"):
                header += f"  [{hit.symbol_name}]"
            snippet = hit.content[:per_chunk]
            block = f"{header}\n{snippet}"
            sections.append(block)
            budget -= len(block)

        return "\n\n---\n\n".join(sections)


# ============================================================
# VectorStore
# ============================================================

class VectorStore:
    """
    ChromaDB 向量存储，作用域为单个项目

    Collection 名称：project_{md5(abs_project_root)[:12]}
    距离函数：cosine（score = 1 - distance）
    """

    def __init__(self, project_root: str, storage_subdir: str = ".circuit_ai/vector_store"):
        self._project_root = os.path.abspath(project_root)
        self._storage_path = os.path.join(self._project_root, storage_subdir)
        self._client = None
        self._collection = None

        path_hash = hashlib.md5(self._project_root.encode("utf-8")).hexdigest()[:12]
        self._collection_name = f"project_{path_hash}"

    # ============================================================
    # 初始化
    # ============================================================

    def initialize(self) -> None:
        """
        初始化 ChromaDB PersistentClient 和 Collection（同步）

        Raises:
            ImportError: chromadb 未安装
            RuntimeError: 初始化失败
        """
        os.makedirs(self._storage_path, exist_ok=True)
        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=self._storage_path)
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                f"VectorStore initialized: collection={self._collection_name}, "
                f"docs={self._collection.count()}"
            )
        except ImportError as exc:
            raise ImportError(
                "chromadb is not installed. Run: pip install chromadb"
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"VectorStore initialization failed: {exc}") from exc

    @property
    def is_initialized(self) -> bool:
        return self._collection is not None

    # ============================================================
    # 写操作
    # ============================================================

    def upsert_file(
        self,
        rel_path: str,
        chunks: List[Any],
        vectors: List[List[float]],
    ) -> None:
        """
        先删除文件旧 chunk，再批量插入新 chunk（upsert 语义）

        Args:
            rel_path: 文件相对路径（作为 where 过滤条件）
            chunks:   List[Chunk]（来自 chunker.py）
            vectors:  与 chunks 等长的向量列表（来自 embedder.py）
        """
        if not self._collection:
            logger.warning("VectorStore not initialized, skipping upsert")
            return

        self._delete_by_file(rel_path)

        if not chunks:
            return

        ids       = [c.chunk_id for c in chunks]
        documents = [c.content for c in chunks]
        metadatas = [
            {
                "file_path":   c.file_path,
                "chunk_index": c.chunk_index,
                "file_type":   c.file_type,
                "symbol_name": c.symbol_name,
            }
            for c in chunks
        ]

        try:
            self._collection.upsert(
                ids=ids,
                documents=documents,
                embeddings=vectors,
                metadatas=metadatas,
            )
            logger.debug(f"Upserted {len(chunks)} chunks for {rel_path}")
        except Exception as exc:
            logger.error(f"Failed to upsert chunks for {rel_path}: {exc}")

    def delete_file(self, rel_path: str) -> None:
        """删除文件的所有 chunk"""
        if not self._collection:
            return
        self._delete_by_file(rel_path)

    def _delete_by_file(self, rel_path: str) -> None:
        try:
            existing = self._collection.get(
                where={"file_path": rel_path},
                include=[],
            )
            ids = existing.get("ids", [])
            if ids:
                self._collection.delete(ids=ids)
                logger.debug(f"Deleted {len(ids)} old chunks for {rel_path}")
        except Exception as exc:
            logger.debug(f"No old chunks to delete for {rel_path}: {exc}")

    def clear(self) -> None:
        """清空整个 Collection（重置知识库）"""
        if not self._client or not self._collection:
            return
        try:
            self._client.delete_collection(self._collection_name)
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(f"VectorStore collection cleared: {self._collection_name}")
        except Exception as exc:
            logger.error(f"Failed to clear VectorStore: {exc}")

    # ============================================================
    # 查询操作
    # ============================================================

    def query(
        self,
        vector: List[float],
        top_k: int = 10,
    ) -> List[QueryHit]:
        """
        余弦相似度检索

        Args:
            vector: 查询向量（来自 embedder.embed_single）
            top_k:  返回数量上限

        Returns:
            按 score 降序排列的 QueryHit 列表
        """
        if not self._collection:
            return []

        count = self._collection.count()
        if count == 0:
            return []

        n_results = min(top_k, count)
        try:
            results = self._collection.query(
                query_embeddings=[vector],
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            logger.error(f"VectorStore query failed: {exc}")
            return []

        hits: List[QueryHit] = []
        docs      = results.get("documents", [[]])[0]
        metas     = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for doc, meta, dist in zip(docs, metas, distances):
            hits.append(QueryHit(
                content=doc,
                file_path=meta.get("file_path", ""),
                score=max(0.0, 1.0 - float(dist)),  # cosine distance → similarity
                symbol_name=meta.get("symbol_name", ""),
                chunk_index=int(meta.get("chunk_index", 0)),
                file_type=meta.get("file_type", ""),
            ))

        return sorted(hits, key=lambda h: h.score, reverse=True)

    # ============================================================
    # 状态查询
    # ============================================================

    def count(self) -> int:
        if not self._collection:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0


__all__ = ["VectorStore", "RAGQueryResult", "QueryHit"]
