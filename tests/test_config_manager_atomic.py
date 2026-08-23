from __future__ import annotations

import json

from infrastructure.config import config_manager as config_module
from infrastructure.config.config_manager import ConfigManager


def _manager_at(path) -> ConfigManager:
    manager = ConfigManager()
    manager._config_file = path
    manager._config = {"first": "old", "second": 1}
    assert manager.save_config() is True
    return manager


def test_update_many_persists_and_publishes_one_complete_snapshot(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    manager = _manager_at(config_path)
    events: list[tuple[str, object, object]] = []
    manager.subscribe_change(
        "first",
        lambda key, old, new: events.append((key, old, new)),
    )

    assert manager.update_many({"first": "new", "second": 2}) is True

    assert manager.get_all() == {"first": "new", "second": 2}
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "first": "new",
        "second": 2,
    }
    assert events == [("first", "old", "new")]


def test_failed_atomic_replace_keeps_memory_and_previous_file(
    tmp_path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.json"
    manager = _manager_at(config_path)
    previous_text = config_path.read_text(encoding="utf-8")

    def fail_replace(_source, _destination) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(config_module.os, "replace", fail_replace)

    assert manager.update_many({"first": "new", "second": 2}) is False

    assert manager.get_all() == {"first": "old", "second": 1}
    assert config_path.read_text(encoding="utf-8") == previous_text
    assert not config_path.with_suffix(".json.tmp").exists()
