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
from typing import Any, Dict, List, Optional

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
        self._web_snapshot_cache: Optional[Dict[str, Any]] = None
        
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
        self._web_snapshot_cache = None
        
        self._logger.info(
            f"Loaded data: {self._model.total_rows} rows, "
            f"{len(self._model.signal_names)} signals"
        )
    
    def clear(self):
        """清空数据"""
        self._model.clear()
        self._web_snapshot_cache = None
    
    def get_web_snapshot(self) -> Dict[str, Any]:
        if self._web_snapshot_cache is not None:
            return self._web_snapshot_cache
        snapshot = self._model.snapshot
        if snapshot is None or snapshot.total_rows <= 0:
            self._web_snapshot_cache = {
                "visible_columns": [],
                "rows": [],
            }
            return self._web_snapshot_cache
        signal_names = self._model.signal_names
        visible_columns = [self._model.x_label, *signal_names]
        visible_column_arrays = [snapshot.x_values]
        visible_column_arrays.extend(snapshot.signal_columns.get(signal_name) for signal_name in signal_names)
        rows = []
        for row_index in range(snapshot.total_rows):
            values = [
                self._format_web_value(column_values, row_index)
                for column_values in visible_column_arrays
            ]
            rows.append({
                "row_number": row_index + 1,
                "values": values,
            })
        self._web_snapshot_cache = {
            "visible_columns": visible_columns,
            "rows": rows,
        }
        return self._web_snapshot_cache
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        return

    # ============================================================
    # 内部方法
    # ============================================================

    def _format_web_value(self, column_values: Optional[np.ndarray], row_index: int) -> str:
        if column_values is None or row_index < 0 or row_index >= len(column_values):
            return "--"
        value = float(column_values[row_index])
        if not np.isfinite(value):
            return "--"
        return self._model._format_value(value)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "RawDataTable",
    "RawDataTableModel",
]
