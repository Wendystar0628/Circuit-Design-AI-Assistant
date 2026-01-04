# Prompt Variable Panel
"""
变量面板组件 - 显示模板变量并支持插入

职责：
- 显示当前模板的变量列表
- 区分必需变量和可选变量
- 提供"插入变量"功能
"""

from typing import List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton,
    QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


class PromptVariablePanel(QWidget):
    """
    变量面板组件
    
    Signals:
        variable_insert_requested(str): 请求插入变量
    """
    
    variable_insert_requested = pyqtSignal(str)
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._variables: List[str] = []
        self._required_variables: List[str] = []
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # 变量组
        group = QGroupBox(self._get_text("dialog.prompt_editor.variables", "变量"))
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(8, 12, 8, 8)
        group_layout.setSpacing(8)
        
        # 变量列表
        self._variable_list = QListWidget()
        self._variable_list.setMaximumHeight(150)
        self._variable_list.setAlternatingRowColors(True)
        self._variable_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        group_layout.addWidget(self._variable_list)
        
        # 插入按钮
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        
        self._insert_btn = QPushButton(
            self._get_text("dialog.prompt_editor.insert_variable", "插入变量")
        )
        self._insert_btn.setEnabled(False)
        self._insert_btn.clicked.connect(self._on_insert_clicked)
        btn_layout.addStretch()
        btn_layout.addWidget(self._insert_btn)
        
        group_layout.addLayout(btn_layout)
        
        # 提示标签
        hint_label = QLabel(
            self._get_text(
                "dialog.prompt_editor.variable_hint",
                "双击或选中后点击按钮插入变量"
            )
        )
        hint_label.setStyleSheet("color: #888; font-size: 11px;")
        hint_label.setWordWrap(True)
        group_layout.addWidget(hint_label)
        
        layout.addWidget(group)
        layout.addStretch()
        
        # 连接选择变化信号
        self._variable_list.itemSelectionChanged.connect(self._on_selection_changed)
    
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
    
    def set_variables(
        self,
        variables: List[str],
        required_variables: Optional[List[str]] = None
    ) -> None:
        """
        设置变量列表
        
        Args:
            variables: 所有变量列表
            required_variables: 必需变量列表
        """
        self._variables = variables or []
        self._required_variables = required_variables or []
        self._update_list()
    
    def _update_list(self) -> None:
        """更新列表显示"""
        self._variable_list.clear()
        
        for var in self._variables:
            item = QListWidgetItem()
            is_required = var in self._required_variables
            
            # 显示文本
            display_text = f"{{{var}}}"
            if is_required:
                display_text += " *"
            
            item.setText(display_text)
            item.setData(Qt.ItemDataRole.UserRole, var)
            
            # 必需变量使用粗体
            if is_required:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setToolTip(
                    self._get_text(
                        "dialog.prompt_editor.required_variable",
                        "必需变量"
                    )
                )
            else:
                item.setToolTip(
                    self._get_text(
                        "dialog.prompt_editor.optional_variable",
                        "可选变量"
                    )
                )
            
            self._variable_list.addItem(item)
        
        self._insert_btn.setEnabled(False)
    
    def _on_selection_changed(self) -> None:
        """选择变化处理"""
        has_selection = len(self._variable_list.selectedItems()) > 0
        self._insert_btn.setEnabled(has_selection)
    
    def _on_insert_clicked(self) -> None:
        """插入按钮点击"""
        items = self._variable_list.selectedItems()
        if items:
            var_name = items[0].data(Qt.ItemDataRole.UserRole)
            self.variable_insert_requested.emit(f"{{{var_name}}}")
    
    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        """双击列表项"""
        var_name = item.data(Qt.ItemDataRole.UserRole)
        self.variable_insert_requested.emit(f"{{{var_name}}}")
    
    def clear(self) -> None:
        """清空变量列表"""
        self._variables = []
        self._required_variables = []
        self._variable_list.clear()
        self._insert_btn.setEnabled(False)


__all__ = ["PromptVariablePanel"]
