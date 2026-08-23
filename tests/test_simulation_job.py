from __future__ import annotations

import dataclasses
import datetime as dt

import pytest

from domain.simulation.models.simulation_job import JobOrigin, JobStatus, SimulationJob


def _job(tmp_path, *, origin=JobOrigin.UI_EDITOR) -> SimulationJob:
    return SimulationJob(
        circuit_file=str(tmp_path / "amp.cir"),
        project_root=str(tmp_path),
        origin=origin,
    )


def _bundle(tmp_path) -> tuple[str, str]:
    relative = "simulation_results/amp/run/result.json"
    absolute = str(tmp_path / "simulation_results" / "amp" / "run")
    return relative, absolute


def test_new_job_is_immutable_pending_snapshot_with_opaque_id(tmp_path):
    first = _job(tmp_path)
    second = _job(tmp_path)
    assert first.status is JobStatus.PENDING
    assert first.job_id.startswith("job_")
    assert first.job_id != second.job_id
    assert first.submitted_at.utcoffset() == dt.timedelta(0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.status = JobStatus.COMPLETED  # type: ignore[misc]


def test_transitions_return_new_snapshots_and_leave_old_values_unchanged(tmp_path):
    pending = _job(tmp_path)
    running = pending.start()
    result_path, export_root = _bundle(tmp_path)
    completed = running.complete(
        result_path=result_path,
        export_root=export_root,
    )

    assert pending.status is JobStatus.PENDING
    assert pending.started_at is None
    assert running.status is JobStatus.RUNNING
    assert running.started_at is not None
    assert completed.status is JobStatus.COMPLETED
    assert completed.finished_at is not None
    assert completed.result_path == result_path
    assert completed.export_root == export_root


def test_failure_requires_running_state_and_nonempty_message(tmp_path):
    pending = _job(tmp_path)
    with pytest.raises(ValueError, match="cannot enter failed"):
        pending.fail(error_message="bad")

    running = pending.start()
    with pytest.raises(ValueError, match="error_message"):
        running.fail(error_message="  ")
    failed = running.fail(error_message=" ngspice failed ")
    assert failed.status is JobStatus.FAILED
    assert failed.error_message == "ngspice failed"


def test_completion_requires_running_state_and_canonical_bundle(tmp_path):
    pending = _job(tmp_path)
    result_path, export_root = _bundle(tmp_path)
    with pytest.raises(ValueError, match="cannot enter completed"):
        pending.complete(result_path=result_path, export_root=export_root)

    running = pending.start()
    with pytest.raises(ValueError, match="both"):
        running.complete(result_path=result_path, export_root="")
    with pytest.raises(ValueError, match="result.json"):
        running.complete(
            result_path="simulation_results/amp/run/output.json",
            export_root=export_root,
        )
    with pytest.raises(ValueError, match="absolute"):
        running.complete(
            result_path=result_path,
            export_root="simulation_results/amp/run",
        )
    for invalid in (
        "other/amp/run/result.json",
        "simulation_results/amp/result.json",
        "simulation_results/bad:bundle/run/result.json",
        "simulation_results/amp/.__bundle_tmp__/result.json",
    ):
        with pytest.raises(ValueError, match="safe project-relative POSIX"):
            running.complete(result_path=invalid, export_root=export_root)


def test_cancelled_outcome_is_independent_from_prior_cancel_intent(tmp_path):
    pending = _job(tmp_path)
    authoritative_cancelled = pending.cancel()
    assert authoritative_cancelled.status is JobStatus.CANCELLED
    assert authoritative_cancelled.cancel_requested is False

    queued_cancelled = pending.request_cancellation().cancel()
    assert queued_cancelled.status is JobStatus.CANCELLED
    assert queued_cancelled.cancel_requested is True
    assert queued_cancelled.started_at is None

    running = _job(tmp_path).start().request_cancellation()
    result_path, export_root = _bundle(tmp_path)
    running_cancelled = running.cancel(
        result_path=result_path,
        export_root=export_root,
    )
    assert running_cancelled.status is JobStatus.CANCELLED
    assert running_cancelled.result_path == result_path


def test_cancel_request_does_not_override_an_authoritative_terminal_result(tmp_path):
    running = _job(tmp_path).start().request_cancellation()
    result_path, export_root = _bundle(tmp_path)

    completed = running.complete(
        result_path=result_path,
        export_root=export_root,
    )
    failed = running.fail(error_message="persisted executor failure")

    assert completed.status is JobStatus.COMPLETED
    assert completed.cancel_requested is True
    assert completed.result_path == result_path
    assert failed.status is JobStatus.FAILED
    assert failed.cancel_requested is True
    assert failed.error_message == "persisted executor failure"


def test_terminal_snapshot_rejects_all_transitions(tmp_path):
    result_path, export_root = _bundle(tmp_path)
    terminal = _job(tmp_path).start().complete(
        result_path=result_path,
        export_root=export_root,
    )
    with pytest.raises(ValueError):
        terminal.start()
    with pytest.raises(ValueError):
        terminal.fail(error_message="late")
    with pytest.raises(ValueError):
        terminal.request_cancellation().cancel()


def test_identity_and_state_shape_are_validated_at_construction(tmp_path):
    with pytest.raises(ValueError, match="absolute"):
        SimulationJob(
            circuit_file="relative.cir",
            project_root=str(tmp_path),
            origin=JobOrigin.UI_EDITOR,
        )
    with pytest.raises(ValueError, match="positive integer"):
        SimulationJob(
            circuit_file=str(tmp_path / "a.cir"),
            project_root=str(tmp_path),
            origin=JobOrigin.UI_EDITOR,
            version=0,
        )
    with pytest.raises(ValueError, match="running job"):
        SimulationJob(
            circuit_file=str(tmp_path / "a.cir"),
            project_root=str(tmp_path),
            origin=JobOrigin.UI_EDITOR,
            status=JobStatus.RUNNING,
        )
