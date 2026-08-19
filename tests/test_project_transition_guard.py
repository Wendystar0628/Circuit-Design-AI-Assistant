from types import SimpleNamespace
from unittest.mock import MagicMock

from PyQt6.QtWidgets import QMessageBox

from application.project_service import ProjectService, ProjectStatus
from presentation.action_handlers import ActionHandlers
from presentation.main_window import MainWindow
from presentation.panels.workspace_code_editor_panel import CodeEditorPanel
from shared.service_locator import ServiceLocator
from shared.service_names import SVC_EVENT_BUS


class _FakeMainWindow:
    def get_right_panel(self):
        return None

    def activate_right_panel(self, _panel_id: str) -> None:
        return None


class _PreparedEditor:
    def __init__(self, result: bool):
        self.result = result
        self.prepare_calls = 0

    def prepare_close_all(self) -> bool:
        self.prepare_calls += 1
        return self.result


class _ProjectService:
    def __init__(self):
        self.switch_calls = []
        self.close_calls = 0

    def switch_project(self, path: str):
        self.switch_calls.append(path)
        return True, "switched"

    def close_project(self):
        self.close_calls += 1
        return True, "closed"


class _SessionPersistencePreflight:
    def __init__(self, project_root: str, result: bool):
        self.project_root = project_root
        self.result = result
        self.calls = []

    def get_project_root(self):
        return self.project_root

    def ensure_current_session_persisted(self, project_root=None):
        self.calls.append(project_root)
        return self.result


def _handlers(editor: _PreparedEditor, service: _ProjectService) -> ActionHandlers:
    handlers = ActionHandlers(_FakeMainWindow(), {"code_editor": editor})
    handlers._project_service = service
    handlers._logger = MagicMock()
    return handlers


def _handlers_without_project_service(editor: _PreparedEditor, monkeypatch):
    event_bus = MagicMock()
    warning = MagicMock()
    handlers = ActionHandlers(_FakeMainWindow(), {"code_editor": editor})
    handlers._logger = MagicMock()
    handlers._i18n_manager = SimpleNamespace(
        get_text=lambda _key, default=None: default or _key
    )

    # Make the hard dependency unavailable while leaving an EventBus present.
    # This proves the old fallback cannot publish fake lifecycle events.
    monkeypatch.setattr(
        ActionHandlers,
        "project_service",
        property(lambda _self: None),
    )
    monkeypatch.setitem(ServiceLocator._services, SVC_EVENT_BUS, event_bus)
    monkeypatch.setattr(QMessageBox, "warning", warning)
    return handlers, event_bus, warning


def test_open_project_cancel_vetoes_every_project_service_call(tmp_path):
    editor = _PreparedEditor(False)
    service = _ProjectService()
    handlers = _handlers(editor, service)

    assert handlers._open_project(str(tmp_path)) is False

    assert editor.prepare_calls == 1
    assert service.switch_calls == []
    assert service.close_calls == 0


def test_normal_and_recent_project_open_use_the_same_switch_path(tmp_path):
    editor = _PreparedEditor(True)
    service = _ProjectService()
    handlers = _handlers(editor, service)

    assert handlers._open_project(str(tmp_path)) is True
    handlers.on_recent_project_clicked(str(tmp_path))

    assert editor.prepare_calls == 2
    assert service.switch_calls == [str(tmp_path), str(tmp_path)]


def test_open_project_without_service_fails_closed(tmp_path, monkeypatch):
    editor = _PreparedEditor(True)
    handlers, event_bus, warning = _handlers_without_project_service(
        editor,
        monkeypatch,
    )

    assert handlers._open_project(str(tmp_path)) is False

    assert not (tmp_path / ".circuit_ai").exists()
    assert editor.prepare_calls == 0
    event_bus.publish.assert_not_called()
    warning.assert_called_once()


def test_recent_project_without_service_uses_same_fail_closed_path(
    tmp_path,
    monkeypatch,
):
    recent_project = tmp_path / "recent-project"
    recent_project.mkdir()
    editor = _PreparedEditor(True)
    handlers, event_bus, warning = _handlers_without_project_service(
        editor,
        monkeypatch,
    )

    assert handlers.on_recent_project_clicked(str(recent_project)) is False

    assert not (recent_project / ".circuit_ai").exists()
    assert editor.prepare_calls == 0
    event_bus.publish.assert_not_called()
    warning.assert_called_once()


def test_close_workspace_cancel_leaves_project_service_untouched():
    editor = _PreparedEditor(False)
    service = _ProjectService()
    handlers = _handlers(editor, service)

    assert handlers.on_close_workspace() is False

    assert editor.prepare_calls == 1
    assert service.close_calls == 0


def test_close_workspace_without_service_does_not_publish_fake_close(
    monkeypatch,
):
    editor = _PreparedEditor(True)
    handlers, event_bus, warning = _handlers_without_project_service(
        editor,
        monkeypatch,
    )

    assert handlers.on_close_workspace() is False

    assert editor.prepare_calls == 0
    event_bus.publish.assert_not_called()
    warning.assert_called_once()


def test_switch_project_does_not_initialize_after_close_failure():
    service = ProjectService()
    service._logger = MagicMock()
    service.close_project = MagicMock(return_value=(False, "old project stayed open"))
    service.initialize_project = MagicMock(return_value=(True, "should not run"))

    success, message = service.switch_project("new-project")

    assert success is False
    assert "old project stayed open" in message
    service.initialize_project.assert_not_called()


def _project_service_ready_for_failed_persistence(tmp_path):
    service = ProjectService()
    service._status = ProjectStatus.READY
    service._current_project_path = tmp_path
    service._degraded_reason = "must remain"
    service._file_watcher = MagicMock()
    service._session_state_projector = MagicMock()
    service._file_manager = MagicMock()
    service._event_bus = MagicMock()
    service._logger = MagicMock()
    session_manager = _SessionPersistencePreflight(str(tmp_path), False)
    service._session_state_manager = session_manager
    return service, session_manager


def test_close_project_persistence_failure_changes_no_lifecycle_state(tmp_path):
    service, session_manager = _project_service_ready_for_failed_persistence(tmp_path)

    success, message = service.close_project()

    assert success is False
    assert "会话" in message
    assert session_manager.calls == [str(tmp_path)]
    assert service._current_project_path == tmp_path
    assert service._status == ProjectStatus.READY
    assert service._degraded_reason == "must remain"
    service._file_watcher.stop_watching.assert_not_called()
    service._session_state_projector.clear_project_state.assert_not_called()
    service._file_manager.set_work_dir.assert_not_called()
    service._event_bus.publish.assert_not_called()


def test_switch_project_persistence_failure_never_closes_or_initializes(tmp_path):
    service, session_manager = _project_service_ready_for_failed_persistence(tmp_path)
    service.initialize_project = MagicMock(return_value=(True, "must not run"))

    success, message = service.switch_project(str(tmp_path / "new-project"))

    assert success is False
    assert "切换项目失败" in message
    assert session_manager.calls == [str(tmp_path)]
    assert service._current_project_path == tmp_path
    assert service._status == ProjectStatus.READY
    service.initialize_project.assert_not_called()
    service._file_watcher.stop_watching.assert_not_called()
    service._session_state_projector.clear_project_state.assert_not_called()
    service._file_manager.set_work_dir.assert_not_called()
    service._event_bus.publish.assert_not_called()


def test_prepare_close_all_cancel_is_two_phase_and_keeps_every_tab():
    first = SimpleNamespace(path="first.cir")
    second = SimpleNamespace(path="second.cir")
    fake_panel = SimpleNamespace(
        _session_entries={"first": first, "second": second},
        _capture_active_entry_state=MagicMock(),
        _entry_is_dirty=lambda _entry: True,
        _prompt_close_decision=MagicMock(
            side_effect=[
                QMessageBox.StandardButton.Discard,
                QMessageBox.StandardButton.Cancel,
            ]
        ),
        _save_entry=MagicMock(return_value=True),
    )

    assert CodeEditorPanel.prepare_close_all(fake_panel) is False

    assert list(fake_panel._session_entries.values()) == [first, second]
    fake_panel._save_entry.assert_not_called()


def test_prepare_close_all_saves_only_after_all_decisions_are_accepted():
    first = SimpleNamespace(path="first.cir")
    second = SimpleNamespace(path="second.cir")
    fake_panel = SimpleNamespace(
        _session_entries={"first": first, "second": second},
        _capture_active_entry_state=MagicMock(),
        _entry_is_dirty=lambda _entry: True,
        _prompt_close_decision=MagicMock(
            side_effect=[
                QMessageBox.StandardButton.Save,
                QMessageBox.StandardButton.Discard,
            ]
        ),
        _save_entry=MagicMock(return_value=True),
    )

    assert CodeEditorPanel.prepare_close_all(fake_panel) is True

    fake_panel._save_entry.assert_called_once_with(first)
    # Prepare resolves dirty buffers but keeps the tabs until the project
    # service publishes the transition's commit event.
    assert list(fake_panel._session_entries.values()) == [first, second]


def test_project_open_event_commits_without_a_second_dirty_prompt():
    fake_panel = SimpleNamespace(
        _discard_all_tabs=MagicMock(),
        _update_empty_state=MagicMock(),
        _emit_workspace_file_state=MagicMock(),
        prepare_close_all=MagicMock(side_effect=AssertionError("too-late prompt")),
    )

    CodeEditorPanel._on_project_opened(fake_panel, {"path": "new-project"})

    fake_panel._discard_all_tabs.assert_called_once_with()
    fake_panel.prepare_close_all.assert_not_called()


def test_main_window_close_cancel_ignores_event_before_persisting_state():
    event = SimpleNamespace(ignore=MagicMock())
    action_handlers = SimpleNamespace(
        prepare_workspace_transition=MagicMock(return_value=False)
    )
    fake_window = SimpleNamespace(
        _action_handlers=action_handlers,
        _window_state_manager=MagicMock(),
        _session_manager=MagicMock(),
    )

    MainWindow.closeEvent(fake_window, event)

    event.ignore.assert_called_once_with()
    fake_window._window_state_manager.save_window_state.assert_not_called()
    fake_window._session_manager.save_session_state.assert_not_called()


def test_main_window_close_session_save_failure_warns_and_changes_nothing(
    tmp_path,
    monkeypatch,
):
    editor = _PreparedEditor(True)
    session_manager = _SessionPersistencePreflight(str(tmp_path), False)
    project_service = SimpleNamespace(
        get_current_project_path=lambda: str(tmp_path),
    )
    warning = MagicMock()
    monkeypatch.setattr(QMessageBox, "warning", warning)
    handlers = ActionHandlers(_FakeMainWindow(), {"code_editor": editor})
    handlers._project_service = project_service
    handlers._session_state_manager = session_manager
    handlers._logger = MagicMock()
    event = SimpleNamespace(ignore=MagicMock())
    fake_window = SimpleNamespace(
        _action_handlers=handlers,
        _window_state_manager=MagicMock(),
        _session_manager=MagicMock(),
    )

    MainWindow.closeEvent(fake_window, event)

    assert editor.prepare_calls == 1
    assert session_manager.calls == [str(tmp_path)]
    warning.assert_called_once()
    event.ignore.assert_called_once_with()
    fake_window._window_state_manager.save_window_state.assert_not_called()
    fake_window._session_manager.save_session_state.assert_not_called()
