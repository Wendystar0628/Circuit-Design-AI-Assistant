"""Exact-handle resolution shared by simulation artifact read tools.

``run_simulation`` returns one project-relative ``result_path``. Every read
tool consumes that handle verbatim. There is deliberately no "latest result"
lookup and no editor-file fallback: both are race-prone when simulations run
concurrently and can silently attach an answer to a stale bundle.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Union

from domain.llm.agent.types import ToolContext, ToolResult
from domain.simulation.models.simulation_result import SimulationResult


@dataclass(frozen=True)
class ResolvedSimulationBundle:
    """A validated, exact simulation-result handle."""

    result_path: str
    bundle_dir: Path
    result: SimulationResult
    circuit_file: str


READ_TOOL_SHARED_GUIDELINES: List[str] = [
    "Pass the project-relative result_path returned by run_simulation "
    "verbatim. Simulation read tools never guess a latest result from an "
    "editor or circuit path.",
    "A missing, malformed, or mismatched bundle is a hard error. Do not "
    "invent or re-derive another result_path; run a new simulation when a "
    "fresh exact handle is needed.",
]


class SimulationArtifactReaderBase:
    """Resolve and validate one exact authoritative ``result.json`` handle."""

    COMMON_PROPERTIES: Dict[str, Dict[str, Any]] = {
        "result_path": {
            "type": "string",
            "description": (
                "Exact project-relative POSIX path to result.json returned "
                "by run_simulation, under simulation_results/."
            ),
        },
    }

    @classmethod
    def build_parameters_schema(
        cls,
        extra_properties: Optional[Dict[str, Dict[str, Any]]] = None,
        extra_required: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        extras = dict(extra_properties or {})
        overlap = set(extras).intersection(cls.COMMON_PROPERTIES)
        if overlap:
            raise ValueError(
                "SimulationArtifactReaderBase.build_parameters_schema: "
                f"extra_properties collide with reserved keys {overlap}"
            )
        required = ["result_path", *(extra_required or [])]
        return {
            "type": "object",
            "properties": {**cls.COMMON_PROPERTIES, **extras},
            "required": required,
        }

    @staticmethod
    def resolve(
        params: Dict[str, Any],
        context: ToolContext,
    ) -> Union[ResolvedSimulationBundle, ToolResult]:
        repository = context.sim_result_repository
        if repository is None:
            return _error(
                "SimulationResultRepository was not injected through "
                "ToolContext; simulation artifacts cannot be resolved."
            )

        project_root = str(context.project_root or "").strip()
        if not project_root:
            return _error(
                "no project is open; simulation artifacts require a "
                "project root."
            )

        raw_result_path = params.get("result_path")
        if not isinstance(raw_result_path, str) or not raw_result_path.strip():
            return _error(
                "result_path is required. Pass the exact handle returned by "
                "run_simulation; latest-result and editor-file fallbacks do "
                "not exist."
            )

        result_path_or_error = _validate_result_handle(
            project_root, raw_result_path.strip()
        )
        if isinstance(result_path_or_error, ToolResult):
            return result_path_or_error
        result_path, expected_result_file = result_path_or_error

        load = repository.load(project_root, result_path)
        if not load.success or load.data is None:
            return _error(
                f"failed to load simulation result '{result_path}': "
                f"{load.error_message or 'unknown repository error'}."
            )

        bundle_dir = repository.resolve_bundle_dir(project_root, result_path)
        if bundle_dir is None:
            return _error(
                f"bundle directory for '{result_path}' is missing or unreadable."
            )

        expected_bundle = expected_result_file.parent.resolve()
        try:
            actual_bundle = Path(bundle_dir).resolve()
        except (OSError, RuntimeError) as exc:
            return _error(
                f"bundle directory for '{result_path}' could not be resolved: {exc}."
            )
        if actual_bundle != expected_bundle or not actual_bundle.is_dir():
            return _error(
                f"repository returned a mismatched bundle directory for "
                f"'{result_path}'."
            )

        sim_result: SimulationResult = load.data
        return ResolvedSimulationBundle(
            result_path=result_path,
            bundle_dir=actual_bundle,
            result=sim_result,
            circuit_file=str(sim_result.file_path or ""),
        )

def _validate_result_handle(
    project_root: str,
    raw_result_path: str,
) -> Union[tuple[str, Path], ToolResult]:
    if "\\" in raw_result_path:
        return _error(
            "result_path must be the project-relative POSIX handle returned "
            "by run_simulation; backslashes are not accepted."
        )

    posix_path = PurePosixPath(raw_result_path)
    parts = posix_path.parts
    if (
        posix_path.is_absolute()
        or Path(raw_result_path).is_absolute()
        or raw_result_path != posix_path.as_posix()
        or any(part in {"", ".", ".."} or ":" in part for part in parts)
        or len(parts) < 4
        or parts[0] != "simulation_results"
        or parts[-1] != "result.json"
    ):
        return _error(
            "invalid result_path handle. Expected a canonical project-relative "
            "path shaped like "
            "'simulation_results/<circuit>/<run>/result.json'."
        )

    try:
        root = Path(project_root).resolve()
        candidate = (root / Path(*parts)).resolve()
    except (OSError, RuntimeError) as exc:
        return _error(f"result_path could not be resolved safely: {exc}")
    try:
        candidate.relative_to(root / "simulation_results")
    except ValueError:
        return _error("result_path escapes the project's simulation_results directory.")
    return posix_path.as_posix(), candidate


def _error(message: str) -> ToolResult:
    return ToolResult(content=f"Error: {message}", is_error=True)


__all__ = [
    "SimulationArtifactReaderBase",
    "ResolvedSimulationBundle",
    "READ_TOOL_SHARED_GUIDELINES",
]
