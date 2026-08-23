import json
from pathlib import Path
import numpy as np
import pytest
from domain.simulation.data.downsampler import crop_to_viewport, downsample, downsample_preserving_gaps
from domain.simulation.data.signal_semantics import insert_nested_dc_breaks, nested_dc_secondary_values, parse_nested_dc_sweep
from domain.simulation.data.simulation_artifact_exporter import simulation_artifact_exporter
from domain.simulation.data.waveform_data_service import WaveformDataService
from domain.simulation.measure.measure_result import MeasureResult, MeasureStatus
from domain.simulation.models.chart_type import ChartType
from domain.simulation.models.simulation_result import NoiseTotals, SimulationData, SimulationResult
_SOURCE_DIGEST = 'a' * 64

def _result(x: np.ndarray, y: np.ndarray) -> SimulationResult:
    return SimulationResult(executor='spice', file_path='numeric_safety.cir', analysis_type='tran', success=True, source_digest=_SOURCE_DIGEST, data=SimulationData(time=x, signals={'V(out)': y}, signal_types={'V(out)': 'voltage'}), analysis_command='.tran 1u 10')

def _nested_dc_result(x: np.ndarray, y: np.ndarray) -> SimulationResult:
    return SimulationResult(executor='spice', file_path='nested_dc.cir', analysis_type='dc', success=True, source_digest=_SOURCE_DIGEST, data=SimulationData(sweep=x, signals={'I(Vce)': y}, signal_types={'I(Vce)': 'current'}), analysis_command='.dc Vce 0 10 5 Ib 10u 30u 10u')

def test_peak_decimator_keeps_spike_caps_points_and_drops_non_finite_pairs():
    x = np.arange(10000, dtype=float)
    y = np.zeros(9900, dtype=float)
    y[4321] = 123.0
    x[100] = np.nan
    y[200] = np.inf
    x_out, y_out = downsample(x, y, target_points=100)
    assert 0 < len(x_out) <= 100
    assert len(x_out) == len(y_out)
    assert np.all(np.isfinite(x_out))
    assert np.all(np.isfinite(y_out))
    assert np.max(y_out) == 123.0

def test_gap_preserving_decimator_keeps_break_spike_and_point_cap():
    x = np.arange(2000, dtype=float)
    y = np.zeros_like(x)
    y[500:510] = np.nan
    y[1500] = 90.0
    x_out, y_out = downsample_preserving_gaps(x, y, target_points=80)
    assert len(x_out) == len(y_out) <= 80
    assert np.any(~np.isfinite(x_out) & ~np.isfinite(y_out))
    assert np.nanmax(y_out) == 90.0

def test_viewport_is_cut_before_decimation_and_narrow_gap_returns_brackets():
    x = np.linspace(0.0, 10.0, 10001)
    y = np.zeros_like(x)
    y[5000] = 50.0
    service = WaveformDataService()
    result = _result(x, y)
    spike_view = service.get_viewport_data(result, 'V(out)', 4.99, 5.01, target_points=12)
    gap_view = service.get_viewport_data(result, 'V(out)', 4.0001, 4.0002, target_points=12)
    assert spike_view is not None
    assert spike_view.point_count <= 12
    assert np.max(spike_view.y_data) == 50.0
    assert gap_view is not None
    assert gap_view.point_count == 2
    assert gap_view.x_data[0] <= 4.0001 <= gap_view.x_data[-1]

def test_nested_sweep_viewport_keeps_every_crossing_branch():
    x = np.array([0.0, 10.0, 0.0, 10.0, 0.0, 10.0])
    y = np.arange(6, dtype=float)
    view = WaveformDataService().get_viewport_data(_nested_dc_result(x, y), 'I(Vce)', 4.0, 6.0, target_points=12)
    assert view is not None
    np.testing.assert_allclose(view.x_data, [0.0, 10.0, np.nan, 0.0, 10.0, np.nan, 0.0, 10.0], equal_nan=True)
    np.testing.assert_allclose(view.y_data, [0.0, 1.0, np.nan, 2.0, 3.0, np.nan, 4.0, 5.0], equal_nan=True)

@pytest.mark.parametrize('second_branch_x', ([0.0, 1.0], [1.0, 0.0]))
def test_viewport_keeps_crossing_branch_when_another_branch_has_inside_sample(second_branch_x):
    x = np.array([0.0, 0.5, 1.0, np.nan, *second_branch_x])
    y = np.array([0.0, 0.5, 1.0, np.nan, 10.0, 11.0])
    cropped_x, cropped_y = crop_to_viewport(x, y, 0.49, 0.51)
    np.testing.assert_allclose(cropped_x, [0.0, 0.5, 1.0, np.nan, *second_branch_x], equal_nan=True)
    np.testing.assert_allclose(cropped_y, [0.0, 0.5, 1.0, np.nan, 10.0, 11.0], equal_nan=True)

def test_schema_v3_ac_roundtrip_stores_only_complex_base_and_derives_components():
    phase_deg = np.array([179.0, -179.0])
    original = SimulationResult(executor='spice', file_path='circuits/phase.cir', analysis_type='ac', success=True, source_digest=_SOURCE_DIGEST, data=SimulationData(frequency=np.array([1.0, 2.0]), signals={'V(out)': np.exp(1j * np.radians(phase_deg))}, signal_types={'V(out)': 'voltage'}), analysis_command='.ac lin 2 1 2')
    restored = SimulationResult.from_dict(original.to_dict())
    assert restored.data is not None
    assert set(restored.data.signals) == {'V(out)'}
    assert np.iscomplexobj(restored.data.signals['V(out)'])
    service = WaveformDataService()
    np.testing.assert_allclose(service.get_signal_data(restored, 'V(out)_mag'), [1.0, 1.0])
    np.testing.assert_allclose(service.get_signal_data(restored, 'V(out)_phase'), [179.0, 181.0])
    np.testing.assert_allclose(service.get_signal_data(restored, 'V(out)_real'), np.real(restored.data.signals['V(out)']))
    np.testing.assert_allclose(service.get_signal_data(restored, 'V(out)_imag'), np.imag(restored.data.signals['V(out)']))

@pytest.mark.parametrize('suffix', ['_mag', '_phase', '_real', '_imag'])
def test_waveform_service_rejects_directly_stored_ac_component_vectors(suffix):
    invalid = SimulationResult(executor='spice', file_path='circuits/invalid_component.cir', analysis_type='ac', success=True, source_digest=_SOURCE_DIGEST, data=SimulationData(frequency=np.array([1.0, 2.0]), signals={f'V(out){suffix}': np.array([1.0, 2.0])}, signal_types={f'V(out){suffix}': 'voltage'}), analysis_command='.ac lin 2 1 2')
    service = WaveformDataService()
    assert service.get_resolved_signal_names(invalid) == []
    assert service.get_signal_data(invalid, f'V(out){suffix}') is None

def test_minimal_failed_measure_result_roundtrips_in_schema_v3():
    result = _result(np.array([0.0, 10.0]), np.array([0.0, 1.0]))
    result.measurements = [MeasureResult(name='unreachable', status=MeasureStatus.FAILED, statement='.measure tran unreachable WHEN V(out)=2', error_message='Measurement condition was not satisfied')]
    payload = result.to_dict()
    assert set(payload['measurements'][0]) == {'name', 'value', 'status', 'statement', 'raw_output', 'error_message'}
    restored = SimulationResult.from_dict(payload)
    assert restored.measurements is not None
    measurement = restored.measurements[0]
    assert measurement.status is MeasureStatus.FAILED
    assert measurement.value is None
    assert measurement.statement == '.measure tran unreachable WHEN V(out)=2'
    assert measurement.raw_output == ''
    assert measurement.error_message == 'Measurement condition was not satisfied'
