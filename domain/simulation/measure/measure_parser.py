"""Parse the measurement section emitted by ngspice.

The parser intentionally does not infer units or UI metadata. ngspice prints
only numeric values here; the netlist statement is the authoritative source
for physical semantics and is resolved by the executor after parsing.
"""

from __future__ import annotations

import math
import re
from collections import OrderedDict
from typing import List, Optional, Sequence

from domain.simulation.measure.measure_result import MeasureResult, MeasureStatus


_SECTION_HEADER = re.compile(
    r"^Measurements for (?P<analysis>.+?) Analysis$",
    re.IGNORECASE,
)
_NUMBER = r"[-+]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?|inf(?:inity)?|nan)"
_SUCCESS_LINE = re.compile(
    rf"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    rf"(?P<value>{_NUMBER})"
    rf"(?P<details>(?:\s+(?:from|to|targ|trig|at)\s*=\s*{_NUMBER})*)\s*$",
    re.IGNORECASE,
)
_FAILED_LINE = re.compile(
    r"^\.meas(?:ure)?\s+(?:dc|ac|tran|sp)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b.*\bfailed!\s*$",
    re.IGNORECASE,
)


class MeasureParser:
    """Extract final ``.measure`` outcomes from ngspice callback output."""

    def parse_measure_output(
        self,
        output: str,
        *,
        analysis_type: str = "",
        expected_names: Optional[Sequence[str]] = None,
    ) -> List[MeasureResult]:
        """Parse outcomes for exactly one authoritative analysis.

        ngspice may print multiple measurement sections when an included file
        adds another analysis.  A single-analysis result must never merge
        those sections.  When ``expected_names`` is supplied, only those
        closure-validated requests are admitted and every missing outcome is
        materialized as ``FAILED`` instead of disappearing silently.
        """

        cleaned_lines = self._clean_output(output).splitlines()
        in_measurement_output = False
        requested_analysis = self._normalize_analysis_type(analysis_type)
        expected_by_key = (
            {
                str(name).casefold(): str(name)
                for name in expected_names
                if str(name).strip()
            }
            if expected_names is not None
            else None
        )
        results: "OrderedDict[str, MeasureResult]" = OrderedDict()
        recent_error = ""

        for raw_line in cleaned_lines:
            line = raw_line.strip()
            section = _SECTION_HEADER.fullmatch(line)
            if section is not None:
                section_analysis = self._normalize_analysis_type(
                    section.group("analysis")
                )
                in_measurement_output = (
                    not requested_analysis
                    or section_analysis == requested_analysis
                )
                recent_error = ""
                continue
            if not in_measurement_output or not line:
                continue

            success = _SUCCESS_LINE.fullmatch(line)
            if success is not None:
                name = success.group("name")
                if (
                    expected_by_key is not None
                    and name.casefold() not in expected_by_key
                ):
                    continue
                raw_value = success.group("value")
                try:
                    value = float(raw_value)
                except ValueError:
                    value = math.nan

                if math.isfinite(value):
                    result = MeasureResult(
                        name=name,
                        value=value,
                        status=MeasureStatus.OK,
                        raw_output=line,
                    )
                else:
                    result = MeasureResult(
                        name=name,
                        value=None,
                        status=MeasureStatus.FAILED,
                        raw_output=line,
                        error_message=f"ngspice returned a non-finite value: {raw_value}",
                    )
                self._store_latest(results, result)
                recent_error = ""
                continue

            failed = _FAILED_LINE.fullmatch(line)
            if failed is not None:
                name = failed.group("name")
                if (
                    expected_by_key is not None
                    and name.casefold() not in expected_by_key
                ):
                    continue
                self._store_latest(
                    results,
                    MeasureResult(
                        name=name,
                        value=None,
                        status=MeasureStatus.FAILED,
                        raw_output=line,
                        error_message=recent_error or "Measurement condition was not satisfied",
                    ),
                )
                recent_error = ""
                continue

            # The callback emits the useful reason (for example "out of
            # interval") immediately before the echoed failed statement.
            if line.lower().startswith("error:") or "out of interval" in line.lower():
                recent_error = line

        if expected_by_key is not None:
            for key, expected_name in expected_by_key.items():
                if key in results:
                    continue
                results[key] = MeasureResult(
                    name=expected_name,
                    value=None,
                    status=MeasureStatus.FAILED,
                    error_message=(
                        "ngspice did not emit an outcome for this requested "
                        "measurement in the authoritative analysis section"
                    ),
                )

        return list(results.values())

    @staticmethod
    def _store_latest(
        results: "OrderedDict[str, MeasureResult]",
        result: MeasureResult,
    ) -> None:
        key = result.name.casefold()
        if key in results:
            del results[key]
        results[key] = result

    @staticmethod
    def _clean_output(output: str) -> str:
        lines = []
        for line in output.splitlines():
            callback_line = line.lstrip()
            if callback_line.startswith("stdout ") or callback_line.startswith("stderr "):
                line = callback_line[7:]
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _normalize_analysis_type(value: object) -> str:
        normalized = str(value or "").strip().lstrip(".").casefold()
        aliases = {
            "transient": "tran",
            "operating point": "op",
        }
        return aliases.get(normalized, normalized)


measure_parser = MeasureParser()
