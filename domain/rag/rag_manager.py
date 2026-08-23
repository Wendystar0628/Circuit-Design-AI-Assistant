# RAG Manager - RAG 业务逻辑管理器
"""
RAG 业务逻辑管理器

设计理念：
    RAG 是项目的原生能力，不需要手动开关。
    打开项目 → 初始化 VectorStore → 自动增量索引 → AI 智能检索。
    切换项目 → 为新项目初始化新实例。

职责：
- 项目生命周期联动（订阅 PROJECT_OPENED / PROJECT_CLOSED）
- 项目打开时初始化 VectorStore + Embedder 并增量索引
- 项目文件扫描与索引（全量/增量/单文件）
- 查询接口（供 rag_search 工具调用）
- 索引状态管理（index_meta.json）
- 增量更新：mtime 对比 + 已删除文件清理
- 通过 EventBus 发布 RAG 事件

架构位置：
- 被 Application 层 bootstrap 创建并注册到 ServiceLocator
- 依赖 Embedder（智谱 embedding-3 API）
- 依赖 VectorStore（ChromaDB 持久化向量库）
- 订阅 EVENT_STATE_PROJECT_OPENED / EVENT_STATE_PROJECT_CLOSED
"""

import asyncio
import copy
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from domain.rag.chunker import chunk_file
from domain.rag.embedder import Embedder
from domain.rag.file_extractor import (
    FileIndexRule,
    INDEX_EXCLUDED_DIR_NAMES,
    extract_indexable_content,
    get_file_index_rule,
)
from domain.rag.rag_worker import RAGWorkerThread
from domain.rag.vector_store import RAGQueryResult, VectorStore
from infrastructure.config.settings import (
    DEFAULT_RAG_TOP_K,
    DEFAULT_RAG_STORAGE_DIR,
    DEFAULT_RAG_CONTEXT_TOKEN_BUDGET,
    DEFAULT_VECTOR_STORE_DIR,
)
from shared.event_types import (
    EVENT_RAG_INIT_COMPLETE,
    EVENT_RAG_INDEX_STARTED,
    EVENT_RAG_INDEX_PROGRESS,
    EVENT_RAG_INDEX_COMPLETE,
    EVENT_RAG_INDEX_ERROR,
    EVENT_RAG_QUERY_COMPLETE,
    EVENT_LLM_CONFIG_CHANGED,
    EVENT_STATE_PROJECT_OPENED,
    EVENT_STATE_PROJECT_CLOSED,
    EVENT_WORKSPACE_SYNC_REQUIRED,
)


logger = logging.getLogger(__name__)


# ============================================================
# 文件扫描规则
# ============================================================

EXCLUDED_DIRS: Set[str] = {
    ".circuit_ai", "__pycache__", ".git", ".venv",
    "node_modules", ".idea", ".vscode",
    *INDEX_EXCLUDED_DIR_NAMES,
}

INDEX_META_FILE = "index_meta.json"
INDEX_META_VERSION = 2
EXTRACTOR_VERSION = "1"
CHUNKER_VERSION = "1"


# ============================================================
# 数据类
# ============================================================

@dataclass
class FileIndexInfo:
    """单文件索引信息"""
    relative_path: str
    doc_id: str = ""
    mtime: float = 0.0
    size: int = 0
    status: str = "pending"  # pending / processing / processed / failed / excluded
    chunks_count: int = 0
    indexed_at: str = ""
    error: Optional[str] = None
    exclude_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "doc_id": self.doc_id,
            "mtime": self.mtime,
            "size": self.size,
            "status": self.status,
            "chunks_count": self.chunks_count,
            "indexed_at": self.indexed_at,
        }
        if self.error:
            d["error"] = self.error
        if self.exclude_reason:
            d["exclude_reason"] = self.exclude_reason
        return d

    @classmethod
    def from_dict(cls, path: str, data: Dict[str, Any]) -> "FileIndexInfo":
        return cls(
            relative_path=path,
            doc_id=data.get("doc_id", ""),
            mtime=data.get("mtime", 0.0),
            size=data.get("size", 0),
            status=data.get("status", "pending"),
            chunks_count=data.get("chunks_count", 0),
            indexed_at=data.get("indexed_at", ""),
            error=data.get("error"),
            exclude_reason=data.get("exclude_reason"),
        )


@dataclass
class IndexStats:
    """索引统计"""
    total_files: int = 0
    processed: int = 0
    failed: int = 0
    excluded: int = 0
    total_chunks: int = 0
    total_entities: int = 0
    total_relations: int = 0
    storage_size_mb: float = 0.0


@dataclass
class IndexStatus:
    """索引状态"""
    available: bool = False
    indexing: bool = False
    current_track_id: Optional[str] = None
    stats: IndexStats = field(default_factory=IndexStats)
    files: List[FileIndexInfo] = field(default_factory=list)


@dataclass(frozen=True)
class IndexSignature:
    """Identity of vectors that may safely coexist in one collection."""

    provider: str
    model: str
    dimensions: int
    backend: str
    metric: str
    extractor: str
    chunker: str
    project: str
    collection: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "dimensions": self.dimensions,
            "backend": self.backend,
            "metric": self.metric,
            "extractor": self.extractor,
            "chunker": self.chunker,
            "project": self.project,
            "collection": self.collection,
        }


@dataclass
class _RuntimeState:
    index_meta: Dict[str, Any] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)
    meta_loaded_from_disk: bool = False
    indexing: bool = False
    current_track_id: Optional[str] = None
    cached_status: IndexStatus = field(default_factory=IndexStatus)
    status_revision: int = 0
    scan_failures: List[Dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class _ProjectRuntime:
    """Immutable project identity captured by every background job.

    The contained state is private to this runtime.  Switching projects swaps
    the complete runtime object rather than retargeting fields used by queued
    jobs.
    """

    generation: int
    project_root: str
    embedder: Embedder
    vector_store: VectorStore
    signature: IndexSignature
    state: _RuntimeState
    cancelled: threading.Event


class _RAGOperationCancelled(RuntimeError):
    pass


# ============================================================
# RAG Manager
# ============================================================

class RAGManager:
    """
    RAG 业务逻辑管理器

    RAG 是项目的原生能力：
    - 打开项目 → 初始化 VectorStore + Embedder → 自动增量索引
    - 关闭项目 → 清除状态（ChromaDB 自动持久化）
    - AI 对话时 → rag_search 工具按需调用 query() 检索

    持久化策略：
    - ChromaDB 向量库：{project}/.circuit_ai/vector_store/
    - index_meta.json：文件索引元数据，随索引操作更新
    → 每个项目有独立的存储，项目隔离
    """

    def __init__(
        self,
        event_bus=None,
        *,
        embedder_factory: Callable[[], Embedder] = Embedder,
        vector_store_factory: Callable[..., VectorStore] = VectorStore,
        worker: Optional[RAGWorkerThread] = None,
    ):
        self._event_bus = event_bus
        self._embedder_factory = embedder_factory
        self._vector_store_factory = vector_store_factory
        self._runtime: Optional[_ProjectRuntime] = None
        self._runtime_lock = threading.RLock()
        self._generation = 0
        self._project_root_hint: Optional[str] = None
        self._init_error: Optional[str] = None  # 初始化失败的错误信息
        self._index_error: Optional[str] = None
        self._subscribed = False
        self._stopped = False
        self._document_watcher = None
        # 后台工作线程：索引和查询在此线程运行，避免阻塞 API 事件循环。
        self._worker = worker or RAGWorkerThread()

    @property
    def is_available(self) -> bool:
        """星 RAG 是否可用（项目已打开且 VectorStore 已初始化）"""
        runtime = self._get_runtime()
        return bool(
            runtime
            and not runtime.cancelled.is_set()
            and runtime.vector_store.is_initialized
        )

    @property
    def is_indexing(self) -> bool:
        runtime = self._get_runtime()
        return bool(runtime and runtime.state.indexing)

    @property
    def project_root(self) -> Optional[str]:
        """当前项目根目录"""
        runtime = self._get_runtime()
        return runtime.project_root if runtime else self._project_root_hint

    @property
    def generation(self) -> int:
        runtime = self._get_runtime()
        return runtime.generation if runtime else self._generation

    @property
    def status_revision(self) -> int:
        """Monotonic revision of the in-memory UI status snapshot."""
        runtime = self._get_runtime()
        if runtime is None:
            return 0
        with runtime.state.lock:
            return runtime.state.status_revision

    @property
    def init_error(self) -> Optional[str]:
        """最近一次初始化错误（None 表示无错误）"""
        return self._init_error

    @property
    def index_error(self) -> Optional[str]:
        """Latest indexing failure; distinct from VectorStore initialization."""
        return self._index_error

    def attach_document_watcher(self, watcher) -> None:
        """Attach the explicitly constructed watcher for coordinated stop."""
        self._document_watcher = watcher

    # ============================================================
    # 生命周期事件订阅
    # ============================================================

    def subscribe_lifecycle_events(self) -> None:
        """
        订阅项目生命周期事件

        在 bootstrap 中调用，绑定到 EventBus。
        同时启动 RAGWorkerThread（后台专用 asyncio 循环）。
        """
        if self._subscribed:
            return

        # 启动后台工作线程
        self._stopped = False
        self._worker.start_and_wait()

        if self._event_bus is None:
            return

        try:
            self._event_bus.subscribe(
                EVENT_STATE_PROJECT_OPENED,
                self._on_project_opened,
            )
            self._event_bus.subscribe(
                EVENT_STATE_PROJECT_CLOSED,
                self._on_project_closed,
            )
            self._event_bus.subscribe(
                EVENT_LLM_CONFIG_CHANGED,
                self._on_model_config_changed,
            )
            self._event_bus.subscribe(
                EVENT_WORKSPACE_SYNC_REQUIRED,
                self._on_workspace_sync_required,
            )
            self._subscribed = True
            logger.info("RAGManager subscribed to project lifecycle events")
        except Exception as e:
            logger.warning(f"Failed to subscribe lifecycle events: {e}")

    def _on_project_opened(self, event_data) -> None:
        """
        项目打开事件处理（同步入口）

        同步设置 project_root → 异步自动初始化 + 自动索引。

        Note: EventBus 将事件数据包装为 {"type":.., "data":{..}, "timestamp":.., "source":..}
              实际业务数据在 event_data["data"] 中。
        """
        # 解包 EventBus 包装层
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data

        project_root = None
        if isinstance(data, dict):
            project_root = data.get("path") or data.get("project_root")
        elif isinstance(data, str):
            project_root = data

        if not project_root:
            return

        project_root = os.path.abspath(os.fspath(project_root))
        self._project_root_hint = project_root
        self._init_error = None
        self._index_error = None

        try:
            runtime = self._create_runtime(project_root)
        except Exception as exc:
            self._init_error = str(exc)
            logger.error(f"Failed to prepare RAG runtime: {exc}")
            self._publish_event(EVENT_RAG_INIT_COMPLETE, {
                "project_root": project_root,
                "generation": self._generation,
                "status": "error",
                "error": f"RAG 自动初始化失败: {exc}",
            })
            return

        logger.info(
            "Project opened, RAG runtime prepared: %s (generation=%s)",
            project_root,
            runtime.generation,
        )

        if not self._worker.is_running:
            self._worker.start_and_wait()
        self._worker.submit(self._init_for_project, runtime)

    def _create_runtime(self, project_root: str) -> _ProjectRuntime:
        """Freeze configuration and atomically replace the active runtime."""
        embedder = self._embedder_factory()
        vector_store = self._vector_store_factory(
            project_root=project_root,
            storage_subdir=DEFAULT_VECTOR_STORE_DIR,
        )

        with self._runtime_lock:
            previous = self._runtime
            if previous is not None:
                previous.cancelled.set()
            self._worker.cancel_pending()
            self._generation += 1
            signature = self._build_signature(project_root, embedder, vector_store)
            runtime = _ProjectRuntime(
                generation=self._generation,
                project_root=project_root,
                embedder=embedder,
                vector_store=vector_store,
                signature=signature,
                state=_RuntimeState(),
                cancelled=threading.Event(),
            )
            self._runtime = runtime
            self._project_root_hint = project_root
        return runtime

    def _init_for_project(self, runtime: _ProjectRuntime) -> None:
        """初始化 VectorStore + Embedder → 自动索引（在工作线程中运行）"""
        try:
            self._ensure_current(runtime)
            runtime.vector_store.initialize()
            self._ensure_current(runtime)
            self._load_index_meta(runtime)
            self._ensure_index_signature(runtime)
            self._ensure_current(runtime)
            self._refresh_status_cache(runtime)
            self._init_error = None

            logger.info("RAG VectorStore initialized, starting auto-index")

            self._publish_event(EVENT_RAG_INIT_COMPLETE, {
                "project_root": runtime.project_root,
                "status": "ready",
            }, runtime=runtime)

            self._safe_index_project(runtime)

        except _RAGOperationCancelled:
            logger.debug("Discarded initialization for stale RAG runtime")
        except Exception as e:
            if not self._is_current(runtime):
                return
            self._init_error = str(e)
            logger.error(f"Failed to auto-init RAG for project: {e}")
            self._publish_event(EVENT_RAG_INIT_COMPLETE, {
                "project_root": runtime.project_root,
                "status": "error",
                "error": f"RAG 自动初始化失败: {e}",
            }, runtime=runtime)

    def _on_project_closed(self, event_data) -> None:
        """
        项目关闭事件处理（同步入口）

        清除项目状态；ChromaDB 数据已自动持久化，无需显式刷盘。
        """
        logger.info("Project closing, clearing RAG state")
        with self._runtime_lock:
            runtime = self._runtime
            if runtime is not None:
                runtime.cancelled.set()
            self._runtime = None
            self._generation += 1
            self._project_root_hint = None
        self._worker.cancel_pending()
        self._init_error = None
        self._index_error = None

    def _on_model_config_changed(self, event_data) -> None:
        """Re-evaluate the frozen embedding signature after settings save."""
        del event_data
        if self.is_available:
            self.trigger_index()

    def _on_workspace_sync_required(self, event_data) -> None:
        """Rescan after a direct on-disk restore bypassed file events."""
        data = (
            event_data.get("data", event_data)
            if isinstance(event_data, dict)
            else {}
        )
        incoming_root = str(data.get("project_root", "") or "")
        runtime = self._get_runtime()
        if runtime is None or not incoming_root:
            return
        current_root = os.path.normcase(
            os.path.realpath(os.path.abspath(runtime.project_root))
        )
        incoming_root = os.path.normcase(
            os.path.realpath(os.path.abspath(incoming_root))
        )
        if incoming_root != current_root or not self._is_current(runtime):
            return
        # trigger_index captures the current immutable runtime and schedules a
        # full incremental scan, including deleted-file cleanup.  A later
        # project/config transition invalidates that captured runtime normally.
        self.trigger_index()

    # ============================================================
    # 索引操作
    # ============================================================

    def index_project_files(self, runtime: Optional[_ProjectRuntime] = None) -> None:
        """
        扫描项目目录，全量/增量索引

        对比 index_meta.json 中的 mtime 与磁盘 mtime，
        仅索引新增或变更的文件。
        """
        runtime = runtime or self._get_runtime()
        if runtime is None or not runtime.vector_store.is_initialized:
            logger.debug("Index library is unavailable, skipping index")
            return
        self._ensure_current(runtime)

        if runtime.state.indexing:
            logger.warning("Indexing already in progress")
            return

        runtime.state.indexing = True
        start_time = time.time()

        try:
            self._ensure_current(runtime)
            with runtime.state.lock:
                runtime.state.scan_failures = []

            # 扫描文件
            files_to_index = self._scan_project_files(runtime)
            with runtime.state.lock:
                scan_failures = list(runtime.state.scan_failures)
            if not files_to_index:
                self._save_index_meta(runtime)
                self._refresh_status_cache(runtime)
                if scan_failures:
                    duration = time.time() - start_time
                    logger.error(
                        "RAG scan completed with %s metadata failures",
                        len(scan_failures),
                    )
                    self._publish_event(EVENT_RAG_INDEX_COMPLETE, {
                        "total_indexed": 0,
                        "failed": len(scan_failures),
                        "duration_s": round(duration, 2),
                        "scan_failed": True,
                    }, runtime=runtime)
                    return

                self._index_error = None
                logger.info("No files to index (all up to date)")
                self._publish_event(EVENT_RAG_INDEX_COMPLETE, {
                    "total_indexed": 0,
                    "failed": 0,
                    "duration_s": 0,
                    "already_up_to_date": True,
                }, runtime=runtime)
                return

            total = len(files_to_index)
            runtime.state.current_track_id = (
                f"idx-{runtime.generation}-{int(time.time())}"
            )

            self._publish_event(EVENT_RAG_INDEX_STARTED, {
                "total_files": total,
                "track_id": runtime.state.current_track_id,
            }, runtime=runtime)

            processed = 0
            failed = len(scan_failures)

            for i, (rel_path, abs_path) in enumerate(files_to_index):
                try:
                    self._ensure_current(runtime)
                    self._publish_event(EVENT_RAG_INDEX_PROGRESS, {
                        "processed": i,
                        "total": total,
                        "current_file": rel_path,
                        "track_id": runtime.state.current_track_id,
                    }, runtime=runtime)

                    self._index_single_file_internal(runtime, rel_path, abs_path)
                    processed += 1

                except _RAGOperationCancelled:
                    raise
                except Exception as e:
                    failed += 1
                    logger.error(f"Failed to index {rel_path}: {e}")
                    # 记录失败状态
                    self._mark_file_failed(runtime, rel_path, str(e))
                    self._record_index_error(
                        runtime,
                        e,
                        file_path=rel_path,
                        phase="file_index",
                        persist=False,
                    )

            self._ensure_current(runtime)
            duration = time.time() - start_time
            self._save_index_meta(runtime)
            self._refresh_status_cache(runtime)

            if failed == 0:
                self._index_error = None

            self._publish_event(EVENT_RAG_INDEX_COMPLETE, {
                "total_indexed": processed,
                "failed": failed,
                "duration_s": round(duration, 2),
                "entities_count": 0,
                "relations_count": 0,
                "chunks_found": 0,
            }, runtime=runtime)

            logger.info(
                f"Indexing complete: {processed}/{total} files, "
                f"{failed} failed, {duration:.1f}s"
            )

        except _RAGOperationCancelled:
            logger.debug(
                "Cancelled index for stale runtime generation=%s",
                runtime.generation,
            )
        except Exception as exc:
            self._record_index_error(
                runtime,
                exc,
                phase="project_index",
                persist=True,
            )
        finally:
            runtime.state.indexing = False
            runtime.state.current_track_id = None

    def index_single_file(
        self,
        file_path: str,
        runtime: Optional[_ProjectRuntime] = None,
    ) -> None:
        """
        单文件增量索引（先删后插）

        Args:
            file_path: 文件路径（绝对或相对于项目根）
        """
        runtime = runtime or self._get_runtime()
        if runtime is None or not runtime.vector_store.is_initialized:
            return
        self._ensure_current(runtime)

        abs_path, rel_path = self._resolve_path(runtime, file_path)
        if not abs_path:
            return

        rule = self._get_file_index_rule(abs_path)
        if rule is None:
            return

        if not rule.should_index:
            try:
                stat = os.stat(abs_path)
                with runtime.state.lock:
                    old_meta = runtime.state.index_meta.get("files", {}).get(rel_path, {})
                self._mark_file_excluded(runtime, rel_path, stat, old_meta, rule)
                self._save_index_meta(runtime)
                self._refresh_status_cache(
                    runtime,
                    measure_vector_store=False,
                    measure_storage=False,
                )
            except OSError as exc:
                self._mark_file_failed(runtime, rel_path, str(exc))
                self._record_index_error(
                    runtime,
                    exc,
                    file_path=rel_path,
                    phase="file_metadata",
                    persist=True,
                )
            return

        try:
            self._index_single_file_internal(runtime, rel_path, abs_path)
            self._save_index_meta(runtime)
            self._refresh_status_cache(
                runtime,
                measure_vector_store=False,
                measure_storage=False,
            )

        except _RAGOperationCancelled:
            return
        except Exception as e:
            logger.error(f"Failed to index single file {rel_path}: {e}")
            self._mark_file_failed(runtime, rel_path, str(e))
            self._record_index_error(
                runtime,
                e,
                file_path=rel_path,
                phase="file_index",
                persist=True,
            )

    def _index_single_file_internal(
        self,
        runtime: _ProjectRuntime,
        rel_path: str,
        abs_path: str,
    ) -> None:
        """Read, chunk, embed and commit one file to its captured runtime."""
        self._ensure_current(runtime)
        stat = os.stat(abs_path)
        content = extract_indexable_content(abs_path)
        self._ensure_current(runtime)

        # Extractors intentionally expose plain text only.  A truly empty
        # file is a valid zero-chunk document, while a non-empty file yielding
        # no bytes indicates an extraction/read failure and must not silently
        # erase the last-known-good metadata as "processed".
        if content == "" and stat.st_size > 0:
            raise RuntimeError(
                f"Content extraction returned no data for non-empty file: {rel_path}"
            )

        # Empty/whitespace text is a successful zero-chunk state.  Deleting
        # old vectors first prevents stale search results for cleared files.
        if not content.strip():
            runtime.vector_store.delete_file(rel_path)
            self._ensure_current(runtime)
            self._update_file_meta(runtime, rel_path, {
                "chunks_count": 0,
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "status": "processed",
                "indexed_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
                "stale": False,
                "empty": True,
            })
            return

        chunks = chunk_file(content, rel_path)
        if not chunks:
            runtime.vector_store.delete_file(rel_path)
            self._ensure_current(runtime)
            self._update_file_meta(runtime, rel_path, {
                "chunks_count": 0,
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "status": "processed",
                "indexed_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
                "stale": False,
                "empty": True,
            })
            return

        vectors = runtime.embedder.embed_texts([c.content for c in chunks])
        self._ensure_current(runtime)
        if len(vectors) != len(chunks):
            raise RuntimeError(
                f"Embedding returned {len(vectors)} vectors for {len(chunks)} chunks"
            )
        expected_dimensions = runtime.signature.dimensions
        if expected_dimensions and any(
            len(vector) != expected_dimensions for vector in vectors
        ):
            actual = len(vectors[0]) if vectors else 0
            raise RuntimeError(
                f"Embedding dimension mismatch: expected {expected_dimensions}, got {actual}"
            )

        runtime.vector_store.upsert_file(rel_path, chunks, vectors)
        self._ensure_current(runtime)

        self._update_file_meta(runtime, rel_path, {
            "chunks_count": len(chunks),
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "status": "processed",
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
            "stale": False,
            "empty": False,
        })

    # ============================================================
    # 查询
    # ============================================================

    def query(
        self,
        query_text: str,
        top_k: int = DEFAULT_RAG_TOP_K,
        runtime: Optional[_ProjectRuntime] = None,
    ) -> RAGQueryResult:
        """
        查询知识库（向量相似度检索）

        Args:
            query_text: 查询文本
            top_k:      返回数量

        Returns:
            RAGQueryResult
        """
        runtime = runtime or self._get_runtime()
        if runtime is None or not runtime.vector_store.is_initialized:
            raise RuntimeError("RAG index library is unavailable")
        self._ensure_current(runtime)

        vector = runtime.embedder.embed_single(query_text)
        self._ensure_current(runtime)
        if runtime.signature.dimensions and len(vector) != runtime.signature.dimensions:
            raise RuntimeError(
                "Query embedding dimension no longer matches the active index"
            )
        hits = runtime.vector_store.query(vector, top_k=top_k)
        self._ensure_current(runtime)
        result = RAGQueryResult(hits=hits)

        self._publish_event(EVENT_RAG_QUERY_COMPLETE, {
            "query": query_text[:100],
            "results_count": len(hits),
            "chunks_found": len(hits),
        }, runtime=runtime)

        return result

    # ============================================================
    # 非阻塞运行时入口（同步入队，工作在后台线程）
    # ============================================================

    def trigger_index(self) -> None:
        """
        触发全量/增量索引并立即返回。

        索引在 RAGWorkerThread 中异步执行。
        """
        runtime = self._get_runtime()
        if runtime is None or not runtime.vector_store.is_initialized:
            logger.debug("Index library is unavailable, cannot trigger index")
            return

        # Settings may have changed since the project opened.  Freeze a new
        # config now and start a new generation when its signature differs.
        try:
            candidate_embedder = self._embedder_factory()
            candidate_store = self._vector_store_factory(
                project_root=runtime.project_root,
                storage_subdir=DEFAULT_VECTOR_STORE_DIR,
            )
            candidate_signature = self._build_signature(
                runtime.project_root, candidate_embedder, candidate_store
            )
            if candidate_signature != runtime.signature:
                runtime = self._create_runtime(runtime.project_root)
                self._worker.submit(self._init_for_project, runtime)
                return
        except Exception as exc:
            self._init_error = str(exc)
            self._publish_event(EVENT_RAG_INDEX_ERROR, {
                "file_path": "",
                "error": f"无法冻结新的索引配置: {exc}",
            }, runtime=runtime)
            return

        self._worker.submit(self.index_project_files, runtime)

    def trigger_index_single_file(self, file_path: str) -> None:
        """
        触发单文件增量索引并立即返回。

        Args:
            file_path: 文件路径（绝对或相对于项目根）
        """
        runtime = self._get_runtime()
        if runtime is None or not runtime.vector_store.is_initialized:
            return
        self._worker.submit(self.index_single_file, file_path, runtime)

    def trigger_delete_file(
        self,
        file_path: str,
        is_directory: bool = False,
    ) -> None:
        """Queue a project-scoped vector/meta deletion."""
        runtime = self._get_runtime()
        if runtime is None or not runtime.vector_store.is_initialized:
            return
        self._worker.submit(
            self._delete_file_runtime,
            runtime,
            file_path,
            is_directory,
        )

    def trigger_move_file(
        self,
        old_path: str,
        new_path: str,
        is_directory: bool = False,
    ) -> None:
        """Queue delete-old then index-new against one captured runtime."""
        runtime = self._get_runtime()
        if runtime is None or not runtime.vector_store.is_initialized:
            return
        self._worker.submit(
            self._move_file_runtime,
            runtime,
            old_path,
            new_path,
            is_directory,
        )

    def _move_file_runtime(
        self,
        runtime: _ProjectRuntime,
        old_path: str,
        new_path: str,
        is_directory: bool = False,
    ) -> None:
        self._delete_file_runtime(runtime, old_path, is_directory)
        self._ensure_current(runtime)
        if is_directory:
            self.index_project_files(runtime)
        else:
            self.index_single_file(new_path, runtime)

    async def query_async(
        self,
        query_text: str,
        top_k: int = DEFAULT_RAG_TOP_K,
    ) -> "RAGQueryResult":
        """
        从 asyncio 调用方异步查询知识库。

        将 query() 提交到工作线程执行，通过 asyncio.wrap_future()
        让调用方 await 工作线程结果，同时不阻塞事件循环。

        Args:
            query_text: 查询文本
            top_k:      返回数量上限

        Returns:
            RAGQueryResult
        """
        runtime = self._get_runtime()
        if runtime is None or not runtime.vector_store.is_initialized:
            raise RuntimeError("RAG index library is unavailable")

        future = self._worker.submit(
            self.query, query_text, top_k, runtime
        )
        if future is None:
            raise RuntimeError("RAG index library worker is not running")

        try:
            result = await asyncio.wrap_future(future)
        except asyncio.CancelledError:
            future.cancel()
            raise

        if not self._is_current(runtime):
            raise _RAGOperationCancelled("RAG project changed during query")
        return result

    def stop(self) -> None:
        """Synchronously and idempotently stop watcher and background work."""
        with self._runtime_lock:
            if self._stopped:
                return
            self._stopped = True
            runtime = self._runtime
            if runtime is not None:
                runtime.cancelled.set()
            self._runtime = None
            self._generation += 1
            self._project_root_hint = None

        watcher = self._document_watcher
        if watcher is not None:
            try:
                watcher.stop()
            except Exception as exc:
                logger.warning(f"Failed to stop DocumentWatcher: {exc}")

        if self._subscribed and self._event_bus is not None:
            try:
                self._event_bus.unsubscribe(
                    EVENT_STATE_PROJECT_OPENED, self._on_project_opened
                )
                self._event_bus.unsubscribe(
                    EVENT_STATE_PROJECT_CLOSED, self._on_project_closed
                )
                self._event_bus.unsubscribe(
                    EVENT_LLM_CONFIG_CHANGED, self._on_model_config_changed
                )
                self._event_bus.unsubscribe(
                    EVENT_WORKSPACE_SYNC_REQUIRED,
                    self._on_workspace_sync_required,
                )
            except Exception as exc:
                logger.debug(f"Failed to unsubscribe RAG lifecycle events: {exc}")
        self._subscribed = False
        self._worker.stop()

    # ============================================================
    # 状态查询
    # ============================================================

    def get_index_status(self) -> IndexStatus:
        """Return the cached, pure-memory UI status snapshot.

        This method is called while the conversation WebView is rebuilt for
        streaming tokens.  It must never touch ChromaDB or walk the vector
        store directory.  Expensive measurements are refreshed by the RAG
        worker only at initialization/index/clear boundaries.
        """
        runtime = self._get_runtime()
        if runtime is None:
            return IndexStatus(available=False)

        with runtime.state.lock:
            cached = runtime.state.cached_status
            return IndexStatus(
                available=(
                    not runtime.cancelled.is_set()
                    and runtime.vector_store.is_initialized
                ),
                indexing=runtime.state.indexing,
                current_track_id=runtime.state.current_track_id,
                # These objects are replaced, never mutated, when the worker
                # refreshes the snapshot.  UI consumers treat them as read-only.
                stats=cached.stats,
                files=cached.files,
            )

    def delete_file(self, rel_path: str) -> None:
        """删除指定文件的所有 chunk"""
        runtime = self._get_runtime()
        if runtime is None or not runtime.vector_store.is_initialized:
            return
        self._delete_file_runtime(runtime, rel_path)

    def _delete_file_runtime(
        self,
        runtime: _ProjectRuntime,
        file_path: str,
        is_directory: bool = False,
    ) -> None:
        normalized = self._normalize_rel_path(runtime, file_path)
        if normalized is None:
            return
        self._ensure_current(runtime)
        if is_directory:
            runtime.vector_store.delete_prefix(normalized)
        else:
            runtime.vector_store.delete_file(normalized)
        self._ensure_current(runtime)
        with runtime.state.lock:
            files = runtime.state.index_meta.get("files", {})
            if is_directory:
                prefix = normalized.rstrip("/") + "/"
                for rel_path in list(files):
                    if rel_path == normalized or rel_path.startswith(prefix):
                        files.pop(rel_path, None)
            else:
                files.pop(normalized, None)
        self._save_index_meta(runtime)
        self._refresh_status_cache(
            runtime,
            measure_vector_store=False,
            measure_storage=False,
        )

    async def clear_index_async(
        self,
        *,
        expected_generation: int,
        expected_project_root: str,
    ) -> None:
        """Clear only the project/index identity approved by the caller.

        Validation and worker submission share ``_runtime_lock`` so a project
        transition cannot slip between the identity check and runtime capture.
        The worker performs its own current-runtime check before mutation.
        """
        with self._runtime_lock:
            runtime = self._runtime
            if runtime is None:
                raise RuntimeError("RAG project is not open")
            if runtime.generation != int(expected_generation):
                raise _RAGOperationCancelled(
                    "RAG project or index generation changed before clear"
                )
            if not str(expected_project_root).strip():
                raise ValueError("expected_project_root is required")
            expected_root = os.path.normcase(
                os.path.realpath(os.path.abspath(expected_project_root))
            )
            runtime_root = os.path.normcase(
                os.path.realpath(os.path.abspath(runtime.project_root))
            )
            if runtime_root != expected_root:
                raise _RAGOperationCancelled(
                    "RAG project changed before clear"
                )
            future = self._worker.submit(self._clear_index_runtime, runtime)
        if future is None:
            raise RuntimeError("RAG worker not running")
        try:
            await asyncio.wrap_future(future)
        except asyncio.CancelledError:
            future.cancel()
            raise
        self._ensure_current(runtime)

    def _clear_index_runtime(self, runtime: _ProjectRuntime) -> None:
        self._ensure_current(runtime)
        runtime.vector_store.clear()
        self._ensure_current(runtime)
        with runtime.state.lock:
            runtime.state.index_meta = self._new_index_meta(runtime)
        self._save_index_meta(runtime)
        self._refresh_status_cache(runtime)

    # ============================================================
    # 文件扫描
    # ============================================================

    def _scan_project_files(self, runtime: _ProjectRuntime) -> List[tuple]:
        """
        扫描项目目录，返回需要索引的 (rel_path, abs_path) 列表

        增量策略：
        1. 对比 mtime，仅返回新增或变更文件
        2. 检测已删除文件并从 index_meta 和 VectorStore 中清理
        """
        self._ensure_current(runtime)

        result = []
        with runtime.state.lock:
            files_meta = copy.deepcopy(
                runtime.state.index_meta.get("files", {})
            )
        root = Path(runtime.project_root)
        disk_files: Set[str] = set()  # 当前磁盘上存在的可索引文件

        def _raise_walk_error(error: OSError) -> None:
            raise error

        for dirpath, dirnames, filenames in os.walk(
            root,
            onerror=_raise_walk_error,
        ):
            self._ensure_current(runtime)
            # 排除目录
            dirnames[:] = [
                d for d in dirnames
                if d not in EXCLUDED_DIRS
            ]

            for filename in filenames:
                abs_path = os.path.join(dirpath, filename)
                try:
                    rule = self._get_file_index_rule(abs_path)
                    if rule is None:
                        continue

                    rel_path = os.path.relpath(abs_path, root).replace("\\", "/")
                    disk_files.add(rel_path)

                    # 增量检查
                    stat = os.stat(abs_path)
                    old_meta = files_meta.get(rel_path, {})
                    old_mtime = old_meta.get("mtime", 0.0)

                    if not rule.should_index:
                        self._mark_file_excluded(
                            runtime, rel_path, stat, old_meta, rule
                        )
                        continue

                    if (old_meta.get("status") == "processed"
                            and abs(stat.st_mtime - old_mtime) < 0.01):
                        continue  # 未变更，跳过

                    result.append((rel_path, abs_path))

                except OSError as exc:
                    rel_path = os.path.relpath(
                        abs_path, root
                    ).replace("\\", "/")
                    # The directory entry exists; a stat failure must not make
                    # deleted-file cleanup erase its last-known-good vectors.
                    disk_files.add(rel_path)
                    self._mark_file_failed(runtime, rel_path, str(exc))
                    failure = {
                        "file_path": rel_path,
                        "error": str(exc),
                    }
                    with runtime.state.lock:
                        runtime.state.scan_failures.append(failure)
                    self._record_index_error(
                        runtime,
                        exc,
                        file_path=rel_path,
                        phase="file_metadata",
                        persist=False,
                    )
                    continue

        # 检测已删除文件：meta 中存在但磁盘上不存在
        deleted_files = [
            rel_path for rel_path in files_meta
            if rel_path not in disk_files
        ]
        if deleted_files:
            self._cleanup_deleted_files(runtime, deleted_files)

        return result

    def _cleanup_deleted_files(
        self,
        runtime: _ProjectRuntime,
        deleted_files: List[str],
    ) -> None:
        """异步清理已删除文件"""
        cleaned = 0

        for rel_path in deleted_files:
            self._ensure_current(runtime)
            # Only commit metadata removal after the vector deletion succeeds.
            runtime.vector_store.delete_file(rel_path)
            self._ensure_current(runtime)
            with runtime.state.lock:
                runtime.state.index_meta.get("files", {}).pop(rel_path, None)
            cleaned += 1

        if cleaned:
            self._save_index_meta(runtime)
            logger.info(f"Cleaned {cleaned} deleted files from index")

    def _get_file_index_rule(self, abs_path: str) -> Optional[FileIndexRule]:
        return get_file_index_rule(abs_path)

    def _mark_file_excluded(
        self,
        runtime: _ProjectRuntime,
        rel_path: str,
        stat: os.stat_result,
        old_meta: Dict[str, Any],
        rule: FileIndexRule,
    ) -> None:
        if (
            old_meta.get("status") == "excluded"
            and abs(stat.st_mtime - old_meta.get("mtime", 0.0)) < 0.01
            and old_meta.get("exclude_reason") == rule.exclude_reason
        ):
            return

        if old_meta.get("status") == "processed":
            self._ensure_current(runtime)
            runtime.vector_store.delete_file(rel_path)

        self._update_file_meta(runtime, rel_path, {
            "doc_id": "",
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "status": "excluded",
            "chunks_count": 0,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
            "exclude_reason": rule.exclude_reason,
        })

    def _resolve_path(
        self,
        runtime: _ProjectRuntime,
        file_path: str,
    ) -> tuple:
        """解析路径为 (abs_path, rel_path)"""
        if os.path.isabs(file_path):
            abs_path = os.path.abspath(file_path)
        else:
            abs_path = os.path.abspath(os.path.join(runtime.project_root, file_path))

        rel_path = self._normalize_rel_path(runtime, abs_path)
        if rel_path is None:
            return None, None

        if not os.path.isfile(abs_path):
            return None, None

        return abs_path, rel_path

    # ============================================================
    # index_meta.json 管理
    # ============================================================

    def _load_index_meta(self, runtime: _ProjectRuntime) -> None:
        """加载 index_meta.json（线程安全）"""
        meta_path = os.path.join(
            runtime.project_root, DEFAULT_RAG_STORAGE_DIR, INDEX_META_FILE
        )
        try:
            if os.path.isfile(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                loaded_from_disk = True
            else:
                data = self._new_index_meta(runtime)
                loaded_from_disk = False
            if not isinstance(data, dict):
                raise ValueError("index_meta.json root must be an object")
            with runtime.state.lock:
                runtime.state.index_meta = data
                runtime.state.meta_loaded_from_disk = loaded_from_disk
        except Exception as e:
            logger.warning(f"Failed to load index meta: {e}")
            with runtime.state.lock:
                runtime.state.index_meta = self._new_index_meta(runtime)
                runtime.state.meta_loaded_from_disk = False

    def _save_index_meta(self, runtime: _ProjectRuntime) -> None:
        """保存 index_meta.json（线程安全）"""
        self._ensure_current(runtime)

        storage_dir = os.path.join(runtime.project_root, DEFAULT_RAG_STORAGE_DIR)
        os.makedirs(storage_dir, exist_ok=True)
        meta_path = os.path.join(storage_dir, INDEX_META_FILE)

        with runtime.state.lock:
            runtime.state.index_meta["version"] = INDEX_META_VERSION
            runtime.state.index_meta["project_root"] = runtime.project_root
            runtime.state.index_meta["signature"] = runtime.signature.to_dict()
            runtime.state.index_meta["last_full_index"] = datetime.now(timezone.utc).isoformat()
            files_meta = runtime.state.index_meta.get("files", {})
            runtime.state.index_meta["stats"] = {
                "total_files": len(files_meta),
                "processed": sum(1 for f in files_meta.values() if f.get("status") == "processed"),
                "failed": sum(1 for f in files_meta.values() if f.get("status") == "failed"),
                "excluded": sum(1 for f in files_meta.values() if f.get("status") == "excluded"),
                "total_chunks": sum(f.get("chunks_count", 0) for f in files_meta.values()),
            }
            snapshot = copy.deepcopy(runtime.state.index_meta)

        temp_path = f"{meta_path}.tmp-{runtime.generation}-{threading.get_ident()}"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            self._ensure_current(runtime)
            os.replace(temp_path, meta_path)
            with runtime.state.lock:
                runtime.state.meta_loaded_from_disk = True
        except Exception as e:
            logger.error(f"Failed to save index meta: {e}")
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            raise

    def _update_file_meta(
        self,
        runtime: _ProjectRuntime,
        rel_path: str,
        data: Dict[str, Any],
    ) -> None:
        """更新单文件的 meta 信息（线程安全）"""
        self._ensure_current(runtime)
        with runtime.state.lock:
            if "files" not in runtime.state.index_meta:
                runtime.state.index_meta["files"] = {}
            existing = runtime.state.index_meta["files"].get(rel_path, {})
            existing.update(data)
            runtime.state.index_meta["files"][rel_path] = existing

    def _mark_file_failed(
        self,
        runtime: _ProjectRuntime,
        rel_path: str,
        error: str,
    ) -> None:
        self._ensure_current(runtime)
        with runtime.state.lock:
            old = runtime.state.index_meta.get("files", {}).get(rel_path, {})
            stale = bool(
                old.get("status") == "processed"
                or old.get("chunks_count", 0)
            )
        self._update_file_meta(runtime, rel_path, {
            "status": "failed",
            "error": error,
            "stale": stale,
            "failed_at": datetime.now(timezone.utc).isoformat(),
        })

    def _new_index_meta(self, runtime: _ProjectRuntime) -> Dict[str, Any]:
        return {
            "version": INDEX_META_VERSION,
            "project_root": runtime.project_root,
            "signature": runtime.signature.to_dict(),
            "files": {},
            "stats": {},
        }

    def _ensure_index_signature(self, runtime: _ProjectRuntime) -> None:
        """Rebuild explicitly when vectors/configuration are incompatible."""
        with runtime.state.lock:
            actual = runtime.state.index_meta.get("signature")
            trusted_meta = runtime.state.meta_loaded_from_disk
            expected_chunks = sum(
                int(entry.get("chunks_count", 0) or 0)
                for entry in runtime.state.index_meta.get("files", {}).values()
            )
        expected = runtime.signature.to_dict()
        actual_chunks = runtime.vector_store.count()
        if (
            trusted_meta
            and actual == expected
            and actual_chunks == expected_chunks
        ):
            return

        logger.info(
            "RAG index identity is untrusted/inconsistent; rebuilding "
            "collection: trusted=%s old=%s new=%s chunks=%s/%s",
            trusted_meta,
            actual,
            expected,
            actual_chunks,
            expected_chunks,
        )
        self._ensure_current(runtime)
        runtime.vector_store.clear()
        self._ensure_current(runtime)
        with runtime.state.lock:
            runtime.state.index_meta = self._new_index_meta(runtime)
            runtime.state.meta_loaded_from_disk = True
        self._save_index_meta(runtime)

    # ============================================================
    # 辅助方法
    # ============================================================

    def _get_runtime(self) -> Optional[_ProjectRuntime]:
        with self._runtime_lock:
            return self._runtime

    def _is_current(self, runtime: _ProjectRuntime) -> bool:
        with self._runtime_lock:
            return (
                not self._stopped
                and self._runtime is runtime
                and not runtime.cancelled.is_set()
            )

    def _ensure_current(self, runtime: _ProjectRuntime) -> None:
        if not self._is_current(runtime):
            raise _RAGOperationCancelled(
                f"Stale RAG runtime generation={runtime.generation}"
            )

    @staticmethod
    def _build_signature(
        project_root: str,
        embedder: Embedder,
        vector_store: VectorStore,
    ) -> IndexSignature:
        normalized_project = os.path.normcase(
            os.path.realpath(os.path.abspath(project_root))
        ).replace("\\", "/")
        return IndexSignature(
            provider=str(getattr(embedder, "provider_id", "unknown") or "unknown"),
            model=str(getattr(embedder, "model_name", "unknown") or "unknown"),
            dimensions=int(getattr(embedder, "dimensions", 0) or 0),
            backend=str(getattr(vector_store, "backend_name", "chromadb") or "chromadb"),
            metric=str(getattr(vector_store, "metric", "cosine") or "cosine"),
            extractor=EXTRACTOR_VERSION,
            chunker=CHUNKER_VERSION,
            project=normalized_project,
            collection=str(
                getattr(vector_store, "collection_name", "") or ""
            ),
        )

    @staticmethod
    def _normalize_rel_path(
        runtime: _ProjectRuntime,
        file_path: str,
    ) -> Optional[str]:
        if not file_path:
            return None
        root = os.path.abspath(runtime.project_root)
        candidate = (
            os.path.abspath(file_path)
            if os.path.isabs(file_path)
            else os.path.abspath(os.path.join(root, file_path))
        )
        try:
            if os.path.commonpath([root, candidate]) != root:
                return None
        except ValueError:
            return None
        return os.path.relpath(candidate, root).replace("\\", "/")

    def _refresh_status_cache(
        self,
        runtime: _ProjectRuntime,
        *,
        measure_vector_store: bool = True,
        measure_storage: bool = True,
    ) -> None:
        """Refresh the UI snapshot from the RAG worker at a low-frequency boundary."""
        self._ensure_current(runtime)
        with runtime.state.lock:
            files_meta = copy.deepcopy(
                runtime.state.index_meta.get("files", {})
            )
            previous_storage_size = (
                runtime.state.cached_status.stats.storage_size_mb
            )

        total_chunks = sum(
            int(entry.get("chunks_count", 0) or 0)
            for entry in files_meta.values()
        )
        if measure_vector_store and runtime.vector_store.is_initialized:
            try:
                total_chunks = int(runtime.vector_store.count())
            except Exception as exc:
                logger.warning(f"Failed to refresh RAG vector count: {exc}")

        storage_size_mb = previous_storage_size
        if measure_storage:
            try:
                storage_size_mb = self._calc_dir_size_mb(
                    os.path.join(runtime.project_root, DEFAULT_VECTOR_STORE_DIR)
                )
            except Exception as exc:
                logger.warning(f"Failed to refresh RAG storage size: {exc}")

        stats = IndexStats(
            total_files=len(files_meta),
            processed=sum(
                1 for entry in files_meta.values()
                if entry.get("status") == "processed"
            ),
            failed=sum(
                1 for entry in files_meta.values()
                if entry.get("status") == "failed"
            ),
            excluded=sum(
                1 for entry in files_meta.values()
                if entry.get("status") == "excluded"
            ),
            total_chunks=total_chunks,
            storage_size_mb=storage_size_mb,
        )
        files = [
            FileIndexInfo.from_dict(path, data)
            for path, data in files_meta.items()
        ]

        self._ensure_current(runtime)
        with runtime.state.lock:
            runtime.state.cached_status = IndexStatus(
                available=True,
                indexing=runtime.state.indexing,
                current_track_id=runtime.state.current_track_id,
                stats=stats,
                files=files,
            )
            runtime.state.status_revision += 1

    @staticmethod
    def _calc_dir_size_mb(dir_path: str) -> float:
        """计算目录大小（MB）"""
        total = 0
        try:
            for dirpath, _, filenames in os.walk(dir_path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    try:
                        total += os.path.getsize(fp)
                    except OSError:
                        pass
        except Exception:
            pass
        return round(total / (1024 * 1024), 2)

    def _publish_event(
        self,
        event_type: str,
        data: Dict[str, Any],
        *,
        runtime: Optional[_ProjectRuntime] = None,
    ) -> None:
        """通过 EventBus 发布事件"""
        if self._event_bus is None:
            return
        if runtime is not None and not self._is_current(runtime):
            return

        payload = dict(data)
        if runtime is not None:
            payload.setdefault("generation", runtime.generation)
            payload.setdefault("project_root", runtime.project_root)

        try:
            self._event_bus.publish(event_type, payload)
        except Exception as e:
            logger.warning(f"Failed to publish event '{event_type}': {e}")

    def _record_index_error(
        self,
        runtime: _ProjectRuntime,
        error: Exception,
        *,
        file_path: str = "",
        phase: str = "index",
        persist: bool,
    ) -> None:
        """Expose an indexing failure without misclassifying initialization."""
        if not self._is_current(runtime):
            return

        message = str(error) or error.__class__.__name__
        self._index_error = message
        logger.error(
            "RAG indexing failed (phase=%s, file=%s): %s",
            phase,
            file_path,
            message,
        )

        if persist:
            try:
                self._save_index_meta(runtime)
            except Exception as save_exc:
                logger.error(
                    "Failed to persist RAG metadata after index error: %s",
                    save_exc,
                )
            try:
                self._refresh_status_cache(
                    runtime,
                    measure_vector_store=False,
                    measure_storage=False,
                )
            except Exception as refresh_exc:
                logger.error(
                    "Failed to refresh RAG status after index error: %s",
                    refresh_exc,
                )

        payload = {
            "file_path": file_path,
            "error": message,
            "phase": phase,
            "fatal": phase in {"project_index", "auto_index", "scan"},
        }
        if runtime.state.current_track_id:
            payload["track_id"] = runtime.state.current_track_id
        self._publish_event(
            EVENT_RAG_INDEX_ERROR,
            payload,
            runtime=runtime,
        )

    def _safe_index_project(self, runtime: _ProjectRuntime) -> None:
        """安全的自动索引（异常不冒泡）"""
        try:
            self.index_project_files(runtime)
        except _RAGOperationCancelled:
            return
        except Exception as e:
            self._record_index_error(
                runtime,
                e,
                phase="auto_index",
                persist=True,
            )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "RAGManager",
    "IndexStatus",
    "IndexStats",
    "FileIndexInfo",
    "IndexSignature",
]
