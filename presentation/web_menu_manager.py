from typing import Any, Callable, Dict, List, Optional
 
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QMainWindow
 
from presentation.widgets.web_menu_bar import WebMenuBar
 
 
class MenuManager:
    def __init__(self, main_window: QMainWindow):
        self._main_window = main_window
        self._callbacks: Dict[str, Callable] = {}
        self._actions: Dict[str, Dict[str, Any]] = {}
        self._recent_projects: List[Dict[str, Any]] = []
        self._recent_callbacks: Dict[str, Callable] = {}
        self._shortcuts: Dict[str, QShortcut] = {}
        self._menu_widget: Optional[WebMenuBar] = None
        self._panel_action_map = {
            "file_browser": "view_file_browser",
            "code_editor": "view_code_editor",
            "simulation": "view_simulation",
        }

    def _get_text(self, key: str, default: Optional[str] = None) -> str:
        if hasattr(self._main_window, "_get_text"):
            return self._main_window._get_text(key, default)
        return default if default else key

    def setup_menus(self, callbacks: Dict[str, Callable]) -> None:
        self._callbacks = dict(callbacks or {})
        self._build_action_registry()
        self._install_menu_widget()
        self._install_shortcuts()
        self._subscribe_events()
        self._sync_language_check()
        self._sync_view_action_checks()
        self._dispatch_state()

    def _install_menu_widget(self) -> None:
        if self._menu_widget is not None:
            return
        self._menu_widget = WebMenuBar(self._main_window)
        self._menu_widget.action_triggered.connect(self.trigger_action)
        native_menu_bar = self._main_window.menuBar()
        native_menu_bar.clear()
        native_menu_bar.hide()
        self._main_window.setMenuWidget(self._menu_widget)

    def _install_shortcuts(self) -> None:
        for shortcut in self._shortcuts.values():
            shortcut.deleteLater()
        self._shortcuts.clear()
        for action_id, meta in self._actions.items():
            sequence = str(meta.get("shortcut", "") or "")
            if not sequence:
                continue
            shortcut = QShortcut(QKeySequence(sequence), self._main_window)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(lambda aid=action_id: self.trigger_action(aid))
            self._shortcuts[action_id] = shortcut

    def _subscribe_events(self) -> None:
        event_bus = getattr(self._main_window, "event_bus", None)
        if not event_bus:
            return
        try:
            from shared.event_types import EVENT_PANEL_VISIBILITY_CHANGED
            event_bus.subscribe(EVENT_PANEL_VISIBILITY_CHANGED, self._on_panel_visibility_changed)
        except Exception:
            pass

    def _build_action_registry(self) -> None:
        self._actions.clear()
        self._register_action("file_open", "menu.file.open", "Open Workspace", handler=self._callbacks.get("on_open_workspace"), shortcut="Ctrl+O")
        self._register_action("file_close", "menu.file.close", "Close Workspace", handler=self._callbacks.get("on_close_workspace"), enabled=False)
        self._register_action("file_save", "menu.file.save", "Save", handler=self._callbacks.get("on_save_file"), enabled=False, shortcut="Ctrl+S")
        self._register_action("file_save_all", "menu.file.save_all", "Save All", handler=self._callbacks.get("on_save_all_files"), enabled=False, shortcut="Ctrl+Shift+S")
        self._register_action("file_exit", "menu.file.exit", "Exit", handler=self._main_window.close)

        self._register_action("edit_undo", "menu.edit.undo", "Undo", handler=self._callbacks.get("on_edit_undo"), enabled=False, shortcut="Ctrl+Z")
        self._register_action("edit_redo", "menu.edit.redo", "Redo", handler=self._callbacks.get("on_edit_redo"), enabled=False, shortcut="Ctrl+Y")
        self._register_action("edit_cut", "menu.edit.cut", "Cut", handler=self._callbacks.get("on_edit_cut"), enabled=False, shortcut="Ctrl+X")
        self._register_action("edit_copy", "menu.edit.copy", "Copy", handler=self._callbacks.get("on_edit_copy"), enabled=False, shortcut="Ctrl+C")
        self._register_action("edit_paste", "menu.edit.paste", "Paste", handler=self._callbacks.get("on_edit_paste"), enabled=False, shortcut="Ctrl+V")
        self._register_action("edit_select_all", "menu.edit.select_all", "Select All", handler=self._callbacks.get("on_edit_select_all"), enabled=False, shortcut="Ctrl+A")

        self._register_action("view_file_browser", "menu.view.file_browser", "File Browser", handler=self._callbacks.get("on_toggle_panel"), checkable=True, checked=True, invoke_with_checked=True, handler_arg="file_browser")
        self._register_action("view_code_editor", "menu.view.code_editor", "Code Editor", handler=self._callbacks.get("on_toggle_panel"), checkable=True, checked=True, invoke_with_checked=True, handler_arg="code_editor")
        self._register_action("view_simulation", "menu.view.simulation", "Simulation Results", handler=self._callbacks.get("on_toggle_panel"), checkable=True, checked=True, invoke_with_checked=True, handler_arg="simulation")
        self._register_action("view_conversation", "menu.view.conversation", "Conversation", handler=self._callbacks.get("on_show_conversation"))
        self._register_action("view_rag", "menu.view.knowledge", "Index Library", handler=self._callbacks.get("on_show_rag"))

        self._register_action("sim_run", "menu.simulation.run", "Run Simulation", handler=self._callbacks.get("on_run_simulation"), enabled=False, shortcut="F5")

        self._register_action("conversation_new", "menu.conversation.new", "New Conversation", handler=self._callbacks.get("on_new_conversation"), shortcut="Ctrl+Shift+N")
        self._register_action("conversation_history", "menu.conversation.history", "History", handler=self._callbacks.get("on_conversation_history"))
        self._register_action("conversation_compress", "menu.conversation.compress", "Compress Context", handler=self._callbacks.get("on_conversation_compress"))

        self._register_action("knowledge_open", "menu.knowledge.open", "Open Index Library", handler=self._callbacks.get("on_show_rag"))
        self._register_action("knowledge_rebuild", "menu.knowledge.rebuild", "Rebuild Index", handler=self._callbacks.get("on_reindex_knowledge"), enabled=False)
        self._register_action("knowledge_clear", "menu.knowledge.clear", "Clear Index", handler=self._callbacks.get("on_clear_knowledge"), enabled=False)

        self._register_action("model_config", "menu.model.config", "Model Configuration", handler=self._callbacks.get("on_api_config"))

        self._register_action("lang_en", "menu.language.english", "English", handler=lambda: self._set_language("en_US"), checkable=True, checked=False, group="language")
        self._register_action("lang_zh", "menu.language.chinese", "简体中文", handler=lambda: self._set_language("zh_CN"), checkable=True, checked=False, group="language")

        self._register_action("help_about", "menu.help.about", "About", handler=self._callbacks.get("on_about"))

    def _register_action(
        self,
        action_id: str,
        text_key: str,
        default_text: str,
        handler: Optional[Callable] = None,
        enabled: bool = True,
        checkable: bool = False,
        checked: bool = False,
        shortcut: str = "",
        group: str = "",
        invoke_with_checked: bool = False,
        handler_arg: Optional[str] = None,
    ) -> None:
        self._actions[action_id] = {
            "id": action_id,
            "text_key": text_key,
            "default_text": default_text,
            "handler": handler,
            "enabled": bool(enabled),
            "checkable": bool(checkable),
            "checked": bool(checked),
            "shortcut": shortcut,
            "group": group,
            "invoke_with_checked": bool(invoke_with_checked),
            "handler_arg": handler_arg,
        }

    def _dynamic_recent_items(self) -> List[Dict[str, Any]]:
        if not self._recent_projects:
            return [{
                "type": "action",
                "id": "recent_empty",
                "label": self._get_text("menu.file.recent.empty", "No Recent Projects"),
                "enabled": False,
                "checkable": False,
                "checked": False,
                "shortcut": "",
            }]
        items: List[Dict[str, Any]] = []
        for index, project in enumerate(self._recent_projects[:10]):
            path = str(project.get("path", "") or "")
            name = str(project.get("name", "") or "")
            exists = bool(project.get("exists", True))
            label = name or path or self._get_text("menu.file.recent.unnamed", "Unnamed Project")
            if not exists:
                label = f"{label} {self._get_text('menu.file.recent.not_exist', '(Not Exist)')}"
            items.append({
                "type": "action",
                "id": f"recent_project:{index}",
                "label": label,
                "enabled": exists,
                "checkable": False,
                "checked": False,
                "shortcut": "",
            })
        items.append({"type": "separator"})
        items.append({
            "type": "action",
            "id": "recent_clear",
            "label": self._get_text("menu.file.recent.clear", "Clear Recent"),
            "enabled": True,
            "checkable": False,
            "checked": False,
            "shortcut": "",
        })
        return items

    def _menu_item(self, action_id: str) -> Dict[str, Any]:
        meta = self._actions[action_id]
        return {
            "type": "action",
            "id": action_id,
            "label": self._get_text(meta["text_key"], meta["default_text"]),
            "enabled": bool(meta.get("enabled", True)),
            "checkable": bool(meta.get("checkable", False)),
            "checked": bool(meta.get("checked", False)),
            "shortcut": str(meta.get("shortcut", "") or ""),
        }

    def _menu_definition(self) -> List[Dict[str, Any]]:
        view_items = [
            self._menu_item("view_file_browser"),
            self._menu_item("view_code_editor"),
            self._menu_item("view_simulation"),
            {"type": "separator"},
            self._menu_item("view_conversation"),
            self._menu_item("view_rag"),
        ]
        return [
            {
                "id": "file",
                "label": self._get_text("menu.file", "File"),
                "items": [
                    self._menu_item("file_open"),
                    self._menu_item("file_close"),
                    {
                        "type": "submenu",
                        "id": "recent",
                        "label": self._get_text("menu.file.recent", "Recent Projects"),
                        "enabled": True,
                        "children": self._dynamic_recent_items(),
                    },
                    {"type": "separator"},
                    self._menu_item("file_save"),
                    self._menu_item("file_save_all"),
                    {"type": "separator"},
                    self._menu_item("file_exit"),
                ],
            },
            {
                "id": "edit",
                "label": self._get_text("menu.edit", "Edit"),
                "items": [
                    self._menu_item("edit_undo"),
                    self._menu_item("edit_redo"),
                    {"type": "separator"},
                    self._menu_item("edit_cut"),
                    self._menu_item("edit_copy"),
                    self._menu_item("edit_paste"),
                    self._menu_item("edit_select_all"),
                ],
            },
            {
                "id": "view",
                "label": self._get_text("menu.view", "View"),
                "items": view_items,
            },
            {
                "id": "simulation",
                "label": self._get_text("menu.simulation", "Simulation"),
                "items": [
                    self._menu_item("sim_run"),
                ],
            },
            {
                "id": "conversation",
                "label": self._get_text("menu.conversation", "Conversation"),
                "items": [
                    self._menu_item("conversation_new"),
                    self._menu_item("conversation_history"),
                    self._menu_item("conversation_compress"),
                ],
            },
            {
                "id": "knowledge",
                "label": self._get_text("menu.knowledge", "Index Library"),
                "items": [
                    self._menu_item("knowledge_open"),
                    self._menu_item("knowledge_rebuild"),
                    self._menu_item("knowledge_clear"),
                ],
            },
            {
                "id": "model",
                "label": self._get_text("menu.model", "Model"),
                "items": [
                    self._menu_item("model_config"),
                ],
            },
            {
                "id": "language",
                "label": self._get_text("menu.language", "Language"),
                "items": [
                    self._menu_item("lang_en"),
                    self._menu_item("lang_zh"),
                ],
            },
            {
                "id": "help",
                "label": self._get_text("menu.help", "Help"),
                "items": [
                    self._menu_item("help_about"),
                ],
            },
        ]

    def _dispatch_state(self) -> None:
        if self._menu_widget is None:
            return
        self._menu_widget.set_menu_state({
            "brandLabel": self._get_text("app.title.short", "Circuit AI"),
            "menus": self._menu_definition(),
        })

    def trigger_action(self, action_id: str) -> None:
        if action_id.startswith("recent_project:") or action_id == "recent_clear":
            self._trigger_recent_action(action_id)
            return
        meta = self._actions.get(action_id)
        if not meta or not meta.get("enabled", True):
            return
        if meta.get("checkable"):
            group = str(meta.get("group", "") or "")
            if group:
                if meta.get("checked"):
                    return
                self._set_group_checked(group, action_id)
            else:
                meta["checked"] = not bool(meta.get("checked", False))
            self._dispatch_state()
        handler = meta.get("handler")
        if callable(handler):
            if meta.get("invoke_with_checked"):
                panel_id = meta.get("handler_arg")
                handler(panel_id, bool(meta.get("checked", False)))
            else:
                handler()

    def _trigger_recent_action(self, action_id: str) -> None:
        if action_id == "recent_clear":
            callback = self._recent_callbacks.get("on_clear_recent")
            if callable(callback):
                callback()
            return
        if not action_id.startswith("recent_project:"):
            return
        try:
            index = int(action_id.split(":", 1)[1])
        except ValueError:
            return
        if index < 0 or index >= len(self._recent_projects):
            return
        callback = self._recent_callbacks.get("on_recent_click")
        if not callable(callback):
            return
        path = str(self._recent_projects[index].get("path", "") or "")
        if path:
            callback(path)

    def _get_current_language(self) -> str:
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_I18N_MANAGER

            manager = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            if manager:
                return str(manager.get_current_language() or "en_US")
        except Exception:
            pass
        return "en_US"

    def _set_language(self, lang_code: str) -> None:
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_I18N_MANAGER

            manager = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            if manager:
                manager.set_language(lang_code)
        except Exception:
            pass

    def _set_group_checked(self, group: str, action_id: str) -> None:
        for meta in self._actions.values():
            if meta.get("group") == group:
                meta["checked"] = meta.get("id") == action_id

    def _sync_language_check(self) -> None:
        current_language = self._get_current_language()
        self._set_group_checked("language", "lang_zh" if current_language == "zh_CN" else "lang_en")

    def _sync_view_action_checks(self) -> None:
        panel_manager = getattr(self._main_window, "panel_manager", None)
        if panel_manager is None:
            return
        for panel_id, action_id in self._panel_action_map.items():
            self.set_action_checked(action_id, panel_manager.is_panel_visible(panel_id))

    def _on_panel_visibility_changed(self, event_data: Dict[str, Any]) -> None:
        payload = event_data.get("data", event_data) if isinstance(event_data, dict) else {}
        panel_id = str(payload.get("panel_id", "") or "")
        visible = payload.get("visible")
        action_id = self._panel_action_map.get(panel_id)
        if action_id is not None and isinstance(visible, bool):
            self.set_action_checked(action_id, visible)

    def retranslate_ui(self) -> None:
        self._sync_language_check()
        self._dispatch_state()

    def update_recent_menu(self, recent_projects: list, callbacks: Dict[str, Callable]) -> None:
        self._recent_projects = list(recent_projects or [])
        self._recent_callbacks = dict(callbacks or {})
        self._dispatch_state()

    def get_action(self, name: str) -> Optional[Dict[str, Any]]:
        return self._actions.get(name)

    def get_menu(self, name: str) -> Optional[Dict[str, Any]]:
        for menu in self._menu_definition():
            if menu.get("id") == name:
                return menu
        return None

    def set_action_enabled(self, name: str, enabled: bool) -> None:
        action = self._actions.get(name)
        if not action:
            return
        action["enabled"] = bool(enabled)
        self._dispatch_state()

    def set_action_checked(self, name: str, checked: bool) -> None:
        action = self._actions.get(name)
        if not action or not action.get("checkable"):
            return
        group = str(action.get("group", "") or "")
        if group and checked:
            self._set_group_checked(group, name)
        else:
            action["checked"] = bool(checked)
        self._dispatch_state()
