import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MeasureMetadata:
    name: str
    display_name: str
    unit: str
    quantity_kind: str


class MeasureMetadataResolver:
    _FIND_EXPR_PATTERN = re.compile(
        r"\b(?:FIND|MAX|MIN|AVG|RMS|PP|MIN_AT|MAX_AT|INTEG(?:RAL)?|DERIV(?:ATIVE)?)\s+([^\s]+)",
        re.IGNORECASE,
    )
    _PARAM_PATTERN = re.compile(r"\bPARAM\s*=\s*'?([^'\s]+)'?", re.IGNORECASE)
    _REFERENCE_TOKEN_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)([kmg])?$", re.IGNORECASE)

    def resolve(
        self,
        name: str,
        statement: str = "",
    ) -> MeasureMetadata:
        normalized_statement = " ".join(statement.split())
        quantity_kind = self._infer_quantity_kind(normalized_statement)
        unit = self._resolve_unit(quantity_kind, normalized_statement)
        display_name = self._format_display_name(name, quantity_kind)
        return MeasureMetadata(
            name=name,
            display_name=display_name,
            unit=unit,
            quantity_kind=quantity_kind,
        )

    def _infer_quantity_kind(self, statement: str) -> str:
        analysis_type = self._extract_analysis_type(statement)
        operation = self._extract_operation(statement)
        expression = self._extract_expression(statement)
        expression_upper = expression.upper()

        # PARAM expressions may combine unlike quantities or normalize them
        # into a ratio.  The leading token alone cannot establish the result
        # unit, so only an explicit caller-supplied hint may label it.
        if self._PARAM_PATTERN.search(statement):
            return "unknown"

        if operation in {"TRIG", "WHEN", "MIN_AT", "MAX_AT"}:
            if analysis_type in {"AC", "SP"}:
                return "frequency"
            if analysis_type == "TRAN":
                return "time"
            # A DC measure returns the swept source's value. The .measure
            # statement alone does not identify whether that source is a
            # voltage or current source, so guessing from the result name is
            # physically unsafe.
            if analysis_type == "DC":
                return "unknown"

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

    def _resolve_unit(
        self,
        quantity_kind: str,
        statement: str,
    ) -> str:
        expression = self._extract_expression(statement)
        operation = self._extract_operation(statement)
        analysis_type = self._extract_analysis_type(statement)
        base_units = {
            "db": "dB",
            "phase": "rad" if expression.upper().startswith("VP(") else "°",
            "frequency": "Hz",
            "time": "s",
            "voltage": "V",
            "current": "A",
            "power": "W",
            "ratio": "V/V",
        }
        unit = base_units.get(quantity_kind, "")

        if operation in {"INTEG", "INTEGRAL", "DERIV", "DERIVATIVE"} and unit:
            axis_unit = "s" if analysis_type == "TRAN" else "Hz" if analysis_type in {"AC", "SP"} else ""
            if axis_unit:
                separator = "·" if operation in {"INTEG", "INTEGRAL"} else "/"
                return f"{unit}{separator}{axis_unit}"
            return ""

        if unit:
            return unit

        return ""

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

measure_metadata_resolver = MeasureMetadataResolver()
