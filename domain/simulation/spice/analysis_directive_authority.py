from __future__ import annotations

from typing import Any, Dict, Optional

from domain.simulation.models.simulation_config import (
    ACAnalysisConfig,
    DCAnalysisConfig,
    NoiseConfig,
    TransientConfig,
)


SUPPORTED_ANALYSIS_TYPES = ("ac", "dc", "tran", "noise", "op")
_SUPPORTED_PREFIXES = tuple(f".{item}" for item in SUPPORTED_ANALYSIS_TYPES)


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
    if matched_prefix == ".noise" and len(pieces) >= 4:
        pieces[3] = pieces[3].lower()
    return " ".join(pieces)


__all__ = [
    "SUPPORTED_ANALYSIS_TYPES",
    "build_analysis_command",
    "detect_last_analysis_type_from_text",
    "extract_last_analysis_command",
    "normalize_analysis_directive",
    "replace_or_inject_analysis_command",
]
