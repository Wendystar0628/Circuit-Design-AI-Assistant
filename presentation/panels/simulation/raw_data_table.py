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
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from PyQt6.QtCore import (
    Qt,
    QAbstractTableModel,
    QModelIndex,
)
from PyQt6.QtWidgets import (
    QWidget,
    QSizePolicy,
)

from domain.simulation.data.waveform_data_service import (
    WaveformDataService,
    TableSnapshot,
    waveform_data_service,
)
from domain.simulation.models.simulation_result import SimulationResult

# ============================================================
# 常量定义
# ============================================================

# 数值显示精度
VALUE_PRECISION = 6

# 搜索容差默认值
DEFAULT_TOLERANCE = 1e-9

WEB_SNAPSHOT_MAX_ROWS = 80
WEB_SNAPSHOT_MAX_SIGNAL_COLUMNS = 8


# ============================================================
# RawDataTableModel - 快照数据模型
# ============================================================

class RawDataTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        self._data_service: WaveformDataService = waveform_data_service
        self._snapshot: Optional[TableSnapshot] = None
    
    def load_result(self, result: SimulationResult):
        self.beginResetModel()
        self._snapshot = self._data_service.build_table_snapshot(result)
        self.endResetModel()
        
        total_rows = self._snapshot.total_rows if self._snapshot else 0
        signal_count = len(self._snapshot.signal_names) if self._snapshot else 0
        self._logger.debug(f"Loaded result snapshot: {total_rows} rows, {signal_count} signals")
    
    def clear(self):
        self.beginResetModel()
        self._snapshot = None
        self.endResetModel()
    
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        if self._snapshot is None:
            return 0
        return self._snapshot.total_rows
    
    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        if self._snapshot is None:
            return 1
        return 1 + len(self._snapshot.signal_names)
    
    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or self._snapshot is None:
            return None
        
        row = index.row()
        col = index.column()
        
        if row < 0 or row >= self._snapshot.total_rows:
            return None
        
        if col < 0 or col >= self.columnCount():
            return None
        
        if role == Qt.ItemDataRole.DisplayRole:
            value = self._get_cell_value(row, col)
            if value is None:
                return "--"
            return self._format_value(value)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        
        return None
    
    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole
    ):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        
        if orientation == Qt.Orientation.Horizontal:
            if section == 0:
                return self.x_label
            if self._snapshot and section - 1 < len(self._snapshot.signal_names):
                return self._snapshot.signal_names[section - 1]
        
        elif orientation == Qt.Orientation.Vertical:
            return str(section + 1)
        
        return None
    
    def get_row_for_x_value(self, x_value: float) -> int:
        """
        获取指定 X 轴值对应的行号
        
        在当前快照中查找最接近的行号。
        
        Args:
            x_value: X 轴值
            
        Returns:
            int: 行号，未找到返回 -1
        """
        if self._snapshot is None or self._snapshot.total_rows == 0:
            return -1

        distances = np.abs(self._snapshot.x_values - x_value)
        return int(np.argmin(distances))
    
    def search_value(
        self,
        column: int,
        value: float,
        tolerance: float = DEFAULT_TOLERANCE,
        start_row: int = 0
    ) -> int:
        """
        搜索特定值
        
        Args:
            column: 列索引
            value: 要搜索的值
            tolerance: 容差
            start_row: 起始行
            
        Returns:
            int: 找到的行号，未找到返回 -1
        """
        if self._snapshot is None or self._snapshot.total_rows == 0:
            return -1
        
        if column < 0 or column >= self.columnCount():
            return -1

        start_row = max(0, start_row)
        column_values = self._get_column_array(column)
        if column_values is None or start_row >= len(column_values):
            return -1

        scan_values = column_values[start_row:]
        matches = np.where(np.isfinite(scan_values) & (np.abs(scan_values - value) <= tolerance))[0]
        if len(matches) == 0:
            return -1
        return start_row + int(matches[0])
    
    @property
    def signal_names(self) -> List[str]:
        if self._snapshot is None:
            return []
        return self._snapshot.signal_names.copy()
    
    @property
    def total_rows(self) -> int:
        if self._snapshot is None:
            return 0
        return self._snapshot.total_rows
    
    @property
    def x_label(self) -> str:
        """获取 X 轴标签"""
        if self._snapshot is None:
            return "X"
        return self._snapshot.x_label

    @property
    def snapshot(self) -> Optional[TableSnapshot]:
        return self._snapshot

    def _get_column_array(self, column: int) -> Optional[np.ndarray]:
        if self._snapshot is None:
            return None
        if column == 0:
            return self._snapshot.x_values
        signal_index = column - 1
        if signal_index < 0 or signal_index >= len(self._snapshot.signal_names):
            return None
        signal_name = self._snapshot.signal_names[signal_index]
        return self._snapshot.signal_columns.get(signal_name)

    def _get_cell_value(self, row: int, column: int) -> Optional[float]:
        column_values = self._get_column_array(column)
        if column_values is None or row < 0 or row >= len(column_values):
            return None
        value = float(column_values[row])
        if not np.isfinite(value):
            return None
        return value

    def _format_value(self, value: float) -> str:
        if abs(value) < 1e-3 or abs(value) >= 1e6:
            return f"{value:.{VALUE_PRECISION}e}"
        return f"{value:.{VALUE_PRECISION}g}"


# ============================================================
# RawDataTable - 原始数据表格组件
# ============================================================

class RawDataTable(QWidget):
    """
    原始数据表格组件
    
    以表格形式显示仿真原始数据，支持：
    - 基于结果快照的稳定表格显示
    - 跳转到指定行/X 轴值
    - 搜索特定值
    - 导出选中数据
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        self._selected_rows: List[int] = []
        self._visible_signal_window_start = 0
        
        # 数据模型
        self._model = RawDataTableModel()
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        self.setStyleSheet("")
        self.retranslate_ui()
    
    # ============================================================
    # 公共方法
    # ============================================================
    
    def load_data(self, result: SimulationResult):
        """
        加载仿真结果数据
        
        Args:
            result: 仿真结果对象
        """
        self._model.load_result(result)
        self._selected_rows = []
        self._visible_signal_window_start = 0
        
        self._logger.info(
            f"Loaded data: {self._model.total_rows} rows, "
            f"{len(self._model.signal_names)} signals"
        )
    
    def clear(self):
        """清空数据"""
        self._model.clear()
        self._selected_rows = []
        self._visible_signal_window_start = 0

    def shift_signal_window(self, page_delta: int) -> bool:
        total_signal_columns = len(self._model.signal_names)
        window_size = max(1, WEB_SNAPSHOT_MAX_SIGNAL_COLUMNS)
        if total_signal_columns <= 0 or page_delta == 0:
            return False
        max_start = max(0, total_signal_columns - window_size)
        next_start = min(
            max(0, self._visible_signal_window_start + int(page_delta) * window_size),
            max_start,
        )
        if next_start == self._visible_signal_window_start:
            return False
        self._visible_signal_window_start = next_start
        return True
    
    def get_web_snapshot(
        self,
        *,
        max_rows: int = WEB_SNAPSHOT_MAX_ROWS,
        max_signal_columns: int = WEB_SNAPSHOT_MAX_SIGNAL_COLUMNS,
    ) -> Dict[str, Any]:
        snapshot = self._model.snapshot
        signal_names = self._model.signal_names
        total_signal_columns = len(signal_names)
        total_rows = self._model.total_rows
        selected_rows = [row for row in self._selected_rows if 0 <= row < total_rows]
        self._selected_rows = list(selected_rows)
        selected_row = selected_rows[0] if selected_rows else None
        if max_rows <= 0 or max_signal_columns <= 0:
            return {
                "has_data": bool(snapshot is not None and total_rows > 0),
                "row_count": total_rows,
                "signal_count": total_signal_columns,
                "x_axis_label": self._model.x_label,
                "result_binding_text": self._build_result_binding_text(),
                "visible_columns": [],
                "rows": [],
                "window_start": 0,
                "window_end": 0,
                "has_more_before": False,
                "has_more_after": total_rows > 0,
                "selected_row_numbers": [row + 1 for row in selected_rows],
                "selection_count": len(selected_rows),
                "visible_signal_start": 0,
                "visible_signal_end": 0,
                "visible_signal_count": 0,
                "has_more_signal_columns_before": False,
                "has_more_signal_columns_after": total_signal_columns > 0,
            }
        if total_rows <= max_rows:
            window_start = 0
            window_end = total_rows
        elif selected_row is not None:
            half_window = max_rows // 2
            window_start = max(0, min(selected_row - half_window, total_rows - max_rows))
            window_end = min(total_rows, window_start + max_rows)
        else:
            window_start = 0
            window_end = min(total_rows, max_rows)
        signal_window_start, signal_window_end = self._resolve_signal_window_bounds(
            total_signal_columns,
            max_signal_columns,
        )
        visible_signal_names = signal_names[signal_window_start:signal_window_end]
        visible_columns = [self._model.x_label, *visible_signal_names] if snapshot is not None else []
        visible_column_arrays = []
        if snapshot is not None:
            visible_column_arrays.append(snapshot.x_values)
            visible_column_arrays.extend(snapshot.signal_columns.get(signal_name) for signal_name in visible_signal_names)
        selected_row_set = set(selected_rows)
        rows = []
        for row_index in range(window_start, window_end):
            values = [
                self._format_web_value(column_values, row_index)
                for column_values in visible_column_arrays
            ]
            rows.append({
                "row_number": row_index + 1,
                "values": values,
                "selected": row_index in selected_row_set,
            })
        return {
            "has_data": bool(snapshot is not None and total_rows > 0),
            "row_count": total_rows,
            "signal_count": total_signal_columns,
            "x_axis_label": self._model.x_label,
            "result_binding_text": self._build_result_binding_text(),
            "visible_columns": visible_columns,
            "rows": rows,
            "window_start": window_start + 1 if rows else 0,
            "window_end": window_end,
            "has_more_before": window_start > 0,
            "has_more_after": window_end < total_rows,
            "selected_row_numbers": [row + 1 for row in selected_rows],
            "selection_count": len(selected_rows),
            "visible_signal_start": signal_window_start + 1 if visible_signal_names else 0,
            "visible_signal_end": signal_window_end,
            "visible_signal_count": len(visible_signal_names),
            "has_more_signal_columns_before": signal_window_start > 0,
            "has_more_signal_columns_after": signal_window_end < total_signal_columns,
        }
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        return

    # ============================================================
    # 内部方法
    # ============================================================

    def _resolve_signal_window_bounds(
        self,
        total_signal_columns: int,
        max_signal_columns: int,
    ) -> Tuple[int, int]:
        if total_signal_columns <= 0:
            self._visible_signal_window_start = 0
            return 0, 0
        window_size = max(1, int(max_signal_columns or 0))
        if total_signal_columns <= window_size:
            self._visible_signal_window_start = 0
            return 0, total_signal_columns
        max_start = max(0, total_signal_columns - window_size)
        window_start = min(max(0, self._visible_signal_window_start), max_start)
        self._visible_signal_window_start = window_start
        return window_start, min(total_signal_columns, window_start + window_size)

    def _ensure_signal_column_visible(self, column: int):
        signal_index = int(column) - 1
        total_signal_columns = len(self._model.signal_names)
        if signal_index < 0 or signal_index >= total_signal_columns:
            return
        window_size = max(1, WEB_SNAPSHOT_MAX_SIGNAL_COLUMNS)
        max_start = max(0, total_signal_columns - window_size)
        if self._visible_signal_window_start <= signal_index < self._visible_signal_window_start + window_size:
            return
        self._visible_signal_window_start = max(0, min(signal_index - window_size // 2, max_start))

    def _format_web_value(self, column_values: Optional[np.ndarray], row_index: int) -> str:
        if column_values is None or row_index < 0 or row_index >= len(column_values):
            return "--"
        value = float(column_values[row_index])
        if not np.isfinite(value):
            return "--"
        return self._model._format_value(value)

    def _build_result_binding_text(self) -> str:
        snapshot = self._model.snapshot
        if snapshot is None:
            return ""

        result_name = os.path.basename(snapshot.result_path) if snapshot.result_path else ""
        parts = [
            snapshot.analysis_type.upper() if snapshot.analysis_type else "",
            f"v{snapshot.version}" if snapshot.version else "",
            snapshot.timestamp or "",
            result_name,
        ]
        return " | ".join(part for part in parts if part)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "RawDataTable",
    "RawDataTableModel",
]
