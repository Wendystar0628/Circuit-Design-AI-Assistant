import errno
import hashlib
import json
import struct
import zlib
from pathlib import Path

import numpy as np
import pytest

from domain.simulation.data.op_result_payload import build_op_result_payload_from_signals
from domain.simulation.data.png_metadata import inject_png_itxt_chunks, read_png_itxt_chunks
from domain.simulation.data.simulation_artifact_exporter import simulation_artifact_exporter
from domain.simulation.data.simulation_artifact_persistence import simulation_artifact_persistence
from domain.simulation.data.simulation_output_reader import LogLevel, simulation_output_reader
from domain.simulation.measure.measure_result import MeasureResult, MeasureStatus
from domain.simulation.models.simulation_result import (
    NoiseTotals,
    RESULT_SCHEMA_VERSION,
    SimulationData,
    SimulationResult,
    create_success_result,
)
from domain.simulation.models.simulation_error import (
    ErrorSeverity,
    SimulationError,
    SimulationErrorType,
)
from domain.simulation.service.display_metric_builder import display_metric_builder
from domain.simulation.service.simulation_result_repository import (
    SimulationResultRepository,
)
from shared.models.load_result import LoadErrorCode


_SOURCE_DIGEST = hashlib.sha256(b"simulation-persistence-fixture").hexdigest()


def _complex_vector(values) -> dict[str, object]:
    array = np.asarray(values, dtype=complex)
    return {
        "_complex": True,
        "real": np.real(array).tolist(),
        "imag": np.imag(array).tolist(),
    }


def _result(*, file_path: str = "circuits/amp.cir", timestamp: str = "2026-08-23T12:00:00Z") -> SimulationResult:
    return SimulationResult(
        executor="spice",
        file_path=file_path,
        analysis_type="tran",
        success=True,
        source_digest=_SOURCE_DIGEST,
        data=SimulationData(
            time=np.array([0.0, 1e-3]),
            signals={"V(out)": np.array([0.0, 1.0])},
            signal_types={"V(out)": "voltage"},
        ),
        raw_output="No errors\nSimulation finished",
        timestamp=timestamp,
        analysis_command=".tran 1u 1m",
    )


def _structured_error(
    message: str = "simulation failed",
    *,
    file_path: str | None = None,
) -> SimulationError:
    return SimulationError(
        type=SimulationErrorType.SCRIPT_ERROR,
        severity=ErrorSeverity.HIGH,
        message=message,
        file_path=file_path,
    )


def _minimal_png() -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixels = zlib.compress(b"\x00\x00\x00\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")


def test_repository_rejects_noncanonical_and_escaping_result_handles(tmp_path: Path):
    repository = SimulationResultRepository()
    outside = tmp_path.parent / "outside-result.json"
    outside.write_text(json.dumps(_result().to_dict()), encoding="utf-8")

    for handle in (
        "../outside-result.json",
        "simulation_results/amp/run/../../../../outside-result.json",
        str(outside),
        "simulation_results\\amp\\run\\result.json",
        "./simulation_results/amp/run/result.json",
        "simulation_results//amp/run/result.json",
        "simulation_results/C:/run/result.json",
        "simulation_results/amp/run/not-result.json",
        "simulation_results/result.json",
        "simulation_results/amp/extra/run/result.json",
    ):
        loaded = repository.load(str(tmp_path), handle)
        assert loaded.success is False
        assert loaded.error_code == LoadErrorCode.PARSE_ERROR
        assert repository.resolve_bundle_dir(str(tmp_path), handle) is None
        assert repository.delete(str(tmp_path), handle) is False


def test_repository_rejects_symlinked_bundle(tmp_path: Path):
    repository = SimulationResultRepository()
    outside = tmp_path.parent / f"outside-bundle-{tmp_path.name}"
    outside.mkdir()
    (outside / "result.json").write_text(json.dumps(_result().to_dict()), encoding="utf-8")
    link = tmp_path / "simulation_results" / "amp" / "run"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are not available in this environment")

    handle = "simulation_results/amp/run/result.json"
    assert repository.load(str(tmp_path), handle).success is False
    assert repository.resolve_bundle_dir(str(tmp_path), handle) is None
    assert repository.delete(str(tmp_path), handle) is False
    assert (outside / "result.json").exists()


def test_repository_load_fails_closed_for_corrupt_or_false_typed_success(tmp_path: Path):
    repository = SimulationResultRepository()
    bundle = tmp_path / "simulation_results" / "amp" / "run"
    bundle.mkdir(parents=True)
    result_file = bundle / "result.json"
    handle = "simulation_results/amp/run/result.json"

    result_file.write_text("{broken", encoding="utf-8")
    corrupt = repository.load(str(tmp_path), handle)
    assert corrupt.success is False
    assert corrupt.error_code == LoadErrorCode.PARSE_ERROR

    payload = _result().to_dict()
    payload["success"] = "false"
    result_file.write_text(json.dumps(payload), encoding="utf-8")
    false_typed = repository.load(str(tmp_path), handle)
    assert false_typed.success is False
    assert false_typed.error_code == LoadErrorCode.PARSE_ERROR

    for field_name, invalid_value in (
        ("timestamp", "2026-08-23T12:00:00"),
        ("version", "1"),
        ("raw_output", ["not", "text"]),
        (
            "analysis_info",
            {
                "analysis_type": "ac",
                "x_axis_kind": "frequency",
                "parameters": {"points_per_decade": "forged"},
            },
        ),
    ):
        payload = _result().to_dict()
        payload[field_name] = invalid_value
        result_file.write_text(json.dumps(payload), encoding="utf-8")
        assert repository.load(str(tmp_path), handle).success is False

    payload = _result().to_dict()
    payload.update(
        success=False,
        data=None,
        error={"type": "E008", "message": "missing severity"},
    )
    result_file.write_text(json.dumps(payload), encoding="utf-8")
    assert repository.load(str(tmp_path), handle).success is False

    missing_schema = _result().to_dict()
    missing_schema.pop("schema_version")
    with pytest.raises(ValueError, match="schema_version"):
        SimulationResult.from_dict(missing_schema)

    for invalid_file_path in (
        str(tmp_path / "circuits" / "amp.cir"),
        "../outside.cir",
        "circuits\\amp.cir",
        "circuits/./amp.cir",
        "C:/circuits/amp.cir",
    ):
        payload = _result().to_dict()
        payload["file_path"] = invalid_file_path
        with pytest.raises(ValueError, match="project-relative POSIX"):
            SimulationResult.from_dict(payload)


def test_repository_enforces_analysis_axis_and_signal_shape_contract(tmp_path: Path):
    repository = SimulationResultRepository()
    bundle = tmp_path / "simulation_results" / "amp" / "run"
    bundle.mkdir(parents=True)
    result_file = bundle / "result.json"
    handle = "simulation_results/amp/run/result.json"
    valid = _result().to_dict()

    invalid_payloads = []

    shortened_signal = json.loads(json.dumps(valid))
    shortened_signal["data"]["signals"]["V(out)"] = [0.0]
    invalid_payloads.append(shortened_signal)

    nonfinite_axis_gap = json.loads(json.dumps(valid))
    nonfinite_axis_gap["data"]["time"] = [0.0, None]
    invalid_payloads.append(nonfinite_axis_gap)

    unrelated_axis = json.loads(json.dumps(valid))
    unrelated_axis["data"]["frequency"] = [1.0, 2.0]
    invalid_payloads.append(unrelated_axis)

    empty_success = json.loads(json.dumps(valid))
    empty_success["data"]["signals"] = {}
    empty_success["data"]["signal_types"] = {}
    invalid_payloads.append(empty_success)

    wrong_axis_metadata = json.loads(json.dumps(valid))
    wrong_axis_metadata["x_axis_kind"] = "frequency"
    invalid_payloads.append(wrong_axis_metadata)

    wrong_scale_metadata = json.loads(json.dumps(valid))
    wrong_scale_metadata["x_axis_scale"] = "log"
    invalid_payloads.append(wrong_scale_metadata)

    failed_with_bad_data = json.loads(json.dumps(shortened_signal))
    failed_with_bad_data.update(
        success=False,
        error=_structured_error(file_path="circuits/amp.cir").to_dict(),
    )
    invalid_payloads.append(failed_with_bad_data)

    for payload in invalid_payloads:
        result_file.write_text(json.dumps(payload), encoding="utf-8")
        assert repository.load(str(tmp_path), handle).success is False

    nonstandard = json.loads(json.dumps(valid))
    nonstandard["data"]["signals"]["V(out)"][0] = "__NAN__"
    encoded = json.dumps(nonstandard).replace('"__NAN__"', "NaN")
    result_file.write_text(encoded, encoding="utf-8")
    assert repository.load(str(tmp_path), handle).success is False

    explicit_gap = json.loads(json.dumps(valid))
    explicit_gap["data"]["signals"]["V(out)"] = [None, 1.0]
    result_file.write_text(json.dumps(explicit_gap), encoding="utf-8")
    loaded = repository.load(str(tmp_path), handle)
    assert loaded.success is False
    assert loaded.error_code == LoadErrorCode.PARSE_ERROR


@pytest.mark.parametrize(
    ("signal_types", "message"),
    [
        ({}, "exactly match"),
        ({"V(out)": "voltage", "V(orphan)": "voltage"}, "orphaned"),
        ({"v(out)": "voltage"}, "exactly match"),
        ({"V(out)": "Voltage"}, "exactly one of"),
        ({"V(out)": "current"}, "must be 'voltage'"),
        ({"V(out)": True}, "values must be strings"),
    ],
)
def test_result_schema_rejects_missing_or_contradictory_signal_types(
    signal_types: dict,
    message: str,
):
    payload = _result().to_dict()
    payload["data"]["signal_types"] = signal_types
    with pytest.raises(ValueError, match=message):
        SimulationResult.from_dict(payload)


def test_result_schema_rejects_lowercase_voltage_signal_alias():
    lowercase_alias = _result().to_dict()
    lowercase_alias["data"]["signals"] = {"v(out)": [0.0, 1.0]}
    lowercase_alias["data"]["signal_types"] = {"v(out)": "voltage"}
    with pytest.raises(ValueError, match="canonical 'V\\('"):
        SimulationResult.from_dict(lowercase_alias)


def test_result_and_data_schema_reject_deleted_or_unknown_fields():
    valid = _result().to_dict()
    for field_name in (
        "analysis_info",
        "x_axis_kind",
        "x_axis_label",
        "x_axis_scale",
        "requested_x_range",
        "actual_x_range",
        "future_guess",
    ):
        payload = json.loads(json.dumps(valid))
        payload[field_name] = None
        with pytest.raises(ValueError, match="fields must exactly match schema"):
            SimulationResult.from_dict(payload)

    for field_name in ("op_result", "sweep_name", "future_guess"):
        payload = json.loads(json.dumps(valid))
        payload["data"][field_name] = {}
        with pytest.raises(ValueError, match="fields must exactly match schema"):
            SimulationResult.from_dict(payload)

    missing_data_field = json.loads(json.dumps(valid))
    missing_data_field["data"].pop("signal_types")
    with pytest.raises(ValueError, match="missing=.*signal_types"):
        SimulationResult.from_dict(missing_data_field)


def test_noise_totals_are_exact_optional_noise_only_scalars():
    result = SimulationResult(
        executor="spice",
        file_path="circuits/noise.cir",
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
        timestamp="2026-08-23T12:00:00Z",
        analysis_command=".noise V(out) V1 lin 2 1 2",
    )
    payload = result.to_dict()
    assert payload["data"]["noise_totals"] == {
        "output_rms": 3e-9,
        "input_referred_rms": 1.5e-9,
    }
    restored = SimulationResult.from_dict(payload)
    assert restored.data is not None
    assert restored.data.noise_totals == NoiseTotals(3e-9, 1.5e-9)

    invalid_totals = [
        {"output_rms": True, "input_referred_rms": 1e-9},
        {"output_rms": "3e-9", "input_referred_rms": 1e-9},
        {"output_rms": -1.0, "input_referred_rms": 1e-9},
        {"output_rms": float("inf"), "input_referred_rms": 1e-9},
        {"output_rms": 3e-9},
        {
            "output_rms": 3e-9,
            "input_referred_rms": 1e-9,
            "unit": "V",
        },
    ]
    for invalid in invalid_totals:
        broken = json.loads(json.dumps(payload))
        broken["data"]["noise_totals"] = invalid
        with pytest.raises(ValueError):
            SimulationResult.from_dict(broken)

    non_noise = _result().to_dict()
    non_noise["data"]["noise_totals"] = {
        "output_rms": 3e-9,
        "input_referred_rms": 1e-9,
    }
    with pytest.raises(ValueError, match="only valid for NOISE"):
        SimulationResult.from_dict(non_noise)

    for missing_signal in ("onoise_spectrum", "inoise_spectrum"):
        broken = json.loads(json.dumps(payload))
        broken["data"]["signals"].pop(missing_signal)
        broken["data"]["signal_types"].pop(missing_signal)
        with pytest.raises(ValueError, match="exactly the two canonical"):
            SimulationResult.from_dict(broken)

    wrong_semantics = json.loads(json.dumps(payload))
    wrong_semantics["data"]["signal_types"]["onoise_spectrum"] = "current"
    with pytest.raises(ValueError, match="derived from analysis_command"):
        SimulationResult.from_dict(wrong_semantics)

    extra_signal = json.loads(json.dumps(payload))
    extra_signal["data"]["signals"]["V(fake)"] = [3.0, 4.0]
    extra_signal["data"]["signal_types"]["V(fake)"] = "voltage"
    with pytest.raises(ValueError, match="exactly the two canonical"):
        SimulationResult.from_dict(extra_signal)

    invalid_current_output = json.loads(json.dumps(payload))
    invalid_current_output["analysis_command"] = (
        ".noise I(Vsense) V1 lin 2 1 2"
    )
    with pytest.raises(ValueError, match="NOISE output operand"):
        SimulationResult.from_dict(invalid_current_output)

    for malformed_output in (
        "V(out,)",
        "V(,ref)",
        "V(out,ref,extra)",
        "V(out,,ref)",
        "V(out(foo))",
        "V(out{foo})",
        "V(out ref)",
        "V(out=ref)",
        "V(out;ref)",
    ):
        malformed = json.loads(json.dumps(payload))
        malformed["analysis_command"] = (
            f".noise {malformed_output} V1 lin 2 1 2"
        )
        with pytest.raises(ValueError, match="canonical node names"):
            SimulationResult.from_dict(malformed)

    differential_voltage_current_input = json.loads(json.dumps(payload))
    differential_voltage_current_input["analysis_command"] = (
        ".noise V(out,ref) IIN lin 2 1 2"
    )
    differential_voltage_current_input["data"]["signal_types"][
        "inoise_spectrum"
    ] = "current"
    assert (
        SimulationResult.from_dict(differential_voltage_current_input).data
        is not None
    )

    no_multi_point_totals = json.loads(json.dumps(payload))
    no_multi_point_totals["data"]["noise_totals"] = None
    with pytest.raises(ValueError, match="requires integrated noise_totals"):
        SimulationResult.from_dict(no_multi_point_totals)

    single_point = json.loads(json.dumps(payload))
    single_point["analysis_command"] = ".noise V(out) V1 lin 1 1 2"
    single_point["data"]["frequency"] = [1.0]
    for signal_name in ("onoise_spectrum", "inoise_spectrum"):
        single_point["data"]["signals"][signal_name] = [1e-9]
    single_point["data"]["noise_totals"] = None
    assert SimulationResult.from_dict(single_point).data.noise_totals is None

    for invalid_command in (
        ".noise gain V1 lin 2 1 2",
        ".noise V(out) X1 lin 2 1 2",
        ".noise V(out) V=source lin 2 1 2",
    ):
        broken = json.loads(json.dumps(payload))
        broken["analysis_command"] = invalid_command
        with pytest.raises(ValueError, match="NOISE (output operand|input source)"):
            SimulationResult.from_dict(broken)


def test_result_schema_rejects_noncanonical_identity_and_scalar_types():
    valid = _result().to_dict()
    for field_name, invalid_value in (
        ("executor", "fake"),
        ("executor", "SPICE"),
        ("analysis_type", "TRAN"),
        ("analysis_type", "tran "),
        ("analysis_type", "unknown"),
        ("duration_seconds", True),
        ("duration_seconds", "0.5"),
    ):
        payload = dict(valid)
        payload[field_name] = invalid_value
        with pytest.raises(ValueError):
            SimulationResult.from_dict(payload)

    for invalid_duration in (True, "0.5", -1.0, float("inf")):
        runtime = _result()
        runtime.duration_seconds = invalid_duration
        with pytest.raises(ValueError, match="duration_seconds"):
            runtime.to_dict()

    failed = SimulationResult(
        executor="unknown",
        file_path="circuits/unavailable.cir",
        analysis_type="unknown",
        success=False,
        error=_structured_error(
            "executor unavailable",
            file_path="circuits/unavailable.cir",
        ),
        timestamp="2026-08-23T12:00:00Z",
    ).to_dict()
    assert SimulationResult.from_dict(failed).executor == "unknown"


def test_failed_result_schema_requires_one_structured_diagnostic_only():
    failed = SimulationResult(
        executor="spice",
        file_path="circuits/amp.cir",
        analysis_type="tran",
        success=False,
        error=_structured_error(file_path="circuits/amp.cir"),
        timestamp="2026-08-23T12:00:00Z",
    ).to_dict()
    assert SimulationResult.from_dict(failed).success is False

    legacy_string = dict(failed, error="simulation failed")
    with pytest.raises(ValueError, match="structured SimulationError"):
        SimulationResult.from_dict(legacy_string)

    partial_data = dict(failed, data=_result().to_dict()["data"])
    with pytest.raises(ValueError, match="partial simulation data"):
        SimulationResult.from_dict(partial_data)

    partial_measurements = dict(
        failed,
        measurements=[
            MeasureResult(
                name="gain",
                value=1.0,
                statement=".measure tran gain param='1'",
            ).to_dict()
        ],
    )
    with pytest.raises(ValueError, match="must not contain measurements"):
        SimulationResult.from_dict(partial_measurements)

    runtime_legacy = SimulationResult(
        executor="spice",
        file_path="circuits/amp.cir",
        analysis_type="tran",
        success=False,
        error="simulation failed",
        timestamp="2026-08-23T12:00:00Z",
    )
    with pytest.raises(ValueError, match="structured SimulationError"):
        runtime_legacy.to_dict()


def test_complex_signal_schema_requires_exact_component_fields():
    result = _result()
    result.analysis_type = "ac"
    result.analysis_command = ".ac lin 2 1 10"
    result.data = SimulationData(
        frequency=np.array([1.0, 10.0]),
        signals={"V(out)": np.array([1 + 2j, 3 + 4j])},
        signal_types={"V(out)": "voltage"},
    )
    valid = result.to_dict()
    for mutation in ("missing", "unknown"):
        payload = json.loads(json.dumps(valid))
        complex_payload = payload["data"]["signals"]["V(out)"]
        if mutation == "missing":
            complex_payload.pop("imag")
        else:
            complex_payload["legacy_phase"] = [0.0, 0.0]
        with pytest.raises(ValueError, match="Complex signal fields"):
            SimulationResult.from_dict(payload)


def test_signal_numeric_kind_is_strictly_bound_to_analysis_type():
    tran = _result().to_dict()
    tran_complex = json.loads(json.dumps(tran))
    tran_complex["data"]["signals"]["V(out)"] = _complex_vector([0.0, 1.0])
    with pytest.raises(ValueError, match="TRAN signal.*real samples"):
        SimulationResult.from_dict(tran_complex)

    ac = json.loads(json.dumps(tran))
    ac.update(
        analysis_type="ac",
        analysis_command=".ac lin 2 1 2",
        data={
            "frequency": [1.0, 2.0],
            "time": None,
            "sweep": None,
            "signals": {"V(out)": _complex_vector([1 + 2j, 0.5 - 1j])},
            "signal_types": {"V(out)": "voltage"},
            "noise_totals": None,
        },
    )
    assert SimulationResult.from_dict(ac).data is not None
    ac_real = json.loads(json.dumps(ac))
    ac_real["data"]["signals"]["V(out)"] = [1.0, 0.5]
    with pytest.raises(ValueError, match="AC signal.*complex samples"):
        SimulationResult.from_dict(ac_real)

    real_only_payloads = [
        (
            "dc",
            ".dc V1 0 1 1",
            {
                "frequency": None,
                "time": None,
                "sweep": [0.0, 1.0],
                "signals": {"V(out)": [0.0, 1.0]},
                "signal_types": {"V(out)": "voltage"},
                "noise_totals": None,
            },
            "V(out)",
        ),
        (
            "op",
            ".op",
            {
                "frequency": None,
                "time": None,
                "sweep": None,
                "signals": {"@m1[gm]": [1e-3]},
                "signal_types": {"@m1[gm]": "other"},
                "noise_totals": None,
            },
            "@m1[gm]",
        ),
        (
            "noise",
            ".noise V(out) V1 lin 2 1 2",
            {
                "frequency": [1.0, 2.0],
                "time": None,
                "sweep": None,
                "signals": {
                    "onoise_spectrum": [1e-9, 2e-9],
                    "inoise_spectrum": [0.5e-9, 1e-9],
                },
                "signal_types": {
                    "onoise_spectrum": "voltage",
                    "inoise_spectrum": "voltage",
                },
                "noise_totals": {
                    "output_rms": 3e-9,
                    "input_referred_rms": 1.5e-9,
                },
            },
            "onoise_spectrum",
        ),
    ]
    for analysis_type, command, sim_data, attacked_signal in real_only_payloads:
        valid = json.loads(json.dumps(tran))
        valid.update(
            analysis_type=analysis_type,
            analysis_command=command,
            data=sim_data,
        )
        assert SimulationResult.from_dict(valid).data is not None
        attacked = json.loads(json.dumps(valid))
        real_values = attacked["data"]["signals"][attacked_signal]
        attacked["data"]["signals"][attacked_signal] = _complex_vector(
            real_values
        )
        with pytest.raises(ValueError, match="signal.*real samples"):
            SimulationResult.from_dict(attacked)


@pytest.mark.parametrize("suffix", ["_mag", "_phase", "_real", "_imag"])
def test_schema_rejects_persisted_virtual_complex_components(
    suffix: str,
):
    payload = _result().to_dict()
    payload.update(
        analysis_type="ac",
        analysis_command=".ac lin 2 1 2",
        data={
            "frequency": [1.0, 2.0],
            "time": None,
            "sweep": None,
            "signals": {
                f"V(out){suffix}": _complex_vector([1 + 1j, 0.5 - 1j])
            },
            "signal_types": {f"V(out){suffix}": "voltage"},
            "noise_totals": None,
        },
    )
    with pytest.raises(ValueError, match="presentation-only component"):
        SimulationResult.from_dict(payload)

    legal_node_suffix = json.loads(json.dumps(payload))
    legal_node_suffix["data"]["signals"] = {
        "V(out_mag)": _complex_vector([1 + 1j, 0.5 - 1j])
    }
    legal_node_suffix["data"]["signal_types"] = {
        "V(out_mag)": "voltage"
    }
    assert SimulationResult.from_dict(legal_node_suffix).data is not None


@pytest.mark.parametrize(
    ("analysis_type", "analysis_command"),
    [
        ("ac", ".ac lin {points} 1 2"),
        ("dc", ".dc V1 0 1 {step}"),
        ("tran", ".tran {step} 1m"),
        ("noise", ".noise V(out) V1 dec 10 {start} 1k"),
        ("dc", ".dc V1 0 1 1e999"),
    ],
)
def test_schema_rejects_nonliteral_or_nonfinite_analysis_operands(
    analysis_type: str,
    analysis_command: str,
):
    payload = _result().to_dict()
    payload["analysis_type"] = analysis_type
    payload["analysis_command"] = analysis_command
    with pytest.raises(ValueError, match="finite literal"):
        SimulationResult.from_dict(payload)


def test_measurement_schema_rejects_repairs_duplicates_and_invalid_values():
    valid_measurement = MeasureResult(
        name="gain",
        value=2.0,
        status=MeasureStatus.OK,
        statement=".measure tran gain param='2'",
    ).to_dict()
    base = _result().to_dict()
    base["measurements"] = [valid_measurement]
    restored = SimulationResult.from_dict(base)
    assert restored.measurements is not None
    assert restored.measurements[0].name == "gain"

    invalid_payloads = []

    empty_name = json.loads(json.dumps(base))
    empty_name["measurements"][0]["name"] = ""
    invalid_payloads.append(empty_name)

    duplicate = json.loads(json.dumps(base))
    duplicate["measurements"].append(
        dict(duplicate["measurements"][0], name="GAIN")
    )
    invalid_payloads.append(duplicate)

    unknown_status = json.loads(json.dumps(base))
    unknown_status["measurements"][0]["status"] = "UNKNOWN"
    invalid_payloads.append(unknown_status)

    wrong_value_type = json.loads(json.dumps(base))
    wrong_value_type["measurements"][0]["value"] = "2.0"
    invalid_payloads.append(wrong_value_type)

    failed_with_value = json.loads(json.dumps(base))
    failed_with_value["measurements"][0].update(
        status="FAILED",
        value=2.0,
        error_message="ngspice measure failed",
    )
    invalid_payloads.append(failed_with_value)

    failed_without_reason = json.loads(json.dumps(base))
    failed_without_reason["measurements"][0].update(
        status="FAILED",
        value=None,
        error_message="",
    )
    invalid_payloads.append(failed_without_reason)

    unknown_field = json.loads(json.dumps(base))
    unknown_field["measurements"][0]["unit"] = "V/V"
    invalid_payloads.append(unknown_field)

    missing_field = json.loads(json.dumps(base))
    missing_field["measurements"][0].pop("raw_output")
    invalid_payloads.append(missing_field)

    for invalid_statement in (
        "",
        ".measure ac gain param='2'",
        ".measure tran other param='2'",
        ".measure tran gain",
        ".measure tran gain param='2'\n.measure tran other param='3'",
    ):
        invalid_statement_payload = json.loads(json.dumps(base))
        invalid_statement_payload["measurements"][0]["statement"] = invalid_statement
        invalid_payloads.append(invalid_statement_payload)

    for payload in invalid_payloads:
        with pytest.raises(ValueError):
            SimulationResult.from_dict(payload)

    nonfinite = json.loads(json.dumps(base))
    nonfinite["measurements"][0]["value"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        SimulationResult.from_dict(nonfinite)

    runtime_duplicate = _result()
    runtime_duplicate.measurements = [
        MeasureResult(
            name="gain",
            value=1.0,
            statement=".measure tran gain param='1'",
        ),
        MeasureResult(
            name="GAIN",
            value=2.0,
            statement=".measure tran GAIN param='2'",
        ),
    ]
    with pytest.raises(ValueError, match="duplicate"):
        runtime_duplicate.to_dict()

    op_payload = json.loads(json.dumps(base))
    op_payload.update(
        analysis_type="op",
        analysis_command=".op",
        data={
            "frequency": None,
            "time": None,
            "sweep": None,
            "signals": {"V(out)": [1.0]},
            "signal_types": {"V(out)": "voltage"},
            "noise_totals": None,
        },
    )
    with pytest.raises(ValueError, match="must not contain top-level"):
        SimulationResult.from_dict(op_payload)


def test_analysis_command_must_match_type_and_numeric_axis_range(tmp_path: Path):
    repository = SimulationResultRepository()
    bundle = tmp_path / "simulation_results" / "ac" / "run"
    bundle.mkdir(parents=True)
    result_path = bundle / "result.json"
    handle = "simulation_results/ac/run/result.json"
    valid = _result().to_dict()
    valid.update(
        analysis_type="ac",
        analysis_command=".ac lin 2 1 10",
        data={
            "frequency": [1.0, 10.0],
            "time": None,
            "sweep": None,
            "signals": {"V(out)": _complex_vector([1.0, 0.5])},
            "signal_types": {"V(out)": "voltage"},
            "noise_totals": None,
        },
    )

    wrong_type = json.loads(json.dumps(valid))
    wrong_type["analysis_command"] = ".tran 1 10"
    wrong_range = json.loads(json.dumps(valid))
    wrong_range["analysis_command"] = ".ac lin 2 1 1Meg"
    for payload in (wrong_type, wrong_range):
        result_path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = repository.load(str(tmp_path), handle)
        assert loaded.success is False
        assert loaded.error_code == LoadErrorCode.PARSE_ERROR


@pytest.mark.parametrize(
    ("analysis_type", "analysis_command", "axis"),
    [
        (
            "ac",
            ".ac dec 3 1 20",
            np.geomspace(1.0, 20.0, 4),
        ),
        (
            "ac",
            ".ac oct 3 1 10",
            np.power(2.0, np.arange(10, dtype=float) / 3.0),
        ),
        (
            "noise",
            ".noise V(out) V1 dec 3 1 20",
            np.power(10.0, np.arange(4, dtype=float) / 3.0),
        ),
        (
            "noise",
            ".noise V(out) V1 oct 3 1 10",
            np.power(2.0, np.arange(10, dtype=float) / 3.0),
        ),
        (
            "noise",
            ".noise V(out) V1 lin 4 1 10",
            np.array([1.0, 4.0, 7.0, 10.0]),
        ),
        ("ac", ".ac lin 1 1 10", np.array([1.0])),
        ("ac", ".ac oct 3 1 1.1", np.array([1.0])),
        (
            "noise",
            ".noise V(out) V1 dec 3 1 2",
            np.array([1.0]),
        ),
    ],
)
def test_frequency_schema_matches_ngspice_generated_grid(
    analysis_type: str,
    analysis_command: str,
    axis: np.ndarray,
):
    payload = _result().to_dict()
    if analysis_type == "noise":
        signals = {
            "onoise_spectrum": np.ones(len(axis)).tolist(),
            "inoise_spectrum": np.ones(len(axis)).tolist(),
        }
        signal_types = {
            "onoise_spectrum": "voltage",
            "inoise_spectrum": "voltage",
        }
        noise_totals = (
            None
            if len(axis) == 1
            else {"output_rms": 1e-9, "input_referred_rms": 1e-9}
        )
    else:
        signals = {"V(out)": _complex_vector(np.ones(len(axis)))}
        signal_types = {"V(out)": "voltage"}
        noise_totals = None
    payload.update(
        analysis_type=analysis_type,
        analysis_command=analysis_command,
        data={
            "frequency": axis.tolist(),
            "time": None,
            "sweep": None,
            "signals": signals,
            "signal_types": signal_types,
            "noise_totals": noise_totals,
        },
    )
    restored = SimulationResult.from_dict(payload)
    assert restored.data is not None
    assert restored.data.frequency == pytest.approx(axis)

    if len(axis) > 1:
        truncated = json.loads(json.dumps(payload))
        truncated["data"]["frequency"] = truncated["data"]["frequency"][:-1]
        for signal_name in truncated["data"]["signals"]:
            signal_payload = truncated["data"]["signals"][signal_name]
            if isinstance(signal_payload, dict):
                signal_payload["real"] = signal_payload["real"][:-1]
                signal_payload["imag"] = signal_payload["imag"][:-1]
            else:
                truncated["data"]["signals"][signal_name] = signal_payload[:-1]
        with pytest.raises(ValueError, match="complete|point_count"):
            SimulationResult.from_dict(truncated)


def test_ac_dec_rejects_a_range_that_generates_no_interval():
    payload = _result().to_dict()
    payload.update(
        analysis_type="ac",
        analysis_command=".ac dec 3 1 2",
        data={
            "frequency": [1.0],
            "time": None,
            "sweep": None,
            "signals": {"V(out)": _complex_vector([1.0])},
            "signal_types": {"V(out)": "voltage"},
            "noise_totals": None,
        },
    )
    with pytest.raises(ValueError, match="at least one generated interval"):
        SimulationResult.from_dict(payload)


@pytest.mark.parametrize(
    ("analysis_command", "axis"),
    [
        (".dc V1 0 1 .3", np.array([0.0, 0.3, 0.6, 0.9])),
        (".dc V1 1 0 -.3", np.array([1.0, 0.7, 0.4, 0.1])),
        (
            ".dc V1 0 1 .3 V2 0 1 .6",
            np.tile(np.array([0.0, 0.3, 0.6, 0.9]), 2),
        ),
    ],
)
def test_dc_schema_matches_ngspice_fixed_step_grid(
    analysis_command: str,
    axis: np.ndarray,
):
    payload = _result().to_dict()
    payload.update(
        analysis_type="dc",
        analysis_command=analysis_command,
        data={
            "frequency": None,
            "time": None,
            "sweep": axis.tolist(),
            "signals": {"V(out)": np.ones(len(axis)).tolist()},
            "signal_types": {"V(out)": "voltage"},
            "noise_totals": None,
        },
    )
    restored = SimulationResult.from_dict(payload)
    assert restored.data is not None
    assert restored.data.sweep == pytest.approx(axis)

    truncated = json.loads(json.dumps(payload))
    truncated["data"]["sweep"] = truncated["data"]["sweep"][:-1]
    truncated["data"]["signals"]["V(out)"] = truncated["data"]["signals"]["V(out)"][:-1]
    with pytest.raises(ValueError, match="complete|length"):
        SimulationResult.from_dict(truncated)


def test_axis_grid_tolerance_scales_with_physical_magnitude_and_step():
    transient = _result().to_dict()
    transient["analysis_command"] = ".tran .1p 1p"
    transient["data"]["time"] = [0.0, 1e-12]
    assert SimulationResult.from_dict(transient).data is not None

    wrong_picosecond_stop = json.loads(json.dumps(transient))
    wrong_picosecond_stop["data"]["time"] = [0.0, 5e-11]
    with pytest.raises(ValueError, match="axis stop"):
        SimulationResult.from_dict(wrong_picosecond_stop)

    tiny_dc = _result().to_dict()
    tiny_dc.update(
        analysis_type="dc",
        analysis_command=".dc V1 0 1n .5n",
        data={
            "frequency": None,
            "time": None,
            "sweep": [0.0, 5e-10, 1e-9],
            "signals": {"V(out)": [0.0, 0.5, 1.0]},
            "signal_types": {"V(out)": "voltage"},
            "noise_totals": None,
        },
    )
    assert SimulationResult.from_dict(tiny_dc).data is not None

    wrong_nanovolt_grid = json.loads(json.dumps(tiny_dc))
    wrong_nanovolt_grid["data"]["sweep"] = [0.0, 5.9e-10, 1.09e-9]
    with pytest.raises(ValueError, match="complete primary sweep grid"):
        SimulationResult.from_dict(wrong_nanovolt_grid)

    accumulated = np.arange(101, dtype=float) * 0.1
    accumulated[-1] = 9.99999999999998
    large_dc = json.loads(json.dumps(tiny_dc))
    large_dc["analysis_command"] = ".dc V1 0 10 .1"
    large_dc["data"]["sweep"] = accumulated.tolist()
    large_dc["data"]["signals"]["V(out)"] = np.ones(len(accumulated)).tolist()
    assert SimulationResult.from_dict(large_dc).data is not None


@pytest.mark.parametrize(
    ("analysis_command", "first_time"),
    [
        (".tran 1u 2u 1u", 1.0056e-6),
        (".tran 1u 2u uic", 2e-10),
        (".tran 1u 2u 0 2u uic", 2e-10),
    ],
)
def test_tran_explicit_start_and_uic_accept_native_first_step_semantics(
    analysis_command: str,
    first_time: float,
):
    payload = _result().to_dict()
    payload["analysis_command"] = analysis_command
    payload["data"]["time"] = [first_time, 2e-6]
    assert SimulationResult.from_dict(payload).data is not None

    default_start = json.loads(json.dumps(payload))
    default_start["analysis_command"] = ".tran 1u 2u"
    with pytest.raises(ValueError, match="axis start"):
        SimulationResult.from_dict(default_start)


def test_tran_explicit_start_rejects_a_first_point_beyond_one_output_step():
    payload = _result().to_dict()
    payload["analysis_command"] = ".tran 1u 5u 1u"
    payload["data"]["time"] = [2.5e-6, 5e-6]
    with pytest.raises(ValueError, match="axis start"):
        SimulationResult.from_dict(payload)


def test_analysis_axes_reject_nonphysical_frequency_and_time_ordering():
    valid = _result().to_dict()
    for invalid_time in ([0.0, 0.0], [0.0, -1e-3], [1e-3, 0.0]):
        payload = json.loads(json.dumps(valid))
        payload["data"]["time"] = invalid_time
        with pytest.raises(ValueError, match="strictly increasing|non-negative"):
            SimulationResult.from_dict(payload)

    for invalid_frequency in ([0.0, 10.0], [1.0, 1.0], [10.0, 1.0]):
        payload = json.loads(json.dumps(valid))
        payload.update(
            analysis_type="ac",
            analysis_command=".ac dec 10 1 10",
        )
        payload["data"].update(
            frequency=invalid_frequency,
            time=None,
        )
        with pytest.raises(ValueError, match="positive and strictly increasing"):
            SimulationResult.from_dict(payload)


@pytest.mark.parametrize(
    ("analysis_type", "analysis_command", "expected_point_field"),
    [
        ("ac", ".ac lin 3 10 30", "point_count"),
        ("noise", ".noise v(out) V1 lin 3 10 30", "point_count"),
        ("ac", ".ac oct 5 10 10k", "points_per_octave"),
        ("noise", ".noise v(out) V1 dec 8 10 10k", "points_per_decade"),
    ],
)
def test_frequency_result_scale_and_parameters_share_command_authority(
    analysis_type: str,
    analysis_command: str,
    expected_point_field: str,
):
    if " lin " in f" {analysis_command.lower()} ":
        frequency = np.array([10.0, 20.0, 30.0])
    elif " oct " in f" {analysis_command.lower()} ":
        interval_count = int(np.floor(5 * np.log2(10_000 / 10)))
        frequency = 10 * np.power(
            2.0,
            np.arange(interval_count + 1, dtype=float) / 5,
        )
    else:
        interval_count = int(np.floor(8 * np.log10(10_000 / 10)))
        frequency = 10 * np.power(
            10.0,
            np.arange(interval_count + 1, dtype=float) / 8,
        )
    if analysis_type == "noise":
        signals = {
            "onoise_spectrum": np.ones(len(frequency)),
            "inoise_spectrum": np.ones(len(frequency)),
        }
        signal_types = {
            "onoise_spectrum": "voltage",
            "inoise_spectrum": "voltage",
        }
        noise_totals = NoiseTotals(1e-9, 1e-9)
    else:
        signals = {"V(out)": np.ones(len(frequency), dtype=complex)}
        signal_types = {"V(out)": "voltage"}
        noise_totals = None
    result = create_success_result(
        executor="spice",
        file_path="circuits/frequency.cir",
        analysis_type=analysis_type,
        data=SimulationData(
            frequency=frequency,
            signals=signals,
            signal_types=signal_types,
            noise_totals=noise_totals,
        ),
        source_digest=_SOURCE_DIGEST,
        analysis_command=analysis_command,
    )

    expected_scale = "linear" if " lin " in f" {analysis_command.lower()} " else "log"
    assert result.x_axis_scale == expected_scale
    assert result.analysis_info["parameters"][expected_point_field] in {"3", "5", "8"}
    assert "analysis_info" not in result.to_dict()

    loaded = SimulationResult.from_dict(result.to_dict())
    assert loaded.x_axis_scale == expected_scale
    assert expected_point_field in loaded.analysis_info["parameters"]


def test_analysis_info_is_a_fresh_read_only_view_with_complete_nested_dc_metadata():
    sweep = np.tile(np.array([0.0, 0.05]), 5)
    result = create_success_result(
        executor="spice",
        file_path="TestCircuit/dc_analysis/04_bjt_output_characteristics.cir",
        analysis_type="dc",
        data=SimulationData(
            sweep=sweep,
            signals={"V(c)": np.linspace(0.0, 1e-3, len(sweep))},
            signal_types={"V(c)": "voltage"},
        ),
        source_digest=_SOURCE_DIGEST,
        analysis_command=".dc Vce 0 0.05 0.05 Ib 10u 50u 10u",
    )

    assert result.analysis_info["parameters"] == {
        "source_name": "Vce",
        "start_value": "0",
        "stop_value": "0.05",
        "step": "0.05",
        "second_source_name": "Ib",
        "second_start_value": "10u",
        "second_stop_value": "50u",
        "second_step": "10u",
    }
    first_view = result.analysis_info
    first_view["analysis_type"] = "ac"
    first_view["parameters"].clear()
    assert result.analysis_info["analysis_type"] == "dc"
    assert result.analysis_info["parameters"]["second_source_name"] == "Ib"
    assert result.x_axis_label == "Vce (V)"
    serialized = result.to_dict()
    for field_name in (
        "analysis_info",
        "x_axis_kind",
        "x_axis_label",
        "x_axis_scale",
        "requested_x_range",
        "actual_x_range",
    ):
        assert field_name not in serialized
    assert "sweep_name" not in serialized["data"]
    with pytest.raises(AttributeError):
        result.analysis_info = {"analysis_type": "ac"}
    with pytest.raises(AttributeError):
        result.x_axis_label = "forged"


def test_bundle_persistence_is_all_or_nothing(monkeypatch, tmp_path: Path):
    result = _result()

    def fail_write(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(simulation_artifact_exporter, "write_json", fail_write)
    with pytest.raises(OSError, match="disk full"):
        simulation_artifact_persistence.persist_bundle(str(tmp_path), result)

    results_root = tmp_path / "simulation_results"
    assert list(results_root.rglob("result.json")) == []
    assert list(results_root.rglob("export_manifest.json")) == []
    assert list(results_root.rglob(".__bundle_tmp__*")) == []


def test_bundle_persistence_rejects_any_extra_staged_file(
    monkeypatch,
    tmp_path: Path,
):
    original_write_json = simulation_artifact_exporter.write_json

    def polluted_write_json(path, payload):
        original_write_json(path, payload)
        (Path(path).parent / "unexpected.txt").write_text(
            "not part of the authoritative bundle",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        simulation_artifact_exporter,
        "write_json",
        polluted_write_json,
    )
    with pytest.raises(RuntimeError, match="must contain only result.json"):
        simulation_artifact_persistence.persist_bundle(str(tmp_path), _result())

    assert list((tmp_path / "simulation_results").rglob("result.json")) == []
    assert list((tmp_path / "simulation_results").rglob("unexpected.txt")) == []


def test_bundle_persistence_rejects_circuits_outside_the_current_project(tmp_path: Path):
    external = tmp_path.parent / f"{tmp_path.name}-external.cir"
    external.write_text("* external", encoding="utf-8")

    with pytest.raises(ValueError, match="outside the current project"):
        simulation_artifact_persistence.persist_bundle(
            str(tmp_path),
            _result(file_path=str(external)),
        )

    assert not (tmp_path / "simulation_results").exists()


def test_bad_digest_is_rejected_before_results_tree_is_created(tmp_path: Path):
    result = _result()
    result.source_digest = "not-a-sha256"

    with pytest.raises(ValueError, match="source_digest|SHA-256"):
        simulation_artifact_persistence.persist_bundle(str(tmp_path), result)

    assert not (tmp_path / "simulation_results").exists()


def test_invalid_success_payload_is_rejected_before_results_tree_is_created(
    tmp_path: Path,
):
    result = _result()
    result.data = SimulationData()

    with pytest.raises(ValueError, match="non-empty time axis"):
        simulation_artifact_persistence.persist_bundle(str(tmp_path), result)

    assert not (tmp_path / "simulation_results").exists()


def test_bundle_folder_names_are_cross_platform_safe(tmp_path: Path):
    result = _result(file_path="CON.cir", timestamp="bad<time>|. ")
    root = simulation_artifact_exporter.build_project_export_root(tmp_path, result)
    assert root.parent.name == "_CON"
    assert not any(character in root.name for character in '<>:"/\\|?*')
    assert not root.name.endswith((" ", "."))

    long_a = simulation_artifact_exporter.build_project_export_root(
        tmp_path,
        _result(file_path=f"{'a' * 300}.cir"),
    )
    long_b = simulation_artifact_exporter.build_project_export_root(
        tmp_path,
        _result(file_path=f"{'a' * 299}b.cir"),
    )
    assert len(long_a.parent.name) <= 96
    assert len(long_a.name) <= 96
    assert long_a.parent.name != long_b.parent.name


def test_bundle_commit_retries_a_real_directory_collision(monkeypatch, tmp_path: Path):
    original_rename = Path.rename
    injected = False

    def collide_once(source: Path, destination):
        nonlocal injected
        if not injected:
            injected = True
            Path(destination).mkdir(parents=True)
            raise OSError(errno.ENOTEMPTY, "simulated concurrent commit")
        return original_rename(source, destination)

    monkeypatch.setattr(Path, "rename", collide_once)
    outcome = simulation_artifact_persistence.persist_bundle(str(tmp_path), _result())

    assert injected is True
    assert outcome.export_root.name.endswith("_2")
    assert (outcome.export_root / "result.json").is_file()


def test_repository_resolves_only_existing_circuits_inside_the_project(tmp_path: Path):
    circuit = tmp_path / "circuits" / "amp.cir"
    circuit.parent.mkdir()
    circuit.write_text("* circuit", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.cir"
    outside.write_text("* outside", encoding="utf-8")
    repository = SimulationResultRepository()

    assert repository.resolve_circuit_path(str(tmp_path), "circuits/amp.cir") == circuit
    assert repository.resolve_circuit_path(str(tmp_path), str(outside)) is None
    assert repository.resolve_circuit_path(str(tmp_path), "circuits/missing.cir") is None


def test_committed_bundle_is_one_strict_portable_result_json(tmp_path: Path):
    circuit = tmp_path / "circuits" / "测试.cir"
    circuit.parent.mkdir()
    circuit.write_text("* demo", encoding="utf-8")
    invalid = _result(file_path=str(circuit))
    invalid.data.signals["V(out)"] = np.array([np.nan, np.inf])
    with pytest.raises(ValueError, match="finite"):
        simulation_artifact_persistence.persist_bundle(str(tmp_path), invalid)
    assert not (tmp_path / "simulation_results").exists()

    result = _result(file_path=str(circuit))
    outcome = simulation_artifact_persistence.persist_bundle(str(tmp_path), result)
    assert not outcome.export_root.name.startswith(".__bundle_tmp__")

    result_payload = json.loads((outcome.export_root / "result.json").read_text(encoding="utf-8"))
    assert result_payload["schema_version"] == RESULT_SCHEMA_VERSION
    assert result_payload["file_path"] == "circuits/测试.cir"
    assert result_payload["source_digest"] == _SOURCE_DIGEST
    assert result_payload["data"]["signals"]["V(out)"] == [0.0, 1.0]

    assert {
        path.relative_to(outcome.export_root).as_posix()
        for path in outcome.export_root.rglob("*")
        if path.is_file()
    } == {"result.json"}

    loaded = SimulationResultRepository().load(str(tmp_path), outcome.result_path)
    assert loaded.success is True
    assert loaded.data is not None
    assert loaded.data.data.signals["V(out)"] == pytest.approx([0.0, 1.0])


def test_failed_simulation_is_persisted_and_loaded_as_failed_not_false_success(tmp_path: Path):
    absolute_circuit = tmp_path / "circuits" / "broken.cir"
    result = SimulationResult(
        executor="spice",
        file_path=str(absolute_circuit),
        analysis_type="tran",
        success=False,
        data=None,
        error=SimulationError(
            type=SimulationErrorType.NGSPICE_CRASH,
            severity=ErrorSeverity.HIGH,
            message="singular matrix",
            file_path=str(absolute_circuit),
        ),
        raw_output="Error: singular matrix",
        timestamp="2026-08-23T12:00:00Z",
    )
    outcome = simulation_artifact_persistence.persist_bundle(str(tmp_path), result)
    loaded = SimulationResultRepository().load(str(tmp_path), outcome.result_path)

    assert loaded.success is True  # the file load succeeded
    assert loaded.data is not None
    assert loaded.data.success is False  # the simulation did not
    assert loaded.data.data is None
    assert loaded.data.file_path == "circuits/broken.cir"
    assert loaded.data.error.file_path == "circuits/broken.cir"
    assert loaded.data.source_digest is None
    assert result.error.file_path == str(absolute_circuit)
    assert list(outcome.export_root.iterdir()) == [outcome.export_root / "result.json"]


def test_repository_orders_timezone_aware_timestamps_chronologically(tmp_path: Path):
    # 11:00Z is newer than 18:00+08 (10:00Z), but lexical ordering says the opposite.
    first = _result(timestamp="2026-08-23T18:00:00+08:00").to_dict()
    second = _result(timestamp="2026-08-23T11:00:00Z").to_dict()
    for run, payload in (("a", first), ("b", second)):
        bundle = tmp_path / "simulation_results" / "amp" / run
        bundle.mkdir(parents=True)
        (bundle / "result.json").write_text(json.dumps(payload), encoding="utf-8")

    groups = SimulationResultRepository().list_by_circuit(
        str(tmp_path),
        per_circuit_limit=2,
    )
    assert len(groups) == 1
    assert [Path(item.result_path).parent.name for item in groups[0].results] == [
        "b",
        "a",
    ]


def test_repository_skips_one_unsortable_timestamp_without_breaking_history(
    tmp_path: Path,
):
    valid = _result(timestamp="2026-08-23T11:00:00Z").to_dict()
    out_of_range_in_utc = _result(
        timestamp="9999-12-31T23:59:59-14:00"
    ).to_dict()
    for run, payload in (("valid", valid), ("unsortable", out_of_range_in_utc)):
        bundle = tmp_path / "simulation_results" / "amp" / run
        bundle.mkdir(parents=True)
        (bundle / "result.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    groups = SimulationResultRepository().list_by_circuit(str(tmp_path))

    assert len(groups) == 1
    assert [Path(item.result_path).parent.name for item in groups[0].results] == [
        "valid"
    ]


def test_png_metadata_is_unicode_safe_replaced_and_corruption_safe(tmp_path: Path):
    path = tmp_path / "chart.png"
    path.write_bytes(_minimal_png())

    assert inject_png_itxt_chunks(path, {"file_path": "电路/旧.cir", "artifact_type": "chart"})
    assert inject_png_itxt_chunks(path, {"file_path": "电路/新.cir"})
    assert read_png_itxt_chunks(path) == {
        "file_path": "电路/新.cir",
        "artifact_type": "chart",
    }
    assert path.read_bytes().count(b"file_path") == 1

    original = path.read_bytes()
    broken = bytearray(original)
    broken[-1] ^= 0x01
    path.write_bytes(broken)
    assert inject_png_itxt_chunks(path, {"file_path": "must-not-write"}) is False
    assert path.read_bytes() == broken
    with pytest.raises(ValueError):
        read_png_itxt_chunks(path)


def test_metric_formatting_uses_prefix_on_unit_not_on_number_token():
    bandwidth_result = _result()
    bandwidth_result.analysis_type = "ac"
    bandwidth_result.analysis_command = ".ac lin 2 1 1500"
    bandwidth_result.data = SimulationData(
        frequency=np.array([1.0, 1500.0]),
        signals={"V(out)": np.array([1.0, 0.5])},
        signal_types={"V(out)": "voltage"},
    )
    bandwidth_result.measurements = [
        MeasureResult(
            name="bandwidth",
            value=1_500.0,
            statement=".measure ac bandwidth WHEN VDB(out)=-3",
        )
    ]
    transient_result = _result()
    transient_result.measurements = [
        MeasureResult(
            name="rise_time",
            value=250e-6,
            statement=(
                ".measure tran rise_time TRIG V(out) VAL=0.1 RISE=1 "
                "TARG V(out) VAL=0.9 RISE=1"
            ),
        ),
        MeasureResult(
            name="gain_db",
            value=60.0,
            statement=".measure tran gain_db FIND VDB(out) AT=1m",
        ),
    ]

    rows = [
        *display_metric_builder.build(bandwidth_result),
        *display_metric_builder.build(transient_result),
    ]
    values = {row.name: row.value for row in rows}
    assert values == {
        "bandwidth": "1.5 kHz",
        "rise_time": "250 μs",
        "gain_db": "60 dB",
    }


def test_output_log_does_not_turn_zero_error_summary_into_an_error():
    lines = simulation_output_reader.get_output_log_from_text(
        "0 errors\n0 tests failed\nError: singular matrix"
    )
    assert [line.level for line in lines] == [
        LogLevel.INFO.value,
        LogLevel.INFO.value,
        LogLevel.ERROR.value,
    ]
    long_log = "\n".join([*("ok" for _ in range(10_001)), "Error: late failure"])
    parsed = simulation_output_reader.get_output_log_from_text(long_log)
    assert len(parsed) == 10_002
    assert parsed[-1].level == LogLevel.ERROR.value
    summary = simulation_output_reader.summarize_text(long_log)
    assert summary.total_lines == 10_002
    assert summary.error_count == 1
    assert summary.first_error == "Error: late failure"


def test_output_log_artifact_keeps_every_structured_line(tmp_path: Path):
    result = _result()
    result.raw_output = "\n".join([*("ok" for _ in range(10_001)), "Error: late failure"])
    simulation_artifact_exporter.export_output_log(tmp_path, result)

    payload = json.loads(
        simulation_artifact_exporter.output_log_paths(tmp_path).json_path.read_text(
            encoding="utf-8"
        )
    )
    assert payload["summary"]["total_lines"] == 10_002
    assert len(payload["data"]["lines"]) == 10_002
    assert "raw_output" not in payload["data"]
    assert payload["data"]["lines"][-1]["level"] == LogLevel.ERROR.value


def test_headless_bundle_derives_op_view_from_authoritative_signals(tmp_path: Path):
    payload = build_op_result_payload_from_signals(
        {"V(out)": np.array([1.25]), "I(V1)": np.array([-1e-3])}
    )
    result = SimulationResult(
        executor="spice",
        file_path="circuits/op.cir",
        analysis_type="op",
        success=True,
        source_digest=_SOURCE_DIGEST,
        data=SimulationData(
            signals={"V(out)": np.array([1.25]), "I(V1)": np.array([-1e-3])},
            signal_types={"V(out)": "voltage", "I(V1)": "current"},
        ),
        timestamp="2026-08-23T12:00:00Z",
        analysis_command=".op",
    )

    outcome = simulation_artifact_persistence.persist_bundle(str(tmp_path), result)
    root_payload = json.loads(
        (outcome.export_root / "result.json").read_text(encoding="utf-8")
    )
    assert "op_result" not in root_payload["data"]
    loaded = SimulationResultRepository().load(str(tmp_path), outcome.result_path)
    assert loaded.success is True
    assert loaded.data is not None
    assert loaded.data.data is not None
    assert loaded.data.data.op_result == payload
    with pytest.raises(AttributeError):
        loaded.data.data.op_result = {}
    assert not simulation_artifact_exporter.op_result_paths(outcome.export_root).directory.exists()


def test_op_payload_does_not_guess_undocumented_mos_region_codes_or_take_waveform_first_point():
    payload = build_op_result_payload_from_signals(
        {
            "V(out)": np.array([1.0, 2.0]),
            "@m1[region]": np.array([2.0]),
            "@m1[id]": np.array([1e-3]),
            "I(V1)": np.array([-1e-3]),
        },
    )
    assert payload["nodes"] == []
    assert payload["devices"][0]["operating_region"] == ""
    assert "saturation" not in json.dumps(payload)
    assert payload["branches"][0]["direction_convention"] == (
        "positive_from_positive_to_negative_terminal"
    )


def test_result_schema_rejects_unknown_version_and_nonfinite_signal_values():
    result = _result()
    result.analysis_type = "ac"
    result.analysis_command = ".ac lin 2 1 10"
    result.data = SimulationData(
        frequency=np.array([1.0, 10.0]),
        signals={"V(out)": np.array([1 + 2j, 3 - 4j])},
        signal_types={"V(out)": "voltage"},
    )
    payload = result.to_dict()
    encoded = json.dumps(payload, allow_nan=False)
    restored = SimulationResult.from_dict(json.loads(encoded))
    assert restored.data is not None
    assert restored.data.signals["V(out)"][0] == 1 + 2j
    assert restored.data.signals["V(out)"][1] == 3 - 4j

    null_component = json.loads(encoded)
    null_component["data"]["signals"]["V(out)"]["imag"][1] = None
    with pytest.raises(ValueError, match="null gaps"):
        SimulationResult.from_dict(null_component)

    result.data.signals["V(out)"][1] = complex(np.nan, 1.0)
    with pytest.raises(ValueError, match="finite"):
        result.to_dict()

    payload["schema_version"] = RESULT_SCHEMA_VERSION + 1
    with pytest.raises(ValueError, match="schema_version"):
        SimulationResult.from_dict(payload)


def test_result_schema_requires_explicit_provenance_digest() -> None:
    success_payload = _result().to_dict()
    for invalid_digest in (None, "", "A" * 64, "0" * 63, "g" * 64):
        payload = dict(success_payload, source_digest=invalid_digest)
        with pytest.raises(ValueError, match="source_digest|SHA-256"):
            SimulationResult.from_dict(payload)

    missing_success_digest = dict(success_payload)
    missing_success_digest.pop("source_digest")
    with pytest.raises(ValueError, match="source_digest"):
        SimulationResult.from_dict(missing_success_digest)

    failed = SimulationResult(
        executor="spice",
        file_path="circuits/unreadable.cir",
        analysis_type="tran",
        success=False,
        source_digest=None,
        error=_structured_error(
            "source could not be read",
            file_path="circuits/unreadable.cir",
        ),
        timestamp="2026-08-23T12:00:00Z",
    ).to_dict()
    assert failed["source_digest"] is None
    assert SimulationResult.from_dict(failed).source_digest is None

    missing_failed_digest = dict(failed)
    missing_failed_digest.pop("source_digest")
    with pytest.raises(ValueError, match="source_digest"):
        SimulationResult.from_dict(missing_failed_digest)
