"""Closure-wide authority for native ngspice ``.measure`` cards.

The application does not generate measurements.  It discovers the physical
cards that ngspice will see, binds every one to the single authoritative
analysis, and preserves source identity for diagnostics and result matching.
Expression bodies remain entirely owned by ngspice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from domain.simulation.spice.directive_tokenizer import (
    is_spice_end_directive,
    tokenize_spice_directive,
)
from domain.simulation.spice.source_closure import (
    SpiceSourceCommand,
    SpiceSourceView,
)


_MEASURE_PREFIX = re.compile(r"^\.meas(?:ure)?\b", re.IGNORECASE)
_MEASURE_HEADER = re.compile(
    r"^\.meas(?:ure)?\s+(?P<analysis>\S+)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+(?P<body>.+)$",
    re.IGNORECASE,
)
_MEASURE_ANALYSES = frozenset({"ac", "dc", "tran"})


@dataclass(frozen=True)
class MeasureValidationError:
    statement: str
    error_type: str
    message: str
    suggestion: str
    source_id: str
    line_number: int


@dataclass(frozen=True)
class MeasureRequest:
    analysis_type: str
    name: str
    statement: str
    source_id: str
    line_number: int


@dataclass(frozen=True)
class ParsedMeasureStatement:
    """Pure structural header parsed from one logical ``.measure`` card."""

    analysis_type: str
    name: str
    body: str


def parse_measure_statement(statement: object) -> ParsedMeasureStatement | None:
    """Parse one complete top-level measure card without evaluating its body."""

    if not isinstance(statement, str) or not statement.strip():
        return None
    if any(character in statement for character in ("\x00", "\r", "\n")):
        return None
    header = _MEASURE_HEADER.fullmatch(statement.strip())
    if header is None:
        return None
    body = header.group("body").strip()
    if not body:
        return None
    return ParsedMeasureStatement(
        analysis_type=header.group("analysis").casefold(),
        name=header.group("name"),
        body=body,
    )


class MeasureAuthority:
    """Discover and validate one source closure's native measurements."""

    def validate_source_views(
        self,
        source_views: Sequence[SpiceSourceView],
        analysis_command: SpiceSourceCommand,
    ) -> Tuple[Tuple[MeasureRequest, ...], List[MeasureValidationError]]:
        if not isinstance(analysis_command, SpiceSourceCommand):
            raise TypeError("analysis_command must be a SpiceSourceCommand")
        requests: List[MeasureRequest] = []
        errors: List[MeasureValidationError] = []
        for source_view in source_views:
            view_requests, view_errors = self._scan_view(source_view)
            requests.extend(view_requests)
            errors.extend(view_errors)
        errors.extend(self._validate_request_set(requests, analysis_command))
        return tuple(requests), errors

    def _scan_view(
        self,
        source_view: SpiceSourceView,
    ) -> Tuple[List[MeasureRequest], List[MeasureValidationError]]:
        lines = source_view.lines
        requests: List[MeasureRequest] = []
        errors: List[MeasureValidationError] = []
        in_control = False
        index = 0

        while index < len(lines):
            source_line = lines[index]
            stripped = source_line.text.strip()
            line_number = source_line.line_number
            index += 1

            if source_view.is_main_deck and line_number == 1:
                continue

            command = (
                stripped.split(None, 1)[0].casefold()
                if stripped.startswith(".")
                else ""
            )
            if in_control:
                if command == ".endc":
                    in_control = False
                continue
            if command == ".control":
                in_control = True
                continue
            if is_spice_end_directive(source_line.text):
                break
            if not _MEASURE_PREFIX.match(stripped):
                continue

            parts = [stripped]
            while index < len(lines):
                continuation = lines[index].text.strip()
                if not continuation.startswith("+"):
                    break
                parts.append(continuation[1:].strip())
                index += 1
            statement = " ".join(part for part in parts if part)
            parsed = parse_measure_statement(statement)
            if parsed is None:
                errors.append(
                    self._error(
                        source_view,
                        line_number,
                        statement,
                        "INVALID_MEASURE_HEADER",
                        ".measure 缺少有效的分析类型、结果名或表达式。",
                        "使用 .measure <AC|DC|TRAN> <name> <expression>。",
                    )
                )
                continue

            request = MeasureRequest(
                analysis_type=parsed.analysis_type,
                name=parsed.name,
                statement=statement,
                source_id=source_view.source_id,
                line_number=line_number,
            )
            requests.append(request)
            if request.analysis_type not in _MEASURE_ANALYSES:
                errors.append(
                    self._request_error(
                        request,
                        "INVALID_ANALYSIS_TYPE",
                        (
                            f"ngspice 顶层 .measure 不支持 "
                            f"{request.analysis_type.upper()} 分析。"
                        ),
                        "顶层 .measure 仅允许 AC、DC 或 TRAN。",
                    )
                )

        return requests, errors

    def _validate_request_set(
        self,
        requests: Sequence[MeasureRequest],
        analysis_command: SpiceSourceCommand,
    ) -> List[MeasureValidationError]:
        if not requests:
            return []

        final_analysis = analysis_command.analysis_type.casefold()
        errors: List[MeasureValidationError] = []
        names: dict[str, MeasureRequest] = {}
        analysis_tokens = tokenize_spice_directive(analysis_command.statement)
        is_nested_dc = (
            final_analysis == "dc"
            and len(analysis_tokens) == 9
            and analysis_tokens[0].casefold() == ".dc"
        )

        for request in requests:
            normalized_name = request.name.casefold()
            first = names.get(normalized_name)
            if first is not None:
                errors.append(
                    self._request_error(
                        request,
                        "DUPLICATE_RESULT_NAME",
                        (
                            f"测量结果名 {request.name} 重复；首次定义位于 "
                            f"{first.source_id}:{first.line_number}。"
                        ),
                        "整个 source closure 中的测量结果名必须唯一。",
                    )
                )
            else:
                names[normalized_name] = request

            if request.analysis_type not in _MEASURE_ANALYSES:
                continue
            if final_analysis not in _MEASURE_ANALYSES:
                errors.append(
                    self._request_error(
                        request,
                        "UNSUPPORTED_FINAL_ANALYSIS",
                        (
                            f"最终 {final_analysis.upper() or 'UNKNOWN'} 分析"
                            "不能承载顶层 .measure 结果。"
                        ),
                        "工作点和噪声结果应直接读取仿真向量。",
                    )
                )
            elif request.analysis_type != final_analysis:
                errors.append(
                    self._request_error(
                        request,
                        "ANALYSIS_TYPE_MISMATCH",
                        (
                            f".measure {request.analysis_type.upper()} 不能绑定到"
                            f"最终 {final_analysis.upper()} 分析结果。"
                        ),
                        "所有闭包内测量必须与唯一主分析类型一致。",
                    )
                )
            elif is_nested_dc:
                errors.append(
                    self._request_error(
                        request,
                        "NESTED_DC_MEASURE_UNSUPPORTED",
                        (
                            "双源嵌套 DC 扫描的 ngspice .measure 输出不携带"
                            "外层扫描值，单个标量无法绑定到唯一分支。"
                        ),
                        (
                            "直接读取带分段身份的原始 DC 向量，或拆成独立的"
                            "单源 DC 扫描后再测量。"
                        ),
                    )
                )
        return errors

    @staticmethod
    def _error(
        source_view: SpiceSourceView,
        line_number: int,
        statement: str,
        error_type: str,
        message: str,
        suggestion: str,
    ) -> MeasureValidationError:
        return MeasureValidationError(
            statement=statement,
            error_type=error_type,
            message=f"{source_view.source_id}:{line_number}: {message}",
            suggestion=suggestion,
            source_id=source_view.source_id,
            line_number=line_number,
        )

    @staticmethod
    def _request_error(
        request: MeasureRequest,
        error_type: str,
        message: str,
        suggestion: str,
    ) -> MeasureValidationError:
        return MeasureValidationError(
            statement=request.statement,
            error_type=error_type,
            message=f"{request.source_id}:{request.line_number}: {message}",
            suggestion=suggestion,
            source_id=request.source_id,
            line_number=request.line_number,
        )


measure_authority = MeasureAuthority()


__all__ = [
    "MeasureAuthority",
    "MeasureRequest",
    "MeasureValidationError",
    "ParsedMeasureStatement",
    "measure_authority",
    "parse_measure_statement",
]
