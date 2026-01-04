# Identity Prompt Tab
"""
身份提示词编辑标签页

职责：
- 提供自由工作模式身份提示词的编辑界面
- 支持变量管理（添加、删除）
- 支持保存、重置操作
- 显示当前状态（系统默认/用户自定义）

设计原则：
- 复用 PromptContentEditor 和 PromptVariablePanel 组件
- 变量面板直接嵌入，不使用外层 GroupBox，节省空间
- 变量以横向按钮块形式显示
"""

import logging
import re
from typing import List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QMessageBox, QInputDialog,
    QGroupBox
)
from PyQt6.QtCore import pyqtSignal

from .prompt_content_editor import PromptContentEditor
from .prompt_variable_panel import PromptVariablePanel


class IdentityPromptTab(QWidget):
    """
    身份提示词编辑标签页
    
    Signals:
        dirty_state_changed(bool): 脏状态变化
        save_requested: 请求保存
        variables_changed: 变量列表变化
    """
    
    dirty_state_changed = pyqtSignal(bool)
    save_requested = pyqtSignal()
    variables_changed = pyqtSignal()
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._logger = logging.getLogger(__name__)
        
        # 身份提示词管理器
        self._manager = None
        
        # 原始内容（用于检测修改）
        self._original_content: str = ""
        
        # 原始变量列表（用于检测修改）
        self._original_variables: List[str] = []
        self._original_required_variables: List[str] = []
        
        # 当前变量列表
        self._current_variables: List[str] = []
        self._current_required_variables: List[str] = []
        
        # 是否已修改
        self._is_dirty: bool = False
        
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self) -> None:
        """初始化 UI - 紧凑布局"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        # 说明区域
        desc_frame = self._create_description_frame()
        layout.addWidget(desc_frame)
        
        # 状态行
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)
        
        status_title = QLabel(self._get_text(
            "dialog.identity_prompt.status",
            "当前状态："
        ))
        status_layout.addWidget(status_title)
        
        self._status_label = QLabel("-")
        self._status_label.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(self._status_label)
        
        status_layout.addStretch()
        layout.addLayout(status_layout)
        
        # 内容编辑器（带标题）
        editor_group = QGroupBox(self._get_text(
            "dialog.identity_prompt.content",
            "提示词内容"
        ))
        editor_layout = QVBoxLayout(editor_group)
        editor_layout.setContentsMargins(8, 12, 8, 8)
        
        self._content_editor = PromptContentEditor()
        self._content_editor.set_variable_highlight_enabled(True)
        editor_layout.addWidget(self._content_editor)
        
        layout.addWidget(editor_group, 1)  # 编辑器占据主要空间
        
        # 变量区域 - 直接嵌入，不使用 GroupBox
        variable_section = self._create_variable_section()
        layout.addWidget(variable_section)
        
        # 底部工具栏
        toolbar_layout = self._create_toolbar()
        layout.addLayout(toolbar_layout)
    
    def _create_description_frame(self) -> QFrame:
        """创建说明区域"""
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        frame.setStyleSheet("""
            QFrame {
                background-color: #f0f7ff;
                border: 1px solid #b3d4fc;
                border-radius: 4px;
            }
        """)
        
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)
        
        title = QLabel(self._get_text(
            "dialog.identity_prompt.title",
            "身份提示词设置"
        ))
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        
        desc = QLabel(self._get_text(
            "dialog.identity_prompt.description",
            "身份提示词定义 AI 助手在自由工作模式下的角色和行为。"
            "它将作为所有对话的固定系统提示，类似 Cursor 的 Rules 功能。"
        ))
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555;")
        layout.addWidget(desc)
        
        return frame
    
    def _create_variable_section(self) -> QWidget:
        """
        创建变量区域 - 紧凑布局
        
        不使用 GroupBox，直接显示变量按钮和管理按钮
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        
        # 变量面板（横向流式布局，带标签）
        self._variable_panel = PromptVariablePanel(show_label=True)
        layout.addWidget(self._variable_panel)
        
        # 变量管理按钮行
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(8)
        
        self._add_var_btn = QPushButton(self._get_text(
            "dialog.identity_prompt.add_variable",
            "+ Add Variable"
        ))
        self._add_var_btn.setFixedHeight(28)
        self._add_var_btn.clicked.connect(self._on_add_variable)
        btn_layout.addWidget(self._add_var_btn)
        
        self._remove_var_btn = QPushButton(self._get_text(
            "dialog.identity_prompt.remove_variable",
            "- Delete Variable"
        ))
        self._remove_var_btn.setFixedHeight(28)
        self._remove_var_btn.clicked.connect(self._on_remove_variable)
        btn_layout.addWidget(self._remove_var_btn)
        
        btn_layout.addStretch()
        
        # 提示文本
        hint_label = QLabel(self._get_text(
            "dialog.identity_prompt.variable_hint",
            "Use {variable_name} format to reference variables in the prompt, which will be automatically filled at runtime"
        ))
        hint_label.setStyleSheet("color: #888; font-size: 11px;")
        btn_layout.addWidget(hint_label)
        
        layout.addLayout(btn_layout)
        
        return widget
    
    def _create_toolbar(self) -> QHBoxLayout:
        """创建底部工具栏"""
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 重置按钮
        self._reset_btn = QPushButton(self._get_text(
            "dialog.identity_prompt.reset",
            "重置为默认"
        ))
        self._reset_btn.clicked.connect(self._on_reset_clicked)
        layout.addWidget(self._reset_btn)
        
        layout.addStretch()
        
        # 字符计数
        self._char_count_label = QLabel(self._get_text(
            "dialog.identity_prompt.char_count",
            "Character count: 0"
        ).replace("{count}", "0"))
        self._char_count_label.setStyleSheet("color: #888;")
        layout.addWidget(self._char_count_label)
        
        return layout
    
    def _connect_signals(self) -> None:
        """连接信号"""
        self._content_editor.content_changed.connect(self._on_content_changed)
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
        初始化标签页，加载身份提示词
        
        Returns:
            是否初始化成功
        """
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_IDENTITY_PROMPT_MANAGER
            
            self._manager = ServiceLocator.get_optional(SVC_IDENTITY_PROMPT_MANAGER)
            if not self._manager:
                # 直接创建实例
                from domain.llm.identity_prompt_manager import IdentityPromptManager
                self._manager = IdentityPromptManager()
                self._manager.initialize()
            
            self.load_content()
            return True
        except Exception as e:
            self._logger.error(f"初始化身份提示词标签页失败: {e}")
            return False
    
    def load_content(self) -> None:
        """从管理器加载内容"""
        if not self._manager:
            return
        
        content = self._manager.get_identity_prompt()
        self._original_content = content
        self._content_editor.set_content(content)
        
        # 加载变量列表
        self._original_variables = self._manager.get_variables()
        self._original_required_variables = self._manager.get_required_variables()
        self._current_variables = self._original_variables.copy()
        self._current_required_variables = self._original_required_variables.copy()
        
        # 更新变量面板
        self._variable_panel.set_variables(
            self._current_variables,
            self._current_required_variables
        )
        
        # 更新状态显示
        self._update_status_display()
        self._update_char_count()
        
        # 重置脏状态
        self._is_dirty = False
        self.dirty_state_changed.emit(False)
    
    def save_content(self) -> bool:
        """
        保存内容到管理器
        
        Returns:
            是否保存成功
        """
        if not self._manager:
            return False
        
        content = self._content_editor.get_content()
        success = self._manager.save_custom(
            content,
            self._current_variables,
            self._current_required_variables
        )
        
        if success:
            self._original_content = content
            self._original_variables = self._current_variables.copy()
            self._original_required_variables = self._current_required_variables.copy()
            self._is_dirty = False
            self.dirty_state_changed.emit(False)
            self._update_status_display()
        
        return success
    
    def reset_to_default(self) -> bool:
        """
        重置为系统默认
        
        Returns:
            是否重置成功
        """
        if not self._manager:
            return False
        
        success = self._manager.reset_to_default()
        
        if success:
            self.load_content()
        
        return success
    
    def has_unsaved_changes(self) -> bool:
        """检查是否有未保存的修改"""
        return self._is_dirty
    
    def get_content(self) -> str:
        """获取当前编辑内容"""
        return self._content_editor.get_content()
    
    def get_variables(self) -> List[str]:
        """获取当前变量列表"""
        return self._current_variables.copy()
    
    def get_required_variables(self) -> List[str]:
        """获取必需变量列表"""
        return self._current_required_variables.copy()
    
    def discard_changes(self) -> None:
        """放弃修改"""
        self._content_editor.set_content(self._original_content)
        self._current_variables = self._original_variables.copy()
        self._current_required_variables = self._original_required_variables.copy()
        self._variable_panel.set_variables(
            self._current_variables,
            self._current_required_variables
        )
        self._is_dirty = False
        self.dirty_state_changed.emit(False)
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _on_content_changed(self, content: str) -> None:
        """内容变化处理"""
        self._check_dirty_state()
        self._update_char_count()
    
    def _check_dirty_state(self) -> None:
        """检查并更新脏状态"""
        content = self._content_editor.get_content()
        content_changed = content != self._original_content
        variables_changed = (
            self._current_variables != self._original_variables or
            self._current_required_variables != self._original_required_variables
        )
        
        new_dirty = content_changed or variables_changed
        
        if new_dirty != self._is_dirty:
            self._is_dirty = new_dirty
            self.dirty_state_changed.emit(new_dirty)
    
    def _on_add_variable(self) -> None:
        """Add variable"""
        name, ok = QInputDialog.getText(
            self,
            self._get_text("dialog.identity_prompt.add_variable_title", "Add Variable"),
            self._get_text("dialog.identity_prompt.add_variable_prompt", "Enter variable name (letters, numbers, and underscores only):")
        )
        
        if not ok or not name:
            return
        
        # 验证变量名格式
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
            QMessageBox.warning(
                self,
                self._get_text("dialog.warning.title", "警告"),
                self._get_text(
                    "dialog.identity_prompt.invalid_variable_name",
                    "无效的变量名，仅支持字母、数字和下划线，且不能以数字开头"
                )
            )
            return
        
        # 检查是否已存在
        if name in self._current_variables:
            QMessageBox.warning(
                self,
                self._get_text("dialog.warning.title", "警告"),
                self._get_text(
                    "dialog.identity_prompt.variable_exists",
                    "变量已存在"
                )
            )
            return
        
        # 添加变量
        self._current_variables.append(name)
        self._variable_panel.set_variables(
            self._current_variables,
            self._current_required_variables
        )
        
        self._check_dirty_state()
        self.variables_changed.emit()
    
    def _on_remove_variable(self) -> None:
        """Delete variable - show selection dialog"""
        if not self._current_variables:
            QMessageBox.information(
                self,
                self._get_text("dialog.info.title", "Information"),
                self._get_text(
                    "dialog.identity_prompt.no_variables",
                    "No variables to delete"
                )
            )
            return
        
        # Show selection dialog
        var_name, ok = QInputDialog.getItem(
            self,
            self._get_text("dialog.identity_prompt.remove_variable_title", "Delete Variable"),
            self._get_text("dialog.identity_prompt.remove_variable_prompt", "Select variable to delete:"),
            self._current_variables,
            0,
            False
        )
        
        if not ok or not var_name:
            return
        
        # 确认删除
        reply = QMessageBox.question(
            self,
            self._get_text("dialog.confirm.title", "确认"),
            self._get_text(
                "dialog.identity_prompt.remove_variable_confirm",
                f"确定要删除变量 '{var_name}' 吗？"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # 删除变量
        if var_name in self._current_variables:
            self._current_variables.remove(var_name)
        if var_name in self._current_required_variables:
            self._current_required_variables.remove(var_name)
        
        self._variable_panel.set_variables(
            self._current_variables,
            self._current_required_variables
        )
        
        self._check_dirty_state()
        self.variables_changed.emit()
    
    def _on_reset_clicked(self) -> None:
        """重置按钮点击"""
        reply = QMessageBox.question(
            self,
            self._get_text("dialog.confirm.title", "确认"),
            self._get_text(
                "dialog.identity_prompt.reset_confirm",
                "确定要将身份提示词重置为系统默认吗？"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.reset_to_default()
    
    def _update_status_display(self) -> None:
        """更新状态显示"""
        if not self._manager:
            self._status_label.setText("-")
            return
        
        if self._manager.is_custom():
            self._status_label.setText(self._get_text(
                "dialog.identity_prompt.status_custom",
                "用户自定义"
            ))
            self._status_label.setStyleSheet("font-weight: bold; color: #1976d2;")
        else:
            self._status_label.setText(self._get_text(
                "dialog.identity_prompt.status_default",
                "系统默认"
            ))
            self._status_label.setStyleSheet("font-weight: bold; color: #388e3c;")
    
    def _update_char_count(self) -> None:
        """更新字符计数"""
        content = self._content_editor.get_content()
        count = len(content)
        self._char_count_label.setText(
            self._get_text("dialog.identity_prompt.char_count", "Character count: {count}").replace("{count}", str(count))
        )


__all__ = ["IdentityPromptTab"]
