import json
from typing import Any, Dict, Optional

from PyQt6.QtCore import QObject, QEvent, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget
from PyQt6.QtWebChannel import QWebChannel

from presentation.core.i18n_text import get_i18n_text
from presentation.core.web_resource_host import app_resource_url, configure_app_web_view

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except ImportError:
    QWebEngineView = None
    WEBENGINE_AVAILABLE = False


class _MenuBarBridge(QObject):
    ready = pyqtSignal()
    menu_toggle_requested = pyqtSignal(str, int, int)
    menu_hover_requested = pyqtSignal(str, int, int)
    dismiss_requested = pyqtSignal()

    @pyqtSlot()
    def notifyReady(self) -> None:
        self.ready.emit()

    @pyqtSlot(str, int, int)
    def toggleMenu(self, menu_id: str, left: int, width: int) -> None:
        self.menu_toggle_requested.emit(str(menu_id or ""), int(left or 0), int(width or 0))

    @pyqtSlot(str, int, int)
    def hoverMenu(self, menu_id: str, left: int, width: int) -> None:
        self.menu_hover_requested.emit(str(menu_id or ""), int(left or 0), int(width or 0))

    @pyqtSlot()
    def dismissMenus(self) -> None:
        self.dismiss_requested.emit()


class _MenuPopupBridge(QObject):
    ready = pyqtSignal()
    action_requested = pyqtSignal(str)
    dismiss_requested = pyqtSignal()

    @pyqtSlot()
    def notifyReady(self) -> None:
        self.ready.emit()

    @pyqtSlot(str)
    def triggerAction(self, action_id: str) -> None:
        self.action_requested.emit(str(action_id or ""))

    @pyqtSlot()
    def dismiss(self) -> None:
        self.dismiss_requested.emit()


class WebMenuBar(QWidget):
    action_triggered = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._host_window = parent if isinstance(parent, QWidget) else None
        self._state: Dict[str, Any] = {"brandLabel": "", "menus": []}
        self._open_menu_id = ""
        self._anchor_left = 0
        self._anchor_width = 0
        self._bar_page_loaded = False
        self._popup_page_loaded = False
        self._bridge: Optional[_MenuBarBridge] = None
        self._popup_bridge: Optional[_MenuPopupBridge] = None
        self._channel: Optional[QWebChannel] = None
        self._popup_channel: Optional[QWebChannel] = None
        self._web_view: Optional[QWebEngineView] = None
        self._overlay_host: Optional[QWidget] = None
        self._popup_view: Optional[QWebEngineView] = None
        self._fallback_label: Optional[QLabel] = None
        self.setFixedHeight(42)
        self._setup_ui()
        if self._host_window is not None:
            self._host_window.installEventFilter(self)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if not WEBENGINE_AVAILABLE:
            fallback = QLabel(get_i18n_text("dependency.pyqt_webengine_required", "Please install PyQt6-WebEngine"), self)
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            layout.addWidget(fallback)
            self._fallback_label = fallback
            return

        self._bridge = _MenuBarBridge(self)
        self._bridge.ready.connect(self._on_bar_ready)
        self._bridge.menu_toggle_requested.connect(self._on_menu_toggle_requested)
        self._bridge.menu_hover_requested.connect(self._on_menu_hover_requested)
        self._bridge.dismiss_requested.connect(self.close_menus)

        self._channel = QWebChannel(self)
        self._channel.registerObject("menuBarBridge", self._bridge)

        self._web_view = QWebEngineView(self)
        self._web_view.page().setWebChannel(self._channel)
        configure_app_web_view(self._web_view)
        self._web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._web_view.loadFinished.connect(self._on_bar_load_finished)
        self.setFocusProxy(self._web_view)
        self._web_view.setUrl(app_resource_url("menu/menu_bar.html"))
        layout.addWidget(self._web_view)

        self._setup_popup_overlay()

    def _setup_popup_overlay(self) -> None:
        if self._host_window is None or not WEBENGINE_AVAILABLE:
            return

        self._popup_bridge = _MenuPopupBridge(self)
        self._popup_bridge.ready.connect(self._on_popup_ready)
        self._popup_bridge.action_requested.connect(self._on_popup_action_requested)
        self._popup_bridge.dismiss_requested.connect(self.close_menus)

        self._popup_channel = QWebChannel(self)
        self._popup_channel.registerObject("menuPopupBridge", self._popup_bridge)

        self._overlay_host = QWidget(self._host_window)
        self._overlay_host.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._overlay_host.setStyleSheet("background: transparent;")
        self._overlay_host.hide()

        self._popup_view = QWebEngineView(self._overlay_host)
        self._popup_view.page().setWebChannel(self._popup_channel)
        configure_app_web_view(self._popup_view)
        self._popup_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._popup_view.loadFinished.connect(self._on_popup_load_finished)
        self._popup_view.setStyleSheet("background: transparent;")
        self._popup_view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        try:
            self._popup_view.page().setBackgroundColor(QColor(0, 0, 0, 0))
        except Exception:
            pass
        self._popup_view.setUrl(app_resource_url("menu/menu_popup.html"))
        self._update_overlay_geometry()

    def _normalize_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(state, dict):
            return {"brandLabel": "", "menus": []}
        menus = state.get("menus", [])
        return {
            "brandLabel": str(state.get("brandLabel", "") or ""),
            "menus": list(menus) if isinstance(menus, list) else [],
        }

    def _find_menu(self, menu_id: str) -> Optional[Dict[str, Any]]:
        for menu in self._state.get("menus", []):
            if isinstance(menu, dict) and str(menu.get("id", "") or "") == str(menu_id or ""):
                return menu
        return None

    def _on_bar_load_finished(self, ok: bool) -> None:
        self._bar_page_loaded = bool(ok)
        if self._bar_page_loaded:
            self._dispatch_bar_state()

    def _on_bar_ready(self) -> None:
        self._bar_page_loaded = True
        self._dispatch_bar_state()

    def _on_popup_load_finished(self, ok: bool) -> None:
        self._popup_page_loaded = bool(ok)
        if self._popup_page_loaded and self._open_menu_id:
            self._dispatch_popup_state()

    def _on_popup_ready(self) -> None:
        self._popup_page_loaded = True
        if self._open_menu_id:
            self._dispatch_popup_state()

    def _dispatch_bar_state(self) -> None:
        if self._web_view is None or not self._bar_page_loaded:
            if self._fallback_label is not None:
                self._fallback_label.setText(self._state.get("brandLabel") or get_i18n_text("app.title.short", "Circuit AI"))
            return
        payload = {
            "brandLabel": self._state.get("brandLabel", ""),
            "menus": self._state.get("menus", []),
            "openMenuId": self._open_menu_id,
        }
        script = "window.menuBarApp && window.menuBarApp.setState(%s);" % json.dumps(payload, ensure_ascii=False)
        self._web_view.page().runJavaScript(script)

    def _dispatch_popup_state(self) -> None:
        if self._popup_view is None or not self._popup_page_loaded:
            return
        payload = {
            "menu": self._find_menu(self._open_menu_id),
            "anchorLeft": self._anchor_left,
            "anchorWidth": self._anchor_width,
            "viewportWidth": self._overlay_host.width() if self._overlay_host is not None else 0,
            "viewportHeight": self._overlay_host.height() if self._overlay_host is not None else 0,
        }
        script = "window.menuPopupApp && window.menuPopupApp.setState(%s);" % json.dumps(payload, ensure_ascii=False)
        self._popup_view.page().runJavaScript(script)

    def _update_overlay_geometry(self) -> None:
        if self._overlay_host is None or self._host_window is None:
            return
        overlay_height = max(0, self._host_window.height() - self.height())
        self._overlay_host.setGeometry(0, self.height(), self._host_window.width(), overlay_height)
        if self._popup_view is not None:
            self._popup_view.setGeometry(self._overlay_host.rect())

    def _open_menu(self, menu_id: str, left: int, width: int) -> None:
        if not menu_id or self._find_menu(menu_id) is None:
            self.close_menus()
            return
        self._open_menu_id = str(menu_id or "")
        self._anchor_left = max(0, int(left or 0))
        self._anchor_width = max(0, int(width or 0))
        self._dispatch_bar_state()
        self._update_overlay_geometry()
        if self._overlay_host is not None:
            self._overlay_host.show()
            self._overlay_host.raise_()
        if self._popup_view is not None:
            self._popup_view.show()
            self._popup_view.raise_()
        self._dispatch_popup_state()

    def _on_menu_toggle_requested(self, menu_id: str, left: int, width: int) -> None:
        next_id = str(menu_id or "")
        if not next_id:
            self.close_menus()
            return
        if self._open_menu_id == next_id:
            self.close_menus()
            return
        self._open_menu(next_id, left, width)

    def _on_menu_hover_requested(self, menu_id: str, left: int, width: int) -> None:
        next_id = str(menu_id or "")
        if not self._open_menu_id or not next_id or self._open_menu_id == next_id:
            return
        self._open_menu(next_id, left, width)

    def _on_popup_action_requested(self, action_id: str) -> None:
        self.action_triggered.emit(str(action_id or ""))
        self.close_menus()

    def set_menu_state(self, state: Dict[str, Any]) -> None:
        self._state = self._normalize_state(state)
        if self._open_menu_id and self._find_menu(self._open_menu_id) is None:
            self._open_menu_id = ""
            if self._overlay_host is not None:
                self._overlay_host.hide()
        self._dispatch_bar_state()
        if self._open_menu_id:
            self._dispatch_popup_state()

    def close_menus(self) -> None:
        if not self._open_menu_id and (self._overlay_host is None or not self._overlay_host.isVisible()):
            return
        self._open_menu_id = ""
        if self._overlay_host is not None:
            self._overlay_host.hide()
        self._dispatch_bar_state()
        self._dispatch_popup_state()

    def eventFilter(self, watched, event) -> bool:
        if watched is self._host_window:
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Move):
                self._update_overlay_geometry()
                if self._open_menu_id:
                    self._dispatch_popup_state()
            elif event.type() in (QEvent.Type.Hide, QEvent.Type.Close, QEvent.Type.WindowDeactivate):
                self.close_menus()
        return super().eventFilter(watched, event)

    def closeEvent(self, event) -> None:
        if self._host_window is not None:
            self._host_window.removeEventFilter(self)
        self.close_menus()
        super().closeEvent(event)


__all__ = ["WebMenuBar"]
