# WaveformWidget - Interactive Waveform Chart Component
"""
波形图表组件

职责：
- 渲染交互式波形图表（基于 pyqtgraph）
- 支持缩放、平移、双光标测量
- 支持多信号叠加显示
- 动态加载不同分辨率数据

技术选型：
- pyqtgraph.PlotWidget：纯 Qt 实现，高性能
- 原生支持大数据量（百万点）
- 内置缩放、平移、光标功能

使用示例：
    from presentation.panels.simulation.waveform_widget import WaveformWidget
    
    widget = WaveformWidget()
    widget.load_waveform(result, "V(out)")
    widget.add_waveform(result, "V(in)")
    
    # 设置测量光标
    widget.set_cursor_a(0.001)
    widget.set_cursor_b(0.002)
    
    # 获取测量结果
    measurement = widget.get_measurement()
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPen
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QToolBar,
    QToolButton,
    QLabel,
    QComboBox,
    QCheckBox,
    QFrame,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QScrollArea,
    QPushButton,
)

import pyqtgraph as pg
import numpy as np

from domain.simulation.data.waveform_data_service import (
    WaveformDataService,
    WaveformData,
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
    FONT_SIZE_SMALL,
    SPACING_SMALL,
    SPACING_NORMAL,
)


# ============================================================
# 常量定义
# ============================================================

# 信号颜色列表（用于多信号显示）
SIGNAL_COLORS = [
    "#1f77b4",  # 蓝色
    "#ff7f0e",  # 橙色
    "#2ca02c",  # 绿色
    "#d62728",  # 红色
    "#9467bd",  # 紫色
    "#8c564b",  # 棕色
    "#e377c2",  # 粉色
    "#7f7f7f",  # 灰色
    "#bcbd22",  # 黄绿色
    "#17becf",  # 青色
]

# 光标颜色
CURSOR_A_COLOR = "#ff0000"  # 红色
CURSOR_B_COLOR = "#00ff00"  # 绿色

# 初始加载点数
INITIAL_POINTS = 500

# 缩放时加载点数
VIEWPORT_POINTS = 1000

# 防抖延迟（毫秒）
DEBOUNCE_DELAY_MS = 100


# ============================================================
# 数据类定义
# ============================================================

@dataclass
class WaveformMeasurement:
    """
    波形测量结果
    
    Attributes:
        cursor_a_x: 光标 A 的 X 位置
        cursor_a_y: 光标 A 的 Y 值（第一个信号）
        cursor_b_x: 光标 B 的 X 位置
        cursor_b_y: 光标 B 的 Y 值（第一个信号）
        delta_x: X 差值
        delta_y: Y 差值
        slope: 斜率
        frequency: 频率（1/delta_x）
        signal_values_a: 光标 A 处各信号的 Y 值
        signal_values_b: 光标 B 处各信号的 Y 值
    """
    cursor_a_x: Optional[float] = None
    cursor_a_y: Optional[float] = None
    cursor_b_x: Optional[float] = None
    cursor_b_y: Optional[float] = None
    delta_x: Optional[float] = None
    delta_y: Optional[float] = None
    slope: Optional[float] = None
    frequency: Optional[float] = None
    signal_values_a: Optional[Dict[str, float]] = None
    signal_values_b: Optional[Dict[str, float]] = None
    
    def has_dual_cursor(self) -> bool:
        """是否有双光标数据"""
        return self.cursor_a_x is not None and self.cursor_b_x is not None


@dataclass
class PlotItem:
    """绘图项数据"""
    signal_name: str
    plot_data_item: pg.PlotDataItem
    color: str
    waveform_data: Optional[WaveformData] = None
    axis: str = "left"  # "left" (电压) 或 "right" (电流)


# ============================================================
# WaveformWidget - 波形图表组件
# ============================================================

class WaveformWidget(QWidget):
    """
    交互式波形图表组件
    
    基于 pyqtgraph 实现，支持：
    - 高性能波形渲染（百万点）
    - 鼠标缩放和平移
    - 双光标测量
    - 多信号叠加显示
    - 动态分辨率加载
    
    Signals:
        measurement_changed: 测量结果变化时发出
        viewport_changed: 视口范围变化时发出
        signal_selected: 信号选择变化时发出
    """
    
    measurement_changed = pyqtSignal(object)  # WaveformMeasurement
    viewport_changed = pyqtSignal(float, float, float, float)  # x_min, x_max, y_min, y_max
    signal_selected = pyqtSignal(str)  # signal_name
    displayed_signals_changed = pyqtSignal(list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # 数据服务
        self._data_service: WaveformDataService = waveform_data_service
        
        # 当前仿真结果
        self._current_result: Optional[SimulationResult] = None
        self._current_result_signature: Optional[Tuple[str, str, str]] = None
        
        # 绘图项字典：signal_name -> PlotItem
        self._plot_items: Dict[str, PlotItem] = {}
        
        # 颜色索引
        self._color_index: int = 0
        
        # 光标
        self._cursor_a: Optional[pg.InfiniteLine] = None
        self._cursor_b: Optional[pg.InfiniteLine] = None
        self._cursor_a_pos: Optional[float] = None
        self._cursor_b_pos: Optional[float] = None
        
        # 右侧 Y 轴 ViewBox（电流）
        self._right_vb: Optional[pg.ViewBox] = None
        
        # 信号类型缓存
        self._signal_types: Dict[str, str] = {}
        
        # 信号树更新锁（防止递归触发）
        self._updating_tree = False
        
        # 防抖定时器
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._on_debounced_range_change)
        self._pending_range: Optional[Tuple[float, float]] = None
        
        # 初始化 UI
        self._setup_ui()
        self._setup_plot()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI 组件"""
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 主分栏：左侧信号树 + 右侧图表
        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter.setHandleWidth(1)
        self._main_splitter.setChildrenCollapsible(True)
        
        # ---- 左侧：信号选择树 ----
        self._signal_panel = QFrame()
        self._signal_panel.setObjectName("signalPanel")
        signal_panel_layout = QVBoxLayout(self._signal_panel)
        signal_panel_layout.setContentsMargins(0, 0, 0, 0)
        signal_panel_layout.setSpacing(0)
        
        # 信号树标题栏
        signal_header = QFrame()
        signal_header.setObjectName("signalHeader")
        header_layout = QHBoxLayout(signal_header)
        header_layout.setContentsMargins(SPACING_SMALL, SPACING_SMALL, SPACING_SMALL, SPACING_SMALL)
        self._signal_title_label = QLabel("Signals")
        self._signal_title_label.setObjectName("signalTitle")
        header_layout.addWidget(self._signal_title_label)
        header_layout.addStretch()
        
        self._clear_all_btn = QPushButton("Clear")
        self._clear_all_btn.setObjectName("clearAllBtn")
        self._clear_all_btn.setFixedHeight(22)
        self._clear_all_btn.setToolTip("Remove all signals from chart")
        self._clear_all_btn.clicked.connect(self._on_clear_all_signals)
        header_layout.addWidget(self._clear_all_btn)
        signal_panel_layout.addWidget(signal_header)
        
        # 信号树（分类 + 复选框）
        self._signal_tree = QTreeWidget()
        self._signal_tree.setObjectName("signalTree")
        self._signal_tree.setHeaderHidden(True)
        self._signal_tree.setRootIsDecorated(True)
        self._signal_tree.setIndentation(16)
        self._signal_tree.itemChanged.connect(self._on_signal_item_changed)
        signal_panel_layout.addWidget(self._signal_tree)
        
        self._main_splitter.addWidget(self._signal_panel)
        
        # ---- 右侧：工具栏 + 图表 + 测量栏 ----
        right_panel = QFrame()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        
        # 工具栏
        self._toolbar = QFrame()
        self._toolbar.setObjectName("waveformToolbar")
        toolbar_layout = QHBoxLayout(self._toolbar)
        toolbar_layout.setContentsMargins(SPACING_SMALL, SPACING_SMALL, SPACING_SMALL, SPACING_SMALL)
        toolbar_layout.setSpacing(SPACING_SMALL)
        
        # 显示选项
        self._grid_checkbox = QCheckBox("Grid")
        self._grid_checkbox.setChecked(True)
        self._grid_checkbox.stateChanged.connect(self._on_grid_changed)
        toolbar_layout.addWidget(self._grid_checkbox)
        
        self._legend_checkbox = QCheckBox("Legend")
        self._legend_checkbox.setChecked(True)
        self._legend_checkbox.stateChanged.connect(self._on_legend_changed)
        toolbar_layout.addWidget(self._legend_checkbox)
        
        toolbar_layout.addSpacing(SPACING_NORMAL)
        
        # 光标按钮
        self._cursor_a_btn = QToolButton()
        self._cursor_a_btn.setText("A")
        self._cursor_a_btn.setCheckable(True)
        self._cursor_a_btn.setToolTip("Toggle Cursor A")
        self._cursor_a_btn.clicked.connect(self._on_toggle_cursor_a)
        toolbar_layout.addWidget(self._cursor_a_btn)
        
        self._cursor_b_btn = QToolButton()
        self._cursor_b_btn.setText("B")
        self._cursor_b_btn.setCheckable(True)
        self._cursor_b_btn.setToolTip("Toggle Cursor B")
        self._cursor_b_btn.clicked.connect(self._on_toggle_cursor_b)
        toolbar_layout.addWidget(self._cursor_b_btn)
        
        toolbar_layout.addSpacing(SPACING_NORMAL)
        
        # 自动缩放按钮
        self._auto_range_btn = QToolButton()
        self._auto_range_btn.setText("Auto")
        self._auto_range_btn.setToolTip("Auto Range")
        self._auto_range_btn.clicked.connect(self._on_auto_range)
        toolbar_layout.addWidget(self._auto_range_btn)
        
        toolbar_layout.addStretch()
        
        right_layout.addWidget(self._toolbar)
        
        # 图表区域
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setBackground(COLOR_BG_PRIMARY)
        right_layout.addWidget(self._plot_widget, 1)
        
        # 测量信息栏
        self._measurement_bar = QFrame()
        self._measurement_bar.setObjectName("measurementBar")
        measurement_layout = QVBoxLayout(self._measurement_bar)
        measurement_layout.setContentsMargins(SPACING_SMALL, SPACING_SMALL, SPACING_SMALL, SPACING_SMALL)
        measurement_layout.setSpacing(2)
        
        # 第一行：光标位置和差值
        cursor_row = QHBoxLayout()
        self._cursor_a_label = QLabel("A: --")
        self._cursor_b_label = QLabel("B: --")
        self._delta_label = QLabel("Δ: --")
        self._freq_label = QLabel("f: --")
        cursor_row.addWidget(self._cursor_a_label)
        cursor_row.addWidget(self._cursor_b_label)
        cursor_row.addWidget(self._delta_label)
        cursor_row.addWidget(self._freq_label)
        cursor_row.addStretch()
        measurement_layout.addLayout(cursor_row)
        
        # 第二行：各信号在光标处的 Y 值
        self._signal_values_label = QLabel("")
        self._signal_values_label.setObjectName("signalValuesLabel")
        self._signal_values_label.setWordWrap(True)
        measurement_layout.addWidget(self._signal_values_label)
        
        right_layout.addWidget(self._measurement_bar)
        self._measurement_bar.hide()
        
        self._main_splitter.addWidget(right_panel)
        
        # 设置初始比例：信号树 20% / 图表 80%
        self._main_splitter.setSizes([160, 640])
        
        main_layout.addWidget(self._main_splitter, 1)
    
    def _setup_plot(self):
        """设置图表（双 Y 轴：左=电压，右=电流）"""
        plot_item = self._plot_widget.getPlotItem()
        
        # 左侧 Y 轴：电压
        plot_item.setLabel('left', 'Voltage (V)')
        plot_item.setLabel('bottom', 'Time (s)')
        
        # 右侧 Y 轴：电流 —— 使用独立 ViewBox
        plot_item.showAxis('right')
        plot_item.getAxis('right').setLabel('Current (A)')
        
        self._right_vb = pg.ViewBox()
        plot_item.scene().addItem(self._right_vb)
        plot_item.getAxis('right').linkToView(self._right_vb)
        self._right_vb.setXLink(plot_item)
        
        # 当主视图几何变化时同步右侧 ViewBox
        plot_item.vb.sigResized.connect(self._sync_right_viewbox)
        
        # 启用网格
        plot_item.showGrid(x=True, y=True, alpha=0.3)
        
        # 启用自动范围
        plot_item.enableAutoRange()
        
        # 连接范围变化信号
        plot_item.sigRangeChanged.connect(self._on_range_changed)
        
        # 创建图例
        self._legend = plot_item.addLegend()
    
    def _sync_right_viewbox(self):
        """同步右侧 ViewBox 的几何与主视图一致"""
        if self._right_vb is not None:
            self._right_vb.setGeometry(
                self._plot_widget.getPlotItem().vb.sceneBoundingRect()
            )
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #signalPanel {{
                background-color: {COLOR_BG_SECONDARY};
                border-right: 1px solid {COLOR_BORDER};
            }}
            
            #signalHeader {{
                background-color: {COLOR_BG_TERTIARY};
                border-bottom: 1px solid {COLOR_BORDER};
            }}
            
            #signalTitle {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_SMALL}px;
                font-weight: bold;
            }}
            
            #clearAllBtn {{
                background-color: transparent;
                color: {COLOR_TEXT_SECONDARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: 3px;
                padding: 1px 6px;
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #clearAllBtn:hover {{
                background-color: {COLOR_BG_PRIMARY};
                color: {COLOR_TEXT_PRIMARY};
            }}
            
            #signalTree {{
                background-color: {COLOR_BG_SECONDARY};
                color: {COLOR_TEXT_PRIMARY};
                border: none;
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #signalTree::item {{
                padding: 2px 0px;
            }}
            
            #signalTree::item:hover {{
                background-color: {COLOR_BG_TERTIARY};
            }}
            
            #waveformToolbar {{
                background-color: {COLOR_BG_TERTIARY};
                border-bottom: 1px solid {COLOR_BORDER};
            }}
            
            #waveformToolbar QLabel {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #waveformToolbar QCheckBox {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #waveformToolbar QToolButton {{
                background-color: {COLOR_BG_SECONDARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                padding: 2px 8px;
                min-width: 24px;
            }}
            
            #waveformToolbar QToolButton:checked {{
                background-color: {COLOR_ACCENT};
                color: white;
            }}
            
            #waveformToolbar QToolButton:hover {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #measurementBar {{
                background-color: {COLOR_BG_TERTIARY};
                border-top: 1px solid {COLOR_BORDER};
            }}
            
            #measurementBar QLabel {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_SMALL}px;
                font-family: monospace;
            }}
            
            #signalValuesLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
                font-family: monospace;
            }}
        """)
    
    # ============================================================
    # 公共方法
    # ============================================================
    
    def load_waveform(
        self,
        result: SimulationResult,
        signal_name: str,
        clear_existing: bool = True
    ) -> bool:
        """
        加载波形数据
        
        Args:
            result: 仿真结果对象
            signal_name: 信号名称
            clear_existing: 是否清除现有波形
            
        Returns:
            bool: 是否加载成功
        """
        result_signature = self._get_result_signature(result)

        if result_signature != self._current_result_signature:
            self._clear_displayed_waveforms(preserve_result_context=True)
            self._set_result_context(result)
        elif self._current_result is None:
            self._set_result_context(result)
        elif clear_existing:
            self._clear_displayed_waveforms(preserve_result_context=True)

        return self.add_waveform(self._current_result, signal_name)
    
    def add_waveform(
        self,
        result: SimulationResult,
        signal_name: str
    ) -> bool:
        """
        添加波形（叠加显示）
        
        根据信号类型自动路由到左轴（电压）或右轴（电流）。
        
        Args:
            result: 仿真结果对象
            signal_name: 信号名称
            
        Returns:
            bool: 是否添加成功
        """
        result_signature = self._get_result_signature(result)
        if result_signature != self._current_result_signature:
            self._clear_displayed_waveforms(preserve_result_context=True)
            self._set_result_context(result)

        if signal_name in self._plot_items:
            self._logger.debug(f"Signal already displayed: {signal_name}")
            return True
        
        waveform_data = self._get_display_waveform_data(result, signal_name)
        
        if waveform_data is None:
            self._logger.warning(f"Failed to load waveform: {signal_name}")
            return False
        
        # 选择颜色
        color = SIGNAL_COLORS[self._color_index % len(SIGNAL_COLORS)]
        self._color_index += 1
        
        # 判断信号类型，决定绘制到左轴还是右轴
        sig_type = WaveformDataService.get_signal_type(signal_name, self._signal_types)
        use_right = (sig_type == "current")
        
        pen = pg.mkPen(color=color, width=1)
        plot_data_item = pg.PlotDataItem(
            waveform_data.x_data,
            waveform_data.y_data,
            pen=pen,
            name=signal_name
        )
        
        if use_right and self._right_vb is not None:
            self._right_vb.addItem(plot_data_item)
            axis_label = "right"
        else:
            self._plot_widget.getPlotItem().addItem(plot_data_item)
            axis_label = "left"
        
        # 保存绘图项
        self._plot_items[signal_name] = PlotItem(
            signal_name=signal_name,
            plot_data_item=plot_data_item,
            color=color,
            waveform_data=waveform_data,
            axis=axis_label
        )
        
        # 同步信号树复选框状态
        self._set_signal_tree_checked(signal_name, True)
        self._refresh_legend()
        self._update_measurement()
        self.displayed_signals_changed.emit(self.get_displayed_signals())
        
        # 自动调整右侧 ViewBox 范围
        if use_right and self._right_vb is not None:
            self._right_vb.autoRange()
        
        self._logger.debug(
            f"Waveform added: {signal_name} [{axis_label}], "
            f"points={waveform_data.point_count}"
        )
        return True
    
    def remove_waveform(self, signal_name: str) -> bool:
        """
        移除波形
        
        Args:
            signal_name: 信号名称
            
        Returns:
            bool: 是否移除成功
        """
        if signal_name not in self._plot_items:
            return False
        
        plot_item = self._plot_items.pop(signal_name)
        
        # 根据轴位置从对应的 ViewBox 移除
        if plot_item.axis == "right" and self._right_vb is not None:
            self._right_vb.removeItem(plot_item.plot_data_item)
        else:
            self._plot_widget.getPlotItem().removeItem(plot_item.plot_data_item)
        
        # 同步信号树复选框状态
        self._set_signal_tree_checked(signal_name, False)
        self._refresh_legend()
        self._update_measurement()
        if not self._plot_items:
            self._color_index = 0
        self.displayed_signals_changed.emit(self.get_displayed_signals())
        
        self._logger.debug(f"Waveform removed: {signal_name}")
        return True
    
    def clear_waveforms(self):
        """清空所有波形"""
        self._clear_displayed_waveforms(preserve_result_context=False)
    
    def set_cursor_a(self, x_position: float):
        """
        设置光标 A 位置
        
        Args:
            x_position: X 轴位置
        """
        if self._cursor_a is None:
            self._create_cursor_a()
        
        self._cursor_a.setValue(x_position)
        self._cursor_a_pos = x_position
        self._cursor_a_btn.setChecked(True)
        self._update_measurement()
    
    def set_cursor_b(self, x_position: float):
        """
        设置光标 B 位置
        
        Args:
            x_position: X 轴位置
        """
        if self._cursor_b is None:
            self._create_cursor_b()
        
        self._cursor_b.setValue(x_position)
        self._cursor_b_pos = x_position
        self._cursor_b_btn.setChecked(True)
        self._update_measurement()
    
    def get_measurement(self) -> WaveformMeasurement:
        """
        获取测量结果（包含所有信号在光标处的 Y 值）
        
        Returns:
            WaveformMeasurement: 测量结果
        """
        measurement = WaveformMeasurement()
        
        if self._cursor_a_pos is not None:
            measurement.cursor_a_x = self._cursor_a_pos
            all_y_a = self._get_all_y_at_x(self._cursor_a_pos)
            measurement.signal_values_a = all_y_a
            if all_y_a:
                measurement.cursor_a_y = next(iter(all_y_a.values()))
        
        if self._cursor_b_pos is not None:
            measurement.cursor_b_x = self._cursor_b_pos
            all_y_b = self._get_all_y_at_x(self._cursor_b_pos)
            measurement.signal_values_b = all_y_b
            if all_y_b:
                measurement.cursor_b_y = next(iter(all_y_b.values()))
        
        if measurement.cursor_a_x is not None and measurement.cursor_b_x is not None:
            measurement.delta_x = measurement.cursor_b_x - measurement.cursor_a_x
            
            if measurement.cursor_a_y is not None and measurement.cursor_b_y is not None:
                measurement.delta_y = measurement.cursor_b_y - measurement.cursor_a_y
                
                if measurement.delta_x != 0:
                    measurement.slope = measurement.delta_y / measurement.delta_x
                    measurement.frequency = 1.0 / abs(measurement.delta_x)
        
        return measurement
    
    def export_image(self, path: str) -> bool:
        """
        导出图表图片
        
        Args:
            path: 导出路径
            
        Returns:
            bool: 是否成功
        """
        try:
            from pyqtgraph.exporters import ImageExporter
            
            exporter = ImageExporter(self._plot_widget.getPlotItem())
            exporter.export(path)
            
            self._logger.info(f"Waveform exported: {path}")
            return True
        except Exception as e:
            self._logger.error(f"Failed to export waveform: {e}")
            return False
    
    def get_displayed_signals(self) -> List[str]:
        """获取当前显示的信号列表"""
        return list(self._plot_items.keys())
    
    def auto_range(self):
        """自动调整范围（包括右侧电流轴）"""
        self._plot_widget.getPlotItem().autoRange()
        if self._right_vb is not None:
            self._right_vb.autoRange()

    def _get_result_signature(self, result: Optional[SimulationResult]) -> Optional[Tuple[str, str, str]]:
        if result is None:
            return None
        return (
            getattr(result, 'file_path', '') or '',
            getattr(result, 'timestamp', '') or '',
            getattr(result, 'analysis_type', '') or '',
        )

    def _set_result_context(self, result: SimulationResult):
        self._current_result = result
        self._current_result_signature = self._get_result_signature(result)
        self._signal_types = getattr(result.data, 'signal_types', {}) if result.data is not None else {}
        self._update_signal_tree(result)
        x_label = self._data_service.get_x_axis_label(result)
        self._plot_widget.getPlotItem().setLabel('bottom', x_label)

    def _clear_displayed_waveforms(self, preserve_result_context: bool):
        for plot_item in list(self._plot_items.values()):
            if plot_item.axis == "right" and self._right_vb is not None:
                self._right_vb.removeItem(plot_item.plot_data_item)
            else:
                self._plot_widget.getPlotItem().removeItem(plot_item.plot_data_item)

        self._plot_items.clear()
        self._color_index = 0
        self._pending_range = None
        self._refresh_legend()
        self._signal_values_label.setText("")
        self._remove_cursor_a()
        self._remove_cursor_b()

        if preserve_result_context and self._current_result is not None:
            self._update_signal_tree(self._current_result)
        else:
            self._current_result = None
            self._current_result_signature = None
            self._signal_types = {}
            self._signal_tree.clear()

        self.displayed_signals_changed.emit(self.get_displayed_signals())

    def _get_display_waveform_data(self, result: SimulationResult, signal_name: str) -> Optional[WaveformData]:
        x_range = self._pending_range
        if x_range is None:
            try:
                view_range = self._plot_widget.getPlotItem().viewRange()
                if view_range and view_range[0]:
                    x_range = (view_range[0][0], view_range[0][1])
            except Exception:
                x_range = None

        if self._plot_items and x_range is not None:
            x_min, x_max = x_range
            if np.isfinite(x_min) and np.isfinite(x_max) and x_max > x_min:
                waveform_data = self._data_service.get_viewport_data(
                    result,
                    signal_name,
                    x_min,
                    x_max,
                    target_points=VIEWPORT_POINTS
                )
                if waveform_data is not None:
                    return waveform_data

        return self._data_service.get_initial_data(
            result,
            signal_name,
            target_points=INITIAL_POINTS
        )

    def _refresh_legend(self):
        if self._legend is None:
            return

        try:
            self._legend.clear()
        except Exception:
            return

        if not self._legend_checkbox.isChecked():
            return

        for signal_name, plot_item in self._plot_items.items():
            self._legend.addItem(plot_item.plot_data_item, signal_name)

    
    # ============================================================
    # 内部方法 - 光标管理
    # ============================================================
    
    def _create_cursor_a(self):
        """创建光标 A"""
        if self._cursor_a is not None:
            return
        
        pen = pg.mkPen(color=CURSOR_A_COLOR, width=1, style=Qt.PenStyle.DashLine)
        self._cursor_a = pg.InfiniteLine(
            pos=0,
            angle=90,
            pen=pen,
            movable=True,
            label='A',
            labelOpts={'color': CURSOR_A_COLOR, 'position': 0.95}
        )
        self._cursor_a.sigPositionChanged.connect(self._on_cursor_a_moved)
        self._plot_widget.addItem(self._cursor_a)
        self._measurement_bar.show()
    
    def _create_cursor_b(self):
        """创建光标 B"""
        if self._cursor_b is not None:
            return
        
        pen = pg.mkPen(color=CURSOR_B_COLOR, width=1, style=Qt.PenStyle.DashLine)
        self._cursor_b = pg.InfiniteLine(
            pos=0,
            angle=90,
            pen=pen,
            movable=True,
            label='B',
            labelOpts={'color': CURSOR_B_COLOR, 'position': 0.90}
        )
        self._cursor_b.sigPositionChanged.connect(self._on_cursor_b_moved)
        self._plot_widget.addItem(self._cursor_b)
        self._measurement_bar.show()
    
    def _remove_cursor_a(self):
        """移除光标 A"""
        if self._cursor_a is not None:
            self._plot_widget.removeItem(self._cursor_a)
            self._cursor_a = None
            self._cursor_a_pos = None
            self._cursor_a_btn.setChecked(False)
            self._update_measurement()
            self._check_hide_measurement_bar()
    
    def _remove_cursor_b(self):
        """移除光标 B"""
        if self._cursor_b is not None:
            self._plot_widget.removeItem(self._cursor_b)
            self._cursor_b = None
            self._cursor_b_pos = None
            self._cursor_b_btn.setChecked(False)
            self._update_measurement()
            self._check_hide_measurement_bar()
    
    def _check_hide_measurement_bar(self):
        """检查是否需要隐藏测量栏"""
        if self._cursor_a is None and self._cursor_b is None:
            self._measurement_bar.hide()
    
    def _on_cursor_a_moved(self, line):
        """光标 A 移动事件"""
        self._cursor_a_pos = line.value()
        self._update_measurement()
    
    def _on_cursor_b_moved(self, line):
        """光标 B 移动事件"""
        self._cursor_b_pos = line.value()
        self._update_measurement()
    
    def _get_all_y_at_x(self, x: float) -> Dict[str, float]:
        """
        获取指定 X 位置处所有显示信号的 Y 值
        
        使用线性插值获取精确值。
        
        Returns:
            Dict[str, float]: {signal_name: y_value}
        """
        result: Dict[str, float] = {}
        for name, item in self._plot_items.items():
            if item.waveform_data is None:
                continue
            x_data = item.waveform_data.x_data
            y_data = item.waveform_data.y_data
            if len(x_data) == 0:
                continue
            try:
                result[name] = float(np.interp(x, x_data, y_data))
            except Exception:
                pass
        return result
    
    def _update_measurement(self):
        """更新测量显示（包括所有信号在光标处的 Y 值）"""
        measurement = self.get_measurement()
        
        # 更新第一行：光标位置和差值
        if measurement.cursor_a_x is not None:
            y_str = f"{measurement.cursor_a_y:.4g}" if measurement.cursor_a_y is not None else "--"
            self._cursor_a_label.setText(f"A: {measurement.cursor_a_x:.4g}, {y_str}")
        else:
            self._cursor_a_label.setText("A: --")
        
        if measurement.cursor_b_x is not None:
            y_str = f"{measurement.cursor_b_y:.4g}" if measurement.cursor_b_y is not None else "--"
            self._cursor_b_label.setText(f"B: {measurement.cursor_b_x:.4g}, {y_str}")
        else:
            self._cursor_b_label.setText("B: --")
        
        if measurement.delta_x is not None:
            delta_y_str = f"{measurement.delta_y:.4g}" if measurement.delta_y is not None else "--"
            self._delta_label.setText(f"Δ: {measurement.delta_x:.4g}, {delta_y_str}")
        else:
            self._delta_label.setText("Δ: --")
        
        if measurement.frequency is not None:
            self._freq_label.setText(f"f: {measurement.frequency:.4g} Hz")
        else:
            self._freq_label.setText("f: --")
        
        # 更新第二行：各信号在光标处的 Y 值
        value_parts = []
        vals_a = measurement.signal_values_a or {}
        vals_b = measurement.signal_values_b or {}
        for name in self._plot_items:
            color = self._plot_items[name].color
            a_val = f"{vals_a[name]:.4g}" if name in vals_a else "--"
            if vals_b:
                b_val = f"{vals_b[name]:.4g}" if name in vals_b else "--"
                value_parts.append(f'<span style="color:{color}">{name}: A={a_val}  B={b_val}</span>')
            else:
                value_parts.append(f'<span style="color:{color}">{name}: {a_val}</span>')
        self._signal_values_label.setText("  |  ".join(value_parts))
        
        # 发出信号
        self.measurement_changed.emit(measurement)
    
    # ============================================================
    # 内部方法 - 事件处理
    # ============================================================
    
    def _on_signal_item_changed(self, item: QTreeWidgetItem, column: int):
        """信号树复选框变化 —— 勾选添加信号，取消勾选移除信号"""
        if self._updating_tree:
            return
        if item.childCount() > 0:
            return  # 忽略分类根节点
        
        signal_name = item.text(0)
        if self._current_result is None:
            return
        
        checked = item.checkState(0) == Qt.CheckState.Checked
        if checked:
            if signal_name not in self._plot_items:
                self.add_waveform(self._current_result, signal_name)
            self.signal_selected.emit(signal_name)
        else:
            if signal_name in self._plot_items:
                self.remove_waveform(signal_name)
    
    def _on_clear_all_signals(self):
        """清除所有已显示的信号（保留信号树）"""
        self._clear_displayed_waveforms(preserve_result_context=True)
    
    def _on_grid_changed(self, state: int):
        """网格显示变化"""
        show = state == Qt.CheckState.Checked.value
        self._plot_widget.getPlotItem().showGrid(x=show, y=show, alpha=0.3)
    
    def _on_legend_changed(self, state: int):
        """图例显示变化"""
        if state == Qt.CheckState.Checked.value:
            if self._legend is None:
                self._legend = self._plot_widget.getPlotItem().addLegend()
            self._refresh_legend()
        else:
            if self._legend is not None:
                self._legend.clear()
    
    def _on_toggle_cursor_a(self, checked: bool):
        """切换光标 A"""
        if checked:
            # 在视口中心创建光标
            view_range = self._plot_widget.getPlotItem().viewRange()
            x_center = (view_range[0][0] + view_range[0][1]) / 2
            self.set_cursor_a(x_center)
        else:
            self._remove_cursor_a()
    
    def _on_toggle_cursor_b(self, checked: bool):
        """切换光标 B"""
        if checked:
            # 在视口中心偏右创建光标
            view_range = self._plot_widget.getPlotItem().viewRange()
            x_center = (view_range[0][0] + view_range[0][1]) / 2
            x_offset = (view_range[0][1] - view_range[0][0]) * 0.1
            self.set_cursor_b(x_center + x_offset)
        else:
            self._remove_cursor_b()
    
    def _on_auto_range(self):
        """自动范围按钮"""
        self.auto_range()
    
    def _on_range_changed(self, view_box, ranges):
        """视口范围变化（带防抖）"""
        x_range = ranges[0]
        self._pending_range = (x_range[0], x_range[1])
        
        # 重启防抖定时器
        self._debounce_timer.start(DEBOUNCE_DELAY_MS)
    
    def _on_debounced_range_change(self):
        """防抖后的范围变化处理"""
        if self._pending_range is None or self._current_result is None:
            return
        
        x_min, x_max = self._pending_range
        self._pending_range = None
        
        # 更新所有信号的数据
        for signal_name, plot_item in self._plot_items.items():
            waveform_data = self._data_service.get_viewport_data(
                self._current_result,
                signal_name,
                x_min,
                x_max,
                target_points=VIEWPORT_POINTS
            )
            
            if waveform_data is not None:
                plot_item.plot_data_item.setData(
                    waveform_data.x_data,
                    waveform_data.y_data
                )
                plot_item.waveform_data = waveform_data

        self._update_measurement()
        
        # 发出视口变化信号
        view_range = self._plot_widget.getPlotItem().viewRange()
        self.viewport_changed.emit(
            view_range[0][0], view_range[0][1],
            view_range[1][0], view_range[1][1]
        )
    
    def _update_signal_tree(self, result: SimulationResult):
        """更新信号树（分类显示：电压 / 电流 / 其他）"""
        self._updating_tree = True
        self._signal_tree.clear()
        
        classified = self._data_service.get_classified_signals(result)
        
        category_labels = {
            "voltage": "\u26a1 Voltage",
            "current": "\U0001f50c Current",
            "other": "\u2699 Other",
        }
        
        for cat_key in ("voltage", "current", "other"):
            signals = classified.get(cat_key, [])
            if not signals:
                continue
            
            root = QTreeWidgetItem(self._signal_tree, [category_labels[cat_key]])
            root.setFlags(root.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            root.setExpanded(True)
            
            for sig_name in signals:
                child = QTreeWidgetItem(root, [sig_name])
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                is_displayed = sig_name in self._plot_items
                child.setCheckState(
                    0,
                    Qt.CheckState.Checked if is_displayed else Qt.CheckState.Unchecked
                )
        
        self._updating_tree = False
    
    def _set_signal_tree_checked(self, signal_name: str, checked: bool):
        """同步信号树中某个信号的复选框状态"""
        self._updating_tree = True
        root = self._signal_tree.invisibleRootItem()
        for i in range(root.childCount()):
            category = root.child(i)
            for j in range(category.childCount()):
                child = category.child(j)
                if child.text(0) == signal_name:
                    child.setCheckState(
                        0,
                        Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                    )
                    self._updating_tree = False
                    return
        self._updating_tree = False
    
    # ============================================================
    # 国际化支持
    # ============================================================
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._signal_title_label.setText(self._tr("Signals"))
        self._clear_all_btn.setText(self._tr("Clear"))
        self._grid_checkbox.setText(self._tr("Grid"))
        self._legend_checkbox.setText(self._tr("Legend"))
        self._cursor_a_btn.setToolTip(self._tr("Toggle Cursor A"))
        self._cursor_b_btn.setToolTip(self._tr("Toggle Cursor B"))
        self._auto_range_btn.setToolTip(self._tr("Auto Range"))
    
    def _tr(self, text: str) -> str:
        """翻译文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(f"waveform_widget.{text}", default=text)
        except ImportError:
            return text


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "WaveformWidget",
    "WaveformMeasurement",
]
