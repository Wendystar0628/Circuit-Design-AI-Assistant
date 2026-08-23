from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from PyQt6.QtCore import QObject, pyqtSignal

class MetricTargetStorageError(RuntimeError):
    """Raised when metric targets cannot be loaded or committed safely."""


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
        self._storage_error = ""
        self._storage_error_root = ""
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
        project_root = self._get_project_root()
        key = self._resolve_relative_key(source_file_path, project_root)
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
        project_root = self._get_project_root()
        key = self._resolve_relative_key(source_file_path, project_root)
        if not key:
            raise ValueError(
                "Metric targets can only be written for a file inside the "
                "currently open project"
            )
        cleaned: Dict[str, str] = {}
        if isinstance(targets, dict):
            for raw_name, raw_value in targets.items():
                name = str(raw_name or "").strip()
                value = str(raw_value or "").strip()
                if name and value:
                    cleaned[name] = value
        with self._lock:
            self._require_current_project(project_root)
            if self._storage_error_root == self._normalize_root(project_root):
                raise MetricTargetStorageError(self._storage_error)

            candidate = {
                relative_path: dict(values)
                for relative_path, values in self._targets.items()
            }
            if cleaned:
                candidate[key] = cleaned
            else:
                candidate.pop(key, None)

            # Disk is authoritative.  Do not publish an in-memory state that
            # failed to persist, and never re-resolve the project root during
            # the write (that used to allow an A request to land in B).
            self._save_storage_locked(project_root, candidate)
            self._require_current_project(project_root)
            self._targets = candidate
        return self._emit_state_changed()

    def reload_from_storage(self, *, emit_signal: bool = True) -> Dict[str, Any]:
        with self._lock:
            self._targets = {}
            self._storage_error = ""
            self._storage_error_root = ""
            project_root = self._get_project_root()
            if project_root:
                try:
                    payload = self._load_storage_payload(project_root)
                    self._targets = self._parse_storage_payload(payload)
                except MetricTargetStorageError as exc:
                    # Keep the damaged file untouched and make every later
                    # write fail closed until a successful reload occurs.
                    self._storage_error = str(exc)
                    self._storage_error_root = self._normalize_root(project_root)
                    if self.logger:
                        self.logger.error(self._storage_error)
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
            self._storage_error = ""
            self._storage_error_root = ""
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
            "storage_error": self._storage_error,
        }

    def _save_storage_locked(
        self,
        project_root: str,
        targets_by_file: Dict[str, Dict[str, str]],
    ) -> None:
        self._require_current_project(project_root)
        storage_path = self._get_storage_path(project_root)
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._assert_storage_path_safe(storage_path)
        payload = {
            "files": [
                {
                    "relative_path": relative_path,
                    "targets": dict(targets),
                }
                for relative_path, targets in sorted(targets_by_file.items())
            ]
        }
        serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{storage_path.name}.",
                suffix=".tmp",
                dir=storage_path.parent,
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            self._require_current_project(project_root)
            os.replace(temp_path, storage_path)
            temp_path = None
        except Exception as exc:
            raise MetricTargetStorageError(
                f"Failed to persist metric targets at {storage_path}: {exc}"
            ) from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _load_storage_payload(self, project_root: str) -> Dict[str, Any]:
        storage_path = self._get_storage_path(project_root)
        if not storage_path.is_file():
            return {"files": []}
        try:
            payload = json.loads(storage_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise MetricTargetStorageError(
                f"Metric target file is unreadable and was left untouched: "
                f"{storage_path}: {exc}"
            ) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
            raise MetricTargetStorageError(
                f"Metric target file has an invalid schema and was left "
                f"untouched: {storage_path}"
            )
        return payload

    def _parse_storage_payload(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Dict[str, str]]:
        parsed: Dict[str, Dict[str, str]] = {}
        for index, item in enumerate(payload["files"]):
            if not isinstance(item, dict):
                raise MetricTargetStorageError(
                    f"Metric target entry {index} is not an object"
                )
            relative_path = str(item.get("relative_path", "") or "").strip()
            raw_targets = item.get("targets")
            if (
                not relative_path
                or Path(relative_path).is_absolute()
                or ".." in Path(relative_path).parts
                or not isinstance(raw_targets, dict)
            ):
                raise MetricTargetStorageError(
                    f"Metric target entry {index} has an invalid path or targets"
                )
            cleaned: Dict[str, str] = {}
            for raw_name, raw_value in raw_targets.items():
                if not isinstance(raw_name, str) or not isinstance(raw_value, str):
                    raise MetricTargetStorageError(
                        f"Metric target entry {index} contains a non-string value"
                    )
                name = raw_name.strip()
                value = raw_value.strip()
                if name and value:
                    cleaned[name] = value
            if cleaned:
                parsed[Path(relative_path).as_posix()] = cleaned
        return parsed

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

    def _resolve_relative_key(
        self,
        source_file_path: str,
        project_root: str,
    ) -> str:
        raw = str(source_file_path or "").strip()
        if not raw or not project_root:
            return ""
        root_obj = Path(project_root).resolve()
        raw_path = Path(raw).expanduser()
        abs_obj = (
            raw_path.resolve()
            if raw_path.is_absolute()
            else (root_obj / raw_path).resolve()
        )
        try:
            relative = abs_obj.relative_to(root_obj).as_posix()
        except Exception:
            return ""
        return relative

    def _require_current_project(self, expected_root: str) -> None:
        current = self._normalize_root(self._get_project_root())
        expected = self._normalize_root(expected_root)
        if not expected or current != expected:
            raise MetricTargetStorageError(
                "The active project changed while metric targets were being saved"
            )

    @staticmethod
    def _normalize_root(project_root: str) -> str:
        raw = str(project_root or "").strip()
        if not raw:
            return ""
        return os.path.normcase(str(Path(raw).resolve()))

    @staticmethod
    def _assert_storage_path_safe(storage_path: Path) -> None:
        for candidate in (storage_path.parent, storage_path):
            if not candidate.exists():
                continue
            is_junction = getattr(candidate, "is_junction", lambda: False)
            if candidate.is_symlink() or is_junction():
                raise MetricTargetStorageError(
                    f"Refusing to access metric targets through a link: {candidate}"
                )


__all__ = ["MetricTargetService", "MetricTargetStorageError"]
