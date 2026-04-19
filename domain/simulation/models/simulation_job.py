"""``SimulationJob`` — authoritative entity for a single simulation run.

A ``SimulationJob`` is the one and only way the codebase talks about
"a simulation". Any code that needs to reference, forward, persist, or
query the lifecycle of a run holds the ``job_id`` (or a full
``SimulationJob`` instance) — never a standalone boolean such as
``is_running`` or a shared "current simulation" slot.

The class is a **pure domain object**: no Qt, no EventBus, no
``ServiceLocator``. It knows only its own state machine. The
``SimulationJobManager`` (introduced in the next implementation step)
owns the thread-safe index of live jobs and the broadcasting of
lifecycle events; the ``SimulationService`` stays on the execution
side and reports back through manager hooks. This separation keeps
``SimulationJob`` importable from any layer — tests, headless
pipelines, and the agent tool boundary all use the exact same type.

Immutability contract
---------------------

A job is mutable between ``PENDING`` and either ``RUNNING`` or a
terminal status. Once it reaches a terminal state (``COMPLETED`` /
``FAILED`` / ``CANCELLED``) it is frozen: further attribute writes
raise ``AttributeError``. This is the in-memory mirror of the fact
that the on-disk bundle is immutable too — the pair
``result_path`` + ``export_root`` captured on the job at completion
points at a bundle that will never be rewritten.

Identity
--------

``job_id`` is a random, non-sequential token to discourage any
consumer (LLM prompt, UI widget, log scraper) from reading ordering
semantics into it. Jobs are distinguished only by identity; the
order in which they were submitted is recoverable from
``submitted_at`` when truly needed.
"""

from __future__ import annotations

import datetime as _dt
import secrets
from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet, Optional


class JobOrigin(Enum):
    """Who submitted the job.

    Origin is a **mandatory identity tag**, not optional metadata.
    UI event filtering, log attribution, and (later) permission
    scoping all key off it — which is why the enum is closed to the
    minimum set the current architecture needs. Adding a new origin
    is a deliberate design decision, not a drive-by extension.
    """

    UI_EDITOR = "ui_editor"
    """Submitted by the editor Run button (user-visible execution)."""

    AGENT_TOOL = "agent_tool"
    """Submitted by the agent's ``run_simulation`` tool (headless)."""


class JobStatus(Enum):
    r"""Lifecycle states of a ``SimulationJob``.

    The state machine is strictly linear in one direction::

        PENDING -> RUNNING -> {COMPLETED, FAILED, CANCELLED}
               \-----------> CANCELLED  (direct when cancelled while queued)

    No transitions back to ``PENDING``/``RUNNING`` from terminal
    states are permitted. The manager is responsible for enforcing
    these transitions through the ``mark_*`` methods below.
    """

    PENDING = "pending"
    """Submitted but not yet executing."""

    RUNNING = "running"
    """Currently executing inside a worker."""

    COMPLETED = "completed"
    """Terminal: simulation finished and its bundle persisted."""

    FAILED = "failed"
    """Terminal: simulation (or persistence) raised an error."""

    CANCELLED = "cancelled"
    """Terminal: cancellation was honoured before or during the run."""


_TERMINAL_STATUSES: FrozenSet[JobStatus] = frozenset(
    {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
)


def _generate_job_id() -> str:
    """Create a random, non-sequential job identifier.

    Using ``secrets.token_hex`` gives us a compact URL-safe token with
    no ordering semantics — deliberately so, since ``job_id`` shows
    up in LLM tool arguments and we do not want the model to read
    "later" or "earlier" into adjacent values.
    """
    return f"job_{secrets.token_hex(6)}"


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


@dataclass
class SimulationJob:
    """Full lifecycle record of a single simulation run.

    The object is assembled at submission time with the minimum
    required context (``circuit_file`` + ``origin``) and then
    progressed exclusively through the ``mark_*`` / ``request_cancel``
    methods. Direct field assignment is allowed only before the job
    reaches a terminal status; afterwards it raises.
    """

    circuit_file: str
    """Circuit source path the job was submitted against.

    Stored as a project-relative POSIX-style string. The job is the
    single authority on "which circuit this run is about" — callers
    must not infer it from ambient UI state or from the active editor
    tab.
    """

    origin: JobOrigin
    """Who submitted the job (see :class:`JobOrigin`)."""

    project_root: str = ""
    """Absolute project root the job persists its bundle under.

    Every submission must target a project so the artifact bundle
    lands in ``<project_root>/simulation_results/<stem>/<ts>/``. The
    manager rejects empty values at :meth:`submit` time — keeping the
    field on the job itself (rather than in a manager-side context map)
    means any downstream consumer holding a ``SimulationJob`` reference
    has the full provenance without extra lookups.
    """

    job_id: str = field(default_factory=_generate_job_id)
    """Random, non-sequential identifier."""

    status: JobStatus = JobStatus.PENDING
    """Current lifecycle state."""

    submitted_at: _dt.datetime = field(default_factory=_utcnow)
    """UTC timestamp of ``submit`` on the manager."""

    started_at: Optional[_dt.datetime] = None
    """UTC timestamp the worker moved the job to ``RUNNING``."""

    finished_at: Optional[_dt.datetime] = None
    """UTC timestamp a terminal status was recorded."""

    cancel_requested: bool = False
    """``True`` once :meth:`request_cancel` has been called.

    Purely an intent flag — the actual status transition to
    ``CANCELLED`` is still driven by :meth:`mark_cancelled`. This
    mirrors the manager's MVP semantics: ``PENDING`` jobs are
    cancelled immediately, ``RUNNING`` jobs only flip status once
    their worker returns.
    """

    result_path: Optional[str] = None
    """Project-relative POSIX path of ``result.json`` for the bundle
    (e.g. ``simulation_results/amp/2026-04-06_00-10-00/result.json``).

    Populated only on ``COMPLETED``. The value is whatever the
    persistence layer actually wrote to disk — never a predicted or
    pre-computed path — so unique-suffix collisions are reflected
    faithfully.
    """

    export_root: Optional[str] = None
    """Project-relative POSIX path of the bundle directory (i.e. the
    parent of :attr:`result_path`).

    Kept explicitly on the job so downstream consumers (UI panels,
    agent read tools) never have to recompute it.
    """

    error_message: Optional[str] = None
    """Human-readable failure reason. Set only on ``FAILED``."""

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------

    @property
    def is_terminal(self) -> bool:
        """``True`` when the job is in any terminal status."""
        return self.status in _TERMINAL_STATUSES

    def mark_running(self, *, started_at: Optional[_dt.datetime] = None) -> None:
        """Move a ``PENDING`` job into ``RUNNING``.

        Raises ``ValueError`` if called from any other status so
        accidental re-entry from a worker is surfaced loudly.
        """
        if self.status is not JobStatus.PENDING:
            raise ValueError(
                f"SimulationJob[{self.job_id}] cannot enter RUNNING "
                f"from status {self.status.value}"
            )
        self.status = JobStatus.RUNNING
        self.started_at = started_at or _utcnow()

    def mark_completed(
        self,
        *,
        result_path: str,
        export_root: str,
        finished_at: Optional[_dt.datetime] = None,
    ) -> None:
        """Record a successful run and freeze the job.

        Both ``result_path`` and ``export_root`` are mandatory — a
        "completed" job without a persisted bundle is nonsensical and
        must not be representable.
        """
        self._require_non_terminal("COMPLETED")
        if not result_path:
            raise ValueError("result_path is required on completion")
        if not export_root:
            raise ValueError("export_root is required on completion")
        self.status = JobStatus.COMPLETED
        self.result_path = result_path
        self.export_root = export_root
        self.finished_at = finished_at or _utcnow()
        self._freeze()

    def mark_failed(
        self,
        *,
        error_message: str,
        finished_at: Optional[_dt.datetime] = None,
    ) -> None:
        """Record a failed run and freeze the job.

        ``error_message`` is mandatory so callers cannot leave a
        failed job with a silent ``None`` reason; empty strings are
        rejected for the same reason.
        """
        self._require_non_terminal("FAILED")
        if not error_message:
            raise ValueError("error_message is required on failure")
        self.status = JobStatus.FAILED
        self.error_message = error_message
        self.finished_at = finished_at or _utcnow()
        self._freeze()

    def mark_cancelled(
        self,
        *,
        finished_at: Optional[_dt.datetime] = None,
    ) -> None:
        """Record a cancelled run and freeze the job.

        Valid from either ``PENDING`` (cancelled while queued) or
        ``RUNNING`` (cancelled after the worker observed
        :attr:`cancel_requested` and returned).
        """
        self._require_non_terminal("CANCELLED")
        self.status = JobStatus.CANCELLED
        self.finished_at = finished_at or _utcnow()
        self._freeze()

    def request_cancel(self) -> None:
        """Flag an intent to cancel the job.

        Idempotent and safe to call on terminal jobs (where it is a
        no-op) — the manager calls this unconditionally on user
        request and then decides whether to invoke
        :meth:`mark_cancelled` directly (``PENDING``) or wait for the
        worker to return (``RUNNING``).
        """
        if self.is_terminal:
            return
        self.cancel_requested = True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_non_terminal(self, target_status_name: str) -> None:
        if self.status in _TERMINAL_STATUSES:
            raise ValueError(
                f"SimulationJob[{self.job_id}] is already terminal "
                f"({self.status.value}); cannot transition to {target_status_name}"
            )

    def _freeze(self) -> None:
        """Lock the job against further attribute writes.

        Enforced by :meth:`__setattr__`. Called exactly once, on
        transition into a terminal status.
        """
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, name: str, value: object) -> None:  # noqa: D401
        # ``_frozen`` itself must always be assignable so
        # ``_freeze`` can set it, and so initial ``__init__`` /
        # ``__post_init__`` writes work before the flag exists.
        if name == "_frozen":
            object.__setattr__(self, name, value)
            return
        if getattr(self, "_frozen", False):
            raise AttributeError(
                f"SimulationJob[{getattr(self, 'job_id', '?')}] is terminal; "
                f"field '{name}' is immutable"
            )
        object.__setattr__(self, name, value)


__all__ = [
    "JobOrigin",
    "JobStatus",
    "SimulationJob",
]
