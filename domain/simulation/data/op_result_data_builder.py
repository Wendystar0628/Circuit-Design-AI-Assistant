from pathlib import Path
from typing import Any, Dict, Optional

from domain.simulation.data.op_result_payload import (
    build_op_result_payload_from_signals,
    build_op_result_sections,
    normalize_op_result_payload,
    render_op_result_markdown,
)
from domain.simulation.models.simulation_result import SimulationResult


class OpResultDataBuilder:
    def build(self, result: Optional[SimulationResult]) -> Dict[str, Any]:
        payload = self.get_payload(result)
        if not payload:
            return {
                "is_available": False,
                "file_name": "",
                "analysis_command": "",
                "row_count": 0,
                "section_count": 0,
                "sections": [],
            }

        assert result is not None
        return {
            "is_available": True,
            "file_name": Path(str(result.file_path or "")).name if str(result.file_path or "") else "",
            "analysis_command": str(result.analysis_command or ".op"),
            "row_count": int(payload.get("row_count", 0)),
            "section_count": int(payload.get("section_count", 0)),
            "sections": build_op_result_sections(payload),
        }

    def build_text(self, result: Optional[SimulationResult]) -> str:
        payload = self.get_payload(result)
        if not payload:
            return ""
        return render_op_result_markdown(payload)

    def get_payload(self, result: Optional[SimulationResult]) -> Dict[str, Any]:
        if not self._is_op_candidate(result):
            return {}

        assert result is not None
        data = result.data
        assert data is not None

        payload = normalize_op_result_payload(getattr(data, "op_result", {}))
        if int(payload.get("row_count", 0)) == 0:
            payload = build_op_result_payload_from_signals(
                getattr(data, "signals", {}),
                getattr(data, "signal_types", {}),
            )
            data.op_result = payload
        return payload if int(payload.get("row_count", 0)) > 0 else {}

    def is_available(self, result: Optional[SimulationResult]) -> bool:
        return bool(self.get_payload(result))

    def _is_op_candidate(self, result: Optional[SimulationResult]) -> bool:
        return bool(
            result is not None
            and result.success
            and getattr(result, "data", None) is not None
            and str(result.analysis_type or "").lower() == "op"
        )


op_result_data_builder = OpResultDataBuilder()

__all__ = ["OpResultDataBuilder", "op_result_data_builder"]
