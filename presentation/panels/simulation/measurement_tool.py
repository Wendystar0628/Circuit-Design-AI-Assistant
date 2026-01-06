# MeasurementTool - Dual Cursor Measurement Tool
"""
双光标测量工具

职责：
- 提供双光标测量 UI 面板
- 支持精确的光标位置输入
- 提供关键点快速定位（峰值、过零点、-3dB 点）
- 与 WaveformWidget 双向绑定
- 显示测量结果（ΔX、ΔY、斜率、频率）

设计参考：借鉴 LTspice 的交互式测量功能

被调用方：
- simulation_tab.py
- chart_viewer.py

使用示例：
    from presentation.panels.simulation.measurement_tool import MeasurementTool
    from presentation.panels.simulation.waveform_widget import WaveformWidget
    
    waveform = WaveformWidget()
    tool = MeasurementTool()
    tool.bind_waveform_widget(waveform)
    
    # 快速定位到峰值
    tool.snap_to_peak()
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional, Tuple

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QGroupBox,
    QSizePolicy,
    QDoubleSpinBox,
)
from PyQt6.QtGui import QDoubleValidator

from resources.theme import (
    COLOR_BG_PRIMARY,
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_BORDER,
    COLOR_ACCENT,
    COLOR_ACCENT_LIGHT,
    FONT_SIZE_NORMAL,
    FONT_SIZE_SMALL,
    SPACING_SMALL,
    SPACING_NORMAL,
    BORDER_RADIUS_NORMAL,
)


# ============================================================
# 常量定义
# ============================================================

# 光标颜色
CURSOR_A_COLOR = "#ff0000"  # 红色
CURSOR_B_COLOR = "#00ff00"  # 绿色

# 默认 -3dB 参考值
DEFAULT_3DB_REFERENCE = -3.0

# 峰值检测最小突出度
PEAK_PROMINENCE = 0.1


# ============================================================
# 数据类定义
# ============================================================

class SnapTarget(Enum):
    """快速定位目标类型"""
    PEAK = "peak"
    VALLEY = "valley"
    ZERO_CROSSING = "zero_crossing"
    MINUS_3DB = "minus_3db"


@dataclass
class MeasurementValues:
    """
    测量值数据类
    
    Attributes:
        cursor_a_x: 光标 A 的 X 位置
        cursor_a_y: 光标 A 的 Y 值
        cursor_b_x: 光标 B 的 X 位置
        cursor_b_y: 光标 B 的 Y 值
        delta_x: X 差值
        delta_y: Y 差值
        slope: 斜率 (ΔY/ΔX)
        frequency: 频率 (1/|ΔX|)
    """
    cursor_a_x: Optional[float] = None
    cursor_a_y: Optional[float] = None
    cursor_b_x: Optional[float] = None
    cursor_b_y: Optional[float] = None
    delta_x: Optional[float] = None
    delta_y: Optional[float] = None
    slope: Optional[float] = None
    frequency: Optional[float] = None
    
    def has_cursor_a(self) -> bool:
        """是否有光标 A 数据"""
        return self.cursor_a_x is not None
    
    def has_cursor_b(self) -> bool:
        """是否有光标 B 数据"""
        return self.cursor_b_x is not None
    
    def has_dual_cursor(self) -> bool:
        """是否有双光标数据"""
        return self.has_cursor_a() and self.has_cursor_b()


# ============================================================
# MeasurementTool - 双光标测量工具
# ============================================================

class MeasurementTool(QWidget):
    """
    双光标测量工具面板
    
    提供精确的光标位置控制和关键点快速定位功能。
    
    Signals:
        cursor_a_changed: 光标 A 位置变化
        cursor_b_changed: 光标 B 位置变化
        measurement_updated: 测量值更新
    """
    
    cursor_a_changed = pyqtSignal(float)
    cursor_b_changed = pyqtSignal(float)
    measurement_updated = pyqtSignal(object)  # MeasurementValues
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # 绑定的波形组件
        self._waveform_widget = None
        
        # 当前波形数据（用于关键点检测）
        self._x_data: Optional[np.ndarray] = None
        self._y_data: Optional[np.ndarray] = None
        
        # 当前测量值
        self._measurement = MeasurementValues()
        
        # -3dB 参考值
        self._db_reference = DEFAULT_3DB_REFERENCE
        
        # 初始化 UI
        self._setup_ui()
        self._apply_style()
        self.retranslate_ui()
    
    def _setup_ui(self):
        """初始化 UI 组件"""
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Minimum
        )
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        main_layout.setSpacing(SPACING_NORMAL)
        
        # 光标控制组
        cursor_group = QGroupBox()
        cursor_group.setObjectName("cursorGroup")
        cursor_layout = QGridLayout(cursor_group)
        cursor_layout.setSpacing(SPACING_SMALL)
        
        # 光标 A 行
        self._cursor_a_label = QLabel()
        self._cursor_a_label.setObjectName("cursorALabel")
        cursor_layout.addWidget(self._cursor_a_label, 0, 0)
        
        self._cursor_a_x_input = QDoubleSpinBox()
        self._cursor_a_x_input.setObjectName("cursorAXInput")
        self._cursor_a_x_input.setDecimals(6)
        self._cursor_a_x_input.setRange(-1e12, 1e12)
        self._cursor_a_x_input.setSingleStep(0.001)
        self._cursor_a_x_input.valueChanged.connect(self._on_cursor_a_x_changed)
        cursor_layout.addWidget(self._cursor_a_x_input, 0, 1)
        
        self._cursor_a_y_display = QLabel("--")
        self._cursor_a_y_display.setObjectName("cursorAYDisplay")
        self._cursor_a_y_display.setMinimumWidth(80)
        cursor_layout.addWidget(self._cursor_a_y_display, 0, 2)
        
        self._cursor_a_toggle = QToolButton()
        self._cursor_a_toggle.setObjectName("cursorAToggle")
        self._cursor_a_toggle.setText("A")
        self._cursor_a_toggle.setCheckable(True)
        self._cursor_a_toggle.clicked.connect(self._on_cursor_a_toggle)
        cursor_layout.addWidget(self._cursor_a_toggle, 0, 3)
        
        # 光标 B 行
        self._cursor_b_label = QLabel()
        self._cursor_b_label.setObjectName("cursorBLabel")
        cursor_layout.addWidget(self._cursor_b_label, 1, 0)
        
        self._cursor_b_x_input = QDoubleSpinBox()
        self._cursor_b_x_input.setObjectName("cursorBXInput")
        self._cursor_b_x_input.setDecimals(6)
        self._cursor_b_x_input.setRange(-1e12, 1e12)
        self._cursor_b_x_input.setSingleStep(0.001)
        self._cursor_b_x_input.valueChanged.connect(self._on_cursor_b_x_changed)
        cursor_layout.addWidget(self._cursor_b_x_input, 1, 1)
        
        self._cursor_b_y_display = QLabel("--")
        self._cursor_b_y_display.setObjectName("cursorBYDisplay")
        self._cursor_b_y_display.setMinimumWidth(80)
        cursor_layout.addWidget(self._cursor_b_y_display, 1, 2)
        
        self._cursor_b_toggle = QToolButton()
        self._cursor_b_toggle.setObjectName("cursorBToggle")
        self._cursor_b_toggle.setText("B")
        self._cursor_b_toggle.setCheckable(True)
        self._cursor_b_toggle.clicked.connect(self._on_cursor_b_toggle)
        cursor_layout.addWidget(self._cursor_b_toggle, 1, 3)
        
        main_layout.addWidget(cursor_group)
        
        # 测量结果组
        result_group = QGroupBox()
        result_group.setObjectName("resultGroup")
        result_layout = QGridLayout(result_group)
        result_layout.setSpacing(SPACING_SMALL)
        
        # ΔX
        self._delta_x_label = QLabel("ΔX:")
        result_layout.addWidget(self._delta_x_label, 0, 0)
        self._delta_x_value = QLabel("--")
        self._delta_x_value.setObjectName("deltaXValue")
        result_layout.addWidget(self._delta_x_value, 0, 1)
        
        # ΔY
        self._delta_y_label = QLabel("ΔY:")
        result_layout.addWidget(self._delta_y_label, 0, 2)
        self._delta_y_value = QLabel("--")
        self._delta_y_value.setObjectName("deltaYValue")
        result_layout.addWidget(self._delta_y_value, 0, 3)
        
        # 斜率
        self._slope_label = QLabel()
        result_layout.addWidget(self._slope_label, 1, 0)
        self._slope_value = QLabel("--")
        self._slope_value.setObjectName("slopeValue")
        result_layout.addWidget(self._slope_value, 1, 1)
        
        # 频率
        self._freq_label = QLabel()
        result_layout.addWidget(self._freq_label, 1, 2)
        self._freq_value = QLabel("--")
        self._freq_value.setObjectName("freqValue")
        result_layout.addWidget(self._freq_value, 1, 3)
        
        main_layout.addWidget(result_group)
        
        # 快速定位按钮组
        snap_group = QGroupBox()
        snap_group.setObjectName("snapGroup")
        snap_layout = QHBoxLayout(snap_group)
        snap_layout.setSpacing(SPACING_SMALL)
        
        self._snap_peak_btn = QPushButton()
        self._snap_peak_btn.setObjectName("snapPeakBtn")
        self._snap_peak_btn.clicked.connect(self.snap_to_peak)
        snap_layout.addWidget(self._snap_peak_btn)
        
        self._snap_valley_btn = QPushButton()
        self._snap_valley_btn.setObjectName("snapValleyBtn")
        self._snap_valley_btn.clicked.connect(self.snap_to_valley)
        snap_layout.addWidget(self._snap_valley_btn)
        
        self._snap_zero_btn = QPushButton()
        self._snap_zero_btn.setObjectName("snapZeroBtn")
        self._snap_zero_btn.clicked.connect(self.snap_to_zero_crossing)
        snap_layout.addWidget(self._snap_zero_btn)
        
        self._snap_3db_btn = QPushButton()
        self._snap_3db_btn.setObjectName("snap3dbBtn")
        self._snap_3db_btn.clicked.connect(self.snap_to_minus_3db)
        snap_layout.addWidget(self._snap_3db_btn)
        
        main_layout.addWidget(snap_group)
        
        main_layout.addStretch()
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            MeasurementTool {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            QGroupBox {{
                background-color: {COLOR_BG_SECONDARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: {SPACING_NORMAL}px;
                margin-top: 8px;
            }}
            
            QGroupBox::title {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_SMALL}px;
                subcontrol-origin: margin;
                left: {SPACING_NORMAL}px;
            }}
            
            QLabel {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #cursorALabel {{
                color: {CURSOR_A_COLOR};
                font-weight: bold;
            }}
            
            #cursorBLabel {{
                color: {CURSOR_B_COLOR};
                font-weight: bold;
            }}
            
            #cursorAYDisplay, #cursorBYDisplay {{
                font-family: monospace;
                color: {COLOR_TEXT_SECONDARY};
            }}
            
            #deltaXValue, #deltaYValue, #slopeValue, #freqValue {{
                font-family: monospace;
                font-weight: bold;
            }}
            
            QDoubleSpinBox {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 2px 4px;
                min-width: 100px;
            }}
            
            QDoubleSpinBox:focus {{
                border-color: {COLOR_ACCENT};
            }}
            
            QToolButton {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 4px 8px;
                min-width: 24px;
                font-weight: bold;
            }}
            
            #cursorAToggle:checked {{
                background-color: {CURSOR_A_COLOR};
                color: white;
                border-color: {CURSOR_A_COLOR};
            }}
            
            #cursorBToggle:checked {{
                background-color: {CURSOR_B_COLOR};
                color: white;
                border-color: {CURSOR_B_COLOR};
            }}
            
            QPushButton {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 4px 8px;
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            QPushButton:hover {{
                background-color: {COLOR_ACCENT_LIGHT};
                border-color: {COLOR_ACCENT};
            }}
            
            QPushButton:pressed {{
                background-color: {COLOR_ACCENT};
                color: white;
            }}
            
            QPushButton:disabled {{
                background-color: {COLOR_BG_SECONDARY};
                color: {COLOR_TEXT_SECONDARY};
                border-color: {COLOR_BORDER};
            }}
        """)

    # ============================================================
    # 公共方法
    # ============================================================
    
    def bind_waveform_widget(self, widget) -> None:
        """
        绑定波形组件
        
        建立双向绑定：
        - 本工具的光标变化会同步到波形组件
        - 波形组件的光标变化会同步到本工具
        
        Args:
            widget: WaveformWidget 实例
        """
        self._waveform_widget = widget
        
        # 连接波形组件的信号
        if hasattr(widget, 'measurement_changed'):
            widget.measurement_changed.connect(self._on_waveform_measurement_changed)
        
        self._logger.debug("Waveform widget bound")
    
    def unbind_waveform_widget(self) -> None:
        """解除波形组件绑定"""
        if self._waveform_widget is not None:
            if hasattr(self._waveform_widget, 'measurement_changed'):
                try:
                    self._waveform_widget.measurement_changed.disconnect(
                        self._on_waveform_measurement_changed
                    )
                except TypeError:
                    pass
            self._waveform_widget = None
    
    def set_waveform_data(
        self,
        x_data: np.ndarray,
        y_data: np.ndarray
    ) -> None:
        """
        设置波形数据（用于关键点检测）
        
        Args:
            x_data: X 轴数据数组
            y_data: Y 轴数据数组
        """
        self._x_data = np.asarray(x_data)
        self._y_data = np.asarray(y_data)
        
        # 更新输入框范围
        if len(self._x_data) > 0:
            x_min, x_max = float(self._x_data.min()), float(self._x_data.max())
            self._cursor_a_x_input.setRange(x_min, x_max)
            self._cursor_b_x_input.setRange(x_min, x_max)
    
    def set_cursor_a(self, x_position: float) -> None:
        """
        设置光标 A 位置
        
        Args:
            x_position: X 轴位置
        """
        # 更新输入框（阻止信号循环）
        self._cursor_a_x_input.blockSignals(True)
        self._cursor_a_x_input.setValue(x_position)
        self._cursor_a_x_input.blockSignals(False)
        
        # 更新测量值
        self._measurement.cursor_a_x = x_position
        self._measurement.cursor_a_y = self._get_y_at_x(x_position)
        
        # 更新 Y 值显示
        if self._measurement.cursor_a_y is not None:
            self._cursor_a_y_display.setText(f"{self._measurement.cursor_a_y:.4g}")
        else:
            self._cursor_a_y_display.setText("--")
        
        # 更新切换按钮状态
        self._cursor_a_toggle.setChecked(True)
        
        # 同步到波形组件
        if self._waveform_widget is not None:
            self._waveform_widget.set_cursor_a(x_position)
        
        # 更新差值计算
        self._update_delta_values()
        
        # 发出信号
        self.cursor_a_changed.emit(x_position)
    
    def set_cursor_b(self, x_position: float) -> None:
        """
        设置光标 B 位置
        
        Args:
            x_position: X 轴位置
        """
        # 更新输入框（阻止信号循环）
        self._cursor_b_x_input.blockSignals(True)
        self._cursor_b_x_input.setValue(x_position)
        self._cursor_b_x_input.blockSignals(False)
        
        # 更新测量值
        self._measurement.cursor_b_x = x_position
        self._measurement.cursor_b_y = self._get_y_at_x(x_position)
        
        # 更新 Y 值显示
        if self._measurement.cursor_b_y is not None:
            self._cursor_b_y_display.setText(f"{self._measurement.cursor_b_y:.4g}")
        else:
            self._cursor_b_y_display.setText("--")
        
        # 更新切换按钮状态
        self._cursor_b_toggle.setChecked(True)
        
        # 同步到波形组件
        if self._waveform_widget is not None:
            self._waveform_widget.set_cursor_b(x_position)
        
        # 更新差值计算
        self._update_delta_values()
        
        # 发出信号
        self.cursor_b_changed.emit(x_position)
    
    def get_delta_values(self) -> MeasurementValues:
        """
        获取差值计算结果
        
        Returns:
            MeasurementValues: 测量值数据
        """
        return self._measurement
    
    def snap_to_peak(self) -> bool:
        """
        光标吸附到最近峰值
        
        将当前活动光标移动到最近的局部最大值位置。
        
        Returns:
            bool: 是否成功找到峰值
        """
        return self._snap_to_target(SnapTarget.PEAK)
    
    def snap_to_valley(self) -> bool:
        """
        光标吸附到最近谷值
        
        将当前活动光标移动到最近的局部最小值位置。
        
        Returns:
            bool: 是否成功找到谷值
        """
        return self._snap_to_target(SnapTarget.VALLEY)
    
    def snap_to_zero_crossing(self) -> bool:
        """
        光标吸附到最近过零点
        
        将当前活动光标移动到最近的过零点位置。
        
        Returns:
            bool: 是否成功找到过零点
        """
        return self._snap_to_target(SnapTarget.ZERO_CROSSING)
    
    def snap_to_minus_3db(self) -> bool:
        """
        光标吸附到 -3dB 点
        
        将当前活动光标移动到最近的 -3dB 点位置。
        适用于频率响应分析。
        
        Returns:
            bool: 是否成功找到 -3dB 点
        """
        return self._snap_to_target(SnapTarget.MINUS_3DB)
    
    def set_db_reference(self, reference: float) -> None:
        """
        设置 dB 参考值
        
        Args:
            reference: 参考值（默认 -3.0）
        """
        self._db_reference = reference
    
    def clear(self) -> None:
        """清空测量数据"""
        self._measurement = MeasurementValues()
        self._x_data = None
        self._y_data = None
        
        # 重置输入框
        self._cursor_a_x_input.blockSignals(True)
        self._cursor_b_x_input.blockSignals(True)
        self._cursor_a_x_input.setValue(0)
        self._cursor_b_x_input.setValue(0)
        self._cursor_a_x_input.blockSignals(False)
        self._cursor_b_x_input.blockSignals(False)
        
        # 重置显示
        self._cursor_a_y_display.setText("--")
        self._cursor_b_y_display.setText("--")
        self._delta_x_value.setText("--")
        self._delta_y_value.setText("--")
        self._slope_value.setText("--")
        self._freq_value.setText("--")
        
        # 重置切换按钮
        self._cursor_a_toggle.setChecked(False)
        self._cursor_b_toggle.setChecked(False)
    
    # ============================================================
    # 内部方法 - 事件处理
    # ============================================================
    
    def _on_cursor_a_x_changed(self, value: float) -> None:
        """光标 A X 位置输入变化"""
        self.set_cursor_a(value)
    
    def _on_cursor_b_x_changed(self, value: float) -> None:
        """光标 B X 位置输入变化"""
        self.set_cursor_b(value)
    
    def _on_cursor_a_toggle(self, checked: bool) -> None:
        """光标 A 切换按钮"""
        if checked:
            # 在数据中心位置创建光标
            if self._x_data is not None and len(self._x_data) > 0:
                center = float((self._x_data.min() + self._x_data.max()) / 2)
                self.set_cursor_a(center)
        else:
            # 移除光标
            self._measurement.cursor_a_x = None
            self._measurement.cursor_a_y = None
            self._cursor_a_y_display.setText("--")
            self._update_delta_values()
            
            # 同步到波形组件
            if self._waveform_widget is not None:
                self._waveform_widget._remove_cursor_a()
    
    def _on_cursor_b_toggle(self, checked: bool) -> None:
        """光标 B 切换按钮"""
        if checked:
            # 在数据中心偏右位置创建光标
            if self._x_data is not None and len(self._x_data) > 0:
                x_min, x_max = float(self._x_data.min()), float(self._x_data.max())
                center = (x_min + x_max) / 2
                offset = (x_max - x_min) * 0.1
                self.set_cursor_b(center + offset)
        else:
            # 移除光标
            self._measurement.cursor_b_x = None
            self._measurement.cursor_b_y = None
            self._cursor_b_y_display.setText("--")
            self._update_delta_values()
            
            # 同步到波形组件
            if self._waveform_widget is not None:
                self._waveform_widget._remove_cursor_b()
    
    def _on_waveform_measurement_changed(self, waveform_measurement) -> None:
        """
        处理波形组件测量变化
        
        从 WaveformWidget 同步测量数据到本工具。
        """
        # 更新光标 A
        if waveform_measurement.cursor_a_x is not None:
            self._cursor_a_x_input.blockSignals(True)
            self._cursor_a_x_input.setValue(waveform_measurement.cursor_a_x)
            self._cursor_a_x_input.blockSignals(False)
            
            self._measurement.cursor_a_x = waveform_measurement.cursor_a_x
            self._measurement.cursor_a_y = waveform_measurement.cursor_a_y
            
            if waveform_measurement.cursor_a_y is not None:
                self._cursor_a_y_display.setText(f"{waveform_measurement.cursor_a_y:.4g}")
            
            self._cursor_a_toggle.setChecked(True)
        
        # 更新光标 B
        if waveform_measurement.cursor_b_x is not None:
            self._cursor_b_x_input.blockSignals(True)
            self._cursor_b_x_input.setValue(waveform_measurement.cursor_b_x)
            self._cursor_b_x_input.blockSignals(False)
            
            self._measurement.cursor_b_x = waveform_measurement.cursor_b_x
            self._measurement.cursor_b_y = waveform_measurement.cursor_b_y
            
            if waveform_measurement.cursor_b_y is not None:
                self._cursor_b_y_display.setText(f"{waveform_measurement.cursor_b_y:.4g}")
            
            self._cursor_b_toggle.setChecked(True)
        
        # 更新差值
        self._update_delta_values()

    # ============================================================
    # 内部方法 - 数据处理
    # ============================================================
    
    def _get_y_at_x(self, x: float) -> Optional[float]:
        """
        获取指定 X 位置的 Y 值（线性插值）
        
        Args:
            x: X 轴位置
            
        Returns:
            Optional[float]: Y 值，无数据时返回 None
        """
        if self._x_data is None or self._y_data is None:
            return None
        
        if len(self._x_data) == 0:
            return None
        
        try:
            return float(np.interp(x, self._x_data, self._y_data))
        except Exception:
            return None
    
    def _update_delta_values(self) -> None:
        """更新差值计算"""
        # 计算差值
        if self._measurement.has_dual_cursor():
            self._measurement.delta_x = (
                self._measurement.cursor_b_x - self._measurement.cursor_a_x
            )
            
            if self._measurement.cursor_a_y is not None and self._measurement.cursor_b_y is not None:
                self._measurement.delta_y = (
                    self._measurement.cursor_b_y - self._measurement.cursor_a_y
                )
                
                # 计算斜率
                if self._measurement.delta_x != 0:
                    self._measurement.slope = (
                        self._measurement.delta_y / self._measurement.delta_x
                    )
                else:
                    self._measurement.slope = None
            else:
                self._measurement.delta_y = None
                self._measurement.slope = None
            
            # 计算频率
            if self._measurement.delta_x != 0:
                self._measurement.frequency = 1.0 / abs(self._measurement.delta_x)
            else:
                self._measurement.frequency = None
        else:
            self._measurement.delta_x = None
            self._measurement.delta_y = None
            self._measurement.slope = None
            self._measurement.frequency = None
        
        # 更新显示
        self._update_display()
        
        # 发出信号
        self.measurement_updated.emit(self._measurement)
    
    def _update_display(self) -> None:
        """更新显示"""
        # ΔX
        if self._measurement.delta_x is not None:
            self._delta_x_value.setText(f"{self._measurement.delta_x:.4g}")
        else:
            self._delta_x_value.setText("--")
        
        # ΔY
        if self._measurement.delta_y is not None:
            self._delta_y_value.setText(f"{self._measurement.delta_y:.4g}")
        else:
            self._delta_y_value.setText("--")
        
        # 斜率
        if self._measurement.slope is not None:
            self._slope_value.setText(f"{self._measurement.slope:.4g}")
        else:
            self._slope_value.setText("--")
        
        # 频率
        if self._measurement.frequency is not None:
            self._freq_value.setText(f"{self._measurement.frequency:.4g} Hz")
        else:
            self._freq_value.setText("--")
    
    def _snap_to_target(self, target: SnapTarget) -> bool:
        """
        光标吸附到目标位置
        
        Args:
            target: 目标类型
            
        Returns:
            bool: 是否成功
        """
        if self._x_data is None or self._y_data is None:
            self._logger.warning("No waveform data for snap operation")
            return False
        
        if len(self._x_data) == 0:
            return False
        
        # 获取当前光标位置作为搜索起点
        current_x = self._measurement.cursor_a_x
        if current_x is None:
            current_x = float((self._x_data.min() + self._x_data.max()) / 2)
        
        # 查找目标位置
        target_x = self._find_target_position(target, current_x)
        
        if target_x is not None:
            self.set_cursor_a(target_x)
            return True
        
        return False
    
    def _find_target_position(
        self,
        target: SnapTarget,
        reference_x: float
    ) -> Optional[float]:
        """
        查找目标位置
        
        Args:
            target: 目标类型
            reference_x: 参考 X 位置（用于查找最近的目标）
            
        Returns:
            Optional[float]: 目标 X 位置，未找到返回 None
        """
        if target == SnapTarget.PEAK:
            return self._find_nearest_peak(reference_x)
        elif target == SnapTarget.VALLEY:
            return self._find_nearest_valley(reference_x)
        elif target == SnapTarget.ZERO_CROSSING:
            return self._find_nearest_zero_crossing(reference_x)
        elif target == SnapTarget.MINUS_3DB:
            return self._find_nearest_3db_point(reference_x)
        
        return None
    
    def _find_nearest_peak(self, reference_x: float) -> Optional[float]:
        """
        查找最近的峰值
        
        使用简单的局部最大值检测。
        """
        if len(self._y_data) < 3:
            return None
        
        # 查找所有局部最大值
        peaks = []
        for i in range(1, len(self._y_data) - 1):
            if self._y_data[i] > self._y_data[i-1] and self._y_data[i] > self._y_data[i+1]:
                # 检查突出度
                prominence = min(
                    self._y_data[i] - self._y_data[i-1],
                    self._y_data[i] - self._y_data[i+1]
                )
                y_range = self._y_data.max() - self._y_data.min()
                if y_range > 0 and prominence / y_range >= PEAK_PROMINENCE:
                    peaks.append(i)
        
        if not peaks:
            # 没有找到峰值，返回全局最大值
            max_idx = int(np.argmax(self._y_data))
            return float(self._x_data[max_idx])
        
        # 找到最近的峰值
        ref_idx = int(np.searchsorted(self._x_data, reference_x))
        nearest_peak = min(peaks, key=lambda p: abs(p - ref_idx))
        
        return float(self._x_data[nearest_peak])
    
    def _find_nearest_valley(self, reference_x: float) -> Optional[float]:
        """
        查找最近的谷值
        
        使用简单的局部最小值检测。
        """
        if len(self._y_data) < 3:
            return None
        
        # 查找所有局部最小值
        valleys = []
        for i in range(1, len(self._y_data) - 1):
            if self._y_data[i] < self._y_data[i-1] and self._y_data[i] < self._y_data[i+1]:
                # 检查突出度
                prominence = min(
                    self._y_data[i-1] - self._y_data[i],
                    self._y_data[i+1] - self._y_data[i]
                )
                y_range = self._y_data.max() - self._y_data.min()
                if y_range > 0 and prominence / y_range >= PEAK_PROMINENCE:
                    valleys.append(i)
        
        if not valleys:
            # 没有找到谷值，返回全局最小值
            min_idx = int(np.argmin(self._y_data))
            return float(self._x_data[min_idx])
        
        # 找到最近的谷值
        ref_idx = int(np.searchsorted(self._x_data, reference_x))
        nearest_valley = min(valleys, key=lambda v: abs(v - ref_idx))
        
        return float(self._x_data[nearest_valley])
    
    def _find_nearest_zero_crossing(self, reference_x: float) -> Optional[float]:
        """
        查找最近的过零点
        
        使用符号变化检测。
        """
        if len(self._y_data) < 2:
            return None
        
        # 查找所有过零点
        zero_crossings = []
        for i in range(len(self._y_data) - 1):
            if self._y_data[i] * self._y_data[i+1] < 0:
                # 线性插值找到精确的过零点
                x0, x1 = self._x_data[i], self._x_data[i+1]
                y0, y1 = self._y_data[i], self._y_data[i+1]
                
                if y1 != y0:
                    zero_x = x0 - y0 * (x1 - x0) / (y1 - y0)
                    zero_crossings.append(zero_x)
        
        if not zero_crossings:
            return None
        
        # 找到最近的过零点
        nearest = min(zero_crossings, key=lambda z: abs(z - reference_x))
        
        return float(nearest)
    
    def _find_nearest_3db_point(self, reference_x: float) -> Optional[float]:
        """
        查找最近的 -3dB 点
        
        适用于频率响应分析，查找增益下降 3dB 的位置。
        """
        if len(self._y_data) < 2:
            return None
        
        # 假设 Y 数据是 dB 值
        # 找到最大值作为参考
        max_y = float(self._y_data.max())
        target_y = max_y + self._db_reference  # 通常是 max - 3
        
        # 查找所有穿越 target_y 的点
        crossings = []
        for i in range(len(self._y_data) - 1):
            y0, y1 = self._y_data[i], self._y_data[i+1]
            
            # 检查是否穿越目标值
            if (y0 >= target_y >= y1) or (y0 <= target_y <= y1):
                x0, x1 = self._x_data[i], self._x_data[i+1]
                
                if y1 != y0:
                    cross_x = x0 + (target_y - y0) * (x1 - x0) / (y1 - y0)
                    crossings.append(cross_x)
        
        if not crossings:
            return None
        
        # 找到最近的穿越点
        nearest = min(crossings, key=lambda c: abs(c - reference_x))
        
        return float(nearest)
    
    # ============================================================
    # 国际化支持
    # ============================================================
    
    def retranslate_ui(self) -> None:
        """重新翻译 UI 文本"""
        self._cursor_a_label.setText(self._tr("Cursor A:"))
        self._cursor_b_label.setText(self._tr("Cursor B:"))
        self._slope_label.setText(self._tr("Slope:"))
        self._freq_label.setText(self._tr("Freq:"))
        
        self._snap_peak_btn.setText(self._tr("Peak"))
        self._snap_valley_btn.setText(self._tr("Valley"))
        self._snap_zero_btn.setText(self._tr("Zero"))
        self._snap_3db_btn.setText(self._tr("-3dB"))
        
        # 工具提示
        self._snap_peak_btn.setToolTip(self._tr("Snap to nearest peak"))
        self._snap_valley_btn.setToolTip(self._tr("Snap to nearest valley"))
        self._snap_zero_btn.setToolTip(self._tr("Snap to nearest zero crossing"))
        self._snap_3db_btn.setToolTip(self._tr("Snap to -3dB point"))
        
        self._cursor_a_toggle.setToolTip(self._tr("Toggle Cursor A"))
        self._cursor_b_toggle.setToolTip(self._tr("Toggle Cursor B"))
    
    def _tr(self, text: str) -> str:
        """翻译文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(f"measurement_tool.{text}", default=text)
        except ImportError:
            return text


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "MeasurementTool",
    "MeasurementValues",
    "SnapTarget",
]
