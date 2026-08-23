import asyncio
import json
from pathlib import Path

import numpy as np

from domain.llm.agent.tools.read_op_result import ReadOpResultTool
from domain.llm.agent.types import ToolContext
from domain.simulation.data.simulation_artifact_exporter import (
    CATEGORY_OP_RESULT,
    simulation_artifact_exporter,
)
from domain.simulation.models.simulation_result import SimulationData, SimulationResult
from shared.models.load_result import LoadResult

_SOURCE_DIGEST = "b" * 64


class _FakeRepository:
    def __init__(self, result_path: str, result: SimulationResult, bundle_dir: Path):
        self.result_path = result_path
        self.result = result
        self.bundle_dir = bundle_dir

    def load(self, project_root: str, result_path: str):
        if result_path == self.result_path:
            return LoadResult.ok(self.result, result_path)
        return LoadResult.file_missing(result_path)

    def resolve_bundle_dir(self, project_root: str, result_path: str):
        return self.bundle_dir if result_path == self.result_path else None


def _setup(tmp_path: Path, result: SimulationResult):
    result_path = "simulation_results/op/run-1/result.json"
    bundle_dir = tmp_path / "simulation_results" / "op" / "run-1"
    bundle_dir.mkdir(parents=True)
    context = ToolContext(
        project_root=str(tmp_path),
        sim_result_repository=_FakeRepository(result_path, result, bundle_dir),
    )
    return result_path, bundle_dir, context


def _run(params, context):
    return asyncio.run(ReadOpResultTool().execute("call", params, context))


def test_read_op_result_rejects_non_op_analysis(tmp_path: Path):
    result = SimulationResult(
        executor="spice",
        file_path="circuits/amp.cir",
        analysis_type="tran",
        success=True,
        source_digest=_SOURCE_DIGEST,
        timestamp="2026-08-23T10:00:00",
        data=SimulationData(),
        analysis_command=".tran 1u 1m",
    )
    result_path, _, context = _setup(tmp_path, result)
    response = _run({"result_path": result_path}, context)
    assert response.is_error is True
    assert "requires an exact .op bundle" in response.content


def test_read_op_result_derives_from_signals_and_ignores_tampered_sidecars(
    tmp_path: Path,
):
    result = SimulationResult(
        executor="spice",
        file_path="circuits/op.cir",
        analysis_type="op",
        success=True,
        source_digest=_SOURCE_DIGEST,
        timestamp="2026-08-23T10:00:00",
        data=SimulationData(
            signals={
                "V(out)": np.array([2.5]),
                "I(V1)": np.array([0.001]),
            },
            signal_types={"V(out)": "voltage", "I(V1)": "current"},
        ),
        analysis_command=".op",
    )
    result_path, bundle_dir, context = _setup(tmp_path, result)
    paths = simulation_artifact_exporter.op_result_paths(bundle_dir)
    paths.directory.mkdir()
    # Both derived exports deliberately contradict result.json.  The JSON also
    # carries stale identity metadata; neither file is an application read path.
    payload = simulation_artifact_exporter.build_artifact_payload(
        result,
        CATEGORY_OP_RESULT,
        data={
            "nodes": [{"name": "tampered", "voltage": 99.0, "formatted": "99 V"}],
            "branches": [],
            "devices": [],
            "row_count": 1,
            "section_count": 2,
        },
    )
    payload["metadata"]["file_path"] = "circuits/other.cir"
    paths.json_path.write_text(json.dumps(payload), encoding="utf-8")
    paths.text_path.write_text("## nodes\n| fake |", encoding="utf-8")

    response = _run({"result_path": result_path}, context)
    assert response.is_error is False
    assert response.details["source"] == "result.json:data.signals (derived OP view)"
    assert response.details["row_count"] == 2
    assert "| out | 2.5 | 2.5 V |" in response.content
    assert "| V1 | 0.001 | 0.001 A |" in response.content
    assert "fake" not in response.content
    assert "tampered" not in response.content
    assert "99 V" not in response.content


def test_read_op_result_rejects_empty_signals_even_with_valid_sidecar(
    tmp_path: Path,
):
    result = SimulationResult(
        executor="spice",
        file_path="circuits/op.cir",
        analysis_type="op",
        success=True,
        source_digest=_SOURCE_DIGEST,
        timestamp="2026-08-23T10:00:00",
        data=SimulationData(),
        analysis_command=".op",
    )
    result_path, bundle_dir, context = _setup(tmp_path, result)
    paths = simulation_artifact_exporter.op_result_paths(bundle_dir)
    paths.directory.mkdir()
    payload = simulation_artifact_exporter.build_artifact_payload(
        result,
        CATEGORY_OP_RESULT,
        data={
            "nodes": [{"name": "sidecar-only", "voltage": 2.5, "formatted": "2.5 V"}],
            "branches": [],
            "devices": [],
        },
    )
    paths.json_path.write_text(json.dumps(payload), encoding="utf-8")

    response = _run({"result_path": result_path}, context)
    assert response.is_error is True
    assert "data.signals produce no valid" in response.content
    assert "sidecar-only" not in response.content
