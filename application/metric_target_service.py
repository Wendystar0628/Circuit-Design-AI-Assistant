from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from shared.path_utils import normalize_absolute_path


class MetricTargetService(QObject):
    """Per-circuit-file metric-target store.

    Each SPICE source file produces a set of ``.MEASURE`` metrics. The
    user may attach a textual target (e.g. ``"\u2265 20 dB"``) to each
    metric; this service is the **only** place those target strings
    live between sessions. It persists to
    ``<project_root>/.circuit_ai/metric_targets.json`` and is keyed by
    the POSIX-style project-relative path of the circuit source file.

    Design rules:
    - ``set_targets_for_file`` is the sole write entry. The frontend's
      "\u786e\u8ba4\u4fee\u6539" button flushes the whole metric table at once
      through this method, so the service never merges partial updates;
      the caller owns the full target map for that file.
    - Empty target strings are not persisted. Passing an empty string
      clears that particular metric's target.
    - Targets outside the current project root (e.g. scratch files)
      are silently dropped; there is no per-file sidecar fallback.
    - The service reloads when ``EVENT_STATE_PROJECT_OPENED`` /
      ``EVENT_STATE_PROJECT_CLOSED`` fire, mirroring
      ``PendingWorkspaceEditService``'s life-cycle.
    """

    state_changed = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self._targets: Dict[str, Dict[str, str]] = {}
        self._event_bus = None
        self._session_state_manager = None
        self._logger = None
        self._subscribed = False
        self._lock = threading.RLock()
        self._subscribe_events()
        self.reload_from_storage(emit_signal=False)

    # ------------------------------------------------------------------
    # Service-locator wired dependencies (lazy).
    # ------------------------------------------------------------------

    @property
    def event_bus(self):
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS

                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus

    @property
    def session_state_manager(self):
        if self._session_state_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE_MANAGER

                self._session_state_manager = ServiceLocator.get_optional(SVC_SESSION_STATE_MANAGER)
            except Exception:
                pass
        return self._session_state_manager

    @property
    def logger(self):
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger

                self._logger = get_logger("metric_target_service")
            except Exception:
                pass
        return self._logger

    # ------------------------------------------------------------------
    # Public API.
    # ------------------------------------------------------------------

    def get_targets_for_file(self, source_file_path: str) -> Dict[str, str]:
        """Return the metric -> target-string map for one circuit source
        file. Returns an empty dict if no targets have been recorded.
        The returned dict is a defensive copy.
        """
        key = self._resolve_relative_key(source_file_path)
        if not key:
            return {}
        with self._lock:
            bucket = self._targets.get(key) or {}
            return dict(bucket)

    def set_targets_for_file(
        self,
        source_file_path: str,
        targets: Dict[str, str],
    ) -> Dict[str, Any]:
        """Replace the target map for ``source_file_path`` in full.

        Empty-string values are dropped. If the resulting map is empty
        the file's bucket is removed outright so the stored JSON stays
        minimal and no ghost buckets remain for files that no longer
        have any targets.
        """
        key = self._resolve_relative_key(source_file_path)
        if not key:
            return self.get_state()
        cleaned: Dict[str, str] = {}
        if isinstance(targets, dict):
            for raw_name, raw_value in targets.items():
                name = str(raw_name or "").strip()
                value = str(raw_value or "").strip()
                if name and value:
                    cleaned[name] = value
        with self._lock:
            if cleaned:
                self._targets[key] = cleaned
            else:
                self._targets.pop(key, None)
            self._save_storage_locked()
        return self._emit_state_changed()

    def reload_from_storage(self, *, emit_signal: bool = True) -> Dict[str, Any]:
        with self._lock:
            self._targets = {}
            project_root = self._get_project_root()
            if project_root:
                payload = self._load_storage_payload(project_root)
                for item in payload.get("files", []):
                    if not isinstance(item, dict):
                        continue
                    relative_path = str(item.get("relative_path", "") or "").strip()
                    if not relative_path:
                        continue
                    raw_targets = item.get("targets")
                    if not isinstance(raw_targets, dict):
                        continue
                    cleaned: Dict[str, str] = {}
                    for raw_name, raw_value in raw_targets.items():
                        name = str(raw_name or "").strip()
                        value = str(raw_value or "").strip()
                        if name and value:
                            cleaned[name] = value
                    if cleaned:
                        self._targets[relative_path] = cleaned
            state = self._build_state_locked()
        if emit_signal:
            self._emit_signals_for_state(state)
        return state

    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            return self._build_state_locked()

    # ------------------------------------------------------------------
    # Event wiring.
    # ------------------------------------------------------------------

    def _subscribe_events(self) -> None:
        if self._subscribed or self.event_bus is None:
            return
        try:
            from shared.event_types import (
                EVENT_STATE_PROJECT_CLOSED,
                EVENT_STATE_PROJECT_OPENED,
            )

            self.event_bus.subscribe(EVENT_STATE_PROJECT_OPENED, self._on_project_opened)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_CLOSED, self._on_project_closed)
            self._subscribed = True
        except Exception as exc:
            if self.logger:
                self.logger.warning(f"Failed to subscribe metric-target events: {exc}")

    def _on_project_opened(self, event_data: Dict[str, Any]) -> None:
        self.reload_from_storage()

    def _on_project_closed(self, event_data: Dict[str, Any]) -> None:
        with self._lock:
            self._targets = {}
            state = self._build_state_locked()
        self._emit_signals_for_state(state)

    # ------------------------------------------------------------------
    # Internals.
    # ------------------------------------------------------------------

    def _emit_state_changed(self) -> Dict[str, Any]:
        state = self.get_state()
        self._emit_signals_for_state(state)
        return state

    def _emit_signals_for_state(self, state: Dict[str, Any]) -> None:
        self.state_changed.emit(state)

    def _build_state_locked(self) -> Dict[str, Any]:
        files = [
            {
                "relative_path": relative_path,
                "targets": dict(targets),
            }
            for relative_path, targets in sorted(self._targets.items())
        ]
        return {
            "file_count": len(files),
            "files": files,
        }

    def _save_storage_locked(self) -> None:
        project_root = self._get_project_root()
        if not project_root:
            return
        storage_path = self._get_storage_path(project_root)
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "files": [
                {
                    "relative_path": relative_path,
                    "targets": dict(targets),
                }
                for relative_path, targets in sorted(self._targets.items())
            ]
        }
        storage_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_storage_payload(self, project_root: str) -> Dict[str, Any]:
        storage_path = self._get_storage_path(project_root)
        if not storage_path.is_file():
            return {"files": []}
        try:
            payload = json.loads(storage_path.read_text(encoding="utf-8"))
        except Exception:
            return {"files": []}
        return payload if isinstance(payload, dict) else {"files": []}

    def _get_storage_path(self, project_root: str) -> Path:
        return Path(project_root).resolve() / ".circuit_ai" / "metric_targets.json"

    def _get_project_root(self) -> str:
        manager = self.session_state_manager
        if manager is None:
            return ""
        try:
            return str(manager.get_project_root() or "")
        except Exception:
            return ""

    def _resolve_relative_key(self, source_file_path: str) -> str:
        raw = str(source_file_path or "").strip()
        if not raw:
            return ""
        project_root = self._get_project_root()
        if not project_root:
            return ""
        absolute = normalize_absolute_path(raw)
        abs_obj = Path(absolute).resolve()
        root_obj = Path(project_root).resolve()
        try:
            relative = abs_obj.relative_to(root_obj).as_posix()
        except Exception:
            try:
                relative = os.path.relpath(str(abs_obj), str(root_obj)).replace("\\", "/")
            except Exception:
                return ""
        # Files outside the project root (e.g. absolute-path scratch
        # circuits) must not bleed into the project-scoped store.
        if relative.startswith("../") or relative == "..":
            return ""
        return relative


__all__ = ["MetricTargetService"]
