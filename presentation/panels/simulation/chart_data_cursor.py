from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from resources.theme import COLOR_BG_SECONDARY, COLOR_BORDER, COLOR_TEXT_PRIMARY, FONT_SIZE_SMALL, SPACING_NORMAL, SPACING_SMALL


CURSOR_GUIDE_COLOR = "#000000"
CURSOR_MARKER_COLOR = "#000000"


@dataclass(frozen=True)
class DataCursorTarget:
    target_id: str
    display_name: str


@dataclass(frozen=True)
class DataCursorValue:
    label: str
    value_text: str


@dataclass(frozen=True)
class DataCursorSample:
    title: str
    plot_y_value: float
    values: List[DataCursorValue]


class DataCursorSelectionDialog(QDialog):
    def __init__(
        self,
        targets: List[DataCursorTarget],
        *,
        current_target_id: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("Select Cursor Signal")
        self._targets = targets

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_SMALL)

        title_label = QLabel("Select signal")
        layout.addWidget(title_label)

        self._list_widget = QListWidget()
        for target in targets:
            item = QListWidgetItem(target.display_name)
            item.setData(Qt.ItemDataRole.UserRole, target.target_id)
            self._list_widget.addItem(item)
            if current_target_id and target.target_id == current_target_id:
                self._list_widget.setCurrentItem(item)

        if self._list_widget.currentItem() is None and self._list_widget.count() > 0:
            self._list_widget.setCurrentRow(0)

        self._list_widget.itemDoubleClicked.connect(lambda _: self.accept())
        layout.addWidget(self._list_widget)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLOR_BG_SECONDARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
            }}
            QLabel {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            QListWidget {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
        """)
        self.resize(320, 360)

    def selected_target_id(self) -> str:
        current_item = self._list_widget.currentItem()
        if current_item is None:
            return ""
        return str(current_item.data(Qt.ItemDataRole.UserRole) or "")

    @classmethod
    def select_target(
        cls,
        targets: List[DataCursorTarget],
        *,
        current_target_id: str = "",
        parent: Optional[QWidget] = None,
    ) -> str:
        if not targets:
            return ""
        dialog = cls(targets, current_target_id=current_target_id, parent=parent)
        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            return ""
        return dialog.selected_target_id()


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
        current_view_x_range: Callable[[], Optional[Tuple[float, float]]],
        parent: Optional[QWidget] = None,
    ):
        self._plot_widget = plot_widget
        self._sample_at = sample_at
        self._current_view_x_range = current_view_x_range
        self._target_id = ""
        self._enabled = False
        self._cursor_x: Optional[float] = None
        self._vertical_line: Optional[pg.InfiniteLine] = None
        self._horizontal_line: Optional[pg.InfiniteLine] = None
        self._marker: Optional[pg.ScatterPlotItem] = None
        self._dialog = DataCursorValueDialog(parent)

    def is_enabled(self) -> bool:
        return self._enabled

    def target_id(self) -> str:
        return self._target_id

    def set_target(self, target_id: str):
        self._target_id = target_id
        if self._enabled:
            self.refresh()

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        if not self._enabled:
            self._remove_items()
            self._dialog.hide()
            self._dialog.clear_values()
            return
        if not self._target_id:
            self._enabled = False
            return
        self._ensure_items()
        x_range = self._current_view_x_range()
        if self._cursor_x is None and x_range is not None:
            self._cursor_x = (x_range[0] + x_range[1]) / 2
        if self._vertical_line is not None and self._cursor_x is not None:
            self._vertical_line.setValue(self._cursor_x)
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
        self._cursor_x = float(self._vertical_line.value())
        sample = self._sample_at(self._target_id, self._cursor_x)
        if sample is None:
            self._dialog.hide()
            self._dialog.clear_values()
            self._vertical_line.hide()
            if self._horizontal_line is not None:
                self._horizontal_line.hide()
            if self._marker is not None:
                self._marker.setData([], [])
                self._marker.hide()
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
        guide_pen = pg.mkPen(CURSOR_GUIDE_COLOR, width=1, style=Qt.PenStyle.DashLine)
        marker_pen = pg.mkPen(CURSOR_MARKER_COLOR, width=1)
        marker_brush = pg.mkBrush(CURSOR_MARKER_COLOR)
        if self._vertical_line is None:
            self._vertical_line = pg.InfiniteLine(angle=90, movable=True, pen=guide_pen)
            self._vertical_line.sigPositionChanged.connect(self._on_cursor_moved)
            self._plot_widget.addItem(self._vertical_line)
        if self._horizontal_line is None:
            self._horizontal_line = pg.InfiniteLine(angle=0, movable=False, pen=guide_pen)
            self._plot_widget.addItem(self._horizontal_line)
        if self._marker is None:
            self._marker = pg.ScatterPlotItem(size=7, pen=marker_pen, brush=marker_brush)
            self._plot_widget.addItem(self._marker)

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
        self.refresh()


__all__ = [
    "CURSOR_GUIDE_COLOR",
    "CURSOR_MARKER_COLOR",
    "DataCursorTarget",
    "DataCursorValue",
    "DataCursorSample",
    "DataCursorSelectionDialog",
    "DataCursorValueDialog",
    "ChartDataCursorController",
]
