"""Submit one exact project circuit and return an addressable result handle."""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.llm.agent.types import BaseTool, ToolContext, ToolResult
from domain.llm.agent.utils.path_utils import validate_file_path
from domain.simulation.models.simulation_job import (
    DuplicateSimulationJobError,
    JobOrigin,
    JobStatus,
)
from shared.workspace_file_types import (
    SIMULATABLE_CIRCUIT_EXTENSIONS,
    is_simulatable_circuit_extension,
)


class RunSimulationTool(BaseTool):
    @property
    def name(self) -> str:
        return "run_simulation"

    @property
    def label(self) -> str:
        return "Run Simulation"

    @property
    def description(self) -> str:
        return (
            "Run the analysis directives embedded in one explicit project "
            "circuit file. The tool waits for a terminal job state and only "
            "reports success when the persisted bundle is readable and tied "
            "to the submitted circuit, session, and version. A successful "
            "call returns the exact "
            "project-relative result_path required by every simulation read "
            "tool and an absolute export_root."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": (
                        "Explicit project-relative or absolute circuit path "
                        "inside the open project. Supported extensions: "
                        + ", ".join(sorted(SIMULATABLE_CIRCUIT_EXTENSIONS))
                        + "."
                    ),
                }
            },
            "required": ["file_path"],
        }

    @property
    def prompt_snippet(self) -> Optional[str]:
        return "Run an explicit project circuit and return its exact result_path handle"

    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        return [
            "Always pass file_path explicitly; run_simulation does not infer the editor's active file.",
            "Parallel agent runs of the same project circuit are rejected atomically; use the existing job instead of resubmitting it.",
            "Pass the returned result_path verbatim to read_metrics, read_output_log, read_op_result, or read_signals.",
        ]

    async def execute(
        self,
        tool_call_id: str,
        params: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        manager = context.sim_job_manager
        if manager is None:
            return _error(
                "SimulationJobManager was not injected through ToolContext."
            )
        repository = context.sim_result_repository
        if repository is None:
            return _error(
                "SimulationResultRepository was not injected through ToolContext."
            )
        project_root = str(context.project_root or "").strip()
        if not project_root:
            return _error("no project is open")

        raw_path = params.get("file_path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return _error(
                "file_path is required; editor-active-file fallback does not exist"
            )
        raw_path = raw_path.strip()
        circuit_file, path_error = validate_file_path(
            raw_path, project_root, must_exist=True
        )
        if path_error:
            return _error(path_error)
        assert circuit_file is not None
        if not is_simulatable_circuit_extension(circuit_file):
            return _error(
                f"'{raw_path}' is not a simulatable circuit file; supported "
                f"extensions: {', '.join(sorted(SIMULATABLE_CIRCUIT_EXTENSIONS))}"
            )

        try:
            job = manager.submit(
                circuit_file=circuit_file,
                origin=JobOrigin.AGENT_TOOL,
                project_root=project_root,
            )
        except DuplicateSimulationJobError as exc:
            return ToolResult(
                content=(
                    f"Error: an agent simulation for '{exc.circuit_file}' "
                    f"is already active (job_id={exc.existing_job_id}, "
                    f"status={exc.status.value})."
                ),
                is_error=True,
                details={
                    "job_id": exc.existing_job_id,
                    "circuit_file": exc.circuit_file,
                    "status": exc.status.value,
                    "duplicate": True,
                },
            )
        except Exception as exc:
            return ToolResult(
                content=f"Error: simulation job submission failed: {exc}",
                is_error=True,
                details={"circuit_file": circuit_file},
            )

        try:
            final_job = await manager.await_completion_async(job.job_id)
        except asyncio.CancelledError:
            _request_cancel_safely(manager, job.job_id)
            raise
        except TimeoutError as exc:
            _request_cancel_safely(manager, job.job_id)
            return ToolResult(
                content=(
                    f"Error: simulation job {job.job_id} timed out while "
                    f"waiting for completion: {exc}"
                ),
                is_error=True,
                details={
                    "job_id": job.job_id,
                    "circuit_file": circuit_file,
                    "status": "timeout",
                },
            )
        except Exception as exc:
            _request_cancel_safely(manager, job.job_id)
            return ToolResult(
                content=(
                    f"Error: failed while awaiting simulation job "
                    f"{job.job_id}: {exc}"
                ),
                is_error=True,
                details={
                    "job_id": job.job_id,
                    "circuit_file": circuit_file,
                    "status": "await_failed",
                },
            )

        return self._format_terminal(final_job, project_root, repository)

    def _format_terminal(self, job, project_root: str, repository) -> ToolResult:
        details: Dict[str, Any] = {
            "job_id": job.job_id,
            "circuit_file": job.circuit_file,
            "status": job.status.value,
            "session_id": job.session_id,
            "version": job.version,
            "result_path": job.result_path or "",
            "export_root": job.export_root or "",
        }
        if job.status is JobStatus.FAILED:
            message = str(job.error_message or "unknown simulation failure").rstrip(".")
            bundle_note = (
                f" Failure bundle result_path: {job.result_path}."
                if job.result_path
                else ""
            )
            return ToolResult(
                content=f"Simulation FAILED (job_id={job.job_id}): {message}.{bundle_note}",
                is_error=True,
                details=details,
            )
        if job.status is JobStatus.CANCELLED:
            return ToolResult(
                content=f"Simulation was cancelled (job_id={job.job_id}).",
                is_error=True,
                details=details,
            )
        if job.status is not JobStatus.COMPLETED:
            return ToolResult(
                content=(
                    f"Error: simulation job {job.job_id} returned unexpected "
                    f"status '{job.status.value}'."
                ),
                is_error=True,
                details=details,
            )
        return self._format_completed(job, project_root, repository, details)

    def _format_completed(
        self,
        job,
        project_root: str,
        repository,
        details: Dict[str, Any],
    ) -> ToolResult:
        if not job.result_path:
            return _completed_contract_error(
                job, details, "COMPLETED job has no result_path"
            )
        if not job.export_root or not Path(job.export_root).is_absolute():
            return _completed_contract_error(
                job, details, "export_root is missing or not absolute"
            )

        try:
            expected_export_root = (
                Path(project_root) / job.result_path
            ).resolve().parent
            actual_export_root = Path(job.export_root).resolve()
        except (OSError, RuntimeError) as exc:
            return _completed_contract_error(
                job, details, f"export_root cannot be resolved: {exc}"
            )
        if actual_export_root != expected_export_root:
            return _completed_contract_error(
                job, details, "result_path and export_root identify different bundles"
            )

        try:
            loaded = repository.load(project_root, job.result_path)
        except Exception as exc:
            return _completed_contract_error(
                job, details, f"result bundle load raised: {exc}"
            )
        if not loaded.success or loaded.data is None:
            return _completed_contract_error(
                job,
                details,
                "result bundle is unreadable: "
                f"{loaded.error_message or 'unknown repository error'}",
            )

        result = loaded.data
        if not result.success:
            return _completed_contract_error(
                job, details, "persisted SimulationResult.success is false"
            )
        if not _same_circuit_identity(
            project_root, job.circuit_file, result.file_path
        ):
            details["persisted_circuit_file"] = result.file_path
            return _completed_contract_error(
                job,
                details,
                f"persisted circuit '{result.file_path}' does not match "
                f"submitted circuit '{job.circuit_file}'",
            )
        if type(result.version) is not int or result.version != job.version:
            details["persisted_version"] = result.version
            return _completed_contract_error(
                job,
                details,
                f"persisted version {result.version!r} does not match "
                f"submitted version {job.version!r}",
            )
        if (
            not isinstance(result.session_id, str)
            or result.session_id != job.session_id
        ):
            details["persisted_session_id"] = result.session_id
            return _completed_contract_error(
                job,
                details,
                f"persisted session_id {result.session_id!r} does not match "
                f"submitted session_id {job.session_id!r}",
            )

        analysis_type = str(result.analysis_type or "").strip().lstrip(".").lower()
        if not analysis_type:
            return _completed_contract_error(
                job, details, "persisted result has no analysis_type"
            )
        try:
            duration = float(result.duration_seconds or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        if not math.isfinite(duration) or duration < 0:
            duration = 0.0

        details.update(
            analysis_type=analysis_type,
            duration_seconds=duration,
        )
        return ToolResult(
            content="\n".join(
                [
                    f"Simulation completed (job_id={job.job_id}).",
                    f"- Analysis: {analysis_type}",
                    f"- Duration: {duration:.3f}s",
                    f"- result_path: {job.result_path}",
                    f"- export_root: {job.export_root}",
                ]
            ),
            details=details,
        )


def _request_cancel_safely(manager, job_id: str) -> None:
    try:
        manager.request_cancel(job_id)
    except Exception:
        pass


def _same_circuit_identity(project_root: str, submitted: str, persisted: str) -> bool:
    if not submitted or not persisted:
        return False

    def resolve(value: str) -> Path:
        path = Path(value)
        return (path if path.is_absolute() else Path(project_root) / path).resolve()

    try:
        return resolve(submitted) == resolve(persisted)
    except (OSError, RuntimeError):
        return False


def _completed_contract_error(job, details: Dict[str, Any], reason: str) -> ToolResult:
    details["contract_error"] = reason
    return ToolResult(
        content=(
            f"Error: simulation job {job.job_id} reported COMPLETED, but the "
            f"run/read result contract is broken: {reason}."
        ),
        is_error=True,
        details=details,
    )


def _error(reason: str) -> ToolResult:
    return ToolResult(content=f"Error: {reason}.", is_error=True)


__all__ = ["RunSimulationTool"]
