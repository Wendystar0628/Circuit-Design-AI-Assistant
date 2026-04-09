import json
from typing import Any, Dict, Optional, Tuple

from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget
from PyQt6.QtWebChannel import QWebChannel
from presentation.core.web_resource_host import app_resource_url, configure_app_web_view
from shared.workspace_file_types import language_for_extension

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except ImportError:
    QWebEngineView = None
    WEBENGINE_AVAILABLE = False


class _EditorBridge(QObject):
    ready = pyqtSignal()
    content_changed = pyqtSignal(str)
    cursor_changed = pyqtSignal(int, int)
    accept_file_requested = pyqtSignal()
    reject_file_requested = pyqtSignal()
    accept_hunk_requested = pyqtSignal(str)
    reject_hunk_requested = pyqtSignal(str)

    @pyqtSlot()
    def notifyReady(self) -> None:
        self.ready.emit()

    @pyqtSlot(str)
    def notifyContentChanged(self, content: str) -> None:
        self.content_changed.emit(str(content or ""))

    @pyqtSlot(int, int)
    def notifyCursorChanged(self, line: int, column: int) -> None:
        self.cursor_changed.emit(max(1, int(line or 1)), max(1, int(column or 1)))

    @pyqtSlot()
    def acceptFile(self) -> None:
        self.accept_file_requested.emit()

    @pyqtSlot()
    def rejectFile(self) -> None:
        self.reject_file_requested.emit()

    @pyqtSlot(str)
    def acceptHunk(self, hunk_id: str) -> None:
        self.accept_hunk_requested.emit(str(hunk_id or ""))

    @pyqtSlot(str)
    def rejectHunk(self, hunk_id: str) -> None:
        self.reject_hunk_requested.emit(str(hunk_id or ""))


class CodeEditor(QWidget):
    modification_changed = pyqtSignal(bool)
    cursor_position_changed = pyqtSignal(int, int)
    accept_file_requested = pyqtSignal(str)
    reject_file_requested = pyqtSignal(str)
    accept_hunk_requested = pyqtSignal(str, str)
    reject_hunk_requested = pyqtSignal(str, str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._file_path = ""
        self._content = ""
        self._baseline_content = ""
        self._pending_file_state: Optional[Dict[str, Any]] = None
        self._language = "plaintext"
        self._is_modified = False
        self._is_readonly = False
        self._cursor_position: Tuple[int, int] = (1, 1)
        self._page_loaded = False
        self._web_view: Optional[QWebEngineView] = None
        self._bridge: Optional[_EditorBridge] = None
        self._channel: Optional[QWebChannel] = None
        self._fallback_label: Optional[QLabel] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if not WEBENGINE_AVAILABLE:
            fallback = QLabel("请安装 PyQt6-WebEngine", self)
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            layout.addWidget(fallback)
            self._fallback_label = fallback
            return
        self._bridge = _EditorBridge(self)
        self._bridge.ready.connect(self._on_ready)
        self._bridge.content_changed.connect(self._on_content_changed)
        self._bridge.cursor_changed.connect(self._on_cursor_changed)
        self._bridge.accept_file_requested.connect(self._emit_accept_file_requested)
        self._bridge.reject_file_requested.connect(self._emit_reject_file_requested)
        self._bridge.accept_hunk_requested.connect(self._emit_accept_hunk_requested)
        self._bridge.reject_hunk_requested.connect(self._emit_reject_hunk_requested)
        self._channel = QWebChannel(self)
        self._channel.registerObject("editorBridge", self._bridge)
        self._web_view = QWebEngineView(self)
        self._web_view.page().setWebChannel(self._channel)
        configure_app_web_view(self._web_view)
        self.setFocusProxy(self._web_view)
        self._web_view.loadFinished.connect(self._on_load_finished)
        self._web_view.setUrl(app_resource_url("editor/code_editor.html"))
        layout.addWidget(self._web_view)

    def _on_load_finished(self, ok: bool) -> None:
        if ok:
            self._page_loaded = True
            self._dispatch_state()

    def _on_ready(self) -> None:
        self._page_loaded = True
        self._dispatch_state()

    def _on_content_changed(self, content: str) -> None:
        self._content = str(content or "")
        self.set_modified(True)

    def _on_cursor_changed(self, line: int, column: int) -> None:
        self._cursor_position = (max(1, int(line or 1)), max(1, int(column or 1)))
        self.cursor_position_changed.emit(*self._cursor_position)

    def _emit_accept_file_requested(self) -> None:
        if self._file_path:
            self.accept_file_requested.emit(self._file_path)

    def _emit_reject_file_requested(self) -> None:
        if self._file_path:
            self.reject_file_requested.emit(self._file_path)

    def _emit_accept_hunk_requested(self, hunk_id: str) -> None:
        if self._file_path and hunk_id:
            self.accept_hunk_requested.emit(self._file_path, hunk_id)

    def _emit_reject_hunk_requested(self, hunk_id: str) -> None:
        if self._file_path and hunk_id:
            self.reject_hunk_requested.emit(self._file_path, hunk_id)

    def _state_payload(self) -> Dict[str, Any]:
        pending_state = dict(self._pending_file_state) if isinstance(self._pending_file_state, dict) else None
        return {
            "content": self._content,
            "baselineContent": self._baseline_content,
            "language": self._language,
            "readOnly": self._is_readonly,
            "isModified": self._is_modified,
            "pendingFileState": pending_state,
        }

    def _dispatch_state(self) -> None:
        payload = self._state_payload()
        if self._web_view is None or not self._page_loaded:
            return
        script = "window.codeEditorApp && window.codeEditorApp.setState(%s);" % json.dumps(payload, ensure_ascii=False)
        self._web_view.page().runJavaScript(script)

    def _run_script(self, script: str) -> None:
        if self._web_view is None or not self._page_loaded:
            return
        self._web_view.page().runJavaScript(script)

    def set_file_path(self, path: str) -> None:
        self._file_path = str(path or "")

    def set_highlighter(self, ext: str) -> None:
        self._language = language_for_extension(ext)
        self._dispatch_state()

    def load_content(self, content: str) -> None:
        self._content = str(content or "")
        self._cursor_position = (1, 1)
        self.set_modified(False)
        self._dispatch_state()

    def toPlainText(self) -> str:
        return self._content

    def is_modified(self) -> bool:
        return self._is_modified

    def set_modified(self, modified: bool) -> None:
        new_value = bool(modified)
        if self._is_modified == new_value:
            if not new_value:
                self._dispatch_state()
            return
        self._is_modified = new_value
        self.modification_changed.emit(self._is_modified)
        self._dispatch_state()

    def set_pending_file_state(self, file_state: Optional[Dict[str, Any]]) -> None:
        self._pending_file_state = dict(file_state) if isinstance(file_state, dict) else None
        baseline_content = ""
        if isinstance(self._pending_file_state, dict):
            baseline_content = str(self._pending_file_state.get("baseline_content", "") or "")
        self._baseline_content = baseline_content
        self._dispatch_state()

    def setReadOnly(self, readonly: bool) -> None:
        self._is_readonly = bool(readonly)
        self._dispatch_state()

    def isReadOnly(self) -> bool:
        return self._is_readonly

    def get_cursor_position(self) -> Tuple[int, int]:
        return self._cursor_position

    def go_to_line(self, line_number: int, column_number: int = 1) -> None:
        line = max(1, int(line_number or 1))
        column = max(1, int(column_number or 1))
        self._cursor_position = (line, column)
        script = "window.codeEditorApp && window.codeEditorApp.goToLine(%d, %d);" % (line, column)
        self._run_script(script)

    def _execute_command(self, command_name: str) -> None:
        script = "window.codeEditorApp && window.codeEditorApp.executeCommand(%s);" % json.dumps(str(command_name or ""), ensure_ascii=False)
        self._run_script(script)

    def supports_edit_commands(self) -> bool:
        return bool(self._web_view is not None and self._page_loaded)

    def undo(self) -> None:
        self._execute_command("undo")

    def redo(self) -> None:
        self._execute_command("redo")

    def cut(self) -> None:
        self._execute_command("cut")

    def copy(self) -> None:
        self._execute_command("copy")

    def paste(self) -> None:
        self._execute_command("paste")

    def select_all(self) -> None:
        self._execute_command("selectAll")

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self._run_script("window.codeEditorApp && window.codeEditorApp.focus();")


__all__ = ["CodeEditor"]
