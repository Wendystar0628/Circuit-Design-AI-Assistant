import numpy as np
import pytest
import importlib
from PyQt6.QtWidgets import QApplication

import domain.simulation.data as simulation_data_package
from domain.simulation.data.simulation_artifact_exporter import simulation_artifact_exporter
from domain.simulation.data.waveform_data_service import WaveformDataService
from domain.simulation.models.simulation_result import SimulationData, SimulationResult
from presentation.panels.simulation.raw_data_table import (
    RawDataTable,
)


waveform_data_service_module = importlib.import_module("domain.simulation.data.waveform_data_service")


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
        file_path="results/run_007.json",
        analysis_type="tran",
        success=True,
        data=data,
        timestamp="2026-04-05T17:00:00",
        version=7,
        session_id="session-raw-7",
        x_axis_kind="time",
        x_axis_label="Time (s)",
        x_axis_scale="linear",
    )


def build_result(*, row_count: int, signal_count: int) -> SimulationResult:
    time = np.arange(row_count, dtype=float) * 0.1
    data = SimulationData(
        time=time,
        signals={
            f"V(n{index})": np.arange(row_count, dtype=float) + float(index)
            for index in range(signal_count)
        },
    )

    return SimulationResult(
        executor="spice",
        file_path=f"results/wide_{row_count}_{signal_count}.json",
        analysis_type="tran",
        success=True,
        data=data,
        timestamp="2026-04-05T18:00:00",
        version=8,
        session_id=f"session-wide-{row_count}-{signal_count}",
        x_axis_kind="time",
        x_axis_label="Time (s)",
        x_axis_scale="linear",
    )


def test_waveform_data_service_builds_stable_table_snapshot(sample_result: SimulationResult):
    service = WaveformDataService(cache_size=4)

    snapshot = service.build_table_snapshot(sample_result)

    assert snapshot is not None
    assert snapshot.total_rows == 4
    assert snapshot.analysis_type == "tran"
    assert snapshot.version == 7
    assert snapshot.session_id == "session-raw-7"
    assert snapshot.timestamp == "2026-04-05T17:00:00"
    assert snapshot.x_label == "Time (s)"
    assert snapshot.signal_names == ["V(out)", "V(in)"]
    np.testing.assert_allclose(snapshot.x_values, np.array([0.0, 0.1, 0.2, 0.3]))
    np.testing.assert_allclose(snapshot.signal_columns["V(out)"], np.array([1.0, 2.0, 3.0, 4.0]))
    np.testing.assert_allclose(snapshot.signal_columns["V(in)"], np.array([0.5, 0.6, 0.7, 0.8]))
    assert waveform_data_service_module.__all__ == [
        "WaveformData",
        "TableSnapshot",
        "WaveformDataService",
        "waveform_data_service",
    ]
    assert {"WaveformData", "TableSnapshot", "WaveformDataService", "waveform_data_service"}.issubset(
        set(simulation_data_package.__all__)
    )


def test_raw_data_table_document_payload_exposes_metadata(qapp, sample_result: SimulationResult):
    table = RawDataTable()
    table.load_data(sample_result)
    document = table.get_document_payload()

    assert document["dataset_id"] == "session-raw-7::results/run_007.json::2026-04-05T17:00:00"
    assert document["version"] == 1
    assert document["has_data"] is True
    assert document["row_count"] == 4
    assert document["column_count"] == 3
    assert [column["label"] for column in document["columns"]] == ["Time (s)", "V(out)", "V(in)"]

    table.clear()
    cleared_document = table.get_document_payload()
    assert cleared_document["has_data"] is False
    assert cleared_document["row_count"] == 0
    assert cleared_document["column_count"] == 0
    assert cleared_document["columns"] == []


def test_raw_data_table_viewport_payload_returns_requested_chunk(qapp, sample_result: SimulationResult):
    table = RawDataTable()
    table.load_data(sample_result)
    document = table.get_document_payload()

    viewport = table.get_viewport_payload(
        dataset_id=document["dataset_id"],
        version=document["version"],
        row_start=1,
        row_end=4,
        col_start=0,
        col_end=2,
    )

    assert viewport["dataset_id"] == document["dataset_id"]
    assert viewport["version"] == document["version"]
    assert viewport["row_start"] == 1
    assert viewport["row_end"] == 4
    assert viewport["col_start"] == 0
    assert viewport["col_end"] == 2
    assert [row["row_index"] for row in viewport["rows"]] == [1, 2, 3]
    assert viewport["rows"][0]["values"] == ["0.1", "2"]
    assert viewport["rows"][2]["values"] == ["0.3", "4"]


def test_raw_data_table_document_and_viewport_cover_all_signal_columns(qapp):
    table = RawDataTable()
    table.load_data(build_result(row_count=120, signal_count=20))
    document = table.get_document_payload()
    column_labels = [column["label"] for column in document["columns"]]

    assert column_labels == ["Time (s)", *table.signal_names]
    assert len(document["columns"]) == 21
    assert document["row_count"] == 120
    target_column_index = column_labels.index("V(n19)")

    viewport = table.get_viewport_payload(
        dataset_id=document["dataset_id"],
        version=document["version"],
        row_start=5,
        row_end=6,
        col_start=target_column_index,
        col_end=target_column_index + 1,
    )

    assert len(viewport["rows"]) == 1
    assert viewport["rows"][0]["row_index"] == 5
    assert viewport["rows"][0]["values"] == ["24"]


def test_raw_data_table_copy_range_to_clipboard(qapp, sample_result: SimulationResult, monkeypatch):
    class DummyClipboard:
        def __init__(self):
            self.value = ""

        def setText(self, value: str):
            self.value = value

    clipboard = DummyClipboard()
    monkeypatch.setattr(QApplication, "clipboard", lambda self: clipboard)

    table = RawDataTable()
    table.load_data(sample_result)
    document = table.get_document_payload()

    copied = table.copy_range_to_clipboard(
        dataset_id=document["dataset_id"],
        version=document["version"],
        row_start=1,
        row_end=3,
        col_start=0,
        col_end=2,
        include_headers=True,
    )

    assert copied is True
    assert clipboard.value == "Time (s)\tV(out)\n0.1\t2\n0.2\t3"


def test_simulation_artifact_exporter_exports_full_raw_data_snapshot(sample_result: SimulationResult, tmp_path):
    export_root = simulation_artifact_exporter.create_export_root(str(tmp_path), sample_result)

    exported_files = simulation_artifact_exporter.export_raw_data(export_root, sample_result)

    assert len(exported_files) == 2
    exported_csv = (export_root / "raw_data" / "raw_data.csv").read_text(encoding="utf-8").splitlines()
    assert exported_csv[0] == "Time (s),V(out),V(in)"
    assert exported_csv[2] == "0.1,2.0,0.6"
