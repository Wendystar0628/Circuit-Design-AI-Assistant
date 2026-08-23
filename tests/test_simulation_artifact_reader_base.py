from pathlib import Path

import numpy as np
import pytest

from domain.llm.agent.tools.simulation_artifact_reader_base import (
    ResolvedSimulationBundle,
    SimulationArtifactReaderBase,
)
from domain.llm.agent.types import ToolContext, ToolResult
from domain.simulation.models.simulation_result import SimulationData, SimulationResult
from domain.simulation.spice.source_closure import collect_spice_source_closure
from shared.models.load_result import LoadResult


class _FakeRepository:
    def __init__(self, result_path: str = "", result=None, bundle_dir=None):
        self.result_path = result_path
        self.result = result
        self.bundle_dir = bundle_dir

    def load(self, project_root: str, result_path: str):
        if result_path == self.result_path and self.result is not None:
            return LoadResult.ok(self.result, result_path)
        return LoadResult.file_missing(result_path)

    def resolve_bundle_dir(self, project_root: str, result_path: str):
        return self.bundle_dir if result_path == self.result_path else None


def _result(tmp_path: Path) -> SimulationResult:
    analysis_command = ".tran 1 1"
    circuit = tmp_path / "circuits" / "amp.cir"
    circuit.parent.mkdir(parents=True, exist_ok=True)
    circuit.write_text(
        "Artifact reader fixture\n"
        "V1 in 0 1\n"
        "R1 in out 1k\n"
        f"{analysis_command}\n"
        ".end\n",
        encoding="utf-8",
    )
    return SimulationResult(
        executor="spice",
        file_path="circuits/amp.cir",
        analysis_type="tran",
        analysis_command=analysis_command,
        success=True,
        source_digest=collect_spice_source_closure(circuit).digest,
        timestamp="2026-08-23T10:00:00+08:00",
        data=SimulationData(
            time=np.array([0.0, 1.0]),
            signals={"V(out)": np.array([0.0, 1.0])},
            signal_types={"V(out)": "voltage"},
        ),
    )


def _resolved(tmp_path: Path, result=None):
    result_path = "simulation_results/amp/run-1/result.json"
    bundle_dir = tmp_path / "simulation_results" / "amp" / "run-1"
    bundle_dir.mkdir(parents=True)
    sim_result = result or _result(tmp_path)
    repository = _FakeRepository(result_path, sim_result, bundle_dir)
    context = ToolContext(
        project_root=str(tmp_path), sim_result_repository=repository
    )
    resolved = SimulationArtifactReaderBase.resolve(
        {"result_path": result_path}, context
    )
    assert isinstance(resolved, ResolvedSimulationBundle)
    return resolved


def test_schema_requires_only_exact_result_handle():
    schema = SimulationArtifactReaderBase.build_parameters_schema(
        extra_properties={"section": {"type": "string"}}
    )
    assert set(schema["properties"]) == {"result_path", "section"}
    assert schema["required"] == ["result_path"]
    assert "file_path" not in schema["properties"]


def test_schema_rejects_result_path_override():
    with pytest.raises(ValueError, match="collide"):
        SimulationArtifactReaderBase.build_parameters_schema(
            extra_properties={"result_path": {"type": "integer"}}
        )


def test_resolve_requires_injected_repository_and_project(tmp_path: Path):
    missing_repo = SimulationArtifactReaderBase.resolve(
        {"result_path": "simulation_results/a/b/result.json"},
        ToolContext(project_root=str(tmp_path)),
    )
    assert isinstance(missing_repo, ToolResult) and missing_repo.is_error
    assert "ToolContext" in missing_repo.content

    missing_project = SimulationArtifactReaderBase.resolve(
        {"result_path": "simulation_results/a/b/result.json"},
        ToolContext(project_root="", sim_result_repository=_FakeRepository()),
    )
    assert isinstance(missing_project, ToolResult) and missing_project.is_error
    assert "project" in missing_project.content.lower()


def test_resolve_requires_result_path_without_latest_fallback(tmp_path: Path):
    result = SimulationArtifactReaderBase.resolve(
        {},
        ToolContext(
            project_root=str(tmp_path),
            current_file=str(tmp_path / "circuits" / "amp.cir"),
            sim_result_repository=_FakeRepository(),
        ),
    )
    assert isinstance(result, ToolResult) and result.is_error
    assert "result_path is required" in result.content
    assert "fallbacks do not exist" in result.content


@pytest.mark.parametrize(
    "handle",
    [
        "../outside/result.json",
        "simulation_results/amp/../outside/result.json",
        "simulation_results\\amp\\run-1\\result.json",
        "other/amp/run-1/result.json",
        "simulation_results/amp/run-1/not-result.json",
        "simulation_results//amp/run-1/result.json",
    ],
)
def test_resolve_rejects_noncanonical_or_escaping_handles(
    tmp_path: Path, handle: str
):
    result = SimulationArtifactReaderBase.resolve(
        {"result_path": handle},
        ToolContext(
            project_root=str(tmp_path),
            sim_result_repository=_FakeRepository(),
        ),
    )
    assert isinstance(result, ToolResult) and result.is_error


def test_resolve_rejects_absolute_handle(tmp_path: Path):
    absolute = (
        tmp_path / "simulation_results" / "amp" / "run-1" / "result.json"
    )
    result = SimulationArtifactReaderBase.resolve(
        {"result_path": absolute.as_posix()},
        ToolContext(
            project_root=str(tmp_path),
            sim_result_repository=_FakeRepository(),
        ),
    )
    assert isinstance(result, ToolResult) and result.is_error
    assert "invalid result_path" in result.content


def test_resolve_exact_handle(tmp_path: Path):
    resolved = _resolved(tmp_path)
    assert resolved.result_path == "simulation_results/amp/run-1/result.json"
    assert resolved.bundle_dir == (
        tmp_path / "simulation_results" / "amp" / "run-1"
    ).resolve()
    assert resolved.circuit_file == "circuits/amp.cir"


def test_resolve_rejects_repository_bundle_identity_mismatch(tmp_path: Path):
    result_path = "simulation_results/amp/run-1/result.json"
    wrong_bundle = tmp_path / "simulation_results" / "other" / "run-1"
    wrong_bundle.mkdir(parents=True)
    result = SimulationArtifactReaderBase.resolve(
        {"result_path": result_path},
        ToolContext(
            project_root=str(tmp_path),
            sim_result_repository=_FakeRepository(
                result_path, _result(tmp_path), wrong_bundle
            ),
        ),
    )
    assert isinstance(result, ToolResult) and result.is_error
    assert "mismatched bundle" in result.content
