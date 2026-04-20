from __future__ import annotations

from typing import Dict, Optional, Tuple

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
_COMPLEX_COMPONENT_SUFFIXES = ("_mag", "_phase", "_real", "_imag")
_NOISE_OUTPUT_VECTOR_TYPES = {
    VECTOR_TYPE_OUTPUT_N_DENS,
    VECTOR_TYPE_OUTPUT_NOISE,
}
_NOISE_INPUT_VECTOR_TYPES = {
    VECTOR_TYPE_INPUT_N_DENS,
    VECTOR_TYPE_INPUT_NOISE,
}


def normalize_signal_type_label(value: str) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in _VALID_SIGNAL_TYPES else SIGNAL_TYPE_OTHER


def strip_signal_component_suffix(signal_name: str) -> str:
    candidate = str(signal_name or "")
    for suffix in _COMPLEX_COMPONENT_SUFFIXES:
        if candidate.endswith(suffix):
            return candidate[:-len(suffix)]
    return candidate


def infer_signal_type_from_name(signal_name: str) -> str:
    base_name = strip_signal_component_suffix(signal_name)
    upper = base_name.upper()
    if upper.startswith("V(") and upper.endswith(")"):
        return SIGNAL_TYPE_VOLTAGE
    if upper.startswith("I(") and upper.endswith(")"):
        return SIGNAL_TYPE_CURRENT
    return SIGNAL_TYPE_OTHER


def resolve_signal_type(signal_name: str, signal_types: Optional[Dict[str, str]] = None) -> str:
    if signal_types:
        if signal_name in signal_types:
            return normalize_signal_type_label(signal_types[signal_name])
        base_name = strip_signal_component_suffix(signal_name)
        if base_name in signal_types:
            return normalize_signal_type_label(signal_types[base_name])
    return infer_signal_type_from_name(signal_name)


def normalize_simulation_signal_name(name: str, vec_type: int = 0) -> str:
    raw_name = str(name or "").strip()
    lowered = raw_name.lower()

    if lowered.startswith("v(") and lowered.endswith(")"):
        return f"V({raw_name[2:-1]})"
    if lowered.startswith("i(") and lowered.endswith(")"):
        return f"I({raw_name[2:-1]})"

    branch_index = lowered.find("#branch")
    if branch_index >= 0:
        branch_device = raw_name[:branch_index].strip()
        if branch_device:
            return f"I({branch_device.upper()})"

    if vec_type == VECTOR_TYPE_VOLTAGE and not raw_name.upper().startswith(("V(", "I(")):
        return f"V({raw_name})"
    if vec_type == VECTOR_TYPE_CURRENT and not raw_name.upper().startswith(("V(", "I(")):
        return f"I({raw_name})"

    return raw_name


def resolve_vector_signal_type(
    name: str,
    vec_type: int,
    *,
    analysis_type: str = "",
    analysis_command: str = "",
) -> str:
    normalized_name = normalize_simulation_signal_name(name, vec_type)

    if vec_type == VECTOR_TYPE_VOLTAGE:
        return SIGNAL_TYPE_VOLTAGE
    if vec_type == VECTOR_TYPE_CURRENT:
        return SIGNAL_TYPE_CURRENT

    normalized_analysis = str(analysis_type or "").strip().lower()
    if normalized_analysis == "noise" or str(analysis_command or "").strip().lower().startswith(".noise"):
        noise_type = _resolve_noise_signal_type(normalized_name, vec_type, analysis_command)
        if noise_type != SIGNAL_TYPE_OTHER:
            return noise_type

    return infer_signal_type_from_name(normalized_name)


def _resolve_noise_signal_type(signal_name: str, vec_type: int, analysis_command: str) -> str:
    base_name = strip_signal_component_suffix(signal_name).strip().lower()
    output_target, input_source = _extract_noise_operands(analysis_command)

    if base_name.startswith("onoise"):
        return _classify_noise_output_target(output_target)
    if base_name.startswith("inoise"):
        return _classify_noise_input_source(input_source)

    if vec_type in _NOISE_OUTPUT_VECTOR_TYPES:
        return _classify_noise_output_target(output_target)
    if vec_type in _NOISE_INPUT_VECTOR_TYPES:
        return _classify_noise_input_source(input_source)
    return SIGNAL_TYPE_OTHER


def _extract_noise_operands(analysis_command: str) -> Tuple[str, str]:
    tokens = str(analysis_command or "").split()
    if not tokens or tokens[0].lower() != ".noise":
        return "", ""
    output_target = tokens[1] if len(tokens) > 1 else ""
    input_source = tokens[2] if len(tokens) > 2 else ""
    return output_target, input_source


def _classify_noise_output_target(output_target: str) -> str:
    candidate = str(output_target or "").strip().upper()
    if candidate.startswith("V(") and candidate.endswith(")"):
        return SIGNAL_TYPE_VOLTAGE
    if candidate.startswith("I(") and candidate.endswith(")"):
        return SIGNAL_TYPE_CURRENT
    return SIGNAL_TYPE_OTHER


def _classify_noise_input_source(input_source: str) -> str:
    candidate = str(input_source or "").strip().upper()
    if candidate.startswith("V"):
        return SIGNAL_TYPE_VOLTAGE
    if candidate.startswith("I"):
        return SIGNAL_TYPE_CURRENT
    return SIGNAL_TYPE_OTHER


__all__ = [
    "SIGNAL_TYPE_CURRENT",
    "SIGNAL_TYPE_OTHER",
    "SIGNAL_TYPE_VOLTAGE",
    "infer_signal_type_from_name",
    "normalize_signal_type_label",
    "normalize_simulation_signal_name",
    "resolve_signal_type",
    "resolve_vector_signal_type",
    "strip_signal_component_suffix",
]
