# Design Goals Dialog - Design Goals Editor
"""
设计目标编辑对话框

职责：
- 展示当前项目的设计目标列表
- 支持添加/编辑/删除设计目标
- 支持设置约束类型、目标值、权重等参数
- 与 DesignGoalsManager 集成进行数据持久化

被调用方：
- action_handlers.py（设计菜单 → 设计目标）
"""

from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QLabel,
    QGroupBox,
    QMessageBox,
    QWidget,
    QHeaderView,
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QFormLayout,
    QDialogButtonBox,
    QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from domain.design.design_goals import (
    DesignGoal,
    DesignGoalsManager,
    ConstraintType,
    SUPPORTED_METRICS,
    get_supported_metric_identifiers,
)


class GoalEditDialog(QDialog):
    """单个设计目标编辑对话框"""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        goal: Optional[DesignGoal] = None,
        is_edit: bool = False
    ):
        super().__init__(parent)
        self._goal = goal
        self._is_edit = is_edit
        self._i18n_manager = None
        
        self._identifier_combo: Optional[QComboBox] = None
        self._identifier_edit: Optional[QLineEdit] = None
        self._name_edit: Optional[QLineEdit] = None
        self._target_spin: Optional[QDoubleSpinBox] = None
        self._unit_edit: Optional[QLineEdit] = None
        self._constraint_combo: Optional[QComboBox] = None
        self._weight_spin: Optional[QDoubleSpinBox] = None
        self._tolerance_spin: Optional[QDoubleSpinBox] = None
        self._range_max_spin: Optional[QDoubleSpinBox] = None
        self._description_edit: Optional[QLineEdit] = None
        
        self._setup_dialog()
        self._setup_ui()
        self._load_goal_data()
        self.retranslate_ui()

    @property
    def i18n_manager(self):
        if self._i18n_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_I18N_MANAGER
                self._i18n_manager = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            except Exception:
                pass
        return self._i18n_manager

    def _get_text(self, key: str, default: Optional[str] = None) -> str:
        if self.i18n_manager:
            return self.i18n_manager.get_text(key, default)
        return default if default else key

    def _setup_dialog(self):
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setMinimumWidth(500)
        self.setModal(True)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        form_layout = QFormLayout()
        form_layout.setSpacing(8)
        
        # 指标标识符（预设或自定义）
        id_layout = QHBoxLayout()
        self._identifier_combo = QComboBox()
        self._identifier_combo.addItem("-- 选择预设指标 --", "")
        for identifier in get_supported_metric_identifiers():
            info = SUPPORTED_METRICS[identifier]
            self._identifier_combo.addItem(f"{info['name']} ({identifier})", identifier)
        self._identifier_combo.currentIndexChanged.connect(self._on_preset_selected)
        id_layout.addWidget(self._identifier_combo, 2)
        
        self._identifier_edit = QLineEdit()
        self._identifier_edit.setPlaceholderText("自定义标识符")
        id_layout.addWidget(self._identifier_edit, 1)
        form_layout.addRow("标识符:", id_layout)
        
        # 显示名称
        self._name_edit = QLineEdit()
        form_layout.addRow("显示名称:", self._name_edit)
        
        # 目标值和单位
        value_layout = QHBoxLayout()
        self._target_spin = QDoubleSpinBox()
        self._target_spin.setRange(-1e12, 1e12)
        self._target_spin.setDecimals(6)
        value_layout.addWidget(self._target_spin, 3)
        
        self._unit_edit = QLineEdit()
        self._unit_edit.setMaximumWidth(80)
        self._unit_edit.setPlaceholderText("单位")
        value_layout.addWidget(self._unit_edit, 1)
        form_layout.addRow("目标值:", value_layout)
        
        # 约束类型
        self._constraint_combo = QComboBox()
        self._constraint_combo.addItem("最小值 (≥)", ConstraintType.MINIMUM.value)
        self._constraint_combo.addItem("最大值 (≤)", ConstraintType.MAXIMUM.value)
        self._constraint_combo.addItem("精确值 (=)", ConstraintType.EXACT.value)
        self._constraint_combo.addItem("范围", ConstraintType.RANGE.value)
        self._constraint_combo.addItem("最小化优化", ConstraintType.MINIMIZE.value)
        self._constraint_combo.addItem("最大化优化", ConstraintType.MAXIMIZE.value)
        self._constraint_combo.currentIndexChanged.connect(self._on_constraint_changed)
        form_layout.addRow("约束类型:", self._constraint_combo)
        
        # 范围上限（仅 RANGE 类型显示）
        self._range_max_spin = QDoubleSpinBox()
        self._range_max_spin.setRange(-1e12, 1e12)
        self._range_max_spin.setDecimals(6)
        self._range_max_label = QLabel("范围上限:")
        form_layout.addRow(self._range_max_label, self._range_max_spin)
        
        # 容差百分比（仅 EXACT 类型显示）
        self._tolerance_spin = QDoubleSpinBox()
        self._tolerance_spin.setRange(0, 100)
        self._tolerance_spin.setDecimals(2)
        self._tolerance_spin.setValue(5.0)
        self._tolerance_spin.setSuffix(" %")
        self._tolerance_label = QLabel("容差:")
        form_layout.addRow(self._tolerance_label, self._tolerance_spin)
        
        # 权重
        self._weight_spin = QDoubleSpinBox()
        self._weight_spin.setRange(0, 1)
        self._weight_spin.setDecimals(2)
        self._weight_spin.setSingleStep(0.1)
        self._weight_spin.setValue(1.0)
        form_layout.addRow("权重 (0-1):", self._weight_spin)
        
        # 描述
        self._description_edit = QLineEdit()
        self._description_edit.setPlaceholderText("可选描述")
        form_layout.addRow("描述:", self._description_edit)
        
        layout.addLayout(form_layout)
        
        # 按钮
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        # 初始化约束相关控件可见性
        self._on_constraint_changed()

    def _on_preset_selected(self, index: int):
        """预设指标选择变更"""
        identifier = self._identifier_combo.currentData()
        if identifier and identifier in SUPPORTED_METRICS:
            info = SUPPORTED_METRICS[identifier]
            self._identifier_edit.setText(identifier)
            self._name_edit.setText(info["name"])
            self._unit_edit.setText(info["unit"])
            
            # 设置默认约束类型
            default_constraint = info.get("default_constraint", "minimum")
            for i in range(self._constraint_combo.count()):
                if self._constraint_combo.itemData(i) == default_constraint:
                    self._constraint_combo.setCurrentIndex(i)
                    break

    def _on_constraint_changed(self):
        """约束类型变更"""
        constraint = self._constraint_combo.currentData()
        
        # 范围上限仅在 RANGE 类型显示
        is_range = constraint == ConstraintType.RANGE.value
        self._range_max_label.setVisible(is_range)
        self._range_max_spin.setVisible(is_range)
        
        # 容差仅在 EXACT 类型显示
        is_exact = constraint == ConstraintType.EXACT.value
        self._tolerance_label.setVisible(is_exact)
        self._tolerance_spin.setVisible(is_exact)

    def _load_goal_data(self):
        """加载目标数据到表单"""
        if self._goal is None:
            return
        
        # 设置标识符
        self._identifier_edit.setText(self._goal.identifier)
        for i in range(self._identifier_combo.count()):
            if self._identifier_combo.itemData(i) == self._goal.identifier:
                self._identifier_combo.setCurrentIndex(i)
                break
        
        self._name_edit.setText(self._goal.name)
        self._target_spin.setValue(self._goal.target_value)
        self._unit_edit.setText(self._goal.unit)
        self._weight_spin.setValue(self._goal.weight)
        self._tolerance_spin.setValue(self._goal.tolerance_percent)
        self._description_edit.setText(self._goal.description)
        
        if self._goal.range_max is not None:
            self._range_max_spin.setValue(self._goal.range_max)
        
        # 设置约束类型
        for i in range(self._constraint_combo.count()):
            if self._constraint_combo.itemData(i) == self._goal.constraint_type.value:
                self._constraint_combo.setCurrentIndex(i)
                break

    def _on_accept(self):
        """确认按钮点击"""
        identifier = self._identifier_edit.text().strip()
        if not identifier:
            QMessageBox.warning(self, "警告", "请输入标识符")
            return
        
        name = self._name_edit.text().strip()
        if not name:
            name = identifier
        
        self.accept()

    def get_goal(self) -> DesignGoal:
        """获取编辑后的目标"""
        constraint_value = self._constraint_combo.currentData()
        constraint_type = ConstraintType(constraint_value)
        
        range_max = None
        if constraint_type == ConstraintType.RANGE:
            range_max = self._range_max_spin.value()
        
        return DesignGoal(
            identifier=self._identifier_edit.text().strip(),
            name=self._name_edit.text().strip() or self._identifier_edit.text().strip(),
            target_value=self._target_spin.value(),
            unit=self._unit_edit.text().strip(),
            constraint_type=constraint_type,
            weight=self._weight_spin.value(),
            tolerance_percent=self._tolerance_spin.value(),
            range_max=range_max,
            description=self._description_edit.text().strip(),
        )

    def retranslate_ui(self):
        """更新界面文本"""
        title = "编辑设计目标" if self._is_edit else "添加设计目标"
        self.setWindowTitle(self._get_text("dialog.goal_edit.title", title))



class DesignGoalsDialog(QDialog):
    """
    设计目标编辑对话框
    
    展示和编辑项目的设计目标列表。
    """
    
    goals_changed = pyqtSignal()
    """设计目标变更信号"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._manager: Optional[DesignGoalsManager] = None
        self._project_root: Optional[str] = None
        self._i18n_manager = None
        
        self._table: Optional[QTableWidget] = None
        self._circuit_type_edit: Optional[QLineEdit] = None
        self._description_edit: Optional[QLineEdit] = None
        self._score_label: Optional[QLabel] = None
        
        self._setup_dialog()
        self._setup_ui()
        self.retranslate_ui()

    @property
    def i18n_manager(self):
        if self._i18n_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_I18N_MANAGER
                self._i18n_manager = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            except Exception:
                pass
        return self._i18n_manager

    def _get_text(self, key: str, default: Optional[str] = None) -> str:
        if self.i18n_manager:
            return self.i18n_manager.get_text(key, default)
        return default if default else key

    def _setup_dialog(self):
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setMinimumSize(700, 500)
        self.setModal(True)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        # 项目信息区域
        info_group = QGroupBox("项目信息")
        info_layout = QFormLayout(info_group)
        
        self._circuit_type_edit = QLineEdit()
        self._circuit_type_edit.setPlaceholderText("如: amplifier, filter, ldo")
        info_layout.addRow("电路类型:", self._circuit_type_edit)
        
        self._description_edit = QLineEdit()
        self._description_edit.setPlaceholderText("设计需求描述")
        info_layout.addRow("设计描述:", self._description_edit)
        
        layout.addWidget(info_group)
        
        # 目标列表区域
        goals_group = QGroupBox("设计目标")
        goals_layout = QVBoxLayout(goals_group)
        
        # 工具栏
        toolbar = QHBoxLayout()
        
        add_btn = QPushButton("添加")
        add_btn.clicked.connect(self._on_add_goal)
        toolbar.addWidget(add_btn)
        
        edit_btn = QPushButton("编辑")
        edit_btn.clicked.connect(self._on_edit_goal)
        toolbar.addWidget(edit_btn)
        
        delete_btn = QPushButton("删除")
        delete_btn.clicked.connect(self._on_delete_goal)
        toolbar.addWidget(delete_btn)
        
        toolbar.addStretch()
        
        self._score_label = QLabel("综合评分: --")
        toolbar.addWidget(self._score_label)
        
        goals_layout.addLayout(toolbar)
        
        # 目标表格
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels([
            "标识符", "名称", "目标值", "单位", "约束", "权重", "状态"
        ])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.doubleClicked.connect(self._on_edit_goal)
        
        goals_layout.addWidget(self._table)
        layout.addWidget(goals_group)
        
        # 底部按钮
        button_layout = QHBoxLayout()
        
        validate_btn = QPushButton("校验")
        validate_btn.clicked.connect(self._on_validate)
        button_layout.addWidget(validate_btn)
        
        button_layout.addStretch()
        
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._on_save)
        button_layout.addWidget(save_btn)
        
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)

    def load_goals(self, project_root: str):
        """
        加载项目的设计目标
        
        Args:
            project_root: 项目根目录
        """
        self._project_root = project_root
        self._manager = DesignGoalsManager(project_root)
        
        # 更新项目信息
        self._circuit_type_edit.setText(self._manager.collection.circuit_type)
        self._description_edit.setText(self._manager.collection.description)
        
        # 更新表格
        self._refresh_table()

    def _refresh_table(self):
        """刷新目标表格"""
        if self._manager is None:
            return
        
        self._table.setRowCount(len(self._manager.collection.goals))
        
        for row, goal in enumerate(self._manager.collection.goals):
            # 标识符
            self._table.setItem(row, 0, QTableWidgetItem(goal.identifier))
            
            # 名称
            self._table.setItem(row, 1, QTableWidgetItem(goal.name))
            
            # 目标值
            value_str = f"{goal.target_value:.6g}"
            if goal.constraint_type == ConstraintType.RANGE and goal.range_max is not None:
                value_str = f"{goal.target_value:.6g} ~ {goal.range_max:.6g}"
            self._table.setItem(row, 2, QTableWidgetItem(value_str))
            
            # 单位
            self._table.setItem(row, 3, QTableWidgetItem(goal.unit))
            
            # 约束类型
            constraint_names = {
                ConstraintType.MINIMUM: "≥ 最小",
                ConstraintType.MAXIMUM: "≤ 最大",
                ConstraintType.EXACT: "= 精确",
                ConstraintType.RANGE: "范围",
                ConstraintType.MINIMIZE: "最小化",
                ConstraintType.MAXIMIZE: "最大化",
            }
            self._table.setItem(
                row, 4, QTableWidgetItem(constraint_names.get(goal.constraint_type, ""))
            )
            
            # 权重
            self._table.setItem(row, 5, QTableWidgetItem(f"{goal.weight:.2f}"))
            
            # 状态
            status_item = QTableWidgetItem()
            if goal.is_met is None:
                status_item.setText("未评估")
                status_item.setForeground(QColor("#888888"))
            elif goal.is_met:
                status_item.setText("✓ 达标")
                status_item.setForeground(QColor("#4CAF50"))
            else:
                status_item.setText("✗ 未达标")
                status_item.setForeground(QColor("#F44336"))
            self._table.setItem(row, 6, status_item)
        
        # 更新评分
        self._update_score()

    def _update_score(self):
        """更新综合评分显示"""
        if self._manager is None:
            self._score_label.setText("综合评分: --")
            return
        
        # 收集已评估的目标
        actual_values = {}
        for goal in self._manager.collection.goals:
            if goal.current_value is not None:
                actual_values[goal.identifier] = goal.current_value
        
        if actual_values:
            score = self._manager.calculate_score(actual_values)
            self._score_label.setText(f"综合评分: {score * 100:.1f}%")
        else:
            self._score_label.setText("综合评分: 未评估")

    def _on_add_goal(self):
        """添加目标"""
        dialog = GoalEditDialog(self, is_edit=False)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            goal = dialog.get_goal()
            self._manager.add_goal(goal)
            self._refresh_table()

    def _on_edit_goal(self):
        """编辑选中的目标"""
        row = self._table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择一个目标")
            return
        
        goal = self._manager.collection.goals[row]
        dialog = GoalEditDialog(self, goal=goal, is_edit=True)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_goal = dialog.get_goal()
            # 保留当前值和达标状态
            new_goal.current_value = goal.current_value
            new_goal.is_met = goal.is_met
            self._manager.collection.goals[row] = new_goal
            self._refresh_table()

    def _on_delete_goal(self):
        """删除选中的目标"""
        row = self._table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择一个目标")
            return
        
        goal = self._manager.collection.goals[row]
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除目标 '{goal.name}' 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self._manager.remove_goal(goal.identifier)
            self._refresh_table()

    def _on_validate(self):
        """校验目标"""
        if self._manager is None:
            return
        
        errors = self._manager.validate()
        if errors:
            QMessageBox.warning(
                self,
                "校验失败",
                "发现以下问题:\n\n" + "\n".join(f"• {e}" for e in errors)
            )
        else:
            QMessageBox.information(self, "校验通过", "所有设计目标校验通过")

    def _on_save(self):
        """保存设计目标"""
        if self._manager is None:
            return
        
        # 更新项目信息
        self._manager.collection.circuit_type = self._circuit_type_edit.text().strip()
        self._manager.collection.description = self._description_edit.text().strip()
        
        # 校验
        errors = self._manager.validate()
        if errors:
            reply = QMessageBox.question(
                self,
                "校验警告",
                "发现以下问题:\n\n" + "\n".join(f"• {e}" for e in errors) +
                "\n\n是否仍要保存？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        
        try:
            self._manager.save()
            self.goals_changed.emit()
            QMessageBox.information(self, "保存成功", "设计目标已保存")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存失败: {str(e)}")

    def retranslate_ui(self):
        """更新界面文本"""
        self.setWindowTitle(self._get_text("dialog.design_goals.title", "设计目标"))


__all__ = ["DesignGoalsDialog", "GoalEditDialog"]
