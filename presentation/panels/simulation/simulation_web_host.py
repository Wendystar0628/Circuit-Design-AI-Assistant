import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget
from PyQt6.QtWebChannel import QWebChannel

from presentation.core.web_resource_host import app_resource_url, configure_app_web_view
from presentation.panels.simulation.simulation_web_bridge import SimulationWebBridge

if TYPE_CHECKING:
    from presentation.panels.simulation.simulation_tab import SimulationTab

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except ImportError:
    QWebEngineView = None
    WEBENGINE_AVAILABLE = False


class SimulationWebHost(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._page_loaded = False
        self._state: Dict[str, Any] = {}
        self._pending_app_calls: List[str] = []
        self._bridge: Optional[SimulationWebBridge] = None
        self._channel: Optional[QWebChannel] = None
        self._web_view: Optional[QWebEngineView] = None
        self._fallback_label: Optional[QLabel] = None
        self._simulation_tab: Optional["SimulationTab"] = None
        self._setup_ui()

    @property
    def bridge(self) -> Optional[SimulationWebBridge]:
        return self._bridge

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

        self._bridge = SimulationWebBridge(self)
        self._bridge.ready.connect(self._on_ready)
        self._channel = QWebChannel(self)
        self._channel.registerObject("simulationBridge", self._bridge)
        self._web_view = QWebEngineView(self)
        self._web_view.page().setWebChannel(self._channel)
        configure_app_web_view(self._web_view)
        self._web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self._web_view.loadFinished.connect(self._on_load_finished)
        self._web_view.setUrl(app_resource_url(self._resolve_entry_resource_path()))
        self.setFocusProxy(self._web_view)
        layout.addWidget(self._web_view)

    def _resolve_entry_resource_path(self) -> str:
        project_root = Path(__file__).resolve().parents[3]
        react_entry = project_root / "resources" / "simulation" / "react-dist" / "index.html"
        if react_entry.is_file():
            return "simulation/react-dist/index.html"
        return "simulation/simulation_host.html"

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

    def set_active_tab(self, tab_id: str) -> None:
        self._run_app_script(
            "window.simulationApp && window.simulationApp.activateTab && "
            "window.simulationApp.activateTab(%s);" % json.dumps(str(tab_id or "metrics"), ensure_ascii=False)
        )

    def attach_simulation_tab(self, simulation_tab: Optional["SimulationTab"]) -> None:
        if simulation_tab is self._simulation_tab:
            return
        if self._simulation_tab is not None:
            try:
                self._simulation_tab.authoritative_frontend_state_changed.disconnect(self.set_state)
            except Exception:
                pass
        self._simulation_tab = simulation_tab
        if self._simulation_tab is None:
            self.set_state({})
            return
        self._simulation_tab.authoritative_frontend_state_changed.connect(self.set_state)
        if self._bridge is not None:
            self._simulation_tab.bind_web_bridge(self._bridge)
        self.set_state(self._simulation_tab.get_authoritative_frontend_state())

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
        if self._simulation_tab is not None:
            try:
                self._simulation_tab.authoritative_frontend_state_changed.disconnect(self.set_state)
            except Exception:
                pass

    def _dispatch_state(self) -> None:
        if self._web_view is None or not self._page_loaded:
            if self._fallback_label is not None:
                runtime = self._state.get("simulation_runtime", {}) if isinstance(self._state, dict) else {}
                self._fallback_label.setText(str(runtime.get("project_root", "Simulation")))
            return
        script = "window.simulationApp && window.simulationApp.setState(%s);" % json.dumps(
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


__all__ = ["SimulationWebHost"]
