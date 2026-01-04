# Identity Prompt Tab
"""
身份提示词编辑标签页

职责：
- 提供自由工作模式身份提示词的编辑界面
- 支持保存、重置操作
- 显示当前状态（系统默认/用户自定义）

设计原则：
- 复用 PromptContentEditor 组件
- 与 IdentityPromptManager 交互
"""

import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal

from .prompt_content_editor import PromptContentEditor


class IdentityPromptTab(QWidget):
    """
    身份提示词编辑标签页
    
    Signals:
        dirty_state_changed(bool): 脏状态变化
        save_requested: 请求保存
    """
    
    dirty_state_changed = pyqtSignal(bool)
    save_requested = pyqtSignal()
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._logger = logging.getLogger(__name__)
        
        # 身份提示词管理器
        self._manager = None
        
        # 原始内容（用于检测修改）
        self._original_content: str = ""
        
        # 是否已修改
        self._is_dirty: bool = False
        
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self) -> None:
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        
        # 说明区域
        desc_frame = self._create_description_frame()
        layout.addWidget(desc_frame)
        
        # 状态标签
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
        
        # 内容编辑器
        self._content_editor = PromptContentEditor()
        self._content_editor.set_variable_highlight_enabled(False)  # 禁用变量高亮
        layout.addWidget(self._content_editor, 1)
        
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
            "字符数: 0"
        ))
        self._char_count_label.setStyleSheet("color: #888;")
        layout.addWidget(self._char_count_label)
        
        return layout
    
    def _connect_signals(self) -> None:
        """连接信号"""
        self._content_editor.content_changed.connect(self._on_content_changed)
    
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
        success = self._manager.save_custom(content)
        
        if success:
            self._original_content = content
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
    
    def discard_changes(self) -> None:
        """放弃修改"""
        self._content_editor.set_content(self._original_content)
        self._is_dirty = False
        self.dirty_state_changed.emit(False)
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _on_content_changed(self, content: str) -> None:
        """内容变化处理"""
        # 检测是否有修改
        new_dirty = content != self._original_content
        
        if new_dirty != self._is_dirty:
            self._is_dirty = new_dirty
            self.dirty_state_changed.emit(new_dirty)
        
        self._update_char_count()
    
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
        self._char_count_label.setText(self._get_text(
            "dialog.identity_prompt.char_count",
            f"字符数: {count}"
        ).replace("0", str(count)))


__all__ = ["IdentityPromptTab"]
