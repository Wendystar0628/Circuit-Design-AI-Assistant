from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from domain.simulation.data.waveform_data_service import waveform_data_service
from domain.simulation.models.simulation_result import SimulationResult


class OpResultDataBuilder:
    def build(self, result: Optional[SimulationResult]) -> Dict[str, Any]:
        if not self.is_available(result):
            return {
                "is_available": False,
                "file_name": "",
                "analysis_command": "",
                "row_count": 0,
                "section_count": 0,
                "sections": [],
            }

        assert result is not None
        classified = waveform_data_service.get_classified_signals(result)
        node_voltages = sorted(classified.get("voltage", []), key=self._node_voltage_sort_key)
        source_currents, device_currents = self._split_current_signals(classified.get("current", []))
        other_signals = sorted(classified.get("other", []), key=str.lower)
        sections = [
            self._build_section("node_voltage", "节点电压", node_voltages, "voltage", result),
            self._build_section("source_current", "电源电流", source_currents, "current", result),
            self._build_section("device_current", "器件电流", device_currents, "current", result),
            self._build_section("other", "其他量", other_signals, "other", result),
        ]
        row_count = sum(int(section["row_count"]) for section in sections)
        return {
            "is_available": True,
            "file_name": Path(str(result.file_path or "")).name if str(result.file_path or "") else "",
            "analysis_command": str(result.analysis_command or ".op"),
            "row_count": row_count,
            "section_count": len(sections),
            "sections": sections,
        }

    def build_text(self, result: Optional[SimulationResult]) -> str:
        payload = self.build(result)
        if not payload.get("is_available", False):
            return ""
        lines = [
            f"file_name: {payload.get('file_name', '')}",
            f"analysis_command: {payload.get('analysis_command', '')}",
            f"row_count: {payload.get('row_count', 0)}",
            "",
        ]
        for section in payload.get("sections", []):
            lines.append(f"[{section.get('title', '')}]")
            rows = section.get("rows", []) or []
            if not rows:
                lines.append("  无")
                lines.append("")
                continue
            for row in rows:
                lines.append(f"  {row.get('name', '')}: {row.get('formatted_value', '')}")
            lines.append("")
        return "\n".join(lines).strip()

    def is_available(self, result: Optional[SimulationResult]) -> bool:
        return bool(
            result is not None
            and result.success
            and getattr(result, "data", None) is not None
            and str(result.analysis_type or "").lower() == "op"
        )

    def _build_section(
        self,
        section_id: str,
        title: str,
        signal_names: List[str],
        signal_type: str,
        result: SimulationResult,
    ) -> Dict[str, Any]:
        rows = [
            row
            for row in (self._build_row(signal_name, signal_type, result) for signal_name in signal_names)
            if row is not None
        ]
        return {
            "id": section_id,
            "title": title,
            "row_count": len(rows),
            "rows": rows,
        }

    def _build_row(self, signal_name: str, signal_type: str, result: SimulationResult) -> Optional[Dict[str, Any]]:
        value = self._get_signal_scalar(result, signal_name)
        if value is None:
            return None
        unit = {
            "voltage": "V",
            "current": "A",
        }.get(signal_type, "")
        formatted_value = f"{value:.6g} {unit}".strip()
        return {
            "name": signal_name,
            "formatted_value": formatted_value,
            "raw_value": value,
            "unit": unit,
        }

    def _get_signal_scalar(self, result: SimulationResult, signal_name: str) -> Optional[float]:
        data = getattr(result, "data", None)
        if data is None:
            return None
        signal = data.get_signal(signal_name) if hasattr(data, "get_signal") else None
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

    def _split_current_signals(self, signal_names: List[str]) -> Tuple[List[str], List[str]]:
        source_currents: List[str] = []
        device_currents: List[str] = []
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
        return target[:1].upper() in {"V", "I"}

    def _extract_signal_target(self, signal_name: str) -> str:
        if len(signal_name) >= 4 and signal_name[1] == "(" and signal_name.endswith(")"):
            return signal_name[2:-1]
        return signal_name

    def _node_voltage_sort_key(self, signal_name: str) -> Tuple[int, str]:
        target = self._extract_signal_target(signal_name)
        return (self._supply_name_rank(target), target.lower())

    def _source_current_sort_key(self, signal_name: str) -> Tuple[int, str]:
        target = self._extract_signal_target(signal_name)
        return (self._supply_name_rank(target), target.lower())

    def _device_current_sort_key(self, signal_name: str) -> Tuple[int, str]:
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
        lowered = str(name or "").lower()
        if lowered.startswith(("vcc", "vdd", "vee", "vss")):
            return 0
        if lowered.startswith(("vp", "vn", "vin", "vref", "ibias")):
            return 1
        return 2


op_result_data_builder = OpResultDataBuilder()

__all__ = ["OpResultDataBuilder", "op_result_data_builder"]
