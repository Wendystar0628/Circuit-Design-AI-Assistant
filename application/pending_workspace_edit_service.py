from __future__ import annotations

import difflib
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from domain.llm.agent.utils.edit_diff import normalize_to_lf
from shared.path_utils import normalize_absolute_path, normalize_identity_path


class PendingWorkspaceEditService(QObject):
    state_changed = pyqtSignal(dict)
    summary_changed = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self._records: Dict[str, Dict[str, Any]] = {}
        self._event_bus = None
        self._file_manager = None
        self._session_state_manager = None
        self._logger = None
        self._subscribed = False
        self._lock = threading.RLock()
        self._subscribe_events()
        self.reload_from_storage(emit_signal=False)

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
    def file_manager(self):
        if self._file_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_FILE_MANAGER

                self._file_manager = ServiceLocator.get_optional(SVC_FILE_MANAGER)
            except Exception:
                pass
        return self._file_manager

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

                self._logger = get_logger("pending_workspace_edit_service")
            except Exception:
                pass
        return self._logger

    def record_agent_edit(
        self,
        path: str,
        new_content: str,
        *,
        tool_name: str = "",
        tool_call_id: str = "",
    ) -> Dict[str, Any]:
        source = {
            "kind": "agent",
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
        }
        return self._record_saved_text(path, new_content, source)

    def record_manual_save(self, path: str, new_content: str) -> Dict[str, Any]:
        source = {"kind": "manual"}
        return self._record_saved_text(path, new_content, source)

    def accept_all_edits(self) -> Dict[str, Any]:
        with self._lock:
            if not self._records:
                return self._build_state_locked()
            self._records.clear()
            self._save_storage_locked()
        return self._emit_state_changed()

    def reject_all_edits(self) -> Dict[str, Any]:
        with self._lock:
            for abs_path in list(self._records.keys()):
                self._reject_file_locked(abs_path)
            self._save_storage_locked()
        return self._emit_state_changed()

    def accept_file_edits(self, path: str) -> Dict[str, Any]:
        abs_path = self._normalize_path(path)
        with self._lock:
            if abs_path in self._records:
                self._records.pop(abs_path, None)
                self._save_storage_locked()
        return self._emit_state_changed()

    def reject_file_edits(self, path: str) -> Dict[str, Any]:
        abs_path = self._normalize_path(path)
        with self._lock:
            self._reject_file_locked(abs_path)
            self._save_storage_locked()
        return self._emit_state_changed()

    def accept_hunk(self, path: str, hunk_id: str) -> Dict[str, Any]:
        abs_path = self._normalize_path(path)
        with self._lock:
            record = self._records.get(abs_path)
            if record is None:
                return self._build_state_locked()
            current_exists = os.path.isfile(abs_path)
            current_content = self._read_disk_text(abs_path) if current_exists else ""
            file_state = self._build_file_state(abs_path, record, current_exists, current_content)
            if file_state is None:
                self._records.pop(abs_path, None)
                self._save_storage_locked()
                return self._build_state_locked()
            target = next((item for item in file_state["hunks"] if item["id"] == hunk_id), None)
            if target is None:
                return self._build_state_locked()
            baseline_lines = self._split_text(record["baseline_content"])
            start = int(target["old_start"])
            end = start + int(target["old_count"])
            baseline_lines[start:end] = list(target["new_lines"])
            record["baseline_content"] = self._join_lines(baseline_lines)
            record["baseline_exists"] = True
            if not self._has_changes(
                record["baseline_exists"],
                record["baseline_content"],
                current_exists,
                current_content,
            ):
                self._records.pop(abs_path, None)
            self._save_storage_locked()
        return self._emit_state_changed()

    def reject_hunk(self, path: str, hunk_id: str) -> Dict[str, Any]:
        abs_path = self._normalize_path(path)
        with self._lock:
            record = self._records.get(abs_path)
            if record is None:
                return self._build_state_locked()
            current_exists = os.path.isfile(abs_path)
            current_content = self._read_disk_text(abs_path) if current_exists else ""
            file_state = self._build_file_state(abs_path, record, current_exists, current_content)
            if file_state is None:
                self._records.pop(abs_path, None)
                self._save_storage_locked()
                return self._build_state_locked()
            target = next((item for item in file_state["hunks"] if item["id"] == hunk_id), None)
            if target is None:
                return self._build_state_locked()
            current_lines = self._split_text(current_content)
            start = int(target["new_start"])
            end = start + int(target["new_count"])
            current_lines[start:end] = list(target["old_lines"])
            updated_content = self._join_lines(current_lines)
            baseline_exists = bool(record["baseline_exists"])
            baseline_content = str(record["baseline_content"] or "")
            if not baseline_exists and updated_content == baseline_content:
                self._delete_file_if_exists(abs_path)
                current_exists = False
                current_content = ""
            else:
                self._write_text(abs_path, updated_content)
                current_exists = True
                current_content = updated_content
            if not self._has_changes(baseline_exists, baseline_content, current_exists, current_content):
                self._records.pop(abs_path, None)
            self._save_storage_locked()
        return self._emit_state_changed()

    def reload_from_storage(self, *, emit_signal: bool = True) -> Dict[str, Any]:
        with self._lock:
            self._records = {}
            project_root = self._get_project_root()
            if project_root:
                payload = self._load_storage_payload(project_root)
                for item in payload.get("files", []):
                    if not isinstance(item, dict):
                        continue
                    relative_path = str(item.get("relative_path", "") or "")
                    if not relative_path:
                        continue
                    display_path = normalize_absolute_path(os.path.join(project_root, relative_path))
                    abs_path = self._normalize_path(display_path)
                    if self._is_internal_path(abs_path, project_root):
                        continue
                    baseline_exists = bool(item.get("baseline_exists", False))
                    baseline_content = str(item.get("baseline_content", "") or "")
                    current_exists = os.path.isfile(abs_path)
                    current_content = self._read_disk_text(abs_path) if current_exists else ""
                    if not self._has_changes(baseline_exists, baseline_content, current_exists, current_content):
                        continue
                    sources = item.get("sources", [])
                    self._records[abs_path] = {
                        "relative_path": relative_path,
                        "display_path": display_path,
                        "baseline_exists": baseline_exists,
                        "baseline_content": baseline_content,
                        "sources": list(sources) if isinstance(sources, list) else [],
                    }
            self._save_storage_locked()
            state = self._build_state_locked()
        if emit_signal:
            self._emit_signals_for_state(state)
        return state

    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            return self._build_state_locked()

    def get_summary_state(self) -> Dict[str, Any]:
        with self._lock:
            return self._build_summary_state(self._build_state_locked())

    def _subscribe_events(self) -> None:
        if self._subscribed or self.event_bus is None:
            return
        try:
            from shared.event_types import (
                EVENT_SESSION_CHANGED,
                EVENT_STATE_PROJECT_CLOSED,
                EVENT_STATE_PROJECT_OPENED,
            )

            self.event_bus.subscribe(EVENT_STATE_PROJECT_OPENED, self._on_project_opened)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_CLOSED, self._on_project_closed)
            self.event_bus.subscribe(EVENT_SESSION_CHANGED, self._on_session_changed)
            self._subscribed = True
        except Exception as exc:
            if self.logger:
                self.logger.warning(f"Failed to subscribe pending edit events: {exc}")

    def _on_project_opened(self, event_data: Dict[str, Any]) -> None:
        self.reload_from_storage()

    def _on_project_closed(self, event_data: Dict[str, Any]) -> None:
        with self._lock:
            self._records = {}
            state = self._build_state_locked()
        self._emit_signals_for_state(state)

    def _on_session_changed(self, event_data: Dict[str, Any]) -> None:
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else {}
        if not isinstance(data, dict):
            return
        if str(data.get("action", "") or "") == "rollback":
            self.reload_from_storage()

    def _record_saved_text(
        self,
        path: str,
        new_content: str,
        source: Dict[str, Any],
    ) -> Dict[str, Any]:
        display_path = normalize_absolute_path(path)
        abs_path = self._normalize_path(display_path)
        project_root = self._get_project_root(display_path)
        if not project_root or self._is_internal_path(abs_path, project_root):
            return self.get_state()
        with self._lock:
            record = self._records.get(abs_path)
            if record is None:
                file_exists = os.path.isfile(abs_path)
                baseline_content = self._read_disk_text(abs_path) if file_exists else ""
                record = {
                    "relative_path": self._to_relative_path(display_path, project_root),
                    "display_path": display_path,
                    "baseline_exists": file_exists,
                    "baseline_content": baseline_content,
                    "sources": [],
                }
            self._write_text(abs_path, new_content)
            current_exists = os.path.isfile(abs_path)
            current_content = self._read_disk_text(abs_path) if current_exists else ""
            if self._has_changes(
                bool(record["baseline_exists"]),
                str(record["baseline_content"] or ""),
                current_exists,
                current_content,
            ):
                sources = list(record.get("sources", []))
                if not sources or sources[-1] != source:
                    sources.append(dict(source))
                record["sources"] = sources
                record["relative_path"] = self._to_relative_path(display_path, project_root)
                record["display_path"] = display_path
                self._records[abs_path] = record
            else:
                self._records.pop(abs_path, None)
            self._save_storage_locked()
        return self._emit_state_changed()

    def _reject_file_locked(self, abs_path: str) -> None:
        record = self._records.get(abs_path)
        if record is None:
            return
        baseline_exists = bool(record["baseline_exists"])
        baseline_content = str(record["baseline_content"] or "")
        if baseline_exists:
            self._write_text(abs_path, baseline_content)
        else:
            self._delete_file_if_exists(abs_path)
        self._records.pop(abs_path, None)

    def _emit_state_changed(self) -> Dict[str, Any]:
        state = self.get_state()
        self._emit_signals_for_state(state)
        return state

    def _emit_signals_for_state(self, state: Dict[str, Any]) -> None:
        self.state_changed.emit(state)
        self.summary_changed.emit(self._build_summary_state(state))

    def _build_summary_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(state, dict):
            return {
                "file_count": 0,
                "added_lines": 0,
                "deleted_lines": 0,
                "files": [],
            }

        files: List[Dict[str, Any]] = []
        for file_state in state.get("files", []) or []:
            if not isinstance(file_state, dict):
                continue
            file_path = str(file_state.get("path", "") or "")
            if not file_path:
                continue
            files.append(
                {
                    "path": file_path,
                    "relative_path": str(file_state.get("relative_path", file_path) or file_path),
                    "added_lines": int(file_state.get("added_lines", 0) or 0),
                    "deleted_lines": int(file_state.get("deleted_lines", 0) or 0),
                }
            )

        return {
            "file_count": len(files),
            "added_lines": sum(int(item["added_lines"]) for item in files),
            "deleted_lines": sum(int(item["deleted_lines"]) for item in files),
            "files": files,
        }

    def _build_state_locked(self) -> Dict[str, Any]:
        files: List[Dict[str, Any]] = []
        stale_paths: List[str] = []
        for abs_path, record in sorted(
            self._records.items(),
            key=lambda item: item[1].get("relative_path", item[0]),
        ):
            current_exists = os.path.isfile(abs_path)
            current_content = self._read_disk_text(abs_path) if current_exists else ""
            file_state = self._build_file_state(abs_path, record, current_exists, current_content)
            if file_state is None:
                stale_paths.append(abs_path)
                continue
            files.append(file_state)
        for stale_path in stale_paths:
            self._records.pop(stale_path, None)
        if stale_paths:
            self._save_storage_locked()
        return {
            "file_count": len(files),
            "added_lines": sum(int(item["added_lines"]) for item in files),
            "deleted_lines": sum(int(item["deleted_lines"]) for item in files),
            "files": files,
        }

    def _build_file_state(
        self,
        abs_path: str,
        record: Dict[str, Any],
        current_exists: bool,
        current_content: str,
    ) -> Optional[Dict[str, Any]]:
        baseline_exists = bool(record.get("baseline_exists", False))
        baseline_content = str(record.get("baseline_content", "") or "")
        if not self._has_changes(baseline_exists, baseline_content, current_exists, current_content):
            return None
        hunks = self._build_hunks(baseline_content, current_content)
        return {
            "path": str(record.get("display_path", abs_path) or abs_path),
            "identity_path": abs_path,
            "relative_path": str(record.get("relative_path", abs_path) or abs_path),
            "added_lines": sum(int(item["added_lines"]) for item in hunks),
            "deleted_lines": sum(int(item["deleted_lines"]) for item in hunks),
            "hunks": hunks,
            "sources": list(record.get("sources", [])),
            "baseline_exists": baseline_exists,
            "current_exists": current_exists,
        }

    def _build_hunks(self, baseline_content: str, current_content: str) -> List[Dict[str, Any]]:
        old_lines = self._split_text(baseline_content)
        new_lines = self._split_text(current_content)
        matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
        hunks: List[Dict[str, Any]] = []
        for index, (tag, i1, i2, j1, j2) in enumerate(matcher.get_opcodes()):
            if tag == "equal":
                continue
            old_segment = old_lines[i1:i2]
            new_segment = new_lines[j1:j2]
            lines: List[Dict[str, Any]] = []
            for offset, text in enumerate(old_segment):
                lines.append(
                    {
                        "kind": "deleted",
                        "old_line_number": i1 + offset + 1,
                        "new_line_number": None,
                        "text": text,
                    }
                )
            for offset, text in enumerate(new_segment):
                lines.append(
                    {
                        "kind": "added",
                        "old_line_number": None,
                        "new_line_number": j1 + offset + 1,
                        "text": text,
                    }
                )
            hunks.append(
                {
                    "id": f"h{index}_{i1}_{i2}_{j1}_{j2}",
                    "header": f"@@ -{i1 + 1},{i2 - i1} +{j1 + 1},{j2 - j1} @@",
                    "old_start": i1,
                    "old_count": i2 - i1,
                    "new_start": j1,
                    "new_count": j2 - j1,
                    "old_lines": list(old_segment),
                    "new_lines": list(new_segment),
                    "added_lines": len(new_segment),
                    "deleted_lines": len(old_segment),
                    "lines": lines,
                }
            )
        return hunks

    def _save_storage_locked(self) -> None:
        project_root = self._get_project_root()
        if not project_root:
            return
        storage_path = self._get_storage_path(project_root)
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "files": [
                {
                    "relative_path": record["relative_path"],
                    "baseline_exists": bool(record["baseline_exists"]),
                    "baseline_content": str(record["baseline_content"] or ""),
                    "sources": list(record.get("sources", [])),
                }
                for _, record in sorted(
                    self._records.items(),
                    key=lambda item: item[1].get("relative_path", item[0]),
                )
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
        return Path(project_root).resolve() / ".circuit_ai" / "pending_workspace_edits.json"

    def _get_project_root(self, path: str = "") -> str:
        project_root = ""
        manager = self.session_state_manager
        if manager is not None:
            try:
                project_root = str(manager.get_project_root() or "")
            except Exception:
                project_root = ""
        if project_root:
            return self._normalize_path(project_root)
        if path:
            return self._normalize_path(str(Path(path).resolve().parent))
        return ""

    def _to_relative_path(self, abs_path: str, project_root: str) -> str:
        abs_obj = Path(abs_path).resolve()
        root_obj = Path(project_root).resolve()
        try:
            return abs_obj.relative_to(root_obj).as_posix()
        except Exception:
            return os.path.relpath(str(abs_obj), str(root_obj)).replace("\\", "/")

    def _write_text(self, abs_path: str, content: str) -> None:
        manager = self.file_manager
        if manager is None:
            raise RuntimeError("FileManager not available")
        if os.path.isfile(abs_path):
            manager.update_file(abs_path, content)
        else:
            manager.rewrite_file(abs_path, content)

    def _delete_file_if_exists(self, abs_path: str) -> None:
        manager = self.file_manager
        if manager is None:
            raise RuntimeError("FileManager not available")
        if os.path.isfile(abs_path):
            manager.delete_file(abs_path)

    def _read_disk_text(self, abs_path: str) -> str:
        manager = self.file_manager
        if manager is None:
            raise RuntimeError("FileManager not available")
        return str(manager.read_file(abs_path) or "")

    def _has_changes(
        self,
        baseline_exists: bool,
        baseline_content: str,
        current_exists: bool,
        current_content: str,
    ) -> bool:
        return bool(baseline_exists) != bool(current_exists) or str(baseline_content or "") != str(current_content or "")

    def _split_text(self, text: str) -> List[str]:
        normalized = normalize_to_lf(str(text or ""))
        if normalized == "":
            return []
        return normalized.split("\n")

    def _join_lines(self, lines: List[str]) -> str:
        return "\n".join(lines)

    def _normalize_path(self, path: str) -> str:
        return normalize_identity_path(path)

    def _is_internal_path(self, abs_path: str, project_root: str) -> bool:
        relative_path = self._to_relative_path(abs_path, project_root)
        normalized = relative_path.replace("\\", "/")
        if normalized == ".circuit_ai/pending_workspace_edits.json":
            return True
        if normalized.startswith(".circuit_ai/snapshots/"):
            return True
        if normalized.startswith(".circuit_ai/conversations/"):
            return True
        return False


__all__ = ["PendingWorkspaceEditService"]
