import json
from pathlib import PurePath
from typing import Any, Dict, Optional

from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget
from PyQt6.QtWebChannel import QWebChannel
from presentation.core.web_resource_host import app_resource_url, configure_app_web_view

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except ImportError:
    QWebEngineView = None
    WEBENGINE_AVAILABLE = False


class _WorkspaceTabsBridge(QObject):
    ready = pyqtSignal()
    activate_file_requested = pyqtSignal(str)
    close_file_requested = pyqtSignal(str)
    run_simulation_requested = pyqtSignal()
    stop_simulation_requested = pyqtSignal()

    @pyqtSlot()
    def markReady(self) -> None:
        self.ready.emit()

    @pyqtSlot(str)
    def activateFile(self, path: str) -> None:
        self.activate_file_requested.emit(str(path or ""))

    @pyqtSlot(str)
    def closeFile(self, path: str) -> None:
        self.close_file_requested.emit(str(path or ""))

    @pyqtSlot()
    def runSimulation(self) -> None:
        self.run_simulation_requested.emit()

    @pyqtSlot()
    def stopSimulation(self) -> None:
        self.stop_simulation_requested.emit()


class WebWorkspaceTabBar(QWidget):
    activate_file_requested = pyqtSignal(str)
    close_file_requested = pyqtSignal(str)
    run_simulation_requested = pyqtSignal()
    stop_simulation_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._page_loaded = False
        self._state: Dict[str, Any] = {
            "items": [],
            "emptyMessage": "",
            "runIconUrl": app_resource_url("icons/toolbar/play.svg").toString(),
            "stopIconUrl": app_resource_url("icons/toolbar/stop.svg").toString(),
            "simulationControl": {
                "isRunning": False,
                "isStopRequested": False,
                "canRun": False,
                "canStop": False,
                "primaryAction": "run",
                "primaryEnabled": False,
                "primaryTooltip": "",
            },
        }
        self._bridge: Optional[_WorkspaceTabsBridge] = None
        self._channel: Optional[QWebChannel] = None
        self._web_view: Optional[QWebEngineView] = None
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
        self._bridge = _WorkspaceTabsBridge(self)
        self._bridge.ready.connect(self._on_ready)
        self._bridge.activate_file_requested.connect(self.activate_file_requested.emit)
        self._bridge.close_file_requested.connect(self.close_file_requested.emit)
        self._bridge.run_simulation_requested.connect(self.run_simulation_requested.emit)
        self._bridge.stop_simulation_requested.connect(self.stop_simulation_requested.emit)
        self._channel = QWebChannel(self)
        self._channel.registerObject("workspaceTabsBridge", self._bridge)
        self._web_view = QWebEngineView(self)
        self._web_view.page().setWebChannel(self._channel)
        configure_app_web_view(self._web_view)
        self._web_view.loadFinished.connect(self._on_load_finished)
        self._web_view.setUrl(app_resource_url("workspace/workspace_tabs.html"))
        layout.addWidget(self._web_view)

    def _on_load_finished(self, ok: bool) -> None:
        self._page_loaded = bool(ok)
        if self._page_loaded:
            self._dispatch_state()

    def _on_ready(self) -> None:
        self._page_loaded = True
        self._dispatch_state()

    def set_workspace_file_state(self, state: Dict[str, Any], empty_message: str) -> None:
        items = []
        raw_items = state.get("items", []) if isinstance(state, dict) else []
        for item in raw_items if isinstance(raw_items, list) else []:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path", "") or "")
            if not path:
                continue
            name = str(item.get("name", "") or "")
            if not name:
                normalized_path = path.replace("\\", "/")
                name = PurePath(normalized_path).name or path
            items.append({
                "path": path,
                "name": name,
                "isActive": bool(item.get("is_active", False)),
                "isDirty": bool(item.get("is_dirty", False)),
            })
        self._state["items"] = items
        self._state["emptyMessage"] = str(empty_message or "")
        self._dispatch_state()

    def set_simulation_control_state(self, state: Dict[str, Any]) -> None:
        incoming = state if isinstance(state, dict) else {}
        self._state["simulationControl"] = {
            "isRunning": bool(incoming.get("isRunning", False)),
            "isStopRequested": bool(incoming.get("isStopRequested", False)),
            "canRun": bool(incoming.get("canRun", False)),
            "canStop": bool(incoming.get("canStop", False)),
            "primaryAction": str(incoming.get("primaryAction", "run") or "run"),
            "primaryEnabled": bool(incoming.get("primaryEnabled", False)),
            "primaryTooltip": str(incoming.get("primaryTooltip", "") or ""),
        }
        self._dispatch_state()

    def _dispatch_state(self) -> None:
        if self._web_view is None or not self._page_loaded:
            if self._fallback_label is not None:
                self._fallback_label.setText(self._state.get("emptyMessage", ""))
            return
        script = "window.workspaceTabsApp && window.workspaceTabsApp.setState(%s);" % json.dumps(self._state, ensure_ascii=False)
        self._web_view.page().runJavaScript(script)


__all__ = ["WebWorkspaceTabBar"]
