# Document Watcher - 文件变更检测
"""
文件变更检测

职责：
- 订阅 EVENT_FILE_CHANGED 事件
- 2 秒防抖，批量处理累积变更
- 仅处理符合扫描规则的扩展名

架构位置：
- 被 Application 层 bootstrap 创建
- 依赖 RAGManager（增量索引）
- 依赖 EventBus（事件订阅）
"""

import asyncio
import logging
import os
from typing import Dict, Optional, Tuple

from shared.event_types import EVENT_FILE_CHANGED
from shared.file_change import FileChange, extract_file_change


logger = logging.getLogger(__name__)

# 防抖间隔（秒）
DEBOUNCE_SECONDS = 2.0


class DocumentWatcher:
    """
    文件变更检测器

    监听文件变更事件，防抖后触发 RAGManager 单文件增量索引。
    """

    def __init__(self, event_bus=None, rag_manager=None, file_manager=None):
        self._event_bus = event_bus
        self._rag_manager = rag_manager
        self._file_manager = file_manager
        self._pending_changes: Dict[
            Tuple[str, str, str], Tuple[FileChange, int]
        ] = {}
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

        self._pending_changes.clear()
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

        change = extract_file_change(event_data)
        if change is None:
            return

        normalized = str(change.path).replace("\\", "/")
        if normalized.endswith("/.circuit_ai/pending_workspace_edits.json"):
            return

        if not self._belongs_to_current_project(change, manager.project_root):
            return
        if not self._matches_file_generation(change):
            return

        # Keep the newest form of the same operation and capture the RAG
        # generation now; a project switch during debounce invalidates it.
        key = (change.operation, change.path, change.dest_path)
        self._pending_changes[key] = (change, int(manager.generation))

        # 重置防抖定时器
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()

        try:
            loop = asyncio.get_running_loop()
            self._debounce_task = loop.create_task(self._debounced_process())
        except RuntimeError:
            # Tests and non-Qt callers may emit without an asyncio loop.
            self._process_pending_changes()

    async def _debounced_process(self) -> None:
        """防抖处理：等待 DEBOUNCE_SECONDS 后触发工作线程索引

        asyncio.sleep 在 Qt 主线程协作执行（无 CPU 耗时），安全。
        实际索引工作通过 trigger_index_single_file 提交到 RAGWorkerThread，
        不阻塞 Qt 主线程。
        """
        await asyncio.sleep(DEBOUNCE_SECONDS)

        self._process_pending_changes()

    def _process_pending_changes(self) -> None:
        if not self._pending_changes:
            return

        changes = list(self._pending_changes.values())
        self._pending_changes.clear()

        manager = self.rag_manager
        if not manager or not manager.is_available:
            return

        logger.debug(f"Applying {len(changes)} changed files to RAG")

        for change, rag_generation in changes:
            if rag_generation != int(manager.generation):
                continue
            if not self._matches_file_generation(change):
                continue
            if not self._belongs_to_current_project(change, manager.project_root):
                continue

            if change.operation == "delete":
                manager.trigger_delete_file(
                    change.path, is_directory=change.is_directory
                )
            elif change.operation == "move":
                manager.trigger_move_file(
                    change.path,
                    change.dest_path,
                    is_directory=change.is_directory,
                )
            else:
                manager.trigger_index_single_file(change.path)

    @staticmethod
    def _belongs_to_current_project(
        change: FileChange,
        project_root: Optional[str],
    ) -> bool:
        if not project_root:
            return False
        root = os.path.normcase(os.path.abspath(project_root))
        return os.path.normcase(os.path.abspath(change.project_root)) == root

    def _matches_file_generation(self, change: FileChange) -> bool:
        """Compare producer identity to FileManager, never RAG generation.

        RAG generation also changes for an embedding-model rebuild while the
        FileManager project generation correctly remains stable.
        """
        if self._file_manager is None:
            return False
        try:
            current = int(self._file_manager.project_generation)
        except (AttributeError, TypeError, ValueError):
            return False
        return change.generation == current


# ============================================================
# 模块导出
# ============================================================

__all__ = ["DocumentWatcher"]
