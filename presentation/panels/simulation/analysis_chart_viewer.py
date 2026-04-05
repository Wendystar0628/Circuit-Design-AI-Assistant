import csv
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QGuiApplication
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from domain.simulation.models.simulation_result import SimulationResult
from domain.simulation.service.chart_selector import ChartType
from presentation.panels.simulation.ltspice_plot_interaction import (
    LTSpiceViewBox,
    apply_dynamic_tick_spacing,
    clamp_range,
    finite_range,
    merge_ranges,
)
from resources.theme import (
    BORDER_RADIUS_NORMAL,
    COLOR_ACCENT,
    COLOR_ACCENT_LIGHT,
    COLOR_BG_PRIMARY,
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    FONT_SIZE_SMALL,
    SPACING_NORMAL,
    SPACING_SMALL,
)


SERIES_COLORS = [
    "#4a9eff",
    "#ff6b6b",
    "#2ecc71",
    "#f39c12",
    "#9b59b6",
    "#1abc9c",
    "#e67e22",
    "#e84393",
]
DERIVED_SIGNAL_SUFFIXES = ("_mag", "_phase", "_real", "_imag")
SUPPORTED_CHART_TYPES = (
    ChartType.WAVEFORM_TIME,
    ChartType.BODE_MAGNITUDE,
    ChartType.BODE_PHASE,
    ChartType.DC_SWEEP,
    ChartType.NOISE_SPECTRUM,
)


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


class MeasurementBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("measurementBar")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        layout.setSpacing(2)

        first_row = QHBoxLayout()
        self._cursor_a_label = QLabel("A: --")
        self._cursor_b_label = QLabel("B: --")
        self._delta_label = QLabel("Δ: --")
        self._freq_label = QLabel("f: --")
        first_row.addWidget(self._cursor_a_label)
        first_row.addWidget(self._cursor_b_label)
        first_row.addWidget(self._delta_label)
        first_row.addWidget(self._freq_label)
        first_row.addStretch()
        layout.addLayout(first_row)

        self._values_label = QLabel("")
        self._values_label.setObjectName("signalValuesLabel")
        self._values_label.setWordWrap(True)
        layout.addWidget(self._values_label)
        self.hide()

    def clear_values(self):
        self._cursor_a_label.setText("A: --")
        self._cursor_b_label.setText("B: --")
        self._delta_label.setText("Δ: --")
        self._freq_label.setText("f: --")
        self._values_label.setText("")

    def update_values(
        self,
        cursor_a_x: Optional[float],
        cursor_b_x: Optional[float],
        series_values_a: Dict[str, float],
        series_values_b: Dict[str, float],
        colors: Dict[str, str],
        *,
        show_frequency: bool,
    ):
        if cursor_a_x is None:
            self._cursor_a_label.setText("A: --")
        else:
            self._cursor_a_label.setText(f"A: {cursor_a_x:.6g}")

        if cursor_b_x is None:
            self._cursor_b_label.setText("B: --")
        else:
            self._cursor_b_label.setText(f"B: {cursor_b_x:.6g}")

        if cursor_a_x is not None and cursor_b_x is not None:
            delta_x = cursor_b_x - cursor_a_x
            self._delta_label.setText(f"Δ: {delta_x:.6g}")
            if show_frequency and delta_x != 0:
                self._freq_label.setText(f"f: {1.0 / abs(delta_x):.6g} Hz")
            else:
                self._freq_label.setText("f: --")
        else:
            self._delta_label.setText("Δ: --")
            self._freq_label.setText("f: --")

        parts: List[str] = []
        series_names = list(colors.keys())
        for name in series_names:
            a_text = f"A={series_values_a[name]:.6g}" if name in series_values_a else "A=--"
            if cursor_b_x is not None:
                b_text = f"B={series_values_b[name]:.6g}" if name in series_values_b else "B=--"
                text = f"{name}: {a_text}  {b_text}"
            else:
                text = f"{name}: {a_text}"
            parts.append(f'<span style="color:{colors[name]}">{text}</span>')
        self._values_label.setText("  |  ".join(parts))


class ChartPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._logger = logging.getLogger(__name__)
        self._spec: Optional[ChartSpec] = None
        self._cursor_a: Optional[pg.InfiniteLine] = None
        self._cursor_b: Optional[pg.InfiniteLine] = None
        self._cursor_a_pos: Optional[float] = None
        self._cursor_b_pos: Optional[float] = None
        self._series_colors: Dict[str, str] = {}

        self._plot_items: Dict[str, pg.PlotDataItem] = {}
        self._series_items: Dict[str, QTreeWidgetItem] = {}
        self._updating_tree = False
        self._syncing_view = False
        self._x_domain: Optional[Tuple[float, float]] = None
        self._y_domain: Optional[Tuple[float, float]] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter.setHandleWidth(1)
        self._main_splitter.setChildrenCollapsible(True)

        self._signal_panel = QFrame()
        self._signal_panel.setObjectName("signalPanel")
        signal_layout = QVBoxLayout(self._signal_panel)
        signal_layout.setContentsMargins(0, 0, 0, 0)
        signal_layout.setSpacing(0)

        signal_header = QFrame()
        signal_header.setObjectName("signalHeader")
        signal_header_layout = QHBoxLayout(signal_header)
        signal_header_layout.setContentsMargins(SPACING_SMALL, SPACING_SMALL, SPACING_SMALL, SPACING_SMALL)
        self._signal_title_label = QLabel("Signals")
        self._signal_title_label.setObjectName("signalTitle")
        signal_header_layout.addWidget(self._signal_title_label)
        signal_header_layout.addStretch()

        self._clear_all_btn = QPushButton("Clear")
        self._clear_all_btn.setObjectName("clearAllBtn")
        self._clear_all_btn.setFixedHeight(22)
        self._clear_all_btn.clicked.connect(self._on_clear_all_series)
        signal_header_layout.addWidget(self._clear_all_btn)
        signal_layout.addWidget(signal_header)

        self._signal_tree = QTreeWidget()
        self._signal_tree.setObjectName("signalTree")
        self._signal_tree.setHeaderHidden(True)
        self._signal_tree.setRootIsDecorated(False)
        self._signal_tree.itemChanged.connect(self._on_signal_item_changed)
        signal_layout.addWidget(self._signal_tree)

        self._main_splitter.addWidget(self._signal_panel)

        right_panel = QFrame()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._plot_widget = pg.PlotWidget(viewBox=LTSpiceViewBox())
        self._plot_widget.setBackground(COLOR_BG_PRIMARY)
        plot_item = self._plot_widget.getPlotItem()
        plot_item.showGrid(x=True, y=True, alpha=0.25)
        plot_item.disableAutoRange()
        view_box = plot_item.vb
        if isinstance(view_box, LTSpiceViewBox):
            view_box.rect_selected.connect(self._on_rect_selected)
        self._legend = plot_item.addLegend()
        right_layout.addWidget(self._plot_widget, 1)

        self._measurement_bar = MeasurementBar()
        right_layout.addWidget(self._measurement_bar)

        self._main_splitter.addWidget(right_panel)
        self._main_splitter.setSizes([180, 620])
        layout.addWidget(self._main_splitter, 1)

    def clear(self):
        self._plot_widget.clear()
        plot_item = self._plot_widget.getPlotItem()
        plot_item.showGrid(x=True, y=True, alpha=0.25)
        plot_item.disableAutoRange()
        self._legend = plot_item.addLegend()
        self._remove_cursors()
        self._measurement_bar.clear_values()
        self._measurement_bar.hide()
        self._spec = None
        self._series_colors = {}
        self._plot_items = {}
        self._series_items = {}
        self._x_domain = None
        self._y_domain = None
        self._signal_tree.clear()

    def set_chart(self, spec: ChartSpec):
        self.clear()
        self._spec = spec
        plot_item = self._plot_widget.getPlotItem()
        plot_item.setTitle(spec.title)
        plot_item.setLabel("bottom", spec.x_label)
        plot_item.setLabel("left", spec.y_label)
        plot_item.setLogMode(x=spec.log_x, y=spec.log_y)

        valid_series: List[ChartSeries] = []
        self._updating_tree = True
        self._signal_tree.clear()
        self._series_items = {}
        for series in spec.series:
            x_data = np.asarray(series.x_data, dtype=float)
            y_data = np.asarray(series.y_data, dtype=float)
            if len(x_data) == 0 or len(y_data) == 0 or len(x_data) != len(y_data):
                continue
            valid_series.append(series)
            item = QTreeWidgetItem(self._signal_tree, [series.name])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)
            self._series_items[series.name] = item
        self._updating_tree = False

        self._spec.series = valid_series
        self._rebuild_plot()

    def has_chart(self) -> bool:
        return bool(self._plot_items)

    def fit_to_view(self):
        self._rebuild_plot()

    def set_measurement_enabled(self, enabled: bool):
        if enabled:
            self._ensure_cursors()
            self._measurement_bar.show()
            self._update_measurement()
        else:
            self._remove_cursors()
            self._measurement_bar.clear_values()
            self._measurement_bar.hide()

    def is_measurement_enabled(self) -> bool:
        return self._cursor_a is not None or self._cursor_b is not None

    def export_image(self, path: str) -> bool:
        pixmap = self._plot_widget.grab()
        if pixmap.isNull():
            return False
        return pixmap.save(path)

    def copy_image(self) -> bool:
        pixmap = self._plot_widget.grab()
        if pixmap.isNull():
            return False
        QGuiApplication.clipboard().setPixmap(pixmap)
        return True

    def export_chart_data(self, path: str, format_name: str) -> bool:
        visible_series = self._visible_series()
        if self._spec is None or not visible_series:
            return False

        rows = self._build_data_rows(visible_series)
        if format_name == "json":
            payload = {
                "chart_type": self._spec.chart_type.value,
                "title": self._spec.title,
                "x_label": self._spec.x_label,
                "y_label": self._spec.y_label,
                "rows": rows,
            }
            Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return True

        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            headers = [self._spec.x_label] + [series.name for series in visible_series]
            writer.writerow(headers)
            for row in rows:
                writer.writerow([row.get(header, "") for header in headers])
        return True

    def _build_data_rows(self, series_list: List[ChartSeries]) -> List[Dict[str, float]]:
        if self._spec is None or not series_list:
            return []
        primary_x = series_list[0].x_data
        rows: List[Dict[str, float]] = []
        for index, x_value in enumerate(primary_x):
            row: Dict[str, float] = {self._spec.x_label: float(x_value)}
            for series in series_list:
                if index < len(series.y_data):
                    row[series.name] = float(series.y_data[index])
            rows.append(row)
        return rows

    def _ensure_cursors(self):
        if self._spec is None or not self._plot_items:
            return
        if self._cursor_a is None:
            pen = pg.mkPen("#ff6b6b", width=1, style=Qt.PenStyle.DashLine)
            self._cursor_a = pg.InfiniteLine(angle=90, movable=True, pen=pen)
            self._cursor_a.sigPositionChanged.connect(self._on_cursor_a_moved)
            self._plot_widget.addItem(self._cursor_a)
        if self._cursor_b is None:
            pen = pg.mkPen("#2ecc71", width=1, style=Qt.PenStyle.DashLine)
            self._cursor_b = pg.InfiniteLine(angle=90, movable=True, pen=pen)
            self._cursor_b.sigPositionChanged.connect(self._on_cursor_b_moved)
            self._plot_widget.addItem(self._cursor_b)

        view_range = self._plot_widget.getPlotItem().viewRange()[0]
        x_min, x_max = view_range[0], view_range[1]
        center = (x_min + x_max) / 2
        offset = max((x_max - x_min) * 0.08, 1e-12)
        if self._cursor_a_pos is None:
            self._cursor_a_pos = center - offset
            self._cursor_a.setValue(self._cursor_a_pos)
        if self._cursor_b_pos is None:
            self._cursor_b_pos = center + offset
            self._cursor_b.setValue(self._cursor_b_pos)

    def _remove_cursors(self):
        if self._cursor_a is not None:
            self._plot_widget.removeItem(self._cursor_a)
            self._cursor_a = None
        if self._cursor_b is not None:
            self._plot_widget.removeItem(self._cursor_b)
            self._cursor_b = None
        self._cursor_a_pos = None
        self._cursor_b_pos = None

    def _on_cursor_a_moved(self):
        if self._cursor_a is None:
            return
        self._cursor_a_pos = float(self._cursor_a.value())
        self._update_measurement()

    def _on_cursor_b_moved(self):
        if self._cursor_b is None:
            return
        self._cursor_b_pos = float(self._cursor_b.value())
        self._update_measurement()

    def _update_measurement(self):
        if self._spec is None:
            return
        values_a: Dict[str, float] = {}
        values_b: Dict[str, float] = {}
        if self._cursor_a_pos is not None:
            values_a = self._sample_series(self._cursor_a_pos)
        if self._cursor_b_pos is not None:
            values_b = self._sample_series(self._cursor_b_pos)
        cursor_a_x = self._to_display_x(self._cursor_a_pos)
        cursor_b_x = self._to_display_x(self._cursor_b_pos)
        self._measurement_bar.update_values(
            cursor_a_x,
            cursor_b_x,
            values_a,
            values_b,
            self._series_colors,
            show_frequency=self._should_show_frequency(),
        )

    def _sample_series(self, x_position: float) -> Dict[str, float]:
        if self._spec is None:
            return {}
        sampled: Dict[str, float] = {}
        for series in self._visible_series():
            x_data = np.asarray(series.x_data, dtype=float)
            if self._spec.log_x:
                x_data = np.log10(np.maximum(x_data, 1e-30))
            y_data = np.asarray(series.y_data, dtype=float)
            if len(x_data) == 0 or len(y_data) == 0:
                continue
            sampled[series.name] = float(np.interp(x_position, x_data, y_data))
        return sampled

    def _to_display_x(self, x_position: Optional[float]) -> Optional[float]:
        if x_position is None:
            return None
        if self._spec is not None and self._spec.log_x:
            return float(10 ** x_position)
        return float(x_position)

    def _should_show_frequency(self) -> bool:
        if self._spec is None:
            return False
        return "time" in self._spec.x_label.lower() and not self._spec.log_x

    def retranslate_ui(self):
        self._signal_title_label.setText(self._tr("Signals"))
        self._clear_all_btn.setText(self._tr("Clear"))

    def _tr(self, text: str) -> str:
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(f"chart_viewer.{text}", default=text)
        except ImportError:
            return text

    def _visible_series(self) -> List[ChartSeries]:
        if self._spec is None:
            return []
        visible_names = {
            name
            for name, item in self._series_items.items()
            if item.checkState(0) == Qt.CheckState.Checked
        }
        return [series for series in self._spec.series if series.name in visible_names]

    def _rebuild_plot(self):
        plot_item = self._plot_widget.getPlotItem()
        for item in list(self._plot_items.values()):
            plot_item.removeItem(item)
        self._plot_items.clear()

        try:
            self._legend.clear()
        except Exception:
            self._legend = plot_item.addLegend()

        self._series_colors = {}
        visible_series = self._visible_series()
        for series in visible_series:
            pen = pg.mkPen(series.color, width=1.6, style=Qt.PenStyle.SolidLine)
            item = pg.PlotDataItem(
                np.asarray(series.x_data, dtype=float),
                np.asarray(series.y_data, dtype=float),
                pen=pen,
                name=series.name,
            )
            plot_item.addItem(item)
            self._plot_items[series.name] = item
            self._series_colors[series.name] = series.color
            self._legend.addItem(item, series.name)

        if not visible_series:
            self._measurement_bar.clear_values()
            self._remove_cursors()
            self._measurement_bar.hide()
            self._x_domain = None
            self._y_domain = None
            return

        self._rebuild_domains()
        self._apply_full_viewport()

        if self.is_measurement_enabled():
            self._update_measurement()

    def _rebuild_domains(self):
        if self._spec is None:
            self._x_domain = None
            self._y_domain = None
            return

        x_ranges = []
        y_ranges = []
        for series in self._visible_series():
            x_range = finite_range(
                self._to_view_axis_data(series.x_data, log_enabled=self._spec.log_x),
                positive_only=self._spec.log_x,
            )
            y_range = finite_range(
                self._to_view_axis_data(series.y_data, log_enabled=self._spec.log_y),
                positive_only=self._spec.log_y,
            )
            if x_range is not None:
                x_ranges.append(x_range)
            if y_range is not None:
                y_ranges.append(y_range)

        self._x_domain = self._spec.x_domain or merge_ranges(x_ranges)
        self._y_domain = merge_ranges(y_ranges)

    def _apply_domain_limits(self):
        plot_item = self._plot_widget.getPlotItem()
        view_box = plot_item.vb
        if self._x_domain is not None:
            view_box.setLimits(xMin=self._x_domain[0], xMax=self._x_domain[1])
        if self._y_domain is not None:
            view_box.setLimits(yMin=self._y_domain[0], yMax=self._y_domain[1])

    def _apply_viewport(
        self,
        x_range: Optional[Tuple[float, float]],
        y_range: Optional[Tuple[float, float]],
    ):
        if x_range is None or y_range is None:
            return
        self._syncing_view = True
        try:
            plot_item = self._plot_widget.getPlotItem()
            plot_item.setXRange(x_range[0], x_range[1], padding=0.0)
            plot_item.setYRange(y_range[0], y_range[1], padding=0.0)
            apply_dynamic_tick_spacing(plot_item.getAxis('bottom'), x_range, log_enabled=self._spec.log_x if self._spec is not None else False)
            apply_dynamic_tick_spacing(plot_item.getAxis('left'), y_range, log_enabled=self._spec.log_y if self._spec is not None else False)
        finally:
            self._syncing_view = False

    def _apply_full_viewport(self):
        if self._x_domain is None or self._y_domain is None:
            return
        self._apply_domain_limits()
        self._apply_viewport(self._x_domain, self._y_domain)

    def _on_signal_item_changed(self, item: QTreeWidgetItem, column: int):
        if self._updating_tree or self._spec is None:
            return
        self._rebuild_plot()

    def _on_clear_all_series(self):
        self._updating_tree = True
        for item in self._series_items.values():
            item.setCheckState(0, Qt.CheckState.Unchecked)
        self._updating_tree = False
        self._rebuild_plot()

    def _on_rect_selected(
        self,
        requested_x_range: Tuple[float, float],
        requested_y_range: Tuple[float, float],
    ):
        if self._spec is None or not self._plot_items:
            return
        clamped_x_range = clamp_range(
            requested_x_range,
            self._x_domain,
            positive_only=self._spec.log_x,
        )
        clamped_y_range = clamp_range(
            requested_y_range,
            self._y_domain,
            positive_only=self._spec.log_y,
        )
        if clamped_x_range is None or clamped_y_range is None:
            return
        self._apply_domain_limits()
        self._apply_viewport(clamped_x_range, clamped_y_range)
        if self.is_measurement_enabled():
            self._update_measurement()

    def _to_view_axis_data(self, values: np.ndarray, *, log_enabled: bool) -> np.ndarray:
        array = np.asarray(values, dtype=float)
        if not log_enabled:
            return array
        transformed = np.full(array.shape, np.nan, dtype=float)
        mask = np.isfinite(array) & (array > 0)
        transformed[mask] = np.log10(array[mask])
        return transformed


class ChartViewer(QWidget):
    tab_changed = pyqtSignal(str)
    data_exported = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._logger = logging.getLogger(__name__)
        self._result: Optional[SimulationResult] = None
        self._chart_specs: List[ChartSpec] = []
        self._pages: List[ChartPage] = []

        self._setup_ui()
        self._apply_style()
        self.retranslate_ui()

    def _setup_ui(self):
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tab_bar = QTabBar()
        self._tab_bar.setObjectName("chartTabBar")
        self._tab_bar.setDrawBase(False)
        self._tab_bar.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tab_bar)

        self._stack = QStackedWidget()
        self._empty_label = QLabel()
        self._empty_label.setObjectName("emptyLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._stack, 1)
        layout.addWidget(self._empty_label, 1)
        self._empty_label.hide()

        self._toolbar = QToolBar()
        self._toolbar.setObjectName("chartToolbar")
        self._toolbar.setIconSize(QSize(16, 16))
        self._toolbar.setMovable(False)
        self._setup_toolbar()
        layout.addWidget(self._toolbar)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        self._hint_label = QLabel()
        self._hint_label.setObjectName("hintLabel")
        status_row.addStretch()
        status_row.addWidget(self._hint_label)
        layout.addLayout(status_row)

    def _setup_toolbar(self):
        self._action_fit = QAction("Fit", self)
        self._action_fit.triggered.connect(self._on_fit_to_view)
        self._toolbar.addAction(self._action_fit)

        self._toolbar.addSeparator()

        self._action_measure = QAction("Measure", self)
        self._action_measure.setCheckable(True)
        self._action_measure.triggered.connect(self._on_toggle_measurement)
        self._toolbar.addAction(self._action_measure)

        self._toolbar.addSeparator()

        self._action_save = QAction("Save", self)
        self._action_save.triggered.connect(self._on_save_chart)
        self._toolbar.addAction(self._action_save)

        self._action_copy = QAction("Copy", self)
        self._action_copy.triggered.connect(self._on_copy_chart)
        self._toolbar.addAction(self._action_copy)

        self._action_export_data = QAction("Export Data", self)
        self._action_export_data.triggered.connect(self._on_export_data)
        self._toolbar.addAction(self._action_export_data)

    def _apply_style(self):
        self.setStyleSheet(f"""
            ChartViewer {{
                background-color: {COLOR_BG_SECONDARY};
            }}
            #signalPanel {{
                background-color: {COLOR_BG_SECONDARY};
                border-right: 1px solid {COLOR_BORDER};
            }}
            #signalHeader {{
                background-color: {COLOR_BG_TERTIARY};
                border-bottom: 1px solid {COLOR_BORDER};
            }}
            #signalTitle {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_SMALL}px;
                font-weight: bold;
            }}
            #clearAllBtn {{
                background-color: transparent;
                color: {COLOR_TEXT_SECONDARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: 3px;
                padding: 1px 6px;
                font-size: {FONT_SIZE_SMALL}px;
            }}
            #clearAllBtn:hover {{
                background-color: {COLOR_BG_PRIMARY};
                color: {COLOR_TEXT_PRIMARY};
            }}
            #signalTree {{
                background-color: {COLOR_BG_SECONDARY};
                color: {COLOR_TEXT_PRIMARY};
                border: none;
                font-size: {FONT_SIZE_SMALL}px;
            }}
            #signalTree::item {{
                padding: 2px 0px;
            }}
            #signalTree::item:hover {{
                background-color: {COLOR_BG_TERTIARY};
            }}
            #chartTabBar {{
                background-color: {COLOR_BG_TERTIARY};
                border-bottom: 1px solid {COLOR_BORDER};
            }}
            #chartTabBar::tab {{
                background-color: transparent;
                color: {COLOR_TEXT_SECONDARY};
                padding: 6px 12px;
                margin-right: 2px;
                border: none;
                border-bottom: 2px solid transparent;
            }}
            #chartTabBar::tab:selected {{
                color: {COLOR_ACCENT};
                border-bottom: 2px solid {COLOR_ACCENT};
            }}
            #chartTabBar::tab:hover:!selected {{
                color: {COLOR_TEXT_PRIMARY};
                background-color: {COLOR_ACCENT_LIGHT};
            }}
            #chartToolbar {{
                background-color: {COLOR_BG_TERTIARY};
                border-top: 1px solid {COLOR_BORDER};
                spacing: {SPACING_SMALL}px;
                padding: {SPACING_SMALL}px;
            }}
            #chartToolbar QToolButton {{
                background-color: transparent;
                color: {COLOR_TEXT_PRIMARY};
                border: none;
                padding: 4px 8px;
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            #chartToolbar QToolButton:hover {{
                background-color: {COLOR_ACCENT_LIGHT};
            }}
            #chartToolbar QToolButton:checked {{
                background-color: {COLOR_ACCENT};
                color: white;
            }}
            #emptyLabel, #hintLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            #measurementBar {{
                background-color: {COLOR_BG_TERTIARY};
                border-top: 1px solid {COLOR_BORDER};
            }}
            #measurementBar QLabel {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_SMALL}px;
                font-family: Consolas, monospace;
            }}
            #signalValuesLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
                font-family: Consolas, monospace;
            }}
        """)

    def load_result(self, result: SimulationResult, enabled_chart_types: List[ChartType]):
        self._result = result
        self._action_measure.setChecked(False)
        self._chart_specs = self._build_chart_specs(result, enabled_chart_types)
        self._rebuild_pages()

    def clear(self):
        self._result = None
        self._chart_specs = []
        self._action_measure.setChecked(False)
        while self._tab_bar.count() > 0:
            self._tab_bar.removeTab(0)
        while self._stack.count() > 0:
            widget = self._stack.widget(0)
            self._stack.removeWidget(widget)
            widget.deleteLater()
        self._pages = []
        self._show_empty_state()

    def retranslate_ui(self):
        self._action_fit.setText(self._tr("Fit"))
        self._action_measure.setText(self._tr("Measure"))
        self._action_save.setText(self._tr("Save"))
        self._action_copy.setText(self._tr("Copy"))
        self._action_export_data.setText(self._tr("Export Data"))
        self._hint_label.setText(self._tr("Left-drag to zoom selected traces. Use Fit to restore the full selected range."))
        self._empty_label.setText(self._tr("No interactive chart available for the current result."))
        for page in self._pages:
            page.retranslate_ui()

    def _rebuild_pages(self):
        while self._tab_bar.count() > 0:
            self._tab_bar.removeTab(0)
        while self._stack.count() > 0:
            widget = self._stack.widget(0)
            self._stack.removeWidget(widget)
            widget.deleteLater()
        self._pages = []

        for spec in self._chart_specs:
            page = ChartPage()
            page.set_chart(spec)
            page.retranslate_ui()
            self._pages.append(page)
            self._stack.addWidget(page)
            self._tab_bar.addTab(ChartType.get_display_name(spec.chart_type))

        if self._pages:
            self._tab_bar.setCurrentIndex(0)
            self._stack.setCurrentIndex(0)
            self._hide_empty_state()
        else:
            self._show_empty_state()

    def _current_page(self) -> Optional[ChartPage]:
        index = self._tab_bar.currentIndex()
        if index < 0 or index >= len(self._pages):
            return None
        return self._pages[index]

    def _build_chart_specs(
        self,
        result: SimulationResult,
        enabled_chart_types: List[ChartType],
    ) -> List[ChartSpec]:
        if result is None or not result.success or result.data is None:
            return []

        enabled_supported = [ct for ct in enabled_chart_types if ct in SUPPORTED_CHART_TYPES]
        if not enabled_supported:
            return []

        specs: List[ChartSpec] = []
        analysis = (result.analysis_type or "").lower()
        for chart_type in enabled_supported:
            spec = self._build_chart_spec(result, analysis, chart_type)
            if spec is not None:
                spec.series = self._deduplicate_series(spec.series)
            if spec is not None and spec.series:
                specs.append(spec)
        return specs

    def _deduplicate_series(self, series_list: List[ChartSeries]) -> List[ChartSeries]:
        deduplicated: List[ChartSeries] = []
        seen_names = set()
        for series in series_list:
            if series.name in seen_names:
                continue
            deduplicated.append(series)
            seen_names.add(series.name)
        return deduplicated

    def _build_chart_spec(
        self,
        result: SimulationResult,
        analysis: str,
        chart_type: ChartType,
    ) -> Optional[ChartSpec]:
        data = result.data
        if data is None:
            return None

        resolved_x_data = result.get_x_axis_data()
        resolved_x_label = result.get_x_axis_label()
        resolved_log_x = result.is_x_axis_log()
        resolved_x_domain = self._resolve_chart_x_domain(result, resolved_x_data, resolved_log_x)

        if chart_type == ChartType.WAVEFORM_TIME and analysis == "tran":
            x_data = resolved_x_data
            if x_data is None:
                return None
            series = self._build_real_signal_series(result, x_data, include_derived=False)
            return ChartSpec(chart_type, "Transient Waveforms", resolved_x_label, "Value", series, log_x=resolved_log_x, x_domain=resolved_x_domain)

        if chart_type == ChartType.BODE_MAGNITUDE and analysis == "ac":
            x_data = resolved_x_data
            if x_data is None:
                return None
            series = self._build_bode_series(result, x_data, component="magnitude")
            return ChartSpec(chart_type, "Bode Magnitude", resolved_x_label, "Magnitude (dB)", series, log_x=resolved_log_x, x_domain=resolved_x_domain)

        if chart_type == ChartType.BODE_PHASE and analysis == "ac":
            x_data = resolved_x_data
            if x_data is None:
                return None
            series = self._build_bode_series(result, x_data, component="phase")
            return ChartSpec(chart_type, "Bode Phase", resolved_x_label, "Phase (°)", series, log_x=resolved_log_x, x_domain=resolved_x_domain)

        if chart_type == ChartType.DC_SWEEP and analysis == "dc":
            x_data = resolved_x_data
            if x_data is None:
                return None
            series = self._build_real_signal_series(result, x_data, include_derived=False)
            return ChartSpec(chart_type, "DC Sweep", resolved_x_label, "Value", series, log_x=resolved_log_x, x_domain=resolved_x_domain)

        if chart_type == ChartType.NOISE_SPECTRUM and analysis == "noise":
            x_data = resolved_x_data
            if x_data is None:
                return None
            series = self._build_noise_series(result, x_data)
            return ChartSpec(chart_type, "Noise Spectrum", resolved_x_label, "Noise Spectral Density", series, log_x=resolved_log_x, log_y=True, x_domain=resolved_x_domain)

        return None

    def _resolve_chart_x_domain(
        self,
        result: SimulationResult,
        x_data: Optional[np.ndarray],
        log_enabled: bool,
    ) -> Optional[Tuple[float, float]]:
        requested_range = result.requested_x_range
        if requested_range is not None:
            requested_array = np.asarray(requested_range, dtype=float)
            if log_enabled:
                transformed = np.full(requested_array.shape, np.nan, dtype=float)
                mask = np.isfinite(requested_array) & (requested_array > 0)
                transformed[mask] = np.log10(requested_array[mask])
                requested_domain = finite_range(transformed)
            else:
                requested_domain = finite_range(requested_array)
            if requested_domain is not None:
                return requested_domain

        if x_data is None:
            return None

        if log_enabled:
            transformed = np.full(x_data.shape, np.nan, dtype=float)
            mask = np.isfinite(x_data) & (x_data > 0)
            transformed[mask] = np.log10(x_data[mask])
            return finite_range(transformed)

        return finite_range(np.asarray(x_data, dtype=float))

    def _build_real_signal_series(
        self,
        result: SimulationResult,
        x_data: np.ndarray,
        *,
        include_derived: bool,
    ) -> List[ChartSeries]:
        data = result.data
        if data is None:
            return []
        series: List[ChartSeries] = []
        for index, signal_name in enumerate(self._get_base_signal_names(result, include_derived=include_derived)):
            y_data = data.get_signal(signal_name)
            if y_data is None or np.iscomplexobj(y_data) or len(y_data) != len(x_data):
                continue
            series.append(
                ChartSeries(
                    name=signal_name,
                    x_data=np.asarray(x_data, dtype=float),
                    y_data=np.asarray(y_data, dtype=float),
                    color=SERIES_COLORS[index % len(SERIES_COLORS)],
                )
            )
        return series

    def _build_bode_series(
        self,
        result: SimulationResult,
        x_data: np.ndarray,
        *,
        component: str,
    ) -> List[ChartSeries]:
        data = result.data
        if data is None:
            return []
        series: List[ChartSeries] = []
        color_index = 0
        for signal_name in self._get_base_signal_names(result, include_derived=False):
            raw_signal = data.get_signal(signal_name)
            derived_name = f"{signal_name}_{'mag' if component == 'magnitude' else 'phase'}"
            derived_signal = data.get_signal(derived_name)
            if raw_signal is None and derived_signal is None:
                continue

            if component == "magnitude":
                if raw_signal is not None and np.iscomplexobj(raw_signal):
                    y_data = 20 * np.log10(np.maximum(np.abs(raw_signal), 1e-30))
                elif derived_signal is not None:
                    y_data = 20 * np.log10(np.maximum(np.asarray(derived_signal, dtype=float), 1e-30))
                else:
                    continue
            else:
                if raw_signal is not None and np.iscomplexobj(raw_signal):
                    y_data = np.degrees(np.angle(raw_signal))
                elif derived_signal is not None:
                    y_data = np.asarray(derived_signal, dtype=float)
                else:
                    continue

            if len(y_data) != len(x_data):
                continue
            series.append(
                ChartSeries(
                    name=signal_name,
                    x_data=np.asarray(x_data, dtype=float),
                    y_data=np.asarray(y_data, dtype=float),
                    color=SERIES_COLORS[color_index % len(SERIES_COLORS)],
                )
            )
            color_index += 1
        return series

    def _build_noise_series(self, result: SimulationResult, x_data: np.ndarray) -> List[ChartSeries]:
        data = result.data
        if data is None:
            return []
        series: List[ChartSeries] = []
        color_index = 0
        for signal_name in self._get_base_signal_names(result, include_derived=False):
            signal = data.get_signal(signal_name)
            if signal is None:
                continue
            y_data = np.abs(signal) if np.iscomplexobj(signal) else np.asarray(signal, dtype=float)
            if len(y_data) != len(x_data):
                continue
            y_data = np.maximum(np.asarray(y_data, dtype=float), 1e-30)
            series.append(
                ChartSeries(
                    name=signal_name,
                    x_data=np.asarray(x_data, dtype=float),
                    y_data=y_data,
                    color=SERIES_COLORS[color_index % len(SERIES_COLORS)],
                )
            )
            color_index += 1
        return series

    def _get_base_signal_names(self, result: SimulationResult, *, include_derived: bool) -> List[str]:
        data = result.data
        if data is None:
            return []
        signal_types = getattr(data, "signal_types", {})
        signal_names = data.get_signal_names()
        filtered: List[str] = []
        for name in signal_names:
            if not include_derived and name.endswith(DERIVED_SIGNAL_SUFFIXES):
                continue
            filtered.append(name)
        filtered.sort(key=lambda name: self._signal_sort_key(name, signal_types))
        return filtered

    def _signal_sort_key(self, name: str, signal_types: Dict[str, str]):
        name_lower = name.lower()
        if "out" in name_lower:
            role_rank = 0
        elif "in" in name_lower:
            role_rank = 1
        else:
            role_rank = 2
        signal_type = signal_types.get(name, "")
        type_rank = {"voltage": 0, "current": 1, "other": 2}.get(signal_type, 2)
        return (role_rank, type_rank, name_lower)

    def _on_tab_changed(self, index: int):
        if index < 0 or index >= len(self._chart_specs):
            return
        self._stack.setCurrentIndex(index)
        self._action_measure.setChecked(False)
        for page in self._pages:
            page.set_measurement_enabled(False)
        self.tab_changed.emit(self._chart_specs[index].chart_type.value)

    def _on_fit_to_view(self):
        page = self._current_page()
        if page is not None:
            page.fit_to_view()

    def _on_toggle_measurement(self, checked: bool):
        page = self._current_page()
        if page is not None:
            page.set_measurement_enabled(checked)

    def _on_save_chart(self):
        page = self._current_page()
        if page is None or not page.has_chart():
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._tr("Save Chart"),
            "",
            "PNG Files (*.png);;All Files (*)",
        )
        if path and not page.export_image(path):
            QMessageBox.warning(self, self._tr("Save Chart"), self._tr("Failed to save chart image."))

    def _on_copy_chart(self):
        page = self._current_page()
        if page is None or not page.has_chart():
            return
        if not page.copy_image():
            QMessageBox.warning(self, self._tr("Copy"), self._tr("Failed to copy chart image."))

    def _on_export_data(self):
        page = self._current_page()
        if page is None or not page.has_chart():
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            self._tr("Export Data"),
            "",
            "CSV Files (*.csv);;JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        if path.endswith(".json") or "JSON" in selected_filter:
            format_name = "json"
        else:
            format_name = "csv"
            if not path.endswith(".csv"):
                path += ".csv"
        if page.export_chart_data(path, format_name):
            self.data_exported.emit(path)
        else:
            QMessageBox.warning(self, self._tr("Export Data"), self._tr("Failed to export chart data."))

    def _show_empty_state(self):
        self._stack.hide()
        self._empty_label.show()

    def _hide_empty_state(self):
        self._empty_label.hide()
        self._stack.show()

    def _tr(self, text: str) -> str:
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(f"chart_viewer.{text}", default=text)
        except ImportError:
            return text


__all__ = ["ChartViewer", "ChartSpec", "ChartSeries", "SUPPORTED_CHART_TYPES"]
