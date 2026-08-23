import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget
from PyQt6.QtWebChannel import QWebChannel

from presentation.core.i18n_text import get_i18n_text
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
        self._frontend_ready = False
        self._state: Dict[str, Any] = {}
        self._schematic_document: Dict[str, Any] = {}
        self._schematic_write_result: Dict[str, Any] = {}
        self._raw_data_document: Dict[str, Any] = {}
        self._raw_data_viewport: Dict[str, Any] = {}
        self._raw_data_copy_result: Dict[str, Any] = {}
        self._bridge: Optional[SimulationWebBridge] = None
        self._channel: Optional[QWebChannel] = None
        self._web_view: Optional[QWebEngineView] = None
        self._fallback_label: Optional[QLabel] = None
        self._simulation_tab: Optional["SimulationTab"] = None
        # Coalesce all Python-side state changes that happen in one Qt tick
        # into one JS call.  The previous six independent dispatch paths let
        # React briefly combine a new result with the previous raw-data or
        # schematic document.
        self._dispatch_timer = QTimer(self)
        self._dispatch_timer.setSingleShot(True)
        self._dispatch_timer.timeout.connect(self._dispatch_snapshot)
        self._setup_ui()

    @property
    def bridge(self) -> Optional[SimulationWebBridge]:
        return self._bridge

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if not WEBENGINE_AVAILABLE:
            fallback = QLabel(get_i18n_text("dependency.pyqt_webengine_required", "Please install PyQt6-WebEngine"), self)
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
        self._web_view.loadStarted.connect(self._on_load_started)
        self._web_view.loadFinished.connect(self._on_load_finished)
        self._web_view.setUrl(app_resource_url(self._react_entry_resource_path()))
        self.setFocusProxy(self._web_view)
        layout.addWidget(self._web_view)

    def _react_entry_resource_path(self) -> str:
        project_root = Path(__file__).resolve().parents[3]
        react_entry = project_root / "resources" / "simulation" / "react-dist" / "index.html"
        if not react_entry.is_file():
            raise FileNotFoundError(f"Missing simulation React entry: {react_entry}")
        return "simulation/react-dist/index.html"

    def _on_load_started(self) -> None:
        self._page_loaded = False
        self._frontend_ready = False

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            return
        self._page_loaded = True

    def _on_ready(self) -> None:
        self._page_loaded = True
        self._frontend_ready = True
        self._dispatch_timer.stop()
        self._dispatch_snapshot()

    def set_state(self, state: Dict[str, Any]) -> None:
        normalized = state if isinstance(state, dict) else {}
        if normalized == self._state:
            return
        self._state = normalized
        self._schedule_snapshot_dispatch()

    def set_schematic_document(self, state: Dict[str, Any]) -> None:
        normalized = state if isinstance(state, dict) else {}
        if normalized == self._schematic_document:
            return
        self._schematic_document = normalized
        self._schedule_snapshot_dispatch()

    def finish_schematic_write(self, state: Dict[str, Any]) -> None:
        normalized = state if isinstance(state, dict) else {}
        if normalized == self._schematic_write_result:
            return
        self._schematic_write_result = normalized
        self._schedule_snapshot_dispatch()

    def set_raw_data_document(self, state: Dict[str, Any]) -> None:
        normalized = state if isinstance(state, dict) else {}
        if normalized == self._raw_data_document:
            return
        self._raw_data_document = normalized
        self._schedule_snapshot_dispatch()

    def set_raw_data_viewport(self, state: Dict[str, Any]) -> None:
        normalized = state if isinstance(state, dict) else {}
        if normalized == self._raw_data_viewport:
            return
        self._raw_data_viewport = normalized
        self._schedule_snapshot_dispatch()

    def finish_raw_data_copy(self, state: Dict[str, Any]) -> None:
        normalized = state if isinstance(state, dict) else {}
        if normalized == self._raw_data_copy_result:
            return
        self._raw_data_copy_result = normalized
        self._schedule_snapshot_dispatch()

    def attach_simulation_tab(self, simulation_tab: Optional["SimulationTab"]) -> None:
        if simulation_tab is self._simulation_tab:
            return
        if self._simulation_tab is not None:
            try:
                self._simulation_tab.authoritative_frontend_state_changed.disconnect(self.set_state)
            except Exception:
                pass
            try:
                self._simulation_tab.schematic_document_changed.disconnect(self.set_schematic_document)
            except Exception:
                pass
            try:
                self._simulation_tab.schematic_write_result_changed.disconnect(self.finish_schematic_write)
            except Exception:
                pass
            try:
                self._simulation_tab.raw_data_document_changed.disconnect(self.set_raw_data_document)
            except Exception:
                pass
            try:
                self._simulation_tab.raw_data_viewport_changed.disconnect(self.set_raw_data_viewport)
            except Exception:
                pass
            try:
                self._simulation_tab.raw_data_copy_result_changed.disconnect(self.finish_raw_data_copy)
            except Exception:
                pass
        self._simulation_tab = simulation_tab
        if self._simulation_tab is None:
            self.set_state({})
            self.set_schematic_document({})
            self.finish_schematic_write({})
            self.set_raw_data_document({})
            self.set_raw_data_viewport({})
            self.finish_raw_data_copy({})
            return
        self._simulation_tab.authoritative_frontend_state_changed.connect(self.set_state)
        self._simulation_tab.schematic_document_changed.connect(self.set_schematic_document)
        self._simulation_tab.schematic_write_result_changed.connect(self.finish_schematic_write)
        self._simulation_tab.raw_data_document_changed.connect(self.set_raw_data_document)
        self._simulation_tab.raw_data_viewport_changed.connect(self.set_raw_data_viewport)
        self._simulation_tab.raw_data_copy_result_changed.connect(self.finish_raw_data_copy)
        if self._bridge is not None:
            self._simulation_tab.bind_web_bridge(self._bridge)
        self.set_state(self._simulation_tab.get_authoritative_frontend_state())
        self.set_schematic_document(self._simulation_tab.get_authoritative_schematic_document())
        self.finish_schematic_write(self._simulation_tab.get_authoritative_schematic_write_result())
        self.set_raw_data_document(self._simulation_tab.get_authoritative_raw_data_document())
        self.set_raw_data_viewport(self._simulation_tab.get_authoritative_raw_data_viewport())
        self.finish_raw_data_copy(self._simulation_tab.get_authoritative_raw_data_copy_result())

    def cleanup(self) -> None:
        self._dispatch_timer.stop()
        self._frontend_ready = False
        self._page_loaded = False
        if self._web_view is not None:
            try:
                self._web_view.loadStarted.disconnect(self._on_load_started)
            except Exception:
                pass
            try:
                self._web_view.loadFinished.disconnect(self._on_load_finished)
            except Exception:
                pass
        if self._bridge is not None:
            try:
                self._bridge.ready.disconnect(self._on_ready)
            except Exception:
                pass
        self.attach_simulation_tab(None)

    def _schedule_snapshot_dispatch(self) -> None:
        if self._web_view is None or not self._page_loaded or not self._frontend_ready:
            if self._fallback_label is not None:
                runtime = self._state.get("simulation_runtime", {}) if isinstance(self._state, dict) else {}
                self._fallback_label.setText(str(runtime.get("project_root") or get_i18n_text("panel.simulation", "Simulation Results")))
            return
        if not self._dispatch_timer.isActive():
            self._dispatch_timer.start(0)

    def _dispatch_snapshot(self) -> None:
        if self._web_view is None or not self._page_loaded or not self._frontend_ready:
            return
        snapshot = {
            "state": self._state,
            "schematicDocument": self._schematic_document,
            "schematicWriteResult": self._schematic_write_result,
            "rawDataDocument": self._raw_data_document,
            "rawDataViewport": self._raw_data_viewport,
            "rawDataCopyResult": self._raw_data_copy_result,
        }
        # ensure_ascii escapes JS line separators as well as arbitrary source
        # text, keeping the JSON literal safe inside runJavaScript.
        script = "window.simulationApp && window.simulationApp.applySnapshot(%s);" % json.dumps(
            snapshot,
            ensure_ascii=True,
        )
        self._web_view.page().runJavaScript(script)


__all__ = ["SimulationWebHost"]
