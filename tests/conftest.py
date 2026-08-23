import pytest
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    """Keep one Qt application with a real program-name argument.

    Qt WebEngine initializes Chromium's command-line state from argv. An empty
    argv is a fatal Qt contract violation on Windows, so every widget test uses
    this single process-wide application instead of defining local fixtures.
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication(["circuit-design-ai-tests"])
    yield app
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
