import asyncio
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from domain.llm.agent.tools.run_simulation import RunSimulationTool
from domain.llm.agent.types import ToolContext
from domain.simulation.models.simulation_job import (
    DuplicateSimulationJobError,
    JobStatus,
)
from domain.simulation.models.simulation_result import (
    SimulationData,
    SimulationResult,
    create_success_result,
)
from shared.models.load_result import LoadResult


_SOURCE_DIGEST = "0" * 64


class _Repository:
    def __init__(self, result=None, result_path=""):
        self.result = result
        self.result_path = result_path

    def load(self, project_root, result_path):
        if self.result is not None and result_path == self.result_path:
            return LoadResult.ok(self.result, result_path)
        return LoadResult.file_missing(result_path)


class _Manager:
    def __init__(self, *, final_job=None, submit_error=None, await_error=None):
        self.final_job = final_job
        self.submit_error = submit_error
        self.await_error = await_error
        self.cancelled = []

    def submit(self, **kwargs):
        if self.submit_error:
            raise self.submit_error
        return SimpleNamespace(job_id="job-new")

    async def await_completion_async(self, job_id):
        if self.await_error:
            raise self.await_error
        return self.final_job

    def request_cancel(self, job_id):
        self.cancelled.append(job_id)
        return True


def _job(
    circuit_file: str,
    *,
    status=JobStatus.COMPLETED,
    result_path="simulation_results/amp/run-1/result.json",
    export_root="",
    error_message="",
    version=1,
    session_id="",
):
    return SimpleNamespace(
        job_id="job-new",
        circuit_file=circuit_file,
        status=status,
        version=version,
        session_id=session_id,
        result_path=result_path,
        export_root=export_root,
        error_message=error_message,
    )


def _context(tmp_path: Path, manager, repository):
    circuit = tmp_path / "circuits" / "amp.cir"
    circuit.parent.mkdir(parents=True, exist_ok=True)
    circuit.write_text("V1 in 0 1\n.tran 1n 1u\n.end\n", encoding="utf-8")
    return circuit, ToolContext(
        project_root=str(tmp_path),
        sim_job_manager=manager,
        sim_result_repository=repository,
    )


def _successful_result(
    circuit: Path,
    *,
    version: int = 1,
    session_id: str = "",
) -> SimulationResult:
    return create_success_result(
        executor="spice",
        file_path=str(circuit),
        analysis_type="tran",
        analysis_command=".tran 1n 1u",
        data=SimulationData(
            time=np.array([0.0, 1e-9, 1e-6]),
            signals={"V(in)": np.array([0.0, 1.0, 1.0])},
            signal_types={"V(in)": "voltage"},
        ),
        source_digest=_SOURCE_DIGEST,
        duration_seconds=0.25,
        version=version,
        session_id=session_id,
    )


def test_run_simulation_surfaces_atomic_duplicate_without_list_precheck(tmp_path: Path):
    duplicate = DuplicateSimulationJobError(
        existing_job_id="job-existing",
        circuit_file=str(tmp_path / "circuits" / "amp.cir"),
        status=JobStatus.RUNNING,
    )
    manager = _Manager(submit_error=duplicate)
    circuit, context = _context(tmp_path, manager, _Repository())
    response = asyncio.run(
        RunSimulationTool().execute(
            "call", {"file_path": str(circuit)}, context
        )
    )
    assert response.is_error is True
    assert response.details["duplicate"] is True
    assert response.details["job_id"] == "job-existing"
    assert "already active" in response.content
    assert not hasattr(manager, "list")


def test_run_simulation_requires_explicit_file_path_even_with_active_editor(tmp_path: Path):
    manager = _Manager()
    circuit, context = _context(tmp_path, manager, _Repository())
    context.current_file = str(circuit)
    response = asyncio.run(RunSimulationTool().execute("call", {}, context))
    assert response.is_error is True
    assert "editor-active-file fallback does not exist" in response.content
    assert RunSimulationTool().parameters["required"] == ["file_path"]


def test_run_simulation_completed_without_readable_bundle_is_error(tmp_path: Path):
    circuit = tmp_path / "circuits" / "amp.cir"
    bundle = tmp_path / "simulation_results" / "amp" / "run-1"
    bundle.mkdir(parents=True)
    manager = _Manager(
        final_job=_job(str(circuit), export_root=str(bundle.resolve()))
    )
    circuit, context = _context(tmp_path, manager, _Repository())
    response = asyncio.run(
        RunSimulationTool().execute("call", {"file_path": str(circuit)}, context)
    )
    assert response.is_error is True
    assert "reported COMPLETED" in response.content
    assert "result bundle is unreadable" in response.content


def test_run_simulation_success_returns_exact_handle(tmp_path: Path):
    circuit = tmp_path / "circuits" / "amp.cir"
    bundle = tmp_path / "simulation_results" / "amp" / "run-1"
    bundle.mkdir(parents=True)
    result_path = "simulation_results/amp/run-1/result.json"
    result = _successful_result(circuit)
    manager = _Manager(
        final_job=_job(
            str(circuit),
            result_path=result_path,
            export_root=str(bundle.resolve()),
        )
    )
    circuit, context = _context(
        tmp_path, manager, _Repository(result, result_path)
    )
    response = asyncio.run(
        RunSimulationTool().execute("call", {"file_path": str(circuit)}, context)
    )
    assert response.is_error is False
    assert response.details["result_path"] == result_path
    assert response.details["export_root"] == str(bundle.resolve())
    assert response.details["analysis_type"] == "tran"
    assert f"- result_path: {result_path}" in response.content


@pytest.mark.parametrize(
    ("job_version", "job_session", "result_version", "result_session", "reason"),
    [
        (2, "session-a", 1, "session-a", "persisted version"),
        (2, "session-a", 2, "session-b", "persisted session_id"),
    ],
)
def test_run_simulation_rejects_persisted_result_from_another_job_identity(
    tmp_path: Path,
    job_version: int,
    job_session: str,
    result_version: int,
    result_session: str,
    reason: str,
):
    circuit = tmp_path / "circuits" / "amp.cir"
    bundle = tmp_path / "simulation_results" / "amp" / "run-1"
    bundle.mkdir(parents=True)
    result_path = "simulation_results/amp/run-1/result.json"
    result = _successful_result(
        circuit,
        version=result_version,
        session_id=result_session,
    )
    manager = _Manager(
        final_job=_job(
            str(circuit),
            result_path=result_path,
            export_root=str(bundle.resolve()),
            version=job_version,
            session_id=job_session,
        )
    )
    circuit, context = _context(
        tmp_path, manager, _Repository(result, result_path)
    )

    response = asyncio.run(
        RunSimulationTool().execute("call", {"file_path": str(circuit)}, context)
    )

    assert response.is_error is True
    assert reason in response.content
    assert response.details["contract_error"].startswith(reason)


def test_run_simulation_wait_timeout_is_model_visible_and_requests_cancel(tmp_path: Path):
    manager = _Manager(await_error=TimeoutError("worker deadline"))
    circuit, context = _context(tmp_path, manager, _Repository())
    response = asyncio.run(
        RunSimulationTool().execute("call", {"file_path": str(circuit)}, context)
    )
    assert response.is_error is True
    assert response.details["status"] == "timeout"
    assert manager.cancelled == ["job-new"]


def test_run_simulation_async_cancellation_propagates(tmp_path: Path):
    manager = _Manager(await_error=asyncio.CancelledError())
    circuit, context = _context(tmp_path, manager, _Repository())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            RunSimulationTool().execute(
                "call", {"file_path": str(circuit)}, context
            )
        )
    assert manager.cancelled == ["job-new"]
