"""Tests for ``SimulationJobManager`` — the single submission channel.

Covers the public API contract (minimal, closed surface), the three
lifecycle events with full identity payloads, sync/async completion
waiters, cancellation semantics for both ``PENDING`` and ``RUNNING``
jobs, and concurrent-job behaviour.

The tests deliberately use fake executors, persistence, and event bus
implementations so no ngspice / Qt / filesystem state is exercised —
the manager's behaviour is purely orchestration and those dependencies
are hidden behind narrow interfaces we can substitute.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from domain.simulation.data.simulation_artifact_persistence import (
    BundlePersistenceResult,
)
from domain.simulation.executor.simulation_executor import SimulationExecutor
from domain.simulation.models.simulation_error import (
    ErrorSeverity,
    SimulationError,
    SimulationErrorType,
)
from domain.simulation.models.simulation_job import (
    JobOrigin,
    JobStatus,
    SimulationJob,
)
from domain.simulation.models.simulation_result import (
    SimulationData,
    SimulationResult,
    create_error_result,
    create_success_result,
)
from domain.services.simulation_job_manager import SimulationJobManager
from shared.event_types import (
    EVENT_SIM_COMPLETE,
    EVENT_SIM_ERROR,
    EVENT_SIM_STARTED,
)
from shared.sim_event_payload import extract_sim_payload


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _RecordingEventBus:
    """Captures ``publish`` calls on the worker thread for assertions.

    The real :class:`shared.event_bus.EventBus` requires a Qt app loop
    to deliver handlers back to the main thread. The manager contract
    is only that it *calls* ``publish`` — delivery is the bus's
    problem. A thread-safe list is enough to observe that contract.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.events: List[Tuple[str, Dict[str, Any], Optional[str]]] = []

    def publish(
        self,
        event_type: str,
        data: Any = None,
        source: Optional[str] = None,
    ) -> None:
        with self._lock:
            self.events.append((event_type, dict(data or {}), source))

    def events_of(self, event_type: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [payload for t, payload, _ in self.events if t == event_type]


class _FakeExecutor(SimulationExecutor):
    """SimulationExecutor double whose behaviour can be scripted per test.

    ``delay`` blocks the worker for the given seconds; ``raise_exc``
    makes ``execute`` throw; ``success`` toggles the SimulationResult
    shape. Cancellation tests use ``delay`` + a :class:`threading.Event`
    bound to the fake to observe that the executor was actually started.
    """

    def __init__(
        self,
        *,
        extension: str = ".fake",
        success: bool = True,
        delay: float = 0.0,
        raise_exc: Optional[Exception] = None,
    ) -> None:
        self._extension = extension
        self._success = success
        self._delay = delay
        self._raise_exc = raise_exc
        self.started_event = threading.Event()
        self.execute_calls = 0

    def get_name(self) -> str:
        return "fake"

    def get_supported_extensions(self) -> List[str]:
        return [self._extension]

    def get_available_analyses(self) -> List[str]:
        return ["tran"]

    def execute(
        self,
        file_path: str,
        analysis_config: Optional[Dict[str, Any]] = None,
    ) -> SimulationResult:
        self.execute_calls += 1
        self.started_event.set()
        if self._delay:
            time.sleep(self._delay)
        if self._raise_exc is not None:
            raise self._raise_exc
        if self._success:
            return create_success_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=(analysis_config or {}).get("analysis_type", "tran"),
                data=SimulationData(),
                duration_seconds=self._delay,
            )
        err = SimulationError(
            code="E_FAKE",
            type=SimulationErrorType.PARAMETER_INVALID,
            severity=ErrorSeverity.HIGH,
            message="simulated failure",
            file_path=file_path,
        )
        return create_error_result(
            executor=self.get_name(),
            file_path=file_path,
            analysis_type="tran",
            error=err,
            duration_seconds=self._delay,
        )


class _FakeRegistry:
    """Minimal ExecutorRegistry stand-in backed by a single fake executor."""

    def __init__(self, executor: Optional[_FakeExecutor]) -> None:
        self._executor = executor

    def get_executor_for_file(self, file_path: str):  # noqa: ANN201 - mirror API
        if self._executor is None:
            return None
        if Path(file_path).suffix.lower() in (
            e.lower() for e in self._executor.get_supported_extensions()
        ):
            return self._executor
        return None

    def get_all_supported_extensions(self) -> List[str]:
        return list(self._executor.get_supported_extensions()) if self._executor else []


class _FakePersistence:
    """Accepts every persist_bundle call and reports a synthetic path.

    Tests that need to assert persistence failure instantiate with
    ``raise_on_persist`` or supply a callable ``on_persist`` hook.
    """

    def __init__(
        self,
        *,
        raise_on_persist: Optional[Exception] = None,
        on_persist=None,
    ) -> None:
        self._raise = raise_on_persist
        self._on_persist = on_persist
        self.calls: List[Tuple[str, SimulationResult, Dict[str, str]]] = []

    def persist_bundle(
        self,
        project_root: str,
        result: SimulationResult,
        metric_targets=None,
    ) -> BundlePersistenceResult:
        self.calls.append((project_root, result, dict(metric_targets or {})))
        if self._raise is not None:
            raise self._raise
        if self._on_persist is not None:
            self._on_persist(project_root, result)
        stem = Path(result.file_path).stem or "circuit"
        export_root = Path(project_root) / "simulation_results" / stem / "ts"
        result_rel = (
            f"simulation_results/{stem}/ts/result.json"
        )
        return BundlePersistenceResult(
            export_root=export_root,
            result_path=result_rel,
            written_files=[str(export_root / "result.json")],
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bus() -> _RecordingEventBus:
    return _RecordingEventBus()


@pytest.fixture
def manager_factory(bus):
    """Factory fixture so each test controls executor/persistence shape.

    The fixture tracks every built manager and closes it at teardown —
    important because the thread pool otherwise lingers across tests
    and occasionally flakes on Windows CI.
    """
    built: List[SimulationJobManager] = []

    def _build(
        *,
        executor: Optional[_FakeExecutor] = None,
        persistence: Optional[_FakePersistence] = None,
        max_workers: int = 2,
    ) -> SimulationJobManager:
        registry = _FakeRegistry(executor)
        mgr = SimulationJobManager(
            executor_registry=registry,
            artifact_persistence=persistence or _FakePersistence(),
            event_bus=bus,
            max_workers=max_workers,
        )
        built.append(mgr)
        return mgr

    yield _build

    for mgr in built:
        mgr.close()


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------


def test_public_api_is_minimal(manager_factory):
    """Guard rail: only the documented public entry points exist.

    The plan locks the manager's public surface to seven names; any
    drift (a stray ``start_task``, ``set_running``, ``is_running``)
    should fail this test immediately.
    """
    manager = manager_factory(executor=_FakeExecutor())
    expected = {
        "submit",
        "query",
        "list",
        "await_completion",
        "await_completion_async",
        "request_cancel",
        "close",
    }
    public = {
        name for name in dir(manager)
        if not name.startswith("_") and callable(getattr(manager, name))
    }
    assert public == expected, (
        "SimulationJobManager exposed unexpected public members: "
        f"{sorted(public - expected)} or dropped expected ones: "
        f"{sorted(expected - public)}"
    )


# ---------------------------------------------------------------------------
# Submit validation
# ---------------------------------------------------------------------------


def test_submit_rejects_empty_circuit_file(manager_factory):
    manager = manager_factory(executor=_FakeExecutor())
    with pytest.raises(ValueError):
        manager.submit(
            circuit_file="",
            origin=JobOrigin.UI_EDITOR,
            project_root="/tmp/project",
        )


def test_submit_rejects_empty_project_root(manager_factory):
    manager = manager_factory(executor=_FakeExecutor())
    with pytest.raises(ValueError):
        manager.submit(
            circuit_file="amp.fake",
            origin=JobOrigin.UI_EDITOR,
            project_root="",
        )


def test_submit_rejects_non_enum_origin(manager_factory):
    manager = manager_factory(executor=_FakeExecutor())
    with pytest.raises(TypeError):
        manager.submit(
            circuit_file="amp.fake",
            origin="ui_editor",  # type: ignore[arg-type]
            project_root="/tmp/project",
        )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_successful_job_flows_through_started_then_complete(
    manager_factory, bus
):
    """End-to-end happy path assertions.

    Verifies the manager drives ``PENDING → RUNNING → COMPLETED``,
    populates ``result_path`` + ``export_root`` on the job from the
    persistence outcome, and emits both events with every identity
    field required by the Step 5 payload schema.
    """
    executor = _FakeExecutor()
    persistence = _FakePersistence()
    manager = manager_factory(executor=executor, persistence=persistence)

    job = manager.submit(
        circuit_file="amp.fake",
        origin=JobOrigin.UI_EDITOR,
        project_root="/tmp/project",
        analysis_config={"analysis_type": "tran"},
    )

    final = manager.await_completion(job.job_id, timeout=2.0)
    assert final.status is JobStatus.COMPLETED
    assert final.result_path == "simulation_results/amp/ts/result.json"
    assert final.export_root is not None and "simulation_results" in final.export_root

    started = bus.events_of(EVENT_SIM_STARTED)
    complete = bus.events_of(EVENT_SIM_COMPLETE)
    assert len(started) == 1
    assert len(complete) == 1

    started_payload = started[0]
    for field in ("job_id", "origin", "circuit_file", "project_root"):
        assert started_payload[field], f"started payload missing {field!r}"
    assert started_payload["job_id"] == job.job_id
    assert started_payload["origin"] == JobOrigin.UI_EDITOR.value
    assert started_payload["circuit_file"] == "amp.fake"
    assert started_payload["project_root"] == "/tmp/project"
    assert started_payload["analysis_type"] == "tran"

    complete_payload = complete[0]
    for field in (
        "job_id", "origin", "circuit_file", "project_root",
        "result_path", "export_root",
    ):
        assert complete_payload[field], f"complete payload missing {field!r}"
    assert complete_payload["job_id"] == job.job_id
    assert complete_payload["success"] is True
    assert complete_payload["result_path"] == final.result_path
    assert complete_payload["export_root"] == final.export_root


def test_executor_failure_emits_sim_error_with_identity_fields(
    manager_factory, bus
):
    executor = _FakeExecutor(success=False)
    manager = manager_factory(executor=executor)

    job = manager.submit(
        circuit_file="amp.fake",
        origin=JobOrigin.AGENT_TOOL,
        project_root="/tmp/project",
    )
    final = manager.await_completion(job.job_id, timeout=2.0)

    assert final.status is JobStatus.FAILED
    errors = bus.events_of(EVENT_SIM_ERROR)
    assert len(errors) == 1
    payload = errors[0]
    assert payload["job_id"] == job.job_id
    assert payload["origin"] == JobOrigin.AGENT_TOOL.value
    assert payload["circuit_file"] == "amp.fake"
    assert payload["project_root"] == "/tmp/project"
    assert payload["cancelled"] is False
    assert payload["error_message"]  # non-empty
    # Failed bundles are persisted too so UI has log artefacts.
    assert payload["result_path"]
    assert payload["export_root"]


def test_executor_without_matching_extension_reports_parameter_error(
    manager_factory, bus
):
    """Registry returns None → manager synthesises a PARAMETER_INVALID error.

    This is distinct from an executor crash because the user-facing
    remediation ("use a different file type") is different.
    """
    executor = _FakeExecutor(extension=".cir")  # won't match .fake
    manager = manager_factory(executor=executor)

    job = manager.submit(
        circuit_file="amp.fake",
        origin=JobOrigin.UI_EDITOR,
        project_root="/tmp/project",
    )
    final = manager.await_completion(job.job_id, timeout=2.0)
    assert final.status is JobStatus.FAILED
    payload = bus.events_of(EVENT_SIM_ERROR)[0]
    assert "No executor supports" in payload["error_message"]


def test_executor_exception_is_captured_as_failed_job(manager_factory, bus):
    executor = _FakeExecutor(raise_exc=RuntimeError("segfault"))
    manager = manager_factory(executor=executor)

    job = manager.submit(
        circuit_file="amp.fake",
        origin=JobOrigin.AGENT_TOOL,
        project_root="/tmp/project",
    )
    final = manager.await_completion(job.job_id, timeout=2.0)
    assert final.status is JobStatus.FAILED
    assert "segfault" in (final.error_message or "")


def test_persistence_failure_surfaces_as_sim_error_even_on_success(
    manager_factory, bus
):
    """If the executor succeeds but persistence blows up, the job must
    land in ``FAILED`` — a job cannot be marked complete without a
    bundle on disk, otherwise downstream read tools chase a path that
    doesn't exist.
    """
    executor = _FakeExecutor(success=True)
    persistence = _FakePersistence(raise_on_persist=OSError("disk full"))
    manager = manager_factory(executor=executor, persistence=persistence)

    job = manager.submit(
        circuit_file="amp.fake",
        origin=JobOrigin.AGENT_TOOL,
        project_root="/tmp/project",
    )
    final = manager.await_completion(job.job_id, timeout=2.0)
    assert final.status is JobStatus.FAILED
    errors = bus.events_of(EVENT_SIM_ERROR)
    assert errors and "bundle persistence failed" in errors[0]["error_message"]


# ---------------------------------------------------------------------------
# Query / list
# ---------------------------------------------------------------------------


def test_query_returns_registered_job_and_none_for_unknown(manager_factory):
    manager = manager_factory(executor=_FakeExecutor())
    job = manager.submit(
        circuit_file="amp.fake",
        origin=JobOrigin.UI_EDITOR,
        project_root="/tmp/project",
    )
    manager.await_completion(job.job_id, timeout=2.0)

    assert manager.query(job.job_id) is job
    assert manager.query("nonexistent-id") is None


def test_list_filters_by_origin_and_circuit_file(manager_factory):
    manager = manager_factory(executor=_FakeExecutor())
    ui_job = manager.submit(
        circuit_file="amp.fake",
        origin=JobOrigin.UI_EDITOR,
        project_root="/tmp/project",
    )
    agent_job = manager.submit(
        circuit_file="amp.fake",
        origin=JobOrigin.AGENT_TOOL,
        project_root="/tmp/project",
    )
    other_job = manager.submit(
        circuit_file="filter.fake",
        origin=JobOrigin.UI_EDITOR,
        project_root="/tmp/project",
    )
    for j in (ui_job, agent_job, other_job):
        manager.await_completion(j.job_id, timeout=2.0)

    ui_jobs = manager.list(origin=JobOrigin.UI_EDITOR)
    assert {j.job_id for j in ui_jobs} == {ui_job.job_id, other_job.job_id}

    amp_jobs = manager.list(circuit_file="amp.fake")
    assert {j.job_id for j in amp_jobs} == {ui_job.job_id, agent_job.job_id}

    amp_ui_jobs = manager.list(
        origin=JobOrigin.UI_EDITOR,
        circuit_file="amp.fake",
    )
    assert [j.job_id for j in amp_ui_jobs] == [ui_job.job_id]


def test_list_can_exclude_terminal_jobs(manager_factory):
    executor = _FakeExecutor(delay=0.2)
    manager = manager_factory(executor=executor, max_workers=2)
    job = manager.submit(
        circuit_file="amp.fake",
        origin=JobOrigin.UI_EDITOR,
        project_root="/tmp/project",
    )
    # Before completion both filters return the job.
    assert manager.list(include_terminal=False) == [job]
    manager.await_completion(job.job_id, timeout=2.0)
    # After completion include_terminal=False hides it.
    assert manager.list(include_terminal=False) == []
    assert manager.list(include_terminal=True) == [job]


# ---------------------------------------------------------------------------
# await_completion (sync)
# ---------------------------------------------------------------------------


def test_await_completion_blocks_until_terminal(manager_factory):
    executor = _FakeExecutor(delay=0.2)
    manager = manager_factory(executor=executor)
    job = manager.submit(
        circuit_file="amp.fake",
        origin=JobOrigin.UI_EDITOR,
        project_root="/tmp/project",
    )
    assert not job.is_terminal
    start = time.monotonic()
    final = manager.await_completion(job.job_id, timeout=2.0)
    elapsed = time.monotonic() - start
    assert final.status is JobStatus.COMPLETED
    assert elapsed >= 0.15  # at least roughly the executor delay


def test_await_completion_raises_timeout(manager_factory):
    executor = _FakeExecutor(delay=1.0)
    manager = manager_factory(executor=executor)
    job = manager.submit(
        circuit_file="amp.fake",
        origin=JobOrigin.UI_EDITOR,
        project_root="/tmp/project",
    )
    with pytest.raises(TimeoutError):
        manager.await_completion(job.job_id, timeout=0.05)
    # Clean up: actually wait for the job so the fake thread doesn't
    # leak into the next test.
    manager.await_completion(job.job_id, timeout=3.0)


def test_await_completion_raises_for_unknown_job(manager_factory):
    manager = manager_factory(executor=_FakeExecutor())
    with pytest.raises(ValueError):
        manager.await_completion("job_missing")


# ---------------------------------------------------------------------------
# await_completion_async
# ---------------------------------------------------------------------------


def test_await_completion_async_wakes_up_async_caller(manager_factory):
    """The async path must wake up inside the caller's own event loop.

    Worker threads flip the ``asyncio.Future`` via
    ``loop.call_soon_threadsafe`` — this test makes sure a coroutine
    registered before completion actually resumes after it.
    """
    executor = _FakeExecutor(delay=0.1)
    manager = manager_factory(executor=executor)
    job = manager.submit(
        circuit_file="amp.fake",
        origin=JobOrigin.UI_EDITOR,
        project_root="/tmp/project",
    )

    async def wait() -> SimulationJob:
        return await manager.await_completion_async(job.job_id)

    final = asyncio.run(wait())
    assert final.status is JobStatus.COMPLETED
    assert final.job_id == job.job_id


def test_await_completion_async_returns_immediately_for_terminal_job(
    manager_factory,
):
    manager = manager_factory(executor=_FakeExecutor())
    job = manager.submit(
        circuit_file="amp.fake",
        origin=JobOrigin.UI_EDITOR,
        project_root="/tmp/project",
    )
    manager.await_completion(job.job_id, timeout=2.0)
    assert job.is_terminal

    async def wait() -> SimulationJob:
        return await manager.await_completion_async(job.job_id)

    final = asyncio.run(wait())
    assert final is job


def test_two_async_waiters_both_resolve(manager_factory):
    executor = _FakeExecutor(delay=0.1)
    manager = manager_factory(executor=executor)
    job = manager.submit(
        circuit_file="amp.fake",
        origin=JobOrigin.UI_EDITOR,
        project_root="/tmp/project",
    )

    async def wait_both():
        return await asyncio.gather(
            manager.await_completion_async(job.job_id),
            manager.await_completion_async(job.job_id),
        )

    first, second = asyncio.run(wait_both())
    assert first.job_id == second.job_id == job.job_id
    assert first.status is JobStatus.COMPLETED


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_cancelling_unknown_job_returns_false(manager_factory):
    manager = manager_factory(executor=_FakeExecutor())
    assert manager.request_cancel("nope") is False


def test_cancelling_pending_job_prevents_execution(manager_factory, bus):
    """PENDING → CANCELLED fast-path: no executor call, SIM_ERROR with
    ``cancelled=True`` payload emitted before the worker would have
    picked the job up.

    The test uses ``max_workers=1`` + a blocker job so the second
    submission is guaranteed to sit in the pool queue when
    ``request_cancel`` runs.
    """
    blocker_release = threading.Event()

    class _BlockerExecutor(_FakeExecutor):
        def execute(self, file_path, analysis_config=None):
            self.execute_calls += 1
            self.started_event.set()
            blocker_release.wait(timeout=2.0)
            return create_success_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type="tran",
                data=SimulationData(),
            )

    blocker = _BlockerExecutor()
    manager = manager_factory(executor=blocker, max_workers=1)
    blocker_job = manager.submit(
        circuit_file="blocker.fake",
        origin=JobOrigin.UI_EDITOR,
        project_root="/tmp/project",
    )
    # Wait until the blocker actually entered execute() — guarantees
    # the single pool thread is busy.
    assert blocker.started_event.wait(timeout=2.0)

    queued_job = manager.submit(
        circuit_file="queued.fake",
        origin=JobOrigin.UI_EDITOR,
        project_root="/tmp/project",
    )

    # At this point queued_job is PENDING in the pool queue.
    assert manager.request_cancel(queued_job.job_id) is True

    # Release the blocker so the pool wraps up.
    blocker_release.set()
    manager.await_completion(blocker_job.job_id, timeout=3.0)

    final = manager.query(queued_job.job_id)
    assert final is not None and final.status is JobStatus.CANCELLED

    errors = bus.events_of(EVENT_SIM_ERROR)
    cancellation = [e for e in errors if e["job_id"] == queued_job.job_id]
    assert len(cancellation) == 1
    payload = cancellation[0]
    assert payload["cancelled"] is True
    assert payload["origin"] == JobOrigin.UI_EDITOR.value
    assert payload["circuit_file"] == "queued.fake"

    # The queued job's executor was never invoked; only the blocker ran.
    assert blocker.execute_calls == 1
    started_for_queued = [
        e for e in bus.events_of(EVENT_SIM_STARTED)
        if e["job_id"] == queued_job.job_id
    ]
    assert started_for_queued == []


def test_cancelling_running_job_finalises_as_cancelled(manager_factory, bus):
    """RUNNING jobs accept the cancel intent; the terminal status
    flips once the executor returns. MVP policy: no forced subprocess
    kill — the executor runs to natural completion but the outcome is
    reported as cancelled.
    """
    executor = _FakeExecutor(delay=0.2)
    manager = manager_factory(executor=executor)
    job = manager.submit(
        circuit_file="amp.fake",
        origin=JobOrigin.UI_EDITOR,
        project_root="/tmp/project",
    )
    # Wait until execute() actually started so we know we're RUNNING,
    # not PENDING.
    assert executor.started_event.wait(timeout=2.0)
    assert manager.request_cancel(job.job_id) is True

    final = manager.await_completion(job.job_id, timeout=3.0)
    assert final.status is JobStatus.CANCELLED

    cancellation = [
        e for e in bus.events_of(EVENT_SIM_ERROR) if e["job_id"] == job.job_id
    ]
    assert cancellation and cancellation[0]["cancelled"] is True


def test_request_cancel_on_terminal_job_returns_false(manager_factory):
    manager = manager_factory(executor=_FakeExecutor())
    job = manager.submit(
        circuit_file="amp.fake",
        origin=JobOrigin.UI_EDITOR,
        project_root="/tmp/project",
    )
    manager.await_completion(job.job_id, timeout=2.0)
    assert manager.request_cancel(job.job_id) is False


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def test_two_jobs_run_in_parallel(manager_factory):
    """Manager's thread pool must genuinely run jobs concurrently.

    With two workers and two jobs that each sleep 0.3s, wall-clock
    should be roughly 0.3s rather than 0.6s. A small margin accounts
    for scheduling overhead on busy CI hosts.
    """
    executor = _FakeExecutor(delay=0.3)
    manager = manager_factory(executor=executor, max_workers=2)
    start = time.monotonic()
    job_a = manager.submit(
        circuit_file="amp.fake",
        origin=JobOrigin.UI_EDITOR,
        project_root="/tmp/project",
    )
    job_b = manager.submit(
        circuit_file="filter.fake",
        origin=JobOrigin.AGENT_TOOL,
        project_root="/tmp/project",
    )
    manager.await_completion(job_a.job_id, timeout=3.0)
    manager.await_completion(job_b.job_id, timeout=3.0)
    elapsed = time.monotonic() - start
    assert elapsed < 0.55, f"expected parallel execution, got {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# Step-5 round-trip: every emitted payload satisfies the authoritative schema
# ---------------------------------------------------------------------------


def _wrap_envelope(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Reproduce the envelope shape that :class:`shared.event_bus.EventBus`
    builds around every published payload, so the helper sees what a
    real subscriber would see at runtime."""
    return {
        "type": event_type,
        "data": payload,
        "timestamp": 0.0,
        "source": "manager",
    }


def test_every_emitted_payload_passes_extract_sim_payload(
    manager_factory, bus
):
    """End-to-end Step-5 contract: each payload published by the
    manager survives the same ``extract_sim_payload`` validator the
    subscribers run, with no missing identity field, on success
    *and* failure paths.

    If a future producer change forgets a field, this test fails
    before any subscriber ever sees the bad payload."""
    success_executor = _FakeExecutor(success=True)
    failure_executor = _FakeExecutor(success=False)

    success_manager = manager_factory(executor=success_executor)
    success_job = success_manager.submit(
        circuit_file="amp.fake",
        origin=JobOrigin.UI_EDITOR,
        project_root="/tmp/project",
    )
    success_manager.await_completion(success_job.job_id, timeout=2.0)

    failure_manager = manager_factory(executor=failure_executor)
    failure_job = failure_manager.submit(
        circuit_file="amp.fake",
        origin=JobOrigin.AGENT_TOOL,
        project_root="/tmp/project",
    )
    failure_manager.await_completion(failure_job.job_id, timeout=2.0)

    event_payloads_per_type = {
        EVENT_SIM_STARTED: bus.events_of(EVENT_SIM_STARTED),
        EVENT_SIM_COMPLETE: bus.events_of(EVENT_SIM_COMPLETE),
        EVENT_SIM_ERROR: bus.events_of(EVENT_SIM_ERROR),
    }

    # Every lifecycle bucket must have at least one payload, otherwise
    # this test would silently regress to a no-op.
    for event_type, payloads in event_payloads_per_type.items():
        assert payloads, f"manager never emitted {event_type}; round-trip is vacuous"

    for event_type, payloads in event_payloads_per_type.items():
        for payload in payloads:
            envelope = _wrap_envelope(event_type, payload)
            extracted = extract_sim_payload(event_type, envelope)
            assert extracted is payload
