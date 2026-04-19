import asyncio
from pathlib import Path

from domain.llm.agent.tools.read_op_result import ReadOpResultTool
from domain.llm.agent.types import ToolContext
from domain.simulation.data.simulation_artifact_exporter import simulation_artifact_exporter
from domain.simulation.models.simulation_result import SimulationData, SimulationResult
from shared.models.load_result import LoadResult


class _FakeRepository:
    def __init__(self, *, result_path: str, result: SimulationResult, bundle_dir: Path):
        self._result_path = result_path
        self._result = result
        self._bundle_dir = bundle_dir

    def load(self, project_root: str, result_path: str):
        if result_path == self._result_path:
            return LoadResult.ok(self._result, result_path)
        return LoadResult.file_missing(result_path)

    def resolve_bundle_dir(self, project_root: str, result_path: str):
        if result_path == self._result_path:
            return self._bundle_dir
        return None

    def list_by_circuit(self, project_root: str, per_circuit_limit: int = 5):
        return []


def _make_context(tmp_path: Path, result_path: str, result: SimulationResult, bundle_dir: Path) -> ToolContext:
    return ToolContext(
        project_root=str(tmp_path),
        current_file=None,
        sim_result_repository=_FakeRepository(
            result_path=result_path,
            result=result,
            bundle_dir=bundle_dir,
        ),
    )


def test_read_op_result_rejects_non_op_analysis(tmp_path: Path):
    result_path = "simulation_results/amp/2026-01-01/result.json"
    bundle_dir = tmp_path / "simulation_results" / "amp" / "2026-01-01"
    bundle_dir.mkdir(parents=True)
    result = SimulationResult(
        executor="spice",
        file_path="circuits/amp.cir",
        analysis_type="tran",
        success=True,
        data=SimulationData(),
    )
    context = _make_context(tmp_path, result_path, result, bundle_dir)

    tool_result = asyncio.run(
        ReadOpResultTool().execute("call-1", {"result_path": result_path}, context)
    )

    assert tool_result.is_error is True
    assert "only supports actual .op" in tool_result.content


def test_read_op_result_falls_back_to_structured_payload_when_text_missing(tmp_path: Path):
    result_path = "simulation_results/op_amp/2026-01-01/result.json"
    bundle_dir = tmp_path / "simulation_results" / "op_amp" / "2026-01-01"
    bundle_dir.mkdir(parents=True)
    result = SimulationResult(
        executor="spice",
        file_path="circuits/op_amp.cir",
        analysis_type="op",
        success=True,
        analysis_command=".op",
        data=SimulationData(
            op_result={
                "nodes": [
                    {"name": "VDD", "voltage": 5.0, "formatted": "5 V"},
                    {"name": "out", "voltage": 2.5, "formatted": "2.5 V"},
                ],
                "branches": [
                    {"device": "V1", "current": 0.001, "formatted": "0.001 A"},
                ],
            }
        ),
    )
    context = _make_context(tmp_path, result_path, result, bundle_dir)

    tool_result = asyncio.run(
        ReadOpResultTool().execute("call-2", {"result_path": result_path}, context)
    )

    assert tool_result.is_error is False
    assert "# artifact_type: op_result" in tool_result.content
    assert "## nodes" in tool_result.content
    assert "| name | voltage | formatted |" in tool_result.content
    assert "| VDD | 5 | 5 V |" in tool_result.content
    assert "## branches" in tool_result.content
    assert tool_result.details["source"] == "result.data.op_result"


def test_read_op_result_prefers_preformatted_text_when_available(tmp_path: Path):
    result_path = "simulation_results/op_text/2026-01-01/result.json"
    bundle_dir = tmp_path / "simulation_results" / "op_text" / "2026-01-01"
    bundle_dir.mkdir(parents=True)
    result = SimulationResult(
        executor="spice",
        file_path="circuits/op_text.cir",
        analysis_type="op",
        success=True,
        analysis_command=".op",
        data=SimulationData(
            op_result={
                "nodes": [{"name": "out", "voltage": 1.2, "formatted": "1.2 V"}],
                "branches": [{"device": "V1", "current": 0.0005, "formatted": "0.0005 A"}],
            }
        ),
    )
    paths = simulation_artifact_exporter.op_result_paths(bundle_dir)
    paths.directory.mkdir(parents=True, exist_ok=True)
    expected_text = (
        simulation_artifact_exporter.build_text_header_block(result, "op_result")
        + "## nodes\n"
        + "| name | voltage | formatted |\n"
        + "| --- | --- | --- |\n"
        + "| out | 1.2 | 1.2 V |\n\n"
        + "## branches\n"
        + "| device | current | formatted |\n"
        + "| --- | --- | --- |\n"
        + "| V1 | 0.0005 | 0.0005 A |"
    )
    paths.text_path.write_text(expected_text, encoding="utf-8")
    context = _make_context(tmp_path, result_path, result, bundle_dir)

    tool_result = asyncio.run(
        ReadOpResultTool().execute("call-3", {"result_path": result_path}, context)
    )

    assert tool_result.is_error is False
    assert tool_result.content == expected_text
    assert tool_result.details["source"] == "op_result.txt"
