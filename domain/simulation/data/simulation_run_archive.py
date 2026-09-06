"""Portable, self-contained inputs accompanying the authoritative result.

An archive is captured by the executor while its frozen source graph still
exists. Historical reads never consult the circuit's current workspace path.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from domain.simulation.models.simulation_result import SimulationResult
from domain.simulation.service.simulation_result_repository import SimulationResultRepository
from domain.simulation.spice.source_closure import SpiceSourceClosureGraph


RUN_JSON_FILENAME = "run.json"
RUN_SCHEMA_VERSION = 1
_RUN_FIELDS = frozenset({
    "schema_version", "experiment", "original_source", "effective_source",
    "runtime", "omitted_measurements",
})
_RUN_OPTIONAL_FIELDS = frozenset({"engine", "models"})
_RESERVED_NAMES = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)


class RunArchiveUnavailable(ValueError):
    """A historical result has no captured inputs to inspect or replay."""


def _reject_json_constant(token: str) -> None:
    raise ValueError(f"Non-standard JSON numeric constant is forbidden: {token}")


def _portable_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Archived input paths must be non-empty relative POSIX paths")
    parts = PurePosixPath(value).parts
    if (
        not parts or value != PurePosixPath(value).as_posix()
        or PurePosixPath(value).is_absolute()
        or any(part in {".", ".."} for part in parts)
        or any(re.search(r'[<>:"\\|?*\x00-\x1f]', part) for part in parts)
        or any(part.endswith((".", " ")) or _RESERVED_NAMES.match(part) for part in parts)
    ):
        raise ValueError("Archived input paths must be portable relative POSIX paths")
    return value


def prepare_run_archive(payload: Any, *, result: SimulationResult) -> dict[str, Any]:
    """Relocate captured native mirror paths before they cross the disk boundary.

    Only the runtime mirror's root prefix is rewritten. Original source bytes
    and their source identities remain untouched in the two source snapshots.
    """
    if not isinstance(payload, dict):
        raise ValueError("Run provenance must be an object")
    archive = json.loads(json.dumps(payload, allow_nan=False, ensure_ascii=False))
    runtime = archive.get("runtime")
    if isinstance(runtime, dict) and "root" in runtime:
        root = runtime.pop("root")
        if not isinstance(root, str) or not root or not Path(root).is_absolute():
            raise ValueError("Captured runtime root must be an absolute path")
        prefixes = {
            root.rstrip("/\\") + "/",
            root.rstrip("/\\") + "\\",
            root.replace("\\", "/").rstrip("/") + "/",
            root.replace("/", "\\").rstrip("\\") + "\\",
        }
        for item in runtime.get("files", []):
            if not isinstance(item, dict) or not isinstance(item.get("content"), str):
                raise ValueError("Captured runtime files must contain text")
            for prefix in sorted(prefixes, key=len, reverse=True):
                item["content"] = item["content"].replace(prefix, "")
        runtime["paths_rebased"] = True
    return validate_run_archive(archive, result=result)


def _validate_runtime_closure(runtime: dict[str, Any]) -> None:
    """Resolve every runtime include using archived files and no filesystem IO."""
    from domain.simulation.spice.source_closure import build_spice_source_closure

    sources = {item["path"]: item["content"].encode("utf-8") for item in runtime["files"]}

    def resolve_reference(_parent: str, raw_path: str) -> str:
        normalized = raw_path.replace("\\", "/")
        if normalized.startswith("/") or ":" in normalized:
            raise ValueError("Archived runtime contains an absolute dependency path")
        candidate = posixpath.normpath(normalized)
        if candidate in sources:
            return candidate
        raise ValueError(f"Archived runtime dependency is absent: {raw_path}")

    build_spice_source_closure(
        runtime["entry_path"],
        load_bytes=sources.__getitem__,
        resolve_reference=resolve_reference,
        identify_source=lambda _parent, _parent_id, target, _raw: target,
    )


def validate_run_archive(
    payload: Any,
    *,
    result: SimulationResult | None = None,
) -> dict[str, Any]:
    """Validate source identities and replay files without accessing source paths.

    Return an independent JSON value so subsequent runtime mutations cannot
    change an already-validated transaction.
    """
    if (
        not isinstance(payload, dict)
        or not _RUN_FIELDS.issubset(payload)
        or set(payload) - _RUN_FIELDS - _RUN_OPTIONAL_FIELDS
    ):
        raise ValueError("run.json fields must exactly match the execution-input schema")
    archive = json.loads(json.dumps(payload, allow_nan=False, ensure_ascii=False))
    if type(archive["schema_version"]) is not int or archive["schema_version"] != RUN_SCHEMA_VERSION:
        raise ValueError("Unsupported run.json schema_version")
    if not isinstance(archive["experiment"], dict):
        raise ValueError("run.json experiment must be an object")
    from domain.simulation.models.experiment import ExperimentSpec

    experiment = ExperimentSpec.from_dict(archive["experiment"])
    if result is not None and result.success and (
        experiment.analysis_command.casefold().split() != result.analysis_command.casefold().split()
    ):
        raise ValueError("run.json experiment analysis does not match result.json")
    engine = archive.get("engine")
    if engine is not None:
        if not isinstance(engine, dict) or set(engine) != {"name", "version", "platform", "execution_mode"}:
            raise ValueError("run.json engine metadata has invalid fields")
        if engine["name"] != "ngspice" or any(
            not isinstance(engine[key], str) or not engine[key]
            for key in ("platform", "execution_mode")
        ) or (engine["version"] is not None and not isinstance(engine["version"], str)):
            raise ValueError("run.json engine metadata has invalid values")
    from domain.simulation.spice.source_closure import restore_spice_source_graph

    original = restore_spice_source_graph(archive["original_source"])
    effective_payload = archive["effective_source"]
    runtime = archive["runtime"]
    if effective_payload is None or runtime is None:
        if effective_payload is not None or runtime is not None:
            raise ValueError("Captured execution source and runtime must both be present or absent")
        if result is not None and result.success:
            raise ValueError("Successful runs require captured effective source and runtime inputs")
        if "models" in archive:
            from domain.simulation.models.model_manifest import validate_model_manifest

            archive["models"] = validate_model_manifest(archive["models"], graph=original)
        _validate_omitted_measurements(archive["omitted_measurements"])
        return archive
    effective = restore_spice_source_graph(effective_payload)
    if "models" in archive:
        from domain.simulation.models.model_manifest import validate_model_manifest

        archive["models"] = validate_model_manifest(archive["models"], graph=effective)
    if result is not None and effective.digest != result.source_digest:
        raise ValueError("run.json effective source digest does not match result.json")
    if not isinstance(runtime, dict) or set(runtime) != {"entry_path", "files", "paths_rebased"}:
        raise ValueError("run.json runtime must contain entry_path, files and paths_rebased")
    if runtime["paths_rebased"] is not True:
        raise ValueError("run.json runtime paths must be relative to the archive root")
    entry_path = _portable_path(runtime["entry_path"])
    if not isinstance(runtime["files"], list) or not runtime["files"]:
        raise ValueError("run.json runtime files must be a non-empty list")
    paths: set[str] = set()
    exact_paths: set[str] = set()
    for item in runtime["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "content"}:
            raise ValueError("run.json runtime file must contain path and content")
        path = _portable_path(item["path"])
        if path.casefold() in paths or path.casefold() == RUN_JSON_FILENAME:
            raise ValueError("Duplicate or reserved archived input path")
        if not isinstance(item["content"], str) or "\x00" in item["content"]:
            raise ValueError("Archived input content must be text without NUL")
        paths.add(path.casefold())
        exact_paths.add(path)
    if entry_path not in exact_paths:
        raise ValueError("Archived runtime entry_path is absent from files")
    for path in paths:
        if any(parent.as_posix() in paths for parent in PurePosixPath(path).parents if parent.as_posix() != "."):
            raise ValueError("Archived input paths have a file/directory collision")
    _validate_runtime_closure(runtime)
    _validate_omitted_measurements(archive["omitted_measurements"])
    return archive


def _validate_omitted_measurements(omitted: Any) -> None:
    if not isinstance(omitted, list) or any(not isinstance(item, dict) for item in omitted):
        raise ValueError("run.json omitted_measurements must be a list of objects")


def load_run_archive(project_root: str, result_path: str) -> dict[str, Any] | None:
    """Read a captured run next to an exact result handle; absent means unavailable."""
    repository = SimulationResultRepository()
    loaded = repository.load(project_root, result_path)
    if not loaded.success or loaded.data is None:
        raise ValueError("Cannot load run inputs for an invalid simulation result")
    bundle = repository.resolve_bundle_dir(project_root, result_path)
    if bundle is None:
        raise ValueError("Invalid simulation result bundle")
    run_path = bundle / RUN_JSON_FILENAME
    if run_path.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(run_path):
        raise ValueError("run.json must not be a symlink or junction")
    if not run_path.exists():
        return None
    if not run_path.is_file():
        raise ValueError("run.json must be a regular file")
    payload = json.loads(run_path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant)
    return validate_run_archive(payload, result=loaded.data)


def require_run_archive(project_root: str, result_path: str) -> dict[str, Any]:
    archive = load_run_archive(project_root, result_path)
    if archive is None:
        raise RunArchiveUnavailable("此历史结果未保存仿真输入，无法查看历史电路或重放；请重新运行电路以保存输入。")
    return archive


def load_archived_source_graph(
    project_root: str,
    result_path: str,
    *,
    original: bool = False,
) -> SpiceSourceClosureGraph:
    """Rebuild the historical topology input from captured bytes alone."""
    from domain.simulation.spice.source_closure import restore_spice_source_graph

    archive = require_run_archive(project_root, result_path)
    snapshot = archive["original_source"] if original else (archive["effective_source"] or archive["original_source"])
    return restore_spice_source_graph(snapshot)


def summarize_run_archive(archive: dict[str, Any] | None) -> dict[str, Any]:
    """Small UI projection; file contents stay in the explicit inputs export."""
    if archive is None:
        return {
            "available": False,
            "replay_available": False,
            "execution_inputs_available": False,
            "topology_source": None,
            "reason": "此历史结果未保存仿真输入，无法查看历史电路或重放。",
            "experiment": None,
            "source_digest": None,
            "files": [],
            "omitted_measurements": [],
            "engine": None,
            "models": [],
        }
    runtime = archive["runtime"]
    effective = archive["effective_source"]
    return {
        "available": True,
        "replay_available": True,
        "execution_inputs_available": runtime is not None,
        "topology_source": "effective" if effective is not None else "submitted",
        "experiment": archive["experiment"],
        "source_digest": effective["digest"] if effective is not None else None,
        "original_source_digest": archive["original_source"]["digest"],
        "entry_path": runtime["entry_path"] if runtime else None,
        "files": [{"path": item["path"]} for item in (runtime["files"] if runtime else archive["original_source"]["sources"])],
        "omitted_measurements": archive["omitted_measurements"],
        "engine": archive.get("engine"),
        "models": archive.get("models", []),
    }


def _export_source_files(archive: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    """Create portable source files when a worker never returned executed inputs."""
    from domain.simulation.spice.source_closure import restore_spice_source_graph

    graph = restore_spice_source_graph(archive["original_source"])
    paths = {
        blob.key: "circuit.cir" if blob.key == graph.main_key else f"sources/source-{index:04d}.inc"
        for index, blob in enumerate(graph.blobs)
    }
    references = {(edge.parent_key, edge.line_number): edge for edge in graph.references}
    files: list[dict[str, str]] = []
    for blob in graph.blobs:
        lines = blob.source_text.splitlines()
        for line_number, line in enumerate(lines, start=1):
            reference = references.get((blob.key, line_number))
            if reference is None:
                continue
            target = paths[reference.target_key]
            # ngspice opens these paths with the export root as working directory.
            directive = ".lib" if reference.statement_type == "lib" else (
                ".incpslt" if reference.statement_type == "incpslt" else ".include"
            )
            section = f" {reference.library_section}" if reference.statement_type == "lib" else ""
            lines[line_number - 1] = f'{directive} "{target}"{section}'
        content = "\n".join(lines) + ("\n" if blob.source_text.endswith(("\n", "\r")) else "")
        files.append({"path": paths[blob.key], "content": content})
    return "circuit.cir", files


def export_replay_bundle(
    project_root: str,
    result_path: str,
    destination: str | Path,
) -> Path:
    """Publish run.json and the exact portable execution deck into a new folder.

    The returned entry file can run with the export folder as working directory.
    The run.json source snapshots also retain original bytes for in-app replay.
    """
    archive = require_run_archive(project_root, result_path)
    runtime = archive["runtime"]
    entry_path, files = (
        (runtime["entry_path"], runtime["files"])
        if runtime is not None else _export_source_files(archive)
    )
    target = Path(destination).absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Replay export destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".replay-", dir=target.parent))
    try:
        for item in files:
            path = staging / item["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(item["content"], encoding="utf-8", newline="")
        (staging / RUN_JSON_FILENAME).write_text(
            json.dumps(archive, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        staging.rename(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target / entry_path


__all__ = [
    "RUN_JSON_FILENAME", "RUN_SCHEMA_VERSION", "RunArchiveUnavailable",
    "prepare_run_archive", "validate_run_archive", "load_run_archive", "require_run_archive",
    "load_archived_source_graph", "summarize_run_archive", "export_replay_bundle",
]
