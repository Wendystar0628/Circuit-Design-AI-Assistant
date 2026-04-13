from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from presentation.panels.simulation.chart_axis_planner import ChartAxisPlan, apply_axis_plan, build_chart_axis_plan, resolve_axis_key, resolve_axis_label
from presentation.panels.simulation.chart_measurement_point import MeasurementPointSample, MeasurementPointValue, clamp_to_bounds, midpoint_of_bounds, serialize_measurement_point_sample
from presentation.panels.simulation.chart_export_utils import build_chart_export_payload, serialize_chart_series_for_web
from presentation.panels.simulation.chart_view_types import ChartSeries, ChartSpec
from presentation.panels.simulation.qt_surface_export import export_widget_image
from presentation.panels.simulation.ltspice_plot_interaction import (
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
    SPACING_SMALL,
)


class ChartPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._spec: Optional[ChartSpec] = None
        self._measurement_enabled = False
        self._measurement_point_enabled = False
        self._measurement_point_target_id = ""
        self._measurement_point_x: Optional[float] = None
        self._cursor_a_pos: Optional[float] = None
        self._cursor_b_pos: Optional[float] = None
        self._plot_items: Dict[str, pg.PlotDataItem] = {}
        self._rendered_axis_keys: Dict[str, str] = {}
        self._series_items: Dict[str, QTreeWidgetItem] = {}
        self._visible_series_names: Set[str] = set()
        self._updating_tree = False
        self._x_domain: Optional[Tuple[float, float]] = None
        self._y_domain: Optional[Tuple[float, float]] = None
        self._right_y_domain: Optional[Tuple[float, float]] = None
        self._view_x_range: Optional[Tuple[float, float]] = None
        self._view_y_range: Optional[Tuple[float, float]] = None
        self._view_right_y_range: Optional[Tuple[float, float]] = None
        self._viewport_active = False
        self._default_axis_plan: ChartAxisPlan = build_chart_axis_plan([])
        self._active_axis_plan: ChartAxisPlan = self._default_axis_plan
        self._right_vb: Optional[pg.ViewBox] = None

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

        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setBackground(COLOR_BG_PRIMARY)
        self._configure_plot_surface()
        right_layout.addWidget(self._plot_widget, 1)

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
        """)

    def _configure_plot_surface(self):
        plot_item = self._plot_widget.getPlotItem()
        plot_item.showGrid(x=True, y=True, alpha=0.25)
        plot_item.disableAutoRange()
        plot_item.vb.setMenuEnabled(False)
        plot_item.vb.setMouseEnabled(x=False, y=False)
        plot_item.showAxis("right")
        plot_item.getAxis("right").setWidth(72)
        if self._right_vb is not None:
            try:
                plot_item.scene().removeItem(self._right_vb)
            except Exception:
                pass
        self._right_vb = pg.ViewBox()
        plot_item.scene().addItem(self._right_vb)
        plot_item.getAxis("right").linkToView(self._right_vb)
        self._right_vb.setXLink(plot_item)
        self._right_vb.setMenuEnabled(False)
        self._right_vb.setMouseEnabled(x=False, y=False)
        try:
            plot_item.vb.sigResized.disconnect(self._sync_right_viewbox)
        except Exception:
            pass
        plot_item.vb.sigResized.connect(self._sync_right_viewbox)
        self._legend = plot_item.addLegend()
        self._apply_axis_plan_visuals(self._default_axis_plan)
        self._sync_right_viewbox()

    def _sync_right_viewbox(self):
        if self._right_vb is None:
            return
        self._right_vb.setGeometry(self._plot_widget.getPlotItem().vb.sceneBoundingRect())

    def _apply_axis_plan_visuals(self, axis_plan: ChartAxisPlan):
        plot_item = self._plot_widget.getPlotItem()
        plot_item.setLabel("left", axis_plan.left_axis.label)
        if axis_plan.right_axis is not None:
            plot_item.showAxis("right")
            plot_item.getAxis("right").setWidth(72)
            plot_item.setLabel("right", axis_plan.right_axis.label)
        else:
            plot_item.setLabel("right", "")
            plot_item.hideAxis("right")

    def clear(self):
        self._plot_widget.clear()
        self._configure_plot_surface()
        self._measurement_enabled = False
        self._measurement_point_enabled = False
        self._measurement_point_target_id = ""
        self._measurement_point_x = None
        self._clear_measurement_positions()
        self._spec = None
        self._plot_items = {}
        self._rendered_axis_keys = {}
        self._series_items = {}
        self._visible_series_names = set()
        self._x_domain = None
        self._y_domain = None
        self._right_y_domain = None
        self._view_x_range = None
        self._view_y_range = None
        self._view_right_y_range = None
        self._viewport_active = False
        self._default_axis_plan = build_chart_axis_plan([])
        self._active_axis_plan = self._default_axis_plan
        self._signal_tree.clear()

    def set_chart(self, spec: ChartSpec):
        self.clear()
        self._spec = spec
        plot_item = self._plot_widget.getPlotItem()
        plot_item.setTitle(spec.title)
        plot_item.setLabel("bottom", spec.x_label)
        plot_item.setLogMode(x=spec.log_x, y=False)

        valid_series: List[ChartSeries] = []
        self._updating_tree = True
        self._signal_tree.clear()
        self._series_items = {}
        self._visible_series_names = set()
        for series in spec.series:
            x_data = np.asarray(series.x_data, dtype=float)
            y_data = np.asarray(series.y_data, dtype=float)
            if len(x_data) == 0 or len(y_data) == 0 or len(x_data) != len(y_data):
                continue
            valid_series.append(series)
            item = QTreeWidgetItem(self._signal_tree, [series.name])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            is_default_visible = len(valid_series) == 1
            if is_default_visible:
                self._visible_series_names.add(series.name)
            item.setCheckState(0, Qt.CheckState.Checked if is_default_visible else Qt.CheckState.Unchecked)
            self._series_items[series.name] = item
        self._updating_tree = False

        self._spec.series = valid_series
        self._default_axis_plan = build_chart_axis_plan(valid_series)
        self._active_axis_plan = self._default_axis_plan
        self._apply_axis_plan_visuals(self._default_axis_plan)
        if valid_series:
            self._signal_tree.setCurrentItem(self._series_items[valid_series[0].name])
        self._rebuild_plot()

    def has_chart(self) -> bool:
        return bool(self._plot_items)

    def fit_to_view(self):
        self.reset_viewport()

    def reset_viewport(self) -> None:
        self._viewport_active = False
        self._view_x_range = None
        self._view_y_range = None
        self._view_right_y_range = None
        self._apply_full_viewport()
        if self.is_measurement_enabled():
            self._ensure_measurement_positions()

    def set_viewport(self, viewport: Dict[str, Any]) -> bool:
        if self._spec is None or self._x_domain is None or self._y_domain is None:
            return False
        x_min = self._to_axis_x(float(viewport.get("x_min")))
        x_max = self._to_axis_x(float(viewport.get("x_max")))
        y_min = self._to_axis_y(float(viewport.get("left_y_min")), axis_key="left")
        y_max = self._to_axis_y(float(viewport.get("left_y_max")), axis_key="left")
        if None in {x_min, x_max, y_min, y_max}:
            return False
        x_range = clamp_range((x_min, x_max), self._x_domain, positive_only=self._spec.log_x)
        y_range = clamp_range((y_min, y_max), self._y_domain, positive_only=self._axis_log_enabled("left"))
        if x_range is None or y_range is None:
            return False
        right_y_range = None
        if self._right_y_domain is not None and viewport.get("right_y_min") is not None and viewport.get("right_y_max") is not None:
            right_y_min = self._to_axis_y(float(viewport.get("right_y_min")), axis_key="right")
            right_y_max = self._to_axis_y(float(viewport.get("right_y_max")), axis_key="right")
            if None in {right_y_min, right_y_max}:
                return False
            right_y_range = clamp_range(
                (right_y_min, right_y_max),
                self._right_y_domain,
                positive_only=self._axis_log_enabled("right"),
            )
            if right_y_range is None:
                return False
        self._viewport_active = True
        self._apply_domain_limits()
        self._apply_viewport(x_range, y_range, right_y_range)
        if self.is_measurement_enabled():
            self._ensure_measurement_positions()
        return True

    def supports_measurement_point(self) -> bool:
        return bool(self._spec is not None and self._spec.series)

    def is_measurement_point_enabled(self) -> bool:
        return bool(self._measurement_point_enabled)

    def measurement_point_target(self) -> str:
        return str(self._measurement_point_target_id or "")

    def set_measurement_point_target(self, target_id: str) -> bool:
        normalized_target_id = str(target_id or "")
        if not normalized_target_id:
            self._measurement_point_target_id = ""
            self._measurement_point_x = None
            return True
        return self._select_measurement_point_target(normalized_target_id)

    def set_series_visible(self, series_name: str, visible: bool) -> bool:
        if self._spec is None or not series_name or series_name not in self._series_items:
            return False
        next_visible_series_names = set(self._visible_series_names)
        if visible:
            next_visible_series_names.add(series_name)
        else:
            next_visible_series_names.discard(series_name)
        if next_visible_series_names == self._visible_series_names:
            return True
        self._visible_series_names = next_visible_series_names
        self._sync_signal_tree_checks()
        if not visible and series_name == self._measurement_point_target_id:
            self._measurement_point_target_id = ""
            self._measurement_point_x = None
        self._rebuild_plot()
        return True

    def clear_all_series(self):
        self._on_clear_all_series()

    def _select_measurement_point_target(self, target_id: str) -> bool:
        if not target_id or target_id not in self._series_items or target_id not in self._visible_series_names:
            return False
        item = self._series_items[target_id]
        self._signal_tree.setCurrentItem(item)
        self._measurement_point_target_id = target_id
        return True

    def set_measurement_point_enabled(self, enabled: bool):
        self._measurement_point_enabled = bool(enabled)
        if not self._measurement_point_enabled:
            self._measurement_point_x = None

    def set_measurement_point_position(self, x_value: float) -> bool:
        x_view_range = self._current_x_view_range()
        if not self._measurement_point_enabled or not self._measurement_point_target_id or x_view_range is None:
            return False
        axis_x = self._to_axis_x(x_value)
        if axis_x is None:
            return False
        self._measurement_point_x = clamp_to_bounds(axis_x, x_view_range)
        return self._measurement_point_x is not None

    def set_measurement_enabled(self, enabled: bool):
        self._measurement_enabled = bool(enabled)
        if self._measurement_enabled:
            self._ensure_measurement_positions()
            return
        self._clear_measurement_positions()

    def is_measurement_enabled(self) -> bool:
        return bool(self._measurement_enabled)

    def set_measurement_cursor(self, cursor_id: str, x_value: float) -> bool:
        x_view_range = self._current_x_view_range()
        if not self._measurement_enabled or x_view_range is None:
            return False
        axis_x = self._to_axis_x(x_value)
        if axis_x is None:
            return False
        clamped_x = min(max(axis_x, x_view_range[0]), x_view_range[1])
        if cursor_id == "b":
            self._cursor_b_pos = clamped_x
        else:
            self._cursor_a_pos = clamped_x
        return True

    def export_image(self, path: str) -> bool:
        return export_widget_image(self, self._plot_widget, path)

    def build_export_payload(self) -> Optional[Dict[str, Any]]:
        if self._spec is None or not self._spec.series:
            return None
        return build_chart_export_payload(self._spec, self._spec.series)

    def get_web_snapshot(self) -> Dict[str, Any]:
        spec = self._spec
        visible_series = self._planned_visible_series()
        available_series = []
        if spec is not None:
            planned_series = apply_axis_plan(spec.series, self._active_axis_plan)
            available_series = [
                {
                    "name": series.name,
                    "color": series.color,
                    "axis_key": series.axis_key,
                    "line_style": series.line_style,
                    "group_key": series.group_key,
                    "component": series.component,
                    "visible": series.name in self._visible_series_names,
                    "point_count": int(len(series.y_data)),
                }
                for series in planned_series
            ]
        return {
            "title": str(spec.title or "") if spec is not None else "",
            "chart_type": str(spec.chart_type.value) if spec is not None else "",
            "x_label": str(spec.x_label or "") if spec is not None else "",
            "y_label": self._active_axis_plan.left_axis.label if spec is not None else "",
            "secondary_y_label": self._active_axis_plan.right_axis.label if spec is not None and self._active_axis_plan.right_axis is not None else "",
            "log_x": bool(spec.log_x) if spec is not None else False,
            "log_y": bool(self._active_axis_plan.left_axis.log_enabled) if spec is not None else False,
            "right_log_y": bool(self._active_axis_plan.right_axis.log_enabled) if spec is not None and self._active_axis_plan.right_axis is not None else False,
            "available_series": available_series,
            "visible_series": [serialize_chart_series_for_web(series) for series in visible_series],
            "visible_series_count": len(visible_series),
            "viewport": self._build_viewport_snapshot(),
            "measurement_point": self._build_measurement_point_snapshot(),
            "measurement_enabled": self.is_measurement_enabled(),
            "measurement": self._build_measurement_snapshot(),
        }

    def _build_viewport_snapshot(self) -> Dict[str, Any]:
        if not self._viewport_active or self._view_x_range is None or self._view_y_range is None:
            return {
                "active": False,
                "x_min": None,
                "x_max": None,
                "left_y_min": None,
                "left_y_max": None,
                "right_y_min": None,
                "right_y_max": None,
            }
        return {
            "active": True,
            "x_min": self._to_display_x(self._view_x_range[0]),
            "x_max": self._to_display_x(self._view_x_range[1]),
            "left_y_min": self._to_display_y(self._view_y_range[0], axis_key="left"),
            "left_y_max": self._to_display_y(self._view_y_range[1], axis_key="left"),
            "right_y_min": self._to_display_y(self._view_right_y_range[0], axis_key="right") if self._view_right_y_range is not None else None,
            "right_y_max": self._to_display_y(self._view_right_y_range[1], axis_key="right") if self._view_right_y_range is not None else None,
        }

    def _build_measurement_point_snapshot(self) -> Dict[str, Any]:
        if not self._measurement_point_enabled or not self._measurement_point_target_id or self._x_domain is None:
            return {
                "enabled": bool(self._measurement_point_enabled),
                "target_id": self.measurement_point_target(),
                "point_x": None,
                "title": "",
                "plot_series_name": "",
                "plot_axis_key": "left",
                "plot_y": None,
                "values": [],
            }
        next_axis_x = clamp_to_bounds(self._measurement_point_x, self._x_domain)
        if next_axis_x is None:
            next_axis_x = midpoint_of_bounds(self._x_domain)
        self._measurement_point_x = next_axis_x
        sample = self._sample_measurement_point_target(self._measurement_point_target_id, next_axis_x) if next_axis_x is not None else None
        serialized_sample = serialize_measurement_point_sample(sample) if sample is not None else {
            "title": "",
            "plot_series_name": "",
            "plot_axis_key": "left",
            "plot_y": None,
            "values": [],
        }
        return {
            "enabled": True,
            "target_id": self.measurement_point_target(),
            "point_x": self._to_display_x(next_axis_x),
            **serialized_sample,
        }

    def _build_measurement_snapshot(self) -> Dict[str, Any]:
        if not self._measurement_enabled or self._x_domain is None or not self._plot_items:
            return {
                "cursor_a_x": None,
                "cursor_b_x": None,
                "delta_x": None,
                "frequency": None,
                "values_a": {},
                "values_b": {},
            }
        values_a: Dict[str, float] = {}
        values_b: Dict[str, float] = {}
        if self._cursor_a_pos is not None:
            values_a = self._sample_series(self._cursor_a_pos)
        if self._cursor_b_pos is not None:
            values_b = self._sample_series(self._cursor_b_pos)
        cursor_a_x = self._to_display_x(self._cursor_a_pos)
        cursor_b_x = self._to_display_x(self._cursor_b_pos)
        delta_x = None
        frequency = None
        if cursor_a_x is not None and cursor_b_x is not None:
            delta_x = float(cursor_b_x - cursor_a_x)
            if self._should_show_frequency() and delta_x != 0:
                frequency = float(1.0 / abs(delta_x))
        return {
            "cursor_a_x": cursor_a_x,
            "cursor_b_x": cursor_b_x,
            "delta_x": delta_x,
            "frequency": frequency,
            "values_a": values_a,
            "values_b": values_b,
        }

    def _ensure_measurement_positions(self):
        x_view_range = self._current_x_view_range()
        if self._spec is None or not self._plot_items or x_view_range is None:
            return
        x_min, x_max = x_view_range
        center = (x_min + x_max) / 2
        offset = max((x_max - x_min) * 0.08, 1e-12)
        if self._cursor_a_pos is None:
            self._cursor_a_pos = center - offset
        self._cursor_a_pos = min(max(self._cursor_a_pos, x_view_range[0]), x_view_range[1])
        if self._cursor_b_pos is None:
            self._cursor_b_pos = center + offset
        self._cursor_b_pos = min(max(self._cursor_b_pos, x_view_range[0]), x_view_range[1])

    def _current_x_view_range(self) -> Optional[Tuple[float, float]]:
        return self._view_x_range or self._x_domain

    def _apply_stored_or_full_viewport(self):
        if self._x_domain is None or self._y_domain is None:
            return
        if not self._viewport_active or self._view_x_range is None or self._view_y_range is None or self._spec is None:
            self._apply_full_viewport()
            return
        clamped_x_range = clamp_range(self._view_x_range, self._x_domain, positive_only=self._spec.log_x)
        clamped_y_range = clamp_range(self._view_y_range, self._y_domain, positive_only=self._axis_log_enabled("left"))
        if clamped_x_range is None or clamped_y_range is None:
            self._viewport_active = False
            self._view_x_range = None
            self._view_y_range = None
            self._view_right_y_range = None
            self._apply_full_viewport()
            return
        self._apply_domain_limits()
        right_y_range = None
        if self._right_y_domain is not None:
            if self._view_right_y_range is not None:
                right_y_range = clamp_range(
                    self._view_right_y_range,
                    self._right_y_domain,
                    positive_only=self._axis_log_enabled("right"),
                )
            if right_y_range is None:
                right_y_range = self._right_y_domain
        self._apply_viewport(clamped_x_range, clamped_y_range, right_y_range)

    def _clear_measurement_positions(self):
        self._cursor_a_pos = None
        self._cursor_b_pos = None

    def _to_axis_x(self, x_value: float) -> Optional[float]:
        if not np.isfinite(x_value):
            return None
        if self._spec is not None and self._spec.log_x:
            if x_value <= 0:
                return None
            return float(np.log10(x_value))
        return float(x_value)

    def _to_axis_y(self, y_value: float, *, axis_key: str = "left") -> Optional[float]:
        if not np.isfinite(y_value):
            return None
        if self._axis_log_enabled(axis_key):
            if y_value <= 0:
                return None
            return float(np.log10(y_value))
        return float(y_value)

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

    def _to_display_y(self, y_position: Optional[float], *, axis_key: str = "left") -> Optional[float]:
        if y_position is None:
            return None
        if self._axis_log_enabled(axis_key):
            return float(10 ** y_position)
        return float(y_position)

    def _find_series_by_name(self, series_name: str) -> Optional[ChartSeries]:
        if self._spec is None:
            return None
        for series in self._spec.series:
            if series.name == series_name:
                return series
        return None

    def _sample_measurement_point_target(self, target_id: str, x_position: float) -> Optional[MeasurementPointSample]:
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
        axis_key = resolve_axis_key(series, self._active_axis_plan)
        return MeasurementPointSample(
            title=target_id,
            plot_series_name=series.name,
            plot_axis_key=axis_key,
            plot_y_value=y_value,
            values=[
                MeasurementPointValue(label=f"{self._spec.x_label}:", value_text=f"{x_display:.6g}"),
                MeasurementPointValue(label=f"{resolve_axis_label(series, self._active_axis_plan)}:", value_text=f"{y_value:.6g}"),
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
        return [series for series in self._spec.series if series.name in self._visible_series_names]

    def _planned_visible_series(self) -> List[ChartSeries]:
        return apply_axis_plan(self._visible_series(), self._active_axis_plan)

    def _build_active_axis_plan(self) -> ChartAxisPlan:
        if self._spec is None or not self._spec.series:
            return build_chart_axis_plan([])
        if not self._visible_series_names:
            return self._default_axis_plan
        return build_chart_axis_plan(self._spec.series, self._visible_series_names)

    def _axis_log_enabled(self, axis_key: str) -> bool:
        if axis_key == "right" and self._active_axis_plan.right_axis is not None:
            return bool(self._active_axis_plan.right_axis.log_enabled)
        return bool(self._active_axis_plan.left_axis.log_enabled)

    def _sync_signal_tree_checks(self) -> None:
        self._updating_tree = True
        for series_name, item in self._series_items.items():
            desired_state = Qt.CheckState.Checked if series_name in self._visible_series_names else Qt.CheckState.Unchecked
            item.setCheckState(0, desired_state)
        self._updating_tree = False

    def _rebuild_plot(self):
        plot_item = self._plot_widget.getPlotItem()
        for series_name, item in list(self._plot_items.items()):
            if self._rendered_axis_keys.get(series_name) == "right" and self._right_vb is not None:
                self._right_vb.removeItem(item)
            else:
                plot_item.removeItem(item)
        self._plot_items.clear()
        self._rendered_axis_keys.clear()

        try:
            self._legend.clear()
        except Exception:
            self._legend = plot_item.addLegend()

        self._active_axis_plan = self._build_active_axis_plan()
        self._apply_axis_plan_visuals(self._active_axis_plan)
        plot_item.setLogMode(x=self._spec.log_x if self._spec is not None else False, y=self._axis_log_enabled("left"))
        visible_series = self._planned_visible_series()
        for series in visible_series:
            pen = pg.mkPen(series.color, width=1.6, style=Qt.PenStyle.SolidLine)
            axis_key = resolve_axis_key(series, self._active_axis_plan)
            y_data = np.asarray(series.y_data, dtype=float)
            if axis_key == "right" and self._axis_log_enabled("right"):
                y_data = self._to_view_axis_data(y_data, log_enabled=True)
            item = pg.PlotDataItem(
                np.asarray(series.x_data, dtype=float),
                y_data,
                pen=pen,
            )
            if axis_key == "right" and self._right_vb is not None:
                self._right_vb.addItem(item)
            else:
                plot_item.addItem(item)
            self._plot_items[series.name] = item
            self._rendered_axis_keys[series.name] = axis_key
            self._legend.addItem(item, series.name)

        if not visible_series:
            self._x_domain = None
            self._y_domain = None
            self._right_y_domain = None
            self._viewport_active = False
            self._view_x_range = None
            self._view_y_range = None
            self._view_right_y_range = None
            return

        self._rebuild_domains()
        self._apply_stored_or_full_viewport()

        if self.is_measurement_enabled():
            self._ensure_measurement_positions()

    def _rebuild_domains(self):
        if self._spec is None:
            self._x_domain = None
            self._y_domain = None
            self._right_y_domain = None
            return

        x_ranges = []
        y_ranges = []
        right_y_ranges = []
        for series in self._planned_visible_series():
            axis_key = resolve_axis_key(series, self._active_axis_plan)
            x_range = finite_range(
                self._to_view_axis_data(series.x_data, log_enabled=self._spec.log_x),
                positive_only=self._spec.log_x,
            )
            y_range = finite_range(
                self._to_view_axis_data(series.y_data, log_enabled=self._axis_log_enabled(axis_key)),
                positive_only=self._axis_log_enabled(axis_key),
            )
            if x_range is not None:
                x_ranges.append(x_range)
            if y_range is not None:
                if axis_key == "right":
                    right_y_ranges.append(y_range)
                else:
                    y_ranges.append(y_range)

        self._x_domain = self._spec.x_domain or merge_ranges(x_ranges)
        self._y_domain = merge_ranges(y_ranges)
        self._right_y_domain = merge_ranges(right_y_ranges)

    def _apply_domain_limits(self):
        plot_item = self._plot_widget.getPlotItem()
        view_box = plot_item.vb
        if self._x_domain is not None:
            view_box.setLimits(xMin=self._x_domain[0], xMax=self._x_domain[1])
        if self._y_domain is not None:
            view_box.setLimits(yMin=self._y_domain[0], yMax=self._y_domain[1])
        if self._right_vb is not None and self._right_y_domain is not None:
            self._right_vb.setLimits(yMin=self._right_y_domain[0], yMax=self._right_y_domain[1])

    def _update_right_axis_ticks(self):
        axis = self._plot_widget.getPlotItem().getAxis("right")
        if self._active_axis_plan.right_axis is None:
            axis.setTicks([])
            return
        if not self._axis_log_enabled("right"):
            apply_dynamic_tick_spacing(axis, self._view_right_y_range or self._right_y_domain, log_enabled=False)
            return
        if self._right_y_domain is None:
            axis.setTicks([])
            return
        lower_exp = int(np.floor((self._view_right_y_range or self._right_y_domain)[0]))
        upper_exp = int(np.ceil((self._view_right_y_range or self._right_y_domain)[1]))
        ticks = []
        for exponent in range(lower_exp, upper_exp + 1):
            value = 10 ** exponent
            ticks.append((float(exponent), f"{value:.6g}"))
        axis.setTicks([ticks, []])

    def _apply_viewport(
        self,
        x_range: Optional[Tuple[float, float]],
        y_range: Optional[Tuple[float, float]],
        right_y_range: Optional[Tuple[float, float]] = None,
    ):
        if x_range is None or y_range is None:
            return
        plot_item = self._plot_widget.getPlotItem()
        self._view_x_range = x_range
        self._view_y_range = y_range
        self._view_right_y_range = right_y_range
        plot_item.setXRange(x_range[0], x_range[1], padding=0.0)
        plot_item.setYRange(y_range[0], y_range[1], padding=0.0)
        apply_dynamic_tick_spacing(plot_item.getAxis('bottom'), x_range, log_enabled=self._spec.log_x if self._spec is not None else False)
        apply_dynamic_tick_spacing(plot_item.getAxis('left'), y_range, log_enabled=self._axis_log_enabled("left"))
        if self._right_vb is not None and self._active_axis_plan.right_axis is not None:
            applied_right_y = right_y_range or self._right_y_domain or y_range
            self._right_vb.setYRange(applied_right_y[0], applied_right_y[1], padding=0.0)
        self._update_right_axis_ticks()

    def _apply_full_viewport(self):
        if self._x_domain is None or self._y_domain is None:
            return
        self._viewport_active = False
        self._view_x_range = None
        self._view_y_range = None
        self._view_right_y_range = None
        self._apply_domain_limits()
        self._apply_viewport(self._x_domain, self._y_domain, self._right_y_domain)

    def _on_signal_item_changed(self, item: QTreeWidgetItem, column: int):
        if self._updating_tree or self._spec is None or item is None or column != 0:
            return
        series_name = item.text(0)
        if not series_name or series_name not in self._series_items:
            return
        next_visible_series_names = set(self._visible_series_names)
        if item.checkState(0) == Qt.CheckState.Checked:
            next_visible_series_names.add(series_name)
        else:
            next_visible_series_names.discard(series_name)
        if next_visible_series_names == self._visible_series_names:
            return
        self._visible_series_names = next_visible_series_names
        if series_name == self._measurement_point_target_id and series_name not in self._visible_series_names:
            self._measurement_point_target_id = ""
            self._measurement_point_x = None
        self._rebuild_plot()

    def _on_clear_all_series(self):
        self._visible_series_names = set()
        self._sync_signal_tree_checks()
        self._measurement_point_target_id = ""
        self._measurement_point_x = None
        self._viewport_active = False
        self._view_x_range = None
        self._view_y_range = None
        self._view_right_y_range = None
        self._rebuild_plot()

    def _to_view_axis_data(self, values: np.ndarray, *, log_enabled: bool) -> np.ndarray:
        array = np.asarray(values, dtype=float)
        if not log_enabled:
            return array
        transformed = np.full(array.shape, np.nan, dtype=float)
        mask = np.isfinite(array) & (array > 0)
        transformed[mask] = np.log10(array[mask])
        return transformed


__all__ = ["ChartPage"]
