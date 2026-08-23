import asyncio
from pathlib import Path

from domain.llm.agent.tools.read_output_log import ReadOutputLogTool
from domain.llm.agent.types import ToolContext
from domain.simulation.data.simulation_artifact_exporter import (
    simulation_artifact_exporter,
)
from domain.simulation.models.simulation_result import SimulationResult
from shared.models.load_result import LoadResult


class _Repository:
    def __init__(self, result_path, result, bundle_dir):
        self.result_path = result_path
        self.result = result
        self.bundle_dir = bundle_dir

    def load(self, project_root, result_path):
        if result_path == self.result_path:
            return LoadResult.ok(self.result, result_path)
        return LoadResult.file_missing(result_path)

    def resolve_bundle_dir(self, project_root, result_path):
        return self.bundle_dir if result_path == self.result_path else None


def _setup(tmp_path: Path, raw_output="raw simulator output"):
    result = SimulationResult(
        executor="spice",
        file_path="circuits/amp.cir",
        analysis_type="tran",
        success=False,
        timestamp="2026-08-23T10:00:00",
        raw_output=raw_output,
    )
    result_path = "simulation_results/amp/run-1/result.json"
    bundle_dir = tmp_path / "simulation_results" / "amp" / "run-1"
    bundle_dir.mkdir(parents=True)
    repository = _Repository(result_path, result, bundle_dir)
    context = ToolContext(
        project_root=str(tmp_path),
        sim_result_repository=repository,
    )
    return result_path, bundle_dir, repository, context


def _run(params, context):
    return asyncio.run(ReadOutputLogTool().execute("call", params, context))


def test_read_output_log_parses_embedded_raw_output_without_sidecar(
    tmp_path: Path,
):
    result_path, _, _, context = _setup(
        tmp_path,
        "starting\nwarning: device model\nfatal convergence failure",
    )

    response = _run({"result_path": result_path}, context)

    assert response.is_error is False
    assert response.details["source"] == "result.json:raw_output"
    assert response.details["total_lines"] == 3
    assert response.details["error_count"] == 1
    assert response.details["warning_count"] == 1
    assert "first_error: fatal convergence failure" in response.content


def test_read_output_log_all_returns_exact_embedded_raw_output(tmp_path: Path):
    result_path, _, _, context = _setup(tmp_path, "RAW-A\nRAW-B")

    response = _run(
        {"result_path": result_path, "section": "all"}, context
    )

    assert response.is_error is False
    assert "## raw simulator output" in response.content
    assert "RAW-A\nRAW-B" in response.content


def test_read_output_log_default_bounds_error_preview(tmp_path: Path):
    raw_output = "\n".join(f"error {index}" for index in range(100))
    result_path, _, _, context = _setup(tmp_path, raw_output)

    response = _run({"result_path": result_path}, context)

    assert response.is_error is False
    assert "50 additional line(s) omitted" in response.content
    assert "error 49" in response.content
    assert "error 50" not in response.content
    assert "error 80" in response.content


def test_read_output_log_ignores_tampered_derived_sidecars(tmp_path: Path):
    result_path, bundle_dir, _, context = _setup(
        tmp_path,
        "root output\nwarning: from root",
    )
    paths = simulation_artifact_exporter.output_log_paths(bundle_dir)
    paths.directory.mkdir()
    paths.json_path.write_text(
        '{"data":{"raw_output":"TAMPERED","lines":[]}}',
        encoding="utf-8",
    )
    paths.text_path.write_text("CONFLICTING TEXT", encoding="utf-8")

    response = _run(
        {"result_path": result_path, "section": "all"}, context
    )

    assert response.is_error is False
    assert "root output" in response.content
    assert "TAMPERED" not in response.content
    assert "CONFLICTING TEXT" not in response.content


def test_read_output_log_rejects_corrupt_embedded_raw_output(tmp_path: Path):
    result_path, _, repository, context = _setup(tmp_path)
    repository.result.raw_output = {"not": "text"}

    response = _run({"result_path": result_path}, context)

    assert response.is_error is True
    assert "raw_output must be a string or null" in response.content
