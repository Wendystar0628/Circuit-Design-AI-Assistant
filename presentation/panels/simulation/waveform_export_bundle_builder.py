import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Sequence

from domain.simulation.data.simulation_artifact_exporter import simulation_artifact_exporter
from domain.simulation.models.simulation_result import SimulationResult


class WaveformExportBundleBuilder:
    def build_export_rows(
        self,
        plot_items: Mapping[str, Any],
        signal_names: Sequence[str],
        x_label: str,
    ) -> List[Dict[str, float]]:
        if not signal_names:
            return []

        primary_signal = plot_items.get(signal_names[0])
        if primary_signal is None or primary_signal.waveform_data is None:
            return []

        primary_x = primary_signal.waveform_data.x_data
        rows: List[Dict[str, float]] = []
        for index, x_value in enumerate(primary_x):
            row: Dict[str, float] = {x_label: float(x_value)}
            for signal_name in signal_names:
                plot_item = plot_items.get(signal_name)
                waveform_data = plot_item.waveform_data if plot_item is not None else None
                if waveform_data is None or index >= len(waveform_data.y_data):
                    continue
                row[signal_name] = float(waveform_data.y_data[index])
            rows.append(row)
        return rows

    def build_signal_payloads(self, plot_items: Mapping[str, Any]) -> List[Dict[str, Any]]:
        payloads: List[Dict[str, Any]] = []
        for signal_name, plot_item in plot_items.items():
            waveform_data = plot_item.waveform_data
            if waveform_data is None:
                continue
            payloads.append({
                "name": signal_name,
                "axis_key": plot_item.axis,
                "x": [float(value) for value in waveform_data.x_data],
                "y": [float(value) for value in waveform_data.y_data],
                "point_count": len(waveform_data.y_data),
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

        # Canonical waveform filenames live in
        # ``simulation_artifact_exporter.waveforms_paths`` (Step 15
        # layout schema). ``target_dir`` is the canonical
        # ``<export_root>/waveforms/`` directory; we read the filename
        # portion from the schema rather than hard-coding
        # ``waveform.png``/``.csv``/``.json`` here.
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
