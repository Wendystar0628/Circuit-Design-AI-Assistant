from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from domain.simulation.models.chart_type import ChartType


@dataclass
class ChartSeries:
    name: str
    x_data: np.ndarray
    y_data: np.ndarray
    color: str


@dataclass
class ChartSpec:
    chart_type: ChartType
    title: str
    x_label: str
    y_label: str
    series: List[ChartSeries]
    log_x: bool = False
    log_y: bool = False
    x_domain: Optional[Tuple[float, float]] = None


__all__ = ["ChartSeries", "ChartSpec"]
