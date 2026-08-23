from __future__ import annotations

import copy
import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Set

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from domain.simulation.spice.models import SpiceDocument
from domain.simulation.spice.parser import SpiceParser
from domain.simulation.spice.schematic_builder import SpiceSchematicBuilder
from domain.simulation.spice.source_closure import (
    SpiceSourceClosureGraph,
    SpiceSourceClosureError,
    collect_spice_source_closure,
)
from domain.simulation.spice.source_patcher import SpiceSourcePatcher
from presentation.panels.simulation.simulation_frontend_state_serializer import SimulationFrontendStateSerializer
from shared.event_types import EVENT_FILE_CHANGED
from shared.file_change import extract_file_change
from shared.path_utils import normalize_identity_path


_DEBOUNCE_INTERVAL_MS = 250


class SpiceSchematicDocument(QObject):
    schematic_document_changed = pyqtSignal(dict)
    schematic_write_result_changed = pyqtSignal(dict)
    source_provenance_invalidated = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._logger = logging.getLogger(__name__)
        self._state_serializer = SimulationFrontendStateSerializer()
        self._parser = SpiceParser()
        self._builder = SpiceSchematicBuilder()
        self._source_patcher = SpiceSourcePatcher()

        self._current_file_path = ""
        self._expected_source_digest = ""
        self._latest_spice_document: Optional[SpiceDocument] = None
        self._latest_source_text = ""
        self._latest_dependency_snapshots: Dict[str, str] = {}
        self._watched_file_keys: Set[str] = set()
        self._subscribed_to_file_events = False
        self._event_bus = None
        self._file_manager = None

        self._authoritative_schematic_document = self._state_serializer.serialize_schematic_document()
        self._authoritative_schematic_write_result = self._state_serializer.serialize_schematic_write_result()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._flush_debounced_refresh)
        self._pending_refresh_reason = ""

    def get_authoritative_schematic_document(self) -> Dict[str, Any]:
        return copy.deepcopy(self._authoritative_schematic_document)

    def get_authoritative_schematic_write_result(self) -> Dict[str, Any]:
        return copy.deepcopy(self._authoritative_schematic_write_result)

    def load_from_result_file(self, file_path: str, source_digest: str) -> bool:
        next_file_path = str(file_path or "")
        same_source = (
            bool(next_file_path)
            and self._normalize_watch_key(next_file_path)
            == self._normalize_watch_key(self._current_file_path)
        )
        previous_watch_keys = set(self._watched_file_keys) if same_source else set()
        expected_digest = str(source_digest or "").strip().lower()
        if len(expected_digest) != 64 or any(
            character not in "0123456789abcdef" for character in expected_digest
        ):
            self.load_unavailable_source(
                next_file_path,
                "仿真结果缺少有效的源电路摘要，历史结果原理图不可用",
            )
            return False
        self._current_file_path = next_file_path
        self._expected_source_digest = expected_digest
        self._latest_spice_document = None
        self._latest_source_text = ""
        self._latest_dependency_snapshots = {}
        self._watched_file_keys = previous_watch_keys
        self._pending_refresh_reason = ""
        self._refresh_timer.stop()

        if not self._current_file_path:
            self.clear()
            return False

        self._subscribe_file_events()
        self._emit_schematic_write_result()
        return self._refresh_document(reason="result_switched")

    def clear(self) -> None:
        self._current_file_path = ""
        self._expected_source_digest = ""
        self._latest_spice_document = None
        self._latest_source_text = ""
        self._latest_dependency_snapshots = {}
        self._watched_file_keys.clear()
        self._pending_refresh_reason = ""
        self._refresh_timer.stop()
        self._unsubscribe_file_events()
        self._set_schematic_document(
            self._state_serializer.serialize_schematic_document(
                self._builder.build_empty_document()
            )
        )
        self._emit_schematic_write_result()

    def load_unavailable_source(self, source_identity: str, reason: str) -> None:
        """Expose an unresolvable persisted source without reading the CWD.

        ``SimulationResult.file_path`` is an identity, not an arbitrary path
        the presentation layer may open.  The result repository resolves and
        confines it to the active project first; when that fails this method
        produces an explicit read-only error document instead of interpreting
        a relative value against the process working directory.
        """
        unavailable_identity = str(source_identity or "")
        self._current_file_path = ""
        self._expected_source_digest = ""
        self._latest_spice_document = None
        self._latest_source_text = ""
        self._latest_dependency_snapshots = {}
        self._watched_file_keys.clear()
        self._pending_refresh_reason = ""
        self._refresh_timer.stop()
        self._unsubscribe_file_events()
        payload = self._builder.build_empty_document(unavailable_identity)
        payload["parse_errors"] = [
            self._make_parse_error(
                str(reason or "历史结果原理图不可用"),
                unavailable_identity,
            )
        ]
        self._set_schematic_document(
            self._state_serializer.serialize_schematic_document(payload)
        )
        self._emit_schematic_write_result()
        self.source_provenance_invalidated.emit(str(reason or "历史结果原理图不可用"))

    def request_value_update(self, payload: Dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return

        self._refresh_document(reason="write_request_prepare")

        request_id = str(payload.get("request_id") or "")
        component_id = str(payload.get("component_id") or "")
        field_key = str(payload.get("field_key") or "")

        if not self._current_file_path:
            self._emit_schematic_write_result(
                request_id=request_id,
                success=False,
                component_id=component_id,
                field_key=field_key,
                result_type="error",
                error_message="当前没有可写回的源电路文件",
            )
            return

        if self._latest_spice_document is None:
            self._emit_schematic_write_result(
                document_id=str(self._authoritative_schematic_document.get("document_id") or ""),
                revision=str(self._authoritative_schematic_document.get("revision") or ""),
                request_id=request_id,
                success=False,
                component_id=component_id,
                field_key=field_key,
                result_type="error",
                error_message="当前电路文档不可写回，请先修复解析问题",
            )
            return

        patch_result = self._source_patcher.patch_value(
            file_path=self._current_file_path,
            spice_document=self._latest_spice_document,
            document_id=str(payload.get("document_id") or ""),
            revision=str(payload.get("revision") or ""),
            component_id=component_id,
            field_key=field_key,
            new_text=str(payload.get("new_text") or ""),
            request_id=request_id,
            dependency_snapshots=self._latest_dependency_snapshots,
        )

        if patch_result.success and patch_result.changed:
            self._refresh_document(reason="write_success")
        else:
            self._refresh_document(reason="write_rejected")

        self._emit_schematic_write_result(
            document_id=str(self._authoritative_schematic_document.get("document_id") or patch_result.document_id),
            revision=str(self._authoritative_schematic_document.get("revision") or patch_result.revision),
            request_id=patch_result.request_id,
            success=patch_result.success,
            component_id=patch_result.component_id,
            field_key=patch_result.field_key,
            result_type=patch_result.result_type,
            error_message=patch_result.error_message,
        )

    def _refresh_document(self, *, reason: str) -> bool:
        if not self._current_file_path:
            self._latest_spice_document = None
            self._latest_source_text = ""
            self._latest_dependency_snapshots = {}
            self._watched_file_keys.clear()
            self._set_schematic_document(
                self._state_serializer.serialize_schematic_document(
                    self._builder.build_empty_document()
                )
            )
            return False

        try:
            source_closure = collect_spice_source_closure(self._current_file_path)
            self._watched_file_keys = {
                normalized_key
                for path in source_closure.source_keys
                if (normalized_key := self._normalize_watch_key(path))
            }
            if source_closure.digest != self._expected_source_digest:
                invalidation_reason = (
                    "源电路已修改；当前波形仍属于修改前的历史结果。请重新运行仿真。"
                    if reason == "write_success"
                    else "源电路已改变，或其依赖已改变，历史结果原理图不可用"
                )
                return self._invalidate_historical_source(
                    document_message=(
                        "源电路已改变，或其依赖已改变，历史结果原理图不可用"
                    ),
                    status_reason=invalidation_reason,
                )
            main_blob = source_closure.main_blob
            parsed_document = self._parser.parse_source_graph(source_closure)
            dependency_snapshots = (
                self._build_edit_revision_dependency_snapshots(source_closure)
            )
            self._latest_spice_document = parsed_document
            self._latest_source_text = main_blob.source_text
            self._latest_dependency_snapshots = dependency_snapshots
            payload = self._builder.build_document(
                parsed_document,
                source_text=main_blob.source_text,
                dependency_snapshots=dependency_snapshots,
            )
            self._set_schematic_document(
                self._state_serializer.serialize_schematic_document(payload)
            )
            return True
        except SpiceSourceClosureError as exc:
            self._logger.warning(
                "Historical schematic source closure is unavailable (%s): %s",
                reason,
                exc,
            )
            return self._invalidate_historical_source(
                document_message=f"源电路或其依赖不可用：{exc}",
                status_reason="源电路或其依赖不可用，历史结果原理图不可用",
            )
        except Exception as exc:
            self._logger.warning(
                "Failed to build schematic document (%s): %s",
                reason,
                exc,
            )
            self._latest_spice_document = None
            self._latest_source_text = ""
            self._latest_dependency_snapshots = {}
            if not self._watched_file_keys and self._current_file_path:
                self._watched_file_keys = {
                    self._normalize_watch_key(self._current_file_path)
                }
            payload = self._builder.build_empty_document(self._current_file_path)
            payload["parse_errors"] = [
                self._make_parse_error(
                    f"电路文档构建失败: {exc}",
                    self._current_file_path,
                )
            ]
            self._set_schematic_document(
                self._state_serializer.serialize_schematic_document(payload)
            )
            return False

    def _invalidate_historical_source(
        self,
        *,
        document_message: str,
        status_reason: str,
    ) -> bool:
        """Make a persisted schematic read-only after provenance rejection."""
        self._latest_spice_document = None
        self._latest_source_text = ""
        self._latest_dependency_snapshots = {}
        if not self._watched_file_keys and self._current_file_path:
            self._watched_file_keys = {
                self._normalize_watch_key(self._current_file_path)
            }
        payload = self._builder.build_empty_document(self._current_file_path)
        payload["parse_errors"] = [
            self._make_parse_error(document_message, self._current_file_path)
        ]
        self._set_schematic_document(
            self._state_serializer.serialize_schematic_document(payload)
        )
        self.source_provenance_invalidated.emit(status_reason)
        return False

    def _set_schematic_document(self, next_document: Dict[str, Any]) -> None:
        if next_document == self._authoritative_schematic_document:
            return
        self._authoritative_schematic_document = next_document
        self.schematic_document_changed.emit(copy.deepcopy(self._authoritative_schematic_document))

    def _emit_schematic_write_result(
        self,
        *,
        document_id: str = "",
        revision: str = "",
        request_id: str = "",
        success: bool = False,
        component_id: str = "",
        field_key: str = "",
        result_type: str = "",
        error_message: str = "",
    ) -> None:
        next_result = self._state_serializer.serialize_schematic_write_result(
            self._builder.build_write_result(
                document_id=document_id,
                revision=revision,
                request_id=request_id,
                success=success,
                component_id=component_id,
                field_key=field_key,
                result_type=result_type,
                error_message=error_message,
            )
        )
        if next_result == self._authoritative_schematic_write_result:
            return
        self._authoritative_schematic_write_result = next_result
        self.schematic_write_result_changed.emit(copy.deepcopy(self._authoritative_schematic_write_result))

    def _subscribe_file_events(self) -> None:
        if self._subscribed_to_file_events:
            return
        event_bus = self._get_event_bus()
        if event_bus is None:
            return
        try:
            event_bus.subscribe(EVENT_FILE_CHANGED, self._on_file_changed)
            self._subscribed_to_file_events = True
        except Exception as exc:
            self._logger.warning(f"Failed to subscribe schematic file events: {exc}")

    def _unsubscribe_file_events(self) -> None:
        if not self._subscribed_to_file_events:
            return
        event_bus = self._get_event_bus()
        if event_bus is not None:
            try:
                event_bus.unsubscribe(EVENT_FILE_CHANGED, self._on_file_changed)
            except Exception:
                pass
        self._subscribed_to_file_events = False

    def _get_event_bus(self):
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS

                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus

    def _get_file_manager(self):
        if self._file_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_FILE_MANAGER

                self._file_manager = ServiceLocator.get_optional(SVC_FILE_MANAGER)
            except Exception:
                pass
        return self._file_manager

    def _on_file_changed(self, event_data: Dict[str, Any]) -> None:
        if not self._current_file_path or not self._watched_file_keys:
            return
        change = extract_file_change(event_data)
        manager = self._get_file_manager()
        if change is None or manager is None:
            return
        try:
            manager_root = manager.get_work_dir()
            manager_generation = int(manager.project_generation)
        except (AttributeError, TypeError, ValueError):
            return
        if (
            manager_root is None
            or normalize_identity_path(change.project_root)
            != normalize_identity_path(str(manager_root))
            or change.generation != manager_generation
        ):
            return
        if change.is_directory:
            return

        candidate_keys = set()
        path = change.path
        dest_path = change.dest_path
        if path:
            candidate_keys.add(self._normalize_watch_key(path))
        if dest_path:
            candidate_keys.add(self._normalize_watch_key(dest_path))

        if not candidate_keys.intersection(self._watched_file_keys):
            return

        self._pending_refresh_reason = change.operation
        self._refresh_timer.start(_DEBOUNCE_INTERVAL_MS)

    def _flush_debounced_refresh(self) -> None:
        if not self._current_file_path:
            return
        self._refresh_document(reason=self._pending_refresh_reason or "debounced_file_changed")
        self._pending_refresh_reason = ""

    def _build_edit_revision_dependency_snapshots(
        self,
        source_closure: SpiceSourceClosureGraph,
    ) -> Dict[str, str]:
        """Build edit-conflict tokens from the already-verified closure.

        These SHA-1 tokens only detect a stale schematic edit revision. They
        are not scientific provenance; persisted-result identity is exclusively
        ``source_closure.digest``.
        """
        snapshots: Dict[str, str] = {}
        for view in source_closure.active_views:
            if view.is_main_deck:
                continue
            normalized_key = self._normalize_watch_key(view.key)
            if not normalized_key:
                continue
            snapshot_key = normalized_key
            if view.library_section:
                snapshot_key = f"{normalized_key}#lib:{view.library_section}"
            if snapshot_key in snapshots:
                continue
            active_text = "\n".join(
                f"{line.line_number}:{line.text}"
                for line in view.lines
            )
            snapshots[snapshot_key] = (
                self._make_edit_revision_dependency_snapshot_value(active_text)
            )
        return snapshots

    def _make_edit_revision_dependency_snapshot_value(self, source_text: str) -> str:
        digest = hashlib.sha1(str(source_text or "").encode("utf-8")).hexdigest()
        return f"content:{digest}"

    def _normalize_watch_key(self, path: str) -> str:
        if not path:
            return ""
        try:
            normalized = str(Path(path).resolve())
        except Exception:
            normalized = str(path)
        return normalized.replace("\\", "/").lower()

    def _make_parse_error(self, message: str, source_file: str) -> Dict[str, Any]:
        return {
            "message": str(message or ""),
            "source_file": str(source_file or ""),
            "line_text": "",
            "line_index": -1,
            "column_start": -1,
            "column_end": -1,
        }


__all__ = ["SpiceSchematicDocument"]
