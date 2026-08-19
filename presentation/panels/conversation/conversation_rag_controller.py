from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict


@dataclass(frozen=True)
class _RagOperationIdentity:
    """Identity captured before a destructive RAG confirmation is shown."""

    manager: Any
    generation: int
    project_root: str
    request_id: str


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
        self._search_task: asyncio.Task | None = None
        self._clear_task: asyncio.Task | None = None
        self._pending_clear_identity: _RagOperationIdentity | None = None

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
        if self._search_task is not None and not self._search_task.done():
            self._search_task.cancel()
        self._search_task = None
        if self._clear_task is not None and not self._clear_task.done():
            self._clear_task.cancel()
        self._clear_task = None
        self._pending_clear_identity = None
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
            root = os.path.abspath(str(manager.project_root))
            candidate = os.path.abspath(
                os.path.join(root, relative_path.replace("/", os.sep))
            )
            if os.path.commonpath([root, candidate]) != root:
                return ""
            return candidate
        except (OSError, ValueError):
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
        if progress_state.get("is_visible", False):
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
        if getattr(manager, "index_error", None):
            return {
                "phase": "error",
                "label": self._get_text("rag.status.index_error", "索引失败"),
                "tone": "error",
            }
        if getattr(manager, "is_indexing", False):
            return {
                "phase": "indexing",
                "label": self._get_text("rag.status.indexing", "索引中..."),
                "tone": "info",
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
        if not self._event_is_current(data):
            return
        if isinstance(data, dict) and data.get("status") == "error":
            self._set_info(str(data.get("error", "") or ""), tone="error")
        elif isinstance(data, dict) and data.get("status") == "ready":
            self._set_info("", tone="neutral")
        self._notify_state_changed()

    def handle_index_started(self, event_data: Dict[str, Any]) -> None:
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        if not self._event_is_current(data):
            return
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
        if not self._event_is_current(data):
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
        if not self._event_is_current(data):
            return
        self._progress_state = self._create_progress_state()
        if isinstance(data, dict):
            total = max(0, int(data.get("total_indexed", 0) or 0))
            failed = max(0, int(data.get("failed", 0) or 0))
            duration = float(data.get("duration_s", 0.0) or 0.0)
            if data.get("already_up_to_date"):
                self._set_info("索引已是最新", tone="neutral")
            elif failed > 0:
                self._set_info(
                    f"索引完成：{total} 成功，{failed} 失败，耗时 {duration:.1f}s",
                    tone="error",
                )
            else:
                self._set_info(f"索引完成：{total} 文件，耗时 {duration:.1f}s", tone="success")
        self._notify_state_changed()

    def handle_index_error(self, event_data: Dict[str, Any]) -> None:
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        if not self._event_is_current(data):
            return
        if isinstance(data, dict):
            error = str(data.get("error", "") or "")
            file_path = str(data.get("file_path", "") or "")
            phase = str(data.get("phase", "") or "")
            fatal = bool(data.get("fatal")) or (
                not file_path
                and phase in {"project_index", "auto_index", "scan"}
            )
            if fatal:
                self._progress_state = self._create_progress_state()
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
        identity = self._capture_operation_identity(manager)
        if identity is None:
            return
        self._pending_clear_identity = identity
        self._on_confirm_requested(
            kind="rag_clear",
            title=self._get_text("dialog.warning.title", "警告"),
            message="确定要清空当前项目的索引库吗？\n已索引的内容将被全部删除。",
            confirm_label=self._get_text("btn.delete", "删除"),
            cancel_label=self._get_text("btn.cancel", "取消"),
            tone="danger",
            payload={"request_id": identity.request_id},
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
        if self._search_task is not None and not self._search_task.done():
            self._search_task.cancel()
        generation = int(getattr(manager, "generation", 0) or 0)
        self._search_task = asyncio.create_task(
            self._async_search(normalized_query, manager, generation)
        )

    async def _async_search(
        self,
        query: str,
        manager: Any | None = None,
        generation: int | None = None,
    ) -> None:
        manager = manager or self.rag_manager
        if manager is None:
            self._search_state = {
                "is_running": False,
                "result_text": "索引库未就绪（请等待初始化完成）",
            }
            self._notify_state_changed()
            return
        try:
            result = await manager.query_async(query)
            if (
                self.rag_manager is not manager
                or int(getattr(manager, "generation", 0) or 0)
                != int(generation if generation is not None else getattr(manager, "generation", 0) or 0)
            ):
                self._finish_stale_search()
                return
            if result.is_empty:
                result_text = f'未找到与 "{query}" 相关的内容'
            else:
                result_text = f"片段: {result.chunks_count}\n\n{result.format_as_context(max_tokens=3000)}"
            self._search_state = {
                "is_running": False,
                "result_text": result_text,
            }
        except asyncio.CancelledError:
            return
        except Exception as exc:
            if (
                self.rag_manager is not manager
                or int(getattr(manager, "generation", 0) or 0)
                != int(generation if generation is not None else getattr(manager, "generation", 0) or 0)
            ):
                self._finish_stale_search()
                return
            self._search_state = {
                "is_running": False,
                "result_text": f"检索失败: {exc}",
            }
        self._notify_state_changed()

    def _finish_stale_search(self) -> None:
        current = asyncio.current_task()
        if self._search_task not in (None, current):
            return
        self._search_state = self._create_search_state()
        self._set_info("项目或索引配置已变化，请重新检索", tone="neutral")
        self._notify_state_changed()

    def _event_is_current(self, data: Any) -> bool:
        if not isinstance(data, dict):
            return True
        manager = self.rag_manager
        if manager is None:
            return False
        event_generation = data.get("generation")
        if event_generation not in (None, ""):
            try:
                if int(event_generation) != int(getattr(manager, "generation", 0) or 0):
                    return False
            except (TypeError, ValueError):
                return False
        event_root = str(data.get("project_root", "") or "")
        manager_root = str(getattr(manager, "project_root", "") or "")
        if event_root and manager_root:
            try:
                if os.path.normcase(os.path.abspath(event_root)) != os.path.normcase(os.path.abspath(manager_root)):
                    return False
            except (OSError, ValueError):
                return False
        return True

    async def clear_index(
        self,
        identity: _RagOperationIdentity | None = None,
    ) -> None:
        identity = identity or self._capture_operation_identity(self.rag_manager)
        if identity is None or not self._operation_identity_is_current(identity):
            return
        current_task = asyncio.current_task()
        try:
            await identity.manager.clear_index_async(
                expected_generation=identity.generation,
                expected_project_root=identity.project_root,
            )
            if not self._operation_identity_is_current(identity):
                return
            self._search_state = self._create_search_state()
            self._set_info("索引库已清空", tone="success")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._operation_identity_is_current(identity):
                return
            self._set_info(f"清空失败: {exc}", tone="error")
        finally:
            if self._clear_task is current_task:
                self._clear_task = None
        if self._operation_identity_is_current(identity):
            self._notify_state_changed()

    def handle_confirm_acceptance(
        self,
        kind: str,
        payload: Dict[str, Any] | None = None,
    ) -> bool:
        if str(kind or "") != "rag_clear":
            return False
        identity = self._pending_clear_identity
        self._pending_clear_identity = None
        request_id = str((payload or {}).get("request_id", "") or "")
        if (
            identity is None
            or request_id != identity.request_id
            or not self._operation_identity_is_current(identity)
        ):
            # The confirmation belonged to a project/index generation which is
            # no longer current.  Consume it without mutating the new project.
            return True
        if self._clear_task is not None and not self._clear_task.done():
            return True
        self._clear_task = asyncio.create_task(self.clear_index(identity))
        return True

    def _capture_operation_identity(
        self,
        manager: Any | None,
    ) -> _RagOperationIdentity | None:
        if manager is None:
            return None
        project_root = self._normalize_project_root(
            str(getattr(manager, "project_root", "") or "")
        )
        if not project_root:
            return None
        try:
            generation = int(getattr(manager, "generation", 0) or 0)
        except (TypeError, ValueError):
            return None
        return _RagOperationIdentity(
            manager=manager,
            generation=generation,
            project_root=project_root,
            request_id=uuid.uuid4().hex,
        )

    def _operation_identity_is_current(
        self,
        identity: _RagOperationIdentity,
    ) -> bool:
        manager = self.rag_manager
        if manager is not identity.manager:
            return False
        try:
            generation = int(getattr(manager, "generation", 0) or 0)
        except (TypeError, ValueError):
            return False
        return (
            generation == identity.generation
            and self._normalize_project_root(
                str(getattr(manager, "project_root", "") or "")
            )
            == identity.project_root
        )

    @staticmethod
    def _normalize_project_root(project_root: str) -> str:
        if not project_root:
            return ""
        try:
            return os.path.normcase(
                os.path.realpath(os.path.abspath(project_root))
            )
        except (OSError, ValueError):
            return ""


__all__ = ["ConversationRagController"]
