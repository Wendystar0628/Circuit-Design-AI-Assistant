from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from domain.simulation.data.op_result_data_builder import op_result_data_builder
from domain.simulation.models.simulation_result import SimulationResult
from presentation.panels.simulation.simulation_view_model import DisplayMetric


class SimulationFrontendStateSerializer:
    _BASE_TABS = [
        "metrics",
        "chart",
        "waveform",
        "analysis_info",
        "raw_data",
        "output_log",
        "export",
    ]
    _EXPORT_TYPES = [
        "metrics",
        "charts",
        "waveforms",
        "analysis_info",
        "raw_data",
        "output_log",
        "op_result",
    ]
    _ANALYSIS_LABELS = {
        "ac": "AC 小信号分析",
        "dc": "DC 扫描分析",
        "tran": "瞬态分析",
        "noise": "噪声分析",
        "op": "工作点分析",
    }

    def serialize_main_state(
        self,
        *,
        project_root: str = "",
        active_tab: str = "metrics",
        current_result: Optional[SimulationResult] = None,
        current_result_path: str = "",
        metrics: Optional[Sequence[DisplayMetric]] = None,
        overall_score: float = 0.0,
        has_goals: bool = False,
        simulation_status: Any = "idle",
        status_message: str = "",
        error_message: str = "",
        history_results: Optional[Sequence[Dict[str, Any]]] = None,
        latest_project_export_root: str = "",
        awaiting_confirmation: bool = False,
        analysis_chart_snapshot: Optional[Dict[str, Any]] = None,
        waveform_snapshot: Optional[Dict[str, Any]] = None,
        raw_data_snapshot: Optional[Dict[str, Any]] = None,
        output_log_snapshot: Optional[Dict[str, Any]] = None,
        export_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        result = current_result if isinstance(current_result, SimulationResult) else None
        normalized_metrics = [
            self.serialize_metric(metric) for metric in (metrics or []) if isinstance(metric, DisplayMetric)
        ]
        available_tabs = list(self._BASE_TABS)
        if project_root:
            available_tabs.append("history")
        if self._has_op_result(result):
            available_tabs.append("op_result")
        status_phase = self._resolve_status_phase(simulation_status, awaiting_confirmation)
        normalized_active_tab = active_tab if active_tab in available_tabs else "metrics"
        normalized_result_path = self._normalize_result_path(current_result_path)
        normalized_history = [
            self.serialize_history_item(item, current_result_path=normalized_result_path)
            for item in (history_results or [])
            if isinstance(item, dict)
        ]
        has_result = result is not None
        signal_names = self._signal_names(result)
        has_waveform = bool(signal_names)
        has_chart = self._has_chart(result)
        raw_data_snapshot_payload = raw_data_snapshot if isinstance(raw_data_snapshot, dict) else None
        output_log_snapshot_payload = output_log_snapshot if isinstance(output_log_snapshot, dict) else None
        export_snapshot_payload = export_snapshot if isinstance(export_snapshot, dict) else None
        has_output_log = bool(output_log_snapshot_payload.get("has_log")) if output_log_snapshot_payload is not None else bool(getattr(result, "raw_output", None))
        has_op_result = self._has_op_result(result)
        result_summary = self.serialize_result(result, normalized_result_path)
        op_result_view = self.serialize_op_result(result)
        available_export_types = [
            export_type
            for export_type in self._EXPORT_TYPES
            if export_type != "op_result" or has_op_result
        ]

        analysis_chart_view = {
            "has_chart": has_chart,
            "chart_count": 1 if has_chart else 0,
            "can_export": has_chart,
            "can_add_to_conversation": has_chart,
            "title": "",
            "chart_type": "",
            "chart_type_display_name": "",
            "x_label": "",
            "y_label": "",
            "secondary_y_label": "",
            "log_x": False,
            "log_y": False,
            "right_log_y": False,
            "available_series": [],
            "visible_series": [],
            "visible_series_count": 0,
            "viewport": {
                "active": False,
                "x_min": None,
                "x_max": None,
                "left_y_min": None,
                "left_y_max": None,
                "right_y_min": None,
                "right_y_max": None,
            },
            "measurement_point": {
                "enabled": False,
                "target_id": "",
                "point_x": None,
                "title": "",
                "plot_series_name": "",
                "plot_axis_key": "left",
                "plot_y": None,
                "values": [],
            },
            "measurement_enabled": False,
            "measurement": {
                "cursor_a_x": None,
                "cursor_b_x": None,
                "values_a": {},
                "values_b": {},
            },
        }
        waveform_view = {
            "has_waveform": has_waveform,
            "signal_count": len(signal_names),
            "signal_names": signal_names,
            "can_export": has_waveform,
            "can_add_to_conversation": has_waveform,
            "displayed_signal_names": [],
            "signal_catalog": [],
            "visible_series": [],
            "x_axis_label": "",
            "y_label": "",
            "secondary_y_label": "",
            "log_x": False,
            "viewport": {
                "active": False,
                "x_min": None,
                "x_max": None,
                "left_y_min": None,
                "left_y_max": None,
                "right_y_min": None,
                "right_y_max": None,
            },
            "cursor_a_visible": False,
            "cursor_b_visible": False,
            "measurement": {
                "cursor_a_x": None,
                "cursor_b_x": None,
                "values_a": {},
                "values_b": {},
            },
        }
        raw_data_view = {
            "has_data": bool(raw_data_snapshot_payload.get("has_data")) if raw_data_snapshot_payload is not None else bool(result is not None and getattr(result, "data", None) is not None),
            "row_count": int(raw_data_snapshot_payload.get("row_count") or 0) if raw_data_snapshot_payload is not None else self._row_count(result),
            "signal_count": int(raw_data_snapshot_payload.get("signal_count") or 0) if raw_data_snapshot_payload is not None else len(signal_names),
            "x_axis_label": str(raw_data_snapshot_payload.get("x_axis_label") or "") if raw_data_snapshot_payload is not None else str(getattr(result, "x_axis_label", "") or ""),
            "result_binding_text": str(raw_data_snapshot_payload.get("result_binding_text") or "") if raw_data_snapshot_payload is not None else "",
            "visible_columns": [],
            "rows": [],
            "window_start": 0,
            "window_end": 0,
            "has_more_before": False,
            "has_more_after": False,
            "selected_row_numbers": [],
            "selection_count": 0,
            "visible_signal_start": 0,
            "visible_signal_end": 0,
            "visible_signal_count": 0,
            "has_more_signal_columns_before": False,
            "has_more_signal_columns_after": False,
        }
        output_log_view = {
            "has_log": bool(output_log_snapshot_payload.get("has_log")) if output_log_snapshot_payload is not None else has_output_log,
            "can_add_to_conversation": bool(output_log_snapshot_payload.get("can_add_to_conversation")) if output_log_snapshot_payload is not None else has_output_log,
            "current_filter": "all",
            "search_keyword": "",
            "lines": [],
            "selected_line_number": None,
        }
        if isinstance(analysis_chart_snapshot, dict):
            analysis_chart_view.update(analysis_chart_snapshot)
        if isinstance(waveform_snapshot, dict):
            waveform_view.update(waveform_snapshot)
        if isinstance(raw_data_snapshot, dict):
            raw_data_view.update(raw_data_snapshot)
        if isinstance(output_log_snapshot, dict):
            output_log_view.update(output_log_snapshot)

        export_view = {
            "has_result": has_result,
            "can_export": False,
            "items": [
                {
                    "id": export_type,
                    "label": export_type,
                    "selected": True,
                    "enabled": True,
                }
                for export_type in available_export_types
            ] if has_result else [],
            "selected_directory": "",
            "latest_project_export_root": str(latest_project_export_root or ""),
        }
        if export_snapshot_payload is not None:
            export_view.update(export_snapshot_payload)

        return {
            "simulation_runtime": {
                "status": status_phase,
                "status_message": str(status_message or ""),
                "error_message": str(error_message or ""),
                "project_root": str(project_root or ""),
                "has_project": bool(project_root),
                "current_result_path": normalized_result_path,
                "is_empty": not has_result,
                "has_result": has_result,
                "has_error": bool(error_message),
                "awaiting_confirmation": bool(awaiting_confirmation),
                "current_result": result_summary,
            },
            "surface_tabs": {
                "active_tab": normalized_active_tab,
                "available_tabs": available_tabs,
                "has_history": bool(project_root),
                "has_op_result": self._has_op_result(result),
            },
            "metrics_view": {
                "items": normalized_metrics,
                "total": len(normalized_metrics),
                "overall_score": float(overall_score or 0.0),
                "has_goals": bool(has_goals),
                "can_add_to_conversation": has_result,
            },
            "analysis_chart_view": analysis_chart_view,
            "waveform_view": waveform_view,
            "analysis_info_view": self.serialize_analysis_info(result),
            "raw_data_view": raw_data_view,
            "output_log_view": output_log_view,
            "export_view": export_view,
            "history_results_view": {
                "items": normalized_history,
                "selected_result_path": normalized_result_path,
                "can_load": bool(project_root),
            },
            "op_result_view": op_result_view,
        }

    def serialize_metric(self, metric: DisplayMetric) -> Dict[str, Any]:
        return {
            "name": metric.name,
            "display_name": metric.display_name,
            "value": metric.value,
            "unit": metric.unit,
            "target": metric.target,
            "is_met": metric.is_met,
            "trend": metric.trend,
            "category": metric.category,
            "raw_value": metric.raw_value,
            "confidence": metric.confidence,
            "error_message": metric.error_message,
        }

    def serialize_result(
        self,
        result: Optional[SimulationResult],
        current_result_path: str,
    ) -> Dict[str, Any]:
        if result is None:
            return {
                "has_result": False,
                "result_path": "",
                "file_path": "",
                "file_name": "",
                "analysis_type": "",
                "analysis_label": "",
                "executor": "",
                "success": False,
                "timestamp": "",
                "duration_seconds": 0.0,
                "version": 0,
                "session_id": "",
                "x_axis_kind": "",
                "x_axis_label": "",
                "x_axis_scale": "",
                "requested_x_range": None,
                "actual_x_range": None,
                "has_raw_output": False,
            }
        return {
            "has_result": True,
            "result_path": current_result_path,
            "file_path": str(result.file_path or ""),
            "file_name": Path(str(result.file_path or "")).name if str(result.file_path or "") else "",
            "analysis_type": str(result.analysis_type or ""),
            "analysis_label": self._ANALYSIS_LABELS.get(str(result.analysis_type or "").lower(), str(result.analysis_type or "")),
            "executor": str(result.executor or ""),
            "success": bool(result.success),
            "timestamp": str(result.timestamp or ""),
            "duration_seconds": float(result.duration_seconds or 0.0),
            "version": int(result.version or 0),
            "session_id": str(result.session_id or ""),
            "x_axis_kind": str(result.x_axis_kind or ""),
            "x_axis_label": str(result.x_axis_label or ""),
            "x_axis_scale": str(result.x_axis_scale or ""),
            "requested_x_range": self._range_to_list(result.requested_x_range),
            "actual_x_range": self._range_to_list(result.actual_x_range),
            "has_raw_output": bool(getattr(result, "raw_output", None)),
        }

    def serialize_analysis_info(self, result: Optional[SimulationResult]) -> Dict[str, Any]:
        if result is None:
            return {
                "analysis_type": "",
                "analysis_command": "",
                "executor": "",
                "file_name": "",
                "x_axis_kind": "",
                "x_axis_label": "",
                "x_axis_scale": "",
                "requested_x_range": None,
                "actual_x_range": None,
                "parameters": {},
            }
        info = result.analysis_info if isinstance(result.analysis_info, dict) else {}
        return {
            "analysis_type": str(info.get("analysis_type") or result.analysis_type or ""),
            "analysis_command": str(info.get("analysis_command") or result.analysis_command or ""),
            "executor": str(result.executor or ""),
            "file_name": Path(str(result.file_path or "")).name if str(result.file_path or "") else "",
            "x_axis_kind": str(info.get("x_axis_kind") or result.x_axis_kind or ""),
            "x_axis_label": str(info.get("x_axis_label") or result.x_axis_label or ""),
            "x_axis_scale": str(info.get("x_axis_scale") or result.x_axis_scale or ""),
            "requested_x_range": self._range_to_list(info.get("requested_x_range") or result.requested_x_range),
            "actual_x_range": self._range_to_list(info.get("actual_x_range") or result.actual_x_range),
            "parameters": dict(info.get("parameters") or {}),
        }

    def serialize_history_item(
        self,
        item: Dict[str, Any],
        *,
        current_result_path: str,
    ) -> Dict[str, Any]:
        result_path = self._normalize_result_path(str(item.get("path", "") or ""))
        return {
            "id": str(item.get("id", "") or ""),
            "result_path": result_path,
            "file_path": str(item.get("file_path", "") or ""),
            "file_name": Path(str(item.get("file_path", "") or "")).name if str(item.get("file_path", "") or "") else "",
            "analysis_type": str(item.get("analysis_type", "") or ""),
            "success": bool(item.get("success", False)),
            "timestamp": str(item.get("timestamp", "") or ""),
            "is_current": bool(result_path and result_path == current_result_path),
            "can_load": bool(result_path),
        }

    def serialize_op_result(self, result: Optional[SimulationResult]) -> Dict[str, Any]:
        payload = op_result_data_builder.build(result)
        return {
            **payload,
            "can_add_to_conversation": bool(payload.get("is_available", False)),
        }

    def _resolve_status_phase(self, simulation_status: Any, awaiting_confirmation: bool) -> str:
        if awaiting_confirmation:
            return "awaiting_confirmation"
        raw_value = getattr(simulation_status, "value", simulation_status)
        normalized = str(raw_value or "idle").lower()
        if normalized in {"idle", "running", "complete", "error"}:
            return normalized
        return "idle"

    def _has_waveform(self, result: Optional[SimulationResult]) -> bool:
        return bool(self._signal_names(result))

    def _has_chart(self, result: Optional[SimulationResult]) -> bool:
        if result is None or not result.success or getattr(result, "data", None) is None:
            return False
        return str(result.analysis_type or "").lower() != "op"

    def _has_op_result(self, result: Optional[SimulationResult]) -> bool:
        return bool(op_result_data_builder.is_available(result))

    def _signal_names(self, result: Optional[SimulationResult]) -> List[str]:
        data = getattr(result, "data", None) if result is not None else None
        if data is None or not hasattr(data, "get_signal_names"):
            return []
        try:
            names = data.get_signal_names()
        except Exception:
            return []
        return [str(name or "") for name in names if str(name or "")]

    def _row_count(self, result: Optional[SimulationResult]) -> int:
        data = getattr(result, "data", None) if result is not None else None
        if data is None:
            return 0
        for axis_name in ("time", "frequency", "sweep"):
            axis_values = getattr(data, axis_name, None)
            if axis_values is not None:
                try:
                    return int(len(axis_values))
                except Exception:
                    return 0
        signal_names = self._signal_names(result)
        if not signal_names or not hasattr(data, "get_signal"):
            return 0
        try:
            signal = data.get_signal(signal_names[0])
            return int(len(signal)) if signal is not None else 0
        except Exception:
            return 0

    def _range_to_list(self, value: Any) -> Optional[List[float]]:
        if not isinstance(value, (tuple, list)) or len(value) != 2:
            return None
        try:
            return [float(value[0]), float(value[1])]
        except (TypeError, ValueError):
            return None

    def _normalize_result_path(self, value: str) -> str:
        return str(value or "").replace("\\", "/").lower()


__all__ = ["SimulationFrontendStateSerializer"]
