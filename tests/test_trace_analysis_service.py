"""Engineering invariants for the single simulation trace authority."""

import csv
import io
import json
import math

import numpy as np
import pytest

from domain.simulation.data.trace_analysis_service import TraceAnalysisService
from domain.simulation.data.waveform_data_service import WaveformDataService
from domain.simulation.models.simulation_result import SimulationData, SimulationResult


SERVICE = TraceAnalysisService()


def _result(analysis, x, signals, command, types=None):
    axis = {"ac": "frequency", "tran": "time", "dc": "sweep"}.get(analysis)
    data = SimulationData(signals={name: np.asarray(values) for name, values in signals.items()},
                          signal_types=types or {name: "voltage" for name in signals},
                          **({axis: np.asarray(x, dtype=float)} if axis else {}))
    return SimulationResult(executor="spice", file_path="trace.cir", analysis_type=analysis,
                            success=True, source_digest="a" * 64, analysis_command=command, data=data)


def _trace(signal="V(out)", component="real", reference=None):
    return {"signal": signal, "reference": reference, "component": component}


def test_ac_transfer_uses_complex_reference_before_db_and_phase():
    f = np.logspace(1, 4, 100)
    h = 1 / (1 + 1j * f / 1000)
    source = np.full(len(f), 2 * np.exp(1j * np.radians(35)))
    result = _result("ac", f, {"V(in)": source, "V(out)": source * h}, ".ac dec 33 10 10k")
    traces = [_trace(component="db", reference="V(in)"), _trace(component="phase", reference="V(in)"), _trace(component="db")]
    query = SERVICE.query(result, traces)
    ratio, phase, absolute = query["series"]
    np.testing.assert_allclose(ratio["y"], 20 * np.log10(np.abs(h)))
    np.testing.assert_allclose(phase["y"], np.degrees(np.angle(h)))
    np.testing.assert_allclose(np.asarray(absolute["y"]) - ratio["y"], 20 * np.log10(2))
    assert (ratio["unit"], phase["unit"], absolute["unit"]) == ("dB", "°", "dBV")
    assert "gain" not in absolute["label"].lower()
    assert query["x_axis"] == {"kind": "frequency", "label": "Frequency", "unit": "Hz", "scale": "log"}


def test_phase_unwrap_restarts_at_undefined_reference_and_table_keeps_raw_rows():
    phase = np.radians([179, -179, 20, -179, 179])
    result = _result("ac", [1, 2, 3, 4, 5], {"V(out)": np.exp(1j * phase), "V(in)": np.array([1, 1, 0, 1, 1], dtype=complex)}, ".ac lin 5 1 5")
    traces = [_trace(component="phase", reference="V(in)")]
    query = SERVICE.query(result, traces)
    assert query["series"][0]["y"] == pytest.approx([179, 181, None, -179, -181])
    assert query["series"][0]["invalid_sample_count"] == 1
    table = SERVICE.table(result, traces)
    assert table["total_rows"] == 5
    assert [row["x"] for row in table["rows"]] == [1, 2, 3, 4, 5]
    assert table["rows"][2]["values"] == [None]
    measurement = SERVICE.measure(result, traces, cursor_a=2.5, cursor_b=6)["measurements"][0]
    assert measurement["cursor_a"]["status"] == "gap"
    assert measurement["cursor_b"]["status"] == "outside"
    assert measurement["delta_y"] is None
    json.dumps(query, allow_nan=False)
    json.dumps(table, allow_nan=False)


def test_nonuniform_transient_time_moments_use_exact_piecewise_linear_integrals():
    result = _result("tran", [0, 0.1, 1], {"V(out)": [0, 0.1, 1]}, ".tran 100m 1")
    measurement = SERVICE.measure(result, [_trace()], cursor_a=0.2, cursor_b=0.8)["measurements"][0]
    assert measurement["sample_mean"] == pytest.approx(1.1 / 3)
    assert measurement["time_mean"] == pytest.approx(0.5)
    assert measurement["time_rms"] == pytest.approx(math.sqrt(1 / 3))
    assert measurement["cursor_a"]["y"] == pytest.approx(0.2)
    assert measurement["delta_y"] == pytest.approx(0.6)
    assert measurement["slope"] == pytest.approx(1)
    # Neither boundary is a native point. Integrate only the requested interval.
    clipped = SERVICE.measure(result, [_trace()], x_min=0.2, x_max=0.8)["measurements"][0]
    assert clipped["sample_count"] == 0
    assert clipped["min"] == pytest.approx(0.2)
    assert clipped["max"] == pytest.approx(0.8)
    assert clipped["time_mean"] == pytest.approx(0.5)
    assert clipped["time_rms"] == pytest.approx(math.sqrt((0.8**3 - 0.2**3) / (3 * 0.6)))
    assert clipped["duration"] == pytest.approx(0.6)


def test_transient_absolute_value_does_not_claim_a_false_physical_rms_across_zero():
    result = _result("tran", [0, 1], {"V(out)": [-1, 1]}, ".tran 1 1")
    measurements = SERVICE.measure(result, [_trace(), _trace(component="magnitude")])["measurements"]
    native, absolute = measurements
    assert native["time_rms"] == pytest.approx(math.sqrt(1 / 3))
    # Linear interpolation of |samples| is constant 1, whereas |linear V|
    # crosses zero. Do not present the former's RMS as a physical measurement.
    assert absolute["sample_mean"] == 1
    assert absolute["time_mean"] is None
    assert absolute["time_rms"] is None
    assert "require an unreferenced real transient trace" in absolute["statistics_basis"]


def test_nested_dc_branch_identity_is_raw_data_and_never_blended_by_cursors():
    result = _result("dc", [0, 1, 0, 1, 0, 1], {"V(out)": [0, 1, 10, 11, 20, 21]}, ".dc V1 0 1 1 V2 1 3 1")
    query = SERVICE.query(result, [_trace()], x_min=0.4, x_max=0.6)
    series = query["series"][0]
    assert series["x"] == [0, 1, None, 0, 1, None, 0, 1]
    assert series["branch_ids"] == [0, 0, None, 1, 1, None, 2, 2]
    assert [branch["outer_value"] for branch in series["branches"]] == [1, 2, 3]
    table = SERVICE.table(result, [_trace()], offset=1, limit=3)
    assert table["total_rows"] == 6
    assert [row["branch_id"] for row in table["rows"]] == [0, 1, 1]
    assert [row["outer_value"] for row in table["rows"]] == [1, 2, 2]
    measurements = SERVICE.measure(result, [_trace()], cursor_a=0.5)["measurements"]
    assert [row["cursor_a"]["y"] for row in measurements] == [0.5, 10.5, 20.5]
    assert all(row["time_mean"] is None for row in measurements)
    assert all(row["time_rms"] is None for row in measurements)
    legacy = WaveformDataService().build_table_snapshot(result)
    assert legacy.total_rows == 6
    assert np.all(np.isfinite(legacy.x_values))
    with pytest.raises(ValueError, match="at least 8 points"):
        SERVICE.query(result, [_trace()], max_points=6)


def test_decimation_keeps_spikes_on_sparse_time_regions_and_raw_stats_are_independent():
    x = np.concatenate((np.linspace(0, 1e-6, 9900), np.linspace(1, 100, 100)))
    y = np.zeros(len(x))
    y[9960] = 80
    y[9950] = -30
    result = _result("tran", x, {"V(out)": y}, ".tran 1u 100")
    small = SERVICE.query(result, [_trace()], max_points=20)["series"][0]
    assert len(small["x"]) <= 20
    assert min(small["y"]) == -30
    assert max(small["y"]) == 80
    assert small["x"] == sorted(small["x"])
    assert small["downsampled"]
    with pytest.raises(ValueError, match="extremum"):
        SERVICE.query(result, [_trace()], max_points=2)
    metrics = SERVICE.measure(result, [_trace()])["measurements"][0]
    assert metrics["sample_count"] == 10000
    assert metrics["peak_to_peak"] == 110


def test_table_csv_and_chart_share_complex_derived_numbers_and_full_resolution():
    f = np.arange(1, 51, dtype=float)
    result = _result("ac", f, {"V(out)": 1 / (1 + 1j * f)}, ".ac lin 50 1 50")
    traces = [_trace(component="real"), _trace(component="imaginary")]
    table = SERVICE.table(result, traces, offset=0, limit=200)
    exported = SERVICE.export_csv(result, traces)
    rows = list(csv.reader(io.StringIO("\n".join(line for line in exported.splitlines() if not line.startswith("#")))))
    assert len(rows) == 51
    for original, row in zip(table["rows"], rows[1:]):
        assert [float(value) for value in row[4:]] == original["values"]
    assert "full resolution" in exported
    assert "\"component\": \"imaginary\"" in exported


def test_units_preserve_impedance_and_never_invent_a_db_reference():
    result = _result("ac", [1, 2], {"V(out)": np.array([2, 4], dtype=complex), "I(V1)": np.array([1, 2], dtype=complex), "mystery": np.array([1, 2], dtype=complex)}, ".ac lin 2 1 2",
                     {"V(out)": "voltage", "I(V1)": "current", "mystery": "other"})
    query = SERVICE.query(result, [_trace(component="magnitude", reference="I(V1)"), _trace("I(V1)", "db")])
    assert query["series"][0]["unit"] == "Ω"
    assert query["series"][0]["y"] == [2, 2]
    assert query["series"][1]["unit"] == "dBA"
    with pytest.raises(ValueError, match="same known physical dimension"):
        SERVICE.query(result, [_trace(component="db", reference="I(V1)")])
    with pytest.raises(ValueError, match="known V or A"):
        SERVICE.query(result, [_trace("mystery", "db")])
    catalog = SERVICE.catalog(result)
    assert "db" not in next(signal for signal in catalog["signals"] if signal["name"] == "mystery")["components"]


def test_large_finite_samples_do_not_overflow_time_moments_or_json():
    result = _result("tran", [0, 1], {"V(out)": [1e200, 1e200]}, ".tran 1 1")
    payload = SERVICE.measure(result, [_trace()])
    row = payload["measurements"][0]
    assert row["time_mean"] == pytest.approx(1e200)
    assert row["time_rms"] == pytest.approx(1e200)
    json.dumps(payload, allow_nan=False)


def test_failed_run_catalog_and_single_point_operating_point_remain_usable():
    failed = SimulationResult(executor="spice", file_path="bad.cir", analysis_type="op", success=False)
    assert SERVICE.catalog(failed)["signals"] == []
    result = _result("op", None, {"V(out)": [3.3]}, ".op")
    assert SERVICE.catalog(result)["x_axis"]["kind"] == "none"
    assert SERVICE.table(result, [_trace()])["rows"][0]["values"] == [3.3]
    assert SERVICE.measure(result, [_trace()])["measurements"][0]["time_rms"] is None


@pytest.mark.parametrize("changes", [{"max_points": True}, {"x_min": math.nan}, {"x_min": 2, "x_max": 1}])
def test_query_rejects_ambiguous_or_nonfinite_numeric_inputs(changes):
    result = _result("tran", [0, 1], {"V(out)": [0, 1]}, ".tran 1 1")
    with pytest.raises(ValueError):
        SERVICE.query(result, [_trace()], **changes)
