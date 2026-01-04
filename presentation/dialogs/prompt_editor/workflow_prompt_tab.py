# Workflow Prompt Tab
"""
工作流模式提示词编辑标签页

职责：
- 封装原有的工作流模式提示词编辑功能
- 提供模板列表和编辑区
- 管理保存/重置操作

设计原则：
- 从 PromptEditorDialog 中提取，保持原有功能
- 复用 PromptContentEditor 和 PromptVariablePanel 组件
"""

import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QListWidget, QListWidgetItem,
    QPushButton, QGroupBox, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal

from .prompt_editor_view_model import PromptEditorViewModel
from .prompt_content_editor import PromptContentEditor
from .prompt_variable_panel import PromptVariablePanel


class WorkflowPromptTab(QWidget):
    """
    工作流模式提示词编辑标签页
    
    Signals:
        dirty_state_changed(bool): 脏状态变化
        save_requested: 请求保存
    """
    
    dirty_state_changed = pyqtSignal(bool)
    save_requested = pyqtSignal()
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._logger = logging.getLogger(__name__)
        
        # ViewModel
        self._view_model = PromptEditorViewModel(self)
        
        # 当前选中的模板键
        self._current_key: Optional[str] = None
        
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self) -> None:
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        
        # 左侧：模板列表
        left_widget = self._create_template_list()
        splitter.addWidget(left_widget)
        
        # 右侧：编辑区
        right_widget = self._create_editor_area()
        splitter.addWidget(right_widget)
        
        # 设置分割比例
        splitter.setSizes([250, 750])
    
    def _create_template_list(self) -> QWidget:
        """创建模板列表区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        # 标题
        title_label = QLabel(self._get_text(
            "dialog.prompt_editor.template_list",
            "模板列表"
        ))
        title_font = title_label.font()
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        
        # 列表
        self._template_list = QListWidget()
        self._template_list.setAlternatingRowColors(True)
        self._template_list.currentItemChanged.connect(self._on_template_selected)
        layout.addWidget(self._template_list)
        
        # 图例
        legend_layout = QHBoxLayout()
        legend_layout.setContentsMargins(0, 4, 0, 0)
        
        legend_label = QLabel(self._get_text(
            "dialog.prompt_editor.legend",
            "● 内置  ○ 自定义  * 已修改"
        ))
        legend_label.setStyleSheet("color: #888; font-size: 11px;")
        legend_layout.addWidget(legend_label)
        legend_layout.addStretch()
        
        layout.addLayout(legend_layout)
        
        return widget
    
    def _create_editor_area(self) -> QWidget:
        """创建编辑区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        
        # 模板信息区
        info_frame = self._create_info_frame()
        layout.addWidget(info_frame)
        
        # 内容编辑器
        editor_group = QGroupBox(self._get_text(
            "dialog.prompt_editor.content",
            "模板内容"
        ))
        editor_layout = QVBoxLayout(editor_group)
        editor_layout.setContentsMargins(8, 12, 8, 8)
        
        self._content_editor = PromptContentEditor()
        editor_layout.addWidget(self._content_editor)
        
        layout.addWidget(editor_group, 1)
        
        # 变量面板
        self._variable_panel = PromptVariablePanel()
        layout.addWidget(self._variable_panel)
        
        return widget
    
    def _create_info_frame(self) -> QFrame:
        """创建模板信息框"""
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(16)
        
        # 名称
        name_layout = QVBoxLayout()
        name_layout.setSpacing(2)
        
        name_title = QLabel(self._get_text(
            "dialog.prompt_editor.name",
            "名称"
        ))
        name_title.setStyleSheet("color: #888; font-size: 11px;")
        name_layout.addWidget(name_title)
        
        self._name_label = QLabel("-")
        name_font = self._name_label.font()
        name_font.setBold(True)
        self._name_label.setFont(name_font)
        name_layout.addWidget(self._name_label)
        
        layout.addLayout(name_layout)
        
        # 来源
        source_layout = QVBoxLayout()
        source_layout.setSpacing(2)
        
        source_title = QLabel(self._get_text(
            "dialog.prompt_editor.source",
            "来源"
        ))
        source_title.setStyleSheet("color: #888; font-size: 11px;")
        source_layout.addWidget(source_title)
        
        self._source_label = QLabel("-")
        source_layout.addWidget(self._source_label)
        
        layout.addLayout(source_layout)
        
        # 描述
        desc_layout = QVBoxLayout()
        desc_layout.setSpacing(2)
        
        desc_title = QLabel(self._get_text(
            "dialog.prompt_editor.description",
            "描述"
        ))
        desc_title.setStyleSheet("color: #888; font-size: 11px;")
        desc_layout.addWidget(desc_title)
        
        self._desc_label = QLabel("-")
        self._desc_label.setWordWrap(True)
        desc_layout.addWidget(self._desc_label)
        
        layout.addLayout(desc_layout, 1)
        
        # 重置按钮
        self._reset_btn = QPushButton(self._get_text(
            "dialog.prompt_editor.reset",
            "重置为默认"
        ))
        self._reset_btn.setEnabled(False)
        self._reset_btn.clicked.connect(self._on_reset_clicked)
        layout.addWidget(self._reset_btn)
        
        return frame
    
    def _connect_signals(self) -> None:
        """连接信号"""
        # ViewModel 信号
        self._view_model.template_list_changed.connect(self._refresh_template_list)
        self._view_model.template_selected.connect(self._on_vm_template_selected)
        self._view_model.dirty_state_changed.connect(self._on_dirty_state_changed)
        self._view_model.save_completed.connect(self._on_save_completed)
        self._view_model.reset_completed.connect(self._on_reset_completed)
        
        # 编辑器信号
        self._content_editor.content_changed.connect(self._on_content_changed)
        
        # 变量面板信号
        self._variable_panel.variable_insert_requested.connect(
            self._content_editor.insert_variable
        )
    
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
    # 公共方法
    # ============================================================
    
    def initialize(self) -> bool:
        """
        初始化标签页
        
        Returns:
            是否初始化成功
        """
        return self._view_model.initialize()
    
    def has_unsaved_changes(self) -> bool:
        """检查是否有未保存的修改"""
        return self._view_model.has_unsaved_changes()
    
    def save_all(self) -> bool:
        """保存所有修改"""
        return self._view_model.save_all()
    
    def discard_all_changes(self) -> None:
        """放弃所有修改"""
        self._view_model.discard_all_changes()
    
    # ============================================================
    # 模板列表操作
    # ============================================================
    
    def _refresh_template_list(self) -> None:
        """刷新模板列表"""
        self._template_list.clear()
        
        templates = self._view_model.get_template_list()
        for tpl in templates:
            item = QListWidgetItem()
            
            # 构建显示文本
            prefix = "●" if tpl["source"] == "builtin" else "○"
            suffix = " *" if tpl["is_dirty"] else ""
            item.setText(f"{prefix} {tpl['name']}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, tpl["key"])
            
            # 设置工具提示
            source_text = {
                "builtin": self._get_text("dialog.prompt_editor.source_builtin", "内置"),
                "custom": self._get_text("dialog.prompt_editor.source_custom", "自定义"),
                "fallback": self._get_text("dialog.prompt_editor.source_fallback", "回退"),
            }.get(tpl["source"], tpl["source"])
            item.setToolTip(f"{tpl['key']}\n{source_text}")
            
            self._template_list.addItem(item)
        
        # 恢复选中状态
        if self._current_key:
            for i in range(self._template_list.count()):
                item = self._template_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == self._current_key:
                    self._template_list.setCurrentItem(item)
                    break
    
    def _on_template_selected(
        self,
        current: Optional[QListWidgetItem],
        previous: Optional[QListWidgetItem]
    ) -> None:
        """模板选择变化"""
        if not current:
            self._clear_editor()
            return
        
        key = current.data(Qt.ItemDataRole.UserRole)
        self._view_model.select_template(key)
    
    def _on_vm_template_selected(self, key: str) -> None:
        """ViewModel notifies template selected"""
        self._current_key = key
        state = self._view_model.get_template_state(key)
        
        if not state:
            self._clear_editor()
            return
        
        # Update info area - use i18n for template name and description
        name_key = f"template.{key.lower()}"
        display_name = self._get_text(name_key, state.name)
        self._name_label.setText(display_name)
        
        # Translate description
        desc_key = f"template.{key.lower()}.desc"
        display_desc = self._get_text(desc_key, state.description)
        self._desc_label.setText(display_desc or "-")
        
        source_text = {
            "builtin": self._get_text("dialog.prompt_editor.source_builtin", "Built-in"),
            "custom": self._get_text("dialog.prompt_editor.source_custom", "Custom"),
            "fallback": self._get_text("dialog.prompt_editor.source_fallback", "Fallback"),
        }.get(state.source, state.source)
        self._source_label.setText(source_text)
        
        # 更新编辑器
        self._content_editor.set_content(state.current_content)
        
        # 更新变量面板
        self._variable_panel.set_variables(
            state.variables,
            state.required_variables
        )
        
        # 更新按钮状态
        self._update_button_states()
    
    def _clear_editor(self) -> None:
        """清空编辑区"""
        self._current_key = None
        self._name_label.setText("-")
        self._source_label.setText("-")
        self._desc_label.setText("-")
        self._content_editor.set_content("")
        self._variable_panel.clear()
        self._update_button_states()
    
    # ============================================================
    # 编辑操作
    # ============================================================
    
    def _on_content_changed(self, content: str) -> None:
        """内容变化处理"""
        if self._current_key:
            self._view_model.update_content(self._current_key, content)
    
    def _on_dirty_state_changed(self, key: str, is_dirty: bool) -> None:
        """脏状态变化处理"""
        # 更新列表项显示
        for i in range(self._template_list.count()):
            item = self._template_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == key:
                text = item.text()
                if is_dirty and not text.endswith(" *"):
                    item.setText(text + " *")
                elif not is_dirty and text.endswith(" *"):
                    item.setText(text[:-2])
                break
        
        self._update_button_states()
        
        # 通知父组件
        self.dirty_state_changed.emit(self._view_model.has_unsaved_changes())
    
    def _update_button_states(self) -> None:
        """更新按钮状态"""
        has_current = self._current_key is not None
        
        current_dirty = False
        current_custom = False
        if has_current:
            state = self._view_model.get_template_state(self._current_key)
            if state:
                current_dirty = state.is_dirty
                current_custom = state.source == "custom"
        
        self._reset_btn.setEnabled(has_current and (current_custom or current_dirty))
    
    # ============================================================
    # 保存/重置操作
    # ============================================================
    
    def _on_reset_clicked(self) -> None:
        """重置当前模板"""
        if not self._current_key:
            return
        
        reply = QMessageBox.question(
            self,
            self._get_text("dialog.confirm.title", "确认"),
            self._get_text(
                "dialog.prompt_editor.reset_confirm",
                "确定要将此模板重置为内置默认吗？"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self._view_model.reset_template(self._current_key)
    
    def _on_save_completed(self, success: bool, message: str) -> None:
        """保存完成处理"""
        if success:
            self._refresh_template_list()
        else:
            QMessageBox.warning(
                self,
                self._get_text("dialog.warning.title", "警告"),
                self._get_text(
                    "dialog.prompt_editor.save_failed",
                    "保存失败"
                ) + f": {message}"
            )
    
    def _on_reset_completed(self, key: str) -> None:
        """重置完成处理"""
        self._refresh_template_list()
        
        if key == self._current_key:
            self._view_model.select_template(key)


__all__ = ["WorkflowPromptTab"]
