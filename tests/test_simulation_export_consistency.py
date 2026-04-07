from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

from domain.simulation.data.simulation_artifact_exporter import simulation_artifact_exporter
from domain.simulation.models.simulation_result import SimulationData, SimulationResult
from presentation.panels.simulation.analysis_chart_viewer import ChartViewer
from presentation.panels.simulation.waveform_widget import WaveformWidget


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def sample_result() -> SimulationResult:
    time = np.array([0.0, 0.1, 0.2, 0.3], dtype=float)
    data = SimulationData(
        time=time,
        signals={
            "V(out)": np.array([1.0, 2.0, 3.0, 4.0], dtype=float),
            "V(in)": np.array([0.5, 0.6, 0.7, 0.8], dtype=float),
        },
    )
    return SimulationResult(
        executor="spice",
        file_path="results/export_consistency.cir",
        analysis_type="tran",
        success=True,
        data=data,
        raw_output="Simulation started\nwarning: test warning\nSimulation finished",
        timestamp="2026-04-06T00:10:00",
        x_axis_kind="time",
        x_axis_label="Time (s)",
        x_axis_scale="linear",
        analysis_command=".tran 1n 1u",
        analysis_info={
            "parameters": {
                "step_time": "1n",
                "stop_time": "1u",
            }
        },
    )


@pytest.fixture
def sample_ac_result() -> SimulationResult:
    frequency = np.array([1e3, 1e4, 1e5, 1e6], dtype=float)
    response = np.array([
        0.70710678 - 0.70710678j,
        0.09950372 - 0.99503719j,
        0.0099995 - 0.99995j,
        0.001 - 0.9999995j,
    ], dtype=complex)
    data = SimulationData(
        frequency=frequency,
        signals={
            "V(out)": response,
        },
    )
    return SimulationResult(
        executor="spice",
        file_path="results/export_consistency_ac.cir",
        analysis_type="ac",
        success=True,
        data=data,
        raw_output="AC simulation finished",
        timestamp="2026-04-06T00:15:00",
        x_axis_kind="frequency",
        x_axis_label="Frequency (Hz)",
        x_axis_scale="log",
        analysis_command=".ac dec 20 1k 1Meg",
        analysis_info={
            "parameters": {
                "sweep_type": "dec",
                "points_per_decade": "20",
                "start_frequency": "1k",
                "stop_frequency": "1Meg",
            }
        },
    )


@pytest.fixture
def sample_metrics():
    return [
        SimpleNamespace(
            display_name="Gain",
            name="gain",
            value="20",
            unit="dB",
            target=">= 18 dB",
            is_met=True,
            trend="up",
            category="performance",
            raw_value=20.0,
            confidence=0.95,
            error_message="",
        )
    ]


def _assert_common_artifact_payload(payload: dict, artifact_type: str, *, expected_file_name: str, expected_x_axis_label: str):
    assert payload["artifact_type"] == artifact_type
    assert payload["schema_version"] == 1
    assert isinstance(payload["metadata"], dict)
    assert isinstance(payload["summary"], dict)
    assert isinstance(payload["files"], dict)
    assert isinstance(payload["data"], dict)
    assert payload["metadata"]["file_name"] == expected_file_name
    assert payload["metadata"]["x_axis_label"] == expected_x_axis_label


def test_artifact_exporter_outputs_common_payload_schema(sample_result: SimulationResult, sample_metrics, tmp_path: Path):
    export_root = simulation_artifact_exporter.create_export_root(str(tmp_path), sample_result)

    simulation_artifact_exporter.export_metrics(export_root, sample_result, sample_metrics, 88.0)
    simulation_artifact_exporter.export_analysis_info(export_root, sample_result)
    simulation_artifact_exporter.export_raw_data(export_root, sample_result)
    simulation_artifact_exporter.export_output_log(export_root, sample_result)

    metrics_payload = __import__("json").loads((export_root / "metrics" / "metrics.json").read_text(encoding="utf-8"))
    analysis_payload = __import__("json").loads((export_root / "analysis_info" / "analysis_info.json").read_text(encoding="utf-8"))
    raw_data_payload = __import__("json").loads((export_root / "raw_data" / "raw_data.json").read_text(encoding="utf-8"))
    output_log_payload = __import__("json").loads((export_root / "output_log" / "output_log.json").read_text(encoding="utf-8"))

    _assert_common_artifact_payload(metrics_payload, "metrics", expected_file_name="export_consistency.cir", expected_x_axis_label="Time (s)")
    _assert_common_artifact_payload(analysis_payload, "analysis_info", expected_file_name="export_consistency.cir", expected_x_axis_label="Time (s)")
    _assert_common_artifact_payload(raw_data_payload, "raw_data", expected_file_name="export_consistency.cir", expected_x_axis_label="Time (s)")
    _assert_common_artifact_payload(output_log_payload, "output_log", expected_file_name="export_consistency.cir", expected_x_axis_label="Time (s)")

    assert metrics_payload["data"]["columns"][0] == "display_name"
    assert analysis_payload["files"]["text"] == "analysis_info.txt"
    assert raw_data_payload["data"]["columns"][0] == "Time (s)"
    assert len(raw_data_payload["data"]["rows"]) == 4
    assert len(raw_data_payload["data"]["series"]) == 2
    assert output_log_payload["files"]["text"] == "output_log.txt"
    assert len(output_log_payload["data"]["lines"]) == 3
    assert output_log_payload["summary"]["warning_count"] == 1


def test_chart_and_waveform_exports_follow_common_payload_schema(qapp, sample_result: SimulationResult, tmp_path: Path):
    chart_viewer = ChartViewer()
    chart_viewer.load_result(sample_result)

    waveform_widget = WaveformWidget()
    waveform_widget.load_waveform(sample_result, "V(out)")
    waveform_widget.add_waveform(sample_result, "V(in)")

    charts_dir = tmp_path / "charts"
    waveforms_dir = tmp_path / "waveforms"

    chart_viewer.export_bundle(str(charts_dir))
    waveform_widget.export_bundle(str(waveforms_dir))

    charts_manifest = __import__("json").loads((charts_dir / "charts.json").read_text(encoding="utf-8"))
    chart_payload = __import__("json").loads((charts_dir / "01_waveform_time.json").read_text(encoding="utf-8"))
    waveform_payload = __import__("json").loads((waveforms_dir / "waveform.json").read_text(encoding="utf-8"))

    _assert_common_artifact_payload(charts_manifest, "charts", expected_file_name="export_consistency_ac.cir", expected_x_axis_label="Frequency (Hz)")
    _assert_common_artifact_payload(chart_payload, "chart", expected_file_name="export_consistency_ac.cir", expected_x_axis_label="Frequency (Hz)")
    _assert_common_artifact_payload(waveform_payload, "waveforms", expected_file_name="export_consistency.cir", expected_x_axis_label="Time (s)")

    assert charts_manifest["summary"]["chart_count"] == 1
    assert chart_payload["data"]["chart_type"] == "waveform_time"
    assert len(chart_payload["data"]["series"]) == 2
    assert waveform_payload["data"]["columns"][0] == "Time (s)"
    assert len(waveform_payload["data"]["series"]) == 2
    assert waveform_payload["summary"]["row_count"] == 4


def test_ac_chart_exports_single_bode_overlay_with_dual_axis_metadata(qapp, sample_ac_result: SimulationResult, tmp_path: Path):
    chart_viewer = ChartViewer()
    chart_viewer.load_result(sample_ac_result)

    assert len(chart_viewer._chart_specs) == 1
    assert chart_viewer._chart_specs[0].chart_type.value == "bode_overlay"
    assert chart_viewer._pages[0].supports_data_cursor() is True

    charts_dir = tmp_path / "ac_charts"
    chart_viewer.export_bundle(str(charts_dir))

    charts_manifest = __import__("json").loads((charts_dir / "charts.json").read_text(encoding="utf-8"))
    chart_payload = __import__("json").loads((charts_dir / "01_bode_overlay.json").read_text(encoding="utf-8"))

    _assert_common_artifact_payload(charts_manifest, "charts", expected_file_name="export_consistency_ac.cir", expected_x_axis_label="Frequency (Hz)")
    _assert_common_artifact_payload(chart_payload, "chart", expected_file_name="export_consistency_ac.cir", expected_x_axis_label="Frequency (Hz)")

    assert charts_manifest["summary"]["chart_count"] == 1
    assert chart_payload["data"]["chart_type"] == "bode_overlay"
    assert chart_payload["data"]["secondary_y_label"] == "Phase (°)"
    assert chart_payload["data"]["log_x"] is True
    assert len(chart_payload["data"]["series"]) == 2

    series_by_name = {series["name"]: series for series in chart_payload["data"]["series"]}
    assert series_by_name["V(out) | Mag"]["axis_key"] == "left"
    assert series_by_name["V(out) | Mag"]["line_style"] == "solid"
    assert series_by_name["V(out) | Phase"]["axis_key"] == "right"
    assert series_by_name["V(out) | Phase"]["line_style"] == "dash"
    assert chart_payload["summary"]["series_count"] == 2
