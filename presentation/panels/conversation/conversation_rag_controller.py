from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Callable, Dict


class ConversationRagController:
    def __init__(
        self,
        *,
        rag_manager_getter: Callable[[], Any],
        get_text: Callable[[str, str], str],
        on_state_changed: Callable[[], None],
        on_confirm_requested: Callable[..., None],
        logger_getter: Callable[[], Any],
    ) -> None:
        self._rag_manager_getter = rag_manager_getter
        self._get_text = get_text
        self._on_state_changed = on_state_changed
        self._on_confirm_requested = on_confirm_requested
        self._logger_getter = logger_getter
        self._progress_state = self._create_progress_state()
        self._info_state = self._create_info_state()
        self._search_state = self._create_search_state()

    @property
    def logger(self):
        try:
            return self._logger_getter()
        except Exception:
            return None

    @property
    def rag_manager(self):
        try:
            return self._rag_manager_getter()
        except Exception:
            return None

    def _notify_state_changed(self) -> None:
        self._on_state_changed()

    def _create_progress_state(self) -> Dict[str, Any]:
        return {
            "is_visible": False,
            "processed": 0,
            "total": 0,
            "current_file": "",
        }

    def _create_info_state(self) -> Dict[str, Any]:
        return {
            "message": "",
            "tone": "neutral",
        }

    def _create_search_state(self) -> Dict[str, Any]:
        return {
            "is_running": False,
            "result_text": "",
        }

    def reset_runtime_state(self, *, clear_search: bool = True) -> None:
        self._progress_state = self._create_progress_state()
        self._info_state = self._create_info_state()
        if clear_search:
            self._search_state = self._create_search_state()

    def _set_info(self, message: str = "", tone: str = "neutral") -> None:
        self._info_state = {
            "message": str(message or ""),
            "tone": str(tone or "neutral"),
        }

    def _resolve_file_path(self, relative_path: str) -> str:
        manager = self.rag_manager
        if manager is None or not manager.project_root or not relative_path:
            return ""
        try:
            return str((Path(manager.project_root) / relative_path.replace("/", os.sep)).resolve())
        except Exception:
            return ""

    def _build_status_state(self, total_files: int) -> Dict[str, Any]:
        manager = self.rag_manager
        progress_state = self._progress_state
        if manager is None or not manager.project_root:
            return {
                "phase": "idle",
                "label": self._get_text("rag.status.await_project", "等待项目"),
                "tone": "neutral",
            }
        if progress_state.get("is_visible", False) or getattr(manager, "is_indexing", False):
            total = max(0, int(progress_state.get("total", 0) or 0))
            processed = max(0, int(progress_state.get("processed", 0) or 0))
            progress_label = (
                f"索引中 {processed}/{total}" if total > 0 else self._get_text("rag.status.indexing", "索引中...")
            )
            return {
                "phase": "indexing",
                "label": progress_label,
                "tone": "info",
            }
        if getattr(manager, "init_error", None):
            return {
                "phase": "error",
                "label": self._get_text("rag.status.init_error", "初始化失败"),
                "tone": "error",
            }
        if getattr(manager, "is_available", False):
            return {
                "phase": "ready",
                "label": f"已就绪 ({total_files} 文件)",
                "tone": "success",
            }
        return {
            "phase": "initializing",
            "label": self._get_text("rag.status.initializing", "初始化中..."),
            "tone": "info",
        }

    def build_frontend_state(self) -> Dict[str, Any]:
        manager = self.rag_manager
        status = None
        if manager is not None:
            try:
                status = manager.get_index_status()
            except Exception as exc:
                if self.logger:
                    self.logger.debug(f"Failed to query RAG status: {exc}")

        stats = getattr(status, "stats", None)
        files = getattr(status, "files", []) if status is not None else []
        total_files = max(0, int(getattr(stats, "total_files", 0) or 0)) if stats is not None else 0

        return {
            "status": self._build_status_state(total_files),
            "stats": {
                "total_files": total_files,
                "processed": max(0, int(getattr(stats, "processed", 0) or 0)) if stats is not None else 0,
                "failed": max(0, int(getattr(stats, "failed", 0) or 0)) if stats is not None else 0,
                "excluded": max(0, int(getattr(stats, "excluded", 0) or 0)) if stats is not None else 0,
                "total_chunks": max(0, int(getattr(stats, "total_chunks", 0) or 0)) if stats is not None else 0,
                "total_entities": max(0, int(getattr(stats, "total_entities", 0) or 0)) if stats is not None else 0,
                "total_relations": max(0, int(getattr(stats, "total_relations", 0) or 0)) if stats is not None else 0,
                "storage_size_mb": max(0.0, float(getattr(stats, "storage_size_mb", 0.0) or 0.0)) if stats is not None else 0.0,
            },
            "progress": dict(self._progress_state),
            "actions": {
                "can_reindex": bool(manager and manager.project_root and manager.is_available and not manager.is_indexing),
                "can_clear": bool(manager and manager.project_root and manager.is_available and not manager.is_indexing),
                "can_search": bool(manager and manager.project_root and manager.is_available and not self._search_state.get("is_running", False)),
                "is_indexing": bool(manager.is_indexing) if manager is not None else False,
            },
            "files": [
                {
                    "path": self._resolve_file_path(str(getattr(file_info, "relative_path", "") or "")),
                    "relative_path": str(getattr(file_info, "relative_path", "") or ""),
                    "status": str(getattr(file_info, "status", "pending") or "pending"),
                    "status_label": {
                        "processed": "已索引",
                        "processing": "索引中",
                        "failed": "失败",
                        "excluded": "排除索引",
                        "pending": "待索引",
                    }.get(str(getattr(file_info, "status", "pending") or "pending"), str(getattr(file_info, "status", "pending") or "pending")),
                    "chunks_count": max(0, int(getattr(file_info, "chunks_count", 0) or 0)),
                    "indexed_at": str(getattr(file_info, "indexed_at", "") or ""),
                    "tooltip": str(getattr(file_info, "exclude_reason", "") or getattr(file_info, "error", "") or ""),
                }
                for file_info in files
            ],
            "search": dict(self._search_state),
            "info": dict(self._info_state),
        }

    def handle_project_opened(self, event_data: Dict[str, Any]) -> None:
        del event_data
        self.reset_runtime_state(clear_search=True)
        self._notify_state_changed()

    def handle_project_closed(self, event_data: Dict[str, Any]) -> None:
        del event_data
        self.reset_runtime_state(clear_search=True)
        self._notify_state_changed()

    def handle_init_complete(self, event_data: Dict[str, Any]) -> None:
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        if isinstance(data, dict) and data.get("status") == "error":
            self._set_info(str(data.get("error", "") or ""), tone="error")
        elif isinstance(data, dict) and data.get("status") == "ready":
            self._set_info("", tone="neutral")
        self._notify_state_changed()

    def handle_index_started(self, event_data: Dict[str, Any]) -> None:
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        total_files = max(0, int(data.get("total_files", 0) or 0)) if isinstance(data, dict) else 0
        self._progress_state = {
            "is_visible": True,
            "processed": 0,
            "total": total_files,
            "current_file": "",
        }
        self._set_info("", tone="neutral")
        self._notify_state_changed()

    def handle_index_progress(self, event_data: Dict[str, Any]) -> None:
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        if not isinstance(data, dict):
            return
        self._progress_state = {
            "is_visible": True,
            "processed": max(0, int(data.get("processed", 0) or 0)),
            "total": max(0, int(data.get("total", 0) or 0)),
            "current_file": str(data.get("current_file", "") or ""),
        }
        self._notify_state_changed()

    def handle_index_complete(self, event_data: Dict[str, Any]) -> None:
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        self._progress_state = self._create_progress_state()
        if isinstance(data, dict):
            total = max(0, int(data.get("total_indexed", 0) or 0))
            failed = max(0, int(data.get("failed", 0) or 0))
            duration = float(data.get("duration_s", 0.0) or 0.0)
            if data.get("already_up_to_date"):
                self._set_info("索引已是最新", tone="neutral")
            elif failed > 0:
                self._set_info(f"索引完成：{total} 成功，{failed} 失败，耗时 {duration:.1f}s", tone="neutral")
            else:
                self._set_info(f"索引完成：{total} 文件，耗时 {duration:.1f}s", tone="success")
        self._notify_state_changed()

    def handle_index_error(self, event_data: Dict[str, Any]) -> None:
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        if isinstance(data, dict):
            error = str(data.get("error", "") or "")
            file_path = str(data.get("file_path", "") or "")
            if file_path:
                self._set_info(f"错误 ({file_path}): {error}", tone="error")
            else:
                self._set_info(f"错误: {error}", tone="error")
            self._notify_state_changed()

    def trigger_reindex(self) -> None:
        manager = self.rag_manager
        if manager is None or not manager.is_available:
            return
        manager.trigger_index()

    def request_clear_index(self) -> None:
        manager = self.rag_manager
        if manager is None or not manager.is_available:
            return
        self._on_confirm_requested(
            kind="rag_clear",
            title=self._get_text("dialog.warning.title", "警告"),
            message="确定要清空当前项目的索引库吗？\n已索引的内容将被全部删除。",
            confirm_label=self._get_text("btn.delete", "删除"),
            cancel_label=self._get_text("btn.cancel", "取消"),
            tone="danger",
        )

    def request_search(self, query: str) -> None:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return
        manager = self.rag_manager
        if manager is None or not manager.is_available:
            self._search_state = {
                "is_running": False,
                "result_text": "索引库未就绪（请等待初始化完成）",
            }
            self._notify_state_changed()
            return
        self._search_state = {
            "is_running": True,
            "result_text": "检索中...",
        }
        self._notify_state_changed()
        asyncio.create_task(self._async_search(normalized_query))

    async def _async_search(self, query: str) -> None:
        manager = self.rag_manager
        if manager is None:
            self._search_state = {
                "is_running": False,
                "result_text": "索引库未就绪（请等待初始化完成）",
            }
            self._notify_state_changed()
            return
        try:
            result = await manager.query_async(query)
            if result.is_empty:
                result_text = f'未找到与 "{query}" 相关的内容'
            else:
                result_text = f"片段: {result.chunks_count}\n\n{result.format_as_context(max_tokens=3000)}"
            self._search_state = {
                "is_running": False,
                "result_text": result_text,
            }
        except Exception as exc:
            self._search_state = {
                "is_running": False,
                "result_text": f"检索失败: {exc}",
            }
        self._notify_state_changed()

    async def clear_index(self) -> None:
        manager = self.rag_manager
        if manager is None:
            return
        try:
            await manager.clear_index_async()
            self._search_state = self._create_search_state()
            self._set_info("索引库已清空", tone="success")
        except Exception as exc:
            self._set_info(f"清空失败: {exc}", tone="error")
        self._notify_state_changed()

    def handle_confirm_acceptance(self, kind: str) -> bool:
        if str(kind or "") != "rag_clear":
            return False
        asyncio.create_task(self.clear_index())
        return True


__all__ = ["ConversationRagController"]
