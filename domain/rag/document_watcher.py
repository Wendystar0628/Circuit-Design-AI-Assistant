# Document Watcher - 文件变更检测
"""
文件变更检测

职责：
- 订阅 EVENT_FILE_CHANGED 事件
- 2 秒防抖，批量处理累积变更
- 仅在 RAG 模式开启时响应
- 仅处理符合扫描规则的扩展名

架构位置：
- 被 Application 层 bootstrap 创建
- 依赖 RAGManager（增量索引）
- 依赖 EventBus（事件订阅）
"""

import asyncio
import logging
from typing import Optional, Set

from shared.event_types import EVENT_FILE_CHANGED


logger = logging.getLogger(__name__)

# 防抖间隔（秒）
DEBOUNCE_SECONDS = 2.0


class DocumentWatcher:
    """
    文件变更检测器

    监听文件变更事件，防抖后触发 RAGManager 单文件增量索引。
    """

    def __init__(self, event_bus=None, rag_manager=None):
        self._event_bus = event_bus
        self._rag_manager = rag_manager
        self._pending_files: Set[str] = set()
        self._debounce_task: Optional[asyncio.Task] = None
        self._subscribed = False

    def start(self) -> None:
        """开始监听文件变更事件"""
        if self._subscribed:
            return

        if self._event_bus is None:
            return

        try:
            self._event_bus.subscribe(
                EVENT_FILE_CHANGED,
                self._on_file_modified,
            )
            self._subscribed = True
            logger.info("DocumentWatcher started")
        except Exception as e:
            logger.warning(f"Failed to start DocumentWatcher: {e}")

    def stop(self) -> None:
        """停止监听"""
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()

        self._pending_files.clear()
        if self._subscribed and self._event_bus is not None:
            try:
                self._event_bus.unsubscribe(
                    EVENT_FILE_CHANGED,
                    self._on_file_modified,
                )
            except Exception:
                pass
        self._subscribed = False
        logger.info("DocumentWatcher stopped")

    @property
    def rag_manager(self):
        return self._rag_manager

    # ============================================================
    # 事件处理
    # ============================================================

    def _on_file_modified(self, event_data) -> None:
        """
        文件变更事件回调

        Args:
            event_data: EventBus 包装的事件数据 {"type":.., "data":{..}, ...}
        """
        manager = self.rag_manager
        if not manager or not manager.is_available:
            return

        # 解包 EventBus 包装层
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data

        # 提取文件路径
        file_path = None
        if isinstance(data, dict):
            file_path = data.get("file_path") or data.get("path")
        elif isinstance(data, str):
            file_path = data

        if not file_path:
            return

        normalized = str(file_path).replace("\\", "/")
        if normalized.endswith("/.circuit_ai/pending_workspace_edits.json"):
            return

        # 加入待处理集合
        self._pending_files.add(file_path)

        # 重置防抖定时器
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()

        try:
            loop = asyncio.get_running_loop()
            self._debounce_task = loop.create_task(self._debounced_process())
        except RuntimeError:
            # 没有运行中的事件循环，直接跳过
            pass

    async def _debounced_process(self) -> None:
        """防抖处理：等待 DEBOUNCE_SECONDS 后触发工作线程索引

        asyncio.sleep 在 Qt 主线程协作执行（无 CPU 耗时），安全。
        实际索引工作通过 trigger_index_single_file 提交到 RAGWorkerThread，
        不阻塞 Qt 主线程。
        """
        await asyncio.sleep(DEBOUNCE_SECONDS)

        if not self._pending_files:
            return

        files = list(self._pending_files)
        self._pending_files.clear()

        manager = self.rag_manager
        if not manager or not manager.is_available:
            return

        logger.debug(f"Triggering re-index for {len(files)} changed files")

        for file_path in files:
            manager.trigger_index_single_file(file_path)


# ============================================================
# 模块导出
# ============================================================

__all__ = ["DocumentWatcher"]
