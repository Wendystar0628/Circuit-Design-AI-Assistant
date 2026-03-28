# RAG Worker Thread - RAG 后台工作线程
"""
RAG 后台工作线程

设计背景：
    Embedding（sentence-transformers）和 ChromaDB 均为同步阻塞调用，
    不需要 asyncio 事件循环。使用 ThreadPoolExecutor（单 worker）即可将
    所有 RAG 操作移出 Qt 主线程，避免 UI 卡顿。

通信机制：
    Qt 主线程 → 工作线程：executor.submit(fn, *args)
    工作线程  → Qt 主线程：EventBus.publish()（已内置跨线程 QMetaObject 投递）
    查询结果回传：asyncio.wrap_future() 允许 Qt 协程 await concurrent.futures.Future
"""

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class RAGWorkerThread:
    """
    RAG 专用后台工作线程（ThreadPoolExecutor 封装）

    使用单 worker 线程池串行执行所有 RAG 操作，
    使 Qt 主线程（qasync 融合循环）始终保持响应。

    使用方式：
        worker = RAGWorkerThread()
        worker.start_and_wait()

        # 提交同步函数（非阻塞）
        worker.submit(manager.index_project_files)

        # 提交带参函数
        worker.submit(manager.index_single_file, file_path)

        # 提交并在 Qt 协程中等待结果
        future = worker.submit(manager.query, query_text, top_k)
        result = await asyncio.wrap_future(future)

        # 关闭
        worker.stop()
    """

    def __init__(self):
        self._executor: Optional[ThreadPoolExecutor] = None
        self._ready = threading.Event()

    # ============================================================
    # 生命周期
    # ============================================================

    def start_and_wait(self, timeout: float = 5.0) -> bool:
        """
        创建 ThreadPoolExecutor 并标记就绪（立即返回，无需等待）

        Returns:
            True（始终成功）
        """
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="RAGWorker",
        )
        self._ready.set()
        logger.info("RAGWorkerThread (ThreadPoolExecutor) ready")
        return True

    def stop(self) -> None:
        """安全关闭工作线程池（等待当前任务完成）"""
        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None
            logger.info("RAGWorkerThread stopped")

    # ============================================================
    # 任务提交
    # ============================================================

    @property
    def is_running(self) -> bool:
        """工作线程池是否就绪"""
        return self._executor is not None

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
        if not self.is_running:
            logger.error("RAGWorkerThread not running, cannot submit task")
            return None
        return self._executor.submit(fn, *args, **kwargs)


# ============================================================
# 模块导出
# ============================================================

__all__ = ["RAGWorkerThread"]
