import asyncio
from pathlib import Path

import numpy as np
import pytest

from domain.llm.agent.tools.read_signals import ReadSignalsTool
from domain.llm.agent.tools.simulation_series_stats import (
    AnchorScale,
    read_series_table,
)
from domain.llm.agent.types import ToolContext
from domain.simulation.models.simulation_result import SimulationData, SimulationResult
from domain.simulation.spice.source_closure import collect_spice_source_closure
from shared.models.load_result import LoadResult


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


def _context(tmp_path: Path, result: SimulationResult):
    result_path = "simulation_results/amp/run-1/result.json"
    bundle_dir = tmp_path / "simulation_results" / "amp" / "run-1"
    bundle_dir.mkdir(parents=True)
    return result_path, ToolContext(
        project_root=str(tmp_path),
        sim_result_repository=_FakeRepository(result_path, result, bundle_dir),
    )


def _run(tool: ReadSignalsTool, params, context):
    return asyncio.run(tool.execute("call", params, context))


def _successful_result(
    tmp_path: Path,
    *,
    file_path: str,
    analysis_type: str,
    analysis_command: str,
    data: SimulationData,
) -> SimulationResult:
    circuit = tmp_path / file_path
    circuit.parent.mkdir(parents=True, exist_ok=True)
    circuit.write_text(
        "Agent signals fixture\n"
        "V1 in 0 DC 0 AC 1\n"
        "R1 in out 1k\n"
        f"{analysis_command}\n"
        ".end\n",
        encoding="utf-8",
    )
    return SimulationResult(
        executor="spice",
        file_path=file_path,
        analysis_type=analysis_type,
        analysis_command=analysis_command,
        success=True,
        source_digest=collect_spice_source_closure(circuit).digest,
        timestamp="2026-08-23T10:00:00+08:00",
        data=data,
    )


def test_read_signals_has_no_ui_chart_source_and_requires_exact_handle(tmp_path: Path):
    result = _successful_result(
        tmp_path,
        file_path="circuits/amp.cir",
        analysis_type="tran",
        analysis_command=".tran 1 2",
        data=SimulationData(
            time=np.array([0.0, 1.0, 2.0]),
            signals={"V(out)": np.array([0.0, 2.0, 4.0])},
            signal_types={"V(out)": "voltage"},
        ),
    )
    result_path, context = _context(tmp_path, result)
    tool = ReadSignalsTool()

    assert "source" not in tool.parameters["properties"]
    assert "chart_index" not in tool.parameters["properties"]
    assert tool.parameters["required"] == ["result_path"]

    response = _run(tool, {"result_path": result_path}, context)
    assert response.is_error is False
    assert response.details["source"] == "result.json:data"
    assert response.details["signal_count"] == 1
    assert "sample_mean" in response.content
    assert "| V(out) | 3 | 0 | 4 | 2 | 0 | 4 | 4 |" in response.content
    assert "zero_cross" not in response.content
    assert "source_image" not in response.content


def test_read_signals_filter_normalizes_and_expands_complex_signal(tmp_path: Path):
    result = _successful_result(
        tmp_path,
        file_path="circuits/ac.cir",
        analysis_type="ac",
        analysis_command=".ac dec 1 10 1k",
        data=SimulationData(
            frequency=np.array([10.0, 100.0, 1000.0]),
            signals={
                "V(out)": np.array([1 + 0j, 0 + 1j, -1 + 0j]),
                "V(in)": np.array([1 + 0j, 1 + 0j, 1 + 0j]),
            },
            signal_types={"V(out)": "voltage", "V(in)": "voltage"},
        ),
    )
    result_path, context = _context(tmp_path, result)
    response = _run(
        ReadSignalsTool(),
        {
            "result_path": result_path,
            "signal_filter": ["v(out)", "missing"],
            "anchor_count": 4,
        },
        context,
    )

    assert response.is_error is False
    assert response.details["signal_count"] == 4
    assert response.details["anchor_scale_effective"] == "log"
    assert response.details["unmatched_filter_names"] == ["missing"]
    assert "V(out)_mag" in response.content
    assert "V(out)_phase" in response.content
    assert "unmatched_signal_filter: missing" in response.content


def test_read_signals_rejects_large_unfiltered_table(tmp_path: Path):
    signals = {
        f"V(n{index})": np.array([float(index), float(index + 1)])
        for index in range(33)
    }
    result = _successful_result(
        tmp_path,
        file_path="circuits/many.cir",
        analysis_type="tran",
        analysis_command=".tran 1 1",
        data=SimulationData(
            time=np.array([0.0, 1.0]),
            signals=signals,
            signal_types={name: "voltage" for name in signals},
        ),
    )
    result_path, context = _context(tmp_path, result)
    response = _run(ReadSignalsTool(), {"result_path": result_path}, context)
    assert response.is_error is True
    assert "pass signal_filter" in response.content


@pytest.mark.parametrize(
    "params, message",
    [
        ({"signal_filter": "V(out)"}, "signal_filter must be an array"),
        ({"anchor_count": 3}, "anchor_count must be an integer"),
        ({"anchor_scale": "decade"}, "anchor_scale must be"),
    ],
)
def test_read_signals_rejects_invalid_arguments(
    tmp_path: Path, params, message: str
):
    result = _successful_result(
        tmp_path,
        file_path="circuits/amp.cir",
        analysis_type="tran",
        analysis_command=".tran 1 1",
        data=SimulationData(
            time=np.array([0.0, 1.0]),
            signals={"V(out)": np.array([0.0, 1.0])},
            signal_types={"V(out)": "voltage"},
        ),
    )
    result_path, context = _context(tmp_path, result)
    response = _run(
        ReadSignalsTool(), {"result_path": result_path, **params}, context
    )
    assert response.is_error is True
    assert message in response.content


def test_series_stats_labels_sample_mean_and_detects_non_monotonic_x():
    summary = read_series_table(
        x_column_name="Time",
        signal_column_names=["V(out)"],
        x_values=[0.0, 2.0, 1.0],
        signal_columns={"V(out)": [0.0, 10.0, 2.0]},
        anchor_count=4,
        anchor_scale=AnchorScale.LINEAR,
    )
    assert summary.x_order == "non_monotonic"
    assert summary.stats[0].sample_mean == 4.0
    assert not hasattr(summary.stats[0], "zero_crossings")


def test_series_stats_rejects_misaligned_signal_columns():
    with pytest.raises(ValueError, match="expected 3"):
        read_series_table(
            x_column_name="Time",
            signal_column_names=["V(out)"],
            x_values=[0.0, 1.0, 2.0],
            signal_columns={"V(out)": [0.0, 1.0]},
        )


def test_read_signals_nested_dc_keeps_native_rows_and_outer_branch_identity(tmp_path: Path):
    result = _successful_result(
        tmp_path, file_path="circuits/nested.cir", analysis_type="dc",
        analysis_command=".dc V1 0 1 1 V2 1 3 1",
        data=SimulationData(sweep=np.array([0., 1., 0., 1., 0., 1.]),
                            signals={"V(out)": np.arange(6.)},
                            signal_types={"V(out)": "voltage"}),
    )
    result_path, context = _context(tmp_path, result)
    response = _run(ReadSignalsTool(), {"result_path": result_path}, context)
    assert response.is_error is False
    assert response.details["sample_count"] == 6
    assert "Outer sweep V2" in response.content
    assert "native samples only" in response.content


def test_read_signals_phase_description_matches_unwrapped_values(tmp_path: Path):
    result = _successful_result(
        tmp_path, file_path="circuits/phase.cir", analysis_type="ac",
        analysis_command=".ac lin 2 1 2",
        data=SimulationData(frequency=np.array([1., 2.]),
                            signals={"V(out)": np.exp(1j * np.radians([179., -179.]))},
                            signal_types={"V(out)": "voltage"}),
    )
    result_path, context = _context(tmp_path, result)
    response = _run(ReadSignalsTool(), {"result_path": result_path, "signal_filter": ["V(out)_phase"]}, context)
    assert response.is_error is False
    assert "degrees unwrapped within each finite run" in response.content
    assert "181" in response.content
