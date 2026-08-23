"""Read one exact run's authoritative embedded simulator output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from domain.llm.agent.tools.simulation_artifact_reader_base import (
    READ_TOOL_SHARED_GUIDELINES,
    ResolvedSimulationBundle,
    SimulationArtifactReaderBase,
)
from domain.llm.agent.types import BaseTool, ToolContext, ToolResult
from domain.llm.agent.utils.truncate import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_LINES,
    truncate_head,
)
from domain.simulation.data.simulation_output_reader import (
    LogLine,
    simulation_output_reader,
)


_TAIL_LINE_COUNT = 20
_DEFAULT_WARNING_LIMIT = 20
_DEFAULT_ERROR_LIMIT = 50
_VALID_SECTIONS = {"", "errors", "warnings", "tail", "all"}


@dataclass(frozen=True)
class _OutputLog:
    raw_output: str
    lines: List[LogLine]

    @property
    def errors(self) -> List[LogLine]:
        return [line for line in self.lines if line.is_error()]

    @property
    def warnings(self) -> List[LogLine]:
        return [line for line in self.lines if line.is_warning()]


class ReadOutputLogTool(BaseTool):
    @property
    def name(self) -> str:
        return "read_output_log"

    @property
    def label(self) -> str:
        return "Read Output Log"

    @property
    def description(self) -> str:
        return (
            "Parse the authoritative SimulationResult.raw_output inside one "
            "exact result.json. The default view reports counts, a bounded "
            "error and warning preview, and the final 20 parsed lines. "
            "section='all' returns the exact embedded simulator text."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return SimulationArtifactReaderBase.build_parameters_schema(
            extra_properties={
                "section": {
                    "type": "string",
                    "enum": ["errors", "warnings", "tail", "all"],
                    "description": (
                        "Optional focused view. Omit for bounded diagnostics; "
                        "'all' returns raw simulator output."
                    ),
                },
            }
        )

    @property
    def prompt_snippet(self) -> Optional[str]:
        return "Read exact-run simulator diagnostics or bounded raw output"

    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        return [
            *READ_TOOL_SHARED_GUIDELINES,
            "Use the default compact diagnostic view before requesting section='all'.",
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

        section = str(params.get("section") or "").strip().lower()
        if section not in _VALID_SECTIONS:
            return ToolResult(
                content=(
                    f"Error: unsupported section {section!r}; expected "
                    "errors, warnings, tail, all, or omission."
                ),
                is_error=True,
                details={"result_path": bundle.result_path},
            )

        raw_output = bundle.result.raw_output
        if raw_output is None:
            raw_output = ""
        if not isinstance(raw_output, str):
            return _invalid(
                bundle,
                "result.json raw_output must be a string or null",
            )
        output = _OutputLog(
            raw_output=raw_output,
            lines=simulation_output_reader.get_output_log_from_text(
                raw_output,
                max_lines=None,
            ),
        )

        content = self._render(bundle, output, section)
        truncation = truncate_head(
            content,
            max_lines=DEFAULT_MAX_LINES,
            max_bytes=DEFAULT_MAX_BYTES,
        )
        if truncation.truncated:
            content = (
                truncation.content
                + "\n\n"
                + f"[Output truncated by {truncation.truncated_by}; source "
                + f"remains exact result '{bundle.result_path}'.]"
            )

        errors = output.errors
        warnings = output.warnings
        return ToolResult(
            content=content,
            details={
                "result_path": bundle.result_path,
                "section": section or "default",
                "source": "result.json:raw_output",
                "total_lines": len(output.lines),
                "error_count": len(errors),
                "warning_count": len(warnings),
                "first_error": errors[0].content if errors else None,
                "truncated": truncation.truncated,
            },
        )

    def _render(
        self,
        bundle: ResolvedSimulationBundle,
        output: _OutputLog,
        section: str,
    ) -> str:
        errors = output.errors
        warnings = output.warnings
        header = [
            f"source: result.json:raw_output | result_path: {bundle.result_path}",
            f"circuit_file: {bundle.circuit_file or '<unknown>'}",
        ]
        summary = [
            "## summary",
            f"- total_lines: {len(output.lines)}",
            f"- error_count: {len(errors)}",
            f"- warning_count: {len(warnings)}",
            f"- first_error: {errors[0].content if errors else '<none>'}",
        ]

        if section == "all":
            raw = output.raw_output or "<empty raw simulator output>"
            return "\n".join([*header, "", "## raw simulator output", raw])
        if section == "errors":
            return _join(header, summary, self._log_section("errors", errors, None))
        if section == "warnings":
            return _join(header, summary, self._log_section("warnings", warnings, None))
        if section == "tail":
            return _join(
                header,
                summary,
                self._log_section("tail", output.lines[-_TAIL_LINE_COUNT:], None),
            )
        return _join(
            header,
            summary,
            self._log_section("errors", errors, _DEFAULT_ERROR_LIMIT),
            self._log_section("warnings", warnings, _DEFAULT_WARNING_LIMIT),
            self._log_section("tail", output.lines[-_TAIL_LINE_COUNT:], None),
        )

    @staticmethod
    def _log_section(
        name: str,
        lines: List[LogLine],
        limit: Optional[int],
    ) -> List[str]:
        section = [f"## {name}"]
        if not lines:
            return [*section, "- <none>"]
        visible = lines if limit is None else lines[:limit]
        section.extend(_format_log_line(line) for line in visible)
        if limit is not None and len(lines) > limit:
            section.append(f"- … {len(lines) - limit} additional line(s) omitted")
        return section


def _format_log_line(line: LogLine) -> str:
    content = str(line.content or "").replace("\r", " ").replace("\n", " ")
    return f"- L{line.line_number} [{line.level}] {content}"


def _join(*sections: List[str]) -> str:
    return "\n\n".join("\n".join(section) for section in sections)


def _invalid(bundle: ResolvedSimulationBundle, reason: str) -> ToolResult:
    return ToolResult(
        content=(
            f"Error: invalid embedded output log for "
            f"'{bundle.result_path}': {reason}."
        ),
        is_error=True,
        details={"result_path": bundle.result_path},
    )


__all__ = ["ReadOutputLogTool"]
