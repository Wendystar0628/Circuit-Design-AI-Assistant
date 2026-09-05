from __future__ import annotations

import base64
from pathlib import Path

import numpy as np
import pytest

from domain.simulation.executor.spice_executor import SpiceExecutor
from domain.simulation.models.experiment import ExperimentSpec
from domain.simulation.spice.experiment_deck import compile_experiment_graph
from domain.simulation.spice.source_closure import (
    capture_spice_source_snapshot, collect_spice_source_closure,
    export_spice_source_graph, restore_spice_source_graph,
)
from infrastructure.utils.ngspice_config import configure_ngspice


def _native() -> SpiceExecutor:
    if not configure_ngspice():
        pytest.skip("ngspice unavailable")
    executor = SpiceExecutor(timeout_seconds=5)
    if not executor.is_available():
        pytest.skip("ngspice unavailable")
    return executor


def _divider(tmp_path: Path, extra="") -> Path:
    path = tmp_path / "divider.cir"
    path.write_text(
        "parameter divider\n.param rload = 1k cvalue={1u * 2}\n"
        "V1 in 0 DC 1 AC 1\nR1 in out 1k\nR2 out 0 {rload}\n"
        f"{extra}\n.op\n.end\n", encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("payload", [
    {"parameters": {"r": "{2 * x}"}}, {"parameters": {"r": "1k\n.end"}},
    {"parameters": {"r": float("inf")}}, {"parameters": {"r": True}},
    {"parameters": {"r": "1k", "R": "2k"}}, {"parameters": {"r;stop": "1k"}},
    {"solver_options": {"bogus": 1}}, {"solver_options": {"reltol": 0}},
    {"solver_options": {"abstol": "nan"}}, {"solver_options": {"itl4": 1.5}},
    {"solver_options": {"method": "bogus"}}, {"solver_options": {"maxord": 3}},
    {"solver_options": {"method": "gear", "maxord": 7}},
    {"temperature": -273.15}, {"temperature": float("nan")},
    {"timeout_seconds": 0}, {"timeout_seconds": True},
    {"analysis_command": ".op\n.end"}, {"unknown": 1},
])
def test_experiment_rejects_ambiguous_and_invalid_controls(payload):
    with pytest.raises(ValueError):
        ExperimentSpec.from_dict(payload)


def test_experiment_serialization_and_spice_suffixes():
    experiment = ExperimentSpec(
        parameters={"R": "1Meg", "c": "2.2uF"}, temperature=85,
        solver_options={"method": "GEAR", "maxord": 6, "reltol": "1u", "gmin": 0},
    )
    assert experiment.parameters == {"r": "1Meg", "c": "2.2uF"}
    assert experiment.solver_options["method"] == "gear"
    assert ExperimentSpec.from_dict(experiment.to_dict()) == experiment


def test_parameter_override_changes_numeric_result_without_touching_source(tmp_path):
    source = _divider(tmp_path)
    before = source.read_bytes()
    experiment = ExperimentSpec(parameters={"rload": "3k"}, timeout_seconds=5)
    result = _native().execute(str(source), experiment=experiment)
    assert result.success, result.error
    assert np.asarray(result.data.signals["V(out)"])[0] == pytest.approx(0.75)
    assert source.read_bytes() == before
    assert result.source_digest != collect_spice_source_closure(source).digest
    original = restore_spice_source_graph(result.provenance["original_source"])
    effective = restore_spice_source_graph(result.provenance["effective_source"])
    assert original.main_blob.raw_bytes == before
    assert effective.digest == result.source_digest
    assert ".param rload=3k" in effective.main_blob.source_text
    assert "provenance" not in result.to_dict()


@pytest.mark.parametrize("parameter", ["unknown", "local"])
def test_unknown_and_subcircuit_local_parameters_are_rejected(tmp_path, parameter):
    source = _divider(tmp_path, ".subckt unused a b\n.param local=1k\nRlocal a b {local}\n.ends")
    graph = collect_spice_source_closure(source)
    with pytest.raises(ValueError, match="existing top-level"):
        compile_experiment_graph(graph, ExperimentSpec(parameters={parameter: "2k"}))


def test_explicit_analysis_selects_multianalysis_and_records_measure_omissions(tmp_path):
    source = _divider(tmp_path,
        ".ac lin 3 1k 3k\n.tran 1u 3u\n"
        ".measure ac gain FIND vm(out) AT=1k\n"
        ".measure tran vmax MAX v(out)\n+ FROM=0 TO=3u")
    before = source.read_bytes()
    executor = _native()
    ambiguous = executor.execute(str(source))
    selected = executor.execute(str(source), experiment=ExperimentSpec(analysis_command=".ac lin 3 1k 3k"))
    assert not ambiguous.success
    assert selected.success, selected.error
    assert selected.analysis_type == "ac"
    assert selected.data.frequency.tolist() == pytest.approx([1000, 2000, 3000])
    assert [measure.name for measure in selected.measurements] == ["gain"]
    omitted = selected.provenance["omitted_measurements"]
    assert len(omitted) == 1 and ".measure tran vmax" in omitted[0]["statement"]
    assert "FROM=0" in omitted[0]["statement"]
    assert source.read_bytes() == before


def test_source_solver_controls_and_explicit_temperature_are_executed(tmp_path):
    source = _divider(tmp_path, ".options reltol=1e-4 method=gear maxord=4\n.temp 20")
    executor = _native()
    source_options = executor.execute(str(source))
    result = executor.execute(str(source), experiment=ExperimentSpec(
        temperature=75, solver_options={"reltol": "1e-6", "method": "gear", "maxord": 3},
    ))
    assert source_options.success, source_options.error
    assert result.success, result.error
    main = restore_spice_source_graph(result.provenance["effective_source"]).main_blob.source_text
    assert ".temp 75" in main
    assert "method=gear maxord=3" in main
    assert ".temp 20" in source.read_text(encoding="utf-8")


def test_snapshot_freezes_dependencies_and_runs_after_source_deletion(tmp_path):
    dependency = tmp_path / "parts.inc"
    dependency.write_text(".param resistance=1k\n", encoding="utf-8")
    source = tmp_path / "fixed.cir"
    source.write_text("fixed input\n.include parts.inc\nV1 in 0 1\nR1 in out 1k\nR2 out 0 {resistance}\n.op\n.end\n", encoding="utf-8")
    snapshot = capture_spice_source_snapshot(source)
    assert snapshot["entry_path"] == "@main"
    assert str(tmp_path) not in str(snapshot)
    expected = collect_spice_source_closure(source).digest
    source.unlink()
    dependency.unlink()
    result = _native().execute(str(source), source_snapshot=snapshot)
    assert result.success, result.error
    assert result.source_digest == expected
    assert np.asarray(result.data.signals["V(out)"])[0] == pytest.approx(0.5)
    assert restore_spice_source_graph(export_spice_source_graph(restore_spice_source_graph(snapshot))).digest == expected


def test_tampered_snapshot_is_rejected_without_reading_workspace(tmp_path):
    source = _divider(tmp_path)
    snapshot = capture_spice_source_snapshot(source)
    snapshot["sources"][0]["content_base64"] = base64.b64encode(b"changed\n.op\n.end\n").decode()
    with pytest.raises(ValueError, match="digest"):
        restore_spice_source_graph(snapshot)


def test_explicit_analysis_honors_uppercase_end_with_comment(tmp_path):
    source = tmp_path / "upper.cir"
    source.write_text("upper end\nV1 out 0 1\n.OP\n.END $ finished\n", encoding="utf-8")
    result = _native().execute(str(source), experiment=ExperimentSpec(analysis_command=".op"))
    assert result.success, result.error
