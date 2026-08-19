"""Project and RAG lifecycle projection into :mod:`application.session_state`."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from application.session_state import (
    SESSION_PROJECT_ROOT,
    SESSION_RAG_INDEXING,
    SESSION_RAG_INDEX_STATUS,
    SessionState,
)
from shared.event_types import (
    EVENT_RAG_INDEX_COMPLETE,
    EVENT_RAG_INDEX_ERROR,
    EVENT_RAG_INDEX_PROGRESS,
    EVENT_RAG_INDEX_STARTED,
)


class SessionStateProjector:
    """Keep the UI read model aligned with ProjectService and RAGManager."""

    def __init__(self, session_state: SessionState, event_bus=None) -> None:
        self._session_state = session_state
        self._event_bus = event_bus
        self._rag_subscribed = False
        self._logger = logging.getLogger(__name__)

    def update_project_state(self, project_root: str) -> None:
        """Project the newly opened project's resolved root."""
        self._session_state._internal_update(
            {
                SESSION_PROJECT_ROOT: project_root,
                SESSION_RAG_INDEXING: False,
                SESSION_RAG_INDEX_STATUS: {},
            }
        )

    def clear_project_state(self) -> None:
        """Remove all project-scoped values after a successful close."""
        self._session_state._internal_reset()

    def subscribe_rag_events(self) -> bool:
        """Subscribe once to the four RAG lifecycle events."""
        if self._rag_subscribed:
            return True
        if self._event_bus is None:
            return False

        subscriptions = self._rag_subscriptions()
        subscribed = []
        try:
            for event_type, handler in subscriptions:
                self._event_bus.subscribe(event_type, handler)
                subscribed.append((event_type, handler))
        except Exception:
            for event_type, handler in reversed(subscribed):
                try:
                    self._event_bus.unsubscribe(event_type, handler)
                except Exception:
                    pass
            self._logger.exception("Failed to subscribe SessionState RAG projection")
            return False

        self._rag_subscribed = True
        return True

    def shutdown(self) -> None:
        """Symmetrically detach RAG subscriptions during application shutdown."""
        if not self._rag_subscribed or self._event_bus is None:
            self._rag_subscribed = False
            return

        for event_type, handler in self._rag_subscriptions():
            try:
                self._event_bus.unsubscribe(event_type, handler)
            except Exception:
                self._logger.exception(
                    "Failed to unsubscribe SessionState projection from %s",
                    event_type,
                )
        self._rag_subscribed = False

    def _rag_subscriptions(self):
        return (
            (EVENT_RAG_INDEX_STARTED, self._on_rag_index_started),
            (EVENT_RAG_INDEX_PROGRESS, self._on_rag_index_progress),
            (EVENT_RAG_INDEX_COMPLETE, self._on_rag_index_complete),
            (EVENT_RAG_INDEX_ERROR, self._on_rag_index_error),
        )

    @staticmethod
    def _event_data(event: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(event, dict):
            return None
        data = event.get("data", event)
        return data if isinstance(data, dict) else None

    @staticmethod
    def _normalize_root(path: Any) -> str:
        if not path:
            return ""
        return os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(path))))

    def _is_current_project_event(self, data: Dict[str, Any]) -> bool:
        """Reject a late RAG event carrying another project's identity."""
        event_root = data.get("project_root")
        current_root = self._session_state.project_root
        return bool(event_root and current_root) and self._normalize_root(
            event_root
        ) == self._normalize_root(current_root)

    def _on_rag_index_started(self, event: Any) -> None:
        data = self._event_data(event)
        if data is None or not self._is_current_project_event(data):
            return
        self._session_state._internal_update(
            {
                SESSION_RAG_INDEXING: True,
                SESSION_RAG_INDEX_STATUS: {
                    "status": "indexing",
                    "total_files": data.get("total_files", 0),
                    "processed": 0,
                    "track_id": data.get("track_id", ""),
                },
            }
        )

    def _on_rag_index_progress(self, event: Any) -> None:
        data = self._event_data(event)
        if data is None or not self._is_current_project_event(data):
            return
        self._session_state._internal_update(
            {
                SESSION_RAG_INDEXING: True,
                SESSION_RAG_INDEX_STATUS: {
                    "status": "indexing",
                    "total_files": data.get("total", 0),
                    "processed": data.get("processed", 0),
                    "current_file": data.get("current_file", ""),
                    "track_id": data.get("track_id", ""),
                },
            }
        )

    def _on_rag_index_complete(self, event: Any) -> None:
        data = self._event_data(event)
        if data is None or not self._is_current_project_event(data):
            return
        self._session_state._internal_update(
            {
                SESSION_RAG_INDEXING: False,
                SESSION_RAG_INDEX_STATUS: {
                    "status": "complete",
                    "total_indexed": data.get("total_indexed", 0),
                    "failed": data.get("failed", 0),
                    "duration_s": data.get("duration_s", 0),
                },
            }
        )

    def _on_rag_index_error(self, event: Any) -> None:
        data = self._event_data(event)
        if data is None or not self._is_current_project_event(data):
            return
        self._session_state._internal_update(
            {
                SESSION_RAG_INDEXING: False,
                SESSION_RAG_INDEX_STATUS: {
                    "status": "error",
                    "error": data.get("error", ""),
                    "file_path": data.get("file_path", ""),
                },
            }
        )


__all__ = ["SessionStateProjector"]
