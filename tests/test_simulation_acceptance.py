from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from domain.simulation.measure.measure_result import MeasureResult, MeasureStatus
from domain.simulation.models.acceptance import (
    convert_metric_value, evaluate_acceptance, resolve_native_measurement,
    validate_acceptance_constraints,
)
from domain.simulation.models.simulation_result import SimulationData, SimulationResult


def _constraint(**overrides):
    return {"metric": "vout", "unit": "V", "lower": 0.4, "upper": 0.6, **overrides}


def _result(value=0.5, **overrides):
    measurement = MeasureResult("vout", value, statement=".measure tran vout AVG V(out) FROM=0 TO=1m", **overrides)
    return SimpleNamespace(success=True, measurements=[measurement])


def _evaluate(result, constraints=None, **experiment):
    return evaluate_acceptance(result, {"acceptance_constraints": constraints or [_constraint()], **experiment})


@pytest.mark.parametrize("payload", [
    None, {}, [_constraint(lower=None, upper=None)], [_constraint(lower=0.7)],
    [_constraint(lower=float("nan"))], [_constraint(upper=float("inf"))], [_constraint(lower=True)],
    [_constraint(lower="0.4")], [_constraint(unit="")], [_constraint(metric="x\n.end")],
    [_constraint(source="trace_max")], [_constraint(unknown=1)],
    [_constraint(), _constraint(metric="VOUT")],
    [_constraint(conditions={"load": 10})], [_constraint(conditions={"temperature": -273.15})],
    [_constraint(conditions={"temperature": True})], [_constraint(conditions={"parameters": {"R": "1k", "r": "2k"}})],
    [_constraint(conditions={"parameters": {"r": "{foo}"}})],
])
def test_invalid_constraint_contract_is_rejected(payload):
    with pytest.raises(ValueError):
        validate_acceptance_constraints(payload)


def test_normalized_constraints_are_independent_of_mutable_input():
    payload = [_constraint(conditions={"parameters": {"R": "1k"}, "temperature": 25})]
    normalized = validate_acceptance_constraints(payload)
    payload[0]["conditions"]["parameters"]["R"] = "2k"
    assert normalized[0] == {"id": "vout", "source": "measurement", "metric": "vout", "unit": "V",
                             "lower": 0.4, "upper": 0.6,
                             "conditions": {"parameters": {"r": "1k"}, "temperature": 25.0}}
    assert validate_acceptance_constraints(normalized) == normalized


@pytest.mark.parametrize("value,status", [(0.4, "PASS"), (0.6, "PASS"), (0.39, "FAIL"), (0.61, "FAIL")])
def test_limits_are_inclusive_and_failures_retain_real_values(value, status):
    row = _evaluate(_result(value))["rows"][0]
    assert row["status"] == status
    assert row["value"] == value
    assert (row["margin"] >= 0) == (status == "PASS")


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), True, "0"])
def test_invalid_measurements_are_not_zero_and_cannot_pass(value):
    report = _evaluate(_result(value), [_constraint(lower=None, upper=1)])
    assert report["status"] == "NOT_MEASURED"
    assert report["rows"][0]["value"] is None
    assert report["rows"][0]["margin"] is None


@pytest.mark.parametrize("status", [MeasureStatus.FAILED, MeasureStatus.PARSE_ERROR])
def test_failed_measurement_retains_failure_reason_even_if_value_is_zero(status):
    row = _evaluate(_result(0, status=status, error_message="crossing absent"))["rows"][0]
    assert row["status"] == "NOT_MEASURED"
    assert row["value"] is None
    assert row["reason"] == "crossing absent"


def test_missing_duplicate_and_failed_run_do_not_pass():
    result = _result()
    result.measurements = []
    assert _evaluate(result)["status"] == "NOT_MEASURED"
    result = _result()
    result.measurements += deepcopy(result.measurements)
    assert "ambiguous" in _evaluate(result)["rows"][0]["reason"]
    result.success = False
    assert "successfully" in _evaluate(result)["rows"][0]["reason"]


def test_unit_conversion_and_mismatch():
    converted = _evaluate(_result(), [_constraint(unit="mV", lower=400, upper=600)])["rows"][0]
    assert converted["status"] == "PASS"
    assert converted["value"] == 500
    assert converted["margin"] == 100
    assert converted["observed_unit"] == "V"
    mismatch = _evaluate(_result(), [_constraint(unit="A")])["rows"][0]
    assert mismatch["status"] == "NOT_MEASURED"
    assert mismatch["value"] is None
    assert "Unit mismatch" in mismatch["reason"]


@pytest.mark.parametrize("statement", [
    ".measure tran vout PARAM='other/voltage'", ".measure tran vout FIND V(out)/I(V1) AT=1m",
    ".measure dc vout WHEN V(out)=0.5", "", ".measure tran different AVG V(out)",
])
def test_unknown_dimensions_and_mismatched_statement_identity_are_not_guessed(statement):
    result = _result()
    result.measurements[0].statement = statement
    row = _evaluate(result)["rows"][0]
    assert row["status"] == "NOT_MEASURED"
    assert row["value"] is None
    assert "unit cannot be established" in row["reason"]


def test_crossing_reports_time_and_phase_converts_radians_to_degrees():
    result = _result(0.0005)
    result.measurements[0].statement = ".measure tran vout WHEN V(out)=0.5 RISE=1"
    assert _evaluate(result, [_constraint(unit="ms", lower=0.4, upper=0.6)])["status"] == "PASS"
    result.measurements[0].statement = ".measure ac vout FIND VP(out) AT=1k"
    result.measurements[0].value = np.pi / 2
    row = _evaluate(result, [_constraint(unit="°", lower=89, upper=91)])["rows"][0]
    assert row["status"] == "PASS"
    assert row["value"] == pytest.approx(90)


def test_conditions_use_recorded_experiment_values_and_spice_suffix_semantics():
    constraints = [_constraint(conditions={"parameters": {"R": "1k"}, "temperature": 85})]
    assert _evaluate(_result(), constraints, parameters={"r": "1000"}, temperature=85)["status"] == "PASS"
    unmatched = _evaluate(_result(), constraints, parameters={"r": "1Meg"}, temperature=85)
    assert unmatched["status"] == "NOT_MEASURED"
    assert "does not match" in unmatched["rows"][0]["reason"]
    missing_temperature = _evaluate(_result(), constraints, parameters={"r": "1k"})
    assert "temperature is not recorded" in missing_temperature["rows"][0]["reason"]
    missing_parameter = _evaluate(_result(), constraints, temperature=85)
    assert "parameter r is not recorded" in missing_parameter["rows"][0]["reason"]


def test_summary_fail_takes_precedence_and_missing_prevents_overall_pass():
    constraints = [_constraint(), _constraint(id="missing", metric="absent")]
    assert _evaluate(_result(), constraints)["status"] == "NOT_MEASURED"
    report = _evaluate(_result(1), constraints)
    assert report["status"] == "FAIL"
    assert report["counts"] == {"PASS": 0, "FAIL": 1, "NOT_MEASURED": 1}
    assert evaluate_acceptance(_result(), {"acceptance_constraints": []}) == {
        "status": "NOT_MEASURED", "rows": [], "counts": {"PASS": 0, "FAIL": 0, "NOT_MEASURED": 0}}


def test_op_signal_uses_native_single_point_and_known_unit():
    result = SimulationResult(executor="spice", file_path="divider.cir", analysis_type="op", analysis_command=".op",
                              success=True, source_digest="a" * 64, data=SimulationData(signals={"V(out)": np.array([0.5])},
                                                                 signal_types={"V(out)": "voltage"}))
    row = _evaluate(result, [_constraint(source="op_signal", metric="v(out)")])["rows"][0]
    assert row["status"] == "PASS"
    assert row["value"] == 0.5
    result.analysis_type = "tran"
    assert _evaluate(result, [_constraint(source="op_signal", metric="V(out)")])["status"] == "NOT_MEASURED"


def test_one_sided_limit_accepts_real_zero():
    row = _evaluate(_result(0), [_constraint(lower=None, upper=0)])["rows"][0]
    assert row["status"] == "PASS"
    assert row["value"] == 0


def test_shared_native_measurement_contract_excludes_unknown_dimensions():
    result = _result()
    assert resolve_native_measurement(result, "vout") == (0.5, "V", "")
    result.measurements[0].statement = ".measure tran vout PARAM='a/b'"
    value, unit, reason = resolve_native_measurement(result, "vout")
    assert value is None and unit == "" and reason
    result.success = False
    assert resolve_native_measurement(result, "vout")[0] is None


def test_shared_conversion_handles_units_and_overflow_without_fabrication():
    assert convert_metric_value(0.5, "V", "mV") == (500, "")
    assert convert_metric_value(np.pi, "rad", "°")[0] == pytest.approx(180)
    for value, source, target in [(1, "", ""), (1, "V", "A"), (1e308, "V", "pV"), (None, "V", "V")]:
        converted, reason = convert_metric_value(value, source, target)
        assert converted is None and reason
