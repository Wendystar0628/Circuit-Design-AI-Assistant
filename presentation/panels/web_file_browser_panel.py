import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget
from PyQt6.QtWebChannel import QWebChannel
from presentation.core.web_resource_host import app_resource_url, configure_app_web_view

from shared.path_utils import normalize_identity_path
from shared.workspace_file_types import (
    file_type_label,
    is_hidden_workspace_entry,
    workspace_entry_icon_key,
    workspace_entry_icon_tone,
)

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except ImportError:
    QWebEngineView = None
    WEBENGINE_AVAILABLE = False


class _ExplorerBridge(QObject):
    ready = pyqtSignal()
    open_file_requested = pyqtSignal(str)
    refresh_requested = pyqtSignal()

    @pyqtSlot()
    def markReady(self) -> None:
        self.ready.emit()

    @pyqtSlot(str)
    def openFile(self, path: str) -> None:
        self.open_file_requested.emit(str(path or ""))

    @pyqtSlot()
    def requestRefresh(self) -> None:
        self.refresh_requested.emit()


class FileBrowserPanel(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._i18n_manager = None
        self._event_bus = None
        self._logger = None
        self._root_path: Optional[str] = None
        self._workspace_file_state: Dict[str, Any] = {"items": []}
        self._page_loaded = False
        self._bridge: Optional[_ExplorerBridge] = None
        self._channel: Optional[QWebChannel] = None
        self._web_view: Optional[QWebEngineView] = None
        self._fallback_label: Optional[QLabel] = None
        self._setup_ui()
        self._subscribe_events()

    @property
    def i18n_manager(self):
        if self._i18n_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_I18N_MANAGER
                self._i18n_manager = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            except Exception:
                pass
        return self._i18n_manager

    @property
    def event_bus(self):
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus

    @property
    def logger(self):
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("web_file_browser_panel")
            except Exception:
                pass
        return self._logger

    def _get_text(self, key: str, default: Optional[str] = None) -> str:
        if self.i18n_manager:
            return self.i18n_manager.get_text(key, default)
        return default if default else key

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
        self._bridge = _ExplorerBridge(self)
        self._bridge.ready.connect(self._on_ready)
        self._bridge.open_file_requested.connect(self._on_open_file_requested)
        self._bridge.refresh_requested.connect(self.refresh)
        self._channel = QWebChannel(self)
        self._channel.registerObject("workspaceExplorerBridge", self._bridge)
        self._web_view = QWebEngineView(self)
        self._web_view.page().setWebChannel(self._channel)
        configure_app_web_view(self._web_view)
        self.setFocusProxy(self._web_view)
        self._web_view.loadFinished.connect(self._on_load_finished)
        self._web_view.setUrl(app_resource_url("workspace/workspace_explorer.html"))
        layout.addWidget(self._web_view)

    def _on_load_finished(self, ok: bool) -> None:
        self._page_loaded = bool(ok)
        if self._page_loaded:
            self._dispatch_state()

    def _on_ready(self) -> None:
        self._page_loaded = True
        self._dispatch_state()

    def _on_open_file_requested(self, path: str) -> None:
        display_path = str(path or "")
        if not display_path or not os.path.isfile(display_path):
            return
        self.file_selected.emit(display_path)

    def _state_payload(self) -> Dict[str, Any]:
        root_path = self._root_path or ""
        folder_name = os.path.basename(root_path) if root_path else ""
        has_project = bool(root_path)
        tree_nodes = self._build_tree_nodes()
        empty_message = self._get_text(
            "hint.select_file",
            "Select a file to view",
        ) if has_project else self._get_text(
            "hint.open_workspace",
            "Open a workspace to get started",
        )
        if has_project and not tree_nodes:
            empty_message = self._get_text("file_browser.empty", "No files to display")
        return {
            "title": folder_name.upper() if folder_name else self._get_text("panel.file_browser", "EXPLORER"),
            "collapseTooltip": self._get_text("file_browser.collapse_all", "Collapse All"),
            "refreshTooltip": self._get_text("file_browser.refresh", "Refresh"),
            "emptyMessage": empty_message,
            "tree": tree_nodes,
        }

    def _dispatch_state(self) -> None:
        payload = self._state_payload()
        if self._web_view is None or not self._page_loaded:
            if self._fallback_label is not None:
                self._fallback_label.setText(payload.get("emptyMessage", ""))
            return
        script = "window.workspaceExplorerApp && window.workspaceExplorerApp.setState(%s);" % json.dumps(payload, ensure_ascii=False)
        self._web_view.page().runJavaScript(script)

    def _workspace_sets(self) -> Tuple[set[str], set[str], str]:
        state = self._workspace_file_state if isinstance(self._workspace_file_state, dict) else {}
        items = state.get("items", []) if isinstance(state, dict) else []
        open_identity_paths = set()
        dirty_identity_paths = set()
        active_identity_path = ""
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path", "") or "")
            identity_path = str(item.get("identity_path", "") or "")
            if not identity_path and path:
                identity_path = normalize_identity_path(path)
            if not identity_path:
                continue
            open_identity_paths.add(identity_path)
            if bool(item.get("is_dirty", False)):
                dirty_identity_paths.add(identity_path)
            if bool(item.get("is_active", False)):
                active_identity_path = identity_path
        return open_identity_paths, dirty_identity_paths, active_identity_path

    def _build_tree_nodes(self) -> list[Dict[str, Any]]:
        root_path = self._root_path or ""
        if not root_path or not os.path.isdir(root_path):
            return []
        open_identity_paths, dirty_identity_paths, active_identity_path = self._workspace_sets()
        nodes, _ = self._build_directory_nodes(
            Path(root_path),
            open_identity_paths,
            dirty_identity_paths,
            active_identity_path,
        )
        return nodes

    def _build_directory_nodes(
        self,
        folder_path: Path,
        open_identity_paths: set[str],
        dirty_identity_paths: set[str],
        active_identity_path: str,
    ) -> Tuple[list[Dict[str, Any]], bool]:
        nodes = []
        has_active_content = False
        try:
            entries = sorted(
                folder_path.iterdir(),
                key=lambda item: (not item.is_dir(), item.name.lower()),
            )
        except Exception:
            return [], False

        for entry in entries:
            entry_name = entry.name
            try:
                is_directory = entry.is_dir()
            except Exception:
                continue
            if is_hidden_workspace_entry(entry_name, is_directory):
                continue
            entry_path = str(entry)
            if is_directory:
                child_nodes, child_has_active_content = self._build_directory_nodes(
                    entry,
                    open_identity_paths,
                    dirty_identity_paths,
                    active_identity_path,
                )
                nodes.append({
                    "name": entry_name,
                    "path": entry_path,
                    "isDirectory": True,
                    "isOpen": False,
                    "isDirty": False,
                    "isActive": False,
                    "iconKey": workspace_entry_icon_key(entry_name, is_directory=True),
                    "iconTone": workspace_entry_icon_tone(entry_name, is_directory=True),
                    "typeLabel": "Folder",
                    "defaultExpanded": child_has_active_content,
                    "children": child_nodes,
                })
                has_active_content = has_active_content or child_has_active_content
                continue

            identity_path = normalize_identity_path(entry_path)
            is_open = identity_path in open_identity_paths
            is_dirty = identity_path in dirty_identity_paths
            is_active = identity_path == active_identity_path
            nodes.append({
                "name": entry_name,
                "path": entry_path,
                "isDirectory": False,
                "isOpen": is_open,
                "isDirty": is_dirty,
                "isActive": is_active,
                "iconKey": workspace_entry_icon_key(entry_name),
                "iconTone": workspace_entry_icon_tone(entry_name),
                "typeLabel": file_type_label(entry_name),
                "defaultExpanded": False,
                "children": [],
            })
            has_active_content = has_active_content or is_open or is_dirty or is_active

        return nodes, has_active_content

    def set_root_path(self, folder_path: str) -> None:
        display_path = str(folder_path or "")
        if not display_path or not os.path.isdir(display_path):
            if self.logger:
                self.logger.warning(f"Invalid folder path: {folder_path}")
            return
        self._root_path = display_path
        self._dispatch_state()

    def refresh(self) -> None:
        self._dispatch_state()

    def clear(self) -> None:
        self._root_path = None
        self._workspace_file_state = {"items": []}
        self._dispatch_state()

    def set_workspace_file_state(self, state: Dict[str, Any]) -> None:
        self._workspace_file_state = dict(state) if isinstance(state, dict) else {"items": []}
        self._dispatch_state()

    def retranslate_ui(self) -> None:
        self._dispatch_state()

    def _subscribe_events(self) -> None:
        if self.event_bus:
            from shared.event_types import (
                EVENT_LANGUAGE_CHANGED,
                EVENT_FILE_CHANGED,
                EVENT_STATE_PROJECT_OPENED,
                EVENT_STATE_PROJECT_CLOSED,
                EVENT_WORKSPACE_SYNC_REQUIRED,
            )
            self.event_bus.subscribe(EVENT_LANGUAGE_CHANGED, self._on_language_changed)
            self.event_bus.subscribe(EVENT_FILE_CHANGED, self._on_file_changed)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_OPENED, self._on_project_opened)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_CLOSED, self._on_project_closed)
            self.event_bus.subscribe(EVENT_WORKSPACE_SYNC_REQUIRED, self._on_workspace_sync_required)

    def _on_language_changed(self, event_data: Dict[str, Any]) -> None:
        self.retranslate_ui()

    def _on_project_opened(self, event_data: Dict[str, Any]) -> None:
        data = event_data.get("data", {})
        project_path = data.get("path") if isinstance(data, dict) else None
        if project_path:
            self.set_root_path(project_path)

    def _on_project_closed(self, event_data: Dict[str, Any]) -> None:
        self.clear()

    def _on_workspace_sync_required(self, event_data: Dict[str, Any]) -> None:
        if not self._root_path:
            return
        data = event_data.get("data", event_data)
        if not isinstance(data, dict):
            return
        project_root = str(data.get("project_root", "") or "")
        if project_root:
            current_root = os.path.normcase(os.path.abspath(self._root_path))
            incoming_root = os.path.normcase(os.path.abspath(project_root))
            if current_root != incoming_root:
                return
        self._dispatch_state()

    def _on_file_changed(self, event_data: Dict[str, Any]) -> None:
        if not self._root_path:
            return
        data = event_data.get("data", event_data)
        if not isinstance(data, dict):
            return
        root_path = os.path.normcase(os.path.abspath(self._root_path))
        for changed_path in (str(data.get("path", "") or ""), str(data.get("dest_path", "") or "")):
            if not changed_path:
                continue
            normalized = os.path.normcase(os.path.abspath(changed_path))
            try:
                if os.path.commonpath([root_path, normalized]) == root_path:
                    self._dispatch_state()
                    break
            except ValueError:
                continue


__all__ = ["FileBrowserPanel"]
