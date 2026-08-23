"""``SimulationService`` — stateless, reentrant simulation execution unit.

This module is deliberately kept narrow: run ngspice, persist the bundle,
return its exact ``result_path``. Nothing else.

What this module is **not**
---------------------------

- **Not** a lifecycle owner. Running / terminal status, event
  broadcasting, cancellation, concurrent submission — all of that
  belongs to :class:`~domain.services.simulation_job_manager.SimulationJobManager`.
- **Not** an event publisher. This service never imports ``EventBus``
  or any ``EVENT_SIM_*`` constant. The manager is the sole authority
  on simulation lifecycle events; double-publishing from two layers
  is the exact design pathology the job-manager rollout is meant to
  eliminate.
- **Not** stateful. The service carries no running-flag, no
  last-file memory, no running-job index, no hidden counters. Any
  code that used to ask the service "are you busy right now?" or
  "what ran last?" must ask the manager (``query`` / ``list``)
  instead — that is the single source of truth.

Thread safety
-------------

Every ``run_simulation`` call is self-contained: its inputs come via
arguments, its outputs via the return value, and its only mutable
side effect is the filesystem bundle it writes. The service instance
holds only the concrete ngspice executor and artifact persistence it was
handed at construction time. The executor serializes its native session.
That means manager workers can share one service across threads, or
spin up per-worker instances — either works.

Return contract
---------------

``run_simulation`` returns only the project-relative POSIX ``result_path`` of
the freshly-written ``result.json``.  The persisted document is the sole
authority: callers load it through ``SimulationResultRepository`` instead of
trusting a second in-memory result that could drift from disk. No successful
call skips persistence or returns an empty path.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Optional

from domain.simulation.data.simulation_artifact_persistence import (
    SimulationArtifactPersistence,
    simulation_artifact_persistence,
)
from domain.simulation.executor.spice_executor import SpiceExecutor
from domain.simulation.models.simulation_error import (
    ErrorSeverity,
    SimulationError,
    SimulationErrorType,
)
from domain.simulation.models.simulation_result import (
    SimulationResult,
    create_error_result,
)


_logger = logging.getLogger(__name__)


class SimulationService:
    """Stateless simulation orchestrator: validate → run → persist.

    One instance can safely back every manager worker in the pool;
    there is no per-call state the object keeps between invocations.
    All inputs flow in through :meth:`run_simulation` arguments,
    all outputs flow back through the returned authoritative path.
    """

    def __init__(
        self,
        *,
        executor: SpiceExecutor,
        artifact_persistence: Optional[SimulationArtifactPersistence] = None,
    ) -> None:
        if executor is None:
            raise TypeError("executor is required")
        self._executor = executor
        self._artifact_persistence = (
            artifact_persistence
            if artifact_persistence is not None
            else simulation_artifact_persistence
        )

    def run_simulation(
        self,
        *,
        file_path: str,
        project_root: str,
        cancel_signal: Optional[threading.Event] = None,
        version: int = 1,
        session_id: str = "",
    ) -> str:
        """Execute one simulation and persist its bundle.

        Args:
            file_path: Circuit source, absolute or relative to ``project_root``.
            project_root: Non-empty project directory used for the mandatory
                transactional result bundle.
            cancel_signal: Manager-owned cancellation signal forwarded to the
                executor through its explicit cancellation channel.
            version: Iteration version stamped onto the result.
            session_id: Session id stamped onto the result.

        Returns:
            The project-relative POSIX path of the committed ``result.json``.
            Callers must treat it as opaque and load the authoritative result
            through ``SimulationResultRepository``.

        Raises:
            Every executor failure is captured into an error-shaped
            ``SimulationResult`` and returned, never raised. Persistence
            errors, by contrast, propagate out: a "successful" return
            from this method means the bundle is on disk.
        """
        file_path, project_root = self._canonicalize_project_paths(
            file_path,
            project_root,
        )
        start_time = time.time()

        executor = self._executor
        if not executor.can_handle(file_path):
            error = SimulationError(
                type=SimulationErrorType.PARAMETER_INVALID,
                severity=ErrorSeverity.HIGH,
                message=(
                    f"Unsupported circuit file type: "
                    f"{Path(file_path).suffix}"
                ),
                file_path=file_path,
                recovery_suggestion=(
                    "Supported extensions: "
                    + ", ".join(executor.get_supported_extensions())
                ),
            )
            result = create_error_result(
                executor="unknown",
                file_path=file_path,
                analysis_type="unknown",
                error=error,
                duration_seconds=time.time() - start_time,
                version=version,
                session_id=session_id,
            )
        else:
            try:
                result = executor.execute(
                    file_path,
                    cancel_signal=cancel_signal,
                )
            except Exception as exc:
                _logger.exception(
                    "Executor '%s' raised while running %s: %s",
                    executor.get_name(),
                    file_path,
                    exc,
                )
                diagnostic_message = str(exc).strip() or (
                    f"{type(exc).__name__} raised without an error message"
                )
                error = SimulationError(
                    type=SimulationErrorType.NGSPICE_CRASH,
                    severity=ErrorSeverity.CRITICAL,
                    message=diagnostic_message,
                    file_path=file_path,
                )
                result = create_error_result(
                    executor=executor.get_name(),
                    file_path=file_path,
                    analysis_type="unknown",
                    error=error,
                    duration_seconds=time.time() - start_time,
                    version=version,
                    session_id=session_id,
                )
        result = self._validate_executor_result(
            result=result,
            requested_file=file_path,
            project_root=project_root,
            version=version,
            session_id=session_id,
        )

        outcome = self._artifact_persistence.persist_bundle(
            project_root=project_root,
            result=result,
        )
        _logger.info(
            "Simulation result persisted: %s",
            outcome.result_path,
        )
        return outcome.result_path

    @staticmethod
    def _canonicalize_project_paths(
        file_path: str,
        project_root: str,
    ) -> tuple[str, str]:
        if not isinstance(project_root, str) or not project_root.strip():
            raise ValueError("project_root is required")
        if not isinstance(file_path, str) or not file_path.strip():
            raise ValueError("file_path is required")

        project_input = Path(project_root).expanduser()
        if not project_input.is_absolute():
            raise ValueError("project_root must be an absolute directory")
        project = project_input.resolve(strict=False)
        if not project.is_dir():
            raise ValueError("project_root must be an existing directory")
        requested = Path(file_path).expanduser()
        circuit = (
            requested.resolve(strict=False)
            if requested.is_absolute()
            else (project / requested).resolve(strict=False)
        )
        try:
            circuit.relative_to(project)
        except ValueError as exc:
            raise ValueError("file_path must stay inside project_root") from exc
        return str(circuit), str(project)

    @classmethod
    def _validate_executor_result(
        cls,
        *,
        result: Any,
        requested_file: str,
        project_root: str,
        version: int,
        session_id: str,
    ) -> SimulationResult:
        """Fail closed before publishing anything returned by the executor.

        The executor result is still an untrusted in-memory boundary: a wrong
        circuit must never be committed and left behind as a
        misleading history entry.  This layer owns request identity only;
        ``SimulationArtifactPersistence`` is the sole owner of the portable
        on-disk representation and its strict schema round-trip.
        """
        if not isinstance(result, SimulationResult):
            raise TypeError("executor must return a SimulationResult")

        project = Path(project_root).resolve(strict=True)
        requested = Path(requested_file).resolve(strict=False)
        returned = cls._resolve_result_file(result.file_path, project)
        if cls._path_key(returned) != cls._path_key(requested):
            raise ValueError(
                "executor returned a result for a different circuit file"
            )

        if isinstance(result.error, SimulationError) and result.error.file_path is not None:
            error_file = cls._resolve_result_file(result.error.file_path, project)
            if cls._path_key(error_file) != cls._path_key(requested):
                raise ValueError(
                    "executor returned an error for a different circuit file"
                )

        return replace(
            result,
            version=version,
            session_id=session_id,
        )

    @staticmethod
    def _resolve_result_file(value: Any, project_root: Path) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("executor result file_path must be a non-empty string")
        raw = Path(value).expanduser()
        resolved = (
            raw.resolve(strict=False)
            if raw.is_absolute()
            else (project_root / raw).resolve(strict=False)
        )
        try:
            resolved.relative_to(project_root)
        except ValueError as exc:
            raise ValueError(
                "executor result file_path must stay inside project_root"
            ) from exc
        return resolved

    @staticmethod
    def _path_key(path: Path) -> str:
        return os.path.normcase(str(path.resolve(strict=False)))


__all__ = [
    "SimulationService",
]
