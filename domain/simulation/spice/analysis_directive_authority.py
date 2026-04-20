from __future__ import annotations

import re
from typing import Any, Dict, Optional

from domain.simulation.models.simulation_config import (
    ACAnalysisConfig,
    DCAnalysisConfig,
    NoiseConfig,
    TransientConfig,
)


SUPPORTED_ANALYSIS_TYPES = ("ac", "dc", "tran", "noise", "op")
_SUPPORTED_PREFIXES = tuple(f".{item}" for item in SUPPORTED_ANALYSIS_TYPES)
_SPICE_NUMERIC_PATTERN = re.compile(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)([A-Za-z]+)?$")
_SPICE_SUFFIX_SCALES = {
    "t": 1e12,
    "g": 1e9,
    "meg": 1e6,
    "k": 1e3,
    "mil": 25.4e-6,
    "m": 1e-3,
    "u": 1e-6,
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15,
}
_SPICE_FORMAT_SCALES = (
    (1e12, "T"),
    (1e9, "G"),
    (1e6, "Meg"),
    (1e3, "k"),
    (1.0, ""),
    (1e-3, "m"),
    (1e-6, "u"),
    (1e-9, "n"),
    (1e-12, "p"),
    (1e-15, "f"),
)


def detect_last_analysis_type_from_text(netlist_text: str) -> str:
    last_type = ""
    for line in str(netlist_text or "").splitlines():
        normalized = normalize_analysis_directive(line)
        if not normalized:
            continue
        last_type = normalized.split()[0][1:]
    return last_type


def extract_last_analysis_command(netlist_text: str, analysis_type: str = "") -> str:
    requested_type = str(analysis_type or "").strip().lower()
    resolved_command = ""
    for line in str(netlist_text or "").splitlines():
        normalized = normalize_analysis_directive(line)
        if not normalized:
            continue
        current_type = normalized.split()[0][1:]
        if requested_type and current_type != requested_type:
            continue
        resolved_command = normalized
    return resolved_command


def build_analysis_command(analysis_type: str, analysis_config: Optional[Dict[str, Any]]) -> str:
    normalized_type = str(analysis_type or "").strip().lower()
    if normalized_type == "ac":
        config = ACAnalysisConfig()
        if analysis_config:
            config = ACAnalysisConfig(
                start_freq=analysis_config.get("start_freq", config.start_freq),
                stop_freq=analysis_config.get("stop_freq", config.stop_freq),
                points_per_decade=analysis_config.get("points_per_decade", config.points_per_decade),
                sweep_type=analysis_config.get("sweep_type", config.sweep_type),
            )
        return f".ac {str(config.sweep_type).lower()} {config.points_per_decade} {config.start_freq} {config.stop_freq}"

    if normalized_type == "dc":
        config = DCAnalysisConfig()
        if analysis_config:
            config = DCAnalysisConfig(
                source_name=analysis_config.get("source_name", config.source_name),
                start_value=analysis_config.get("start_value", config.start_value),
                stop_value=analysis_config.get("stop_value", config.stop_value),
                step=analysis_config.get("step", config.step),
            )
        if not config.source_name:
            return ""
        return f".dc {config.source_name} {config.start_value} {config.stop_value} {config.step}"

    if normalized_type == "tran":
        config = TransientConfig()
        if analysis_config:
            config = TransientConfig(
                step_time=analysis_config.get("step_time", config.step_time),
                end_time=analysis_config.get("end_time", config.end_time),
                start_time=analysis_config.get("start_time", config.start_time),
                max_step=analysis_config.get("max_step", config.max_step),
                use_initial_conditions=analysis_config.get("use_initial_conditions", config.use_initial_conditions),
            )
        command = f".tran {config.step_time} {config.end_time}"
        if config.start_time > 0 or config.max_step is not None:
            command += f" {config.start_time}"
        if config.max_step is not None:
            command += f" {config.max_step}"
        if config.use_initial_conditions:
            command += " uic"
        return command

    if normalized_type == "noise":
        config = NoiseConfig()
        if analysis_config:
            config = NoiseConfig(
                output_node=analysis_config.get("output_node", config.output_node),
                input_source=analysis_config.get("input_source", config.input_source),
                sweep_type=analysis_config.get("sweep_type", config.sweep_type),
                points_per_decade=analysis_config.get("points_per_decade", config.points_per_decade),
                start_freq=analysis_config.get("start_freq", config.start_freq),
                stop_freq=analysis_config.get("stop_freq", config.stop_freq),
            )
        if not config.output_node or not config.input_source:
            return ""
        return (
            f".noise v({config.output_node}) {config.input_source} "
            f"{str(config.sweep_type).lower()} {config.points_per_decade} {config.start_freq} {config.stop_freq}"
        )

    if normalized_type == "op":
        return ".op"

    return ""


def replace_or_inject_analysis_command(netlist_text: str, analysis_command: str) -> str:
    normalized_command = normalize_analysis_directive(analysis_command)
    if not normalized_command:
        return str(netlist_text or "")

    normalized_target_prefix = normalized_command.split()[0].lower()
    lines = str(netlist_text or "").splitlines()
    result_lines = []
    has_analysis = False
    has_end = False

    for line in lines:
        current_command = normalize_analysis_directive(line)
        if current_command and current_command.split()[0].lower() == normalized_target_prefix:
            result_lines.append(normalized_command)
            has_analysis = True
            continue
        if line.strip().lower() == ".end":
            has_end = True
            if not has_analysis:
                result_lines.append(normalized_command)
                has_analysis = True
            result_lines.append(line)
            continue
        result_lines.append(line)

    if not has_end:
        if not has_analysis:
            result_lines.append(normalized_command)
        result_lines.append(".end")

    return "\n".join(result_lines)


def normalize_analysis_directive(directive_text: str) -> Optional[str]:
    text = str(directive_text or "").strip()
    if not text:
        return None
    if text.startswith((";", "*")):
        return ""
    lowered = text.lower()
    matched_prefix = next(
        (
            prefix for prefix in _SUPPORTED_PREFIXES
            if lowered == prefix or (lowered.startswith(prefix) and len(lowered) > len(prefix) and lowered[len(prefix)] in (" ", "\t"))
        ),
        "",
    )
    if not matched_prefix:
        return None
    pieces = text.split()
    if not pieces:
        return ""
    pieces[0] = matched_prefix
    if matched_prefix == ".op":
        return ".op"
    if matched_prefix == ".ac" and len(pieces) >= 2:
        pieces[1] = pieces[1].lower()
    if matched_prefix == ".tran":
        return _normalize_transient_directive(pieces)
    if matched_prefix == ".noise" and len(pieces) >= 4:
        pieces[3] = pieces[3].lower()
    return " ".join(pieces)


def _normalize_transient_directive(pieces: list[str]) -> str:
    normalized_pieces = list(pieces)
    has_uic = False
    if normalized_pieces and normalized_pieces[-1].lower() == "uic":
        normalized_pieces = normalized_pieces[:-1]
        has_uic = True
    if len(normalized_pieces) == 2:
        stop_token = normalized_pieces[1]
        normalized_pieces = [".tran", _heuristic_transient_step_token(stop_token), stop_token]
    if has_uic:
        normalized_pieces.append("uic")
    return " ".join(normalized_pieces)


def _heuristic_transient_step_token(stop_token: str) -> str:
    stop_value = _parse_spice_numeric(stop_token)
    if stop_value is None or stop_value <= 0:
        return _format_spice_numeric(TransientConfig().step_time)
    step_value = stop_value / 1000.0
    if step_value <= 0:
        return _format_spice_numeric(TransientConfig().step_time)
    return _format_spice_numeric(step_value)


def _parse_spice_numeric(token: str) -> Optional[float]:
    match = _SPICE_NUMERIC_PATTERN.match(str(token or "").strip())
    if match is None:
        return None
    try:
        base_value = float(match.group(1))
    except ValueError:
        return None
    suffix = str(match.group(2) or "").strip().lower()
    if not suffix:
        return base_value
    if suffix.startswith("meg"):
        return base_value * _SPICE_SUFFIX_SCALES["meg"]
    if suffix.startswith("mil"):
        return base_value * _SPICE_SUFFIX_SCALES["mil"]
    scale = _SPICE_SUFFIX_SCALES.get(suffix[:1], 1.0)
    return base_value * scale


def _format_spice_numeric(value: float) -> str:
    absolute = abs(float(value))
    if absolute == 0:
        return "0"
    for scale, suffix in _SPICE_FORMAT_SCALES:
        scaled = value / scale
        if 1 <= abs(scaled) < 1000:
            return f"{scaled:.12g}{suffix}"
    return f"{value:.12g}"


__all__ = [
    "SUPPORTED_ANALYSIS_TYPES",
    "build_analysis_command",
    "detect_last_analysis_type_from_text",
    "extract_last_analysis_command",
    "normalize_analysis_directive",
    "replace_or_inject_analysis_command",
]
