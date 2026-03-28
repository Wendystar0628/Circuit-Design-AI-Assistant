# RAG Service - LightRAG 封装层
"""
LightRAG 封装层

职责：
- 封装 LightRAG 实例的创建、初始化、销毁
- 适配 LLM 和 Embedding 函数（api_key 注入）
- 管理存储生命周期（initialize_storages / finalize_storages）

存储后端：JsonKVStorage + NanoVectorDBStorage + NetworkXStorage（LightRAG 默认）
工作目录：{project_root}/.circuit_ai/rag_storage/

架构位置：
- 被 RAGManager 调用
- 依赖 LightRAG 库、zhipuai SDK
- 通过 ServiceLocator 获取 API Key
"""

import logging
import os
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional

from infrastructure.config.settings import (
    DEFAULT_RAG_CHUNK_SIZE,
    DEFAULT_RAG_CHUNK_OVERLAP,
    DEFAULT_RAG_ENTITY_TYPES,
    DEFAULT_RAG_LANGUAGE,
    DEFAULT_RAG_STORAGE_DIR,
    DEFAULT_RAG_TOP_K,
    DEFAULT_EMBEDDING_DIM,
    DEFAULT_EMBEDDING_MAX_TOKEN_SIZE,
)


logger = logging.getLogger(__name__)


# ============================================================
# RAG 查询结果数据类
# ============================================================

class RAGQueryResult:
    """
    RAG 查询结果

    封装 LightRAG aquery_data() 返回的结构化数据，
    提供便捷属性访问。

    Attributes:
        entities: 匹配的实体列表
        relationships: 匹配的关系列表
        chunks: 匹配的文档分块列表
        references: 引用列表
        metadata: 查询元数据
        raw: 原始返回字典
    """

    def __init__(self, raw_data: Dict[str, Any]):
        self.raw = raw_data
        data = raw_data.get("data", {})
        self.entities: List[Dict] = data.get("entities", [])
        self.relationships: List[Dict] = data.get("relationships", [])
        self.chunks: List[Dict] = data.get("chunks", [])
        self.references: List[Dict] = data.get("references", [])
        self.metadata: Dict = raw_data.get("metadata", {})

    @property
    def is_success(self) -> bool:
        return self.raw.get("status") == "success"

    @property
    def entities_count(self) -> int:
        return len(self.entities)

    @property
    def relations_count(self) -> int:
        return len(self.relationships)

    @property
    def chunks_count(self) -> int:
        return len(self.chunks)

    @property
    def is_empty(self) -> bool:
        return not self.entities and not self.relationships and not self.chunks

    def format_as_context(self, max_tokens: int = 2000) -> str:
        """
        将检索结果格式化为可注入 Prompt 的上下文文本

        Args:
            max_tokens: Token 预算上限（粗估 1 token ≈ 4 字符）

        Returns:
            格式化的上下文字符串，为空时返回空字符串
        """
        if self.is_empty:
            return ""

        sections = []
        budget = max_tokens * 4  # 粗估字符预算

        # 实体
        if self.entities:
            lines = ["### Entities"]
            for e in self.entities[:20]:
                name = e.get("entity_name", "")
                etype = e.get("entity_type", "")
                desc = e.get("description", "")[:200]
                lines.append(f"- **{name}** ({etype}): {desc}")
            section = "\n".join(lines)
            if len(section) <= budget:
                sections.append(section)
                budget -= len(section)

        # 关系
        if self.relationships and budget > 0:
            lines = ["### Relationships"]
            for r in self.relationships[:15]:
                src = r.get("src_id", "")
                tgt = r.get("tgt_id", "")
                desc = r.get("description", "")[:150]
                lines.append(f"- {src} → {tgt}: {desc}")
            section = "\n".join(lines)
            if len(section) <= budget:
                sections.append(section)
                budget -= len(section)

        # 文档片段
        if self.chunks and budget > 0:
            lines = ["### Document Chunks"]
            for c in self.chunks[:10]:
                content = c.get("content", "")
                fp = c.get("file_path", "")
                # 截断到剩余预算
                max_len = min(len(content), budget // max(len(self.chunks), 1))
                snippet = content[:max_len]
                if fp:
                    lines.append(f"[{fp}]\n{snippet}")
                else:
                    lines.append(snippet)
                budget -= len(snippet)
                if budget <= 0:
                    break
            sections.append("\n".join(lines))

        return "\n\n".join(sections)


# ============================================================
# RAG Service
# ============================================================

class RAGService:
    """
    LightRAG 封装层

    管理 LightRAG 实例的完整生命周期：创建 → 初始化 → 使用 → 销毁。
    项目切换时销毁旧实例，创建新实例。
    """

    def __init__(self):
        self._rag = None  # LightRAG 实例
        self._project_root: Optional[str] = None
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized and self._rag is not None

    @property
    def project_root(self) -> Optional[str]:
        return self._project_root

    # ============================================================
    # 生命周期管理
    # ============================================================

    async def create(self, project_root: str) -> None:
        """
        创建 LightRAG 实例

        Args:
            project_root: 项目根目录绝对路径

        Raises:
            RuntimeError: API Key 未配置或 LightRAG 导入失败
        """
        # 销毁旧实例
        if self._rag is not None:
            await self.finalize()

        self._project_root = project_root
        working_dir = os.path.join(project_root, DEFAULT_RAG_STORAGE_DIR)
        os.makedirs(working_dir, exist_ok=True)

        # 获取 API Key
        api_key = self._get_api_key()
        if not api_key:
            raise RuntimeError(
                "Zhipu API Key 未配置，无法初始化 RAG。"
                "请在设置中配置 LLM API Key。"
            )

        try:
            from lightrag.lightrag import LightRAG
            from lightrag.utils import EmbeddingFunc
            from lightrag.llm.zhipu import zhipu_embedding, zhipu_complete

            # Embedding 适配：将 api_key 和 embedding_dim 注入 zhipu_embedding
            # 使用 .func 访问原始函数避免 EmbeddingFunc 双重包装
            # 必须传 embedding_dim 给底层函数，否则智谱 API 返回默认 2048 维
            embedding_func = EmbeddingFunc(
                func=partial(zhipu_embedding.func, api_key=api_key, embedding_dim=DEFAULT_EMBEDDING_DIM),
                embedding_dim=DEFAULT_EMBEDDING_DIM,
                max_token_size=DEFAULT_EMBEDDING_MAX_TOKEN_SIZE,
            )

            # LLM 适配：包装 zhipu_complete
            # 必须剥离 keyword_extraction 参数，因为 LightRAG 传入
            # keyword_extraction=True 但期望返回原始字符串（自行解析 JSON），
            # 而 zhipu_complete 在 keyword_extraction=True 时会返回
            # GPTKeywordExtractionFormat 对象，导致 regex 报错。
            async def _llm_wrapper(prompt, **kwargs):
                kwargs.pop("keyword_extraction", None)
                return await zhipu_complete(prompt, api_key=api_key, **kwargs)

            llm_func = _llm_wrapper

            self._rag = LightRAG(
                working_dir=working_dir,
                llm_model_func=llm_func,
                embedding_func=embedding_func,
                chunk_token_size=DEFAULT_RAG_CHUNK_SIZE,
                chunk_overlap_token_size=DEFAULT_RAG_CHUNK_OVERLAP,
                addon_params={
                    "language": DEFAULT_RAG_LANGUAGE,
                    "entity_types": list(DEFAULT_RAG_ENTITY_TYPES),
                },
            )

            logger.info(
                f"LightRAG instance created: working_dir={working_dir}"
            )

        except ImportError as e:
            raise RuntimeError(
                f"LightRAG 库导入失败，请确认已安装: {e}"
            )

    async def initialize(self) -> None:
        """
        初始化存储（必须在 create 之后调用）

        调用 LightRAG.initialize_storages() 初始化所有存储后端。
        """
        if self._rag is None:
            raise RuntimeError("RAGService.create() must be called first")

        await self._rag.initialize_storages()
        self._initialized = True
        logger.info("LightRAG storages initialized")

    async def finalize(self) -> None:
        """
        销毁实例并持久化存储

        项目关闭或切换时必须调用。
        """
        if self._rag is not None and self._initialized:
            try:
                await self._rag.finalize_storages()
                logger.info("LightRAG storages finalized")
            except Exception as e:
                logger.error(f"Failed to finalize LightRAG storages: {e}")

        self._rag = None
        self._initialized = False
        self._project_root = None

    # ============================================================
    # 文档操作
    # ============================================================

    async def insert(
        self,
        texts: List[str],
        file_paths: Optional[List[str]] = None,
        ids: Optional[List[str]] = None,
    ) -> str:
        """
        插入文档到 LightRAG

        Args:
            texts: 文档文本列表
            file_paths: 对应的文件路径列表（用于引用）
            ids: 文档 ID 列表（可选，默认 MD5 生成）

        Returns:
            track_id: 追踪 ID

        Raises:
            RuntimeError: 未初始化
        """
        self._ensure_initialized()
        return await self._rag.ainsert(
            input=texts,
            file_paths=file_paths,
            ids=ids,
        )

    async def get_doc_info_by_track_id(
        self, track_id: str
    ) -> tuple:
        """
        通过 track_id 查询 LightRAG 的 doc_status 存储，
        获取该次插入产生的真实 doc_id 和 chunks_count。

        LightRAG 设计说明：
        - track_id: ainsert() 返回的监控 ID，仅用于追踪状态
        - doc_id:   文档的真实 ID（content 的 MD5），adelete_by_doc_id() 需要它
        - doc_status.get_docs_by_track_id(track_id) 返回
          {doc_id: DocProcessingStatus} 字典，其中包含 chunks_count

        Args:
            track_id: ainsert() 返回的 track_id

        Returns:
            (doc_id, chunks_count) 元组；未找到时返回 ('', 0)
        """
        self._ensure_initialized()
        try:
            docs = await self._rag.doc_status.get_docs_by_track_id(track_id)
            if not docs:
                return ("", 0)
            doc_id = next(iter(docs))
            status = docs[doc_id]

            # LightRAG 检测到重复文档时，会在 doc_status 中创建一条
            # key="dup-xxx"、status=FAILED、content_summary="[DUPLICATE] Original document: doc-xxx"
            # 的记录。此时我们应查询原始 doc_id 获取真实 chunks_count，
            # 而非使用 dup 记录中错误的 0 值。
            summary = getattr(status, "content_summary", "") or ""
            if summary.startswith("[DUPLICATE] Original document:"):
                original_doc_id = summary.replace(
                    "[DUPLICATE] Original document:", ""
                ).strip()
                original_data = await self._rag.doc_status.get_by_id(original_doc_id)
                if original_data:
                    original_chunks = original_data.get("chunks_count") or 0
                    return (original_doc_id, original_chunks)
                # 原始记录丢失，回退到 doc_id=dup 以防止反复重索引
                return (original_doc_id, 0)

            chunks_count = status.chunks_count if status.chunks_count is not None else 0
            return (doc_id, chunks_count)
        except Exception as e:
            logger.warning(f"get_doc_info_by_track_id failed for {track_id}: {e}")
            return ("", 0)

    async def delete_document(self, doc_id: str) -> None:
        """
        删除文档及关联实体和关系

        Args:
            doc_id: 文档的真实 ID（由 get_doc_info_by_track_id 获取的 MD5 doc_id）
        """
        self._ensure_initialized()
        await self._rag.adelete_by_doc_id(doc_id)

    async def query(
        self,
        query_text: str,
        mode: str = "mix",
        top_k: int = DEFAULT_RAG_TOP_K,
    ) -> RAGQueryResult:
        """
        检索查询（纯数据，不经过 LLM 生成）

        Args:
            query_text: 查询文本
            mode: 检索模式 (naive/local/global/hybrid/mix)
            top_k: 返回数量

        Returns:
            RAGQueryResult: 结构化检索结果
        """
        self._ensure_initialized()

        from lightrag.base import QueryParam

        param = QueryParam(
            mode=mode,
            top_k=top_k,
            only_need_context=False,
        )

        raw = await self._rag.aquery_data(query_text, param)
        return RAGQueryResult(raw)

    # ============================================================
    # Embedding 可用性检测
    # ============================================================

    async def test_embedding(self) -> bool:
        """
        测试 Embedding API 是否可用

        发送测试文本验证 API Key 和网络连通性。

        Returns:
            True: 可用  False: 不可用
        """
        try:
            api_key = self._get_api_key()
            if not api_key:
                return False

            from lightrag.llm.zhipu import zhipu_embedding
            result = await zhipu_embedding.func(["test"], api_key=api_key)
            return result is not None and len(result) > 0
        except Exception as e:
            logger.warning(f"Embedding test failed: {e}")
            return False

    # ============================================================
    # 内部方法
    # ============================================================

    def _ensure_initialized(self) -> None:
        if not self.is_initialized:
            raise RuntimeError(
                "RAGService is not initialized. "
                "Call create() and initialize() first."
            )

    @staticmethod
    def _get_api_key() -> str:
        """从 CredentialManager 获取智谱 API Key"""
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_CREDENTIAL_MANAGER

            credential_manager = ServiceLocator.get_optional(
                SVC_CREDENTIAL_MANAGER
            )
            if credential_manager:
                return credential_manager.get_llm_api_key("zhipu")
        except Exception:
            pass
        return ""


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "RAGService",
    "RAGQueryResult",
]
