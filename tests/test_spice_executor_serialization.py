"""Concurrency regression tests for the process-global SPICE session."""

from __future__ import annotations

import threading
import time

from domain.simulation.executor.spice_executor import SpiceExecutor


def test_spice_execute_serializes_the_entire_session_across_instances():
    """Two executor instances must never overlap their ngspice transaction.

    ``_execute_exclusive`` is replaced with a critical-section probe so the
    test is independent of the native ngspice DLL while still exercising the
    production ``execute`` lock boundary.
    """
    active = 0
    max_active = 0
    state_lock = threading.Lock()
    start_together = threading.Barrier(3)
    errors = []

    def critical_section(_file_path, _analysis_config):
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.08)
            return object()
        finally:
            with state_lock:
                active -= 1

    first = SpiceExecutor.__new__(SpiceExecutor)
    second = SpiceExecutor.__new__(SpiceExecutor)
    first._execute_exclusive = critical_section
    second._execute_exclusive = critical_section

    def run(executor):
        try:
            start_together.wait(timeout=2.0)
            executor.execute("dummy.cir", {"analysis_type": "tran"})
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

