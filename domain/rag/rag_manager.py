# RAG Manager - RAG 业务逻辑管理器
"""
RAG 业务逻辑管理器

设计理念：
    RAG 是项目的原生能力，不需要手动开关。
    打开项目 → 自动初始化 LightRAG → 自动增量索引 → AI 智能检索。
    切换项目 → 自动 finalize 旧索引 → 为新项目重新初始化。

职责：
- 项目生命周期联动（订阅 PROJECT_OPENED / PROJECT_CLOSED）
- 项目打开时自动初始化 LightRAG 并增量索引
- 项目文件扫描与索引（全量/增量/单文件）
- 查询接口（供 ContextRetriever 调用）
- 索引状态管理（index_meta.json）
- 增量更新：mtime 对比 + 已删除文件清理
- 通过 EventBus 发布 RAG 事件

架构位置：
- 被 Application 层 bootstrap 创建并注册到 ServiceLocator
- 依赖 RAGService（LightRAG 封装层）
- 依赖 EventBus（事件发布）
- 订阅 EVENT_STATE_PROJECT_OPENED / EVENT_STATE_PROJECT_CLOSED
"""

import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from domain.rag.rag_service import RAGService, RAGQueryResult
from domain.rag.rag_worker import RAGWorkerThread
from infrastructure.config.settings import (
    DEFAULT_RAG_QUERY_MODE,
    DEFAULT_RAG_TOP_K,
    DEFAULT_RAG_STORAGE_DIR,
    DEFAULT_RAG_CONTEXT_TOKEN_BUDGET,
    DEFAULT_RAG_BATCH_INDEX_SIZE,
    CONFIG_RAG_QUERY_MODE,
)
from shared.event_types import (
    EVENT_RAG_INIT_COMPLETE,
    EVENT_RAG_INDEX_STARTED,
    EVENT_RAG_INDEX_PROGRESS,
    EVENT_RAG_INDEX_COMPLETE,
    EVENT_RAG_INDEX_ERROR,
    EVENT_RAG_QUERY_COMPLETE,
    EVENT_STATE_PROJECT_OPENED,
    EVENT_STATE_PROJECT_CLOSED,
)


logger = logging.getLogger(__name__)


# ============================================================
# 文件扫描规则
# ============================================================

INDEXABLE_EXTENSIONS: Set[str] = {
    ".cir", ".sp", ".spice", ".lib", ".inc",  # SPICE 文件
    ".md", ".txt",                              # 文档
}

EXCLUDED_DIRS: Set[str] = {
    ".circuit_ai", "__pycache__", ".git", ".venv",
    "node_modules", ".idea", ".vscode",
}

INDEX_META_FILE = "index_meta.json"


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
    status: str = "pending"  # pending / processing / processed / failed
    chunks_count: int = 0
    indexed_at: str = ""
    error: Optional[str] = None

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
        )


@dataclass
class IndexStats:
    """索引统计"""
    total_files: int = 0
    processed: int = 0
    failed: int = 0
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


# ============================================================
# RAG Manager
# ============================================================

class RAGManager:
    """
    RAG 业务逻辑管理器

    RAG 是项目的原生能力：
    - 打开项目 → 自动初始化 LightRAG + 自动增量索引
    - 关闭项目 → 自动 finalize 刷盘
    - AI 对话时 → ContextRetriever 自动调用 query() 检索

    持久化策略：
    - LightRAG 存储（KV/Vector/Graph）：{project}/.circuit_ai/rag_storage/
    - index_meta.json：文件索引元数据，随索引操作更新
    → 每个项目有独立的索引存储，项目隔离
    """

    def __init__(self, rag_service: RAGService):
        self._service = rag_service
        self._indexing = False
        self._current_track_id: Optional[str] = None
        self._project_root: Optional[str] = None
        self._index_meta: Dict[str, Any] = {}
        self._meta_lock = threading.RLock()  # 保护 _index_meta 跨线程读写
        self._embedding_verified = False
        self._init_error: Optional[str] = None  # 初始化失败的错误信息
        self._subscribed = False
        # 后台工作线程：所有 LightRAG 操作在此独立 asyncio 循环中执行
        # 避免 CPU 密集操作（分块、图计算）饿死 Qt 主线程（qasync 融合循环）
        self._worker = RAGWorkerThread()

    @property
    def is_available(self) -> bool:
        """RAG 是否可用（项目已打开且服务已初始化）"""
        return bool(self._project_root and self._service.is_initialized)

    @property
    def is_indexing(self) -> bool:
        return self._indexing

    @property
    def project_root(self) -> Optional[str]:
        """当前项目根目录"""
        return self._project_root

    @property
    def init_error(self) -> Optional[str]:
        """最近一次初始化错误（None 表示无错误）"""
        return self._init_error

    @property
    def service(self) -> RAGService:
        return self._service

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
        self._worker.start_and_wait()

        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_EVENT_BUS

            event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            if event_bus:
                event_bus.subscribe(
                    EVENT_STATE_PROJECT_OPENED,
                    self._on_project_opened,
                )
                event_bus.subscribe(
                    EVENT_STATE_PROJECT_CLOSED,
                    self._on_project_closed,
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

        # ── 同步：立即设置 project_root ──
        old_root = self._project_root
        self._project_root = project_root
        self._embedding_verified = False
        self._init_error = None
        self._index_meta = {}
        self._load_index_meta()
        logger.info(f"Project opened, RAG project root set: {project_root}")

        # ── 提交到后台工作线程：finalize 旧服务 → 初始化新服务 → 自动索引 ──
        self._worker.submit(self._async_init_for_project(old_root))

    async def _async_init_for_project(self, old_root: Optional[str]) -> None:
        """
        异步：finalize 旧服务 → 初始化 LightRAG → 验证 Embedding → 自动索引
        """
        try:
            # 1. 销毁旧项目实例
            if old_root and self._service.is_initialized:
                await self._service.finalize()

            # 2. 为新项目初始化 LightRAG
            if not self._project_root:
                return

            await self._service.create(self._project_root)
            await self._service.initialize()

            # 3. 验证 Embedding API
            if not await self._service.test_embedding():
                self._init_error = "Embedding API 不可用，请检查 API Key"
                logger.error(self._init_error)
                self._publish_event(EVENT_RAG_INIT_COMPLETE, {
                    "project_root": self._project_root,
                    "status": "error",
                    "error": self._init_error,
                })
                return
            self._embedding_verified = True
            self._init_error = None

            logger.info("RAG service initialized, starting auto-index")

            # 4. 通知 UI：服务已就绪
            self._publish_event(EVENT_RAG_INIT_COMPLETE, {
                "project_root": self._project_root,
                "status": "ready",
            })

            # 5. 加载已有索引元数据（用于 UI 显示）
            self._load_index_meta()

            # 6. 自动增量索引
            await self._safe_index_project()

        except Exception as e:
            self._init_error = str(e)
            logger.error(f"Failed to auto-init RAG for project: {e}")
            self._publish_event(EVENT_RAG_INIT_COMPLETE, {
                "project_root": self._project_root or "",
                "status": "error",
                "error": f"RAG 自动初始化失败: {e}",
            })

    def _on_project_closed(self, event_data) -> None:
        """
        项目关闭事件处理（同步入口）

        同步清除 project_root → 异步刷盘。
        """
        logger.info("Project closing, finalizing RAG")

        self._project_root = None
        self._index_meta = {}
        self._embedding_verified = False
        self._init_error = None

        # 提交到后台工作线程异步刷盘
        self._worker.submit(self._async_finalize_service())

    async def _async_finalize_service(self) -> None:
        """异步销毁 LightRAG 存储（刷盘持久化）"""
        try:
            if self._service.is_initialized:
                await self._service.finalize()
        except Exception as e:
            logger.error(f"Failed to finalize RAG service: {e}")

    # ============================================================
    # 索引操作
    # ============================================================

    async def index_project_files(self) -> None:
        """
        扫描项目目录，全量/增量索引

        对比 index_meta.json 中的 mtime 与磁盘 mtime，
        仅索引新增或变更的文件。
        """
        if not self._project_root or not self._service.is_initialized:
            logger.debug("RAG not available, skipping index")
            return

        if self._indexing:
            logger.warning("Indexing already in progress")
            return

        if not self._project_root:
            logger.error("No project root set")
            return

        self._indexing = True
        start_time = time.time()

        try:
            # 确保使用最新的磁盘状态（与 _async_init_for_project 路径保持一致）
            self._load_index_meta()

            # 扫描文件
            files_to_index = self._scan_project_files()
            if not files_to_index:
                logger.info("No files to index (all up to date)")
                self._indexing = False
                self._publish_event(EVENT_RAG_INDEX_COMPLETE, {
                    "total_indexed": 0,
                    "failed": 0,
                    "duration_s": 0,
                    "already_up_to_date": True,
                })
                return

            # ── 读取所有文件内容，过滤空文件 ────────────────────────────
            all_entries: List[tuple] = []  # (rel_path, content, stat)
            for rel_path, abs_path in files_to_index:
                content = self._read_file_safe(abs_path)
                if not content.strip():
                    logger.debug(f"Skipping empty file: {rel_path}")
                    continue
                all_entries.append((rel_path, content, os.stat(abs_path)))

            if not all_entries:
                logger.info("No non-empty files to index")
                self._indexing = False
                self._publish_event(EVENT_RAG_INDEX_COMPLETE, {
                    "total_indexed": 0,
                    "failed": 0,
                    "duration_s": 0,
                    "already_up_to_date": True,
                })
                return

            total = len(all_entries)
            batch_size = DEFAULT_RAG_BATCH_INDEX_SIZE
            n_batches = (total + batch_size - 1) // batch_size
            self._current_track_id = f"idx-{int(time.time())}"

            self._publish_event(EVENT_RAG_INDEX_STARTED, {
                "total_files": total,
                "track_id": self._current_track_id,
            })

            logger.info(
                f"Starting indexed: {total} files → "
                f"{n_batches} batch(es) × {batch_size} files/batch "
                f"(LightRAG llm_model_max_async controls per-batch concurrency)"
            )

            # ── 分批次提交 ───────────────────────────────────────────────
            # 策略来源：LightRAG constants.py DEFAULT_MAX_ASYNC=4
            # batch_size = max_async × 4 = 16（在 settings 中可调）
            # 每批一次 ainsert → LightRAG 内部并发处理本批 chunks
            # 每批完成后保存 meta（支持断点：重启后已完成批次自动跳过）
            total_processed = 0
            indexed_at = datetime.now(timezone.utc).isoformat()

            for batch_idx in range(n_batches):
                batch_start = batch_idx * batch_size
                batch_end = min(batch_start + batch_size, total)
                batch = all_entries[batch_start:batch_end]

                batch_rel_paths = [e[0] for e in batch]
                batch_texts = [e[1] for e in batch]
                batch_stats = [e[2] for e in batch]
                b_size = len(batch)

                logger.info(
                    f"Batch {batch_idx + 1}/{n_batches}: "
                    f"files {batch_start + 1}–{batch_end}/{total}"
                )
                self._publish_event(EVENT_RAG_INDEX_PROGRESS, {
                    "processed": total_processed,
                    "total": total,
                    "current_file": batch_rel_paths[0],
                    "batch": batch_idx + 1,
                    "n_batches": n_batches,
                    "track_id": self._current_track_id,
                })

                track_id = await self._service.insert(
                    texts=batch_texts,
                    file_paths=batch_rel_paths,
                )

                doc_info = await self._service.get_all_doc_info_by_track_id(track_id)

                for rel_path, stat in zip(batch_rel_paths, batch_stats):
                    doc_id, chunks_count = doc_info.get(rel_path, ("", 0))
                    self._update_file_meta(rel_path, {
                        "doc_id": doc_id or track_id,
                        "chunks_count": chunks_count,
                        "mtime": stat.st_mtime,
                        "size": stat.st_size,
                        "status": "processed",
                        "indexed_at": indexed_at,
                    })

                # 每批完成后立即持久化 meta（支持断点续传）
                self._save_index_meta()
                total_processed += b_size
                elapsed = time.time() - start_time
                logger.info(
                    f"Batch {batch_idx + 1}/{n_batches} done: "
                    f"{total_processed}/{total} files, {elapsed:.1f}s elapsed"
                )

            duration = time.time() - start_time
            self._publish_event(EVENT_RAG_INDEX_COMPLETE, {
                "total_indexed": total_processed,
                "failed": 0,
                "duration_s": round(duration, 2),
            })

            logger.info(
                f"All batches complete: {total_processed}/{total} files "
                f"in {duration:.1f}s ({duration/max(total_processed,1):.1f}s/file)"
            )

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Batch indexing failed after {duration:.1f}s: {e}")
            self._publish_event(EVENT_RAG_INDEX_ERROR, {
                "file_path": "batch",
                "error": str(e),
                "track_id": self._current_track_id or "",
            })

        finally:
            self._indexing = False
            self._current_track_id = None

    async def index_single_file(self, file_path: str) -> None:
        """
        单文件增量索引（先删后插）

        Args:
            file_path: 文件路径（绝对或相对于项目根）
        """
        if not self.is_available:
            return

        abs_path, rel_path = self._resolve_path(file_path)
        if not abs_path or not self._is_indexable(abs_path):
            return

        try:
            # 先删除旧文档
            old_meta = self._index_meta.get("files", {}).get(rel_path, {})
            old_doc_id = old_meta.get("doc_id")
            if old_doc_id:
                try:
                    await self._service.delete_document(old_doc_id)
                except Exception:
                    pass  # 删除失败不阻塞重新索引

            await self._index_single_file_internal(rel_path, abs_path)
            self._save_index_meta()

        except Exception as e:
            logger.error(f"Failed to index single file {rel_path}: {e}")

    async def _index_single_file_internal(
        self, rel_path: str, abs_path: str
    ) -> None:
        """内部索引单文件

        正确使用 LightRAG doc_status 机制：
        1. ainsert() 返回 track_id（监控用，非文档 ID）
        2. 插入完成后查询 doc_status.get_docs_by_track_id(track_id)
           → 获取真实 doc_id（MD5）和 chunks_count
        3. 将真实 doc_id 写入 meta（供 adelete_by_doc_id 删除时使用）
        """
        content = self._read_file_safe(abs_path)
        if not content.strip():
            return

        stat = os.stat(abs_path)

        track_id = await self._service.insert(
            texts=[content],
            file_paths=[rel_path],
        )

        # 从 LightRAG doc_status 查询真实 doc_id 和 chunks_count
        doc_id, chunks_count = await self._service.get_doc_info_by_track_id(track_id)

        self._update_file_meta(rel_path, {
            "doc_id": doc_id or track_id,  # doc_id 为空时回退到 track_id
            "chunks_count": chunks_count,
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "status": "processed",
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        })

    # ============================================================
    # 查询
    # ============================================================

    async def query(
        self,
        query_text: str,
        mode: str = DEFAULT_RAG_QUERY_MODE,
        top_k: int = DEFAULT_RAG_TOP_K,
    ) -> RAGQueryResult:
        """
        查询知识库

        Args:
            query_text: 查询文本
            mode: 检索模式
            top_k: 返回数量

        Returns:
            RAGQueryResult
        """
        if not self.is_available:
            return RAGQueryResult({"status": "error", "message": "RAG not available"})

        result = await self._service.query(query_text, mode=mode, top_k=top_k)

        self._publish_event(EVENT_RAG_QUERY_COMPLETE, {
            "query": query_text[:100],
            "mode": mode,
            "results_count": result.entities_count + result.chunks_count,
            "entities_found": result.entities_count,
            "relations_found": result.relations_count,
            "chunks_found": result.chunks_count,
        })

        return result

    # ============================================================
    # Qt 主线程入口方法（同步触发，工作在后台线程）
    # ============================================================

    def trigger_index(self) -> None:
        """
        从 Qt 主线程触发全量/增量索引（立即返回，不阻塞 UI）

        索引在 RAGWorkerThread 中异步执行。
        """
        if not self.is_available:
            logger.debug("RAG not available, cannot trigger index")
            return
        self._worker.submit(self.index_project_files())

    def trigger_index_single_file(self, file_path: str) -> None:
        """
        从 Qt 主线程触发单文件增量索引（立即返回，不阻塞 UI）

        Args:
            file_path: 文件路径（绝对或相对于项目根）
        """
        if not self.is_available:
            return
        self._worker.submit(self.index_single_file(file_path))

    async def query_async(
        self,
        query_text: str,
        mode: str = DEFAULT_RAG_QUERY_MODE,
        top_k: int = DEFAULT_RAG_TOP_K,
    ) -> "RAGQueryResult":
        """
        从 Qt 主线程异步查询知识库

        将 query() 提交到工作线程执行，通过 asyncio.wrap_future()
        让 Qt 主线程的协程可以 await 结果，同时不阻塞 UI。

        Args:
            query_text: 查询文本
            mode: 检索模式
            top_k: 返回数量

        Returns:
            RAGQueryResult
        """
        if not self.is_available:
            return RAGQueryResult({"status": "error", "message": "RAG not available"})

        future = self._worker.submit(
            self.query(query_text, mode=mode, top_k=top_k)
        )
        if future is None:
            return RAGQueryResult({"status": "error", "message": "RAG worker not running"})

        return await asyncio.wrap_future(future)

    def stop(self) -> None:
        """停止工作线程（应用退出时调用）"""
        self._worker.stop()

    # ============================================================
    # 状态查询
    # ============================================================

    def get_index_status(self) -> IndexStatus:
        """返回当前索引状态（线程安全）"""
        with self._meta_lock:
            files_meta = dict(self._index_meta.get("files", {}))

        stats = IndexStats(
            total_files=len(files_meta),
            processed=sum(1 for f in files_meta.values() if f.get("status") == "processed"),
            failed=sum(1 for f in files_meta.values() if f.get("status") == "failed"),
            total_chunks=sum(f.get("chunks_count", 0) for f in files_meta.values()),
        )

        # 从 LightRAG 存储文件中读取实体/关系/分块数量
        if self._project_root:
            storage_dir = os.path.join(self._project_root, DEFAULT_RAG_STORAGE_DIR)
            stats.storage_size_mb = self._calc_dir_size_mb(storage_dir)
            stats.total_entities = self._count_json_entries(
                os.path.join(storage_dir, "kv_store_full_entities.json"))
            stats.total_relations = self._count_json_entries(
                os.path.join(storage_dir, "kv_store_full_relations.json"))
            chunks_count = self._count_json_entries(
                os.path.join(storage_dir, "kv_store_text_chunks.json"))
            if chunks_count > 0:
                stats.total_chunks = chunks_count

        files = [
            FileIndexInfo.from_dict(path, data)
            for path, data in files_meta.items()
        ]

        return IndexStatus(
            available=self.is_available,
            indexing=self._indexing,
            current_track_id=self._current_track_id,
            stats=stats,
            files=files,
        )

    async def delete_document(self, doc_id: str) -> None:
        """删除文档及关联实体和关系"""
        if not self._service.is_initialized:
            return

        await self._service.delete_document(doc_id)

        # 从 meta 中移除
        with self._meta_lock:
            files_meta = self._index_meta.get("files", {})
            to_remove = [
                path for path, data in files_meta.items()
                if data.get("doc_id") == doc_id
            ]
            for path in to_remove:
                del files_meta[path]
        self._save_index_meta()

    async def clear_index(self) -> None:
        """
        清空知识库（在工作线程执行）

        删除所有 LightRAG 存储文件并重置索引元数据。
        完成后重新初始化存储。
        """
        if not self._project_root:
            return

        import shutil

        storage_dir = os.path.join(self._project_root, DEFAULT_RAG_STORAGE_DIR)

        # 销毁现有实例
        if self._service.is_initialized:
            try:
                await self._service.finalize()
            except Exception as e:
                logger.warning(f"Finalize before clear failed: {e}")

        # 删除存储文件（保留目录）
        try:
            if os.path.isdir(storage_dir):
                for item in os.listdir(storage_dir):
                    item_path = os.path.join(storage_dir, item)
                    try:
                        if os.path.isfile(item_path):
                            os.remove(item_path)
                        elif os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                    except Exception as e:
                        logger.warning(f"Failed to remove {item_path}: {e}")
        except Exception as e:
            logger.error(f"Failed to clear storage dir: {e}")

        # 重置 meta
        with self._meta_lock:
            self._index_meta = {
                "version": 1,
                "project_root": self._project_root,
                "files": {},
                "stats": {},
            }
        self._save_index_meta()

        # 重新初始化存储
        try:
            await self._service.create(self._project_root)
            await self._service.initialize()
            logger.info("RAG storage cleared and re-initialized")
        except Exception as e:
            logger.error(f"Failed to re-initialize after clear: {e}")

    async def clear_index_async(self) -> None:
        """
        从 Qt 主线程异步清空知识库

        将 clear_index() 提交到工作线程，通过 asyncio.wrap_future()
        让 Qt 协程可以 await 结果。
        """
        future = self._worker.submit(self.clear_index())
        if future is None:
            raise RuntimeError("RAG worker not running")
        await asyncio.wrap_future(future)

    # ============================================================
    # 文件扫描
    # ============================================================

    def _scan_project_files(self) -> List[tuple]:
        """
        扫描项目目录，返回需要索引的 (rel_path, abs_path) 列表

        增量策略：
        1. 对比 mtime，仅返回新增或变更文件
        2. 检测已删除文件并从 index_meta 和 LightRAG 中清理
        """
        if not self._project_root:
            return []

        result = []
        files_meta = self._index_meta.get("files", {})
        root = Path(self._project_root)
        disk_files: Set[str] = set()  # 当前磁盘上存在的可索引文件

        for dirpath, dirnames, filenames in os.walk(root):
            # 排除目录
            dirnames[:] = [
                d for d in dirnames
                if d not in EXCLUDED_DIRS
            ]

            for filename in filenames:
                abs_path = os.path.join(dirpath, filename)
                ext = os.path.splitext(filename)[1].lower()

                if ext not in INDEXABLE_EXTENSIONS:
                    continue

                rel_path = os.path.relpath(abs_path, root).replace("\\", "/")
                disk_files.add(rel_path)

                # 增量检查
                try:
                    stat = os.stat(abs_path)
                    old_meta = files_meta.get(rel_path, {})
                    old_mtime = old_meta.get("mtime", 0.0)

                    if (old_meta.get("status") == "processed"
                            and abs(stat.st_mtime - old_mtime) < 0.01):
                        continue  # 未变更，跳过

                    result.append((rel_path, abs_path))

                except OSError:
                    continue

        # 检测已删除文件：meta 中存在但磁盘上不存在
        deleted_files = [
            rel_path for rel_path in files_meta
            if rel_path not in disk_files
        ]
        if deleted_files:
            self._schedule_cleanup_deleted(deleted_files)

        return result

    def _schedule_cleanup_deleted(self, deleted_files: List[str]) -> None:
        """
        调度清理已删除文件的索引数据

        从 index_meta 和 LightRAG 存储中移除。
        """
        if self._worker.is_running:
            self._worker.submit(self._cleanup_deleted_files(deleted_files))
        else:
            # 工作线程未就绪时仅清理 meta（不含 LightRAG 存储）
            with self._meta_lock:
                files_meta = self._index_meta.get("files", {})
                for rel_path in deleted_files:
                    files_meta.pop(rel_path, None)
            logger.info(f"Cleaned {len(deleted_files)} deleted files from index meta (meta only)")

    async def _cleanup_deleted_files(self, deleted_files: List[str]) -> None:
        """异步清理已删除文件"""
        files_meta = self._index_meta.get("files", {})
        cleaned = 0

        for rel_path in deleted_files:
            meta = files_meta.get(rel_path, {})
            doc_id = meta.get("doc_id")

            # 从 LightRAG 删除
            if doc_id and self._service.is_initialized:
                try:
                    await self._service.delete_document(doc_id)
                except Exception as e:
                    logger.warning(f"Failed to delete {rel_path} from LightRAG: {e}")

            # 从 meta 移除
            files_meta.pop(rel_path, None)
            cleaned += 1

        if cleaned:
            self._save_index_meta()
            logger.info(f"Cleaned {cleaned} deleted files from index")

    def _is_indexable(self, abs_path: str) -> bool:
        """检查文件是否可索引"""
        ext = os.path.splitext(abs_path)[1].lower()
        return ext in INDEXABLE_EXTENSIONS

    def _resolve_path(self, file_path: str) -> tuple:
        """解析路径为 (abs_path, rel_path)"""
        if not self._project_root:
            return None, None

        if os.path.isabs(file_path):
            abs_path = file_path
            try:
                rel_path = os.path.relpath(abs_path, self._project_root).replace("\\", "/")
            except ValueError:
                return None, None
        else:
            rel_path = file_path.replace("\\", "/")
            abs_path = os.path.join(self._project_root, rel_path)

        if not os.path.isfile(abs_path):
            return None, None

        return abs_path, rel_path

    # ============================================================
    # index_meta.json 管理
    # ============================================================

    def _load_index_meta(self) -> None:
        """加载 index_meta.json（线程安全）"""
        if not self._project_root:
            return

        meta_path = os.path.join(
            self._project_root, DEFAULT_RAG_STORAGE_DIR, INDEX_META_FILE
        )
        try:
            if os.path.isfile(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {
                    "version": 1,
                    "project_root": self._project_root,
                    "files": {},
                    "stats": {},
                }
            with self._meta_lock:
                self._index_meta = data
        except Exception as e:
            logger.warning(f"Failed to load index meta: {e}")
            with self._meta_lock:
                self._index_meta = {"version": 1, "files": {}, "stats": {}}

    def _save_index_meta(self) -> None:
        """保存 index_meta.json（线程安全）"""
        if not self._project_root:
            return

        storage_dir = os.path.join(self._project_root, DEFAULT_RAG_STORAGE_DIR)
        os.makedirs(storage_dir, exist_ok=True)
        meta_path = os.path.join(storage_dir, INDEX_META_FILE)

        with self._meta_lock:
            self._index_meta["last_full_index"] = datetime.now(timezone.utc).isoformat()
            files_meta = self._index_meta.get("files", {})
            self._index_meta["stats"] = {
                "total_files": len(files_meta),
                "processed": sum(1 for f in files_meta.values() if f.get("status") == "processed"),
                "failed": sum(1 for f in files_meta.values() if f.get("status") == "failed"),
                "total_chunks": sum(f.get("chunks_count", 0) for f in files_meta.values()),
            }
            snapshot = dict(self._index_meta)

        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save index meta: {e}")

    def _update_file_meta(self, rel_path: str, data: Dict[str, Any]) -> None:
        """更新单文件的 meta 信息（线程安全）"""
        with self._meta_lock:
            if "files" not in self._index_meta:
                self._index_meta["files"] = {}
            existing = self._index_meta["files"].get(rel_path, {})
            existing.update(data)
            self._index_meta["files"][rel_path] = existing

    def invalidate_embedding_cache(self) -> None:
        """
        使 Embedding 验证缓存失效

        API Key 变更时调用，下次打开项目会重新验证。
        """
        self._embedding_verified = False

    # ============================================================
    # 辅助方法
    # ============================================================

    @staticmethod
    def _read_file_safe(abs_path: str, max_size: int = 1024 * 1024) -> str:
        """安全读取文件内容（限制大小）"""
        try:
            size = os.path.getsize(abs_path)
            if size > max_size:
                logger.warning(f"File too large, skipping: {abs_path} ({size} bytes)")
                return ""

            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception as e:
            logger.warning(f"Failed to read file {abs_path}: {e}")
            return ""

    @staticmethod
    def _count_json_entries(json_path: str) -> int:
        """读取 LightRAG KV 存储 JSON 文件中的条目数"""
        try:
            if not os.path.isfile(json_path):
                return 0
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return len(data)
            if isinstance(data, list):
                return len(data)
        except Exception:
            pass
        return 0

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

    @staticmethod
    def _publish_event(event_type: str, data: Dict[str, Any]) -> None:
        """通过 EventBus 发布事件"""
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_EVENT_BUS

            event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            if event_bus:
                event_bus.publish(event_type, data)
        except Exception:
            pass

    async def _safe_index_project(self) -> None:
        """安全的自动索引（异常不冒泡）"""
        try:
            await self.index_project_files()
        except Exception as e:
            logger.error(f"Auto-index failed: {e}")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "RAGManager",
    "IndexStatus",
    "IndexStats",
    "FileIndexInfo",
]
