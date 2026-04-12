from __future__ import annotations

from typing import Any, List

from PyQt6.QtCore import QObject, QJsonValue, pyqtSignal, pyqtSlot


class SimulationWebBridge(QObject):
    ready = pyqtSignal()
    activate_tab_requested = pyqtSignal(str)
    load_history_result_requested = pyqtSignal(str)
    chart_series_visibility_toggled = pyqtSignal(str, bool)
    clear_all_chart_series_requested = pyqtSignal()
    chart_measurement_enabled_changed = pyqtSignal(bool)
    chart_measurement_cursor_move_requested = pyqtSignal(str, float)
    chart_data_cursor_enabled_changed = pyqtSignal(bool)
    chart_fit_requested = pyqtSignal()
    signal_visibility_toggled = pyqtSignal(str, bool)
    clear_all_signals_requested = pyqtSignal()
    cursor_visibility_toggled = pyqtSignal(str, bool)
    cursor_move_requested = pyqtSignal(str, float)
    fit_requested = pyqtSignal()
    zoom_to_range_requested = pyqtSignal(float, float)
    raw_data_jump_to_row_requested = pyqtSignal(int)
    raw_data_jump_to_x_requested = pyqtSignal(float)
    raw_data_value_search_requested = pyqtSignal(int, float, float)
    raw_data_shift_signal_window_requested = pyqtSignal(int)
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
    def setChartDataCursorEnabled(self, enabled: bool) -> None:
        self.chart_data_cursor_enabled_changed.emit(bool(enabled))

    @pyqtSlot()
    def fitChart(self) -> None:
        self.chart_fit_requested.emit()

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

    @pyqtSlot()
    def requestFit(self) -> None:
        self.fit_requested.emit()

    @pyqtSlot(float, float)
    def zoomToRange(self, start: float, end: float) -> None:
        self.zoom_to_range_requested.emit(float(start or 0.0), float(end or 0.0))

    @pyqtSlot(int)
    def jumpRawDataToRow(self, row: int) -> None:
        normalized_row = max(1, int(row or 0)) - 1
        self.raw_data_jump_to_row_requested.emit(normalized_row)

    @pyqtSlot(float)
    def jumpRawDataToX(self, x_value: float) -> None:
        self.raw_data_jump_to_x_requested.emit(float(x_value or 0.0))

    @pyqtSlot(int, float, float)
    def searchRawDataValue(self, column: int, value: float, tolerance: float) -> None:
        self.raw_data_value_search_requested.emit(
            max(0, int(column or 0)),
            float(value or 0.0),
            max(0.0, float(tolerance or 0.0)),
        )

    @pyqtSlot(int)
    def shiftRawDataSignalWindow(self, page_delta: int) -> None:
        normalized_delta = int(page_delta or 0)
        if normalized_delta == 0:
            return
        self.raw_data_shift_signal_window_requested.emit(1 if normalized_delta > 0 else -1)

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


__all__ = ["SimulationWebBridge"]
