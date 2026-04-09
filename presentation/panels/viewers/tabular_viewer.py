import csv
import os
from dataclasses import dataclass

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableView,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class _TabularData:
    headers: list[str]
    rows: list[list[str]]
    encoding: str
    delimiter: str


class _TabularTableModel(QAbstractTableModel):
    def __init__(self, headers: list[str], rows: list[list[str]], parent=None):
        super().__init__(parent)
        self._headers = headers
        self._rows = rows

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._headers)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        value = self._rows[index.row()][index.column()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return value
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignRight if _looks_numeric(value) else Qt.AlignmentFlag.AlignLeft))
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self._headers):
                return self._headers[section]
            return ""
        return str(section + 1)


class TabularViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._summary_label = QLabel(self)
        self._summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self._message_label = QLabel(self)
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message_label.setWordWrap(True)
        self._message_label.hide()

        self._table = QTableView(self)
        self._table.setAlternatingRowColors(True)
        self._table.setWordWrap(False)
        self._table.setSortingEnabled(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(True)
        self._table.setCornerButtonEnabled(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self._table.verticalHeader().setDefaultSectionSize(24)
        self._table.setStyleSheet(
            "QTableView { border: none; background: #ffffff; alternate-background-color: #f8fafc; gridline-color: #dbe3ef; }"
            "QHeaderView::section { background: #f8fafc; color: #0f172a; padding: 6px 8px; border: 1px solid #dbe3ef; font-weight: 600; }"
        )

        header = QFrame(self)
        header.setFrameShape(QFrame.Shape.NoFrame)
        header.setStyleSheet("background: #f8fafc; border-bottom: 1px solid #dbe3ef;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.addWidget(self._summary_label)
        header_layout.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self._message_label)
        layout.addWidget(self._table, 1)

    def load_file(self, path: str) -> bool:
        try:
            data = _read_tabular_data(path)
        except Exception as e:
            self._set_error(f"Failed to load table: {e}")
            return False

        self._message_label.hide()
        self._table.show()
        model = _TabularTableModel(data.headers, data.rows, self._table)
        self._table.setModel(model)
        self._summary_label.setText(
            f"{os.path.basename(path)}    {len(data.rows)} rows    {len(data.headers)} columns    encoding: {data.encoding}    delimiter: {_delimiter_label(data.delimiter)}"
        )
        self._table.resizeColumnsToContents()
        for column in range(model.columnCount()):
            width = min(max(self._table.columnWidth(column), 96), 360)
            self._table.setColumnWidth(column, width)
        return True

    def _set_error(self, message: str) -> None:
        self._summary_label.setText("表格预览不可用")
        self._table.hide()
        self._message_label.setText(message)
        self._message_label.show()


def _read_tabular_data(path: str) -> _TabularData:
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            with open(path, "r", encoding=encoding, newline="") as f:
                sample = f.read(8192)
                f.seek(0)
                sniffer = csv.Sniffer()
                try:
                    dialect = sniffer.sniff(sample, delimiters=",\t;")
                except csv.Error:
                    dialect = csv.excel_tab if path.lower().endswith(".tsv") else csv.excel
                try:
                    has_header = sniffer.has_header(sample)
                except csv.Error:
                    has_header = True
                rows = [list(row) for row in csv.reader(f, dialect)]
            return _build_tabular_data(rows, encoding, dialect.delimiter, has_header)
        except Exception as e:
            last_error = e
    raise last_error or ValueError("Unknown CSV parsing error")


def _build_tabular_data(rows: list[list[str]], encoding: str, delimiter: str, has_header: bool) -> _TabularData:
    if not rows:
        return _TabularData(headers=[], rows=[], encoding=encoding, delimiter=delimiter)

    width = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (width - len(row)) for row in rows]

    if has_header:
        headers = normalized_rows[0]
        body_rows = normalized_rows[1:]
    else:
        headers = [_column_name(index) for index in range(width)]
        body_rows = normalized_rows

    if not headers:
        headers = [_column_name(index) for index in range(width)]

    return _TabularData(headers=headers, rows=body_rows, encoding=encoding, delimiter=delimiter)


def _column_name(index: int) -> str:
    name = ""
    value = index
    while True:
        value, remainder = divmod(value, 26)
        name = chr(65 + remainder) + name
        if value == 0:
            return name
        value -= 1


def _looks_numeric(value: str) -> bool:
    stripped = str(value or "").strip()
    if not stripped:
        return False
    try:
        float(stripped.replace(",", ""))
        return True
    except ValueError:
        return False


def _delimiter_label(delimiter: str) -> str:
    if delimiter == ",":
        return "comma (,)"
    if delimiter == "\t":
        return "tab"
    if delimiter == ";":
        return "semicolon (;)"
    return delimiter or "unknown"


__all__ = ["TabularViewer"]
