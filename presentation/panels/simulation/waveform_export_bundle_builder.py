import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import numpy as np

from domain.simulation.data.downsampler import align_xy
from domain.simulation.data.signal_semantics import (
    insert_nested_dc_breaks,
    parse_nested_dc_sweep,
)
from domain.simulation.data.simulation_artifact_exporter import simulation_artifact_exporter
from domain.simulation.data.waveform_data_service import WaveformDataService
from domain.simulation.models.simulation_result import SimulationResult
from presentation.panels.simulation.chart_export_utils import (
    add_nested_dc_secondary_column,
    build_chart_data_rows,
)
from presentation.panels.simulation.chart_view_types import ChartSeries


class WaveformExportBundleBuilder:
    def build_full_resolution_series(
        self,
        result: SimulationResult,
        data_service: WaveformDataService,
        plot_items: Mapping[str, Any],
        signal_names: Sequence[str],
    ) -> List[ChartSeries]:
        x_data = result.get_x_axis_data()
        if x_data is None:
            return []
        nested_sweep = parse_nested_dc_sweep(result.analysis_type, result.analysis_command)
        series: List[ChartSeries] = []
        for signal_name in signal_names:
            y_data = data_service.get_signal_data(result, signal_name)
            plot_item = plot_items.get(signal_name)
            if y_data is None or plot_item is None:
                continue
            x_series, y_series = align_xy(x_data, y_data)
            if nested_sweep is not None:
                x_series, y_series = insert_nested_dc_breaks(
                    x_series,
                    y_series,
                    nested_sweep,
                )
            series.append(
                ChartSeries(
                    name=signal_name,
                    x_data=x_series,
                    y_data=y_series,
                    color=plot_item.color,
                    axis_key=plot_item.axis,
                    axis_family=getattr(plot_item, "axis_family", "other"),
                )
            )
        return series

    def build_export_rows(
        self,
        series: Sequence[ChartSeries],
        x_label: str,
    ) -> List[Dict[str, float]]:
        return build_chart_data_rows(x_label, series)

    def add_nested_dc_secondary_column(
        self,
        rows: List[Dict[str, Any]],
        x_label: str,
        result: SimulationResult,
    ) -> Optional[str]:
        return add_nested_dc_secondary_column(rows, x_label, result)

    def build_signal_payloads(self, series: Sequence[ChartSeries]) -> List[Dict[str, Any]]:
        payloads: List[Dict[str, Any]] = []
        for item in series:
            x_data, y_data = align_xy(item.x_data, item.y_data)
            payloads.append({
                "name": item.name,
                "axis_key": item.axis_key,
                "axis_family": item.axis_family,
                "x": [float(value) if np.isfinite(value) else None for value in x_data],
                "y": [float(value) if np.isfinite(value) else None for value in y_data],
                "point_count": len(y_data),
            })
        return payloads

    def measurement_to_payload(self, measurement: Any) -> Dict[str, object]:
        return {
            "cursor_a_x": measurement.cursor_a_x,
            "cursor_a_y": measurement.cursor_a_y,
            "cursor_b_x": measurement.cursor_b_x,
            "cursor_b_y": measurement.cursor_b_y,
            "delta_x": measurement.delta_x,
            "delta_y": measurement.delta_y,
            "slope": measurement.slope,
            "frequency": measurement.frequency,
            "signal_values_a": measurement.signal_values_a or {},
            "signal_values_b": measurement.signal_values_b or {},
        }

    def export_bundle(
        self,
        output_dir: str,
        result: SimulationResult,
        signal_names: Sequence[str],
        headers: List[str],
        rows: List[Dict[str, float]],
        measurement: Any,
        signal_payloads: List[Dict[str, Any]],
        export_image: Callable[[str], bool],
    ) -> List[str]:
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        # The exporter owns the external artifact layout.  This builder only
        # supplies waveform content inside the canonical waveforms directory.
        canonical_waveform_paths = simulation_artifact_exporter.waveforms_paths(target_dir.parent)

        exported_files: List[str] = []
        image_path = target_dir / canonical_waveform_paths.image_path.name
        csv_path = target_dir / canonical_waveform_paths.csv_path.name
        json_path = target_dir / canonical_waveform_paths.json_path.name
        file_map: Dict[str, str] = {}

        if export_image(str(image_path)):
            simulation_artifact_exporter.inject_png_linkage(image_path, result, "waveforms")
            exported_files.append(str(image_path))
            file_map["image"] = image_path.name

        simulation_artifact_exporter.write_csv_with_header(
            csv_path,
            result,
            "waveforms",
            headers,
            rows,
        )
        exported_files.append(str(csv_path))
        file_map["csv"] = csv_path.name

        file_map["json"] = json_path.name
        payload = simulation_artifact_exporter.build_artifact_payload(
            result,
            "waveforms",
            summary={
                "signal_count": len(signal_payloads),
                "row_count": len(rows),
                "measurement_enabled": measurement.cursor_a_x is not None or measurement.cursor_b_x is not None,
            },
            files=file_map,
            data={
                "columns": headers,
                "rows": rows,
                "displayed_signal_names": list(signal_names),
                "measurement": self.measurement_to_payload(measurement),
                "series": signal_payloads,
            },
        )
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        exported_files.append(str(json_path))

        return exported_files


waveform_export_bundle_builder = WaveformExportBundleBuilder()


__all__ = ["WaveformExportBundleBuilder", "waveform_export_bundle_builder"]
