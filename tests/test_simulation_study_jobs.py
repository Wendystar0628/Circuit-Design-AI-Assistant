"""Study identities and terminal hooks preserve ordinary job lifecycle rules."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np
import pytest

from domain.services.simulation_job_manager import SimulationJobManager
from domain.simulation.models.experiment import ExperimentSpec
from domain.simulation.models.simulation_error import (
    ErrorSeverity,
    SimulationError,
    SimulationErrorType,
)
from domain.simulation.models.simulation_job import (
    DuplicateSimulationJobError,
    JobOrigin,
    JobStatus,
)
from domain.simulation.models.simulation_result import (
    SimulationData,
    create_error_result,
    create_success_result,
)
from domain.simulation.service.simulation_result_repository import SimulationResultRepository
from shared.event_types import EVENT_SIM_COMPLETE


class _ControlledService:
    """Block workers while recording independent experiment/result identities."""

    def __init__(self):
        self.lock = threading.Lock()
        self.started = threading.Event()
        self.both_started = threading.Event()
        self.release = threading.Event()
        self.calls = []

    def run_simulation(self, **kwargs):
        with self.lock:
            self.calls.append(kwargs)
            sequence = len(self.calls)
            self.started.set()
            if sequence >= 2:
                self.both_started.set()
        while not self.release.wait(0.01):
            if kwargs["cancel_signal"].is_set():
                break
        identity = {
            "executor": "spice",
            "file_path": kwargs["file_path"],
            "analysis_type": "tran",
            "version": kwargs["version"],
            "session_id": kwargs["session_id"],
        }
        if kwargs["cancel_signal"].is_set():
            result = create_error_result(
                **identity,
                error=SimulationError(
                    type=SimulationErrorType.CANCELLED,
                    severity=ErrorSeverity.LOW,
                    message="cancelled by study",
                    file_path=kwargs["file_path"],
                ),
            )
        else:
            result = create_success_result(
                **identity,
                analysis_command=".tran 1u 10u",
                data=SimulationData(
                    time=np.array([0.0, 1e-5]),
                    signals={"V(out)": np.array([0.0, float(sequence)])},
                    signal_types={"V(out)": "voltage"},
                ),
                source_digest="0" * 64,
            )
        relative = f"simulation_results/amp/case-{sequence}/result.json"
        result_file = Path(kwargs["project_root"]) / relative
        result_file.parent.mkdir(parents=True, exist_ok=True)
        payload = result.to_dict()
        payload["file_path"] = "amp.cir"
        if isinstance(payload.get("error"), dict):
            payload["error"]["file_path"] = "amp.cir"
        result_file.write_text(json.dumps(payload), encoding="utf-8")
        return relative


@pytest.fixture
def job_setup(tmp_path):
    (tmp_path / "amp.cir").write_text(
        ".title Study fixture\n.param supply=5\nV1 out 0 {supply}\nR1 out 0 1k\n.tran 1u 10u\n.end\n",
        encoding="utf-8",
    )
    managers = []

    def build(max_workers=2, event_bus=None):
        service = _ControlledService()
        manager = SimulationJobManager(
            simulation_service=service,
            result_repository=SimulationResultRepository(),
            max_workers=max_workers,
            event_bus=event_bus,
        )
        managers.append((manager, service))
        return manager, service

    yield build
    for manager, service in managers:
        service.release.set()
        manager.close(timeout=2)


def _submit(manager, tmp_path, **kwargs):
    return manager.submit(
        circuit_file="amp.cir",
        project_root=str(tmp_path),
        origin=JobOrigin.AGENT_TOOL,
        **kwargs,
    )


def test_distinct_study_cases_run_concurrently_with_independent_inputs(job_setup, tmp_path):
    manager, service = job_setup()
    first_input = ExperimentSpec(parameters={"supply": "3.3"}, temperature=-40)
    first = _submit(
        manager, tmp_path, study_id="supply-corners", case_id="cold",
        session_id="cold", experiment=first_input,
    )
    second = _submit(
        manager, tmp_path, study_id="supply-corners", case_id="hot",
        session_id="hot", experiment=ExperimentSpec(parameters={"supply": "5"}, temperature=85),
    )
    first_input.parameters["supply"] = "12"
    assert service.both_started.wait(1), "Distinct study cases were serialized"
    with pytest.raises(DuplicateSimulationJobError) as error:
        _submit(manager, tmp_path, study_id="supply-corners", case_id="cold")
    assert error.value.existing_job_id == first.job_id

    context = manager.query_context(first.job_id)
    assert context == {"study_id": "supply-corners", "case_id": "cold"}
    context["case_id"] = "changed"
    assert manager.query_context(first.job_id)["case_id"] == "cold"
    service.release.set()
    first_final = manager.await_completion(first.job_id, timeout=2)
    second_final = manager.await_completion(second.job_id, timeout=2)
    assert first_final.status is second_final.status is JobStatus.COMPLETED
    assert first_final.result_path != second_final.result_path
    inputs = {call["session_id"]: call["experiment"] for call in service.calls}
    assert inputs["cold"].parameters == {"supply": "3.3"}
    assert inputs["hot"].temperature == 85
    assert manager.query_context(first.job_id)["study_id"] == "supply-corners"

    repeated = _submit(manager, tmp_path, study_id="supply-corners", case_id="cold")
    assert repeated.job_id != first.job_id
    assert manager.await_completion(repeated.job_id, timeout=2).status is JobStatus.COMPLETED


def test_same_case_dedup_is_atomic_across_concurrent_submitters(job_setup, tmp_path):
    manager, _ = job_setup()
    barrier = threading.Barrier(3)
    outcomes = []

    def submit():
        barrier.wait()
        try:
            outcomes.append(_submit(manager, tmp_path, study_id="study", case_id="case"))
        except DuplicateSimulationJobError as error:
            outcomes.append(error)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    errors = [outcome for outcome in outcomes if isinstance(outcome, DuplicateSimulationJobError)]
    jobs = [outcome for outcome in outcomes if not isinstance(outcome, DuplicateSimulationJobError)]
    assert len(errors) == len(jobs) == 1
    assert errors[0].existing_job_id == jobs[0].job_id


def test_ordinary_dedup_remains_and_study_identity_does_not_collide(job_setup, tmp_path):
    manager, service = job_setup()
    ordinary = _submit(manager, tmp_path)
    study = _submit(manager, tmp_path, study_id="study", case_id="case")
    assert service.both_started.wait(1)
    with pytest.raises(DuplicateSimulationJobError) as error:
        _submit(manager, tmp_path)
    assert error.value.existing_job_id == ordinary.job_id
    assert ordinary.job_id != study.job_id
    assert manager.query_context(ordinary.job_id) == {"study_id": "", "case_id": ""}
    assert manager.query_context("unknown") is None


@pytest.mark.parametrize("study_id,case_id", [
    ("study", ""), ("", "case"), (None, "case"), ("study", 3),
    ("../study", "case"), ("study", "a/b"), ("study", "a b"),
    ("study", "case\n"), ("study", "a" * 129),
])
def test_invalid_study_identity_is_rejected_before_registration(job_setup, tmp_path, study_id, case_id):
    manager, service = job_setup()
    with pytest.raises(ValueError, match="study_id and case_id"):
        _submit(manager, tmp_path, study_id=study_id, case_id=case_id)
    assert manager.list() == []
    assert service.calls == []


def test_listeners_receive_success_and_cancel_once_without_manager_locks(job_setup, tmp_path, caplog):
    manager, service = job_setup(max_workers=1)
    observed = []
    finished = threading.Event()
    lock_checks = []

    def broken_listener(job):
        raise RuntimeError("listener failure")

    def listener(job):
        # Calling cancellation from another thread needs both lifecycle locks.
        other_thread_finished = threading.Event()
        thread = threading.Thread(
            target=lambda: (manager.request_cancel("unknown"), other_thread_finished.set())
        )
        thread.start()
        lock_checks.append(other_thread_finished.wait(1))
        thread.join(1)
        observed.append((job.job_id, job.status, manager.query_context(job.job_id)))
        if len(observed) == 2:
            finished.set()

    removed = []
    manager.add_terminal_listener(removed.append)
    manager.remove_terminal_listener(removed.append)
    manager.add_terminal_listener(broken_listener)
    manager.add_terminal_listener(listener)
    manager.add_terminal_listener(listener)
    running = _submit(manager, tmp_path, study_id="study", case_id="success")
    assert service.started.wait(1)
    queued = _submit(manager, tmp_path, study_id="study", case_id="cancel")
    assert manager.request_cancel(queued.job_id)
    assert not manager.request_cancel(queued.job_id)
    service.release.set()
    assert finished.wait(2)
    assert {entry[:2] for entry in observed} == {
        (running.job_id, JobStatus.COMPLETED), (queued.job_id, JobStatus.CANCELLED)
    }
    assert all(lock_checks)
    assert not removed
    assert "listener failure" in caplog.text
    assert all(entry[2]["study_id"] == "study" for entry in observed)
    assert manager.await_completion(running.job_id, timeout=2).status is JobStatus.COMPLETED


def test_close_notifies_running_and_queued_cancellation(job_setup, tmp_path):
    manager, service = job_setup(max_workers=1)
    observed = []
    manager.add_terminal_listener(observed.append)
    running = _submit(manager, tmp_path, study_id="closing-study", case_id="running")
    assert service.started.wait(1)
    queued = _submit(manager, tmp_path, study_id="closing-study", case_id="queued")

    assert manager.close(timeout=2)
    assert {job.job_id for job in observed} == {running.job_id, queued.job_id}
    assert all(job.status is JobStatus.CANCELLED for job in observed)
    manager.close(timeout=2)
    assert len(observed) == 2


def test_synchronous_event_close_defers_listeners_until_publication_unlocks(job_setup, tmp_path):
    class ClosingBus:
        manager = None

        def publish(self, event_type, data=None, source=None):
            if event_type == EVENT_SIM_COMPLETE:
                self.manager.close()

    bus = ClosingBus()
    manager, service = job_setup(max_workers=1, event_bus=bus)
    bus.manager = manager
    observed = []
    lock_checks = []
    finished = threading.Event()

    def listener(job):
        other_thread_finished = threading.Event()
        thread = threading.Thread(
            target=lambda: (manager.request_cancel("unknown"), other_thread_finished.set())
        )
        thread.start()
        lock_checks.append(other_thread_finished.wait(1))
        thread.join(1)
        observed.append(job)
        if len(observed) == 2:
            finished.set()

    manager.add_terminal_listener(listener)
    running = _submit(manager, tmp_path, study_id="study", case_id="running")
    assert service.started.wait(1)
    queued = _submit(manager, tmp_path, study_id="study", case_id="queued")
    service.release.set()

    assert finished.wait(3)
    assert all(lock_checks), "A nested close invoked a listener while publication was locked"
    assert {(job.job_id, job.status) for job in observed} == {
        (running.job_id, JobStatus.COMPLETED), (queued.job_id, JobStatus.CANCELLED),
    }


def test_listener_registration_rejects_noncallable(job_setup):
    manager, _ = job_setup()
    with pytest.raises(TypeError, match="callable"):
        manager.add_terminal_listener(None)
