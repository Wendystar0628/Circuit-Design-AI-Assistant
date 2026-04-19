"""``SimulationJobManager`` — the single submission channel for every
simulation in the codebase.

Responsibilities
----------------

The manager is the **only** way to start a simulation: UI editor
``Run`` clicks, agent ``run_simulation`` tool calls, and any future
batch / test runner all route through :meth:`submit`. Every submission
returns a :class:`~domain.simulation.models.simulation_job.SimulationJob`
whose identity (``job_id`` + ``origin`` + ``circuit_file``) becomes the
primary key for every later interaction:

- **Query lifecycle**: :meth:`query` / :meth:`list`.
- **Wait for completion**: :meth:`await_completion` (blocking, for
  sync contexts and tests) or :meth:`await_completion_async` (for
  ``asyncio`` callers such as agent tools).
- **Request cancellation**: :meth:`request_cancel` (advisory — see
  "Cancellation semantics" below).

Internally the manager owns three pieces of infrastructure:

1. A ``ThreadPoolExecutor`` for concurrent execution. Two jobs
   targeting *different* circuits run in parallel; the per-job worker
   still runs its executor + persistence steps sequentially inside one
   pool thread.
2. An index of :class:`SimulationJob` instances keyed by ``job_id``.
   Jobs are kept in the index forever for MVP — Step 5/10 of the
   roadmap will add a retention policy if the backlog becomes an
   issue.
3. Per-job synchronisation primitives: one ``threading.Event`` for
   sync waiters, and an ``asyncio.Future`` list for async waiters.
   The async completion path **must** cross threads through
   ``loop.call_soon_threadsafe`` — setting an ``asyncio.Future`` from
   a background thread directly raises ``RuntimeError: non-thread-safe``.

Authoritative event broadcasting
--------------------------------

Simulation lifecycle events (``EVENT_SIM_STARTED`` /
``EVENT_SIM_COMPLETE`` / ``EVENT_SIM_ERROR``) are published **only by
the manager**. The payload carries every identity field downstream
subscribers need to route by ``job_id`` + ``origin``: ``job_id``,
``origin``, ``circuit_file``, ``project_root``, ``result_path``,
``export_root``, plus the usual body (``duration_seconds``,
``error_message`` / ``cancelled`` on failure).

The manager never blocks on ``EventBus.publish`` because the bus
itself ferries handlers onto the Qt main thread via
``QMetaObject.invokeMethod`` (see ``shared/event_bus.py``). Worker
threads simply call ``publish`` and move on.

Cancellation semantics (MVP)
----------------------------

``request_cancel`` is advisory, not surgical:

- ``PENDING`` jobs that have not yet been picked up by a worker are
  cancelled outright: the pool's ``Future.cancel()`` returns ``True``,
  the job transitions ``PENDING -> CANCELLED``, and an ``EVENT_SIM_ERROR``
  is emitted with ``cancelled=True``.
- ``RUNNING`` jobs only get their ``cancel_requested`` flag set. The
  worker's executor (ngspice / python sub-process) keeps running
  until natural completion; the manager checks the intent flag once
  the executor returns and, if set, reports the outcome as cancelled
  regardless of success/failure. Forcefully killing the subprocess is
  a known follow-up and deliberately not implemented here.

Public API contract
-------------------

The public method table is intentionally minimal — exactly::

    submit / query / list / await_completion /
    await_completion_async / request_cancel / close

Anything that looks like ``start_task`` / ``run_simulation_compat`` /
``set_running`` / ``is_running`` is a design smell: the manager
exposes lifecycle only through :meth:`query`. The rest of the codebase
enforces this by importing only the methods above.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
from pathlib import PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Tuple

from domain.services.simulation_service import SimulationService
from domain.simulation.data.simulation_artifact_persistence import (
    SimulationArtifactPersistence,
)
from domain.simulation.executor.executor_registry import ExecutorRegistry
from domain.simulation.models.simulation_error import SimulationError
from domain.simulation.models.simulation_job import (
    JobOrigin,
    JobStatus,
    SimulationJob,
)
from domain.simulation.models.simulation_result import SimulationResult
from shared.event_bus import EventBus
from shared.event_types import (
    EVENT_SIM_COMPLETE,
    EVENT_SIM_ERROR,
    EVENT_SIM_STARTED,
)


_LOGGER = logging.getLogger(__name__)

_DEFAULT_MAX_WORKERS = 4
_CANCELLED_ERROR_MESSAGE = "Simulation cancelled"


class SimulationJobManager:
    """Concurrent, origin-aware submission and lifecycle manager.

    See module docstring for the full responsibility set and cancel
    semantics. Construction is deliberately lightweight: in production
    the application ``bootstrap`` builds exactly one instance and
    registers it under ``SVC_SIMULATION_JOB_MANAGER``.
    """

    def __init__(
        self,
        *,
        simulation_service: Optional[SimulationService] = None,
        executor_registry: Optional[ExecutorRegistry] = None,
        artifact_persistence: Optional[SimulationArtifactPersistence] = None,
        event_bus: Optional[EventBus] = None,
        max_workers: int = _DEFAULT_MAX_WORKERS,
    ) -> None:
        if simulation_service is not None and (
            executor_registry is not None or artifact_persistence is not None
        ):
            raise ValueError(
                "Pass either simulation_service or "
                "(executor_registry, artifact_persistence) — not both; the "
                "registry and persistence belong on the service instance."
            )
        self._service = simulation_service or SimulationService(
            registry=executor_registry,
            artifact_persistence=artifact_persistence,
        )
        self._explicit_event_bus = event_bus
        self._pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)),
            thread_name_prefix="sim-job",
        )

        self._lock = threading.Lock()
        self._jobs: Dict[str, SimulationJob] = {}
        self._futures: Dict[str, concurrent.futures.Future] = {}
        self._done_events: Dict[str, threading.Event] = {}
        self._async_waiters: Dict[
            str, List[Tuple[asyncio.AbstractEventLoop, asyncio.Future]]
        ] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(
        self,
        *,
        circuit_file: str,
        origin: JobOrigin,
        project_root: str,
        analysis_config: Optional[Mapping[str, Any]] = None,
        metric_targets: Optional[Mapping[str, str]] = None,
        version: int = 1,
        session_id: str = "",
    ) -> SimulationJob:
        """Register a new job and hand it to the worker pool.

        Returns the :class:`SimulationJob` with ``status == PENDING``.
        The caller keeps the ``job_id`` as the primary key for later
        queries / cancellations.
        """
        if not circuit_file:
            raise ValueError("circuit_file is required")
        if not project_root:
            raise ValueError(
                "project_root is required; every job persists a bundle under "
                "<project_root>/simulation_results/"
            )
        if not isinstance(origin, JobOrigin):
            raise TypeError(
                f"origin must be JobOrigin, got {type(origin).__name__}"
            )

        job = SimulationJob(
            circuit_file=circuit_file,
            origin=origin,
            project_root=project_root,
        )
        done_event = threading.Event()
        with self._lock:
            self._jobs[job.job_id] = job
            self._done_events[job.job_id] = done_event
            self._async_waiters[job.job_id] = []

        config_snapshot: Dict[str, Any] = dict(analysis_config or {})
        targets_snapshot: Dict[str, str] = dict(metric_targets or {})

        future = self._pool.submit(
            self._run_job,
            job,
            config_snapshot,
            targets_snapshot,
            version,
            session_id,
        )
        with self._lock:
            self._futures[job.job_id] = future
        return job

    def query(self, job_id: str) -> Optional[SimulationJob]:
        """Return the job with ``job_id`` or ``None`` if unknown."""
        with self._lock:
            return self._jobs.get(job_id)

    def list(
        self,
        *,
        origin: Optional[JobOrigin] = None,
        circuit_file: Optional[str] = None,
        include_terminal: bool = True,
    ) -> List[SimulationJob]:
        """Return jobs matching the given filters, submission-time ordered.

        Filters combine with AND semantics; ``None`` means "don't
        filter on this axis". ``include_terminal=False`` drops jobs
        that have already reached a terminal status so UIs can render
        just the live queue.
        """
        with self._lock:
            jobs = list(self._jobs.values())
        matches: List[SimulationJob] = []
        for job in jobs:
            if origin is not None and job.origin is not origin:
                continue
            if circuit_file is not None and job.circuit_file != circuit_file:
                continue
            if not include_terminal and job.is_terminal:
                continue
            matches.append(job)
        matches.sort(key=lambda j: j.submitted_at)
        return matches

    def await_completion(
        self,
        job_id: str,
        timeout: Optional[float] = None,
    ) -> SimulationJob:
        """Block the calling thread until the job terminates.

        ``timeout`` is honoured verbatim; a timeout raises
        :class:`TimeoutError`. Intended for sync contexts (tests, CLI
        helpers). Async callers use :meth:`await_completion_async`.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            event = self._done_events.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        if job.is_terminal:
            return job
        if event is None:
            raise RuntimeError(
                f"Missing done event for job {job_id}; inconsistent state"
            )
        if not event.wait(timeout=timeout):
            raise TimeoutError(
                f"Job {job_id} did not complete within {timeout}s"
            )
        with self._lock:
            return self._jobs[job_id]

    async def await_completion_async(self, job_id: str) -> SimulationJob:
        """Await completion on the caller's running event loop.

        Each call creates a fresh ``asyncio.Future`` tied to the
        caller's loop. Worker threads complete it via
        ``loop.call_soon_threadsafe`` — the only thread-safe way to
        resolve a ``Future`` from outside its owner loop.
        """
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        if job.is_terminal:
            return job

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        with self._lock:
            # Re-check under lock: the worker may have just flipped the
            # job to terminal between the optimistic check above and
            # us registering as a waiter.
            current = self._jobs[job_id]
            if current.is_terminal:
                return current
            self._async_waiters[job_id].append((loop, future))
        return await future

    def request_cancel(self, job_id: str) -> bool:
        """Register the caller's intent to cancel ``job_id``.

        Returns ``True`` if the intent was registered (job exists and
        is non-terminal), ``False`` otherwise. ``PENDING`` jobs whose
        ``Future`` can still be pulled off the pool queue are finalised
        here and emit ``EVENT_SIM_ERROR(cancelled=True)`` before the
        method returns.
        """
        terminal_job: Optional[SimulationJob] = None
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.is_terminal:
                return False
            job.request_cancel()
            future = self._futures.get(job_id)
            if (
                job.status is JobStatus.PENDING
                and future is not None
                and future.cancel()
            ):
                # Future was queued but not yet started; safely
                # transition the job straight to CANCELLED so waiters
                # can stop blocking immediately.
                job.mark_cancelled()
                terminal_job = job
        if terminal_job is not None:
            self._publish_error(
                terminal_job,
                error_message=_CANCELLED_ERROR_MESSAGE,
                cancelled=True,
                result_path="",
                export_root="",
                duration_seconds=0.0,
            )
            self._notify_terminal(terminal_job)
        return True

    def close(self) -> None:
        """Shut down the worker pool.

        Intended for application exit / test teardown. Pending jobs
        get their futures cancelled; running jobs are allowed to finish
        naturally so in-flight ngspice subprocesses are not left in a
        half-dead state. This is not one of the business lifecycle
        methods — it exists purely for resource hygiene.
        """
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------
    # Worker path
    # ------------------------------------------------------------------

    def _run_job(
        self,
        job: SimulationJob,
        analysis_config: Dict[str, Any],
        metric_targets: Dict[str, str],
        version: int,
        session_id: str,
    ) -> None:
        """Thread-pool worker for a single job.

        Delegates the executor → persist chain to
        :class:`SimulationService` (the one place allowed to touch
        those two collaborators) and translates the resulting
        ``(SimulationResult, result_path)`` tuple plus cancel intent
        into the three lifecycle events. Exceptions from persistence
        surface as ``EVENT_SIM_ERROR`` — this worker never propagates
        them back to the pool future.
        """
        # Cancellation preempted us before we could even start.
        if job.cancel_requested:
            self._finalize_cancelled(job, duration_seconds=0.0)
            return

        try:
            job.mark_running()
        except ValueError:
            # Job already terminal (concurrent cancel beat us to it).
            return

        start_time = time.time()
        self._publish_started(job, analysis_config=analysis_config)

        try:
            result, result_path = self._service.run_simulation(
                file_path=job.circuit_file,
                analysis_config=analysis_config,
                project_root=job.project_root,
                version=version,
                session_id=session_id,
                metric_targets=metric_targets,
            )
        except Exception as exc:
            # The service swallows executor failures into error-shaped
            # results and only raises when persistence itself blew up
            # (or some truly unexpected bug slipped through). Either
            # way: no bundle on disk → the job must be FAILED, not
            # silently "completed".
            _LOGGER.exception(
                "SimulationJob[%s] crashed while running service: %s",
                job.job_id,
                exc,
            )
            duration = time.time() - start_time
            err_msg = f"Simulation bundle persistence failed: {exc}"
            job.mark_failed(error_message=err_msg)
            self._publish_error(
                job,
                error_message=err_msg,
                cancelled=False,
                result_path="",
                export_root="",
                duration_seconds=duration,
            )
            self._notify_terminal(job)
            return

        duration = time.time() - start_time
        export_root = _derive_export_root(result_path)

        # Cancellation observed *after* the executor returned: ignore
        # the outcome and record the job as CANCELLED. The bundle on
        # disk stays (useful for post-mortem) but the event payload
        # tells subscribers this run doesn't count.
        if job.cancel_requested:
            job.mark_cancelled()
            self._publish_error(
                job,
                error_message=_CANCELLED_ERROR_MESSAGE,
                cancelled=True,
                result_path=result_path,
                export_root=export_root,
                duration_seconds=duration,
            )
            self._notify_terminal(job)
            return

        if not result.success:
            err_msg = self._format_error_message(result)
            job.mark_failed(error_message=err_msg)
            self._publish_error(
                job,
                error_message=err_msg,
                cancelled=False,
                result_path=result_path,
                export_root=export_root,
                duration_seconds=duration,
            )
            self._notify_terminal(job)
            return

        if not result_path or not export_root:
            # Persistence is mandatory for a completed job — a "success"
            # without a bundle is nonsensical and should surface as an
            # error so downstream read tools don't chase a missing path.
            err_msg = "Simulation succeeded but bundle persistence failed"
            job.mark_failed(error_message=err_msg)
            self._publish_error(
                job,
                error_message=err_msg,
                cancelled=False,
                result_path=result_path,
                export_root=export_root,
                duration_seconds=duration,
            )
            self._notify_terminal(job)
            return

        job.mark_completed(result_path=result_path, export_root=export_root)
        self._publish_complete(
            job,
            result=result,
            duration_seconds=duration,
        )
        self._notify_terminal(job)

    # ------------------------------------------------------------------
    # Event dispatch
    # ------------------------------------------------------------------

    def _publish_started(
        self,
        job: SimulationJob,
        *,
        analysis_config: Dict[str, Any],
    ) -> None:
        payload = {
            "job_id": job.job_id,
            "origin": job.origin.value,
            "circuit_file": job.circuit_file,
            "project_root": job.project_root,
            "analysis_type": str(analysis_config.get("analysis_type", "")),
            "config": dict(analysis_config),
        }
        self._publish(EVENT_SIM_STARTED, payload)

    def _publish_complete(
        self,
        job: SimulationJob,
        *,
        result: SimulationResult,
        duration_seconds: float,
    ) -> None:
        payload = {
            "job_id": job.job_id,
            "origin": job.origin.value,
            "circuit_file": job.circuit_file,
            "project_root": job.project_root,
            "result_path": job.result_path or "",
            "export_root": job.export_root or "",
            "success": bool(result.success),
            "duration_seconds": float(duration_seconds),
        }
        self._publish(EVENT_SIM_COMPLETE, payload)

    def _publish_error(
        self,
        job: SimulationJob,
        *,
        error_message: str,
        cancelled: bool,
        result_path: str,
        export_root: str,
        duration_seconds: float,
    ) -> None:
        payload = {
            "job_id": job.job_id,
            "origin": job.origin.value,
            "circuit_file": job.circuit_file,
            "project_root": job.project_root,
            "error_message": error_message,
            "cancelled": bool(cancelled),
            "result_path": result_path,
            "export_root": export_root,
            "duration_seconds": float(duration_seconds),
        }
        self._publish(EVENT_SIM_ERROR, payload)

    def _publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        bus = self._resolve_event_bus()
        if bus is None:
            return
        try:
            bus.publish(event_type, payload, source="simulation_job_manager")
        except Exception as exc:  # pragma: no cover - defensive
            _LOGGER.warning(
                "SimulationJobManager failed to publish %s: %s",
                event_type,
                exc,
            )

    def _resolve_event_bus(self) -> Optional[EventBus]:
        if self._explicit_event_bus is not None:
            return self._explicit_event_bus
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_EVENT_BUS

            return ServiceLocator.get_optional(SVC_EVENT_BUS)
        except Exception:  # pragma: no cover
            return None

    # ------------------------------------------------------------------
    # Waiter notification
    # ------------------------------------------------------------------

    def _notify_terminal(self, job: SimulationJob) -> None:
        """Wake every waiter registered against ``job.job_id``.

        ``asyncio`` futures are completed via
        ``loop.call_soon_threadsafe`` — setting them directly from a
        worker thread is unsafe and Python logs a big warning if we
        try. ``threading.Event`` is thread-safe and fires every
        ``await_completion`` blocker at once.
        """
        with self._lock:
            waiters = self._async_waiters.pop(job.job_id, [])
            done_event = self._done_events.get(job.job_id)
        for loop, future in waiters:
            if future.done():
                continue
            try:
                loop.call_soon_threadsafe(self._complete_future, future, job)
            except RuntimeError:
                # The loop has already been closed (e.g. async caller
                # bailed out before awaiting). There's nothing to
                # deliver so drop the future silently — it will never
                # be awaited.
                continue
        if done_event is not None:
            done_event.set()

    @staticmethod
    def _complete_future(future: asyncio.Future, job: SimulationJob) -> None:
        if not future.done():
            future.set_result(job)

    def _finalize_cancelled(
        self,
        job: SimulationJob,
        *,
        duration_seconds: float,
    ) -> None:
        """Fast-path cancellation for a job whose worker never got to
        flip it into ``RUNNING``.

        Guards against the race where ``request_cancel`` set the intent
        flag a moment before the pool scheduled the worker: the worker
        notices the flag on entry and finalises here without starting
        the executor.
        """
        try:
            job.mark_cancelled()
        except ValueError:  # pragma: no cover - defensive
            return
        self._publish_error(
            job,
            error_message=_CANCELLED_ERROR_MESSAGE,
            cancelled=True,
            result_path="",
            export_root="",
            duration_seconds=duration_seconds,
        )
        self._notify_terminal(job)

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_error_message(result: SimulationResult) -> str:
        err = result.error
        if isinstance(err, SimulationError):
            return err.message or (err.type.value if err.type else "")
        if err is not None:
            return str(err)
        return "Unknown simulation error"


def _derive_export_root(result_path: str) -> str:
    """Return the bundle directory that contains ``result_path``.

    Job events and :class:`SimulationJob.export_root` carry the
    project-relative POSIX path of the bundle directory. The
    persistence layer only surfaces ``result_path`` in the
    ``(result, result_path)`` return tuple, so the manager computes
    ``export_root`` by taking its parent — they are always sibling
    values, never re-assembled from separate sources.
    """
    if not result_path:
        return ""
    parent = PurePosixPath(result_path).parent
    return "" if str(parent) in ("", ".") else str(parent)


__all__ = [
    "SimulationJobManager",
]
