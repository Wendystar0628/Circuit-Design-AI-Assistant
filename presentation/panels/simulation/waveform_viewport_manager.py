from typing import Callable, Mapping, Optional, Tuple

import numpy as np
import pyqtgraph as pg

from domain.simulation.data.waveform_data_service import WaveformDataService
from domain.simulation.models.simulation_result import SimulationResult
from presentation.panels.simulation.ltspice_plot_interaction import (
    apply_dynamic_tick_spacing,
    finite_range,
    merge_ranges,
)
from presentation.panels.simulation.waveform_plot_types import PlotItem


class WaveformViewportManager:
    def __init__(self, data_service: WaveformDataService):
        self._data_service = data_service

    def reload_initial_data(
        self,
        current_result: Optional[SimulationResult],
        plot_items: Mapping[str, PlotItem],
        target_points: int,
    ) -> None:
        if current_result is None:
            return

        for signal_name, plot_item in plot_items.items():
            waveform_data = self._data_service.get_initial_data(
                current_result,
                signal_name,
                target_points=target_points,
            )
            if waveform_data is None:
                continue
            plot_item.waveform_data = waveform_data
            plot_item.plot_data_item.setData(waveform_data.x_data, waveform_data.y_data)

    def rebuild_domains(
        self,
        current_result: Optional[SimulationResult],
        plot_items: Mapping[str, PlotItem],
        to_view_x_data: Callable[[np.ndarray], np.ndarray],
    ) -> Tuple[
        Optional[Tuple[float, float]],
        Optional[Tuple[float, float]],
        Optional[Tuple[float, float]],
    ]:
        if current_result is None or current_result.data is None or not plot_items:
            return None, None, None

        requested_domain = None
        if current_result.requested_x_range is not None:
            requested_domain = finite_range(
                to_view_x_data(np.asarray(current_result.requested_x_range, dtype=float))
            )

        actual_x_data = current_result.get_x_axis_data()
        actual_domain = None
        if actual_x_data is not None:
            actual_domain = finite_range(to_view_x_data(actual_x_data))

        x_domain = requested_domain or actual_domain

        left_y_ranges = []
        right_y_ranges = []
        for signal_name, plot_item in plot_items.items():
            signal_data = current_result.data.get_signal(signal_name)
            if signal_data is None:
                continue
            y_range = finite_range(signal_data)
            if y_range is None:
                continue
            if plot_item.axis == "right":
                right_y_ranges.append(y_range)
            else:
                left_y_ranges.append(y_range)

        return x_domain, merge_ranges(left_y_ranges), merge_ranges(right_y_ranges)

    def apply_domain_limits(
        self,
        plot_widget: pg.PlotWidget,
        right_vb: Optional[pg.ViewBox],
        x_domain: Optional[Tuple[float, float]],
        left_y_domain: Optional[Tuple[float, float]],
        right_y_domain: Optional[Tuple[float, float]],
    ) -> None:
        plot_item = plot_widget.getPlotItem()
        view_box = plot_item.vb
        if x_domain is not None:
            view_box.setLimits(xMin=x_domain[0], xMax=x_domain[1])

        base_y_domain = left_y_domain or right_y_domain
        if base_y_domain is not None:
            view_box.setLimits(yMin=base_y_domain[0], yMax=base_y_domain[1])

        if right_vb is not None and right_y_domain is not None:
            right_vb.setLimits(yMin=right_y_domain[0], yMax=right_y_domain[1])

    def apply_viewport(
        self,
        plot_widget: pg.PlotWidget,
        right_vb: Optional[pg.ViewBox],
        x_range: Optional[Tuple[float, float]],
        left_y_range: Optional[Tuple[float, float]],
        right_y_range: Optional[Tuple[float, float]],
        *,
        log_x_enabled: bool,
    ) -> None:
        if x_range is None:
            return

        base_y_range = left_y_range or right_y_range
        if base_y_range is None:
            return

        plot_item = plot_widget.getPlotItem()
        plot_item.setXRange(x_range[0], x_range[1], padding=0.0)
        plot_item.setYRange(base_y_range[0], base_y_range[1], padding=0.0)
        if right_vb is not None:
            applied_right_y = right_y_range or base_y_range
            right_vb.setYRange(applied_right_y[0], applied_right_y[1], padding=0.0)
        apply_dynamic_tick_spacing(plot_item.getAxis('bottom'), x_range, log_enabled=log_x_enabled)
        apply_dynamic_tick_spacing(plot_item.getAxis('left'), base_y_range, log_enabled=False)
        if right_vb is not None:
            apply_dynamic_tick_spacing(plot_item.getAxis('right'), right_y_range or base_y_range, log_enabled=False)

    def reload_viewport_data(
        self,
        current_result: Optional[SimulationResult],
        plot_items: Mapping[str, PlotItem],
        view_x_range: Tuple[float, float],
        from_view_x_value: Callable[[float], float],
        target_points: int,
    ) -> None:
        if current_result is None:
            return

        actual_x_min = from_view_x_value(view_x_range[0])
        actual_x_max = from_view_x_value(view_x_range[1])
        for signal_name, plot_item in plot_items.items():
            waveform_data = self._data_service.get_viewport_data(
                current_result,
                signal_name,
                actual_x_min,
                actual_x_max,
                target_points=target_points,
            )
            if waveform_data is None:
                continue
            plot_item.waveform_data = waveform_data
            plot_item.plot_data_item.setData(waveform_data.x_data, waveform_data.y_data)


__all__ = ["WaveformViewportManager"]
