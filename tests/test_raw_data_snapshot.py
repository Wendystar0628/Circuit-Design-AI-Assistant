import numpy as np
import pytest
import importlib
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

import domain.simulation.data as simulation_data_package
from domain.simulation.data.simulation_artifact_exporter import simulation_artifact_exporter
from domain.simulation.data.waveform_data_service import WaveformDataService
from domain.simulation.models.simulation_result import SimulationData, SimulationResult
from presentation.panels.simulation.raw_data_table import (
    RawDataTable,
    RawDataTableModel,
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


def test_raw_data_table_model_keeps_row_identity_stable(sample_result: SimulationResult):
    model = RawDataTableModel()
    model.load_result(sample_result)

    assert model.rowCount() == 4
    assert model.columnCount() == 3
    assert model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "Time (s)"
    assert model.headerData(1, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "V(out)"
    assert model.headerData(0, Qt.Orientation.Vertical, Qt.ItemDataRole.DisplayRole) == "1"
    assert model.headerData(3, Qt.Orientation.Vertical, Qt.ItemDataRole.DisplayRole) == "4"

    first_value = model.data(model.index(0, 1), Qt.ItemDataRole.DisplayRole)
    last_value = model.data(model.index(3, 1), Qt.ItemDataRole.DisplayRole)

    assert first_value == "1"
    assert last_value == "4"

    model.data(model.index(3, 1), Qt.ItemDataRole.DisplayRole)
    assert model.data(model.index(0, 1), Qt.ItemDataRole.DisplayRole) == "1"
    snapshot = model.snapshot
    assert snapshot is not None
    assert float(snapshot.x_values[2]) == 0.2
    assert float(snapshot.signal_columns["V(out)"][2]) == 3.0


def test_raw_data_table_widget_shows_current_result_binding(qapp, sample_result: SimulationResult):
    table = RawDataTable()
    table.load_data(sample_result)
    snapshot = table.get_web_snapshot()

    assert snapshot["has_data"] is True
    assert snapshot["columns"] == ["Time (s)", "V(out)", "V(in)"]
    assert len(snapshot["rows"]) == 4
    assert snapshot["rows"][1] == {"row_number": 2, "values": ["0.1", "2", "0.6"]}

    table.clear()
    cleared_snapshot = table.get_web_snapshot()
    assert cleared_snapshot == {"has_data": False, "columns": [], "rows": []}


def test_raw_data_table_web_snapshot_contains_full_rows_and_columns(qapp):
    table = RawDataTable()
    table.load_data(build_result(row_count=120, signal_count=20))

    initial_snapshot = table.get_web_snapshot()

    assert initial_snapshot["has_data"] is True
    assert len(initial_snapshot["columns"]) == 21
    assert initial_snapshot["columns"][0] == "Time (s)"
    assert set(initial_snapshot["columns"][1:]) == {f"V(n{index})" for index in range(20)}
    assert len(initial_snapshot["rows"]) == 120
    assert initial_snapshot["rows"][110]["row_number"] == 111
    assert len(initial_snapshot["rows"][0]["values"]) == 21


def test_raw_data_table_can_emit_lightweight_web_snapshot_when_table_is_not_active(qapp):
    table = RawDataTable()
    table.load_data(build_result(row_count=32, signal_count=12))

    snapshot = table.get_web_snapshot(include_table_data=False)

    assert snapshot == {"has_data": True, "columns": [], "rows": []}


def test_simulation_artifact_exporter_exports_full_raw_data_snapshot(sample_result: SimulationResult, tmp_path):
    export_root = simulation_artifact_exporter.create_export_root(str(tmp_path), sample_result)

    exported_files = simulation_artifact_exporter.export_raw_data(export_root, sample_result)

    assert len(exported_files) == 2
    exported_csv = (export_root / "raw_data" / "raw_data.csv").read_text(encoding="utf-8").splitlines()
    assert exported_csv[0] == "Time (s),V(out),V(in)"
    assert exported_csv[2] == "0.1,2.0,0.6"
