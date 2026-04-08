from __future__ import annotations

import html
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class PendingWorkspaceEditBar(QWidget):
    accept_all_requested = pyqtSignal()
    reject_all_requested = pyqtSignal()
    accept_file_requested = pyqtSignal(str)
    reject_file_requested = pyqtSignal(str)
    accept_hunk_requested = pyqtSignal(str, str)
    reject_hunk_requested = pyqtSignal(str, str)
    file_clicked = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._state: Dict[str, Any] = {
            "file_count": 0,
            "added_lines": 0,
            "deleted_lines": 0,
            "files": [],
        }
        self._expanded = False
        self._summary_label: Optional[QLabel] = None
        self._toggle_btn: Optional[QToolButton] = None
        self._accept_all_btn: Optional[QPushButton] = None
        self._reject_all_btn: Optional[QPushButton] = None
        self._body_scroll: Optional[QScrollArea] = None
        self._body_container: Optional[QWidget] = None
        self._body_layout: Optional[QVBoxLayout] = None
        self._setup_ui()
        self._refresh_ui()

    def set_state(self, state: Dict[str, Any]) -> None:
        self._state = {
            "file_count": int(state.get("file_count", 0) or 0),
            "added_lines": int(state.get("added_lines", 0) or 0),
            "deleted_lines": int(state.get("deleted_lines", 0) or 0),
            "files": list(state.get("files", []) or []),
        }
        self._refresh_ui()

    def _setup_ui(self) -> None:
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QFrame(self)
        header.setStyleSheet(
            "QFrame { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; }"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 8, 10, 8)
        header_layout.setSpacing(8)

        self._toggle_btn = QToolButton(header)
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.clicked.connect(lambda _checked=False: self._toggle_expanded())
        header_layout.addWidget(self._toggle_btn)

        self._summary_label = QLabel(header)
        self._summary_label.setStyleSheet("QLabel { color: #0f172a; font-size: 12px; font-weight: 600; }")
        header_layout.addWidget(self._summary_label, 1)

        self._accept_all_btn = QPushButton(header)
        self._accept_all_btn.setStyleSheet(
            "QPushButton { background: #ecfdf5; color: #166534; border: 1px solid #bbf7d0; border-radius: 6px; padding: 4px 10px; font-size: 12px; }"
            "QPushButton:hover { background: #dcfce7; }"
        )
        self._accept_all_btn.clicked.connect(lambda _checked=False: self.accept_all_requested.emit())
        header_layout.addWidget(self._accept_all_btn)

        self._reject_all_btn = QPushButton(header)
        self._reject_all_btn.setStyleSheet(
            "QPushButton { background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; border-radius: 6px; padding: 4px 10px; font-size: 12px; }"
            "QPushButton:hover { background: #fee2e2; }"
        )
        self._reject_all_btn.clicked.connect(lambda _checked=False: self.reject_all_requested.emit())
        header_layout.addWidget(self._reject_all_btn)

        layout.addWidget(header)

        self._body_scroll = QScrollArea(self)
        self._body_scroll.setWidgetResizable(True)
        self._body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._body_scroll.setStyleSheet("QScrollArea { background: transparent; }")

        self._body_container = QWidget(self._body_scroll)
        self._body_layout = QVBoxLayout(self._body_container)
        self._body_layout.setContentsMargins(2, 0, 2, 0)
        self._body_layout.setSpacing(8)
        self._body_scroll.setWidget(self._body_container)
        self._body_scroll.setMaximumHeight(320)
        layout.addWidget(self._body_scroll)

    def _toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self._refresh_ui()

    def _refresh_ui(self) -> None:
        file_count = int(self._state.get("file_count", 0) or 0)
        added_lines = int(self._state.get("added_lines", 0) or 0)
        deleted_lines = int(self._state.get("deleted_lines", 0) or 0)
        self.setVisible(file_count > 0)
        if self._toggle_btn is not None:
            self._toggle_btn.setText("▼" if self._expanded else "▶")
            self._toggle_btn.setChecked(self._expanded)
        if self._summary_label is not None:
            self._summary_label.setText(
                f"{file_count} 个文件待确认  +{added_lines} / -{deleted_lines}"
            )
        if self._accept_all_btn is not None:
            self._accept_all_btn.setText("接受全部修改")
            self._accept_all_btn.setEnabled(file_count > 0)
        if self._reject_all_btn is not None:
            self._reject_all_btn.setText("拒绝全部修改")
            self._reject_all_btn.setEnabled(file_count > 0)
        if self._body_scroll is not None:
            self._body_scroll.setVisible(self._expanded and file_count > 0)
        self._rebuild_body()

    def _rebuild_body(self) -> None:
        if self._body_layout is None:
            return
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for file_state in self._state.get("files", []) or []:
            if isinstance(file_state, dict):
                self._body_layout.addWidget(self._build_file_widget(file_state))
        self._body_layout.addStretch(1)

    def _build_file_widget(self, file_state: Dict[str, Any]) -> QWidget:
        frame = QFrame(self._body_container)
        frame.setStyleSheet(
            "QFrame { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; }"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        file_path = str(file_state.get("path", "") or "")
        relative_path = str(file_state.get("relative_path", file_path) or file_path)

        file_btn = QPushButton(relative_path, frame)
        file_btn.setFlat(True)
        file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        file_btn.setStyleSheet(
            "QPushButton { color: #2563eb; text-align: left; border: none; font-size: 12px; font-weight: 600; padding: 0; }"
            "QPushButton:hover { color: #1d4ed8; text-decoration: underline; }"
        )
        file_btn.clicked.connect(lambda _=False, target=file_path: self.file_clicked.emit(target))
        header_layout.addWidget(file_btn, 1)

        stats_label = QLabel(
            f"+{int(file_state.get('added_lines', 0) or 0)} / -{int(file_state.get('deleted_lines', 0) or 0)}",
            frame,
        )
        stats_label.setStyleSheet("QLabel { color: #475569; font-size: 11px; }")
        header_layout.addWidget(stats_label)

        accept_btn = QPushButton("接受文件", frame)
        accept_btn.setStyleSheet(
            "QPushButton { background: #ecfdf5; color: #166534; border: 1px solid #bbf7d0; border-radius: 6px; padding: 4px 8px; font-size: 11px; }"
            "QPushButton:hover { background: #dcfce7; }"
        )
        accept_btn.clicked.connect(
            lambda _=False, target=file_path: self.accept_file_requested.emit(target)
        )
        header_layout.addWidget(accept_btn)

        reject_btn = QPushButton("拒绝文件", frame)
        reject_btn.setStyleSheet(
            "QPushButton { background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; border-radius: 6px; padding: 4px 8px; font-size: 11px; }"
            "QPushButton:hover { background: #fee2e2; }"
        )
        reject_btn.clicked.connect(
            lambda _=False, target=file_path: self.reject_file_requested.emit(target)
        )
        header_layout.addWidget(reject_btn)

        layout.addLayout(header_layout)

        for hunk in file_state.get("hunks", []) or []:
            if isinstance(hunk, dict):
                layout.addWidget(self._build_hunk_widget(file_path, hunk))

        return frame

    def _build_hunk_widget(self, file_path: str, hunk: Dict[str, Any]) -> QWidget:
        frame = QFrame(self._body_container)
        frame.setStyleSheet(
            "QFrame { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; }"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)

        header_label = QLabel(str(hunk.get("header", "") or ""), frame)
        header_label.setStyleSheet(
            "QLabel { color: #334155; font-size: 11px; font-family: 'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace; }"
        )
        top_row.addWidget(header_label, 1)

        stat_label = QLabel(
            f"+{int(hunk.get('added_lines', 0) or 0)} / -{int(hunk.get('deleted_lines', 0) or 0)}",
            frame,
        )
        stat_label.setStyleSheet("QLabel { color: #64748b; font-size: 11px; }")
        top_row.addWidget(stat_label)

        accept_btn = QPushButton("接受", frame)
        accept_btn.setStyleSheet(
            "QPushButton { background: #ecfdf5; color: #166534; border: 1px solid #bbf7d0; border-radius: 6px; padding: 3px 8px; font-size: 11px; }"
            "QPushButton:hover { background: #dcfce7; }"
        )
        accept_btn.clicked.connect(
            lambda _=False, target=file_path, target_hunk=str(hunk.get('id', '') or ''): self.accept_hunk_requested.emit(target, target_hunk)
        )
        top_row.addWidget(accept_btn)

        reject_btn = QPushButton("拒绝", frame)
        reject_btn.setStyleSheet(
            "QPushButton { background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; border-radius: 6px; padding: 3px 8px; font-size: 11px; }"
            "QPushButton:hover { background: #fee2e2; }"
        )
        reject_btn.clicked.connect(
            lambda _=False, target=file_path, target_hunk=str(hunk.get('id', '') or ''): self.reject_hunk_requested.emit(target, target_hunk)
        )
        top_row.addWidget(reject_btn)

        layout.addLayout(top_row)

        preview = QTextBrowser(frame)
        preview.setOpenLinks(False)
        preview.setFrameShape(QFrame.Shape.NoFrame)
        preview.setReadOnly(True)
        preview.setMaximumHeight(180)
        preview.setStyleSheet(
            "QTextBrowser { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px; padding: 0; font-family: 'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace; font-size: 11px; }"
        )
        preview.setHtml(self._build_hunk_html(hunk))
        layout.addWidget(preview)

        return frame

    def _build_hunk_html(self, hunk: Dict[str, Any]) -> str:
        rows: List[str] = []
        for line in hunk.get("lines", []) or []:
            if not isinstance(line, dict):
                continue
            kind = str(line.get("kind", "") or "")
            if kind == "added":
                bg = "#ecfdf5"
                fg = "#166534"
                marker = "+"
            elif kind == "deleted":
                bg = "#fef2f2"
                fg = "#991b1b"
                marker = "-"
            else:
                bg = "#f8fafc"
                fg = "#334155"
                marker = " "
            old_line = line.get("old_line_number")
            new_line = line.get("new_line_number")
            old_html = "" if old_line is None else str(old_line)
            new_html = "" if new_line is None else str(new_line)
            text_html = html.escape(str(line.get("text", "") or "")).replace(" ", "&nbsp;")
            rows.append(
                "<div style=\"display:flex; font-family:JetBrains Mono, Cascadia Code, Consolas, monospace; background:"
                + bg
                + "; color:"
                + fg
                + ";\">"
                + f"<span style=\"width:56px; padding:2px 6px; color:#64748b; border-right:1px solid #e2e8f0;\">{old_html}</span>"
                + f"<span style=\"width:56px; padding:2px 6px; color:#64748b; border-right:1px solid #e2e8f0;\">{new_html}</span>"
                + f"<span style=\"width:24px; padding:2px 6px; color:{fg};\">{marker}</span>"
                + f"<span style=\"flex:1; padding:2px 6px; white-space:pre-wrap;\">{text_html or '&nbsp;'}</span>"
                + "</div>"
            )
        if not rows:
            rows.append(
                "<div style=\"padding:6px 8px; color:#64748b;\">没有可显示的文本 diff。</div>"
            )
        return "<html><body style='margin:0; background:#ffffff;'>" + "".join(rows) + "</body></html>"


__all__ = ["PendingWorkspaceEditBar"]
