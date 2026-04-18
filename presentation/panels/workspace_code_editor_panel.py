import os
from contextlib import contextmanager
from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from shared.path_utils import normalize_absolute_path, normalize_identity_path
from shared.workspace_file_types import file_type_label

from .editor import CodeEditor
from .editor.workspace_editor_session import (
    VIEW_KIND_CODE,
    VIEW_KIND_IMAGE,
    VIEW_KIND_MARKDOWN,
    VIEW_KIND_PDF,
    VIEW_KIND_TABLE,
    VIEW_KIND_WORD,
    WorkspaceEditorSessionEntry,
    build_workspace_editor_session_entry,
    is_view_kind_editable,
)
from .viewers.image_viewer import ImageViewer
from .viewers.markdown_viewer import MarkdownViewer
from .viewers.docx_viewer import DocxViewer
from .viewers.pdf_viewer import PdfViewer
from .viewers.tabular_viewer import TabularViewer
from .web_workspace_tab_bar import WebWorkspaceTabBar


class CodeEditorPanel(QWidget):
    file_saved = pyqtSignal(str)
    open_workspace_requested = pyqtSignal()
    editable_file_state_changed = pyqtSignal(bool)
    workspace_file_state_changed = pyqtSignal(object)
    run_simulation_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._i18n_manager = None
        self._event_bus = None
        self._file_manager = None
        self._pending_workspace_edit_service = None
        self._logger = None
        self._session_entries: Dict[str, WorkspaceEditorSessionEntry] = {}
        self._active_identity_path = ""
        self._content_stack: Optional[QStackedWidget] = None
        self._web_tab_bar: Optional[WebWorkspaceTabBar] = None
        self._status_bar: Optional[QWidget] = None
        self._line_col_label: Optional[QLabel] = None
        self._encoding_label: Optional[QLabel] = None
        self._file_type_label: Optional[QLabel] = None
        self._readonly_label: Optional[QLabel] = None
        self._empty_widget: Optional[QWidget] = None
        self._open_workspace_btn: Optional[QPushButton] = None
        self._simulation_control_state: Dict[str, Any] = {
            "isRunning": False,
            "canRun": False,
            "primaryEnabled": False,
            "primaryTooltip": "",
        }
        self._pending_workspace_edit_connected = False
        self._state_batch_depth = 0
        self._needs_workspace_state_emit = False
        self._needs_editable_state_emit = False
        self._last_workspace_state: Optional[Dict[str, Any]] = None
        self._last_has_editable: Optional[bool] = None
        self._shared_code_editor: Optional[CodeEditor] = None
        self._shared_image_viewer: Optional[ImageViewer] = None
        self._shared_markdown_viewer: Optional[MarkdownViewer] = None
        self._shared_docx_viewer: Optional[DocxViewer] = None
        self._shared_pdf_viewer: Optional[PdfViewer] = None
        self._shared_tabular_viewer: Optional[TabularViewer] = None
        self._setup_ui()
        self._setup_shortcuts()
        self.retranslate_ui()
        self._subscribe_events()
        self._subscribe_pending_workspace_edit_state()

    @property
    def i18n_manager(self):
        if self._i18n_manager is None:
            from shared.service_names import SVC_I18N_MANAGER
            self._i18n_manager = self._get_optional_service(SVC_I18N_MANAGER)
        return self._i18n_manager

    @property
    def event_bus(self):
        if self._event_bus is None:
            from shared.service_names import SVC_EVENT_BUS
            self._event_bus = self._get_optional_service(SVC_EVENT_BUS)
        return self._event_bus

    @property
    def file_manager(self):
        if self._file_manager is None:
            from shared.service_names import SVC_FILE_MANAGER
            self._file_manager = self._get_optional_service(SVC_FILE_MANAGER)
        return self._file_manager

    @property
    def pending_workspace_edit_service(self):
        if self._pending_workspace_edit_service is None:
            from shared.service_names import SVC_PENDING_WORKSPACE_EDIT_SERVICE
            self._pending_workspace_edit_service = self._get_optional_service(
                SVC_PENDING_WORKSPACE_EDIT_SERVICE
            )
        if (
            self._pending_workspace_edit_service is not None
            and not self._pending_workspace_edit_connected
        ):
            try:
                self._pending_workspace_edit_service.state_changed.connect(
                    self._on_pending_workspace_edit_state_changed
                )
                self._pending_workspace_edit_connected = True
            except Exception as exc:
                if self.logger:
                    self.logger.warning(
                        f"Failed to connect pending workspace edit service: {exc}"
                    )
        return self._pending_workspace_edit_service

    @property
    def logger(self):
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("code_editor_panel")
            except Exception:
                pass
        return self._logger

    def _get_optional_service(self, service_name: str):
        try:
            from shared.service_locator import ServiceLocator
            return ServiceLocator.get_optional(service_name)
        except Exception as exc:
            if self.logger:
                self.logger.warning(
                    f"Failed to resolve optional service '{service_name}': {exc}"
                )
            return None

    def _normalize_display_path(self, path: str) -> str:
        return normalize_absolute_path(path)

    def _normalize_identity_path(self, path: str) -> str:
        return normalize_identity_path(path)

    def _find_entry(self, path: str) -> Optional[WorkspaceEditorSessionEntry]:
        if not path:
            return None
        return self._session_entries.get(self._normalize_identity_path(path))

    def _get_active_entry(self) -> Optional[WorkspaceEditorSessionEntry]:
        if not self._active_identity_path:
            return None
        return self._session_entries.get(self._active_identity_path)

    def _get_pending_file_state_map(
        self,
        state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        if state is None:
            service = self.pending_workspace_edit_service
            state = service.get_state() if service is not None else {}
        file_state_map: Dict[str, Dict[str, Any]] = {}
        if not isinstance(state, dict):
            return file_state_map
        for file_state in state.get("files", []) or []:
            if not isinstance(file_state, dict):
                continue
            identity_path = str(
                file_state.get("identity_path", file_state.get("path", "")) or ""
            )
            if not identity_path:
                continue
            file_state_map[self._normalize_identity_path(identity_path)] = file_state
        return file_state_map

    def _get_pending_file_state_for_path(
        self,
        path: str,
        state: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        file_state_map = self._get_pending_file_state_map(state)
        return file_state_map.get(self._normalize_identity_path(path))

    def _refresh_pending_workspace_edit_views(
        self,
        state: Optional[Dict[str, Any]] = None,
    ) -> None:
        entry = self._get_active_entry()
        if entry is None or entry.view_kind != VIEW_KIND_CODE:
            return
        editor = self._ensure_code_editor()
        editor.set_pending_file_state(self._get_pending_file_state_for_path(entry.path, state))

    def _subscribe_pending_workspace_edit_state(self) -> None:
        _ = self.pending_workspace_edit_service

    @contextmanager
    def _batch_state_updates(self):
        self._state_batch_depth += 1
        try:
            yield
        finally:
            self._state_batch_depth -= 1
            if self._state_batch_depth == 0:
                if self._needs_editable_state_emit:
                    self._needs_editable_state_emit = False
                    self._emit_editable_file_state(force=True)
                if self._needs_workspace_state_emit:
                    self._needs_workspace_state_emit = False
                    self._emit_workspace_file_state(force=True)

    def _schedule_state_refresh(self, *, editable: bool, workspace: bool) -> None:
        if self._state_batch_depth > 0:
            self._needs_editable_state_emit = self._needs_editable_state_emit or editable
            self._needs_workspace_state_emit = self._needs_workspace_state_emit or workspace
            return
        if editable:
            self._emit_editable_file_state()
        if workspace:
            self._emit_workspace_file_state()

    def _get_text(self, key: str, default: Optional[str] = None) -> str:
        if self.i18n_manager:
            return self.i18n_manager.get_text(key, default)
        return default if default else key

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tab_bar_container = QWidget()
        tab_bar_container.setFixedHeight(36)
        tab_bar_layout = QHBoxLayout(tab_bar_container)
        tab_bar_layout.setContentsMargins(0, 0, 0, 0)
        tab_bar_layout.setSpacing(0)

        self._web_tab_bar = WebWorkspaceTabBar(tab_bar_container)
        self._web_tab_bar.activate_file_requested.connect(self.switch_to_file)
        self._web_tab_bar.close_file_requested.connect(self._close_file_by_path)
        self._web_tab_bar.run_simulation_requested.connect(self.run_simulation_requested.emit)
        tab_bar_layout.addWidget(self._web_tab_bar, 1)

        self._content_stack = QStackedWidget()
        layout.addWidget(tab_bar_container)
        layout.addWidget(self._content_stack, 1)
        self._empty_widget = self._create_empty_widget()
        layout.addWidget(self._empty_widget)
        self._status_bar = self._create_status_bar()
        layout.addWidget(self._status_bar)
        self._update_empty_state()
        self._sync_workspace_tab_bar()

    def _create_empty_widget(self) -> QWidget:
        widget = QWidget()
        widget.setStyleSheet("background-color: #f5f5f5;")
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #888; font-size: 14px;")
        label.setProperty("empty_hint", True)
        layout.addWidget(label)
        self._open_workspace_btn = QPushButton()
        self._open_workspace_btn.setFixedSize(200, 50)
        self._open_workspace_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; border: none; "
            "border-radius: 8px; font-size: 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #45a049; }"
        )
        self._open_workspace_btn.clicked.connect(self._on_open_workspace_clicked)
        layout.addWidget(self._open_workspace_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        return widget

    def _create_status_bar(self) -> QWidget:
        status_bar = QWidget()
        status_bar.setFixedHeight(24)
        status_bar.setStyleSheet(
            "QWidget { background-color: #f8f9fa; border-top: 1px solid #e0e0e0; }"
            "QLabel { color: #666666; font-size: 11px; padding: 0 8px; }"
        )
        layout = QHBoxLayout(status_bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._readonly_label = QLabel()
        self._readonly_label.setStyleSheet("background-color: #ffeb3b; color: #333; padding: 2px 8px;")
        self._readonly_label.hide()
        layout.addWidget(self._readonly_label)
        layout.addStretch()
        self._line_col_label = QLabel("Ln 1, Col 1")
        layout.addWidget(self._line_col_label)
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        layout.addWidget(sep1)
        self._encoding_label = QLabel("UTF-8")
        layout.addWidget(self._encoding_label)
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        layout.addWidget(sep2)
        self._file_type_label = QLabel("Plain Text")
        layout.addWidget(self._file_type_label)
        return status_bar

    def _setup_shortcuts(self):
        close_shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
        close_shortcut.activated.connect(self._close_current_tab)

    def _check_has_project(self) -> bool:
        from shared.service_names import SVC_SESSION_STATE_MANAGER
        session_state_manager = self._get_optional_service(SVC_SESSION_STATE_MANAGER)
        if session_state_manager:
            project_path = session_state_manager.get_project_root()
            return project_path is not None and project_path != ""
        return False

    def _on_open_workspace_clicked(self):
        self.open_workspace_requested.emit()

    def _update_empty_state(self):
        has_tabs = bool(self._session_entries)
        self._content_stack.setVisible(has_tabs)
        self._empty_widget.setVisible(not has_tabs)
        self._status_bar.setVisible(has_tabs)
        if self._open_workspace_btn:
            has_project = self._check_has_project()
            self._open_workspace_btn.setVisible(not has_project)
            for child in self._empty_widget.findChildren(QLabel):
                if child.property("empty_hint"):
                    if has_project:
                        child.setText(self._get_text("hint.select_file", "Select a file to view"))
                    else:
                        child.setText(self._get_text("hint.open_workspace", "Open a workspace to get started"))

    def _reset_status_bar(self) -> None:
        if self._line_col_label is not None:
            self._line_col_label.setText("Ln 1, Col 1")
        if self._file_type_label is not None:
            self._file_type_label.setText("Plain Text")
        self._sync_readonly_label()

    def _sync_readonly_label(self) -> None:
        if self._readonly_label is None:
            return
        entry = self._get_active_entry()
        if entry is not None and entry.is_readonly:
            self._readonly_label.setText(self._get_text("status.readonly", "READ ONLY"))
            self._readonly_label.show()
            return
        self._readonly_label.hide()

    def _ensure_content_widget(self, widget: QWidget) -> QWidget:
        if self._content_stack.indexOf(widget) < 0:
            self._content_stack.addWidget(widget)
        return widget

    def _show_content_widget(self, widget: QWidget) -> None:
        target = self._ensure_content_widget(widget)
        index = self._content_stack.indexOf(target)
        if index >= 0:
            self._content_stack.setCurrentIndex(index)

    def _ensure_code_editor(self) -> CodeEditor:
        if self._shared_code_editor is None:
            editor = CodeEditor(self)
            editor.cursor_position_changed.connect(lambda _line, _col: self._update_cursor_position())
            editor.modification_changed.connect(self._on_editor_modification_changed)
            editor.accept_file_requested.connect(self._on_pending_edit_accept_file_requested)
            editor.reject_file_requested.connect(self._on_pending_edit_reject_file_requested)
            editor.accept_hunk_requested.connect(self._on_pending_edit_accept_hunk_requested)
            editor.reject_hunk_requested.connect(self._on_pending_edit_reject_hunk_requested)
            self._shared_code_editor = editor
            self._ensure_content_widget(editor)
        return self._shared_code_editor

    def _ensure_image_viewer(self) -> ImageViewer:
        if self._shared_image_viewer is None:
            self._shared_image_viewer = ImageViewer(self)
            self._ensure_content_widget(self._shared_image_viewer)
        return self._shared_image_viewer

    def _ensure_markdown_viewer(self) -> MarkdownViewer:
        if self._shared_markdown_viewer is None:
            self._shared_markdown_viewer = MarkdownViewer(self)
            self._ensure_content_widget(self._shared_markdown_viewer)
        return self._shared_markdown_viewer

    def _ensure_docx_viewer(self) -> DocxViewer:
        if self._shared_docx_viewer is None:
            self._shared_docx_viewer = DocxViewer(self)
            self._ensure_content_widget(self._shared_docx_viewer)
        return self._shared_docx_viewer

    def _ensure_pdf_viewer(self) -> PdfViewer:
        if self._shared_pdf_viewer is None:
            self._shared_pdf_viewer = PdfViewer(self)
            self._ensure_content_widget(self._shared_pdf_viewer)
        return self._shared_pdf_viewer

    def _ensure_tabular_viewer(self) -> TabularViewer:
        if self._shared_tabular_viewer is None:
            self._shared_tabular_viewer = TabularViewer(self)
            self._ensure_content_widget(self._shared_tabular_viewer)
        return self._shared_tabular_viewer

    def _read_file_text(self, path: str) -> str:
        if self.file_manager:
            return str(self.file_manager.read_file(path) or "")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def _capture_active_entry_state(self) -> None:
        entry = self._get_active_entry()
        editor = self._shared_code_editor
        if entry is None or editor is None or entry.view_kind != VIEW_KIND_CODE:
            return
        line_number, column_number = editor.get_cursor_position()
        entry.cursor_line = line_number
        entry.cursor_column = column_number
        if editor.is_modified():
            entry.is_dirty = True
            entry.buffer_content = editor.toPlainText()
        else:
            entry.is_dirty = False
            entry.buffer_content = None

    def _entry_is_dirty(self, entry: WorkspaceEditorSessionEntry) -> bool:
        if entry.identity_path == self._active_identity_path and entry.view_kind == VIEW_KIND_CODE and self._shared_code_editor is not None:
            return bool(self._shared_code_editor.is_modified())
        return bool(entry.is_dirty)

    def _apply_pending_state_to_active_editor(self, state: Optional[Dict[str, Any]] = None) -> None:
        entry = self._get_active_entry()
        editor = self._shared_code_editor
        if entry is None or editor is None or entry.view_kind != VIEW_KIND_CODE:
            return
        editor.set_pending_file_state(self._get_pending_file_state_for_path(entry.path, state))

    def _activate_code_entry(self, entry: WorkspaceEditorSessionEntry) -> bool:
        editor = self._ensure_code_editor()
        content = entry.buffer_content if entry.is_dirty and entry.buffer_content is not None else self._read_file_text(entry.path)
        editor.set_file_path(entry.path)
        editor.set_highlighter(os.path.splitext(entry.path)[1].lower())
        editor.load_content(content)
        editor.setReadOnly(entry.is_readonly)
        if entry.is_dirty:
            editor.set_modified(True)
        self._apply_pending_state_to_active_editor()
        self._show_content_widget(editor)
        editor.go_to_line(entry.cursor_line, entry.cursor_column)
        return True

    def _activate_image_entry(self, entry: WorkspaceEditorSessionEntry) -> bool:
        viewer = self._ensure_image_viewer()
        if not viewer.load_image(entry.path):
            return False
        viewer.fit_to_window()
        self._show_content_widget(viewer)
        return True

    def _activate_markdown_entry(self, entry: WorkspaceEditorSessionEntry) -> bool:
        viewer = self._ensure_markdown_viewer()
        viewer.load_markdown(entry.path)
        self._show_content_widget(viewer)
        return True

    def _activate_docx_entry(self, entry: WorkspaceEditorSessionEntry) -> bool:
        viewer = self._ensure_docx_viewer()
        viewer.load_docx(entry.path)
        self._show_content_widget(viewer)
        return True

    def _activate_pdf_entry(self, entry: WorkspaceEditorSessionEntry) -> bool:
        viewer = self._ensure_pdf_viewer()
        viewer.load_pdf(entry.path)
        self._show_content_widget(viewer)
        return True

    def _activate_table_entry(self, entry: WorkspaceEditorSessionEntry) -> bool:
        viewer = self._ensure_tabular_viewer()
        viewer.load_file(entry.path)
        self._show_content_widget(viewer)
        return True

    def _load_entry_into_view(self, entry: WorkspaceEditorSessionEntry) -> bool:
        if entry.view_kind == VIEW_KIND_CODE:
            return self._activate_code_entry(entry)
        if entry.view_kind == VIEW_KIND_IMAGE:
            return self._activate_image_entry(entry)
        if entry.view_kind == VIEW_KIND_MARKDOWN:
            return self._activate_markdown_entry(entry)
        if entry.view_kind == VIEW_KIND_WORD:
            return self._activate_docx_entry(entry)
        if entry.view_kind == VIEW_KIND_PDF:
            return self._activate_pdf_entry(entry)
        if entry.view_kind == VIEW_KIND_TABLE:
            return self._activate_table_entry(entry)
        return False

    def _activate_entry(self, identity_path: str) -> bool:
        entry = self._session_entries.get(str(identity_path or ""))
        if entry is None:
            return False
        if entry.identity_path == self._active_identity_path:
            return True
        previous_identity = self._active_identity_path
        if previous_identity and previous_identity != entry.identity_path:
            self._capture_active_entry_state()
        try:
            self._active_identity_path = entry.identity_path
            if not self._load_entry_into_view(entry):
                self._active_identity_path = previous_identity
                return False
        except Exception as exc:
            self._active_identity_path = previous_identity
            if self.logger:
                self.logger.error(f"Failed to activate file: {entry.path}, error: {exc}")
            return False
        self._update_status_bar(entry.path)
        self._update_empty_state()
        self._schedule_state_refresh(editable=True, workspace=True)
        return True

    def _build_restore_target_candidates(self, active_file: str) -> list[str]:
        candidates: list[str] = []
        active_identity = self._normalize_identity_path(active_file) if active_file else ""
        if active_identity and active_identity in self._session_entries:
            candidates.append(active_identity)
        for identity_path in self._session_entries.keys():
            if identity_path not in candidates:
                candidates.append(identity_path)
        return candidates

    def restore_session_files(self, open_files: list[str], active_file: Optional[str]) -> None:
        normalized_paths: list[str] = []
        seen: set[str] = set()
        for file_path in open_files if isinstance(open_files, list) else []:
            display_path = self._normalize_display_path(str(file_path or ""))
            if not display_path or not os.path.isfile(display_path):
                continue
            identity_path = self._normalize_identity_path(display_path)
            if identity_path in seen:
                continue
            seen.add(identity_path)
            normalized_paths.append(display_path)
        with self._batch_state_updates():
            self._session_entries.clear()
            self._active_identity_path = ""
            for display_path in normalized_paths:
                entry = build_workspace_editor_session_entry(display_path)
                self._session_entries[entry.identity_path] = entry
            for identity_path in self._build_restore_target_candidates(str(active_file or "")):
                if self._activate_entry(identity_path):
                    break
            self._update_empty_state()
            self._schedule_state_refresh(editable=True, workspace=True)
        if self.logger and self._session_entries:
            self.logger.info(
                f"Restored {len(self._session_entries)} session file(s) with lazy activation"
            )

    def load_file(self, path: str) -> bool:
        display_path = self._normalize_display_path(path)
        if not display_path or not os.path.isfile(display_path):
            if self.logger:
                self.logger.warning(f"Invalid file path: {path}")
            return False
        identity_path = self._normalize_identity_path(display_path)
        if identity_path == self._active_identity_path:
            return True
        created = False
        if identity_path not in self._session_entries:
            self._session_entries[identity_path] = build_workspace_editor_session_entry(display_path)
            created = True
        with self._batch_state_updates():
            if not self._activate_entry(identity_path):
                if created:
                    self._session_entries.pop(identity_path, None)
                self._update_empty_state()
                self._schedule_state_refresh(editable=True, workspace=True)
                return False
        if created and self.logger:
            self.logger.info(f"File loaded: {display_path}")
        return True

    def _save_entry(self, entry: Optional[WorkspaceEditorSessionEntry]) -> bool:
        if entry is None or entry.is_readonly or entry.view_kind != VIEW_KIND_CODE:
            return False
        if entry.identity_path == self._active_identity_path and self._shared_code_editor is not None:
            content = self._shared_code_editor.toPlainText()
            line_number, column_number = self._shared_code_editor.get_cursor_position()
            entry.cursor_line = line_number
            entry.cursor_column = column_number
        else:
            content = entry.buffer_content if entry.buffer_content is not None else self._read_file_text(entry.path)
        try:
            state = self._write_manual_save_to_disk(entry.path, content)
            entry.is_dirty = False
            entry.buffer_content = None
            if entry.identity_path == self._active_identity_path and self._shared_code_editor is not None:
                self._shared_code_editor.set_modified(False)
                self._apply_pending_state_to_active_editor(state)
            self._schedule_state_refresh(editable=False, workspace=True)
            self.file_saved.emit(entry.path)
            if self.logger:
                self.logger.info(f"File saved: {entry.path}")
            return True
        except Exception as exc:
            if self.logger:
                self.logger.error(f"Failed to save file: {entry.path}, error: {exc}")
            return False

    def _write_manual_save_to_disk(self, path: str, content: str) -> Dict[str, Any]:
        """Persist a manual user save without routing through the
        pending-edit review pipeline.

        Manual saves (Ctrl+S in the code editor) represent the user's
        own authored content, so they must never materialise a diff
        confirmation prompt. The write therefore goes through
        ``FileManager`` directly, and if the same path still carries a
        pending record from an earlier agent edit we accept it here to
        keep its baseline synchronised with what the user just saved.
        This is the only sanctioned write path for human-driven edits;
        never reintroduce a dual ``record_manual_save`` entry on the
        pending service.
        """
        manager = self.file_manager
        if manager is None:
            raise RuntimeError("FileManager not available")
        manager.write_file(path, content)
        service = self.pending_workspace_edit_service
        if service is None:
            return {}
        return service.accept_file_edits(path)

    def save_file(self) -> bool:
        return self._save_entry(self._get_active_entry())

    def save_all_files(self) -> int:
        saved_count = 0
        for entry in list(self._session_entries.values()):
            if not self._entry_is_dirty(entry):
                continue
            if self._save_entry(entry):
                saved_count += 1
        return saved_count

    def _get_current_editor(self):
        entry = self._get_active_entry()
        if entry is None or entry.view_kind != VIEW_KIND_CODE:
            return None
        return self._shared_code_editor

    def has_active_editor(self) -> bool:
        return self._get_current_editor() is not None

    def has_active_editable_editor(self) -> bool:
        entry = self._get_active_entry()
        return bool(entry is not None and entry.view_kind == VIEW_KIND_CODE and not entry.is_readonly)

    def undo(self) -> None:
        editor = self._get_current_editor()
        if editor is not None:
            editor.undo()

    def redo(self) -> None:
        editor = self._get_current_editor()
        if editor is not None:
            editor.redo()

    def cut(self) -> None:
        editor = self._get_current_editor()
        if editor is not None:
            editor.cut()

    def copy(self) -> None:
        editor = self._get_current_editor()
        if editor is not None:
            editor.copy()

    def paste(self) -> None:
        editor = self._get_current_editor()
        if editor is not None:
            editor.paste()

    def select_all(self) -> None:
        editor = self._get_current_editor()
        if editor is not None:
            editor.select_all()

    def _discard_entry_by_identity(self, identity_path: str, *, activate_fallback: bool) -> bool:
        entry = self._session_entries.get(identity_path)
        if entry is None:
            return False
        if identity_path == self._active_identity_path:
            self._capture_active_entry_state()
        ordered_identities = list(self._session_entries.keys())
        fallback_identity = ""
        if activate_fallback and identity_path == self._active_identity_path:
            index = ordered_identities.index(identity_path)
            if index + 1 < len(ordered_identities):
                fallback_identity = ordered_identities[index + 1]
            elif index > 0:
                fallback_identity = ordered_identities[index - 1]
        del self._session_entries[identity_path]
        if identity_path == self._active_identity_path:
            self._active_identity_path = ""
            if fallback_identity:
                self._activate_entry(fallback_identity)
            else:
                self._reset_status_bar()
        self._update_empty_state()
        self._schedule_state_refresh(editable=True, workspace=True)
        return True

    def sync_open_tabs_with_workspace(self):
        removed_paths = []
        with self._batch_state_updates():
            for entry in list(self._session_entries.values()):
                if not os.path.isfile(entry.path):
                    if self._entry_is_dirty(entry) and entry.view_kind == VIEW_KIND_CODE:
                        continue
                    if self._discard_entry_by_identity(entry.identity_path, activate_fallback=True):
                        removed_paths.append(entry.path)
                    continue
                if entry.identity_path == self._active_identity_path:
                    self.reload_file(entry.path)
                    continue
                if not self._entry_is_dirty(entry):
                    entry.buffer_content = None
            self._update_empty_state()
            self._schedule_state_refresh(editable=True, workspace=True)
        if removed_paths and self.logger:
            self.logger.info(f"Closed {len(removed_paths)} editor tabs for files removed by rollback")

    def _reload_active_code_entry(self, entry: WorkspaceEditorSessionEntry) -> bool:
        editor = self._ensure_code_editor()
        line_number, column_number = editor.get_cursor_position()
        content = self._read_file_text(entry.path)
        editor.set_file_path(entry.path)
        editor.set_highlighter(os.path.splitext(entry.path)[1].lower())
        editor.load_content(content)
        editor.setReadOnly(entry.is_readonly)
        editor.go_to_line(line_number, column_number)
        entry.is_dirty = False
        entry.buffer_content = None
        entry.cursor_line = line_number
        entry.cursor_column = column_number
        self._apply_pending_state_to_active_editor()
        self._schedule_state_refresh(editable=False, workspace=True)
        if self.logger:
            self.logger.info(f"File reloaded from disk: {entry.path}")
        return True

    def reload_file(self, path: str) -> bool:
        entry = self._find_entry(path)
        if entry is None or not os.path.isfile(entry.path):
            return False
        if entry.view_kind == VIEW_KIND_CODE:
            if self._entry_is_dirty(entry):
                return True
            if entry.identity_path == self._active_identity_path:
                try:
                    return self._reload_active_code_entry(entry)
                except Exception as exc:
                    if self.logger:
                        self.logger.error(f"Failed to reload file: {entry.path}, error: {exc}")
                    return False
            entry.buffer_content = None
            return True
        if entry.identity_path == self._active_identity_path:
            try:
                return self._load_entry_into_view(entry)
            except Exception as exc:
                if self.logger:
                    self.logger.error(f"Failed to reload file: {entry.path}, error: {exc}")
                return False
        return True

    def close_tab(self, index: int) -> bool:
        ordered_entries = list(self._session_entries.values())
        if index < 0 or index >= len(ordered_entries):
            return False
        entry = ordered_entries[index]
        return self._close_entry(entry, activate_fallback=True)

    def _close_entry(self, entry: WorkspaceEditorSessionEntry, *, activate_fallback: bool) -> bool:
        if self._entry_is_dirty(entry):
            reply = QMessageBox.question(
                self,
                self._get_text("dialog.confirm.title", "Confirm"),
                f"Save changes to {os.path.basename(entry.path)}?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Save:
                if not self._save_entry(entry):
                    return False
            elif reply == QMessageBox.StandardButton.Cancel:
                return False
        return self._discard_entry_by_identity(entry.identity_path, activate_fallback=activate_fallback)

    def close_all_tabs(self):
        ordered_identities = list(self._session_entries.keys())
        for identity_path in ordered_identities:
            entry = self._session_entries.get(identity_path)
            if entry is None:
                continue
            if not self._close_entry(entry, activate_fallback=False):
                return
        self._active_identity_path = ""
        self._reset_status_bar()
        self._update_empty_state()
        self._schedule_state_refresh(editable=True, workspace=True)

    def get_open_files(self) -> list:
        return [entry.path for entry in self._session_entries.values()]

    def get_current_file(self) -> Optional[str]:
        entry = self._get_active_entry()
        return entry.path if entry is not None else None

    def switch_to_file(self, path: str) -> bool:
        identity_path = self._normalize_identity_path(path)
        if identity_path not in self._session_entries:
            return False
        with self._batch_state_updates():
            return self._activate_entry(identity_path)

    def _close_current_tab(self):
        entry = self._get_active_entry()
        if entry is None:
            return
        self._close_entry(entry, activate_fallback=True)

    def _close_file_by_path(self, path: str) -> None:
        entry = self._find_entry(path)
        if entry is None:
            return
        self._close_entry(entry, activate_fallback=True)

    def _emit_editable_file_state(self, force: bool = False):
        has_editable = any(is_view_kind_editable(entry.view_kind) for entry in self._session_entries.values())
        if not force and self._last_has_editable == has_editable:
            return
        self._last_has_editable = has_editable
        self.editable_file_state_changed.emit(has_editable)

    def _build_workspace_file_state(self) -> Dict[str, Any]:
        items = []
        has_any_dirty = False
        has_any_editable = False
        for entry in self._session_entries.values():
            is_dirty = self._entry_is_dirty(entry)
            has_any_dirty = has_any_dirty or is_dirty
            has_any_editable = has_any_editable or is_view_kind_editable(entry.view_kind)
            items.append(
                entry.to_workspace_item(
                    active_identity_path=self._active_identity_path,
                    is_active_dirty=is_dirty,
                )
            )
        active_entry = self._get_active_entry()
        return {
            "items": items,
            "active_identity_path": self._active_identity_path,
            "has_active_editor": bool(active_entry is not None and active_entry.view_kind == VIEW_KIND_CODE),
            "has_active_editable": bool(active_entry is not None and active_entry.view_kind == VIEW_KIND_CODE and not active_entry.is_readonly),
            "has_any_dirty": has_any_dirty,
            "has_any_editable": has_any_editable,
        }

    def get_workspace_file_state(self) -> Dict[str, Any]:
        return self._build_workspace_file_state()

    def _emit_workspace_file_state(self, force: bool = False):
        state = self._build_workspace_file_state()
        if not force and self._last_workspace_state == state:
            return
        self._last_workspace_state = state
        self._sync_workspace_tab_bar(state)
        self.workspace_file_state_changed.emit(state)

    def _sync_workspace_tab_bar(self, state: Optional[Dict[str, Any]] = None):
        if self._web_tab_bar is None:
            return
        payload = state if isinstance(state, dict) else self._build_workspace_file_state()
        empty_message = self._get_text("editor.tabs.empty", "No open files")
        self._web_tab_bar.set_workspace_file_state(payload, empty_message)
        self._web_tab_bar.set_simulation_control_state(self._simulation_control_state)

    def set_simulation_control_state(self, state: Dict[str, Any]) -> None:
        incoming = state if isinstance(state, dict) else {}
        self._simulation_control_state = {
            "isRunning": bool(incoming.get("isRunning", False)),
            "canRun": bool(incoming.get("canRun", False)),
            "primaryEnabled": bool(incoming.get("primaryEnabled", False)),
            "primaryTooltip": str(incoming.get("primaryTooltip", "") or ""),
        }
        if self._web_tab_bar is not None:
            self._web_tab_bar.set_simulation_control_state(self._simulation_control_state)

    def _on_editor_modification_changed(self, modified: bool):
        entry = self._get_active_entry()
        if entry is not None and entry.view_kind == VIEW_KIND_CODE:
            entry.is_dirty = bool(modified)
            if not modified:
                entry.buffer_content = None
        self._schedule_state_refresh(editable=False, workspace=True)

    def _update_cursor_position(self):
        editor = self._get_current_editor()
        if editor is not None:
            line, col = editor.get_cursor_position()
            self._line_col_label.setText(f"Ln {line}, Col {col}")
        else:
            self._line_col_label.setText("Ln 1, Col 1")

    def _update_status_bar(self, path: str):
        self._file_type_label.setText(file_type_label(path))
        self._update_cursor_position()
        self._sync_readonly_label()

    def retranslate_ui(self):
        for child in self._empty_widget.findChildren(QLabel):
            if child.property("empty_hint"):
                child.setText(self._get_text("hint.select_file", "Select a file to view"))
        if self._open_workspace_btn:
            self._open_workspace_btn.setText(self._get_text("btn.open_workspace", "Open Workspace"))
        self._sync_readonly_label()
        self._sync_workspace_tab_bar()

    def _subscribe_events(self):
        if self.event_bus:
            from shared.event_types import (
                EVENT_FILE_CHANGED,
                EVENT_LANGUAGE_CHANGED,
                EVENT_STATE_PROJECT_CLOSED,
                EVENT_STATE_PROJECT_OPENED,
                EVENT_WORKSPACE_SYNC_REQUIRED,
            )
            self.event_bus.subscribe(EVENT_LANGUAGE_CHANGED, self._on_language_changed)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_OPENED, self._on_project_opened)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_CLOSED, self._on_project_closed)
            self.event_bus.subscribe(EVENT_FILE_CHANGED, self._on_file_changed)
            self.event_bus.subscribe(EVENT_WORKSPACE_SYNC_REQUIRED, self._on_workspace_sync_required)

    def _on_language_changed(self, event_data: Dict[str, Any]):
        del event_data
        self.retranslate_ui()

    def _on_project_opened(self, event_data: Dict[str, Any]):
        del event_data
        self.close_all_tabs()
        self._update_empty_state()
        self._emit_workspace_file_state(force=True)

    def _on_project_closed(self, event_data: Dict[str, Any]):
        del event_data
        self.close_all_tabs()
        self._update_empty_state()
        self._emit_workspace_file_state(force=True)

    def _on_pending_workspace_edit_state_changed(self, state: Dict[str, Any]):
        self._refresh_pending_workspace_edit_views(state)

    def _on_file_changed(self, event_data: Dict[str, Any]):
        data = event_data.get("data", event_data)
        file_path = data.get("path", "") if isinstance(data, dict) else ""
        if not file_path:
            return
        normalized = str(file_path).replace("\\", "/")
        if normalized.endswith("/.circuit_ai/pending_workspace_edits.json"):
            return
        operation = data.get("operation", "") if isinstance(data, dict) else ""
        if operation == "delete":
            self.sync_open_tabs_with_workspace()
            return
        self.reload_file(file_path)

    def _on_pending_edit_accept_file_requested(self, file_path: str):
        service = self.pending_workspace_edit_service
        if service is None or not file_path:
            return
        state = service.accept_file_edits(file_path)
        if not self.reload_file(file_path):
            self.sync_open_tabs_with_workspace()
            return
        self._refresh_pending_workspace_edit_views(state)

    def _on_pending_edit_reject_file_requested(self, file_path: str):
        service = self.pending_workspace_edit_service
        if service is None or not file_path:
            return
        state = service.reject_file_edits(file_path)
        if not self.reload_file(file_path):
            self.sync_open_tabs_with_workspace()
            return
        self._refresh_pending_workspace_edit_views(state)

    def _on_pending_edit_accept_hunk_requested(self, file_path: str, hunk_id: str):
        service = self.pending_workspace_edit_service
        if service is None or not file_path or not hunk_id:
            return
        state = service.accept_hunk(file_path, hunk_id)
        if not self.reload_file(file_path):
            self.sync_open_tabs_with_workspace()
            return
        self._refresh_pending_workspace_edit_views(state)

    def _on_pending_edit_reject_hunk_requested(self, file_path: str, hunk_id: str):
        service = self.pending_workspace_edit_service
        if service is None or not file_path or not hunk_id:
            return
        state = service.reject_hunk(file_path, hunk_id)
        if not self.reload_file(file_path):
            self.sync_open_tabs_with_workspace()
            return
        self._refresh_pending_workspace_edit_views(state)

    def _on_workspace_sync_required(self, event_data: Dict[str, Any]):
        data = event_data.get("data", event_data)
        if not isinstance(data, dict):
            return
        self.sync_open_tabs_with_workspace()


__all__ = ["CodeEditorPanel", "CodeEditor"]
