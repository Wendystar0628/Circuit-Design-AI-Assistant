# Code Editor Panel - Multi-tab Code Editor with Syntax Highlighting
"""
代码编辑器面板 - 多标签页代码编辑器

职责：
- 显示和编辑文件内容，支持多种格式
- 多标签页管理，支持拖拽排序
- 语法高亮（SPICE、JSON、Python）
- 文档预览（Markdown、Word、PDF、图片）

模块结构：
- editor/: 代码编辑器核心组件
- highlighters/: 语法高亮器
- viewers/: 文件预览器
"""

import os
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTabBar,
    QLabel, QMenu, QApplication, QFrame, QMessageBox, QPushButton,
    QToolButton
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from shared.path_utils import normalize_absolute_path, normalize_identity_path

# 从子模块导入组件
from .editor import CodeEditor
from .viewers import ImageViewer, DocumentViewer

# 文件类型常量
EDITABLE_EXTENSIONS = {'.cir', '.sp', '.spice', '.json', '.txt', '.py'}  # 可编辑文件
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp'}
DOCUMENT_EXTENSIONS = {'.md', '.markdown', '.docx', '.pdf'}


class EditorTab:
    """编辑器标签页数据"""
    def __init__(
        self,
        path: str,
        widget: QWidget,
        is_readonly: bool = False,
        editor: Optional[CodeEditor] = None,
    ):
        self.path = normalize_absolute_path(path)
        self.identity_path = normalize_identity_path(path)
        self.widget = widget
        self.editor = editor
        self.is_readonly = is_readonly


class EditorTabBar(QTabBar):
    """自定义标签栏"""
    tab_close_requested = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setExpanding(False)
        self.tabCloseRequested.connect(self.tab_close_requested.emit)
        close_icon_path = self._get_close_icon_path()
        self.setStyleSheet(f"""
            QTabBar {{ background-color: #f8f9fa; border-bottom: 1px solid #e0e0e0; }}
            QTabBar::tab {{ background-color: #f8f9fa; border: none; border-right: 1px solid #e0e0e0;
                padding: 6px 24px 6px 12px; min-width: 80px; max-width: 200px; }}
            QTabBar::tab:selected {{ background-color: #ffffff; border-bottom: 2px solid #4CAF50; }}
            QTabBar::tab:hover:!selected {{ background-color: #f0f7ff; }}
            QTabBar::close-button {{ image: url({close_icon_path}); subcontrol-position: right;
                width: 16px; height: 16px; margin-right: 4px; border-radius: 2px; }}
            QTabBar::close-button:hover {{ background-color: #e0e0e0; }}
        """)
    
    def _get_close_icon_path(self) -> str:
        try:
            from resources.resource_loader import get_icon_path
            path = get_icon_path("panel", "close")
            if path:
                return path.replace("\\", "/")
        except Exception:
            pass
        return ""


class CodeEditorPanel(QWidget):
    """代码编辑器面板"""
    file_saved = pyqtSignal(str)
    open_workspace_requested = pyqtSignal()
    editable_file_state_changed = pyqtSignal(bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._i18n_manager = None
        self._event_bus = None
        self._file_manager = None
        self._pending_workspace_edit_service = None
        self._logger = None
        self._tabs: Dict[str, EditorTab] = {}
        self._tab_widget: Optional[QTabWidget] = None
        self._tab_bar: Optional[EditorTabBar] = None
        self._status_bar: Optional[QWidget] = None
        self._line_col_label: Optional[QLabel] = None
        self._encoding_label: Optional[QLabel] = None
        self._file_type_label: Optional[QLabel] = None
        self._readonly_label: Optional[QLabel] = None
        self._scroll_left_btn: Optional[QToolButton] = None
        self._scroll_right_btn: Optional[QToolButton] = None
        self._empty_widget: Optional[QWidget] = None
        self._open_workspace_btn: Optional[QPushButton] = None
        self._pending_workspace_edit_connected = False
        self._is_readonly_mode = False
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

    def _find_tab(self, path: str) -> Optional[EditorTab]:
        if not path:
            return None
        return self._tabs.get(self._normalize_identity_path(path))

    def _find_tab_by_widget(self, widget: Optional[QWidget]) -> Optional[EditorTab]:
        if widget is None:
            return None
        for tab in self._tabs.values():
            if tab.widget == widget:
                return tab
        return None

    def _get_current_tab(self) -> Optional[EditorTab]:
        return self._find_tab_by_widget(self._tab_widget.currentWidget())

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

    def _apply_pending_file_state_to_tab(
        self,
        tab: EditorTab,
        file_state: Optional[Dict[str, Any]],
    ) -> None:
        if tab.editor is not None:
            tab.editor.set_pending_file_state(file_state)

    def _refresh_pending_workspace_edit_views(
        self,
        state: Optional[Dict[str, Any]] = None,
    ) -> None:
        file_state_map = self._get_pending_file_state_map(state)
        for identity_path, tab in self._tabs.items():
            self._apply_pending_file_state_to_tab(tab, file_state_map.get(identity_path))

    def _subscribe_pending_workspace_edit_state(self) -> None:
        _ = self.pending_workspace_edit_service

    def _move_editor_cursor_to_line(self, path: str, line_number: int) -> None:
        tab = self._find_tab(path)
        if tab is None or tab.editor is None:
            return
        index = self._tab_widget.indexOf(tab.widget)
        if index >= 0:
            self._tab_widget.setCurrentIndex(index)
        tab.editor.go_to_line(line_number)
        tab.editor.setFocus()

    def _get_text(self, key: str, default: Optional[str] = None) -> str:
        if self.i18n_manager:
            return self.i18n_manager.get_text(key, default)
        return default if default else key

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        tab_bar_container = QWidget()
        tab_bar_container.setFixedHeight(32)
        tab_bar_layout = QHBoxLayout(tab_bar_container)
        tab_bar_layout.setContentsMargins(0, 0, 0, 0)
        tab_bar_layout.setSpacing(0)
        
        self._scroll_left_btn = QToolButton(tab_bar_container)
        self._scroll_left_btn.setArrowType(Qt.ArrowType.LeftArrow)
        self._scroll_left_btn.setFixedSize(24, 28)
        self._scroll_left_btn.setAutoRepeat(True)
        self._scroll_left_btn.clicked.connect(self._on_scroll_left)
        self._scroll_left_btn.setStyleSheet("""
            QToolButton { background-color: #f0f0f0; border: 1px solid #d0d0d0; border-radius: 3px; }
            QToolButton:hover { background-color: #e0e0e0; }
            QToolButton:disabled { background-color: #f8f8f8; }
        """)
        tab_bar_layout.addWidget(self._scroll_left_btn)
        
        self._tab_widget = QTabWidget()
        self._tab_bar = EditorTabBar()
        self._tab_widget.setTabBar(self._tab_bar)
        self._tab_widget.setUsesScrollButtons(False)
        self._tab_widget.setElideMode(Qt.TextElideMode.ElideNone)
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.tabCloseRequested.connect(self._on_tab_close_requested)
        self._tab_widget.currentChanged.connect(self._on_current_tab_changed)
        self._tab_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tab_widget.customContextMenuRequested.connect(self._on_tab_context_menu)
        tab_bar_layout.addWidget(self._tab_bar, 1)
        
        self._scroll_right_btn = QToolButton(tab_bar_container)
        self._scroll_right_btn.setArrowType(Qt.ArrowType.RightArrow)
        self._scroll_right_btn.setFixedSize(24, 28)
        self._scroll_right_btn.setAutoRepeat(True)
        self._scroll_right_btn.clicked.connect(self._on_scroll_right)
        self._scroll_right_btn.setStyleSheet("""
            QToolButton { background-color: #f0f0f0; border: 1px solid #d0d0d0; border-radius: 3px; }
            QToolButton:hover { background-color: #e0e0e0; }
            QToolButton:disabled { background-color: #f8f8f8; }
        """)
        tab_bar_layout.addWidget(self._scroll_right_btn)
        
        self._scroll_left_btn.hide()
        self._scroll_right_btn.hide()
        layout.addWidget(tab_bar_container)
        layout.addWidget(self._tab_widget, 1)
        self._empty_widget = self._create_empty_widget()
        layout.addWidget(self._empty_widget)
        self._status_bar = self._create_status_bar()
        layout.addWidget(self._status_bar)
        self._update_empty_state()

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
        status_bar.setStyleSheet("""
            QWidget { background-color: #f8f9fa; border-top: 1px solid #e0e0e0; }
            QLabel { color: #666666; font-size: 11px; padding: 0 8px; }
        """)
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

    def _update_empty_state(self):
        has_tabs = self._tab_widget.count() > 0
        self._tab_widget.setVisible(has_tabs)
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
    
    def _check_has_project(self) -> bool:
        from shared.service_names import SVC_SESSION_STATE_MANAGER
        session_state_manager = self._get_optional_service(SVC_SESSION_STATE_MANAGER)
        if session_state_manager:
            project_path = session_state_manager.get_project_root()
            return project_path is not None and project_path != ""
        return False
    
    def _on_open_workspace_clicked(self):
        self.open_workspace_requested.emit()


    # ============================================================
    # 核心功能
    # ============================================================

    def load_file(self, path: str) -> bool:
        """加载文件内容"""
        display_path = self._normalize_display_path(path)
        if not display_path or not os.path.isfile(display_path):
            if self.logger:
                self.logger.warning(f"Invalid file path: {path}")
            return False

        tab = self._find_tab(display_path)
        if tab is not None:
            index = self._tab_widget.indexOf(tab.widget)
            if index >= 0:
                self._tab_widget.setCurrentIndex(index)
            return True

        ext = os.path.splitext(display_path)[1].lower()
        editor: Optional[CodeEditor] = None
        
        try:
            if ext in EDITABLE_EXTENSIONS:
                widget, editor = self._create_code_editor_host(display_path, ext)
            elif ext in IMAGE_EXTENSIONS:
                widget = self._create_image_viewer(display_path)
            elif ext in DOCUMENT_EXTENSIONS:
                widget = self._create_document_viewer(display_path, ext)
            else:
                widget, editor = self._create_code_editor_host(display_path, ext)
            
            if widget is None:
                return False
            
            is_readonly = ext in IMAGE_EXTENSIONS or ext in DOCUMENT_EXTENSIONS
            self._add_tab(
                display_path,
                widget,
                is_readonly,
                editor=editor,
            )
            self._refresh_pending_workspace_edit_views()
            
            if self.logger:
                self.logger.info(f"File loaded: {display_path}")
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to load file: {display_path}, error: {e}")
            return False

    def _create_code_editor_host(
        self,
        path: str,
        ext: str,
    ) -> tuple[QWidget, CodeEditor]:
        editor = CodeEditor(self)
        editor.set_file_path(path)
        
        try:
            content = self._read_file_text(path)
            editor.set_highlighter(ext)
            editor.load_content(content)
            editor.cursor_position_changed.connect(
                lambda _line, _col: self._update_cursor_position()
            )
            editor.modification_changed.connect(
                lambda modified, p=path: self._on_editor_modification_changed(p, modified)
            )
            editor.accept_file_requested.connect(self._on_pending_edit_accept_file_requested)
            editor.reject_file_requested.connect(self._on_pending_edit_reject_file_requested)
            editor.accept_hunk_requested.connect(self._on_pending_edit_accept_hunk_requested)
            editor.reject_hunk_requested.connect(self._on_pending_edit_reject_hunk_requested)
            
            if self._is_readonly_mode:
                editor.setReadOnly(True)
            return editor, editor
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to read file: {path}, error: {e}")
            raise

    def _read_file_text(self, path: str) -> str:
        if self.file_manager:
            return str(self.file_manager.read_file(path) or "")
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def _create_image_viewer(self, path: str) -> Optional[ImageViewer]:
        """创建图片预览器"""
        viewer = ImageViewer()
        if viewer.load_image(path):
            viewer.fit_to_window()
            return viewer
        return None

    def _create_document_viewer(self, path: str, ext: str) -> Optional[DocumentViewer]:
        """创建文档预览器"""
        viewer = DocumentViewer()
        if ext in {'.md', '.markdown'}:
            viewer.load_markdown(path)
        elif ext == '.docx':
            viewer.load_word(path)
        elif ext == '.pdf':
            viewer.load_pdf(path)
        return viewer

    def _apply_editor_content(self, tab: EditorTab, content: str) -> None:
        if tab.editor is None:
            return
        line_number, column_number = tab.editor.get_cursor_position()
        tab.editor.load_content(content)
        tab.editor.go_to_line(line_number, column_number)

    def _save_tab(self, tab: Optional[EditorTab]) -> bool:
        if tab is None or tab.is_readonly or tab.editor is None:
            return False

        content = tab.editor.toPlainText()
        try:
            state = self._save_content_via_pending_service(tab.path, content)
            tab.editor.set_modified(False)
            self._update_tab_title(tab.path)
            self._refresh_pending_workspace_edit_views(state)
            self.file_saved.emit(tab.path)
            if self.logger:
                self.logger.info(f"File saved: {tab.path}")
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to save file: {tab.path}, error: {e}")
            return False

    def _add_tab(
        self,
        path: str,
        widget: QWidget,
        is_readonly: bool,
        editor: Optional[CodeEditor] = None,
    ):
        """添加标签页"""
        file_name = os.path.basename(path)
        index = self._tab_widget.addTab(widget, file_name)
        self._tab_widget.setCurrentIndex(index)
        self._tab_widget.setTabToolTip(index, path)
        tab = EditorTab(
            path,
            widget,
            is_readonly,
            editor=editor,
        )
        self._tabs[tab.identity_path] = tab
        self._update_empty_state()
        self._update_status_bar(tab.path)
        self._update_tab_title(tab.path)
        self._emit_editable_file_state()

    def _save_content_via_pending_service(self, path: str, content: str) -> Dict[str, Any]:
        service = self.pending_workspace_edit_service
        if service is None:
            raise RuntimeError("PendingWorkspaceEditService not available")
        return service.record_manual_save(path, content)

    def save_file(self) -> bool:
        """保存当前文件"""
        tab = self._get_current_tab()
        return self._save_tab(tab)

    def save_all_files(self) -> int:
        """保存所有已修改的文件"""
        saved_count = 0
        for tab in self._tabs.values():
            if tab.is_readonly:
                continue
            if tab.editor is not None and tab.editor.is_modified():
                if self._save_tab(tab):
                    saved_count += 1
        return saved_count

    def reset_all_modification_states(self):
        """重置所有打开文件的修改状态"""
        for tab in self._tabs.values():
            if tab.is_readonly:
                continue
            if tab.editor is not None:
                tab.editor.set_modified(False)
                self._update_tab_title(tab.path)

    def sync_open_tabs_with_workspace(self):
        removed_paths = []
        for tab in list(self._tabs.values()):
            path = tab.path
            if not os.path.isfile(path):
                if tab.editor is not None and tab.editor.is_modified():
                    continue
                if self._discard_tab_by_path(path):
                    removed_paths.append(path)
                continue

            if tab.editor is not None and tab.editor.is_modified():
                continue

            if not self.reload_file(path) and self._find_tab(path) is not None:
                was_current = path == self.get_current_file()
                if self._discard_tab_by_path(path):
                    self.load_file(path)
                    if not was_current:
                        self.switch_to_file(path)

        if removed_paths and self.logger:
            self.logger.info(f"Closed {len(removed_paths)} editor tabs for files removed by rollback")

        self._refresh_pending_workspace_edit_views()
        self._update_empty_state()
        self._emit_editable_file_state()
        self._update_scroll_buttons()

    def get_content(self) -> Optional[str]:
        current_tab = self._get_current_tab()
        if current_tab is not None and current_tab.editor is not None:
            return current_tab.editor.toPlainText()
        return None

    def set_readonly(self, readonly: bool):
        """设置只读模式"""
        self._is_readonly_mode = readonly
        for tab in self._tabs.values():
            if tab.editor is not None:
                tab.editor.setReadOnly(readonly or tab.is_readonly)
        if readonly:
            self._readonly_label.setText(self._get_text("status.readonly", "READ ONLY"))
            self._readonly_label.show()
        else:
            self._readonly_label.hide()

    def open_tab(self, path: str) -> bool:
        return self.load_file(path)

    def reload_file(self, path: str) -> bool:
        """
        从磁盘重新加载已打开文件的内容
        
        当外部工具（如 Agent 的 patch_file / rewrite_file）修改了文件时调用，
        确保编辑器显示最新内容。
        
        Args:
            path: 文件绝对路径
            
        Returns:
            True 如果重新加载成功
        """
        display_path = self._normalize_display_path(path)
        tab = self._find_tab(display_path)

        if tab is None or tab.editor is None:
            # 文件未打开，无需刷新
            return False

        if not os.path.isfile(display_path):
            return False
        
        try:
            # 读取磁盘最新内容
            content = self._read_file_text(display_path)

            editor = tab.editor
            if editor.is_modified() and editor.toPlainText() != content:
                return False

            self._apply_editor_content(tab, content)

            # 更新标签页标题（移除修改标记）
            index = self._tab_widget.indexOf(tab.widget)
            if index >= 0:
                file_name = os.path.basename(tab.path)
                self._tab_widget.setTabText(index, file_name)

            self._refresh_pending_workspace_edit_views()

            if self.logger:
                self.logger.info(f"File reloaded from disk: {display_path}")
            return True
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to reload file: {display_path}, error: {e}")
        
        return False

    def close_tab(self, index: int) -> bool:
        """关闭指定标签页"""
        if index < 0 or index >= self._tab_widget.count():
            return False
        
        widget = self._tab_widget.widget(index)
        tab = self._find_tab_by_widget(widget)
        if tab is not None:
            if tab.editor is not None and tab.editor.is_modified():
                reply = QMessageBox.question(
                    self, self._get_text("dialog.confirm.title", "Confirm"),
                    f"Save changes to {os.path.basename(tab.path)}?",
                    QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
                )
                if reply == QMessageBox.StandardButton.Save:
                    if not self._save_tab(tab):
                        return False
                elif reply == QMessageBox.StandardButton.Cancel:
                    return False
            
            self._tab_widget.removeTab(index)
            del self._tabs[tab.identity_path]
            self._update_empty_state()
            self._emit_editable_file_state()
            return True
        return False

    def close_all_tabs(self):
        while self._tab_widget.count() > 0:
            self.close_tab(0)

    def get_open_files(self) -> list:
        return [tab.path for tab in self._tabs.values()]

    def get_current_file(self) -> Optional[str]:
        current_tab = self._get_current_tab()
        return current_tab.path if current_tab is not None else None

    def switch_to_file(self, path: str) -> bool:
        tab = self._find_tab(path)
        if tab is None:
            return False
        index = self._tab_widget.indexOf(tab.widget)
        if index >= 0:
            self._tab_widget.setCurrentIndex(index)
            return True
        return False

    def _discard_tab_by_path(self, path: str) -> bool:
        tab = self._find_tab(path)
        if tab is None:
            return False

        index = self._tab_widget.indexOf(tab.widget)
        if index >= 0:
            self._tab_widget.removeTab(index)
        del self._tabs[tab.identity_path]
        return True

    def _close_current_tab(self):
        current_index = self._tab_widget.currentIndex()
        if current_index >= 0:
            self.close_tab(current_index)


    # ============================================================
    # 事件处理
    # ============================================================

    def _emit_editable_file_state(self):
        has_editable = any(not tab.is_readonly for tab in self._tabs.values())
        self.editable_file_state_changed.emit(has_editable)

    def _on_editor_modification_changed(self, path: str, modified: bool):
        self._update_tab_title(path)

    def _on_tab_close_requested(self, index: int):
        self.close_tab(index)

    def _on_current_tab_changed(self, index: int):
        if index < 0:
            self._update_scroll_buttons()
            return

        widget = self._tab_widget.widget(index)
        tab = self._find_tab_by_widget(widget)
        if tab is not None:
            self._update_status_bar(tab.path)

        self._update_scroll_buttons()

    def _on_scroll_left(self):
        current = self._tab_widget.currentIndex()
        if current > 0:
            self._tab_widget.setCurrentIndex(current - 1)

    def _on_scroll_right(self):
        current = self._tab_widget.currentIndex()
        count = self._tab_widget.count()
        if current < count - 1:
            self._tab_widget.setCurrentIndex(current + 1)

    def _update_scroll_buttons(self):
        tab_count = self._tab_widget.count()
        current_index = self._tab_widget.currentIndex()
        show_buttons = tab_count > 1
        self._scroll_left_btn.setVisible(show_buttons)
        self._scroll_right_btn.setVisible(show_buttons)
        if show_buttons:
            self._scroll_left_btn.setEnabled(current_index > 0)
            self._scroll_right_btn.setEnabled(current_index < tab_count - 1)

    def _on_tab_context_menu(self, position: QPoint):
        tab_bar = self._tab_widget.tabBar()
        index = tab_bar.tabAt(position)
        if index < 0:
            return
        
        menu = QMenu(self)
        close_action = QAction(self._get_text("btn.close", "Close"), self)
        close_action.triggered.connect(lambda: self.close_tab(index))
        menu.addAction(close_action)
        
        close_others_action = QAction("Close Others", self)
        close_others_action.triggered.connect(lambda: self._close_other_tabs(index))
        menu.addAction(close_others_action)
        
        close_all_action = QAction("Close All", self)
        close_all_action.triggered.connect(self.close_all_tabs)
        menu.addAction(close_all_action)
        
        menu.addSeparator()
        copy_path_action = QAction(self._get_text("file_browser.copy_path", "Copy Path"), self)
        copy_path_action.triggered.connect(lambda: self._copy_tab_path(index))
        menu.addAction(copy_path_action)
        
        menu.exec(tab_bar.mapToGlobal(position))

    def _close_other_tabs(self, keep_index: int):
        for i in range(self._tab_widget.count() - 1, -1, -1):
            if i != keep_index:
                self.close_tab(i)

    def _copy_tab_path(self, index: int):
        widget = self._tab_widget.widget(index)
        for tab in self._tabs.values():
            if tab.widget == widget:
                clipboard = QApplication.clipboard()
                clipboard.setText(tab.path)
                break

    def _update_cursor_position(self):
        current_tab = self._get_current_tab()
        if current_tab is not None and current_tab.editor is not None:
            line, col = current_tab.editor.get_cursor_position()
            self._line_col_label.setText(f"Ln {line}, Col {col}")

    def _update_tab_title(self, path: str):
        tab = self._find_tab(path)
        if tab is None:
            return
        index = self._tab_widget.indexOf(tab.widget)
        if index < 0:
            return
        file_name = os.path.basename(tab.path)
        if tab.editor is not None and tab.editor.is_modified():
            self._tab_widget.setTabText(index, f"{file_name} ●")
        else:
            self._tab_widget.setTabText(index, file_name)

    def _update_status_bar(self, path: str):
        ext = os.path.splitext(path)[1].lower()
        file_type_map = {
            '.cir': 'SPICE', '.sp': 'SPICE', '.spice': 'SPICE',
            '.json': 'JSON', '.txt': 'Plain Text', '.py': 'Python',
            '.md': 'Markdown', '.markdown': 'Markdown',
            '.docx': 'Word Document', '.pdf': 'PDF Document',
            '.png': 'PNG Image', '.jpg': 'JPEG Image', '.jpeg': 'JPEG Image',
        }
        file_type = file_type_map.get(ext, 'Plain Text')
        self._file_type_label.setText(file_type)
        self._update_cursor_position()

    # ============================================================
    # 国际化支持
    # ============================================================

    def retranslate_ui(self):
        for child in self._empty_widget.findChildren(QLabel):
            if child.property("empty_hint"):
                child.setText(self._get_text("hint.select_file", "Select a file to view"))
        if self._open_workspace_btn:
            self._open_workspace_btn.setText(self._get_text("btn.open_workspace", "Open Workspace"))
        if self._readonly_label.isVisible():
            self._readonly_label.setText(self._get_text("status.readonly", "READ ONLY"))

    # ============================================================
    # 事件订阅
    # ============================================================

    def _subscribe_events(self):
        if self.event_bus:
            from shared.event_types import (
                EVENT_LANGUAGE_CHANGED, EVENT_STATE_PROJECT_OPENED,
                EVENT_STATE_PROJECT_CLOSED, EVENT_FILE_CHANGED,
                EVENT_SESSION_CHANGED,
            )
            self.event_bus.subscribe(EVENT_LANGUAGE_CHANGED, self._on_language_changed)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_OPENED, self._on_project_opened)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_CLOSED, self._on_project_closed)
            self.event_bus.subscribe(EVENT_FILE_CHANGED, self._on_file_changed)
            self.event_bus.subscribe(EVENT_SESSION_CHANGED, self._on_session_changed)

    def _on_language_changed(self, event_data: Dict[str, Any]):
        self.retranslate_ui()

    def _on_project_opened(self, event_data: Dict[str, Any]):
        self.close_all_tabs()
        self._update_empty_state()

    def _on_project_closed(self, event_data: Dict[str, Any]):
        self.close_all_tabs()
        self._update_empty_state()

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
        if self._find_tab(file_path) is not None and not self.reload_file(file_path):
            self.sync_open_tabs_with_workspace()
            return
        self._refresh_pending_workspace_edit_views(state)

    def _on_pending_edit_reject_file_requested(self, file_path: str):
        service = self.pending_workspace_edit_service
        if service is None or not file_path:
            return
        state = service.reject_file_edits(file_path)
        if self._find_tab(file_path) is not None and not self.reload_file(file_path):
            self.sync_open_tabs_with_workspace()
            return
        self._refresh_pending_workspace_edit_views(state)

    def _on_pending_edit_accept_hunk_requested(self, file_path: str, hunk_id: str):
        service = self.pending_workspace_edit_service
        if service is None or not file_path or not hunk_id:
            return
        state = service.accept_hunk(file_path, hunk_id)
        if self._find_tab(file_path) is not None and not self.reload_file(file_path):
            self.sync_open_tabs_with_workspace()
            return
        self._refresh_pending_workspace_edit_views(state)

    def _on_pending_edit_reject_hunk_requested(self, file_path: str, hunk_id: str):
        service = self.pending_workspace_edit_service
        if service is None or not file_path or not hunk_id:
            return
        state = service.reject_hunk(file_path, hunk_id)
        if self._find_tab(file_path) is not None and not self.reload_file(file_path):
            self.sync_open_tabs_with_workspace()
            return
        self._refresh_pending_workspace_edit_views(state)

    def _on_session_changed(self, event_data: Dict[str, Any]):
        data = event_data.get("data", event_data)
        if data.get("action", "") == "rollback":
            self.sync_open_tabs_with_workspace()



# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "CodeEditorPanel",
    "CodeEditor",
    "ImageViewer",
    "DocumentViewer",
    "EDITABLE_EXTENSIONS",
    "IMAGE_EXTENSIONS",
    "DOCUMENT_EXTENSIONS",
]
