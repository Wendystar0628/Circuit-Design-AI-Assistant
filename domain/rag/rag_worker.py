# RAG Worker Thread - RAG 后台工作线程
"""
RAG 后台工作线程

设计背景：
    Embedding（sentence-transformers）和 ChromaDB 均为同步阻塞调用，
    不需要 asyncio 事件循环。使用 ThreadPoolExecutor（单 worker）即可将
    所有 RAG 操作移出 API 事件循环，避免阻塞请求与事件推送。

通信机制：
    运行时 → 工作线程：executor.submit(fn, *args)
    工作线程 → 运行时：EventBus.publish()
    查询结果回传：asyncio.wrap_future() 将 concurrent.futures.Future
    接回调用方的 asyncio 事件循环。
"""

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Optional, Set

logger = logging.getLogger(__name__)


class RAGWorkerThread:
    """
    RAG 专用后台工作线程（ThreadPoolExecutor 封装）

    使用单 worker 线程池串行执行所有 RAG 操作，
    使 API 事件循环保持响应。

    使用方式：
        worker = RAGWorkerThread()
        worker.start_and_wait()

        # 提交同步函数（非阻塞）
        worker.submit(manager.index_project_files)

        # 提交带参函数
        worker.submit(manager.index_single_file, file_path)

        # 提交并在 asyncio 协程中等待结果
        future = worker.submit(manager.query, query_text, top_k)
        result = await asyncio.wrap_future(future)

        # 关闭
        worker.stop()
    """

    def __init__(self):
        self._executor: Optional[ThreadPoolExecutor] = None
        self._ready = threading.Event()
        self._lock = threading.RLock()
        self._futures: Set[Future] = set()
        self._stopping = False

    # ============================================================
    # 生命周期
    # ============================================================

    def start_and_wait(self, timeout: float = 5.0) -> bool:
        """
        创建 ThreadPoolExecutor 并标记就绪（立即返回，无需等待）

        Returns:
            True（始终成功）
        """
        with self._lock:
            if self._executor is not None:
                return True
            self._stopping = False
            self._executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="RAGWorker",
            )
            self._ready.set()
        logger.info("RAGWorkerThread (ThreadPoolExecutor) ready")
        return True

    def stop(self) -> None:
        """Idempotently cancel queued work and wait for the active job.

        A running synchronous HTTP/database call cannot be force-killed safely;
        its project runtime is cancelled by ``RAGManager`` and checks that
        token before committing any subsequent write or UI event.
        """
        with self._lock:
            executor = self._executor
            if executor is None:
                return
            self._stopping = True
            self._executor = None
            self._ready.clear()
            futures = list(self._futures)

        for future in futures:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)

        with self._lock:
            self._futures.clear()
        logger.info("RAGWorkerThread stopped")

    def cancel_pending(self) -> None:
        """Cancel tasks which have not started yet."""
        with self._lock:
            futures = list(self._futures)
        for future in futures:
            future.cancel()

    # ============================================================
    # 任务提交
    # ============================================================

    @property
    def is_running(self) -> bool:
        """工作线程池是否就绪"""
        with self._lock:
            return self._executor is not None and not self._stopping

    def submit(self, fn: Callable, *args: Any, **kwargs: Any) -> Optional[Future]:
        """
        从任意线程提交同步函数到工作线程（非阻塞）

        Args:
            fn:     可调用对象
            *args:  位置参数
            **kwargs: 关键字参数

        Returns:
            concurrent.futures.Future；工作线程未就绪时返回 None
        """
        with self._lock:
            executor = self._executor
            if executor is None or self._stopping:
                logger.error("RAGWorkerThread not running, cannot submit task")
                return None
            try:
                future = executor.submit(fn, *args, **kwargs)
            except RuntimeError:
                return None
            self._futures.add(future)

        def _discard(done: Future) -> None:
            with self._lock:
                self._futures.discard(done)

        future.add_done_callback(_discard)
        return future


# ============================================================
# 模块导出
# ============================================================

__all__ = ["RAGWorkerThread"]
