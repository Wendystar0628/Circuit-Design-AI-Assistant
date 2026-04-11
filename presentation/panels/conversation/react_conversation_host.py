import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget
from PyQt6.QtWebChannel import QWebChannel

from presentation.core.web_resource_host import app_resource_url, configure_app_web_view
from presentation.panels.conversation.conversation_web_bridge import ConversationWebBridge

try:
    from PyQt6.QtWebEngineCore import QWebEnginePage
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except ImportError:
    QWebEnginePage = None
    QWebEngineView = None
    WEBENGINE_AVAILABLE = False


if WEBENGINE_AVAILABLE:
    class _ConversationReactWebView(QWebEngineView):
        files_dropped = pyqtSignal(list)

        def dragEnterEvent(self, event) -> None:
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
                return
            super().dragEnterEvent(event)

        def dragMoveEvent(self, event) -> None:
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
                return
            super().dragMoveEvent(event)

        def dropEvent(self, event) -> None:
            paths: List[str] = []
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if path and os.path.isfile(path):
                    paths.append(path)
            if paths:
                self.files_dropped.emit(paths)
                event.acceptProposedAction()
                return
            super().dropEvent(event)
else:
    class _ConversationReactWebView:  # type: ignore[no-redef]
        pass


class ReactConversationHost(QWidget):
    files_dropped = pyqtSignal(list)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._page_loaded = False
        self._state: Dict[str, Any] = {}
        self._pending_app_calls: List[str] = []
        self._bridge: Optional[ConversationWebBridge] = None
        self._channel: Optional[QWebChannel] = None
        self._web_view: Optional[_ConversationReactWebView] = None
        self._fallback_label: Optional[QLabel] = None
        self._setup_ui()

    @property
    def bridge(self) -> Optional[ConversationWebBridge]:
        return self._bridge

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if not WEBENGINE_AVAILABLE:
            fallback = QLabel("请安装 PyQt6-WebEngine", self)
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding,
            )
            layout.addWidget(fallback)
            self._fallback_label = fallback
            return

        self._bridge = ConversationWebBridge(self)
        self._bridge.ready.connect(self._on_ready)
        self._channel = QWebChannel(self)
        self._channel.registerObject("conversationBridge", self._bridge)
        self._web_view = _ConversationReactWebView(self)
        self._web_view.page().setWebChannel(self._channel)
        configure_app_web_view(self._web_view)
        self._web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self._web_view.setAcceptDrops(True)
        self._web_view.loadFinished.connect(self._on_load_finished)
        self._web_view.files_dropped.connect(self.files_dropped)
        self._web_view.setUrl(app_resource_url(self._resolve_entry_resource_path()))
        self.setFocusProxy(self._web_view)
        layout.addWidget(self._web_view)

    def _resolve_entry_resource_path(self) -> str:
        project_root = Path(__file__).resolve().parents[3]
        react_entry = project_root / "resources" / "conversation" / "react-dist" / "index.html"
        if react_entry.is_file():
            return "conversation/react-dist/index.html"
        return "conversation/conversation_host.html"

    def _on_load_finished(self, ok: bool) -> None:
        self._page_loaded = bool(ok)
        if self._page_loaded:
            self._dispatch_state()
            self._flush_pending_app_calls()

    def _on_ready(self) -> None:
        self._page_loaded = True
        self._dispatch_state()
        self._flush_pending_app_calls()

    def set_state(self, state: Dict[str, Any]) -> None:
        self._state = state if isinstance(state, dict) else {}
        self._dispatch_state()

    def append_draft_attachments(self, attachments: List[Dict[str, Any]]) -> None:
        payload = attachments if isinstance(attachments, list) else []
        if not payload:
            return
        self._run_app_script(
            "window.conversationApp && window.conversationApp.appendDraftAttachments && "
            "window.conversationApp.appendDraftAttachments(%s);" % json.dumps(
                payload,
                ensure_ascii=False,
            )
        )

    def clear_draft_attachments(self) -> None:
        self._run_app_script(
            "window.conversationApp && window.conversationApp.clearDraftAttachments && "
            "window.conversationApp.clearDraftAttachments();"
        )

    def copy(self) -> None:
        if QWebEnginePage is None:
            return
        self._trigger_web_action(QWebEnginePage.WebAction.Copy)

    def select_all(self) -> None:
        if QWebEnginePage is None:
            return
        self._trigger_web_action(QWebEnginePage.WebAction.SelectAll)

    def cleanup(self) -> None:
        self._pending_app_calls.clear()
        if self._web_view is not None:
            try:
                self._web_view.loadFinished.disconnect(self._on_load_finished)
            except Exception:
                pass
        if self._bridge is not None:
            try:
                self._bridge.ready.disconnect(self._on_ready)
            except Exception:
                pass

    def _dispatch_state(self) -> None:
        if self._web_view is None or not self._page_loaded:
            if self._fallback_label is not None:
                session = self._state.get("session", {}) if isinstance(self._state, dict) else {}
                self._fallback_label.setText(str(session.get("name", "Conversation")))
            return
        script = "window.conversationApp && window.conversationApp.setState(%s);" % json.dumps(
            self._state,
            ensure_ascii=False,
        )
        self._web_view.page().runJavaScript(script)

    def _run_app_script(self, script: str) -> None:
        if self._web_view is None or not self._page_loaded:
            self._pending_app_calls.append(script)
            return
        self._web_view.page().runJavaScript(script)

    def _trigger_web_action(self, action) -> None:
        if self._web_view is None:
            return
        self._web_view.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._web_view.page().triggerAction(action)

    def _flush_pending_app_calls(self) -> None:
        if self._web_view is None or not self._page_loaded or not self._pending_app_calls:
            return
        pending_calls = list(self._pending_app_calls)
        self._pending_app_calls.clear()
        for script in pending_calls:
            self._web_view.page().runJavaScript(script)


__all__ = ["ReactConversationHost", "WEBENGINE_AVAILABLE"]
