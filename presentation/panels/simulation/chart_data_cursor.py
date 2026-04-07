from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QFormLayout, QLabel, QVBoxLayout, QWidget

from resources.theme import COLOR_BG_SECONDARY, COLOR_BORDER, COLOR_TEXT_PRIMARY, FONT_SIZE_SMALL, SPACING_NORMAL, SPACING_SMALL


_CURSOR_GUIDE_COLOR = "#000000"
_CURSOR_MARKER_COLOR = "#000000"
_CURSOR_HOVER_WIDTH = 5
_CURSOR_Z_VALUE = 10_000


def _normalize_bounds(bounds: Optional[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    if bounds is None:
        return None
    minimum = float(bounds[0])
    maximum = float(bounds[1])
    if minimum <= maximum:
        return minimum, maximum
    return maximum, minimum


def _midpoint_of_bounds(bounds: Optional[Tuple[float, float]]) -> Optional[float]:
    normalized = _normalize_bounds(bounds)
    if normalized is None:
        return None
    return (normalized[0] + normalized[1]) / 2.0


def _clamp_to_bounds(value: Optional[float], bounds: Optional[Tuple[float, float]]) -> Optional[float]:
    if value is None:
        return None
    normalized = _normalize_bounds(bounds)
    if normalized is None:
        return float(value)
    return min(max(float(value), normalized[0]), normalized[1])


def build_draggable_vertical_cursor_line(
    color: str,
    *,
    bounds: Optional[Tuple[float, float]] = None,
) -> pg.InfiniteLine:
    line = pg.InfiniteLine(
        angle=90,
        movable=True,
        pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DashLine),
        hoverPen=pg.mkPen(color, width=_CURSOR_HOVER_WIDTH, style=Qt.PenStyle.DashLine),
        bounds=_normalize_bounds(bounds),
    )
    line.setZValue(_CURSOR_Z_VALUE)
    return line


@dataclass(frozen=True)
class DataCursorValue:
    label: str
    value_text: str


@dataclass(frozen=True)
class DataCursorSample:
    title: str
    plot_y_value: float
    values: List[DataCursorValue]


class DataCursorValueDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setModal(False)
        self.setWindowTitle("Data Cursor")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_SMALL)

        self._title_label = QLabel("--")
        layout.addWidget(self._title_label)

        self._form_layout = QFormLayout()
        layout.addLayout(self._form_layout)
        self._value_labels: List[QLabel] = []

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLOR_BG_SECONDARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
            }}
            QLabel {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_SMALL}px;
                font-family: Consolas, monospace;
            }}
        """)
        self.resize(280, 180)

    def clear_values(self):
        self._title_label.setText("--")
        while self._form_layout.rowCount() > 0:
            self._form_layout.removeRow(0)
        self._value_labels = []

    def update_values(self, sample: DataCursorSample):
        self.clear_values()
        self._title_label.setText(sample.title)
        for value in sample.values:
            value_label = QLabel(value.value_text)
            self._form_layout.addRow(value.label, value_label)
            self._value_labels.append(value_label)


class ChartDataCursorController:
    def __init__(
        self,
        *,
        plot_widget: pg.PlotWidget,
        sample_at: Callable[[str, float], Optional[DataCursorSample]],
        x_bounds: Callable[[], Optional[Tuple[float, float]]],
        parent: Optional[QWidget] = None,
    ):
        self._plot_widget = plot_widget
        self._sample_at = sample_at
        self._x_bounds = x_bounds
        self._target_id = ""
        self._enabled = False
        self._cursor_x: Optional[float] = None
        self._vertical_line: Optional[pg.InfiniteLine] = None
        self._horizontal_line: Optional[pg.InfiniteLine] = None
        self._marker: Optional[pg.ScatterPlotItem] = None
        self._dialog = DataCursorValueDialog(parent)
        self._syncing_vertical_line = False

    def is_enabled(self) -> bool:
        return self._enabled

    def target_id(self) -> str:
        return self._target_id

    def set_target(self, target_id: str):
        next_target_id = target_id or ""
        if not next_target_id:
            self._cursor_x = None
        self._target_id = next_target_id
        if not self._enabled:
            return
        if not self._target_id:
            self._remove_items()
            self._dialog.hide()
            self._dialog.clear_values()
            return
        self.refresh()

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        if not self._enabled:
            self._cursor_x = None
            self._remove_items()
            self._dialog.hide()
            self._dialog.clear_values()
            return
        if not self._target_id:
            self._remove_items()
            self._dialog.hide()
            self._dialog.clear_values()
            return
        self.refresh()
        self._dialog.show()
        self._dialog.raise_()

    def clear(self):
        self._enabled = False
        self._target_id = ""
        self._cursor_x = None
        self._remove_items()
        self._dialog.hide()
        self._dialog.clear_values()

    def refresh(self):
        if not self._enabled or not self._target_id:
            return
        self._ensure_items()
        if self._vertical_line is None:
            return
        bounds = _normalize_bounds(self._x_bounds())
        self._vertical_line.setBounds(bounds)
        self._cursor_x = self._resolve_cursor_x(bounds)
        if self._cursor_x is None:
            self._hide_cursor_graphics()
            return
        self._set_vertical_line_value(self._cursor_x)
        sample = self._sample_at(self._target_id, self._cursor_x)
        if sample is None:
            self._hide_cursor_graphics()
            return
        self._vertical_line.show()
        if self._horizontal_line is not None:
            self._horizontal_line.setValue(sample.plot_y_value)
            self._horizontal_line.show()
        if self._marker is not None:
            self._marker.setData([self._cursor_x], [sample.plot_y_value])
            self._marker.show()
        self._dialog.update_values(sample)
        self._dialog.show()

    def _ensure_items(self):
        guide_pen = pg.mkPen(_CURSOR_GUIDE_COLOR, width=1, style=Qt.PenStyle.DashLine)
        marker_pen = pg.mkPen(_CURSOR_MARKER_COLOR, width=1)
        marker_brush = pg.mkBrush(_CURSOR_MARKER_COLOR)
        if self._vertical_line is None:
            self._vertical_line = build_draggable_vertical_cursor_line(_CURSOR_GUIDE_COLOR, bounds=self._x_bounds())
            self._vertical_line.sigPositionChanged.connect(self._on_cursor_moved)
            self._plot_widget.addItem(self._vertical_line)
        if self._horizontal_line is None:
            self._horizontal_line = pg.InfiniteLine(angle=0, movable=False, pen=guide_pen)
            self._horizontal_line.setZValue(_CURSOR_Z_VALUE - 1)
            self._plot_widget.addItem(self._horizontal_line)
        if self._marker is None:
            self._marker = pg.ScatterPlotItem(size=7, pen=marker_pen, brush=marker_brush)
            self._marker.setZValue(_CURSOR_Z_VALUE)
            self._plot_widget.addItem(self._marker)

    def _resolve_cursor_x(self, bounds: Optional[Tuple[float, float]]) -> Optional[float]:
        if self._cursor_x is None:
            self._cursor_x = _midpoint_of_bounds(bounds)
        return _clamp_to_bounds(self._cursor_x, bounds)

    def _set_vertical_line_value(self, value: float):
        if self._vertical_line is None:
            return
        current_value = float(self._vertical_line.value())
        if abs(current_value - value) <= 1e-12:
            return
        self._syncing_vertical_line = True
        try:
            self._vertical_line.setValue(value)
        finally:
            self._syncing_vertical_line = False

    def _hide_cursor_graphics(self):
        self._dialog.hide()
        self._dialog.clear_values()
        if self._vertical_line is not None:
            self._vertical_line.hide()
        if self._horizontal_line is not None:
            self._horizontal_line.hide()
        if self._marker is not None:
            self._marker.setData([], [])
            self._marker.hide()

    def _remove_items(self):
        if self._vertical_line is not None:
            self._plot_widget.removeItem(self._vertical_line)
            self._vertical_line = None
        if self._horizontal_line is not None:
            self._plot_widget.removeItem(self._horizontal_line)
            self._horizontal_line = None
        if self._marker is not None:
            self._plot_widget.removeItem(self._marker)
            self._marker = None

    def _on_cursor_moved(self):
        if self._syncing_vertical_line or self._vertical_line is None:
            return
        clamped_x = _clamp_to_bounds(float(self._vertical_line.value()), _normalize_bounds(self._x_bounds()))
        if clamped_x is None:
            return
        self._cursor_x = clamped_x
        self._set_vertical_line_value(clamped_x)
        self.refresh()


__all__ = [
    "DataCursorValue",
    "DataCursorSample",
    "build_draggable_vertical_cursor_line",
    "ChartDataCursorController",
]
