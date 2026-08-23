import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from domain.services import snapshot_service
from domain.services.snapshot_service import (
    SNAPSHOT_METADATA_FILE,
    SNAPSHOTS_DIR,
    create_snapshot,
    preview_restore_snapshot,
    restore_snapshot,
)


def _create_windows_junction_or_skip(target: Path, link: Path) -> None:
    if os.name != "nt":
        pytest.skip("NTFS junction regression is Windows-specific")
    try:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    except (ImportError, OSError) as exc:
        pytest.skip(f"Windows junction creation is unavailable: {exc}")


def _remove_junction(link: Path) -> None:
    if link.exists() or getattr(link, "is_junction", lambda: False)():
        link.rmdir()


def _create_hardlink_or_skip(source: Path, link: Path) -> None:
    try:
        os.link(source, link)
    except (AttributeError, NotImplementedError, OSError) as exc:
        pytest.skip(f"Hardlink creation is unavailable: {exc}")


def test_restore_and_preview_preserve_excluded_trees_at_any_depth(tmp_path: Path):
    design_file = tmp_path / "design.txt"
    design_file.write_text("before\n", encoding="utf-8")

    create_snapshot(str(tmp_path), "safe-restore")

    design_file.write_text("after\n", encoding="utf-8")
    generated_file = tmp_path / "frontend" / "generated.txt"
    generated_file.parent.mkdir(parents=True, exist_ok=True)
    generated_file.write_text("remove me\n", encoding="utf-8")

    venv_marker = tmp_path / ".venv" / "installed.txt"
    venv_marker.parent.mkdir(parents=True, exist_ok=True)
    venv_marker.write_text("keep current venv\n", encoding="utf-8")

    dependency_marker = tmp_path / "frontend" / "node_modules" / "pkg" / "index.js"
    dependency_marker.parent.mkdir(parents=True, exist_ok=True)
    dependency_marker.write_text("keep current dependency\n", encoding="utf-8")

    preview = preview_restore_snapshot(str(tmp_path), "safe-restore")
    preview_paths = {change.relative_path for change in preview.changed_files}

    assert preview_paths == {"design.txt", "frontend/generated.txt"}
    assert all(not path.startswith(".venv/") for path in preview_paths)
    assert all("/node_modules/" not in f"/{path}/" for path in preview_paths)

    restore_snapshot(str(tmp_path), "safe-restore", backup_current=False)

    assert design_file.read_text(encoding="utf-8") == "before\n"
    assert not generated_file.exists()
    assert venv_marker.read_text(encoding="utf-8") == "keep current venv\n"
    assert dependency_marker.read_text(encoding="utf-8") == "keep current dependency\n"


def test_snapshot_excludes_regenerable_circuit_ai_runtime_directories(tmp_path: Path):
    tracked_file = tmp_path / "design.cir"
    tracked_file.write_text("snapshot design\n", encoding="utf-8")
    runtime_files = [
        tmp_path / ".circuit_ai" / "vector_store" / "vectors.bin",
        tmp_path / ".circuit_ai" / "rag_storage" / "index_meta.json",
        tmp_path / ".circuit_ai" / "temp" / "attachment.txt",
    ]
    for runtime_file in runtime_files:
        runtime_file.parent.mkdir(parents=True, exist_ok=True)
        runtime_file.write_text("runtime before\n", encoding="utf-8")

    create_snapshot(str(tmp_path), "without-runtime-caches")
    snapshot_root = tmp_path / SNAPSHOTS_DIR / "without-runtime-caches"
    for runtime_file in runtime_files:
        relative_path = runtime_file.relative_to(tmp_path)
        assert not (snapshot_root / relative_path).exists()
        runtime_file.write_text("runtime after\n", encoding="utf-8")

    tracked_file.write_text("live design\n", encoding="utf-8")
    preview = preview_restore_snapshot(str(tmp_path), "without-runtime-caches")
    assert [change.relative_path for change in preview.changed_files] == ["design.cir"]

    restore_snapshot(str(tmp_path), "without-runtime-caches", backup_current=False)
    assert tracked_file.read_text(encoding="utf-8") == "snapshot design\n"
    assert all(
        runtime_file.read_text(encoding="utf-8") == "runtime after\n"
        for runtime_file in runtime_files
    )


def test_snapshot_disk_preflight_ignores_excluded_large_runtime_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    tracked_file = tmp_path / "design.cir"
    tracked_file.write_text("R1 in 0 1k\n", encoding="utf-8")
    excluded_file = tmp_path / ".circuit_ai" / "vector_store" / "vectors.bin"
    excluded_file.parent.mkdir(parents=True, exist_ok=True)
    excluded_file.write_bytes(b"x" * (2 * 1024 * 1024))

    # Enough for the captured design, deliberately far below 1.5x the cache.
    monkeypatch.setattr(
        snapshot_service.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=1024),
    )

    create_snapshot(str(tmp_path), "preflight-capture-scope")

    snapshot_root = tmp_path / SNAPSHOTS_DIR / "preflight-capture-scope"
    assert (snapshot_root / "design.cir").is_file()
    assert not (snapshot_root / ".circuit_ai" / "vector_store").exists()


def test_custom_capture_exclusion_is_reused_by_preview_and_restore(tmp_path: Path):
    tracked_file = tmp_path / "tracked.txt"
    tracked_file.write_text("before\n", encoding="utf-8")
    cache_file = tmp_path / "private_cache" / "state.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text('{"value": "before"}', encoding="utf-8")

    create_snapshot(
        str(tmp_path),
        "custom-policy",
        ignore_patterns=["private_cache"],
    )

    tracked_file.write_text("after\n", encoding="utf-8")
    cache_file.write_text('{"value": "after"}', encoding="utf-8")

    preview = preview_restore_snapshot(str(tmp_path), "custom-policy")
    assert [change.relative_path for change in preview.changed_files] == ["tracked.txt"]

    restore_snapshot(str(tmp_path), "custom-policy", backup_current=False)
    assert tracked_file.read_text(encoding="utf-8") == "before\n"
    assert cache_file.read_text(encoding="utf-8") == '{"value": "after"}'


def test_snapshot_without_complete_manifest_uses_copy_only_restore(tmp_path: Path):
    tracked_file = tmp_path / "tracked.txt"
    tracked_file.write_text("before\n", encoding="utf-8")
    create_snapshot(str(tmp_path), "legacy-like")

    metadata_path = tmp_path / SNAPSHOTS_DIR / "legacy-like" / SNAPSHOT_METADATA_FILE
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.pop("restore_manifest")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    tracked_file.write_text("after\n", encoding="utf-8")
    uncaptured_file = tmp_path / "created-after.txt"
    uncaptured_file.write_text("must not be inferred as deletable\n", encoding="utf-8")

    preview = preview_restore_snapshot(str(tmp_path), "legacy-like")
    assert [change.relative_path for change in preview.changed_files] == ["tracked.txt"]

    restore_snapshot(str(tmp_path), "legacy-like", backup_current=False)
    assert tracked_file.read_text(encoding="utf-8") == "before\n"
    assert uncaptured_file.read_text(encoding="utf-8") == "must not be inferred as deletable\n"


def test_backup_creation_failure_aborts_before_target_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    tracked_file = tmp_path / "tracked.txt"
    tracked_file.write_text("snapshot state\n", encoding="utf-8")
    create_snapshot(str(tmp_path), "backup-required")
    tracked_file.write_text("live state must remain\n", encoding="utf-8")

    restore_calls: list[Path] = []

    def fail_backup(*args, **kwargs):
        raise OSError("injected backup failure")

    def record_restore(root, source_dir, *, scope=None):
        restore_calls.append(Path(source_dir))

    monkeypatch.setattr(snapshot_service, "create_snapshot", fail_backup)
    monkeypatch.setattr(snapshot_service, "_restore_files_from_snapshot", record_restore)

    with pytest.raises(RuntimeError, match="restore aborted before modifying"):
        snapshot_service.restore_snapshot(str(tmp_path), "backup-required")

    assert restore_calls == []
    assert tracked_file.read_text(encoding="utf-8") == "live state must remain\n"


def test_restore_and_backup_rollback_double_failure_preserves_backup_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    tracked_file = tmp_path / "tracked.txt"
    tracked_file.write_text("snapshot state\n", encoding="utf-8")
    create_snapshot(str(tmp_path), "double-failure")
    tracked_file.write_text("live safety state\n", encoding="utf-8")

    def fail_restore_and_rollback(root, source_dir, *, scope=None):
        source_dir = Path(source_dir)
        if source_dir.name == "double-failure":
            tracked_file.write_text("partial restore\n", encoding="utf-8")
            raise OSError("injected target restore failure")
        raise OSError("injected safety rollback failure")

    monkeypatch.setattr(
        snapshot_service,
        "_restore_files_from_snapshot",
        fail_restore_and_rollback,
    )

    with pytest.raises(RuntimeError) as exc_info:
        snapshot_service.restore_snapshot(str(tmp_path), "double-failure")

    backup_dirs = list((tmp_path / SNAPSHOTS_DIR).glob("_backup_*"))
    assert len(backup_dirs) == 1
    backup_dir = backup_dirs[0].resolve()
    error_message = str(exc_info.value)
    assert str(backup_dir) in error_message
    assert "injected target restore failure" in error_message
    assert "injected safety rollback failure" in error_message
    assert (backup_dir / "tracked.txt").read_text(encoding="utf-8") == "live safety state\n"
    assert tracked_file.read_text(encoding="utf-8") == "partial restore\n"


def test_failed_target_restore_cleans_backup_only_after_successful_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    tracked_file = tmp_path / "tracked.txt"
    tracked_file.write_text("snapshot state\n", encoding="utf-8")
    create_snapshot(str(tmp_path), "rollback-succeeds")
    tracked_file.write_text("live safety state\n", encoding="utf-8")

    real_restore = snapshot_service._restore_files_from_snapshot

    def fail_target_only(root, source_dir, *, scope=None):
        source_dir = Path(source_dir)
        if source_dir.name == "rollback-succeeds":
            tracked_file.write_text("partial restore\n", encoding="utf-8")
            raise OSError("injected target restore failure")
        return real_restore(root, source_dir, scope=scope)

    monkeypatch.setattr(snapshot_service, "_restore_files_from_snapshot", fail_target_only)

    with pytest.raises(RuntimeError, match="rolled back from its safety backup"):
        snapshot_service.restore_snapshot(str(tmp_path), "rollback-succeeds")

    assert tracked_file.read_text(encoding="utf-8") == "live safety state\n"
    assert list((tmp_path / SNAPSHOTS_DIR).glob("_backup_*")) == []


def test_successful_restore_cleans_temporary_safety_backup(tmp_path: Path):
    tracked_file = tmp_path / "tracked.txt"
    tracked_file.write_text("snapshot state\n", encoding="utf-8")
    create_snapshot(str(tmp_path), "successful-restore")
    tracked_file.write_text("live state\n", encoding="utf-8")

    restore_snapshot(str(tmp_path), "successful-restore")

    assert tracked_file.read_text(encoding="utf-8") == "snapshot state\n"
    assert list((tmp_path / SNAPSHOTS_DIR).glob("_backup_*")) == []


def test_capture_preview_backup_and_restore_never_follow_live_junction(
    tmp_path: Path,
):
    project_root = tmp_path / "project"
    external_root = tmp_path / "external"
    project_root.mkdir()
    external_root.mkdir()
    marker = external_root / "must-survive.bin"
    marker.write_bytes(b"\x00external-data")
    tracked = project_root / "tracked.txt"
    tracked.write_text("snapshot\n", encoding="utf-8")
    junction = project_root / "shared-assets"
    _create_windows_junction_or_skip(external_root, junction)

    try:
        create_snapshot(str(project_root), "junction-live")
        snapshot_root = project_root / SNAPSHOTS_DIR / "junction-live"
        assert not (snapshot_root / "shared-assets").exists()

        tracked.write_text("live\n", encoding="utf-8")
        preview = preview_restore_snapshot(str(project_root), "junction-live")
        assert all(
            not change.relative_path.startswith("shared-assets/")
            for change in preview.changed_files
        )

        # backup_current=True exercises the safety-backup capture as well as
        # the target restore. Neither operation may enumerate the junction.
        restore_snapshot(str(project_root), "junction-live", backup_current=True)
        assert junction.is_junction()
        assert marker.read_bytes() == b"\x00external-data"
        assert tracked.read_text(encoding="utf-8") == "snapshot\n"
    finally:
        _remove_junction(junction)


def test_restore_preserves_junction_that_replaced_a_snapshot_directory(
    tmp_path: Path,
):
    project_root = tmp_path / "project"
    external_root = tmp_path / "external"
    original_dir = project_root / "shared-assets"
    original_dir.mkdir(parents=True)
    (original_dir / "snapshot.txt").write_text("snapshot\n", encoding="utf-8")
    external_root.mkdir()
    marker = external_root / "must-survive.txt"
    marker.write_text("external\n", encoding="utf-8")

    create_snapshot(str(project_root), "junction-replaced-directory")
    (original_dir / "snapshot.txt").unlink()
    original_dir.rmdir()
    _create_windows_junction_or_skip(external_root, original_dir)

    try:
        restore_snapshot(
            str(project_root),
            "junction-replaced-directory",
            backup_current=True,
        )
        assert original_dir.is_junction()
        assert marker.read_text(encoding="utf-8") == "external\n"
        assert not (external_root / "snapshot.txt").exists()
    finally:
        _remove_junction(original_dir)


def test_snapshot_source_junction_fails_before_preview_restore_or_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    project_root = tmp_path / "project"
    external_root = tmp_path / "external"
    project_root.mkdir()
    external_root.mkdir()
    tracked = project_root / "tracked.txt"
    tracked.write_text("snapshot\n", encoding="utf-8")
    marker = external_root / "must-survive.txt"
    marker.write_text("external\n", encoding="utf-8")
    create_snapshot(str(project_root), "junction-in-source")
    tracked.write_text("live must remain\n", encoding="utf-8")

    snapshot_root = project_root / SNAPSHOTS_DIR / "junction-in-source"
    source_junction = snapshot_root / "unsafe-source"
    _create_windows_junction_or_skip(external_root, source_junction)

    try:
        with pytest.raises(RuntimeError, match="link-like"):
            preview_restore_snapshot(str(project_root), "junction-in-source")

        backup_calls = []

        def forbidden_backup(*args, **kwargs):
            backup_calls.append((args, kwargs))
            raise AssertionError("unsafe snapshot must fail before safety backup")

        monkeypatch.setattr(snapshot_service, "create_snapshot", forbidden_backup)
        with pytest.raises(RuntimeError, match="link-like"):
            restore_snapshot(str(project_root), "junction-in-source")
        with pytest.raises(RuntimeError, match="link-like"):
            snapshot_service.delete_snapshot(str(project_root), "junction-in-source")

        assert backup_calls == []
        assert tracked.read_text(encoding="utf-8") == "live must remain\n"
        assert marker.read_text(encoding="utf-8") == "external\n"
    finally:
        _remove_junction(source_junction)


def test_snapshot_storage_ancestor_cannot_be_a_junction(tmp_path: Path):
    project_root = tmp_path / "project"
    external_storage = tmp_path / "external-snapshot-storage"
    system_dir = project_root / ".circuit_ai"
    project_root.mkdir()
    system_dir.mkdir()
    external_storage.mkdir()
    marker = external_storage / "must-survive.txt"
    marker.write_text("external\n", encoding="utf-8")
    storage_junction = system_dir / "snapshots"
    _create_windows_junction_or_skip(external_storage, storage_junction)

    try:
        with pytest.raises(RuntimeError, match="link-like"):
            create_snapshot(str(project_root), "must-not-escape")
        assert marker.read_text(encoding="utf-8") == "external\n"
        assert not (external_storage / "must-not-escape").exists()
    finally:
        _remove_junction(storage_junction)


def test_restore_replaces_project_hardlink_without_mutating_external_file(
    tmp_path: Path,
):
    project_root = tmp_path / "project"
    external_root = tmp_path / "external"
    project_root.mkdir()
    external_root.mkdir()

    external_marker = external_root / "must-survive.bin"
    external_marker.write_bytes(b"snapshot-state\x00")
    project_file = project_root / "tracked.bin"
    _create_hardlink_or_skip(external_marker, project_file)
    assert os.path.samefile(external_marker, project_file)

    create_snapshot(str(project_root), "hardlink-destination")

    # This changes both names while they still share one inode.  Restoring the
    # project name must not truncate or rewrite the external name in place.
    external_marker.write_bytes(b"external-live-state\x00")
    assert project_file.read_bytes() == b"external-live-state\x00"

    restore_snapshot(
        str(project_root),
        "hardlink-destination",
        backup_current=True,
    )

    assert external_marker.read_bytes() == b"external-live-state\x00"
    assert project_file.read_bytes() == b"snapshot-state\x00"
    assert not os.path.samefile(external_marker, project_file)
    assert list(project_root.glob(".tracked.bin.restore-*.tmp")) == []


def test_atomic_restore_preserves_regular_file_content_and_metadata(tmp_path: Path):
    tracked_file = tmp_path / "tracked.bin"
    tracked_file.write_bytes(b"snapshot-content\x00\xff")
    os.utime(
        tracked_file,
        ns=(1_700_000_000_123_456_700, 1_700_000_000_123_456_700),
    )
    create_snapshot(str(tmp_path), "atomic-metadata")

    snapshot_file = tmp_path / SNAPSHOTS_DIR / "atomic-metadata" / "tracked.bin"
    expected_mtime_ns = snapshot_file.stat().st_mtime_ns
    expected_mode = snapshot_file.stat().st_mode

    tracked_file.write_bytes(b"live-content")
    os.utime(
        tracked_file,
        ns=(1_800_000_000_987_654_300, 1_800_000_000_987_654_300),
    )

    restore_snapshot(str(tmp_path), "atomic-metadata", backup_current=False)

    restored_stat = tracked_file.stat()
    assert tracked_file.read_bytes() == b"snapshot-content\x00\xff"
    assert restored_stat.st_mtime_ns == expected_mtime_ns
    assert restored_stat.st_mode == expected_mode
    assert list(tmp_path.glob(".tracked.bin.restore-*.tmp")) == []


def test_atomic_restore_cleans_temp_file_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source_file = tmp_path / "source.bin"
    destination_file = tmp_path / "destination.bin"
    source_file.write_bytes(b"snapshot")
    destination_file.write_bytes(b"live-must-remain")

    def fail_replace(source, destination):
        raise OSError("injected atomic replace failure")

    monkeypatch.setattr(snapshot_service.os, "replace", fail_replace)

    with pytest.raises(OSError, match="injected atomic replace failure"):
        snapshot_service._copy_restore_file_atomic(source_file, destination_file)

    assert destination_file.read_bytes() == b"live-must-remain"
    assert list(tmp_path.glob(".destination.bin.restore-*.tmp")) == []
