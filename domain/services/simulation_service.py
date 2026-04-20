"""``SimulationService`` — stateless, reentrant simulation execution unit.

This module is deliberately kept narrow: pick an executor, run it,
persist the bundle, return ``(result, result_path)``. Nothing else.

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
holds only the executor registry and the artifact persistence it
was handed at construction time; both are themselves safe to share.
That means manager workers can share one service across threads, or
spin up per-worker instances — either works.

Return contract
---------------

``run_simulation`` returns ``(SimulationResult, result_path)``. The
``result_path`` is the project-relative POSIX path of
``result.json`` inside the freshly-written bundle, or the empty
string when ``project_root`` is falsy (headless tests that skip
persistence). No other output channel exists; callers consume the
tuple directly.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from domain.simulation.spice.analysis_directive_authority import detect_last_analysis_type_from_text
from domain.simulation.data.simulation_artifact_persistence import (
    SimulationArtifactPersistence,
    simulation_artifact_persistence,
)
from domain.simulation.executor.executor_registry import (
    ExecutorRegistry,
    executor_registry,
)
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
    """Stateless simulation orchestrator: executor lookup → run → persist.

    One instance can safely back every manager worker in the pool;
    there is no per-call state the object keeps between invocations.
    All inputs flow in through :meth:`run_simulation` arguments,
    all outputs flow back through the returned tuple.
    """

    def __init__(
        self,
        registry: Optional[ExecutorRegistry] = None,
        artifact_persistence: Optional[SimulationArtifactPersistence] = None,
    ) -> None:
        self._registry = registry or executor_registry
        self._artifact_persistence = (
            artifact_persistence or simulation_artifact_persistence
        )

    def run_simulation(
        self,
        file_path: str,
        analysis_config: Optional[Dict[str, Any]] = None,
        project_root: Optional[str] = None,
        version: int = 1,
        session_id: str = "",
        metric_targets: Optional[Mapping[str, str]] = None,
    ) -> Tuple[SimulationResult, str]:
        """Execute one simulation and persist its bundle.

        Args:
            file_path: Circuit source (absolute or project-relative).
            analysis_config: Optional executor config; ``analysis_type``
                is read here, everything else is forwarded untouched.
            project_root: Absolute project directory. When empty, the
                bundle is **not** written and ``result_path`` is ``""``
                — only headless unit tests should rely on this.
            version: Iteration version stamped onto the result.
            session_id: Session id stamped onto the result.
            metric_targets: ``{metric_name: target_text}``. UI callers
                pass ``MetricTargetService.get_targets_for_file``;
                headless callers pass ``{}``.

        Returns:
            ``(SimulationResult, result_path)``. ``result_path`` is the
            project-relative POSIX path of ``result.json``; callers
            must treat it as opaque and never predict the value.

        Raises:
            Every executor failure is captured into an error-shaped
            ``SimulationResult`` and returned, never raised. Persistence
            errors, by contrast, propagate out: a "successful" return
            from this method means the bundle is on disk.
        """
        start_time = time.time()
        analysis_type = self._resolve_analysis_type(analysis_config, file_path)

        executor = self._registry.get_executor_for_file(file_path)
        if executor is None:
            error = SimulationError(
                code="E011",
                type=SimulationErrorType.PARAMETER_INVALID,
                severity=ErrorSeverity.HIGH,
                message=(
                    f"No executor supports file type: "
                    f"{Path(file_path).suffix}"
                ),
                file_path=file_path,
                recovery_suggestion=(
                    "Supported extensions: "
                    + ", ".join(self._registry.get_all_supported_extensions())
                ),
            )
            result = create_error_result(
                executor="unknown",
                file_path=file_path,
                analysis_type=analysis_type,
                error=error,
                duration_seconds=time.time() - start_time,
                version=version,
                session_id=session_id,
            )
        else:
            try:
                result = executor.execute(file_path, analysis_config)
            except Exception as exc:
                _logger.exception(
                    "Executor '%s' raised while running %s: %s",
                    executor.get_name(),
                    file_path,
                    exc,
                )
                error = SimulationError(
                    code="E999",
                    type=SimulationErrorType.NGSPICE_CRASH,
                    severity=ErrorSeverity.CRITICAL,
                    message=str(exc),
                    file_path=file_path,
                )
                result = create_error_result(
                    executor=executor.get_name(),
                    file_path=file_path,
                    analysis_type=analysis_type,
                    error=error,
                    duration_seconds=time.time() - start_time,
                    version=version,
                    session_id=session_id,
                )
            else:
                result.version = version
                result.session_id = session_id

        result_path = ""
        if project_root:
            outcome = self._artifact_persistence.persist_bundle(
                project_root=project_root,
                result=result,
                metric_targets=metric_targets,
            )
            result_path = outcome.result_path
            _logger.info(
                "Simulation bundle persisted: %s (files=%d, errors=%d)",
                result_path,
                len(outcome.written_files),
                len(outcome.errors),
            )
        return result, result_path

    @staticmethod
    def _resolve_analysis_type(
        analysis_config: Optional[Dict[str, Any]],
        file_path: str,
    ) -> str:
        """Prefer the config's ``analysis_type``; fall back to netlist scan."""
        if analysis_config:
            configured = analysis_config.get("analysis_type", "")
            if configured:
                return str(configured)
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""
        return detect_last_analysis_type_from_text(content)


__all__ = [
    "SimulationService",
]
