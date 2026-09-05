from __future__ import annotations

import asyncio
import inspect
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pytest

from domain.services.simulation_job_manager import SimulationJobManager
from domain.simulation.models.simulation_error import (
    ErrorSeverity,
    SimulationError,
    SimulationErrorType,
)
from domain.simulation.models.simulation_job import (
    DuplicateSimulationJobError,
    JobOrigin,
    JobStatus,
    SimulationJob,
)
from domain.simulation.models.simulation_result import (
    SimulationData,
    create_error_result,
    create_success_result,
)
from domain.simulation.service.simulation_result_repository import (
    SimulationResultRepository,
)
from shared.event_types import EVENT_SIM_COMPLETE, EVENT_SIM_ERROR, EVENT_SIM_STARTED
from shared.sim_event_payload import extract_sim_payload


_SOURCE_DIGEST = "0" * 64


class _RecordingEventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.events: List[Tuple[str, Dict[str, Any], Optional[str]]] = []

    def publish(self, event_type, data=None, source=None):
        with self._lock:
            self.events.append((event_type, dict(data), source))

    def of(self, event_type: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [payload for kind, payload, _ in self.events if kind == event_type]

    def for_job(self, job_id: str) -> List[Tuple[str, Dict[str, Any]]]:
        with self._lock:
            return [
                (kind, payload)
                for kind, payload, _ in self.events
                if payload["job_id"] == job_id
            ]


class _FakeService:
    def __init__(
        self,
        *,
        success: bool = True,
        delay: float = 0.0,
        raise_exc: Optional[Exception] = None,
        result_path: Optional[str] = None,
        wait_for_cancel: bool = False,
        cancelled_outcome: bool = False,
        write_bundle: bool = True,
    ) -> None:
        self.success = success
        self.delay = delay
        self.raise_exc = raise_exc
        self.result_path = result_path
        self.wait_for_cancel = wait_for_cancel
        self.cancelled_outcome = cancelled_outcome
        self.write_bundle = write_bundle
        self.started = threading.Event()
        self.calls: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def run_simulation(
        self,
        *,
        file_path,
        project_root,
        cancel_signal,
        version,
        session_id,
        experiment,
        source_snapshot,
    ):
        with self._lock:
            self.calls.append(
                {
                    "file_path": file_path,
                    "project_root": project_root,
                    "cancel_signal": cancel_signal,
                    "version": version,
                    "session_id": session_id,
                    "experiment": experiment,
                    "source_snapshot": source_snapshot,
                }
            )
        self.started.set()
        if self.wait_for_cancel or self.cancelled_outcome:
            if self.wait_for_cancel:
                assert cancel_signal.wait(timeout=2.0)
            result = create_error_result(
                executor="spice",
                file_path=file_path,
                analysis_type="tran",
                error=SimulationError(
                    type=SimulationErrorType.CANCELLED,
                    severity=ErrorSeverity.LOW,
                    message="simulation cancelled",
                    file_path=file_path,
                ),
                version=version,
                session_id=session_id,
            )
        else:
            if self.delay:
                time.sleep(self.delay)
            if self.raise_exc is not None:
                raise self.raise_exc
            if self.success:
                result = create_success_result(
                    executor="spice",
                    file_path=file_path,
                    analysis_type="tran",
                    analysis_command=".tran 1e-3 1e-2",
                    data=SimulationData(
                        time=np.array([0.0, 1e-2]),
                        signals={"V(out)": np.array([0.0, 0.0])},
                        signal_types={"V(out)": "voltage"},
                    ),
                    source_digest=_SOURCE_DIGEST,
                    version=version,
                    session_id=session_id,
                )
            else:
                result = create_error_result(
                    executor="spice",
                    file_path=file_path,
                    analysis_type="tran",
                    error=SimulationError(
                        type=SimulationErrorType.CONVERGENCE_DC,
                        severity=ErrorSeverity.MEDIUM,
                        message="operating point did not converge",
                        file_path=file_path,
                    ),
                    version=version,
                    session_id=session_id,
                )
        relative = self.result_path
        if relative is None:
            relative = f"simulation_results/{Path(file_path).stem}/run/result.json"
        if self.write_bundle:
            _write_fake_bundle(project_root, relative, result)
        return relative


class _BlockingFirstService(_FakeService):
    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()

    def run_simulation(self, **kwargs):
        file_path = kwargs["file_path"]
        if Path(file_path).stem == "blocker":
            self.started.set()
            with self._lock:
                self.calls.append(dict(kwargs))
            self.release.wait(timeout=3.0)
            result = create_success_result(
                executor="spice",
                file_path=file_path,
                analysis_type="tran",
                analysis_command=".tran 1e-3 1e-2",
                data=SimulationData(
                    time=np.array([0.0, 1e-2]),
                    signals={"V(out)": np.array([0.0, 0.0])},
                    signal_types={"V(out)": "voltage"},
                ),
                source_digest=_SOURCE_DIGEST,
                version=kwargs["version"],
                session_id=kwargs["session_id"],
            )
            relative = "simulation_results/blocker/run/result.json"
            _write_fake_bundle(
                kwargs["project_root"],
                relative,
                result,
            )
            return relative
        return super().run_simulation(**kwargs)


def _write_fake_bundle(
    project_root: str,
    result_path: str,
    result,
) -> str:
    """Write the minimal real bundle promised by the fake service contract."""

    normalized = result_path.replace("\\", "/")
    if (
        not normalized.startswith("simulation_results/")
        or not normalized.endswith("/result.json")
        or "/../" in f"/{normalized}/"
    ):
        return result_path
    candidate = (Path(project_root) / result_path).resolve()
    try:
        candidate.relative_to(Path(project_root).resolve())
    except ValueError:
        return result_path
    candidate.parent.mkdir(parents=True, exist_ok=True)
    payload = result.to_dict()
    raw_circuit = Path(str(payload["file_path"]))
    resolved_circuit = (
        raw_circuit.resolve()
        if raw_circuit.is_absolute()
        else (Path(project_root) / raw_circuit).resolve()
    )
    payload["file_path"] = resolved_circuit.relative_to(
        Path(project_root).resolve()
    ).as_posix()
    if isinstance(payload.get("error"), dict) and payload["error"].get("file_path") is not None:
        payload["error"]["file_path"] = payload["file_path"]
    candidate.write_text(json.dumps(payload), encoding="utf-8")
    return result_path


@pytest.fixture
def bus():
    return _RecordingEventBus()


@pytest.fixture
def manager_factory(bus):
    managers: List[SimulationJobManager] = []

    def build(service=None, *, max_workers=2):
        manager = SimulationJobManager(
            simulation_service=service or _FakeService(),
            result_repository=SimulationResultRepository(),
            event_bus=bus,
            max_workers=max_workers,
        )
        managers.append(manager)
        return manager

    yield build
    for manager in managers:
        manager.close(timeout=2.0)


def _submit(manager, tmp_path, name="amp.cir", origin=JobOrigin.UI_EDITOR, **kwargs):
    circuit = tmp_path / name
    if not circuit.exists():
        circuit.write_text(".title Lifecycle fixture\nV1 out 0 1\nR1 out 0 1k\n.op\n.end\n", encoding="utf-8")
    return manager.submit(
        circuit_file=name,
        project_root=str(tmp_path),
        origin=origin,
        **kwargs,
    )


def test_constructor_and_submit_reject_invalid_contracts(tmp_path):
    submit_parameters = inspect.signature(SimulationJobManager.submit).parameters
    assert "analysis_config" not in submit_parameters
    assert "cancel_signal" not in submit_parameters

    repository = SimulationResultRepository()
    with pytest.raises(TypeError, match="simulation_service"):
        SimulationJobManager(
            simulation_service=None,  # type: ignore[arg-type]
            result_repository=repository,
        )
    with pytest.raises(TypeError, match="result_repository"):
        SimulationJobManager(
            simulation_service=_FakeService(),
            result_repository=None,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="max_workers"):
        SimulationJobManager(
            simulation_service=_FakeService(),
            result_repository=repository,
            max_workers=0,
        )

    manager = SimulationJobManager(
        simulation_service=_FakeService(),
        result_repository=repository,
    )
    with pytest.raises(ValueError, match="project_root"):
        manager.submit(circuit_file="a.cir", project_root="", origin=JobOrigin.UI_EDITOR)
    with pytest.raises(ValueError, match="absolute directory"):
        manager.submit(
            circuit_file="a.cir",
            project_root="relative-project",
            origin=JobOrigin.UI_EDITOR,
        )
    project_file = tmp_path / "not-a-directory"
    project_file.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="existing directory"):
        manager.submit(
            circuit_file="a.cir",
            project_root=str(project_file),
            origin=JobOrigin.UI_EDITOR,
        )
    with pytest.raises(TypeError, match="origin"):
        manager.submit(
            circuit_file="a.cir",
            project_root=str(tmp_path),
            origin="ui",  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="inside project_root"):
        manager.submit(
            circuit_file=str(tmp_path.parent / "outside.cir"),
            project_root=str(tmp_path),
            origin=JobOrigin.UI_EDITOR,
        )
    manager.close()


def test_success_flow_uses_canonical_identity_and_exact_event_order(
    manager_factory, bus, tmp_path
):
    service = _FakeService()
    manager = manager_factory(service)
    submitted = _submit(
        manager,
        tmp_path,
        version=3,
        session_id="session-a",
    )
    final = manager.await_completion(submitted.job_id, timeout=2.0)

    assert submitted.status is JobStatus.PENDING  # immutable submission snapshot
    assert final.status is JobStatus.COMPLETED
    assert final is manager.query(final.job_id)
    assert Path(final.circuit_file).is_absolute()
    assert Path(final.project_root).is_absolute()
    assert Path(final.export_root or "").is_absolute()
    assert final.session_id == "session-a"
    assert final.version == 3

    events = bus.for_job(final.job_id)
    assert [kind for kind, _ in events] == [EVENT_SIM_STARTED, EVENT_SIM_COMPLETE]
    assert set(events[0][1]) == {
        "job_id",
        "origin",
        "circuit_file",
        "project_root",
        "session_id",
    }
    assert events[1][1]["result_path"] == final.result_path
    assert events[1][1]["export_root"] == final.export_root
    assert "success" not in events[1][1]

    call = service.calls[0]
    assert isinstance(call["cancel_signal"], threading.Event)
    assert call["cancel_signal"].is_set() is False
    assert call["version"] == 3
    assert call["session_id"] == "session-a"


def test_failure_result_keeps_diagnostic_bundle(manager_factory, bus, tmp_path):
    manager = manager_factory(_FakeService(success=False))
    job = _submit(manager, tmp_path, origin=JobOrigin.AGENT_TOOL)
    final = manager.await_completion(job.job_id, timeout=2.0)
    assert final.status is JobStatus.FAILED
    assert final.result_path
    assert final.export_root
    events = bus.for_job(job.job_id)
    assert [kind for kind, _ in events] == [EVENT_SIM_STARTED, EVENT_SIM_ERROR]
    assert events[1][1]["error_message"] == "operating point did not converge"
    assert events[1][1]["cancelled"] is False


@pytest.mark.parametrize(
    "service",
    [
        _FakeService(raise_exc=OSError("disk full")),
        _FakeService(result_path="../escaped/result.json"),
        _FakeService(result_path="simulation_results/bad:bundle/run/result.json"),
        _FakeService(result_path=""),
    ],
)
def test_service_or_bundle_contract_failure_wakes_as_failed(
    manager_factory, bus, tmp_path, service
):
    manager = manager_factory(service)
    job = _submit(manager, tmp_path)
    final = manager.await_completion(job.job_id, timeout=2.0)
    assert final.status is JobStatus.FAILED
    assert final.result_path is None
    error_events = [event for event in bus.for_job(job.job_id) if event[0] == EVENT_SIM_ERROR]
    assert len(error_events) == 1
    assert "valid bundle" in error_events[0][1]["error_message"]


def test_missing_result_file_cannot_publish_false_complete(
    manager_factory, bus, tmp_path
):
    manager = manager_factory(_FakeService(write_bundle=False))
    job = _submit(manager, tmp_path)

    final = manager.await_completion(job.job_id, timeout=2.0)

    assert final.status is JobStatus.FAILED
    assert final.result_path is None
    events = bus.for_job(job.job_id)
    assert [kind for kind, _payload in events] == [
        EVENT_SIM_STARTED,
        EVENT_SIM_ERROR,
    ]
    assert "missing result.json bundle" in events[-1][1]["error_message"]


@pytest.mark.parametrize(
    ("field", "replacement", "expected"),
    [
        ("file_path", "other.cir", "different circuit"),
        ("version", 999, "different job version"),
        ("session_id", "other-session", "different session"),
    ],
)
def test_cross_job_result_identity_cannot_publish_complete(
    manager_factory, bus, tmp_path, field, replacement, expected
):
    class CrossedResultService(_FakeService):
        def run_simulation(self, **kwargs):
            result_path = super().run_simulation(**kwargs)
            result_file = Path(kwargs["project_root"]) / result_path
            payload = json.loads(result_file.read_text(encoding="utf-8"))
            payload[field] = replacement
            result_file.write_text(json.dumps(payload), encoding="utf-8")
            return result_path

    manager = manager_factory(CrossedResultService())
    job = _submit(
        manager,
        tmp_path,
        version=7,
        session_id="expected-session",
    )

    final = manager.await_completion(job.job_id, timeout=2.0)

    assert final.status is JobStatus.FAILED
    assert expected in (final.error_message or "")
    assert [kind for kind, _payload in bus.for_job(job.job_id)] == [
        EVENT_SIM_STARTED,
        EVENT_SIM_ERROR,
    ]


def test_query_list_and_history_return_current_immutable_snapshots(
    manager_factory, tmp_path
):
    manager = manager_factory(_FakeService(delay=0.05), max_workers=2)
    ui = _submit(manager, tmp_path, name="ui.cir")
    agent = _submit(
        manager,
        tmp_path,
        name="agent.cir",
        origin=JobOrigin.AGENT_TOOL,
    )
    assert {item.job_id for item in manager.list(include_terminal=False)} == {
        ui.job_id,
        agent.job_id,
    }
    manager.await_completion(ui.job_id, timeout=2.0)
    manager.await_completion(agent.job_id, timeout=2.0)
    assert manager.list(include_terminal=False) == []
    assert {item.job_id for item in manager.list(origin=JobOrigin.UI_EDITOR)} == {
        ui.job_id
    }
    assert manager.query("missing") is None


def test_sync_timeout_and_multiple_async_waiters(manager_factory, tmp_path):
    manager = manager_factory(_FakeService(delay=0.15))
    job = _submit(manager, tmp_path)
    with pytest.raises(TimeoutError):
        manager.await_completion(job.job_id, timeout=0.01)

    async def wait_both():
        return await asyncio.gather(
            manager.await_completion_async(job.job_id),
            manager.await_completion_async(job.job_id),
        )

    first, second = asyncio.run(wait_both())
    assert first == second
    assert first.status is JobStatus.COMPLETED


def test_pending_cancel_is_immediate_exactly_once_and_never_executes(
    manager_factory, bus, tmp_path
):
    service = _BlockingFirstService()
    manager = manager_factory(service, max_workers=1)
    blocker = _submit(manager, tmp_path, name="blocker.cir")
    assert service.started.wait(timeout=1.0)
    queued = _submit(manager, tmp_path, name="queued.cir")

    assert manager.request_cancel(queued.job_id) is True
    final = manager.await_completion(queued.job_id, timeout=1.0)
    assert final.status is JobStatus.CANCELLED
    assert [kind for kind, _ in bus.for_job(queued.job_id)] == [EVENT_SIM_ERROR]
    assert bus.for_job(queued.job_id)[0][1]["cancelled"] is True
    assert all(Path(call["file_path"]).stem != "queued" for call in service.calls)

    service.release.set()
    manager.await_completion(blocker.job_id, timeout=2.0)


def test_running_cancel_signals_executor_and_preserves_cancel_bundle(
    manager_factory, bus, tmp_path
):
    service = _FakeService(wait_for_cancel=True)
    manager = manager_factory(service)
    job = _submit(manager, tmp_path)
    assert service.started.wait(timeout=1.0)
    assert manager.request_cancel(job.job_id) is True
    final = manager.await_completion(job.job_id, timeout=2.0)

    assert final.status is JobStatus.CANCELLED
    assert final.result_path and final.export_root
    assert [kind for kind, _ in bus.for_job(job.job_id)] == [
        EVENT_SIM_STARTED,
        EVENT_SIM_ERROR,
    ]
    assert bus.for_job(job.job_id)[1][1]["cancelled"] is True
    assert manager.request_cancel(job.job_id) is False


def test_persisted_cancelled_outcome_is_authoritative_without_prior_intent(
    manager_factory,
    bus,
    tmp_path,
):
    service = _FakeService(cancelled_outcome=True)
    manager = manager_factory(service)
    job = _submit(manager, tmp_path)

    final = manager.await_completion(job.job_id, timeout=2.0)

    assert final.status is JobStatus.CANCELLED
    assert final.cancel_requested is False
    assert final.result_path and final.export_root
    assert [kind for kind, _payload in bus.for_job(job.job_id)] == [
        EVENT_SIM_STARTED,
        EVENT_SIM_ERROR,
    ]
    assert bus.for_job(job.job_id)[1][1]["cancelled"] is True


def test_late_cancel_cannot_override_an_already_persisted_success_bundle(
    manager_factory,
    bus,
    tmp_path,
):
    class PersistThenBlockService(_FakeService):
        def __init__(self) -> None:
            super().__init__()
            self.persisted = threading.Event()
            self.release_return = threading.Event()

        def run_simulation(self, **kwargs):
            result_path = super().run_simulation(**kwargs)
            self.persisted.set()
            assert self.release_return.wait(timeout=2.0)
            return result_path

    service = PersistThenBlockService()
    manager = manager_factory(service)
    job = _submit(manager, tmp_path)
    assert service.persisted.wait(timeout=1.0)
    try:
        assert manager.request_cancel(job.job_id) is True
        assert service.calls[0]["cancel_signal"].is_set() is True
    finally:
        service.release_return.set()

    final = manager.await_completion(job.job_id, timeout=2.0)

    assert final.status is JobStatus.COMPLETED
    assert final.cancel_requested is True
    assert final.result_path and final.export_root
    assert [kind for kind, _payload in bus.for_job(job.job_id)] == [
        EVENT_SIM_STARTED,
        EVENT_SIM_COMPLETE,
    ]


def test_agent_same_circuit_dedup_is_atomic_under_concurrent_submit(
    manager_factory, tmp_path
):
    (tmp_path / "amp.cir").write_text(
        ".title Concurrent fixture\nV1 out 0 1\nR1 out 0 1k\n.op\n.end\n",
        encoding="utf-8",
    )
    service = _FakeService(wait_for_cancel=True)
    manager = manager_factory(service, max_workers=2)
    gate = threading.Barrier(3)
    jobs: List[SimulationJob] = []
    errors: List[DuplicateSimulationJobError] = []

    def submit() -> None:
        gate.wait()
        try:
            jobs.append(
                _submit(manager, tmp_path, origin=JobOrigin.AGENT_TOOL)
            )
        except DuplicateSimulationJobError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=submit), threading.Thread(target=submit)]
    for thread in threads:
        thread.start()
    gate.wait()
    for thread in threads:
        thread.join(timeout=2.0)

    assert len(jobs) == len(errors) == 1
    assert errors[0].existing_job_id == jobs[0].job_id
    assert errors[0].status in (JobStatus.PENDING, JobStatus.RUNNING)
    manager.request_cancel(jobs[0].job_id)
    manager.await_completion(jobs[0].job_id, timeout=2.0)

    # Terminal jobs release the key; a new agent run is a fresh identity.
    again = _submit(manager, tmp_path, origin=JobOrigin.AGENT_TOOL)
    assert again.job_id != jobs[0].job_id
    manager.request_cancel(again.job_id)
    manager.await_completion(again.job_id, timeout=2.0)


def test_ui_submissions_are_not_deduplicated(manager_factory, tmp_path):
    manager = manager_factory(_FakeService(delay=0.05), max_workers=2)
    first = _submit(manager, tmp_path)
    second = _submit(manager, tmp_path)
    assert first.job_id != second.job_id
    manager.await_completion(first.job_id, timeout=2.0)
    manager.await_completion(second.job_id, timeout=2.0)


def test_worker_limit_allows_independent_jobs_to_run_concurrently(
    manager_factory, tmp_path
):
    class ParallelService:
        def __init__(self) -> None:
            self._lock = threading.Lock()
            self.entered = 0
            self.both_entered = threading.Event()
            self.release = threading.Event()

        def run_simulation(self, **kwargs):
            with self._lock:
                self.entered += 1
                if self.entered == 2:
                    self.both_entered.set()
            assert self.release.wait(timeout=2.0)
            file_path = kwargs["file_path"]
            result = create_success_result(
                executor="spice",
                file_path=file_path,
                analysis_type="tran",
                analysis_command=".tran 1e-3 1e-2",
                data=SimulationData(
                    time=np.array([0.0, 1e-2]),
                    signals={"V(out)": np.array([0.0, 0.0])},
                    signal_types={"V(out)": "voltage"},
                ),
                source_digest=_SOURCE_DIGEST,
                version=kwargs["version"],
                session_id=kwargs["session_id"],
            )
            relative = f"simulation_results/{Path(file_path).stem}/run/result.json"
            _write_fake_bundle(kwargs["project_root"], relative, result)
            return relative

    service = ParallelService()
    manager = manager_factory(service, max_workers=2)
    first = _submit(manager, tmp_path, name="first.cir")
    second = _submit(manager, tmp_path, name="second.cir")
    assert service.both_entered.wait(timeout=1.0), "jobs were serialized by the manager"
    service.release.set()
    manager.await_completion(first.job_id, timeout=2.0)
    manager.await_completion(second.job_id, timeout=2.0)


def test_close_cancels_running_and_queued_wakes_waiters_and_rejects_submit(
    manager_factory, bus, tmp_path
):
    service = _FakeService(wait_for_cancel=True)
    manager = manager_factory(service, max_workers=1)
    running = _submit(manager, tmp_path, name="running.cir")
    assert service.started.wait(timeout=1.0)
    queued = _submit(
        manager,
        tmp_path,
        name="queued.cir",
        origin=JobOrigin.AGENT_TOOL,
    )

    waiter_result: List[SimulationJob] = []
    waiter = threading.Thread(
        target=lambda: waiter_result.append(
            manager.await_completion(queued.job_id, timeout=2.0)
        )
    )
    waiter.start()
    manager.close(timeout=2.0)
    waiter.join(timeout=1.0)

    assert waiter_result[0].status is JobStatus.CANCELLED
    assert manager.await_completion(running.job_id, timeout=2.0).status is JobStatus.CANCELLED
    assert [kind for kind, _ in bus.for_job(queued.job_id)] == [EVENT_SIM_ERROR]
    # Running terminal events after close are suppressed at the UI boundary.
    assert [kind for kind, _ in bus.for_job(running.job_id)] == [EVENT_SIM_STARTED]
    with pytest.raises(RuntimeError, match="closed"):
        _submit(manager, tmp_path, name="late.cir")
    assert manager.close(timeout=1.0) is True


def test_unexpected_worker_bug_is_terminal_and_wakes_waiters(
    manager_factory, bus, tmp_path, monkeypatch
):
    manager = manager_factory(_FakeService())

    def explode(*args, **kwargs):
        raise RuntimeError("event construction bug")

    monkeypatch.setattr(manager, "_publish_started", explode)
    job = _submit(manager, tmp_path)
    final = manager.await_completion(job.job_id, timeout=2.0)
    assert final.status is JobStatus.FAILED
    assert "event construction bug" in (final.error_message or "")
    assert [kind for kind, _ in bus.for_job(job.job_id)] == [EVENT_SIM_ERROR]


def test_every_emitted_payload_passes_strict_schema(manager_factory, bus, tmp_path):
    success = manager_factory(_FakeService())
    failure = manager_factory(_FakeService(success=False))
    first = _submit(success, tmp_path, name="ok.cir")
    second = _submit(failure, tmp_path, name="bad.cir")
    success.await_completion(first.job_id, timeout=2.0)
    failure.await_completion(second.job_id, timeout=2.0)

    for event_type, payload, source in bus.events:
        extracted = extract_sim_payload(
            event_type,
            {"type": event_type, "data": payload, "source": source, "timestamp": 0.0},
        )
        assert extracted == payload
