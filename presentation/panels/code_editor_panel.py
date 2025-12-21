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

# 从子模块导入组件
from .editor import CodeEditor
from .viewers import ImageViewer, DocumentViewer
from .highlighters import SpiceHighlighter, JsonHighlighter, PythonHighlighter

# 文件类型常量
EDITABLE_EXTENSIONS = {'.cir', '.sp', '.spice', '.json', '.txt', '.py'}  # 可编辑文件
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp'}
DOCUMENT_EXTENSIONS = {'.md', '.markdown', '.docx', '.pdf'}


class EditorTab:
    """编辑器标签页数据"""
    def __init__(self, path: str, widget: QWidget, is_readonly: bool = False):
        self.path = path
        self.widget = widget
        self.is_readonly = is_readonly
        self.is_modified = False


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
    undo_redo_state_changed = pyqtSignal(bool, bool)
    editable_file_state_changed = pyqtSignal(bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._i18n_manager = None
        self._event_bus = None
        self._file_manager = None
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
        self._is_readonly_mode = False
        self._setup_ui()
        self._setup_shortcuts()
        self.retranslate_ui()
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
    def file_manager(self):
        if self._file_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_FILE_MANAGER
                self._file_manager = ServiceLocator.get_optional(SVC_FILE_MANAGER)
            except Exception:
                pass
        return self._file_manager

    @property
    def logger(self):
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("code_editor_panel")
            except Exception:
                pass
        return self._logger

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
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_SESSION_STATE
            session_state = ServiceLocator.get_optional(SVC_SESSION_STATE)
            if session_state:
                project_path = session_state.project_root
                return project_path is not None and project_path != ""
        except Exception:
            pass
        return False
    
    def _on_open_workspace_clicked(self):
        self.open_workspace_requested.emit()


    # ============================================================
    # 核心功能
    # ============================================================

    def load_file(self, path: str) -> bool:
        """加载文件内容"""
        if not path or not os.path.isfile(path):
            if self.logger:
                self.logger.warning(f"Invalid file path: {path}")
            return False
        
        if path in self._tabs:
            tab = self._tabs[path]
            index = self._tab_widget.indexOf(tab.widget)
            if index >= 0:
                self._tab_widget.setCurrentIndex(index)
            return True
        
        ext = os.path.splitext(path)[1].lower()
        
        try:
            if ext in EDITABLE_EXTENSIONS:
                widget = self._create_code_editor(path, ext)
            elif ext in IMAGE_EXTENSIONS:
                widget = self._create_image_viewer(path)
            elif ext in DOCUMENT_EXTENSIONS:
                widget = self._create_document_viewer(path, ext)
            else:
                widget = self._create_code_editor(path, ext)
            
            if widget is None:
                return False
            
            is_readonly = ext in IMAGE_EXTENSIONS or ext in DOCUMENT_EXTENSIONS
            self._add_tab(path, widget, is_readonly)
            
            if self.logger:
                self.logger.info(f"File loaded: {path}")
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to load file: {path}, error: {e}")
            return False

    def _create_code_editor(self, path: str, ext: str) -> Optional[CodeEditor]:
        """创建代码编辑器"""
        editor = CodeEditor()
        editor.set_file_path(path)
        
        try:
            if self.file_manager:
                content = self.file_manager.read_file(path)
            else:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
            
            editor.blockSignals(True)
            editor.document().blockSignals(True)
            editor.setPlainText(content)
            editor.set_highlighter(ext)
            editor.document().blockSignals(False)
            editor.blockSignals(False)
            editor.document().setModified(False)
            editor.set_modified(False)
            
            editor.cursorPositionChanged.connect(self._update_cursor_position)
            editor.document().undoAvailable.connect(self._on_undo_available_changed)
            editor.document().redoAvailable.connect(self._on_redo_available_changed)
            editor.modification_changed.connect(
                lambda modified, p=path: self._on_editor_modification_changed(p, modified)
            )
            
            if self._is_readonly_mode:
                editor.setReadOnly(True)
            return editor
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to read file: {path}, error: {e}")
            return None

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

    def _add_tab(self, path: str, widget: QWidget, is_readonly: bool):
        """添加标签页"""
        file_name = os.path.basename(path)
        index = self._tab_widget.addTab(widget, file_name)
        self._tab_widget.setCurrentIndex(index)
        self._tab_widget.setTabToolTip(index, path)
        tab = EditorTab(path, widget, is_readonly)
        self._tabs[path] = tab
        self._update_empty_state()
        self._update_status_bar(path)
        self._update_tab_title(path)
        self._emit_editable_file_state()

    def save_file(self) -> bool:
        """保存当前文件"""
        current_widget = self._tab_widget.currentWidget()
        if not current_widget:
            return False
        
        tab = None
        for t in self._tabs.values():
            if t.widget == current_widget:
                tab = t
                break
        
        if not tab or tab.is_readonly:
            return False
        
        if isinstance(current_widget, CodeEditor):
            content = current_widget.toPlainText()
            try:
                if self.file_manager:
                    self.file_manager.update_file(tab.path, content)
                else:
                    with open(tab.path, 'w', encoding='utf-8') as f:
                        f.write(content)
                
                current_widget.set_modified(False)
                tab.is_modified = False
                self._update_tab_title(tab.path)
                self.file_saved.emit(tab.path)
                if self.logger:
                    self.logger.info(f"File saved: {tab.path}")
                return True
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Failed to save file: {tab.path}, error: {e}")
                return False
        return False

    def save_all_files(self) -> int:
        """保存所有已修改的文件"""
        saved_count = 0
        for path, tab in self._tabs.items():
            if tab.is_readonly:
                continue
            if isinstance(tab.widget, CodeEditor) and tab.widget.is_modified():
                content = tab.widget.toPlainText()
                try:
                    if self.file_manager:
                        self.file_manager.update_file(path, content)
                    else:
                        with open(path, 'w', encoding='utf-8') as f:
                            f.write(content)
                    tab.widget.set_modified(False)
                    tab.is_modified = False
                    self._update_tab_title(path)
                    self.file_saved.emit(path)
                    saved_count += 1
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"Failed to save file: {path}, error: {e}")
        return saved_count

    def reset_all_modification_states(self):
        """重置所有打开文件的修改状态"""
        for path, tab in self._tabs.items():
            if tab.is_readonly:
                continue
            if isinstance(tab.widget, CodeEditor):
                tab.widget.document().setModified(False)
                tab.widget.set_modified(False)
                tab.is_modified = False
                self._update_tab_title(path)

    def undo(self) -> None:
        """编辑器撤销"""
        current_widget = self._tab_widget.currentWidget()
        if isinstance(current_widget, CodeEditor):
            current_widget.undo()

    def redo(self) -> None:
        """编辑器重做"""
        current_widget = self._tab_widget.currentWidget()
        if isinstance(current_widget, CodeEditor):
            current_widget.redo()

    def can_undo(self) -> bool:
        current_widget = self._tab_widget.currentWidget()
        if isinstance(current_widget, CodeEditor):
            return current_widget.document().isUndoAvailable()
        return False

    def can_redo(self) -> bool:
        current_widget = self._tab_widget.currentWidget()
        if isinstance(current_widget, CodeEditor):
            return current_widget.document().isRedoAvailable()
        return False

    def get_content(self) -> Optional[str]:
        current_widget = self._tab_widget.currentWidget()
        if isinstance(current_widget, CodeEditor):
            return current_widget.toPlainText()
        return None

    def set_readonly(self, readonly: bool):
        """设置只读模式"""
        self._is_readonly_mode = readonly
        for tab in self._tabs.values():
            if isinstance(tab.widget, CodeEditor):
                tab.widget.setReadOnly(readonly or tab.is_readonly)
        if readonly:
            self._readonly_label.setText(self._get_text("status.readonly", "READ ONLY"))
            self._readonly_label.show()
        else:
            self._readonly_label.hide()

    def open_tab(self, path: str) -> bool:
        return self.load_file(path)

    def close_tab(self, index: int) -> bool:
        """关闭指定标签页"""
        if index < 0 or index >= self._tab_widget.count():
            return False
        
        widget = self._tab_widget.widget(index)
        path_to_remove = None
        for path, tab in self._tabs.items():
            if tab.widget == widget:
                path_to_remove = path
                break
        
        if path_to_remove:
            tab = self._tabs[path_to_remove]
            if isinstance(widget, CodeEditor) and widget.is_modified():
                reply = QMessageBox.question(
                    self, self._get_text("dialog.confirm.title", "Confirm"),
                    f"Save changes to {os.path.basename(path_to_remove)}?",
                    QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
                )
                if reply == QMessageBox.StandardButton.Save:
                    self.save_file()
                elif reply == QMessageBox.StandardButton.Cancel:
                    return False
            
            self._tab_widget.removeTab(index)
            del self._tabs[path_to_remove]
            self._update_empty_state()
            self._emit_editable_file_state()
            return True
        return False

    def close_all_tabs(self):
        while self._tab_widget.count() > 0:
            self.close_tab(0)

    def get_open_files(self) -> list:
        return list(self._tabs.keys())

    def get_current_file(self) -> Optional[str]:
        current_widget = self._tab_widget.currentWidget()
        if not current_widget:
            return None
        for path, tab in self._tabs.items():
            if tab.widget == current_widget:
                return path
        return None

    def switch_to_file(self, path: str) -> bool:
        if path not in self._tabs:
            return False
        tab = self._tabs[path]
        index = self._tab_widget.indexOf(tab.widget)
        if index >= 0:
            self._tab_widget.setCurrentIndex(index)
            return True
        return False

    def _close_current_tab(self):
        current_index = self._tab_widget.currentIndex()
        if current_index >= 0:
            self.close_tab(current_index)


    # ============================================================
    # 事件处理
    # ============================================================

    def _emit_undo_redo_state(self):
        can_undo = self.can_undo()
        can_redo = self.can_redo()
        self.undo_redo_state_changed.emit(can_undo, can_redo)

    def _emit_editable_file_state(self):
        has_editable = any(not tab.is_readonly for tab in self._tabs.values())
        self.editable_file_state_changed.emit(has_editable)

    def _on_undo_available_changed(self, available: bool):
        self._emit_undo_redo_state()

    def _on_redo_available_changed(self, available: bool):
        self._emit_undo_redo_state()

    def _on_editor_modification_changed(self, path: str, modified: bool):
        self._update_tab_title(path)

    def _on_tab_close_requested(self, index: int):
        self.close_tab(index)

    def _on_current_tab_changed(self, index: int):
        if index < 0:
            self.undo_redo_state_changed.emit(False, False)
            return
        widget = self._tab_widget.widget(index)
        for path, tab in self._tabs.items():
            if tab.widget == widget:
                self._update_status_bar(path)
                break
        self._emit_undo_redo_state()
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
        for path, tab in self._tabs.items():
            if tab.widget == widget:
                clipboard = QApplication.clipboard()
                clipboard.setText(path)
                break

    def _update_cursor_position(self):
        current_widget = self._tab_widget.currentWidget()
        if isinstance(current_widget, CodeEditor):
            line, col = current_widget.get_cursor_position()
            self._line_col_label.setText(f"Ln {line}, Col {col}")

    def _update_tab_title(self, path: str):
        if path not in self._tabs:
            return
        tab = self._tabs[path]
        index = self._tab_widget.indexOf(tab.widget)
        if index < 0:
            return
        file_name = os.path.basename(path)
        if isinstance(tab.widget, CodeEditor) and tab.widget.is_modified():
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
                EVENT_STATE_PROJECT_CLOSED, EVENT_WORKFLOW_LOCKED, EVENT_WORKFLOW_UNLOCKED
            )
            self.event_bus.subscribe(EVENT_LANGUAGE_CHANGED, self._on_language_changed)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_OPENED, self._on_project_opened)
            self.event_bus.subscribe(EVENT_STATE_PROJECT_CLOSED, self._on_project_closed)
            self.event_bus.subscribe(EVENT_WORKFLOW_LOCKED, self._on_workflow_locked)
            self.event_bus.subscribe(EVENT_WORKFLOW_UNLOCKED, self._on_workflow_unlocked)

    def _on_language_changed(self, event_data: Dict[str, Any]):
        self.retranslate_ui()

    def _on_project_opened(self, event_data: Dict[str, Any]):
        self.close_all_tabs()
        self._update_empty_state()

    def _on_project_closed(self, event_data: Dict[str, Any]):
        self.close_all_tabs()
        self._update_empty_state()

    def _on_workflow_locked(self, event_data: Dict[str, Any]):
        self.set_readonly(True)

    def _on_workflow_unlocked(self, event_data: Dict[str, Any]):
        self.set_readonly(False)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "CodeEditorPanel",
    "CodeEditor",
    "SpiceHighlighter",
    "JsonHighlighter",
    "PythonHighlighter",
    "ImageViewer",
    "DocumentViewer",
    "EDITABLE_EXTENSIONS",
    "IMAGE_EXTENSIONS",
    "DOCUMENT_EXTENSIONS",
]
