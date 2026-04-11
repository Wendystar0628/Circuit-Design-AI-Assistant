import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from domain.simulation.data.simulation_artifact_exporter import simulation_artifact_exporter
from domain.simulation.models.chart_type import ChartType
from domain.simulation.models.simulation_result import SimulationResult
from presentation.panels.simulation.bode_overlay_chart_page import BodeOverlayChartPage
from presentation.panels.simulation.chart_export_utils import write_chart_csv
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
class ChartViewer(QWidget):
    add_to_conversation_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._result: Optional[SimulationResult] = None
        self._chart_spec: Optional[ChartSpec] = None
        self._chart_page: Optional[QWidget] = None

        self._setup_ui()
        self._apply_style()
        self.retranslate_ui()

    def _setup_ui(self):
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._page_host = QWidget()
        self._page_host_layout = QVBoxLayout(self._page_host)
        self._page_host_layout.setContentsMargins(0, 0, 0, 0)
        self._page_host_layout.setSpacing(0)
        self._empty_label = QLabel()
        self._empty_label.setObjectName("emptyLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._page_host, 1)
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

        self._toolbar.addSeparator()

        self._action_add_to_conversation = QAction("Add to Conversation", self)
        self._action_add_to_conversation.setEnabled(False)
        self._action_add_to_conversation.triggered.connect(self.add_to_conversation_clicked.emit)
        self._toolbar.addAction(self._action_add_to_conversation)

    def _apply_style(self):
        self.setStyleSheet(f"""
            ChartViewer {{
                background-color: {COLOR_BG_SECONDARY};
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
        self._chart_spec = self._resolve_chart_spec(result)
        self._rebuild_page()

    def clear(self):
        self._result = None
        self._chart_spec = None
        self._action_measure.setChecked(False)
        self._action_cursor.setChecked(False)
        self._action_cursor.setEnabled(False)
        self._action_add_to_conversation.setEnabled(False)
        self._clear_chart_page()
        self._show_empty_state()

    def retranslate_ui(self):
        self._action_fit.setText(self._tr("Fit"))
        self._action_measure.setText(self._tr("Measure"))
        self._action_cursor.setText(self._tr("Cursor"))
        self._action_add_to_conversation.setText(self._tr("Add to Conversation"))
        self._empty_label.setText(self._tr("No interactive chart available for the current result."))
        if self._chart_page is not None:
            self._chart_page.retranslate_ui()

    def get_web_snapshot(self) -> Dict[str, Any]:
        page = self._chart_page
        page_snapshot = page.get_web_snapshot() if page is not None else {}
        return {
            "has_chart": bool(page is not None and page.has_chart()),
            "chart_count": 1 if self._chart_spec is not None else 0,
            "can_export": bool(page is not None and page.has_chart()),
            "can_add_to_conversation": bool(self._action_add_to_conversation.isEnabled()),
            **page_snapshot,
        }

    def export_current_image(self, path: str) -> bool:
        page = self._chart_page
        if page is None or not page.has_chart():
            return False
        return bool(page.export_image(path))

    def export_bundle(self, output_dir: str) -> List[str]:
        if self._result is None:
            return []

        page = self._chart_page
        spec = self._chart_spec
        if page is None or spec is None or not page.has_chart():
            return []

        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        exported_files: List[str] = []
        chart_entries: List[Dict[str, Any]] = []
        chart_payload = page.build_export_payload()
        if chart_payload is None:
            return []

        chart_index = 1
        base_name = f"{chart_index:02d}_{spec.chart_type.value}"
        image_path = target_dir / f"{base_name}.png"
        csv_path = target_dir / f"{base_name}.csv"
        json_path = target_dir / f"{base_name}.json"
        file_map: Dict[str, str] = {}

        if page.export_image(str(image_path)):
            exported_files.append(str(image_path))
            file_map["image"] = image_path.name
        if write_chart_csv(str(csv_path), chart_payload):
            exported_files.append(str(csv_path))
            file_map["csv"] = csv_path.name

        file_map["json"] = json_path.name
        wrapped_payload = simulation_artifact_exporter.build_artifact_payload(
            self._result,
            "chart",
            summary={
                "chart_index": chart_index,
                "chart_type": spec.chart_type.value,
                "title": spec.title,
                "series_count": len(chart_payload["series"]),
                "row_count": len(chart_payload["rows"]),
            },
            files=file_map,
            data=chart_payload,
            extra_metadata={
                "chart_index": chart_index,
            },
        )
        json_path.write_text(json.dumps(wrapped_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        exported_files.append(str(json_path))

        chart_entries.append({
            "chart_index": chart_index,
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

    def _clear_chart_page(self):
        while self._page_host_layout.count() > 0:
            item = self._page_host_layout.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            widget.deleteLater()
        self._chart_page = None

    def _rebuild_page(self):
        self._clear_chart_page()

        spec = self._chart_spec
        if spec is None:
            self._action_cursor.setChecked(False)
            self._action_cursor.setEnabled(False)
            self._action_add_to_conversation.setEnabled(False)
            self._show_empty_state()
            return

        page = self._create_page(spec)
        page.set_chart(spec)
        page.retranslate_ui()
        self._chart_page = page
        self._page_host_layout.addWidget(page)
        self._reset_page_interaction_state()
        self._update_toolbar_state()
        self._hide_empty_state()

    def _create_page(self, spec: ChartSpec) -> QWidget:
        if spec.chart_type == ChartType.BODE_OVERLAY:
            return BodeOverlayChartPage()
        return ChartPage()

    def _resolve_chart_spec(
        self,
        result: SimulationResult,
    ) -> Optional[ChartSpec]:
        if result is None or not result.success or result.data is None:
            return None

        chart_type = self._get_chart_type_for_result(result)
        if chart_type is None:
            return None

        analysis = (result.analysis_type or "").lower()
        spec = self._build_chart_spec(result, analysis, chart_type)
        if spec is None:
            return None
        spec.series = self._deduplicate_series(spec.series)
        if not spec.series:
            return None
        return spec

    def _get_chart_type_for_result(self, result: SimulationResult) -> Optional[ChartType]:
        analysis = (result.analysis_type or "").lower()
        if analysis == "tran":
            return ChartType.WAVEFORM_TIME
        if analysis == "ac":
            return ChartType.BODE_OVERLAY
        if analysis == "dc":
            return ChartType.DC_SWEEP
        if analysis == "noise":
            return ChartType.NOISE_SPECTRUM
        return None

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

    def _reset_page_interaction_state(self):
        self._action_measure.setChecked(False)
        self._action_cursor.setChecked(False)
        page = self._chart_page
        if page is not None:
            page.set_measurement_enabled(False)
            page.set_data_cursor_enabled(False)
        self._update_toolbar_state()

    def _on_fit_to_view(self):
        page = self._chart_page
        if page is not None:
            page.fit_to_view()

    def _on_toggle_measurement(self, checked: bool):
        page = self._chart_page
        if page is not None:
            page.set_measurement_enabled(checked)

    def _on_toggle_cursor(self, checked: bool):
        page = self._chart_page
        if page is None:
            self._action_cursor.setChecked(False)
            return
        page.set_data_cursor_enabled(checked)

    def _update_toolbar_state(self):
        page = self._chart_page
        supports_cursor = bool(page is not None and page.supports_data_cursor())
        has_chart = bool(page is not None and page.has_chart())
        self._action_cursor.setEnabled(supports_cursor)
        self._action_add_to_conversation.setEnabled(has_chart)
        if not supports_cursor:
            self._action_cursor.setChecked(False)

    def _show_empty_state(self):
        self._page_host.hide()
        self._empty_label.show()

    def _hide_empty_state(self):
        self._empty_label.hide()
        self._page_host.show()

    def _tr(self, text: str) -> str:
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(f"chart_viewer.{text}", default=text)
        except ImportError:
            return text


__all__ = ["ChartViewer", "ChartSpec", "ChartSeries"]
