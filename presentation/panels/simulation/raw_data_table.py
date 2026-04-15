# RawDataTable - Snapshot-backed Data Table for Simulation Results
"""
原始数据表格

职责：
- 以表格形式显示仿真原始数据
- 以当前仿真结果快照稳定显示完整数据
- 支持跳转、搜索、导出功能

技术选型：
- QTableView + 自定义 QAbstractTableModel
- 模型直接绑定当前仿真结果快照
- 表格滚动不触发数据重排或懒加载补块

使用示例：
    from presentation.panels.simulation.raw_data_table import RawDataTable
    
    table = RawDataTable()
    table.load_data(simulation_result)
    table.jump_to_x_value(0.001)
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication

from domain.simulation.data.waveform_data_service import (
    TableSnapshot,
    waveform_data_service,
)
from domain.simulation.models.simulation_result import SimulationResult

VALUE_PRECISION = 6
DEFAULT_COLUMN_WIDTH_PX = 136
DEFAULT_ROW_HEIGHT_PX = 28
DEFAULT_COLUMN_HEADER_HEIGHT_PX = 32
DEFAULT_ROW_HEADER_WIDTH_PX = 64


class RawDataTable(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._logger = logging.getLogger(__name__)
        self._snapshot: Optional[TableSnapshot] = None
        self._dataset_id = ""
        self._document_version = 0

    @property
    def dataset_id(self) -> str:
        return self._dataset_id

    @property
    def document_version(self) -> int:
        return self._document_version

    @property
    def signal_names(self) -> List[str]:
        if self._snapshot is None:
            return []
        return list(self._snapshot.signal_names)

    @property
    def row_count(self) -> int:
        if self._snapshot is None:
            return 0
        return self._snapshot.total_rows

    @property
    def column_count(self) -> int:
        if self._snapshot is None:
            return 0
        return 1 + len(self._snapshot.signal_names)

    @property
    def x_label(self) -> str:
        if self._snapshot is None:
            return "X"
        return self._snapshot.x_label

    def load_data(self, result: SimulationResult):
        self._snapshot = waveform_data_service.build_table_snapshot(result)
        self._document_version += 1
        self._dataset_id = self._build_dataset_id(result) if self._snapshot is not None and self._snapshot.total_rows > 0 else ""
        total_rows = self._snapshot.total_rows if self._snapshot else 0
        signal_count = len(self._snapshot.signal_names) if self._snapshot else 0
        self._logger.info(
            f"Loaded data: {total_rows} rows, {signal_count} signals"
        )

    def clear(self):
        self._snapshot = None
        self._dataset_id = ""
        self._document_version += 1

    def get_document_payload(self) -> Dict[str, Any]:
        snapshot = self._snapshot
        if snapshot is None or snapshot.total_rows <= 0:
            return self._build_empty_document_payload()
        columns = [
            {
                "key": f"column_{column_index}",
                "label": self._column_label(column_index),
                "width_px": DEFAULT_COLUMN_WIDTH_PX,
            }
            for column_index in range(self.column_count)
        ]
        return {
            "dataset_id": self._dataset_id,
            "version": self._document_version,
            "has_data": True,
            "row_count": snapshot.total_rows,
            "column_count": len(columns),
            "row_header_width_px": DEFAULT_ROW_HEADER_WIDTH_PX,
            "row_height_px": DEFAULT_ROW_HEIGHT_PX,
            "column_header_height_px": DEFAULT_COLUMN_HEADER_HEIGHT_PX,
            "columns": columns,
        }

    def get_viewport_payload(
        self,
        *,
        dataset_id: str = "",
        version: Optional[int] = None,
        row_start: int = 0,
        row_end: int = 0,
        col_start: int = 0,
        col_end: int = 0,
    ) -> Dict[str, Any]:
        snapshot = self._snapshot
        if snapshot is None or not self._matches_document(dataset_id, version):
            return self._build_empty_viewport_payload()
        normalized_row_start, normalized_row_end = self._clamp_range(row_start, row_end, snapshot.total_rows)
        normalized_col_start, normalized_col_end = self._clamp_range(col_start, col_end, self.column_count)
        if normalized_row_start >= normalized_row_end or normalized_col_start >= normalized_col_end:
            return {
                "dataset_id": self._dataset_id,
                "version": self._document_version,
                "row_start": normalized_row_start,
                "row_end": normalized_row_end,
                "col_start": normalized_col_start,
                "col_end": normalized_col_end,
                "rows": [],
            }
        column_arrays = [
            self._get_column_array(column_index)
            for column_index in range(normalized_col_start, normalized_col_end)
        ]
        rows = []
        for row_index in range(normalized_row_start, normalized_row_end):
            rows.append({
                "row_index": row_index,
                "values": [
                    self._format_web_value(column_array, row_index)
                    for column_array in column_arrays
                ],
            })
        return {
            "dataset_id": self._dataset_id,
            "version": self._document_version,
            "row_start": normalized_row_start,
            "row_end": normalized_row_end,
            "col_start": normalized_col_start,
            "col_end": normalized_col_end,
            "rows": rows,
        }

    def copy_range_to_clipboard(
        self,
        *,
        dataset_id: str = "",
        version: Optional[int] = None,
        row_start: int = 0,
        row_end: int = 0,
        col_start: int = 0,
        col_end: int = 0,
        include_headers: bool = False,
    ) -> bool:
        snapshot = self._snapshot
        if snapshot is None or not self._matches_document(dataset_id, version):
            return False
        text = self._build_copy_text(
            row_start=row_start,
            row_end=row_end,
            col_start=col_start,
            col_end=col_end,
            include_headers=include_headers,
        )
        if not text:
            return False
        app = QApplication.instance()
        if app is None:
            return False
        clipboard = app.clipboard()
        if clipboard is None:
            return False
        clipboard.setText(text)
        return True

    def retranslate_ui(self):
        return

    def _build_empty_document_payload(self) -> Dict[str, Any]:
        return {
            "dataset_id": self._dataset_id,
            "version": self._document_version,
            "has_data": False,
            "row_count": 0,
            "column_count": 0,
            "row_header_width_px": DEFAULT_ROW_HEADER_WIDTH_PX,
            "row_height_px": DEFAULT_ROW_HEIGHT_PX,
            "column_header_height_px": DEFAULT_COLUMN_HEADER_HEIGHT_PX,
            "columns": [],
        }

    def _build_empty_viewport_payload(self) -> Dict[str, Any]:
        return {
            "dataset_id": self._dataset_id,
            "version": self._document_version,
            "row_start": 0,
            "row_end": 0,
            "col_start": 0,
            "col_end": 0,
            "rows": [],
        }

    def _build_copy_text(
        self,
        *,
        row_start: int,
        row_end: int,
        col_start: int,
        col_end: int,
        include_headers: bool,
    ) -> str:
        snapshot = self._snapshot
        if snapshot is None:
            return ""
        normalized_row_start, normalized_row_end = self._clamp_range(row_start, row_end, snapshot.total_rows)
        normalized_col_start, normalized_col_end = self._clamp_range(col_start, col_end, self.column_count)
        if normalized_row_start >= normalized_row_end or normalized_col_start >= normalized_col_end:
            return ""
        column_arrays = [
            self._get_column_array(column_index)
            for column_index in range(normalized_col_start, normalized_col_end)
        ]
        lines: List[str] = []
        if include_headers:
            lines.append("\t".join(
                self._column_label(column_index)
                for column_index in range(normalized_col_start, normalized_col_end)
            ))
        for row_index in range(normalized_row_start, normalized_row_end):
            lines.append("\t".join(
                self._format_web_value(column_array, row_index)
                for column_array in column_arrays
            ))
        return "\n".join(lines)

    def _column_label(self, column_index: int) -> str:
        if column_index <= 0:
            return self.x_label
        signal_index = column_index - 1
        if signal_index < 0 or signal_index >= len(self.signal_names):
            return ""
        return self.signal_names[signal_index]

    def _get_column_array(self, column_index: int) -> Optional[np.ndarray]:
        snapshot = self._snapshot
        if snapshot is None:
            return None
        if column_index == 0:
            return snapshot.x_values
        signal_index = column_index - 1
        if signal_index < 0 or signal_index >= len(snapshot.signal_names):
            return None
        signal_name = snapshot.signal_names[signal_index]
        return snapshot.signal_columns.get(signal_name)

    def _format_web_value(self, column_values: Optional[np.ndarray], row_index: int) -> str:
        if column_values is None or row_index < 0 or row_index >= len(column_values):
            return "--"
        value = float(column_values[row_index])
        if not np.isfinite(value):
            return "--"
        return self._format_value(value)

    def _format_value(self, value: float) -> str:
        if abs(value) < 1e-3 or abs(value) >= 1e6:
            return f"{value:.{VALUE_PRECISION}e}"
        return f"{value:.{VALUE_PRECISION}g}"

    def _build_dataset_id(self, result: SimulationResult) -> str:
        parts = [
            str(getattr(result, "session_id", "") or "").strip(),
            str(getattr(result, "file_path", "") or "").strip(),
            str(getattr(result, "timestamp", "") or "").strip(),
        ]
        normalized_parts = [part for part in parts if part]
        if normalized_parts:
            return "::".join(normalized_parts)
        return f"raw-data-{self._document_version}"

    def _matches_document(self, dataset_id: str, version: Optional[int]) -> bool:
        normalized_dataset_id = str(dataset_id or "").strip()
        if normalized_dataset_id and normalized_dataset_id != self._dataset_id:
            return False
        if version is None:
            return True
        try:
            return int(version) == self._document_version
        except (TypeError, ValueError):
            return False

    def _clamp_range(self, start: int, end: int, length: int) -> Tuple[int, int]:
        try:
            normalized_start = int(start)
        except (TypeError, ValueError):
            normalized_start = 0
        try:
            normalized_end = int(end)
        except (TypeError, ValueError):
            normalized_end = normalized_start
        normalized_start = max(0, min(normalized_start, length))
        normalized_end = max(normalized_start, min(normalized_end, length))
        return normalized_start, normalized_end


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "RawDataTable",
]
