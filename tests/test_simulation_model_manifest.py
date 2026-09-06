from __future__ import annotations

import copy
from pathlib import Path

import pytest

from domain.simulation.models.model_manifest import (
    capture_model_manifest,
    validate_model_bindings,
    validate_model_manifest,
)
from domain.simulation.spice.source_closure import (
    collect_spice_source_closure,
    export_spice_source_graph,
    restore_spice_source_graph,
)


def _deck(tmp_path: Path, model: str = ".model DTEST D(IS=1n)\n") -> Path:
    main = tmp_path / "diode.cir"
    main.write_text(
        "model provenance\n.include model.lib\nV1 in 0 1\nR1 in out 1k\n"
        "D1 out 0 DTEST\n.op\n.end\n.model AFTER_END D(IS=9)\n",
        encoding="utf-8",
    )
    (tmp_path / "model.lib").write_text(model, encoding="utf-8")
    return main


def test_model_binding_validation_copies_annotations_and_preserves_unknowns():
    binding = {"name": "DTEST", "voltage_range": {"max": 5}, "simplified": True, "assumptions": ["DC fit"]}
    validated = validate_model_bindings([binding])[0]
    assert validated["kind"] == "model"
    assert validated["version"] is None
    assert validated["frequency_range"] is None
    assert validated["voltage_range"] == {"min": None, "max": 5.0}
    binding["assumptions"].append("mutated")
    assert validated["assumptions"] == ["DC fit"]


@pytest.mark.parametrize("binding", [
    {"name": ""}, {"name": "bad name"}, {"name": "x", "kind": "unknown"},
    {"name": "x", "voltage_range": {"min": 5, "max": 1}},
    {"name": "x", "frequency_range": {"min": -1}},
    {"name": "x", "temperature_range": {"min": -274}},
    {"name": "x", "voltage_range": {"max": float("nan")}},
    {"name": "x", "voltage_range": {"max": True}},
    {"name": "x", "voltage_range": {"unit": "mV", "max": 5}},
    {"name": "x", "simplified": "false"}, {"name": "x", "assumptions": "DC only"},
    {"name": "x", "unknown": 1},
])
def test_model_binding_rejects_ambiguous_or_nonphysical_metadata(binding):
    with pytest.raises(ValueError):
        validate_model_bindings([binding])


def test_inventory_uses_only_selected_library_section_and_complete_continuations(tmp_path: Path):
    main = _deck(tmp_path, ".lib typical\n.model DTEST D(IS=1n\n+ N=1.5)\n.endl typical\n.lib slow\n.model DSLOW D(IS=2n)\n.endl slow\n")
    main.write_text(main.read_text().replace(".include model.lib", ".lib model.lib typical"), encoding="utf-8")
    graph = collect_spice_source_closure(main)
    manifest = capture_model_manifest(graph)
    assert [item["name"] for item in manifest] == ["DTEST"]
    assert manifest[0]["library_section"] == "typical"
    assert manifest[0]["source_id"] == "model.lib"
    assert manifest[0]["version"] is None
    assert manifest[0]["simplified"] is None
    assert validate_model_manifest(manifest, graph=graph) == manifest
    changed = _deck(tmp_path, ".model DTEST D(IS=1n\n+ N=2)\n")
    next_manifest = capture_model_manifest(collect_spice_source_closure(changed))
    assert next_manifest[0]["definition_digest"] != manifest[0]["definition_digest"]


def test_duplicate_local_model_names_are_not_assigned_false_metadata(tmp_path: Path):
    main = _deck(tmp_path, ".subckt A in out\n.model DX D(IS=1n)\n.ends A\n.subckt B in out\n.model DX D(IS=2n)\n.ends B\n")
    graph = collect_spice_source_closure(main)
    manifest = capture_model_manifest(graph, [{"name": "DX", "version": "1.0"}])
    models = [item for item in manifest if item["identity"] and item["name"] == "DX"]
    assert [item["scope"] for item in models] == ["A", "B"]
    assert all(item["version"] is None for item in models)
    assert manifest[-1]["binding_status"] == "ambiguous"
    assert manifest[-1]["identity"] is None
    assert manifest[-1]["file_digest"] is None
    assert validate_model_manifest(manifest, graph=graph) == manifest


def test_missing_binding_does_not_claim_source_or_bypass_inventory(tmp_path: Path):
    graph = collect_spice_source_closure(_deck(tmp_path))
    manifest = capture_model_manifest(graph, [{"name": "NOT_PRESENT", "source": "Vendor", "version": "v2"}])
    assert manifest[-1]["binding_status"] == "unmatched"
    assert manifest[-1]["usage_state"] == "not_bound"
    assert manifest[-1]["file_digest"] is None
    assert validate_model_manifest(manifest, graph=graph) == manifest
    with pytest.raises(ValueError, match="identities"):
        validate_model_manifest(manifest[1:], graph=graph)
    corrupted = copy.deepcopy(manifest)
    corrupted[0]["file_digest"] = "0" * 64
    with pytest.raises(ValueError, match="digest"):
        validate_model_manifest(corrupted, graph=graph)


def test_model_upgrade_cannot_change_historical_definition_or_annotations(tmp_path: Path):
    main = _deck(tmp_path)
    graph = collect_spice_source_closure(main)
    snapshot = export_spice_source_graph(graph)
    bindings = [{"name": "DTEST", "source": "Measured fit", "version": "1.0", "simplified": True,
                 "temperature_range": {"min": 20, "max": 30}, "assumptions": ["Room-temperature DC fit"]}]
    history = capture_model_manifest(graph, bindings)
    bindings[0]["version"] = "2.0"
    (tmp_path / "model.lib").write_text(".model DTEST D(IS=20n)\n", encoding="utf-8")
    current = capture_model_manifest(collect_spice_source_closure(main), bindings)
    main.unlink()
    (tmp_path / "model.lib").unlink()
    restored = restore_spice_source_graph(snapshot)
    assert restored.digest == graph.digest
    assert validate_model_manifest(history, graph=restored) == history
    assert history[0]["version"] == "1.0"
    assert current[0]["version"] == "2.0"
    assert current[0]["file_digest"] != history[0]["file_digest"]
    assert "IS=1n" in next(blob.source_text for blob in restored.blobs if blob.source_id == "model.lib")


def test_bundled_metadata_requires_exact_frozen_file_not_same_part_name(tmp_path: Path):
    library = Path(__file__).resolve().parents[1] / "resources/models/sub/LM741.lib"
    main = _deck(tmp_path, library.read_text(encoding="utf-8"))
    # Preserve the library bytes, including their original line endings.
    (tmp_path / "model.lib").write_bytes(library.read_bytes())
    graph = collect_spice_source_closure(main)
    model = next(item for item in capture_model_manifest(graph) if item["name"] == "LM741")
    assert model["metadata_origin"] == "bundled_source"
    assert model["simplified"] is True
    assert "National Semiconductor" in model["source"]
    assert model["version"] is None
    assert model["voltage_range"] is None
    replacement = _deck(tmp_path, ".subckt LM741 in out\nR1 in out 1k\n.ends LM741\n")
    changed = capture_model_manifest(collect_spice_source_closure(replacement))[0]
    assert changed["source"] is None
    assert changed["simplified"] is None


def test_experiment_override_keeps_untouched_bundled_bytes_and_metadata(tmp_path: Path):
    from domain.simulation.models.experiment import ExperimentSpec
    from domain.simulation.spice.experiment_deck import compile_experiment_graph

    library = Path(__file__).resolve().parents[1] / "resources/models/sub/LM741.lib"
    main = _deck(tmp_path)
    raw_model = library.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    (tmp_path / "model.lib").write_bytes(raw_model)
    graph = collect_spice_source_closure(main)
    experiment = ExperimentSpec(analysis_command=".op", temperature=40)
    effective, _, _ = compile_experiment_graph(graph, experiment)
    captured = capture_model_manifest(effective)
    assert next(blob.raw_bytes for blob in effective.blobs if blob.source_id == "model.lib") == raw_model
    assert next(item for item in captured if item["name"] == "LM741")["metadata_origin"] == "bundled_source"
    replay, _, _ = compile_experiment_graph(restore_spice_source_graph(export_spice_source_graph(graph)), experiment)
    assert capture_model_manifest(replay) == captured


def test_cancelled_worker_keeps_model_annotations_with_frozen_source(tmp_path: Path, monkeypatch):
    from domain.simulation.executor.process_spice_executor import ProcessSpiceExecutor
    from domain.simulation.models.experiment import ExperimentSpec
    from domain.simulation.models.simulation_error import ErrorSeverity, SimulationError, SimulationErrorType
    from domain.simulation.models.simulation_result import create_error_result

    main = _deck(tmp_path)
    snapshot = export_spice_source_graph(collect_spice_source_closure(main))
    executor = ProcessSpiceExecutor()
    error = create_error_result(executor="spice", file_path=str(main), analysis_type="unknown", error=SimulationError(
        type=SimulationErrorType.CANCELLED, severity=ErrorSeverity.LOW, message="cancelled",
    ))
    monkeypatch.setattr(executor, "_execute", lambda *args, **kwargs: error)
    result = executor.execute(str(main), source_snapshot=snapshot, experiment=ExperimentSpec(model_bindings=[{"name": "DTEST", "version": "1.0"}]))
    assert result.error.type == SimulationErrorType.CANCELLED
    assert result.provenance["effective_source"] is None
    assert result.provenance["models"][0]["version"] == "1.0"
    assert result.provenance["models"][0]["usage_state"] == "declared_in_active_source"


def test_real_model_archive_replays_old_definition_after_library_upgrade(tmp_path: Path):
    from domain.simulation.data.simulation_artifact_persistence import simulation_artifact_persistence
    from domain.simulation.data.simulation_run_archive import load_run_archive
    from domain.simulation.executor.process_spice_executor import ProcessSpiceExecutor
    from domain.simulation.models.experiment import ExperimentSpec
    from infrastructure.utils.ngspice_config import configure_ngspice

    if not configure_ngspice():
        pytest.skip("Native ngspice is unavailable")
    main = _deck(tmp_path)
    experiment = ExperimentSpec(model_bindings=[{"name": "DTEST", "source": "Local diode fit", "version": "1.0", "simplified": True}])
    executor = ProcessSpiceExecutor(timeout_seconds=10)
    original = executor.execute(str(main), experiment=experiment)
    assert original.success, original.error
    outcome = simulation_artifact_persistence.persist_bundle(str(tmp_path), original)
    archive = load_run_archive(str(tmp_path), outcome.result_path)
    assert archive["models"][0]["version"] == "1.0"
    (tmp_path / "model.lib").write_text(".model DTEST D(IS=20n)\n", encoding="utf-8")
    current = executor.execute(str(main), experiment=ExperimentSpec(model_bindings=[{"name": "DTEST", "version": "2.0"}]))
    assert current.success, current.error
    assert current.data.signals["V(out)"][0] != pytest.approx(original.data.signals["V(out)"][0])
    replay = executor.execute(str(main), experiment=ExperimentSpec.from_dict(archive["experiment"]), source_snapshot=archive["original_source"])
    assert replay.success, replay.error
    assert replay.data.signals["V(out)"][0] == pytest.approx(original.data.signals["V(out)"][0])
    assert replay.provenance["models"] == archive["models"]
    assert load_run_archive(str(tmp_path), outcome.result_path)["models"] == archive["models"]
