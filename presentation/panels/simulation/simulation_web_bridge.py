from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, QJsonValue, pyqtSignal, pyqtSlot


class SimulationWebBridge(QObject):
    ready = pyqtSignal()
    activate_tab_requested = pyqtSignal(str)
    load_history_result_requested = pyqtSignal(str)
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
    output_log_jump_to_error_requested = pyqtSignal()
    output_log_refresh_requested = pyqtSignal()
    export_requested = pyqtSignal(list)
    add_to_conversation_requested = pyqtSignal(str)

    @pyqtSlot()
    def markReady(self) -> None:
        self.ready.emit()

    @pyqtSlot(str)
    def activateTab(self, tab_id: str) -> None:
        self.activate_tab_requested.emit(self._normalize_tab_id(tab_id))

    @pyqtSlot(str)
    def loadHistoryResult(self, result_path: str) -> None:
        self.load_history_result_requested.emit(str(result_path or ""))

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

    @pyqtSlot()
    def jumpToOutputLogError(self) -> None:
        self.output_log_jump_to_error_requested.emit()

    @pyqtSlot()
    def refreshOutputLog(self) -> None:
        self.output_log_refresh_requested.emit()

    @pyqtSlot(QJsonValue)
    @pyqtSlot(list)
    def requestExport(self, export_types: Any) -> None:
        normalized = self._normalize_list_payload(export_types)
        self.export_requested.emit(normalized)

    @pyqtSlot(str)
    def addToConversation(self, target: str) -> None:
        self.add_to_conversation_requested.emit(self._normalize_attachment_target(target))

    def _normalize_list_payload(self, payload: Any) -> List[str]:
        if isinstance(payload, QJsonValue):
            payload = payload.toVariant()
        if not isinstance(payload, list):
            return []
        normalized: List[str] = []
        for item in payload:
            value = str(item or "").strip()
            if value:
                normalized.append(value)
        return normalized

    def _normalize_tab_id(self, tab_id: str) -> str:
        normalized = str(tab_id or "metrics").strip().lower()
        allowed = {
            "metrics",
            "chart",
            "waveform",
            "analysis_info",
            "raw_data",
            "output_log",
            "export",
            "history",
            "op_result",
        }
        return normalized if normalized in allowed else "metrics"

    def _normalize_cursor_id(self, cursor_id: str) -> str:
        normalized = str(cursor_id or "a").strip().lower()
        return normalized if normalized in {"a", "b"} else "a"

    def _normalize_attachment_target(self, target: str) -> str:
        normalized = str(target or "metrics").strip().lower()
        allowed = {"metrics", "chart", "waveform", "output_log", "op_result"}
        return normalized if normalized in allowed else "metrics"

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
