from pathlib import Path
from typing import Optional

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from domain.simulation.data.waveform_data_service import waveform_data_service
from domain.simulation.models.simulation_result import SimulationResult
from resources.theme import (
    BORDER_RADIUS_NORMAL,
    COLOR_BG_PRIMARY,
    COLOR_BG_TERTIARY,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    FONT_SIZE_SMALL,
    SPACING_NORMAL,
    SPACING_SMALL,
)


class OPResultDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._result: Optional[SimulationResult] = None

        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setModal(True)
        self.resize(620, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_SMALL)

        self._title_label = QLabel()
        self._title_label.setObjectName("opResultTitle")
        layout.addWidget(self._title_label)

        self._meta_label = QLabel()
        self._meta_label.setObjectName("opResultMeta")
        self._meta_label.setWordWrap(True)
        layout.addWidget(self._meta_label)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        layout.addWidget(self._tree, 1)

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self._buttons.rejected.connect(self.reject)
        self._buttons.accepted.connect(self.accept)
        layout.addWidget(self._buttons)

        self._apply_style()
        self.retranslate_ui()

    def load_result(self, result: Optional[SimulationResult]):
        self._result = result
        self._rebuild()

    def retranslate_ui(self):
        self.setWindowTitle(self._get_text("simulation.op_result.window_title", "OP Analysis Result"))
        self._buttons.button(QDialogButtonBox.StandardButton.Close).setText(
            self._get_text("btn_close", "关闭")
        )
        self._tree.setHeaderLabels([
            self._get_text("simulation.op_result.quantity", "量"),
            self._get_text("simulation.op_result.value", "值"),
        ])
        self._rebuild()

    def _rebuild(self):
        self._tree.clear()
        result = self._result
        if result is None or not result.success or result.data is None:
            self._title_label.setText(self._get_text("simulation.op_result.title", "工作点结果"))
            self._meta_label.setText(
                self._get_text("simulation.op_result.empty", "当前没有可显示的工作点结果。")
            )
            return

        file_name = Path(result.file_path).name if result.file_path else ""
        analysis_command = result.analysis_command or ".op"
        self._title_label.setText(self._get_text("simulation.op_result.title", "工作点结果"))
        self._meta_label.setText(f"{file_name}\n{analysis_command}".strip())

        classified = waveform_data_service.get_classified_signals(result)
        node_voltages = sorted(classified.get("voltage", []), key=self._node_voltage_sort_key)
        source_currents, device_currents = self._split_current_signals(classified.get("current", []))
        other_signals = sorted(classified.get("other", []), key=str.lower)

        self._add_section(
            self._get_text("simulation.op_result.voltage_section", "节点电压"),
            node_voltages,
            "voltage",
        )
        self._add_section(
            self._get_text("simulation.op_result.source_current_section", "电源电流"),
            source_currents,
            "current",
        )
        self._add_section(
            self._get_text("simulation.op_result.device_current_section", "器件电流"),
            device_currents,
            "current",
        )
        self._add_section(
            self._get_text("simulation.op_result.other_section", "其他量"),
            other_signals,
            "other",
        )

        self._tree.expandAll()
        self._tree.header().setStretchLastSection(True)

    def _add_section(self, title: str, signal_names: list[str], signal_type: str):
        section = QTreeWidgetItem(self._tree, [title, ""])
        section.setFirstColumnSpanned(True)

        row_count = 0
        for signal_name in signal_names:
            formatted_value = self._format_signal_value(signal_name, signal_type)
            if not formatted_value:
                continue
            QTreeWidgetItem(section, [signal_name, formatted_value])
            row_count += 1

        if row_count == 0:
            QTreeWidgetItem(section, [self._get_text("simulation.op_result.none", "无"), ""])

    def _format_signal_value(self, signal_name: str, signal_type: str) -> str:
        value = self._get_signal_scalar(signal_name)
        if value is None:
            return ""

        unit = {
            "voltage": "V",
            "current": "A",
        }.get(signal_type, "")
        if unit:
            return f"{value:.6g} {unit}"
        return f"{value:.6g}"

    def _get_signal_scalar(self, signal_name: str) -> Optional[float]:
        result = self._result
        if result is None or result.data is None:
            return None

        signal = result.data.get_signal(signal_name)
        if signal is None or len(signal) == 0:
            return None

        value = signal[0]
        if np.iscomplexobj(value):
            complex_value = complex(value)
            if abs(complex_value.imag) > 1e-15:
                return None
            return float(complex_value.real)

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _split_current_signals(self, signal_names: list[str]) -> tuple[list[str], list[str]]:
        source_currents: list[str] = []
        device_currents: list[str] = []

        for signal_name in signal_names:
            if self._is_source_current(signal_name):
                source_currents.append(signal_name)
            else:
                device_currents.append(signal_name)

        source_currents.sort(key=self._source_current_sort_key)
        device_currents.sort(key=self._device_current_sort_key)
        return source_currents, device_currents

    def _is_source_current(self, signal_name: str) -> bool:
        target = self._extract_signal_target(signal_name)
        if not target:
            return False
        lead = target[:1].upper()
        return lead in {"V", "I"}

    def _extract_signal_target(self, signal_name: str) -> str:
        if len(signal_name) >= 4 and signal_name[1] == "(" and signal_name.endswith(")"):
            return signal_name[2:-1]
        return signal_name

    def _node_voltage_sort_key(self, signal_name: str) -> tuple[int, str]:
        target = self._extract_signal_target(signal_name)
        return (self._supply_name_rank(target), target.lower())

    def _source_current_sort_key(self, signal_name: str) -> tuple[int, str]:
        target = self._extract_signal_target(signal_name)
        return (self._supply_name_rank(target), target.lower())

    def _device_current_sort_key(self, signal_name: str) -> tuple[int, str]:
        target = self._extract_signal_target(signal_name)
        device_rank = {
            "Q": 0,
            "M": 1,
            "J": 2,
            "D": 3,
            "R": 4,
            "C": 5,
            "L": 6,
            "X": 7,
        }.get(target[:1].upper(), 99)
        return (device_rank, target.lower())

    def _supply_name_rank(self, name: str) -> int:
        lowered = name.lower()
        if lowered.startswith(("vcc", "vdd", "vee", "vss")):
            return 0
        if lowered.startswith(("vp", "vn", "vin", "vref", "ibias")):
            return 1
        return 2

    def _apply_style(self):
        self.setStyleSheet(f"""
            OPResultDialog {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            #opResultTitle {{
                color: {COLOR_TEXT_PRIMARY};
                font-weight: bold;
            }}
            #opResultMeta {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
                background-color: {COLOR_BG_TERTIARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 8px;
            }}
            QTreeWidget {{
                background-color: {COLOR_BG_PRIMARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
            }}
            QTreeWidget::item {{
                padding: 4px 6px;
            }}
        """)

    def _get_text(self, key: str, default: str) -> str:
        try:
            from shared.i18n_manager import I18nManager
            return I18nManager().get_text(key, default)
        except Exception:
            return default


__all__ = ["OPResultDialog"]
