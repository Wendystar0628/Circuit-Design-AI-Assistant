"""Concurrency regression tests for the process-global SPICE session."""

from __future__ import annotations

import logging
import threading
import time
from types import SimpleNamespace

from domain.simulation.executor.spice_executor import SpiceExecutor
from domain.simulation.models.simulation_error import (
    ErrorSeverity,
    SimulationError,
    SimulationErrorType,
)
from domain.simulation.models.simulation_result import create_error_result


def test_spice_execute_serializes_the_native_session_across_instances(tmp_path):
    """Two executor instances must never overlap their ngspice transaction.

    ``_run_simulation`` is replaced with a critical-section probe so the test
    is independent of the native ngspice DLL while still exercising the
    production process-global lock boundary.
    """
    active = 0
    max_active = 0
    state_lock = threading.Lock()
    start_together = threading.Barrier(3)
    errors = []

    def critical_section(**kwargs):
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.08)
            return create_error_result(
                executor="spice",
                file_path=kwargs["file_path"],
                analysis_type=kwargs["analysis_type"],
                error=SimulationError(
                    type=SimulationErrorType.NGSPICE_CRASH,
                    severity=ErrorSeverity.HIGH,
                    message="Synthetic serialization probe",
                    file_path=kwargs["file_path"],
                ),
                source_digest=kwargs["source_digest"],
                analysis_command=kwargs["analysis_command"],
            )
        finally:
            with state_lock:
                active -= 1

    circuit = tmp_path / "serialization.cir"
    circuit.write_text(
        "serialization test\nV1 out 0 1\n.tran 1n 2n\n.end\n",
        encoding="utf-8",
    )

    first = SpiceExecutor.__new__(SpiceExecutor)
    second = SpiceExecutor.__new__(SpiceExecutor)
    for executor in (first, second):
        executor._logger = logging.getLogger(__name__)
        executor._timeout_seconds = 2.0
        executor._init_error = None
        executor._ngspice = SimpleNamespace(
            initialized=True,
            fatal_error_message="",
        )
        executor._run_simulation = critical_section

    def run(executor):
        try:
            start_together.wait(timeout=2.0)
            executor.execute(str(circuit))
        except BaseException as exc:  # surfaced in the assertion below
            errors.append(exc)

    threads = [
        threading.Thread(target=run, args=(first,)),
        threading.Thread(target=run, args=(second,)),
    ]
    for thread in threads:
        thread.start()
    start_together.wait(timeout=2.0)
    for thread in threads:
        thread.join(timeout=2.0)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    assert max_active == 1
