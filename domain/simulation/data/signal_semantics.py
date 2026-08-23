from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np

from domain.simulation.spice.numeric import parse_spice_number
from domain.simulation.spice.directive_tokenizer import tokenize_spice_directive
from domain.simulation.spice.noise_directive import parse_noise_directive

SIGNAL_TYPE_VOLTAGE = "voltage"
SIGNAL_TYPE_CURRENT = "current"
SIGNAL_TYPE_OTHER = "other"

VECTOR_TYPE_TIME = 1
VECTOR_TYPE_FREQUENCY = 2
VECTOR_TYPE_VOLTAGE = 3
VECTOR_TYPE_CURRENT = 4
VECTOR_TYPE_OUTPUT_N_DENS = 5
VECTOR_TYPE_OUTPUT_NOISE = 6
VECTOR_TYPE_INPUT_N_DENS = 7
VECTOR_TYPE_INPUT_NOISE = 8

_VALID_SIGNAL_TYPES = {
    SIGNAL_TYPE_VOLTAGE,
    SIGNAL_TYPE_CURRENT,
    SIGNAL_TYPE_OTHER,
}
VIRTUAL_COMPLEX_COMPONENT_SUFFIXES = ("_mag", "_phase", "_real", "_imag")
_NOISE_OUTPUT_VECTOR_TYPES = {
    VECTOR_TYPE_OUTPUT_N_DENS,
    VECTOR_TYPE_OUTPUT_NOISE,
}
_NOISE_INPUT_VECTOR_TYPES = {
    VECTOR_TYPE_INPUT_N_DENS,
    VECTOR_TYPE_INPUT_NOISE,
}
_DEVICE_PARAMETER_SIGNAL_PATTERN = re.compile(
    r"^@(?P<device>[^\[\]]+)\[(?P<parameter>[^\[\]]+)\]$"
)
_DEVICE_PARAMETER_UNIT_MAP = {
    "id": "A",
    "cd": "A",
    "ic": "A",
    "ib": "A",
    "ie": "A",
    "is": "A",
    "ig": "A",
    "ibd": "A",
    "ibs": "A",
    "gm": "S",
    "gds": "S",
    "gmb": "S",
    "gmbs": "S",
    "vgs": "V",
    "vds": "V",
    "vbs": "V",
    "vbd": "V",
    "vdsat": "V",
    "vth": "V",
    "von": "V",
    "vbe": "V",
    "vce": "V",
    "vbc": "V",
    "ro": "Ω",
}


@dataclass(frozen=True)
class NestedDCSweep:
    primary_source: str
    primary_start: float
    primary_stop: float
    primary_step: float
    secondary_source: str
    secondary_start: float
    secondary_stop: float
    secondary_step: float

    @property
    def primary_direction(self) -> float:
        return 1.0 if self.primary_step > 0 else -1.0

    @property
    def primary_point_count(self) -> int:
        ratio = abs((self.primary_stop - self.primary_start) / self.primary_step)
        return max(1, int(np.floor(ratio + 1e-9)) + 1)

    @property
    def secondary_unit(self) -> str:
        return _source_unit(self.secondary_source)

    @property
    def secondary_column_label(self) -> str:
        unit = self.secondary_unit
        suffix = f" ({unit})" if unit else ""
        return f"Outer sweep {self.secondary_source}{suffix}"


def parse_nested_dc_sweep(
    analysis_type: str, analysis_command: str
) -> Optional[NestedDCSweep]:
    """Return the two literal numeric sweeps in a nested ``.dc`` directive."""

    if str(analysis_type or "").strip().lower() != "dc":
        return None
    tokens = tokenize_spice_directive(analysis_command)
    if len(tokens) != 9 or tokens[0].lower() != ".dc":
        return None
    if not tokens[1].strip() or not tokens[5].strip():
        return None
    primary_range = _parse_dc_numeric_range(tokens, 2)
    secondary_range = _parse_dc_numeric_range(tokens, 6)
    if primary_range is None or secondary_range is None:
        return None
    primary_start, primary_stop, primary_step = primary_range
    secondary_start, secondary_stop, secondary_step = secondary_range
    return NestedDCSweep(
        primary_source=tokens[1],
        primary_start=primary_start,
        primary_stop=primary_stop,
        primary_step=primary_step,
        secondary_source=tokens[5],
        secondary_start=secondary_start,
        secondary_stop=secondary_stop,
        secondary_step=secondary_step,
    )


def nested_dc_reset_indexes(x_values: np.ndarray, sweep: NestedDCSweep) -> np.ndarray:
    """Return raw indexes that begin a new outer-sweep branch."""

    try:
        x_array = np.asarray(x_values, dtype=float)
    except (TypeError, ValueError, OverflowError):
        return np.empty(0, dtype=np.int64)
    if x_array.ndim != 1 or len(x_array) < 2:
        return np.empty(0, dtype=np.int64)
    finite_values = x_array[np.isfinite(x_array)]
    if len(finite_values) < 2:
        return np.empty(0, dtype=np.int64)
    scale = max(float(np.max(np.abs(finite_values))), 1.0)
    tolerance = np.finfo(float).eps * scale * 32.0
    primary_direction = sweep.primary_direction
    expected_points = sweep.primary_point_count
    resets = []
    previous_value: Optional[float] = None
    points_in_branch = 0
    for index, value in enumerate(x_array):
        if not np.isfinite(value):
            continue
        numeric_value = float(value)
        difference = (
            numeric_value - previous_value if previous_value is not None else 0.0
        )
        direction_reset = (
            previous_value is not None
            and difference * primary_direction < -tolerance
        )
        count_reset = points_in_branch >= expected_points
        if direction_reset or count_reset:
            resets.append(index)
            points_in_branch = 0
        previous_value = numeric_value
        points_in_branch += 1
    return np.asarray(resets, dtype=np.int64)


def insert_nested_dc_breaks(
    x_values: np.ndarray,
    y_values: np.ndarray,
    sweep: NestedDCSweep,
) -> Tuple[np.ndarray, np.ndarray]:
    """Insert NaN separators before every outer-sweep branch reset."""

    try:
        x_array = np.asarray(x_values, dtype=float)
        y_array = np.asarray(y_values, dtype=float)
    except (TypeError, ValueError, OverflowError):
        return np.empty(0, dtype=float), np.empty(0, dtype=float)
    if x_array.ndim != 1 or y_array.ndim != 1:
        return np.empty(0, dtype=float), np.empty(0, dtype=float)
    pair_count = min(len(x_array), len(y_array))
    x_array = x_array[:pair_count]
    y_array = y_array[:pair_count]
    reset_indexes = set(int(index) for index in nested_dc_reset_indexes(x_array, sweep))
    if not reset_indexes:
        return x_array.copy(), y_array.copy()
    x_out = []
    y_out = []
    for index, (x_value, y_value) in enumerate(zip(x_array, y_array)):
        if index in reset_indexes and (index == 0 or np.isfinite(x_array[index - 1])):
            x_out.append(np.nan)
            y_out.append(np.nan)
        x_out.append(float(x_value))
        y_out.append(float(y_value))
    return np.asarray(x_out, dtype=float), np.asarray(y_out, dtype=float)


def nested_dc_secondary_values(
    x_values: np.ndarray, sweep: NestedDCSweep
) -> np.ndarray:
    """Derive the outer source value for each flattened simulator row."""

    try:
        x_array = np.asarray(x_values, dtype=float)
    except (TypeError, ValueError, OverflowError):
        return np.empty(0, dtype=float)
    if x_array.ndim != 1:
        return np.empty(0, dtype=float)
    result = np.full(x_array.shape, np.nan, dtype=float)
    if len(x_array) == 0:
        return result
    resets = set(int(index) for index in nested_dc_reset_indexes(x_array, sweep))
    segment_index = 0
    tolerance = abs(sweep.secondary_step) * 1e-9 + np.finfo(float).eps
    for index in range(len(x_array)):
        if index in resets:
            segment_index += 1
        value = sweep.secondary_start + segment_index * sweep.secondary_step
        inside = (
            value <= sweep.secondary_stop + tolerance
            if sweep.secondary_step > 0
            else value >= sweep.secondary_stop - tolerance
        )
        if inside and np.isfinite(x_array[index]):
            result[index] = value
    return result


def _parse_dc_numeric_range(
    tokens: list[str],
    start_index: int,
) -> Optional[Tuple[float, float, float]]:
    values = [
        parse_spice_number(tokens[index])
        for index in range(start_index, start_index + 3)
    ]
    if any(value is None for value in values):
        return None
    start, stop, step = (float(value) for value in values)
    if step == 0 or (stop - start) * step < 0:
        return None
    return start, stop, step


def _source_unit(source_name: str) -> str:
    candidate = str(source_name or "").strip().upper()
    if candidate == "TEMP":
        return "°C"
    if candidate.startswith("V"):
        return "V"
    if candidate.startswith("I"):
        return "A"
    if candidate.startswith("R"):
        return "Ω"
    return ""


def normalize_signal_type_label(value: str) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in _VALID_SIGNAL_TYPES else SIGNAL_TYPE_OTHER


def strip_signal_component_suffix(signal_name: str) -> str:
    return split_virtual_complex_component_name(signal_name)[0]


def split_virtual_complex_component_name(signal_name: str) -> Tuple[str, str]:
    """Split a presentation-only complex component suffix from its base."""

    candidate = str(signal_name or "")
    for suffix in VIRTUAL_COMPLEX_COMPONENT_SUFFIXES:
        if candidate.endswith(suffix):
            return candidate[: -len(suffix)], suffix
    return candidate, ""


def infer_signal_type_from_name(signal_name: str) -> str:
    base_name = strip_signal_component_suffix(signal_name)
    device_parameter = parse_device_parameter_signal_name(base_name)
    if device_parameter is not None:
        return _signal_type_from_device_parameter(device_parameter[1])
    upper = base_name.upper()
    if upper.startswith("V(") and upper.endswith(")"):
        return SIGNAL_TYPE_VOLTAGE
    if upper.startswith("I(") and upper.endswith(")"):
        return SIGNAL_TYPE_CURRENT
    return SIGNAL_TYPE_OTHER


def parse_device_parameter_signal_name(
    signal_name: str,
) -> Optional[Tuple[str, str]]:
    """Return the device and parameter encoded by an ngspice ``@dev[param]`` vector."""

    match = _DEVICE_PARAMETER_SIGNAL_PATTERN.fullmatch(str(signal_name or "").strip())
    if match is None:
        return None
    device_name = match.group("device").strip()
    parameter_name = match.group("parameter").strip().lower()
    if not device_name or not parameter_name:
        return None
    return device_name, parameter_name


def resolve_device_parameter_unit(parameter_name: str) -> str:
    """Return a physical unit only for a device parameter with known semantics."""

    return _DEVICE_PARAMETER_UNIT_MAP.get(
        str(parameter_name or "").strip().lower(),
        "",
    )


def _signal_type_from_device_parameter(parameter_name: str) -> str:
    unit = resolve_device_parameter_unit(parameter_name)
    if unit == "V":
        return SIGNAL_TYPE_VOLTAGE
    if unit == "A":
        return SIGNAL_TYPE_CURRENT
    return SIGNAL_TYPE_OTHER


def resolve_signal_type(
    signal_name: str, signal_types: Optional[Dict[str, str]] = None
) -> str:
    device_parameter = parse_device_parameter_signal_name(signal_name)
    if device_parameter is not None:
        return _signal_type_from_device_parameter(device_parameter[1])
    if signal_types:
        if signal_name in signal_types:
            return normalize_signal_type_label(signal_types[signal_name])
        base_name = strip_signal_component_suffix(signal_name)
        if base_name in signal_types:
            return normalize_signal_type_label(signal_types[base_name])
        # Imported results are not required to preserve ngspice's original
        # case.  Type metadata remains authoritative across that harmless
        # spelling difference.
        casefolded_types = {
            str(name).casefold(): value for name, value in signal_types.items()
        }
        if signal_name.casefold() in casefolded_types:
            return normalize_signal_type_label(casefolded_types[signal_name.casefold()])
        if base_name.casefold() in casefolded_types:
            return normalize_signal_type_label(casefolded_types[base_name.casefold()])
    return infer_signal_type_from_name(signal_name)


def normalize_simulation_signal_name(name: str, vec_type: int = 0) -> str:
    raw_name = str(name or "").strip()
    lowered = raw_name.lower()

    # A device parameter is neither a node nor a branch.
    # ngspice still tags values such as @m1[vds] and @m1[id] with voltage and
    # current vector types, so syntax identity must win over that broad type.
    if parse_device_parameter_signal_name(raw_name) is not None:
        return raw_name

    if lowered.startswith("v(") and lowered.endswith(")"):
        return f"V({raw_name[2:-1]})"
    if lowered.startswith("i(") and lowered.endswith(")"):
        return f"I({raw_name[2:-1]})"

    branch_index = lowered.find("#branch")
    if branch_index >= 0:
        branch_device = raw_name[:branch_index].strip()
        if branch_device:
            return f"I({branch_device.upper()})"

    if vec_type == VECTOR_TYPE_VOLTAGE and not raw_name.upper().startswith(
        ("V(", "I(")
    ):
        return f"V({raw_name})"
    if vec_type == VECTOR_TYPE_CURRENT and not raw_name.upper().startswith(
        ("V(", "I(")
    ):
        return f"I({raw_name})"

    return raw_name


def resolve_vector_signal_type(
    name: str,
    vec_type: int,
    *,
    analysis_type: str = "",
    analysis_command: str = "",
) -> str:
    device_parameter = parse_device_parameter_signal_name(name)
    if device_parameter is not None:
        return _signal_type_from_device_parameter(device_parameter[1])

    normalized_name = normalize_simulation_signal_name(name, vec_type)

    if vec_type == VECTOR_TYPE_VOLTAGE:
        return SIGNAL_TYPE_VOLTAGE
    if vec_type == VECTOR_TYPE_CURRENT:
        return SIGNAL_TYPE_CURRENT

    normalized_analysis = str(analysis_type or "").strip().lower()
    if normalized_analysis == "noise" or str(
        analysis_command or ""
    ).strip().lower().startswith(".noise"):
        noise_type = _resolve_noise_signal_type(
            normalized_name, vec_type, analysis_command
        )
        if noise_type != SIGNAL_TYPE_OTHER:
            return noise_type

    return infer_signal_type_from_name(normalized_name)


def _resolve_noise_signal_type(
    signal_name: str, vec_type: int, analysis_command: str
) -> str:
    base_name = strip_signal_component_suffix(signal_name).strip().lower()
    try:
        directive = parse_noise_directive(analysis_command)
    except ValueError:
        return SIGNAL_TYPE_OTHER

    if base_name.startswith("onoise"):
        return SIGNAL_TYPE_VOLTAGE
    if base_name.startswith("inoise"):
        return directive.input_signal_type

    if vec_type in _NOISE_OUTPUT_VECTOR_TYPES:
        return SIGNAL_TYPE_VOLTAGE
    if vec_type in _NOISE_INPUT_VECTOR_TYPES:
        return directive.input_signal_type
    return SIGNAL_TYPE_OTHER


__all__ = [
    "NestedDCSweep",
    "SIGNAL_TYPE_CURRENT",
    "SIGNAL_TYPE_OTHER",
    "SIGNAL_TYPE_VOLTAGE",
    "VIRTUAL_COMPLEX_COMPONENT_SUFFIXES",
    "infer_signal_type_from_name",
    "normalize_signal_type_label",
    "normalize_simulation_signal_name",
    "insert_nested_dc_breaks",
    "nested_dc_reset_indexes",
    "nested_dc_secondary_values",
    "parse_device_parameter_signal_name",
    "parse_nested_dc_sweep",
    "resolve_signal_type",
    "resolve_device_parameter_unit",
    "resolve_vector_signal_type",
    "strip_signal_component_suffix",
    "split_virtual_complex_component_name",
]
