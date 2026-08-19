"""Thread-safe read model for the current project and its RAG index.

``SessionState`` is deliberately small. Conversation messages and session
identity live in ``SessionStateManager``/``ContextManager``; project lifecycle
and RAG are the only application services that project data here for UI
consumers.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional


SESSION_PROJECT_ROOT = "project_root"
SESSION_RAG_INDEXING = "rag_indexing"
SESSION_RAG_INDEX_STATUS = "rag_index_status"


class SessionState:
    """Read-only-to-consumers application state projected by services."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state: Dict[str, Any] = self._default_state()

    @staticmethod
    def _default_state() -> Dict[str, Any]:
        return {
            SESSION_PROJECT_ROOT: None,
            SESSION_RAG_INDEXING: False,
            SESSION_RAG_INDEX_STATUS: {},
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Return one projected value."""
        with self._lock:
            value = self._state.get(key, default)
            return dict(value) if isinstance(value, dict) else value

    def get_all(self) -> Dict[str, Any]:
        """Return an isolated snapshot of the read model."""
        with self._lock:
            snapshot = self._state.copy()
            snapshot[SESSION_RAG_INDEX_STATUS] = dict(
                snapshot[SESSION_RAG_INDEX_STATUS]
            )
            return snapshot

    def _internal_update(self, updates: Dict[str, Any]) -> None:
        """Atomically update known fields from the state projector."""
        with self._lock:
            unknown = updates.keys() - self._state.keys()
            if unknown:
                raise KeyError(f"Unknown SessionState fields: {sorted(unknown)}")
            self._state.update(updates)

    def _internal_reset(self) -> None:
        """Reset the projected project and RAG state."""
        with self._lock:
            self._state = self._default_state()

    @property
    def project_root(self) -> Optional[str]:
        return self.get(SESSION_PROJECT_ROOT)

    @property
    def rag_indexing(self) -> bool:
        return bool(self.get(SESSION_RAG_INDEXING, False))

    @property
    def rag_index_status(self) -> Dict[str, Any]:
        return self.get(SESSION_RAG_INDEX_STATUS, {})


__all__ = [
    "SessionState",
    "SESSION_PROJECT_ROOT",
    "SESSION_RAG_INDEXING",
    "SESSION_RAG_INDEX_STATUS",
]
