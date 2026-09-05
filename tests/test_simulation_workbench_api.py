"""HTTP workbench contracts use real persisted results and numerical services."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from application.runtime import ApplicationRuntime, ProjectIdentity
from desktop_backend.app import create_app
from domain.simulation.data.simulation_artifact_persistence import SimulationArtifactPersistence
from domain.simulation.models.experiment import ExperimentSpec
from domain.simulation.models.simulation_job import JobOrigin, SimulationJob
from domain.simulation.models.simulation_result import SimulationData, create_success_result
from domain.simulation.service.simulation_result_repository import SimulationResultRepository
from domain.simulation.spice.source_closure import capture_spice_source_snapshot


TOKEN = "b" * 64
PROJECT_ID = "workbench-project"
BASE = f"/api/v1/projects/{PROJECT_ID}"
RATIO = {"signal": "V(out)", "reference": "V(in)", "component": "db"}


class _Runtime(ApplicationRuntime):
    async def start(self):
        pass

    async def stop(self):
        pass


@pytest.fixture
def api(tmp_path):
    runtime = _Runtime()
    runtime._project = ProjectIdentity(PROJECT_ID, str(tmp_path), tmp_path.name, 1)
    runtime.simulation_result_repository = SimulationResultRepository()
    runtime.session_state_manager = SimpleNamespace(get_current_session_id=lambda: "current-session")
    submissions = []

    def submit(**kwargs):
        submissions.append(kwargs)
        return SimulationJob(
            circuit_file=kwargs["circuit_file"], origin=kwargs["origin"],
            project_root=kwargs["project_root"], session_id=kwargs["session_id"],
        )

    runtime.simulation_job_manager = SimpleNamespace(list=lambda: [], submit=submit)

    def publish(result):
        bundle = SimulationArtifactPersistence().persist_bundle(str(tmp_path), result)
        result_id = runtime._register_result(bundle.result_path, None)
        return f"{BASE}/simulation-results/{result_id}", bundle

    app = create_app(TOKEN, "http://localhost:5173", runtime=runtime)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield SimpleNamespace(
            client=client, runtime=runtime, publish=publish, root=tmp_path,
            submissions=submissions,
        )


def _ac_result(root, *, archived=False):
    source = root / "amp.cir"
    source.write_text(
        '.title Captured AC circuit\nV1 in 0 AC 2\nR1 in out 1k\n'
        '.include "load.inc"\n.temp 42\n.ac lin 3 1 3\n.end\n',
        encoding="utf-8",
    )
    dependency = root / "load.inc"
    dependency.write_text("R2 out 0 2k\n", encoding="utf-8")
    snapshot = capture_spice_source_snapshot(source)
    result = create_success_result(
        executor="spice", file_path=str(source), analysis_type="ac",
        analysis_command=".ac lin 3 1 3", source_digest=snapshot["digest"],
        version=4, session_id="recorded-session",
        data=SimulationData(
            frequency=np.array([1.0, 2.0, 3.0]),
            signals={
                "V(in)": np.array([2 + 0j, 2 + 0j, 2 + 0j]),
                "V(out)": np.array([2 + 0j, 1 - 1j, 0 - 1j]),
            },
            signal_types={"V(in)": "voltage", "V(out)": "voltage"},
        ),
    )
    if archived:
        result.provenance = {
            "schema_version": 1,
            "experiment": ExperimentSpec(analysis_command=".ac lin 3 1 3", temperature=42).to_dict(),
            "original_source": snapshot,
            "effective_source": snapshot,
            "runtime": {
                "entry_path": "amp.cir", "paths_rebased": True,
                "files": [
                    {"path": "amp.cir", "content": source.read_text(encoding="utf-8")},
                    {"path": "load.inc", "content": dependency.read_text(encoding="utf-8")},
                ],
            },
            "omitted_measurements": [],
            "engine": {
                "name": "ngspice", "version": "fixture-version",
                "platform": "test-platform", "execution_mode": "isolated-process",
            },
        }
    return result


def _dc_result(root):
    return create_success_result(
        executor="spice", file_path=str(root / "sweep.cir"), analysis_type="dc",
        analysis_command=".dc V1 0 2 1 V2 10 20 10", source_digest="1" * 64,
        data=SimulationData(
            sweep=np.array([0.0, 1.0, 2.0, 0.0, 1.0, 2.0]),
            signals={"V(out)": np.array([0.0, 1.0, 2.0, 10.0, 11.0, 12.0])},
            signal_types={"V(out)": "voltage"},
        ),
    )


def _csv_payload(response):
    assert response.status_code == 200, response.text
    metadata, row_lines = {}, []
    for line in response.text.splitlines():
        if line.startswith("# "):
            key, value = line[2:].split(": ", 1)
            metadata[key] = json.loads(value)
        else:
            row_lines.append(line)
    return metadata, list(csv.reader(row_lines))


def test_workbench_reads_the_real_bundle_without_transferring_native_vectors(api):
    result = _ac_result(api.root)
    url, bundle = api.publish(result)

    response = api.client.get(url + "/workbench")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["result_path"] == bundle.result_path
    assert "data" not in payload["result"]
    assert "data" not in payload
    assert payload["result"]["source_digest"] == result.source_digest
    assert payload["result"]["version"] == 4
    assert {item["name"] for item in payload["catalog"]["signals"]} == {"V(in)", "V(out)"}
    assert payload["catalog"]["x_axis"]["unit"] == "Hz"
    assert all("values" not in signal for signal in payload["catalog"]["signals"])
    assert payload["provenance"]["available"] is False
    assert payload["schematic"] is None
    assert api.client.get(url + "/surface-data").status_code == 404


@pytest.mark.parametrize(("endpoint", "extra"), [
    ("traces", {"x_min": "NaN"}),
    ("traces", {"x_max": "Infinity"}),
    ("traces", {"x_min": 3, "x_max": 1}),
    ("traces", {"max_points": True}),
    ("traces", {"max_points": 20001}),
    ("trace-table", {"offset": -1}),
    ("trace-table", {"limit": True}),
    ("trace-measurements", {"cursor_a": "NaN"}),
    ("trace-measurements", {"cursor_b": "-Infinity"}),
    ("trace-measurements", {"unexpected": 1}),
])
def test_trace_http_requests_reject_invalid_windows_and_nonfinite_controls(api, endpoint, extra):
    url, _bundle = api.publish(_ac_result(api.root))

    response = api.client.post(url + "/" + endpoint, json={"traces": [RATIO], **extra})

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(("endpoint", "field"), [
    ("traces", "x_min"),
    ("trace-measurements", "cursor_a"),
])
def test_overflowing_json_numbers_return_validation_errors_instead_of_500(api, endpoint, field):
    url, _bundle = api.publish(_ac_result(api.root))
    payload = '{"traces": [{"signal": "V(out)"}], "' + field + '": 1e309}'

    response = api.client.post(
        url + "/" + endpoint, content=payload,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422, response.text


@pytest.mark.parametrize("traces", [
    [], [{"signal": "V(missing)"}], [{"signal": "V(out)", "component": "phase-ish"}],
    [{"signal": "V(out)", "reference": "V(missing)"}],
    [{"signal": "V(out)", "old_mode": "db"}], [RATIO, RATIO],
])
def test_trace_http_requests_reject_unknown_signals_and_ambiguous_specs(api, traces):
    url, _bundle = api.publish(_ac_result(api.root))
    response = api.client.post(url + "/traces", json={"traces": traces})
    assert response.status_code == 422, response.text


def test_ac_ratio_query_table_and_full_resolution_csv_use_one_numeric_definition(api):
    result = _ac_result(api.root)
    url, _bundle = api.publish(result)
    phase = {**RATIO, "component": "phase"}
    traces = [RATIO, phase]

    query = api.client.post(url + "/traces", json={"traces": traces})
    table = api.client.post(url + "/trace-table", json={"traces": traces, "offset": 1, "limit": 2})
    export = api.client.post(url + "/trace-exports", json={"traces": traces, "format": "csv"})

    assert query.status_code == table.status_code == 200
    series = query.json()["series"]
    expected_db = [0, 20 * np.log10(np.sqrt(2) / 2), 20 * np.log10(0.5)]
    assert series[0]["y"] == pytest.approx(expected_db)
    assert series[0]["unit"] == "dB"
    assert series[1]["y"] == pytest.approx([0, -45, -90])
    assert series[1]["unit"] == "°"
    assert [row["values"][0] for row in table.json()["rows"]] == pytest.approx(expected_db[1:])
    assert table.json()["total_rows"] == 3
    metadata, rows = _csv_payload(export)
    assert metadata["file_path"] == "amp.cir"
    assert metadata["source_digest"] == result.source_digest
    assert metadata["analysis_command"] == result.analysis_command
    assert metadata["timestamp"] == result.timestamp
    assert metadata["trace_specs"] == traces
    assert "full resolution" in metadata["sampling"]
    assert "dB" in rows[0][4] and "°" in rows[0][5]
    assert len(rows) == 4
    assert [float(row[4]) for row in rows[1:]] == pytest.approx(expected_db)
    assert [int(row[0]) for row in rows[1:]] == [0, 1, 2]


def test_json_and_native_complex_csv_exports_preserve_source_identity_and_all_samples(api):
    result = _ac_result(api.root)
    url, bundle = api.publish(result)
    json_link = api.client.post(url + "/exports", json={"format": "json", "surface": "data"})
    assert json_link.status_code == 200, json_link.text
    exported_json = api.client.get(json_link.json()["download_url"])
    assert exported_json.status_code == 200
    expected = json.loads((api.root / bundle.result_path).read_text(encoding="utf-8"))
    assert exported_json.json() == expected
    assert expected["version"] == 4 and expected["session_id"] == "recorded-session"

    csv_link = api.client.post(url + "/exports", json={"format": "csv", "surface": "data"})
    assert csv_link.status_code == 200, csv_link.text
    exported_csv = api.client.get(csv_link.json()["download_url"])
    metadata, rows = _csv_payload(exported_csv)
    assert metadata["source_digest"] == result.source_digest
    assert metadata["analysis_command"] == result.analysis_command
    assert metadata["timestamp"] == result.timestamp
    assert {(trace["signal"], trace["component"]) for trace in metadata["trace_specs"]} == {
        (name, component) for name in ["V(in)", "V(out)"] for component in ["real", "imaginary"]
    }
    assert len(rows) == 4


def test_nested_dc_table_and_cursors_keep_branch_identity_without_render_separators(api):
    url, _bundle = api.publish(_dc_result(api.root))
    traces = [{"signal": "V(out)", "component": "real"}]
    table = api.client.post(url + "/trace-table", json={"traces": traces})
    measurements = api.client.post(url + "/trace-measurements", json={
        "traces": traces, "cursor_a": 0, "cursor_b": 2,
    })
    query = api.client.post(url + "/traces", json={"traces": traces})

    assert table.status_code == measurements.status_code == query.status_code == 200
    rows = table.json()["rows"]
    assert len(rows) == table.json()["total_rows"] == 6
    assert [row["branch_id"] for row in rows] == [0, 0, 0, 1, 1, 1]
    assert [row["outer_value"] for row in rows] == [10, 10, 10, 20, 20, 20]
    assert [row["x"] for row in rows] == [0, 1, 2, 0, 1, 2]
    measured = measurements.json()["measurements"]
    assert [item["branch_id"] for item in measured] == [0, 1]
    assert [item["cursor_a"]["y"] for item in measured] == [0, 10]
    assert [item["cursor_b"]["y"] for item in measured] == [2, 12]
    assert [item["delta_y"] for item in measured] == [2, 2]
    assert all(item["time_mean"] is None and item["time_rms"] is None for item in measured)
    assert query.json()["series"][0]["x"] == [0, 1, 2, None, 0, 1, 2]


def test_legacy_result_stays_readable_and_replay_explains_missing_archived_inputs(api):
    url, bundle = api.publish(_ac_result(api.root))
    (api.root / "amp.cir").unlink()
    (api.root / "load.inc").unlink()
    assert not (bundle.export_root / "run.json").exists()

    detail = api.client.get(url)
    workbench = api.client.get(url + "/workbench")
    replay = api.client.post(url + "/replay")
    inputs = api.client.get(url + "/inputs")

    assert detail.status_code == workbench.status_code == 200
    assert detail.json()["result"]["data"]
    assert workbench.json()["provenance"]["available"] is False
    assert replay.status_code == inputs.status_code == 422
    assert "archived" in replay.json()["detail"].lower()
    assert api.submissions == []


def test_archived_history_retains_topology_replay_and_download_after_source_deletion(api):
    result = _ac_result(api.root, archived=True)
    original_snapshot = result.provenance["original_source"]
    url, bundle = api.publish(result)
    (api.root / "amp.cir").unlink()
    (api.root / "load.inc").unlink()
    assert (bundle.export_root / "run.json").is_file()

    workbench = api.client.get(url + "/workbench")
    replay = api.client.post(url + "/replay")
    inputs = api.client.get(url + "/inputs")

    assert workbench.status_code == 200, workbench.text
    payload = workbench.json()
    assert payload["provenance"]["available"] is True
    assert payload["provenance"]["engine"]["version"] == "fixture-version"
    assert payload["schematic"]["has_schematic"] is True
    assert {item["instance_name"] for item in payload["schematic"]["components"]} == {"V1", "R1", "R2"}
    assert replay.status_code == 202, replay.text
    assert replay.json()["job"]["circuit_file"] == "amp.cir"
    assert len(api.submissions) == 1
    submission = api.submissions[0]
    assert submission["origin"] is JobOrigin.UI_EDITOR
    assert submission["source_snapshot"] == original_snapshot
    assert submission["experiment"].analysis_command == ".ac lin 3 1 3"
    assert submission["experiment"].temperature == 42
    assert submission["session_id"] == "current-session"
    assert inputs.status_code == 200, inputs.text
    assert inputs.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(inputs.content)) as archive:
        assert set(archive.namelist()) == {"run.json", "amp.cir", "load.inc"}
        assert archive.read("load.inc").decode("utf-8") == "R2 out 0 2k\n"
        saved_archive = json.loads(archive.read("run.json"))
        assert saved_archive["original_source"] == original_snapshot


def test_simulation_start_forwards_explicit_experiment_and_rejects_invalid_controls(api):
    _ac_result(api.root)
    response = api.client.post(BASE + "/simulations", json={
        "circuit_path": "amp.cir",
        "experiment": {"analysis_command": ".ac lin 3 1 3", "temperature": 65, "timeout_seconds": 8},
    })
    assert response.status_code == 202, response.text
    assert api.submissions[0]["experiment"].temperature == 65
    assert api.submissions[0]["experiment"].timeout_seconds == 8

    rejected = api.client.post(BASE + "/simulations", json={
        "circuit_path": "amp.cir", "experiment": {"solver_options": {"reltol": "garbage"}},
    })
    assert rejected.status_code == 422
    assert len(api.submissions) == 1
