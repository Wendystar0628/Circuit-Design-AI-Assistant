import pytest

from domain.simulation.models.simulation_error import (
    ErrorSeverity,
    SimulationError,
    SimulationErrorType,
)


def _canonical_payload():
    return SimulationError(
        type=SimulationErrorType.PARAMETER_INVALID,
        severity=ErrorSeverity.HIGH,
        message="invalid sweep",
    ).to_dict()


def test_error_code_is_derived_from_type_and_round_trips():
    error = SimulationError(
        type=SimulationErrorType.PARAMETER_INVALID,
        severity=ErrorSeverity.HIGH,
        message="invalid sweep",
    )
    assert error.code == "E010"
    assert SimulationError.from_dict(error.to_dict()).to_dict() == error.to_dict()


def test_deserialization_rejects_contradictory_code_and_type():
    payload = _canonical_payload()
    payload["code"] = "E011"

    with pytest.raises(ValueError, match="contradicts"):
        SimulationError.from_dict(payload)


@pytest.mark.parametrize("missing_field", tuple(_canonical_payload()))
def test_deserialization_requires_every_canonical_key(missing_field):
    payload = _canonical_payload()
    payload.pop(missing_field)

    with pytest.raises(ValueError, match="exact canonical keys.*missing"):
        SimulationError.from_dict(payload)


def test_deserialization_rejects_unknown_keys():
    payload = _canonical_payload()
    payload["legacy_error_code"] = "E010"

    with pytest.raises(ValueError, match="exact canonical keys.*unknown"):
        SimulationError.from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("recovery_attempted", "false", "must be a boolean"),
        ("details", [["attempt", "retry"]], "must be an object"),
        ("file_path", 123, "must be a string or null"),
        ("context", ["line"], "must be a string or null"),
        ("recovery_result", {"status": "failed"}, "must be a string or null"),
        ("recovery_suggestion", False, "must be a string or null"),
        ("raw_output", ["stderr"], "must be a string or null"),
    ],
)
def test_deserialization_rejects_diagnostic_type_coercion(field, value, expected):
    payload = _canonical_payload()
    payload[field] = value

    with pytest.raises(TypeError, match=expected):
        SimulationError.from_dict(payload)


def test_constructor_rejects_false_recovery_truthiness():
    with pytest.raises(TypeError, match="recovery_attempted"):
        SimulationError(
            type=SimulationErrorType.PARAMETER_INVALID,
            severity=ErrorSeverity.HIGH,
            message="invalid sweep",
            recovery_attempted="false",  # type: ignore[arg-type]
        )


def test_cancelled_is_not_misclassified_as_timeout():
    error = SimulationError(
        type=SimulationErrorType.CANCELLED,
        severity=ErrorSeverity.LOW,
        message="simulation cancelled",
    )
    assert error.code == "E014"
    assert error.type is not SimulationErrorType.TIMEOUT
