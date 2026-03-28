# RAG Worker Thread - RAG 后台工作线程
"""
RAG 后台工作线程

设计背景：
    应用使用 qasync 将 asyncio 与 Qt 事件循环融合到同一主线程。
    LLM 流式对话不会卡顿，因为其 await 点纯属网络 I/O，频率高、CPU 耗时极短。
    LightRAG 的 ainsert/aquery 在 await 点之间存在大量 CPU 密集操作
    （文本分块、实体图计算、KV JSON 序列化等），每次可持续 100-500ms，
    完全饿死 Qt 主线程事件循环，导致所有 UI 操作卡顿甚至假死。

解决方案：
    将所有 LightRAG 操作（初始化、索引、查询）移入独立后台线程，
    该线程持有专属 asyncio 事件循环，与 Qt 主线程完全解耦。

通信机制：
    Qt 主线程 → 工作线程：asyncio.run_coroutine_threadsafe()
    工作线程  → Qt 主线程：EventBus.publish()（已内置跨线程 QMetaObject 投递）
    查询结果回传：asyncio.wrap_future() 允许 Qt 协程 await 工作线程结果
"""

import asyncio
import logging
import threading
from concurrent.futures import Future
from typing import Any, Coroutine, Optional

logger = logging.getLogger(__name__)


class RAGWorkerThread(threading.Thread):
    """
    RAG 专用后台工作线程

    运行独立 asyncio 事件循环，接收并执行所有 LightRAG 协程，
    使 Qt 主线程（qasync 融合循环）始终保持响应。

    使用方式：
        worker = RAGWorkerThread()
        worker.start_and_wait()

        # 提交协程（非阻塞）
        worker.submit(manager.index_project_files())

        # 提交并在 Qt 协程中等待结果
        future = worker.submit(manager.query(...))
        result = await asyncio.wrap_future(future)

        # 关闭
        worker.stop()
    """

    def __init__(self):
        super().__init__(daemon=True, name="RAGWorker")
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()

    # ============================================================
    # 线程生命周期
    # ============================================================

    def run(self) -> None:
        """线程入口：创建并运行专用 asyncio 事件循环"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        logger.info("RAGWorkerThread: dedicated event loop started")
        try:
            self._loop.run_forever()
        finally:
            # 取消所有未完成任务后关闭循环
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            self._loop.close()
            logger.info("RAGWorkerThread: event loop closed")

    def start_and_wait(self, timeout: float = 5.0) -> bool:
        """
        启动线程并等待事件循环就绪

        Returns:
            True 表示启动成功，False 表示超时
        """
        self.start()
        ready = self._ready.wait(timeout=timeout)
        if ready:
            logger.info("RAGWorkerThread ready")
        else:
            logger.error("RAGWorkerThread failed to start within timeout")
        return ready

    def stop(self) -> None:
        """安全停止工作线程（等待最多 10 秒）"""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self.join(timeout=10.0)
            logger.info("RAGWorkerThread stopped")

    # ============================================================
    # 任务提交
    # ============================================================

    @property
    def is_running(self) -> bool:
        """工作线程是否正在运行"""
        return (
            self._loop is not None
            and self._loop.is_running()
            and self.is_alive()
        )

    def submit(self, coro: Coroutine) -> Optional[Future]:
        """
        从任意线程提交协程到工作线程的事件循环（非阻塞）

        Args:
            coro: 要执行的协程

        Returns:
            concurrent.futures.Future，可用于检查结果/异常；
            工作线程未就绪时返回 None
        """
        if not self.is_running:
            logger.error("RAGWorkerThread not running, cannot submit coroutine")
            return None
        return asyncio.run_coroutine_threadsafe(coro, self._loop)


# ============================================================
# 模块导出
# ============================================================

__all__ = ["RAGWorkerThread"]
