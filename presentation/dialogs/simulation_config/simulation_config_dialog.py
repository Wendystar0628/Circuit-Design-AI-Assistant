# Simulation Config Dialog
"""
仿真配置对话框

职责：
- 协调各配置标签页，管理对话框整体布局和按钮行为
- 与 SimulationConfigViewModel 集成
- 提供仿真参数配置界面（AC/DC/瞬态/噪声/收敛参数）

触发方式：
- 菜单栏「设置 → 仿真参数配置」

国际化支持：
- 实现 retranslate_ui() 方法
- 所有文本支持中英文切换

被调用方：
- main_window.py（菜单项触发）
"""

import logging
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QComboBox,
)

from presentation.dialogs.simulation_config.simulation_config_view_model import (
    SimulationConfigViewModel,
)


class SimulationConfigDialog(QDialog):
    """
    仿真配置对话框
    
    功能：
    - AC/DC/瞬态/噪声分析参数配置
    - 收敛参数配置
    - 配置校验和持久化
    """
    
    # 信号定义
    config_saved = pyqtSignal()
    """配置保存成功时发射"""
    
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        view_model: Optional[SimulationConfigViewModel] = None,
    ):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # ViewModel
        self._view_model = view_model or SimulationConfigViewModel()
        
        # 项目根目录
        self._project_root: Optional[str] = None
        
        # UI 组件引用
        self._tab_widget: Optional[QTabWidget] = None
        
        # AC 配置组件
        self._ac_start_freq_spin: Optional[QDoubleSpinBox] = None
        self._ac_stop_freq_spin: Optional[QDoubleSpinBox] = None
        self._ac_points_spin: Optional[QSpinBox] = None
        self._ac_sweep_combo: Optional[QComboBox] = None
        
        # DC 配置组件
        self._dc_source_edit: Optional[QLineEdit] = None
        self._dc_start_spin: Optional[QDoubleSpinBox] = None
        self._dc_stop_spin: Optional[QDoubleSpinBox] = None
        self._dc_step_spin: Optional[QDoubleSpinBox] = None
        
        # 瞬态配置组件
        self._tran_step_spin: Optional[QDoubleSpinBox] = None
        self._tran_end_spin: Optional[QDoubleSpinBox] = None
        self._tran_start_spin: Optional[QDoubleSpinBox] = None
        self._tran_max_step_spin: Optional[QDoubleSpinBox] = None
        self._tran_uic_check: Optional[QCheckBox] = None
        
        # 噪声配置组件
        self._noise_output_edit: Optional[QLineEdit] = None
        self._noise_input_edit: Optional[QLineEdit] = None
        self._noise_start_freq_spin: Optional[QDoubleSpinBox] = None
        self._noise_stop_freq_spin: Optional[QDoubleSpinBox] = None
        
        # 收敛配置组件
        self._conv_gmin_spin: Optional[QDoubleSpinBox] = None
        self._conv_abstol_spin: Optional[QDoubleSpinBox] = None
        self._conv_reltol_spin: Optional[QDoubleSpinBox] = None
        self._conv_vntol_spin: Optional[QDoubleSpinBox] = None
        self._conv_itl1_spin: Optional[QSpinBox] = None
        self._conv_itl4_spin: Optional[QSpinBox] = None
        self._global_timeout_spin: Optional[QSpinBox] = None
        self._global_temp_spin: Optional[QDoubleSpinBox] = None
        
        # 按钮
        self._save_btn: Optional[QPushButton] = None
        self._reset_btn: Optional[QPushButton] = None
        self._cancel_btn: Optional[QPushButton] = None
        
        # 状态标签
        self._status_label: Optional[QLabel] = None
        
        # 初始化 UI
        self._setup_dialog()
        self._setup_ui()
        self._connect_signals()
        
        # 初始化 ViewModel
        self._view_model.initialize()
        
        # 应用国际化文本
        self.retranslate_ui()
    
    # ============================================================
    # 公共方法
    # ============================================================
    
    def set_project_root(self, project_root: str) -> None:
        """设置项目根目录"""
        self._project_root = project_root
    
    def load_config(self, project_root: str) -> bool:
        """
        从项目加载配置
        
        Args:
            project_root: 项目根目录
            
        Returns:
            bool: 是否加载成功
        """
        self._project_root = project_root
        success = self._view_model.load_config(project_root)
        if success:
            self._sync_ui_from_view_model()
        return success
    
    def retranslate_ui(self) -> None:
        """更新国际化文本"""
        # 对话框标题
        self.setWindowTitle(self._get_text("sim_config_title", "仿真参数配置"))
        
        # 标签页标题
        if self._tab_widget:
            self._tab_widget.setTabText(
                0, self._get_text("sim_config_ac_tab", "AC 分析")
            )
            self._tab_widget.setTabText(
                1, self._get_text("sim_config_dc_tab", "DC 分析")
            )
            self._tab_widget.setTabText(
                2, self._get_text("sim_config_tran_tab", "瞬态分析")
            )
            self._tab_widget.setTabText(
                3, self._get_text("sim_config_noise_tab", "噪声分析")
            )
            self._tab_widget.setTabText(
                4, self._get_text("sim_config_conv_tab", "收敛参数")
            )
        
        # 按钮文本
        if self._save_btn:
            self._save_btn.setText(self._get_text("btn_save", "保存"))
        if self._reset_btn:
            self._reset_btn.setText(self._get_text("btn_reset_default", "重置默认"))
        if self._cancel_btn:
            self._cancel_btn.setText(self._get_text("btn_cancel", "取消"))
    
    # ============================================================
    # UI 初始化
    # ============================================================
    
    def _setup_dialog(self) -> None:
        """设置对话框基本属性"""
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setMinimumWidth(480)
        self.setMinimumHeight(400)
        self.setModal(True)
    
    def _setup_ui(self) -> None:
        """设置 UI 布局"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        
        # 标签页容器
        self._tab_widget = QTabWidget()
        self._tab_widget.addTab(self._create_ac_tab(), "AC 分析")
        self._tab_widget.addTab(self._create_dc_tab(), "DC 分析")
        self._tab_widget.addTab(self._create_transient_tab(), "瞬态分析")
        self._tab_widget.addTab(self._create_noise_tab(), "噪声分析")
        self._tab_widget.addTab(self._create_convergence_tab(), "收敛参数")
        main_layout.addWidget(self._tab_widget)
        
        # 状态标签
        self._status_label = QLabel()
        self._status_label.setStyleSheet("color: #666;")
        main_layout.addWidget(self._status_label)
        
        # 按钮区域
        main_layout.addWidget(self._create_button_area())
    
    def _create_ac_tab(self) -> QWidget:
        """创建 AC 分析配置标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        
        # 参数组
        group = QGroupBox(self._get_text("sim_config_ac_params", "AC 分析参数"))
        form = QFormLayout(group)
        
        # 起始频率
        self._ac_start_freq_spin = self._create_scientific_spinbox(1e-3, 1e15, 1.0)
        self._ac_start_freq_spin.setSuffix(" Hz")
        form.addRow(
            self._get_text("sim_config_start_freq", "起始频率:"),
            self._ac_start_freq_spin
        )
        
        # 终止频率
        self._ac_stop_freq_spin = self._create_scientific_spinbox(1e-3, 1e15, 1e9)
        self._ac_stop_freq_spin.setSuffix(" Hz")
        form.addRow(
            self._get_text("sim_config_stop_freq", "终止频率:"),
            self._ac_stop_freq_spin
        )
        
        # 每十倍频程点数
        self._ac_points_spin = QSpinBox()
        self._ac_points_spin.setRange(1, 1000)
        self._ac_points_spin.setValue(20)
        form.addRow(
            self._get_text("sim_config_points_per_decade", "每十倍频程点数:"),
            self._ac_points_spin
        )
        
        # 扫描类型
        self._ac_sweep_combo = QComboBox()
        self._ac_sweep_combo.addItem("十倍频程 (dec)", "dec")
        self._ac_sweep_combo.addItem("八倍频程 (oct)", "oct")
        self._ac_sweep_combo.addItem("线性 (lin)", "lin")
        form.addRow(
            self._get_text("sim_config_sweep_type", "扫描类型:"),
            self._ac_sweep_combo
        )
        
        layout.addWidget(group)
        
        # 说明
        hint = QLabel(self._get_text(
            "sim_config_ac_hint",
            "AC 分析用于计算电路的频率响应，包括增益和相位。"
        ))
        hint.setStyleSheet("color: #666; padding: 8px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        
        layout.addStretch()
        return tab
    
    def _create_dc_tab(self) -> QWidget:
        """创建 DC 分析配置标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        
        # 参数组
        group = QGroupBox(self._get_text("sim_config_dc_params", "DC 分析参数"))
        form = QFormLayout(group)
        
        # 扫描源名称
        self._dc_source_edit = QLineEdit()
        self._dc_source_edit.setPlaceholderText("例如: Vin, Vdd")
        form.addRow(
            self._get_text("sim_config_source_name", "扫描源名称:"),
            self._dc_source_edit
        )
        
        # 起始值
        self._dc_start_spin = QDoubleSpinBox()
        self._dc_start_spin.setRange(-1e6, 1e6)
        self._dc_start_spin.setDecimals(6)
        self._dc_start_spin.setValue(0.0)
        self._dc_start_spin.setSuffix(" V")
        form.addRow(
            self._get_text("sim_config_start_value", "起始值:"),
            self._dc_start_spin
        )
        
        # 终止值
        self._dc_stop_spin = QDoubleSpinBox()
        self._dc_stop_spin.setRange(-1e6, 1e6)
        self._dc_stop_spin.setDecimals(6)
        self._dc_stop_spin.setValue(5.0)
        self._dc_stop_spin.setSuffix(" V")
        form.addRow(
            self._get_text("sim_config_stop_value", "终止值:"),
            self._dc_stop_spin
        )
        
        # 步进值
        self._dc_step_spin = QDoubleSpinBox()
        self._dc_step_spin.setRange(1e-12, 1e6)
        self._dc_step_spin.setDecimals(6)
        self._dc_step_spin.setValue(0.1)
        self._dc_step_spin.setSuffix(" V")
        form.addRow(
            self._get_text("sim_config_step", "步进值:"),
            self._dc_step_spin
        )
        
        layout.addWidget(group)
        
        # 说明
        hint = QLabel(self._get_text(
            "sim_config_dc_hint",
            "DC 分析用于扫描直流电源，计算电路的直流工作点和传输特性。"
        ))
        hint.setStyleSheet("color: #666; padding: 8px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        
        layout.addStretch()
        return tab
    
    def _create_transient_tab(self) -> QWidget:
        """创建瞬态分析配置标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        
        # 参数组
        group = QGroupBox(self._get_text("sim_config_tran_params", "瞬态分析参数"))
        form = QFormLayout(group)
        
        # 时间步长
        self._tran_step_spin = self._create_scientific_spinbox(1e-15, 1e3, 1e-6)
        self._tran_step_spin.setSuffix(" s")
        form.addRow(
            self._get_text("sim_config_step_time", "时间步长:"),
            self._tran_step_spin
        )
        
        # 终止时间
        self._tran_end_spin = self._create_scientific_spinbox(1e-15, 1e6, 1e-3)
        self._tran_end_spin.setSuffix(" s")
        form.addRow(
            self._get_text("sim_config_end_time", "终止时间:"),
            self._tran_end_spin
        )
        
        # 起始时间
        self._tran_start_spin = self._create_scientific_spinbox(0, 1e6, 0)
        self._tran_start_spin.setSuffix(" s")
        form.addRow(
            self._get_text("sim_config_start_time", "起始时间:"),
            self._tran_start_spin
        )
        
        # 最大步长
        self._tran_max_step_spin = self._create_scientific_spinbox(0, 1e3, 0)
        self._tran_max_step_spin.setSuffix(" s")
        self._tran_max_step_spin.setSpecialValueText("自动")
        form.addRow(
            self._get_text("sim_config_max_step", "最大步长:"),
            self._tran_max_step_spin
        )
        
        # 使用初始条件
        self._tran_uic_check = QCheckBox(
            self._get_text("sim_config_use_ic", "使用初始条件 (UIC)")
        )
        form.addRow("", self._tran_uic_check)
        
        layout.addWidget(group)
        
        # 说明
        hint = QLabel(self._get_text(
            "sim_config_tran_hint",
            "瞬态分析用于计算电路的时域响应，观察信号随时间的变化。"
        ))
        hint.setStyleSheet("color: #666; padding: 8px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        
        layout.addStretch()
        return tab
    
    def _create_noise_tab(self) -> QWidget:
        """创建噪声分析配置标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        
        # 参数组
        group = QGroupBox(self._get_text("sim_config_noise_params", "噪声分析参数"))
        form = QFormLayout(group)
        
        # 输出节点
        self._noise_output_edit = QLineEdit()
        self._noise_output_edit.setPlaceholderText("例如: out, vout")
        form.addRow(
            self._get_text("sim_config_output_node", "输出节点:"),
            self._noise_output_edit
        )
        
        # 输入源
        self._noise_input_edit = QLineEdit()
        self._noise_input_edit.setPlaceholderText("例如: Vin, Vsig")
        form.addRow(
            self._get_text("sim_config_input_source", "输入源:"),
            self._noise_input_edit
        )
        
        # 起始频率
        self._noise_start_freq_spin = self._create_scientific_spinbox(1e-3, 1e15, 1.0)
        self._noise_start_freq_spin.setSuffix(" Hz")
        form.addRow(
            self._get_text("sim_config_start_freq", "起始频率:"),
            self._noise_start_freq_spin
        )
        
        # 终止频率
        self._noise_stop_freq_spin = self._create_scientific_spinbox(1e-3, 1e15, 1e6)
        self._noise_stop_freq_spin.setSuffix(" Hz")
        form.addRow(
            self._get_text("sim_config_stop_freq", "终止频率:"),
            self._noise_stop_freq_spin
        )
        
        layout.addWidget(group)
        
        # 说明
        hint = QLabel(self._get_text(
            "sim_config_noise_hint",
            "噪声分析用于计算电路的噪声特性，包括输入参考噪声和输出噪声。"
        ))
        hint.setStyleSheet("color: #666; padding: 8px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        
        layout.addStretch()
        return tab

    def _create_convergence_tab(self) -> QWidget:
        """创建收敛参数配置标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        
        # 全局参数组
        global_group = QGroupBox(self._get_text("sim_config_global_params", "全局参数"))
        global_form = QFormLayout(global_group)
        
        # 超时时间
        self._global_timeout_spin = QSpinBox()
        self._global_timeout_spin.setRange(10, 3600)
        self._global_timeout_spin.setValue(300)
        self._global_timeout_spin.setSuffix(" s")
        global_form.addRow(
            self._get_text("sim_config_timeout", "超时时间:"),
            self._global_timeout_spin
        )
        
        # 仿真温度
        self._global_temp_spin = QDoubleSpinBox()
        self._global_temp_spin.setRange(-273.15, 500)
        self._global_temp_spin.setDecimals(2)
        self._global_temp_spin.setValue(27.0)
        self._global_temp_spin.setSuffix(" °C")
        global_form.addRow(
            self._get_text("sim_config_temperature", "仿真温度:"),
            self._global_temp_spin
        )
        
        layout.addWidget(global_group)
        
        # 收敛参数组
        conv_group = QGroupBox(self._get_text("sim_config_conv_params", "收敛参数"))
        conv_form = QFormLayout(conv_group)
        
        # gmin
        self._conv_gmin_spin = self._create_scientific_spinbox(1e-20, 1e-6, 1e-12)
        self._conv_gmin_spin.setSuffix(" S")
        conv_form.addRow("gmin:", self._conv_gmin_spin)
        
        # abstol
        self._conv_abstol_spin = self._create_scientific_spinbox(1e-20, 1e-6, 1e-12)
        self._conv_abstol_spin.setSuffix(" A")
        conv_form.addRow("abstol:", self._conv_abstol_spin)
        
        # reltol
        self._conv_reltol_spin = QDoubleSpinBox()
        self._conv_reltol_spin.setRange(1e-6, 0.1)
        self._conv_reltol_spin.setDecimals(6)
        self._conv_reltol_spin.setValue(1e-3)
        conv_form.addRow("reltol:", self._conv_reltol_spin)
        
        # vntol
        self._conv_vntol_spin = self._create_scientific_spinbox(1e-12, 1e-3, 1e-6)
        self._conv_vntol_spin.setSuffix(" V")
        conv_form.addRow("vntol:", self._conv_vntol_spin)
        
        # itl1
        self._conv_itl1_spin = QSpinBox()
        self._conv_itl1_spin.setRange(10, 10000)
        self._conv_itl1_spin.setValue(100)
        conv_form.addRow(
            self._get_text("sim_config_itl1", "itl1 (DC 迭代限制):"),
            self._conv_itl1_spin
        )
        
        # itl4
        self._conv_itl4_spin = QSpinBox()
        self._conv_itl4_spin.setRange(1, 1000)
        self._conv_itl4_spin.setValue(10)
        conv_form.addRow(
            self._get_text("sim_config_itl4", "itl4 (瞬态迭代限制):"),
            self._conv_itl4_spin
        )
        
        layout.addWidget(conv_group)
        
        # 说明
        hint = QLabel(self._get_text(
            "sim_config_conv_hint",
            "收敛参数影响仿真精度和速度。如遇收敛问题，可尝试增大 gmin 或放宽容差。"
        ))
        hint.setStyleSheet("color: #666; padding: 8px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        
        layout.addStretch()
        return tab
    
    def _create_button_area(self) -> QWidget:
        """创建按钮区域"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 10, 0, 0)
        
        # 重置默认按钮
        self._reset_btn = QPushButton("重置默认")
        self._reset_btn.clicked.connect(self._on_reset_clicked)
        layout.addWidget(self._reset_btn)
        
        layout.addStretch()
        
        # 保存按钮
        self._save_btn = QPushButton("保存")
        self._save_btn.setDefault(True)
        self._save_btn.setStyleSheet(
            "QPushButton { background-color: #4a9eff; color: white; "
            "border: none; border-radius: 4px; padding: 8px 20px; }"
            "QPushButton:hover { background-color: #3d8ce6; }"
        )
        self._save_btn.clicked.connect(self._on_save_clicked)
        layout.addWidget(self._save_btn)
        
        # 取消按钮
        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self._cancel_btn)
        
        return widget
    
    def _create_scientific_spinbox(
        self,
        min_val: float,
        max_val: float,
        default_val: float,
    ) -> QDoubleSpinBox:
        """
        创建支持科学计数法的 SpinBox
        
        Args:
            min_val: 最小值
            max_val: 最大值
            default_val: 默认值
            
        Returns:
            QDoubleSpinBox: 配置好的 SpinBox
        """
        spin = QDoubleSpinBox()
        spin.setRange(min_val, max_val)
        spin.setDecimals(15)
        spin.setValue(default_val)
        # 使用科学计数法显示
        spin.setStepType(QDoubleSpinBox.StepType.AdaptiveDecimalStepType)
        return spin
    
    # ============================================================
    # 信号连接
    # ============================================================
    
    def _connect_signals(self) -> None:
        """连接信号槽"""
        # ViewModel 信号
        self._view_model.config_changed.connect(self._on_config_changed)
        self._view_model.validation_failed.connect(self._on_validation_failed)
        self._view_model.save_completed.connect(self._on_save_completed)
        
        # AC 配置变更
        if self._ac_start_freq_spin:
            self._ac_start_freq_spin.valueChanged.connect(
                lambda v: self._view_model.update_ac_config("start_freq", v)
            )
        if self._ac_stop_freq_spin:
            self._ac_stop_freq_spin.valueChanged.connect(
                lambda v: self._view_model.update_ac_config("stop_freq", v)
            )
        if self._ac_points_spin:
            self._ac_points_spin.valueChanged.connect(
                lambda v: self._view_model.update_ac_config("points_per_decade", v)
            )
        if self._ac_sweep_combo:
            self._ac_sweep_combo.currentIndexChanged.connect(
                lambda: self._view_model.update_ac_config(
                    "sweep_type", self._ac_sweep_combo.currentData()
                )
            )
        
        # DC 配置变更
        if self._dc_source_edit:
            self._dc_source_edit.textChanged.connect(
                lambda v: self._view_model.update_dc_config("source_name", v)
            )
        if self._dc_start_spin:
            self._dc_start_spin.valueChanged.connect(
                lambda v: self._view_model.update_dc_config("start_value", v)
            )
        if self._dc_stop_spin:
            self._dc_stop_spin.valueChanged.connect(
                lambda v: self._view_model.update_dc_config("stop_value", v)
            )
        if self._dc_step_spin:
            self._dc_step_spin.valueChanged.connect(
                lambda v: self._view_model.update_dc_config("step", v)
            )
        
        # 瞬态配置变更
        if self._tran_step_spin:
            self._tran_step_spin.valueChanged.connect(
                lambda v: self._view_model.update_transient_config("step_time", v)
            )
        if self._tran_end_spin:
            self._tran_end_spin.valueChanged.connect(
                lambda v: self._view_model.update_transient_config("end_time", v)
            )
        if self._tran_start_spin:
            self._tran_start_spin.valueChanged.connect(
                lambda v: self._view_model.update_transient_config("start_time", v)
            )
        if self._tran_max_step_spin:
            self._tran_max_step_spin.valueChanged.connect(
                lambda v: self._view_model.update_transient_config(
                    "max_step", v if v > 0 else None
                )
            )
        if self._tran_uic_check:
            self._tran_uic_check.stateChanged.connect(
                lambda s: self._view_model.update_transient_config(
                    "use_initial_conditions", s == Qt.CheckState.Checked.value
                )
            )
        
        # 噪声配置变更
        if self._noise_output_edit:
            self._noise_output_edit.textChanged.connect(
                lambda v: self._view_model.update_noise_config("output_node", v)
            )
        if self._noise_input_edit:
            self._noise_input_edit.textChanged.connect(
                lambda v: self._view_model.update_noise_config("input_source", v)
            )
        if self._noise_start_freq_spin:
            self._noise_start_freq_spin.valueChanged.connect(
                lambda v: self._view_model.update_noise_config("start_freq", v)
            )
        if self._noise_stop_freq_spin:
            self._noise_stop_freq_spin.valueChanged.connect(
                lambda v: self._view_model.update_noise_config("stop_freq", v)
            )
        
        # 收敛配置变更
        if self._conv_gmin_spin:
            self._conv_gmin_spin.valueChanged.connect(
                lambda v: self._view_model.update_convergence_config("gmin", v)
            )
        if self._conv_abstol_spin:
            self._conv_abstol_spin.valueChanged.connect(
                lambda v: self._view_model.update_convergence_config("abstol", v)
            )
        if self._conv_reltol_spin:
            self._conv_reltol_spin.valueChanged.connect(
                lambda v: self._view_model.update_convergence_config("reltol", v)
            )
        if self._conv_vntol_spin:
            self._conv_vntol_spin.valueChanged.connect(
                lambda v: self._view_model.update_convergence_config("vntol", v)
            )
        if self._conv_itl1_spin:
            self._conv_itl1_spin.valueChanged.connect(
                lambda v: self._view_model.update_convergence_config("itl1", v)
            )
        if self._conv_itl4_spin:
            self._conv_itl4_spin.valueChanged.connect(
                lambda v: self._view_model.update_convergence_config("itl4", v)
            )
        
        # 全局配置变更
        if self._global_timeout_spin:
            self._global_timeout_spin.valueChanged.connect(
                lambda v: self._view_model.update_global_config("timeout_seconds", v)
            )
        if self._global_temp_spin:
            self._global_temp_spin.valueChanged.connect(
                lambda v: self._view_model.update_global_config("temperature", v)
            )
    
    # ============================================================
    # 数据同步
    # ============================================================
    
    def _sync_ui_from_view_model(self) -> None:
        """从 ViewModel 同步数据到 UI"""
        # 阻止信号触发
        self._block_signals(True)
        
        try:
            # AC 配置
            ac = self._view_model.ac_config
            if self._ac_start_freq_spin:
                self._ac_start_freq_spin.setValue(ac.start_freq)
            if self._ac_stop_freq_spin:
                self._ac_stop_freq_spin.setValue(ac.stop_freq)
            if self._ac_points_spin:
                self._ac_points_spin.setValue(ac.points_per_decade)
            if self._ac_sweep_combo:
                idx = self._ac_sweep_combo.findData(ac.sweep_type)
                if idx >= 0:
                    self._ac_sweep_combo.setCurrentIndex(idx)
            
            # DC 配置
            dc = self._view_model.dc_config
            if self._dc_source_edit:
                self._dc_source_edit.setText(dc.source_name)
            if self._dc_start_spin:
                self._dc_start_spin.setValue(dc.start_value)
            if self._dc_stop_spin:
                self._dc_stop_spin.setValue(dc.stop_value)
            if self._dc_step_spin:
                self._dc_step_spin.setValue(dc.step)
            
            # 瞬态配置
            tran = self._view_model.transient_config
            if self._tran_step_spin:
                self._tran_step_spin.setValue(tran.step_time)
            if self._tran_end_spin:
                self._tran_end_spin.setValue(tran.end_time)
            if self._tran_start_spin:
                self._tran_start_spin.setValue(tran.start_time)
            if self._tran_max_step_spin:
                self._tran_max_step_spin.setValue(tran.max_step or 0)
            if self._tran_uic_check:
                self._tran_uic_check.setChecked(tran.use_initial_conditions)
            
            # 噪声配置
            noise = self._view_model.noise_config
            if self._noise_output_edit:
                self._noise_output_edit.setText(noise.output_node)
            if self._noise_input_edit:
                self._noise_input_edit.setText(noise.input_source)
            if self._noise_start_freq_spin:
                self._noise_start_freq_spin.setValue(noise.start_freq)
            if self._noise_stop_freq_spin:
                self._noise_stop_freq_spin.setValue(noise.stop_freq)
            
            # 收敛配置
            conv = self._view_model.convergence_config
            if self._conv_gmin_spin:
                self._conv_gmin_spin.setValue(conv.gmin)
            if self._conv_abstol_spin:
                self._conv_abstol_spin.setValue(conv.abstol)
            if self._conv_reltol_spin:
                self._conv_reltol_spin.setValue(conv.reltol)
            if self._conv_vntol_spin:
                self._conv_vntol_spin.setValue(conv.vntol)
            if self._conv_itl1_spin:
                self._conv_itl1_spin.setValue(conv.itl1)
            if self._conv_itl4_spin:
                self._conv_itl4_spin.setValue(conv.itl4)
            
            # 全局配置
            glob = self._view_model.global_config
            if self._global_timeout_spin:
                self._global_timeout_spin.setValue(glob.timeout_seconds)
            if self._global_temp_spin:
                self._global_temp_spin.setValue(glob.temperature)
                
        finally:
            self._block_signals(False)
    
    def _block_signals(self, block: bool) -> None:
        """阻止/恢复所有输入组件的信号"""
        widgets = [
            self._ac_start_freq_spin, self._ac_stop_freq_spin,
            self._ac_points_spin, self._ac_sweep_combo,
            self._dc_source_edit, self._dc_start_spin,
            self._dc_stop_spin, self._dc_step_spin,
            self._tran_step_spin, self._tran_end_spin,
            self._tran_start_spin, self._tran_max_step_spin,
            self._tran_uic_check,
            self._noise_output_edit, self._noise_input_edit,
            self._noise_start_freq_spin, self._noise_stop_freq_spin,
            self._conv_gmin_spin, self._conv_abstol_spin,
            self._conv_reltol_spin, self._conv_vntol_spin,
            self._conv_itl1_spin, self._conv_itl4_spin,
            self._global_timeout_spin, self._global_temp_spin,
        ]
        for w in widgets:
            if w:
                w.blockSignals(block)
    
    # ============================================================
    # 事件处理
    # ============================================================
    
    def _on_save_clicked(self) -> None:
        """保存按钮点击"""
        if not self._project_root:
            QMessageBox.warning(
                self,
                self._get_text("warning", "警告"),
                self._get_text("sim_config_no_project", "未设置项目根目录，无法保存配置。")
            )
            return
        
        self._view_model.save_config(self._project_root)
    
    def _on_reset_clicked(self) -> None:
        """重置按钮点击"""
        reply = QMessageBox.question(
            self,
            self._get_text("confirm", "确认"),
            self._get_text("sim_config_reset_confirm", "确定要重置为默认配置吗？"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self._view_model.reset_to_default()
            self._sync_ui_from_view_model()
            self._update_status(self._get_text("sim_config_reset_done", "已重置为默认配置"))
    
    def _on_config_changed(self) -> None:
        """配置变更处理"""
        self._update_status(self._get_text("sim_config_modified", "配置已修改（未保存）"))
    
    def _on_validation_failed(self, errors: List[str]) -> None:
        """校验失败处理"""
        error_text = "\n".join(f"• {e}" for e in errors)
        QMessageBox.warning(
            self,
            self._get_text("validation_error", "校验错误"),
            self._get_text("sim_config_validation_failed", "配置校验失败：\n") + error_text
        )
    
    def _on_save_completed(self, success: bool) -> None:
        """保存完成处理"""
        if success:
            self._update_status(self._get_text("sim_config_saved", "配置已保存"))
            self.config_saved.emit()
            self.accept()
        else:
            self._update_status(self._get_text("sim_config_save_failed", "保存失败"))
    
    def _update_status(self, message: str) -> None:
        """更新状态标签"""
        if self._status_label:
            self._status_label.setText(message)
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_I18N_MANAGER
            i18n = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            if i18n:
                return i18n.get_text(key, default)
        except Exception:
            pass
        return default


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SimulationConfigDialog",
]
