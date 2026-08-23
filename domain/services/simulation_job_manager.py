"""Thread-safe authority for simulation submission and lifecycle state."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple

from domain.simulation.models.simulation_error import (
    SimulationError,
    SimulationErrorType,
)
from domain.simulation.models.simulation_job import (
    DuplicateSimulationJobError,
    JobOrigin,
    JobStatus,
    SimulationJob,
)
from domain.simulation.models.simulation_result import SimulationResult
from shared.event_types import EVENT_SIM_COMPLETE, EVENT_SIM_ERROR, EVENT_SIM_STARTED
from shared.models.load_result import LoadResult
from shared.sim_event_payload import validate_sim_payload


_LOGGER = logging.getLogger(__name__)
_DEFAULT_MAX_WORKERS = 4
_CANCELLED_ERROR_MESSAGE = "Simulation cancelled"


class _SimulationService(Protocol):
    def run_simulation(
        self,
        *,
        file_path: str,
        project_root: str,
        cancel_signal: threading.Event,
        version: int,
        session_id: str,
    ) -> str: ...


class _SimulationResultRepository(Protocol):
    def load(
        self,
        project_root: str,
        result_path: str,
    ) -> LoadResult[SimulationResult]: ...

    def resolve_bundle_dir(
        self,
        project_root: str,
        result_path: str,
    ) -> Optional[Path]: ...


class _EventBus(Protocol):
    def publish(
        self,
        event_type: str,
        data: Any = None,
        source: Optional[str] = None,
    ) -> None: ...


class SimulationJobManager:
    """Own immutable job snapshots, worker scheduling, cancellation and events.

    Dependency composition happens in bootstrap.  The manager accepts one
    fully constructed service and never reaches into a global registry or
    silently constructs alternate executor stacks.
    """

    def __init__(
        self,
        *,
        simulation_service: _SimulationService,
        result_repository: _SimulationResultRepository,
        event_bus: Optional[_EventBus] = None,
        max_workers: int = _DEFAULT_MAX_WORKERS,
    ) -> None:
        if simulation_service is None:
            raise TypeError("simulation_service is required")
        if result_repository is None:
            raise TypeError("result_repository is required")
        if (
            isinstance(max_workers, bool)
            or not isinstance(max_workers, int)
            or max_workers < 1
        ):
            raise ValueError("max_workers must be a positive integer")

        self._service = simulation_service
        self._result_repository = result_repository
        self._event_bus = event_bus
        self._pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="sim-job",
        )

        self._lock = threading.RLock()
        # Terminal state + terminal event are linearized against close.  The
        # RLock is intentional because a headless EventBus may run handlers
        # synchronously and a handler can call close/request_cancel.
        self._publish_lock = threading.RLock()
        self._jobs: Dict[str, SimulationJob] = {}
        self._futures: Dict[str, concurrent.futures.Future[None]] = {}
        self._done_events: Dict[str, threading.Event] = {}
        self._cancel_events: Dict[str, threading.Event] = {}
        self._async_waiters: Dict[
            str, List[Tuple[asyncio.AbstractEventLoop, asyncio.Future[SimulationJob]]]
        ] = {}
        self._active_agent_jobs: Dict[Tuple[str, str], str] = {}
        self._closed = False

    def submit(
        self,
        *,
        circuit_file: str,
        origin: JobOrigin,
        project_root: str,
        version: int = 1,
        session_id: str = "",
    ) -> SimulationJob:
        """Atomically register and schedule one simulation.

        Concurrent agent submissions for the same canonical project circuit
        are rejected inside this method. UI jobs remain explicit user actions
        and may coexist with an agent job or another UI job.
        """

        if not isinstance(origin, JobOrigin):
            raise TypeError(f"origin must be JobOrigin, got {type(origin).__name__}")
        canonical_project, canonical_circuit = _canonical_submission_paths(
            project_root,
            circuit_file,
        )

        job = SimulationJob(
            circuit_file=canonical_circuit,
            origin=origin,
            project_root=canonical_project,
            session_id=session_id,
            version=version,
        )
        done_event = threading.Event()
        cancel_event = threading.Event()
        active_key = _circuit_key(canonical_project, canonical_circuit)

        with self._lock:
            if self._closed:
                raise RuntimeError("SimulationJobManager is closed")
            if origin is JobOrigin.AGENT_TOOL:
                existing_id = self._active_agent_jobs.get(active_key)
                if existing_id is not None:
                    existing = self._jobs[existing_id]
                    if not existing.is_terminal:
                        raise DuplicateSimulationJobError(
                            existing_job_id=existing.job_id,
                            circuit_file=existing.circuit_file,
                            status=existing.status,
                        )
                    self._active_agent_jobs.pop(active_key, None)

            self._jobs[job.job_id] = job
            self._done_events[job.job_id] = done_event
            self._cancel_events[job.job_id] = cancel_event
            self._async_waiters[job.job_id] = []
            if origin is JobOrigin.AGENT_TOOL:
                self._active_agent_jobs[active_key] = job.job_id

            try:
                future = self._pool.submit(
                    self._worker_entry,
                    job.job_id,
                    cancel_event,
                )
            except Exception:
                self._remove_registration_locked(job)
                raise
            self._futures[job.job_id] = future
            future.add_done_callback(
                lambda completed, job_id=job.job_id: self._forget_future(
                    job_id, completed
                )
            )
        return job

    def query(self, job_id: str) -> Optional[SimulationJob]:
        """Return an immutable current snapshot, or ``None`` if unknown."""

        with self._lock:
            return self._jobs.get(job_id)

    def list(
        self,
        *,
        origin: Optional[JobOrigin] = None,
        circuit_file: Optional[str] = None,
        include_terminal: bool = True,
    ) -> List[SimulationJob]:
        """Return immutable snapshots matching the requested filters."""

        if origin is not None and not isinstance(origin, JobOrigin):
            raise TypeError("origin must be JobOrigin or None")
        canonical_filter = None
        if circuit_file is not None:
            if not isinstance(circuit_file, str) or not circuit_file.strip():
                raise ValueError("circuit_file filter must be an absolute path")
            filter_path = Path(circuit_file).expanduser()
            if not filter_path.is_absolute():
                raise ValueError("circuit_file filter must be an absolute path")
            canonical_filter = os.path.normcase(str(filter_path.resolve()))
        with self._lock:
            jobs = tuple(self._jobs.values())
        matches = [
            job
            for job in jobs
            if (origin is None or job.origin is origin)
            and (
                canonical_filter is None
                or os.path.normcase(job.circuit_file) == canonical_filter
            )
            and (include_terminal or not job.is_terminal)
        ]
        return sorted(matches, key=lambda item: item.submitted_at)

    def await_completion(
        self,
        job_id: str,
        timeout: Optional[float] = None,
    ) -> SimulationJob:
        """Block until ``job_id`` reaches a terminal state."""

        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
                raise ValueError("timeout must be a non-negative number or None")
            if timeout < 0:
                raise ValueError("timeout must be non-negative")
        with self._lock:
            job = self._jobs.get(job_id)
            done_event = self._done_events.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        if job.is_terminal:
            return job
        if done_event is None:
            raise RuntimeError(f"Missing completion event for active job {job_id}")
        if not done_event.wait(timeout=timeout):
            raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")
        with self._lock:
            return self._jobs[job_id]

    async def await_completion_async(self, job_id: str) -> SimulationJob:
        """Await terminal state on the caller's event loop."""

        loop = asyncio.get_running_loop()
        future: asyncio.Future[SimulationJob] = loop.create_future()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ValueError(f"Unknown job_id: {job_id}")
            if job.is_terminal:
                return job
            self._async_waiters[job_id].append((loop, future))
        return await future

    def request_cancel(self, job_id: str) -> bool:
        """Cancel queued work immediately or signal a running executor."""

        terminal: Optional[SimulationJob] = None
        with self._publish_lock:
            with self._lock:
                current = self._jobs.get(job_id)
                if current is None or current.is_terminal:
                    return False
                current = current.request_cancellation()
                self._jobs[job_id] = current
                self._cancel_events[job_id].set()
                if current.status is JobStatus.PENDING:
                    terminal = current.cancel()
                    self._store_job_locked(terminal)
                    future = self._futures.get(job_id)
                    if future is not None:
                        future.cancel()

            if terminal is not None:
                self._publish_error(
                    terminal,
                    error_message=_CANCELLED_ERROR_MESSAGE,
                    cancelled=True,
                    duration_seconds=0.0,
                )
                self._notify_terminal(terminal)
        return True

    def close(self, timeout: float = 0.0) -> bool:
        """Stop submissions, cancel all work, and wait up to ``timeout``."""

        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("timeout must be a non-negative number")
        if timeout < 0:
            raise ValueError("timeout must be non-negative")

        cancelled: List[SimulationJob] = []
        first_close = False
        with self._publish_lock:
            with self._lock:
                if not self._closed:
                    first_close = True
                    self._closed = True
                    for job_id, current in tuple(self._jobs.items()):
                        if current.is_terminal:
                            continue
                        current = current.request_cancellation()
                        self._jobs[job_id] = current
                        self._cancel_events[job_id].set()
                        if current.status is JobStatus.PENDING:
                            terminal = current.cancel()
                            self._store_job_locked(terminal)
                            cancelled.append(terminal)
                            future = self._futures.get(job_id)
                            if future is not None:
                                future.cancel()
                futures = tuple(self._futures.values())

            for terminal in cancelled:
                self._publish_error(
                    terminal,
                    error_message=_CANCELLED_ERROR_MESSAGE,
                    cancelled=True,
                    duration_seconds=0.0,
                    allow_closed=True,
                )
                self._notify_terminal(terminal)

        if first_close:
            self._pool.shutdown(wait=False, cancel_futures=True)
        if timeout and futures:
            concurrent.futures.wait(futures, timeout=float(timeout))
        return all(future.done() for future in futures)

    # ------------------------------------------------------------------
    # Worker lifecycle
    # ------------------------------------------------------------------

    def _worker_entry(
        self,
        job_id: str,
        cancel_event: threading.Event,
    ) -> None:
        try:
            self._run_job(
                job_id,
                cancel_event,
            )
        except BaseException as exc:  # keep waiters from hanging on worker bugs
            _LOGGER.exception("Simulation job %s crashed internally", job_id)
            self._finalize_internal_failure(job_id, exc)

    def _run_job(
        self,
        job_id: str,
        cancel_event: threading.Event,
    ) -> None:
        with self._publish_lock:
            with self._lock:
                current = self._jobs[job_id]
                if current.is_terminal:
                    return
                if current.cancel_requested:
                    terminal = current.cancel()
                    self._store_job_locked(terminal)
                else:
                    terminal = None
                    current = current.start()
                    self._jobs[job_id] = current
            if terminal is not None:
                self._publish_error(
                    terminal,
                    error_message=_CANCELLED_ERROR_MESSAGE,
                    cancelled=True,
                    duration_seconds=0.0,
                )
                self._notify_terminal(terminal)
                return
            self._publish_started(current)

        if cancel_event.is_set():
            # Cancellation may have arrived from a synchronous STARTED
            # subscriber before execution began.
            self._finalize_cancelled_without_bundle(job_id, 0.0)
            return

        start = time.monotonic()
        try:
            result_path = self._service.run_simulation(
                file_path=current.circuit_file,
                project_root=current.project_root,
                cancel_signal=cancel_event,
                version=current.version,
                session_id=current.session_id,
            )
        except Exception as exc:
            _LOGGER.exception("Simulation service failed for job %s", job_id)
            self._finalize_service_exception(job_id, exc, time.monotonic() - start)
            return

        duration = time.monotonic() - start
        try:
            result, canonical_result_path, export_root = self._load_persisted_result(
                current,
                result_path,
            )
        except ValueError as exc:
            self._finalize_service_exception(job_id, exc, duration)
            return

        with self._publish_lock:
            with self._lock:
                latest = self._jobs[job_id]
                if result.success:
                    terminal = latest.complete(
                        result_path=canonical_result_path,
                        export_root=export_root,
                    )
                elif (
                    isinstance(result.error, SimulationError)
                    and result.error.type is SimulationErrorType.CANCELLED
                ):
                    terminal = latest.cancel(
                        result_path=canonical_result_path,
                        export_root=export_root,
                    )
                else:
                    terminal = latest.fail(
                        error_message=self._format_error_message(result),
                        result_path=canonical_result_path,
                        export_root=export_root,
                    )
                self._store_job_locked(terminal)

            if terminal.status is JobStatus.COMPLETED:
                self._publish_complete(terminal, duration_seconds=duration)
            else:
                self._publish_error(
                    terminal,
                    error_message=(
                        _CANCELLED_ERROR_MESSAGE
                        if terminal.status is JobStatus.CANCELLED
                        else terminal.error_message or "Unknown simulation error"
                    ),
                    cancelled=terminal.status is JobStatus.CANCELLED,
                    duration_seconds=duration,
                )
            self._notify_terminal(terminal)

    def _load_persisted_result(
        self,
        job: SimulationJob,
        result_path: str,
    ) -> Tuple[SimulationResult, str, str]:
        """Load the service output from the one authoritative document.

        The service intentionally returns no in-memory ``SimulationResult``.
        A lifecycle terminal state is derived only after the exact repository
        handle passes schema, containment, identity and existence checks.
        """

        if not isinstance(result_path, str) or not result_path:
            raise ValueError("simulation service returned no result bundle")
        try:
            loaded = self._result_repository.load(job.project_root, result_path)
        except Exception as exc:
            raise ValueError(
                f"persisted result bundle load raised: {exc}"
            ) from exc
        if not loaded.success or loaded.data is None:
            reason = loaded.error_message or "unknown repository error"
            raise ValueError(
                "simulation service returned no valid bundle "
                "(missing result.json bundle or invalid document): "
                f"{reason}"
            )
        result = loaded.data
        if not isinstance(result, SimulationResult):
            raise ValueError(
                "result repository returned a non-SimulationResult value"
            )
        _validate_persisted_result_identity(job, result)

        try:
            bundle_dir = self._result_repository.resolve_bundle_dir(
                job.project_root,
                result_path,
            )
        except Exception as exc:
            raise ValueError(
                f"persisted result bundle resolution raised: {exc}"
            ) from exc
        if bundle_dir is None or not bundle_dir.is_dir():
            raise ValueError(
                "simulation service returned a missing result.json bundle"
            )
        return result, result_path, str(bundle_dir.resolve(strict=True))

    def _finalize_service_exception(
        self,
        job_id: str,
        exc: Exception,
        duration: float,
    ) -> None:
        message = f"Simulation service failed before producing a valid bundle: {exc}"
        with self._publish_lock:
            with self._lock:
                current = self._jobs[job_id]
                if current.is_terminal:
                    return
                if current.cancel_requested:
                    terminal = current.cancel()
                else:
                    terminal = current.fail(error_message=message)
                self._store_job_locked(terminal)
            self._publish_error(
                terminal,
                error_message=(
                    _CANCELLED_ERROR_MESSAGE
                    if terminal.status is JobStatus.CANCELLED
                    else message
                ),
                cancelled=terminal.status is JobStatus.CANCELLED,
                duration_seconds=duration,
            )
            self._notify_terminal(terminal)

    def _finalize_internal_failure(self, job_id: str, exc: BaseException) -> None:
        message = f"Simulation job worker failed: {type(exc).__name__}: {exc}"
        with self._publish_lock:
            with self._lock:
                current = self._jobs.get(job_id)
                if current is None or current.is_terminal:
                    return
                if current.status is JobStatus.PENDING and not current.cancel_requested:
                    current = current.start()
                terminal = (
                    current.cancel()
                    if current.cancel_requested
                    else current.fail(error_message=message)
                )
                self._store_job_locked(terminal)
            self._publish_error(
                terminal,
                error_message=(
                    _CANCELLED_ERROR_MESSAGE
                    if terminal.status is JobStatus.CANCELLED
                    else message
                ),
                cancelled=terminal.status is JobStatus.CANCELLED,
                duration_seconds=0.0,
            )
            self._notify_terminal(terminal)

    def _finalize_cancelled_without_bundle(self, job_id: str, duration: float) -> None:
        with self._publish_lock:
            with self._lock:
                current = self._jobs[job_id]
                if current.is_terminal:
                    return
                terminal = current.cancel()
                self._store_job_locked(terminal)
            self._publish_error(
                terminal,
                error_message=_CANCELLED_ERROR_MESSAGE,
                cancelled=True,
                duration_seconds=duration,
            )
            self._notify_terminal(terminal)

    # ------------------------------------------------------------------
    # State/index helpers
    # ------------------------------------------------------------------

    def _store_job_locked(self, job: SimulationJob) -> None:
        self._jobs[job.job_id] = job
        if job.is_terminal and job.origin is JobOrigin.AGENT_TOOL:
            key = _circuit_key(job.project_root, job.circuit_file)
            if self._active_agent_jobs.get(key) == job.job_id:
                self._active_agent_jobs.pop(key, None)

    def _remove_registration_locked(self, job: SimulationJob) -> None:
        self._jobs.pop(job.job_id, None)
        self._done_events.pop(job.job_id, None)
        self._cancel_events.pop(job.job_id, None)
        self._async_waiters.pop(job.job_id, None)
        if job.origin is JobOrigin.AGENT_TOOL:
            key = _circuit_key(job.project_root, job.circuit_file)
            if self._active_agent_jobs.get(key) == job.job_id:
                self._active_agent_jobs.pop(key, None)

    def _forget_future(
        self,
        job_id: str,
        future: concurrent.futures.Future[None],
    ) -> None:
        with self._lock:
            if self._futures.get(job_id) is future:
                self._futures.pop(job_id, None)

    def _notify_terminal(self, job: SimulationJob) -> None:
        with self._lock:
            waiters = self._async_waiters.pop(job.job_id, [])
            done_event = self._done_events.pop(job.job_id, None)
            self._cancel_events.pop(job.job_id, None)
        if done_event is not None:
            done_event.set()
        for loop, future in waiters:
            if future.done():
                continue
            try:
                loop.call_soon_threadsafe(self._complete_future, future, job)
            except RuntimeError:
                continue

    @staticmethod
    def _complete_future(
        future: asyncio.Future[SimulationJob],
        job: SimulationJob,
    ) -> None:
        if not future.done():
            future.set_result(job)

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _identity(job: SimulationJob) -> Dict[str, Any]:
        return {
            "job_id": job.job_id,
            "origin": job.origin.value,
            "circuit_file": job.circuit_file,
            "project_root": job.project_root,
            "session_id": job.session_id,
        }

    def _publish_started(
        self,
        job: SimulationJob,
    ) -> None:
        self._publish(
            EVENT_SIM_STARTED,
            self._identity(job),
        )

    def _publish_complete(
        self,
        job: SimulationJob,
        *,
        duration_seconds: float,
    ) -> None:
        self._publish(
            EVENT_SIM_COMPLETE,
            {
                **self._identity(job),
                "result_path": job.result_path or "",
                "export_root": job.export_root or "",
                "duration_seconds": float(duration_seconds),
            },
        )

    def _publish_error(
        self,
        job: SimulationJob,
        *,
        error_message: str,
        cancelled: bool,
        duration_seconds: float,
        allow_closed: bool = False,
    ) -> None:
        self._publish(
            EVENT_SIM_ERROR,
            {
                **self._identity(job),
                "error_message": error_message,
                "result_path": job.result_path or "",
                "export_root": job.export_root or "",
                "cancelled": bool(cancelled),
                "duration_seconds": float(duration_seconds),
            },
            allow_closed=allow_closed,
        )

    def _publish(
        self,
        event_type: str,
        payload: Dict[str, Any],
        *,
        allow_closed: bool = False,
    ) -> None:
        validated = dict(validate_sim_payload(event_type, payload))
        with self._lock:
            if self._closed and not allow_closed:
                return
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(
                event_type,
                validated,
                source="simulation_job_manager",
            )
        except Exception as exc:  # event delivery must not strand waiters
            _LOGGER.warning("Failed to publish %s: %s", event_type, exc)

    @staticmethod
    def _format_error_message(result: SimulationResult) -> str:
        error = result.error
        if isinstance(error, SimulationError):
            return error.message
        if error is not None:
            return str(error)
        return "Unknown simulation error"


def _canonical_submission_paths(project_root: str, circuit_file: str) -> Tuple[str, str]:
    if not isinstance(project_root, str) or not project_root.strip():
        raise ValueError("project_root is required")
    if not isinstance(circuit_file, str) or not circuit_file.strip():
        raise ValueError("circuit_file is required")
    project_input = Path(project_root).expanduser()
    if not project_input.is_absolute():
        raise ValueError("project_root must be an absolute directory")
    project = project_input.resolve()
    if not project.is_dir():
        raise ValueError("project_root must be an existing directory")
    circuit = Path(circuit_file).expanduser()
    if not circuit.is_absolute():
        circuit = project / circuit
    circuit = circuit.resolve()
    try:
        circuit.relative_to(project)
    except ValueError as exc:
        raise ValueError("circuit_file must be inside project_root") from exc
    return str(project), str(circuit)


def _circuit_key(project_root: str, circuit_file: str) -> Tuple[str, str]:
    return os.path.normcase(project_root), os.path.normcase(circuit_file)


def _validate_persisted_result_identity(
    job: SimulationJob,
    result: SimulationResult,
) -> None:
    """Reject cross-job or incomplete persisted output before a terminal event.

    The exact ``result.json`` is the trust boundary. A shared worker must not
    bind another circuit or session to this job; its persisted analysis
    identity must be non-empty and every successful result must carry actual
    structured data.
    """

    if not isinstance(result, SimulationResult):
        raise ValueError("simulation service returned a non-SimulationResult value")
    if type(result.success) is not bool:
        raise ValueError("simulation service returned a non-boolean success flag")
    if result.success and result.data is None:
        raise ValueError("successful simulation result contains no structured data")
    if result.version != job.version:
        raise ValueError(
            "simulation service returned a result for a different job version"
        )
    if result.session_id != job.session_id:
        raise ValueError(
            "simulation service returned a result for a different session"
        )

    actual_analysis = str(result.analysis_type or "").strip().lstrip(".").lower()
    if not actual_analysis:
        raise ValueError("persisted simulation result has no analysis identity")
    raw_file = str(result.file_path or "").strip()
    if not raw_file:
        raise ValueError("simulation service returned a result without circuit identity")
    project = Path(job.project_root).resolve()
    candidate = Path(raw_file).expanduser()
    if not candidate.is_absolute():
        candidate = project / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(project)
    except ValueError as exc:
        raise ValueError(
            "simulation service returned a circuit outside project_root"
        ) from exc
    if os.path.normcase(str(resolved)) != os.path.normcase(job.circuit_file):
        raise ValueError(
            "simulation service returned a result for a different circuit"
        )


__all__ = ["SimulationJobManager"]
