from typing import Any, Dict, Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMenu, QMenuBar, QSizePolicy, QWidget


class WebMenuBar(QWidget):
    action_triggered = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._state: Dict[str, Any] = {"brandLabel": "", "menus": []}
        self._brand_label: Optional[QLabel] = None
        self._menu_bar: Optional[QMenuBar] = None
        self.setObjectName("nativeMenuBar")
        self.setFixedHeight(42)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        self._brand_label = QLabel(self)
        self._brand_label.setObjectName("menuBarBrand")
        self._brand_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._brand_label)

        self._menu_bar = QMenuBar(self)
        self._menu_bar.setObjectName("menuBarControl")
        self._menu_bar.setNativeMenuBar(False)
        self._menu_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._menu_bar, 1)

        self.setStyleSheet(
            """
            QWidget#nativeMenuBar {
                background: #f6f8fc;
                border-bottom: 1px solid #e2e8f0;
            }
            QLabel#menuBarBrand {
                padding: 0 10px;
                min-height: 28px;
                border-radius: 14px;
                background: rgba(37, 99, 235, 0.08);
                color: #1d4ed8;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 0.04em;
            }
            QMenuBar#menuBarControl {
                background: transparent;
                border: none;
            }
            QMenuBar#menuBarControl::item {
                padding: 6px 12px;
                margin: 0 2px;
                border-radius: 9px;
                background: transparent;
                color: #243244;
                font-size: 13px;
                font-weight: 600;
            }
            QMenuBar#menuBarControl::item:selected {
                background: rgba(37, 99, 235, 0.10);
                color: #1d4ed8;
            }
            QMenuBar#menuBarControl::item:pressed {
                background: #dbeafe;
                color: #1d4ed8;
            }
            QMenu#menuBarPopup {
                background: #ffffff;
                border: 1px solid #dbe4ef;
                border-radius: 10px;
                padding: 6px;
            }
            QMenu#menuBarPopup::item {
                padding: 7px 14px 7px 28px;
                margin: 1px 2px;
                border-radius: 6px;
                color: #213042;
            }
            QMenu#menuBarPopup::item:selected {
                background: #eff6ff;
                color: #1d4ed8;
            }
            QMenu#menuBarPopup::item:disabled {
                color: rgba(71, 85, 105, 0.48);
                background: transparent;
            }
            QMenu#menuBarPopup::separator {
                height: 1px;
                margin: 6px 8px;
                background: #e2e8f0;
            }
            QMenu#menuBarPopup::indicator {
                width: 12px;
                height: 12px;
                left: 10px;
            }
            """
        )

    def _normalize_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(state, dict):
            return {"brandLabel": "", "menus": []}
        menus = state.get("menus", [])
        return {
            "brandLabel": str(state.get("brandLabel", "") or ""),
            "menus": list(menus) if isinstance(menus, list) else [],
        }

    def _rebuild(self) -> None:
        if self._brand_label is not None:
            self._brand_label.setText(self._state.get("brandLabel") or "CIRCUIT AI")
        if self._menu_bar is None:
            return
        self._menu_bar.clear()
        for menu_data in self._state.get("menus", []):
            if not isinstance(menu_data, dict):
                continue
            label = str(menu_data.get("label", "") or "")
            if not label:
                continue
            menu = QMenu(label, self._menu_bar)
            menu.setObjectName("menuBarPopup")
            menu.setSeparatorsCollapsible(False)
            self._populate_menu(menu, menu_data.get("items", []))
            self._menu_bar.addMenu(menu)

    def _populate_menu(self, menu: QMenu, items: Any) -> None:
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", "action") or "action")
            if item_type == "separator":
                menu.addSeparator()
                continue

            children = item.get("children", [])
            has_children = isinstance(children, list) and len(children) > 0
            if item_type == "submenu" or has_children:
                submenu = QMenu(str(item.get("label", "") or ""), menu)
                submenu.setObjectName("menuBarPopup")
                submenu.setEnabled(bool(item.get("enabled", True)))
                submenu.setSeparatorsCollapsible(False)
                self._populate_menu(submenu, children)
                submenu_action = menu.addMenu(submenu)
                submenu_action.setEnabled(bool(item.get("enabled", True)))
                continue

            action = QAction(str(item.get("label", "") or ""), menu)
            action.setEnabled(bool(item.get("enabled", True)))
            action.setCheckable(bool(item.get("checkable", False)))
            action.setChecked(bool(item.get("checked", False)))
            shortcut = str(item.get("shortcut", "") or "")
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
                action.setShortcutVisibleInContextMenu(True)
            action_id = str(item.get("id", "") or "")
            if action_id:
                action.triggered.connect(lambda _checked=False, aid=action_id: self.action_triggered.emit(aid))
            menu.addAction(action)

    def set_menu_state(self, state: Dict[str, Any]) -> None:
        self._state = self._normalize_state(state)
        self._rebuild()


__all__ = ["WebMenuBar"]
