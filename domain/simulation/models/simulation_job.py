"""Immutable lifecycle record for one simulation execution.

``SimulationJobManager`` stores and returns these values as snapshots. A
caller can inspect a job without being able to corrupt the manager's state
machine from another thread. Every transition returns a new snapshot; there
is no mutable compatibility API.
"""

from __future__ import annotations

import datetime as _dt
import secrets
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import PurePath, PurePosixPath
from typing import FrozenSet, Optional


class JobOrigin(Enum):
    """The user-facing boundary that submitted a simulation."""

    UI_EDITOR = "ui_editor"
    AGENT_TOOL = "agent_tool"


class JobStatus(Enum):
    """Strict lifecycle states for a simulation job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TERMINAL_STATUSES: FrozenSet[JobStatus] = frozenset(
    {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
)


class DuplicateSimulationJobError(RuntimeError):
    """An agent already has the same project circuit in flight.

    The manager raises this exception from the same lock-protected section
    that registers jobs, eliminating a racy ``list`` then ``submit`` check.
    """

    def __init__(
        self,
        *,
        existing_job_id: str,
        circuit_file: str,
        status: JobStatus,
    ) -> None:
        self.existing_job_id = existing_job_id
        self.circuit_file = circuit_file
        self.status = status
        super().__init__(
            "An agent simulation for "
            f"{circuit_file!r} is already active "
            f"(job_id={existing_job_id}, status={status.value})"
        )


def _generate_job_id() -> str:
    # 128 random bits keep identifiers opaque without the collision risk of
    # the former 48-bit token.
    return f"job_{secrets.token_hex(16)}"


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _is_absolute_path(path: str) -> bool:
    """Recognise both native and Windows absolute paths on every platform."""

    return PurePath(path).is_absolute() or (
        len(path) >= 3 and path[1] == ":" and path[2] in ("/", "\\")
    )


def _validate_bundle_paths(
    result_path: Optional[str],
    export_root: Optional[str],
) -> None:
    if bool(result_path) != bool(export_root):
        raise ValueError(
            "result_path and export_root must either both be provided or both be omitted"
        )
    if not result_path:
        return

    relative = PurePosixPath(result_path)
    if (
        relative.is_absolute()
        or str(relative) != result_path
        or len(relative.parts) < 4
        or relative.parts[0] != "simulation_results"
        or any(
            part in {"", ".", ".."}
            or ":" in part
            or part.startswith(".__bundle_tmp__")
            for part in relative.parts
        )
    ):
        raise ValueError("result_path must be a safe project-relative POSIX path")
    if relative.name != "result.json":
        raise ValueError("result_path must identify the persisted result.json")
    if not export_root or not _is_absolute_path(export_root):
        raise ValueError("export_root must be an absolute bundle directory")


@dataclass(frozen=True, slots=True)
class SimulationJob:
    """An immutable, provenance-complete simulation lifecycle snapshot."""

    circuit_file: str
    origin: JobOrigin
    project_root: str
    session_id: str = ""
    version: int = 1
    job_id: str = field(default_factory=_generate_job_id)
    status: JobStatus = JobStatus.PENDING
    submitted_at: _dt.datetime = field(default_factory=_utcnow)
    started_at: Optional[_dt.datetime] = None
    finished_at: Optional[_dt.datetime] = None
    cancel_requested: bool = False
    result_path: Optional[str] = None
    export_root: Optional[str] = None
    error_message: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.circuit_file or not _is_absolute_path(self.circuit_file):
            raise ValueError("circuit_file must be an absolute path")
        if not self.project_root or not _is_absolute_path(self.project_root):
            raise ValueError("project_root must be an absolute path")
        if not isinstance(self.origin, JobOrigin):
            raise TypeError("origin must be JobOrigin")
        if not isinstance(self.session_id, str):
            raise TypeError("session_id must be a string")
        if (
            isinstance(self.version, bool)
            or not isinstance(self.version, int)
            or self.version < 1
        ):
            raise ValueError("version must be a positive integer")
        if not self.job_id:
            raise ValueError("job_id is required")
        for name, timestamp in (
            ("submitted_at", self.submitted_at),
            ("started_at", self.started_at),
            ("finished_at", self.finished_at),
        ):
            if timestamp is not None and (
                timestamp.tzinfo is None or timestamp.utcoffset() is None
            ):
                raise ValueError(f"{name} must be timezone-aware")

        _validate_bundle_paths(self.result_path, self.export_root)
        self._validate_state_shape()

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES

    def start(self, *, started_at: Optional[_dt.datetime] = None) -> "SimulationJob":
        if self.status is not JobStatus.PENDING:
            self._raise_bad_transition(JobStatus.RUNNING)
        if self.cancel_requested:
            raise ValueError(
                f"SimulationJob[{self.job_id}] has a cancellation request and cannot start"
            )
        return replace(
            self,
            status=JobStatus.RUNNING,
            started_at=started_at or _utcnow(),
        )

    def request_cancellation(self) -> "SimulationJob":
        if self.is_terminal or self.cancel_requested:
            return self
        return replace(self, cancel_requested=True)

    def complete(
        self,
        *,
        result_path: str,
        export_root: str,
        finished_at: Optional[_dt.datetime] = None,
    ) -> "SimulationJob":
        self._require_running(JobStatus.COMPLETED)
        _validate_bundle_paths(result_path, export_root)
        if not result_path:
            raise ValueError("a completed job requires its persisted bundle")
        return replace(
            self,
            status=JobStatus.COMPLETED,
            result_path=result_path,
            export_root=export_root,
            finished_at=finished_at or _utcnow(),
        )

    def fail(
        self,
        *,
        error_message: str,
        result_path: Optional[str] = None,
        export_root: Optional[str] = None,
        finished_at: Optional[_dt.datetime] = None,
    ) -> "SimulationJob":
        self._require_running(JobStatus.FAILED)
        if not error_message or not error_message.strip():
            raise ValueError("error_message is required on failure")
        _validate_bundle_paths(result_path, export_root)
        return replace(
            self,
            status=JobStatus.FAILED,
            error_message=error_message.strip(),
            result_path=result_path,
            export_root=export_root,
            finished_at=finished_at or _utcnow(),
        )

    def cancel(
        self,
        *,
        result_path: Optional[str] = None,
        export_root: Optional[str] = None,
        finished_at: Optional[_dt.datetime] = None,
    ) -> "SimulationJob":
        if self.status not in (JobStatus.PENDING, JobStatus.RUNNING):
            self._raise_bad_transition(JobStatus.CANCELLED)
        _validate_bundle_paths(result_path, export_root)
        return replace(
            self,
            status=JobStatus.CANCELLED,
            result_path=result_path,
            export_root=export_root,
            finished_at=finished_at or _utcnow(),
        )

    def _require_running(self, target: JobStatus) -> None:
        if self.status is not JobStatus.RUNNING:
            self._raise_bad_transition(target)

    def _raise_bad_transition(self, target: JobStatus) -> None:
        raise ValueError(
            f"SimulationJob[{self.job_id}] cannot enter {target.value} "
            f"from {self.status.value}"
        )

    def _validate_state_shape(self) -> None:
        if self.status is JobStatus.PENDING:
            if self.started_at is not None or self.finished_at is not None:
                raise ValueError("a pending job cannot have lifecycle timestamps")
            if self.result_path or self.error_message:
                raise ValueError("a pending job cannot have a result or error")
            return

        if self.status is JobStatus.RUNNING:
            if self.started_at is None or self.finished_at is not None:
                raise ValueError("a running job requires started_at only")
            if self.result_path or self.error_message:
                raise ValueError("a running job cannot have a result or error")
            return

        if self.finished_at is None:
            raise ValueError("a terminal job requires finished_at")
        if self.status is JobStatus.COMPLETED:
            if self.started_at is None or not self.result_path or self.error_message:
                raise ValueError("a completed job requires a successful persisted run")
        elif self.status is JobStatus.FAILED:
            if self.started_at is None or not self.error_message:
                raise ValueError("a failed job requires started_at and error_message")


__all__ = [
    "DuplicateSimulationJobError",
    "JobOrigin",
    "JobStatus",
    "SimulationJob",
]
