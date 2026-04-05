import csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from domain.simulation.data.simulation_output_reader import simulation_output_reader
from domain.simulation.data.waveform_data_service import waveform_data_service
from domain.simulation.models.simulation_result import SimulationResult


class SimulationArtifactExporter:
    def __init__(self):
        self._logger = logging.getLogger(__name__)

    def create_export_root(self, base_directory: str, result: SimulationResult) -> Path:
        root = Path(base_directory)
        circuit_folder = (Path(result.file_path).name if result.file_path else "simulation_result") or "simulation_result"
        timestamp_folder = self.format_timestamp_folder(getattr(result, "timestamp", ""))
        export_root = root / circuit_folder / timestamp_folder
        export_root.mkdir(parents=True, exist_ok=True)
        return export_root

    def format_timestamp_folder(self, timestamp: str) -> str:
        return self._format_timestamp_folder(timestamp)

    def export_metrics(self, export_root: Path, metrics: List[Any], overall_score: float) -> List[str]:
        category_dir = self._ensure_category_dir(export_root, "metrics")
        csv_path = category_dir / "metrics.csv"
        json_path = category_dir / "metrics.json"

        rows = [self._metric_to_row(metric) for metric in metrics]
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                "display_name",
                "name",
                "value",
                "unit",
                "target",
                "is_met",
                "trend",
                "category",
                "raw_value",
                "confidence",
                "error_message",
            ])
            for row in rows:
                writer.writerow([
                    row["display_name"],
                    row["name"],
                    row["value"],
                    row["unit"],
                    row["target"],
                    row["is_met"],
                    row["trend"],
                    row["category"],
                    row["raw_value"],
                    row["confidence"],
                    row["error_message"],
                ])

        self._write_json(json_path, {
            "overall_score": overall_score,
            "metric_count": len(rows),
            "metrics": rows,
        })
        return [str(csv_path), str(json_path)]

    def export_analysis_info(self, export_root: Path, result: SimulationResult) -> List[str]:
        category_dir = self._ensure_category_dir(export_root, "analysis_info")
        json_path = category_dir / "analysis_info.json"
        text_path = category_dir / "analysis_info.txt"

        payload = self._build_analysis_info_payload(result)
        self._write_json(json_path, payload)
        text_path.write_text(self._build_analysis_info_text(payload), encoding="utf-8")
        return [str(json_path), str(text_path)]

    def export_raw_data(self, export_root: Path, result: SimulationResult) -> List[str]:
        category_dir = self._ensure_category_dir(export_root, "raw_data")
        csv_path = category_dir / "raw_data.csv"
        json_path = category_dir / "raw_data.json"

        snapshot = waveform_data_service.build_table_snapshot(result)
        if snapshot is None:
            self._write_json(json_path, {
                "analysis_type": result.analysis_type,
                "x_label": result.get_x_axis_label(),
                "signal_names": [],
                "total_rows": 0,
            })
            csv_path.write_text("", encoding="utf-8")
            return [str(csv_path), str(json_path)]

        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow([snapshot.x_label, *snapshot.signal_names])
            for row_index in range(snapshot.total_rows):
                row = [float(snapshot.x_values[row_index])]
                for signal_name in snapshot.signal_names:
                    column = snapshot.signal_columns.get(signal_name)
                    if column is None or row_index >= len(column):
                        row.append("")
                        continue
                    raw_value = column[row_index]
                    row.append(float(raw_value) if self._is_finite_number(raw_value) else "")
                writer.writerow(row)

        self._write_json(json_path, {
            "analysis_type": snapshot.analysis_type,
            "x_label": snapshot.x_label,
            "signal_names": snapshot.signal_names,
            "total_rows": snapshot.total_rows,
            "result_path": snapshot.result_path,
            "timestamp": snapshot.timestamp,
        })
        return [str(csv_path), str(json_path)]

    def export_output_log(self, export_root: Path, result: SimulationResult) -> List[str]:
        category_dir = self._ensure_category_dir(export_root, "output_log")
        text_path = category_dir / "output_log.txt"
        json_path = category_dir / "output_log_summary.json"

        raw_output = getattr(result, "raw_output", None) or ""
        text_path.write_text(raw_output, encoding="utf-8")

        log_lines = simulation_output_reader.get_output_log_from_text(raw_output)
        error_count = sum(1 for line in log_lines if line.is_error())
        warning_count = sum(1 for line in log_lines if line.is_warning())
        self._write_json(json_path, {
            "total_lines": len(log_lines),
            "error_count": error_count,
            "warning_count": warning_count,
            "info_count": len(log_lines) - error_count - warning_count,
        })
        return [str(text_path), str(json_path)]

    def _ensure_category_dir(self, export_root: Path, category_name: str) -> Path:
        category_dir = export_root / category_name
        category_dir.mkdir(parents=True, exist_ok=True)
        return category_dir

    def _metric_to_row(self, metric: Any) -> Dict[str, Any]:
        return {
            "display_name": str(getattr(metric, "display_name", "") or ""),
            "name": str(getattr(metric, "name", "") or ""),
            "value": str(getattr(metric, "value", "") or ""),
            "unit": str(getattr(metric, "unit", "") or ""),
            "target": str(getattr(metric, "target", "") or ""),
            "is_met": getattr(metric, "is_met", None),
            "trend": str(getattr(metric, "trend", "") or ""),
            "category": str(getattr(metric, "category", "") or ""),
            "raw_value": getattr(metric, "raw_value", None),
            "confidence": getattr(metric, "confidence", None),
            "error_message": str(getattr(metric, "error_message", "") or ""),
        }

    def _build_analysis_info_payload(self, result: SimulationResult) -> Dict[str, Any]:
        info = result.analysis_info if isinstance(result.analysis_info, dict) else {}
        parameters = info.get("parameters") if isinstance(info.get("parameters"), dict) else {}
        return {
            "analysis_type": info.get("analysis_type") or result.analysis_type,
            "executor": result.executor,
            "file_name": Path(result.file_path).name if result.file_path else "",
            "file_path": result.file_path,
            "success": result.success,
            "timestamp": result.timestamp,
            "duration_seconds": result.duration_seconds,
            "analysis_command": result.analysis_command,
            "x_axis_kind": info.get("x_axis_kind") or result.x_axis_kind,
            "x_axis_label": info.get("x_axis_label") or result.x_axis_label,
            "x_axis_scale": info.get("x_axis_scale") or result.x_axis_scale,
            "requested_x_range": self._serialize_range(info.get("requested_x_range") or result.requested_x_range),
            "actual_x_range": self._serialize_range(info.get("actual_x_range") or result.actual_x_range),
            "parameters": parameters,
        }

    def _build_analysis_info_text(self, payload: Dict[str, Any]) -> str:
        lines = [
            f"analysis_type: {payload.get('analysis_type', '')}",
            f"executor: {payload.get('executor', '')}",
            f"file_name: {payload.get('file_name', '')}",
            f"timestamp: {payload.get('timestamp', '')}",
            f"analysis_command: {payload.get('analysis_command', '')}",
            f"x_axis_kind: {payload.get('x_axis_kind', '')}",
            f"x_axis_label: {payload.get('x_axis_label', '')}",
            f"x_axis_scale: {payload.get('x_axis_scale', '')}",
            f"requested_x_range: {payload.get('requested_x_range', '')}",
            f"actual_x_range: {payload.get('actual_x_range', '')}",
            "",
            "parameters:",
        ]
        for key, value in (payload.get("parameters") or {}).items():
            lines.append(f"  {key}: {value}")
        return "\n".join(lines).strip()

    def _serialize_range(self, value: Any) -> List[float] | None:
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return None
        try:
            return [float(value[0]), float(value[1])]
        except (TypeError, ValueError):
            return None

    def _format_timestamp_folder(self, timestamp: str) -> str:
        candidate = str(timestamp or "").strip()
        if not candidate:
            return "simulation_time_unknown"
        safe = candidate.replace(":", "-").replace("T", "_")
        safe = safe.replace("/", "-").replace("\\", "-")
        safe = safe.replace("+", "_").replace("Z", "")
        safe = safe.split(".")[0]
        return safe or "simulation_time_unknown"

    def _write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _is_finite_number(self, value: Any) -> bool:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        return number == number and number not in (float("inf"), float("-inf"))


simulation_artifact_exporter = SimulationArtifactExporter()

__all__ = [
    "SimulationArtifactExporter",
    "simulation_artifact_exporter",
]
