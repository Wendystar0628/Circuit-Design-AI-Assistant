import struct
import zlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from domain.simulation.data.png_metadata import read_png_itxt_chunks
from domain.simulation.data.simulation_artifact_exporter import simulation_artifact_exporter
from domain.simulation.data.simulation_artifact_persistence import simulation_artifact_persistence
from domain.simulation.models.display_metric import DisplayMetric
from domain.simulation.models.simulation_result import NoiseTotals, SimulationData, SimulationResult
from domain.simulation.spice.source_closure import SPICE_SOURCE_CLOSURE_ALGORITHM
from shared.service_locator import ServiceLocator
from shared.service_names import SVC_EVENT_BUS

def _build_minimal_png_bytes() -> bytes:
    """Assemble a valid 1x1 RGBA PNG using pure stdlib so fake
    exporters in tests can emit real PNG files (and we can then verify
    ``iTXt`` chunks are injected after attach). No Pillow dependency.
    """
    ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)
    ihdr_crc = struct.pack('>I', zlib.crc32(b'IHDR' + ihdr_data) & 4294967295)
    ihdr = struct.pack('>I', len(ihdr_data)) + b'IHDR' + ihdr_data + ihdr_crc
    raw = b'\x00' + b'\x00\x00\x00\x00'
    idat_data = zlib.compress(raw, 9)
    idat_crc = struct.pack('>I', zlib.crc32(b'IDAT' + idat_data) & 4294967295)
    idat = struct.pack('>I', len(idat_data)) + b'IDAT' + idat_data + idat_crc
    iend_crc = struct.pack('>I', zlib.crc32(b'IEND') & 4294967295)
    iend = b'\x00\x00\x00\x00' + b'IEND' + iend_crc
    return b'\x89PNG\r\n\x1a\n' + ihdr + idat + iend
_MINIMAL_PNG_BYTES = _build_minimal_png_bytes()
_SOURCE_DIGEST = '0' * 64

@pytest.fixture
def sample_result() -> SimulationResult:
    time = np.array([0.0, 0.1, 0.2, 0.3], dtype=float)
    data = SimulationData(time=time, signals={'V(out)': np.array([1.0, 2.0, 3.0, 4.0], dtype=float), 'V(in)': np.array([0.5, 0.6, 0.7, 0.8], dtype=float)}, signal_types={'V(out)': 'voltage', 'V(in)': 'voltage'})
    result = SimulationResult(executor='spice', file_path='results/export_consistency.cir', analysis_type='tran', success=True, source_digest=_SOURCE_DIGEST, data=data, raw_output='Simulation started\nwarning: test warning\nSimulation finished', timestamp='2026-04-06T00:10:00Z', analysis_command='.tran 100m 300m')
    return SimulationResult.from_dict(result.to_dict())

@pytest.fixture
def sample_mixed_axis_result() -> SimulationResult:
    time = np.array([0.0, 0.1, 0.2, 0.3], dtype=float)
    data = SimulationData(time=time, signals={'V(out)': np.array([1.0, 2.0, 3.0, 4.0], dtype=float), 'I(V1)': np.array([0.001, 0.0015, 0.002, 0.0025], dtype=float)}, signal_types={'V(out)': 'voltage', 'I(V1)': 'current'})
    return SimulationResult(executor='spice', file_path='results/export_consistency_mixed.cir', analysis_type='tran', success=True, source_digest=_SOURCE_DIGEST, data=data, raw_output='Transient mixed-axis simulation finished', timestamp='2026-04-06T00:12:00Z', analysis_command='.tran 100m 300m')

@pytest.fixture
def sample_noise_result() -> SimulationResult:
    frequency = np.array([10.0, 100.0, 1000.0, 10000.0], dtype=float)
    data = SimulationData(frequency=frequency, signals={'onoise_spectrum': np.array([1e-09, 2e-09, 3e-09, 4e-09], dtype=float), 'inoise_spectrum': np.array([2e-12, 3e-12, 4e-12, 5e-12], dtype=float)}, signal_types={'onoise_spectrum': 'voltage', 'inoise_spectrum': 'current'}, noise_totals=NoiseTotals(output_rms=5e-09, input_referred_rms=7e-12))
    result = SimulationResult(executor='spice', file_path='results/export_consistency_noise.cir', analysis_type='noise', success=True, source_digest=_SOURCE_DIGEST, data=data, raw_output='Noise simulation finished', timestamp='2026-04-06T00:18:00Z', analysis_command='.noise v(out) I1 dec 1 10 10k')
    return SimulationResult.from_dict(result.to_dict())

@pytest.fixture
def sample_ac_result() -> SimulationResult:
    frequency = np.array([1000.0, 10000.0, 100000.0, 1000000.0], dtype=float)
    response = np.array([0.70710678 - 0.70710678j, 0.09950372 - 0.99503719j, 0.0099995 - 0.99995j, 0.001 - 0.9999995j], dtype=complex)
    data = SimulationData(frequency=frequency, signals={'V(out)': response}, signal_types={'V(out)': 'voltage'})
    result = SimulationResult(executor='spice', file_path='results/export_consistency_ac.cir', analysis_type='ac', success=True, source_digest=_SOURCE_DIGEST, data=data, raw_output='AC simulation finished', timestamp='2026-04-06T00:15:00Z', analysis_command='.ac dec 1 1k 1Meg')
    return SimulationResult.from_dict(result.to_dict())

@pytest.fixture
def invalid_derived_ac_result() -> SimulationResult:
    frequency = np.array([1000.0, 10000.0, 100000.0, 1000000.0], dtype=float)
    data = SimulationData(frequency=frequency, signals={'V(out)_mag': np.array([0.70710678, 0.09950372, 0.0099995, 0.001], dtype=float), 'V(out)_phase': np.array([-45.0, -84.2894, -89.4271, -89.9427], dtype=float)}, signal_types={'V(out)_mag': 'voltage', 'V(out)_phase': 'voltage'})
    return SimulationResult(executor='spice', file_path='results/export_consistency_invalid_ac.cir', analysis_type='ac', success=True, source_digest=_SOURCE_DIGEST, data=data, raw_output='AC simulation finished', timestamp='2026-04-06T00:20:00Z', analysis_command='.ac dec 20 1k 1Meg')

@pytest.fixture
def sample_metrics():
    return [DisplayMetric(display_name='Gain', name='gain', value='20', unit='dB', status='OK', error_message='', raw_value=20.0, target='>= 18 dB')]

def _assert_common_artifact_payload(payload: dict, artifact_type: str, *, expected_file_name: str, expected_x_axis_label: str):
    assert payload['artifact_type'] == artifact_type
    assert payload['schema_version'] == 2
    assert isinstance(payload['metadata'], dict)
    assert isinstance(payload['summary'], dict)
    assert isinstance(payload['files'], dict)
    assert isinstance(payload['data'], dict)
    assert payload['metadata']['file_name'] == expected_file_name
    assert payload['metadata']['x_axis_label'] == expected_x_axis_label
    assert payload['metadata']['source_digest'] == _SOURCE_DIGEST
    assert payload['metadata']['source_digest_algorithm'] == SPICE_SOURCE_CLOSURE_ALGORITHM

def test_artifact_exporter_outputs_common_payload_schema(sample_result: SimulationResult, sample_metrics, tmp_path: Path):
    export_root = simulation_artifact_exporter.create_export_root(str(tmp_path), sample_result)
    simulation_artifact_exporter.export_metrics(export_root, sample_result, sample_metrics)
    simulation_artifact_exporter.export_analysis_info(export_root, sample_result)
    simulation_artifact_exporter.export_raw_data(export_root, sample_result)
    simulation_artifact_exporter.export_output_log(export_root, sample_result)
    metrics_payload = __import__('json').loads((export_root / 'metrics' / 'metrics.json').read_text(encoding='utf-8'))
    analysis_payload = __import__('json').loads((export_root / 'analysis_info' / 'analysis_info.json').read_text(encoding='utf-8'))
    raw_data_payload = __import__('json').loads((export_root / 'raw_data' / 'raw_data.json').read_text(encoding='utf-8'))
    output_log_payload = __import__('json').loads((export_root / 'output_log' / 'output_log.json').read_text(encoding='utf-8'))
    _assert_common_artifact_payload(metrics_payload, 'metrics', expected_file_name='export_consistency.cir', expected_x_axis_label='Time (s)')
    _assert_common_artifact_payload(analysis_payload, 'analysis_info', expected_file_name='export_consistency.cir', expected_x_axis_label='Time (s)')
    _assert_common_artifact_payload(raw_data_payload, 'raw_data', expected_file_name='export_consistency.cir', expected_x_axis_label='Time (s)')
    _assert_common_artifact_payload(output_log_payload, 'output_log', expected_file_name='export_consistency.cir', expected_x_axis_label='Time (s)')
    assert metrics_payload['data']['columns'][0] == 'display_name'
    assert metrics_payload['data']['columns'][4:6] == ['status', 'error_message']
    assert metrics_payload['data']['rows'][0]['status'] == 'OK'
    assert metrics_payload['summary']['failed_metric_count'] == 0
    assert analysis_payload['files']['text'] == 'analysis_info.txt'
    assert raw_data_payload['data']['columns'][0] == 'Time (s)'
    assert len(raw_data_payload['data']['rows']) == 4
    assert len(raw_data_payload['data']['series']) == 2
    assert output_log_payload['files']['text'] == 'output_log.txt'
    assert len(output_log_payload['data']['lines']) == 3
    assert output_log_payload['summary']['warning_count'] == 1

def test_metric_export_preserves_failed_outcome_and_diagnostic(sample_result: SimulationResult, tmp_path: Path):
    export_root = simulation_artifact_exporter.create_export_root(str(tmp_path), sample_result)
    failed_metric = DisplayMetric(name='settling_time', display_name='Settling Time', value='', unit='s', status='FAILED', error_message='Error: out of interval', raw_value=None, target='< 1 ms')
    simulation_artifact_exporter.export_metrics(export_root, sample_result, [failed_metric])
    payload = __import__('json').loads((export_root / 'metrics' / 'metrics.json').read_text(encoding='utf-8'))
    row = payload['data']['rows'][0]
    assert payload['summary']['failed_metric_count'] == 1
    assert row['status'] == 'FAILED'
    assert row['error_message'] == 'Error: out of interval'
    assert row['value'] == ''
    assert row['raw_value'] is None

def test_integrated_noise_totals_export_separately_from_density_series(tmp_path: Path):
    result = SimulationResult(executor='spice', file_path='results/noise_totals.cir', analysis_type='noise', success=True, source_digest=_SOURCE_DIGEST, data=SimulationData(frequency=np.array([1.0, 2.0]), signals={'onoise_spectrum': np.array([1e-09, 2e-09]), 'inoise_spectrum': np.array([5e-10, 1e-09])}, signal_types={'onoise_spectrum': 'voltage', 'inoise_spectrum': 'voltage'}, noise_totals=NoiseTotals(output_rms=3e-09, input_referred_rms=1.5e-09)), analysis_command='.noise V(out) V1 lin 2 1 2')
    export_root = simulation_artifact_exporter.create_export_root(str(tmp_path), result)
    simulation_artifact_exporter.export_metrics(export_root, result, [])
    simulation_artifact_exporter.export_raw_data(export_root, result)
    simulation_artifact_exporter.export_analysis_info(export_root, result)
    json_module = __import__('json')
    metrics = json_module.loads((export_root / 'metrics' / 'metrics.json').read_text(encoding='utf-8'))
    raw_data = json_module.loads((export_root / 'raw_data' / 'raw_data.json').read_text(encoding='utf-8'))
    analysis_info = json_module.loads((export_root / 'analysis_info' / 'analysis_info.json').read_text(encoding='utf-8'))
    expected = {'applicable': True, 'available': True, 'source': 'ngspice_noise_totals', 'items': [{'key': 'output_rms', 'value': 3e-09, 'unit': 'V'}, {'key': 'input_referred_rms', 'value': 1.5e-09, 'unit': 'V'}]}
    assert metrics['data']['noise_totals'] == expected
    assert metrics['data']['rows'] == []
    assert raw_data['data']['noise_totals'] == expected
    assert 'output_rms' not in raw_data['data']['columns']
    assert 'input_referred_rms' not in raw_data['data']['columns']
    assert analysis_info['data']['noise_totals'] == expected
    assert all(('��Hz' not in item['unit'] for item in expected['items']))

def test_external_export_root_uses_unique_timestamp_directories(sample_result: SimulationResult, tmp_path: Path):
    external_base = tmp_path / 'exports'
    first_root = simulation_artifact_exporter.create_export_root(str(external_base), sample_result)
    second_root = simulation_artifact_exporter.create_export_root(str(external_base), sample_result)
    assert first_root.relative_to(external_base).parts == ('export_consistency', '2026-04-06_00-10-00')
    assert second_root.relative_to(external_base).parts == ('export_consistency', '2026-04-06_00-10-00_2')

def test_artifact_persistence_writes_authoritative_bundle_regardless_of_ui_selection(sample_result: SimulationResult, tmp_path: Path):
    """``SimulationArtifactPersistence`` is the sole owner of the
    canonical ``simulation_results/<stem>/<ts>/`` bundle.

    It runs after every simulation (UI or agent) with no user-facing
    selection. The immutable bundle contains only the authoritative
    ``result.json``; every CSV/TXT/PNG/derived JSON is an external export
    or a bundle-external conversation attachment.
    """
    from domain.simulation.data.simulation_artifact_persistence import simulation_artifact_persistence
    outcome = simulation_artifact_persistence.persist_bundle(project_root=str(tmp_path), result=sample_result)
    assert outcome.export_root.relative_to(tmp_path).parts == ('simulation_results', 'export_consistency', '2026-04-06_00-10-00')
    assert outcome.result_path.replace('\\', '/') == 'simulation_results/export_consistency/2026-04-06_00-10-00/result.json'
    bundle_root = outcome.export_root
    assert {path.relative_to(bundle_root).as_posix() for path in bundle_root.rglob('*') if path.is_file()} == {'result.json'}

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
