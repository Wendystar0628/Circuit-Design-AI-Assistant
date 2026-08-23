from __future__ import annotations

import logging
import math
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from domain.simulation.executor.ngspice_shared import (
    NgSpiceCancelledError,
    NgSpiceTimeoutError,
    NgSpiceWrapper,
    VectorInfo,
    VectorType,
)
from domain.simulation.executor.spice_executor import SpiceExecutor
from domain.simulation.executor import spice_executor as spice_executor_module
from domain.simulation.models.simulation_error import SimulationErrorType
from domain.simulation.measure.measure_authority import MeasureRequest
from domain.simulation.measure.measure_result import MeasureStatus
from domain.simulation.spice.source_closure import collect_spice_source_closure
from infrastructure.utils.ngspice_config import configure_ngspice


def _native_executor_or_skip(*, timeout_seconds: float = 5) -> SpiceExecutor:
    if not configure_ngspice():
        pytest.skip("ngspice shared library is unavailable")
    executor = SpiceExecutor(timeout_seconds=timeout_seconds)
    if not executor.is_available():
        pytest.skip("ngspice shared library could not be initialized")
    return executor


def _write_netlist(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def _closure_digest(path: Path) -> str:
    return collect_spice_source_closure(path).digest


def test_missing_file_and_missing_analysis_keep_persistable_error_identity(
    tmp_path: Path,
) -> None:
    executor = SpiceExecutor(timeout_seconds=5)

    missing_file = executor.execute(str(tmp_path / "missing.cir"))
    no_analysis = executor.execute(
        str(_write_netlist(tmp_path / "no_analysis.cir", "no analysis\nR1 1 0 1k\n.end\n"))
    )

    assert missing_file.success is False
    assert missing_file.analysis_type == "unknown"
    assert missing_file.error.type is SimulationErrorType.FILE_ACCESS
    assert missing_file.source_digest is None
    assert no_analysis.success is False
    assert no_analysis.analysis_type == "unknown"
    assert no_analysis.error.type is SimulationErrorType.PARAMETER_INVALID
    assert "只能包含一张" in no_analysis.error.message
    assert "0 张" in no_analysis.error.message
    assert no_analysis.source_digest == _closure_digest(tmp_path / "no_analysis.cir")


def test_gb18030_source_uses_editor_codec_with_closure_provenance(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    source = "中文工作点\n* 电阻负载\nV1 in 0 1\nR1 in 0 1k\n.op\n.end\n".encode(
        "gb18030"
    )
    deck = tmp_path / "gb18030.cir"
    deck.write_bytes(source)
    expected_digest = _closure_digest(deck)

    result = executor.execute(str(deck))

    assert result.success is True
    assert result.analysis_type == "op"
    assert result.source_digest == expected_digest


def test_success_digest_matches_the_exact_collected_source_closure(tmp_path: Path) -> None:
    executor = _native_executor_or_skip()
    source = b"digest op\nV1 in 0 1\nR1 in 0 1k\n.op\n.end\n"
    deck = tmp_path / "digest.cir"
    deck.write_bytes(source)
    expected_digest = _closure_digest(deck)

    result = executor.execute(str(deck))

    assert result.success is True
    assert result.source_digest == expected_digest


def test_unavailable_native_keeps_known_closure_and_analysis_identity(
    tmp_path: Path,
) -> None:
    executor = SpiceExecutor(timeout_seconds=5)
    executor._ngspice = None
    executor._init_error = "synthetic unavailable native"
    deck = _write_netlist(
        tmp_path / "unavailable_native.cir",
        "unavailable native\nV1 out 0 1\n.op\n.end\n",
    )

    result = executor.execute(str(deck))

    assert result.success is False
    assert result.error.type is SimulationErrorType.NGSPICE_CRASH
    assert result.source_digest == _closure_digest(deck)
    assert result.analysis_type == "op"
    assert result.analysis_command == ".op"


@pytest.mark.parametrize(
    "title",
    [
        "simulation interrupted",
        "DC solution failed",
        "fatal error amplifier",
        "unknown subckt checker",
        "undefined parameter study",
        "cannot recover supply",
    ],
)
def test_real_native_failure_gate_does_not_match_circuit_titles(
    tmp_path: Path,
    title: str,
) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / f"safe_title_{title.replace(' ', '_').lower()}.cir",
        f"{title}\nV1 out 0 1\nR1 out 0 1k\n.op\n.end\n",
    )

    result = executor.execute(str(deck))

    assert result.success is True
    assert result.analysis_type == "op"
    assert result.analysis_command == ".op"


def test_dependency_mutation_after_collection_cannot_change_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    dependency = _write_netlist(tmp_path / "values.inc", ".param rload=1k\n")
    deck = _write_netlist(
        tmp_path / "snapshot.cir",
        (
            "closure snapshot\n"
            ".include values.inc\n"
            "V1 in 0 1\n"
            "R1 in out 1k\n"
            "R2 out 0 {rload}\n"
            ".op\n"
            ".end\n"
        ),
    )
    expected_digest = _closure_digest(deck)
    snapshot_roots: list[Path] = []
    original_snapshot = spice_executor_module.snapshot_spice_source_closure

    def snapshot_then_mutate(*args, **kwargs):
        closure = original_snapshot(*args, **kwargs)
        snapshot_roots.append(closure.snapshot_root)
        dependency.write_text(".param rload=3k\n", encoding="utf-8")
        return closure

    monkeypatch.setattr(
        spice_executor_module,
        "snapshot_spice_source_closure",
        snapshot_then_mutate,
    )

    first = executor.execute(str(deck))

    assert first.success is True
    assert first.analysis_type == "op"
    assert first.analysis_command == ".op"
    assert first.source_digest == expected_digest
    assert float(np.asarray(first.data.signals["V(out)"])[0]) == pytest.approx(0.5)
    assert _closure_digest(deck) != expected_digest
    assert snapshot_roots and all(not path.exists() for path in snapshot_roots)

    second = executor.execute(str(deck))
    assert second.success is True
    assert second.source_digest != first.source_digest
    assert float(np.asarray(second.data.signals["V(out)"])[0]) == pytest.approx(0.75)


def test_invalid_tran_operand_is_rejected_before_native_and_next_job_recovers(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    invalid = _write_netlist(
        tmp_path / "invalid.cir",
        "invalid transient\nV1 in 0 1\nR1 in 0 1k\n.tran bananas\n.end\n",
    )
    valid = _write_netlist(
        tmp_path / "valid.cir",
        (
            "valid transient\n"
            "V1 in 0 PULSE(0 1 0 1n 1n 10u 20u)\n"
            "R1 in out 1k\n"
            "C1 out 0 1u\n"
            ".tran 1u 20u\n"
            ".end\n"
        ),
    )

    failed = executor.execute(str(invalid))
    recovered = executor.execute(str(valid))

    assert failed.success is False
    assert failed.error.type is SimulationErrorType.PARAMETER_INVALID
    assert "TRAN analysis_command" in failed.error.message
    assert failed.raw_output in {None, ""}
    assert failed.source_digest == _closure_digest(invalid)
    assert recovered.success is True
    assert recovered.data is not None
    assert recovered.data.time is not None
    assert recovered.data.time.size > 1
    assert "V(out)" in recovered.data.signals


def test_real_invalid_dc_source_is_parameter_error_and_native_session_recovers(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    invalid = _write_netlist(
        tmp_path / "invalid_dc_source.cir",
        (
            "invalid DC source identity\n"
            "V1 in 0 1\n"
            "B1 out 0 V=V(in)\n"
            "R1 out 0 1k\n"
            ".dc B1 0 1 0.5\n"
            ".end\n"
        ),
    )
    recovery = _short_operating_point_deck(tmp_path)

    failed = executor.execute(str(invalid))
    recovered = executor.execute(str(recovery))

    assert failed.success is False
    assert failed.error.type is SimulationErrorType.PARAMETER_INVALID
    assert "Fatal error: DC Transfer Function" in failed.raw_output
    assert failed.source_digest == _closure_digest(invalid)
    assert failed.analysis_command == ".dc B1 0 1 0.5"
    assert executor._ngspice.has_fatal_error is False
    assert recovered.success is True


def test_real_zero_dc_step_is_rejected_before_native_and_session_recovers(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip(timeout_seconds=5)
    invalid = _write_netlist(
        tmp_path / "zero_dc_step.cir",
        (
            "zero DC step must never enter ngspice\n"
            "V1 out 0 0\n"
            "R1 out 0 1k\n"
            ".dc V1 0 1 0\n"
            ".end\n"
        ),
    )
    recovery = _short_operating_point_deck(tmp_path)

    failed = executor.execute(str(invalid))
    recovered = executor.execute(str(recovery))

    assert failed.success is False
    assert failed.error.type is SimulationErrorType.PARAMETER_INVALID
    assert "step must be non-zero" in failed.error.message
    assert failed.raw_output in {None, ""}
    assert failed.duration_seconds < 1
    assert failed.source_digest == _closure_digest(invalid)
    assert failed.analysis_command == ".dc V1 0 1 0"
    assert executor._ngspice.has_fatal_error is False
    assert recovered.success is True


@pytest.mark.parametrize(
    ("name", "body", "diagnostic"),
    [
        (
            "ignored_model_parameter",
            (
                "V1 in 0 1\n"
                "D1 in 0 DM\n"
                ".model DM D(IS=1e-12 totallyfake=123)\n"
                ".op\n"
            ),
            "unrecognized parameter (totallyfake) - ignored",
        ),
        (
            "replaced_model_level",
            (
                "Vd d 0 1\n"
                "Vg g 0 1\n"
                "M1 d g 0 0 NM\n"
                ".model NM NMOS(level=999 vto=1 kp=1m)\n"
                ".op\n"
            ),
            "Setting Level to 1",
        ),
    ],
)
def test_real_native_silent_parameter_fallback_is_failure_and_session_recovers(
    tmp_path: Path,
    name: str,
    body: str,
    diagnostic: str,
) -> None:
    executor = _native_executor_or_skip()
    invalid = _write_netlist(
        tmp_path / f"{name}.cir",
        f"silent fallback must fail\n{body}.end\n",
    )
    recovery = _short_operating_point_deck(tmp_path)

    failed = executor.execute(str(invalid))
    recovered = executor.execute(str(recovery))

    assert failed.success is False
    assert failed.data is None
    assert failed.error.type is SimulationErrorType.PARAMETER_INVALID
    assert diagnostic.casefold() in (failed.raw_output or "").casefold()
    assert "静默降级" in failed.error.message
    assert executor._ngspice.has_fatal_error is False
    assert recovered.success is True


@pytest.mark.parametrize("directive", [".ic", ".nodeset"])
def test_real_nonexistent_initial_condition_node_fails_but_existing_node_runs(
    tmp_path: Path,
    directive: str,
) -> None:
    executor = _native_executor_or_skip()
    stem = directive.lstrip(".")
    invalid = _write_netlist(
        tmp_path / f"invalid_{stem}.cir",
        (
            "invalid initial-state node must not be ignored\n"
            "V1 in 0 PULSE(0 1 0 1n 1n 1u 2u)\n"
            "R1 in out 1k\n"
            "C1 out 0 1n\n"
            f"{directive} V(foo)=1\n"
            ".tran 100n 1u uic\n"
            ".end\n"
        ),
    )
    valid = _write_netlist(
        tmp_path / f"valid_{stem}.cir",
        (
            "valid initial-state node\n"
            "V1 in 0 PULSE(0 1 0 1n 1n 1u 2u)\n"
            "R1 in out 1k\n"
            "C1 out 0 1n\n"
            f"{directive} V(out)=1\n"
            ".tran 100n 1u uic\n"
            ".end\n"
        ),
    )

    failed = executor.execute(str(invalid))
    accepted = executor.execute(str(valid))

    assert failed.success is False
    assert failed.data is None
    assert failed.error.type is SimulationErrorType.PARAMETER_INVALID
    assert "non-existent node" in (failed.raw_output or "")
    assert "静默降级" in failed.error.message
    assert failed.source_digest == _closure_digest(invalid)
    assert accepted.success is True, accepted.error
    assert accepted.data is not None
    assert accepted.data.time is not None


def test_real_multi_temperature_is_rejected_but_single_values_are_honored(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    multiple = _write_netlist(
        tmp_path / "multiple_temperatures.cir",
        (
            "multi-temperature result dimension is unsupported\n"
            "V1 out 0 1\n"
            "R1 out 0 1k\n"
            ".temp 25 50 75\n"
            ".op\n"
            ".end\n"
        ),
    )
    single = _write_netlist(
        tmp_path / "single_temperature.cir",
        (
            "single temperature\n"
            "V1 out 0 1\n"
            "R1 out 0 1k\n"
            ".temp 50\n"
            ".op\n"
            ".end\n"
        ),
    )
    expression = _write_netlist(
        tmp_path / "parameter_temperature.cir",
        (
            "single parameterized temperature\n"
            ".param t=50\n"
            "V1 out 0 1\n"
            "R1 out 0 1k\n"
            ".temp {t}\n"
            ".op\n"
            ".end\n"
        ),
    )

    rejected = executor.execute(str(multiple))
    accepted = executor.execute(str(single))
    accepted_expression = executor.execute(str(expression))

    assert rejected.success is False
    assert rejected.error.type is SimulationErrorType.PARAMETER_INVALID
    assert rejected.data is None
    assert ".temp" in rejected.error.message
    assert rejected.analysis_command == ".op"
    assert accepted.success is True, accepted.error
    assert "TEMP = 50.000000" in (accepted.raw_output or "")
    assert accepted_expression.success is True, accepted_expression.error
    assert "TEMP = 50.000000" in (accepted_expression.raw_output or "")


def test_temperature_native_warning_is_a_fail_closed_backstop() -> None:
    output = (
        "stderr Warning: Could not set temperature to 25 50 75\n"
        "stderr Set to default 27 C instead."
    )
    executor = SpiceExecutor.__new__(SpiceExecutor)

    assert SpiceExecutor._has_native_failure_output(output) is True
    error = executor._parse_ngspice_output(output, "bad_temp.cir")
    assert error.type is SimulationErrorType.PARAMETER_INVALID


def test_real_ngspice_rejects_aborted_partial_transient_plot(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    unstable = _write_netlist(
        tmp_path / "aborted_partial_tran.cir",
        (
            "aborted partial transient\n"
            "B1 out 0 V={time < 1u ? 0 : v(out)+1}\n"
            "R1 out 0 1k\n"
            ".tran 10n 2u\n"
            ".end\n"
        ),
    )
    recovery = _write_netlist(
        tmp_path / "recovery_after_aborted_tran.cir",
        "recovery\nV1 out 0 1\n.op\n.end\n",
    )

    failed = executor.execute(str(unstable))
    recovered = executor.execute(str(recovery))

    assert failed.success is False
    assert failed.error.type is SimulationErrorType.CONVERGENCE_TRAN
    assert failed.data is None
    assert failed.source_digest == _closure_digest(unstable)
    assert failed.analysis_command == ".tran 10n 2u"
    assert "timestep too small" in (failed.raw_output or "").lower()
    assert "run simulation(s) aborted" in (failed.raw_output or "").lower()
    assert recovered.success is True
    assert recovered.analysis_type == "op"


@pytest.mark.parametrize(
    "terminal_output",
    [
        "stderr doAnalyses: TRAN: Timestep too small; time = 1e-6",
        "stderr run simulation(s) aborted",
        "stdout DC solution failed -",
        "stderr Transient solution failed",
        "stderr simulation interrupted",
    ],
)
def test_native_terminal_gate_covers_aborted_analysis_diagnostics(
    terminal_output: str,
) -> None:
    assert SpiceExecutor._has_native_failure_output(terminal_output) is True


def test_native_terminal_gate_does_not_reject_a_recoverable_singular_warning() -> None:
    output = (
        "stderr Warning: singular matrix: check nodes out and out\n"
        "stdout Trying gmin stepping\n"
        "stdout Transient op finished successfully\n"
    )

    assert SpiceExecutor._has_native_failure_output(output) is False


def test_only_authorized_paired_measure_error_is_non_terminal() -> None:
    request = MeasureRequest(
        analysis_type="tran",
        name="bad",
        statement=".measure tran bad find v(foo) at=0.5u",
        source_id="@main",
        line_number=6,
    )
    paired = (
        "stdout Measurements for Transient Analysis\n"
        "stderr Error: no such vector as v(foo).\n"
        "stderr .measure tran bad find v(foo) at=0.5u failed!"
    )
    unpaired = (
        "stdout Measurements for Transient Analysis\n"
        "stderr Error: no such vector as v(foo)."
    )
    unknown_name = (
        "stdout Measurements for Transient Analysis\n"
        "stderr Error: no such vector as v(foo).\n"
        "stderr .measure tran other find v(foo) at=0.5u failed!"
    )

    assert SpiceExecutor._has_native_failure_output(
        paired,
        analysis_type="tran",
        measure_requests=(request,),
    ) is False
    assert SpiceExecutor._has_native_failure_output(
        unpaired,
        analysis_type="tran",
        measure_requests=(request,),
    ) is True
    assert SpiceExecutor._has_native_failure_output(
        unknown_name,
        analysis_type="tran",
        measure_requests=(request,),
    ) is True


def test_real_failed_measure_keeps_successful_waveform_and_failed_outcome(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / "failed_measure_local_error.cir",
        (
            "measurement failure is not simulation failure\n"
            "V1 in 0 PULSE(0 1 0 1n 1n 1u 2u)\n"
            "R1 in out 1k\n"
            "C1 out 0 1n\n"
            ".tran 100n 2u\n"
            ".measure tran bad find v(foo) at=0.5u\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is True, result.error
    assert result.data is not None
    assert result.data.time is not None
    assert len(result.data.time) > 1
    assert result.measurements is not None
    assert len(result.measurements) == 1
    measurement = result.measurements[0]
    assert measurement.name == "bad"
    assert measurement.status is MeasureStatus.FAILED
    assert measurement.value is None
    assert "no such vector" in measurement.error_message
    assert "stderr Error: no such vector" in (result.raw_output or "")
    assert result.to_dict()["success"] is True


@pytest.mark.parametrize(
    "title",
    [
        "fatal error amplifier",
        "unknown subckt checker",
        "undefined parameter study",
        "cannot recover supply",
    ],
)
def test_error_classifier_ignores_circuit_title_when_real_syntax_error_follows(
    title: str,
) -> None:
    executor = SpiceExecutor.__new__(SpiceExecutor)
    output = f"stdout Circuit: {title}\nstderr Error: bad syntax"

    error = executor._parse_ngspice_output(output, "broken.cir")

    assert error.type is SimulationErrorType.SYNTAX_ERROR
    assert "bad syntax" in error.message


@pytest.mark.parametrize(
    "diagnostic",
    [
        "stderr Access violation reading location 0x0",
        "stderr Segmentation fault",
    ],
)
def test_error_classifier_reserves_crash_for_process_integrity_failures(
    diagnostic: str,
) -> None:
    executor = SpiceExecutor.__new__(SpiceExecutor)

    error = executor._parse_ngspice_output(diagnostic, "broken.cir")

    assert error.type is SimulationErrorType.NGSPICE_CRASH
    assert error.severity.value == "critical"


@pytest.mark.parametrize(
    ("output", "expected_type"),
    [
        (
            "stdout timeout = 1\n"
            "stderr Fatal error: source is not in circuit",
            SimulationErrorType.PARAMETER_INVALID,
        ),
        (
            "stderr Error: no such device foo",
            SimulationErrorType.PARAMETER_INVALID,
        ),
        (
            "stderr cannot recover from previous input error",
            SimulationErrorType.SYNTAX_ERROR,
        ),
        (
            "stderr Warning: model placeholder unknown\n"
            "stderr Fatal error: source is not in circuit",
            SimulationErrorType.PARAMETER_INVALID,
        ),
    ],
)
def test_error_classifier_uses_terminal_records_without_warning_or_stdout_pollution(
    output: str,
    expected_type: SimulationErrorType,
) -> None:
    executor = SpiceExecutor.__new__(SpiceExecutor)

    error = executor._parse_ngspice_output(output, "broken.cir")

    assert error.type is expected_type


@pytest.mark.parametrize(
    ("name", "parameter", "analysis_command", "analysis_type"),
    [
        ("tran_stop", ".param tend=1u", ".tran 10n {tend}", "tran"),
        ("dc_step", ".param s=0", ".dc V1 0 1 {s}", "dc"),
        ("ac_points", ".param n=2", ".ac lin {n} 1 2", "ac"),
        ("ac_stop", ".param hi=2", ".ac dec 3 1 {hi}", "ac"),
        (
            "noise_points",
            ".param n=3",
            ".noise V(out) V1 dec {n} 1 10",
            "noise",
        ),
    ],
)
def test_parameterized_analysis_grid_is_rejected_before_native(
    tmp_path: Path,
    name: str,
    parameter: str,
    analysis_command: str,
    analysis_type: str,
) -> None:
    class _MustNotEnterNative:
        fatal_error_message = ""

        @property
        def initialized(self) -> bool:
            raise AssertionError("non-literal analysis grid reached native state")

    executor = SpiceExecutor(timeout_seconds=5)
    executor._ngspice = _MustNotEnterNative()
    deck = _write_netlist(
        tmp_path / f"parameterized_{name}.cir",
        (
            "parameterized grid is not provable\n"
            f"{parameter}\n"
            "V1 in 0 AC 1\n"
            "R1 in out 1k\n"
            "C1 out 0 10p\n"
            f"{analysis_command}\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is False
    assert result.data is None
    assert result.error.type is SimulationErrorType.PARAMETER_INVALID
    assert "finite literal" in result.error.message
    assert result.analysis_type == analysis_type
    assert result.analysis_command == analysis_command
    assert result.source_digest == _closure_digest(deck)


def test_real_noise_accepts_a_single_point_spectrum_plus_totals_pair(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / "single_point_noise.cir",
        (
            "single point noise\n"
            "V1 in 0 AC 1\n"
            "R1 in out 1k\n"
            "R2 out 0 1k\n"
            ".noise V(out) V1 dec 3 1 2\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is True
    assert result.analysis_type == "noise"
    assert result.analysis_command == ".noise V(out) V1 dec 3 1 2"
    assert result.data is not None
    assert result.data.frequency is not None
    assert result.data.frequency.size == 1
    assert result.data.noise_totals is not None
    assert result.data.noise_totals.output_rms >= 0
    assert result.data.noise_totals.input_referred_rms >= 0
    assert result.source_digest == _closure_digest(deck)


def test_real_noise_accepts_lin_one_spectrum_without_totals_plot(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / "lin_one_noise.cir",
        (
            "lin one noise\n"
            "V1 in 0 AC 1\n"
            "R1 in out 1k\n"
            "R2 out 0 1k\n"
            ".noise V(out) V1 lin 1 1 10\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is True
    assert result.analysis_type == "noise"
    assert result.analysis_command == ".noise V(out) V1 lin 1 1 10"
    assert result.data is not None
    assert result.data.frequency is not None
    assert result.data.frequency.size == 1
    assert result.data.noise_totals is None


def test_real_noise_preserves_integrated_totals_as_two_scalars() -> None:
    executor = _native_executor_or_skip()
    sample = (
        Path(__file__).resolve().parents[1]
        / "TestCircuit"
        / "noise_analysis"
        / "01_resistor_thermal_noise.cir"
    )

    result = executor.execute(str(sample))

    assert result.success is True
    assert result.data is not None
    assert result.data.noise_totals is not None
    assert result.data.noise_totals.output_rms == pytest.approx(
        2.878894273285597e-05,
        rel=1e-9,
    )
    assert result.data.noise_totals.input_referred_rms == pytest.approx(
        5.757788546571194e-05,
        rel=1e-9,
    )
    assert "onoise_total" not in result.data.signals
    assert "inoise_total" not in result.data.signals


def _fake_noise_native(case: str):
    spectrum = {
        "frequency": VectorInfo(
            "frequency",
            VectorType.SV_FREQUENCY,
            2,
            np.asarray([1.0, 2.0]),
        ),
        "inoise_spectrum": VectorInfo(
            "inoise_spectrum",
            VectorType.SV_INPUT_N_DENS,
            2,
            np.asarray([2e-9, 2e-9]),
        ),
        "onoise_spectrum": VectorInfo(
            "onoise_spectrum",
            VectorType.SV_OUTPUT_N_DENS,
            2,
            np.asarray([1e-9, 1e-9]),
        ),
    }
    valid_totals = {
        "inoise_total": VectorInfo(
            "inoise_total",
            VectorType.SV_INPUT_NOISE,
            1,
            np.asarray([2e-9]),
        ),
        "onoise_total": VectorInfo(
            "onoise_total",
            VectorType.SV_OUTPUT_NOISE,
            1,
            np.asarray([1e-9]),
        ),
    }
    plots = {"noise1": spectrum}
    if case == "nan_spectrum":
        spectrum["onoise_spectrum"] = VectorInfo(
            "onoise_spectrum",
            VectorType.SV_OUTPUT_N_DENS,
            2,
            np.asarray([np.nan, 1e-9]),
        )
        plots["noise2"] = valid_totals
    elif case == "duplicate_totals_plot":
        plots["noise2"] = valid_totals
        plots["noise3"] = valid_totals
    elif case == "missing_total_vector":
        plots["noise2"] = {"onoise_total": valid_totals["onoise_total"]}
    elif case in {"non_scalar", "nan", "negative"}:
        invalid_totals = dict(valid_totals)
        if case == "non_scalar":
            values = np.asarray([1e-9, 2e-9])
        elif case == "nan":
            values = np.asarray([np.nan])
        else:
            values = np.asarray([-1e-9])
        invalid_totals["onoise_total"] = VectorInfo(
            "onoise_total",
            VectorType.SV_OUTPUT_NOISE,
            len(values),
            values,
        )
        plots["noise2"] = invalid_totals

    class _FakeNoiseNative:
        has_fatal_error = False
        fatal_error_message = ""

        @staticmethod
        def destroy(*, deadline: float) -> bool:
            assert deadline > time.monotonic()
            return True

        @staticmethod
        def set_input_path(_path: Path) -> None:
            return None

        @staticmethod
        def load_netlist(_lines: list[str]) -> bool:
            return True

        @staticmethod
        def run(*, timeout_seconds: float, cancel_signal=None) -> None:
            assert timeout_seconds > 0

        @staticmethod
        def get_stdout() -> str:
            return ""

        @staticmethod
        def get_all_plots() -> list[str]:
            return list(plots)

        @staticmethod
        def get_all_vectors(plot_name: str) -> list[str]:
            return list(plots[plot_name])

        @staticmethod
        def get_vector_info(vector_name: str, *, plot_name: str):
            return plots[plot_name].get(vector_name)

        @staticmethod
        def get_plot_scale_name(plot_name: str):
            return "frequency" if plot_name == "noise1" else None

    return _FakeNoiseNative()


@pytest.mark.parametrize(
    "case",
    [
        "missing_totals",
        "duplicate_totals_plot",
        "missing_total_vector",
        "non_scalar",
        "nan",
        "negative",
        "nan_spectrum",
    ],
)
def test_malformed_multi_point_noise_totals_fail_closed_as_output_parse_error(
    tmp_path: Path,
    case: str,
) -> None:
    executor = SpiceExecutor.__new__(SpiceExecutor)
    executor._logger = logging.getLogger(__name__)
    executor._ngspice = _fake_noise_native(case)

    result = executor._run_simulation(
        file_path=str(tmp_path / "noise.cir"),
        source_text=(
            "synthetic noise\n"
            "V1 in 0 AC 1\n"
            "R1 in out 1k\n"
            "R2 out 0 1k\n"
            ".noise V(out) V1 lin 2 1 2\n"
            ".end\n"
        ),
        source_digest="0" * 64,
        runtime_input_path=tmp_path,
        analysis_type="noise",
        analysis_command=".noise V(out) V1 lin 2 1 2",
        measure_requests=(),
        cancel_signal=None,
        deadline=time.monotonic() + 5,
    )

    assert result.success is False
    assert result.error.type is SimulationErrorType.OUTPUT_PARSE_ERROR
    assert result.data is None


def test_ac_dec_zero_interval_grid_is_rejected_before_native(
    tmp_path: Path,
) -> None:
    class _MustNotEnterNative:
        initialized = True
        fatal_error_message = ""

        @property
        def has_fatal_error(self) -> bool:
            raise AssertionError("AC DEC preflight must run before native state access")

    executor = SpiceExecutor(timeout_seconds=5)
    executor._ngspice = _MustNotEnterNative()
    deck = _write_netlist(
        tmp_path / "zero_interval_ac_dec.cir",
        (
            "zero interval ac dec\n"
            "V1 in 0 AC 1\n"
            "R1 in 0 1k\n"
            ".ac dec 3 1 2\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is False
    assert result.error.type is SimulationErrorType.PARAMETER_INVALID
    assert "at least one generated interval" in result.error.message
    assert result.source_digest == _closure_digest(deck)
    assert result.analysis_command == ".ac dec 3 1 2"


def test_noise_current_output_is_rejected_by_shared_grammar_before_native(
    tmp_path: Path,
) -> None:
    class _MustNotEnterNative:
        initialized = True
        fatal_error_message = ""

        @property
        def has_fatal_error(self) -> bool:
            raise AssertionError("NOISE grammar must run before native state access")

    executor = SpiceExecutor(timeout_seconds=5)
    executor._ngspice = _MustNotEnterNative()
    deck = _write_netlist(
        tmp_path / "noise_current_output.cir",
        (
            "unsupported NOISE current output\n"
            "V1 in 0 AC 1\n"
            "Vsense in out 0\n"
            "R1 out 0 1k\n"
            ".noise I(Vsense) V1 lin 2 1 2\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is False
    assert result.error.type is SimulationErrorType.PARAMETER_INVALID
    assert "V(node)" in result.error.message
    assert result.analysis_type == "noise"
    assert result.analysis_command == ".noise I(Vsense) V1 lin 2 1 2"
    assert result.source_digest == _closure_digest(deck)


def test_real_ngspice_does_not_repair_missing_end_in_source_deck(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / "missing_end.cir",
        "missing end\nV1 in 0 1\nR1 in 0 1k\n.op\n",
    )

    result = executor.execute(str(deck))

    assert result.success is False
    assert result.error.type is SimulationErrorType.SYNTAX_ERROR
    assert result.analysis_type == "op"
    assert result.analysis_command == ".op"


@pytest.mark.parametrize("comment_marker", [";", "$"])
def test_real_ngspice_accepts_commented_end_and_ignores_following_source(
    tmp_path: Path,
    comment_marker: str,
) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / f"commented_end_{ord(comment_marker)}.cir",
        (
            "commented end\n"
            "V1 out 0 1\n"
            ".op\n"
            f".end {comment_marker} end of active deck\n"
            ".include missing_after_end.lib\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is True
    assert result.analysis_type == "op"
    assert result.analysis_command == ".op"
    assert result.source_digest == _closure_digest(deck)


@pytest.mark.parametrize(
    ("name", "body", "analysis_type"),
    [
        (
            "op",
            "V1 out 0 1\nR1 out 0 1k\n.op\n",
            "op",
        ),
        (
            "dc",
            "V1 out 0 0\nR1 out 0 1k\n.dc V1 0 1 0.5\n",
            "dc",
        ),
        (
            "tran",
            (
                "V1 in 0 PULSE(0 1 0 1n 1n 500n 1u)\n"
                "R1 in out 1k\nC1 out 0 1n\n.tran 100n 1u\n"
            ),
            "tran",
        ),
        (
            "ac",
            "V1 in 0 AC 1\nR1 in out 1k\nC1 out 0 1n\n.ac lin 3 1 3\n",
            "ac",
        ),
        (
            "noise",
            (
                "V1 in 0 AC 1\nR1 in out 1k\nR2 out 0 1k\n"
                ".noise V(out) V1 dec 3 1 10\n"
            ),
            "noise",
        ),
    ],
)
def test_real_success_for_every_analysis_satisfies_complete_result_contract(
    tmp_path: Path,
    name: str,
    body: str,
    analysis_type: str,
) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / f"strict_success_{name}.cir",
        f"strict {name} success\n{body}.end\n",
    )

    result = executor.execute(str(deck))

    assert result.success is True, result.error
    assert result.analysis_type == analysis_type
    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["analysis_type"] == analysis_type
    assert payload["source_digest"] == result.source_digest


def test_real_ac_lin_two_native_grid_is_rejected_before_success(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / "ac_lin_two.cir",
        (
            "ngspice AC LIN2 grid anomaly\n"
            "V1 in 0 AC 1\n"
            "R1 in out 1k\n"
            "C1 out 0 1n\n"
            ".ac lin 2 1 2\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is False
    assert result.data is None
    assert result.error.type is SimulationErrorType.OUTPUT_PARSE_ERROR
    assert "AC LIN axis length" in result.error.message
    # A failed result must itself remain persistable and diagnosable.
    assert result.to_dict()["success"] is False


@pytest.mark.parametrize(
    "analysis_command",
    [
        ".tran 1u 2u 1u",
        ".tran 1u 2u 0 2u uic",
    ],
)
def test_real_valid_tran_start_semantics_pass_complete_result_contract(
    tmp_path: Path,
    analysis_command: str,
) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / "tran_start_contract.cir",
        (
            "valid transient saved-start semantics\n"
            "V1 in 0 1\n"
            "R1 in out 1k\n"
            "C1 out 0 1n IC=0\n"
            f"{analysis_command}\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is True, result.error
    assert result.data is not None
    assert result.to_dict()["success"] is True


@pytest.mark.parametrize(
    "analysis_block",
    [
        ".op\n.tran 100n 4u",
        ".tran 1n 100n\n.tran 1n 10n",
        (
            ".param mode=1\n"
            ".if (mode == 1)\n"
            ".tran 1n 100n\n"
            ".else\n"
            ".tran 2n 20n\n"
            ".endif"
        ),
    ],
    ids=["different-types", "same-type", "conditional-same-type"],
)
def test_multiple_main_analysis_cards_are_rejected_before_native(
    tmp_path: Path,
    analysis_block: str,
) -> None:
    executor = SpiceExecutor(timeout_seconds=5)
    deck = _write_netlist(
        tmp_path / "ambiguous.cir",
        (
            "ambiguous source deck\n"
            "V1 in 0 1\n"
            "R1 in 0 1k\n"
            f"{analysis_block}\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is False
    assert result.analysis_type == "unknown"
    assert result.error.type is SimulationErrorType.PARAMETER_INVALID
    assert "2" in result.error.message
    assert result.source_digest == _closure_digest(deck)


@pytest.mark.parametrize(
    "unsupported_directive",
    sorted(spice_executor_module._UNSUPPORTED_ANALYSIS_DIRECTIVES),
)
def test_unsupported_top_level_analysis_cards_are_rejected_before_native(
    tmp_path: Path,
    unsupported_directive: str,
) -> None:
    class _MustNotEnterNative:
        initialized = True
        fatal_error_message = ""

        @property
        def has_fatal_error(self) -> bool:
            raise AssertionError("unsupported analysis must fail before native access")

    executor = SpiceExecutor(timeout_seconds=5)
    executor._ngspice = _MustNotEnterNative()
    deck = _write_netlist(
        tmp_path / f"unsupported_{unsupported_directive[1:]}.cir",
        (
            "unsupported top-level analysis\n"
            "V1 in 0 1\n"
            "R1 in out 1k\n"
            "R2 out 0 1k\n"
            ".op\n"
            f"{unsupported_directive} V(out) V1\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is False
    assert result.error.type is SimulationErrorType.PARAMETER_INVALID
    assert unsupported_directive in result.error.message
    assert "静默丢弃" in result.error.message
    assert result.analysis_type == "op"
    assert result.analysis_command == ".op"
    assert result.source_digest == _closure_digest(deck)


@pytest.mark.parametrize("location", ["main", "include", "selected-lib"])
def test_active_runtime_options_are_rejected_before_native_and_session_recovers(
    tmp_path: Path,
    location: str,
) -> None:
    executor = _native_executor_or_skip()
    option_card = ".options totallyfake=1"
    dependency_card = ""
    if location == "main":
        dependency_card = option_card
    elif location == "include":
        include_path = tmp_path / "runtime_options.inc"
        include_path.write_text(option_card + "\n", encoding="utf-8")
        dependency_card = f'.include "{include_path.name}"'
    else:
        library_path = tmp_path / "runtime_options.lib"
        library_path.write_text(
            ".lib tt\n" + option_card + "\n.endl tt\n",
            encoding="utf-8",
        )
        dependency_card = f'.lib "{library_path.name}" tt'
    invalid = _write_netlist(
        tmp_path / f"runtime_options_{location}.cir",
        (
            "runtime options are not a supported authority\n"
            f"{dependency_card}\n"
            "V1 out 0 1\n"
            "R1 out 0 1k\n"
            ".op\n"
            ".end\n"
        ),
    )

    failed = executor.execute(str(invalid))
    recovered = executor.execute(str(_short_operating_point_deck(tmp_path)))

    assert failed.success is False
    assert failed.data is None
    assert failed.error.type is SimulationErrorType.PARAMETER_INVALID
    assert ".option/.options" in failed.error.message
    assert failed.raw_output in {None, ""}
    assert failed.source_digest == _closure_digest(invalid)
    assert recovered.success is True


@pytest.mark.parametrize("unknown_plot", ["future1", "acfuture1", "dcfoo", "opx"])
def test_unknown_native_plot_is_a_fail_closed_authority_conflict(
    unknown_plot: str,
) -> None:
    class _UnknownPlotNative:
        @staticmethod
        def get_all_plots() -> list[str]:
            return [unknown_plot, "op1", "const"]

    executor = SpiceExecutor.__new__(SpiceExecutor)
    executor._ngspice = _UnknownPlotNative()

    target, totals, types, conflicts = executor._find_source_analysis_plot()

    assert target is None
    assert totals is None
    assert types == ("op",)
    assert conflicts == ("op1", unknown_plot)


def test_real_nested_dc_preserves_second_sweep_parameters_and_segmented_axis() -> None:
    executor = _native_executor_or_skip()
    sample = (
        Path(__file__).resolve().parents[1]
        / "TestCircuit"
        / "dc_analysis"
        / "04_bjt_output_characteristics.cir"
    )

    result = executor.execute(str(sample))

    assert result.success is True
    assert result.data is not None
    assert result.data.sweep is not None
    assert result.analysis_info["parameters"] == {
        "source_name": "Vce",
        "start_value": "0",
        "stop_value": "10",
        "step": "0.05",
        "second_source_name": "Ib",
        "second_start_value": "10u",
        "second_stop_value": "50u",
        "second_step": "10u",
    }
    sweep = np.asarray(result.data.sweep)
    reset_indices = np.flatnonzero(np.diff(sweep) < 0) + 1
    assert reset_indices.tolist() == [201, 402, 603, 804]
    assert np.diff(np.r_[0, reset_indices, sweep.size]).tolist() == [201] * 5


def test_nested_dc_measure_is_rejected_before_native_without_outer_identity(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / "nested_dc_measure.cir",
        (
            "nested DC measure has no outer identity\n"
            "V1 out 0 0\n"
            "V2 control 0 0\n"
            "R1 out 0 1k\n"
            ".measure dc max_out MAX V(out)\n"
            ".dc V1 0 1 0.5 V2 0 1 1\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is False
    assert result.error.type is SimulationErrorType.PARAMETER_INVALID
    assert "外层扫描值" in result.error.message
    assert result.source_digest == _closure_digest(deck)
    assert result.analysis_command == ".dc V1 0 1 0.5 V2 0 1 1"


def test_real_dc_scale_metadata_does_not_consume_nodes_named_sweep(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / "dc_sweep_nodes.cir",
        (
            "DC nodes named like the scale\n"
            "V1 sweep 0 0\n"
            "R1 sweep sweepout 1k\n"
            "R2 sweepout 0 1k\n"
            ".dc V1 0 1 0.1\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is True
    assert result.data is not None
    assert np.asarray(result.data.sweep).tolist() == pytest.approx(
        np.linspace(0.0, 1.0, 11).tolist()
    )
    assert "V(sweep)" in result.data.signals
    assert "V(sweepout)" in result.data.signals
    assert np.asarray(result.data.signals["V(sweep)"]).tolist() == pytest.approx(
        np.asarray(result.data.sweep).tolist()
    )


def test_real_op_treats_node_named_time_as_voltage_not_axis(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / "op_time_node.cir",
        (
            "OP node named time\n"
            "V1 time 0 1\n"
            "R1 time 0 1k\n"
            ".op\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is True
    assert result.data is not None
    assert result.data.time is None
    assert result.data.frequency is None
    assert result.data.sweep is None
    assert np.asarray(result.data.signals["V(time)"]).tolist() == pytest.approx(
        [1.0]
    )


def test_real_dc_treats_node_named_time_as_voltage_not_second_axis(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / "dc_time_node.cir",
        (
            "DC node named time\n"
            "V1 time 0 0\n"
            "R1 time 0 1k\n"
            ".dc V1 0 1 0.5\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is True
    assert result.data is not None
    assert result.data.time is None
    assert result.data.frequency is None
    assert np.asarray(result.data.sweep).tolist() == pytest.approx([0.0, 0.5, 1.0])
    assert np.asarray(result.data.signals["V(time)"]).tolist() == pytest.approx(
        [0.0, 0.5, 1.0]
    )


def test_real_tran_treats_node_named_frequency_as_voltage_not_second_axis(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / "tran_frequency_node.cir",
        (
            "TRAN node named frequency\n"
            "V1 frequency 0 PULSE(0 1 0 1n 1n 1u 2u)\n"
            "R1 frequency 0 1k\n"
            ".tran 100n 1u\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is True
    assert result.data is not None
    assert result.data.time is not None
    assert result.data.frequency is None
    assert result.data.sweep is None
    assert "V(frequency)" in result.data.signals
    assert len(result.data.signals["V(frequency)"]) == len(result.data.time)


@pytest.mark.parametrize(
    ("name", "body", "reserved_name"),
    [
        (
            "tran_time",
            "V1 time 0 1\nR1 time 0 1k\n.tran 1n 10n\n",
            "time",
        ),
        (
            "ac_frequency",
            "V1 frequency 0 AC 1\nR1 frequency 0 1k\n.ac lin 2 1 2\n",
            "frequency",
        ),
        (
            "noise_frequency",
            (
                "V1 frequency 0 AC 1\n"
                "R1 frequency 0 1k\n"
                ".noise V(frequency) V1 lin 2 1 2\n"
            ),
            "frequency",
        ),
        (
            "dc_voltage_scale",
            "V1 v-sweep 0 0\nR1 v-sweep 0 1k\n.dc V1 0 1 1\n",
            "v-sweep",
        ),
        (
            "dc_current_scale",
            "I1 i-sweep 0 0\nR1 i-sweep 0 1k\n.dc I1 0 1m 1m\n",
            "i-sweep",
        ),
        (
            "dc_temperature_scale",
            "V1 temp-sweep 0 1\nR1 temp-sweep 0 1k\n.dc TEMP 20 30 10\n",
            "temp-sweep",
        ),
        (
            "dc_resistance_scale",
            "V1 res-sweep 0 1\nR1 res-sweep 0 1k\n.dc R1 1k 2k 1k\n",
            "res-sweep",
        ),
    ],
)
def test_reserved_native_axis_node_collision_is_rejected_before_run(
    tmp_path: Path,
    name: str,
    body: str,
    reserved_name: str,
) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / f"reserved_{name}.cir",
        f"reserved native axis\n{body}.end\n",
    )

    result = executor.execute(str(deck))

    assert result.success is False
    assert result.error.type is SimulationErrorType.PARAMETER_INVALID
    assert reserved_name in result.error.message
    assert "请重命名" in result.error.message
    assert result.source_digest == _closure_digest(deck)


@pytest.mark.parametrize(
    ("name", "element_lines", "analysis_command", "expected_scale", "scale_name"),
    [
        (
            "temperature",
            "V1 out 0 1\nR1 out 0 1k\n",
            ".dc TEMP 20 30 10",
            [20.0, 30.0],
            "temp-sweep",
        ),
        (
            "resistance",
            "V1 in 0 1\nR1 in 0 1k\n",
            ".dc R1 1k 2k 1k",
            [1000.0, 2000.0],
            "res-sweep",
        ),
    ],
)
def test_real_dc_uses_callback_scale_for_temperature_and_resistance(
    tmp_path: Path,
    name: str,
    element_lines: str,
    analysis_command: str,
    expected_scale: list[float],
    scale_name: str,
) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / f"dc_{name}.cir",
        f"DC {name} sweep\n{element_lines}{analysis_command}\n.end\n",
    )

    result = executor.execute(str(deck))

    assert result.success is True
    assert result.analysis_command == analysis_command
    assert result.data is not None
    assert np.asarray(result.data.sweep).tolist() == pytest.approx(expected_scale)
    assert all(
        signal_name.casefold() != scale_name
        for signal_name in result.data.signals
    )


@pytest.mark.parametrize(
    ("name", "body", "analysis_command", "axis_name", "signal_name"),
    [
        (
            "tran",
            (
                "V1 in 0 PULSE(0 1 0 1n 1n 1u 2u)\n"
                "X1 in out cell\n"
                ".subckt cell a y\n"
                "R1 a time 1k\n"
                "C1 time 0 1n\n"
                "E1 y 0 time 0 1\n"
                ".ends cell\n"
            ),
            ".tran 100n 2u",
            "time",
            "V(x1.time)",
        ),
        (
            "ac",
            (
                "V1 in 0 AC 1\n"
                "X1 in out cell\n"
                ".subckt cell a y\n"
                "R1 a frequency 1k\n"
                "C1 frequency 0 1n\n"
                "E1 y 0 frequency 0 1\n"
                ".ends cell\n"
            ),
            ".ac lin 3 1 3",
            "frequency",
            "V(x1.frequency)",
        ),
        (
            "dc",
            (
                "V1 in 0 0\n"
                "X1 in out cell\n"
                ".subckt cell a y\n"
                "R1 a v-sweep 1k\n"
                "R2 v-sweep 0 1k\n"
                "E1 y 0 v-sweep 0 1\n"
                ".ends cell\n"
            ),
            ".dc V1 0 1 0.5",
            "sweep",
            "V(x1.v-sweep)",
        ),
    ],
)
def test_real_hierarchical_reserved_node_is_not_mistaken_for_native_axis(
    tmp_path: Path,
    name: str,
    body: str,
    analysis_command: str,
    axis_name: str,
    signal_name: str,
) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / f"hierarchical_{name}_axis_name.cir",
        f"hierarchical reserved node identity\n{body}{analysis_command}\n.end\n",
    )

    result = executor.execute(str(deck))

    assert result.success is True, result.error
    assert result.data is not None
    assert getattr(result.data, axis_name) is not None
    assert signal_name in result.data.signals
    assert result.data.signal_types[signal_name] == "voltage"
    assert len(result.data.signals[signal_name]) == len(
        getattr(result.data, axis_name)
    )


def test_real_op_keeps_mos_device_parameters_out_of_nodes_and_branches(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / "mos_device_parameters.cir",
        (
            "MOS device parameter identity\n"
            "Vd d 0 5\n"
            "Vg g 0 2\n"
            "M1 d g 0 0 NM\n"
            ".model NM NMOS(level=1 VTO=1 KP=1m)\n"
            ".save all @m1[id] @m1[gm] @m1[vgs] @m1[vds]\n"
            ".op\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is True
    assert result.data is not None
    expected_parameters = {"@m1[id]", "@m1[gm]", "@m1[vgs]", "@m1[vds]"}
    assert expected_parameters <= set(result.data.signals)
    assert {name: result.data.signal_types[name] for name in expected_parameters} == {
        "@m1[id]": "current",
        "@m1[gm]": "other",
        "@m1[vgs]": "voltage",
        "@m1[vds]": "voltage",
    }

    payload = result.data.op_result
    assert all(
        not str(row["name"]).startswith("@") for row in payload["nodes"]
    )
    assert all(
        not str(row["device"]).startswith("@") for row in payload["branches"]
    )
    device_rows = [
        row for row in payload["devices"] if str(row["device"]).casefold() == "m1"
    ]
    assert len(device_rows) == 1
    parameters = {
        item["name"]: item for item in device_rows[0]["key_parameters"]
    }
    assert set(parameters) == {"id", "gm", "vgs", "vds"}
    assert {name: item["unit"] for name, item in parameters.items()} == {
        "id": "A",
        "gm": "S",
        "vgs": "V",
        "vds": "V",
    }


def test_control_script_is_rejected_in_main_or_included_deck(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    direct = _write_netlist(
        tmp_path / "direct_control.cir",
        (
            "control script\n"
            "V1 in 0 1\n"
            ".control\nrun\n.endc\n"
            ".op\n.end\n"
        ),
    )
    included = _write_netlist(
        tmp_path / "script.lib",
        ".control\nrun\n.endc\n",
    )
    indirect = _write_netlist(
        tmp_path / "included_control.cir",
        (
            "included control script\n"
            f'.include "{included.as_posix()}"\n'
            "V1 in 0 1\nR1 in 0 1k\n.op\n.end\n"
        ),
    )

    direct_result = executor.execute(str(direct))
    indirect_result = executor.execute(str(indirect))

    assert direct_result.success is False
    assert direct_result.error.type is SimulationErrorType.PARAMETER_INVALID
    assert ".control" in direct_result.error.message
    assert indirect_result.success is False
    assert indirect_result.error.type is SimulationErrorType.PARAMETER_INVALID
    assert "script.lib" in indirect_result.error.message


@pytest.mark.parametrize(
    ("dependency_body", "message_fragment"),
    [
        (".tran 1n 10n\n", "分析指令"),
        (".control\nrun\n.endc\n", ".control"),
    ],
    ids=["analysis", "control"],
)
def test_incpslt_dependency_cannot_escape_single_analysis_policy(
    tmp_path: Path,
    dependency_body: str,
    message_fragment: str,
) -> None:
    executor = SpiceExecutor(timeout_seconds=5)
    _write_netlist(tmp_path / "hidden.lib", dependency_body)
    deck = _write_netlist(
        tmp_path / "incpslt_escape.cir",
        (
            "incpslt policy\n"
            ".incpslt hidden.lib\n"
            "V1 in 0 1\n"
            "R1 in 0 1k\n"
            ".op\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is False
    assert result.error.type is SimulationErrorType.PARAMETER_INVALID
    assert message_fragment in result.error.message
    assert result.source_digest == _closure_digest(deck)


def test_measure_type_mismatch_is_rejected_before_native_run(tmp_path: Path) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / "wrong_measure.cir",
        (
            "measure mismatch\n"
            "V1 in 0 AC 1\n"
            "R1 in out 1k\n"
            "C1 out 0 1u\n"
            ".measure tran peak MAX V(out)\n"
            ".ac dec 5 10 10k\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is False
    assert result.error.type is SimulationErrorType.PARAMETER_INVALID
    assert "@main:5" in result.error.message
    assert "TRAN" in result.error.message
    assert "AC" in result.error.message


def test_dependency_measure_is_bound_to_the_single_analysis_and_parsed(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    _write_netlist(
        tmp_path / "metrics.inc",
        ".measure tran peak_out MAX V(out)\n",
    )
    deck = _write_netlist(
        tmp_path / "dependency_measure.cir",
        (
            "dependency measure\n"
            ".include metrics.inc\n"
            "V1 in 0 PULSE(0 1 0 1n 1n 5u 10u)\n"
            "R1 in out 1k\n"
            "C1 out 0 10n\n"
            ".tran 100n 10u\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is True
    assert len(result.measurements) == 1
    measurement = result.measurements[0]
    assert measurement.name == "peak_out"
    assert measurement.status is MeasureStatus.OK
    assert measurement.value == pytest.approx(
        1.0 - math.exp(-0.5),
        rel=5e-3,
    )
    assert measurement.statement == ".measure tran peak_out MAX V(out)"


def test_missing_measure_outcome_is_a_structured_failure_not_silently_dropped(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    deck = _write_netlist(
        tmp_path / "failed_measure.cir",
        (
            "failed measure\n"
            "V1 out 0 PULSE(0 1 0 1n 1n 5u 10u)\n"
            ".measure tran unreachable WHEN V(out)=2\n"
            ".tran 100n 10u\n"
            ".end\n"
        ),
    )

    result = executor.execute(str(deck))

    assert result.success is True
    assert len(result.measurements) == 1
    measurement = result.measurements[0]
    assert measurement.name == "unreachable"
    assert measurement.status is MeasureStatus.FAILED
    assert measurement.value is None
    assert measurement.error_message
    assert measurement.statement == ".measure tran unreachable WHEN V(out)=2"

    persisted_payload = result.to_dict()
    persisted_payload["file_path"] = "circuits/failed_measure.cir"
    restored = type(result).from_dict(persisted_payload)
    assert restored.measurements is not None
    restored_measurement = restored.measurements[0]
    assert restored_measurement.status is MeasureStatus.FAILED
    assert restored_measurement.value is None
    assert restored_measurement.statement == measurement.statement
    assert restored_measurement.error_message == measurement.error_message


def _long_transient_deck(tmp_path: Path) -> Path:
    return _write_netlist(
        tmp_path / "long_running.cir",
        (
            "long transient\n"
            "V1 in 0 PULSE(0 1 0 1n 1n 50m 100m)\n"
            "R1 in out 1k\n"
            "C1 out 0 1u\n"
            ".tran 1n 100m\n"
            ".end\n"
        ),
    )


def _short_operating_point_deck(tmp_path: Path) -> Path:
    return _write_netlist(
        tmp_path / "recovery.cir",
        "recovery op\nV1 in 0 1\nR1 in 0 1k\n.op\n.end\n",
    )


def test_cancel_while_waiting_for_native_slot_returns_before_lock_release(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    recovery = _native_executor_or_skip()
    deck = _short_operating_point_deck(tmp_path)
    cancel_event = threading.Event()
    waiting = threading.Event()
    results = []
    original_wait = executor._wait_for_native_slot

    def observed_wait(**kwargs):
        waiting.set()
        return original_wait(**kwargs)

    monkeypatch.setattr(executor, "_wait_for_native_slot", observed_wait)
    spice_executor_module._SPICE_EXECUTION_LOCK.acquire()
    worker = threading.Thread(
        target=lambda: results.append(
            executor.execute(str(deck), cancel_signal=cancel_event)
        )
    )
    try:
        worker.start()
        assert waiting.wait(timeout=1)
        cancel_event.set()
        worker.join(timeout=1)
        assert not worker.is_alive()
        assert results[0].error.type is SimulationErrorType.CANCELLED
        assert results[0].source_digest == _closure_digest(deck)
    finally:
        spice_executor_module._SPICE_EXECUTION_LOCK.release()
        worker.join(timeout=1)

    assert recovery.execute(str(deck)).success is True


def test_total_timeout_expires_while_waiting_for_native_slot_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip(timeout_seconds=0.1)
    recovery = _native_executor_or_skip(timeout_seconds=5)
    deck = _short_operating_point_deck(tmp_path)
    waiting = threading.Event()
    results = []
    original_wait = executor._wait_for_native_slot

    def observed_wait(**kwargs):
        waiting.set()
        return original_wait(**kwargs)

    monkeypatch.setattr(executor, "_wait_for_native_slot", observed_wait)
    spice_executor_module._SPICE_EXECUTION_LOCK.acquire()
    worker = threading.Thread(target=lambda: results.append(executor.execute(str(deck))))
    try:
        worker.start()
        assert waiting.wait(timeout=1)
        worker.join(timeout=1)
        assert not worker.is_alive()
        assert results[0].error.type is SimulationErrorType.TIMEOUT
        assert results[0].source_digest == _closure_digest(deck)
    finally:
        spice_executor_module._SPICE_EXECUTION_LOCK.release()
        worker.join(timeout=1)

    assert recovery.execute(str(deck)).success is True


def test_destroy_and_load_time_reduce_native_run_budget(tmp_path: Path) -> None:
    class _SlowNative:
        initialized = True
        fatal_error_message = ""
        has_fatal_error = False

        def __init__(self) -> None:
            self.run_budgets: list[float] = []

        def destroy(self, *, deadline: float) -> bool:
            assert deadline > time.monotonic()
            time.sleep(0.03)
            return True

        def set_input_path(self, _path: Path) -> None:
            return None

        def load_netlist(self, _lines: list[str]) -> bool:
            time.sleep(0.03)
            return True

        def get_stdout(self) -> str:
            return ""

        def run(self, *, timeout_seconds: float, cancel_signal=None) -> None:
            self.run_budgets.append(timeout_seconds)
            raise NgSpiceTimeoutError("synthetic timeout")

    executor = SpiceExecutor(timeout_seconds=0.2)
    native = _SlowNative()
    executor._ngspice = native
    deck = _short_operating_point_deck(tmp_path)

    result = executor.execute(str(deck))

    assert result.error.type is SimulationErrorType.TIMEOUT
    assert len(native.run_budgets) == 1
    assert 0 < native.run_budgets[0] < 0.16
    assert result.source_digest == _closure_digest(deck)
    assert result.analysis_command == ".op"


def test_real_background_cancel_stops_worker_and_next_job_recovers(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip()
    cancel_event = threading.Event()
    long_deck = _long_transient_deck(tmp_path)
    expected_digest = _closure_digest(long_deck)
    timer = threading.Timer(0.05, cancel_event.set)
    timer.start()
    try:
        cancelled = executor.execute(
            str(long_deck),
            cancel_signal=cancel_event,
        )
    finally:
        timer.cancel()
        timer.join(timeout=1)

    recovered = executor.execute(str(_short_operating_point_deck(tmp_path)))

    assert cancel_event.is_set()
    assert cancelled.success is False
    assert cancelled.error.type is SimulationErrorType.CANCELLED
    assert cancelled.source_digest == expected_digest
    assert executor._ngspice.is_running() is False
    assert executor._ngspice.has_fatal_error is False
    assert recovered.success is True


def test_real_background_timeout_stops_worker_and_next_job_recovers(
    tmp_path: Path,
) -> None:
    executor = _native_executor_or_skip(timeout_seconds=0.01)
    recovery_executor = _native_executor_or_skip(timeout_seconds=5)
    long_deck = _long_transient_deck(tmp_path)
    expected_digest = _closure_digest(long_deck)

    timed_out = executor.execute(str(long_deck))
    recovered = recovery_executor.execute(str(_short_operating_point_deck(tmp_path)))

    assert timed_out.success is False
    assert timed_out.error.type is SimulationErrorType.TIMEOUT
    assert timed_out.source_digest == expected_digest
    assert executor._ngspice.is_running() is False
    assert executor._ngspice.has_fatal_error is False
    assert recovered.success is True


def _fake_background_wrapper() -> tuple[NgSpiceWrapper, list[str], dict[str, bool]]:
    wrapper = object.__new__(NgSpiceWrapper)
    wrapper._logger = logging.getLogger(__name__)
    wrapper._state_lock = threading.Lock()
    wrapper._fatal_error_message = None
    wrapper._initialized = True
    wrapper._run_started = threading.Event()
    wrapper._run_finished = threading.Event()
    commands: list[str] = []
    state = {"running": False}

    def execute_command(command: str) -> bool:
        commands.append(command)
        if command == "bg_run":
            state["running"] = True
            wrapper._run_started.set()
            return True
        if command == "bg_halt":
            state["running"] = False
            wrapper._run_finished.set()
            return True
        raise AssertionError(command)

    wrapper.execute_command = execute_command
    wrapper.is_running = lambda: state["running"]
    return wrapper, commands, state


def test_background_cancel_halts_native_worker_and_keeps_session_trusted() -> None:
    wrapper, commands, state = _fake_background_wrapper()
    cancelled = threading.Event()
    cancelled.set()

    with pytest.raises(NgSpiceCancelledError):
        wrapper.run(timeout_seconds=1, cancel_signal=cancelled)

    assert commands == ["bg_run", "bg_halt"]
    assert state["running"] is False
    assert wrapper.has_fatal_error is False


def test_background_timeout_halts_native_worker_and_keeps_session_trusted() -> None:
    wrapper, commands, state = _fake_background_wrapper()

    with pytest.raises(NgSpiceTimeoutError):
        wrapper.run(timeout_seconds=0.001)

    assert commands == ["bg_run", "bg_halt"]
    assert state["running"] is False
    assert wrapper.has_fatal_error is False


def test_background_timeout_does_not_add_hidden_callback_grace_period() -> None:
    wrapper, commands, state = _fake_background_wrapper()

    def execute_without_callbacks(command: str) -> bool:
        commands.append(command)
        if command == "bg_run":
            state["running"] = True
            return True
        if command == "bg_halt":
            state["running"] = False
            return True
        raise AssertionError(command)

    wrapper.execute_command = execute_without_callbacks
    started_at = time.monotonic()

    with pytest.raises(NgSpiceTimeoutError):
        wrapper.run(timeout_seconds=0.01)

    elapsed = time.monotonic() - started_at
    assert commands == ["bg_run", "bg_halt"]
    assert state["running"] is False
    assert wrapper.has_fatal_error is False
    assert elapsed < 0.1
