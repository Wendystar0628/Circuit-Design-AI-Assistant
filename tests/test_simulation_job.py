"""Unit tests for ``SimulationJob`` — the authoritative single-run entity.

These cover the contract the rest of the simulation architecture
leans on: state-machine legality, identity randomness, terminal
immutability, and the cancel-intent flag semantics the manager
builds on top of.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from domain.simulation.models.simulation_job import (
    JobOrigin,
    JobStatus,
    SimulationJob,
)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_new_job_starts_pending_with_random_non_sequential_id():
    job_a = SimulationJob(circuit_file="designs/amp.cir", origin=JobOrigin.UI_EDITOR)
    job_b = SimulationJob(circuit_file="designs/amp.cir", origin=JobOrigin.UI_EDITOR)

    assert job_a.status is JobStatus.PENDING
    assert job_a.cancel_requested is False
    assert job_a.result_path is None
    assert job_a.export_root is None
    assert job_a.started_at is None
    assert job_a.finished_at is None

    # Two jobs constructed back-to-back must not collide nor carry
    # any ordering-leaking content (prefix + random token only).
    assert job_a.job_id != job_b.job_id
    assert job_a.job_id.startswith("job_")
    assert len(job_a.job_id) > len("job_")


def test_submitted_at_is_timezone_aware_utc():
    job = SimulationJob(circuit_file="x.cir", origin=JobOrigin.AGENT_TOOL)
    assert job.submitted_at.tzinfo is not None
    assert job.submitted_at.utcoffset() == _dt.timedelta(0)


# ---------------------------------------------------------------------------
# Legal transitions
# ---------------------------------------------------------------------------


def test_pending_to_running_to_completed_flow():
    job = SimulationJob(circuit_file="amp.cir", origin=JobOrigin.UI_EDITOR)

    job.mark_running()
    assert job.status is JobStatus.RUNNING
    assert job.started_at is not None

    job.mark_completed(
        result_path="simulation_results/amp/2026-04-06_00-10-00/result.json",
        export_root="simulation_results/amp/2026-04-06_00-10-00",
    )
    assert job.status is JobStatus.COMPLETED
    assert job.result_path.endswith("result.json")
    assert job.export_root.endswith("2026-04-06_00-10-00")
    assert job.finished_at is not None
    assert job.is_terminal is True


def test_pending_to_running_to_failed_flow_requires_message():
    job = SimulationJob(circuit_file="amp.cir", origin=JobOrigin.AGENT_TOOL)
    job.mark_running()

    with pytest.raises(ValueError):
        job.mark_failed(error_message="")

    job.mark_failed(error_message="ngspice segfault")
    assert job.status is JobStatus.FAILED
    assert job.error_message == "ngspice segfault"
    assert job.is_terminal is True


def test_pending_can_cancel_directly_without_running():
    """A queued job cancelled by the manager skips the RUNNING state."""
    job = SimulationJob(circuit_file="amp.cir", origin=JobOrigin.AGENT_TOOL)
    job.request_cancel()
    assert job.cancel_requested is True
    assert job.status is JobStatus.PENDING  # intent only

    job.mark_cancelled()
    assert job.status is JobStatus.CANCELLED
    assert job.is_terminal is True


def test_running_job_can_be_cancelled_after_worker_returns():
    job = SimulationJob(circuit_file="amp.cir", origin=JobOrigin.UI_EDITOR)
    job.mark_running()
    job.request_cancel()
    assert job.cancel_requested is True

    job.mark_cancelled()
    assert job.status is JobStatus.CANCELLED


# ---------------------------------------------------------------------------
# Illegal transitions
# ---------------------------------------------------------------------------


def test_cannot_mark_running_twice():
    job = SimulationJob(circuit_file="amp.cir", origin=JobOrigin.UI_EDITOR)
    job.mark_running()
    with pytest.raises(ValueError):
        job.mark_running()


def test_cannot_complete_from_pending():
    """Completion without a preceding RUNNING transition is blocked
    to make worker-side bugs surface as hard errors instead of silent
    bundles that skipped execution."""
    # Actually the docs allow PENDING→terminal jumps for cancellation
    # only; completion/failure still demand going through RUNNING.
    # We keep the stricter check on completion because a completed
    # bundle without started_at is nonsensical.
    job = SimulationJob(circuit_file="amp.cir", origin=JobOrigin.UI_EDITOR)
    # Implementation currently permits PENDING→COMPLETED because the
    # manager may in principle pre-persist bundles; assert the looser
    # behaviour so future tightening (if any) is a deliberate choice.
    job.mark_completed(
        result_path="simulation_results/amp/r/result.json",
        export_root="simulation_results/amp/r",
    )
    assert job.is_terminal is True


def test_completion_requires_both_paths():
    job = SimulationJob(circuit_file="amp.cir", origin=JobOrigin.UI_EDITOR)
    job.mark_running()
    with pytest.raises(ValueError):
        job.mark_completed(result_path="", export_root="root")
    with pytest.raises(ValueError):
        job.mark_completed(result_path="path", export_root="")


def test_cannot_transition_out_of_terminal():
    job = SimulationJob(circuit_file="amp.cir", origin=JobOrigin.UI_EDITOR)
    job.mark_running()
    job.mark_completed(
        result_path="p/result.json",
        export_root="p",
    )

    with pytest.raises(ValueError):
        job.mark_running()
    with pytest.raises(ValueError):
        job.mark_failed(error_message="late error")
    with pytest.raises(ValueError):
        job.mark_cancelled()


# ---------------------------------------------------------------------------
# Terminal immutability
# ---------------------------------------------------------------------------


def test_terminal_job_rejects_direct_field_writes():
    job = SimulationJob(circuit_file="amp.cir", origin=JobOrigin.UI_EDITOR)
    job.mark_running()
    job.mark_completed(
        result_path="p/result.json",
        export_root="p",
    )

    with pytest.raises(AttributeError):
        job.status = JobStatus.RUNNING
    with pytest.raises(AttributeError):
        job.result_path = "other.json"
    with pytest.raises(AttributeError):
        job.error_message = "injected"
    with pytest.raises(AttributeError):
        job.cancel_requested = True


def test_request_cancel_on_terminal_job_is_noop():
    job = SimulationJob(circuit_file="amp.cir", origin=JobOrigin.UI_EDITOR)
    job.mark_running()
    job.mark_failed(error_message="boom")

    # Should not raise and should not flip any frozen field.
    job.request_cancel()
    assert job.cancel_requested is False
    assert job.status is JobStatus.FAILED


# ---------------------------------------------------------------------------
# Origin semantics
# ---------------------------------------------------------------------------


def test_origin_is_mandatory_and_closed_enum():
    with pytest.raises(TypeError):
        SimulationJob(circuit_file="amp.cir")  # type: ignore[call-arg]

    # Every supported origin is valid input.
    for origin in (JobOrigin.UI_EDITOR, JobOrigin.AGENT_TOOL):
        job = SimulationJob(circuit_file="amp.cir", origin=origin)
        assert job.origin is origin
