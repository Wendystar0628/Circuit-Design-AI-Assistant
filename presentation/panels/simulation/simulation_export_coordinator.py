from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Sequence

from domain.simulation.data.simulation_artifact_exporter import simulation_artifact_exporter
from domain.simulation.models.simulation_result import SimulationResult


EXPORT_TYPE_ORDER = (
    "metrics",
    "charts",
    "waveforms",
    "analysis_info",
    "raw_data",
    "output_log",
)


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


class SimulationExportCoordinator:
    def __init__(self, chart_viewer, waveform_widget):
        self._chart_viewer = chart_viewer
        self._waveform_widget = waveform_widget

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
        overall_score: float,
    ) -> SimulationExportExecution:
        export_root = simulation_artifact_exporter.create_export_root(base_directory, result)
        return self._export_to_root(export_root, result, selected_types, metrics, overall_score)

    def export_to_project_directory(
        self,
        project_root: str,
        result: SimulationResult,
        selected_types: Sequence[str],
        metrics: List[Any],
        overall_score: float,
    ) -> SimulationExportExecution:
        export_root = simulation_artifact_exporter.create_project_export_root(project_root, result)
        return self._export_to_root(export_root, result, selected_types, metrics, overall_score)

    def _export_to_root(
        self,
        export_root: Path,
        result: SimulationResult,
        selected_types: Sequence[str],
        metrics: List[Any],
        overall_score: float,
    ) -> SimulationExportExecution:
        resolved_types = self.normalize_selected_types(selected_types)
        export_root.mkdir(parents=True, exist_ok=True)

        execution = SimulationExportExecution(
            export_root=export_root,
            selected_types=resolved_types,
        )

        for export_type in resolved_types:
            try:
                category_file_paths = self._export_category(export_root, result, export_type, metrics, overall_score)
                execution.exported_files.extend(category_file_paths)
                execution.category_exports[export_type] = self._to_relative_paths(export_root, category_file_paths)
            except Exception as exc:
                execution.category_exports[export_type] = []
                execution.errors.append({
                    "artifact_type": export_type,
                    "message": str(exc),
                })

        manifest_path = export_root / "export_manifest.json"
        manifest_payload = simulation_artifact_exporter.build_artifact_payload(
            result,
            "export_manifest",
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
                "exported_files": self._to_relative_paths(export_root, [*execution.exported_files, str(manifest_path)]),
                "errors": execution.errors,
            },
        )
        manifest_path.write_text(simulation_artifact_exporter.dumps_json(manifest_payload), encoding="utf-8")
        execution.exported_files.append(str(manifest_path))
        return execution

    def _export_category(
        self,
        export_root: Path,
        result: SimulationResult,
        export_type: str,
        metrics: List[Any],
        overall_score: float,
    ) -> List[str]:
        if export_type == "metrics":
            return simulation_artifact_exporter.export_metrics(export_root, result, metrics, overall_score)
        if export_type == "charts":
            return self._chart_viewer.export_bundle(str(export_root / "charts"))
        if export_type == "waveforms":
            return self._waveform_widget.export_bundle(str(export_root / "waveforms"))
        if export_type == "analysis_info":
            return simulation_artifact_exporter.export_analysis_info(export_root, result)
        if export_type == "raw_data":
            return simulation_artifact_exporter.export_raw_data(export_root, result)
        if export_type == "output_log":
            return simulation_artifact_exporter.export_output_log(export_root, result)
        raise ValueError(f"Unsupported export type: {export_type}")

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
