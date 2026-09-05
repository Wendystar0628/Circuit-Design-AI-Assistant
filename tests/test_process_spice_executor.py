"""The parent must remain usable after actual worker hangs and crashes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from domain.simulation.executor import process_spice_executor as process_module
from domain.simulation.executor.process_spice_executor import ProcessSpiceExecutor
from domain.simulation.models.simulation_error import SimulationErrorType


def _deck(tmp_path: Path) -> Path:
    path = tmp_path / "divider.cir"
    path.write_text(
        "Resistor divider\nV1 in 0 10\nR1 in out 1k\nR2 out 0 1k\n.op\n.end\n",
        encoding="utf-8",
    )
    return path


def _record_processes(monkeypatch) -> list[subprocess.Popen]:
    processes = []
    original = subprocess.Popen

    def launch(*args, **kwargs):
        if os.name == "nt":
            assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
        assert kwargs["stdout"] is not subprocess.PIPE
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(process_module.subprocess, "Popen", launch)
    return processes


def test_parent_constructor_does_not_initialize_native_dll(monkeypatch):
    from domain.simulation.executor.spice_executor import SpiceExecutor

    def forbidden(*args, **kwargs):
        pytest.fail("The API process must never construct the native executor")

    monkeypatch.setattr(SpiceExecutor, "__init__", forbidden)
    executor = ProcessSpiceExecutor()
    assert executor.get_name() == "spice"
    assert executor.can_handle("amplifier.CIR")


def test_hard_deadline_kills_worker_even_when_native_call_cannot_cooperate(
    monkeypatch, tmp_path
):
    executor = ProcessSpiceExecutor(timeout_seconds=0.15)
    monkeypatch.setattr(
        executor, "_worker_command",
        lambda *_: [sys.executable, "-c", "import time; time.sleep(30)"],
    )
    processes = _record_processes(monkeypatch)
    started = time.monotonic()
    result = executor.execute(str(_deck(tmp_path)))
    assert result.error.type is SimulationErrorType.TIMEOUT
    assert time.monotonic() - started < 2.0
    assert len(processes) == 1
    assert processes[0].poll() is not None


def test_running_cancellation_reaps_worker(monkeypatch, tmp_path):
    executor = ProcessSpiceExecutor(timeout_seconds=10)
    monkeypatch.setattr(
        executor, "_worker_command",
        lambda *_: [sys.executable, "-c", "import time; time.sleep(30)"],
    )
    processes = _record_processes(monkeypatch)
    cancellation = threading.Event()
    timer = threading.Timer(0.1, cancellation.set)
    timer.start()
    try:
        result = executor.execute(str(_deck(tmp_path)), cancel_signal=cancellation)
    finally:
        timer.cancel()
        timer.join()
    assert result.error.type is SimulationErrorType.CANCELLED
    assert len(processes) == 1
    assert processes[0].poll() is not None


def test_experiment_budget_controls_parent_deadline(monkeypatch, tmp_path):
    from domain.simulation.models.experiment import ExperimentSpec

    executor = ProcessSpiceExecutor(timeout_seconds=30)
    monkeypatch.setattr(
        executor, "_worker_command",
        lambda *_: [sys.executable, "-c", "import time; time.sleep(30)"],
    )
    started = time.monotonic()
    result = executor.execute(
        str(_deck(tmp_path)), experiment=ExperimentSpec(timeout_seconds=0.1)
    )
    assert result.error.type is SimulationErrorType.TIMEOUT
    assert "0.1" in result.error.message
    assert time.monotonic() - started < 2.0


def test_interrupted_run_keeps_replay_inputs_without_claiming_execution_inputs(
    monkeypatch, tmp_path
):
    from domain.simulation.models.experiment import ExperimentSpec
    from domain.simulation.spice.source_closure import capture_spice_source_snapshot

    deck = _deck(tmp_path)
    snapshot = capture_spice_source_snapshot(deck)
    experiment = ExperimentSpec(analysis_command=".op", timeout_seconds=0.1)
    executor = ProcessSpiceExecutor()
    monkeypatch.setattr(
        executor, "_worker_command",
        lambda *_: [sys.executable, "-c", "import time; time.sleep(30)"],
    )
    result = executor.execute(
        str(deck), experiment=experiment, source_snapshot=snapshot,
    )
    assert result.error.type is SimulationErrorType.TIMEOUT
    assert result.source_digest is None
    assert result.provenance["original_source"] == snapshot
    assert result.provenance["experiment"] == experiment.to_dict()
    assert result.provenance["effective_source"] is None
    assert result.provenance["runtime"] is None


def test_cancelled_submission_does_not_start_a_worker(monkeypatch, tmp_path):
    cancellation = threading.Event()
    cancellation.set()
    processes = _record_processes(monkeypatch)
    result = ProcessSpiceExecutor().execute(
        str(_deck(tmp_path)), cancel_signal=cancellation
    )
    assert result.error.type is SimulationErrorType.CANCELLED
    assert processes == []


def test_worker_crash_preserves_diagnostics_and_allows_next_real_simulation(
    monkeypatch, tmp_path
):
    from infrastructure.utils.ngspice_config import configure_ngspice

    if not configure_ngspice():
        pytest.skip("Native ngspice is unavailable")
    executor = ProcessSpiceExecutor(timeout_seconds=10)
    command = executor._worker_command
    processes = _record_processes(monkeypatch)
    monkeypatch.setattr(
        executor, "_worker_command",
        lambda *_: [
            sys.executable, "-c",
            "import os; print('native crash evidence', flush=True); os._exit(23)",
        ],
    )
    deck = _deck(tmp_path)
    crashed = executor.execute(str(deck))
    assert crashed.error.type is SimulationErrorType.NGSPICE_CRASH
    assert "23" in crashed.error.message
    assert "native crash evidence" in crashed.raw_output
    assert processes[0].poll() == 23
    monkeypatch.setattr(executor, "_worker_command", command)
    recovered = executor.execute(str(deck))
    assert recovered.success, (recovered.error, recovered.raw_output)
    assert recovered.data.signals["V(out)"][0] == pytest.approx(5.0)
    assert recovered.provenance is not None
    assert recovered.provenance["engine"]["execution_mode"] == "isolated_process"
    assert recovered.provenance["engine"]["version"]
    assert processes[1].pid != processes[0].pid
    assert processes[1].poll() == 0
    assert not Path(processes[1].args[-2]).parent.exists()


def test_real_worker_runs_captured_dependencies_and_explicit_experiment_after_deletion(
    tmp_path,
):
    from domain.simulation.models.experiment import ExperimentSpec
    from domain.simulation.spice.source_closure import capture_spice_source_snapshot
    from infrastructure.utils.ngspice_config import configure_ngspice

    if not configure_ngspice():
        pytest.skip("Native ngspice is unavailable")
    deck = tmp_path / "parameterized.cir"
    dependency = tmp_path / "resistor.inc"
    deck.write_text(
        "Parameterized divider\n.param resistance=1k\n.include resistor.inc\n"
        "V1 in 0 10\nR1 in out 1k\n.op\n.end\n",
        encoding="utf-8",
    )
    dependency.write_text("R2 out 0 {resistance}\n", encoding="utf-8")
    snapshot = capture_spice_source_snapshot(deck)
    deck.unlink()
    dependency.unlink()
    experiment = ExperimentSpec(
        analysis_command=".op", parameters={"resistance": "3k"},
        solver_options={"reltol": "1e-5"}, timeout_seconds=10,
    )
    result = ProcessSpiceExecutor().execute(
        str(deck), experiment=experiment, source_snapshot=snapshot,
    )
    assert result.success, (result.error, result.raw_output)
    assert result.data.signals["V(out)"][0] == pytest.approx(7.5)
    assert result.provenance["original_source"] == snapshot
    assert result.provenance["experiment"] == experiment.to_dict()


def test_worker_protocol_rejects_wrong_circuit_identity(monkeypatch, tmp_path):
    from domain.simulation.models.simulation_error import ErrorSeverity, SimulationError
    from domain.simulation.models.simulation_result import create_error_result

    wrong_result = create_error_result(
        executor="spice", file_path=str(tmp_path / "wrong.cir"),
        analysis_type="unknown",
        error=SimulationError(
            type=SimulationErrorType.FILE_ACCESS,
            severity=ErrorSeverity.HIGH, message="missing",
        ),
    )
    payload = {
        "protocol_version": 1, "result": wrong_result.to_dict(), "provenance": None,
    }
    fixture = tmp_path / "response-fixture.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    executor = ProcessSpiceExecutor(timeout_seconds=5)
    monkeypatch.setattr(
        executor, "_worker_command",
        lambda request, response: [
            sys.executable, "-c",
            "import shutil, sys; shutil.copyfile(sys.argv[1], sys.argv[2])",
            str(fixture), str(response),
        ],
    )
    result = executor.execute(str(_deck(tmp_path)))
    assert result.error.type is SimulationErrorType.NGSPICE_CRASH
    assert "different circuit" in result.error.message


def test_frozen_worker_command_uses_private_entry_point(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    request = tmp_path / "request.json"
    response = tmp_path / "response.json"
    assert ProcessSpiceExecutor._worker_command(request, response) == [
        sys.executable, "--simulation-worker", str(request), str(response),
    ]


def test_packaged_entry_routes_worker_without_starting_api(monkeypatch):
    from desktop_backend import __main__ as entry
    from domain.simulation.executor import spice_worker

    calls = []
    monkeypatch.setattr(spice_worker, "main", lambda argv: calls.append(argv))
    monkeypatch.setattr(sys, "argv", [
        "desktop_backend.exe", "--simulation-worker", "request.json", "response.json"
    ])
    entry.main()
    assert calls == [["request.json", "response.json"]]
