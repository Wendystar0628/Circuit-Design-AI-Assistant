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
    """
    cursor_a_x: Optional[float] = None
    cursor_a_y: Optional[float] = None
    cursor_b_x: Optional[float] = None
    cursor_b_y: Optional[float] = None
    delta_x: Optional[float] = None
    delta_y: Optional[float] = None
    slope: Optional[float] = None
    frequency: Optional[float] = None
    
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
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # 数据服务
        self._data_service: WaveformDataService = waveform_data_service
        
        # 当前仿真结果
        self._current_result: Optional[SimulationResult] = None
        
        # 绘图项字典：signal_name -> PlotItem
        self._plot_items: Dict[str, PlotItem] = {}
        
        # 颜色索引
        self._color_index: int = 0
        
        # 光标
        self._cursor_a: Optional[pg.InfiniteLine] = None
        self._cursor_b: Optional[pg.InfiniteLine] = None
        self._cursor_a_pos: Optional[float] = None
        self._cursor_b_pos: Optional[float] = None
        
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
        
        # 工具栏
        self._toolbar = QFrame()
        self._toolbar.setObjectName("waveformToolbar")
        toolbar_layout = QHBoxLayout(self._toolbar)
        toolbar_layout.setContentsMargins(SPACING_SMALL, SPACING_SMALL, SPACING_SMALL, SPACING_SMALL)
        toolbar_layout.setSpacing(SPACING_SMALL)
        
        # 信号选择下拉框
        self._signal_label = QLabel("Signal:")
        self._signal_combo = QComboBox()
        self._signal_combo.setMinimumWidth(120)
        self._signal_combo.currentTextChanged.connect(self._on_signal_selected)
        toolbar_layout.addWidget(self._signal_label)
        toolbar_layout.addWidget(self._signal_combo)
        
        toolbar_layout.addSpacing(SPACING_NORMAL)
        
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
        
        main_layout.addWidget(self._toolbar)
        
        # 图表区域
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setBackground(COLOR_BG_PRIMARY)
        main_layout.addWidget(self._plot_widget, 1)
        
        # 测量信息栏
        self._measurement_bar = QFrame()
        self._measurement_bar.setObjectName("measurementBar")
        measurement_layout = QHBoxLayout(self._measurement_bar)
        measurement_layout.setContentsMargins(SPACING_SMALL, SPACING_SMALL, SPACING_SMALL, SPACING_SMALL)
        measurement_layout.setSpacing(SPACING_NORMAL)
        
        self._cursor_a_label = QLabel("A: --")
        self._cursor_b_label = QLabel("B: --")
        self._delta_label = QLabel("Δ: --")
        self._freq_label = QLabel("f: --")
        
        measurement_layout.addWidget(self._cursor_a_label)
        measurement_layout.addWidget(self._cursor_b_label)
        measurement_layout.addWidget(self._delta_label)
        measurement_layout.addWidget(self._freq_label)
        measurement_layout.addStretch()
        
        main_layout.addWidget(self._measurement_bar)
        self._measurement_bar.hide()
    
    def _setup_plot(self):
        """设置图表"""
        plot_item = self._plot_widget.getPlotItem()
        
        # 设置标签
        plot_item.setLabel('left', 'Amplitude')
        plot_item.setLabel('bottom', 'Time (s)')
        
        # 启用网格
        plot_item.showGrid(x=True, y=True, alpha=0.3)
        
        # 启用自动范围
        plot_item.enableAutoRange()
        
        # 连接范围变化信号
        plot_item.sigRangeChanged.connect(self._on_range_changed)
        
        # 创建图例
        self._legend = plot_item.addLegend()
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #waveformToolbar {{
                background-color: {COLOR_BG_TERTIARY};
                border-bottom: 1px solid {COLOR_BORDER};
            }}
            
            #waveformToolbar QLabel {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #waveformToolbar QComboBox {{
                background-color: {COLOR_BG_SECONDARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                padding: 2px 6px;
                min-height: 20px;
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
        if clear_existing:
            self.clear_waveforms()
        
        self._current_result = result
        
        # 更新信号下拉框
        self._update_signal_combo(result)
        
        # 添加波形
        return self.add_waveform(result, signal_name)
    
    def add_waveform(
        self,
        result: SimulationResult,
        signal_name: str
    ) -> bool:
        """
        添加波形（叠加显示）
        
        Args:
            result: 仿真结果对象
            signal_name: 信号名称
            
        Returns:
            bool: 是否添加成功
        """
        if signal_name in self._plot_items:
            self._logger.debug(f"Signal already displayed: {signal_name}")
            return True
        
        # 获取初始数据（低分辨率）
        waveform_data = self._data_service.get_initial_data(
            result, signal_name, target_points=INITIAL_POINTS
        )
        
        if waveform_data is None:
            self._logger.warning(f"Failed to load waveform: {signal_name}")
            return False
        
        # 选择颜色
        color = SIGNAL_COLORS[self._color_index % len(SIGNAL_COLORS)]
        self._color_index += 1
        
        # 创建绘图项
        pen = pg.mkPen(color=color, width=1)
        plot_data_item = self._plot_widget.plot(
            waveform_data.x_data,
            waveform_data.y_data,
            pen=pen,
            name=signal_name
        )
        
        # 保存绘图项
        self._plot_items[signal_name] = PlotItem(
            signal_name=signal_name,
            plot_data_item=plot_data_item,
            color=color,
            waveform_data=waveform_data
        )
        
        # 更新 X 轴标签
        x_label = self._data_service.get_x_axis_label(result)
        self._plot_widget.getPlotItem().setLabel('bottom', x_label)
        
        self._logger.debug(f"Waveform added: {signal_name}, points={waveform_data.point_count}")
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
        self._plot_widget.removeItem(plot_item.plot_data_item)
        
        self._logger.debug(f"Waveform removed: {signal_name}")
        return True
    
    def clear_waveforms(self):
        """清空所有波形"""
        for signal_name in list(self._plot_items.keys()):
            self.remove_waveform(signal_name)
        
        self._color_index = 0
        self._current_result = None
        self._signal_combo.clear()
        
        # 清除光标
        self._remove_cursor_a()
        self._remove_cursor_b()
    
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
        获取测量结果
        
        Returns:
            WaveformMeasurement: 测量结果
        """
        measurement = WaveformMeasurement()
        
        if self._cursor_a_pos is not None:
            measurement.cursor_a_x = self._cursor_a_pos
            measurement.cursor_a_y = self._get_y_at_x(self._cursor_a_pos)
        
        if self._cursor_b_pos is not None:
            measurement.cursor_b_x = self._cursor_b_pos
            measurement.cursor_b_y = self._get_y_at_x(self._cursor_b_pos)
        
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
        """自动调整范围"""
        self._plot_widget.getPlotItem().autoRange()

    
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
    
    def _get_y_at_x(self, x: float) -> Optional[float]:
        """
        获取指定 X 位置的 Y 值（第一个信号）
        
        使用线性插值获取精确值。
        """
        if not self._plot_items:
            return None
        
        # 获取第一个信号的数据
        first_item = next(iter(self._plot_items.values()))
        waveform_data = first_item.waveform_data
        
        if waveform_data is None:
            return None
        
        x_data = waveform_data.x_data
        y_data = waveform_data.y_data
        
        if len(x_data) == 0:
            return None
        
        # 线性插值
        try:
            return float(np.interp(x, x_data, y_data))
        except Exception:
            return None
    
    def _update_measurement(self):
        """更新测量显示"""
        measurement = self.get_measurement()
        
        # 更新标签
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
        
        # 发出信号
        self.measurement_changed.emit(measurement)
    
    # ============================================================
    # 内部方法 - 事件处理
    # ============================================================
    
    def _on_signal_selected(self, signal_name: str):
        """信号选择变化"""
        if not signal_name or self._current_result is None:
            return
        
        # 如果信号未显示，则添加
        if signal_name not in self._plot_items:
            self.add_waveform(self._current_result, signal_name)
        
        self.signal_selected.emit(signal_name)
    
    def _on_grid_changed(self, state: int):
        """网格显示变化"""
        show = state == Qt.CheckState.Checked.value
        self._plot_widget.getPlotItem().showGrid(x=show, y=show, alpha=0.3)
    
    def _on_legend_changed(self, state: int):
        """图例显示变化"""
        if state == Qt.CheckState.Checked.value:
            if self._legend is None:
                self._legend = self._plot_widget.getPlotItem().addLegend()
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
        
        # 发出视口变化信号
        view_range = self._plot_widget.getPlotItem().viewRange()
        self.viewport_changed.emit(
            view_range[0][0], view_range[0][1],
            view_range[1][0], view_range[1][1]
        )
    
    def _update_signal_combo(self, result: SimulationResult):
        """更新信号下拉框"""
        self._signal_combo.blockSignals(True)
        self._signal_combo.clear()
        
        signals = self._data_service.get_available_signals(result)
        self._signal_combo.addItems(signals)
        
        self._signal_combo.blockSignals(False)
    
    # ============================================================
    # 国际化支持
    # ============================================================
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._signal_label.setText(self._tr("Signal:"))
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
