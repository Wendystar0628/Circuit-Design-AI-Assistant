from typing import Callable, Dict, List, Mapping, Optional

import numpy as np

from domain.simulation.data.waveform_data_service import WaveformDataService
from domain.simulation.models.simulation_result import SimulationResult
from presentation.panels.simulation.waveform_plot_types import PlotItem, WaveformMeasurement


class WaveformMeasurementSupport:
    def get_all_y_at_x(
        self,
        current_result: Optional[SimulationResult],
        data_service: WaveformDataService,
        plot_items: Mapping[str, PlotItem],
        x: float,
    ) -> Dict[str, float]:
        result: Dict[str, float] = {}
        if current_result is None:
            return result
        x_data = current_result.get_x_axis_data()
        if x_data is None or len(x_data) == 0:
            return result
        x_array = np.asarray(x_data, dtype=float)
        for signal_name in plot_items:
            y_data = data_service.get_signal_data(current_result, signal_name)
            if y_data is None:
                continue
            y_array = np.asarray(y_data, dtype=float)
            if len(y_array) == 0 or len(y_array) != len(x_array):
                continue
            try:
                result[signal_name] = float(np.interp(x, x_array, y_array))
            except Exception:
                continue
        return result

    def build_measurement(
        self,
        current_result: Optional[SimulationResult],
        data_service: WaveformDataService,
        plot_items: Mapping[str, PlotItem],
        cursor_a_pos: Optional[float],
        cursor_b_pos: Optional[float],
        from_view_x_value: Callable[[float], float],
    ) -> WaveformMeasurement:
        measurement = WaveformMeasurement()

        if cursor_a_pos is not None:
            measurement.cursor_a_x = from_view_x_value(cursor_a_pos)
            all_y_a = self.get_all_y_at_x(current_result, data_service, plot_items, measurement.cursor_a_x)
            measurement.signal_values_a = all_y_a
            if all_y_a:
                measurement.cursor_a_y = next(iter(all_y_a.values()))

        if cursor_b_pos is not None:
            measurement.cursor_b_x = from_view_x_value(cursor_b_pos)
            all_y_b = self.get_all_y_at_x(current_result, data_service, plot_items, measurement.cursor_b_x)
            measurement.signal_values_b = all_y_b
            if all_y_b:
                measurement.cursor_b_y = next(iter(all_y_b.values()))

        if measurement.cursor_a_x is not None and measurement.cursor_b_x is not None:
            measurement.delta_x = measurement.cursor_b_x - measurement.cursor_a_x
            if measurement.cursor_a_y is not None and measurement.cursor_b_y is not None:
                measurement.delta_y = measurement.cursor_b_y - measurement.cursor_a_y
                if measurement.delta_x != 0:
                    measurement.slope = measurement.delta_y / measurement.delta_x
                    if (
                        current_result is not None
                        and current_result.x_axis_kind == "time"
                        and not current_result.is_x_axis_log()
                    ):
                        measurement.frequency = 1.0 / abs(measurement.delta_x)

        return measurement

    def build_value_parts(
        self,
        measurement: WaveformMeasurement,
        plot_items: Mapping[str, PlotItem],
    ) -> List[str]:
        parts: List[str] = []
        values_a = measurement.signal_values_a or {}
        values_b = measurement.signal_values_b or {}
        for signal_name, plot_item in plot_items.items():
            color = plot_item.color
            a_value = f"{values_a[signal_name]:.4g}" if signal_name in values_a else "--"
            if values_b:
                b_value = f"{values_b[signal_name]:.4g}" if signal_name in values_b else "--"
                parts.append(f'<span style="color:{color}">{signal_name}: A={a_value}  B={b_value}</span>')
            else:
                parts.append(f'<span style="color:{color}">{signal_name}: {a_value}</span>')
        return parts


waveform_measurement_support = WaveformMeasurementSupport()


__all__ = ["WaveformMeasurementSupport", "waveform_measurement_support"]
