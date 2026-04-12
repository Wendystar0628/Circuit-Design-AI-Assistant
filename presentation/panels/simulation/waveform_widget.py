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
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QSizePolicy,
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

from resources.theme import COLOR_BG_PRIMARY


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
    """
    
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
        self._measurement_cache: Optional[WaveformMeasurement] = None
        
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
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._plot_widget = pg.PlotWidget(viewBox=LTSpiceViewBox())
        self._plot_widget.setBackground(COLOR_BG_PRIMARY)
        layout.addWidget(self._plot_widget, 1)
    
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
        self.setStyleSheet("")
    
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

        self._measurement_cache = None
        self._refresh_legend()
        self.fit_to_view()
        
        self._logger.debug(
            f"Waveform added: {resolved_signal_name} [{axis_label}], "
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

        self._measurement_cache = None
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
        return True
    
    def clear_displayed_signals(self):
        """清空当前已显示信号，但保留当前结果上下文与信号目录"""
        self._clear_displayed_waveforms(preserve_result_context=True)

    def reset(self):
        """清空波形结果上下文与所有显示状态"""
        self._clear_displayed_waveforms(preserve_result_context=False)

    def set_signal_visible(self, signal_name: str, visible: bool) -> bool:
        if visible:
            if self._current_result is None:
                return False
            return self.add_waveform(self._current_result, signal_name)
        return self.remove_waveform(signal_name)
    
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
        self._update_measurement()

    def set_cursor_a_visible(self, visible: bool):
        if visible:
            if self._cursor_a is None:
                if self._x_domain is not None:
                    x_position = (self._x_domain[0] + self._x_domain[1]) / 2
                else:
                    x_position = 0.0
                self.set_cursor_a(x_position)
            return
        self._remove_cursor_a()
    
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
        self._update_measurement()

    def set_cursor_b_visible(self, visible: bool):
        if visible:
            if self._cursor_b is None:
                if self._x_domain is not None:
                    span = self._x_domain[1] - self._x_domain[0]
                    x_position = self._x_domain[0] + span * 0.6
                else:
                    x_position = 0.0
                self.set_cursor_b(x_position)
            return
        self._remove_cursor_b()
    
    def get_measurement(self) -> WaveformMeasurement:
        """
        获取测量结果（包含所有信号在光标处的 Y 值）
        
        Returns:
            WaveformMeasurement: 测量结果
        """
        if self._measurement_cache is None:
            self._measurement_cache = self._measurement_support.build_measurement(
                self._current_result,
                self._plot_items,
                self._cursor_a_pos,
                self._cursor_b_pos,
                self._from_view_x_value,
            )
        return self._measurement_cache

    def export_image(self, path: str) -> bool:
        if self._current_result is None or not self._plot_items:
            return False
        self.resize(max(self.width(), 1280), max(self.height(), 840))
        layout = self.layout()
        if layout is not None:
            layout.activate()
        render_width = max(self._plot_widget.width(), 960)
        render_height = max(self._plot_widget.height(), 640)
        pixmap = QPixmap(render_width, render_height)
        pixmap.fill(Qt.GlobalColor.transparent)
        self._plot_widget.render(pixmap)
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

    def get_web_snapshot(self, *, max_points: int = 1000) -> Dict[str, Any]:
        available_signal_names: List[str] = []
        if self._current_result is not None:
            try:
                available_signal_names = self._data_service.get_resolved_signal_names(self._current_result)
            except Exception:
                available_signal_names = []
        displayed_signal_names = self.get_displayed_signal_names()
        displayed_signal_set = set(displayed_signal_names)
        measurement = self.get_measurement()
        visible_series = []
        for signal_name, plot_item in self._plot_items.items():
            waveform_data = plot_item.waveform_data
            if waveform_data is None:
                continue
            x_data = waveform_data.x_data
            y_data = waveform_data.y_data
            total_points = min(len(x_data), len(y_data))
            if total_points <= 0:
                x_values: List[float] = []
                y_values: List[float] = []
            else:
                if max_points > 0 and total_points > max_points:
                    sample_indexes = np.linspace(0, total_points - 1, num=max_points, dtype=int)
                    x_sample = x_data[sample_indexes]
                    y_sample = y_data[sample_indexes]
                else:
                    x_sample = x_data[:total_points]
                    y_sample = y_data[:total_points]
                x_values = [float(value) for value in x_sample]
                y_values = [float(value) for value in y_sample]
            visible_series.append({
                "name": signal_name,
                "color": plot_item.color,
                "axis": plot_item.axis,
                "x": x_values,
                "y": y_values,
                "point_count": total_points,
                "sampled_point_count": len(y_values),
            })
        signal_catalog = [
            {
                "name": signal_name,
                "visible": signal_name in displayed_signal_set,
                "signal_type": WaveformDataService.get_signal_type(signal_name, self._signal_types),
            }
            for signal_name in available_signal_names
        ]
        return {
            "has_waveform": bool(available_signal_names),
            "signal_count": len(available_signal_names),
            "signal_names": available_signal_names,
            "displayed_signal_names": displayed_signal_names,
            "signal_catalog": signal_catalog,
            "visible_series": visible_series,
            "x_axis_label": self._get_x_axis_label(),
            "log_x": self._is_log_x_enabled(),
            "cursor_a_visible": self._cursor_a is not None,
            "cursor_b_visible": self._cursor_b is not None,
            "measurement": {
                "cursor_a_x": float(measurement.cursor_a_x) if measurement.cursor_a_x is not None else None,
                "cursor_b_x": float(measurement.cursor_b_x) if measurement.cursor_b_x is not None else None,
                "delta_x": float(measurement.delta_x) if measurement.delta_x is not None else None,
                "delta_y": float(measurement.delta_y) if measurement.delta_y is not None else None,
                "slope": float(measurement.slope) if measurement.slope is not None else None,
                "frequency": float(measurement.frequency) if measurement.frequency is not None else None,
                "values_a": {name: float(value) for name, value in (measurement.signal_values_a or {}).items()},
                "values_b": {name: float(value) for name, value in (measurement.signal_values_b or {}).items()},
            },
            "can_export": bool(self._current_result is not None and self._plot_items),
            "can_add_to_conversation": bool(self._plot_items),
        }

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

    def zoom_to_x_range(self, start: float, end: float):
        if self._current_result is None or not self._plot_items or self._x_domain is None:
            return
        requested_range = np.asarray([min(start, end), max(start, end)], dtype=float)
        view_range_array = self._to_view_x_data(requested_range)
        if view_range_array.size != 2 or not np.isfinite(view_range_array).all():
            return
        clamped_x_range = clamp_range(
            (float(view_range_array[0]), float(view_range_array[1])),
            self._x_domain,
            positive_only=self._is_log_x_enabled(),
        )
        if clamped_x_range is None:
            return
        current_left_y = self._viewport_manager.get_current_left_view_range(self._plot_widget) or self._left_y_domain
        current_right_y = self._viewport_manager.get_current_right_view_range(self._right_vb) or self._right_y_domain
        self._viewport_manager.reload_viewport_data(
            self._current_result,
            self._plot_items,
            clamped_x_range,
            self._from_view_x_value,
            VIEWPORT_POINTS,
        )
        self._apply_domain_limits()
        self._apply_viewport(clamped_x_range, current_left_y, current_right_y)
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
        self._measurement_cache = None
        self._x_domain = None
        self._left_y_domain = None
        self._right_y_domain = None
        x_label = result.get_x_axis_label()
        plot_item = self._plot_widget.getPlotItem()
        plot_item.setLabel('bottom', x_label)
        plot_item.setLogMode(x=result.is_x_axis_log(), y=False)

    def _clear_displayed_waveforms(self, preserve_result_context: bool):
        for plot_item in list(self._plot_items.values()):
            if plot_item.axis == "right" and self._right_vb is not None:
                self._right_vb.removeItem(plot_item.plot_data_item)
            else:
                self._plot_widget.getPlotItem().removeItem(plot_item.plot_data_item)

        self._plot_items.clear()
        self._color_index = 0
        self._measurement_cache = None
        self._x_domain = None
        self._left_y_domain = None
        self._right_y_domain = None
        self._refresh_legend()
        self._remove_cursor_a()
        self._remove_cursor_b()

        if not preserve_result_context or self._current_result is None:
            self._current_result = None
            self._current_result_signature = None
            self._signal_types = {}
            self._plot_widget.getPlotItem().setLogMode(x=False, y=False)

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

    def _remove_cursor_a(self):
        """移除光标 A"""
        if self._cursor_a is not None:
            self._plot_widget.removeItem(self._cursor_a)
            self._cursor_a = None
            self._cursor_a_pos = None
            self._update_measurement()

    def _remove_cursor_b(self):
        """移除光标 B"""
        if self._cursor_b is not None:
            self._plot_widget.removeItem(self._cursor_b)
            self._cursor_b = None
            self._cursor_b_pos = None
            self._update_measurement()

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
        self._measurement_cache = self._measurement_support.build_measurement(
            self._current_result,
            self._plot_items,
            self._cursor_a_pos,
            self._cursor_b_pos,
            self._from_view_x_value,
        )

    # ============================================================
    # 内部方法 - 事件处理
    # ============================================================

    # ============================================================
    # 国际化支持
    # ============================================================

    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        return

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
