import os
from pathlib import Path

from presentation.panels.simulation.spice_schematic_document import (
    SpiceSchematicDocument,
)
from presentation.panels.web_file_browser_panel import FileBrowserPanel
from shared.event_types import EVENT_FILE_CHANGED
from shared.file_change import FileChange


class _FileManager:
    def __init__(self, root: Path, generation: int):
        self._root = root
        self.project_generation = generation

    def get_work_dir(self):
        return self._root


def _event(change: FileChange) -> dict:
    return {
        "type": EVENT_FILE_CHANGED,
        "data": change.to_payload(),
        "source": change.origin,
    }


def _change(root: Path, generation: int, path: Path) -> FileChange:
    return FileChange(
        operation="update",
        path=str(path),
        dest_path="",
        is_directory=False,
        origin="test",
        project_root=str(root),
        generation=generation,
        revision="test-revision",
    )


def test_file_browser_requires_current_root_and_generation(tmp_path):
    changed = tmp_path / "main.cir"

    class Probe:
        _root_path = str(tmp_path)
        file_manager = _FileManager(tmp_path, 6)

        def __init__(self):
            self.dispatch_count = 0

        def _remap_expanded_directory_paths(self, _source, _destination):
            return False

        def _synchronize_expanded_directory_paths(self):
            return False

        def _persist_expanded_directory_paths(self):
            raise AssertionError("unchanged expanded state must not be persisted")

        def _dispatch_state(self):
            self.dispatch_count += 1

    probe = Probe()
    FileBrowserPanel._on_file_changed(probe, _event(_change(tmp_path, 5, changed)))
    FileBrowserPanel._on_file_changed(
        probe,
        _event(_change(tmp_path / "other", 6, changed)),
    )
    assert probe.dispatch_count == 0

    FileBrowserPanel._on_file_changed(probe, _event(_change(tmp_path, 6, changed)))
    assert probe.dispatch_count == 1


def test_spice_document_requires_current_root_and_generation(tmp_path):
    changed = tmp_path / "main.cir"

    class Timer:
        def __init__(self):
            self.starts = []

        def start(self, interval):
            self.starts.append(interval)

    class Probe:
        _current_file_path = str(changed)
        _watched_file_keys = {os.path.normcase(os.path.abspath(changed))}
        _pending_refresh_reason = ""
        _refresh_timer = Timer()

        @staticmethod
        def _get_file_manager():
            return _FileManager(tmp_path, 8)

        @staticmethod
        def _normalize_watch_key(path):
            return os.path.normcase(os.path.abspath(path))

    probe = Probe()
    SpiceSchematicDocument._on_file_changed(
        probe,
        _event(_change(tmp_path, 7, changed)),
    )
    SpiceSchematicDocument._on_file_changed(
        probe,
        _event(_change(tmp_path / "other", 8, changed)),
    )
    assert probe._refresh_timer.starts == []

    SpiceSchematicDocument._on_file_changed(
        probe,
        _event(_change(tmp_path, 8, changed)),
    )
    assert len(probe._refresh_timer.starts) == 1
    assert probe._pending_refresh_reason == "update"
