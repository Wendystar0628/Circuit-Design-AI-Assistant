import asyncio
from pathlib import Path

import numpy as np

from domain.llm.agent.tools.read_metrics import ReadMetricsTool
from domain.llm.agent.types import ToolContext
from domain.simulation.data.simulation_artifact_exporter import (
    simulation_artifact_exporter,
)
from domain.simulation.measure.measure_result import MeasureResult, MeasureStatus
from domain.simulation.models.simulation_result import (
    NoiseTotals,
    SimulationData,
    SimulationResult,
)
from domain.simulation.spice.source_closure import collect_spice_source_closure
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


def _setup(tmp_path: Path, measurements):
    analysis_command = ".ac dec 1 10 1k"
    circuit = tmp_path / "circuits" / "amp.cir"
    circuit.parent.mkdir(parents=True)
    circuit.write_text(
        "Agent metrics fixture\n"
        "V1 in 0 DC 0 AC 1\n"
        "R1 in out 1k\n"
        f"{analysis_command}\n"
        ".end\n",
        encoding="utf-8",
    )
    result = SimulationResult(
        executor="spice",
        file_path="circuits/amp.cir",
        analysis_type="ac",
        analysis_command=analysis_command,
        success=True,
        source_digest=collect_spice_source_closure(circuit).digest,
        data=SimulationData(
            frequency=np.array([10.0, 100.0, 1000.0]),
            signals={"V(out)": np.array([1.0, 0.5, 0.1])},
            signal_types={"V(out)": "voltage"},
        ),
        timestamp="2026-08-23T10:00:00+08:00",
        measurements=measurements,
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
    return asyncio.run(ReadMetricsTool().execute("call", params, context))


def _setup_noise(
    tmp_path: Path,
    *,
    totals: NoiseTotals | None,
):
    point_count = 2 if totals is not None else 1
    analysis_command = f".noise V(out) I1 lin {point_count} 1 2"
    circuit = tmp_path / "circuits" / "noise.cir"
    circuit.parent.mkdir(parents=True)
    circuit.write_text(
        "Agent noise metrics fixture\n"
        "I1 in 0 AC 1\n"
        "R1 in out 1k\n"
        "R2 out 0 1k\n"
        f"{analysis_command}\n"
        ".end\n",
        encoding="utf-8",
    )
    result = SimulationResult(
        executor="spice",
        file_path="circuits/noise.cir",
        analysis_type="noise",
        analysis_command=analysis_command,
        success=True,
        source_digest=collect_spice_source_closure(circuit).digest,
        data=SimulationData(
            frequency=np.arange(1, point_count + 1, dtype=float),
            signals={
                "onoise_spectrum": np.full(point_count, 2e-9),
                "inoise_spectrum": np.full(point_count, 1e-9),
            },
            signal_types={
                "onoise_spectrum": "voltage",
                "inoise_spectrum": "current",
            },
            noise_totals=totals,
        ),
        timestamp="2026-08-23T10:00:00+08:00",
        measurements=None,
    )
    result = SimulationResult.from_dict(result.to_dict())
    result_path = "simulation_results/noise/run-1/result.json"
    bundle_dir = tmp_path / "simulation_results" / "noise" / "run-1"
    bundle_dir.mkdir(parents=True)
    context = ToolContext(
        project_root=str(tmp_path),
        sim_result_repository=_Repository(result_path, result, bundle_dir),
    )
    return result_path, context


def test_read_metrics_reads_embedded_measurements_without_sidecar(
    tmp_path: Path,
):
    result_path, _, _, context = _setup(
        tmp_path,
        [
            MeasureResult(
                name="gain_db",
                value=20.0,
                statement=".measure ac gain_db FIND VDB(out) AT=100",
            ),
            MeasureResult(
                name="bandwidth",
                value=2_000_000.0,
                statement=".measure ac bandwidth WHEN VDB(out)=-3",
            ),
        ],
    )

    response = _run({"result_path": result_path}, context)

    assert response.is_error is False
    assert response.details["source"] == "result.json:measurements"
    assert response.details["target_data_available"] is False
    assert response.details["target_comparison_performed"] is False
    assert response.details["metric_count"] == 2
    assert "integrated_noise_totals" not in response.details
    assert "20 dB" in response.content
    assert "2000000" in response.content
    assert "target_data: unavailable" in response.content
    assert "target_text" not in response.content
    assert "PASS" not in response.content
    assert "FAIL" not in response.content


def test_read_metrics_exposes_validated_integrated_noise_totals_separately(
    tmp_path: Path,
):
    tool = ReadMetricsTool()
    result_path, context = _setup_noise(
        tmp_path,
        totals=NoiseTotals(output_rms=3e-9, input_referred_rms=1.5e-9),
    )

    response = asyncio.run(
        tool.execute("call", {"result_path": result_path}, context)
    )

    assert response.is_error is False
    assert "integrated RMS noise totals" in tool.prompt_snippet
    assert any(
        "never integrate" in guideline
        for guideline in tool.prompt_guidelines
    )
    assert response.details["metric_count"] == 0
    assert response.details["integrated_noise_totals"] == {
        "source": "result.json:data.noise_totals",
        "available": True,
        "items": [
            {"key": "output_rms", "value": 3e-9, "unit": "V"},
            {
                "key": "input_referred_rms",
                "value": 1.5e-9,
                "unit": "A",
            },
        ],
    }
    assert "## Integrated Noise Totals" in response.content
    assert "FSTART-to-FSTOP sweep band" in response.content
    assert "not .MEASURE rows or spectral-density samples" in response.content
    assert "- output_rms: 3e-09 V RMS" in response.content
    assert "- input_referred_rms: 1.5e-09 A RMS" in response.content
    assert "√Hz" not in response.content


def test_read_metrics_reports_missing_noise_totals_without_inference(
    tmp_path: Path,
):
    result_path, context = _setup_noise(tmp_path, totals=None)

    response = _run({"result_path": result_path}, context)

    assert response.is_error is False
    assert response.details["integrated_noise_totals"] == {
        "source": "result.json:data.noise_totals",
        "available": False,
        "items": [],
    }
    assert "status: unavailable for this run" in response.content
    assert "sampled spectra were not integrated to invent totals" in response.content
    assert "output_rms:" not in response.content


def test_read_metrics_exact_filter_and_missing_name(tmp_path: Path):
    result_path, _, _, context = _setup(
        tmp_path,
        [
            MeasureResult(
                name="gain_db",
                value=20.0,
                statement=".measure ac gain_db FIND VDB(out) AT=100",
            )
        ],
    )
    selected = _run(
        {"result_path": result_path, "metric_name": "GAIN_DB"}, context
    )
    assert selected.is_error is False
    assert selected.details["metric_count"] == 1

    missing = _run(
        {"result_path": result_path, "metric_name": "phase_margin"}, context
    )
    assert missing.is_error is True
    assert "Available: gain_db" in missing.content


def test_read_metrics_ignores_tampered_derived_sidecar(tmp_path: Path):
    result_path, bundle_dir, _, context = _setup(
        tmp_path,
        [
            MeasureResult(
                name="root_value",
                value=1.25,
                statement=".measure ac root_value FIND V(out) AT=100",
            )
        ],
    )
    paths = simulation_artifact_exporter.metrics_paths(bundle_dir)
    paths.directory.mkdir()
    paths.json_path.write_text(
        '{"rows":[{"name":"tampered","raw_value":999}]}',
        encoding="utf-8",
    )
    paths.csv_path.write_text("tampered,999", encoding="utf-8")

    response = _run({"result_path": result_path}, context)

    assert response.is_error is False
    assert "Root Value" in response.content
    assert "1.25 V" in response.content
    assert "tampered" not in response.content
    assert "999" not in response.content


def test_read_metrics_rejects_corrupt_embedded_measurement_container(
    tmp_path: Path,
):
    result_path, _, repository, context = _setup(tmp_path, [])
    repository.result.measurements = {"not": "a list"}

    response = _run({"result_path": result_path}, context)

    assert response.is_error is True
    assert "measurements must be a list" in response.content


def test_read_metrics_reports_failed_measure_without_failing_the_tool(tmp_path: Path):
    result_path, _, _, context = _setup(
        tmp_path,
        [
            MeasureResult(
                name="bandwidth",
                value=None,
                status=MeasureStatus.FAILED,
                statement=".measure ac bandwidth WHEN VDB(out)=-3",
                error_message="Error: out of interval",
            )
        ],
    )

    response = _run({"result_path": result_path}, context)

    assert response.is_error is False
    assert response.details["metric_count"] == 1
    assert response.details["failed_metric_count"] == 1
    assert "| Bandwidth | FAILED | — | — | Hz | Error: out of interval |" in response.content
