import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.simulation.data.op_result_data_builder import op_result_data_builder
from domain.simulation.data.png_metadata import inject_png_text_chunks
from domain.simulation.data.simulation_output_reader import simulation_output_reader
from domain.simulation.data.waveform_data_service import waveform_data_service
from domain.simulation.models.simulation_result import SimulationResult


EXPORT_SCHEMA_VERSION = 1
PROJECT_EXPORTS_DIR_NAME = "simulation_results"
DEFAULT_EXPORT_FOLDER_NAME = "simulation_result"


class SimulationArtifactExporter:
    def create_export_root(self, base_directory: str, result: SimulationResult) -> Path:
        export_root = self._build_export_root(base_directory, result)
        export_root.mkdir(parents=True, exist_ok=False)
        return export_root

    def create_project_export_root(self, project_root: str, result: SimulationResult) -> Path:
        export_root = self._build_export_root(Path(project_root) / PROJECT_EXPORTS_DIR_NAME, result)
        export_root.mkdir(parents=True, exist_ok=False)
        return export_root

    def _build_export_root(self, base_directory: str | Path, result: SimulationResult) -> Path:
        root = Path(base_directory)
        circuit_folder = self._format_circuit_folder(getattr(result, "file_path", ""))
        timestamp_folder = self._format_timestamp_folder(getattr(result, "timestamp", ""))
        return self._ensure_unique_directory(root / circuit_folder / timestamp_folder)

    def _format_circuit_folder(self, file_path: str) -> str:
        candidate = Path(file_path).stem if file_path else DEFAULT_EXPORT_FOLDER_NAME
        return self._sanitize_folder_name(candidate or DEFAULT_EXPORT_FOLDER_NAME)

    def dumps_json(self, payload: Dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def build_artifact_payload(
        self,
        result: SimulationResult,
        artifact_type: str,
        *,
        summary: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        metadata = self.build_result_metadata(result, artifact_type)
        if extra_metadata:
            metadata.update(extra_metadata)
        return {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "artifact_type": artifact_type,
            "metadata": metadata,
            "summary": summary or {},
            "files": files or {},
            "data": data or {},
        }

    def build_result_metadata(self, result: SimulationResult, artifact_type: str) -> Dict[str, Any]:
        return {
            "artifact_type": artifact_type,
            "file_name": Path(result.file_path).name if result.file_path else "",
            "file_path": result.file_path,
            "analysis_type": result.analysis_type,
            "timestamp": result.timestamp,
            "success": result.success,
            "executor": result.executor,
            "duration_seconds": result.duration_seconds,
            "analysis_command": result.analysis_command,
            "x_axis_kind": result.x_axis_kind,
            "x_axis_label": result.get_x_axis_label(),
            "x_axis_scale": result.x_axis_scale,
            "requested_x_range": self._serialize_range(result.requested_x_range),
            "actual_x_range": self._serialize_range(result.actual_x_range),
        }

    # ------------------------------------------------------------------
    # Circuit-linkage header helpers
    #
    # Every artifact we write — JSON, CSV, TXT, PNG — carries enough
    # metadata for an agent (or any downstream consumer) to trace the
    # file back to the originating circuit. JSON gets it via
    # ``metadata.*``; the other three formats use the helpers below so
    # there is a single authoritative source.
    # ------------------------------------------------------------------

    def build_linkage_entries(self, result: SimulationResult, artifact_type: str) -> List[tuple[str, str]]:
        """Canonical key/value pairs that link an artifact to its
        source circuit. Order is preserved so headers read top-down.
        """
        file_path = str(getattr(result, "file_path", "") or "")
        file_name = Path(file_path).name if file_path else ""
        return [
            ("artifact_type", str(artifact_type or "")),
            ("circuit_file", file_name),
            ("file_path", file_path),
            ("analysis_type", str(getattr(result, "analysis_type", "") or "")),
            ("executor", str(getattr(result, "executor", "") or "")),
            ("timestamp", str(getattr(result, "timestamp", "") or "")),
        ]

    def build_text_header_block(self, result: SimulationResult, artifact_type: str) -> str:
        """Return a ``# key: value``-style header block (with trailing
        blank line) suitable for prefixing TXT and CSV artifacts.

        The ``#`` prefix is chosen because:
        - TXT: ngspice output and op-result tables never start with
          ``#`` themselves, so the block is unambiguous.
        - CSV: pandas/duckdb/polars all honour ``comment='#'``; Excel
          will render the lines as data but still surfaces the link.
        """
        lines = [f"# {key}: {value}" for key, value in self.build_linkage_entries(result, artifact_type)]
        return "\n".join(lines) + "\n\n"

    def build_png_text_chunks(self, result: SimulationResult, artifact_type: str) -> Dict[str, str]:
        """Return tEXt chunk payload for PNG injection. Empty values
        are dropped — PNG tEXt requires non-empty keyword/value pairs
        to actually carry meaning.
        """
        return {
            key: value
            for key, value in self.build_linkage_entries(result, artifact_type)
            if value
        }

    def write_text_with_header(
        self,
        path: str | Path,
        result: SimulationResult,
        artifact_type: str,
        body: str,
    ) -> None:
        Path(path).write_text(
            self.build_text_header_block(result, artifact_type) + (body or ""),
            encoding="utf-8",
        )

    def write_csv_with_header(
        self,
        path: str | Path,
        result: SimulationResult,
        artifact_type: str,
        columns: List[str],
        rows: List[Dict[str, Any]],
    ) -> None:
        with Path(path).open("w", newline="", encoding="utf-8") as handle:
            handle.write(self.build_text_header_block(result, artifact_type))
            writer = csv.writer(handle)
            writer.writerow(columns)
            for row in rows:
                writer.writerow([row.get(column, "") for column in columns])

    def inject_png_linkage(self, path: str | Path, result: SimulationResult, artifact_type: str) -> bool:
        """Rewrite a PNG file in place with canonical circuit-linkage
        tEXt chunks. Returns ``True`` if the file was touched.
        """
        return inject_png_text_chunks(path, self.build_png_text_chunks(result, artifact_type))

    def export_metrics(self, export_root: Path, result: SimulationResult, metrics: List[Any]) -> List[str]:
        """Export the current ``DisplayMetric`` list as CSV + JSON side
        by side. Columns are restricted to fields that actually carry
        meaning to the agent / downstream pipeline. ``target`` is the
        user-authored goal string ingested from ``MetricTargetService``
        upstream, so the exported payload naturally carries target
        information and the agent sees goals alongside values.
        """
        category_dir = self._ensure_category_dir(export_root, "metrics")
        csv_path = category_dir / "metrics.csv"
        json_path = category_dir / "metrics.json"

        columns = [
            "display_name",
            "name",
            "value",
            "unit",
            "raw_value",
            "target",
        ]
        rows = [self._metric_to_row(metric) for metric in metrics]
        self.write_csv_with_header(csv_path, result, "metrics", columns, rows)

        self._write_json(json_path, self.build_artifact_payload(
            result=result,
            artifact_type="metrics",
            summary={
                "metric_count": len(rows),
                "metrics_with_target": sum(1 for row in rows if row.get("target")),
            },
            files={
                "csv": csv_path.name,
            },
            data={
                "columns": columns,
                "rows": rows,
            },
        ))
        return [str(csv_path), str(json_path)]

    def export_analysis_info(self, export_root: Path, result: SimulationResult) -> List[str]:
        category_dir = self._ensure_category_dir(export_root, "analysis_info")
        json_path = category_dir / "analysis_info.json"
        text_path = category_dir / "analysis_info.txt"

        payload = self._build_analysis_info_payload(result)
        self._write_json(json_path, self.build_artifact_payload(
            result,
            "analysis_info",
            summary={
                "parameter_count": len(payload.get("parameters") or {}),
            },
            files={
                "text": text_path.name,
            },
            data=payload,
        ))
        self.write_text_with_header(
            text_path,
            result,
            "analysis_info",
            self._build_analysis_info_text(payload),
        )
        return [str(json_path), str(text_path)]

    def export_raw_data(self, export_root: Path, result: SimulationResult) -> List[str]:
        category_dir = self._ensure_category_dir(export_root, "raw_data")
        csv_path = category_dir / "raw_data.csv"
        json_path = category_dir / "raw_data.json"

        snapshot = waveform_data_service.build_table_snapshot(result)
        x_label = snapshot.x_label if snapshot is not None else result.get_x_axis_label()
        signal_names = list(snapshot.signal_names) if snapshot is not None else []
        columns = [x_label, *signal_names]
        rows = self._build_snapshot_rows(snapshot)
        series = self._build_snapshot_series(snapshot)

        self.write_csv_with_header(csv_path, result, "raw_data", columns, rows)

        self._write_json(json_path, self.build_artifact_payload(
            result,
            "raw_data",
            summary={
                "row_count": len(rows),
                "signal_count": len(signal_names),
                "x_axis_label": x_label,
            },
            files={
                "csv": csv_path.name,
            },
            data={
                "columns": columns,
                "rows": rows,
                "series": series,
            },
        ))
        return [str(csv_path), str(json_path)]

    def export_output_log(self, export_root: Path, result: SimulationResult) -> List[str]:
        category_dir = self._ensure_category_dir(export_root, "output_log")
        text_path = category_dir / "output_log.txt"
        json_path = category_dir / "output_log.json"

        raw_output = getattr(result, "raw_output", None) or ""
        self.write_text_with_header(text_path, result, "output_log", raw_output)

        log_lines = simulation_output_reader.get_output_log_from_text(raw_output)
        error_count = sum(1 for line in log_lines if line.is_error())
        warning_count = sum(1 for line in log_lines if line.is_warning())
        info_count = len(log_lines) - error_count - warning_count
        first_error = next((line.content for line in log_lines if line.is_error()), None)
        self._write_json(json_path, self.build_artifact_payload(
            result,
            "output_log",
            summary={
                "total_lines": len(log_lines),
                "error_count": error_count,
                "warning_count": warning_count,
                "info_count": info_count,
                "first_error": first_error,
            },
            files={
                "text": text_path.name,
            },
            data={
                "raw_output": raw_output,
                "lines": [line.to_dict() for line in log_lines],
            },
        ))
        return [str(text_path), str(json_path)]

    def export_op_result(self, export_root: Path, result: SimulationResult) -> List[str]:
        if not op_result_data_builder.is_available(result):
            raise ValueError("OP result export is unavailable for the current simulation result")
        category_dir = self._ensure_category_dir(export_root, "op_result")
        json_path = category_dir / "op_result.json"
        text_path = category_dir / "op_result.txt"

        payload = op_result_data_builder.build(result)
        self.write_text_with_header(
            text_path,
            result,
            "op_result",
            op_result_data_builder.build_text(result),
        )
        self._write_json(json_path, self.build_artifact_payload(
            result,
            "op_result",
            summary={
                "row_count": int(payload.get("row_count", 0)),
                "section_count": int(payload.get("section_count", 0)),
            },
            files={
                "text": text_path.name,
            },
            data=payload,
        ))
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
            "raw_value": getattr(metric, "raw_value", None),
            "target": str(getattr(metric, "target", "") or ""),
        }

    def _build_snapshot_rows(self, snapshot) -> List[Dict[str, Any]]:
        if snapshot is None:
            return []

        rows: List[Dict[str, Any]] = []
        for row_index in range(snapshot.total_rows):
            row: Dict[str, Any] = {snapshot.x_label: float(snapshot.x_values[row_index])}
            for signal_name in snapshot.signal_names:
                column = snapshot.signal_columns.get(signal_name)
                if column is None or row_index >= len(column):
                    row[signal_name] = ""
                    continue
                raw_value = column[row_index]
                row[signal_name] = float(raw_value) if self._is_finite_number(raw_value) else ""
            rows.append(row)
        return rows

    def _build_snapshot_series(self, snapshot) -> List[Dict[str, Any]]:
        if snapshot is None:
            return []

        x_values = [float(value) for value in snapshot.x_values]
        series: List[Dict[str, Any]] = []
        for signal_name in snapshot.signal_names:
            column = snapshot.signal_columns.get(signal_name)
            values = []
            if column is not None:
                for raw_value in column:
                    values.append(float(raw_value) if self._is_finite_number(raw_value) else None)
            series.append({
                "name": signal_name,
                "x": x_values,
                "y": values,
                "point_count": len(values),
            })
        return series

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
        # circuit linkage (``file_name`` / ``file_path``) is emitted by
        # the authoritative header block — this body only carries the
        # analysis-specific fields to avoid duplication.
        lines = [
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
        safe = safe.replace(".", "_")
        return safe or "simulation_time_unknown"

    def _sanitize_folder_name(self, value: str) -> str:
        safe = re.sub(r'[<>:"/\\|?*]+', "_", str(value or "").strip())
        safe = safe.rstrip(" .")
        return safe or DEFAULT_EXPORT_FOLDER_NAME

    def _ensure_unique_directory(self, path: Path) -> Path:
        if not path.exists():
            return path
        suffix = 2
        while True:
            candidate = path.with_name(f"{path.name}_{suffix}")
            if not candidate.exists():
                return candidate
            suffix += 1

    def _write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.write_text(self.dumps_json(payload), encoding="utf-8")

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
