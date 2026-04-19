from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.llm.agent.tools.simulation_artifact_reader_base import (
    READ_TOOL_SHARED_GUIDELINES,
    SimulationArtifactReaderBase,
    sort_op_result_branch_rows,
    sort_op_result_device_rows,
    sort_op_result_node_rows,
)
from domain.llm.agent.types import BaseTool, ToolContext, ToolResult
from domain.simulation.data.op_result_data_builder import op_result_data_builder
from domain.simulation.data.op_result_payload import render_op_result_markdown
from domain.simulation.data.simulation_artifact_exporter import (
    CATEGORY_OP_RESULT,
    simulation_artifact_exporter,
)


class ReadOpResultTool(BaseTool):
    @property
    def name(self) -> str:
        return "read_op_result"

    @property
    def label(self) -> str:
        return "Read Op Result"

    @property
    def description(self) -> str:
        return (
            "Read a simulation bundle's NgSpice .op operating-point result as "
            "a compact structured report. It returns a self-identifying header, "
            "a nodes table (name/voltage/formatted), a branches table "
            "(device/current/formatted), and an optional devices table "
            "(device/operating_region/key_parameters). Supply result_path from "
            "an earlier run_simulation for an exact handle; supply file_path to "
            "pick that circuit's most recent bundle; omit both to fall back to "
            "the editor's active circuit. This tool is only for actual .op results."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return SimulationArtifactReaderBase.build_parameters_schema()

    @property
    def prompt_snippet(self) -> Optional[str]:
        return "Read structured .op operating-point node voltages, branch currents, and device bias info"

    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        return [
            *READ_TOOL_SHARED_GUIDELINES,
            (
                "Use read_op_result only when the current result actually comes "
                "from an NgSpice .op operating-point analysis."
            ),
            (
                "Do not call read_op_result for AC / DC / TRAN / NOISE waveform "
                "results; use read_metrics or read_signals instead."
            ),
            (
                "If read_op_result reports that no .op result is available, tell "
                "the user that this circuit/result did not execute a usable .op "
                "analysis instead of forcing a read."
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

        analysis_type = str(getattr(resolved.result, "analysis_type", "") or "").lower()
        if analysis_type != "op":
            return ToolResult(
                content=(
                    "Error: read_op_result only supports actual .op operating-point "
                    f"results, but this bundle is analysis_type='{analysis_type or '<unknown>'}'. "
                    "Use read_metrics for .MEASURE summaries and read_signals for waveform/chart data. "
                    "If you need node voltages or branch currents, rerun the circuit with a real .op analysis first."
                ),
                is_error=True,
                details={
                    "result_path": resolved.result_path,
                    "used_fallback": resolved.used_fallback,
                    "analysis_type": analysis_type,
                },
            )

        paths = simulation_artifact_exporter.op_result_paths(resolved.bundle_dir)
        text_content = self._try_read_text(paths.text_path)
        if text_content is not None:
            return ToolResult(
                content=text_content,
                details={
                    "result_path": resolved.result_path,
                    "used_fallback": resolved.used_fallback,
                    "analysis_type": analysis_type,
                    "source": "op_result.txt",
                    "op_result_text_path": str(paths.text_path),
                    "op_result_json_path": str(paths.json_path),
                },
            )

        payload = op_result_data_builder.get_payload(resolved.result)
        if not payload:
            return ToolResult(
                content=(
                    "Error: no structured .op operating-point result is available for this bundle. "
                    "Tell the user that this circuit/result did not produce usable .op data, and do not force a read. "
                    "Use read_metrics for existing .MEASURE output, or rerun the circuit with .op if operating-point "
                    "node voltages and branch currents are needed."
                ),
                is_error=True,
                details={
                    "result_path": resolved.result_path,
                    "used_fallback": resolved.used_fallback,
                    "analysis_type": analysis_type,
                    "op_result_text_path": str(paths.text_path),
                    "op_result_json_path": str(paths.json_path),
                },
            )

        normalized_payload = {
            **payload,
            "nodes": sort_op_result_node_rows(list(payload.get("nodes") or [])),
            "branches": sort_op_result_branch_rows(list(payload.get("branches") or [])),
            "devices": sort_op_result_device_rows(list(payload.get("devices") or [])),
        }
        content = (
            simulation_artifact_exporter.build_text_header_block(resolved.result, CATEGORY_OP_RESULT)
            + render_op_result_markdown(normalized_payload)
        )
        return ToolResult(
            content=content,
            details={
                "result_path": resolved.result_path,
                "used_fallback": resolved.used_fallback,
                "analysis_type": analysis_type,
                "source": "result.data.op_result",
                "op_result_text_path": str(paths.text_path),
                "op_result_json_path": str(paths.json_path),
                "row_count": int(normalized_payload.get("row_count", 0)),
                "section_count": int(normalized_payload.get("section_count", 0)),
            },
        )

    def _try_read_text(self, path: Path) -> Optional[str]:
        if not path.is_file():
            return None
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return None
        if not content.strip():
            return None
        if "## nodes" not in content or "| name | voltage | formatted |" not in content:
            return None
        return content


__all__ = ["ReadOpResultTool"]
