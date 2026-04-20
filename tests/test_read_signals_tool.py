import asyncio
import json
from pathlib import Path

import numpy as np

from domain.llm.agent.tools.read_signals import ReadSignalsTool
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


def _make_complex_ac_result() -> SimulationResult:
    frequency = np.array([1.0, 10.0, 100.0], dtype=float)
    response = np.array([1.0 + 1.0j, 0.5 + 0.5j, 0.1 + 0.1j], dtype=complex)
    return SimulationResult(
        executor="spice",
        file_path="circuits/complex_amp.cir",
        analysis_type="ac",
        analysis_command=".ac dec 10 1 100",
        success=True,
        x_axis_kind="frequency",
        x_axis_label="Frequency (Hz)",
        x_axis_scale="log",
        data=SimulationData(
            frequency=frequency,
            signals={"V(out)": response},
            signal_types={"V(out)": "voltage"},
        ),
    )


def test_read_signals_raw_reads_authoritative_result_data_without_raw_artifact(tmp_path: Path):
    result_path = "simulation_results/complex_amp/2026-04-19/result.json"
    bundle_dir = tmp_path / "simulation_results" / "complex_amp" / "2026-04-19"
    bundle_dir.mkdir(parents=True)
    result = _make_complex_ac_result()
    context = _make_context(tmp_path, result_path, result, bundle_dir)

    tool_result = asyncio.run(
        ReadSignalsTool().execute("call-raw-1", {"result_path": result_path}, context)
    )

    assert tool_result.is_error is False
    assert tool_result.details["source"] == "raw"
    assert tool_result.details["source_authority"] == "simulation_result.data"
    assert tool_result.details["signal_count"] == 4
    assert tool_result.details["source_json_path"] is None
    assert "V(out)_mag" in tool_result.content
    assert "V(out)_phase" in tool_result.content


def test_read_signals_raw_filter_uses_waveform_authority_normalization_and_complex_expansion(tmp_path: Path):
    result_path = "simulation_results/complex_amp/2026-04-19/result.json"
    bundle_dir = tmp_path / "simulation_results" / "complex_amp" / "2026-04-19"
    bundle_dir.mkdir(parents=True)
    result = _make_complex_ac_result()
    context = _make_context(tmp_path, result_path, result, bundle_dir)

    tool_result = asyncio.run(
        ReadSignalsTool().execute(
            "call-raw-2",
            {
                "result_path": result_path,
                "signal_filter": ["v(out)"],
            },
            context,
        )
    )

    assert tool_result.is_error is False
    assert tool_result.details["source"] == "raw"
    assert tool_result.details["signal_count"] == 4
    assert tool_result.details["unmatched_filter_names"] == []
    assert "V(out)_mag" in tool_result.content
    assert "V(out)_imag" in tool_result.content


def test_read_signals_chart_reads_json_sidecar_authority_without_chart_csv(tmp_path: Path):
    result_path = "simulation_results/tran_amp/2026-04-19/result.json"
    bundle_dir = tmp_path / "simulation_results" / "tran_amp" / "2026-04-19"
    charts_dir = bundle_dir / "charts"
    charts_dir.mkdir(parents=True)

    time = np.array([0.0, 1.0, 2.0], dtype=float)
    result = SimulationResult(
        executor="spice",
        file_path="circuits/tran_amp.cir",
        analysis_type="tran",
        analysis_command=".tran 1n 2n",
        success=True,
        x_axis_kind="time",
        x_axis_label="Time (s)",
        x_axis_scale="linear",
        data=SimulationData(
            time=time,
            signals={"V(out)": np.array([1.0, 2.0, 3.0], dtype=float)},
            signal_types={"V(out)": "voltage"},
        ),
    )

    chart_payload = simulation_artifact_exporter.build_artifact_payload(
        result,
        "chart",
        summary={
            "chart_index": 1,
            "chart_type": "waveform_time",
            "title": "Waveform",
            "series_count": 1,
            "row_count": 3,
        },
        files={"json": "01_waveform_time.json"},
        data={
            "chart_type": "waveform_time",
            "title": "Waveform",
            "x_label": "Time (s)",
            "y_label": "Voltage (V)",
            "secondary_y_label": "",
            "log_x": False,
            "log_y": False,
            "right_log_y": False,
            "series": [
                {
                    "name": "V(out)",
                    "color": "#ff0000",
                    "axis_key": "left",
                    "line_style": "solid",
                    "group_key": "V(out)",
                    "component": None,
                    "x": [0.0, 1.0, 2.0],
                    "y": [1.0, 2.0, 3.0],
                    "point_count": 3,
                }
            ],
            "rows": [
                {"Time (s)": 0.0, "V(out)": 1.0},
                {"Time (s)": 1.0, "V(out)": 2.0},
                {"Time (s)": 2.0, "V(out)": 3.0},
            ],
        },
        extra_metadata={"chart_index": 1},
    )
    (charts_dir / "01_waveform_time.json").write_text(
        json.dumps(chart_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    charts_manifest = simulation_artifact_exporter.build_artifact_payload(
        result,
        "charts",
        summary={"chart_count": 1},
        files={"items": [{"json": "01_waveform_time.json"}]},
        data={
            "charts": [
                {
                    "chart_index": 1,
                    "chart_type": "waveform_time",
                    "title": "Waveform",
                    "files": {"json": "01_waveform_time.json"},
                }
            ]
        },
    )
    (charts_dir / "charts.json").write_text(
        json.dumps(charts_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    context = _make_context(tmp_path, result_path, result, bundle_dir)
    tool_result = asyncio.run(
        ReadSignalsTool().execute(
            "call-chart-1",
            {"result_path": result_path, "source": "chart", "chart_index": 1},
            context,
        )
    )

    assert tool_result.is_error is False
    assert tool_result.details["source"] == "chart"
    assert tool_result.details["source_json_path"].endswith("01_waveform_time.json")
    assert tool_result.details["source_csv_path"] is None
    assert tool_result.details["signal_count"] == 1
    assert "source_authority" in tool_result.content
    assert "V(out)" in tool_result.content
