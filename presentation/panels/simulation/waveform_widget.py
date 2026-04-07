# WaveformWidget - Interactive Waveform Chart Component
"""
波形图表组件

职责：
- 渲染交互式波形图表（基于 pyqtgraph）
- 支持框选放大、Fit 全显示、双光标测量
- 支持多信号叠加显示
- 动态加载不同分辨率数据

技术选型：
- pyqtgraph.PlotWidget：纯 Qt 实现，高性能
- 原生支持大数据量（百万点）
- 配合自定义 ViewBox 提供 LTspice 风格交互

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
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QToolButton,
    QLabel,
    QCheckBox,
    QFrame,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QPushButton,
)

import numpy as np
import pyqtgraph as pg

from domain.simulation.data.waveform_data_service import (
    WaveformDataService,
    waveform_data_service,
)
from domain.simulation.models.simulation_result import SimulationResult
from presentation.panels.simulation.waveform_export_bundle_builder import waveform_export_bundle_builder
from presentation.panels.simulation.waveform_measurement_support import waveform_measurement_support
from presentation.panels.simulation.waveform_plot_types import (
    CURSOR_A_COLOR,
    CURSOR_B_COLOR,
    INITIAL_POINTS,
    VIEWPORT_POINTS,
    PlotItem,
    SIGNAL_COLORS,
    WaveformMeasurement,
)
from presentation.panels.simulation.waveform_viewport_manager import WaveformViewportManager
from presentation.panels.simulation.ltspice_plot_interaction import (
    LTSpiceViewBox,
    clamp_range,
)

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


# ============================================================
# 数据类定义
# ============================================================


# ============================================================
# WaveformWidget - 波形图表组件
# ============================================================

class WaveformWidget(QWidget):
    """
    交互式波形图表组件
    
    基于 pyqtgraph 实现，支持：
    - 高性能波形渲染（百万点）
    - 左键框选放大与 Fit
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
    add_to_conversation_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # 数据服务
        self._data_service: WaveformDataService = waveform_data_service
        self._measurement_support = waveform_measurement_support
        self._viewport_manager = WaveformViewportManager(self._data_service)
        
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
        self._x_domain: Optional[Tuple[float, float]] = None
        self._left_y_domain: Optional[Tuple[float, float]] = None
        self._right_y_domain: Optional[Tuple[float, float]] = None
        
        # 信号类型缓存
        self._signal_types: Dict[str, str] = {}
        
        # 信号树更新锁（防止递归触发）
        self._updating_tree = False
        
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
        
        # Fit 按钮
        self._fit_btn = QToolButton()
        self._fit_btn.setText("Fit")
        self._fit_btn.setToolTip("Fit")
        self._fit_btn.clicked.connect(self._on_fit_view)
        toolbar_layout.addWidget(self._fit_btn)

        self._add_to_conversation_btn = QToolButton()
        self._add_to_conversation_btn.setEnabled(False)
        self._add_to_conversation_btn.clicked.connect(self.add_to_conversation_clicked.emit)
        toolbar_layout.addWidget(self._add_to_conversation_btn)
        
        toolbar_layout.addStretch()
        
        right_layout.addWidget(self._toolbar)
        
        # 图表区域
        self._plot_widget = pg.PlotWidget(viewBox=LTSpiceViewBox())
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
        plot_item.setLabel('bottom', 'X')
        
        # 右侧 Y 轴：电流 —— 使用独立 ViewBox
        plot_item.showAxis('right')
        plot_item.getAxis('right').setLabel('Current (A)')
        
        self._right_vb = pg.ViewBox()
        plot_item.scene().addItem(self._right_vb)
        plot_item.getAxis('right').linkToView(self._right_vb)
        self._right_vb.setXLink(plot_item)
        self._right_vb.setMenuEnabled(False)
        self._right_vb.setMouseEnabled(x=False, y=False)
        
        # 当主视图几何变化时同步右侧 ViewBox
        plot_item.vb.sigResized.connect(self._sync_right_viewbox)
        
        # 启用网格
        plot_item.showGrid(x=True, y=True, alpha=0.3)

        plot_item.disableAutoRange()

        view_box = plot_item.vb
        if isinstance(view_box, LTSpiceViewBox):
            view_box.rect_selected.connect(self._on_rect_selected)
        
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
        
        waveform_data = self._data_service.get_initial_data(
            result,
            signal_name,
            target_points=INITIAL_POINTS,
        )
        
        if waveform_data is None:
            self._logger.warning(f"Failed to load waveform: {signal_name}")
            return False

        resolved_signal_name = waveform_data.signal_name
        if resolved_signal_name in self._plot_items:
            self._logger.debug(f"Signal already displayed: {resolved_signal_name}")
            self._update_add_to_conversation_enabled()
            return True
        
        # 选择颜色
        color = SIGNAL_COLORS[self._color_index % len(SIGNAL_COLORS)]
        self._color_index += 1
        
        # 判断信号类型，决定绘制到左轴还是右轴
        sig_type = WaveformDataService.get_signal_type(resolved_signal_name, self._signal_types)
        use_right = (sig_type == "current")
        
        pen = pg.mkPen(color=color, width=1.2, style=Qt.PenStyle.SolidLine)
        plot_data_item = pg.PlotDataItem(
            waveform_data.x_data,
            waveform_data.y_data,
            pen=pen,
            name=resolved_signal_name
        )
        
        if use_right and self._right_vb is not None:
            self._right_vb.addItem(plot_data_item)
            axis_label = "right"
        else:
            self._plot_widget.getPlotItem().addItem(plot_data_item)
            axis_label = "left"
        
        # 保存绘图项
        self._plot_items[resolved_signal_name] = PlotItem(
            plot_data_item=plot_data_item,
            color=color,
            waveform_data=waveform_data,
            axis=axis_label
        )
        
        # 同步信号树复选框状态
        self._set_signal_tree_checked(resolved_signal_name, True)
        self._refresh_legend()
        self.fit_to_view()
        
        self._logger.debug(
            f"Waveform added: {resolved_signal_name} [{axis_label}], "
            f"points={waveform_data.point_count}"
        )
        self._update_add_to_conversation_enabled()
        return True
    
    def remove_waveform(self, signal_name: str) -> bool:
        """
        移除波形
        
        Args:
            signal_name: 信号名称
            
        Returns:
            bool: 是否移除成功
        """
        if signal_name not in self._plot_items and self._current_result is not None:
            resolved_signal_name = self._data_service.resolve_signal_name(
                self._current_result,
                signal_name,
            )
            if resolved_signal_name is not None:
                signal_name = resolved_signal_name

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
        if not self._plot_items:
            self._color_index = 0
            self._x_domain = None
            self._left_y_domain = None
            self._right_y_domain = None
            self._update_measurement()
        else:
            self.fit_to_view()
        
        self._logger.debug(f"Waveform removed: {signal_name}")
        self._update_add_to_conversation_enabled()
        return True
    
    def clear_waveforms(self):
        """清空所有波形"""
        self._clear_displayed_waveforms(preserve_result_context=False)
        self._update_add_to_conversation_enabled()
    
    def set_cursor_a(self, x_position: float):
        """
        设置光标 A 位置
        
        Args:
            x_position: X 轴位置
        """
        if self._cursor_a is None:
            self._create_cursor_a()
        if self._x_domain is not None:
            x_position = min(max(x_position, self._x_domain[0]), self._x_domain[1])
        
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
        if self._x_domain is not None:
            x_position = min(max(x_position, self._x_domain[0]), self._x_domain[1])
        
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
        return self._measurement_support.build_measurement(
            self._current_result,
            self._plot_items,
            self._cursor_a_pos,
            self._cursor_b_pos,
            self._from_view_x_value,
        )

    def export_image(self, path: str) -> bool:
        if self._current_result is None or not self._plot_items:
            return False
        pixmap = self._plot_widget.grab()
        if pixmap.isNull():
            return False
        return pixmap.save(path)

    def export_bundle(self, output_dir: str) -> List[str]:
        if self._current_result is None:
            return []

        measurement = self.get_measurement()
        signal_names = self.get_displayed_signal_names()
        headers = [self._get_x_axis_label(), *signal_names]
        rows = waveform_export_bundle_builder.build_export_rows(
            self._plot_items,
            signal_names,
            self._get_x_axis_label(),
        )
        signal_payloads = waveform_export_bundle_builder.build_signal_payloads(self._plot_items)
        return waveform_export_bundle_builder.export_bundle(
            output_dir,
            self._current_result,
            signal_names,
            headers,
            rows,
            measurement,
            signal_payloads,
            self.export_image,
        )

    def get_displayed_signal_names(self) -> List[str]:
        return list(self._plot_items.keys())

    def _get_x_axis_label(self) -> str:
        if self._current_result is None:
            return "X"
        return self._current_result.get_x_axis_label()

    def fit_to_view(self):
        if self._current_result is None or not self._plot_items:
            return

        self._viewport_manager.reload_initial_data(
            self._current_result,
            self._plot_items,
            INITIAL_POINTS,
        )

        self._rebuild_domains()
        self._apply_full_viewport()
        self._update_measurement()

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
        self._x_domain = None
        self._left_y_domain = None
        self._right_y_domain = None
        self._update_signal_tree(result)
        x_label = result.get_x_axis_label()
        plot_item = self._plot_widget.getPlotItem()
        plot_item.setLabel('bottom', x_label)
        plot_item.setLogMode(x=result.is_x_axis_log(), y=False)
        self._update_add_to_conversation_enabled()

    def _clear_displayed_waveforms(self, preserve_result_context: bool):
        for plot_item in list(self._plot_items.values()):
            if plot_item.axis == "right" and self._right_vb is not None:
                self._right_vb.removeItem(plot_item.plot_data_item)
            else:
                self._plot_widget.getPlotItem().removeItem(plot_item.plot_data_item)

        self._plot_items.clear()
        self._color_index = 0
        self._x_domain = None
        self._left_y_domain = None
        self._right_y_domain = None
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
            self._plot_widget.getPlotItem().setLogMode(x=False, y=False)
        self._update_add_to_conversation_enabled()

    def _is_log_x_enabled(self) -> bool:
        return self._current_result is not None and self._current_result.is_x_axis_log()

    def _to_view_x_data(self, values: np.ndarray) -> np.ndarray:
        array = np.asarray(values, dtype=float)
        if not self._is_log_x_enabled():
            return array
        transformed = np.full(array.shape, np.nan, dtype=float)
        mask = np.isfinite(array) & (array > 0)
        transformed[mask] = np.log10(array[mask])
        return transformed

    def _from_view_x_value(self, value: float) -> float:
        if not self._is_log_x_enabled():
            return float(value)
        return float(10 ** value)

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

    def _rebuild_domains(self):
        self._x_domain, self._left_y_domain, self._right_y_domain = self._viewport_manager.rebuild_domains(
            self._current_result,
            self._plot_items,
            self._to_view_x_data,
        )

    def _apply_domain_limits(self):
        self._viewport_manager.apply_domain_limits(
            self._plot_widget,
            self._right_vb,
            self._x_domain,
            self._left_y_domain,
            self._right_y_domain,
        )

    def _apply_viewport(
        self,
        x_range: Optional[Tuple[float, float]],
        left_y_range: Optional[Tuple[float, float]],
        right_y_range: Optional[Tuple[float, float]],
    ):
        self._viewport_manager.apply_viewport(
            self._plot_widget,
            self._right_vb,
            x_range,
            left_y_range,
            right_y_range,
            log_x_enabled=self._is_log_x_enabled(),
        )

    def _apply_full_viewport(self):
        if self._x_domain is None:
            return

        self._apply_domain_limits()
        self._apply_viewport(self._x_domain, self._left_y_domain, self._right_y_domain)
        self._emit_viewport_changed()

    def _emit_viewport_changed(self):
        current_x = self._viewport_manager.get_current_view_x_range(self._plot_widget)
        current_left_y = self._viewport_manager.get_current_left_view_range(self._plot_widget)
        if current_x is None or current_left_y is None:
            return
        self.viewport_changed.emit(
            self._from_view_x_value(current_x[0]),
            self._from_view_x_value(current_x[1]),
            current_left_y[0],
            current_left_y[1],
        )

    def _on_rect_selected(
        self,
        requested_x_range: Tuple[float, float],
        requested_y_range: Tuple[float, float],
    ):
        if self._current_result is None or not self._plot_items or self._x_domain is None:
            return

        clamped_x_range = clamp_range(
            requested_x_range,
            self._x_domain,
            positive_only=self._is_log_x_enabled(),
        )
        base_y_domain = self._left_y_domain or self._right_y_domain
        if clamped_x_range is None or base_y_domain is None:
            return

        clamped_left_y_range = clamp_range(requested_y_range, base_y_domain)
        if clamped_left_y_range is None:
            return

        current_left_view = self._viewport_manager.get_current_left_view_range(self._plot_widget) or base_y_domain
        current_right_view = self._viewport_manager.get_current_right_view_range(self._right_vb) or self._right_y_domain
        applied_right_y_range = self._right_y_domain
        if current_right_view is not None and self._right_y_domain is not None:
            mapped_right = self._viewport_manager.map_parallel_y_range(
                current_left_view,
                current_right_view,
                clamped_left_y_range,
            )
            applied_right_y_range = clamp_range(mapped_right, self._right_y_domain)

        self._viewport_manager.reload_viewport_data(
            self._current_result,
            self._plot_items,
            clamped_x_range,
            self._from_view_x_value,
            VIEWPORT_POINTS,
        )
        self._apply_domain_limits()
        self._apply_viewport(clamped_x_range, clamped_left_y_range, applied_right_y_range)
        self._update_measurement()
        self._emit_viewport_changed()

    
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
        value_parts = self._measurement_support.build_value_parts(measurement, self._plot_items)
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
            return

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
        self._update_add_to_conversation_enabled()

    def _update_add_to_conversation_enabled(self):
        self._add_to_conversation_btn.setEnabled(bool(self._current_result is not None and self._plot_items))

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
            view_range = self._plot_widget.getPlotItem().viewRange()
            x_center = (view_range[0][0] + view_range[0][1]) / 2
            self.set_cursor_a(x_center)
        else:
            self._remove_cursor_a()

    def _on_toggle_cursor_b(self, checked: bool):
        """切换光标 B"""
        if checked:
            view_range = self._plot_widget.getPlotItem().viewRange()
            x_center = (view_range[0][0] + view_range[0][1]) / 2
            x_offset = (view_range[0][1] - view_range[0][0]) * 0.1
            self.set_cursor_b(x_center + x_offset)
        else:
            self._remove_cursor_b()

    def _on_fit_view(self):
        """Fit 按钮"""
        self.fit_to_view()

    def _update_signal_tree(self, result: SimulationResult):
        """更新信号树（分类显示：电压 / 电流 / 其他）"""
        self._updating_tree = True
        self._signal_tree.clear()

        classified = self._data_service.get_classified_signals(result)
        category_labels = {
            "voltage": "⚡ Voltage",
            "current": "🔌 Current",
            "other": "⚙ Other",
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
                    Qt.CheckState.Checked if is_displayed else Qt.CheckState.Unchecked,
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
                        Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked,
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
        self._fit_btn.setText(self._tr("Fit"))
        self._fit_btn.setToolTip(self._tr("Fit"))
        self._add_to_conversation_btn.setText(self._tr("Add to Conversation"))
        self._add_to_conversation_btn.setToolTip(self._tr("Add to Conversation"))

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
]
