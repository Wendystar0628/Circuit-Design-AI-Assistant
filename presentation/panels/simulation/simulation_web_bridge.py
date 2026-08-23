from __future__ import annotations

import math
from typing import Any, Dict, Optional

from PyQt6.QtCore import QObject, QJsonValue, pyqtSignal, pyqtSlot

from presentation.panels.simulation.simulation_frontend_state_serializer import ALL_TAB_IDS


class SimulationWebBridge(QObject):
    ready = pyqtSignal()
    activate_tab_requested = pyqtSignal(str)
    load_result_by_path_requested = pyqtSignal(dict)
    cancel_simulation_requested = pyqtSignal(dict)
    schematic_value_update_requested = pyqtSignal(dict)
    raw_data_viewport_requested = pyqtSignal(dict)
    raw_data_copy_requested = pyqtSignal(dict)
    chart_series_visibility_toggled = pyqtSignal(str, bool)
    clear_all_chart_series_requested = pyqtSignal()
    chart_measurement_enabled_changed = pyqtSignal(bool)
    chart_measurement_cursor_move_requested = pyqtSignal(str, float)
    chart_measurement_point_enabled_changed = pyqtSignal(bool)
    chart_measurement_point_target_changed = pyqtSignal(str)
    chart_measurement_point_move_requested = pyqtSignal(float)
    chart_viewport_changed = pyqtSignal(dict)
    chart_viewport_reset_requested = pyqtSignal()
    signal_visibility_toggled = pyqtSignal(str, bool)
    clear_all_signals_requested = pyqtSignal()
    cursor_visibility_toggled = pyqtSignal(str, bool)
    cursor_move_requested = pyqtSignal(str, float)
    waveform_viewport_changed = pyqtSignal(dict)
    waveform_viewport_reset_requested = pyqtSignal()
    output_log_search_requested = pyqtSignal(str)
    output_log_filter_requested = pyqtSignal(str)
    output_log_copy_requested = pyqtSignal()
    export_type_selection_changed = pyqtSignal(str, bool)
    export_all_selection_requested = pyqtSignal(bool)
    export_directory_pick_requested = pyqtSignal()
    export_directory_clear_requested = pyqtSignal()
    export_requested = pyqtSignal(dict)
    asc_conversion_pick_requested = pyqtSignal()
    add_to_conversation_requested = pyqtSignal(dict)
    update_metric_targets_requested = pyqtSignal(dict)

    @pyqtSlot()
    def markReady(self) -> None:
        self.ready.emit()

    @pyqtSlot(str)
    def activateTab(self, tab_id: str) -> None:
        self.activate_tab_requested.emit(self._normalize_tab_id(tab_id))

    @pyqtSlot(QJsonValue)
    @pyqtSlot(dict)
    def loadResultByPath(self, payload: Any) -> None:
        normalized = self._normalize_result_identity_payload(payload)
        if normalized is not None:
            self.load_result_by_path_requested.emit(normalized)

    @pyqtSlot(QJsonValue)
    @pyqtSlot(dict)
    def cancelSimulation(self, payload: Any) -> None:
        normalized = self._normalize_cancel_identity_payload(payload)
        if normalized is not None:
            self.cancel_simulation_requested.emit(normalized)

    @pyqtSlot(QJsonValue)
    @pyqtSlot(dict)
    def updateSchematicValue(self, payload: Any) -> None:
        normalized = self._normalize_schematic_value_update_payload(payload)
        if normalized is not None:
            self.schematic_value_update_requested.emit(normalized)

    @pyqtSlot(QJsonValue)
    @pyqtSlot(dict)
    def requestRawDataViewport(self, payload: Any) -> None:
        normalized = self._normalize_raw_data_range_payload(payload)
        if normalized is not None:
            self.raw_data_viewport_requested.emit(normalized)

    @pyqtSlot(QJsonValue)
    @pyqtSlot(dict)
    def copyRawDataRange(self, payload: Any) -> None:
        normalized = self._normalize_raw_data_range_payload(payload)
        if normalized is not None:
            normalized["include_headers"] = bool(normalized.get("include_headers"))
            self.raw_data_copy_requested.emit(normalized)

    @pyqtSlot(str, bool)
    def setChartSeriesVisible(self, series_name: str, visible: bool) -> None:
        self.chart_series_visibility_toggled.emit(str(series_name or ""), bool(visible))

    @pyqtSlot()
    def clearAllChartSeries(self) -> None:
        self.clear_all_chart_series_requested.emit()

    @pyqtSlot(bool)
    def setChartMeasurementEnabled(self, enabled: bool) -> None:
        self.chart_measurement_enabled_changed.emit(bool(enabled))

    @pyqtSlot(str, float)
    def moveChartMeasurementCursor(self, cursor_id: str, position: float) -> None:
        normalized = self._finite_float(position)
        if normalized is not None:
            self.chart_measurement_cursor_move_requested.emit(self._normalize_cursor_id(cursor_id), normalized)

    @pyqtSlot(bool)
    def setChartMeasurementPointEnabled(self, enabled: bool) -> None:
        self.chart_measurement_point_enabled_changed.emit(bool(enabled))

    @pyqtSlot(str)
    def setChartMeasurementPointTarget(self, target_id: str) -> None:
        self.chart_measurement_point_target_changed.emit(str(target_id or ""))

    @pyqtSlot(float)
    def moveChartMeasurementPoint(self, position: float) -> None:
        normalized = self._finite_float(position)
        if normalized is not None:
            self.chart_measurement_point_move_requested.emit(normalized)

    @pyqtSlot(QJsonValue)
    @pyqtSlot(dict)
    def setChartViewport(self, viewport: Any) -> None:
        normalized = self._normalize_viewport_payload(viewport)
        if normalized is not None:
            self.chart_viewport_changed.emit(normalized)

    @pyqtSlot()
    def resetChartViewport(self) -> None:
        self.chart_viewport_reset_requested.emit()

    @pyqtSlot(str, bool)
    def setSignalVisible(self, signal_name: str, visible: bool) -> None:
        self.signal_visibility_toggled.emit(str(signal_name or ""), bool(visible))

    @pyqtSlot()
    def clearAllSignals(self) -> None:
        self.clear_all_signals_requested.emit()

    @pyqtSlot(str, bool)
    def setCursorVisible(self, cursor_id: str, visible: bool) -> None:
        self.cursor_visibility_toggled.emit(self._normalize_cursor_id(cursor_id), bool(visible))

    @pyqtSlot(str, float)
    def moveCursor(self, cursor_id: str, position: float) -> None:
        normalized = self._finite_float(position)
        if normalized is not None:
            self.cursor_move_requested.emit(self._normalize_cursor_id(cursor_id), normalized)

    @pyqtSlot(QJsonValue)
    @pyqtSlot(dict)
    def setWaveformViewport(self, viewport: Any) -> None:
        normalized = self._normalize_viewport_payload(viewport)
        if normalized is not None:
            self.waveform_viewport_changed.emit(normalized)

    @pyqtSlot()
    def resetWaveformViewport(self) -> None:
        self.waveform_viewport_reset_requested.emit()

    @pyqtSlot(str)
    def searchOutputLog(self, keyword: str) -> None:
        self.output_log_search_requested.emit(str(keyword or ""))

    @pyqtSlot(str)
    def filterOutputLog(self, level: str) -> None:
        self.output_log_filter_requested.emit(str(level or ""))

    @pyqtSlot()
    def copyOutputLog(self) -> None:
        self.output_log_copy_requested.emit()

    @pyqtSlot(str, bool)
    def setExportTypeSelected(self, export_type: str, selected: bool) -> None:
        self.export_type_selection_changed.emit(str(export_type or ""), bool(selected))

    @pyqtSlot(bool)
    def setAllExportTypesSelected(self, selected: bool) -> None:
        self.export_all_selection_requested.emit(bool(selected))

    @pyqtSlot()
    def chooseExportDirectory(self) -> None:
        self.export_directory_pick_requested.emit()

    @pyqtSlot()
    def clearExportDirectory(self) -> None:
        self.export_directory_clear_requested.emit()

    @pyqtSlot(QJsonValue)
    @pyqtSlot(dict)
    def requestExport(self, payload: Any) -> None:
        normalized = self._normalize_result_identity_payload(payload)
        if normalized is not None:
            self.export_requested.emit(normalized)

    @pyqtSlot()
    def chooseAscFilesForConversion(self) -> None:
        self.asc_conversion_pick_requested.emit()

    @pyqtSlot(QJsonValue)
    @pyqtSlot(dict)
    def addToConversation(self, payload: Any) -> None:
        normalized = self._normalize_result_identity_payload(payload)
        if normalized is None:
            return
        raw_payload = payload.toVariant() if isinstance(payload, QJsonValue) else payload
        target = self._normalize_attachment_target(raw_payload.get("target"))
        if target is None:
            return
        normalized["target"] = target
        self.add_to_conversation_requested.emit(normalized)

    @pyqtSlot(QJsonValue)
    @pyqtSlot(dict)
    def updateMetricTargets(self, payload: Any) -> None:
        normalized = self._normalize_metric_targets_payload(payload)
        if normalized is not None:
            self.update_metric_targets_requested.emit(normalized)

    def _normalize_tab_id(self, tab_id: str) -> str:
        """Normalise a JS-supplied tab id, falling back to ``metrics``.

        The membership set is the authoritative
        :data:`~presentation.panels.simulation.simulation_frontend_state_serializer.ALL_TAB_IDS`
        tuple — this bridge deliberately refuses to maintain its own
        tab catalogue. Prior to this collapse three independent sets
        existed (``_BASE_TABS`` in the serializer, a literal set in
        ``SimulationTab._is_allowed_frontend_tab``, and another here)
        which made adding ``circuit_selection`` a three-place change.
        """
        normalized = str(tab_id or "metrics").strip().lower()
        return normalized if normalized in ALL_TAB_IDS else "metrics"

    def _normalize_cursor_id(self, cursor_id: str) -> str:
        normalized = str(cursor_id or "a").strip().lower()
        return normalized if normalized in {"a", "b"} else "a"

    def _normalize_attachment_target(self, target: Any) -> Optional[str]:
        if not isinstance(target, str):
            return None
        normalized = target.strip().lower()
        allowed = {"metrics", "chart", "waveform", "output_log", "op_result"}
        return normalized if normalized in allowed else None

    def _normalize_result_identity_payload(self, payload: Any) -> Optional[Dict[str, str]]:
        normalized = self._normalize_string_fields(
            payload,
            {"projectRoot": "project_root", "resultPath": "result_path"},
        )
        return normalized

    def _normalize_cancel_identity_payload(self, payload: Any) -> Optional[Dict[str, str]]:
        normalized = self._normalize_string_fields(
            payload,
            {"projectRoot": "project_root", "jobId": "job_id"},
        )
        return normalized

    @staticmethod
    def _normalize_string_fields(
        payload: Any,
        field_map: Dict[str, str],
    ) -> Optional[Dict[str, str]]:
        if isinstance(payload, QJsonValue):
            payload = payload.toVariant()
        if not isinstance(payload, dict):
            return None
        normalized: Dict[str, str] = {}
        for wire_name, internal_name in field_map.items():
            value = payload.get(wire_name)
            if not isinstance(value, str) or not value.strip():
                return None
            normalized[internal_name] = value
        return normalized

    def _normalize_metric_targets_payload(self, payload: Any) -> Optional[Dict[str, Any]]:
        if isinstance(payload, QJsonValue):
            payload = payload.toVariant()
        if not isinstance(payload, dict):
            return None
        identity = self._normalize_result_identity_payload(payload)
        if identity is None:
            return None
        source_file_path = payload.get("sourceFilePath")
        if not isinstance(source_file_path, str) or not source_file_path.strip():
            return None
        raw_targets = payload.get("targets")
        if not isinstance(raw_targets, dict):
            return None
        cleaned: Dict[str, str] = {}
        for raw_name, raw_value in raw_targets.items():
            if not isinstance(raw_name, str) or not raw_name.strip():
                return None
            if not isinstance(raw_value, str):
                return None
            cleaned[raw_name.strip()] = raw_value.strip()
        return {
            **identity,
            "source_file_path": source_file_path,
            "targets": cleaned,
        }

    def _normalize_schematic_value_update_payload(self, payload: Any) -> Optional[Dict[str, Any]]:
        if isinstance(payload, QJsonValue):
            payload = payload.toVariant()
        if not isinstance(payload, dict):
            return None
        return {
            "document_id": str(payload.get("documentId") or ""),
            "revision": str(payload.get("revision") or ""),
            "component_id": str(payload.get("componentId") or ""),
            "field_key": str(payload.get("fieldKey") or ""),
            "new_text": str(payload.get("newText") or ""),
            "request_id": str(payload.get("requestId") or ""),
        }

    def _normalize_raw_data_range_payload(self, payload: Any) -> Optional[Dict[str, Any]]:
        if isinstance(payload, QJsonValue):
            payload = payload.toVariant()
        if not isinstance(payload, dict):
            return None
        try:
            row_start = max(0, int(payload.get("rowStart") or 0))
            row_end = max(row_start, int(payload.get("rowEnd") or row_start))
            col_start = max(0, int(payload.get("colStart") or 0))
            col_end = max(col_start, int(payload.get("colEnd") or col_start))
        except (TypeError, ValueError):
            return None
        version_value = payload.get("version")
        try:
            version = int(version_value) if version_value is not None else None
        except (TypeError, ValueError):
            version = None
        return {
            "dataset_id": str(payload.get("datasetId") or ""),
            "version": version,
            "row_start": row_start,
            "row_end": row_end,
            "col_start": col_start,
            "col_end": col_end,
            "include_headers": bool(payload.get("includeHeaders")),
        }

    def _normalize_viewport_payload(self, payload: Any) -> Optional[Dict[str, Optional[float]]]:
        if isinstance(payload, QJsonValue):
            payload = payload.toVariant()
        if not isinstance(payload, dict):
            return None
        try:
            x_min = float(payload.get("xMin"))
            x_max = float(payload.get("xMax"))
            left_y_min = float(payload.get("leftYMin"))
            left_y_max = float(payload.get("leftYMax"))
        except (TypeError, ValueError):
            return None
        right_y_min = payload.get("rightYMin")
        right_y_max = payload.get("rightYMax")
        resolved_right_y_min = self._finite_float(right_y_min) if right_y_min is not None else None
        resolved_right_y_max = self._finite_float(right_y_max) if right_y_max is not None else None
        required = (x_min, x_max, left_y_min, left_y_max)
        if not all(math.isfinite(value) for value in required):
            return None
        if x_min >= x_max or left_y_min >= left_y_max:
            return None
        if (resolved_right_y_min is None) != (resolved_right_y_max is None):
            return None
        if resolved_right_y_min is not None and resolved_right_y_min >= resolved_right_y_max:
            return None
        return {
            "x_min": x_min,
            "x_max": x_max,
            "left_y_min": left_y_min,
            "left_y_max": left_y_max,
            "right_y_min": resolved_right_y_min,
            "right_y_max": resolved_right_y_max,
        }

    @staticmethod
    def _finite_float(value: Any) -> Optional[float]:
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            return None
        return normalized if math.isfinite(normalized) else None


__all__ = ["SimulationWebBridge"]
