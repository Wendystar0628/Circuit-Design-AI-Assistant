from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class PendingWorkspaceEditBar(QWidget):
    accept_all_requested = pyqtSignal()
    reject_all_requested = pyqtSignal()
    file_clicked = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._summary_state: Dict[str, Any] = {
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

    def set_summary_state(self, summary_state: Dict[str, Any]) -> None:
        files = []
        for file_summary in summary_state.get("files", []) or []:
            if not isinstance(file_summary, dict):
                continue
            file_path = str(file_summary.get("path", "") or "")
            if not file_path:
                continue
            files.append(
                {
                    "path": file_path,
                    "relative_path": str(file_summary.get("relative_path", file_path) or file_path),
                    "added_lines": int(file_summary.get("added_lines", 0) or 0),
                    "deleted_lines": int(file_summary.get("deleted_lines", 0) or 0),
                }
            )
        self._summary_state = {
            "file_count": len(files),
            "added_lines": int(summary_state.get("added_lines", 0) or 0),
            "deleted_lines": int(summary_state.get("deleted_lines", 0) or 0),
            "files": files,
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
        file_count = int(self._summary_state.get("file_count", 0) or 0)
        added_lines = int(self._summary_state.get("added_lines", 0) or 0)
        deleted_lines = int(self._summary_state.get("deleted_lines", 0) or 0)
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
        for file_summary in self._summary_state.get("files", []) or []:
            if isinstance(file_summary, dict):
                self._body_layout.addWidget(self._build_file_widget(file_summary))
        self._body_layout.addStretch(1)

    def _build_file_widget(self, file_summary: Dict[str, Any]) -> QWidget:
        frame = QFrame(self._body_container)
        frame.setStyleSheet(
            "QFrame { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; }"
        )
        header_layout = QHBoxLayout(frame)
        header_layout.setContentsMargins(10, 10, 10, 10)
        header_layout.setSpacing(8)

        file_path = str(file_summary.get("path", "") or "")
        relative_path = str(file_summary.get("relative_path", file_path) or file_path)

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
            f"+{int(file_summary.get('added_lines', 0) or 0)} / -{int(file_summary.get('deleted_lines', 0) or 0)}",
            frame,
        )
        stats_label.setStyleSheet("QLabel { color: #475569; font-size: 11px; }")
        header_layout.addWidget(stats_label)

        return frame


__all__ = ["PendingWorkspaceEditBar"]
