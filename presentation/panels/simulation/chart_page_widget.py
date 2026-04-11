from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSplitter, QTreeWidgetItem, QVBoxLayout, QWidget

from presentation.panels.simulation.chart_data_cursor import ChartDataCursorController, DataCursorSample, DataCursorValue, build_draggable_vertical_cursor_line
from presentation.panels.simulation.chart_export_utils import build_chart_export_payload
from presentation.panels.simulation.chart_signal_tree import SignalTreeWidget
from presentation.panels.simulation.chart_view_types import ChartSeries, ChartSpec
from presentation.panels.simulation.ltspice_plot_interaction import (
    LTSpiceViewBox,
    apply_dynamic_tick_spacing,
    clamp_range,
    finite_range,
    merge_ranges,
)
from resources.theme import (
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
        self._spec: Optional[ChartSpec] = None
        self._cursor_a: Optional[pg.InfiniteLine] = None
        self._cursor_b: Optional[pg.InfiniteLine] = None
        self._cursor_a_pos: Optional[float] = None
        self._cursor_b_pos: Optional[float] = None
        self._series_colors: Dict[str, str] = {}
        self._plot_items: Dict[str, pg.PlotDataItem] = {}
        self._series_items: Dict[str, QTreeWidgetItem] = {}
        self._updating_tree = False
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

        self._signal_tree = SignalTreeWidget()
        self._signal_tree.setObjectName("signalTree")
        self._signal_tree.setHeaderHidden(True)
        self._signal_tree.setRootIsDecorated(False)
        self._signal_tree.itemChanged.connect(self._on_signal_item_changed)
        self._signal_tree.signal_label_clicked.connect(self._on_signal_label_clicked)
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
        self._data_cursor = ChartDataCursorController(
            plot_widget=self._plot_widget,
            sample_at=self._sample_cursor_target,
            x_bounds=self._data_cursor_x_bounds,
            parent=self,
        )

        self._measurement_bar = MeasurementBar()
        right_layout.addWidget(self._measurement_bar)

        self._main_splitter.addWidget(right_panel)
        self._main_splitter.setSizes([180, 620])
        layout.addWidget(self._main_splitter, 1)

        self.setStyleSheet(f"""
            QWidget {{
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

    def clear(self):
        self._plot_widget.clear()
        plot_item = self._plot_widget.getPlotItem()
        plot_item.showGrid(x=True, y=True, alpha=0.25)
        plot_item.disableAutoRange()
        self._legend = plot_item.addLegend()
        self._remove_cursors()
        self._data_cursor.clear()
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
            is_default_visible = len(valid_series) == 1
            item.setCheckState(0, Qt.CheckState.Checked if is_default_visible else Qt.CheckState.Unchecked)
            self._series_items[series.name] = item
        self._updating_tree = False

        self._spec.series = valid_series
        if valid_series:
            self._signal_tree.setCurrentItem(self._series_items[valid_series[0].name])
        self._rebuild_plot()

    def has_chart(self) -> bool:
        return bool(self._plot_items)

    def fit_to_view(self):
        self._rebuild_plot()

    def supports_data_cursor(self) -> bool:
        return bool(self._spec is not None and self._spec.series)

    def _activate_cursor_target(self, target_id: str) -> bool:
        if not target_id or target_id not in self._series_items:
            return False
        item = self._series_items[target_id]
        self._signal_tree.setCurrentItem(item)
        if item.checkState(0) != Qt.CheckState.Checked:
            self._updating_tree = True
            item.setCheckState(0, Qt.CheckState.Checked)
            self._updating_tree = False
            self._rebuild_plot()
        self._data_cursor.set_target(target_id)
        return True

    def set_data_cursor_enabled(self, enabled: bool):
        self._data_cursor.set_enabled(enabled)

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
        self.resize(max(self.width(), 1280), max(self.height(), 840))
        layout = self.layout()
        if layout is not None:
            layout.activate()
        render_width = max(self._plot_widget.width(), 960)
        render_height = max(self._plot_widget.height(), 640)
        pixmap = QPixmap(render_width, render_height)
        pixmap.fill(Qt.GlobalColor.transparent)
        self._plot_widget.render(pixmap)
        if pixmap.isNull():
            return False
        return pixmap.save(path)

    def build_export_payload(self) -> Optional[Dict[str, Any]]:
        if self._spec is None or not self._spec.series:
            return None
        return build_chart_export_payload(self._spec, self._spec.series)

    def _ensure_cursors(self):
        if self._spec is None or not self._plot_items or self._x_domain is None:
            return
        if self._cursor_a is None:
            self._cursor_a = build_draggable_vertical_cursor_line("#ff6b6b", bounds=self._x_domain)
            self._cursor_a.sigPositionChanged.connect(self._on_cursor_a_moved)
            self._plot_widget.addItem(self._cursor_a)
        if self._cursor_b is None:
            self._cursor_b = build_draggable_vertical_cursor_line("#2ecc71", bounds=self._x_domain)
            self._cursor_b.sigPositionChanged.connect(self._on_cursor_b_moved)
            self._plot_widget.addItem(self._cursor_b)

        self._cursor_a.setBounds(self._x_domain)
        self._cursor_b.setBounds(self._x_domain)

        view_range = self._plot_widget.getPlotItem().viewRange()[0]
        x_min, x_max = view_range[0], view_range[1]
        center = (x_min + x_max) / 2
        offset = max((x_max - x_min) * 0.08, 1e-12)
        if self._cursor_a_pos is None:
            self._cursor_a_pos = center - offset
        self._cursor_a_pos = min(max(self._cursor_a_pos, self._x_domain[0]), self._x_domain[1])
        self._cursor_a.setValue(self._cursor_a_pos)
        if self._cursor_b_pos is None:
            self._cursor_b_pos = center + offset
        self._cursor_b_pos = min(max(self._cursor_b_pos, self._x_domain[0]), self._x_domain[1])
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

    def _to_plot_y_value(self, y_value: float) -> float:
        if self._spec is None:
            return float(y_value)
        transformed = self._to_view_axis_data(np.asarray([y_value], dtype=float), log_enabled=self._spec.log_y)
        return float(transformed[0])

    def _data_cursor_x_bounds(self) -> Optional[Tuple[float, float]]:
        return self._x_domain

    def _find_series_by_name(self, series_name: str) -> Optional[ChartSeries]:
        if self._spec is None:
            return None
        for series in self._spec.series:
            if series.name == series_name:
                return series
        return None

    def _sample_cursor_target(self, target_id: str, x_position: float) -> Optional[DataCursorSample]:
        series = self._find_series_by_name(target_id)
        if series is None or target_id not in self._plot_items:
            return None
        x_display = self._to_display_x(x_position)
        if x_display is None:
            return None
        sampled_values = self._sample_series(x_position)
        if target_id not in sampled_values:
            return None
        y_value = float(sampled_values[target_id])
        return DataCursorSample(
            title=target_id,
            plot_y_value=self._to_plot_y_value(y_value),
            values=[
                DataCursorValue(label=f"{self._spec.x_label}:", value_text=f"{x_display:.6g}"),
                DataCursorValue(label=f"{self._spec.y_label}:", value_text=f"{y_value:.6g}"),
            ],
        )

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
            )
            plot_item.addItem(item)
            self._plot_items[series.name] = item
            self._series_colors[series.name] = series.color
            self._legend.addItem(item, series.name)

        if not visible_series:
            self._measurement_bar.clear_values()
            self._remove_cursors()
            if self._data_cursor.is_enabled():
                self._data_cursor.refresh()
            self._measurement_bar.hide()
            self._x_domain = None
            self._y_domain = None
            return

        self._rebuild_domains()
        self._apply_full_viewport()

        if self.is_measurement_enabled():
            self._update_measurement()
        if self._data_cursor.is_enabled():
            self._data_cursor.refresh()

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
        plot_item = self._plot_widget.getPlotItem()
        plot_item.setXRange(x_range[0], x_range[1], padding=0.0)
        plot_item.setYRange(y_range[0], y_range[1], padding=0.0)
        apply_dynamic_tick_spacing(plot_item.getAxis('bottom'), x_range, log_enabled=self._spec.log_x if self._spec is not None else False)
        apply_dynamic_tick_spacing(plot_item.getAxis('left'), y_range, log_enabled=self._spec.log_y if self._spec is not None else False)

    def _apply_full_viewport(self):
        if self._x_domain is None or self._y_domain is None:
            return
        self._apply_domain_limits()
        self._apply_viewport(self._x_domain, self._y_domain)

    def _on_signal_item_changed(self, item: QTreeWidgetItem, column: int):
        if self._updating_tree or self._spec is None:
            return
        if item.checkState(0) != Qt.CheckState.Checked and item.text(0) == self._data_cursor.target_id():
            self._data_cursor.set_target("")
        self._rebuild_plot()

    def _on_signal_label_clicked(self, item: QTreeWidgetItem):
        if self._spec is None or self._updating_tree or item is None:
            return
        if not self._data_cursor.is_enabled():
            return
        self._activate_cursor_target(item.text(0))

    def _on_clear_all_series(self):
        self._updating_tree = True
        for item in self._series_items.values():
            item.setCheckState(0, Qt.CheckState.Unchecked)
        self._updating_tree = False
        self._data_cursor.set_target("")
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
        if self._data_cursor.is_enabled():
            self._data_cursor.refresh()

    def _to_view_axis_data(self, values: np.ndarray, *, log_enabled: bool) -> np.ndarray:
        array = np.asarray(values, dtype=float)
        if not log_enabled:
            return array
        transformed = np.full(array.shape, np.nan, dtype=float)
        mask = np.isfinite(array) & (array > 0)
        transformed[mask] = np.log10(array[mask])
        return transformed


__all__ = ["ChartPage", "MeasurementBar"]
