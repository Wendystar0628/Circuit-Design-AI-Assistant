import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Final, List, Optional, Tuple

from domain.simulation.data.op_result_data_builder import op_result_data_builder
from domain.simulation.data.png_metadata import inject_png_text_chunks
from domain.simulation.data.simulation_output_reader import simulation_output_reader
from domain.simulation.data.waveform_data_service import waveform_data_service
from domain.simulation.models.simulation_result import SimulationResult


EXPORT_SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Canonical disk layout — SINGLE source of truth for Step 15's
# "stable artifact layout schema".
#
# Every simulation bundle — whether produced by the headless service,
# the UI Run button, or an agent tool — lives at
# ``<project_root>/<CANONICAL_RESULTS_DIR>/<stem>/<ts>/``. Under that
# ``export_root`` the layout is fixed and exposed only through the
# ``*_paths(export_root)`` helpers further down this file.
#
# Downstream modules (persistence, UI coordinators, bundle builders,
# agent read tools, tests) MUST call those helpers to obtain paths.
# Direct string concatenation like
# ``export_root / "metrics" / "metrics.json"`` is a contract violation:
# the grep-proof constraint in Step 15 of
# ``AGENT_SIMULATION_TOOL_IMPLEMENTATION_PLAN.md`` states those literals
# may appear only in this file and in the plan's schema section.
# ---------------------------------------------------------------------------
CANONICAL_RESULTS_DIR: Final[str] = "simulation_results"

DEFAULT_EXPORT_FOLDER_NAME: Final[str] = "simulation_result"

# Bundle root filename: every bundle's ``SimulationResult`` is serialised
# here and all addressing flows through a ``result_path`` pointing at it.
RESULT_JSON_FILENAME: Final[str] = "result.json"

# Bundle root manifest filename: emitted by both headless persistence
# (``SimulationArtifactPersistence``) and the UI-triggered export
# coordinator. Two writers, same filename, one schema.
EXPORT_MANIFEST_FILENAME: Final[str] = "export_manifest.json"

# Artifact-type tag for the manifest payload itself (keeps all
# ``artifact_type`` values authored in this file, not strewn across
# persistence / coordinator code).
ARTIFACT_TYPE_EXPORT_MANIFEST: Final[str] = "export_manifest"

# ---- Canonical category names ----
#
# These names are simultaneously:
#   1. The disk subdirectory names under ``export_root``
#   2. The UI export-picker keys (ExportPanel, frontend state serializer)
#   3. The keys used to index ``BundlePersistenceResult.category_files``
# The three roles are deliberately unified — no translation layer means
# no drift between "user picked X", "bundle has subdir X/", and
# "persistence reports category X".

CATEGORY_METRICS:       Final[str] = "metrics"
CATEGORY_ANALYSIS_INFO: Final[str] = "analysis_info"
CATEGORY_RAW_DATA:      Final[str] = "raw_data"
CATEGORY_OUTPUT_LOG:    Final[str] = "output_log"
CATEGORY_OP_RESULT:     Final[str] = "op_result"
CATEGORY_CHARTS:        Final[str] = "charts"
CATEGORY_WAVEFORMS:     Final[str] = "waveforms"

# category name -> disk subdir name. The identity mapping is intentional:
# renaming a subdir in the future only requires editing this dict, not
# hunting every consumer. Any new category must also add a matching
# ``*_paths`` helper below — a bare entry here without a helper is a
# half-implemented contract.
_CANONICAL_SUBDIRS: Final[Dict[str, str]] = {
    CATEGORY_METRICS:       CATEGORY_METRICS,
    CATEGORY_ANALYSIS_INFO: CATEGORY_ANALYSIS_INFO,
    CATEGORY_RAW_DATA:      CATEGORY_RAW_DATA,
    CATEGORY_OUTPUT_LOG:    CATEGORY_OUTPUT_LOG,
    CATEGORY_OP_RESULT:     CATEGORY_OP_RESULT,
    CATEGORY_CHARTS:        CATEGORY_CHARTS,
    CATEGORY_WAVEFORMS:     CATEGORY_WAVEFORMS,
}

# Ordered tuples for the two consumption modes. Persistence (headless)
# never writes chart/waveform PNGs — those are UI-side display snapshots.
# The ExportPanel (display) can additionally trigger chart / waveform
# bundles on top of the headless set.
HEADLESS_ARTIFACT_CATEGORIES: Final[Tuple[str, ...]] = (
    CATEGORY_METRICS,
    CATEGORY_ANALYSIS_INFO,
    CATEGORY_RAW_DATA,
    CATEGORY_OUTPUT_LOG,
    CATEGORY_OP_RESULT,
)

DISPLAY_EXPORT_CATEGORIES: Final[Tuple[str, ...]] = (
    CATEGORY_METRICS,
    CATEGORY_CHARTS,
    CATEGORY_WAVEFORMS,
    CATEGORY_ANALYSIS_INFO,
    CATEGORY_RAW_DATA,
    CATEGORY_OUTPUT_LOG,
    CATEGORY_OP_RESULT,
)


# ---------------------------------------------------------------------------
# Typed path bundles — one dataclass per artifact category
#
# Each dataclass exposes every canonical file path a consumer would need
# for that category. Using a dataclass (rather than a single dict or a
# ``get_path(category, kind)`` multiplexer) gives every caller static
# attribute-typed access and forbids the "kind: str" polymorphism Step 15
# explicitly bans.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricsArtifactPaths:
    """Canonical paths for the ``metrics`` artifact category."""
    directory: Path
    csv_path: Path
    json_path: Path


@dataclass(frozen=True)
class AnalysisInfoArtifactPaths:
    """Canonical paths for the ``analysis_info`` artifact category."""
    directory: Path
    json_path: Path
    text_path: Path


@dataclass(frozen=True)
class RawDataArtifactPaths:
    """Canonical paths for the ``raw_data`` artifact category."""
    directory: Path
    csv_path: Path
    json_path: Path


@dataclass(frozen=True)
class OutputLogArtifactPaths:
    """Canonical paths for the ``output_log`` artifact category."""
    directory: Path
    text_path: Path
    json_path: Path


@dataclass(frozen=True)
class OpResultArtifactPaths:
    """Canonical paths for the ``op_result`` artifact category."""
    directory: Path
    text_path: Path
    json_path: Path


@dataclass(frozen=True)
class ChartsArtifactPaths:
    """Canonical paths for the ``charts`` artifact category.

    The ``charts/`` subdirectory holds one triplet (``{idx:02d}_{type}``
    ``.png`` / ``.csv`` / ``.json``) per displayed chart plus a single
    ``charts.json`` manifest listing them. A one-shot conversation
    snapshot also lives here (``current_chart.png``).
    """
    directory: Path
    manifest_json_path: Path
    conversation_snapshot_png_path: Path


@dataclass(frozen=True)
class WaveformsArtifactPaths:
    """Canonical paths for the ``waveforms`` artifact category.

    The ``waveforms/`` subdirectory holds the authoritative overlay
    triplet (``waveform.png`` / ``.csv`` / ``.json``) plus the one-shot
    conversation snapshot (``current_waveform.png``).
    """
    directory: Path
    image_path: Path
    csv_path: Path
    json_path: Path
    conversation_snapshot_png_path: Path


class SimulationArtifactExporter:
    # ------------------------------------------------------------------
    # Canonical path helpers — one per artifact category
    #
    # Every consumer that needs to locate a file inside an ``export_root``
    # MUST call one of these helpers. They are deliberately single-purpose
    # (no ``kind: str`` parameter, no if/elif inside) so every call site
    # reads like ``exporter.metrics_paths(root).csv_path`` with the
    # artifact category statically visible.
    # ------------------------------------------------------------------

    def result_json_path(self, export_root: str | Path) -> Path:
        """Canonical ``result.json`` path at the bundle root."""
        return Path(export_root) / RESULT_JSON_FILENAME

    def export_manifest_path(self, export_root: str | Path) -> Path:
        """Canonical ``export_manifest.json`` path at the bundle root."""
        return Path(export_root) / EXPORT_MANIFEST_FILENAME

    def metrics_paths(self, export_root: str | Path) -> MetricsArtifactPaths:
        directory = Path(export_root) / _CANONICAL_SUBDIRS[CATEGORY_METRICS]
        return MetricsArtifactPaths(
            directory=directory,
            csv_path=directory / "metrics.csv",
            json_path=directory / "metrics.json",
        )

    def analysis_info_paths(self, export_root: str | Path) -> AnalysisInfoArtifactPaths:
        directory = Path(export_root) / _CANONICAL_SUBDIRS[CATEGORY_ANALYSIS_INFO]
        return AnalysisInfoArtifactPaths(
            directory=directory,
            json_path=directory / "analysis_info.json",
            text_path=directory / "analysis_info.txt",
        )

    def raw_data_paths(self, export_root: str | Path) -> RawDataArtifactPaths:
        directory = Path(export_root) / _CANONICAL_SUBDIRS[CATEGORY_RAW_DATA]
        return RawDataArtifactPaths(
            directory=directory,
            csv_path=directory / "raw_data.csv",
            json_path=directory / "raw_data.json",
        )

    def output_log_paths(self, export_root: str | Path) -> OutputLogArtifactPaths:
        directory = Path(export_root) / _CANONICAL_SUBDIRS[CATEGORY_OUTPUT_LOG]
        return OutputLogArtifactPaths(
            directory=directory,
            text_path=directory / "output_log.txt",
            json_path=directory / "output_log.json",
        )

    def op_result_paths(self, export_root: str | Path) -> OpResultArtifactPaths:
        directory = Path(export_root) / _CANONICAL_SUBDIRS[CATEGORY_OP_RESULT]
        return OpResultArtifactPaths(
            directory=directory,
            text_path=directory / "op_result.txt",
            json_path=directory / "op_result.json",
        )

    def charts_paths(self, export_root: str | Path) -> ChartsArtifactPaths:
        directory = Path(export_root) / _CANONICAL_SUBDIRS[CATEGORY_CHARTS]
        return ChartsArtifactPaths(
            directory=directory,
            manifest_json_path=directory / "charts.json",
            conversation_snapshot_png_path=directory / "current_chart.png",
        )

    def waveforms_paths(self, export_root: str | Path) -> WaveformsArtifactPaths:
        directory = Path(export_root) / _CANONICAL_SUBDIRS[CATEGORY_WAVEFORMS]
        return WaveformsArtifactPaths(
            directory=directory,
            image_path=directory / "waveform.png",
            csv_path=directory / "waveform.csv",
            json_path=directory / "waveform.json",
            conversation_snapshot_png_path=directory / "current_waveform.png",
        )

    def build_chart_entry_paths(
        self,
        export_root: str | Path,
        chart_index: int,
        chart_type: str,
    ) -> Tuple[Path, Path, Path]:
        """Return the ``(png, csv, json)`` triplet for a single chart entry.

        Chart bundles enumerate one triplet per displayed chart; the
        filename pattern ``{idx:02d}_{chart_type}.{ext}`` is anchored
        here so the order/format contract cannot drift between the
        writer and any future reader.
        """
        base = f"{int(chart_index):02d}_{str(chart_type)}"
        directory = self.charts_paths(export_root).directory
        return (
            directory / f"{base}.png",
            directory / f"{base}.csv",
            directory / f"{base}.json",
        )

    def build_project_export_root(self, project_root: str | Path, result: SimulationResult) -> Path:
        """Resolve the canonical bundle root **without** touching disk.

        Callers that own persistence (``SimulationArtifactPersistence``,
        attachment coordinators) use this helper to derive the exact
        ``<project_root>/simulation_results/<stem>/<ts>/`` path and
        create/reuse it themselves; this keeps path derivation purely a
        function of ``(project_root, result)`` and leaves collision
        handling (the ``_N`` suffix) to the single persistence entry.
        """
        return self._build_export_root(
            Path(project_root) / CANONICAL_RESULTS_DIR,
            result,
        )

    def create_export_root(self, base_directory: str, result: SimulationResult) -> Path:
        """Create a brand-new export root directly under an arbitrary
        base directory. Used by the manual "export to external folder"
        path — this is the only case where the exporter decides disk
        addressing on its own.
        """
        export_root = self._build_export_root(base_directory, result)
        export_root.mkdir(parents=True, exist_ok=False)
        return export_root

    def create_project_export_root(self, project_root: str | Path, result: SimulationResult) -> Path:
        """Resolve and physically create the canonical project bundle root.

        Thin convenience wrapper for call sites that need the bundle
        directory to exist right away (attachment fallbacks, integration
        tests). The unique-suffix collision rule is delegated to
        ``_build_export_root`` so two rapid-fire calls with the same
        timestamp produce ``<ts>`` and ``<ts>_2`` respectively.
        """
        export_root = self.build_project_export_root(project_root, result)
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
        paths = self.metrics_paths(export_root)
        paths.directory.mkdir(parents=True, exist_ok=True)

        columns = [
            "display_name",
            "name",
            "value",
            "unit",
            "raw_value",
            "target",
        ]
        rows = [self._metric_to_row(metric) for metric in metrics]
        self.write_csv_with_header(paths.csv_path, result, CATEGORY_METRICS, columns, rows)

        self._write_json(paths.json_path, self.build_artifact_payload(
            result=result,
            artifact_type=CATEGORY_METRICS,
            summary={
                "metric_count": len(rows),
                "metrics_with_target": sum(1 for row in rows if row.get("target")),
            },
            files={
                "csv": paths.csv_path.name,
            },
            data={
                "columns": columns,
                "rows": rows,
            },
        ))
        return [str(paths.csv_path), str(paths.json_path)]

    def export_analysis_info(self, export_root: Path, result: SimulationResult) -> List[str]:
        paths = self.analysis_info_paths(export_root)
        paths.directory.mkdir(parents=True, exist_ok=True)

        payload = self._build_analysis_info_payload(result)
        self._write_json(paths.json_path, self.build_artifact_payload(
            result,
            CATEGORY_ANALYSIS_INFO,
            summary={
                "parameter_count": len(payload.get("parameters") or {}),
            },
            files={
                "text": paths.text_path.name,
            },
            data=payload,
        ))
        self.write_text_with_header(
            paths.text_path,
            result,
            CATEGORY_ANALYSIS_INFO,
            self._build_analysis_info_text(payload),
        )
        return [str(paths.json_path), str(paths.text_path)]

    def export_raw_data(self, export_root: Path, result: SimulationResult) -> List[str]:
        paths = self.raw_data_paths(export_root)
        paths.directory.mkdir(parents=True, exist_ok=True)

        snapshot = waveform_data_service.build_table_snapshot(result)
        x_label = snapshot.x_label if snapshot is not None else result.get_x_axis_label()
        signal_names = list(snapshot.signal_names) if snapshot is not None else []
        columns = [x_label, *signal_names]
        rows = self._build_snapshot_rows(snapshot)
        series = self._build_snapshot_series(snapshot)

        self.write_csv_with_header(paths.csv_path, result, CATEGORY_RAW_DATA, columns, rows)

        self._write_json(paths.json_path, self.build_artifact_payload(
            result,
            CATEGORY_RAW_DATA,
            summary={
                "row_count": len(rows),
                "signal_count": len(signal_names),
                "x_axis_label": x_label,
            },
            files={
                "csv": paths.csv_path.name,
            },
            data={
                "columns": columns,
                "rows": rows,
                "series": series,
            },
        ))
        return [str(paths.csv_path), str(paths.json_path)]

    def export_output_log(self, export_root: Path, result: SimulationResult) -> List[str]:
        paths = self.output_log_paths(export_root)
        paths.directory.mkdir(parents=True, exist_ok=True)

        raw_output = getattr(result, "raw_output", None) or ""
        self.write_text_with_header(paths.text_path, result, CATEGORY_OUTPUT_LOG, raw_output)

        log_lines = simulation_output_reader.get_output_log_from_text(raw_output)
        error_count = sum(1 for line in log_lines if line.is_error())
        warning_count = sum(1 for line in log_lines if line.is_warning())
        info_count = len(log_lines) - error_count - warning_count
        first_error = next((line.content for line in log_lines if line.is_error()), None)
        self._write_json(paths.json_path, self.build_artifact_payload(
            result,
            CATEGORY_OUTPUT_LOG,
            summary={
                "total_lines": len(log_lines),
                "error_count": error_count,
                "warning_count": warning_count,
                "info_count": info_count,
                "first_error": first_error,
            },
            files={
                "text": paths.text_path.name,
            },
            data={
                "raw_output": raw_output,
                "lines": [line.to_dict() for line in log_lines],
            },
        ))
        return [str(paths.text_path), str(paths.json_path)]

    def export_op_result(self, export_root: Path, result: SimulationResult) -> List[str]:
        if not op_result_data_builder.is_available(result):
            raise ValueError("OP result export is unavailable for the current simulation result")
        paths = self.op_result_paths(export_root)
        paths.directory.mkdir(parents=True, exist_ok=True)

        payload = op_result_data_builder.get_payload(result)
        self.write_text_with_header(
            paths.text_path,
            result,
            CATEGORY_OP_RESULT,
            op_result_data_builder.build_text(result),
        )
        self._write_json(paths.json_path, self.build_artifact_payload(
            result,
            CATEGORY_OP_RESULT,
            summary={
                "row_count": int(payload.get("row_count", 0)),
                "section_count": int(payload.get("section_count", 0)),
            },
            files={
                "text": paths.text_path.name,
            },
            data=payload,
        ))
        return [str(paths.text_path), str(paths.json_path)]

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
    # Exporter class + singleton
    "SimulationArtifactExporter",
    "simulation_artifact_exporter",
    # Top-level layout constants
    "CANONICAL_RESULTS_DIR",
    "EXPORT_SCHEMA_VERSION",
    "RESULT_JSON_FILENAME",
    "EXPORT_MANIFEST_FILENAME",
    "ARTIFACT_TYPE_EXPORT_MANIFEST",
    # Canonical category names
    "CATEGORY_METRICS",
    "CATEGORY_ANALYSIS_INFO",
    "CATEGORY_RAW_DATA",
    "CATEGORY_OUTPUT_LOG",
    "CATEGORY_OP_RESULT",
    "CATEGORY_CHARTS",
    "CATEGORY_WAVEFORMS",
    # Ordered category tuples
    "HEADLESS_ARTIFACT_CATEGORIES",
    "DISPLAY_EXPORT_CATEGORIES",
    # Typed path bundles
    "MetricsArtifactPaths",
    "AnalysisInfoArtifactPaths",
    "RawDataArtifactPaths",
    "OutputLogArtifactPaths",
    "OpResultArtifactPaths",
    "ChartsArtifactPaths",
    "WaveformsArtifactPaths",
]
