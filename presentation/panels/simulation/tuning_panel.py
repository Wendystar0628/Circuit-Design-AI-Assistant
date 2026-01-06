# TuningPanel - Quick Parameter Tuning Panel
"""
快速调参面板

职责：
- 提供可视化的参数调整界面
- 支持滑块调参和数值输入
- 防抖触发自动仿真
- 应用参数修改到电路文件

设计参考：
- 借鉴 LTspice 的实时参数调整（Tuning）功能

被调用方：
- simulation_tab.py
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Callable

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QSlider,
    QDoubleSpinBox,
    QPushButton,
    QScrollArea,
    QCheckBox,
    QSizePolicy,
    QToolButton,
)
from PyQt6.QtGui import QIcon

from resources.theme import (
    COLOR_BG_PRIMARY,
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_ACCENT,
    COLOR_ACCENT_LIGHT,
    COLOR_BORDER,
    COLOR_SUCCESS,
    COLOR_WARNING,
    FONT_SIZE_NORMAL,
    FONT_SIZE_SMALL,
    SPACING_SMALL,
    SPACING_NORMAL,
    SPACING_LARGE,
    BORDER_RADIUS_NORMAL,
    BORDER_RADIUS_SMALL,
)

_logger = logging.getLogger(__name__)

# 防抖延迟（毫秒）
DEBOUNCE_DELAY_MS = 500

# 滑块精度（分成多少步）
SLIDER_STEPS = 1000


@dataclass
class ParameterState:
    """参数状态"""
    name: str
    current_value: float
    original_value: float
    min_value: float
    max_value: float
    step: float
    unit: str
    param_type: str
    line_number: int
    element_name: str


class ParameterSliderWidget(QFrame):
    """
    单个参数滑块组件
    
    包含：参数名、滑块、数值输入框、单位标签、范围设置按钮
    """
    
    value_changed = pyqtSignal(str, float)  # (param_name, new_value)
    range_edit_requested = pyqtSignal(str)  # param_name
    
    def __init__(
        self, 
        param: ParameterState,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        
        self._param = param
        self._is_updating = False  # 防止循环更新
        
        self.setObjectName("parameterSlider")
        self._setup_ui()
        self._apply_style()
        self._connect_signals()
        self._update_display()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_SMALL, SPACING_SMALL, SPACING_SMALL, SPACING_SMALL)
        layout.setSpacing(SPACING_SMALL)
        
        # 顶部行：参数名 + 范围设置按钮
        top_row = QHBoxLayout()
        top_row.setSpacing(SPACING_SMALL)
        
        # 参数名标签
        self._name_label = QLabel(self._param.name)
        self._name_label.setObjectName("paramName")
        top_row.addWidget(self._name_label)
        
        # 参数类型标签
        type_text = self._get_type_display(self._param.param_type)
        self._type_label = QLabel(type_text)
        self._type_label.setObjectName("paramType")
        top_row.addWidget(self._type_label)
        
        top_row.addStretch()
        
        # 范围设置按钮
        self._range_btn = QToolButton()
        self._range_btn.setObjectName("rangeBtn")
        self._range_btn.setText("⚙")
        self._range_btn.setToolTip("设置范围")
        self._range_btn.setFixedSize(20, 20)
        top_row.addWidget(self._range_btn)
        
        layout.addLayout(top_row)
        
        # 中间行：滑块
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setObjectName("paramSlider")
        self._slider.setRange(0, SLIDER_STEPS)
        self._slider.setFixedHeight(20)
        layout.addWidget(self._slider)
        
        # 底部行：最小值 + 数值输入 + 最大值
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(SPACING_SMALL)
        
        # 最小值标签
        self._min_label = QLabel()
        self._min_label.setObjectName("rangeLabel")
        self._min_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        bottom_row.addWidget(self._min_label)
        
        bottom_row.addStretch()
        
        # 数值输入框
        self._spin_box = QDoubleSpinBox()
        self._spin_box.setObjectName("paramSpinBox")
        self._spin_box.setDecimals(6)
        self._spin_box.setFixedWidth(100)
        bottom_row.addWidget(self._spin_box)
        
        # 单位标签
        self._unit_label = QLabel(self._param.unit)
        self._unit_label.setObjectName("unitLabel")
        self._unit_label.setFixedWidth(30)
        bottom_row.addWidget(self._unit_label)
        
        bottom_row.addStretch()
        
        # 最大值标签
        self._max_label = QLabel()
        self._max_label.setObjectName("rangeLabel")
        self._max_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        bottom_row.addWidget(self._max_label)
        
        layout.addLayout(bottom_row)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #parameterSlider {{
                background-color: {COLOR_BG_SECONDARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #paramName {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
                font-weight: bold;
            }}
            
            #paramType {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
                padding: 1px 4px;
                background-color: {COLOR_BG_TERTIARY};
                border-radius: {BORDER_RADIUS_SMALL}px;
            }}
            
            #rangeLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #unitLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #rangeBtn {{
                background-color: transparent;
                border: none;
                color: {COLOR_TEXT_SECONDARY};
            }}
            
            #rangeBtn:hover {{
                color: {COLOR_ACCENT};
            }}
            
            #paramSlider {{
                background-color: transparent;
            }}
            
            #paramSlider::groove:horizontal {{
                border: none;
                height: 4px;
                background-color: {COLOR_BG_TERTIARY};
                border-radius: 2px;
            }}
            
            #paramSlider::handle:horizontal {{
                background-color: {COLOR_ACCENT};
                border: none;
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }}
            
            #paramSlider::handle:horizontal:hover {{
                background-color: {COLOR_ACCENT};
                width: 16px;
                height: 16px;
                margin: -6px 0;
                border-radius: 8px;
            }}
            
            #paramSlider::sub-page:horizontal {{
                background-color: {COLOR_ACCENT};
                border-radius: 2px;
            }}
            
            #paramSpinBox {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_SMALL}px;
                padding: 2px 4px;
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #paramSpinBox:focus {{
                border-color: {COLOR_ACCENT};
            }}
        """)
    
    def _connect_signals(self):
        """连接信号"""
        self._slider.valueChanged.connect(self._on_slider_changed)
        self._spin_box.valueChanged.connect(self._on_spinbox_changed)
        self._range_btn.clicked.connect(
            lambda: self.range_edit_requested.emit(self._param.name)
        )
    
    def _update_display(self):
        """更新显示"""
        self._is_updating = True
        
        # 更新范围标签
        self._min_label.setText(self._format_value(self._param.min_value))
        self._max_label.setText(self._format_value(self._param.max_value))
        
        # 更新 SpinBox 范围
        self._spin_box.setRange(self._param.min_value, self._param.max_value)
        self._spin_box.setSingleStep(self._param.step)
        self._spin_box.setValue(self._param.current_value)
        
        # 更新滑块位置
        slider_pos = self._value_to_slider(self._param.current_value)
        self._slider.setValue(slider_pos)
        
        self._is_updating = False
    
    def _on_slider_changed(self, position: int):
        """滑块值变化"""
        if self._is_updating:
            return
        
        value = self._slider_to_value(position)
        self._is_updating = True
        self._spin_box.setValue(value)
        self._is_updating = False
        
        self._param.current_value = value
        self.value_changed.emit(self._param.name, value)
    
    def _on_spinbox_changed(self, value: float):
        """数值输入框变化"""
        if self._is_updating:
            return
        
        self._is_updating = True
        slider_pos = self._value_to_slider(value)
        self._slider.setValue(slider_pos)
        self._is_updating = False
        
        self._param.current_value = value
        self.value_changed.emit(self._param.name, value)
    
    def _value_to_slider(self, value: float) -> int:
        """将实际值转换为滑块位置"""
        if self._param.max_value == self._param.min_value:
            return 0
        
        ratio = (value - self._param.min_value) / (self._param.max_value - self._param.min_value)
        return int(ratio * SLIDER_STEPS)
    
    def _slider_to_value(self, position: int) -> float:
        """将滑块位置转换为实际值"""
        ratio = position / SLIDER_STEPS
        return self._param.min_value + ratio * (self._param.max_value - self._param.min_value)
    
    def _format_value(self, value: float) -> str:
        """格式化数值显示"""
        abs_val = abs(value)
        if abs_val == 0:
            return "0"
        elif abs_val >= 1e6:
            return f"{value/1e6:.2g}M"
        elif abs_val >= 1e3:
            return f"{value/1e3:.2g}k"
        elif abs_val >= 1:
            return f"{value:.3g}"
        elif abs_val >= 1e-3:
            return f"{value*1e3:.2g}m"
        elif abs_val >= 1e-6:
            return f"{value*1e6:.2g}u"
        elif abs_val >= 1e-9:
            return f"{value*1e9:.2g}n"
        elif abs_val >= 1e-12:
            return f"{value*1e12:.2g}p"
        else:
            return f"{value:.2e}"
    
    def _get_type_display(self, param_type: str) -> str:
        """获取参数类型显示文本"""
        type_map = {
            "param": "参数",
            "resistor": "电阻",
            "capacitor": "电容",
            "inductor": "电感",
            "voltage": "电压",
            "current": "电流",
        }
        return type_map.get(param_type, param_type)
    
    @property
    def param_name(self) -> str:
        """获取参数名"""
        return self._param.name
    
    @property
    def current_value(self) -> float:
        """获取当前值"""
        return self._param.current_value
    
    @property
    def original_value(self) -> float:
        """获取原始值"""
        return self._param.original_value
    
    @property
    def is_modified(self) -> bool:
        """是否已修改"""
        return self._param.current_value != self._param.original_value
    
    def set_value(self, value: float):
        """设置值"""
        self._param.current_value = value
        self._update_display()
    
    def reset_to_original(self):
        """重置为原始值"""
        self._param.current_value = self._param.original_value
        self._update_display()
    
    def set_range(self, min_val: float, max_val: float):
        """设置范围"""
        self._param.min_value = min_val
        self._param.max_value = max_val
        self._param.step = (max_val - min_val) / 100.0
        self._update_display()



class TuningPanel(QWidget):
    """
    快速调参面板
    
    提供可视化的参数调整界面，支持滑块调参和实时仿真更新。
    
    Signals:
        parameters_changed: 参数变更信号，携带变更的参数字典
        apply_requested: 请求应用参数到电路文件
        reset_requested: 请求重置所有参数
        simulation_requested: 请求触发仿真
    """
    
    parameters_changed = pyqtSignal(dict)  # {param_name: new_value}
    apply_requested = pyqtSignal(dict)  # {param_name: new_value}
    reset_requested = pyqtSignal()
    simulation_requested = pyqtSignal(dict)  # {param_name: new_value}
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self._logger = _logger
        
        # 参数状态
        self._parameters: Dict[str, ParameterState] = {}
        self._sliders: Dict[str, ParameterSliderWidget] = {}
        
        # 自动仿真模式
        self._auto_simulation_enabled = False
        
        # 防抖定时器
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._on_debounce_timeout)
        
        # 待应用的参数变更
        self._pending_changes: Dict[str, float] = {}
        
        # 电路文件路径
        self._circuit_file_path: str = ""
        
        # EventBus 引用
        self._event_bus = None
        
        self._setup_ui()
        self._apply_style()
        self._connect_signals()
        self.retranslate_ui()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 顶部工具栏
        self._toolbar = QFrame()
        self._toolbar.setObjectName("tuningToolbar")
        self._toolbar.setFixedHeight(36)
        toolbar_layout = QHBoxLayout(self._toolbar)
        toolbar_layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        toolbar_layout.setSpacing(SPACING_NORMAL)
        
        # 标题
        self._title_label = QLabel()
        self._title_label.setObjectName("tuningTitle")
        toolbar_layout.addWidget(self._title_label)
        
        toolbar_layout.addStretch()
        
        # 自动仿真开关
        self._auto_sim_checkbox = QCheckBox()
        self._auto_sim_checkbox.setObjectName("autoSimCheckbox")
        toolbar_layout.addWidget(self._auto_sim_checkbox)
        
        # 应用按钮
        self._apply_btn = QPushButton()
        self._apply_btn.setObjectName("applyBtn")
        self._apply_btn.setFixedHeight(24)
        toolbar_layout.addWidget(self._apply_btn)
        
        # 重置按钮
        self._reset_btn = QPushButton()
        self._reset_btn.setObjectName("resetBtn")
        self._reset_btn.setFixedHeight(24)
        toolbar_layout.addWidget(self._reset_btn)
        
        layout.addWidget(self._toolbar)
        
        # 滚动区域
        self._scroll_area = QScrollArea()
        self._scroll_area.setObjectName("tuningScrollArea")
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # 参数列表容器
        self._params_container = QWidget()
        self._params_container.setObjectName("paramsContainer")
        self._params_layout = QVBoxLayout(self._params_container)
        self._params_layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        self._params_layout.setSpacing(SPACING_NORMAL)
        self._params_layout.addStretch()
        
        self._scroll_area.setWidget(self._params_container)
        layout.addWidget(self._scroll_area, 1)
        
        # 空状态提示
        self._empty_widget = QFrame()
        self._empty_widget.setObjectName("emptyWidget")
        empty_layout = QVBoxLayout(self._empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self._empty_label = QLabel()
        self._empty_label.setObjectName("emptyLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._empty_label)
        
        self._empty_hint = QLabel()
        self._empty_hint.setObjectName("emptyHint")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._empty_hint)
        
        layout.addWidget(self._empty_widget)
        
        # 初始显示空状态
        self._show_empty_state()
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            TuningPanel {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #tuningToolbar {{
                background-color: {COLOR_BG_PRIMARY};
                border-bottom: 1px solid {COLOR_BORDER};
            }}
            
            #tuningTitle {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
                font-weight: bold;
            }}
            
            #autoSimCheckbox {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #applyBtn {{
                background-color: {COLOR_ACCENT};
                color: white;
                border: none;
                border-radius: {BORDER_RADIUS_SMALL}px;
                padding: 4px 12px;
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #applyBtn:hover {{
                background-color: {COLOR_ACCENT};
                opacity: 0.9;
            }}
            
            #applyBtn:disabled {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_SECONDARY};
            }}
            
            #resetBtn {{
                background-color: transparent;
                color: {COLOR_TEXT_SECONDARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_SMALL}px;
                padding: 4px 12px;
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #resetBtn:hover {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_PRIMARY};
            }}
            
            #tuningScrollArea {{
                background-color: {COLOR_BG_PRIMARY};
                border: none;
            }}
            
            #paramsContainer {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #emptyWidget {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #emptyLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #emptyHint {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
                margin-top: {SPACING_SMALL}px;
            }}
        """)
    
    def _connect_signals(self):
        """连接信号"""
        self._auto_sim_checkbox.toggled.connect(self._on_auto_sim_toggled)
        self._apply_btn.clicked.connect(self._on_apply_clicked)
        self._reset_btn.clicked.connect(self._on_reset_clicked)
    
    def _get_event_bus(self):
        """获取 EventBus"""
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus
    
    # ============================================================
    # 公共方法
    # ============================================================
    
    def load_parameters(self, param_list: list):
        """
        加载可调参数列表
        
        Args:
            param_list: TunableParameter 对象列表
        """
        self.clear()
        
        if not param_list:
            self._show_empty_state()
            return
        
        for param in param_list:
            state = ParameterState(
                name=param.name,
                current_value=param.value,
                original_value=param.value,
                min_value=param.min_value,
                max_value=param.max_value,
                step=param.step,
                unit=param.unit,
                param_type=param.param_type.value if hasattr(param.param_type, 'value') else str(param.param_type),
                line_number=param.line_number,
                element_name=param.element_name,
            )
            self._add_parameter(state)
        
        self._hide_empty_state()
        self._update_buttons_state()
        
        self._logger.info(f"Loaded {len(param_list)} parameters")
    
    def load_from_file(self, file_path: str):
        """
        从电路文件加载参数
        
        Args:
            file_path: 电路文件路径
        """
        self._circuit_file_path = file_path
        
        try:
            from domain.simulation.service.parameter_extractor import parameter_extractor
            
            result = parameter_extractor.extract_from_file(file_path)
            if result.success:
                self.load_parameters(result.parameters)
                
                # 发布事件
                event_bus = self._get_event_bus()
                if event_bus:
                    from shared.event_types import EVENT_PARAMETERS_EXTRACTED
                    event_bus.publish(EVENT_PARAMETERS_EXTRACTED, {
                        "file_path": file_path,
                        "parameter_count": result.count,
                        "parameters": [p.name for p in result.parameters],
                    })
            else:
                self._logger.warning(f"Failed to extract parameters: {result.error_message}")
                self._show_empty_state()
                
        except Exception as e:
            self._logger.error(f"Failed to load parameters from file: {e}")
            self._show_empty_state()
    
    def get_modified_parameters(self) -> Dict[str, float]:
        """
        获取已修改的参数
        
        Returns:
            Dict[str, float]: 参数名到新值的映射
        """
        modified = {}
        for name, slider in self._sliders.items():
            if slider.is_modified:
                modified[name] = slider.current_value
        return modified
    
    def get_all_parameters(self) -> Dict[str, float]:
        """
        获取所有参数当前值
        
        Returns:
            Dict[str, float]: 参数名到当前值的映射
        """
        return {name: slider.current_value for name, slider in self._sliders.items()}
    
    def set_circuit_file(self, file_path: str):
        """设置电路文件路径"""
        self._circuit_file_path = file_path
    
    def set_auto_simulation(self, enabled: bool):
        """设置自动仿真模式"""
        self._auto_simulation_enabled = enabled
        self._auto_sim_checkbox.setChecked(enabled)
    
    def clear(self):
        """清空所有参数"""
        # 移除所有滑块组件
        for slider in self._sliders.values():
            slider.setParent(None)
            slider.deleteLater()
        
        self._sliders.clear()
        self._parameters.clear()
        self._pending_changes.clear()
        
        self._show_empty_state()
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._title_label.setText(self._get_text(
            "tuning.title", "参数调整"
        ))
        self._auto_sim_checkbox.setText(self._get_text(
            "tuning.auto_simulation", "自动仿真"
        ))
        self._apply_btn.setText(self._get_text(
            "tuning.apply", "应用"
        ))
        self._reset_btn.setText(self._get_text(
            "tuning.reset", "重置"
        ))
        self._empty_label.setText(self._get_text(
            "tuning.no_parameters", "暂无可调参数"
        ))
        self._empty_hint.setText(self._get_text(
            "tuning.load_hint", "打开电路文件后，可调参数将显示在此处"
        ))
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _add_parameter(self, param: ParameterState):
        """添加参数滑块"""
        slider = ParameterSliderWidget(param, self)
        slider.value_changed.connect(self._on_parameter_value_changed)
        slider.range_edit_requested.connect(self._on_range_edit_requested)
        
        # 插入到布局中（在 stretch 之前）
        count = self._params_layout.count()
        self._params_layout.insertWidget(count - 1, slider)
        
        self._parameters[param.name] = param
        self._sliders[param.name] = slider
    
    def _on_parameter_value_changed(self, param_name: str, new_value: float):
        """处理参数值变化"""
        self._pending_changes[param_name] = new_value
        self._update_buttons_state()
        
        # 发布事件
        event_bus = self._get_event_bus()
        if event_bus:
            from shared.event_types import EVENT_PARAMETER_VALUE_CHANGED
            param = self._parameters.get(param_name)
            old_value = param.original_value if param else 0.0
            event_bus.publish(EVENT_PARAMETER_VALUE_CHANGED, {
                "param_name": param_name,
                "old_value": old_value,
                "new_value": new_value,
                "source": "slider",
            })
        
        # 发射信号
        self.parameters_changed.emit({param_name: new_value})
        
        # 如果启用自动仿真，启动防抖定时器
        if self._auto_simulation_enabled:
            self._debounce_timer.start(DEBOUNCE_DELAY_MS)
    
    def _on_debounce_timeout(self):
        """防抖定时器超时，触发仿真"""
        if self._pending_changes:
            self._logger.info(f"Auto simulation triggered with {len(self._pending_changes)} changes")
            self.simulation_requested.emit(self._pending_changes.copy())
            
            # 发布事件
            event_bus = self._get_event_bus()
            if event_bus:
                from shared.event_types import EVENT_TUNING_REQUEST_SIMULATION
                event_bus.publish(EVENT_TUNING_REQUEST_SIMULATION, {
                    "changed_params": self._pending_changes.copy(),
                    "trigger_source": "auto_sim",
                })
    
    def _on_auto_sim_toggled(self, checked: bool):
        """自动仿真开关切换"""
        self._auto_simulation_enabled = checked
        
        # 发布事件
        event_bus = self._get_event_bus()
        if event_bus:
            from shared.event_types import EVENT_AUTO_SIMULATION_CHANGED
            event_bus.publish(EVENT_AUTO_SIMULATION_CHANGED, {
                "enabled": checked,
            })
    
    def _on_apply_clicked(self):
        """应用按钮点击"""
        modified = self.get_modified_parameters()
        if modified:
            self._logger.info(f"Applying {len(modified)} parameter changes")
            self.apply_requested.emit(modified)
            
            # 发布事件
            event_bus = self._get_event_bus()
            if event_bus:
                from shared.event_types import EVENT_PARAMETERS_APPLIED
                event_bus.publish(EVENT_PARAMETERS_APPLIED, {
                    "file_path": self._circuit_file_path,
                    "parameters": modified,
                    "success": True,
                })
            
            # 更新原始值
            for name, value in modified.items():
                if name in self._parameters:
                    self._parameters[name].original_value = value
            
            self._pending_changes.clear()
            self._update_buttons_state()
    
    def _on_reset_clicked(self):
        """重置按钮点击"""
        for slider in self._sliders.values():
            slider.reset_to_original()
        
        self._pending_changes.clear()
        self._update_buttons_state()
        self.reset_requested.emit()
    
    def _on_range_edit_requested(self, param_name: str):
        """范围编辑请求"""
        # TODO: 弹出范围编辑对话框
        self._logger.info(f"Range edit requested for: {param_name}")
    
    def _update_buttons_state(self):
        """更新按钮状态"""
        has_modified = any(s.is_modified for s in self._sliders.values())
        self._apply_btn.setEnabled(has_modified)
    
    def _show_empty_state(self):
        """显示空状态"""
        self._scroll_area.hide()
        self._empty_widget.show()
        self._apply_btn.setEnabled(False)
    
    def _hide_empty_state(self):
        """隐藏空状态"""
        self._empty_widget.hide()
        self._scroll_area.show()
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(key, default)
        except ImportError:
            return default


__all__ = [
    "TuningPanel",
    "ParameterSliderWidget",
    "ParameterState",
]
