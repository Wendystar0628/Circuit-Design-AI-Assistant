# RawDataTable - Virtual Scrolling Data Table for Simulation Results
"""
原始数据表格

职责：
- 以表格形式显示仿真原始数据
- 使用虚拟滚动技术支持大数据量显示
- 支持跳转、搜索、导出功能

技术选型：
- QTableView + 自定义 QAbstractTableModel
- 仅渲染可见行（约 30-50 行）
- 滚动时动态加载数据块

使用示例：
    from presentation.panels.simulation.raw_data_table import RawDataTable
    
    table = RawDataTable()
    table.load_data(simulation_result)
    table.jump_to_time(0.001)
    table.export_selection("output.csv", "csv")
"""

import logging
from typing import Dict, List, Optional, Set

from PyQt6.QtCore import (
    Qt,
    QAbstractTableModel,
    QModelIndex,
    pyqtSignal,
    QTimer,
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
    QFileDialog,
    QMessageBox,
    QSizePolicy,
    QAbstractItemView,
)
from PyQt6.QtGui import QColor

from domain.simulation.data.waveform_data_service import (
    WaveformDataService,
    TableData,
    TableRow,
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
    FONT_SIZE_NORMAL,
    SPACING_SMALL,
    SPACING_NORMAL,
    BORDER_RADIUS_NORMAL,
)


# ============================================================
# 常量定义
# ============================================================

# 每次加载的行数
CHUNK_SIZE = 100

# 预加载缓冲区大小（可见行数的倍数）
BUFFER_MULTIPLIER = 2

# 数值显示精度
VALUE_PRECISION = 6

# 搜索容差默认值
DEFAULT_TOLERANCE = 1e-9


# ============================================================
# RawDataTableModel - 虚拟滚动数据模型
# ============================================================

class RawDataTableModel(QAbstractTableModel):
    """
    原始数据表格模型
    
    实现虚拟滚动：
    - 仅缓存可见区域附近的数据
    - 滚动时动态加载新数据块
    - 使用 LRU 策略管理缓存
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # 数据服务
        self._data_service: WaveformDataService = waveform_data_service
        
        # 当前仿真结果
        self._result: Optional[SimulationResult] = None
        
        # 表格元数据
        self._total_rows: int = 0
        self._signal_names: List[str] = []
        self._x_label: str = "Time"
        
        # 数据缓存：row_index -> TableRow
        self._cache: Dict[int, TableRow] = {}
        self._cache_start: int = 0
        self._cache_end: int = 0
        
        # 选中的信号列（用于过滤显示）
        self._visible_signals: Optional[Set[str]] = None
    
    def load_result(self, result: SimulationResult, signal_names: Optional[List[str]] = None):
        """
        加载仿真结果
        
        Args:
            result: 仿真结果对象
            signal_names: 要显示的信号列表（None 表示全部）
        """
        self.beginResetModel()
        
        self._result = result
        self._cache.clear()
        self._cache_start = 0
        self._cache_end = 0
        
        # 获取初始数据以确定总行数和列名
        initial_data = self._data_service.get_table_data(
            result, start_row=0, count=CHUNK_SIZE, signal_names=signal_names
        )
        
        if initial_data:
            self._total_rows = initial_data.total_rows
            self._signal_names = initial_data.signal_names
            self._x_label = initial_data.x_label
            
            # 缓存初始数据
            for row in initial_data.rows:
                self._cache[row.index] = row
            
            self._cache_start = 0
            self._cache_end = len(initial_data.rows)
        else:
            self._total_rows = 0
            self._signal_names = []
            self._x_label = "Time"
        
        if signal_names:
            self._visible_signals = set(signal_names)
        else:
            self._visible_signals = None
        
        self.endResetModel()
        
        self._logger.debug(
            f"Loaded result: {self._total_rows} rows, "
            f"{len(self._signal_names)} signals"
        )
    
    def clear(self):
        """清空数据"""
        self.beginResetModel()
        
        self._result = None
        self._total_rows = 0
        self._signal_names = []
        self._x_label = "Time"
        self._cache.clear()
        self._cache_start = 0
        self._cache_end = 0
        self._visible_signals = None
        
        self.endResetModel()
    
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """返回行数"""
        if parent.isValid():
            return 0
        return self._total_rows
    
    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """返回列数（X 轴 + 信号列）"""
        if parent.isValid():
            return 0
        return 1 + len(self._signal_names)
    
    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        """获取单元格数据"""
        if not index.isValid():
            return None
        
        row = index.row()
        col = index.column()
        
        if row < 0 or row >= self._total_rows:
            return None
        
        if col < 0 or col >= self.columnCount():
            return None
        
        # 确保数据已加载
        self._ensure_row_loaded(row)
        
        if row not in self._cache:
            return None
        
        table_row = self._cache[row]
        
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                # X 轴值
                return self._format_value(table_row.x_value)
            else:
                # 信号值
                signal_name = self._signal_names[col - 1]
                value = table_row.values.get(signal_name)
                if value is not None:
                    return self._format_value(value)
                return "--"
        
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        
        return None
    
    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole
    ):
        """获取表头数据"""
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        
        if orientation == Qt.Orientation.Horizontal:
            if section == 0:
                return self._x_label
            elif section - 1 < len(self._signal_names):
                return self._signal_names[section - 1]
        
        elif orientation == Qt.Orientation.Vertical:
            return str(section)
        
        return None
    
    def get_row_for_time(self, time_value: float) -> int:
        """
        获取指定时间值对应的行号
        
        使用二分查找在缓存或数据中定位。
        
        Args:
            time_value: 时间值
            
        Returns:
            int: 行号，未找到返回 -1
        """
        if self._result is None or self._total_rows == 0:
            return -1
        
        # 加载足够的数据进行搜索
        # 简化实现：线性搜索缓存，如果不在缓存中则加载更多数据
        
        # 首先检查缓存
        for row_idx, row in self._cache.items():
            if abs(row.x_value - time_value) < DEFAULT_TOLERANCE:
                return row_idx
        
        # 二分查找：加载数据块进行搜索
        low, high = 0, self._total_rows - 1
        
        while low <= high:
            mid = (low + high) // 2
            
            # 确保 mid 行已加载
            self._ensure_row_loaded(mid)
            
            if mid not in self._cache:
                break
            
            mid_value = self._cache[mid].x_value
            
            if abs(mid_value - time_value) < DEFAULT_TOLERANCE:
                return mid
            elif mid_value < time_value:
                low = mid + 1
            else:
                high = mid - 1
        
        # 返回最接近的行
        return low if low < self._total_rows else self._total_rows - 1
    
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
        if self._result is None or self._total_rows == 0:
            return -1
        
        if column < 0 or column >= self.columnCount():
            return -1
        
        # 逐块搜索
        for chunk_start in range(start_row, self._total_rows, CHUNK_SIZE):
            chunk_end = min(chunk_start + CHUNK_SIZE, self._total_rows)
            
            # 加载数据块
            self._load_chunk(chunk_start, chunk_end - chunk_start)
            
            # 在缓存中搜索
            for row_idx in range(chunk_start, chunk_end):
                if row_idx not in self._cache:
                    continue
                
                row = self._cache[row_idx]
                
                if column == 0:
                    cell_value = row.x_value
                else:
                    signal_name = self._signal_names[column - 1]
                    cell_value = row.values.get(signal_name)
                
                if cell_value is not None and abs(cell_value - value) <= tolerance:
                    return row_idx
        
        return -1
    
    def get_row_data(self, row: int) -> Optional[TableRow]:
        """获取指定行的数据"""
        self._ensure_row_loaded(row)
        return self._cache.get(row)
    
    def get_column_values(self, column: int, start_row: int, count: int) -> List[float]:
        """获取指定列的值列表"""
        values = []
        
        for row_idx in range(start_row, min(start_row + count, self._total_rows)):
            self._ensure_row_loaded(row_idx)
            
            if row_idx not in self._cache:
                continue
            
            row = self._cache[row_idx]
            
            if column == 0:
                values.append(row.x_value)
            else:
                signal_name = self._signal_names[column - 1]
                value = row.values.get(signal_name)
                if value is not None:
                    values.append(value)
        
        return values
    
    @property
    def signal_names(self) -> List[str]:
        """获取信号名称列表"""
        return self._signal_names.copy()
    
    @property
    def total_rows(self) -> int:
        """获取总行数"""
        return self._total_rows
    
    @property
    def x_label(self) -> str:
        """获取 X 轴标签"""
        return self._x_label
    
    def _ensure_row_loaded(self, row: int):
        """确保指定行已加载到缓存"""
        if row in self._cache:
            return
        
        # 计算需要加载的数据块
        chunk_start = max(0, row - CHUNK_SIZE // 2)
        self._load_chunk(chunk_start, CHUNK_SIZE)
    
    def _load_chunk(self, start_row: int, count: int):
        """加载数据块到缓存"""
        if self._result is None:
            return
        
        # 检查是否已在缓存中
        all_cached = all(
            i in self._cache
            for i in range(start_row, min(start_row + count, self._total_rows))
        )
        
        if all_cached:
            return
        
        # 加载数据
        signal_names = list(self._visible_signals) if self._visible_signals else None
        table_data = self._data_service.get_table_data(
            self._result,
            start_row=start_row,
            count=count,
            signal_names=signal_names
        )
        
        if table_data:
            for row in table_data.rows:
                self._cache[row.index] = row
            
            # 更新缓存范围
            self._cache_start = min(self._cache_start, start_row)
            self._cache_end = max(self._cache_end, start_row + len(table_data.rows))
            
            # 清理过大的缓存
            self._trim_cache()
    
    def _trim_cache(self):
        """清理过大的缓存"""
        max_cache_size = CHUNK_SIZE * BUFFER_MULTIPLIER * 2
        
        if len(self._cache) <= max_cache_size:
            return
        
        # 保留最近访问的数据（简化实现：保留中间部分）
        sorted_keys = sorted(self._cache.keys())
        
        if len(sorted_keys) > max_cache_size:
            # 移除最旧的数据
            keys_to_remove = sorted_keys[:len(sorted_keys) - max_cache_size]
            for key in keys_to_remove:
                del self._cache[key]
    
    def _format_value(self, value: float) -> str:
        """格式化数值显示"""
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
    - 虚拟滚动（大数据量）
    - 跳转到指定行/时间
    - 搜索特定值
    - 导出选中数据
    
    Signals:
        row_selected: 行选中时发出，携带行号
        time_selected: 时间选中时发出，携带时间值
    """
    
    row_selected = pyqtSignal(int)
    time_selected = pyqtSignal(float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # 数据模型
        self._model = RawDataTableModel()
        
        # 当前仿真结果
        self._result: Optional[SimulationResult] = None
        
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
        self._jump_row_spin.setMinimum(0)
        self._jump_row_spin.setMaximum(0)
        self._jump_row_spin.setFixedWidth(80)
        self._jump_row_btn = QPushButton()
        self._jump_row_btn.setObjectName("jumpBtn")
        self._jump_row_btn.clicked.connect(self._on_jump_to_row)
        
        toolbar_layout.addWidget(self._jump_row_label)
        toolbar_layout.addWidget(self._jump_row_spin)
        toolbar_layout.addWidget(self._jump_row_btn)
        
        toolbar_layout.addSpacing(SPACING_NORMAL)
        
        # 跳转到时间
        self._jump_time_label = QLabel()
        self._jump_time_spin = QDoubleSpinBox()
        self._jump_time_spin.setDecimals(9)
        self._jump_time_spin.setMinimum(0.0)
        self._jump_time_spin.setMaximum(1e9)
        self._jump_time_spin.setFixedWidth(120)
        self._jump_time_btn = QPushButton()
        self._jump_time_btn.setObjectName("jumpBtn")
        self._jump_time_btn.clicked.connect(self._on_jump_to_time)
        
        toolbar_layout.addWidget(self._jump_time_label)
        toolbar_layout.addWidget(self._jump_time_spin)
        toolbar_layout.addWidget(self._jump_time_btn)
        
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
        
        # 导出按钮
        self._export_btn = QPushButton()
        self._export_btn.setObjectName("exportBtn")
        self._export_btn.clicked.connect(self._on_export)
        toolbar_layout.addWidget(self._export_btn)
        
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
        self._selection_label = QLabel()
        
        status_layout.addWidget(self._row_count_label)
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
            
            #jumpBtn, #searchBtn, #exportBtn {{
                background-color: {COLOR_BG_SECONDARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 2px 8px;
                min-height: 20px;
            }}
            
            #jumpBtn:hover, #searchBtn:hover, #exportBtn:hover {{
                background-color: {COLOR_ACCENT_LIGHT};
                border-color: {COLOR_ACCENT};
            }}
            
            #jumpBtn:pressed, #searchBtn:pressed, #exportBtn:pressed {{
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
    
    def load_data(
        self,
        result: SimulationResult,
        signal_names: Optional[List[str]] = None
    ):
        """
        加载仿真结果数据
        
        Args:
            result: 仿真结果对象
            signal_names: 要显示的信号列表（None 表示全部）
        """
        self._result = result
        self._model.load_result(result, signal_names)
        
        # 更新 UI
        self._update_controls()
        self._update_status()
        
        self._logger.info(
            f"Loaded data: {self._model.total_rows} rows, "
            f"{len(self._model.signal_names)} signals"
        )
    
    def clear(self):
        """清空数据"""
        self._result = None
        self._model.clear()
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
        
        self.row_selected.emit(row_number)
    
    def jump_to_time(self, time_value: float):
        """
        跳转到指定时间点
        
        Args:
            time_value: 时间值
        """
        row = self._model.get_row_for_time(time_value)
        
        if row >= 0:
            self.jump_to_row(row)
            
            # 获取实际时间值
            row_data = self._model.get_row_data(row)
            if row_data:
                self.time_selected.emit(row_data.x_value)
    
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
    
    def export_selection(self, path: str, format: str = "csv") -> bool:
        """
        导出选中数据
        
        Args:
            path: 导出路径
            format: 导出格式（csv, tsv）
            
        Returns:
            bool: 是否成功
        """
        selection = self._table_view.selectionModel().selectedRows()
        
        if not selection:
            self._logger.warning("No rows selected for export")
            return False
        
        try:
            delimiter = "," if format == "csv" else "\t"
            
            with open(path, "w", encoding="utf-8") as f:
                # 写入表头
                headers = [self._model.x_label] + self._model.signal_names
                f.write(delimiter.join(headers) + "\n")
                
                # 写入数据
                for index in selection:
                    row = index.row()
                    row_data = self._model.get_row_data(row)
                    
                    if row_data:
                        values = [str(row_data.x_value)]
                        for signal in self._model.signal_names:
                            val = row_data.values.get(signal)
                            values.append(str(val) if val is not None else "")
                        f.write(delimiter.join(values) + "\n")
            
            self._logger.info(f"Exported {len(selection)} rows to {path}")
            return True
            
        except Exception as e:
            self._logger.error(f"Export failed: {e}")
            return False
    
    def get_selected_rows(self) -> List[int]:
        """获取选中的行号列表"""
        selection = self._table_view.selectionModel().selectedRows()
        return [index.row() for index in selection]
    
    def get_selected_data(self) -> List[TableRow]:
        """获取选中行的数据"""
        rows = self.get_selected_rows()
        return [
            self._model.get_row_data(row)
            for row in rows
            if self._model.get_row_data(row) is not None
        ]
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._jump_row_label.setText(self._tr("Row:"))
        self._jump_row_btn.setText(self._tr("Go"))
        self._jump_time_label.setText(self._tr("Time:"))
        self._jump_time_btn.setText(self._tr("Go"))
        self._search_label.setText(self._tr("Search:"))
        self._search_btn.setText(self._tr("Find"))
        self._export_btn.setText(self._tr("Export"))
        
        self._update_status()
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _update_controls(self):
        """更新控件状态"""
        total_rows = self._model.total_rows
        
        # 更新行号范围
        self._jump_row_spin.setMaximum(max(0, total_rows - 1))
        
        # 更新搜索列下拉框
        self._search_column_combo.clear()
        self._search_column_combo.addItem(self._model.x_label)
        for signal in self._model.signal_names:
            self._search_column_combo.addItem(signal)
        
        # 启用/禁用控件
        has_data = total_rows > 0
        self._jump_row_spin.setEnabled(has_data)
        self._jump_row_btn.setEnabled(has_data)
        self._jump_time_spin.setEnabled(has_data)
        self._jump_time_btn.setEnabled(has_data)
        self._search_column_combo.setEnabled(has_data)
        self._search_value_edit.setEnabled(has_data)
        self._search_btn.setEnabled(has_data)
        self._export_btn.setEnabled(has_data)
    
    def _update_status(self):
        """更新状态栏"""
        total_rows = self._model.total_rows
        
        self._row_count_label.setText(
            self._tr("Total: {count} rows").format(count=total_rows)
        )
        
        selection = self._table_view.selectionModel().selectedRows()
        if selection:
            self._selection_label.setText(
                self._tr("Selected: {count} rows").format(count=len(selection))
            )
        else:
            self._selection_label.setText("")
    
    def _on_jump_to_row(self):
        """跳转到行按钮点击"""
        row = self._jump_row_spin.value()
        self.jump_to_row(row)
    
    def _on_jump_to_time(self):
        """跳转到时间按钮点击"""
        time_value = self._jump_time_spin.value()
        self.jump_to_time(time_value)
    
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
    
    def _on_export(self):
        """导出按钮点击"""
        selection = self._table_view.selectionModel().selectedRows()
        
        if not selection:
            QMessageBox.warning(
                self,
                self._tr("No Selection"),
                self._tr("Please select rows to export.")
            )
            return
        
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._tr("Export Data"),
            "",
            "CSV Files (*.csv);;TSV Files (*.tsv)"
        )
        
        if not path:
            return
        
        format = "tsv" if path.endswith(".tsv") else "csv"
        
        if self.export_selection(path, format):
            QMessageBox.information(
                self,
                self._tr("Export Complete"),
                self._tr("Data exported successfully.")
            )
        else:
            QMessageBox.critical(
                self,
                self._tr("Export Failed"),
                self._tr("Failed to export data.")
            )
    
    def _on_selection_changed(self, selected, deselected):
        """选择变化"""
        self._update_status()
    
    def _on_double_clicked(self, index: QModelIndex):
        """双击行"""
        row = index.row()
        row_data = self._model.get_row_data(row)
        
        if row_data:
            self.time_selected.emit(row_data.x_value)
    
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
