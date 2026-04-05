import numpy as np
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from domain.simulation.data.waveform_data_service import WaveformDataService
from domain.simulation.models.simulation_result import SimulationData, SimulationResult
from presentation.panels.simulation.raw_data_table import RawDataTable, RawDataTableModel


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
    assert model.search_value(1, 3.0, tolerance=1e-9) == 2
    assert model.get_row_for_x_value(0.29) == 3

    row_data = model.get_row_data(2)
    assert row_data is not None
    assert row_data.index == 2
    assert row_data.x_value == 0.2
    assert row_data.values["V(out)"] == 3.0


def test_raw_data_table_widget_shows_current_result_binding(qapp, sample_result: SimulationResult):
    table = RawDataTable()
    table.load_data(sample_result)

    assert table._jump_row_spin.minimum() == 1
    assert table._jump_row_spin.maximum() == 4
    assert table._jump_row_spin.value() == 1
    assert table._row_count_label.text() == "Total: 4 rows"

    binding_text = table._result_binding_label.text()
    assert "TRAN" in binding_text
    assert "v7" in binding_text
    assert "2026-04-05T17:00:00" in binding_text
    assert "run_007.json" in binding_text

    table.jump_to_row(2)
    selected_rows = table._table_view.selectionModel().selectedRows()
    assert len(selected_rows) == 1
    assert selected_rows[0].row() == 2

    table.clear()
    assert table._result_binding_label.text() == ""
    assert table._row_count_label.text() == "Total: 0 rows"
