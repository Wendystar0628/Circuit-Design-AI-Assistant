"""Corner study inputs, persistence and independent lifecycle contracts."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from domain.simulation.measure.measure_result import MeasureResult, MeasureStatus
from domain.simulation.models.experiment import ExperimentSpec
from domain.simulation.models.simulation_job import SimulationJob
from domain.simulation.models.simulation_result import SimulationResult
from domain.simulation.models.study import expand_corner_cases
from domain.simulation.service.experiment_study_service import ExperimentStudyService
from domain.simulation.spice.source_closure import restore_spice_source_graph
from shared.models.load_result import LoadResult


class _Manager:
    def __init__(self):
        self.jobs = {}
        self.inputs = []
        self.listeners = []
        self.on_submit = None

    def add_terminal_listener(self, callback):
        self.listeners.append(callback)

    def remove_terminal_listener(self, callback):
        self.listeners.remove(callback)

    def submit(self, **kwargs):
        self.inputs.append(copy.deepcopy(kwargs))
        job = SimulationJob(circuit_file=kwargs["circuit_file"], project_root=kwargs["project_root"],
                            origin=kwargs["origin"], session_id=kwargs["session_id"], version=kwargs["version"])
        self.jobs[job.job_id] = job
        if self.on_submit:
            self.on_submit()
        return job

    def query(self, job_id):
        return self.jobs.get(job_id)

    def request_cancel(self, job_id):
        current = self.jobs[job_id]
        if current.is_terminal:
            return False
        current = current.request_cancellation().cancel()
        self.jobs[job_id] = current
        for listener in self.listeners:
            listener(current)
        return True

    def complete(self, job_id, result_path):
        current = self.jobs[job_id].start().complete(
            result_path=result_path, export_root=str(Path(self.jobs[job_id].project_root) / Path(result_path).parent),
        )
        self.jobs[job_id] = current
        for listener in self.listeners:
            listener(current)


class _Repository:
    def __init__(self):
        self.results = {}

    def load(self, project_root, result_path):
        if result_path not in self.results:
            return LoadResult.file_missing(result_path)
        return LoadResult.ok(self.results[result_path], result_path)


@pytest.fixture
def setup_study(tmp_path):
    circuit = tmp_path / "divider.cir"
    circuit.write_text("Divider\n.param vcc=5 rload=1k\nV1 in 0 {vcc}\nR1 in out 1k\nR2 out 0 {rload}\n.tran 1u 10u\n.measure tran vout AVG V(out)\n.end\n", encoding="utf-8")
    manager = _Manager()
    repository = _Repository()
    service = ExperimentStudyService(job_manager=manager, result_repository=repository)
    return tmp_path, circuit, manager, repository, service


def _start(setup_study, **kwargs):
    root, circuit, _manager, _repository, service = setup_study
    return service.create(project_root=str(root), circuit_file=str(circuit), **kwargs)


def test_cartesian_axes_are_distinct_named_parameter_bindings():
    base = ExperimentSpec(parameters={"bias": "1"})
    axes, cases = expand_corner_cases(base, [
        {"kind": "supply", "parameter": "VCC", "values": [3.3, 5]},
        {"kind": "load", "parameter": "RLOAD", "values": ["1k", "2k"]},
        {"kind": "temperature", "values": [-40, 85]},
    ])
    assert len(cases) == 8
    assert len({case["case_id"] for case in cases}) == 8
    assert axes[0].parameter == "vcc"
    assert cases[0]["experiment"]["parameters"] == {"bias": "1", "vcc": "3.3", "rload": "1k"}
    assert cases[-1]["experiment"]["temperature"] == 85
    cases[0]["experiment"]["parameters"]["bias"] = "99"
    assert cases[1]["experiment"]["parameters"]["bias"] == "1"
    assert base.parameters == {"bias": "1"}


@pytest.mark.parametrize("axes", [
    [{"kind": "supply", "values": [3, 5]}],
    [{"kind": "temperature", "parameter": "x", "values": [25]}],
    [{"kind": "parameter", "parameter": "r", "values": ["1k", "1000"]}],
    [{"kind": "parameter", "parameter": "r", "values": [1]}, {"kind": "load", "parameter": "R", "values": [2]}],
    [{"kind": "parameter", "parameter": "r", "values": list(range(9))}, {"kind": "temperature", "values": list(range(8))}],
])
def test_axes_reject_ambiguous_duplicate_and_oversized_inputs(axes):
    with pytest.raises(ValueError):
        expand_corner_cases(ExperimentSpec(), axes)


def test_unknown_supply_binding_rejected_before_submitting_any_job(setup_study):
    with pytest.raises(ValueError, match="existing top-level"):
        _start(setup_study, axes=[{"kind": "supply", "parameter": "unknown", "values": [3.3, 5]}])
    assert setup_study[2].inputs == []
    assert not (setup_study[0] / ".circuit_ai" / "studies").exists()


def test_source_frozen_once_even_when_working_file_changes_during_submission(setup_study):
    root, circuit, manager, _repository, _service = setup_study
    manager.on_submit = lambda: circuit.write_text("Changed\nV1 out 0 99\n.op\n.end\n", encoding="utf-8")
    study = _start(setup_study, axes=[{"kind": "supply", "parameter": "vcc", "values": [3.3, 5]}])
    assert study["status"] == "pending"
    assert len({case["job_id"] for case in study["cases"]}) == 2
    assert len({case["session_id"] for case in study["cases"]}) == 2
    assert manager.inputs[0]["source_snapshot"] == manager.inputs[1]["source_snapshot"]
    assert "vcc=5" in restore_spice_source_graph(manager.inputs[1]["source_snapshot"]).main_blob.source_text
    snapshot = json.loads((root / study["source_snapshot_path"]).read_text(encoding="utf-8"))
    assert snapshot["digest"] == study["source_digest"]


def test_cancel_one_case_preserves_other_jobs_and_manifest_survives_restart(setup_study):
    root, _circuit, manager, repository, service = setup_study
    study = _start(setup_study, axes=[{"kind": "temperature", "values": [25, 85]}])
    cancelled = service.cancel(str(root), study["study_id"], study["cases"][0]["case_id"])
    assert [case["status"] for case in cancelled["cases"]] == ["cancelled", "pending"]
    service.close()
    restored = ExperimentStudyService(job_manager=_Manager(), result_repository=repository).get(str(root), study["study_id"])
    assert [case["status"] for case in restored["cases"]] == ["cancelled", "failed"]
    assert "restart" in restored["cases"][1]["error"]
    assert len(manager.inputs) == 2


def test_listener_persists_results_and_failed_measure_never_becomes_zero(setup_study):
    root, _circuit, manager, repository, service = setup_study
    constraint = {"id": "output", "metric": "vout", "unit": "V", "lower": 1, "upper": 3}
    study = _start(setup_study, experiment=ExperimentSpec(acceptance_constraints=[constraint]),
                   axes=[{"kind": "supply", "parameter": "vcc", "values": [3.3, 5, 6]}])
    for index, (case, value) in enumerate(zip(study["cases"], [1.65, 2.5, None])):
        path = f"simulation_results/divider/run_{index}/result.json"
        measure = MeasureResult(name="vout", value=value, statement=".measure tran vout AVG V(out)",
                                status=MeasureStatus.OK if value is not None else MeasureStatus.FAILED)
        repository.results[path] = SimulationResult(executor="spice", file_path="divider.cir", analysis_type="tran",
                                                   success=True, source_digest="0" * 64, analysis_command=".tran 1u 10u",
                                                   measurements=[measure], duration_seconds=0.1)
        manager.complete(case["job_id"], path)
    # Read disk directly: persistence must not depend on a get/poll call.
    manifest_path = root / ".circuit_ai" / "studies" / study["study_id"] / "study.json"
    completed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert completed["status"] == "completed"
    assert completed["summary"]["acceptance_status"] == "NOT_MEASURED"
    row = completed["summary"]["metrics"][0]
    assert (row["min"], row["max"], row["delta"]) == (1.65, 2.5, 0.8500000000000001)
    assert row["measured_cases"] == 2 and row["unmeasured_cases"] == 1
    assert completed["cases"][2]["metrics"][0]["value"] is None
    assert completed["cases"][2]["acceptance"]["rows"][0]["status"] == "NOT_MEASURED"
    assert service.list(str(root))[0]["study_id"] == study["study_id"]


def test_missing_study_and_path_traversal_are_rejected(setup_study):
    root, _circuit, _manager, _repository, service = setup_study
    with pytest.raises(FileNotFoundError):
        service.get(str(root), "study_" + "0" * 32)
    with pytest.raises(ValueError, match="study_id"):
        service.get(str(root), "../study_" + "0" * 32)


def test_missing_result_does_not_revert_failed_case_to_completed_on_next_read(setup_study):
    root, _circuit, manager, _repository, service = setup_study
    study = _start(setup_study, axes=[{"kind": "temperature", "values": [25]}])
    manager.complete(study["cases"][0]["job_id"], "simulation_results/divider/missing/result.json")
    first = service.get(str(root), study["study_id"])
    second = service.get(str(root), study["study_id"])
    assert first["status"] == second["status"] == "failed"
    assert first["cases"][0]["error"] == second["cases"][0]["error"]


def test_completed_case_keeps_persisted_runtime_across_repeated_polling(setup_study):
    root, _circuit, manager, repository, service = setup_study
    study = _start(setup_study, axes=[{"kind": "temperature", "values": [25]}])
    path = "simulation_results/divider/runtime/result.json"
    repository.results[path] = SimulationResult(
        executor="spice", file_path="divider.cir", analysis_type="tran", success=True,
        source_digest="0" * 64, analysis_command=".tran 1u 10u", duration_seconds=0.797,
    )
    manager.complete(study["cases"][0]["job_id"], path)
    first = service.get(str(root), study["study_id"])
    second = service.get(str(root), study["study_id"])
    assert first["cases"][0]["duration_seconds"] == 0.797
    assert second["cases"][0]["duration_seconds"] == 0.797
    assert first["summary"]["duration_seconds"] == second["summary"]["duration_seconds"] == 0.797
