import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QTabBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from domain.simulation.data.simulation_artifact_exporter import simulation_artifact_exporter
from domain.simulation.models.chart_type import ChartType
from domain.simulation.models.simulation_result import SimulationResult
from presentation.panels.simulation.bode_overlay_chart_page import BodeOverlayChartPage
from presentation.panels.simulation.chart_data_cursor import DataCursorSelectionDialog
from presentation.panels.simulation.chart_page_widget import ChartPage
from presentation.panels.simulation.chart_view_types import ChartSeries, ChartSpec
from presentation.panels.simulation.ltspice_plot_interaction import finite_range
from resources.theme import (
    BORDER_RADIUS_NORMAL,
    COLOR_ACCENT,
    COLOR_ACCENT_LIGHT,
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    FONT_SIZE_SMALL,
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
SUPPORTED_CHART_TYPES = (
    ChartType.WAVEFORM_TIME,
    ChartType.BODE_OVERLAY,
    ChartType.DC_SWEEP,
    ChartType.NOISE_SPECTRUM,
)


class ChartViewer(QWidget):
    tab_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._result: Optional[SimulationResult] = None
        self._chart_specs: List[ChartSpec] = []
        self._pages: List[QWidget] = []

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

    def _setup_toolbar(self):
        self._action_fit = QAction("Fit", self)
        self._action_fit.triggered.connect(self._on_fit_to_view)
        self._toolbar.addAction(self._action_fit)

        self._toolbar.addSeparator()

        self._action_measure = QAction("Measure", self)
        self._action_measure.setCheckable(True)
        self._action_measure.triggered.connect(self._on_toggle_measurement)
        self._toolbar.addAction(self._action_measure)

        self._action_cursor = QAction("Cursor", self)
        self._action_cursor.setCheckable(True)
        self._action_cursor.setEnabled(False)
        self._action_cursor.triggered.connect(self._on_toggle_cursor)
        self._toolbar.addAction(self._action_cursor)

    def _apply_style(self):
        self.setStyleSheet(f"""
            ChartViewer {{
                background-color: {COLOR_BG_SECONDARY};
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
            #emptyLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
        """)

    def load_result(self, result: SimulationResult):
        self._result = result
        self._action_measure.setChecked(False)
        self._action_cursor.setChecked(False)
        self._action_cursor.setEnabled(False)
        self._chart_specs = self._build_chart_specs(result)
        self._rebuild_pages()

    def clear(self):
        self._result = None
        self._chart_specs = []
        self._action_measure.setChecked(False)
        self._action_cursor.setChecked(False)
        self._action_cursor.setEnabled(False)
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
        self._action_cursor.setText(self._tr("Cursor"))
        self._empty_label.setText(self._tr("No interactive chart available for the current result."))
        for page in self._pages:
            page.retranslate_ui()

    def export_bundle(self, output_dir: str) -> List[str]:
        if self._result is None:
            return []

        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        exported_files: List[str] = []
        chart_entries: List[Dict[str, Any]] = []
        for index, page in enumerate(self._pages, start=1):
            if not page.has_chart():
                continue

            spec = self._chart_specs[index - 1]
            chart_payload = page.build_export_payload()
            if chart_payload is None:
                continue

            base_name = f"{index:02d}_{spec.chart_type.value}"
            image_path = target_dir / f"{base_name}.png"
            csv_path = target_dir / f"{base_name}.csv"
            json_path = target_dir / f"{base_name}.json"
            file_map: Dict[str, str] = {}

            if page.export_image(str(image_path)):
                exported_files.append(str(image_path))
                file_map["image"] = image_path.name
            if page.export_chart_data(str(csv_path), "csv"):
                exported_files.append(str(csv_path))
                file_map["csv"] = csv_path.name

            file_map["json"] = json_path.name
            wrapped_payload = simulation_artifact_exporter.build_artifact_payload(
                self._result,
                "chart",
                summary={
                    "chart_index": index,
                    "chart_type": spec.chart_type.value,
                    "title": spec.title,
                    "series_count": len(chart_payload["series"]),
                    "row_count": len(chart_payload["rows"]),
                },
                files=file_map,
                data=chart_payload,
                extra_metadata={
                    "chart_index": index,
                },
            )
            json_path.write_text(json.dumps(wrapped_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            exported_files.append(str(json_path))

            chart_entries.append({
                "chart_index": index,
                "chart_type": spec.chart_type.value,
                "title": spec.title,
                "series_count": len(chart_payload["series"]),
                "row_count": len(chart_payload["rows"]),
                "files": file_map,
            })

        manifest_path = target_dir / "charts.json"
        manifest_payload = simulation_artifact_exporter.build_artifact_payload(
            self._result,
            "charts",
            summary={
                "chart_count": len(chart_entries),
            },
            files={
                "items": [entry["files"] for entry in chart_entries],
            },
            data={
                "charts": chart_entries,
            },
        )
        manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        exported_files.append(str(manifest_path))

        return exported_files

    def _rebuild_pages(self):
        while self._tab_bar.count() > 0:
            self._tab_bar.removeTab(0)
        while self._stack.count() > 0:
            widget = self._stack.widget(0)
            self._stack.removeWidget(widget)
            widget.deleteLater()
        self._pages = []

        for spec in self._chart_specs:
            page = self._create_page(spec)
            page.set_chart(spec)
            page.retranslate_ui()
            self._pages.append(page)
            self._stack.addWidget(page)
            self._tab_bar.addTab(ChartType.get_display_name(spec.chart_type))

        if self._pages:
            self._tab_bar.setCurrentIndex(0)
            self._stack.setCurrentIndex(0)
            self._update_toolbar_state()
            self._hide_empty_state()
        else:
            self._action_cursor.setChecked(False)
            self._action_cursor.setEnabled(False)
            self._show_empty_state()

    def _create_page(self, spec: ChartSpec) -> QWidget:
        if spec.chart_type == ChartType.BODE_OVERLAY:
            return BodeOverlayChartPage()
        return ChartPage()

    def _current_page(self) -> Optional[QWidget]:
        index = self._tab_bar.currentIndex()
        if index < 0 or index >= len(self._pages):
            return None
        return self._pages[index]

    def _build_chart_specs(
        self,
        result: SimulationResult,
    ) -> List[ChartSpec]:
        if result is None or not result.success or result.data is None:
            return []

        resolved_chart_types = self._get_chart_types_for_result(result)
        if not resolved_chart_types:
            return []

        specs: List[ChartSpec] = []
        analysis = (result.analysis_type or "").lower()
        for chart_type in resolved_chart_types:
            spec = self._build_chart_spec(result, analysis, chart_type)
            if spec is not None:
                spec.series = self._deduplicate_series(spec.series)
            if spec is not None and spec.series:
                specs.append(spec)
        return specs

    def _get_chart_types_for_result(self, result: SimulationResult) -> List[ChartType]:
        analysis = (result.analysis_type or "").lower()
        if analysis == "tran":
            return [ChartType.WAVEFORM_TIME]
        if analysis == "ac":
            return [ChartType.BODE_OVERLAY]
        if analysis == "dc":
            return [ChartType.DC_SWEEP]
        if analysis == "noise":
            return [ChartType.NOISE_SPECTRUM]
        return []

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
            series = self._build_real_signal_series(result, x_data)
            return ChartSpec(chart_type, "Transient Waveforms", resolved_x_label, "Value", series, log_x=resolved_log_x, x_domain=resolved_x_domain)

        if chart_type == ChartType.BODE_OVERLAY and analysis == "ac":
            x_data = resolved_x_data
            if x_data is None:
                return None
            series = self._build_bode_overlay_series(result, x_data)
            return ChartSpec(chart_type, "Bode Overlay", resolved_x_label, "Magnitude (dB)", series, log_x=resolved_log_x, x_domain=resolved_x_domain, secondary_y_label="Phase (°)")

        if chart_type == ChartType.DC_SWEEP and analysis == "dc":
            x_data = resolved_x_data
            if x_data is None:
                return None
            series = self._build_real_signal_series(result, x_data)
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
    ) -> List[ChartSeries]:
        data = result.data
        if data is None:
            return []
        series: List[ChartSeries] = []
        for index, signal_name in enumerate(self._get_base_signal_names(result)):
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

    def _build_bode_overlay_series(
        self,
        result: SimulationResult,
        x_data: np.ndarray,
    ) -> List[ChartSeries]:
        data = result.data
        if data is None:
            return []
        series: List[ChartSeries] = []
        color_index = 0
        for signal_name in self._get_base_signal_names(result):
            raw_signal = data.get_signal(signal_name)
            if raw_signal is None or not np.iscomplexobj(raw_signal):
                continue

            magnitude_data = 20 * np.log10(np.maximum(np.abs(raw_signal), 1e-30))
            phase_data = np.degrees(np.angle(raw_signal))

            if len(magnitude_data) != len(x_data) or len(phase_data) != len(x_data):
                continue
            color = SERIES_COLORS[color_index % len(SERIES_COLORS)]
            series.append(
                ChartSeries(
                    name=f"{signal_name} | Mag",
                    x_data=np.asarray(x_data, dtype=float),
                    y_data=np.asarray(magnitude_data, dtype=float),
                    color=color,
                    axis_key="left",
                    line_style="solid",
                    group_key=signal_name,
                    component="magnitude",
                )
            )
            series.append(
                ChartSeries(
                    name=f"{signal_name} | Phase",
                    x_data=np.asarray(x_data, dtype=float),
                    y_data=np.asarray(phase_data, dtype=float),
                    color=color,
                    axis_key="right",
                    line_style="dash",
                    group_key=signal_name,
                    component="phase",
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
        for signal_name in self._get_base_signal_names(result):
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

    def _get_base_signal_names(self, result: SimulationResult) -> List[str]:
        data = result.data
        if data is None:
            return []
        signal_types = getattr(data, "signal_types", {})
        signal_names = data.get_signal_names()
        return sorted(signal_names, key=lambda name: self._signal_sort_key(name, signal_types))

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
        self._action_cursor.setChecked(False)
        for page in self._pages:
            page.set_measurement_enabled(False)
            page.set_data_cursor_enabled(False)
        self._update_toolbar_state()
        self.tab_changed.emit(self._chart_specs[index].chart_type.value)

    def _on_fit_to_view(self):
        page = self._current_page()
        if page is not None:
            page.fit_to_view()

    def _on_toggle_measurement(self, checked: bool):
        page = self._current_page()
        if page is not None:
            page.set_measurement_enabled(checked)

    def _on_toggle_cursor(self, checked: bool):
        page = self._current_page()
        if page is None:
            self._action_cursor.setChecked(False)
            return
        if not checked:
            page.set_data_cursor_enabled(False)
            return

        targets = page.list_data_cursor_targets()
        target_id = DataCursorSelectionDialog.select_target(
            targets,
            current_target_id=page.current_data_cursor_target_id(),
            parent=self,
        )
        if not target_id or not page.select_data_cursor_target(target_id):
            self._action_cursor.setChecked(False)
            page.set_data_cursor_enabled(False)
            return
        page.set_data_cursor_enabled(True)

    def _update_toolbar_state(self):
        page = self._current_page()
        supports_cursor = bool(page is not None and page.supports_data_cursor() and page.list_data_cursor_targets())
        self._action_cursor.setEnabled(supports_cursor)
        if not supports_cursor:
            self._action_cursor.setChecked(False)

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
