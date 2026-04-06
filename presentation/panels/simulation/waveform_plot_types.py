from dataclasses import dataclass
from typing import Dict, Optional

import pyqtgraph as pg

from domain.simulation.data.waveform_data_service import WaveformData


SIGNAL_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
]

CURSOR_A_COLOR = "#ff0000"
CURSOR_B_COLOR = "#00ff00"

INITIAL_POINTS = 500
VIEWPORT_POINTS = 1000


@dataclass
class WaveformMeasurement:
    cursor_a_x: Optional[float] = None
    cursor_a_y: Optional[float] = None
    cursor_b_x: Optional[float] = None
    cursor_b_y: Optional[float] = None
    delta_x: Optional[float] = None
    delta_y: Optional[float] = None
    slope: Optional[float] = None
    frequency: Optional[float] = None
    signal_values_a: Optional[Dict[str, float]] = None
    signal_values_b: Optional[Dict[str, float]] = None


@dataclass
class PlotItem:
    plot_data_item: pg.PlotDataItem
    color: str
    waveform_data: Optional[WaveformData] = None
    axis: str = "left"


__all__ = [
    "SIGNAL_COLORS",
    "CURSOR_A_COLOR",
    "CURSOR_B_COLOR",
    "INITIAL_POINTS",
    "VIEWPORT_POINTS",
    "WaveformMeasurement",
    "PlotItem",
]
