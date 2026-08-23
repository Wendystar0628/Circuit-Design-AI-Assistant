# SimulationResult - Standardized Simulation Result Data Class
"""
仿真结果数据类

职责：
- 定义标准化的仿真结果数据结构
- 提供仿真数据的序列化和反序列化
- 支持仿真结果的查询和验证

设计原则：
- 使用 dataclass 确保类型安全
- 提供 numpy 数组的序列化支持
- 与 SimulationError 数据类集成

使用示例：
    # 创建仿真结果
    result = SimulationResult(
        executor="spice",
        file_path="amplifier.cir",
        analysis_type="ac",
        success=True,
        source_digest="0" * 64,
        data=SimulationData(
            frequency=np.array([1e3, 50.5e3, 100e3]),
            signals={"V(out)": np.array([0.1, 1.0, 10.0], dtype=complex)},
            signal_types={"V(out)": "voltage"},
        ),
        analysis_command=".ac lin 3 1k 100k",
        measurements=[
            MeasureResult(
                name="gain",
                value=20.0,
                statement=".measure ac gain FIND VDB(out) AT=1k",
            ),
            MeasureResult(
                name="bandwidth",
                value=1e5,
                statement=".measure ac bandwidth WHEN VDB(out)=-3 FALL=1",
            ),
        ],
        timestamp=datetime.now(timezone.utc).isoformat(),
        duration_seconds=2.5,
        version=1
    )
    
    # 序列化
    data_dict = result.to_dict()
    
    # 反序列化
    loaded_result = SimulationResult.from_dict(data_dict)
    
    # 查询信号
    output_signal = result.get_signal("V(out)")
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from numbers import Real
from pathlib import PurePosixPath
from typing import Any, Dict, Optional

import numpy as np

from domain.simulation.measure.measure_authority import parse_measure_statement
from domain.simulation.measure.measure_result import MeasureResult, MeasureStatus
from domain.simulation.models.simulation_error import SimulationError
from domain.simulation.spice.analysis_directive import validate_analysis_command
from domain.simulation.spice.directive_tokenizer import tokenize_spice_directive
from domain.simulation.spice.noise_directive import parse_noise_directive
from domain.simulation.spice.numeric import parse_spice_number


RESULT_SCHEMA_VERSION = 3
"""Version of the JSON document written to ``result.json``.

Persisted results must declare this version explicitly. Historical repository
fixtures are migrated with the code change that introduces a schema revision;
the runtime does not carry an open-ended compatibility parser.
"""


X_AXIS_KIND_NONE = "none"
X_AXIS_KIND_TIME = "time"
X_AXIS_KIND_FREQUENCY = "frequency"
X_AXIS_KIND_SWEEP = "sweep"

X_AXIS_SCALE_NONE = "none"
X_AXIS_SCALE_LINEAR = "linear"
X_AXIS_SCALE_LOG = "log"

_SOURCE_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MEASURE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MEASUREMENT_FIELDS = frozenset(
    {
        "name",
        "value",
        "status",
        "statement",
        "raw_output",
        "error_message",
    }
)
_SIMULATION_DATA_FIELDS = frozenset(
    {
        "frequency",
        "time",
        "sweep",
        "signals",
        "signal_types",
        "noise_totals",
    }
)
_NOISE_TOTAL_FIELDS = frozenset({"output_rms", "input_referred_rms"})
_SIMULATION_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "executor",
        "file_path",
        "analysis_type",
        "success",
        "source_digest",
        "data",
        "measurements",
        "error",
        "raw_output",
        "timestamp",
        "duration_seconds",
        "version",
        "session_id",
        "analysis_command",
    }
)
_SUCCESS_ANALYSIS_TYPES = frozenset({"ac", "dc", "tran", "noise", "op"})


def _require_exact_fields(
    payload: Dict[str, Any],
    expected_fields: frozenset[str],
    *,
    object_name: str,
) -> None:
    actual_fields = set(payload)
    if actual_fields == expected_fields:
        return
    missing = sorted(expected_fields - actual_fields)
    unknown = sorted(actual_fields - expected_fields)
    details = []
    if missing:
        details.append(f"missing={missing!r}")
    if unknown:
        details.append(f"unknown={unknown!r}")
    raise ValueError(
        f"{object_name} fields must exactly match schema"
        + (f" ({', '.join(details)})" if details else "")
    )


def _validate_source_digest(
    value: Any,
    *,
    success: bool,
) -> Optional[str]:
    if value is None:
        if success:
            raise ValueError(
                "Successful simulation result requires source_digest"
            )
        return None
    if not isinstance(value, str) or not _SOURCE_DIGEST_PATTERN.fullmatch(value):
        raise ValueError(
            "Simulation result 'source_digest' must be a lowercase SHA-256 "
            "hex digest or null for a failed result"
        )
    return value


def _validate_result_identity(
    *,
    executor: Any,
    analysis_type: Any,
    success: Any,
) -> None:
    if type(success) is not bool:
        raise ValueError("Simulation result 'success' must be a boolean")
    allowed_executors = {"spice"} if success else {"spice", "unknown"}
    if executor not in allowed_executors:
        raise ValueError(
            "Simulation result 'executor' must be 'spice'"
            + (" or 'unknown' for a failed result" if not success else "")
        )
    allowed_analyses = (
        _SUCCESS_ANALYSIS_TYPES
        if success
        else _SUCCESS_ANALYSIS_TYPES | {"unknown"}
    )
    if analysis_type not in allowed_analyses:
        raise ValueError(
            "Simulation result 'analysis_type' must be an exact lowercase "
            f"analysis name, got {analysis_type!r}"
        )


def _validate_duration_seconds(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(
            "Simulation result 'duration_seconds' must be a JSON number"
        )
    duration = float(value)
    if not np.isfinite(duration) or duration < 0:
        raise ValueError(
            "Simulation result 'duration_seconds' must be finite and non-negative"
        )
    return duration


def _strict_measurement_payload(
    item: Any,
    *,
    index: int,
    analysis_type: str,
) -> Dict[str, Any]:
    if isinstance(item, MeasureResult):
        payload: Dict[str, Any] = {
            "name": item.name,
            "value": item.value,
            "status": item.status.value
            if isinstance(item.status, MeasureStatus)
            else item.status,
            "statement": item.statement,
            "raw_output": item.raw_output,
            "error_message": item.error_message,
        }
    elif isinstance(item, dict):
        item_fields = set(item)
        if item_fields != _MEASUREMENT_FIELDS:
            missing = sorted(_MEASUREMENT_FIELDS - item_fields)
            unknown = sorted(item_fields - _MEASUREMENT_FIELDS)
            details = []
            if missing:
                details.append(f"missing={missing!r}")
            if unknown:
                details.append(f"unknown={unknown!r}")
            raise ValueError(
                f"Simulation measurement[{index}] fields must match schema"
                + (f" ({', '.join(details)})" if details else "")
            )
        payload = dict(item)
    else:
        raise ValueError(
            f"Simulation measurement[{index}] must be a MeasureResult or object"
        )

    name = payload.get("name")
    if not isinstance(name, str) or not _MEASURE_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            f"Simulation measurement[{index}] name must be a SPICE identifier"
        )

    parsed_statement = parse_measure_statement(payload.get("statement"))
    if parsed_statement is None:
        raise ValueError(
            f"Simulation measurement[{index}] statement must be one complete "
            ".measure directive"
        )
    if parsed_statement.analysis_type != analysis_type:
        raise ValueError(
            f"Simulation measurement[{index}] statement analysis must match "
            f"result analysis_type {analysis_type!r}"
        )
    if parsed_statement.name.casefold() != name.casefold():
        raise ValueError(
            f"Simulation measurement[{index}] statement name must match "
            f"payload name {name!r}"
        )

    for field_name in _MEASUREMENT_FIELDS - {"name", "value", "status"}:
        if not isinstance(payload.get(field_name), str):
            raise ValueError(
                f"Simulation measurement[{index}] {field_name!r} must be a string"
            )

    status_raw = payload.get("status")
    if not isinstance(status_raw, str):
        raise ValueError(
            f"Simulation measurement[{index}] status must be a string enum"
        )
    try:
        status = MeasureStatus(status_raw)
    except ValueError as exc:
        raise ValueError(
            f"Simulation measurement[{index}] has unknown status {status_raw!r}"
        ) from exc

    value = payload.get("value")
    if status is MeasureStatus.OK:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(
                f"Simulation measurement[{index}] OK value must be numeric"
            )
        numeric_value = float(value)
        if not np.isfinite(numeric_value):
            raise ValueError(
                f"Simulation measurement[{index}] OK value must be finite"
            )
        payload["value"] = numeric_value
    else:
        if value is not None:
            raise ValueError(
                f"Simulation measurement[{index}] non-OK value must be null"
            )
        if not payload["error_message"].strip():
            raise ValueError(
                f"Simulation measurement[{index}] non-OK result requires error_message"
            )

    payload["status"] = status.value
    return payload


def _serialize_measurements_strict(
    measurements: Optional[list[Any]],
    *,
    analysis_type: str,
) -> Optional[list[Dict[str, Any]]]:
    if measurements is None:
        return None
    if not isinstance(measurements, list):
        raise ValueError("Simulation result 'measurements' must be a list or null")
    if not measurements:
        return None
    if analysis_type not in {"ac", "dc", "tran"}:
        raise ValueError(
            f"{analysis_type.upper()} simulation results must not contain "
            "top-level .measure outcomes"
        )
    payloads: list[Dict[str, Any]] = []
    names: set[str] = set()
    for index, item in enumerate(measurements):
        payload = _strict_measurement_payload(
            item,
            index=index,
            analysis_type=analysis_type,
        )
        name_key = payload["name"].casefold()
        if name_key in names:
            raise ValueError(
                f"Simulation measurements contain duplicate name {payload['name']!r}"
            )
        names.add(name_key)
        payloads.append(payload)
    return payloads


def _deserialize_measurements_strict(
    measurements: Any,
    *,
    analysis_type: str,
) -> Optional[list[MeasureResult]]:
    if measurements == []:
        raise ValueError(
            "Simulation result 'measurements' must be null or a non-empty list"
        )
    payloads = _serialize_measurements_strict(
        measurements,
        analysis_type=analysis_type,
    )
    if payloads is None:
        return None
    return [
        MeasureResult(
            name=payload["name"],
            value=payload["value"],
            status=MeasureStatus(payload["status"]),
            statement=payload["statement"],
            raw_output=payload["raw_output"],
            error_message=payload["error_message"],
        )
        for payload in payloads
    ]


def _analysis_x_axis_kind(analysis_type: str) -> str:
    return {
        "tran": X_AXIS_KIND_TIME,
        "ac": X_AXIS_KIND_FREQUENCY,
        "noise": X_AXIS_KIND_FREQUENCY,
        "dc": X_AXIS_KIND_SWEEP,
        "op": X_AXIS_KIND_NONE,
    }.get(str(analysis_type or "").strip().lower(), X_AXIS_KIND_NONE)


def _infer_x_axis_label(kind: str, analysis_command: str) -> str:
    if kind == X_AXIS_KIND_TIME:
        return "Time (s)"
    if kind == X_AXIS_KIND_FREQUENCY:
        return "Frequency (Hz)"
    if kind == X_AXIS_KIND_SWEEP:
        tokens = _split_analysis_command(analysis_command)
        if len(tokens) > 1 and tokens[0].lower() == ".dc":
            source_name = tokens[1].strip()
            if source_name:
                source_kind = source_name.upper()
                if source_kind == "TEMP":
                    unit = "°C"
                else:
                    source_prefix = source_kind[:1]
                    unit = {
                        "V": "V",
                        "I": "A",
                        "R": "Ω",
                    }.get(source_prefix, "")
                return f"{source_name} ({unit})" if unit else source_name
        return "Sweep"
    return "X"


def _get_x_axis_array(data: Optional["SimulationData"], kind: str) -> Optional[np.ndarray]:
    if data is None:
        return None
    if kind == X_AXIS_KIND_TIME:
        return data.time
    if kind == X_AXIS_KIND_FREQUENCY:
        return data.frequency
    if kind == X_AXIS_KIND_SWEEP:
        return data.sweep
    return None


def _infer_actual_x_range(
    data: Optional["SimulationData"],
    kind: str,
) -> Optional[tuple[float, float]]:
    axis_data = _get_x_axis_array(data, kind)
    if axis_data is None or len(axis_data) == 0:
        return None
    try:
        numeric = np.asarray(axis_data, dtype=float)
    except (TypeError, ValueError):
        return None
    if numeric.ndim != 1 or numeric.size == 0 or not np.all(np.isfinite(numeric)):
        return None
    return (float(np.min(numeric)), float(np.max(numeric)))


def _json_safe(value: Any) -> Any:
    """Return a strict-JSON representation of numpy/scientific values.

    Python's ``json`` module otherwise writes NaN/Infinity tokens which are
    not valid JSON and are rejected by browsers and strict parsers. Schema-v3
    native numeric results must be finite, so non-finite values fail instead
    of being rewritten as ambiguous ``null`` samples.
    """
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, float):
        if not np.isfinite(value):
            raise ValueError("Simulation result contains a non-finite number")
        return value
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _validate_json_numeric_array(
    values: Any,
    *,
    field_name: str,
) -> None:
    if not isinstance(values, list):
        raise ValueError(f"{field_name} must be a JSON array")
    for value in values:
        if value is None:
            raise ValueError(f"{field_name} must not contain null gaps")
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"{field_name} must contain only numeric values")
        if not np.isfinite(float(value)):
            raise ValueError(
                f"{field_name} must not contain NaN or Infinity tokens"
            )


def _default_x_axis_scale(
    analysis_type: str,
    kind: str,
    analysis_command: str = "",
) -> str:
    if kind == X_AXIS_KIND_NONE:
        return X_AXIS_SCALE_NONE
    analysis = (analysis_type or "").lower()
    if analysis in {"ac", "noise"} and kind == X_AXIS_KIND_FREQUENCY:
        if analysis == "noise":
            try:
                sweep_mode = parse_noise_directive(
                    analysis_command
                ).sweep_mode
            except ValueError:
                sweep_mode = ""
        else:
            tokens = _split_analysis_command(analysis_command)
            sweep_mode = tokens[1].lower() if len(tokens) > 1 else ""
        return X_AXIS_SCALE_LINEAR if sweep_mode == "lin" else X_AXIS_SCALE_LOG
    return X_AXIS_SCALE_LINEAR


def _validate_axis_matches_analysis_command(
    *,
    analysis_type: str,
    analysis_command: str,
    data: Optional["SimulationData"],
) -> None:
    analysis = str(analysis_type or "").strip().lower()
    axis_kind = _analysis_x_axis_kind(analysis)
    axis = _get_x_axis_array(data, axis_kind)
    if axis is None or len(axis) == 0 or analysis == "op":
        return
    numeric_axis = np.asarray(axis, dtype=float)
    tokens = _split_analysis_command(analysis_command)
    if analysis == "dc":
        _validate_dc_axis_grid(numeric_axis, tokens)
        return
    if analysis in {"ac", "noise"}:
        _validate_frequency_axis_grid(analysis, numeric_axis, tokens)
        return
    start_token, stop_token = _analysis_endpoint_tokens(analysis, tokens)
    expected_start = (
        parse_spice_number(start_token) if start_token is not None else None
    )
    expected_stop = (
        parse_spice_number(stop_token) if stop_token is not None else None
    )
    actual_start = float(numeric_axis[0])
    actual_stop = float(numeric_axis[-1])
    tran_has_uic = analysis == "tran" and tokens[-1].lower() == "uic"
    tran_numeric_tokens = tokens[:-1] if tran_has_uic else tokens
    tran_has_explicit_start = (
        analysis == "tran" and len(tran_numeric_tokens) >= 4
    )
    endpoint_scale = (
        parse_spice_number(tokens[1])
        if analysis == "tran" and len(tokens) > 1
        else None
    )
    start_matches = (
        expected_start is None
        or _numeric_endpoints_match(
            actual_start,
            expected_start,
            scale=endpoint_scale,
        )
    )
    if (
        analysis == "tran"
        and expected_start is not None
        and (tran_has_explicit_start or tran_has_uic)
    ):
        tstep = parse_spice_number(tokens[1])
        lower_matches = actual_start >= expected_start or _numeric_endpoints_match(
            actual_start,
            expected_start,
            scale=tstep,
        )
        start_matches = lower_matches and (
            tstep is None
            or actual_start <= expected_start + tstep
            or _numeric_endpoints_match(
                actual_start,
                expected_start + tstep,
                scale=tstep,
            )
        )
    if not start_matches:
        raise ValueError(
            f"{analysis.upper()} axis start {actual_start!r} does not match "
            f"analysis_command start {expected_start!r}"
        )
    if expected_stop is not None and not _numeric_endpoints_match(
        actual_stop,
        expected_stop,
        scale=endpoint_scale,
    ):
        raise ValueError(
            f"{analysis.upper()} axis stop {actual_stop!r} does not match "
            f"analysis_command stop {expected_stop!r}"
        )
def _analysis_endpoint_tokens(
    analysis: str,
    tokens: list[str],
) -> tuple[Optional[str], Optional[str]]:
    if analysis == "tran" and len(tokens) >= 3:
        extra_tokens = [token for token in tokens[3:] if token.lower() != "uic"]
        return (extra_tokens[0] if extra_tokens else "0", tokens[2])
    if analysis == "dc" and len(tokens) >= 4:
        return tokens[2], tokens[3]
    if analysis == "ac" and len(tokens) >= 5:
        return tokens[3], tokens[4]
    if analysis == "noise" and len(tokens) >= 7:
        return tokens[5], tokens[6]
    return None, None


def _validate_dc_axis_grid(axis: np.ndarray, tokens: list[str]) -> None:
    if len(tokens) not in {5, 9}:
        return
    primary = _numeric_dc_sweep_spec(tokens, start_index=1)
    secondary = (
        _numeric_dc_sweep_spec(tokens, start_index=5)
        if len(tokens) == 9
        else None
    )

    if primary is not None:
        primary_start, primary_step, primary_count = primary
        if secondary is not None:
            expected_count = primary_count * secondary[2]
            if len(axis) != expected_count:
                raise ValueError(
                    "Nested DC axis length must equal the complete inner and "
                    "outer sweep grid"
                )
        elif len(tokens) == 5:
            if len(axis) != primary_count:
                raise ValueError(
                    "DC axis length must equal the complete sweep grid"
                )
        elif len(axis) % primary_count != 0:
            raise ValueError(
                "Nested DC axis must contain complete primary sweep branches"
            )

        expected = primary_start + (
            np.arange(len(axis), dtype=float) % primary_count
        ) * primary_step
        _require_axis_values_match(
            axis,
            expected,
            message="DC axis does not follow the complete primary sweep grid",
        )
        return

    if secondary is None:
        return

    outer_count = secondary[2]
    if len(axis) % outer_count != 0 or len(axis) == 0:
        raise ValueError(
            "Nested DC axis length must contain one complete branch per "
            "outer sweep point"
        )
    branch_length = len(axis) // outer_count
    first_branch = axis[:branch_length]
    for branch_index in range(1, outer_count):
        branch = axis[
            branch_index * branch_length : (branch_index + 1) * branch_length
        ]
        _require_axis_values_match(
            branch,
            first_branch,
            message=(
                "Nested DC primary sweep branches must repeat for every "
                "outer sweep point"
            ),
        )


def _numeric_dc_sweep_spec(
    tokens: list[str],
    *,
    start_index: int,
) -> Optional[tuple[float, float, int]]:
    start = parse_spice_number(tokens[start_index + 1])
    stop = parse_spice_number(tokens[start_index + 2])
    step = parse_spice_number(tokens[start_index + 3])
    if start is None or stop is None or step is None:
        return None
    if not all(np.isfinite(value) for value in (start, stop, step)):
        raise ValueError("DC sweep literals must be finite")
    if step == 0 or (stop - start) * step < 0:
        raise ValueError("DC sweep step must reach the stop value")

    interval_ratio = (stop - start) / step
    if not np.isfinite(interval_ratio):
        raise ValueError("DC sweep grid is too large")
    rounding_tolerance = max(abs(interval_ratio), 1.0) * 1e-12
    interval_count = int(np.floor(interval_ratio + rounding_tolerance))
    return start, step, interval_count + 1


def _validate_frequency_axis_grid(
    analysis: str,
    axis: np.ndarray,
    tokens: list[str],
) -> None:
    if analysis == "noise":
        directive = parse_noise_directive(" ".join(tokens))
        mode = directive.sweep_mode
        start = parse_spice_number(directive.start_frequency)
        stop = parse_spice_number(directive.stop_frequency)
        points_value = parse_spice_number(directive.points)
    else:
        if len(tokens) != 5:
            return
        mode = tokens[1].lower()
        points_value = parse_spice_number(tokens[2])
        start = parse_spice_number(tokens[3])
        stop = parse_spice_number(tokens[4])
    if start is not None and not _numeric_endpoints_match(float(axis[0]), start):
        raise ValueError(
            f"{analysis.upper()} axis start {float(axis[0])!r} does not match "
            f"analysis_command start {start!r}"
        )
    if start is None or stop is None or points_value is None:
        return
    if not all(np.isfinite(value) for value in (start, stop, points_value)):
        raise ValueError(f"{analysis.upper()} sweep literals must be finite")

    points = int(points_value)
    if mode == "lin":
        expected_count = points
        if len(axis) != expected_count:
            raise ValueError(
                f"{analysis.upper()} LIN axis length must equal point_count"
            )
        expected = (
            np.asarray([start], dtype=float)
            if points == 1
            else np.linspace(start, stop, points, dtype=float)
        )
    else:
        logarithmic_span = (
            np.log10(stop / start)
            if mode == "dec"
            else np.log2(stop / start)
        )
        raw_interval_count = points * logarithmic_span
        rounding_tolerance = max(abs(raw_interval_count), 1.0) * 1e-12
        interval_count = int(
            np.floor(raw_interval_count + rounding_tolerance)
        )
        if analysis == "ac" and mode == "dec" and interval_count < 1:
            raise ValueError(
                "AC DEC sweep must span at least one generated interval"
            )
        expected_count = interval_count + 1
        if len(axis) != expected_count:
            raise ValueError(
                f"{analysis.upper()} {mode.upper()} axis length must equal "
                "the complete generated sweep grid"
            )
        if analysis == "ac" and mode == "dec":
            expected = np.geomspace(start, stop, expected_count, dtype=float)
        else:
            base = 10.0 if mode == "dec" else 2.0
            expected = start * np.power(
                base,
                np.arange(expected_count, dtype=float) / points,
            )

    _require_axis_values_match(
        axis,
        expected,
        message=(
            f"{analysis.upper()} axis does not match the complete "
            f"{mode.upper()} sweep grid"
        ),
    )


def _require_axis_values_match(
    actual: np.ndarray,
    expected: np.ndarray,
    *,
    message: str,
) -> None:
    if len(actual) != len(expected):
        raise ValueError(message)
    for index, (actual_value, expected_value) in enumerate(
        zip(actual, expected)
    ):
        neighbouring_steps = []
        if index > 0:
            neighbouring_steps.append(
                abs(float(expected[index]) - float(expected[index - 1]))
            )
        if index + 1 < len(expected):
            neighbouring_steps.append(
                abs(float(expected[index + 1]) - float(expected[index]))
            )
        comparison_scale = max(
            [abs(float(expected_value)), *neighbouring_steps],
            default=0.0,
        )
        if not _numeric_endpoints_match(
            float(actual_value),
            float(expected_value),
            scale=comparison_scale,
        ):
            raise ValueError(message)


def _numeric_endpoints_match(
    actual: float,
    expected: float,
    *,
    scale: Optional[float] = None,
) -> bool:
    reference_scale = max(
        abs(float(expected)),
        abs(float(scale)) if scale is not None else 0.0,
    )
    ulp = abs(float(np.spacing(reference_scale)))
    absolute_tolerance = max(reference_scale * 1e-12, ulp * 32.0)
    return bool(
        np.isclose(
            actual,
            expected,
            rtol=1e-8,
            atol=absolute_tolerance,
        )
    )


def _split_analysis_command(command: str) -> list[str]:
    return list(tokenize_spice_directive(command))


def _infer_analysis_parameters(analysis_type: str, analysis_command: str) -> Dict[str, Any]:
    analysis = (analysis_type or "").lower()
    tokens = _split_analysis_command(analysis_command)
    if not analysis or not tokens or tokens[0].lower() != f".{analysis}":
        return {}

    if analysis == "ac":
        sweep_type = tokens[1] if len(tokens) > 1 else ""
        parameters = {
            "sweep_type": sweep_type,
            "start_frequency": tokens[3] if len(tokens) > 3 else "",
            "stop_frequency": tokens[4] if len(tokens) > 4 else "",
        }
        parameters[_sweep_point_parameter_name(sweep_type)] = (
            tokens[2] if len(tokens) > 2 else ""
        )
        return parameters

    if analysis == "dc":
        parameters = {
            "source_name": tokens[1] if len(tokens) > 1 else "",
            "start_value": tokens[2] if len(tokens) > 2 else "",
            "stop_value": tokens[3] if len(tokens) > 3 else "",
            "step": tokens[4] if len(tokens) > 4 else "",
        }
        if len(tokens) >= 9:
            parameters.update(
                {
                    "second_source_name": tokens[5],
                    "second_start_value": tokens[6],
                    "second_stop_value": tokens[7],
                    "second_step": tokens[8],
                }
            )
        return parameters

    if analysis == "tran":
        extra_tokens = [token for token in tokens[3:] if token.lower() != "uic"]
        parameters = {
            "step_time": tokens[1] if len(tokens) > 1 else "",
            "stop_time": tokens[2] if len(tokens) > 2 else "",
            "start_time": extra_tokens[0] if len(extra_tokens) > 0 else "",
            "max_step": extra_tokens[1] if len(extra_tokens) > 1 else "",
        }
        if any(token.lower() == "uic" for token in tokens[3:]):
            parameters["use_initial_conditions"] = "uic"
        return parameters

    if analysis == "noise":
        try:
            directive = parse_noise_directive(analysis_command)
        except ValueError:
            return {}
        sweep_type = directive.sweep_mode
        parameters = {
            "output_node": directive.output_expression,
            "input_source": directive.input_source,
            "sweep_type": sweep_type,
            "start_frequency": directive.start_frequency,
            "stop_frequency": directive.stop_frequency,
        }
        parameters[_sweep_point_parameter_name(sweep_type)] = (
            directive.points
        )
        return parameters

    return {}


def _sweep_point_parameter_name(sweep_type: str) -> str:
    normalized = str(sweep_type or "").strip().lower()
    if normalized == "lin":
        return "point_count"
    if normalized == "oct":
        return "points_per_octave"
    return "points_per_decade"


def _derive_analysis_info(
    *,
    analysis_type: str,
    analysis_command: str,
    x_axis_kind: str,
    x_axis_label: str,
    x_axis_scale: str,
    requested_x_range: Optional[tuple[float, float]],
    actual_x_range: Optional[tuple[float, float]],
) -> Dict[str, Any]:
    resolved_analysis_type = str(analysis_type or "").lower()
    resolved_analysis_command = str(analysis_command or "")
    return {
        "analysis_type": resolved_analysis_type,
        "analysis_command": resolved_analysis_command,
        "x_axis_kind": str(x_axis_kind or ""),
        "x_axis_label": str(x_axis_label or ""),
        "x_axis_scale": str(x_axis_scale or ""),
        "requested_x_range": requested_x_range,
        "actual_x_range": actual_x_range,
        "parameters": _infer_analysis_parameters(
            resolved_analysis_type,
            resolved_analysis_command,
        ),
    }


def _infer_requested_x_range(
    analysis_type: str,
    analysis_command: str,
) -> Optional[tuple[float, float]]:
    analysis = str(analysis_type or "").strip().lower()
    tokens = _split_analysis_command(analysis_command)
    if not tokens or tokens[0].lower() != f".{analysis}":
        return None

    start_token: Optional[str]
    stop_token: Optional[str]
    if analysis == "tran":
        extra_tokens = [token for token in tokens[3:] if token.lower() != "uic"]
        start_token = extra_tokens[0] if extra_tokens else "0"
        stop_token = tokens[2] if len(tokens) > 2 else None
    elif analysis == "dc":
        start_token = tokens[2] if len(tokens) > 2 else None
        stop_token = tokens[3] if len(tokens) > 3 else None
    elif analysis == "ac":
        start_token = tokens[3] if len(tokens) > 3 else None
        stop_token = tokens[4] if len(tokens) > 4 else None
    elif analysis == "noise":
        try:
            directive = parse_noise_directive(analysis_command)
        except ValueError:
            return None
        start_token = directive.start_frequency
        stop_token = directive.stop_frequency
    else:
        return None

    if start_token is None or stop_token is None:
        return None
    start = parse_spice_number(start_token)
    stop = parse_spice_number(stop_token)
    if start is None or stop is None:
        return None
    return (start, stop)


# ============================================================
# SimulationData - 仿真数据容器
# ============================================================

@dataclass(frozen=True)
class NoiseTotals:
    """Integrated RMS noise scalars emitted by ngspice's totals plot."""

    output_rms: float
    input_referred_rms: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "output_rms",
            self._validate_scalar(self.output_rms, "output_rms"),
        )
        object.__setattr__(
            self,
            "input_referred_rms",
            self._validate_scalar(
                self.input_referred_rms,
                "input_referred_rms",
            ),
        )

    @staticmethod
    def _validate_scalar(value: Any, field_name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(
                f"Noise total {field_name!r} must be a JSON number"
            )
        numeric = float(value)
        if not np.isfinite(numeric) or numeric < 0:
            raise ValueError(
                f"Noise total {field_name!r} must be finite and non-negative"
            )
        return numeric

    def to_dict(self) -> Dict[str, float]:
        return {
            "output_rms": self.output_rms,
            "input_referred_rms": self.input_referred_rms,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "NoiseTotals":
        if not isinstance(payload, dict):
            raise ValueError("Simulation noise_totals must be an object")
        _require_exact_fields(
            payload,
            _NOISE_TOTAL_FIELDS,
            object_name="Simulation noise_totals",
        )
        return cls(
            output_rms=payload["output_rms"],
            input_referred_rms=payload["input_referred_rms"],
        )


@dataclass
class SimulationData:
    """
    仿真数据容器
    
    Attributes:
        frequency: AC 分析频率点（Hz）
        time: 瞬态分析时间点（秒）
        sweep: DC 分析扫描变量数据
        signals: 信号数据字典，键为信号名称，值为 numpy 数组
    """
    
    frequency: Optional[np.ndarray] = None
    """AC 分析频率点（Hz）"""
    
    time: Optional[np.ndarray] = None
    """瞬态分析时间点（秒）"""
    
    sweep: Optional[np.ndarray] = None
    """DC 分析扫描变量数据"""
    
    signals: Dict[str, np.ndarray] = field(default_factory=dict)
    """信号数据字典，键为信号名称（如 "V(out)"），值为 numpy 数组"""
    
    signal_types: Dict[str, str] = field(default_factory=dict)
    """信号类型字典，键为信号名称，值为 voltage / current / other"""

    noise_totals: Optional[NoiseTotals] = None
    """ngspice 积分噪声总量；非 NOISE 分析必须为 None。"""
    
    # ============================================================
    # 序列化方法
    # ============================================================
    
    def to_dict(self) -> Dict[str, Any]:
        """
        序列化为字典
        
        Returns:
            Dict: 序列化后的字典
        """
        self._validate_signal_types()
        if self.noise_totals is not None and not isinstance(
            self.noise_totals,
            NoiseTotals,
        ):
            raise ValueError(
                "Simulation data 'noise_totals' must be NoiseTotals or null"
            )
        return {
            "frequency": self._serialize_real_array(self.frequency),
            "time": self._serialize_real_array(self.time),
            "sweep": self._serialize_real_array(self.sweep),
            "signals": {
                name: self._serialize_array(data)
                for name, data in self.signals.items()
            },
            "signal_types": dict(self.signal_types) if self.signal_types else {},
            "noise_totals": (
                self.noise_totals.to_dict()
                if self.noise_totals is not None
                else None
            ),
        }

    @staticmethod
    def _serialize_real_array(data: Any) -> Any:
        if data is None:
            return None
        array = np.asarray(data)
        if np.iscomplexobj(array):
            raise ValueError("Simulation axes must contain real numeric values")
        try:
            numeric = array.astype(float, copy=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("Simulation axes must contain numeric values") from exc
        if numeric.ndim != 1:
            raise ValueError("Simulation axes must be one-dimensional")
        if numeric.size and not np.all(np.isfinite(numeric)):
            raise ValueError("Simulation axes must contain only finite values")
        return _json_safe(numeric.tolist())
    
    def _serialize_array(self, data: Any) -> Any:
        """
        序列化数组数据，处理复数类型
        
        Args:
            data: 数组数据（可能是实数或复数）
            
        Returns:
            可 JSON 序列化的数据
        """
        array = np.asarray(data)

        # 检查是否为复数数组
        if np.iscomplexobj(array):
            try:
                array = array.astype(complex, copy=False)
            except (TypeError, ValueError) as exc:
                raise ValueError("Complex signal contains non-numeric values") from exc
            if array.ndim != 1:
                raise ValueError("Signal arrays must be one-dimensional")
            if not np.all(np.isfinite(np.real(array))) or not np.all(
                np.isfinite(np.imag(array))
            ):
                raise ValueError(
                    "Complex signal components must contain only finite values"
                )
            # 复数数组：分别存储实部和虚部
            return {
                "_complex": True,
                "real": _json_safe(np.real(array).tolist()),
                "imag": _json_safe(np.imag(array).tolist()),
            }
        else:
            # 实数数组：直接转换为列表
            try:
                numeric = array.astype(float, copy=False)
            except (TypeError, ValueError) as exc:
                raise ValueError("Signal contains non-numeric values") from exc
            if numeric.ndim != 1:
                raise ValueError("Signal arrays must be one-dimensional")
            if not np.all(np.isfinite(numeric)):
                raise ValueError("Signal arrays must contain only finite values")
            return _json_safe(numeric.tolist())
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimulationData":
        """
        从字典反序列化
        
        Args:
            data: 序列化的字典
            
        Returns:
            SimulationData: 反序列化后的对象
        """
        if not isinstance(data, dict):
            raise ValueError("Simulation data must be a JSON object")
        _require_exact_fields(
            data,
            _SIMULATION_DATA_FIELDS,
            object_name="Simulation data",
        )
        signals = data["signals"]
        signal_types = data["signal_types"]
        noise_totals_payload = data["noise_totals"]
        if not isinstance(signals, dict):
            raise ValueError("Simulation data 'signals' must be an object")
        if not isinstance(signal_types, dict):
            raise ValueError("Simulation data 'signal_types' must be an object")
        if any(not isinstance(name, str) for name in signals):
            raise ValueError("Simulation data signal names must be strings")
        if any(not isinstance(name, str) for name in signal_types):
            raise ValueError("Simulation data signal-type names must be strings")
        if any(not isinstance(kind, str) for kind in signal_types.values()):
            raise ValueError("Simulation data signal-type values must be strings")

        result = cls(
            frequency=cls._deserialize_real_array(data["frequency"], "frequency"),
            time=cls._deserialize_real_array(data["time"], "time"),
            sweep=cls._deserialize_real_array(data["sweep"], "sweep"),
            signals={
                name: cls._deserialize_array(signal_data)
                for name, signal_data in signals.items()
            },
            signal_types=dict(signal_types),
            noise_totals=(
                NoiseTotals.from_dict(noise_totals_payload)
                if noise_totals_payload is not None
                else None
            ),
        )
        result._validate_signal_types()
        return result

    @property
    def op_result(self) -> Dict[str, Any]:
        """Return a fresh OP presentation derived from authoritative vectors."""
        from domain.simulation.data.op_result_payload import (
            build_op_result_payload_from_signals,
        )

        return build_op_result_payload_from_signals(self.signals)

    def _validate_signal_types(self) -> None:
        from domain.simulation.data.signal_semantics import (
            SIGNAL_TYPE_OTHER,
            infer_signal_type_from_name,
            parse_device_parameter_signal_name,
            split_virtual_complex_component_name,
        )

        casefolded_names: set[str] = set()
        for signal_name in self.signals:
            if (
                not isinstance(signal_name, str)
                or not signal_name
                or signal_name != signal_name.strip()
            ):
                raise ValueError(
                    "Simulation signal names must be non-empty canonical strings"
                )
            name_key = signal_name.casefold()
            if name_key in casefolded_names:
                raise ValueError(
                    f"Simulation signals contain case-insensitive alias {signal_name!r}"
                )
            casefolded_names.add(name_key)
            _base_name, virtual_suffix = split_virtual_complex_component_name(
                signal_name
            )
            if virtual_suffix:
                raise ValueError(
                    "Persisted simulation signals must contain native complex "
                    "base vectors, not presentation-only component names: "
                    f"{signal_name!r}"
                )
            upper_name = signal_name.upper()
            if upper_name.startswith("V(") and not signal_name.startswith("V("):
                raise ValueError(
                    f"Voltage signal name must use canonical 'V(' spelling: {signal_name!r}"
                )
            if upper_name.startswith("I(") and not signal_name.startswith("I("):
                raise ValueError(
                    f"Current signal name must use canonical 'I(' spelling: {signal_name!r}"
                )

        signal_names = set(self.signals)
        metadata_names = set(self.signal_types)
        if metadata_names != signal_names:
            missing = sorted(signal_names - metadata_names)
            orphaned = sorted(metadata_names - signal_names)
            details = []
            if missing:
                details.append(f"missing={missing!r}")
            if orphaned:
                details.append(f"orphaned={orphaned!r}")
            raise ValueError(
                "Simulation data 'signal_types' keys must exactly match signals"
                + (f" ({', '.join(details)})" if details else "")
            )

        allowed_types = {"voltage", "current", "other"}
        for signal_name, signal_type in self.signal_types.items():
            if signal_type not in allowed_types:
                raise ValueError(
                    "Simulation signal type must be exactly one of "
                    f"{sorted(allowed_types)!r}: {signal_name!r}={signal_type!r}"
                )
            inferred_type = infer_signal_type_from_name(signal_name)
            has_structural_semantics = (
                inferred_type != SIGNAL_TYPE_OTHER
                or parse_device_parameter_signal_name(signal_name) is not None
            )
            if has_structural_semantics and signal_type != inferred_type:
                raise ValueError(
                    f"Simulation signal type for {signal_name!r} must be "
                    f"{inferred_type!r}, got {signal_type!r}"
                )

    @staticmethod
    def _deserialize_real_array(data: Any, field_name: str) -> Optional[np.ndarray]:
        if data is None:
            return None
        _validate_json_numeric_array(
            data,
            field_name=f"Simulation data '{field_name}'",
        )
        try:
            array = np.asarray(data, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Simulation data '{field_name}' contains non-numeric values") from exc
        if array.ndim != 1:
            raise ValueError(f"Simulation data '{field_name}' must be one-dimensional")
        return array
    
    @classmethod
    def _deserialize_array(cls, data: Any) -> Any:
        """
        反序列化数组数据，处理复数类型
        
        Args:
            data: 序列化的数据
            
        Returns:
            numpy 数组（实数或复数）
        """
        if isinstance(data, dict) and data.get("_complex") is True:
            expected_fields = {"_complex", "real", "imag"}
            if set(data) != expected_fields:
                missing = sorted(expected_fields - set(data))
                unknown = sorted(set(data) - expected_fields, key=str)
                details = []
                if missing:
                    details.append(f"missing={missing!r}")
                if unknown:
                    details.append(f"unknown={unknown!r}")
                raise ValueError(
                    "Complex signal fields must exactly match schema"
                    + (f" ({', '.join(details)})" if details else "")
                )
            # 复数数组：从实部和虚部重建
            real_data = data.get("real")
            imag_data = data.get("imag")
            if not isinstance(real_data, list) or not isinstance(imag_data, list):
                raise ValueError("Complex signal requires real and imag arrays")
            _validate_json_numeric_array(
                real_data,
                field_name="Complex signal real component",
            )
            _validate_json_numeric_array(
                imag_data,
                field_name="Complex signal imaginary component",
            )
            try:
                real = np.asarray(real_data, dtype=float)
                imag = np.asarray(imag_data, dtype=float)
            except (TypeError, ValueError) as exc:
                raise ValueError("Complex signal contains non-numeric values") from exc
            if real.ndim != 1 or imag.ndim != 1 or real.shape != imag.shape:
                raise ValueError("Complex signal real/imag arrays must be one-dimensional and equal length")
            return real + 1j * imag
        elif isinstance(data, list):
            # 实数数组
            _validate_json_numeric_array(
                data,
                field_name="Signal",
            )
            try:
                array = np.asarray(data, dtype=float)
            except (TypeError, ValueError) as exc:
                raise ValueError("Signal contains non-numeric values") from exc
            if array.ndim != 1:
                raise ValueError("Signal arrays must be one-dimensional")
            return array
        else:
            raise ValueError("Signal must be a numeric array or complex split object")

    def validate_for_analysis(
        self,
        analysis_type: str,
        *,
        analysis_command: str,
        success: bool,
    ) -> None:
        """Validate the finite native vectors stored in schema-v3 results."""
        self._validate_signal_types()
        analysis = str(analysis_type or "").strip().lower()
        expected_axis_name = {
            "tran": "time",
            "ac": "frequency",
            "noise": "frequency",
            "dc": "sweep",
        }.get(analysis)
        axes = {
            "frequency": self.frequency,
            "time": self.time,
            "sweep": self.sweep,
        }
        if analysis != "noise" and self.noise_totals is not None:
            raise ValueError(
                "Simulation noise_totals are only valid for NOISE analysis"
            )

        if analysis == "op":
            if any(axis is not None for axis in axes.values()):
                raise ValueError("OP result must not contain sweep axes")
            expected_length = 1
        elif expected_axis_name is not None:
            unexpected_axes = [
                name
                for name, values in axes.items()
                if name != expected_axis_name and values is not None
            ]
            if unexpected_axes:
                raise ValueError(
                    f"{analysis} result must not contain unrelated axes: "
                    f"{', '.join(unexpected_axes)}"
                )
            axis = getattr(self, expected_axis_name)
            if axis is None or len(axis) == 0:
                raise ValueError(
                    f"Successful or data-bearing {analysis} result requires "
                    f"a non-empty {expected_axis_name} axis"
                )
            axis_array = np.asarray(axis)
            try:
                numeric_axis = axis_array.astype(float, copy=False)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Simulation {expected_axis_name} axis must be numeric"
                ) from exc
            if (
                numeric_axis.ndim != 1
                or np.iscomplexobj(axis_array)
                or not np.all(np.isfinite(numeric_axis))
            ):
                raise ValueError(
                    f"Simulation {expected_axis_name} axis must be "
                    "one-dimensional and finite"
                )
            if analysis in {"ac", "noise"}:
                if np.any(numeric_axis <= 0) or (
                    len(numeric_axis) > 1
                    and np.any(np.diff(numeric_axis) <= 0)
                ):
                    raise ValueError(
                        f"Simulation {analysis} frequency axis must be "
                        "positive and strictly increasing"
                    )
            if analysis == "tran":
                if np.any(numeric_axis < 0) or (
                    len(numeric_axis) > 1
                    and np.any(np.diff(numeric_axis) <= 0)
                ):
                    raise ValueError(
                        "Simulation tran time axis must be non-negative "
                        "and strictly increasing"
                    )
            expected_length = len(axis_array)
            if success and not self.signals:
                raise ValueError(
                    f"Successful {analysis} result requires at least one signal"
                )
        else:
            raise ValueError(
                f"Data-bearing simulation result has unsupported analysis_type: {analysis!r}"
            )

        if analysis == "noise":
            required_noise_signals = {
                "onoise_spectrum",
                "inoise_spectrum",
            }
            actual_noise_signals = set(self.signals)
            if actual_noise_signals != required_noise_signals:
                missing_noise_signals = sorted(
                    required_noise_signals - actual_noise_signals
                )
                unexpected_noise_signals = sorted(
                    actual_noise_signals - required_noise_signals
                )
                raise ValueError(
                    "NOISE result signals must be exactly the two canonical "
                    "spectrum vectors "
                    f"(missing={missing_noise_signals!r}, "
                    f"unexpected={unexpected_noise_signals!r})"
                )

            noise_directive = parse_noise_directive(analysis_command)
            expected_noise_types = {
                "onoise_spectrum": "voltage",
                "inoise_spectrum": noise_directive.input_signal_type,
            }
            for signal_name, expected_type in expected_noise_types.items():
                actual_type = self.signal_types.get(signal_name)
                if actual_type != expected_type:
                    raise ValueError(
                        f"NOISE signal {signal_name!r} must have "
                        f"{expected_type!r} semantics derived from "
                        f"analysis_command, got {actual_type!r}"
                    )
            if self.noise_totals is not None and not isinstance(
                self.noise_totals,
                NoiseTotals,
            ):
                raise ValueError(
                    "Simulation noise_totals must be NoiseTotals or null"
                )
            if expected_length > 1 and self.noise_totals is None:
                raise ValueError(
                    "Multi-point NOISE result requires integrated noise_totals"
                )

        for signal_name, signal_values in self.signals.items():
            signal = np.asarray(signal_values)
            if signal.ndim != 1:
                raise ValueError(
                    f"Simulation signal {signal_name!r} must be one-dimensional"
                )
            if len(signal) != expected_length:
                raise ValueError(
                    f"Simulation signal {signal_name!r} length {len(signal)} "
                    f"does not match expected axis length {expected_length}"
                )
            is_complex = np.iscomplexobj(signal)
            if analysis == "ac" and not is_complex:
                raise ValueError(
                    f"AC signal {signal_name!r} must use complex samples"
                )
            if analysis != "ac" and is_complex:
                raise ValueError(
                    f"{analysis.upper()} signal {signal_name!r} must use real samples"
                )
            if is_complex:
                if not np.all(np.isfinite(np.real(signal))) or not np.all(
                    np.isfinite(np.imag(signal))
                ):
                    raise ValueError(
                        f"Simulation signal {signal_name!r} must be finite"
                    )
            else:
                try:
                    numeric_signal = signal.astype(float)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Simulation signal {signal_name!r} must be numeric"
                    ) from exc
                if not np.all(np.isfinite(numeric_signal)):
                    raise ValueError(
                        f"Simulation signal {signal_name!r} must be finite"
                    )
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def get_signal(self, name: str) -> Optional[np.ndarray]:
        """
        获取指定信号数据
        
        Args:
            name: 信号名称（如 "V(out)"）
            
        Returns:
            Optional[np.ndarray]: 信号数据，若不存在则返回 None
        """
        return self.signals.get(name)
    
    def has_signal(self, name: str) -> bool:
        """
        检查是否包含指定信号
        
        Args:
            name: 信号名称
            
        Returns:
            bool: 是否包含该信号
        """
        return name in self.signals
    
    def get_signal_names(self) -> list[str]:
        """
        获取所有信号名称列表
        
        Returns:
            list[str]: 信号名称列表
        """
        return list(self.signals.keys())


# ============================================================
# SimulationResult - 标准化仿真结果
# ============================================================

@dataclass
class SimulationResult:
    """
    标准化仿真结果
    
    Attributes:
        executor: 执行器名称（当前为 "spice"）
        file_path: 仿真文件路径
        analysis_type: 分析类型（如 "ac", "dc", "tran", "noise"）
        success: 是否成功
        source_digest: 有效 SPICE 源闭包的 schema-v3 摘要；失败且无法建立闭包时可为 None
        data: 仿真数据（成功时有值）
        measurements: 规范化测量结果列表（可选）
        error: 错误信息（失败时有值）
        raw_output: 原始输出（调试用）
        timestamp: ISO 格式时间戳
        duration_seconds: 执行耗时（秒）
        version: 由仿真提交方分配的版本号
        session_id: 所属会话 ID（用于追踪）
    """
    
    executor: str
    """执行器名称（当前为 ``spice``）。"""
    
    file_path: str
    """仿真文件路径"""
    
    analysis_type: str
    """分析类型（如 "ac", "dc", "tran", "noise"）"""
    
    success: bool
    """是否成功"""

    source_digest: Optional[str] = None
    """Effective SPICE source-closure identity as a lowercase SHA-256 digest."""
    
    data: Optional[SimulationData] = None
    """仿真数据（成功时有值）"""
    
    measurements: Optional[list[MeasureResult]] = None
    """
    .MEASURE 测量结果列表（新格式）
    
    存储 ngspice .MEASURE 语句的执行结果。
    列表元素为 MeasureResult 对象或等效字典。
    
    示例：
        [
            MeasureResult(
                name="gain_db",
                value=20.5,
                statement=".measure ac gain_db FIND VDB(out) AT=1k",
            ),
            MeasureResult(
                name="f_3db",
                value=1e6,
                statement=".measure ac f_3db WHEN VDB(out)=-3 FALL=1",
            ),
        ]
    """
    
    error: Optional[SimulationError] = None
    """失败时唯一的结构化仿真错误。"""
    
    raw_output: Optional[str] = None
    """原始输出（调试用）"""
    
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    """带时区的 ISO 时间戳（如 2024-12-20T14:30:22.123456+00:00）。"""
    
    duration_seconds: float = 0.0
    """执行耗时（秒）"""
    
    version: int = 1
    """调用方提供的正整数数据版本，用于 UI 数据集新鲜度检查。"""
    
    session_id: str = ""
    """可选的调用方会话关联标识。"""
    
    analysis_command: str = ""

    def __post_init__(self):
        _validate_source_digest(
            self.source_digest,
            success=self.success,
        )
        validate_analysis_command(
            analysis_type=self.analysis_type,
            analysis_command=self.analysis_command,
            required=self.success,
        )

    # ============================================================
    # 序列化方法
    # ============================================================

    def to_dict(self) -> Dict[str, Any]:
        """
        序列化为字典
        
        Returns:
            Dict: 序列化后的字典
        """
        _validate_result_identity(
            executor=self.executor,
            analysis_type=self.analysis_type,
            success=self.success,
        )
        validate_analysis_command(
            analysis_type=self.analysis_type,
            analysis_command=self.analysis_command,
            required=self.success,
        )
        if self.success:
            if self.data is None:
                raise ValueError(
                    "Successful simulation result must contain simulation data"
                )
            if self.error is not None:
                raise ValueError(
                    "Successful simulation result must not contain an error"
                )
        else:
            if self.data is not None:
                raise ValueError(
                    "Failed simulation result must not contain partial simulation data"
                )
            if self.measurements is not None:
                raise ValueError(
                    "Failed simulation result must not contain measurements"
                )
            if not isinstance(self.error, SimulationError):
                raise ValueError(
                    "Failed simulation result requires a structured SimulationError"
                )
        if self.data is not None:
            self.data.validate_for_analysis(
                self.analysis_type,
                analysis_command=self.analysis_command,
                success=self.success,
            )
            _validate_axis_matches_analysis_command(
                analysis_type=self.analysis_type,
                analysis_command=self.analysis_command,
                data=self.data,
            )
        if self.success and self.analysis_type.strip().lower() == "op":
            op_payload = self.data.op_result if self.data is not None else {}
            if int(op_payload.get("row_count", 0)) <= 0:
                raise ValueError(
                    "Successful OP result must contain scalar OP signals"
                )
        source_digest = _validate_source_digest(
            self.source_digest,
            success=self.success,
        )
        duration = _validate_duration_seconds(self.duration_seconds)

        measurements_data = _serialize_measurements_strict(
            self.measurements,
            analysis_type=self.analysis_type,
        )

        return _json_safe({
            "schema_version": RESULT_SCHEMA_VERSION,
            "executor": self.executor,
            "file_path": self.file_path,
            "analysis_type": self.analysis_type,
            "success": self.success,
            "source_digest": source_digest,
            "data": self.data.to_dict() if self.data is not None else None,
            "measurements": measurements_data,
            "error": self.error.to_dict() if self.error is not None else None,
            "raw_output": self.raw_output,
            "timestamp": self.timestamp,
            "duration_seconds": duration,
            "version": self.version,
            "session_id": self.session_id,
            "analysis_command": self.analysis_command,
        })

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimulationResult":
        """
        从字典反序列化
        
        Args:
            data: 序列化的字典
            
        Returns:
            SimulationResult: 反序列化后的对象
        """
        if not isinstance(data, dict):
            raise ValueError("Simulation result must be a JSON object")
        _require_exact_fields(
            data,
            _SIMULATION_RESULT_FIELDS,
            object_name="Simulation result",
        )

        schema_version = data.get("schema_version")
        if type(schema_version) is not int or schema_version != RESULT_SCHEMA_VERSION:
            raise ValueError(f"Unsupported simulation result schema_version: {schema_version!r}")

        required_strings = ("executor", "file_path", "analysis_type")
        for field_name in required_strings:
            if not isinstance(data.get(field_name), str) or not data[field_name].strip():
                raise ValueError(f"Simulation result '{field_name}' must be a non-empty string")
        file_path = data["file_path"]
        portable_path = PurePosixPath(file_path)
        if (
            "\\" in file_path
            or portable_path.is_absolute()
            or file_path != portable_path.as_posix()
            or any(
                part in {"", ".", ".."} or ":" in part
                for part in portable_path.parts
            )
        ):
            raise ValueError(
                "Simulation result 'file_path' must be a canonical "
                "project-relative POSIX path"
            )
        _validate_result_identity(
            executor=data["executor"],
            analysis_type=data["analysis_type"],
            success=data["success"],
        )
        if "source_digest" not in data:
            raise ValueError("Simulation result 'source_digest' is required")
        source_digest = _validate_source_digest(
            data["source_digest"],
            success=data["success"],
        )

        timestamp = data.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp.strip():
            raise ValueError("Simulation result 'timestamp' must be a non-empty ISO timestamp")
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Simulation result 'timestamp' is not valid ISO-8601") from exc
        if parsed_timestamp.utcoffset() is None:
            raise ValueError(
                "Versioned simulation result 'timestamp' must include a timezone offset"
            )
        duration = _validate_duration_seconds(data["duration_seconds"])

        data_payload = data["data"]
        if data["success"] and data_payload is None:
            raise ValueError("Successful simulation result must contain simulation data")
        if not data["success"] and data_payload is not None:
            raise ValueError(
                "Failed simulation result must not contain partial simulation data"
            )
        if data_payload is not None and not isinstance(data_payload, dict):
            raise ValueError("Simulation result 'data' must be an object or null")

        raw_output = data["raw_output"]
        if raw_output is not None and not isinstance(raw_output, str):
            raise ValueError("Simulation result 'raw_output' must be a string or null")
        version = data["version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValueError("Simulation result 'version' must be a positive integer")
        session_id = data["session_id"]
        if not isinstance(session_id, str):
            raise ValueError("Simulation result 'session_id' must be a string")
        if not isinstance(data.get("analysis_command"), str):
            raise ValueError("Simulation result 'analysis_command' must be a string")
        validate_analysis_command(
            analysis_type=data["analysis_type"],
            analysis_command=data["analysis_command"],
            required=data["success"],
        )

        # 反序列化仿真数据
        sim_data = None
        if data_payload is not None:
            sim_data = SimulationData.from_dict(data_payload)
            sim_data.validate_for_analysis(
                data["analysis_type"],
                analysis_command=data["analysis_command"],
                success=data["success"],
            )
            _validate_axis_matches_analysis_command(
                analysis_type=data["analysis_type"],
                analysis_command=data["analysis_command"],
                data=sim_data,
            )
        if data["success"] and data["analysis_type"].strip().lower() == "op":
            op_payload = sim_data.op_result if sim_data is not None else {}
            if int(op_payload.get("row_count", 0)) <= 0:
                raise ValueError(
                    "Successful OP result must contain scalar OP signals"
                )

        # 反序列化 measurements
        if not data["success"] and data["measurements"] is not None:
            raise ValueError(
                "Failed simulation result must not contain measurements"
            )
        measurements = _deserialize_measurements_strict(
            data["measurements"],
            analysis_type=data["analysis_type"],
        )

        # 反序列化错误信息
        error = None
        error_data = data["error"]
        if data["success"] and error_data is not None:
            raise ValueError("Successful simulation result must not contain an error")
        if not data["success"] and error_data is None:
            raise ValueError("Failed simulation result must contain an error")
        if error_data is not None:
            if not isinstance(error_data, dict):
                raise ValueError(
                    "Simulation result 'error' must be a structured SimulationError"
                )
            error = SimulationError.from_dict(error_data)
            if (
                error.file_path is not None
                and error.file_path != data["file_path"]
            ):
                raise ValueError(
                    "Structured simulation error file_path must match "
                    "the result file_path or be null"
                )

        return cls(
            executor=data["executor"],
            file_path=data["file_path"],
            analysis_type=data["analysis_type"],
            success=data["success"],
            source_digest=source_digest,
            data=sim_data,
            measurements=measurements,
            error=error,
            raw_output=raw_output,
            timestamp=timestamp,
            duration_seconds=duration,
            version=version,
            session_id=session_id,
            analysis_command=data["analysis_command"],
        )

    # ============================================================
    # 辅助方法
    # ============================================================

    def get_signal(self, name: str) -> Optional[np.ndarray]:
        """
        获取指定信号数据
        
        Args:
            name: 信号名称（如 "V(out)"）
            
        Returns:
            Optional[np.ndarray]: 信号数据，若不存在或仿真失败则返回 None
        """
        if not self.success or self.data is None:
            return None
        return self.data.get_signal(name)

    def get_x_axis_data(self) -> Optional[np.ndarray]:
        if not self.success or self.data is None:
            return None
        return _get_x_axis_array(self.data, self.x_axis_kind)

    def get_x_axis_label(self) -> str:
        return self.x_axis_label

    def is_x_axis_log(self) -> bool:
        return self.x_axis_scale == X_AXIS_SCALE_LOG

    @property
    def x_axis_kind(self) -> str:
        return _analysis_x_axis_kind(self.analysis_type)

    @property
    def x_axis_label(self) -> str:
        return _infer_x_axis_label(self.x_axis_kind, self.analysis_command)

    @property
    def x_axis_scale(self) -> str:
        return _default_x_axis_scale(
            self.analysis_type,
            self.x_axis_kind,
            self.analysis_command,
        )

    @property
    def requested_x_range(self) -> Optional[tuple[float, float]]:
        return _infer_requested_x_range(
            self.analysis_type,
            self.analysis_command,
        )

    @property
    def actual_x_range(self) -> Optional[tuple[float, float]]:
        return _infer_actual_x_range(self.data, self.x_axis_kind)

    @property
    def analysis_info(self) -> Dict[str, Any]:
        """Return a fresh view derived from the authoritative result fields."""
        return _derive_analysis_info(
            analysis_type=self.analysis_type,
            analysis_command=self.analysis_command,
            x_axis_kind=self.x_axis_kind,
            x_axis_label=self.x_axis_label,
            x_axis_scale=self.x_axis_scale,
            requested_x_range=self.requested_x_range,
            actual_x_range=self.actual_x_range,
        )

# ============================================================
# 工厂方法
# ============================================================

def create_success_result(
    executor: str,
    file_path: str,
    analysis_type: str,
    data: SimulationData,
    source_digest: str,
    measurements: Optional[list[MeasureResult]] = None,
    raw_output: Optional[str] = None,
    duration_seconds: float = 0.0,
    version: int = 1,
    session_id: str = "",
    analysis_command: str = "",
) -> SimulationResult:
    """
    创建成功的仿真结果
    
    Args:
        executor: 执行器名称
        file_path: 仿真文件路径
        analysis_type: 分析类型
        data: 仿真数据
        source_digest: 有效 SPICE 源闭包的 schema-v3 摘要
        measurements: 规范化测量结果列表（可选）
        raw_output: 原始输出（可选）
        duration_seconds: 执行耗时
        version: 调用方分配的版本号
        session_id: 调用方提供的会话 ID
        
    Returns:
        SimulationResult: 成功的仿真结果
    """
    return SimulationResult(
        executor=executor,
        file_path=file_path,
        analysis_type=analysis_type,
        success=True,
        source_digest=source_digest,
        data=data,
        measurements=measurements,
        error=None,
        raw_output=raw_output,
        timestamp=datetime.now(timezone.utc).isoformat(),
        duration_seconds=duration_seconds,
        version=version,
        session_id=session_id,
        analysis_command=analysis_command,
    )


def create_error_result(
    executor: str,
    file_path: str,
    analysis_type: str,
    error: SimulationError,
    source_digest: Optional[str] = None,
    raw_output: Optional[str] = None,
    duration_seconds: float = 0.0,
    version: int = 1,
    session_id: str = "",
    analysis_command: str = "",
) -> SimulationResult:
    """
    创建失败的仿真结果
    
    Args:
        executor: 执行器名称
        file_path: 仿真文件路径
        analysis_type: 分析类型
        error: 结构化仿真错误
        source_digest: 已建立的有效 SPICE 源闭包摘要；无法建立时为 None
        raw_output: 原始输出（可选）
        duration_seconds: 执行耗时
        version: 调用方分配的版本号
        session_id: 调用方提供的会话 ID
        
    Returns:
        SimulationResult: 失败的仿真结果
    """
    return SimulationResult(
        executor=executor,
        file_path=file_path,
        analysis_type=analysis_type,
        success=False,
        source_digest=source_digest,
        data=None,
        error=error,
        raw_output=raw_output,
        timestamp=datetime.now(timezone.utc).isoformat(),
        duration_seconds=duration_seconds,
        version=version,
        session_id=session_id,
        analysis_command=analysis_command,
    )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "RESULT_SCHEMA_VERSION",
    "NoiseTotals",
    "SimulationData",
    "SimulationResult",
    "create_success_result",
    "create_error_result",
]
