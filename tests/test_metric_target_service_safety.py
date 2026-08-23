from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from application.metric_target_service import (
    MetricTargetService,
    MetricTargetStorageError,
)


def _service_for(monkeypatch: pytest.MonkeyPatch, project_root: Path) -> MetricTargetService:
    service = MetricTargetService()
    active = {"root": str(project_root)}
    monkeypatch.setattr(service, "_get_project_root", lambda: active["root"])
    service._test_active_project = active  # type: ignore[attr-defined]
    service.reload_from_storage(emit_signal=False)
    return service


def test_corrupt_metric_target_file_blocks_writes_and_preserves_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = tmp_path / ".circuit_ai" / "metric_targets.json"
    storage.parent.mkdir(parents=True)
    damaged = b'{"files": [broken'
    storage.write_bytes(damaged)
    circuit = tmp_path / "design.cir"
    circuit.write_text("* test\n.end\n", encoding="utf-8")

    service = _service_for(monkeypatch, tmp_path)

    assert service.get_state()["storage_error"]
    with pytest.raises(MetricTargetStorageError, match="unreadable"):
        service.set_targets_for_file(str(circuit), {"gain": ">= 10 dB"})
    assert storage.read_bytes() == damaged


def test_metric_target_commit_is_disk_first_and_cleans_failed_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    circuit = tmp_path / "design.cir"
    circuit.write_text("* test\n.end\n", encoding="utf-8")
    service = _service_for(monkeypatch, tmp_path)
    storage = tmp_path / ".circuit_ai" / "metric_targets.json"

    def fail_replace(_source: object, _target: object) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(MetricTargetStorageError, match="replace failure"):
        service.set_targets_for_file(str(circuit), {"gain": "10"})

    assert service.get_targets_for_file(str(circuit)) == {}
    assert not storage.exists()
    assert list(storage.parent.glob(".metric_targets.json.*.tmp")) == []


def test_metric_target_commit_rejects_project_switch_before_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_a = tmp_path / "a"
    project_b = tmp_path / "b"
    project_a.mkdir()
    project_b.mkdir()
    circuit = project_a / "design.cir"
    circuit.write_text("* test\n.end\n", encoding="utf-8")
    service = _service_for(monkeypatch, project_a)
    active = service._test_active_project  # type: ignore[attr-defined]

    real_fsync = os.fsync

    def switch_project(fd: int) -> None:
        real_fsync(fd)
        active["root"] = str(project_b)

    monkeypatch.setattr(os, "fsync", switch_project)

    with pytest.raises(MetricTargetStorageError, match="active project changed"):
        service.set_targets_for_file(str(circuit), {"gain": "10"})

    assert not (project_a / ".circuit_ai" / "metric_targets.json").exists()
    assert not (project_b / ".circuit_ai" / "metric_targets.json").exists()


def test_metric_target_commit_preserves_existing_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    circuit = tmp_path / "design.cir"
    circuit.write_text("* test\n.end\n", encoding="utf-8")
    service = _service_for(monkeypatch, tmp_path)

    service.set_targets_for_file(
        "design.cir",
        {"gain": ">= 20 dB", "empty": ""},
    )

    storage = tmp_path / ".circuit_ai" / "metric_targets.json"
    payload = json.loads(storage.read_text(encoding="utf-8"))
    assert payload == {
        "files": [
            {
                "relative_path": "design.cir",
                "targets": {"gain": ">= 20 dB"},
            }
        ]
    }
    assert service.get_targets_for_file("design.cir") == {"gain": ">= 20 dB"}
