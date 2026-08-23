import struct
import zlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from domain.simulation.data.png_metadata import read_png_itxt_chunks
from domain.simulation.data.simulation_artifact_exporter import simulation_artifact_exporter
from domain.simulation.data.simulation_artifact_persistence import (
    simulation_artifact_persistence,
)
from domain.simulation.models.display_metric import DisplayMetric
from domain.simulation.models.simulation_result import (
    NoiseTotals,
    SimulationData,
    SimulationResult,
)
from domain.simulation.spice.source_closure import SPICE_SOURCE_CLOSURE_ALGORITHM
from presentation.panels.simulation.analysis_chart_viewer import ChartViewer
from presentation.panels.simulation.simulation_tab import SimulationTab
from presentation.panels.simulation.simulation_conversation_attachment_coordinator import SimulationConversationAttachmentCoordinator
from presentation.panels.simulation.simulation_export_panel import SimulationExportPanel
from presentation.panels.simulation.waveform_widget import WaveformWidget
from shared.event_types import (
    EVENT_UI_ACTIVATE_CONVERSATION_TAB,
    EVENT_UI_ATTACH_FILES_TO_CONVERSATION,
)
from shared.service_locator import ServiceLocator
from shared.service_names import SVC_EVENT_BUS


def _build_minimal_png_bytes() -> bytes:
    """Assemble a valid 1x1 RGBA PNG using pure stdlib so fake
    exporters in tests can emit real PNG files (and we can then verify
    ``iTXt`` chunks are injected after attach). No Pillow dependency.
    """
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    ihdr_crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF)
    ihdr = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + ihdr_crc
    raw = b"\x00" + b"\x00\x00\x00\x00"  # filter=None + transparent RGBA pixel
    idat_data = zlib.compress(raw, 9)
    idat_crc = struct.pack(">I", zlib.crc32(b"IDAT" + idat_data) & 0xFFFFFFFF)
    idat = struct.pack(">I", len(idat_data)) + b"IDAT" + idat_data + idat_crc
    iend_crc = struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF)
    iend = b"\x00\x00\x00\x00" + b"IEND" + iend_crc
    return b"\x89PNG\r\n\x1a\n" + ihdr + idat + iend


_MINIMAL_PNG_BYTES = _build_minimal_png_bytes()
_SOURCE_DIGEST = "0" * 64


@pytest.fixture
def sample_result() -> SimulationResult:
    time = np.array([0.0, 0.1, 0.2, 0.3], dtype=float)
    data = SimulationData(
        time=time,
        signals={
            "V(out)": np.array([1.0, 2.0, 3.0, 4.0], dtype=float),
            "V(in)": np.array([0.5, 0.6, 0.7, 0.8], dtype=float),
        },
        signal_types={
            "V(out)": "voltage",
            "V(in)": "voltage",
        },
    )
    result = SimulationResult(
        executor="spice",
        file_path="results/export_consistency.cir",
        analysis_type="tran",
        success=True,
        source_digest=_SOURCE_DIGEST,
        data=data,
        raw_output="Simulation started\nwarning: test warning\nSimulation finished",
        timestamp="2026-04-06T00:10:00Z",
        analysis_command=".tran 100m 300m",
    )
    return SimulationResult.from_dict(result.to_dict())


@pytest.fixture
def sample_mixed_axis_result() -> SimulationResult:
    time = np.array([0.0, 0.1, 0.2, 0.3], dtype=float)
    data = SimulationData(
        time=time,
        signals={
            "V(out)": np.array([1.0, 2.0, 3.0, 4.0], dtype=float),
            "I(V1)": np.array([1e-3, 1.5e-3, 2e-3, 2.5e-3], dtype=float),
        },
        signal_types={
            "V(out)": "voltage",
            "I(V1)": "current",
        },
    )
    return SimulationResult(
        executor="spice",
        file_path="results/export_consistency_mixed.cir",
        analysis_type="tran",
        success=True,
        source_digest=_SOURCE_DIGEST,
        data=data,
        raw_output="Transient mixed-axis simulation finished",
        timestamp="2026-04-06T00:12:00Z",
        analysis_command=".tran 100m 300m",
    )


@pytest.fixture
def sample_noise_result() -> SimulationResult:
    frequency = np.array([1e1, 1e2, 1e3, 1e4], dtype=float)
    data = SimulationData(
        frequency=frequency,
        signals={
            "onoise_spectrum": np.array([1e-9, 2e-9, 3e-9, 4e-9], dtype=float),
            "inoise_spectrum": np.array([2e-12, 3e-12, 4e-12, 5e-12], dtype=float),
        },
        signal_types={
            "onoise_spectrum": "voltage",
            "inoise_spectrum": "current",
        },
        noise_totals=NoiseTotals(
            output_rms=5e-9,
            input_referred_rms=7e-12,
        ),
    )
    result = SimulationResult(
        executor="spice",
        file_path="results/export_consistency_noise.cir",
        analysis_type="noise",
        success=True,
        source_digest=_SOURCE_DIGEST,
        data=data,
        raw_output="Noise simulation finished",
        timestamp="2026-04-06T00:18:00Z",
        analysis_command=".noise v(out) I1 dec 1 10 10k",
    )
    return SimulationResult.from_dict(result.to_dict())


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
        signal_types={"V(out)": "voltage"},
    )
    result = SimulationResult(
        executor="spice",
        file_path="results/export_consistency_ac.cir",
        analysis_type="ac",
        success=True,
        source_digest=_SOURCE_DIGEST,
        data=data,
        raw_output="AC simulation finished",
        timestamp="2026-04-06T00:15:00Z",
        analysis_command=".ac dec 1 1k 1Meg",
    )
    return SimulationResult.from_dict(result.to_dict())


@pytest.fixture
def invalid_derived_ac_result() -> SimulationResult:
    frequency = np.array([1e3, 1e4, 1e5, 1e6], dtype=float)
    data = SimulationData(
        frequency=frequency,
        signals={
            "V(out)_mag": np.array([0.70710678, 0.09950372, 0.0099995, 0.001], dtype=float),
            "V(out)_phase": np.array([-45.0, -84.2894, -89.4271, -89.9427], dtype=float),
        },
        signal_types={
            "V(out)_mag": "voltage",
            "V(out)_phase": "voltage",
        },
    )
    return SimulationResult(
        executor="spice",
        file_path="results/export_consistency_invalid_ac.cir",
        analysis_type="ac",
        success=True,
        source_digest=_SOURCE_DIGEST,
        data=data,
        raw_output="AC simulation finished",
        timestamp="2026-04-06T00:20:00Z",
        analysis_command=".ac dec 20 1k 1Meg",
    )


@pytest.fixture
def sample_metrics():
    return [
        DisplayMetric(
            display_name="Gain",
            name="gain",
            value="20",
            unit="dB",
            status="OK",
            error_message="",
            raw_value=20.0,
            target=">= 18 dB",
        )
    ]


def _assert_common_artifact_payload(payload: dict, artifact_type: str, *, expected_file_name: str, expected_x_axis_label: str):
    assert payload["artifact_type"] == artifact_type
    assert payload["schema_version"] == 2
    assert isinstance(payload["metadata"], dict)
    assert isinstance(payload["summary"], dict)
    assert isinstance(payload["files"], dict)
    assert isinstance(payload["data"], dict)
    assert payload["metadata"]["file_name"] == expected_file_name
    assert payload["metadata"]["x_axis_label"] == expected_x_axis_label
    assert payload["metadata"]["source_digest"] == _SOURCE_DIGEST
    assert (
        payload["metadata"]["source_digest_algorithm"]
        == SPICE_SOURCE_CLOSURE_ALGORITHM
    )


def test_artifact_exporter_outputs_common_payload_schema(sample_result: SimulationResult, sample_metrics, tmp_path: Path):
    export_root = simulation_artifact_exporter.create_export_root(str(tmp_path), sample_result)

    simulation_artifact_exporter.export_metrics(export_root, sample_result, sample_metrics)
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
    assert metrics_payload["data"]["columns"][4:6] == [
        "status",
        "error_message",
    ]
    assert metrics_payload["data"]["rows"][0]["status"] == "OK"
    assert metrics_payload["summary"]["failed_metric_count"] == 0
    assert analysis_payload["files"]["text"] == "analysis_info.txt"
    assert raw_data_payload["data"]["columns"][0] == "Time (s)"
    assert len(raw_data_payload["data"]["rows"]) == 4
    assert len(raw_data_payload["data"]["series"]) == 2
    assert output_log_payload["files"]["text"] == "output_log.txt"
    assert len(output_log_payload["data"]["lines"]) == 3
    assert output_log_payload["summary"]["warning_count"] == 1


def test_metric_export_preserves_failed_outcome_and_diagnostic(
    sample_result: SimulationResult,
    tmp_path: Path,
):
    export_root = simulation_artifact_exporter.create_export_root(
        str(tmp_path), sample_result
    )
    failed_metric = DisplayMetric(
        name="settling_time",
        display_name="Settling Time",
        value="",
        unit="s",
        status="FAILED",
        error_message="Error: out of interval",
        raw_value=None,
        target="< 1 ms",
    )

    simulation_artifact_exporter.export_metrics(
        export_root,
        sample_result,
        [failed_metric],
    )

    payload = __import__("json").loads(
        (export_root / "metrics" / "metrics.json").read_text(encoding="utf-8")
    )
    row = payload["data"]["rows"][0]
    assert payload["summary"]["failed_metric_count"] == 1
    assert row["status"] == "FAILED"
    assert row["error_message"] == "Error: out of interval"
    assert row["value"] == ""
    assert row["raw_value"] is None


def test_integrated_noise_totals_export_separately_from_density_series(
    tmp_path: Path,
):
    result = SimulationResult(
        executor="spice",
        file_path="results/noise_totals.cir",
        analysis_type="noise",
        success=True,
        source_digest=_SOURCE_DIGEST,
        data=SimulationData(
            frequency=np.array([1.0, 2.0]),
            signals={
                "onoise_spectrum": np.array([1e-9, 2e-9]),
                "inoise_spectrum": np.array([0.5e-9, 1e-9]),
            },
            signal_types={
                "onoise_spectrum": "voltage",
                "inoise_spectrum": "voltage",
            },
            noise_totals=NoiseTotals(
                output_rms=3e-9,
                input_referred_rms=1.5e-9,
            ),
        ),
        analysis_command=".noise V(out) V1 lin 2 1 2",
    )
    export_root = simulation_artifact_exporter.create_export_root(
        str(tmp_path), result
    )

    simulation_artifact_exporter.export_metrics(export_root, result, [])
    simulation_artifact_exporter.export_raw_data(export_root, result)
    simulation_artifact_exporter.export_analysis_info(export_root, result)

    json_module = __import__("json")
    metrics = json_module.loads(
        (export_root / "metrics" / "metrics.json").read_text(encoding="utf-8")
    )
    raw_data = json_module.loads(
        (export_root / "raw_data" / "raw_data.json").read_text(encoding="utf-8")
    )
    analysis_info = json_module.loads(
        (export_root / "analysis_info" / "analysis_info.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {
        "applicable": True,
        "available": True,
        "source": "ngspice_noise_totals",
        "items": [
            {"key": "output_rms", "value": 3e-9, "unit": "V"},
            {"key": "input_referred_rms", "value": 1.5e-9, "unit": "V"},
        ],
    }

    assert metrics["data"]["noise_totals"] == expected
    assert metrics["data"]["rows"] == []
    assert raw_data["data"]["noise_totals"] == expected
    assert "output_rms" not in raw_data["data"]["columns"]
    assert "input_referred_rms" not in raw_data["data"]["columns"]
    assert analysis_info["data"]["noise_totals"] == expected
    assert all("√Hz" not in item["unit"] for item in expected["items"])


def test_external_export_root_uses_unique_timestamp_directories(sample_result: SimulationResult, tmp_path: Path):
    external_base = tmp_path / "exports"
    first_root = simulation_artifact_exporter.create_export_root(
        str(external_base), sample_result
    )
    second_root = simulation_artifact_exporter.create_export_root(
        str(external_base), sample_result
    )

    assert first_root.relative_to(external_base).parts == (
        "export_consistency",
        "2026-04-06_00-10-00",
    )
    assert second_root.relative_to(external_base).parts == (
        "export_consistency",
        "2026-04-06_00-10-00_2",
    )


def test_chart_and_waveform_exports_follow_common_payload_schema(qapp, sample_result: SimulationResult, tmp_path: Path):
    chart_viewer = ChartViewer()
    chart_viewer.load_result(sample_result)
    chart_snapshot = chart_viewer.get_web_snapshot()

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

    _assert_common_artifact_payload(charts_manifest, "charts", expected_file_name="export_consistency.cir", expected_x_axis_label="Time (s)")
    _assert_common_artifact_payload(chart_payload, "chart", expected_file_name="export_consistency.cir", expected_x_axis_label="Time (s)")
    _assert_common_artifact_payload(waveform_payload, "waveforms", expected_file_name="export_consistency.cir", expected_x_axis_label="Time (s)")

    assert chart_snapshot["y_label"] == "Voltage (V)"
    assert chart_snapshot["secondary_y_label"] == ""
    assert charts_manifest["summary"]["chart_count"] == 1
    assert chart_payload["data"]["chart_type"] == "waveform_time"
    assert [series["name"] for series in chart_payload["data"]["series"]] == ["V(out)"]
    assert waveform_payload["data"]["columns"][0] == "Time (s)"
    assert len(waveform_payload["data"]["series"]) == 2
    assert waveform_payload["summary"]["row_count"] == 4


def test_artifact_persistence_writes_authoritative_bundle_regardless_of_ui_selection(
    sample_result: SimulationResult, tmp_path: Path
):
    """``SimulationArtifactPersistence`` is the sole owner of the
    canonical ``simulation_results/<stem>/<ts>/`` bundle.

    It runs after every simulation (UI or agent) with no user-facing
    selection. The immutable bundle contains only the authoritative
    ``result.json``; every CSV/TXT/PNG/derived JSON is an external export
    or a bundle-external conversation attachment.
    """
    from domain.simulation.data.simulation_artifact_persistence import (
        simulation_artifact_persistence,
    )

    outcome = simulation_artifact_persistence.persist_bundle(
        project_root=str(tmp_path),
        result=sample_result,
    )

    assert outcome.export_root.relative_to(tmp_path).parts == (
        "simulation_results",
        "export_consistency",
        "2026-04-06_00-10-00",
    )
    assert outcome.result_path.replace("\\", "/") == (
        "simulation_results/export_consistency/2026-04-06_00-10-00/result.json"
    )

    bundle_root = outcome.export_root
    assert {
        path.relative_to(bundle_root).as_posix()
        for path in bundle_root.rglob("*")
        if path.is_file()
    } == {"result.json"}


def test_export_panel_snapshot_tracks_selection_and_directory_state(qapp, sample_result: SimulationResult, tmp_path: Path):
    chart_viewer = ChartViewer()
    chart_viewer.load_result(sample_result)

    waveform_widget = WaveformWidget()
    waveform_widget.load_waveform(sample_result, "V(out)")

    export_panel = SimulationExportPanel(chart_viewer, waveform_widget)
    export_panel.set_result(sample_result)

    initial_snapshot = export_panel.get_web_snapshot()
    initial_items = {item["id"]: item for item in initial_snapshot["items"]}

    assert initial_snapshot["has_result"] is True
    assert initial_snapshot["can_export"] is False
    assert initial_snapshot["selected_directory"] == ""
    assert initial_items["metrics"]["selected"] is True
    assert initial_items["op_result"]["enabled"] is False
    assert initial_items["op_result"]["selected"] is False

    export_panel.set_export_type_selected("metrics", False)
    export_panel.set_manual_export_directory(str(tmp_path))

    updated_snapshot = export_panel.get_web_snapshot()
    updated_items = {item["id"]: item for item in updated_snapshot["items"]}

    assert updated_snapshot["selected_directory"] == str(tmp_path)
    assert updated_snapshot["can_export"] is True
    assert updated_items["metrics"]["selected"] is False
    assert updated_items["charts"]["selected"] is True


def test_manual_export_cannot_target_immutable_simulation_results_tree(qapp, sample_result: SimulationResult, tmp_path: Path):
    export_panel = SimulationExportPanel(_FakeChartExporter(), _FakeWaveformExporter())
    export_panel.set_project_root(str(tmp_path))
    export_panel.set_result(sample_result)
    export_panel.set_manual_export_directory(str(tmp_path / "simulation_results" / "existing"))

    snapshot = export_panel.get_web_snapshot()

    assert Path(snapshot["selected_directory"]).parts[-2:] == ("simulation_results", "existing")
    assert snapshot["can_export"] is False

    export_panel.set_project_root(str(tmp_path / "another_project"))
    assert export_panel.get_web_snapshot()["selected_directory"] == ""


def test_ac_chart_exports_single_bode_overlay_with_dual_axis_metadata(qapp, sample_ac_result: SimulationResult, tmp_path: Path):
    chart_viewer = ChartViewer()
    chart_viewer.load_result(sample_ac_result)
    snapshot = chart_viewer.get_web_snapshot()

    assert snapshot["has_chart"] is True
    assert snapshot["chart_type"] == "bode_overlay"
    assert chart_viewer.supports_measurement_point() is True

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
    assert snapshot["right_log_y"] is False
    assert len(chart_payload["data"]["series"]) == 2

    series_by_name = {series["name"]: series for series in chart_payload["data"]["series"]}
    assert series_by_name["V(out) | Mag"]["axis_key"] == "left"
    assert series_by_name["V(out) | Mag"]["line_style"] == "solid"
    assert series_by_name["V(out) | Phase"]["axis_key"] == "right"
    assert series_by_name["V(out) | Phase"]["line_style"] == "dash"
    assert chart_payload["summary"]["series_count"] == 2


def test_ac_chart_rejects_noncanonical_derived_only_bode_signals(qapp, invalid_derived_ac_result: SimulationResult):
    chart_viewer = ChartViewer()
    chart_viewer.load_result(invalid_derived_ac_result)
    snapshot = chart_viewer.get_web_snapshot()

    assert snapshot["has_chart"] is False
    assert snapshot["chart_type"] == ""
    assert chart_viewer.supports_measurement_point() is False


def test_tran_chart_reassigns_axes_based_on_visible_signal_semantics(qapp, sample_mixed_axis_result: SimulationResult):
    chart_viewer = ChartViewer()
    chart_viewer.load_result(sample_mixed_axis_result)

    initial_snapshot = chart_viewer.get_web_snapshot()
    assert initial_snapshot["y_label"] == "Voltage (V)"
    assert initial_snapshot["secondary_y_label"] == ""
    assert {series["name"]: series["axis_key"] for series in initial_snapshot["visible_series"]} == {"V(out)": "left"}

    assert chart_viewer.set_series_visible("I(V1)", True) is True
    dual_axis_snapshot = chart_viewer.get_web_snapshot()
    assert dual_axis_snapshot["y_label"] == "Voltage (V)"
    assert dual_axis_snapshot["secondary_y_label"] == "Current (A)"
    assert dual_axis_snapshot["log_y"] is False
    assert dual_axis_snapshot["right_log_y"] is False
    assert {series["name"]: series["axis_key"] for series in dual_axis_snapshot["visible_series"]} == {
        "V(out)": "left",
        "I(V1)": "right",
    }

    assert chart_viewer.set_series_visible("V(out)", False) is True
    current_only_snapshot = chart_viewer.get_web_snapshot()
    assert current_only_snapshot["y_label"] == "Current (A)"
    assert current_only_snapshot["secondary_y_label"] == ""
    assert {series["name"]: series["axis_key"] for series in current_only_snapshot["visible_series"]} == {"I(V1)": "left"}


def test_noise_chart_emits_dual_log_axis_metadata_for_mixed_noise_quantities(qapp, sample_noise_result: SimulationResult):
    chart_viewer = ChartViewer()
    chart_viewer.load_result(sample_noise_result)

    assert chart_viewer.set_series_visible("onoise_spectrum", True) is True
    snapshot = chart_viewer.get_web_snapshot()

    assert snapshot["chart_type"] == "noise_spectrum"
    assert snapshot["y_label"] == "Voltage Noise Density (V/√Hz)"
    assert snapshot["secondary_y_label"] == "Current Noise Density (A/√Hz)"
    assert snapshot["log_x"] is True
    assert snapshot["log_y"] is True
    assert snapshot["right_log_y"] is True
    assert {series["name"]: series["axis_key"] for series in snapshot["visible_series"]} == {
        "onoise_spectrum": "left",
        "inoise_spectrum": "right",
    }


def test_waveform_widget_accepts_viewport_for_resolved_complex_waveform_series(qapp, sample_ac_result: SimulationResult):
    waveform_widget = WaveformWidget()
    waveform_widget.load_waveform(sample_ac_result, "V(out)")

    snapshot = waveform_widget.get_web_snapshot()
    assert [series["name"] for series in snapshot["visible_series"]] == ["V(out)_mag"]

    visible_series = snapshot["visible_series"][0]
    assert waveform_widget.set_viewport({
        "x_min": float(visible_series["x"][0]),
        "x_max": float(visible_series["x"][-2]),
        "left_y_min": float(min(visible_series["y"])),
        "left_y_max": float(max(visible_series["y"])),
    }) is True

    updated_snapshot = waveform_widget.get_web_snapshot()
    assert updated_snapshot["viewport"]["active"] is True
    assert updated_snapshot["viewport"]["x_min"] == pytest.approx(float(visible_series["x"][0]))
    assert updated_snapshot["viewport"]["x_max"] == pytest.approx(float(visible_series["x"][-2]))

def test_chart_measurement_point_target_write_does_not_reenable_hidden_series(qapp, sample_result: SimulationResult):
    chart_viewer = ChartViewer()
    chart_viewer.load_result(sample_result)

    assert chart_viewer.set_series_visible("V(out)", False) is True
    snapshot_after_hide = chart_viewer.get_web_snapshot()
    visibility_after_hide = {item["name"]: bool(item["visible"]) for item in snapshot_after_hide["available_series"]}

    assert visibility_after_hide == {
        "V(out)": False,
        "V(in)": False,
    }
    assert snapshot_after_hide["visible_series"] == []

    assert chart_viewer.set_measurement_point_target("V(out)") is False

    snapshot_after_target_request = chart_viewer.get_web_snapshot()
    visibility_after_target_request = {item["name"]: bool(item["visible"]) for item in snapshot_after_target_request["available_series"]}
    assert visibility_after_target_request == visibility_after_hide
    assert snapshot_after_target_request["visible_series"] == []
    assert snapshot_after_target_request["measurement_point"]["target_id"] == ""


def test_chart_measurement_point_sync_retains_visible_targets_only():
    class _FakeChartViewer:
        def __init__(self):
            self._target = "V(out)"
            self.calls = []

        def get_web_snapshot(self):
            return {
                "available_series": [
                    {"name": "V(out)", "group_key": "V(out)", "visible": False},
                    {"name": "V(in)", "group_key": "V(in)", "visible": True},
                ]
            }

        def measurement_point_target(self):
            return self._target

        def set_measurement_point_target(self, target_id: str):
            self.calls.append(target_id)
            self._target = target_id
            return True

    fake_chart_viewer = _FakeChartViewer()

    SimulationTab._sync_chart_measurement_point_target(SimpleNamespace(), fake_chart_viewer)

    assert fake_chart_viewer.calls == ["V(in)"]
    assert fake_chart_viewer.measurement_point_target() == "V(in)"


class _FakeEventBus:
    def __init__(self):
        self.published = []

    def publish(self, event_type: str, payload: dict):
        self.published.append((event_type, payload))


class _FakeChartExporter:
    def export_current_image(self, path: str) -> bool:
        Path(path).write_bytes(_MINIMAL_PNG_BYTES)
        return True


class _FakeWaveformExporter:
    def export_image(self, path: str) -> bool:
        Path(path).write_bytes(_MINIMAL_PNG_BYTES)
        return True


def test_simulation_conversation_text_attachments_do_not_mutate_committed_bundle(sample_result: SimulationResult, sample_metrics, tmp_path: Path):
    persisted_result = replace(sample_result, timestamp="2026-04-06T00:10:00+00:00")
    persisted = simulation_artifact_persistence.persist_bundle(
        str(tmp_path), persisted_result
    )
    export_root = persisted.export_root
    result_path = persisted.result_path
    bundle_before = {
        path.relative_to(export_root).as_posix(): path.read_bytes()
        for path in export_root.rglob("*")
        if path.is_file()
    }

    event_bus = _FakeEventBus()
    ServiceLocator.register(SVC_EVENT_BUS, event_bus)
    coordinator = SimulationConversationAttachmentCoordinator(_FakeChartExporter(), _FakeWaveformExporter())

    try:
        metrics_path = coordinator.attach_metrics(str(tmp_path), result_path, sample_metrics)
        output_log_path = coordinator.attach_output_log(str(tmp_path), result_path)
    finally:
        ServiceLocator.unregister(SVC_EVENT_BUS)

    attachment_base = tmp_path / ".circuit_ai" / "temp" / "simulation_attachments"
    assert Path(metrics_path).is_relative_to(attachment_base)
    assert Path(output_log_path).is_relative_to(attachment_base)
    assert Path(metrics_path).name == "metrics.json"
    assert Path(output_log_path).name == "output_log.txt"
    log_text = Path(output_log_path).read_text(encoding="utf-8")
    assert log_text.startswith("# artifact_type: output_log\n")
    assert "# circuit_file: export_consistency.cir" in log_text
    assert sample_result.raw_output in log_text
    bundle_after = {
        path.relative_to(export_root).as_posix(): path.read_bytes()
        for path in export_root.rglob("*")
        if path.is_file()
    }
    assert bundle_after == bundle_before
    assert event_bus.published == [
        (EVENT_UI_ATTACH_FILES_TO_CONVERSATION, {"paths": [metrics_path]}),
        (EVENT_UI_ACTIVATE_CONVERSATION_TAB, {}),
        (EVENT_UI_ATTACH_FILES_TO_CONVERSATION, {"paths": [output_log_path]}),
        (EVENT_UI_ACTIVATE_CONVERSATION_TAB, {}),
    ]


def test_simulation_conversation_image_attachments_do_not_mutate_committed_bundle(sample_result: SimulationResult, tmp_path: Path):
    persisted_result = replace(sample_result, timestamp="2026-04-06T00:10:00+00:00")
    persisted = simulation_artifact_persistence.persist_bundle(
        str(tmp_path), persisted_result
    )
    export_root = persisted.export_root
    result_path = persisted.result_path
    bundle_before = {
        path.relative_to(export_root).as_posix(): path.read_bytes()
        for path in export_root.rglob("*")
        if path.is_file()
    }

    event_bus = _FakeEventBus()
    ServiceLocator.register(SVC_EVENT_BUS, event_bus)
    coordinator = SimulationConversationAttachmentCoordinator(_FakeChartExporter(), _FakeWaveformExporter())

    try:
        chart_path = coordinator.attach_chart_image(str(tmp_path), result_path)
        waveform_path = coordinator.attach_waveform_image(str(tmp_path), result_path)
    finally:
        ServiceLocator.unregister(SVC_EVENT_BUS)

    attachment_base = tmp_path / ".circuit_ai" / "temp" / "simulation_attachments"
    assert Path(chart_path).is_relative_to(attachment_base)
    assert Path(waveform_path).is_relative_to(attachment_base)
    assert Path(chart_path).name == "current_chart.png"
    assert Path(waveform_path).name == "current_waveform.png"

    chart_chunks = read_png_itxt_chunks(chart_path)
    waveform_chunks = read_png_itxt_chunks(waveform_path)
    assert chart_chunks["circuit_file"] == "export_consistency.cir"
    assert chart_chunks["file_path"] == sample_result.file_path
    assert chart_chunks["source_digest"] == _SOURCE_DIGEST
    assert (
        chart_chunks["source_digest_algorithm"]
        == SPICE_SOURCE_CLOSURE_ALGORITHM
    )
    assert chart_chunks["artifact_type"] == "chart"
    assert waveform_chunks["circuit_file"] == "export_consistency.cir"
    assert waveform_chunks["file_path"] == sample_result.file_path
    assert waveform_chunks["source_digest"] == _SOURCE_DIGEST
    assert (
        waveform_chunks["source_digest_algorithm"]
        == SPICE_SOURCE_CLOSURE_ALGORITHM
    )
    assert waveform_chunks["artifact_type"] == "waveforms"

    bundle_after = {
        path.relative_to(export_root).as_posix(): path.read_bytes()
        for path in export_root.rglob("*")
        if path.is_file()
    }
    assert bundle_after == bundle_before

    assert event_bus.published == [
        (EVENT_UI_ATTACH_FILES_TO_CONVERSATION, {"paths": [chart_path]}),
        (EVENT_UI_ACTIVATE_CONVERSATION_TAB, {}),
        (EVENT_UI_ATTACH_FILES_TO_CONVERSATION, {"paths": [waveform_path]}),
        (EVENT_UI_ACTIVATE_CONVERSATION_TAB, {}),
    ]


def test_simulation_conversation_attachment_rejects_missing_exact_bundle_without_side_effects(sample_result: SimulationResult, tmp_path: Path):
    coordinator = SimulationConversationAttachmentCoordinator(
        _FakeChartExporter(),
        _FakeWaveformExporter(),
    )

    with pytest.raises(ValueError):
        coordinator.attach_output_log(
            str(tmp_path),
            "simulation_results/missing/run/result.json",
        )

    assert not (tmp_path / ".circuit_ai").exists()


def test_text_and_csv_artifacts_carry_circuit_linkage_header(qapp, sample_result: SimulationResult, sample_metrics, tmp_path: Path):
    """Every CSV / TXT artifact must prefix a ``#`` metadata header
    that names the source circuit. This is the authoritative contract
    agents rely on when reading loose files.
    """
    export_root = simulation_artifact_exporter.create_export_root(
        str(tmp_path / "exports"), sample_result
    )

    simulation_artifact_exporter.export_metrics(export_root, sample_result, sample_metrics)
    simulation_artifact_exporter.export_raw_data(export_root, sample_result)
    simulation_artifact_exporter.export_output_log(export_root, sample_result)
    simulation_artifact_exporter.export_analysis_info(export_root, sample_result)

    chart_viewer = ChartViewer()
    chart_viewer.load_result(sample_result)
    chart_viewer.export_bundle(str(export_root / "charts"))

    waveform_widget = WaveformWidget()
    waveform_widget.load_waveform(sample_result, "V(out)")
    waveform_widget.add_waveform(sample_result, "V(in)")
    waveform_widget.export_bundle(str(export_root / "waveforms"))

    text_like_files = [
        export_root / "metrics" / "metrics.csv",
        export_root / "raw_data" / "raw_data.csv",
        export_root / "output_log" / "output_log.txt",
        export_root / "analysis_info" / "analysis_info.txt",
        export_root / "charts" / "01_waveform_time.csv",
        export_root / "waveforms" / "waveform.csv",
    ]
    for path in text_like_files:
        content = path.read_text(encoding="utf-8")
        assert content.startswith("# artifact_type: "), f"{path} missing header prefix"
        assert "# circuit_file: export_consistency.cir" in content, f"{path} missing circuit_file"
        assert f"# file_path: {sample_result.file_path}" in content, f"{path} missing file_path"
        assert f"# source_digest: {_SOURCE_DIGEST}" in content, f"{path} missing source_digest"
        assert (
            f"# source_digest_algorithm: {SPICE_SOURCE_CLOSURE_ALGORITHM}"
            in content
        ), f"{path} missing source_digest_algorithm"


def test_png_artifacts_carry_circuit_linkage_text_chunks(qapp, sample_result: SimulationResult, tmp_path: Path):
    """Every PNG artifact must carry ``iTXt`` chunks that link it to
    the source circuit — this is the only in-band way to tie an image
    handed off to the agent back to its origin.
    """
    export_root = simulation_artifact_exporter.create_export_root(
        str(tmp_path / "exports"), sample_result
    )

    chart_viewer = ChartViewer()
    chart_viewer.load_result(sample_result)
    chart_viewer.export_bundle(str(export_root / "charts"))

    waveform_widget = WaveformWidget()
    waveform_widget.load_waveform(sample_result, "V(out)")
    waveform_widget.add_waveform(sample_result, "V(in)")
    waveform_widget.export_bundle(str(export_root / "waveforms"))

    chart_png = export_root / "charts" / "01_waveform_time.png"
    waveform_png = export_root / "waveforms" / "waveform.png"

    chart_chunks = read_png_itxt_chunks(chart_png)
    waveform_chunks = read_png_itxt_chunks(waveform_png)

    assert chart_chunks["circuit_file"] == "export_consistency.cir"
    assert chart_chunks["file_path"] == sample_result.file_path
    assert chart_chunks["artifact_type"] == "chart"
    assert (
        chart_chunks["source_digest_algorithm"]
        == SPICE_SOURCE_CLOSURE_ALGORITHM
    )
    assert waveform_chunks["circuit_file"] == "export_consistency.cir"
    assert waveform_chunks["file_path"] == sample_result.file_path
    assert waveform_chunks["artifact_type"] == "waveforms"
    assert (
        waveform_chunks["source_digest_algorithm"]
        == SPICE_SOURCE_CLOSURE_ALGORITHM
    )
