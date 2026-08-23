"""Read one exact run's authoritative scalar simulation metrics."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from domain.llm.agent.tools.simulation_artifact_reader_base import (
    READ_TOOL_SHARED_GUIDELINES,
    ResolvedSimulationBundle,
    SimulationArtifactReaderBase,
)
from domain.llm.agent.types import BaseTool, ToolContext, ToolResult
from domain.simulation.data.noise_totals import build_noise_totals_payload
from domain.simulation.measure.measure_result import MeasureResult
from domain.simulation.models.display_metric import DisplayMetric
from domain.simulation.service.display_metric_builder import display_metric_builder


_MAX_CONTENT_LINES = 500
_MAX_CELL_CHARS = 300


class ReadMetricsTool(BaseTool):
    @property
    def name(self) -> str:
        return "read_metrics"

    @property
    def label(self) -> str:
        return "Read Metrics"

    @property
    def description(self) -> str:
        return (
            "Read all .MEASURE outcomes from the authoritative "
            "SimulationResult.measurements inside one exact result.json "
            "returned by run_simulation. Successful values and failed "
            "measurement reasons are rendered by the shared display-metric "
            "builder. For NOISE results, also report ngspice's authoritative "
            "output and input-referred RMS totals integrated across that "
            "run's .noise FSTART-to-FSTOP sweep band, from "
            "SimulationResult.data.noise_totals as a separate block; those "
            "totals are not .MEASURE rows and are never inferred by "
            "integrating spectral samples. Mutable project target settings "
            "are not part of the exact-run result, so this tool neither "
            "reports targets nor guesses pass/fail. Optional metric_name "
            "selects an exact case-insensitive metric or display name."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return SimulationArtifactReaderBase.build_parameters_schema(
            extra_properties={
                "metric_name": {
                    "type": "string",
                    "description": (
                        "Optional case-insensitive exact metric name or "
                        "display name."
                    ),
                },
            }
        )

    @property
    def prompt_snippet(self) -> Optional[str]:
        return (
            "Read exact-run .MEASURE outcomes and, for NOISE, integrated RMS "
            "noise totals"
        )

    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        return [
            *READ_TOOL_SHARED_GUIDELINES,
            (
                "Targets are mutable project settings and are not captured in "
                "the immutable result; do not infer a target or pass/fail state."
            ),
            (
                "For NOISE, integrated_noise_totals are ngspice RMS scalars "
                "for that run's FSTART-to-FSTOP sweep band, stored in "
                "result.json:data.noise_totals. They are not "
                ".MEASURE rows or spectral-density samples; never integrate "
                "the sampled spectrum to replace a missing total."
            ),
        ]

    async def execute(
        self,
        tool_call_id: str,
        params: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        resolved = SimulationArtifactReaderBase.resolve(params, context)
        if isinstance(resolved, ToolResult):
            return resolved
        return self._read_metrics(resolved, params)

    def _read_metrics(
        self,
        bundle: ResolvedSimulationBundle,
        params: Dict[str, Any],
    ) -> ToolResult:
        measurements = bundle.result.measurements
        if measurements is not None and (
            not isinstance(measurements, list)
            or any(not isinstance(item, MeasureResult) for item in measurements)
        ):
            return ToolResult(
                content=(
                    "Error: result.json measurements must be a list of "
                    "normalized MeasureResult objects."
                ),
                is_error=True,
                details={"result_path": bundle.result_path},
            )

        rows = display_metric_builder.build(bundle.result, {})
        filter_text = str(params.get("metric_name") or "").strip()
        selected = list(rows)
        if filter_text:
            needle = filter_text.casefold()
            selected = [
                row
                for row in rows
                if needle
                in {
                    str(row.name or "").strip().casefold(),
                    str(row.display_name or "").strip().casefold(),
                }
            ]
            if not selected:
                available = sorted(
                    {str(row.name or "").strip() for row in rows} - {""}
                )
                preview = ", ".join(available[:40]) or "<none>"
                if len(available) > 40:
                    preview += f", … ({len(available) - 40} more)"
                return ToolResult(
                    content=(
                        f"Error: metric '{_cell(filter_text)}' is not present "
                        f"in result '{bundle.result_path}'. Available: {preview}."
                    ),
                    is_error=True,
                    details={"result_path": bundle.result_path},
                )

        selected.sort(
            key=lambda row: str(row.display_name or row.name or "").casefold()
        )
        integrated_noise_totals = _integrated_noise_totals(bundle.result)
        lines = self._render(
            bundle,
            selected,
            filter_text,
            integrated_noise_totals,
        )
        truncated = len(lines) > _MAX_CONTENT_LINES
        if truncated:
            omitted = len(lines) - (_MAX_CONTENT_LINES - 2)
            lines = [
                *lines[: _MAX_CONTENT_LINES - 2],
                "",
                (
                    f"_{omitted} line(s) omitted from exact result "
                    f"'{bundle.result_path}'._"
                ),
            ]

        details = {
            "result_path": bundle.result_path,
            "source": "result.json:measurements",
            "metric_count": len(selected),
            "failed_metric_count": sum(
                1 for row in selected if row.status != "OK"
            ),
            "target_data_available": False,
            "target_comparison_performed": False,
            "truncated": truncated,
        }
        if integrated_noise_totals is not None:
            details["integrated_noise_totals"] = integrated_noise_totals
        return ToolResult(content="\n".join(lines), details=details)

    @staticmethod
    def _render(
        bundle: ResolvedSimulationBundle,
        rows: List[DisplayMetric],
        filter_text: str,
        integrated_noise_totals: Optional[Dict[str, Any]],
    ) -> List[str]:
        result = bundle.result
        lines = [
            "# Metrics",
            "",
            f"- result_path: {bundle.result_path}",
            f"- circuit_file: {_cell(bundle.circuit_file) or '<unknown>'}",
            f"- analysis_type: {_cell(result.analysis_type) or '<unknown>'}",
            f"- timestamp: {_cell(result.timestamp)}",
            f"- metric_count: {len(rows)}",
            "- target_data: unavailable in the immutable simulation result",
            "- target_status: not evaluated",
        ]
        if filter_text:
            lines.append(f"- filter: {_cell(filter_text)}")
        if not rows:
            lines.extend(["", "_No .MEASURE rows are present._"])
        else:
            lines.extend(
                [
                    "",
                    "| metric | status | display_value | raw_value | unit | error |",
                    "| --- | --- | --- | ---: | --- | --- |",
                ]
            )
            for row in rows:
                name = row.display_name or row.name or "<unnamed>"
                lines.append(
                    f"| {_cell(name)} | {_cell(row.status)} | "
                    f"{_cell(row.value) or '—'} | "
                    f"{_raw_number(row.raw_value)} | "
                    f"{_cell(row.unit) or '—'} | "
                    f"{_cell(row.error_message) or '—'} |"
                )
        lines.extend(_render_integrated_noise_totals(integrated_noise_totals))
        return lines


def _integrated_noise_totals(
    result: Any,
) -> Optional[Dict[str, Any]]:
    payload = build_noise_totals_payload(result)
    if not payload["applicable"]:
        return None
    return {
        "source": "result.json:data.noise_totals",
        "available": payload["available"],
        "items": payload["items"],
    }


def _render_integrated_noise_totals(
    payload: Optional[Dict[str, Any]],
) -> List[str]:
    if payload is None:
        return []

    lines = [
        "",
        "## Integrated Noise Totals",
        "",
        "- source: result.json:data.noise_totals",
        "- meaning: ngspice RMS scalars integrated across this run's .noise FSTART-to-FSTOP sweep band; not .MEASURE rows or spectral-density samples",
    ]
    if not payload["available"]:
        lines.extend(
            [
                "- status: unavailable for this run",
                "- inference: none; sampled spectra were not integrated to invent totals",
            ]
        )
        return lines

    for item in payload["items"]:
        key = str(item.get("key") or "")
        if key not in {"output_rms", "input_referred_rms"}:
            raise ValueError(
                "Validated NOISE totals contain an unexpected scalar key"
            )
        value = _raw_number(item.get("value"))
        unit = _cell(item.get("unit"))
        if unit not in {"V", "A"}:
            raise ValueError(
                "Validated NOISE totals must resolve to an exact V or A unit"
            )
        lines.append(f"- {key}: {value} {unit} RMS")
    return lines


def _cell(value: Any) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    text = text.replace("|", "\\|").strip()
    if len(text) > _MAX_CELL_CHARS:
        return text[: _MAX_CELL_CHARS - 1] + "…"
    return text


def _raw_number(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    number = float(value)
    if not math.isfinite(number):
        return "—"
    return f"{number:.12g}"


__all__ = ["ReadMetricsTool"]
