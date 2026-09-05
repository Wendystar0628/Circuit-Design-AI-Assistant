from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from domain.simulation.data.simulation_artifact_exporter import simulation_artifact_exporter
from domain.simulation.data.simulation_artifact_persistence import simulation_artifact_persistence
from domain.simulation.data.simulation_run_archive import (
    RunArchiveUnavailable,
    export_replay_bundle,
    load_archived_source_graph,
    load_run_archive,
    prepare_run_archive,
    summarize_run_archive,
    validate_run_archive,
)
from domain.simulation.models.simulation_error import ErrorSeverity, SimulationError, SimulationErrorType
from domain.simulation.models.simulation_result import SimulationData, SimulationResult
from domain.simulation.service.simulation_result_repository import SimulationResultRepository
from domain.simulation.spice.source_closure import export_spice_source_graph, snapshot_spice_source_closure


def _captured_result(tmp_path: Path) -> SimulationResult:
    source_root = tmp_path / "circuits"
    source_root.mkdir(exist_ok=True)
    main = source_root / "divider.cir"
    main.write_text(
        'frozen divider\n.include "model.inc"\nV1 in 0 DC 1\nR1 in 0 {rval}\n.op\n.end\n',
        encoding="utf-8",
    )
    (source_root / "model.inc").write_text('.include "values.inc"\n', encoding="utf-8")
    (source_root / "values.inc").write_text('.param rval=1000\n', encoding="utf-8")
    with snapshot_spice_source_closure(main) as captured:
        snapshot = export_spice_source_graph(captured.graph)
        result = SimulationResult(
            executor="spice", file_path=str(main), analysis_type="op", success=True,
            source_digest=captured.digest, analysis_command=".op",
            data=SimulationData(
                signals={"V(in)": np.array([1.0]), "I(V1)": np.array([-0.001])},
                signal_types={"V(in)": "voltage", "I(V1)": "current"},
            ),
        )
        result.provenance = {
            "schema_version": 1,
            "experiment": {"analysis_command": ".op"},
            "original_source": snapshot,
            "effective_source": copy.deepcopy(snapshot),
            "runtime": {
                "entry_path": "circuit.cir",
                "root": captured.snapshot_root.as_posix(),
                "files": [{"path": "circuit.cir", "content": captured.main_text}] + [
                    {"path": path.relative_to(captured.snapshot_root).as_posix(), "content": path.read_text(encoding="utf-8")}
                    for path in sorted((captured.snapshot_root / "sources").iterdir())
                ],
            },
            "omitted_measurements": [],
            "engine": {"name": "ngspice", "version": None, "platform": "test", "execution_mode": "in_process"},
        }
    return result


def test_run_archive_survives_deleted_sources_and_native_snapshot(tmp_path: Path):
    result = _captured_result(tmp_path)
    runtime_root = result.provenance["runtime"]["root"]
    assert not Path(runtime_root).exists()
    outcome = simulation_artifact_persistence.persist_bundle(str(tmp_path), result)
    for path in (tmp_path / "circuits").iterdir():
        path.unlink()
    (tmp_path / "circuits").rmdir()

    archive = load_run_archive(str(tmp_path), outcome.result_path)
    assert archive is not None
    assert archive["runtime"]["paths_rebased"] is True
    assert "root" not in archive["runtime"]
    serialized = (outcome.export_root / "run.json").read_text(encoding="utf-8")
    assert runtime_root not in serialized
    assert "circuit-ai-spice-closure-" not in serialized
    graph = load_archived_source_graph(str(tmp_path), outcome.result_path)
    assert graph.digest == result.source_digest
    assert any("rval=1000" in blob.source_text for blob in graph.blobs)
    assert set(path.name for path in outcome.export_root.iterdir()) == {"result.json", "run.json"}
    payload = json.loads((outcome.export_root / "result.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 3
    assert "provenance" not in payload
    assert summarize_run_archive(archive)["engine"]["version"] is None
    assert summarize_run_archive(archive)["execution_inputs_available"] is True


def test_missing_run_archive_never_uses_current_source(tmp_path: Path):
    result = _captured_result(tmp_path)
    result.provenance = None
    outcome = simulation_artifact_persistence.persist_bundle(str(tmp_path), result)
    assert load_run_archive(str(tmp_path), outcome.result_path) is None
    assert summarize_run_archive(None)["replay_available"] is False
    assert SimulationResultRepository().load(str(tmp_path), outcome.result_path).success
    with pytest.raises(RunArchiveUnavailable, match="未保存仿真输入"):
        load_archived_source_graph(str(tmp_path), outcome.result_path)
    with pytest.raises(RunArchiveUnavailable):
        export_replay_bundle(str(tmp_path), outcome.result_path, tmp_path / "replay")
    assert not (tmp_path / "replay").exists()


def test_failed_second_document_write_publishes_neither_document(monkeypatch, tmp_path: Path):
    result = _captured_result(tmp_path)
    write_json = simulation_artifact_exporter.write_json

    def fail_run(path, payload):
        if Path(path).name == "run.json":
            raise OSError("disk full on run inputs")
        write_json(path, payload)

    monkeypatch.setattr(simulation_artifact_exporter, "write_json", fail_run)
    with pytest.raises(OSError, match="disk full"):
        simulation_artifact_persistence.persist_bundle(str(tmp_path), result)
    assert not list((tmp_path / "simulation_results").rglob("*.json"))
    assert not list((tmp_path / "simulation_results").rglob(".__bundle_tmp__"))


@pytest.mark.parametrize("invalid_path", ["../escape.inc", "/root.inc", "C:/root.inc", "sources\\file.inc", "CON.inc", "sources/file. "])
def test_archive_rejects_unsafe_export_paths_before_publication(tmp_path: Path, invalid_path: str):
    result = _captured_result(tmp_path)
    result.provenance["runtime"]["files"][0]["path"] = invalid_path
    with pytest.raises(ValueError, match="relative POSIX"):
        simulation_artifact_persistence.persist_bundle(str(tmp_path), result)
    assert not (tmp_path / "simulation_results").exists()


def test_archive_validates_digest_and_complete_runtime_dependencies(tmp_path: Path):
    result = _captured_result(tmp_path)
    archive = prepare_run_archive(result.provenance, result=result)
    corrupted = copy.deepcopy(archive)
    corrupted["effective_source"]["digest"] = "0" * 64
    with pytest.raises(ValueError, match="digest"):
        validate_run_archive(corrupted, result=result)
    corrupted = copy.deepcopy(archive)
    corrupted["runtime"]["files"] = corrupted["runtime"]["files"][:1]
    with pytest.raises(ValueError, match="dependency is absent"):
        validate_run_archive(corrupted, result=result)
    corrupted = copy.deepcopy(archive)
    corrupted["runtime"]["files"][0]["content"] = 'external\n.include "C:/deleted/model.inc"\n.op\n.end\n'
    with pytest.raises(ValueError, match="absolute dependency"):
        validate_run_archive(corrupted, result=result)


def test_source_only_failed_archive_preserves_truthful_replay_input(tmp_path: Path):
    result = _captured_result(tmp_path)
    result.success = False
    result.data = None
    result.error = SimulationError(type=SimulationErrorType.TIMEOUT, severity=ErrorSeverity.HIGH, message="worker timed out")
    result.provenance.update(effective_source=None, runtime=None)
    outcome = simulation_artifact_persistence.persist_bundle(str(tmp_path), result)
    archive = load_run_archive(str(tmp_path), outcome.result_path)
    summary = summarize_run_archive(archive)
    assert summary["available"] and summary["replay_available"]
    assert not summary["execution_inputs_available"]
    assert summary["source_digest"] is None
    assert load_archived_source_graph(str(tmp_path), outcome.result_path).digest == result.source_digest
    entry = export_replay_bundle(str(tmp_path), outcome.result_path, tmp_path / "replay")
    assert entry.read_text(encoding="utf-8").startswith("frozen divider")
    assert (entry.parent / "run.json").is_file()


def test_export_is_complete_portable_and_does_not_overwrite(tmp_path: Path):
    result = _captured_result(tmp_path)
    outcome = simulation_artifact_persistence.persist_bundle(str(tmp_path), result)
    target = tmp_path / "export"
    entry = export_replay_bundle(str(tmp_path), outcome.result_path, target)
    assert entry == target / "circuit.cir"
    assert '.include "sources/' in entry.read_text(encoding="utf-8")
    assert len(list((target / "sources").iterdir())) == 3
    assert json.loads((target / "run.json").read_text(encoding="utf-8"))["runtime"]["paths_rebased"]
    with pytest.raises(FileExistsError):
        export_replay_bundle(str(tmp_path), outcome.result_path, target)


def test_portable_export_runs_nested_includes_in_native_ngspice(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    dll = repo_root / "vendor/ngspice/win64/Spice64_dll/dll-vs/ngspice.dll"
    if sys.platform != "win32" or not dll.is_file():
        pytest.skip("Bundled Windows ngspice is unavailable")
    result = _captured_result(tmp_path)
    outcome = simulation_artifact_persistence.persist_bundle(str(tmp_path), result)
    entry = export_replay_bundle(str(tmp_path), outcome.result_path, tmp_path / "native-export")
    script = """
import os, sys
from pathlib import Path
from domain.simulation.executor.ngspice_shared import NgSpiceWrapper
spice = NgSpiceWrapper(Path(sys.argv[1]))
entry = Path(sys.argv[2])
os.chdir(entry.parent)
assert spice.load_netlist(entry.read_text(encoding='utf-8').splitlines())
spice.run(timeout_seconds=5)
assert 'No. of Data Rows : 1' in spice.get_stdout(), spice.get_stdout()
assert 'Error' not in spice.get_stdout(), spice.get_stdout()
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(dll), str(entry)],
        cwd=repo_root, capture_output=True, text=True, timeout=15,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_real_worker_bundle_replays_frozen_experiment_after_source_deletion(tmp_path: Path):
    from domain.simulation.executor.process_spice_executor import ProcessSpiceExecutor
    from domain.simulation.models.experiment import ExperimentSpec
    from domain.simulation.spice.source_closure import capture_spice_source_snapshot
    from infrastructure.utils.ngspice_config import configure_ngspice

    if not configure_ngspice():
        pytest.skip("Native ngspice is unavailable")
    main = tmp_path / "divider.cir"
    dependency = tmp_path / "resistor.inc"
    main.write_text(
        "queued divider\n.param resistance=1k\n.include resistor.inc\n"
        "V1 in 0 1\nR1 in out 1k\n.op\n.end\n", encoding="utf-8",
    )
    dependency.write_text("R2 out 0 {resistance}\n", encoding="utf-8")
    frozen = capture_spice_source_snapshot(main)
    experiment = ExperimentSpec(analysis_command=".op", parameters={"resistance": "3k"})
    main.unlink()
    dependency.unlink()
    executor = ProcessSpiceExecutor(timeout_seconds=10)
    result = executor.execute(str(main), experiment=experiment, source_snapshot=frozen)
    assert result.success, result.error
    outcome = simulation_artifact_persistence.persist_bundle(str(tmp_path), result)
    archive = load_run_archive(str(tmp_path), outcome.result_path)
    assert archive["engine"]["execution_mode"] == "isolated_process"
    assert archive["engine"]["version"]
    assert archive["effective_source"]["digest"] != archive["original_source"]["digest"]
    replay = executor.execute(
        str(main), experiment=ExperimentSpec.from_dict(archive["experiment"]),
        source_snapshot=archive["original_source"],
    )
    assert replay.success, replay.error
    assert result.data.signals["V(out)"][0] == pytest.approx(0.75)
    assert replay.data.signals["V(out)"][0] == pytest.approx(0.75)
    assert replay.source_digest == result.source_digest
