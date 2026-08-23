"""Single structural authority for supported top-level analysis directives."""

from __future__ import annotations

import math

from domain.simulation.spice.directive_tokenizer import tokenize_spice_directive
from domain.simulation.spice.noise_directive import parse_noise_directive
from domain.simulation.spice.numeric import parse_spice_number


def validate_analysis_command(
    *,
    analysis_type: str,
    analysis_command: str,
    required: bool = True,
) -> None:
    """Validate one supported analysis card without evaluating expressions.

    Required analysis cards must use finite literal numeric sweep operands.
    Expressions are rejected because ngspice may silently substitute defaults
    or hang on a resolved zero step. ``.temp`` is outside this API and retains
    its separately validated expression support.
    """

    analysis = str(analysis_type or "").strip().casefold()
    if not isinstance(analysis_command, str):
        raise ValueError("analysis_command must be a string")
    stripped = analysis_command.strip()
    if not stripped:
        if required:
            raise ValueError("Analysis command is required")
        return
    if any(character in analysis_command for character in ("\x00", "\r", "\n")):
        raise ValueError("analysis_command must contain exactly one directive")

    tokens = list(tokenize_spice_directive(stripped))
    expected = f".{analysis}"
    if not analysis or not tokens or tokens[0].casefold() != expected:
        raise ValueError(
            f"analysis_command must start with {expected!r} for "
            f"analysis_type {analysis!r}"
        )
    if not required:
        return

    _validate_analysis_command_shape(analysis, tokens, stripped)


def _validate_analysis_command_shape(
    analysis: str,
    tokens: list[str],
    analysis_command: str,
) -> None:
    if analysis == "op":
        if len(tokens) != 1:
            raise ValueError("OP analysis_command must be exactly '.op'")
        return

    if analysis == "ac":
        if len(tokens) != 5:
            raise ValueError(
                "AC analysis_command must be "
                "'.ac <lin|dec|oct> <points> <start> <stop>'"
            )
        _validate_frequency_sweep_tokens(
            analysis,
            tokens,
            mode_index=1,
            points_index=2,
            start_index=3,
        )
        return

    if analysis == "noise":
        parse_noise_directive(analysis_command)
        _validate_frequency_sweep_tokens(
            analysis,
            tokens,
            mode_index=3,
            points_index=4,
            start_index=5,
        )
        return

    if analysis == "dc":
        if len(tokens) not in {5, 9}:
            raise ValueError(
                "DC analysis_command must contain one or two complete source sweeps"
            )
        _validate_dc_sweep_tokens(
            tokens,
            start_index=1,
        )
        if len(tokens) == 9:
            _validate_dc_sweep_tokens(
                tokens,
                start_index=5,
            )
        return

    if analysis == "tran":
        numeric_tokens = tokens[:-1] if tokens[-1].casefold() == "uic" else tokens
        if any(token.casefold() == "uic" for token in numeric_tokens):
            raise ValueError("TRAN 'uic' option must appear at most once at the end")
        if len(numeric_tokens) < 3 or len(numeric_tokens) > 5:
            raise ValueError(
                "TRAN analysis_command must include tstep, tstop, optional "
                "tstart/tmax, and optional uic"
            )
        _validate_positive_literal(
            numeric_tokens[1],
            field_name="TRAN tstep",
        )
        _validate_positive_literal(
            numeric_tokens[2],
            field_name="TRAN tstop",
        )
        if len(numeric_tokens) > 3:
            _validate_nonnegative_literal(
                numeric_tokens[3],
                field_name="TRAN tstart",
            )
        if len(numeric_tokens) > 4:
            _validate_positive_literal(
                numeric_tokens[4],
                field_name="TRAN tmax",
            )
        start_value = (
            parse_spice_number(numeric_tokens[3])
            if len(numeric_tokens) > 3
            else 0.0
        )
        stop_value = parse_spice_number(numeric_tokens[2])
        if (
            start_value is not None
            and stop_value is not None
            and start_value >= stop_value
        ):
            raise ValueError("TRAN tstart must be smaller than tstop")
        return

    raise ValueError(f"Unsupported simulation analysis_type: {analysis!r}")


def _validate_frequency_sweep_tokens(
    analysis: str,
    tokens: list[str],
    *,
    mode_index: int,
    points_index: int,
    start_index: int,
) -> None:
    sweep_mode = tokens[mode_index].casefold()
    if sweep_mode not in {"lin", "dec", "oct"}:
        raise ValueError(
            f"{analysis.upper()} sweep mode must be lin, dec, or oct"
        )
    point_count = parse_spice_number(tokens[points_index])
    if point_count is None or not math.isfinite(point_count):
        raise ValueError(
            f"{analysis.upper()} point count must be a finite literal number"
        )
    if point_count is not None and (
        point_count <= 0 or not float(point_count).is_integer()
    ):
        raise ValueError(
            f"{analysis.upper()} point count must be a positive integer"
        )
    start_value = parse_spice_number(tokens[start_index])
    stop_value = parse_spice_number(tokens[start_index + 1])
    if (
        start_value is None
        or stop_value is None
        or not math.isfinite(start_value)
        or not math.isfinite(stop_value)
    ):
        raise ValueError(
            f"{analysis.upper()} frequency bounds must be finite literal numbers"
        )
    if start_value is not None and start_value <= 0:
        raise ValueError(f"{analysis.upper()} start frequency must be positive")
    if stop_value is not None and stop_value <= 0:
        raise ValueError(f"{analysis.upper()} stop frequency must be positive")
    if (
        start_value is not None
        and stop_value is not None
        and start_value >= stop_value
    ):
        raise ValueError(
            f"{analysis.upper()} start frequency must be smaller than stop frequency"
        )
    if analysis == "ac" and sweep_mode == "dec":
        raw_interval_count = point_count * math.log10(stop_value / start_value)
        rounding_tolerance = max(abs(raw_interval_count), 1.0) * 1e-12
        if math.floor(raw_interval_count + rounding_tolerance) < 1:
            raise ValueError(
                "AC DEC sweep must span at least one generated interval"
            )


def _validate_dc_sweep_tokens(
    tokens: list[str],
    *,
    start_index: int,
) -> None:
    source_name = tokens[start_index]
    if not source_name.strip():
        raise ValueError("DC source name must not be empty")
    start_value = parse_spice_number(tokens[start_index + 1])
    stop_value = parse_spice_number(tokens[start_index + 2])
    step_value = parse_spice_number(tokens[start_index + 3])
    if (
        None in {start_value, stop_value, step_value}
        or not all(
            math.isfinite(value)
            for value in (start_value, stop_value, step_value)
            if value is not None
        )
    ):
        raise ValueError(
            "DC sweep bounds and step must be finite literal numbers"
        )
    if step_value is not None and step_value == 0:
        raise ValueError("DC sweep step must be non-zero")
    if (
        start_value is not None
        and stop_value is not None
        and step_value is not None
        and (stop_value - start_value) * step_value < 0
    ):
        raise ValueError("DC sweep step direction must reach the stop value")


def _validate_positive_literal(
    token: str,
    *,
    field_name: str,
) -> None:
    value = parse_spice_number(token)
    if value is None or not math.isfinite(value):
        raise ValueError(f"{field_name} must be a finite literal number")
    if value is not None and value <= 0:
        raise ValueError(f"{field_name} must be positive")


def _validate_nonnegative_literal(
    token: str,
    *,
    field_name: str,
) -> None:
    value = parse_spice_number(token)
    if value is None or not math.isfinite(value):
        raise ValueError(f"{field_name} must be a finite literal number")
    if value is not None and value < 0:
        raise ValueError(f"{field_name} must be non-negative")


__all__ = ["validate_analysis_command"]
