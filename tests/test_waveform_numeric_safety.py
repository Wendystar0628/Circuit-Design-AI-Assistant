import json
from pathlib import Path

import numpy as np
import pytest
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from domain.simulation.data.downsampler import (
    crop_to_viewport,
    downsample,
    downsample_preserving_gaps,
)
from domain.simulation.data.signal_semantics import (
    insert_nested_dc_breaks,
    nested_dc_secondary_values,
    parse_nested_dc_sweep,
)
from domain.simulation.data.simulation_artifact_exporter import (
    simulation_artifact_exporter,
)
from domain.simulation.data.waveform_data_service import WaveformDataService
from domain.simulation.measure.measure_result import MeasureResult, MeasureStatus
from domain.simulation.models.chart_type import ChartType
from domain.simulation.models.simulation_result import (
    NoiseTotals,
    SimulationData,
    SimulationResult,
)
from presentation.panels.simulation.bode_overlay_chart_page import BodeOverlayChartPage
from presentation.panels.simulation.analysis_chart_viewer import ChartViewer
from presentation.panels.simulation.chart_export_utils import (
    add_nested_dc_secondary_column,
    build_chart_data_rows,
    serialize_chart_series_for_web,
)
from presentation.panels.simulation.chart_page_widget import ChartPage
from presentation.panels.simulation.chart_view_types import ChartSeries, ChartSpec
from presentation.panels.simulation.ltspice_plot_interaction import (
    sample_phase_degrees_at_x,
    sample_series_at_x,
)
from presentation.panels.simulation.qt_surface_export import export_widget_image
from presentation.panels.simulation.waveform_export_bundle_builder import (
    waveform_export_bundle_builder,
)
from presentation.panels.simulation.waveform_widget import WaveformWidget

_SOURCE_DIGEST = "a" * 64


def _result(x: np.ndarray, y: np.ndarray) -> SimulationResult:
    return SimulationResult(
        executor="spice",
        file_path="numeric_safety.cir",
        analysis_type="tran",
        success=True,
        source_digest=_SOURCE_DIGEST,
        data=SimulationData(
            time=x,
            signals={"V(out)": y},
            signal_types={"V(out)": "voltage"},
        ),
        analysis_command=".tran 1u 10",
    )


def _nested_dc_result(x: np.ndarray, y: np.ndarray) -> SimulationResult:
    return SimulationResult(
        executor="spice",
        file_path="nested_dc.cir",
        analysis_type="dc",
        success=True,
        source_digest=_SOURCE_DIGEST,
        data=SimulationData(
            sweep=x,
            signals={"I(Vce)": y},
            signal_types={"I(Vce)": "current"},
        ),
        analysis_command=".dc Vce 0 10 5 Ib 10u 30u 10u",
    )


def test_peak_decimator_keeps_spike_caps_points_and_drops_non_finite_pairs():
    x = np.arange(10_000, dtype=float)
    y = np.zeros(9_900, dtype=float)  # deliberately truncated simulator vector
    y[4_321] = 123.0
    x[100] = np.nan
    y[200] = np.inf

    x_out, y_out = downsample(x, y, target_points=100)

    assert 0 < len(x_out) <= 100
    assert len(x_out) == len(y_out)
    assert np.all(np.isfinite(x_out))
    assert np.all(np.isfinite(y_out))
    assert np.max(y_out) == 123.0


def test_gap_preserving_decimator_keeps_break_spike_and_point_cap():
    x = np.arange(2_000, dtype=float)
    y = np.zeros_like(x)
    y[500:510] = np.nan
    y[1_500] = 90.0

    x_out, y_out = downsample_preserving_gaps(x, y, target_points=80)

    assert len(x_out) == len(y_out) <= 80
    assert np.any(~np.isfinite(x_out) & ~np.isfinite(y_out))
    assert np.nanmax(y_out) == 90.0


def test_viewport_is_cut_before_decimation_and_narrow_gap_returns_brackets():
    x = np.linspace(0.0, 10.0, 10_001)
    y = np.zeros_like(x)
    y[5_000] = 50.0
    service = WaveformDataService()
    result = _result(x, y)

    spike_view = service.get_viewport_data(
        result, "V(out)", 4.99, 5.01, target_points=12
    )
    gap_view = service.get_viewport_data(
        result, "V(out)", 4.0001, 4.0002, target_points=12
    )

    assert spike_view is not None
    assert spike_view.point_count <= 12
    assert np.max(spike_view.y_data) == 50.0
    assert gap_view is not None
    assert gap_view.point_count == 2
    assert gap_view.x_data[0] <= 4.0001 <= gap_view.x_data[-1]


def test_nested_sweep_viewport_keeps_every_crossing_branch():
    x = np.array([0.0, 10.0, 0.0, 10.0, 0.0, 10.0])
    y = np.arange(6, dtype=float)
    view = WaveformDataService().get_viewport_data(
        _nested_dc_result(x, y),
        "I(Vce)",
        4.0,
        6.0,
        target_points=12,
    )

    assert view is not None
    np.testing.assert_allclose(
        view.x_data,
        [0.0, 10.0, np.nan, 0.0, 10.0, np.nan, 0.0, 10.0],
        equal_nan=True,
    )
    np.testing.assert_allclose(
        view.y_data,
        [0.0, 1.0, np.nan, 2.0, 3.0, np.nan, 4.0, 5.0],
        equal_nan=True,
    )


@pytest.mark.parametrize("second_branch_x", ([0.0, 1.0], [1.0, 0.0]))
def test_viewport_keeps_crossing_branch_when_another_branch_has_inside_sample(
    second_branch_x,
):
    x = np.array([0.0, 0.5, 1.0, np.nan, *second_branch_x])
    y = np.array([0.0, 0.5, 1.0, np.nan, 10.0, 11.0])

    cropped_x, cropped_y = crop_to_viewport(x, y, 0.49, 0.51)

    np.testing.assert_allclose(
        cropped_x,
        [0.0, 0.5, 1.0, np.nan, *second_branch_x],
        equal_nan=True,
    )
    np.testing.assert_allclose(
        cropped_y,
        [0.0, 0.5, 1.0, np.nan, 10.0, 11.0],
        equal_nan=True,
    )


def test_measurement_interpolation_obeys_monotonic_contract():
    assert sample_series_at_x([0.0, 1.0, 2.0], [0.0, 10.0, 20.0], 1.5) == pytest.approx(
        15.0
    )
    assert sample_series_at_x([2.0, 1.0, 0.0], [20.0, 10.0, 0.0], 1.5) == pytest.approx(
        15.0
    )
    # One scalar X is ambiguous across nested sweep branches, so the cursor
    # must refuse a value instead of silently choosing an outer step.
    assert sample_series_at_x([0.0, 2.0, 1.0], [0.0, 20.0, 10.0], 1.1) is None
    assert sample_series_at_x([0.0, np.nan, 2.0], [0.0, 999.0, 20.0], 1.0) is None
    assert sample_series_at_x([0.0, 1.0], [0.0, 10.0], 2.0) is None
    assert sample_series_at_x([0.0, 1.0, 2.0], [0.0, np.nan, 20.0], 1.0) is None


def test_phase_sampler_unwraps_wrap_boundary_and_respects_gap():
    assert abs(
        sample_phase_degrees_at_x([1.0, 2.0], [179.0, -179.0], 1.5)
    ) == pytest.approx(180.0)
    assert (
        sample_phase_degrees_at_x(
            [1.0, 2.0, 3.0],
            [179.0, np.nan, -179.0],
            2.0,
        )
        is None
    )


def test_chart_export_aligns_different_series_by_physical_x():
    series = [
        ChartSeries("A", np.array([0.0, 2.0]), np.array([0.0, 2.0]), "#fff"),
        ChartSeries("B", np.array([1.0, 2.0]), np.array([10.0, 20.0]), "#000"),
    ]

    rows = build_chart_data_rows("Time (s)", series)

    assert rows == [
        {"Time (s)": 0.0, "A": 0.0},
        {"Time (s)": 1.0, "B": 10.0},
        {"Time (s)": 2.0, "A": 2.0, "B": 20.0},
    ]


def test_chart_export_preserves_descending_sweep_direction():
    series = [
        ChartSeries("A", np.array([2.0, 0.0]), np.array([20.0, 0.0]), "#fff"),
        ChartSeries("B", np.array([1.0, 0.0]), np.array([10.0, 0.0]), "#000"),
    ]

    rows = build_chart_data_rows("Sweep", series)

    assert [row["Sweep"] for row in rows] == [2.0, 1.0, 0.0]
    assert rows[1] == {"Sweep": 1.0, "B": 10.0}


def test_nested_dc_semantics_break_curves_and_derive_outer_sweep_column():
    result = _nested_dc_result(
        np.array([0.0, 5.0, 10.0, 0.0, 5.0, 10.0, 0.0, 5.0, 10.0]),
        np.arange(9, dtype=float),
    )
    sweep = parse_nested_dc_sweep(result.analysis_type, result.analysis_command)
    assert sweep is not None

    broken_x, broken_y = insert_nested_dc_breaks(
        result.data.sweep,
        result.data.signals["I(Vce)"],
        sweep,
    )
    np.testing.assert_allclose(
        broken_x,
        [0.0, 5.0, 10.0, np.nan, 0.0, 5.0, 10.0, np.nan, 0.0, 5.0, 10.0],
        equal_nan=True,
    )
    assert np.flatnonzero(~np.isfinite(broken_y)).tolist() == [3, 7]

    secondary = nested_dc_secondary_values(broken_x, sweep)
    np.testing.assert_allclose(
        secondary,
        [10e-6, 10e-6, 10e-6, np.nan, 20e-6, 20e-6, 20e-6, np.nan, 30e-6, 30e-6, 30e-6],
        equal_nan=True,
    )

    rows = build_chart_data_rows(
        "Vce (V)",
        [ChartSeries("I(Vce)", broken_x, broken_y, "#fff")],
    )
    label = add_nested_dc_secondary_column(rows, "Vce (V)", result)
    assert label == "Outer sweep Ib (A)"
    assert rows[3].get(label) is None
    assert rows[7].get(label) is None
    np.testing.assert_allclose(
        [row[label] for row in rows if label in row],
        [10e-6] * 3 + [20e-6] * 3 + [30e-6] * 3,
    )
    assert [row["Vce (V)"] for row in rows] == [
        0.0,
        5.0,
        10.0,
        None,
        0.0,
        5.0,
        10.0,
        None,
        0.0,
        5.0,
        10.0,
    ]


def test_nested_dc_single_point_primary_sweep_still_has_distinct_branches():
    result = SimulationResult(
        executor="spice",
        file_path="nested_single_point.cir",
        analysis_type="dc",
        success=True,
        source_digest=_SOURCE_DIGEST,
        data=SimulationData(
            sweep=np.array([5.0, 5.0, 5.0]),
            signals={"I(V1)": np.array([1.0, 2.0, 3.0])},
            signal_types={"I(V1)": "current"},
        ),
        analysis_command=".dc V1 5 5 1 I1 1m 3m 1m",
    )
    sweep = parse_nested_dc_sweep(result.analysis_type, result.analysis_command)
    assert sweep is not None
    x_data, y_data = insert_nested_dc_breaks(
        result.data.sweep,
        result.data.signals["I(V1)"],
        sweep,
    )
    np.testing.assert_allclose(
        x_data,
        [5.0, np.nan, 5.0, np.nan, 5.0],
        equal_nan=True,
    )
    np.testing.assert_allclose(
        nested_dc_secondary_values(x_data, sweep),
        [1e-3, np.nan, 2e-3, np.nan, 3e-3],
        equal_nan=True,
    )
    assert sample_series_at_x(x_data, y_data, 5.0) is None


def test_nested_dc_chart_table_and_measurement_share_branch_contract(qapp, tmp_path: Path):
    result = _nested_dc_result(
        np.array([0.0, 5.0, 10.0, 0.0, 5.0, 10.0, 0.0, 5.0, 10.0]),
        np.arange(9, dtype=float),
    )
    viewer = ChartViewer()
    series = viewer._build_real_signal_series(result, result.data.sweep, "dc")
    assert len(series) == 1
    assert np.flatnonzero(~np.isfinite(series[0].x_data)).tolist() == [3, 7]

    snapshot = WaveformDataService().build_table_snapshot(result)
    assert snapshot is not None
    assert snapshot.signal_names[0] == "Outer sweep Ib (A)"
    np.testing.assert_allclose(
        snapshot.x_values,
        [0.0, 5.0, 10.0, np.nan, 0.0, 5.0, 10.0, np.nan, 0.0, 5.0, 10.0],
        equal_nan=True,
    )
    np.testing.assert_allclose(
        snapshot.signal_columns["Outer sweep Ib (A)"],
        [10e-6] * 3
        + [np.nan]
        + [20e-6] * 3
        + [np.nan]
        + [30e-6] * 3,
        equal_nan=True,
    )

    simulation_artifact_exporter.export_raw_data(tmp_path, result)
    csv_text = (tmp_path / "raw_data" / "raw_data.csv").read_text(encoding="utf-8")
    _, _, table_text = csv_text.partition("\n\n")
    csv_rows = table_text.splitlines()
    assert csv_rows[0] == "Vce (V),Outer sweep Ib (A),I(Vce)"
    assert csv_rows[4] == ",,"
    assert csv_rows[8] == ",,"

    raw_payload = json.loads(
        (tmp_path / "raw_data" / "raw_data.json").read_text(encoding="utf-8")
    )
    assert raw_payload["data"]["rows"][3] == {
        "Vce (V)": None,
        "Outer sweep Ib (A)": None,
        "I(Vce)": None,
    }
    assert raw_payload["data"]["rows"][7] == {
        "Vce (V)": None,
        "Outer sweep Ib (A)": None,
        "I(Vce)": None,
    }

    page = ChartPage()
    page.set_chart(
        ChartSpec(
            chart_type=ChartType.DC_SWEEP,
            title="DC Sweep",
            x_label="Vce (V)",
            y_label="Current (A)",
            series=series,
        )
    )
    page.set_measurement_enabled(True)
    assert page.is_measurement_enabled() is False
    assert page.supports_measurement_point() is False
    assert page.set_measurement_cursor("a", 5.0) is False


def test_web_series_preserves_null_gap_instead_of_rejoining_curve():
    payload = serialize_chart_series_for_web(
        ChartSeries(
            "V(out)",
            np.array([0.0, 1.0, 2.0]),
            np.array([0.0, np.nan, 2.0]),
            "#fff",
        )
    )

    assert payload["x"] == [0.0, 1.0, 2.0]
    assert payload["y"] == [0.0, None, 2.0]


def test_chart_builder_preserves_invalid_x_as_two_sided_gap(qapp):
    result = _result(
        np.array([0.0, np.nan, 2.0]),
        np.array([0.0, 999.0, 2.0]),
    )
    series = ChartViewer()._build_real_signal_series(
        result,
        result.data.time,
        "tran",
    )[0]
    payload = serialize_chart_series_for_web(series)

    assert payload["x"] == [0.0, None, 2.0]
    assert payload["y"] == [0.0, None, 2.0]


def test_log_domains_retain_sub_unit_frequency_and_noise(qapp):
    spec = ChartSpec(
        chart_type=ChartType.NOISE_SPECTRUM,
        title="Noise",
        x_label="Frequency (Hz)",
        y_label="Voltage Noise Density (V/√Hz)",
        series=[
            ChartSeries(
                "onoise_spectrum",
                np.array([0.1, 1.0, 10.0]),
                np.array([1e-12, 1e-11, 1e-10]),
                "#fff",
                axis_family="noise_voltage_density",
            )
        ],
        log_x=True,
        log_y=True,
    )
    page = ChartPage()
    page.set_chart(spec)

    assert page._x_domain == pytest.approx((-1.0, 1.0))
    assert page._y_domain == pytest.approx((-12.0, -10.0))


def test_chart_trims_length_mismatch_instead_of_dropping_whole_signal(qapp):
    page = ChartPage()
    page.set_chart(
        ChartSpec(
            chart_type=ChartType.WAVEFORM_TIME,
            title="Transient",
            x_label="Time (s)",
            y_label="Voltage (V)",
            series=[
                ChartSeries(
                    "V(out)",
                    np.array([0.0, 1.0, 2.0]),
                    np.array([3.0, 4.0]),
                    "#fff",
                    axis_family="voltage",
                )
            ],
        )
    )

    assert len(page._spec.series) == 1
    np.testing.assert_array_equal(page._spec.series[0].x_data, [0.0, 1.0])
    np.testing.assert_array_equal(page._spec.series[0].y_data, [3.0, 4.0])


def test_chart_web_snapshot_crops_raw_viewport_before_peak_decimation(qapp):
    x = np.arange(10_000, dtype=float)
    y = np.zeros_like(x)
    y[5_000] = 75.0
    page = ChartPage()
    page.set_chart(
        ChartSpec(
            chart_type=ChartType.WAVEFORM_TIME,
            title="Transient",
            x_label="Time (s)",
            y_label="Voltage (V)",
            series=[ChartSeries("V(out)", x, y, "#fff", axis_family="voltage")],
        )
    )

    assert (
        page.set_viewport(
            {
                "x_min": 4_990.0,
                "x_max": 5_010.0,
                "left_y_min": 0.0,
                "left_y_max": 75.0,
            }
        )
        is True
    )
    payload = page.get_web_snapshot()["visible_series"][0]

    assert len(payload["x"]) < 100
    assert payload["x"][0] <= 4_990.0
    assert payload["x"][-1] >= 5_010.0
    assert max(value for value in payload["y"] if value is not None) == 75.0


def test_bode_uses_real_secondary_viewbox_and_keeps_sub_hertz_domain(qapp):
    x = np.array([0.1, 1.0, 10.0])
    spec = ChartSpec(
        chart_type=ChartType.BODE_OVERLAY,
        title="AC Magnitude & Phase",
        x_label="Frequency (Hz)",
        y_label="Magnitude (dB re 1 unit)",
        secondary_y_label="Phase (°)",
        series=[
            ChartSeries(
                "V(out) | Mag",
                x,
                np.array([0.0, -3.0, -20.0]),
                "#fff",
                axis_family="magnitude_db",
                group_key="V(out)",
                component="magnitude",
            ),
            ChartSeries(
                "V(out) | Phase",
                x,
                np.array([0.0, -45.0, -90.0]),
                "#fff",
                axis_key="right",
                axis_family="phase_deg",
                group_key="V(out)",
                component="phase",
            ),
        ],
        log_x=True,
    )
    page = BodeOverlayChartPage()
    page.set_chart(spec)

    assert page._right_vb is not None
    assert page._rendered_axis_keys["V(out) | Phase"] == "right"
    assert page._x_domain == pytest.approx((-1.0, 1.0))
    assert page._phase_domain == pytest.approx((-90.0, 0.0))


def test_ac_zero_response_is_missing_db_not_invented_floor(qapp):
    result = SimulationResult(
        executor="spice",
        file_path="ac.cir",
        analysis_type="ac",
        success=True,
        source_digest=_SOURCE_DIGEST,
        data=SimulationData(
            frequency=np.array([1.0, 10.0]),
            signals={"V(out)": np.array([0.0 + 0.0j, 1.0 + 0.0j])},
            signal_types={"V(out)": "voltage"},
        ),
        analysis_command=".ac dec 1 1 10",
    )
    series = ChartViewer()._build_bode_overlay_series(result, result.data.frequency)
    magnitude = next(item for item in series if item.component == "magnitude")

    assert np.isnan(magnitude.y_data[0])
    assert magnitude.y_data[1] == pytest.approx(0.0)


def test_ac_phase_display_is_continuous_across_wrap(qapp):
    phase_deg = np.array([179.0, -179.0])
    complex_signal = np.exp(1j * np.radians(phase_deg))
    result = SimulationResult(
        executor="spice",
        file_path="phase.cir",
        analysis_type="ac",
        success=True,
        source_digest=_SOURCE_DIGEST,
        data=SimulationData(
            frequency=np.array([1.0, 2.0]),
            signals={"V(out)": complex_signal},
            signal_types={"V(out)": "voltage"},
        ),
        analysis_command=".ac lin 2 1 2",
    )
    series = ChartViewer()._build_bode_overlay_series(result, result.data.frequency)
    phase = next(item for item in series if item.component == "phase")

    np.testing.assert_allclose(phase.y_data, [179.0, 181.0])
    np.testing.assert_allclose(
        WaveformDataService().get_signal_data(result, "V(out)_phase"),
        [179.0, 181.0],
    )


def test_schema_v3_ac_roundtrip_stores_only_complex_base_and_derives_components():
    phase_deg = np.array([179.0, -179.0])
    original = SimulationResult(
        executor="spice",
        file_path="circuits/phase.cir",
        analysis_type="ac",
        success=True,
        source_digest=_SOURCE_DIGEST,
        data=SimulationData(
            frequency=np.array([1.0, 2.0]),
            signals={"V(out)": np.exp(1j * np.radians(phase_deg))},
            signal_types={"V(out)": "voltage"},
        ),
        analysis_command=".ac lin 2 1 2",
    )

    restored = SimulationResult.from_dict(original.to_dict())

    assert restored.data is not None
    assert set(restored.data.signals) == {"V(out)"}
    assert np.iscomplexobj(restored.data.signals["V(out)"])
    service = WaveformDataService()
    np.testing.assert_allclose(service.get_signal_data(restored, "V(out)_mag"), [1.0, 1.0])
    np.testing.assert_allclose(service.get_signal_data(restored, "V(out)_phase"), [179.0, 181.0])
    np.testing.assert_allclose(
        service.get_signal_data(restored, "V(out)_real"),
        np.real(restored.data.signals["V(out)"]),
    )
    np.testing.assert_allclose(
        service.get_signal_data(restored, "V(out)_imag"),
        np.imag(restored.data.signals["V(out)"]),
    )


@pytest.mark.parametrize("suffix", ["_mag", "_phase", "_real", "_imag"])
def test_waveform_service_rejects_directly_stored_ac_component_vectors(suffix):
    invalid = SimulationResult(
        executor="spice",
        file_path="circuits/invalid_component.cir",
        analysis_type="ac",
        success=True,
        source_digest=_SOURCE_DIGEST,
        data=SimulationData(
            frequency=np.array([1.0, 2.0]),
            signals={f"V(out){suffix}": np.array([1.0, 2.0])},
            signal_types={f"V(out){suffix}": "voltage"},
        ),
        analysis_command=".ac lin 2 1 2",
    )

    service = WaveformDataService()
    assert service.get_resolved_signal_names(invalid) == []
    assert service.get_signal_data(invalid, f"V(out){suffix}") is None


def test_bode_web_snapshot_crops_raw_viewport_before_decimation(qapp):
    x = np.arange(1.0, 10_001.0)
    magnitude = np.zeros_like(x)
    magnitude[4_999] = 60.0
    page = BodeOverlayChartPage()
    page.set_chart(
        ChartSpec(
            chart_type=ChartType.BODE_OVERLAY,
            title="AC",
            x_label="Frequency (Hz)",
            y_label="Magnitude (dB re 1 unit)",
            secondary_y_label="Phase (°)",
            series=[
                ChartSeries(
                    "V(out) | Mag",
                    x,
                    magnitude,
                    "#fff",
                    axis_family="magnitude_db",
                    group_key="V(out)",
                    component="magnitude",
                ),
                ChartSeries(
                    "V(out) | Phase",
                    x,
                    np.zeros_like(x),
                    "#fff",
                    axis_key="right",
                    axis_family="phase_deg",
                    group_key="V(out)",
                    component="phase",
                ),
            ],
        )
    )

    assert (
        page.set_viewport(
            {
                "x_min": 4_990.0,
                "x_max": 5_010.0,
                "left_y_min": 0.0,
                "left_y_max": 60.0,
                "right_y_min": 0.0,
                "right_y_max": 0.0,
            }
        )
        is True
    )
    payloads = page.get_web_snapshot()["visible_series"]

    assert all(len(payload["x"]) < 100 for payload in payloads)
    magnitude_payload = next(
        payload for payload in payloads if payload["component"] == "magnitude"
    )
    assert max(value for value in magnitude_payload["y"] if value is not None) == 60.0


def test_bode_phase_measurement_interpolates_across_wrap_without_false_zero(qapp):
    page = BodeOverlayChartPage()
    page._spec = ChartSpec(
        chart_type=ChartType.BODE_OVERLAY,
        title="AC",
        x_label="Frequency (Hz)",
        y_label="Magnitude",
        series=[],
        log_x=False,
    )
    phase = ChartSeries(
        "V(out) | Phase",
        np.array([1.0, 2.0]),
        np.array([179.0, -179.0]),
        "#fff",
        component="phase",
    )

    assert abs(page._sample_raw_series(phase, 1.5)) == pytest.approx(180.0)


def test_chart_payload_exports_only_currently_visible_series(qapp):
    x = np.array([0.0, 1.0])
    page = ChartPage()
    page.set_chart(
        ChartSpec(
            chart_type=ChartType.WAVEFORM_TIME,
            title="Transient",
            x_label="Time (s)",
            y_label="Voltage (V)",
            series=[
                ChartSeries("V(a)", x, x, "#fff", axis_family="voltage"),
                ChartSeries("V(b)", x, x + 1.0, "#000", axis_family="voltage"),
            ],
        )
    )

    payload = page.build_export_payload()

    assert payload is not None
    assert [item["name"] for item in payload["series"]] == ["V(a)"]


def test_noise_waveform_uses_density_units_and_log_y(qapp):
    frequency = np.array([0.1, 1.0, 10.0])
    result = SimulationResult(
        executor="spice",
        file_path="noise.cir",
        analysis_type="noise",
        success=True,
        source_digest=_SOURCE_DIGEST,
        data=SimulationData(
            frequency=frequency,
            signals={"onoise_spectrum": np.array([1e-12, 1e-11, 1e-10])},
            signal_types={"onoise_spectrum": "voltage"},
        ),
        analysis_command=".noise V(out) Vin dec 10 0.1 10",
    )
    widget = WaveformWidget()

    assert widget.load_waveform(result, "onoise_spectrum") is True
    snapshot = widget.get_web_snapshot()

    assert snapshot["y_label"] == "Voltage Noise Density (V/√Hz)"
    assert snapshot["log_y"] is True
    assert snapshot["right_log_y"] is False
    assert widget._left_y_domain == pytest.approx((-12.0, -10.0))


def test_linear_frequency_sweeps_keep_linear_x_with_correct_y_semantics(qapp):
    noise = SimulationResult(
        executor="spice",
        file_path="circuits/linear_noise.cir",
        analysis_type="noise",
        success=True,
        source_digest=_SOURCE_DIGEST,
        data=SimulationData(
            frequency=np.array([1.0, 2.0]),
            signals={
                "onoise_spectrum": np.array([1e-12, 2e-12]),
                "inoise_spectrum": np.array([0.5e-12, 1e-12]),
            },
            signal_types={
                "onoise_spectrum": "voltage",
                "inoise_spectrum": "voltage",
            },
            noise_totals=NoiseTotals(
                output_rms=2e-12,
                input_referred_rms=1e-12,
            ),
        ),
        analysis_command=".noise V(out) V1 lin 2 1 2",
    )
    noise = SimulationResult.from_dict(noise.to_dict())

    chart = ChartViewer()
    chart.load_result(noise)
    chart_snapshot = chart.get_web_snapshot()
    assert chart_snapshot["log_x"] is False
    assert chart_snapshot["log_y"] is True

    waveform = WaveformWidget()
    assert waveform.load_waveform(noise, "onoise_spectrum") is True
    waveform_snapshot = waveform.get_web_snapshot()
    assert waveform_snapshot["log_x"] is False
    assert waveform_snapshot["log_y"] is True

    ac = SimulationResult(
        executor="spice",
        file_path="circuits/linear_ac.cir",
        analysis_type="ac",
        success=True,
        source_digest=_SOURCE_DIGEST,
        data=SimulationData(
            frequency=np.array([1.0, 2.0]),
            signals={"V(out)": np.array([1.0 + 0.0j, 0.5 - 0.5j])},
            signal_types={"V(out)": "voltage"},
        ),
        analysis_command=".ac lin 2 1 2",
    )
    ac = SimulationResult.from_dict(ac.to_dict())
    chart.load_result(ac)
    assert chart.get_web_snapshot()["log_x"] is False


def test_minimal_failed_measure_result_roundtrips_in_schema_v3():
    result = _result(
        np.array([0.0, 10.0]),
        np.array([0.0, 1.0]),
    )
    result.measurements = [
        MeasureResult(
            name="unreachable",
            status=MeasureStatus.FAILED,
            statement=".measure tran unreachable WHEN V(out)=2",
            error_message="Measurement condition was not satisfied",
        )
    ]

    payload = result.to_dict()
    assert set(payload["measurements"][0]) == {
        "name",
        "value",
        "status",
        "statement",
        "raw_output",
        "error_message",
    }
    restored = SimulationResult.from_dict(payload)

    assert restored.measurements is not None
    measurement = restored.measurements[0]
    assert measurement.status is MeasureStatus.FAILED
    assert measurement.value is None
    assert measurement.statement == ".measure tran unreachable WHEN V(out)=2"
    assert measurement.raw_output == ""
    assert measurement.error_message == "Measurement condition was not satisfied"


def test_waveform_export_uses_full_raw_signal_not_plot_preview(qapp):
    x = np.linspace(0.0, 1.0, 2_000)
    result = _result(x, np.sin(2.0 * np.pi * x))
    widget = WaveformWidget()
    assert widget.load_waveform(result, "V(out)") is True
    assert widget._plot_items["V(out)"].waveform_data.point_count <= 500

    full_series = waveform_export_bundle_builder.build_full_resolution_series(
        result,
        widget._data_service,
        widget._plot_items,
        ["V(out)"],
    )
    rows = waveform_export_bundle_builder.build_export_rows(full_series, "Time (s)")

    assert len(rows) == 2_000
    assert rows[-1]["Time (s)"] == pytest.approx(1.0)


def test_image_export_restores_live_widget_size(qapp, tmp_path: Path):
    owner = QWidget()
    layout = QVBoxLayout(owner)
    target = QLabel("plot")
    layout.addWidget(target)
    owner.resize(320, 240)
    original_size = owner.size()

    assert export_widget_image(owner, target, str(tmp_path / "plot.png")) is True
    assert owner.size() == original_size
