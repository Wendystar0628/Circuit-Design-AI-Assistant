"""Read raw numerical signals from one exact simulation result.

The tool intentionally has no UI-chart or waveform-selection branch.  Charts
are presentation derivatives; ``SimulationResult.data`` is the single raw
signal authority tied to the supplied result handle.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from domain.llm.agent.tools.simulation_artifact_reader_base import (
    READ_TOOL_SHARED_GUIDELINES,
    ResolvedSimulationBundle,
    SimulationArtifactReaderBase,
)
from domain.llm.agent.tools.simulation_series_stats import (
    AnchorRow,
    AnchorScale,
    SeriesReadResult,
    SeriesStats,
    read_series_table,
)
from domain.llm.agent.types import BaseTool, ToolContext, ToolResult
from domain.simulation.data.waveform_data_service import waveform_data_service


_DEFAULT_ANCHOR_COUNT = 14
_MAX_SIGNALS_PER_CALL = 32
_MAX_FILTER_ENTRIES = 64
_MAX_CONTENT_LINES = 500


class ReadSignalsTool(BaseTool):
    @property
    def name(self) -> str:
        return "read_signals"

    @property
    def label(self) -> str:
        return "Read Signals"

    @property
    def description(self) -> str:
        return (
            "Read the raw numerical signal table in SimulationResult.data "
            "for one exact result_path returned by run_simulation. Reports "
            "min/max/sample_mean/initial/final/peak-to-peak and bounded "
            "anchor rows. sample_mean is an arithmetic sample mean, not an "
            "integrated physical average. UI charts, PNGs, displayed-series "
            "state, and .MEASURE figures of merit are deliberately outside "
            "this tool. Complex _phase series remain wrapped in degrees and "
            "no unit conversion is guessed. Use signal_filter when a result "
            "has more than 32 resolved signals."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return SimulationArtifactReaderBase.build_parameters_schema(
            extra_properties={
                "signal_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": _MAX_FILTER_ENTRIES,
                    "description": (
                        "Optional signal names. Exact names are preferred; "
                        "canonical voltage/current normalization and AC "
                        "complex-component expansion are supported."
                    ),
                },
                "anchor_count": {
                    "type": "integer",
                    "minimum": 4,
                    "maximum": 32,
                    "description": "Number of bounded anchor rows; default 14.",
                },
                "anchor_scale": {
                    "type": "string",
                    "enum": ["auto", "linear", "log"],
                    "description": (
                        "Anchor distribution. auto uses log for AC/noise "
                        "frequency axes and linear otherwise."
                    ),
                },
            }
        )

    @property
    def prompt_snippet(self) -> Optional[str]:
        return "Read exact-run raw signal statistics and anchor samples"

    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        return [
            *READ_TOOL_SHARED_GUIDELINES,
            "Use read_metrics for .MEASURE values and read_op_result for .op data; read_signals only reports raw numerical series.",
            "Do not interpret sample_mean as a time-weighted, frequency-weighted, RMS, or integrated engineering metric.",
            "Treat *_phase values as wrapped degrees; the tool does not unwrap phase or derive margins/bandwidth from samples.",
        ]

    async def execute(
        self,
        tool_call_id: str,
        params: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        bundle = SimulationArtifactReaderBase.resolve(params, context)
        if isinstance(bundle, ToolResult):
            return bundle
        return self._read(bundle, params)

    def _read(
        self,
        bundle: ResolvedSimulationBundle,
        params: Dict[str, Any],
    ) -> ToolResult:
        result = bundle.result
        if not result.success:
            return _error(
                bundle,
                "the simulation result is unsuccessful and has no trustworthy raw signal table",
            )
        if result.data is None:
            return _error(bundle, "SimulationResult.data is absent")

        available = tuple(waveform_data_service.get_resolved_signal_names(result))
        filter_or_error = _parse_filter(params.get("signal_filter"), bundle)
        if isinstance(filter_or_error, ToolResult):
            return filter_or_error
        requested = filter_or_error

        selected, unmatched = self._resolve_filter(bundle, requested)
        if requested and not selected:
            return _error(
                bundle,
                "none of the requested signals exists. Available resolved "
                f"signals: {_preview_names(available)}",
            )
        if not requested:
            selected = available
        if not selected:
            return _error(bundle, "the result contains no readable signal vectors")
        if len(selected) > _MAX_SIGNALS_PER_CALL:
            return _error(
                bundle,
                f"the result exposes {len(selected)} resolved signals; pass "
                f"signal_filter with at most {_MAX_SIGNALS_PER_CALL}. Available: "
                f"{_preview_names(selected)}",
            )

        anchor_count_or_error = _parse_anchor_count(
            params.get("anchor_count"), bundle
        )
        if isinstance(anchor_count_or_error, ToolResult):
            return anchor_count_or_error
        anchor_count = anchor_count_or_error

        scale_or_error = _parse_anchor_scale(
            params.get("anchor_scale"), result.analysis_type, bundle
        )
        if isinstance(scale_or_error, ToolResult):
            return scale_or_error

        snapshot = waveform_data_service.build_table_snapshot(
            result, list(selected)
        )
        if snapshot is None:
            return _error(
                bundle,
                "the result has no tabular x axis; use read_op_result for .op data",
            )
        try:
            summary = read_series_table(
                x_column_name=snapshot.x_label,
                signal_column_names=snapshot.signal_names,
                x_values=snapshot.x_values,
                signal_columns=snapshot.signal_columns,
                anchor_count=anchor_count,
                anchor_scale=scale_or_error,
            )
        except (TypeError, ValueError) as exc:
            return _error(bundle, f"raw signal table is inconsistent: {exc}")

        lines = self._render(
            bundle=bundle,
            summary=summary,
            available=available,
            unmatched=unmatched,
            anchor_count=anchor_count,
        )
        truncated = len(lines) > _MAX_CONTENT_LINES
        if truncated:
            omitted = len(lines) - (_MAX_CONTENT_LINES - 2)
            lines = [
                *lines[: _MAX_CONTENT_LINES - 2],
                "",
                f"_{omitted} line(s) omitted; narrow signal_filter._",
            ]

        return ToolResult(
            content="\n".join(lines),
            details={
                "result_path": bundle.result_path,
                "source": "result.json:data",
                "signal_count": len(summary.signal_column_names),
                "signal_count_total": len(available),
                "sample_count": summary.total_rows,
                "x_order": summary.x_order,
                "anchor_count_requested": anchor_count,
                "anchor_count_effective": len(summary.anchors),
                "anchor_scale_requested": summary.anchor_scale_requested.value,
                "anchor_scale_effective": summary.anchor_scale_effective.value,
                "unmatched_filter_names": list(unmatched),
                "truncated": truncated,
            },
        )

    @staticmethod
    def _resolve_filter(
        bundle: ResolvedSimulationBundle,
        requested: Tuple[str, ...],
    ) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
        selected: List[str] = []
        unmatched: List[str] = []
        seen = set()
        for name in requested:
            resolved = waveform_data_service.get_resolved_signal_names(
                bundle.result, [name]
            )
            if not resolved:
                unmatched.append(name)
                continue
            for resolved_name in resolved:
                if resolved_name not in seen:
                    selected.append(resolved_name)
                    seen.add(resolved_name)
        return tuple(selected), tuple(unmatched)

    @staticmethod
    def _render(
        *,
        bundle: ResolvedSimulationBundle,
        summary: SeriesReadResult,
        available: Sequence[str],
        unmatched: Sequence[str],
        anchor_count: int,
    ) -> List[str]:
        result = bundle.result
        lines = [
            "# Raw Signals",
            "",
            f"- result_path: {bundle.result_path}",
            f"- circuit_file: {_cell(bundle.circuit_file) or '<unknown>'}",
            f"- analysis_type: {_cell(result.analysis_type) or '<unknown>'}",
            f"- timestamp: {_cell(result.timestamp)}",
            "- source_authority: result.json -> SimulationResult.data",
            f"- x_axis: {_cell(summary.x_column_name)}",
            f"- x_range: [{_fmt(summary.x_range[0])}, {_fmt(summary.x_range[1])}]",
            f"- x_order: {summary.x_order}",
            f"- sample_count: {summary.total_rows}",
            f"- signal_count: {len(summary.signal_column_names)} of {len(available)}",
            f"- anchor_scale: {summary.anchor_scale_effective.value}",
            "- statistic_semantics: sample_mean is arithmetic over finite samples; no interpolation, integration, RMS, or zero-crossing inference is performed",
            "- phase_semantics: *_phase vectors are wrapped degrees; no phase unwrapping is performed",
            "- unit_semantics: values are simulator-native scalars; this tool does not guess or convert physical units",
        ]
        if summary.anchor_scale_effective is not summary.anchor_scale_requested:
            lines.append(
                f"- anchor_scale_fallback: requested "
                f"{summary.anchor_scale_requested.value}, used linear because "
                "the x axis is non-positive or degenerate"
            )
        if unmatched:
            lines.append(
                f"- unmatched_signal_filter: {_cell(', '.join(unmatched))}"
            )

        lines.extend(
            [
                "",
                "## Descriptive sample statistics",
                "",
                "| signal | finite_samples | min | max | sample_mean | initial_finite | final_finite | peak_to_peak |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        lines.extend(_render_stats_row(stats) for stats in summary.stats)

        if summary.anchors:
            lines.extend(
                [
                    "",
                    f"## Anchor rows ({len(summary.anchors)} of requested {anchor_count})",
                    "",
                    "| " + _cell(summary.x_column_name) + " | "
                    + " | ".join(_cell(name) for name in summary.signal_column_names)
                    + " |",
                    "| " + " | ".join(
                        ["---:", *(["---:"] * len(summary.signal_column_names))]
                    ) + " |",
                ]
            )
            lines.extend(_render_anchor_row(anchor) for anchor in summary.anchors)
        return lines


def _parse_filter(
    raw: Any,
    bundle: ResolvedSimulationBundle,
) -> Tuple[str, ...] | ToolResult:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        return _error(bundle, "signal_filter must be an array of non-empty strings")
    if len(raw) > _MAX_FILTER_ENTRIES:
        return _error(
            bundle, f"signal_filter accepts at most {_MAX_FILTER_ENTRIES} entries"
        )
    names: List[str] = []
    seen = set()
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            return _error(bundle, "signal_filter must contain only non-empty strings")
        name = item.strip()
        if name not in seen:
            names.append(name)
            seen.add(name)
    return tuple(names)


def _parse_anchor_count(
    raw: Any,
    bundle: ResolvedSimulationBundle,
) -> int | ToolResult:
    if raw is None:
        return _DEFAULT_ANCHOR_COUNT
    if isinstance(raw, bool) or not isinstance(raw, int) or not 4 <= raw <= 32:
        return _error(bundle, "anchor_count must be an integer from 4 through 32")
    return raw


def _parse_anchor_scale(
    raw: Any,
    analysis_type: str,
    bundle: ResolvedSimulationBundle,
) -> AnchorScale | ToolResult:
    value = str(raw or "auto").strip().lower()
    if value == "linear":
        return AnchorScale.LINEAR
    if value == "log":
        return AnchorScale.LOG
    if value != "auto":
        return _error(bundle, "anchor_scale must be auto, linear, or log")
    normalized_analysis = str(analysis_type or "").strip().lstrip(".").lower()
    return (
        AnchorScale.LOG
        if normalized_analysis in {"ac", "noise"}
        else AnchorScale.LINEAR
    )


def _render_stats_row(stats: SeriesStats) -> str:
    return (
        f"| {_cell(stats.name)} | {stats.samples} | {_fmt(stats.min_value)} | "
        f"{_fmt(stats.max_value)} | {_fmt(stats.sample_mean)} | "
        f"{_fmt(stats.initial_value)} | {_fmt(stats.final_value)} | "
        f"{_fmt(stats.peak_to_peak)} |"
    )


def _render_anchor_row(anchor: AnchorRow) -> str:
    values = [
        _fmt(value) if value is not None else "—" for value in anchor.values
    ]
    return "| " + " | ".join([_fmt(anchor.x), *values]) + " |"


def _preview_names(names: Sequence[str]) -> str:
    visible = list(names[:40])
    preview = ", ".join(visible) or "<none>"
    if len(names) > 40:
        preview += f", … ({len(names) - 40} more)"
    return preview


def _cell(value: Any) -> str:
    return (
        str(value or "")
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("|", "\\|")
        .strip()
    )


def _fmt(value: Optional[float]) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    return f"{number:.12g}"


def _error(bundle: ResolvedSimulationBundle, reason: str) -> ToolResult:
    return ToolResult(
        content=f"Error: cannot read raw signals for '{bundle.result_path}': {reason}.",
        is_error=True,
        details={"result_path": bundle.result_path},
    )


__all__ = ["ReadSignalsTool"]
