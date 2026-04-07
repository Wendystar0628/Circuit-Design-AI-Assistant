from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from presentation.panels.simulation.chart_page_widget import MeasurementBar
from presentation.panels.simulation.chart_view_types import ChartSeries, ChartSpec
from presentation.panels.simulation.ltspice_plot_interaction import LTSpiceViewBox, apply_dynamic_tick_spacing, clamp_range, finite_range, merge_ranges, nice_tick_spacing
from resources.theme import COLOR_BG_PRIMARY, COLOR_BG_SECONDARY, COLOR_BG_TERTIARY, COLOR_BORDER, COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY, FONT_SIZE_SMALL, SPACING_NORMAL, SPACING_SMALL


class BodeCursorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setModal(False)
        self.setWindowTitle("Bode Cursor")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_SMALL)

        self._series_label = QLabel("--")
        layout.addWidget(self._series_label)

        form = QFormLayout()
        self._freq_value = QLabel("--")
        self._mag_value = QLabel("--")
        self._phase_value = QLabel("--")
        self._delay_value = QLabel("--")
        form.addRow("Freq:", self._freq_value)
        form.addRow("Mag:", self._mag_value)
        form.addRow("Phase:", self._phase_value)
        form.addRow("Group Delay:", self._delay_value)
        layout.addLayout(form)

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
        self.resize(260, 140)

    def clear_values(self):
        self._series_label.setText("--")
        self._freq_value.setText("--")
        self._mag_value.setText("--")
        self._phase_value.setText("--")
        self._delay_value.setText("--")

    def update_values(
        self,
        *,
        series_name: str,
        frequency_hz: float,
        magnitude_db: float,
        phase_deg: float,
        group_delay_seconds: Optional[float],
    ):
        self._series_label.setText(series_name)
        self._freq_value.setText(_format_frequency_value(frequency_hz))
        self._mag_value.setText(f"{magnitude_db:.6g} dB")
        self._phase_value.setText(f"{phase_deg:.6g}°")
        if group_delay_seconds is None or not np.isfinite(group_delay_seconds):
            self._delay_value.setText("--")
        else:
            self._delay_value.setText(_format_duration_value(group_delay_seconds))


class BodeOverlayChartPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._spec: Optional[ChartSpec] = None
        self._series_items: Dict[str, QTreeWidgetItem] = {}
        self._series_groups: Dict[str, Dict[str, ChartSeries]] = {}
        self._plot_items: Dict[str, pg.PlotDataItem] = {}
        self._group_colors: Dict[str, str] = {}
        self._updating_tree = False
        self._measurement_enabled = False
        self._cursor_a: Optional[pg.InfiniteLine] = None
        self._cursor_b: Optional[pg.InfiniteLine] = None
        self._cursor_a_pos: Optional[float] = None
        self._cursor_b_pos: Optional[float] = None
        self._data_cursor_enabled = False
        self._data_cursor_line: Optional[pg.InfiniteLine] = None
        self._data_cursor_crosshair: Optional[pg.InfiniteLine] = None
        self._data_cursor_marker: Optional[pg.ScatterPlotItem] = None
        self._data_cursor_pos: Optional[float] = None
        self._active_cursor_group: str = ""
        self._cursor_dialog = BodeCursorDialog(self)
        self._x_domain: Optional[Tuple[float, float]] = None
        self._mag_domain: Optional[Tuple[float, float]] = None
        self._phase_domain: Optional[Tuple[float, float]] = None
        self._mag_view_range: Optional[Tuple[float, float]] = None
        self._phase_view_range: Optional[Tuple[float, float]] = None

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
        self._signal_tree.itemSelectionChanged.connect(self._on_signal_selection_changed)
        signal_layout.addWidget(self._signal_tree)

        self._main_splitter.addWidget(self._signal_panel)

        right_panel = QFrame()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._plot_widget = pg.PlotWidget(viewBox=LTSpiceViewBox())
        self._plot_widget.setBackground(COLOR_BG_PRIMARY)
        self._plot_item = self._plot_widget.getPlotItem()
        self._plot_item.showGrid(x=True, y=True, alpha=0.25)
        self._plot_item.disableAutoRange()
        self._plot_item.showAxis("right")
        self._plot_item.getAxis("right").setWidth(72)
        view_box = self._plot_item.vb
        if isinstance(view_box, LTSpiceViewBox):
            view_box.rect_selected.connect(self._on_rect_selected)
        self._legend = self._plot_item.addLegend()
        right_layout.addWidget(self._plot_widget, 1)

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
        self._plot_item = self._plot_widget.getPlotItem()
        self._plot_item.showGrid(x=True, y=True, alpha=0.25)
        self._plot_item.disableAutoRange()
        self._plot_item.showAxis("right")
        self._plot_item.getAxis("right").setWidth(72)
        self._legend = self._plot_item.addLegend()
        view_box = self._plot_item.vb
        if isinstance(view_box, LTSpiceViewBox):
            try:
                view_box.rect_selected.disconnect(self._on_rect_selected)
            except Exception:
                pass
            view_box.rect_selected.connect(self._on_rect_selected)
        self._remove_measurement_cursors()
        self._remove_data_cursor()
        self._measurement_bar.clear_values()
        self._measurement_bar.hide()
        self._cursor_dialog.hide()
        self._cursor_dialog.clear_values()
        self._spec = None
        self._series_items = {}
        self._series_groups = {}
        self._plot_items = {}
        self._group_colors = {}
        self._x_domain = None
        self._mag_domain = None
        self._phase_domain = None
        self._mag_view_range = None
        self._phase_view_range = None
        self._active_cursor_group = ""
        self._data_cursor_pos = None
        self._signal_tree.clear()

    def set_chart(self, spec: ChartSpec):
        self.clear()
        self._spec = spec
        self._plot_item.setTitle(spec.title)
        self._plot_item.setLabel("bottom", spec.x_label)
        self._plot_item.setLabel("left", spec.y_label)
        self._plot_item.setLabel("right", spec.secondary_y_label or "Phase (°)")
        self._plot_item.setLogMode(x=spec.log_x, y=False)

        valid_series: List[ChartSeries] = []
        self._updating_tree = True
        for series in spec.series:
            x_data = np.asarray(series.x_data, dtype=float)
            y_data = np.asarray(series.y_data, dtype=float)
            if len(x_data) == 0 or len(y_data) == 0 or len(x_data) != len(y_data):
                continue
            group_key = series.group_key or series.name
            normalized = ChartSeries(
                name=series.name,
                x_data=x_data,
                y_data=y_data,
                color=series.color,
                axis_key=series.axis_key,
                line_style=series.line_style,
                group_key=group_key,
                component=series.component,
            )
            valid_series.append(normalized)
            if group_key not in self._series_items:
                item = QTreeWidgetItem(self._signal_tree, [group_key])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
                item.setCheckState(0, Qt.CheckState.Checked)
                self._series_items[group_key] = item
        self._updating_tree = False
        if self._signal_tree.topLevelItemCount() > 0:
            self._signal_tree.setCurrentItem(self._signal_tree.topLevelItem(0))

        spec.series = valid_series
        self._rebuild_series_groups()
        self._rebuild_plot()

    def has_chart(self) -> bool:
        return bool(self._plot_items)

    def supports_data_cursor(self) -> bool:
        return True

    def fit_to_view(self):
        self._rebuild_plot()

    def set_measurement_enabled(self, enabled: bool):
        self._measurement_enabled = bool(enabled)
        if enabled:
            self._ensure_measurement_cursors()
            self._measurement_bar.show()
            self._update_measurement()
        else:
            self._remove_measurement_cursors()
            self._measurement_bar.clear_values()
            self._measurement_bar.hide()

    def set_data_cursor_enabled(self, enabled: bool):
        self._data_cursor_enabled = bool(enabled)
        if enabled:
            self._ensure_active_cursor_group()
            if not self._active_cursor_group:
                self._remove_data_cursor()
                self._cursor_dialog.hide()
                return
            self._ensure_data_cursor()
            self._cursor_dialog.show()
            self._cursor_dialog.raise_()
            self._update_data_cursor()
        else:
            self._remove_data_cursor()
            self._cursor_dialog.hide()
            self._cursor_dialog.clear_values()

    def export_image(self, path: str) -> bool:
        pixmap = self._plot_widget.grab()
        if pixmap.isNull():
            return False
        return pixmap.save(path)

    def export_chart_data(self, path: str, format_name: str) -> bool:
        import csv
        import json

        payload = self.build_export_payload()
        if payload is None:
            return False
        if format_name == "json":
            Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return True
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            headers = [payload["x_label"]] + [series["name"] for series in payload["series"]]
            writer.writerow(headers)
            for row in payload["rows"]:
                writer.writerow([row.get(header, "") for header in headers])
        return True

    def build_export_payload(self) -> Optional[Dict[str, object]]:
        if self._spec is None:
            return None
        visible_series = self._visible_series()
        if not visible_series:
            return None
        rows: List[Dict[str, float]] = []
        primary_x = visible_series[0].x_data
        for index, x_value in enumerate(primary_x):
            row: Dict[str, float] = {self._spec.x_label: float(x_value)}
            for series in visible_series:
                if index < len(series.y_data):
                    row[series.name] = float(series.y_data[index])
            rows.append(row)
        return {
            "chart_type": self._spec.chart_type.value,
            "title": self._spec.title,
            "x_label": self._spec.x_label,
            "y_label": self._spec.y_label,
            "secondary_y_label": self._spec.secondary_y_label,
            "log_x": self._spec.log_x,
            "log_y": False,
            "series": [
                {
                    "name": series.name,
                    "color": series.color,
                    "axis_key": series.axis_key,
                    "line_style": series.line_style,
                    "group_key": series.group_key,
                    "component": series.component,
                    "x": [float(value) for value in series.x_data],
                    "y": [float(value) for value in series.y_data],
                    "point_count": len(series.y_data),
                }
                for series in visible_series
            ],
            "rows": rows,
        }

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

    def _rebuild_series_groups(self):
        self._series_groups = {}
        self._group_colors = {}
        if self._spec is None:
            return
        for series in self._spec.series:
            group_key = series.group_key or series.name
            bucket = self._series_groups.setdefault(group_key, {})
            bucket[series.component] = series
            self._group_colors[group_key] = series.color

    def _visible_group_keys(self) -> List[str]:
        return [key for key, item in self._series_items.items() if item.checkState(0) == Qt.CheckState.Checked]

    def _visible_series(self) -> List[ChartSeries]:
        if self._spec is None:
            return []
        visible_groups = set(self._visible_group_keys())
        return [series for series in self._spec.series if (series.group_key or series.name) in visible_groups]

    def _is_log_x(self) -> bool:
        return bool(self._spec.log_x) if self._spec is not None else False

    def _to_view_axis_data(self, values: np.ndarray, *, log_enabled: bool) -> np.ndarray:
        array = np.asarray(values, dtype=float)
        if not log_enabled:
            return array
        transformed = np.full(array.shape, np.nan, dtype=float)
        mask = np.isfinite(array) & (array > 0)
        transformed[mask] = np.log10(array[mask])
        return transformed

    def _to_display_x(self, x_position: Optional[float]) -> Optional[float]:
        if x_position is None:
            return None
        if self._is_log_x():
            return float(10 ** x_position)
        return float(x_position)

    def _rebuild_domains(self):
        x_ranges = []
        mag_ranges = []
        phase_ranges = []
        for group_key in self._visible_group_keys():
            pair = self._series_groups.get(group_key, {})
            mag_series = pair.get("magnitude")
            phase_series = pair.get("phase")
            if mag_series is not None:
                x_range = finite_range(self._to_view_axis_data(mag_series.x_data, log_enabled=self._is_log_x()), positive_only=self._is_log_x())
                mag_range = finite_range(np.asarray(mag_series.y_data, dtype=float))
                if x_range is not None:
                    x_ranges.append(x_range)
                if mag_range is not None:
                    mag_ranges.append(mag_range)
            if phase_series is not None:
                phase_range = finite_range(np.asarray(phase_series.y_data, dtype=float))
                if phase_range is not None:
                    phase_ranges.append(phase_range)

        self._x_domain = self._spec.x_domain if self._spec is not None else None
        if self._x_domain is None:
            self._x_domain = merge_ranges(x_ranges)
        self._mag_domain = merge_ranges(mag_ranges)
        self._phase_domain = merge_ranges(phase_ranges)
        self._mag_view_range = self._mag_domain
        self._phase_view_range = self._phase_domain

    def _phase_to_display_value(self, phase_value: float) -> float:
        if self._mag_view_range is None or self._phase_view_range is None:
            return float(phase_value)
        mag_min, mag_max = self._mag_view_range
        phase_min, phase_max = self._phase_view_range
        phase_span = phase_max - phase_min
        mag_span = mag_max - mag_min
        if abs(phase_span) <= 1e-30 or abs(mag_span) <= 1e-30:
            return mag_min
        normalized = (phase_value - phase_min) / phase_span
        return mag_min + normalized * mag_span

    def _map_phase_array_to_display(self, phase_values: np.ndarray) -> np.ndarray:
        phase_array = np.asarray(phase_values, dtype=float)
        if phase_array.size == 0:
            return phase_array
        return np.asarray([self._phase_to_display_value(value) for value in phase_array], dtype=float)

    def _pen_style_for_series(self, series: ChartSeries) -> Qt.PenStyle:
        if series.line_style == "dash":
            return Qt.PenStyle.DashLine
        return Qt.PenStyle.SolidLine

    def _rebuild_plot(self):
        for item in list(self._plot_items.values()):
            self._plot_item.removeItem(item)
        self._plot_items.clear()
        try:
            self._legend.clear()
        except Exception:
            self._legend = self._plot_item.addLegend()

        if not self._visible_group_keys():
            self._measurement_bar.clear_values()
            self._measurement_bar.hide()
            self._remove_measurement_cursors()
            self._remove_data_cursor()
            self._cursor_dialog.hide()
            self._x_domain = None
            self._mag_domain = None
            self._phase_domain = None
            self._mag_view_range = None
            self._phase_view_range = None
            return

        self._rebuild_domains()
        for group_key in self._visible_group_keys():
            pair = self._series_groups.get(group_key, {})
            mag_series = pair.get("magnitude")
            phase_series = pair.get("phase")
            if mag_series is not None:
                mag_pen = pg.mkPen(mag_series.color, width=1.6, style=self._pen_style_for_series(mag_series))
                mag_item = pg.PlotDataItem(np.asarray(mag_series.x_data, dtype=float), np.asarray(mag_series.y_data, dtype=float), pen=mag_pen)
                self._plot_item.addItem(mag_item)
                self._plot_items[mag_series.name] = mag_item
                self._legend.addItem(mag_item, group_key)
            if phase_series is not None:
                phase_pen = pg.mkPen(phase_series.color, width=1.4, style=self._pen_style_for_series(phase_series))
                phase_item = pg.PlotDataItem(np.asarray(phase_series.x_data, dtype=float), self._map_phase_array_to_display(np.asarray(phase_series.y_data, dtype=float)), pen=phase_pen)
                self._plot_item.addItem(phase_item)
                self._plot_items[phase_series.name] = phase_item

        self._apply_full_viewport()
        if self._measurement_enabled:
            self._ensure_measurement_cursors()
            self._measurement_bar.show()
            self._update_measurement()
        if self._data_cursor_enabled:
            self._ensure_active_cursor_group()
            self._ensure_data_cursor()
            self._cursor_dialog.show()
            self._update_data_cursor()

    def _apply_domain_limits(self):
        view_box = self._plot_item.vb
        if self._x_domain is not None:
            view_box.setLimits(xMin=self._x_domain[0], xMax=self._x_domain[1])
        if self._mag_domain is not None:
            view_box.setLimits(yMin=self._mag_domain[0], yMax=self._mag_domain[1])

    def _update_right_axis_ticks(self):
        axis = self._plot_item.getAxis("right")
        if self._phase_view_range is None or self._mag_view_range is None:
            axis.setTicks([])
            return
        phase_min, phase_max = self._phase_view_range
        step = nice_tick_spacing(max(phase_max - phase_min, 1e-9), target_ticks=8)
        start = np.floor(phase_min / step) * step
        stop = np.ceil(phase_max / step) * step
        ticks = []
        value = start
        while value <= stop + step * 0.5:
            display = self._phase_to_display_value(value)
            ticks.append((display, f"{value:.6g}"))
            value += step
        axis.setTicks([ticks, []])

    def _apply_viewport(
        self,
        x_range: Optional[Tuple[float, float]],
        mag_range: Optional[Tuple[float, float]],
        phase_range: Optional[Tuple[float, float]],
    ):
        if x_range is None or mag_range is None or phase_range is None:
            return
        self._mag_view_range = mag_range
        self._phase_view_range = phase_range
        self._apply_domain_limits()
        self._plot_item.setXRange(x_range[0], x_range[1], padding=0.0)
        self._plot_item.setYRange(mag_range[0], mag_range[1], padding=0.0)
        apply_dynamic_tick_spacing(self._plot_item.getAxis("bottom"), x_range, log_enabled=self._is_log_x())
        apply_dynamic_tick_spacing(self._plot_item.getAxis("left"), mag_range, log_enabled=False)
        self._update_right_axis_ticks()
        self._refresh_phase_curves()

    def _apply_full_viewport(self):
        if self._x_domain is None or self._mag_domain is None or self._phase_domain is None:
            return
        self._apply_viewport(self._x_domain, self._mag_domain, self._phase_domain)

    def _refresh_phase_curves(self):
        for pair in self._series_groups.values():
            phase_series = pair.get("phase")
            if phase_series is None:
                continue
            item = self._plot_items.get(phase_series.name)
            if item is None:
                continue
            item.setData(np.asarray(phase_series.x_data, dtype=float), self._map_phase_array_to_display(np.asarray(phase_series.y_data, dtype=float)))
        if self._data_cursor_enabled:
            self._update_data_cursor()

    def _sample_raw_series(self, series: ChartSeries, x_position: float) -> Optional[float]:
        x_data = self._to_view_axis_data(series.x_data, log_enabled=self._is_log_x())
        y_data = np.asarray(series.y_data, dtype=float)
        if len(x_data) == 0 or len(y_data) == 0:
            return None
        return float(np.interp(x_position, x_data, y_data))

    def _sample_measurement_values(self, x_position: float) -> Dict[str, float]:
        values: Dict[str, float] = {}
        for group_key in self._visible_group_keys():
            pair = self._series_groups.get(group_key, {})
            mag_series = pair.get("magnitude")
            phase_series = pair.get("phase")
            if mag_series is not None:
                mag_value = self._sample_raw_series(mag_series, x_position)
                if mag_value is not None:
                    values[f"{group_key} Mag"] = mag_value
            if phase_series is not None:
                phase_value = self._sample_raw_series(phase_series, x_position)
                if phase_value is not None:
                    values[f"{group_key} Phase"] = phase_value
        return values

    def _measurement_colors(self) -> Dict[str, str]:
        colors: Dict[str, str] = {}
        for group_key in self._visible_group_keys():
            color = self._group_colors.get(group_key, "#ffffff")
            colors[f"{group_key} Mag"] = color
            colors[f"{group_key} Phase"] = color
        return colors

    def _ensure_measurement_cursors(self):
        if self._x_domain is None:
            return
        if self._cursor_a is None:
            self._cursor_a = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen("#ff6b6b", width=1, style=Qt.PenStyle.DashLine))
            self._cursor_a.sigPositionChanged.connect(self._on_cursor_a_moved)
            self._plot_widget.addItem(self._cursor_a)
        if self._cursor_b is None:
            self._cursor_b = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen("#2ecc71", width=1, style=Qt.PenStyle.DashLine))
            self._cursor_b.sigPositionChanged.connect(self._on_cursor_b_moved)
            self._plot_widget.addItem(self._cursor_b)
        x_min, x_max = self._plot_item.viewRange()[0]
        center = (x_min + x_max) / 2
        offset = max((x_max - x_min) * 0.08, 1e-12)
        if self._cursor_a_pos is None:
            self._cursor_a_pos = center - offset
            self._cursor_a.setValue(self._cursor_a_pos)
        if self._cursor_b_pos is None:
            self._cursor_b_pos = center + offset
            self._cursor_b.setValue(self._cursor_b_pos)

    def _remove_measurement_cursors(self):
        if self._cursor_a is not None:
            self._plot_widget.removeItem(self._cursor_a)
            self._cursor_a = None
        if self._cursor_b is not None:
            self._plot_widget.removeItem(self._cursor_b)
            self._cursor_b = None
        self._cursor_a_pos = None
        self._cursor_b_pos = None

    def _update_measurement(self):
        values_a = self._sample_measurement_values(self._cursor_a_pos) if self._cursor_a_pos is not None else {}
        values_b = self._sample_measurement_values(self._cursor_b_pos) if self._cursor_b_pos is not None else {}
        self._measurement_bar.update_values(
            self._to_display_x(self._cursor_a_pos),
            self._to_display_x(self._cursor_b_pos),
            values_a,
            values_b,
            self._measurement_colors(),
            show_frequency=False,
        )

    def _ensure_active_cursor_group(self):
        visible_groups = self._visible_group_keys()
        if self._active_cursor_group in visible_groups:
            return
        current_item = self._signal_tree.currentItem()
        if current_item is not None and current_item.checkState(0) == Qt.CheckState.Checked:
            self._active_cursor_group = current_item.text(0)
            return
        self._active_cursor_group = visible_groups[0] if visible_groups else ""

    def _ensure_data_cursor(self):
        if not self._active_cursor_group or self._mag_view_range is None:
            return
        if self._data_cursor_line is None:
            self._data_cursor_line = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen("#dddddd", width=1, style=Qt.PenStyle.DashLine))
            self._data_cursor_line.sigPositionChanged.connect(self._on_data_cursor_moved)
            self._plot_widget.addItem(self._data_cursor_line)
        if self._data_cursor_crosshair is None:
            self._data_cursor_crosshair = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen("#dddddd", width=1, style=Qt.PenStyle.DashLine))
            self._plot_widget.addItem(self._data_cursor_crosshair)
        if self._data_cursor_marker is None:
            self._data_cursor_marker = pg.ScatterPlotItem(size=7, brush=pg.mkBrush("#ffffff"), pen=pg.mkPen("#ffffff"))
            self._plot_widget.addItem(self._data_cursor_marker)
        if self._data_cursor_pos is None:
            x_min, x_max = self._plot_item.viewRange()[0]
            self._data_cursor_pos = (x_min + x_max) / 2
        self._data_cursor_line.setValue(self._data_cursor_pos)

    def _remove_data_cursor(self):
        if self._data_cursor_line is not None:
            self._plot_widget.removeItem(self._data_cursor_line)
            self._data_cursor_line = None
        if self._data_cursor_crosshair is not None:
            self._plot_widget.removeItem(self._data_cursor_crosshair)
            self._data_cursor_crosshair = None
        if self._data_cursor_marker is not None:
            self._plot_widget.removeItem(self._data_cursor_marker)
            self._data_cursor_marker = None
        self._data_cursor_pos = None

    def _update_data_cursor(self):
        if not self._data_cursor_enabled or not self._active_cursor_group:
            return
        pair = self._series_groups.get(self._active_cursor_group, {})
        mag_series = pair.get("magnitude")
        phase_series = pair.get("phase")
        if mag_series is None or phase_series is None or self._data_cursor_line is None:
            self._cursor_dialog.hide()
            return
        x_position = float(self._data_cursor_line.value())
        self._data_cursor_pos = x_position
        mag_value = self._sample_raw_series(mag_series, x_position)
        phase_value = self._sample_raw_series(phase_series, x_position)
        if mag_value is None or phase_value is None:
            self._cursor_dialog.hide()
            return
        if self._data_cursor_crosshair is not None:
            self._data_cursor_crosshair.setValue(mag_value)
        if self._data_cursor_marker is not None:
            self._data_cursor_marker.setData([x_position], [mag_value])
        freq_hz = self._to_display_x(x_position)
        if freq_hz is None:
            return
        group_delay = self._sample_group_delay(phase_series, freq_hz)
        self._cursor_dialog.update_values(
            series_name=self._active_cursor_group,
            frequency_hz=freq_hz,
            magnitude_db=mag_value,
            phase_deg=phase_value,
            group_delay_seconds=group_delay,
        )
        self._cursor_dialog.show()

    def _sample_group_delay(self, phase_series: ChartSeries, frequency_hz: float) -> Optional[float]:
        x_data = np.asarray(phase_series.x_data, dtype=float)
        phase_deg = np.asarray(phase_series.y_data, dtype=float)
        if len(x_data) < 2 or len(phase_deg) < 2:
            return None
        if not np.all(np.isfinite(x_data)) or not np.all(np.isfinite(phase_deg)):
            return None
        order = np.argsort(x_data)
        sorted_x = x_data[order]
        sorted_phase = phase_deg[order]
        unique_x, unique_indices = np.unique(sorted_x, return_index=True)
        unique_phase = sorted_phase[unique_indices]
        if len(unique_x) < 2:
            return None
        unwrapped_rad = np.unwrap(np.radians(unique_phase))
        omega = 2.0 * np.pi * unique_x
        derivative = np.gradient(unwrapped_rad, omega)
        return float(-np.interp(frequency_hz, unique_x, derivative))

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

    def _on_data_cursor_moved(self):
        self._update_data_cursor()

    def _on_signal_item_changed(self, item: QTreeWidgetItem, column: int):
        if self._updating_tree or self._spec is None:
            return
        if item.checkState(0) != Qt.CheckState.Checked and item.text(0) == self._active_cursor_group:
            self._active_cursor_group = ""
        self._rebuild_plot()

    def _on_signal_selection_changed(self):
        current_item = self._signal_tree.currentItem()
        if current_item is None:
            return
        self._active_cursor_group = current_item.text(0)
        if self._data_cursor_enabled:
            self._ensure_active_cursor_group()
            self._ensure_data_cursor()
            self._update_data_cursor()

    def _on_clear_all_series(self):
        self._updating_tree = True
        for item in self._series_items.values():
            item.setCheckState(0, Qt.CheckState.Unchecked)
        self._updating_tree = False
        self._active_cursor_group = ""
        self._rebuild_plot()

    def _on_rect_selected(self, requested_x_range: Tuple[float, float], requested_y_range: Tuple[float, float]):
        if self._x_domain is None or self._mag_domain is None or self._phase_domain is None:
            return
        clamped_x_range = clamp_range(requested_x_range, self._x_domain, positive_only=self._is_log_x())
        clamped_mag_range = clamp_range(requested_y_range, self._mag_domain, positive_only=False)
        if clamped_x_range is None or clamped_mag_range is None or self._mag_view_range is None or self._phase_view_range is None:
            return
        current_mag_min, current_mag_max = self._mag_view_range
        current_phase_min, current_phase_max = self._phase_view_range
        current_mag_span = max(current_mag_max - current_mag_min, 1e-30)
        current_phase_span = current_phase_max - current_phase_min
        norm_start = (requested_y_range[0] - current_mag_min) / current_mag_span
        norm_end = (requested_y_range[1] - current_mag_min) / current_mag_span
        raw_phase_range = (
            current_phase_min + norm_start * current_phase_span,
            current_phase_min + norm_end * current_phase_span,
        )
        clamped_phase_range = clamp_range(raw_phase_range, self._phase_domain, positive_only=False)
        if clamped_phase_range is None:
            return
        self._apply_viewport(clamped_x_range, clamped_mag_range, clamped_phase_range)
        if self._measurement_enabled:
            self._update_measurement()



def _format_frequency_value(value: float) -> str:
    return _format_engineering(value, "Hz")



def _format_duration_value(value: float) -> str:
    absolute = abs(value)
    if absolute >= 1.0:
        return f"{value:.6g}s"
    if absolute >= 1e-3:
        return f"{value * 1e3:.6g}ms"
    if absolute >= 1e-6:
        return f"{value * 1e6:.6g}us"
    if absolute >= 1e-9:
        return f"{value * 1e9:.6g}ns"
    return f"{value:.6g}s"



def _format_engineering(value: float, unit: str) -> str:
    if not np.isfinite(value):
        return "--"
    absolute = abs(value)
    if absolute == 0:
        return f"0{unit}"
    prefixes = [
        (1e9, "G"),
        (1e6, "M"),
        (1e3, "K"),
        (1.0, ""),
        (1e-3, "m"),
        (1e-6, "u"),
        (1e-9, "n"),
    ]
    for scale, prefix in prefixes:
        if absolute >= scale:
            return f"{value / scale:.6g}{prefix}{unit}"
    return f"{value:.6g}{unit}"


__all__ = ["BodeOverlayChartPage", "BodeCursorDialog"]
