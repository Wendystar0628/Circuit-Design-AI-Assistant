from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from presentation.panels.workspace_code_editor_panel import CodeEditorPanel
from shared.file_change import FileChange
from shared.path_utils import normalize_absolute_path, normalize_identity_path


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _ScopedFileManager:
    def __init__(self, project_root: Path, generation: int):
        self._project_root = project_root.resolve()
        self._generation = generation

    def get_work_dir(self) -> Path:
        return self._project_root

    @property
    def project_generation(self) -> int:
        return self._generation

    def read_file(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> None:
        Path(path).write_text(content, encoding="utf-8")


class _PendingWorkspaceEdits:
    def get_state(self):
        return {}

    def accept_file_edits(self, _path: str):
        return {}


def _make_panel(monkeypatch, project_root: Path, generation: int) -> CodeEditorPanel:
    # Keep the widget independent from process-global services so each test
    # controls the project root and generation explicitly.
    monkeypatch.setattr(
        CodeEditorPanel,
        "_get_optional_service",
        lambda _self, _service_name: None,
    )
    panel = CodeEditorPanel()
    panel._file_manager = _ScopedFileManager(project_root, generation)
    panel._pending_workspace_edit_service = _PendingWorkspaceEdits()
    panel._pending_workspace_edit_connected = True
    return panel


def _move_change(
    source: Path,
    destination: Path,
    project_root: Path,
    generation: int,
    *,
    is_directory: bool = False,
) -> FileChange:
    return FileChange(
        operation="move",
        path=str(source),
        dest_path=str(destination),
        is_directory=is_directory,
        origin="test",
        project_root=str(project_root),
        generation=generation,
        revision="test-revision",
    )


def _event(change: FileChange) -> dict:
    return {
        "type": "file_changed",
        "data": change.to_payload(),
        "source": change.origin,
    }


def test_file_move_rebinds_dirty_active_tab_and_save_uses_destination(
    tmp_path,
    monkeypatch,
    qapp,
):
    del qapp
    source = tmp_path / "old-name.cir"
    destination = tmp_path / "new-name.cir"
    source.write_text("disk content", encoding="utf-8")
    panel = _make_panel(monkeypatch, tmp_path, generation=7)
    assert panel.load_file(str(source)) is True
    panel._shared_code_editor._on_content_changed("unsaved buffer")

    source.rename(destination)
    panel._on_file_changed(
        _event(_move_change(source, destination, tmp_path, 7))
    )

    assert panel.get_open_files() == [normalize_absolute_path(str(destination))]
    assert panel.get_current_file() == normalize_absolute_path(str(destination))
    assert panel._shared_code_editor.toPlainText() == "unsaved buffer"
    assert panel._shared_code_editor.is_modified() is True
    assert panel._shared_code_editor._file_path == normalize_absolute_path(
        str(destination)
    )
    moved_entry = panel._find_entry(str(destination))
    assert moved_entry is not None
    assert moved_entry.name == destination.name
    assert moved_entry.identity_path == normalize_identity_path(str(destination))

    assert panel.save_file() is True
    assert destination.read_text(encoding="utf-8") == "unsaved buffer"
    assert not source.exists()
    panel.deleteLater()


def test_directory_move_rekeys_all_descendant_tabs_and_preserves_buffer(
    tmp_path,
    monkeypatch,
    qapp,
):
    del qapp
    source_dir = tmp_path / "old-dir"
    nested_dir = source_dir / "nested"
    nested_dir.mkdir(parents=True)
    source_a = source_dir / "a.cir"
    source_b = nested_dir / "b.cir"
    source_a.write_text("a on disk", encoding="utf-8")
    source_b.write_text("b on disk", encoding="utf-8")

    panel = _make_panel(monkeypatch, tmp_path, generation=11)
    assert panel.load_file(str(source_a)) is True
    panel._shared_code_editor._on_content_changed("dirty a buffer")
    assert panel.load_file(str(source_b)) is True

    destination_dir = tmp_path / "renamed-dir"
    source_dir.rename(destination_dir)
    destination_a = destination_dir / "a.cir"
    destination_b = destination_dir / "nested" / "b.cir"
    panel._on_file_changed(
        _event(_move_change(
            source_dir,
            destination_dir,
            tmp_path,
            11,
            is_directory=True,
        ))
    )

    assert panel.get_open_files() == [
        normalize_absolute_path(str(destination_a)),
        normalize_absolute_path(str(destination_b)),
    ]
    assert panel.get_current_file() == normalize_absolute_path(str(destination_b))
    assert panel._find_entry(str(source_a)) is None
    assert panel._find_entry(str(source_b)) is None

    moved_dirty_entry = panel._find_entry(str(destination_a))
    assert moved_dirty_entry is not None
    assert moved_dirty_entry.is_dirty is True
    assert moved_dirty_entry.buffer_content == "dirty a buffer"

    assert panel.switch_to_file(str(destination_a)) is True
    assert panel._shared_code_editor.toPlainText() == "dirty a buffer"
    assert panel.save_file() is True
    assert destination_a.read_text(encoding="utf-8") == "dirty a buffer"
    assert not source_dir.exists()
    panel.deleteLater()


def test_file_move_from_old_generation_is_ignored(
    tmp_path,
    monkeypatch,
    qapp,
):
    del qapp
    source = tmp_path / "current.cir"
    destination = tmp_path / "stale-name.cir"
    source.write_text("current", encoding="utf-8")
    panel = _make_panel(monkeypatch, tmp_path, generation=23)
    assert panel.load_file(str(source)) is True

    panel._on_file_changed(
        _event(_move_change(source, destination, tmp_path, 22))
    )

    assert panel.get_open_files() == [normalize_absolute_path(str(source))]
    assert panel.get_current_file() == normalize_absolute_path(str(source))
    assert panel._find_entry(str(destination)) is None
    panel.deleteLater()
