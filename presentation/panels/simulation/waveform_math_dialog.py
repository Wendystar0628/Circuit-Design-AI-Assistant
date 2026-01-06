# WaveformMathDialog - Waveform Mathematical Operations Dialog
"""
波形数学运算对话框

职责：
- 提供波形数学运算的 UI 界面
- 支持表达式输入和预设运算按钮
- 显示运算结果预览
- 与 WaveformMathService 集成执行计算

设计参考：借鉴 LTspice 的波形数学运算功能

使用示例：
    from presentation.panels.simulation.waveform_math_dialog import WaveformMathDialog
    
    dialog = WaveformMathDialog(parent, simulation_result)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        result = dialog.get_result()
        # 使用计算结果
"""

import logging
from typing import Callable, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QGroupBox,
    QFrame,
    QDialogButtonBox,
    QCompleter,
    QMessageBox,
    QSizePolicy,
)

from domain.simulation.models.simulation_result import SimulationResult
from domain.simulation.data.waveform_data_service import WaveformData
from domain.simulation.data.waveform_math_service import (
    waveform_math_service,
    WaveformMathService,
    MathResult,
    PresetOperation,
    PRESET_OPERATIONS,
)
from resources.theme import (
    COLOR_BG_PRIMARY,
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_BORDER,
    COLOR_ACCENT,
    COLOR_SUCCESS,
    COLOR_ERROR,
    FONT_SIZE_NORMAL,
    FONT_SIZE_SMALL,
    SPACING_SMALL,
    SPACING_NORMAL,
    SPACING_LARGE,
    BORDER_RADIUS_NORMAL,
)


# ============================================================
# 常量定义
# ============================================================

DIALOG_MIN_WIDTH = 500
DIALOG_MIN_HEIGHT = 400

# 预设运算按钮每行数量
PRESET_BUTTONS_PER_ROW = 5


# ============================================================
# WaveformMathDialog - 波形数学运算对话框
# ============================================================

class WaveformMathDialog(QDialog):
    """
    波形数学运算对话框
    
    提供波形数学运算的 UI 界面，支持：
    - 表达式输入（带信号名自动补全）
    - 预设运算按钮
    - 信号选择下拉框
    - 结果预览
    
    Signals:
        result_ready: 运算结果就绪时发出
    """
    
    result_ready = pyqtSignal(object)  # WaveformData
    
    def __init__(
        self,
        parent=None,
        simulation_result: Optional[SimulationResult] = None
    ):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        self._math_service: WaveformMathService = waveform_math_service
        
        # 仿真结果
        self._simulation_result = simulation_result
        
        # 可用信号列表
        self._available_signals: List[str] = []
        if simulation_result:
            self._available_signals = self._math_service.get_available_signals(
                simulation_result
            )
        
        # 计算结果
        self._result: Optional[WaveformData] = None
        
        # 初始化 UI
        self._setup_ui()
        self._setup_connections()
        self._apply_style()
        self._update_signal_combos()
        
        # 初始化文本
        self.retranslate_ui()
    
    def _setup_ui(self):
        """初始化 UI 组件"""
        self.setWindowTitle("波形数学运算")
        self.setMinimumSize(DIALOG_MIN_WIDTH, DIALOG_MIN_HEIGHT)
        self.setModal(True)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(
            SPACING_LARGE, SPACING_LARGE, 
            SPACING_LARGE, SPACING_LARGE
        )
        main_layout.setSpacing(SPACING_NORMAL)
        
        # 信号选择区域
        self._setup_signal_selection(main_layout)
        
        # 预设运算按钮区域
        self._setup_preset_buttons(main_layout)
        
        # 表达式输入区域
        self._setup_expression_input(main_layout)
        
        # 结果名称输入
        self._setup_result_name(main_layout)
        
        # 预览区域
        self._setup_preview(main_layout)
        
        # 按钮栏
        self._setup_buttons(main_layout)
    
    def _setup_signal_selection(self, parent_layout: QVBoxLayout):
        """设置信号选择区域"""
        group = QGroupBox()
        group.setObjectName("signalGroup")
        layout = QHBoxLayout(group)
        layout.setContentsMargins(
            SPACING_NORMAL, SPACING_NORMAL,
            SPACING_NORMAL, SPACING_NORMAL
        )
        layout.setSpacing(SPACING_NORMAL)
        
        # 信号 1
        self._signal1_label = QLabel("信号 1:")
        self._signal1_combo = QComboBox()
        self._signal1_combo.setMinimumWidth(150)
        self._signal1_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed
        )
        
        layout.addWidget(self._signal1_label)
        layout.addWidget(self._signal1_combo)
        
        layout.addSpacing(SPACING_LARGE)
        
        # 信号 2
        self._signal2_label = QLabel("信号 2:")
        self._signal2_combo = QComboBox()
        self._signal2_combo.setMinimumWidth(150)
        self._signal2_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed
        )
        
        layout.addWidget(self._signal2_label)
        layout.addWidget(self._signal2_combo)
        
        parent_layout.addWidget(group)
    
    def _setup_preset_buttons(self, parent_layout: QVBoxLayout):
        """设置预设运算按钮区域"""
        group = QGroupBox()
        group.setObjectName("presetGroup")
        layout = QGridLayout(group)
        layout.setContentsMargins(
            SPACING_NORMAL, SPACING_NORMAL,
            SPACING_NORMAL, SPACING_NORMAL
        )
        layout.setSpacing(SPACING_SMALL)
        
        self._preset_buttons: List[QPushButton] = []
        
        for i, preset in enumerate(PRESET_OPERATIONS):
            btn = QPushButton(preset.display_name)
            btn.setObjectName("presetButton")
            btn.setToolTip(preset.description)
            btn.setProperty("preset_name", preset.name)
            btn.clicked.connect(lambda checked, p=preset: self._on_preset_clicked(p))
            
            row = i // PRESET_BUTTONS_PER_ROW
            col = i % PRESET_BUTTONS_PER_ROW
            layout.addWidget(btn, row, col)
            
            self._preset_buttons.append(btn)
        
        parent_layout.addWidget(group)
    
    def _setup_expression_input(self, parent_layout: QVBoxLayout):
        """设置表达式输入区域"""
        group = QGroupBox()
        group.setObjectName("expressionGroup")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(
            SPACING_NORMAL, SPACING_NORMAL,
            SPACING_NORMAL, SPACING_NORMAL
        )
        layout.setSpacing(SPACING_SMALL)
        
        # 标签
        self._expression_label = QLabel("表达式:")
        layout.addWidget(self._expression_label)
        
        # 输入框
        self._expression_input = QLineEdit()
        self._expression_input.setObjectName("expressionInput")
        self._expression_input.setPlaceholderText(
            "例如: V(out) - V(in), db(V(out)/V(in)), deriv(V(out))"
        )
        
        # 设置自动补全
        if self._available_signals:
            completer = QCompleter(self._available_signals)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self._expression_input.setCompleter(completer)
        
        layout.addWidget(self._expression_input)
        
        # 帮助文本
        self._help_label = QLabel()
        self._help_label.setObjectName("helpLabel")
        self._help_label.setWordWrap(True)
        layout.addWidget(self._help_label)
        
        parent_layout.addWidget(group)
    
    def _setup_result_name(self, parent_layout: QVBoxLayout):
        """设置结果名称输入"""
        layout = QHBoxLayout()
        layout.setSpacing(SPACING_NORMAL)
        
        self._result_name_label = QLabel("结果名称:")
        self._result_name_input = QLineEdit()
        self._result_name_input.setObjectName("resultNameInput")
        self._result_name_input.setText("Math Result")
        self._result_name_input.setMaximumWidth(200)
        
        layout.addWidget(self._result_name_label)
        layout.addWidget(self._result_name_input)
        layout.addStretch()
        
        parent_layout.addLayout(layout)
    
    def _setup_preview(self, parent_layout: QVBoxLayout):
        """设置预览区域"""
        group = QGroupBox()
        group.setObjectName("previewGroup")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(
            SPACING_NORMAL, SPACING_NORMAL,
            SPACING_NORMAL, SPACING_NORMAL
        )
        
        # 预览标签
        self._preview_label = QLabel()
        self._preview_label.setObjectName("previewLabel")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumHeight(60)
        layout.addWidget(self._preview_label)
        
        # 预览按钮
        self._preview_btn = QPushButton()
        self._preview_btn.setObjectName("previewButton")
        self._preview_btn.clicked.connect(self._on_preview)
        layout.addWidget(self._preview_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        parent_layout.addWidget(group)
    
    def _setup_buttons(self, parent_layout: QVBoxLayout):
        """设置按钮栏"""
        button_box = QDialogButtonBox()
        button_box.setObjectName("buttonBox")
        
        self._ok_btn = button_box.addButton(QDialogButtonBox.StandardButton.Ok)
        self._cancel_btn = button_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._apply_btn = button_box.addButton(QDialogButtonBox.StandardButton.Apply)
        
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        self._apply_btn.clicked.connect(self._on_apply)
        
        parent_layout.addWidget(button_box)
    
    def _setup_connections(self):
        """设置信号连接"""
        self._expression_input.textChanged.connect(self._on_expression_changed)
        self._signal1_combo.currentTextChanged.connect(self._on_signal_changed)
        self._signal2_combo.currentTextChanged.connect(self._on_signal_changed)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            WaveformMathDialog {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            QGroupBox {{
                background-color: {COLOR_BG_SECONDARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                margin-top: 8px;
                padding-top: 8px;
            }}
            
            QGroupBox::title {{
                color: {COLOR_TEXT_PRIMARY};
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
            
            QLabel {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #helpLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            QComboBox {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 4px 8px;
                min-height: 24px;
            }}
            
            QComboBox:hover {{
                border-color: {COLOR_ACCENT};
            }}
            
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            
            #presetButton {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 6px 12px;
                min-width: 50px;
                font-weight: bold;
            }}
            
            #presetButton:hover {{
                background-color: {COLOR_ACCENT};
                color: white;
                border-color: {COLOR_ACCENT};
            }}
            
            #expressionInput {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 8px;
                font-family: monospace;
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #expressionInput:focus {{
                border-color: {COLOR_ACCENT};
            }}
            
            #resultNameInput {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 4px 8px;
            }}
            
            #previewLabel {{
                background-color: {COLOR_BG_TERTIARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 8px;
                font-family: monospace;
            }}
            
            #previewButton {{
                background-color: {COLOR_ACCENT};
                color: white;
                border: none;
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 6px 16px;
            }}
            
            #previewButton:hover {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_ACCENT};
                border: 1px solid {COLOR_ACCENT};
            }}
            
            QPushButton {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 6px 16px;
                min-width: 80px;
            }}
            
            QPushButton:hover {{
                background-color: {COLOR_ACCENT};
                color: white;
                border-color: {COLOR_ACCENT};
            }}
        """)
    
    def _update_signal_combos(self):
        """更新信号下拉框"""
        self._signal1_combo.clear()
        self._signal2_combo.clear()
        
        self._signal1_combo.addItems(self._available_signals)
        self._signal2_combo.addItems(self._available_signals)
        
        # 默认选择前两个信号
        if len(self._available_signals) >= 2:
            self._signal1_combo.setCurrentIndex(0)
            self._signal2_combo.setCurrentIndex(1)
    
    # ============================================================
    # 公共方法
    # ============================================================
    
    def set_simulation_result(self, result: SimulationResult):
        """
        设置仿真结果
        
        Args:
            result: 仿真结果对象
        """
        self._simulation_result = result
        self._available_signals = self._math_service.get_available_signals(result)
        self._update_signal_combos()
        
        # 更新自动补全
        if self._available_signals:
            completer = QCompleter(self._available_signals)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self._expression_input.setCompleter(completer)
    
    def get_result(self) -> Optional[WaveformData]:
        """
        获取计算结果
        
        Returns:
            Optional[WaveformData]: 计算结果，若未计算则返回 None
        """
        return self._result
    
    def get_expression(self) -> str:
        """
        获取当前表达式
        
        Returns:
            str: 表达式字符串
        """
        return self._expression_input.text().strip()
    
    def set_expression(self, expression: str):
        """
        设置表达式
        
        Args:
            expression: 表达式字符串
        """
        self._expression_input.setText(expression)
    
    # ============================================================
    # 事件处理
    # ============================================================
    
    def _on_preset_clicked(self, preset: PresetOperation):
        """预设运算按钮点击"""
        signal1 = self._signal1_combo.currentText()
        signal2 = self._signal2_combo.currentText()
        
        if not signal1:
            return
        
        if preset.requires_two_signals and not signal2:
            QMessageBox.warning(
                self,
                "警告",
                "此运算需要选择两个信号"
            )
            return
        
        expression = self._math_service.build_expression(
            preset, signal1, signal2 if preset.requires_two_signals else None
        )
        self._expression_input.setText(expression)
    
    def _on_expression_changed(self, text: str):
        """表达式变化"""
        # 清除预览
        self._preview_label.setText("")
        self._preview_label.setStyleSheet("")
    
    def _on_signal_changed(self, text: str):
        """信号选择变化"""
        pass
    
    def _on_preview(self):
        """预览按钮点击"""
        if not self._simulation_result:
            self._show_preview_error("无仿真数据")
            return
        
        expression = self.get_expression()
        if not expression:
            self._show_preview_error("请输入表达式")
            return
        
        # 验证表达式
        valid, error_msg = self._math_service.validate_expression(
            self._simulation_result, expression
        )
        
        if not valid:
            self._show_preview_error(error_msg)
            return
        
        # 执行计算
        result_name = self._result_name_input.text().strip() or "Math Result"
        math_result = self._math_service.evaluate(
            self._simulation_result, expression, result_name
        )
        
        if math_result.success and math_result.data:
            self._result = math_result.data
            self._show_preview_success(math_result.data)
        else:
            self._show_preview_error(math_result.error_message or "计算失败")
    
    def _on_apply(self):
        """应用按钮点击"""
        self._on_preview()
        if self._result:
            self.result_ready.emit(self._result)
    
    def _on_accept(self):
        """确定按钮点击"""
        self._on_preview()
        if self._result:
            self.result_ready.emit(self._result)
            self.accept()
        else:
            QMessageBox.warning(
                self,
                "警告",
                "请先预览并确认计算结果"
            )
    
    def _show_preview_success(self, data: WaveformData):
        """显示预览成功"""
        stats = f"点数: {data.point_count}\n"
        stats += f"X 范围: [{data.x_range[0]:.4g}, {data.x_range[1]:.4g}]\n"
        stats += f"Y 范围: [{data.y_range[0]:.4g}, {data.y_range[1]:.4g}]"
        
        self._preview_label.setText(stats)
        self._preview_label.setStyleSheet(f"color: {COLOR_SUCCESS};")
    
    def _show_preview_error(self, message: str):
        """显示预览错误"""
        self._preview_label.setText(f"错误: {message}")
        self._preview_label.setStyleSheet(f"color: {COLOR_ERROR};")
        self._result = None
    
    # ============================================================
    # 国际化支持
    # ============================================================
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self.setWindowTitle(self._tr("波形数学运算"))
        
        self._signal1_label.setText(self._tr("信号 1:"))
        self._signal2_label.setText(self._tr("信号 2:"))
        self._expression_label.setText(self._tr("表达式:"))
        self._result_name_label.setText(self._tr("结果名称:"))
        self._preview_btn.setText(self._tr("预览"))
        
        self._help_label.setText(self._tr(
            "支持的运算: +, -, *, /, abs(), sqrt(), log(), log10(), "
            "deriv(), integ(), db(), phase()\n"
            "示例: V(out) - V(in), db(V(out)/V(in)), deriv(V(out))"
        ))
        
        self._ok_btn.setText(self._tr("确定"))
        self._cancel_btn.setText(self._tr("取消"))
        self._apply_btn.setText(self._tr("应用"))
    
    def _tr(self, text: str) -> str:
        """翻译文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(f"waveform_math_dialog.{text}", default=text)
        except ImportError:
            return text


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "WaveformMathDialog",
]
