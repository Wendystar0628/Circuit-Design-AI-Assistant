from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, QJsonValue, pyqtSignal, pyqtSlot

from presentation.panels.simulation.simulation_frontend_state_serializer import ALL_TAB_IDS


class SimulationWebBridge(QObject):
    ready = pyqtSignal()
    activate_tab_requested = pyqtSignal(str)
    load_result_by_path_requested = pyqtSignal(str)
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
    export_type_selection_changed = pyqtSignal(str, bool)
    export_all_selection_requested = pyqtSignal(bool)
    export_directory_pick_requested = pyqtSignal()
    export_directory_clear_requested = pyqtSignal()
    export_requested = pyqtSignal()
    add_to_conversation_requested = pyqtSignal(str)
    update_metric_targets_requested = pyqtSignal(dict)
    text_clipboard_copy_requested = pyqtSignal(str)

    @pyqtSlot()
    def markReady(self) -> None:
        self.ready.emit()

    @pyqtSlot(str)
    def activateTab(self, tab_id: str) -> None:
        self.activate_tab_requested.emit(self._normalize_tab_id(tab_id))

    @pyqtSlot(str)
    def loadResultByPath(self, result_path: str) -> None:
        self.load_result_by_path_requested.emit(str(result_path or ""))

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
        self.chart_measurement_cursor_move_requested.emit(self._normalize_cursor_id(cursor_id), float(position or 0.0))

    @pyqtSlot(bool)
    def setChartMeasurementPointEnabled(self, enabled: bool) -> None:
        self.chart_measurement_point_enabled_changed.emit(bool(enabled))

    @pyqtSlot(str)
    def setChartMeasurementPointTarget(self, target_id: str) -> None:
        self.chart_measurement_point_target_changed.emit(str(target_id or ""))

    @pyqtSlot(float)
    def moveChartMeasurementPoint(self, position: float) -> None:
        self.chart_measurement_point_move_requested.emit(float(position or 0.0))

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
        self.cursor_move_requested.emit(self._normalize_cursor_id(cursor_id), float(position or 0.0))

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

    @pyqtSlot()
    def requestExport(self) -> None:
        self.export_requested.emit()

    @pyqtSlot(str)
    def addToConversation(self, target: str) -> None:
        self.add_to_conversation_requested.emit(self._normalize_attachment_target(target))

    @pyqtSlot(QJsonValue)
    @pyqtSlot(dict)
    def updateMetricTargets(self, payload: Any) -> None:
        normalized = self._normalize_metric_targets_payload(payload)
        if normalized is not None:
            self.update_metric_targets_requested.emit(normalized)

    @pyqtSlot(str)
    def copyTextToClipboard(self, text: str) -> None:
        # Generic text-to-clipboard pipe. The frontend cannot rely on
        # navigator.clipboard / document.execCommand inside QtWebEngine
        # (sandbox / non-secure-context), so every copy-to-clipboard
        # button in the simulation panel funnels through this slot and
        # the host sets the system clipboard via QClipboard.
        self.text_clipboard_copy_requested.emit(str(text or ""))

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

    def _normalize_attachment_target(self, target: str) -> str:
        normalized = str(target or "metrics").strip().lower()
        allowed = {"metrics", "chart", "waveform", "output_log", "op_result"}
        return normalized if normalized in allowed else "metrics"

    def _normalize_metric_targets_payload(self, payload: Any) -> Optional[Dict[str, Any]]:
        if isinstance(payload, QJsonValue):
            payload = payload.toVariant()
        if not isinstance(payload, dict):
            return None
        raw_targets = payload.get("targets")
        if not isinstance(raw_targets, dict):
            return None
        cleaned: Dict[str, str] = {}
        for raw_name, raw_value in raw_targets.items():
            name = str(raw_name or "").strip()
            value = str(raw_value or "").strip()
            if name:
                cleaned[name] = value
        return {
            "source_file_path": str(payload.get("sourceFilePath") or ""),
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
        return {
            "x_min": x_min,
            "x_max": x_max,
            "left_y_min": left_y_min,
            "left_y_max": left_y_max,
            "right_y_min": float(right_y_min) if right_y_min is not None else None,
            "right_y_max": float(right_y_max) if right_y_max is not None else None,
        }


__all__ = ["SimulationWebBridge"]
