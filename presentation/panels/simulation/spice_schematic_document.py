from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Set

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from domain.simulation.spice.file_codec import read_spice_source_file
from domain.simulation.spice.models import SpiceDocument
from domain.simulation.spice.parser import SpiceParser
from domain.simulation.spice.schematic_builder import SpiceSchematicBuilder
from domain.simulation.spice.source_patcher import SpiceSourcePatcher
from presentation.panels.simulation.simulation_frontend_state_serializer import SimulationFrontendStateSerializer
from shared.event_types import EVENT_FILE_CHANGED


_DEBOUNCE_INTERVAL_MS = 250


class SpiceSchematicDocument(QObject):
    schematic_document_changed = pyqtSignal(dict)
    schematic_write_result_changed = pyqtSignal(dict)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._logger = logging.getLogger(__name__)
        self._state_serializer = SimulationFrontendStateSerializer()
        self._parser = SpiceParser()
        self._builder = SpiceSchematicBuilder()
        self._source_patcher = SpiceSourcePatcher()

        self._current_file_path = ""
        self._latest_spice_document: Optional[SpiceDocument] = None
        self._latest_source_text = ""
        self._watched_file_keys: Set[str] = set()
        self._subscribed_to_file_events = False
        self._event_bus = None

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

    def load_from_result_file(self, file_path: str) -> None:
        next_file_path = str(file_path or "")
        if next_file_path == self._current_file_path and next_file_path:
            return

        self._current_file_path = next_file_path
        self._latest_spice_document = None
        self._latest_source_text = ""
        self._watched_file_keys.clear()
        self._pending_refresh_reason = ""
        self._refresh_timer.stop()

        if not self._current_file_path:
            self.clear()
            return

        self._subscribe_file_events()
        self._emit_schematic_write_result()
        self._refresh_document(reason="result_switched")

    def clear(self) -> None:
        self._current_file_path = ""
        self._latest_spice_document = None
        self._latest_source_text = ""
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
            error_message=patch_result.error_message,
        )

    def _refresh_document(self, *, reason: str) -> None:
        if not self._current_file_path:
            self._latest_spice_document = None
            self._latest_source_text = ""
            self._watched_file_keys.clear()
            self._set_schematic_document(
                self._state_serializer.serialize_schematic_document(
                    self._builder.build_empty_document()
                )
            )
            return

        try:
            source_file = read_spice_source_file(self._current_file_path)
            parsed_document = self._parser.parse_content(source_file.source_text, self._current_file_path)
            self._latest_spice_document = parsed_document
            self._latest_source_text = source_file.source_text
            self._watched_file_keys = self._resolve_watched_file_keys(self._current_file_path, parsed_document)
            payload = self._builder.build_document(
                parsed_document,
                source_text=source_file.source_text,
            )
            self._set_schematic_document(self._state_serializer.serialize_schematic_document(payload))
        except FileNotFoundError:
            self._latest_spice_document = None
            self._latest_source_text = ""
            self._watched_file_keys = {self._normalize_watch_key(self._current_file_path)} if self._current_file_path else set()
            payload = self._builder.build_empty_document(self._current_file_path)
            payload["parse_errors"] = [self._make_parse_error("未找到源电路文件", self._current_file_path)]
            self._set_schematic_document(self._state_serializer.serialize_schematic_document(payload))
        except Exception as exc:
            self._logger.warning(f"Failed to refresh schematic document ({reason}): {exc}")
            self._latest_spice_document = None
            self._latest_source_text = ""
            self._watched_file_keys = {self._normalize_watch_key(self._current_file_path)} if self._current_file_path else set()
            payload = self._builder.build_empty_document(self._current_file_path)
            payload["parse_errors"] = [self._make_parse_error(f"电路文档构建失败: {exc}", self._current_file_path)]
            self._set_schematic_document(self._state_serializer.serialize_schematic_document(payload))

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

    def _on_file_changed(self, event_data: Dict[str, Any]) -> None:
        if not self._current_file_path or not self._watched_file_keys:
            return
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        if not isinstance(data, dict):
            return
        if bool(data.get("is_directory")):
            return

        candidate_keys = set()
        path = str(data.get("path") or "")
        dest_path = str(data.get("dest_path") or "")
        if path:
            candidate_keys.add(self._normalize_watch_key(path))
        if dest_path:
            candidate_keys.add(self._normalize_watch_key(dest_path))

        if not candidate_keys.intersection(self._watched_file_keys):
            return

        self._pending_refresh_reason = str(data.get("event_type") or "file_changed")
        self._refresh_timer.start(_DEBOUNCE_INTERVAL_MS)

    def _flush_debounced_refresh(self) -> None:
        if not self._current_file_path:
            return
        self._refresh_document(reason=self._pending_refresh_reason or "debounced_file_changed")
        self._pending_refresh_reason = ""

    def _resolve_watched_file_keys(self, source_file_path: str, spice_document: SpiceDocument) -> Set[str]:
        watched_keys = {self._normalize_watch_key(source_file_path)}
        source_path = Path(source_file_path)
        source_dir = source_path.parent
        for include in spice_document.includes:
            include_path = str(include.path or "").strip()
            if not include_path:
                continue
            watched_keys.add(self._normalize_watch_key(self._resolve_include_path(source_dir, include_path)))
        return watched_keys

    def _resolve_include_path(self, source_dir: Path, include_path: str) -> str:
        candidate = Path(include_path)
        if not candidate.is_absolute():
            candidate = source_dir / candidate
        return str(candidate.resolve())

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
