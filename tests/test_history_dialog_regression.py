from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from domain.llm.context_manager import ContextManager
from domain.llm.session_state_manager import SessionStateManager
from domain.services import context_service
from presentation.dialogs.history_dialog import HistoryDialog
from shared.service_locator import ServiceLocator
from shared.service_names import SVC_EVENT_BUS, SVC_SESSION_STATE_MANAGER


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def clear_services():
    ServiceLocator.clear()
    yield
    ServiceLocator.clear()


class _FakeEventBus:
    def __init__(self):
        self.subscriptions = []
        self.published = []

    def subscribe(self, event_type: str, handler):
        self.subscriptions.append((event_type, handler))

    def unsubscribe(self, event_type: str, handler):
        try:
            self.subscriptions.remove((event_type, handler))
            return True
        except ValueError:
            return False

    def publish(self, event_type: str, payload=None, source: str = None):
        self.published.append((event_type, payload, source))
        for subscribed_event, handler in list(self.subscriptions):
            if subscribed_event == event_type:
                handler({"type": event_type, "data": payload, "source": source})


@pytest.fixture
def history_env(tmp_path: Path):
    event_bus = _FakeEventBus()
    manager = SessionStateManager()
    manager._context_manager = ContextManager()
    manager._event_bus = event_bus
    session_ids = iter(["session-archived", "session-current"])
    manager._generate_session_id = lambda: next(session_ids)

    archived_session_id = manager.create_session(str(tmp_path))
    manager.context_manager.add_user_message(
        "历史会话里的用户问题",
        timestamp="2026-04-08T16:36:00",
    )
    manager.mark_dirty()
    manager.context_manager.add_assistant_message(
        "历史会话里的助手回复",
        timestamp="2026-04-08T16:36:30",
    )
    manager.save_current_session(project_root=str(tmp_path))

    current_session_id = manager.create_session(str(tmp_path))
    manager.context_manager.add_user_message(
        "写入一个测试文件",
        timestamp="2026-04-08T18:09:00",
    )
    manager.mark_dirty()
    manager.context_manager.add_assistant_message(
        "已完成当前对话回复",
        timestamp="2026-04-08T18:09:20",
    )

    ServiceLocator.register(SVC_EVENT_BUS, event_bus)
    ServiceLocator.register(SVC_SESSION_STATE_MANAGER, manager)

    return {
        "project_root": str(tmp_path),
        "event_bus": event_bus,
        "manager": manager,
        "archived_session_id": archived_session_id,
        "current_session_id": current_session_id,
    }


def test_history_dialog_loads_current_session_into_list_and_detail(qapp, history_env):
    dialog = HistoryDialog()
    try:
        qapp.processEvents()

        manager = history_env["manager"]
        current_session_id = history_env["current_session_id"]

        assert manager.get_current_session_id() == current_session_id
        assert context_service.session_exists(history_env["project_root"], current_session_id)
        assert dialog._session_list.count() == 2
        assert dialog._session_list.currentItem().data(Qt.ItemDataRole.UserRole) == current_session_id
        assert "写入一个测试文件" in dialog._session_list.currentItem().text()

        detail_text = dialog._detail_text.toPlainText()
        assert "写入一个测试文件" in detail_text
        assert "已完成当前对话回复" in detail_text
        assert dialog._open_btn.isEnabled()
        assert dialog._export_btn.isEnabled()
        assert dialog._delete_btn.isEnabled()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_history_dialog_open_session_persists_current_session_before_switch(qapp, history_env):
    dialog = HistoryDialog()
    try:
        qapp.processEvents()

        manager = history_env["manager"]
        archived_session_id = history_env["archived_session_id"]
        current_session_id = history_env["current_session_id"]

        manager.context_manager.add_user_message(
            "打开历史前新增的一条当前消息",
            timestamp="2026-04-08T18:10:00",
        )
        manager.mark_dirty()

        assert dialog.open_session(archived_session_id) is True
        assert manager.get_current_session_id() == archived_session_id

        saved_messages = context_service.load_messages(history_env["project_root"], current_session_id)
        assert any(msg.get("content") == "打开历史前新增的一条当前消息" for msg in saved_messages)
    finally:
        dialog.close()
        dialog.deleteLater()


def test_history_dialog_delete_refreshes_list_and_selection(qapp, history_env, monkeypatch):
    dialog = HistoryDialog()
    try:
        qapp.processEvents()

        archived_session_id = history_env["archived_session_id"]
        current_session_id = history_env["current_session_id"]

        assert dialog._select_session_by_id(archived_session_id) is True
        qapp.processEvents()
        assert dialog._current_session_id == archived_session_id

        monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

        dialog._on_delete_clicked()
        qapp.processEvents()

        assert not context_service.session_exists(history_env["project_root"], archived_session_id)
        assert dialog._session_list.count() == 1
        assert dialog._session_list.currentItem().data(Qt.ItemDataRole.UserRole) == current_session_id
        remaining_ids = [
            dialog._session_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(dialog._session_list.count())
        ]
        assert archived_session_id not in remaining_ids
    finally:
        dialog.close()
        dialog.deleteLater()


def test_session_state_manager_normalizes_project_root_for_live_current_session_messages(tmp_path: Path):
    manager = SessionStateManager()
    manager._context_manager = ContextManager()

    session_id = manager.create_session(str(tmp_path))
    manager.context_manager.add_user_message(
        "当前会话消息",
        timestamp="2026-04-08T18:12:00",
    )
    manager.mark_dirty()

    variant_project_root = str(tmp_path).replace("\\", "/").upper()
    messages = manager.get_session_messages(session_id, project_root=variant_project_root)

    assert len(messages) == 1
    assert messages[0]["type"] == "user"
    assert messages[0]["content"] == "当前会话消息"
