from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence

from domain.simulation.data.simulation_artifact_exporter import (
    ARTIFACT_TYPE_EXPORT_MANIFEST,
    CATEGORY_ANALYSIS_INFO,
    CATEGORY_CHARTS,
    CATEGORY_METRICS,
    CATEGORY_OP_RESULT,
    CATEGORY_OUTPUT_LOG,
    CATEGORY_RAW_DATA,
    CATEGORY_WAVEFORMS,
    DISPLAY_EXPORT_CATEGORIES,
    simulation_artifact_exporter,
)
from domain.simulation.models.simulation_result import SimulationResult


# Public alias. The authoritative order lives in
# ``simulation_artifact_exporter.DISPLAY_EXPORT_CATEGORIES`` (Step 15
# canonical layout schema); kept as ``EXPORT_TYPE_ORDER`` for the
# stable ``__all__`` contract consumed by ExportPanel.
EXPORT_TYPE_ORDER = DISPLAY_EXPORT_CATEGORIES


@dataclass
class SimulationExportExecution:
    export_root: Path
    selected_types: List[str]
    exported_files: List[str] = field(default_factory=list)
    category_exports: Dict[str, List[str]] = field(default_factory=dict)
    errors: List[Dict[str, str]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors


# Type alias for the dispatch-table entries. A runner maps
# ``(export_root, result, metrics)`` to the list of written files;
# chart/waveform runners ignore ``result`` + ``metrics`` because their
# content is already held by the widget.
_CategoryRunner = Callable[[Path, SimulationResult, List[Any]], List[str]]


class SimulationExportCoordinator:
    """UI-triggered "Export to…" coordinator.

    Unlike ``SimulationArtifactPersistence`` (headless, project-internal)
    this writes to a **user-chosen** folder and can additionally emit
    chart / waveform PNG bundles captured from the live widgets. The
    on-disk filenames — both per-category and the bundle-root
    ``export_manifest.json`` — are owned by
    ``simulation_artifact_exporter`` (Step 15); this class never
    constructs a path literal itself.
    """

    def __init__(self, chart_viewer, waveform_widget):
        self._chart_viewer = chart_viewer
        self._waveform_widget = waveform_widget
        self._category_runners: Dict[str, _CategoryRunner] = self._build_runners()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def all_export_types(self) -> List[str]:
        return list(EXPORT_TYPE_ORDER)

    def normalize_selected_types(self, selected_types: Sequence[str]) -> List[str]:
        requested = {str(item) for item in selected_types}
        return [export_type for export_type in EXPORT_TYPE_ORDER if export_type in requested]

    def export_to_base_directory(
        self,
        base_directory: str,
        result: SimulationResult,
        selected_types: Sequence[str],
        metrics: List[Any],
    ) -> SimulationExportExecution:
        """Manual export to a user-chosen folder (outside the project's
        canonical bundle tree).

        This is the **only** disk-writing path that this UI coordinator
        owns; project-internal persistence runs through the headless
        ``SimulationArtifactPersistence`` and is invoked by
        ``SimulationService`` immediately after a result is computed.
        """
        export_root = simulation_artifact_exporter.create_export_root(base_directory, result)
        return self._export_to_root(export_root, result, selected_types, metrics)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _export_to_root(
        self,
        export_root: Path,
        result: SimulationResult,
        selected_types: Sequence[str],
        metrics: List[Any],
    ) -> SimulationExportExecution:
        resolved_types = self.normalize_selected_types(selected_types)
        export_root.mkdir(parents=True, exist_ok=True)

        execution = SimulationExportExecution(
            export_root=export_root,
            selected_types=resolved_types,
        )

        for export_type in resolved_types:
            try:
                category_file_paths = self._export_category(export_root, result, export_type, metrics)
                execution.exported_files.extend(category_file_paths)
                execution.category_exports[export_type] = self._to_relative_paths(export_root, category_file_paths)
            except Exception as exc:
                execution.category_exports[export_type] = []
                execution.errors.append({
                    "artifact_type": export_type,
                    "message": str(exc),
                })

        self._write_manifest(export_root, result, resolved_types, execution)
        return execution

    def _write_manifest(
        self,
        export_root: Path,
        result: SimulationResult,
        resolved_types: List[str],
        execution: SimulationExportExecution,
    ) -> None:
        manifest_path = simulation_artifact_exporter.export_manifest_path(export_root)
        manifest_payload = simulation_artifact_exporter.build_artifact_payload(
            result,
            ARTIFACT_TYPE_EXPORT_MANIFEST,
            summary={
                "selected_type_count": len(resolved_types),
                "exported_file_count": len(execution.exported_files) + 1,
                "error_count": len(execution.errors),
            },
            files={
                "categories": execution.category_exports,
                "manifest": manifest_path.name,
            },
            data={
                "selected_types": resolved_types,
                "exported_files": self._to_relative_paths(
                    export_root, [*execution.exported_files, str(manifest_path)]
                ),
                "errors": execution.errors,
            },
        )
        manifest_path.write_text(
            simulation_artifact_exporter.dumps_json(manifest_payload),
            encoding="utf-8",
        )
        execution.exported_files.append(str(manifest_path))

    def _export_category(
        self,
        export_root: Path,
        result: SimulationResult,
        export_type: str,
        metrics: List[Any],
    ) -> List[str]:
        """Dispatch one UI-export category to its runner.

        Categories map 1:1 to entries in ``DISPLAY_EXPORT_CATEGORIES``.
        Adding a category is an entry in the dispatch table plus a
        matching helper in ``simulation_artifact_exporter`` (the
        canonical layout owner).
        """
        runner = self._category_runners.get(export_type)
        if runner is None:
            raise ValueError(f"Unsupported export type: {export_type}")
        return runner(export_root, result, metrics)

    def _build_runners(self) -> Dict[str, _CategoryRunner]:
        # Chart / waveform runners grab their output directory from
        # the exporter's typed-paths helpers so we never spell out a
        # subdirectory name here.
        def run_charts(root: Path, _result: SimulationResult, _metrics: List[Any]) -> List[str]:
            directory = simulation_artifact_exporter.charts_paths(root).directory
            return self._chart_viewer.export_bundle(str(directory))

        def run_waveforms(root: Path, _result: SimulationResult, _metrics: List[Any]) -> List[str]:
            directory = simulation_artifact_exporter.waveforms_paths(root).directory
            return self._waveform_widget.export_bundle(str(directory))

        return {
            CATEGORY_METRICS: lambda root, result, metrics:
                simulation_artifact_exporter.export_metrics(root, result, metrics),
            CATEGORY_CHARTS: run_charts,
            CATEGORY_WAVEFORMS: run_waveforms,
            CATEGORY_ANALYSIS_INFO: lambda root, result, _metrics:
                simulation_artifact_exporter.export_analysis_info(root, result),
            CATEGORY_RAW_DATA: lambda root, result, _metrics:
                simulation_artifact_exporter.export_raw_data(root, result),
            CATEGORY_OUTPUT_LOG: lambda root, result, _metrics:
                simulation_artifact_exporter.export_output_log(root, result),
            CATEGORY_OP_RESULT: lambda root, result, _metrics:
                simulation_artifact_exporter.export_op_result(root, result),
        }

    def _to_relative_paths(self, export_root: Path, file_paths: List[str]) -> List[str]:
        root = export_root.resolve()
        relative_paths: List[str] = []
        for file_path in file_paths:
            path = Path(file_path)
            try:
                relative_paths.append(str(path.resolve().relative_to(root)).replace("\\", "/"))
            except Exception:
                relative_paths.append(path.name)
        return relative_paths


__all__ = [
    "EXPORT_TYPE_ORDER",
    "SimulationExportExecution",
    "SimulationExportCoordinator",
]
