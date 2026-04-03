import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class MeasureDefinition:
    name: str
    statement: str
    description: str = ""


@dataclass(frozen=True)
class MeasureMetadata:
    name: str
    display_name: str
    unit: str
    category: str
    quantity_kind: str
    description: str = ""


class MeasureMetadataResolver:
    _MEASURE_NAME_PATTERN = re.compile(
        r"^\s*\.measure\s+\w+\s+([a-zA-Z_][a-zA-Z0-9_]*)\b",
        re.IGNORECASE,
    )
    _FIND_EXPR_PATTERN = re.compile(
        r"\b(?:FIND|MAX|MIN|AVG|RMS|PP|INTEG|DERIV)\s+([^\s]+)",
        re.IGNORECASE,
    )
    _PARAM_PATTERN = re.compile(r"\bPARAM\s*=\s*'?([^'\s]+)'?", re.IGNORECASE)
    _REFERENCE_TOKEN_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)([kmg])?$", re.IGNORECASE)

    def extract_definitions(self, netlist: str) -> Dict[str, MeasureDefinition]:
        definitions: Dict[str, MeasureDefinition] = {}
        lines = netlist.splitlines()
        comment_buffer = []
        index = 0

        while index < len(lines):
            raw_line = lines[index].rstrip()
            stripped = raw_line.strip()

            if not stripped:
                comment_buffer.clear()
                index += 1
                continue

            if stripped.startswith("*"):
                comment = stripped[1:].strip()
                if comment:
                    comment_buffer.append(comment)
                index += 1
                continue

            if stripped.upper().startswith(".MEASURE"):
                statement_lines = [stripped]
                index += 1
                while index < len(lines):
                    continuation = lines[index].strip()
                    if continuation.startswith("+"):
                        statement_lines.append(continuation[1:].strip())
                        index += 1
                        continue
                    break

                statement = " ".join(part for part in statement_lines if part)
                name = self._extract_measure_name(statement)
                if name:
                    definitions[name] = MeasureDefinition(
                        name=name,
                        statement=statement,
                        description=self._pick_description(comment_buffer),
                    )
                comment_buffer.clear()
                continue

            comment_buffer.clear()
            index += 1

        return definitions

    def resolve(
        self,
        name: str,
        statement: str = "",
        description: str = "",
        fallback_unit: str = "",
    ) -> MeasureMetadata:
        normalized_statement = " ".join(statement.split())
        quantity_kind = self._infer_quantity_kind(name, normalized_statement)
        unit = self._resolve_unit(name, quantity_kind, fallback_unit)
        display_name = description.strip() or self._format_display_name(name, quantity_kind)
        category = self._infer_category(name, quantity_kind)
        return MeasureMetadata(
            name=name,
            display_name=display_name,
            unit=unit,
            category=category,
            quantity_kind=quantity_kind,
            description=description.strip(),
        )

    def _extract_measure_name(self, statement: str) -> str:
        match = self._MEASURE_NAME_PATTERN.match(statement)
        if not match:
            return ""
        return match.group(1)

    def _pick_description(self, comments: Iterable[str]) -> str:
        meaningful = [comment for comment in comments if self._is_meaningful_comment(comment)]
        if not meaningful:
            return ""
        return meaningful[-1]

    def _is_meaningful_comment(self, comment: str) -> bool:
        stripped = comment.strip()
        if not stripped:
            return False
        if stripped.upper().startswith(".MEASURE"):
            return False
        if "MEASURE 语句" in stripped:
            return False
        if set(stripped) <= {"=", "-", "_", "*", " "}:
            return False
        return True

    def _infer_quantity_kind(self, name: str, statement: str) -> str:
        name_lower = name.lower()
        analysis_type = self._extract_analysis_type(statement)
        operation = self._extract_operation(statement)
        expression = self._extract_expression(statement)
        expression_upper = expression.upper()

        if operation == "WHEN":
            if analysis_type == "AC":
                return "frequency"
            if analysis_type == "TRAN":
                return "time"
            if analysis_type == "DC":
                if name_lower.startswith("i") or "current" in name_lower:
                    return "current"
                return "voltage"

        if expression_upper.startswith("VDB("):
            return "db"
        if expression_upper.startswith("VP("):
            return "phase"
        if expression_upper.startswith("VM("):
            return "voltage"
        if expression_upper.startswith("VR("):
            return "voltage"
        if expression_upper.startswith("VI("):
            return "voltage"
        if expression_upper.startswith("V("):
            return "voltage"
        if expression_upper.startswith("I("):
            return "current"
        if expression_upper.startswith("P("):
            return "power"

        if any(keyword in name_lower for keyword in ["phase", "margin", "pm", "deg"]):
            return "phase"
        if any(keyword in name_lower for keyword in ["freq", "f_", "bw", "gbw", "ugf", "bandwidth"]):
            return "frequency"
        if any(keyword in name_lower for keyword in ["rise", "fall", "delay", "period", "pw", "time"]):
            return "time"
        if any(keyword in name_lower for keyword in ["power", "pwr", "pdiss"]):
            return "power"
        if any(keyword in name_lower for keyword in ["noise", "snr", "nf"]):
            return "noise"
        if "db" in name_lower:
            return "db"
        if "gain" in name_lower:
            return "ratio"
        if name_lower.startswith("i") or "current" in name_lower or "bias" in name_lower:
            return "current"
        if name_lower.startswith("v") or "voltage" in name_lower or "offset" in name_lower:
            return "voltage"
        return "unknown"

    def _extract_analysis_type(self, statement: str) -> str:
        parts = statement.split()
        if len(parts) >= 2:
            return parts[1].upper()
        return ""

    def _extract_operation(self, statement: str) -> str:
        parts = statement.split()
        if len(parts) >= 4:
            return parts[3].upper()
        return ""

    def _extract_expression(self, statement: str) -> str:
        if not statement:
            return ""

        find_match = self._FIND_EXPR_PATTERN.search(statement)
        if find_match:
            return find_match.group(1)

        param_match = self._PARAM_PATTERN.search(statement)
        if param_match:
            return param_match.group(1)

        return ""

    def _resolve_unit(self, name: str, quantity_kind: str, fallback_unit: str) -> str:
        if fallback_unit:
            return fallback_unit
        if quantity_kind == "db":
            return "dB"
        if quantity_kind == "phase":
            return "°"
        if quantity_kind == "frequency":
            return "Hz"
        if quantity_kind == "time":
            return "s"
        if quantity_kind == "voltage":
            return "V"
        if quantity_kind == "current":
            return "A"
        if quantity_kind == "power":
            return "W"
        if quantity_kind == "ratio":
            return "V/V"

        name_lower = name.lower()
        if any(keyword in name_lower for keyword in ["phase", "margin", "pm", "deg"]):
            return "°"
        if any(keyword in name_lower for keyword in ["freq", "f_", "bw", "gbw", "ugf", "bandwidth"]):
            return "Hz"
        if any(keyword in name_lower for keyword in ["rise", "fall", "delay", "period", "pw", "time"]):
            return "s"
        if any(keyword in name_lower for keyword in ["power", "pwr", "pdiss"]):
            return "W"
        if "db" in name_lower:
            return "dB"
        if "gain" in name_lower:
            return "V/V"
        if name_lower.startswith("i") or "current" in name_lower or "bias" in name_lower:
            return "A"
        if name_lower.startswith("v") or "voltage" in name_lower or "offset" in name_lower:
            return "V"
        return ""

    def _infer_category(self, name: str, quantity_kind: str) -> str:
        name_lower = name.lower()

        if any(keyword in name_lower for keyword in ["noise", "snr", "nf"]):
            return "noise"
        if any(keyword in name_lower for keyword in ["thd", "distortion", "imd", "sfdr"]):
            return "distortion"
        if quantity_kind in {"power", "current"} or any(
            keyword in name_lower for keyword in ["power", "current", "efficiency", "consumption"]
        ):
            return "power"
        if quantity_kind == "time" or any(
            keyword in name_lower for keyword in ["rise", "fall", "slew", "settling", "overshoot", "delay"]
        ):
            return "transient"
        if quantity_kind in {"db", "phase", "frequency", "ratio"} or any(
            keyword in name_lower for keyword in ["gain", "bandwidth", "phase", "margin", "gbw"]
        ):
            return "amplifier"
        return "general"

    def _format_display_name(self, name: str, quantity_kind: str) -> str:
        name_lower = name.lower()

        if name_lower == "gain_dc":
            return "DC Gain"
        if name_lower == "f_3db":
            return "-3 dB Frequency"
        if name_lower == "phase_3db":
            return "Phase @ -3 dB"

        if name_lower.startswith("gain_"):
            reference = self._format_reference(name_lower.split("_", 1)[1])
            if reference:
                return f"Gain @ {reference}"
        if name_lower.startswith("phase_"):
            reference = self._format_reference(name_lower.split("_", 1)[1])
            if reference:
                return f"Phase @ {reference}"
        if name_lower.startswith("v_"):
            suffix = name_lower.split("_", 1)[1]
            if suffix in {"oh", "ol", "th", "ih", "il"}:
                return f"V{suffix.upper()}"

        tokens = [self._format_token(token, quantity_kind) for token in name.split("_") if token]
        return " ".join(token for token in tokens if token) or name

    def _format_reference(self, token: str) -> str:
        if token == "dc":
            return "DC"
        if token.endswith("db") and token[:-2].replace(".", "", 1).isdigit():
            return f"-{token[:-2]} dB"

        match = self._REFERENCE_TOKEN_PATTERN.match(token)
        if not match:
            return ""

        value = match.group(1)
        suffix = (match.group(2) or "").lower()
        if suffix == "k":
            return f"{value} kHz"
        if suffix == "m":
            return f"{value} MHz"
        if suffix == "g":
            return f"{value} GHz"
        return value

    def _format_token(self, token: str, quantity_kind: str) -> str:
        token_lower = token.lower()
        special = {
            "dc": "DC",
            "ac": "AC",
            "db": "dB",
            "gbw": "GBW",
            "ugf": "UGF",
            "bw": "BW",
            "pp": "PP",
            "snr": "SNR",
            "thd": "THD",
            "nf": "NF",
        }
        if token_lower in special:
            return special[token_lower]

        reference = self._format_reference(token_lower)
        if reference and quantity_kind in {"db", "phase", "ratio", "frequency"}:
            return reference

        if token_lower.startswith("v") and len(token_lower) > 1 and token_lower[1:].isalpha():
            return f"V{token_lower[1:]}".title()
        if token_lower.startswith("i") and len(token_lower) > 1 and token_lower[1:].isalpha():
            return f"I{token_lower[1:]}".title()

        if token.isupper():
            return token
        return token.title()


_NUMBER_PATTERN = re.compile(r"^\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*(.*)$")
_ENGINEERING_PREFIXES = {
    "g": 1e9,
    "meg": 1e6,
    "k": 1e3,
    "m": 1e-3,
    "u": 1e-6,
    "μ": 1e-6,
    "n": 1e-9,
    "p": 1e-12,
}


def coerce_metric_value(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, dict):
        return coerce_metric_value(value.get("value"))
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None

    match = _NUMBER_PATTERN.match(value.strip())
    if not match:
        return None

    try:
        numeric_value = float(match.group(1))
    except ValueError:
        return None

    suffix = match.group(2).strip()
    if not suffix:
        return numeric_value

    suffix_lower = suffix.lower()
    if suffix_lower.startswith("meg"):
        return numeric_value * _ENGINEERING_PREFIXES["meg"]

    prefix = suffix[0]
    if prefix in {"G", "K", "M"}:
        return numeric_value * {"G": 1e9, "K": 1e3, "M": 1e6}[prefix]

    if prefix.lower() in _ENGINEERING_PREFIXES and suffix_lower not in {"db", "deg"}:
        return numeric_value * _ENGINEERING_PREFIXES[prefix.lower()]

    return numeric_value


def infer_unit_hint(value: Any) -> str:
    if isinstance(value, dict):
        explicit_unit = value.get("unit")
        if isinstance(explicit_unit, str) and explicit_unit.strip():
            return explicit_unit.strip()
        value = value.get("value")

    if not isinstance(value, str):
        return ""

    match = _NUMBER_PATTERN.match(value.strip())
    if not match:
        return ""

    suffix = match.group(2).strip()
    if not suffix:
        return ""

    suffix_lower = suffix.lower()
    if suffix_lower.endswith("db"):
        return "dB"
    if suffix_lower.endswith("deg") or suffix == "°":
        return "°"
    if suffix_lower.endswith("hz"):
        return "Hz"
    if suffix_lower.endswith("s"):
        return "s"
    if suffix_lower.endswith("v"):
        return "V"
    if suffix_lower.endswith("a"):
        return "A"
    if suffix_lower.endswith("w"):
        return "W"
    return ""


def extract_numeric_metric_values(measurements: Any = None) -> Dict[str, float]:
    values: Dict[str, float] = {}

    if measurements:
        for measurement in measurements:
            if hasattr(measurement, "name"):
                name = getattr(measurement, "name", "")
                raw_value = getattr(measurement, "value", None)
                is_valid = getattr(measurement, "is_valid", None)
                status = getattr(measurement, "status", None)
                if is_valid is None:
                    if hasattr(status, "value"):
                        is_valid = status.value == "OK" and raw_value is not None
                    else:
                        is_valid = status == "OK" and raw_value is not None
            elif isinstance(measurement, dict):
                name = measurement.get("name", "")
                raw_value = measurement.get("value")
                status = measurement.get("status", "OK")
                is_valid = status == "OK" and raw_value is not None
            else:
                continue

            if not name or not is_valid:
                continue

            numeric_value = coerce_metric_value(raw_value)
            if numeric_value is not None:
                values[name] = numeric_value

    return values


def resolve_result_metric_values(result: Any) -> Dict[str, float]:
    return extract_numeric_metric_values(measurements=getattr(result, "measurements", None))


def get_result_metric_value(result: Any, name: str, default: Any = None) -> Any:
    values = resolve_result_metric_values(result)
    return values.get(name, default)


def normalize_measurements_payload(measurements: Optional[List[Any]]) -> List[Any]:
    if not measurements:
        return []

    from domain.simulation.measure.measure_result import MeasureResult, MeasureStatus

    results: List[MeasureResult] = []
    for item in measurements:
        if isinstance(item, MeasureResult):
            metadata = measure_metadata_resolver.resolve(
                item.name,
                statement=item.statement,
                description=item.description or item.display_name,
                fallback_unit=item.unit,
            )
            results.append(MeasureResult(
                name=item.name,
                value=item.value,
                unit=metadata.unit,
                status=item.status,
                statement=item.statement,
                description=item.description,
                display_name=item.display_name or metadata.display_name,
                category=item.category or metadata.category,
                quantity_kind=metadata.quantity_kind,
                raw_output=item.raw_output,
                error_message=item.error_message,
            ))
            continue

        if not isinstance(item, dict):
            continue

        name = item.get("name", "")
        if not name:
            continue

        raw_value = item.get("value")
        unit = item.get("unit", "") or infer_unit_hint(raw_value)
        display_name = item.get("display_name", "")
        category = item.get("category", "")
        description = item.get("description", "")
        statement = item.get("statement", "")
        status_raw = item.get("status", "OK")

        try:
            status = status_raw if isinstance(status_raw, MeasureStatus) else MeasureStatus(str(status_raw))
        except ValueError:
            status = MeasureStatus.PARSE_ERROR

        value = None if raw_value is None else coerce_metric_value(raw_value)
        metadata = measure_metadata_resolver.resolve(
            name,
            statement=statement,
            description=description or display_name,
            fallback_unit=unit,
        )

        results.append(MeasureResult(
            name=name,
            value=value,
            unit=metadata.unit,
            status=status,
            statement=statement,
            description=description,
            display_name=display_name or metadata.display_name,
            category=category or metadata.category,
            quantity_kind=metadata.quantity_kind,
            raw_output=item.get("raw_output", ""),
            error_message=item.get("error_message", ""),
        ))

    return results


measure_metadata_resolver = MeasureMetadataResolver()
