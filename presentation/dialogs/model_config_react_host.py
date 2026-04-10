from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget
from PyQt6.QtWebChannel import QWebChannel

from presentation.core.web_resource_host import app_resource_url, configure_app_web_view
from presentation.dialogs.model_config_bridge import ModelConfigWebBridge

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except ImportError:
    QWebEngineView = None
    WEBENGINE_AVAILABLE = False


if WEBENGINE_AVAILABLE:
    class _ModelConfigReactWebView(QWebEngineView):
        pass
else:
    class _ModelConfigReactWebView:  # type: ignore[no-redef]
        pass


class ModelConfigReactHost(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._page_loaded = False
        self._state: Dict[str, Any] = {}
        self._pending_app_calls: List[str] = []
        self._bridge: Optional[ModelConfigWebBridge] = None
        self._channel: Optional[QWebChannel] = None
        self._web_view: Optional[_ModelConfigReactWebView] = None
        self._fallback_label: Optional[QLabel] = None
        self._setup_ui()

    @property
    def bridge(self) -> Optional[ModelConfigWebBridge]:
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

        self._bridge = ModelConfigWebBridge(self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("modelConfigBridge", self._bridge)
        self._web_view = _ModelConfigReactWebView(self)
        self._web_view.page().setWebChannel(self._channel)
        configure_app_web_view(self._web_view)
        self._web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._web_view.loadFinished.connect(self._on_load_finished)
        self._web_view.setUrl(app_resource_url(self._resolve_entry_resource_path()))
        layout.addWidget(self._web_view)

    def _resolve_entry_resource_path(self) -> str:
        project_root = Path(__file__).resolve().parents[2]
        react_entry = project_root / "resources" / "conversation" / "react-dist" / "model-config.html"
        if react_entry.is_file():
            return "conversation/react-dist/model-config.html"
        return "conversation/model_config_host.html"

    def set_state(self, state: Dict[str, Any]) -> None:
        self._state = state if isinstance(state, dict) else {}
        self._dispatch_state()

    def cleanup(self) -> None:
        self._pending_app_calls.clear()
        if self._web_view is not None:
            try:
                self._web_view.loadFinished.disconnect(self._on_load_finished)
            except Exception:
                pass

    def _on_load_finished(self, ok: bool) -> None:
        self._page_loaded = bool(ok)
        if self._page_loaded:
            self._dispatch_state()
            self._flush_pending_app_calls()

    def _dispatch_state(self) -> None:
        if self._web_view is None or not self._page_loaded:
            if self._fallback_label is not None:
                title = "Model Configuration"
                if isinstance(self._state, dict):
                    dialog = self._state.get("dialog", {})
                    if isinstance(dialog, dict):
                        title = str(dialog.get("title") or title)
                self._fallback_label.setText(title)
            return
        script = "window.modelConfigApp && window.modelConfigApp.setState(%s);" % json.dumps(
            self._state,
            ensure_ascii=False,
        )
        self._web_view.page().runJavaScript(script)

    def _run_app_script(self, script: str) -> None:
        if self._web_view is None or not self._page_loaded:
            self._pending_app_calls.append(script)
            return
        self._web_view.page().runJavaScript(script)

    def _flush_pending_app_calls(self) -> None:
        if self._web_view is None or not self._page_loaded or not self._pending_app_calls:
            return
        pending_calls = list(self._pending_app_calls)
        self._pending_app_calls.clear()
        for script in pending_calls:
            self._web_view.page().runJavaScript(script)


__all__ = ["ModelConfigReactHost", "WEBENGINE_AVAILABLE"]
