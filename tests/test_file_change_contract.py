from pathlib import Path

import pytest

from application.tasks.file_watch_task import FileWatchReceiver
from infrastructure.file_intelligence.search.file_search_service import FileSearchService
from infrastructure.persistence.file_manager import FileManager
from shared.event_types import (
    EVENT_FILE_CHANGED,
    EVENT_STATE_PROJECT_OPENED,
)
from shared.file_change import FileChange, extract_file_change, normalize_file_change
from shared.service_locator import ServiceLocator
from shared.service_names import SVC_EVENT_BUS, SVC_FILE_MANAGER


class _EventBus:
    def __init__(self):
        self.published = []
        self.handlers = {}

    def subscribe(self, event_type, handler):
        self.handlers.setdefault(event_type, []).append(handler)

    def publish(self, event_type, payload=None, source=None):
        self.published.append((event_type, payload, source))
        envelope = {
            "type": event_type,
            "data": payload,
            "source": source,
            "timestamp": 0.0,
        }
        for handler in list(self.handlers.get(event_type, [])):
            handler(envelope)


@pytest.fixture(autouse=True)
def _clear_services():
    ServiceLocator.clear()
    yield
    ServiceLocator.clear()


def _install_file_services(root: Path):
    event_bus = _EventBus()
    file_manager = FileManager()
    file_manager.set_work_dir(root)
    ServiceLocator.register(SVC_EVENT_BUS, event_bus)
    ServiceLocator.register(SVC_FILE_MANAGER, file_manager)
    return file_manager, event_bus


def _canonical_change(**overrides) -> FileChange:
    values = {
        "operation": "move",
        "path": "/project/a.cir",
        "dest_path": "/project/b.cir",
        "is_directory": False,
        "origin": "file_watcher",
        "project_root": "/project",
        "generation": 3,
        "revision": "test-revision",
    }
    values.update(overrides)
    return FileChange(**values)


def _published_change(record) -> FileChange:
    event_type, payload, source = record
    return normalize_file_change(
        {"type": event_type, "data": payload, "source": source}
    )


def test_normalizer_accepts_file_change_and_canonical_eventbus_envelope():
    change = _canonical_change()

    direct = normalize_file_change(change)
    wrapped = normalize_file_change(
        {
            "type": EVENT_FILE_CHANGED,
            "data": change.to_payload(),
            "source": "file_watcher",
        }
    )

    assert direct is change
    assert wrapped == change


@pytest.mark.parametrize(
    "candidate",
    [
        # A raw mapping is not an EventBus envelope.
        _canonical_change().to_payload(),
        # Removed watchdog spelling and operation aliases stay invalid.
        {
            "type": EVENT_FILE_CHANGED,
            "data": {
                **_canonical_change().to_payload(),
                "event_type": "moved",
            },
        },
        {
            "type": EVENT_FILE_CHANGED,
            "data": {
                **_canonical_change().to_payload(),
                "operation": "moved",
            },
        },
        {
            "type": EVENT_FILE_CHANGED,
            "data": {
                **_canonical_change().to_payload(),
                "src_path": "/project/a.cir",
            },
        },
        # Project identity is mandatory, not inferred from the path/source.
        {
            "type": EVENT_FILE_CHANGED,
            "data": {
                key: value
                for key, value in _canonical_change().to_payload().items()
                if key != "project_root"
            },
        },
        {
            "type": EVENT_FILE_CHANGED,
            "data": {
                key: value
                for key, value in _canonical_change().to_payload().items()
                if key != "generation"
            },
        },
    ],
)
def test_normalizer_rejects_raw_legacy_or_partially_scoped_payload(candidate):
    with pytest.raises(ValueError):
        normalize_file_change(candidate)
    assert extract_file_change(candidate) is None


def test_file_manager_publishes_one_canonical_move_and_delete(tmp_path: Path):
    file_manager, event_bus = _install_file_services(tmp_path)
    source = tmp_path / "source.cir"
    destination = tmp_path / "destination.cir"
    source.write_text("R1 in out 1k\n", encoding="utf-8")

    assert file_manager.move_file(source, destination)
    event_type, payload, source_name = event_bus.published[-1]
    change = _published_change(event_bus.published[-1])

    assert event_type == EVENT_FILE_CHANGED
    assert source_name == "file_manager"
    assert change.operation == "move"
    assert change.path == str(source)
    assert change.dest_path == str(destination)
    assert change.project_root == str(tmp_path)
    assert change.generation == file_manager.project_generation
    assert change.revision not in {"", "missing"}

    assert file_manager.delete_file(destination)
    deleted = _published_change(event_bus.published[-1])
    assert deleted.operation == "delete"
    assert deleted.revision == "missing"


def test_watchdog_publishes_same_canonical_contract(tmp_path: Path, qapp):
    del qapp
    file_manager, event_bus = _install_file_services(tmp_path)
    file_path = tmp_path / "external.cir"
    file_path.write_text("V1 in 0 1\n", encoding="utf-8")

    receiver = FileWatchReceiver()
    receiver.on_file_event(
        str(file_path),
        "modified",
        False,
        "",
        str(tmp_path),
        file_manager.project_generation,
    )
    receiver._flush_debounce_buffer()

    change = _published_change(event_bus.published[-1])
    assert change.operation == "update"
    assert change.origin == "file_watcher"
    assert change.project_root == str(tmp_path)
    assert change.generation == file_manager.project_generation
    assert change.revision not in {"", "missing"}


def test_watchdog_drops_event_without_project_identity(tmp_path: Path, qapp):
    del qapp
    _file_manager, event_bus = _install_file_services(tmp_path)
    file_path = tmp_path / "unscoped.cir"
    file_path.write_text("R1 in out 1k\n", encoding="utf-8")

    receiver = FileWatchReceiver()
    receiver.on_file_event(
        str(file_path),
        "modified",
        False,
        "",
        "",
        0,
    )
    receiver._flush_debounce_buffer()

    assert event_bus.published == []


def test_near_window_external_write_with_different_hash_is_not_suppressed(
    tmp_path: Path,
    qapp,
):
    del qapp
    file_manager, event_bus = _install_file_services(tmp_path)
    file_path = tmp_path / "main.py"
    file_manager.write_file(file_path, "internal = 1\n")
    assert len(event_bus.published) == 1

    # This happens inside the 0.5 s echo window but has a different revision.
    file_path.write_text("external = 2\n", encoding="utf-8")
    receiver = FileWatchReceiver()
    receiver.on_file_event(
        str(file_path),
        "modified",
        False,
        "",
        str(tmp_path),
        file_manager.project_generation,
    )
    receiver._flush_debounce_buffer()

    assert len(event_bus.published) == 2
    external = _published_change(event_bus.published[-1])
    assert external.origin == "file_watcher"
    assert external.revision != _published_change(event_bus.published[0]).revision


def test_file_name_index_rebinds_on_project_switch_and_ignores_late_event(
    tmp_path: Path,
):
    root_a = tmp_path / "project-a"
    root_b = tmp_path / "project-b"
    root_a.mkdir()
    root_b.mkdir()
    old_file = root_a / "old.cir"
    new_file = root_b / "new.cir"
    old_file.write_text("old\n", encoding="utf-8")
    new_file.write_text("new\n", encoding="utf-8")

    file_manager, event_bus = _install_file_services(root_a)
    generation_a = file_manager.project_generation
    service = FileSearchService()
    service._file_manager = file_manager
    service._event_bus = event_bus
    assert service.build_index() == 1
    assert service.find_file("old.cir") is not None

    file_manager.set_work_dir(root_b)
    event_bus.publish(EVENT_STATE_PROJECT_OPENED, {"path": str(root_b)})

    assert service.find_file("old.cir") is None
    assert service.find_file("new.cir") is not None
    assert service.get_index_stats()["project_root"] == str(root_b.resolve())

    late_file = root_a / "late.cir"
    late_file.write_text("late\n", encoding="utf-8")
    event_bus.publish(
        EVENT_FILE_CHANGED,
        FileChange(
            operation="create",
            path=str(late_file),
            dest_path="",
            is_directory=False,
            origin="file_watcher",
            project_root=str(root_a),
            generation=generation_a,
            revision="test-revision",
        ).to_payload(),
        source="file_watcher",
    )
    assert service.find_file("late.cir") is None


def test_file_name_index_applies_external_delete_and_move(tmp_path: Path):
    file_manager, event_bus = _install_file_services(tmp_path)
    source = tmp_path / "source.cir"
    destination = tmp_path / "destination.cir"
    source.write_text("content\n", encoding="utf-8")

    service = FileSearchService()
    service._file_manager = file_manager
    service._event_bus = event_bus
    service.build_index()

    source.rename(destination)
    event_bus.publish(
        EVENT_FILE_CHANGED,
        FileChange(
            operation="move",
            path=str(source),
            dest_path=str(destination),
            is_directory=False,
            origin="file_watcher",
            project_root=str(tmp_path),
            generation=file_manager.project_generation,
            revision="test-revision",
        ).to_payload(),
        source="file_watcher",
    )
    assert service.find_file("source.cir") is None
    assert service.find_file("destination.cir") is not None

    destination.unlink()
    event_bus.publish(
        EVENT_FILE_CHANGED,
        FileChange(
            operation="delete",
            path=str(destination),
            dest_path="",
            is_directory=False,
            origin="file_watcher",
            project_root=str(tmp_path),
            generation=file_manager.project_generation,
            revision="missing",
        ).to_payload(),
        source="file_watcher",
    )
    assert service.find_file("destination.cir") is None
