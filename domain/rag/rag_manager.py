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
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from domain.rag.chunker import chunk_file
from domain.rag.embedder import Embedder
from domain.rag.file_extractor import FileIndexRule, extract_content, get_file_index_rule
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
    EVENT_STATE_PROJECT_OPENED,
    EVENT_STATE_PROJECT_CLOSED,
)


logger = logging.getLogger(__name__)


# ============================================================
# 文件扫描规则
# ============================================================

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

    def __init__(self):
        self._embedder: Optional[Embedder] = None
        self._vector_store: Optional[VectorStore] = None
        self._indexing = False
        self._current_track_id: Optional[str] = None
        self._project_root: Optional[str] = None
        self._index_meta: Dict[str, Any] = {}
        self._meta_lock = threading.RLock()  # 保护 _index_meta 跨线程读写
        self._init_error: Optional[str] = None  # 初始化失败的错误信息
        self._subscribed = False
        # 后台工作线程：索引和查询在此线程运行，避免阻塞 Qt UI
        self._worker = RAGWorkerThread()

    @property
    def is_available(self) -> bool:
        """星 RAG 是否可用（项目已打开且 VectorStore 已初始化）"""
        return bool(
            self._project_root
            and self._vector_store is not None
            and self._vector_store.is_initialized
        )

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
        self._init_error = None
        self._index_meta = {}
        self._load_index_meta()
        logger.info(f"Project opened, RAG project root set: {project_root}")

        # ── 提交到后台工作线程：finalize 旧服务 → 初始化新服务 → 自动索引 ──
        self._worker.submit(self._init_for_project, old_root)

    def _init_for_project(self, old_root: Optional[str]) -> None:
        """初始化 VectorStore + Embedder → 自动索引（在工作线程中运行）"""
        try:
            if not self._project_root:
                return

            if self._embedder is None:
                self._embedder = Embedder()

            # 初始化 VectorStore（ChromaDB，同步，~100ms）
            self._vector_store = VectorStore(
                project_root=self._project_root,
                storage_subdir=DEFAULT_VECTOR_STORE_DIR,
            )
            self._vector_store.initialize()
            self._init_error = None

            logger.info("RAG VectorStore initialized, starting auto-index")

            self._publish_event(EVENT_RAG_INIT_COMPLETE, {
                "project_root": self._project_root,
                "status": "ready",
            })

            self._load_index_meta()
            self._safe_index_project()

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

        清除项目状态；ChromaDB 数据已自动持久化，无需显式刷盘。
        """
        logger.info("Project closing, clearing RAG state")
        self._project_root = None
        self._vector_store = None
        self._index_meta = {}
        self._init_error = None

    # ============================================================
    # 索引操作
    # ============================================================

    def index_project_files(self) -> None:
        """
        扫描项目目录，全量/增量索引

        对比 index_meta.json 中的 mtime 与磁盘 mtime，
        仅索引新增或变更的文件。
        """
        if not self._project_root or not self.is_available:
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
                self._save_index_meta()
                self._indexing = False
                self._publish_event(EVENT_RAG_INDEX_COMPLETE, {
                    "total_indexed": 0,
                    "failed": 0,
                    "duration_s": 0,
                    "already_up_to_date": True,
                })
                return

            total = len(files_to_index)
            self._current_track_id = f"idx-{int(time.time())}"

            self._publish_event(EVENT_RAG_INDEX_STARTED, {
                "total_files": total,
                "track_id": self._current_track_id,
            })

            processed = 0
            failed = 0

            for i, (rel_path, abs_path) in enumerate(files_to_index):
                try:
                    self._publish_event(EVENT_RAG_INDEX_PROGRESS, {
                        "processed": i,
                        "total": total,
                        "current_file": rel_path,
                        "track_id": self._current_track_id,
                    })

                    self._index_single_file_internal(rel_path, abs_path)
                    processed += 1

                except Exception as e:
                    failed += 1
                    logger.error(f"Failed to index {rel_path}: {e}")
                    self._publish_event(EVENT_RAG_INDEX_ERROR, {
                        "file_path": rel_path,
                        "error": str(e),
                        "track_id": self._current_track_id,
                    })
                    # 记录失败状态
                    self._update_file_meta(rel_path, {
                        "status": "failed",
                        "error": str(e),
                    })

            duration = time.time() - start_time
            self._save_index_meta()

            self._publish_event(EVENT_RAG_INDEX_COMPLETE, {
                "total_indexed": processed,
                "failed": failed,
                "duration_s": round(duration, 2),
                "entities_count": 0,
                "relations_count": 0,
                "chunks_found": 0,
            })

            logger.info(
                f"Indexing complete: {processed}/{total} files, "
                f"{failed} failed, {duration:.1f}s"
            )

        finally:
            self._indexing = False
            self._current_track_id = None

    def index_single_file(self, file_path: str) -> None:
        """
        单文件增量索引（先删后插）

        Args:
            file_path: 文件路径（绝对或相对于项目根）
        """
        if not self.is_available:
            return

        abs_path, rel_path = self._resolve_path(file_path)
        if not abs_path:
            return

        rule = self._get_file_index_rule(abs_path)
        if rule is None:
            return

        if not rule.should_index:
            try:
                stat = os.stat(abs_path)
                old_meta = self._index_meta.get("files", {}).get(rel_path, {})
                self._mark_file_excluded(rel_path, stat, old_meta, rule)
                self._save_index_meta()
            except OSError:
                pass
            return

        try:
            self._index_single_file_internal(rel_path, abs_path)
            self._save_index_meta()

        except Exception as e:
            logger.error(f"Failed to index single file {rel_path}: {e}")

    def _index_single_file_internal(
        self, rel_path: str, abs_path: str
    ) -> None:
        """内部索引单文件

        流程：读取内容 → 分块 → Embedding → upsert 到 VectorStore
        """
        content = extract_content(abs_path)
        if not content.strip():
            return

        stat = os.stat(abs_path)

        chunks = chunk_file(content, rel_path)
        if not chunks:
            return

        vectors = self._embedder.embed_texts([c.content for c in chunks])
        self._vector_store.upsert_file(rel_path, chunks, vectors)

        self._update_file_meta(rel_path, {
            "chunks_count": len(chunks),
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "status": "processed",
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        })

    # ============================================================
    # 查询
    # ============================================================

    def query(
        self,
        query_text: str,
        top_k: int = DEFAULT_RAG_TOP_K,
        **_kwargs,
    ) -> RAGQueryResult:
        """
        查询知识库（向量相似度检索）

        Args:
            query_text: 查询文本
            top_k:      返回数量

        Returns:
            RAGQueryResult
        """
        if not self.is_available:
            return RAGQueryResult(error="RAG not available")

        vector = self._embedder.embed_single(query_text)
        hits = self._vector_store.query(vector, top_k=top_k)
        result = RAGQueryResult(hits=hits)

        self._publish_event(EVENT_RAG_QUERY_COMPLETE, {
            "query": query_text[:100],
            "results_count": len(hits),
            "chunks_found": len(hits),
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
        self._worker.submit(self.index_project_files)

    def trigger_index_single_file(self, file_path: str) -> None:
        """
        从 Qt 主线程触发单文件增量索引（立即返回，不阻塞 UI）

        Args:
            file_path: 文件路径（绝对或相对于项目根）
        """
        if not self.is_available:
            return
        self._worker.submit(self.index_single_file, file_path)

    async def query_async(
        self,
        query_text: str,
        top_k: int = DEFAULT_RAG_TOP_K,
        **_kwargs,
    ) -> "RAGQueryResult":
        """
        从 Qt 主线程异步查询知识库

        将 query() 提交到工作线程执行，通过 asyncio.wrap_future()
        让 Qt 主线程的协程可以 await 结果，同时不阻塞 UI。

        Args:
            query_text: 查询文本
            top_k:      返回数量上限

        Returns:
            RAGQueryResult
        """
        if not self.is_available:
            return RAGQueryResult(error="RAG not available")

        future = self._worker.submit(
            self.query, query_text, top_k
        )
        if future is None:
            return RAGQueryResult(error="RAG worker not running")

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

        total_chunks = sum(f.get("chunks_count", 0) for f in files_meta.values())
        # 优先使用 VectorStore 的实际 chunk 计数
        if self._vector_store:
            vc = self._vector_store.count()
            if vc > 0:
                total_chunks = vc

        stats = IndexStats(
            total_files=len(files_meta),
            processed=sum(1 for f in files_meta.values() if f.get("status") == "processed"),
            failed=sum(1 for f in files_meta.values() if f.get("status") == "failed"),
            excluded=sum(1 for f in files_meta.values() if f.get("status") == "excluded"),
            total_chunks=total_chunks,
        )

        if self._project_root:
            vs_dir = os.path.join(self._project_root, DEFAULT_VECTOR_STORE_DIR)
            stats.storage_size_mb = self._calc_dir_size_mb(vs_dir)

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

    def delete_file(self, rel_path: str) -> None:
        """删除指定文件的所有 chunk"""
        if self._vector_store:
            self._vector_store.delete_file(rel_path)
        with self._meta_lock:
            self._index_meta.get("files", {}).pop(rel_path, None)
        self._save_index_meta()

    def clear_index(self) -> None:
        """清空知识库（在工作线程执行）"""
        if not self._project_root:
            return

        if self._vector_store:
            self._vector_store.clear()

        with self._meta_lock:
            self._index_meta = {
                "version": 1,
                "project_root": self._project_root,
                "files": {},
                "stats": {},
            }
        self._save_index_meta()
        logger.info("RAG index cleared")

    async def clear_index_async(self) -> None:
        """从 Qt 主线程异步清空知识库"""
        future = self._worker.submit(self.clear_index)
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
        2. 检测已删除文件并从 index_meta 和 VectorStore 中清理
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
                rule = self._get_file_index_rule(abs_path)
                if rule is None:
                    continue

                rel_path = os.path.relpath(abs_path, root).replace("\\", "/")
                disk_files.add(rel_path)

                # 增量检查
                try:
                    stat = os.stat(abs_path)
                    old_meta = files_meta.get(rel_path, {})
                    old_mtime = old_meta.get("mtime", 0.0)

                    if not rule.should_index:
                        self._mark_file_excluded(rel_path, stat, old_meta, rule)
                        continue

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

        从 index_meta 和 VectorStore 中移除。
        """
        if self._worker.is_running:
            self._worker.submit(self._cleanup_deleted_files, deleted_files)
        else:
            # 工作线程未就绪时仅清理 meta
            with self._meta_lock:
                files_meta = self._index_meta.get("files", {})
                for rel_path in deleted_files:
                    files_meta.pop(rel_path, None)
            logger.info(f"Cleaned {len(deleted_files)} deleted files from index meta (meta only)")

    def _cleanup_deleted_files(self, deleted_files: List[str]) -> None:
        """异步清理已删除文件"""
        files_meta = self._index_meta.get("files", {})
        cleaned = 0

        for rel_path in deleted_files:
            if self._vector_store:
                try:
                    self._vector_store.delete_file(rel_path)
                except Exception as e:
                    logger.warning(f"Failed to delete {rel_path} from VectorStore: {e}")
            files_meta.pop(rel_path, None)
            cleaned += 1

        if cleaned:
            self._save_index_meta()
            logger.info(f"Cleaned {cleaned} deleted files from index")

    def _get_file_index_rule(self, abs_path: str) -> Optional[FileIndexRule]:
        return get_file_index_rule(abs_path)

    def _mark_file_excluded(
        self,
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

        if self._vector_store and old_meta.get("status") == "processed":
            try:
                self._vector_store.delete_file(rel_path)
            except Exception as e:
                logger.warning(f"Failed to delete excluded file vectors for {rel_path}: {e}")

        self._update_file_meta(rel_path, {
            "doc_id": "",
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "status": "excluded",
            "chunks_count": 0,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
            "exclude_reason": rule.exclude_reason,
        })

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
                "excluded": sum(1 for f in files_meta.values() if f.get("status") == "excluded"),
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

    # ============================================================
    # 辅助方法
    # ============================================================

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
        except Exception as e:
            logger.warning(f"Failed to publish event '{event_type}': {e}")

    def _safe_index_project(self) -> None:
        """安全的自动索引（异常不冒泡）"""
        try:
            self.index_project_files()
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
