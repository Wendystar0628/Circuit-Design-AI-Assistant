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
from typing import Any, Dict, List, Optional

import numpy as np

from PyQt6.QtCore import (
    Qt,
    QAbstractTableModel,
    QModelIndex,
)
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableView,
    QHeaderView,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QMessageBox,
    QSizePolicy,
    QAbstractItemView,
)

from domain.simulation.data.waveform_data_service import (
    WaveformDataService,
    TableSnapshot,
    waveform_data_service,
)
from domain.simulation.models.simulation_result import SimulationResult

from resources.theme import (
    COLOR_BG_PRIMARY,
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_BORDER,
    COLOR_ACCENT,
    COLOR_ACCENT_LIGHT,
    FONT_SIZE_SMALL,
    SPACING_SMALL,
    SPACING_NORMAL,
    BORDER_RADIUS_NORMAL,
)


# ============================================================
# 常量定义
# ============================================================

# 数值显示精度
VALUE_PRECISION = 6

# 搜索容差默认值
DEFAULT_TOLERANCE = 1e-9


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
        
        # 数据模型
        self._model = RawDataTableModel()
        
        # 初始化 UI
        self._setup_ui()
        self._apply_style()
        self._connect_signals()
        
        # 初始化文本
        self.retranslate_ui()
    
    def _setup_ui(self):
        """初始化 UI 组件"""
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 工具栏
        self._toolbar = QFrame()
        self._toolbar.setObjectName("rawDataToolbar")
        toolbar_layout = QHBoxLayout(self._toolbar)
        toolbar_layout.setContentsMargins(
            SPACING_SMALL, SPACING_SMALL, SPACING_SMALL, SPACING_SMALL
        )
        toolbar_layout.setSpacing(SPACING_SMALL)
        
        # 跳转到行
        self._jump_row_label = QLabel()
        self._jump_row_spin = QSpinBox()
        self._jump_row_spin.setRange(0, 0)
        self._jump_row_spin.setFixedWidth(80)
        self._jump_row_btn = QPushButton()
        self._jump_row_btn.setObjectName("jumpBtn")
        self._jump_row_btn.clicked.connect(self._on_jump_to_row)
        
        toolbar_layout.addWidget(self._jump_row_label)
        toolbar_layout.addWidget(self._jump_row_spin)
        toolbar_layout.addWidget(self._jump_row_btn)
        
        toolbar_layout.addSpacing(SPACING_NORMAL)
        
        # 跳转到 X 轴值
        self._jump_x_label = QLabel()
        self._jump_x_spin = QDoubleSpinBox()
        self._jump_x_spin.setDecimals(9)
        self._jump_x_spin.setMinimum(0.0)
        self._jump_x_spin.setMaximum(1e9)
        self._jump_x_spin.setFixedWidth(120)
        self._jump_x_btn = QPushButton()
        self._jump_x_btn.setObjectName("jumpBtn")
        self._jump_x_btn.clicked.connect(self._on_jump_to_x_value)
        
        toolbar_layout.addWidget(self._jump_x_label)
        toolbar_layout.addWidget(self._jump_x_spin)
        toolbar_layout.addWidget(self._jump_x_btn)
        
        toolbar_layout.addSpacing(SPACING_NORMAL)
        
        # 搜索
        self._search_label = QLabel()
        self._search_column_combo = QComboBox()
        self._search_column_combo.setFixedWidth(100)
        self._search_value_edit = QLineEdit()
        self._search_value_edit.setFixedWidth(100)
        self._search_value_edit.setPlaceholderText("Value")
        self._search_btn = QPushButton()
        self._search_btn.setObjectName("searchBtn")
        self._search_btn.clicked.connect(self._on_search)
        
        toolbar_layout.addWidget(self._search_label)
        toolbar_layout.addWidget(self._search_column_combo)
        toolbar_layout.addWidget(self._search_value_edit)
        toolbar_layout.addWidget(self._search_btn)
        
        toolbar_layout.addStretch()
        
        main_layout.addWidget(self._toolbar)
        
        # 表格视图
        self._table_view = QTableView()
        self._table_view.setObjectName("rawDataTableView")
        self._table_view.setModel(self._model)
        self._table_view.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table_view.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._table_view.setAlternatingRowColors(True)
        self._table_view.setSortingEnabled(False)
        self._table_view.setShowGrid(True)
        
        # 表头设置
        h_header = self._table_view.horizontalHeader()
        h_header.setStretchLastSection(True)
        h_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h_header.setDefaultSectionSize(100)
        
        v_header = self._table_view.verticalHeader()
        v_header.setDefaultSectionSize(24)
        v_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        
        main_layout.addWidget(self._table_view, 1)
        
        # 状态栏
        self._status_bar = QFrame()
        self._status_bar.setObjectName("rawDataStatusBar")
        status_layout = QHBoxLayout(self._status_bar)
        status_layout.setContentsMargins(
            SPACING_SMALL, SPACING_SMALL, SPACING_SMALL, SPACING_SMALL
        )
        status_layout.setSpacing(SPACING_NORMAL)
        
        self._row_count_label = QLabel()
        self._result_binding_label = QLabel()
        self._selection_label = QLabel()
        
        status_layout.addWidget(self._row_count_label)
        status_layout.addWidget(self._result_binding_label)
        status_layout.addStretch()
        status_layout.addWidget(self._selection_label)
        
        main_layout.addWidget(self._status_bar)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #rawDataToolbar {{
                background-color: {COLOR_BG_TERTIARY};
                border-bottom: 1px solid {COLOR_BORDER};
            }}
            
            #rawDataToolbar QLabel {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #rawDataToolbar QSpinBox,
            #rawDataToolbar QDoubleSpinBox,
            #rawDataToolbar QLineEdit,
            #rawDataToolbar QComboBox {{
                background-color: {COLOR_BG_SECONDARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                padding: 2px 4px;
                min-height: 20px;
            }}
            
            #jumpBtn, #searchBtn {{
                background-color: {COLOR_BG_SECONDARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 2px 8px;
                min-height: 20px;
            }}
            
            #jumpBtn:hover, #searchBtn:hover {{
                background-color: {COLOR_ACCENT_LIGHT};
                border-color: {COLOR_ACCENT};
            }}
            
            #jumpBtn:pressed, #searchBtn:pressed {{
                background-color: {COLOR_ACCENT};
                color: white;
            }}
            
            #rawDataTableView {{
                background-color: {COLOR_BG_PRIMARY};
                alternate-background-color: {COLOR_BG_SECONDARY};
                color: {COLOR_TEXT_PRIMARY};
                gridline-color: {COLOR_BORDER};
                border: none;
                font-family: monospace;
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #rawDataTableView::item {{
                padding: 2px 4px;
            }}
            
            #rawDataTableView::item:selected {{
                background-color: {COLOR_ACCENT_LIGHT};
                color: {COLOR_TEXT_PRIMARY};
            }}
            
            #rawDataTableView QHeaderView::section {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_PRIMARY};
                border: none;
                border-right: 1px solid {COLOR_BORDER};
                border-bottom: 1px solid {COLOR_BORDER};
                padding: 4px;
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #rawDataStatusBar {{
                background-color: {COLOR_BG_TERTIARY};
                border-top: 1px solid {COLOR_BORDER};
            }}
            
            #rawDataStatusBar QLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
        """)
    
    def _connect_signals(self):
        """连接信号"""
        self._table_view.selectionModel().selectionChanged.connect(
            self._on_selection_changed
        )
        self._table_view.doubleClicked.connect(self._on_double_clicked)
    
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
        self._table_view.clearSelection()
        self._table_view.scrollToTop()
        
        # 更新 UI
        self._update_controls()
        self._update_status()
        
        self._logger.info(
            f"Loaded data: {self._model.total_rows} rows, "
            f"{len(self._model.signal_names)} signals"
        )
    
    def clear(self):
        """清空数据"""
        self._model.clear()
        self._table_view.clearSelection()
        self._table_view.scrollToTop()
        self._update_controls()
        self._update_status()
    
    def jump_to_row(self, row_number: int):
        """
        跳转到指定行
        
        Args:
            row_number: 行号（从 0 开始）
        """
        if row_number < 0 or row_number >= self._model.total_rows:
            return
        
        index = self._model.index(row_number, 0)
        self._table_view.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        self._table_view.selectRow(row_number)
    
    def jump_to_x_value(self, x_value: float):
        """
        跳转到指定 X 轴值
        
        Args:
            x_value: X 轴值
        """
        row = self._model.get_row_for_x_value(x_value)
        
        if row >= 0:
            self.jump_to_row(row)
    
    def search_value(
        self,
        column: int,
        value: float,
        tolerance: float = DEFAULT_TOLERANCE
    ) -> bool:
        """
        搜索特定值
        
        Args:
            column: 列索引
            value: 要搜索的值
            tolerance: 容差
            
        Returns:
            bool: 是否找到
        """
        # 从当前选中行的下一行开始搜索
        selection = self._table_view.selectionModel().selectedRows()
        start_row = 0
        if selection:
            start_row = selection[-1].row() + 1
        
        row = self._model.search_value(column, value, tolerance, start_row)
        
        if row >= 0:
            self.jump_to_row(row)
            return True
        
        # 如果从中间开始没找到，从头开始搜索
        if start_row > 0:
            row = self._model.search_value(column, value, tolerance, 0)
            if row >= 0:
                self.jump_to_row(row)
                return True
        
        return False
    
    def get_web_snapshot(self, *, max_rows: int = 400) -> Dict[str, Any]:
        snapshot = self._model.snapshot
        headers = [self._model.x_label, *self._model.signal_names] if snapshot is not None else []
        selection_model = self._table_view.selectionModel()
        selected_rows = []
        if selection_model is not None:
            selected_rows = sorted(index.row() for index in selection_model.selectedRows())
        selected_row = selected_rows[0] if selected_rows else None
        total_rows = self._model.total_rows
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
        selected_row_set = set(selected_rows)
        rows = []
        for row_index in range(window_start, window_end):
            values = []
            for column_index in range(len(headers)):
                cell_value = self._model._get_cell_value(row_index, column_index)
                values.append(self._model._format_value(cell_value) if cell_value is not None else "--")
            rows.append({
                "row_number": row_index + 1,
                "values": values,
                "selected": row_index in selected_row_set,
            })
        return {
            "has_data": bool(snapshot is not None and total_rows > 0),
            "row_count": total_rows,
            "signal_count": len(self._model.signal_names),
            "x_axis_label": self._model.x_label,
            "columns": headers,
            "rows": rows,
            "window_start": window_start + 1 if rows else 0,
            "window_end": window_end,
            "has_more_before": window_start > 0,
            "has_more_after": window_end < total_rows,
            "selected_row_numbers": [row + 1 for row in selected_rows],
            "selection_count": len(selected_rows),
        }
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._jump_row_label.setText(self._tr("Row:"))
        self._jump_row_btn.setText(self._tr("Go"))
        self._jump_x_btn.setText(self._tr("Go"))
        self._search_label.setText(self._tr("Search:"))
        self._search_btn.setText(self._tr("Find"))
        
        self._update_axis_labels()
        self._update_status()
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _update_controls(self):
        """更新控件状态"""
        total_rows = self._model.total_rows
        self._update_axis_labels()
        
        # 更新行号范围
        if total_rows > 0:
            self._jump_row_spin.setRange(1, total_rows)
            if self._jump_row_spin.value() <= 0:
                self._jump_row_spin.setValue(1)
        else:
            self._jump_row_spin.setRange(0, 0)
        
        # 更新搜索列下拉框
        self._search_column_combo.clear()
        self._search_column_combo.addItem(self._model.x_label)
        for signal in self._model.signal_names:
            self._search_column_combo.addItem(signal)
        
        # 启用/禁用控件
        has_data = total_rows > 0
        self._jump_row_spin.setEnabled(has_data)
        self._jump_row_btn.setEnabled(has_data)
        self._jump_x_spin.setEnabled(has_data)
        self._jump_x_btn.setEnabled(has_data)
        self._search_column_combo.setEnabled(has_data)
        self._search_value_edit.setEnabled(has_data)
        self._search_btn.setEnabled(has_data)

    def _update_axis_labels(self):
        axis_name = self._get_x_axis_name()
        self._jump_x_label.setText(f"{axis_name}:")

    def _get_x_axis_name(self) -> str:
        label = self._model.x_label or "X"
        if " (" in label:
            return label.split(" (", 1)[0]
        return label
    
    def _update_status(self):
        """更新状态栏"""
        total_rows = self._model.total_rows
        
        self._row_count_label.setText(
            self._tr("Total: {count} rows").format(count=total_rows)
        )
        self._result_binding_label.setText(self._build_result_binding_text())
        
        selection = self._table_view.selectionModel().selectedRows()
        if selection:
            self._selection_label.setText(
                self._tr("Selected: {count} rows").format(count=len(selection))
            )
        else:
            self._selection_label.setText("")
    
    def _on_jump_to_row(self):
        """跳转到行按钮点击"""
        row = max(0, self._jump_row_spin.value() - 1)
        self.jump_to_row(row)
    
    def _on_jump_to_x_value(self):
        """跳转到 X 轴值按钮点击"""
        x_value = self._jump_x_spin.value()
        self.jump_to_x_value(x_value)
    
    def _on_search(self):
        """搜索按钮点击"""
        column = self._search_column_combo.currentIndex()
        value_text = self._search_value_edit.text().strip()
        
        if not value_text:
            return
        
        try:
            value = float(value_text)
        except ValueError:
            QMessageBox.warning(
                self,
                self._tr("Invalid Value"),
                self._tr("Please enter a valid number.")
            )
            return
        
        found = self.search_value(column, value)
        
        if not found:
            QMessageBox.information(
                self,
                self._tr("Not Found"),
                self._tr("Value not found in the selected column.")
            )
    
    def _on_selection_changed(self, selected, deselected):
        """选择变化"""
        self._update_status()
    
    def _on_double_clicked(self, index: QModelIndex):
        """双击行"""
        row = index.row()
        self.jump_to_row(row)

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
    
    def _tr(self, text: str) -> str:
        """翻译文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(f"raw_data_table.{text}", default=text)
        except ImportError:
            return text


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "RawDataTable",
    "RawDataTableModel",
]
