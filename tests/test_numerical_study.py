from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from domain.simulation.executor.spice_executor import SpiceExecutor
from domain.simulation.measure.measure_result import MeasureResult, MeasureStatus
from domain.simulation.models.experiment import ExperimentSpec
from domain.simulation.models.numerical_study import (
    NumericalStudySpec, build_numerical_experiments, compare_numerical_results,
)
from domain.simulation.models.simulation_result import SimulationResult
from domain.simulation.spice.experiment_deck import compile_experiment_graph
from domain.simulation.spice.numeric import parse_spice_number
from domain.simulation.spice.source_closure import (
    capture_spice_source_snapshot, collect_spice_source_closure, restore_spice_source_graph,
)
from infrastructure.utils.ngspice_config import configure_ngspice


def _spec(**kwargs):
    return NumericalStudySpec.from_dict({
        "metrics": [{"name": "vout", "unit": "V", "absolute_tolerance": 0.001,
                     "relative_tolerance": 0.01}], **kwargs,
    })


def _source(tmp_path: Path, command=".tran 10u 2m", controls=""):
    path = tmp_path / "rc.cir"
    path.write_text(
        "RC numerical study\n.param rval=1k\n"
        "V1 in 0 1\nR1 in out {rval}\nC1 out 0 1u\n"
        f"{controls}\n{command}\n.measure tran vout FIND v(out) AT=2m\n.end\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("payload", [
    {}, {"metrics": []}, {"metrics": "vout"},
    {"metrics": [{"name": "x"}]},
    {"metrics": [{"name": "x", "unit": ""}]},
    {"metrics": [{"name": "x", "unit": "V", "absolute_tolerance": -1}]},
    {"metrics": [{"name": "x", "unit": "V", "relative_tolerance": float("nan")}]},
    {"metrics": [{"name": "x", "unit": "V", "absolute_tolerance": True}]},
    {"metrics": [{"name": "x", "unit": "V", "extra": 1}]},
    {"metrics": [{"name": "x", "unit": "V"}, {"name": "X", "unit": "V"}]},
])
def test_numerical_spec_rejects_invalid_thresholds_and_selection(payload):
    with pytest.raises(ValueError):
        NumericalStudySpec.from_dict(payload)


@pytest.mark.parametrize("factor", [0, -1, 1, 1.01, True, float("nan"), float("inf"), "0.5"])
@pytest.mark.parametrize("field", ["tolerance_factor", "max_timestep_factor"])
def test_numerical_spec_requires_finite_stricter_factors(field, factor):
    with pytest.raises(ValueError):
        _spec(**{field: factor})


def test_baseline_and_refinement_use_effective_source_controls(tmp_path):
    source = _source(tmp_path, controls=".options reltol=1e-8 abstol=1e-14 method=gear maxord=4")
    before = source.read_bytes()
    graph = collect_spice_source_closure(source)
    base = ExperimentSpec(parameters={"rval": "2k"}, temperature=80, solver_options={"reltol": "2e-8"})
    baseline, refined = build_numerical_experiments(base, graph, _spec())
    assert parse_spice_number(baseline.solver_options["reltol"]) == pytest.approx(2e-8)
    assert parse_spice_number(refined.solver_options["reltol"]) == pytest.approx(2e-9)
    assert parse_spice_number(refined.solver_options["abstol"]) == pytest.approx(1e-15)
    assert parse_spice_number(baseline.solver_options["vntol"]) == pytest.approx(1e-6)
    assert baseline.solver_options["method"] == refined.solver_options["method"] == "gear"
    assert baseline.solver_options["maxord"] == refined.solver_options["maxord"] == "4"
    assert baseline.parameters == refined.parameters == {"rval": "2k"}
    assert baseline.temperature == refined.temperature == 80
    assert source.read_bytes() == before
    assert graph.main_blob.raw_bytes == before
    assert NumericalStudySpec.from_dict(_spec().to_dict()) == _spec()


@pytest.mark.parametrize("command,expected_max,expected_start,uic", [
    (".tran 10u 2m", 10e-6, 0, False),
    (".tran 1m 2m 1m", 20e-6, 1e-3, False),
    (".tran 1m 2m 500u 5u UIC", 5e-6, 500e-6, True),
    (".tran 10u 2m uic", 10e-6, 0, True),
])
def test_transient_refines_actual_tmax_and_preserves_initial_conditions(tmp_path, command, expected_max, expected_start, uic):
    graph = collect_spice_source_closure(_source(tmp_path, command=command))
    baseline, refined = build_numerical_experiments(ExperimentSpec(), graph, _spec())
    for experiment, factor in ((baseline, 1), (refined, 0.5)):
        tokens = experiment.analysis_command.split()
        assert tokens[:3] == command.split()[:3]
        assert parse_spice_number(tokens[3]) == pytest.approx(expected_start)
        assert parse_spice_number(tokens[4]) == pytest.approx(expected_max * factor)
        assert (tokens[-1] == "uic") == uic
        effective, _, _ = compile_experiment_graph(graph, experiment)
        assert experiment.analysis_command in effective.main_blob.source_text


def test_nontransient_analysis_keeps_grid_and_refines_only_tolerances(tmp_path):
    graph = collect_spice_source_closure(_source(tmp_path, command=".ac dec 10 1k 100k"))
    baseline, refined = build_numerical_experiments(ExperimentSpec(), graph, _spec())
    assert baseline.analysis_command == refined.analysis_command == ".ac dec 10 1k 100k"
    assert float(refined.solver_options["reltol"]) < float(baseline.solver_options["reltol"])


def test_refinement_below_supported_tolerance_fails_explicitly(tmp_path):
    graph = collect_spice_source_closure(_source(tmp_path, controls=".options reltol=1e-15"))
    with pytest.raises(ValueError, match="reltol"):
        build_numerical_experiments(ExperimentSpec(), graph, _spec())


def _result(value, *, name="vout", statement=".measure tran vout FIND v(out) AT=2m", status=MeasureStatus.OK):
    return SimulationResult(
        executor="spice", file_path="rc.cir", analysis_type="tran", success=True,
        source_digest="0" * 64, analysis_command=".tran 10u 2m 0 5u",
        duration_seconds=0.5,
        measurements=[MeasureResult(name, value, status, statement,
                                    error_message="Not measured" if status is not MeasureStatus.OK else "")],
    )


@pytest.mark.parametrize("before,after,stable", [(0, 0.0009, True), (0, 0.002, False),
                                                  (10, 10.05, True), (10, 10.2, False),
                                                  (-10, -10.05, True)])
def test_stability_uses_absolute_plus_relative_threshold_with_zero_baseline(before, after, stable):
    result = compare_numerical_results(_result(before), _result(after), _spec(), comparable=True)
    assert result["stable"] is stable
    assert result["status"] == ("stable" if stable else "unstable")
    assert result["metrics"][0]["relative_delta"] == (pytest.approx(abs(after - before) / abs(before)) if before else None)
    assert result["cost"] == {"baseline_seconds": 0.5, "refined_seconds": 0.5, "total_seconds": 1, "ratio": 1}


@pytest.mark.parametrize("right", [
    _result(None, status=MeasureStatus.FAILED),
    _result(None, status=MeasureStatus.PARSE_ERROR),
    _result(0, name="missing", statement=".measure tran missing FIND v(out) AT=2m"),
    _result(0, statement=".measure tran vout FIND i(v1) AT=2m"),
    _result(0, statement=".measure tran vout FIND v(out) AT=1m"),
])
def test_failed_missing_or_different_measurement_is_never_stable(right):
    result = compare_numerical_results(_result(0), right, _spec(), comparable=True)
    assert result["status"] == "inconclusive"
    assert result["stable"] is False
    assert result["metrics"][0]["absolute_delta"] is None


def test_all_metrics_require_valid_results_and_matching_units():
    unit_mismatch = _spec(metrics=[{"name": "vout", "unit": "Hz"}])
    assert compare_numerical_results(_result(0), _result(0), unit_mismatch, comparable=True)["status"] == "inconclusive"
    selection = _spec(metrics=[{"name": "vout", "unit": "V"}, {"name": "gain", "unit": "dB"}])
    assert not compare_numerical_results(_result(0), _result(0), selection, comparable=True)["stable"]
    assert compare_numerical_results(_result(0), _result(0), _spec())["status"] == "inconclusive"


@pytest.mark.parametrize("statement", [
    ".measure tran vout FIND v(out)/i(v1) AT=2m",
    ".measure tran vout PARAM='1'",
])
def test_unknown_measurement_dimension_cannot_claim_stability(statement):
    report = compare_numerical_results(_result(1, statement=statement), _result(1, statement=statement),
                                       _spec(), comparable=True)
    assert report["status"] == "inconclusive"
    assert "unit" in report["reason"].casefold()


def test_unit_conversion_keeps_delta_and_absolute_threshold_in_selected_unit():
    selection = _spec(metrics=[{"name": "vout", "unit": "mV", "absolute_tolerance": 2,
                                "relative_tolerance": 0}])
    report = compare_numerical_results(_result(1), _result(1.001), selection, comparable=True)
    assert report["stable"]
    metric = report["metrics"][0]
    assert metric["baseline_value"] == pytest.approx(1000)
    assert metric["refined_value"] == pytest.approx(1001)
    assert metric["absolute_delta"] == pytest.approx(1)
    assert metric["allowed_delta"] == 2


def test_changed_transient_initial_conditions_are_not_comparable():
    right = _result(0)
    right.analysis_command = ".tran 10u 2m 0 2u uic"
    assert compare_numerical_results(_result(0), right, _spec(), comparable=True)["status"] == "inconclusive"


def test_overflowing_difference_and_allowance_are_inconclusive_and_json_safe():
    result = compare_numerical_results(_result(-1e308), _result(1e308), _spec(), comparable=True)
    assert not result["stable"]
    json.dumps(result, allow_nan=False)
    spec = _spec(metrics=[{"name": "vout", "unit": "V", "relative_tolerance": 1e308}])
    result = compare_numerical_results(_result(100), _result(100), spec, comparable=True)
    assert result["status"] == "inconclusive"
    json.dumps(result, allow_nan=False)


def test_native_refinement_respects_maximum_step_and_archived_snapshot(tmp_path):
    if not configure_ngspice():
        pytest.skip("ngspice unavailable")
    executor = SpiceExecutor(timeout_seconds=10)
    if not executor.is_available():
        pytest.skip("ngspice unavailable")
    source = _source(tmp_path, command=".tran 10u 2m uic")
    snapshot = capture_spice_source_snapshot(source)
    baseline_spec, refined_spec = build_numerical_experiments(
        ExperimentSpec(), restore_spice_source_graph(snapshot), _spec(),
    )
    # The two runs consume frozen bytes even after the live circuit changes.
    source.write_text("changed after capture\n.end\n", encoding="utf-8")
    baseline = executor.execute(str(source), experiment=baseline_spec, source_snapshot=snapshot)
    refined = executor.execute(str(source), experiment=refined_spec, source_snapshot=snapshot)
    assert baseline.success, baseline.error
    assert refined.success, refined.error
    assert np.max(np.diff(baseline.data.time)) <= 10e-6 * 1.000001
    assert np.max(np.diff(refined.data.time)) <= 5e-6 * 1.000001
    assert len(refined.data.time) > len(baseline.data.time)
    assert baseline.source_digest != refined.source_digest
    report = compare_numerical_results(baseline, refined, _spec(), comparable=True)
    assert report["status"] == "stable", report
    assert report["cost"]["total_seconds"] > 0
    assert report["metrics"][0]["baseline_value"] == pytest.approx(1 - np.exp(-2), rel=1e-3)
    refined.provenance = copy.deepcopy(refined.provenance)
    refined.provenance["experiment"]["temperature"] = 100
    assert compare_numerical_results(baseline, refined, _spec(), comparable=True)["status"] == "inconclusive"
