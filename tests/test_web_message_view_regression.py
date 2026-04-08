import pytest
from PyQt6.QtWidgets import QApplication

import presentation.panels.conversation.web_message_view as web_message_view_module
from presentation.panels.conversation.web_message_view import WebMessageView


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_intercepted_navigation_failure_does_not_break_future_renders(monkeypatch, qapp):
    monkeypatch.setattr(web_message_view_module, "WEBENGINE_AVAILABLE", False)

    view = WebMessageView()
    try:
        applied_states: list[tuple[str, str]] = []
        pending_state = {
            "messages": "<div>messages</div>",
            "runtime": "<div>runtime</div>",
        }

        monkeypatch.setattr(
            view,
            "_apply_render_state",
            lambda messages, runtime: applied_states.append((messages, runtime)),
        )

        view._page_loaded = True
        view._pending_render_state = dict(pending_state)

        view._on_page_loaded(False)

        assert view._page_loaded is True
        assert view._pending_render_state == pending_state
        assert applied_states == []

        view._on_page_loaded(True)

        assert view._page_loaded is True
        assert view._pending_render_state is None
        assert applied_states == [(pending_state["messages"], pending_state["runtime"])]
    finally:
        view.deleteLater()
