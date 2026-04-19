from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
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
from domain.simulation.data.simulation_artifact_exporter import (
    simulation_artifact_exporter,
)
from domain.simulation.data.simulation_output_reader import (
    LogLine,
    SimulationSummary,
    simulation_output_reader,
)

_WARNING_PREVIEW_LIMIT = 20
_TAIL_LINE_COUNT = 20
_VALID_SECTIONS = {"", "errors", "warnings", "tail", "all"}


@dataclass(frozen=True)
class _LoadedOutputLog:
    summary: SimulationSummary
    lines: List[LogLine]
    raw_output: str
    full_text_for_all: str
    structured_source: str
    structured_source_path: Path
    full_text_source_path: Path
    text_path: Path
    json_path: Path


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
            "Read a simulation bundle's NgSpice output log as a compact "
            "diagnostic view. By default it returns a self-identifying "
            "header, summary (total_lines/error_count/warning_count/"
            "first_error), all error lines, a warning preview, and the "
            "last 20 lines. Optional section='errors' | 'warnings' | "
            "'tail' narrows the response; section='all' returns the full "
            "log text truncated with the same shared head-truncation "
            "limits used by read_file. Supply result_path from an earlier "
            "run_simulation for an exact handle; supply file_path to pick "
            "that circuit's most recent bundle; omit both to fall back to "
            "the editor's active circuit."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return SimulationArtifactReaderBase.build_parameters_schema(
            extra_properties={
                "section": {
                    "type": "string",
                    "enum": ["errors", "warnings", "tail", "all"],
                    "description": (
                        "Optional focused view. Omit this parameter for the "
                        "default compact diagnostic layout (summary + all "
                        "errors + warning preview + tail). Use 'all' only "
                        "when the compact view is insufficient."
                    ),
                },
            },
        )

    @property
    def prompt_snippet(self) -> Optional[str]:
        return (
            "Read the important diagnostic slices of a simulation output log "
            "without dumping the whole file by default"
        )

    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        return [
            *READ_TOOL_SHARED_GUIDELINES,
            (
                "When simulation failure or suspicious NgSpice behaviour is "
                "the question, call read_output_log without section first — "
                "the default view returns summary, all errors, a warning "
                "preview, and the last 20 lines in one response."
            ),
            (
                "Do not jump straight to read_output_log(section='all') "
                "unless the compact diagnostic view is insufficient."
            ),
            (
                "Treat read_output_log's first_error field as a diagnostic "
                "lead for the next step (for example, deciding whether to "
                "inspect the netlist, metrics, or the full log)."
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

        section = str(params.get("section") or "").strip().lower()
        if section not in _VALID_SECTIONS:
            return ToolResult(
                content=(
                    "Error: unsupported section value "
                    f"'{params.get('section')}'. Expected one of "
                    "errors, warnings, tail, all, or omit the parameter "
                    "for the default compact diagnostic view."
                ),
                is_error=True,
            )

        loaded = self._load_output_log(resolved)
        if isinstance(loaded, ToolResult):
            return loaded

        if section == "all":
            return self._format_all(resolved, loaded)
        if section == "errors":
            content = self._join_sections(
                self._build_header(resolved, loaded),
                self._build_summary_section(loaded.summary),
                self._build_errors_section(loaded.lines),
            )
        elif section == "warnings":
            content = self._join_sections(
                self._build_header(resolved, loaded),
                self._build_summary_section(loaded.summary),
                self._build_warnings_section(
                    loaded.lines,
                    limit=None,
                    text_path=loaded.text_path,
                ),
            )
        elif section == "tail":
            content = self._join_sections(
                self._build_header(resolved, loaded),
                self._build_summary_section(loaded.summary),
                self._build_tail_section(loaded.lines),
            )
        else:
            content = self._join_sections(
                self._build_header(resolved, loaded),
                self._build_summary_section(loaded.summary),
                self._build_errors_section(loaded.lines),
                self._build_warnings_section(
                    loaded.lines,
                    limit=_WARNING_PREVIEW_LIMIT,
                    text_path=loaded.text_path,
                ),
                self._build_tail_section(loaded.lines),
            )

        return ToolResult(
            content=content,
            details={
                "result_path": resolved.result_path,
                "used_fallback": resolved.used_fallback,
                "section": section or "default",
                "structured_source": loaded.structured_source,
                "structured_source_path": str(loaded.structured_source_path),
                "output_log_text_path": str(loaded.text_path),
                "output_log_json_path": str(loaded.json_path),
                "total_lines": loaded.summary.total_lines,
                "error_count": loaded.summary.error_count,
                "warning_count": loaded.summary.warning_count,
                "first_error": loaded.summary.first_error,
            },
        )

    def _load_output_log(
        self,
        bundle: ResolvedSimulationBundle,
    ) -> _LoadedOutputLog | ToolResult:
        paths = simulation_artifact_exporter.output_log_paths(bundle.bundle_dir)
        text_content, text_error = self._try_read_text(paths.text_path)

        if paths.json_path.is_file():
            json_loaded = self._try_load_from_json(
                bundle=bundle,
                json_path=paths.json_path,
                text_path=paths.text_path,
                text_content=text_content,
            )
            if isinstance(json_loaded, _LoadedOutputLog):
                return json_loaded
            json_error = json_loaded
        else:
            json_error = None

        if text_content is not None:
            return self._load_from_text(
                bundle=bundle,
                text_path=paths.text_path,
                json_path=paths.json_path,
                text_content=text_content,
            )

        if not paths.json_path.is_file() and not paths.text_path.is_file():
            return ToolResult(
                content=(
                    f"Error: output log artifacts are missing for bundle "
                    f"'{bundle.result_path}': neither '{paths.json_path.as_posix()}' "
                    f"nor '{paths.text_path.as_posix()}' exists. Check whether "
                    "run_simulation succeeded for this circuit, or inspect "
                    "read_metrics if you expected a successful run to emit "
                    "measurements."
                ),
                is_error=True,
            )

        problems: List[str] = []
        if json_error:
            problems.append(json_error)
        if text_error:
            problems.append(text_error)
        detail_text = "; ".join(problems) if problems else "unknown reason"
        return ToolResult(
            content=(
                f"Error: failed to load output log artifacts for bundle "
                f"'{bundle.result_path}'. {detail_text}. Check whether "
                "run_simulation completed successfully, or inspect "
                "read_metrics if a partial result exists."
            ),
            is_error=True,
        )

    def _try_load_from_json(
        self,
        *,
        bundle: ResolvedSimulationBundle,
        json_path: Path,
        text_path: Path,
        text_content: Optional[str],
    ) -> _LoadedOutputLog | str:
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return f"output_log.json could not be parsed ({exc})"

        summary_data = payload.get("summary")
        summary = (
            SimulationSummary.from_dict(summary_data)
            if isinstance(summary_data, dict)
            else SimulationSummary()
        )

        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        raw_output = data.get("raw_output") if isinstance(data.get("raw_output"), str) else ""
        raw_lines = data.get("lines") if isinstance(data.get("lines"), list) else []
        lines = self._deserialize_lines(raw_lines)
        if not raw_output and lines:
            raw_output = "\n".join(str(line.content or "") for line in lines)
        if not lines and raw_output:
            lines = self._parse_log_text(raw_output)
        if self._summary_needs_fallback(summary) and lines:
            summary = self._build_summary_from_lines(lines)

        full_text_for_all: str
        full_text_source_path: Path
        if text_content is not None:
            full_text_for_all = text_content
            full_text_source_path = text_path
        else:
            full_text_for_all = self._build_full_text_fallback(
                bundle=bundle,
                source_path=json_path,
                raw_output=raw_output,
            )
            full_text_source_path = json_path

        return _LoadedOutputLog(
            summary=summary,
            lines=lines,
            raw_output=raw_output,
            full_text_for_all=full_text_for_all,
            structured_source="json",
            structured_source_path=json_path,
            full_text_source_path=full_text_source_path,
            text_path=text_path,
            json_path=json_path,
        )

    def _load_from_text(
        self,
        *,
        bundle: ResolvedSimulationBundle,
        text_path: Path,
        json_path: Path,
        text_content: str,
    ) -> _LoadedOutputLog:
        raw_output = self._strip_export_header(text_content)
        lines = self._parse_log_text(raw_output)
        summary = self._build_summary_from_lines(lines)
        return _LoadedOutputLog(
            summary=summary,
            lines=lines,
            raw_output=raw_output,
            full_text_for_all=text_content,
            structured_source="text",
            structured_source_path=text_path,
            full_text_source_path=text_path,
            text_path=text_path,
            json_path=json_path,
        )

    @staticmethod
    def _try_read_text(path: Path) -> tuple[Optional[str], Optional[str]]:
        if not path.is_file():
            return None, None
        try:
            return path.read_text(encoding="utf-8"), None
        except OSError as exc:
            return None, f"output_log.txt could not be read ({exc})"

    @staticmethod
    def _deserialize_lines(items: List[Any]) -> List[LogLine]:
        lines: List[LogLine] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                lines.append(LogLine.from_dict(item))
            except (KeyError, TypeError, ValueError):
                continue
        return lines

    @staticmethod
    def _parse_log_text(raw_output: str) -> List[LogLine]:
        if not raw_output:
            return []
        max_lines = raw_output.count("\n") + 1
        return simulation_output_reader.get_output_log_from_text(
            raw_output,
            max_lines=max_lines,
        )

    @staticmethod
    def _build_summary_from_lines(lines: List[LogLine]) -> SimulationSummary:
        error_lines = [line for line in lines if line.is_error()]
        warning_lines = [line for line in lines if line.is_warning()]
        return SimulationSummary(
            total_lines=len(lines),
            error_count=len(error_lines),
            warning_count=len(warning_lines),
            info_count=len(lines) - len(error_lines) - len(warning_lines),
            first_error=error_lines[0].content if error_lines else None,
        )

    @staticmethod
    def _summary_needs_fallback(summary: SimulationSummary) -> bool:
        return (
            summary.total_lines <= 0
            and summary.error_count <= 0
            and summary.warning_count <= 0
            and not summary.first_error
        )

    @staticmethod
    def _strip_export_header(text: str) -> str:
        lines = text.splitlines()
        index = 0
        while index < len(lines) and lines[index].startswith("# "):
            index += 1
        if index > 0 and index < len(lines) and lines[index] == "":
            return "\n".join(lines[index + 1 :])
        return text

    @staticmethod
    def _build_header(
        bundle: ResolvedSimulationBundle,
        loaded: _LoadedOutputLog,
    ) -> List[str]:
        return [
            f"artifact_type: output_log | result_path: {bundle.result_path}",
            (
                f"source: {loaded.structured_source_path.as_posix()} | "
                f"circuit_file: {bundle.circuit_file or '<unknown>'}"
            ),
        ]

    @staticmethod
    def _build_summary_section(summary: SimulationSummary) -> List[str]:
        return [
            "## summary",
            f"- total_lines: {summary.total_lines}",
            f"- error_count: {summary.error_count}",
            f"- warning_count: {summary.warning_count}",
            f"- first_error: {summary.first_error or '<none>'}",
        ]

    @staticmethod
    def _build_errors_section(lines: List[LogLine]) -> List[str]:
        error_lines = [line for line in lines if line.is_error()]
        section = ["## errors"]
        if not error_lines:
            section.append("- <none>")
            return section
        section.extend(ReadOutputLogTool._format_log_line(line) for line in error_lines)
        return section

    @staticmethod
    def _build_warnings_section(
        lines: List[LogLine],
        *,
        limit: Optional[int],
        text_path: Path,
    ) -> List[str]:
        warning_lines = [line for line in lines if line.is_warning()]
        section = ["## warnings"]
        if not warning_lines:
            section.append("- <none>")
            return section

        visible = warning_lines if limit is None else warning_lines[:limit]
        section.extend(ReadOutputLogTool._format_log_line(line) for line in visible)
        if limit is not None and len(warning_lines) > limit:
            omitted = len(warning_lines) - limit
            section.append(
                (
                    f"- {omitted} warning(s) omitted; for the complete list, "
                    f"see '{text_path.as_posix()}'."
                )
            )
        return section

    @staticmethod
    def _build_tail_section(lines: List[LogLine]) -> List[str]:
        section = ["## tail"]
        if not lines:
            section.append("- <none>")
            return section
        tail = lines[-_TAIL_LINE_COUNT:]
        section.extend(ReadOutputLogTool._format_log_line(line) for line in tail)
        return section

    def _format_all(
        self,
        bundle: ResolvedSimulationBundle,
        loaded: _LoadedOutputLog,
    ) -> ToolResult:
        truncation = truncate_head(
            loaded.full_text_for_all,
            max_lines=DEFAULT_MAX_LINES,
            max_bytes=DEFAULT_MAX_BYTES,
        )
        content = truncation.content
        if truncation.truncated:
            content += (
                "\n\n"
                f"[Output truncated by {truncation.truncated_by}; showing the first "
                f"{truncation.output_lines} of {truncation.total_lines} lines from "
                f"'{loaded.full_text_source_path.as_posix()}'. The shared limit is "
                f"{DEFAULT_MAX_LINES} lines / {DEFAULT_MAX_BYTES // 1024}KB.]"
            )
        return ToolResult(
            content=content,
            details={
                "result_path": bundle.result_path,
                "used_fallback": bundle.used_fallback,
                "section": "all",
                "structured_source": loaded.structured_source,
                "structured_source_path": str(loaded.structured_source_path),
                "full_text_source_path": str(loaded.full_text_source_path),
                "output_log_text_path": str(loaded.text_path),
                "output_log_json_path": str(loaded.json_path),
                "truncation": {
                    "truncated": truncation.truncated,
                    "truncated_by": truncation.truncated_by,
                    "total_lines": truncation.total_lines,
                    "total_bytes": truncation.total_bytes,
                    "output_lines": truncation.output_lines,
                    "output_bytes": truncation.output_bytes,
                    "max_lines": truncation.max_lines,
                    "max_bytes": truncation.max_bytes,
                },
            },
        )

    @staticmethod
    def _build_full_text_fallback(
        *,
        bundle: ResolvedSimulationBundle,
        source_path: Path,
        raw_output: str,
    ) -> str:
        prefix = [
            f"artifact_type: output_log | result_path: {bundle.result_path}",
            f"source: {source_path.as_posix()} | circuit_file: {bundle.circuit_file or '<unknown>'}",
            "",
        ]
        if raw_output:
            prefix.append(raw_output)
        return "\n".join(prefix)

    @staticmethod
    def _format_log_line(line: LogLine) -> str:
        return f"- L{line.line_number} [{line.level}] {line.content}"

    @staticmethod
    def _join_sections(*sections: List[str]) -> str:
        lines: List[str] = []
        for index, section in enumerate(sections):
            if index > 0:
                lines.append("")
            lines.extend(section)
        return "\n".join(lines)


__all__ = ["ReadOutputLogTool"]
