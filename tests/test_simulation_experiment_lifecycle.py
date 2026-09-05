"""Submission freezes experiment controls and the complete SPICE source graph."""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path

import numpy as np
import pytest

from domain.services.simulation_job_manager import SimulationJobManager
from domain.services.simulation_service import SimulationService
from domain.simulation.models.experiment import ExperimentSpec
from domain.simulation.models.simulation_job import JobOrigin, JobStatus
from domain.simulation.models.simulation_result import SimulationData, create_success_result
from domain.simulation.service.simulation_result_repository import SimulationResultRepository
from domain.simulation.spice.numeric import parse_spice_number
from domain.simulation.spice.source_closure import (
    SpiceSourceClosureError,
    capture_spice_source_snapshot,
    restore_spice_source_graph,
)
from shared.event_types import EVENT_SIM_COMPLETE, EVENT_SIM_ERROR, EVENT_SIM_STARTED


def _write_circuit(root: Path, name: str = "amp.cir", *, include: bool = False) -> Path:
    circuit = root / name
    dependency = '.include "load.inc"\n' if include else "R1 out 0 {rload}\n"
    circuit.write_text(
        ".title Experiment fixture\n.param rload=1k\nV1 out 0 1\n"
        + dependency
        + ".tran 1u 10u\n.end\n",
        encoding="utf-8",
    )
    return circuit


class _Events:
    def __init__(self):
        self.items = []
        self.lock = threading.Lock()

    def publish(self, event_type, data=None, source=None):
        with self.lock:
            self.items.append((event_type, dict(data)))

    def for_job(self, job_id):
        with self.lock:
            return [(kind, data) for kind, data in self.items if data["job_id"] == job_id]


class _RecordingExecutor:
    """Run the real service/persistence boundary with deterministic numerical output."""

    def __init__(self):
        self.blocker_started = threading.Event()
        self.release = threading.Event()
        self.calls = []
        self.lock = threading.Lock()

    def can_handle(self, file_path):
        return Path(file_path).suffix == ".cir"

    def get_name(self):
        return "spice"

    def get_supported_extensions(self):
        return [".cir"]

    def execute(self, file_path, *, cancel_signal, experiment, source_snapshot):
        if Path(file_path).stem == "blocker":
            self.blocker_started.set()
            assert self.release.wait(timeout=5), "test did not release the queue blocker"
        graph = restore_spice_source_graph(source_snapshot)
        command = experiment.analysis_command or graph.main_analysis_commands[0].statement
        with self.lock:
            self.calls.append({
                "file_path": file_path,
                "experiment": experiment.to_dict(),
                "snapshot": copy.deepcopy(source_snapshot),
                "sources": {blob.source_id: blob.raw_bytes for blob in graph.blobs},
            })
        stop = parse_spice_number(command.split()[2])
        return create_success_result(
            executor="spice", file_path=file_path, analysis_type="tran",
            analysis_command=command, source_digest=graph.digest,
            data=SimulationData(
                time=np.array([0.0, stop]),
                signals={"V(out)": np.array([0.0, 1.0])},
                signal_types={"V(out)": "voltage"},
            ),
        )


@pytest.fixture
def lifecycle(tmp_path):
    executor = _RecordingExecutor()
    events = _Events()
    manager = SimulationJobManager(
        simulation_service=SimulationService(executor=executor),
        result_repository=SimulationResultRepository(),
        event_bus=events,
        max_workers=1,
    )
    yield manager, executor, events
    executor.release.set()
    manager.close(timeout=5)


def _submit(manager, root, name="amp.cir", **kwargs):
    return manager.submit(
        circuit_file=name, project_root=str(root), origin=JobOrigin.UI_EDITOR, **kwargs,
    )


def _block_worker(manager, executor, root):
    _write_circuit(root, "blocker.cir")
    job = _submit(manager, root, "blocker.cir")
    assert executor.blocker_started.wait(timeout=2)
    return job


def _payload(root, final):
    assert final.status is JobStatus.COMPLETED
    assert final.result_path
    return json.loads((root / final.result_path).read_text(encoding="utf-8"))


@pytest.mark.parametrize("bad_source", ["missing_main", "missing_dependency", "malformed_include"])
def test_unreadable_source_is_rejected_before_job_registration(lifecycle, tmp_path, bad_source):
    manager, executor, events = lifecycle
    if bad_source == "missing_dependency":
        _write_circuit(tmp_path, include=True)
    elif bad_source == "malformed_include":
        (tmp_path / "amp.cir").write_text(".title Invalid\n.include\n.tran 1u 10u\n.end\n", encoding="utf-8")

    with pytest.raises(SpiceSourceClosureError):
        _submit(manager, tmp_path)

    assert manager.list() == []
    assert manager._inputs == {}
    assert executor.calls == []
    assert events.items == []
    assert not (tmp_path / "simulation_results").exists()


def test_queued_job_executes_submission_bytes_after_main_and_dependency_edits(lifecycle, tmp_path):
    manager, executor, events = lifecycle
    blocker = _block_worker(manager, executor, tmp_path)
    circuit = _write_circuit(tmp_path, include=True)
    dependency = tmp_path / "load.inc"
    dependency.write_text("R1 out 0 {rload}\n", encoding="utf-8")
    original_main, original_dependency = circuit.read_bytes(), dependency.read_bytes()
    original_snapshot = capture_spice_source_snapshot(circuit)
    queued = _submit(manager, tmp_path, version=9, session_id="frozen-input")
    assert manager.query(queued.job_id).status is JobStatus.PENDING

    circuit.write_text(".title Edited\nV1 out 0 9\nR1 out 0 9k\n.tran 1u 90u\n.end\n", encoding="utf-8")
    dependency.write_text("R1 out 0 99k\n", encoding="utf-8")
    executor.release.set()
    manager.await_completion(blocker.job_id, timeout=5)
    final = manager.await_completion(queued.job_id, timeout=5)

    call = next(call for call in executor.calls if Path(call["file_path"]).name == "amp.cir")
    assert call["sources"]["@main"] == original_main
    assert original_dependency in call["sources"].values()
    assert call["snapshot"] == original_snapshot
    persisted = _payload(tmp_path, final)
    assert persisted["analysis_command"] == ".tran 1u 10u"
    assert persisted["source_digest"] == original_snapshot["digest"]
    assert persisted["file_path"] == "amp.cir"
    assert persisted["version"] == 9
    assert persisted["session_id"] == "frozen-input"
    assert [kind for kind, _ in events.for_job(queued.job_id)] == [EVENT_SIM_STARTED, EVENT_SIM_COMPLETE]
    assert queued.job_id not in manager._inputs


def test_queued_cancel_releases_only_its_input_and_preserves_the_next_experiment(lifecycle, tmp_path):
    manager, executor, events = lifecycle
    blocker = _block_worker(manager, executor, tmp_path)
    _write_circuit(tmp_path)
    cancelled = _submit(manager, tmp_path, experiment=ExperimentSpec(parameters={"rload": "2k"}))
    survivor = _submit(manager, tmp_path, experiment=ExperimentSpec(parameters={"rload": "3k"}))
    assert cancelled.job_id in manager._inputs and survivor.job_id in manager._inputs

    assert manager.request_cancel(cancelled.job_id)
    terminal = manager.await_completion(cancelled.job_id, timeout=2)
    assert terminal.status is JobStatus.CANCELLED
    assert terminal.result_path is None
    assert cancelled.job_id not in manager._inputs
    assert survivor.job_id in manager._inputs
    assert not manager.request_cancel(cancelled.job_id)
    cancellation_events = events.for_job(cancelled.job_id)
    assert [kind for kind, _ in cancellation_events] == [EVENT_SIM_ERROR]
    assert cancellation_events[0][1]["cancelled"] is True

    executor.release.set()
    manager.await_completion(blocker.job_id, timeout=5)
    _payload(tmp_path, manager.await_completion(survivor.job_id, timeout=5))
    amp_calls = [call for call in executor.calls if Path(call["file_path"]).name == "amp.cir"]
    assert len(amp_calls) == 1
    assert amp_calls[0]["experiment"]["parameters"] == {"rload": "3k"}
    assert manager._inputs == {}


def test_same_source_experiments_keep_independent_submitted_controls_and_snapshots(lifecycle, tmp_path):
    manager, executor, _events = lifecycle
    blocker = _block_worker(manager, executor, tmp_path)
    circuit = _write_circuit(tmp_path)
    first_experiment = ExperimentSpec(
        analysis_command=".tran 1u 10u", parameters={"rload": "2k"},
        temperature=25, solver_options={"method": "gear"},
    )
    first_snapshot = capture_spice_source_snapshot(circuit)
    expected_snapshot = copy.deepcopy(first_snapshot)
    first = _submit(
        manager, tmp_path, experiment=first_experiment, source_snapshot=first_snapshot,
        version=1, session_id="experiment-one",
    )
    # Neither a retained UI form value nor a replay payload remains manager-owned.
    first_experiment.parameters["rload"] = "99k"
    first_experiment.solver_options["method"] = "trap"
    first_snapshot["sources"].clear()
    first_snapshot["digest"] = "f" * 64
    circuit.write_text(circuit.read_text(encoding="utf-8").replace("rload=1k", "rload=4k"), encoding="utf-8")
    second_experiment = ExperimentSpec(
        analysis_command=".tran 2u 20u", parameters={"rload": "5k"},
        temperature=75, solver_options={"method": "trap"},
    )
    second_snapshot = capture_spice_source_snapshot(circuit)
    second = _submit(manager, tmp_path, experiment=second_experiment, version=2, session_id="experiment-two")
    assert first.job_id != second.job_id
    executor.release.set()
    manager.await_completion(blocker.job_id, timeout=5)
    first_final = manager.await_completion(first.job_id, timeout=5)
    second_final = manager.await_completion(second.job_id, timeout=5)

    amp_calls = [call for call in executor.calls if Path(call["file_path"]).name == "amp.cir"]
    assert len(amp_calls) == 2
    assert amp_calls[0]["experiment"]["parameters"] == {"rload": "2k"}
    assert amp_calls[0]["experiment"]["solver_options"] == {"method": "gear"}
    assert amp_calls[0]["experiment"]["temperature"] == 25
    assert amp_calls[0]["snapshot"] == expected_snapshot
    assert amp_calls[1]["experiment"] == second_experiment.to_dict()
    assert amp_calls[1]["snapshot"] == second_snapshot
    assert first_final.result_path != second_final.result_path
    first_payload, second_payload = _payload(tmp_path, first_final), _payload(tmp_path, second_final)
    assert first_payload["analysis_command"] == ".tran 1u 10u"
    assert second_payload["analysis_command"] == ".tran 2u 20u"
    assert first_payload["source_digest"] == expected_snapshot["digest"]
    assert second_payload["source_digest"] == second_snapshot["digest"]
    assert first_payload["source_digest"] != second_payload["source_digest"]
    assert first_payload["session_id"] == "experiment-one" and first_payload["version"] == 1
    assert second_payload["session_id"] == "experiment-two" and second_payload["version"] == 2
    assert manager._inputs == {}
