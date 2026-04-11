import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from presentation.action_handlers import ActionHandlers


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _FakeCopyPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.copy_calls = 0
        self.select_all_calls = 0
        self.focus_child = QWidget(self)

    def copy(self):
        self.copy_calls += 1

    def select_all(self):
        self.select_all_calls += 1


class _FakeMainWindow:
    def __init__(self, right_panel):
        self._right_panel = right_panel
        self.activated_panel_id = ""

    def get_right_panel(self):
        return self._right_panel

    def activate_right_panel(self, panel_id: str) -> None:
        self.activated_panel_id = panel_id


def test_edit_copy_routes_to_focused_right_panel(qapp):
    del qapp
    code_editor = _FakeCopyPanel()
    right_panel = _FakeCopyPanel()
    handlers = ActionHandlers(_FakeMainWindow(right_panel), {"code_editor": code_editor})
    handlers._get_focus_widget = lambda: right_panel.focus_child

    handlers.on_edit_copy()

    assert right_panel.copy_calls == 1
    assert code_editor.copy_calls == 0


def test_edit_select_all_routes_to_focused_right_panel(qapp):
    del qapp
    code_editor = _FakeCopyPanel()
    right_panel = _FakeCopyPanel()
    handlers = ActionHandlers(_FakeMainWindow(right_panel), {"code_editor": code_editor})
    handlers._get_focus_widget = lambda: right_panel.focus_child

    handlers.on_edit_select_all()

    assert right_panel.select_all_calls == 1
    assert code_editor.select_all_calls == 0


def test_edit_copy_preserves_code_editor_priority_when_editor_has_focus(qapp):
    del qapp
    code_editor = _FakeCopyPanel()
    right_panel = _FakeCopyPanel()
    handlers = ActionHandlers(_FakeMainWindow(right_panel), {"code_editor": code_editor})
    handlers._get_focus_widget = lambda: code_editor.focus_child

    handlers.on_edit_copy()

    assert code_editor.copy_calls == 1
    assert right_panel.copy_calls == 0
