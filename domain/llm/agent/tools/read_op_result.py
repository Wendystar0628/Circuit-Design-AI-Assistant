"""Read one exact run's operating-point view derived from authoritative signals.

``result.json`` signal vectors are the single persisted truth. Optional OP
export files are human-facing derived views and are never read back as a
second source.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from domain.llm.agent.tools.simulation_artifact_reader_base import (
    READ_TOOL_SHARED_GUIDELINES,
    SimulationArtifactReaderBase,
)
from domain.llm.agent.types import BaseTool, ToolContext, ToolResult
from domain.llm.agent.utils.truncate import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_LINES,
    truncate_head,
)
from domain.simulation.data.op_result_payload import render_op_result_markdown


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
            "Read node voltages, branch currents, and device operating "
            "information derived from authoritative SimulationData.signals "
            "inside one exact .op result.json returned by run_simulation."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return SimulationArtifactReaderBase.build_parameters_schema()

    @property
    def prompt_snippet(self) -> Optional[str]:
        return "Read exact-run structured .op node voltages and branch currents"

    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        return [
            *READ_TOOL_SHARED_GUIDELINES,
            "Use this tool only for a result whose analysis_type is .op.",
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

        analysis_type = (
            str(bundle.result.analysis_type or "").strip().lstrip(".").lower()
        )
        if analysis_type != "op":
            return ToolResult(
                content=(
                    "Error: read_op_result requires an exact .op bundle; "
                    f"this result has analysis_type="
                    f"'{bundle.result.analysis_type or '<unknown>'}'."
                ),
                is_error=True,
                details={
                    "result_path": bundle.result_path,
                    "analysis_type": analysis_type,
                },
            )

        if not bundle.result.success or bundle.result.data is None:
            return _invalid_payload(
                bundle.result_path,
                "the simulation did not produce successful structured data",
            )
        derived = bundle.result.data.op_result
        if not isinstance(derived, dict):
            return _invalid_payload(
                bundle.result_path,
                "the OP view derived from result.json data.signals must be an object",
            )
        if not any(derived[key] for key in ("nodes", "branches", "devices")):
            return _invalid_payload(
                bundle.result_path,
                "result.json data.signals produce no valid node, branch, or device rows",
            )

        content = "\n".join(
            [
                (
                    "source: result.json:data.signals (derived OP view) | "
                    f"result_path: {bundle.result_path}"
                ),
                f"circuit_file: {bundle.circuit_file or '<unknown>'}",
                f"analysis_type: {bundle.result.analysis_type}",
                f"timestamp: {bundle.result.timestamp}",
                "",
                render_op_result_markdown(derived),
            ]
        )
        truncation = truncate_head(
            content,
            max_lines=DEFAULT_MAX_LINES,
            max_bytes=DEFAULT_MAX_BYTES,
        )
        if truncation.truncated:
            content = (
                truncation.content
                + "\n\n"
                + f"[Output truncated by {truncation.truncated_by}; pass the "
                + "same exact result_path again with a narrower workflow if needed.]"
            )

        return ToolResult(
            content=content,
            details={
                "result_path": bundle.result_path,
                "analysis_type": analysis_type,
                "source": "result.json:data.signals (derived OP view)",
                "row_count": sum(
                    len(derived[key]) for key in ("nodes", "branches", "devices")
                ),
                "truncated": truncation.truncated,
            },
        )


def _invalid_payload(result_path: str, reason: str) -> ToolResult:
    return ToolResult(
        content=f"Error: invalid derived OP view for '{result_path}': {reason}.",
        is_error=True,
        details={"result_path": result_path},
    )


__all__ = ["ReadOpResultTool"]
