"""Professional-study HTTP workflows exercise real isolated ngspice workers."""

from __future__ import annotations

import copy
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from application.runtime import ApplicationRuntime, ProjectIdentity
from desktop_backend.app import create_app
from domain.services.simulation_job_manager import SimulationJobManager
from domain.services.simulation_service import SimulationService
from domain.simulation.executor.process_spice_executor import ProcessSpiceExecutor
from domain.simulation.service.simulation_result_repository import SimulationResultRepository


TOKEN = "c" * 64
PROJECT_ID = "professional-study-project"
BASE = f"/api/v1/projects/{PROJECT_ID}"
STUDIES = BASE + "/simulation-studies"


class _Runtime(ApplicationRuntime):
    async def start(self):
        pass

    async def stop(self):
        pass


class _GatedNativeExecutor(ProcessSpiceExecutor):
    """Hold the native boundary so HTTP edits/cancellation have deterministic timing."""

    def __init__(self):
        super().__init__(timeout_seconds=10)
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def execute(self, file_path, **kwargs):
        self.entered.set()
        assert self.release.wait(timeout=15), "test did not release its native worker"
        return super().execute(file_path, **kwargs)


@pytest.fixture
def native_api(tmp_path):
    from infrastructure.utils.ngspice_config import configure_ngspice

    if not configure_ngspice():
        pytest.skip("Native ngspice is unavailable")
    runtime = _Runtime()
    runtime._project = ProjectIdentity(PROJECT_ID, str(tmp_path), tmp_path.name, 1)
    runtime.session_state_manager = SimpleNamespace(get_current_session_id=lambda: "study-session")
    runtime.simulation_result_repository = SimulationResultRepository()
    executor = _GatedNativeExecutor()
    manager = SimulationJobManager(
        simulation_service=SimulationService(executor=executor),
        result_repository=runtime.simulation_result_repository,
        max_workers=1,
    )
    runtime.simulation_job_manager = manager
    app = create_app(TOKEN, "http://localhost:5173", runtime=runtime)
    try:
        with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
            yield SimpleNamespace(
                client=client, runtime=runtime, root=tmp_path, executor=executor,
                manager=manager,
            )
    finally:
        executor.release.set()
        manager.close(timeout=15)


def _divider(api, *, failed_measurement=False):
    source = api.root / "divider.cir"
    source.write_text(
        "Parameterized divider\n.param vdd=10 rseries=1k rload=1k\n"
        "V1 in 0 {vdd}\nR1 in out {rseries}\n.include load.inc\n"
        ".tran 1u 10u 0 1u\n.measure tran vout FIND v(out) AT=5u\n"
        + (".measure tran never_cross WHEN v(out)=99 RISE=1\n" if failed_measurement else "")
        + ".end\n",
        encoding="utf-8",
    )
    dependency = api.root / "load.inc"
    dependency.write_text(
        "R2 out 0 {rload}\n.model DTEST D(IS=1e-14)\nD1 0 out DTEST\n",
        encoding="utf-8",
    )
    return source, dependency


def _submit(api, **request):
    response = api.client.post(STUDIES, json={"circuit_path": "divider.cir", **request})
    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["project_id"] == PROJECT_ID
    return payload["study"]


def _finish(api, study):
    # Waiting on the actual jobs avoids timing-sensitive HTTP polling.
    for case in study["cases"]:
        if case.get("job_id"):
            api.manager.await_completion(case["job_id"], timeout=15)
    response = api.client.get(f"{STUDIES}/{study['study_id']}")
    assert response.status_code == 200, response.text
    return response.json()["study"]


def _workbench(api, case):
    assert case["result_id"], case
    response = api.client.get(f"{BASE}/simulation-results/{case['result_id']}/workbench")
    assert response.status_code == 200, response.text
    return response.json()


def test_corner_matrix_keeps_native_measurements_limits_and_model_history(native_api):
    api = native_api
    source, dependency = _divider(api, failed_measurement=True)
    original_source = source.read_bytes()
    binding = {
        "name": "DTEST", "kind": "model", "source": "Measured diode fit",
        "version": "1.0", "voltage_range": {"min": 0, "max": 12},
        "frequency_range": {"min": 0, "max": 1e6},
        "temperature_range": {"min": -20, "max": 100},
        "simplified": True, "assumptions": ["Reverse leakage approximation"],
    }
    experiment = {
        "timeout_seconds": 10,
        "model_bindings": [binding],
        "acceptance_constraints": [
            {"id": "voltage", "metric": "vout", "unit": "V", "lower": 4, "upper": 6},
            {"id": "crossing", "metric": "never_cross", "unit": "s", "lower": -1, "upper": 1},
        ],
    }
    api.executor.release.clear()
    study = _submit(
        api, kind="corner", experiment=experiment,
        axes=[
            {"kind": "parameter", "parameter": "rseries", "values": ["1k"]},
            {"kind": "temperature", "values": [25, 85]},
            {"kind": "supply", "parameter": "vdd", "values": [10]},
            {"kind": "load", "parameter": "rload", "values": ["1k", "3k"]},
        ],
    )
    assert len(study["cases"]) == 4
    assert api.executor.entered.wait(timeout=3)
    # Edits made while jobs are queued must affect only future submissions.
    dependency.write_text(
        "R2 out 0 100k\n.model DTEST D(IS=1e-3)\nD1 0 out DTEST\n",
        encoding="utf-8",
    )
    experiment["acceptance_constraints"][0]["upper"] = 100
    binding["version"] = "2.0"
    api.executor.release.set()
    final = _finish(api, study)
    assert final["status"] == "completed", final
    assert len({case["job_id"] for case in final["cases"]}) == 4
    assert len({case["result_id"] for case in final["cases"]}) == 4
    assert len({case["result_path"] for case in final["cases"]}) == 4
    assert source.read_bytes() == original_source
    historical = []
    for case in final["cases"]:
        result = _workbench(api, case)
        assert result["result"]["success"] is True
        expected = 5.0 if case["experiment"]["parameters"]["rload"] == "1k" else 7.5
        metrics = {metric["name"]: metric for metric in result["metrics"]}
        assert metrics["vout"]["value"] == pytest.approx(expected, abs=1e-4)
        assert metrics["never_cross"]["value"] is None
        assert metrics["never_cross"]["status"] == "FAILED"
        provenance = result["provenance"]
        assert provenance["experiment"]["acceptance_constraints"][0]["upper"] == 6
        rows = {row["id"]: row for row in provenance["acceptance"]["rows"]}
        assert rows["voltage"]["status"] == ("PASS" if expected == 5 else "FAIL")
        assert rows["crossing"]["status"] == "NOT_MEASURED"
        assert rows["crossing"]["value"] is None
        model = next(model for model in provenance["models"] if model["name"].casefold() == "dtest")
        assert model["version"] == "1.0"
        assert model["source"] == "Measured diode fit"
        assert model["simplified"] is True
        assert model["binding_status"] == "matched"
        assert model["definition_digest"]
        historical.append((case, copy.deepcopy(provenance)))
    voltage = next(metric for metric in final["summary"]["metrics"] if metric["name"] == "vout")
    assert voltage["min"] == pytest.approx(5.0, abs=1e-4)
    assert voltage["max"] == pytest.approx(7.5, abs=1e-4)
    assert voltage["delta"] == pytest.approx(2.5, abs=1e-4)
    assert voltage["measured_cases"] == 4
    assert final["summary"]["acceptance_status"] == "FAIL"
    # History must remain inspectable after the workspace source graph disappears.
    source.unlink()
    dependency.unlink()
    api.runtime.simulation_study_service = None
    restored = api.client.get(f"{STUDIES}/{study['study_id']}")
    assert restored.status_code == 200, restored.text
    assert restored.json()["study"]["status"] == "completed"
    for case, provenance in historical:
        assert _workbench(api, case)["provenance"] == provenance
    listing = api.client.get(STUDIES)
    assert listing.status_code == 200, listing.text
    assert [item["study_id"] for item in listing.json()["studies"]] == [study["study_id"]]


def test_numerical_study_runs_and_retains_two_native_results_with_explicit_cost(native_api):
    api = native_api
    _divider(api)
    study = _submit(
        api, kind="numerical",
        experiment={"solver_options": {"reltol": 0.001}, "timeout_seconds": 10},
        numerical={
            "metrics": [{"name": "vout", "unit": "V", "absolute_tolerance": 1e-5,
                         "relative_tolerance": 0.001}],
            "tolerance_factor": 0.1, "max_timestep_factor": 0.5,
        },
    )
    final = _finish(api, study)
    assert final["status"] == "completed", final
    assert len(final["cases"]) == 2
    assert len({case["result_id"] for case in final["cases"]}) == 2
    results = [_workbench(api, case) for case in final["cases"]]
    assert all(result["result"]["success"] for result in results)
    for result in results:
        metric = next(item for item in result["metrics"] if item["name"] == "vout")
        assert metric["value"] == pytest.approx(5.0, abs=1e-5)
        assert result["provenance"]["engine"]["execution_mode"] == "isolated_process"
    baseline, refined = [result["provenance"]["experiment"] for result in results]
    assert float(refined["solver_options"]["reltol"]) < float(baseline["solver_options"]["reltol"])
    assert baseline["analysis_command"] != refined["analysis_command"]
    comparison = final["summary"]["numerical"]
    assert comparison["status"] == "stable", comparison
    assert comparison["stable"] is True
    metric = comparison["metrics"][0]
    assert metric["baseline_value"] == pytest.approx(5, abs=1e-5)
    assert metric["refined_value"] == pytest.approx(5, abs=1e-5)
    assert metric["absolute_delta"] <= metric["allowed_delta"]
    assert metric["allowed_delta"] == pytest.approx(1e-5 + 0.001 * abs(metric["baseline_value"]))
    cost = comparison["cost"]
    assert cost["baseline_seconds"] > 0
    assert cost["refined_seconds"] > 0
    assert cost["total_seconds"] == pytest.approx(cost["baseline_seconds"] + cost["refined_seconds"])


def test_case_cancellation_does_not_cancel_its_native_sibling(native_api):
    api = native_api
    _divider(api)
    api.executor.release.clear()
    study = _submit(
        api, kind="corner", axes=[{"kind": "load", "parameter": "rload", "values": ["1k", "3k"]}],
    )
    assert api.executor.entered.wait(timeout=3)
    cancelled_id = study["cases"][1]["case_id"]
    response = api.client.post(
        f"{STUDIES}/{study['study_id']}/cancel", json={"case_id": cancelled_id},
    )
    assert response.status_code == 200, response.text
    api.executor.release.set()
    final = _finish(api, study)
    survivor, cancelled = final["cases"]
    assert survivor["status"] == "completed", survivor
    assert cancelled["status"] == "cancelled", cancelled
    assert cancelled["result_id"] is None
    assert cancelled["result_path"] is None
    assert _workbench(api, survivor)["result"]["success"] is True


def test_failed_native_corner_is_retained_and_excluded_from_numeric_summary(native_api):
    api = native_api
    source, _dependency = _divider(api)
    source.write_text(
        source.read_text(encoding="utf-8")
        .replace("rload=1k", "rload=1k selector=1")
        .replace("V1 in 0 {vdd}", "V1 in 0 {vdd/selector}"),
        encoding="utf-8",
    )
    study = _submit(
        api, kind="corner",
        axes=[{"kind": "parameter", "parameter": "selector", "values": [1, 0]}],
        experiment={"acceptance_constraints": [
            {"metric": "vout", "unit": "V", "lower": 4, "upper": 6},
        ]},
    )
    final = _finish(api, study)
    assert final["status"] == "failed", final
    completed, failed = final["cases"]
    assert completed["status"] == "completed"
    assert failed["status"] == "failed"
    assert failed["error"]
    assert failed["result_id"]
    response = api.client.get(f"{BASE}/simulation-results/{failed['result_id']}")
    assert response.status_code == 200, response.text
    assert response.json()["result"]["success"] is False
    assert failed["acceptance"]["status"] == "NOT_MEASURED"
    assert failed["acceptance"]["rows"][0]["value"] is None
    voltage = next(metric for metric in final["summary"]["metrics"] if metric["name"] == "vout")
    assert voltage["measured_cases"] == voltage["unmeasured_cases"] == 1
    assert voltage["min"] == voltage["max"] == pytest.approx(5, abs=1e-5)


@pytest.mark.parametrize(("axes", "error"), [
    ([], "at least one axis"),
    ([{"kind": "supply", "values": [3.3, 5]}], ".param name"),
    ([{"kind": "load", "parameter": "rload", "values": ["1k", "1000"]}], "duplicate numeric"),
    ([{"kind": "temperature", "values": [-300]}], "absolute zero"),
])
def test_invalid_corner_inputs_are_rejected_before_any_job_is_created(native_api, axes, error):
    api = native_api
    _divider(api)
    response = api.client.post(STUDIES, json={"circuit_path": "divider.cir", "axes": axes})
    assert response.status_code == 422, response.text
    assert error in response.json()["detail"]
    assert api.manager.list() == []
