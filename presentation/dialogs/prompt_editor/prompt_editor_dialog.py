# Prompt Editor Dialog
"""
Prompt 设置主对话框

职责：
- 提供双标签页布局：工作流模式 + 自由工作模式
- 管理保存/取消操作
- 协调各标签页的状态

设计原则：
- 模态对话框，阻塞主窗口交互
- 标签页容器，各标签页独立管理自己的状态
"""

import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QWidget, QPushButton, QMessageBox
)
from PyQt6.QtCore import pyqtSignal

from .workflow_prompt_tab import WorkflowPromptTab
from .identity_prompt_tab import IdentityPromptTab


class PromptEditorDialog(QDialog):
    """
    Prompt 设置对话框
    
    布局：
    - 标签页容器：工作流模式 | 自由工作模式
    - 底部：操作按钮
    
    Signals:
        settings_saved: 设置保存完成
    """
    
    settings_saved = pyqtSignal()
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._logger = logging.getLogger(__name__)
        
        self._setup_ui()
        self._connect_signals()
        self._initialize()
    
    def _setup_ui(self) -> None:
        """初始化 UI"""
        self.setWindowTitle(self._get_text(
            "dialog.prompt_settings.title",
            "Prompt 设置"
        ))
        self.setMinimumSize(900, 600)
        self.resize(1000, 700)
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)
        
        # 标签页容器
        self._tab_widget = QTabWidget()
        main_layout.addWidget(self._tab_widget, 1)
        
        # 工作流模式标签页
        self._workflow_tab = WorkflowPromptTab()
        self._tab_widget.addTab(
            self._workflow_tab,
            self._get_text("dialog.prompt_settings.workflow_tab", "工作流模式")
        )
        
        # 自由工作模式标签页
        self._identity_tab = IdentityPromptTab()
        self._tab_widget.addTab(
            self._identity_tab,
            self._get_text("dialog.prompt_settings.identity_tab", "自由工作模式")
        )
        
        # 底部按钮
        button_layout = self._create_buttons()
        main_layout.addLayout(button_layout)
    
    def _create_buttons(self) -> QHBoxLayout:
        """创建底部按钮"""
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 8, 0, 0)
        
        layout.addStretch()
        
        # 取消
        self._cancel_btn = QPushButton(self._get_text("btn.cancel", "取消"))
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        layout.addWidget(self._cancel_btn)
        
        # 应用
        self._apply_btn = QPushButton(self._get_text("btn.apply", "应用"))
        self._apply_btn.clicked.connect(self._on_apply_clicked)
        layout.addWidget(self._apply_btn)
        
        # 确定
        self._ok_btn = QPushButton(self._get_text("btn.ok", "确定"))
        self._ok_btn.setDefault(True)
        self._ok_btn.clicked.connect(self._on_ok_clicked)
        layout.addWidget(self._ok_btn)
        
        return layout
    
    def _connect_signals(self) -> None:
        """连接信号"""
        # 标签页脏状态变化
        self._workflow_tab.dirty_state_changed.connect(self._on_dirty_state_changed)
        self._identity_tab.dirty_state_changed.connect(self._on_dirty_state_changed)
        
        # 标签页切换
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
    
    def _initialize(self) -> None:
        """初始化数据"""
        # 初始化工作流模式标签页
        if not self._workflow_tab.initialize():
            self._logger.warning("工作流模式标签页初始化失败")
        
        # 初始化身份提示词标签页
        if not self._identity_tab.initialize():
            self._logger.warning("身份提示词标签页初始化失败")
        
        # 更新按钮状态
        self._update_button_states()
    
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
    # 状态管理
    # ============================================================
    
    def _has_any_unsaved_changes(self) -> bool:
        """检查是否有任何未保存的修改"""
        return (
            self._workflow_tab.has_unsaved_changes() or
            self._identity_tab.has_unsaved_changes()
        )
    
    def _on_dirty_state_changed(self, is_dirty: bool) -> None:
        """脏状态变化处理"""
        self._update_tab_titles()
        self._update_button_states()
    
    def _on_tab_changed(self, index: int) -> None:
        """标签页切换处理"""
        # 可以在这里添加切换时的逻辑
        pass
    
    def _update_tab_titles(self) -> None:
        """更新标签页标题（显示修改标记）"""
        # 工作流模式标签页
        workflow_title = self._get_text(
            "dialog.prompt_settings.workflow_tab",
            "工作流模式"
        )
        if self._workflow_tab.has_unsaved_changes():
            workflow_title += " *"
        self._tab_widget.setTabText(0, workflow_title)
        
        # 身份提示词标签页
        identity_title = self._get_text(
            "dialog.prompt_settings.identity_tab",
            "自由工作模式"
        )
        if self._identity_tab.has_unsaved_changes():
            identity_title += " *"
        self._tab_widget.setTabText(1, identity_title)
    
    def _update_button_states(self) -> None:
        """更新按钮状态"""
        has_changes = self._has_any_unsaved_changes()
        self._apply_btn.setEnabled(has_changes)
    
    # ============================================================
    # 按钮操作
    # ============================================================
    
    def _on_cancel_clicked(self) -> None:
        """取消按钮点击"""
        if self._has_any_unsaved_changes():
            reply = QMessageBox.question(
                self,
                self._get_text("dialog.confirm.title", "确认"),
                self._get_text(
                    "dialog.prompt_settings.discard_confirm",
                    "有未保存的修改，确定要放弃吗？"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                return
            
            # 放弃所有修改
            self._workflow_tab.discard_all_changes()
            self._identity_tab.discard_changes()
        
        self.reject()
    
    def _on_apply_clicked(self) -> None:
        """应用按钮点击"""
        self._save_all()
    
    def _on_ok_clicked(self) -> None:
        """确定按钮点击"""
        if self._has_any_unsaved_changes():
            if not self._save_all():
                return
        
        self.accept()
    
    def _save_all(self) -> bool:
        """
        保存所有修改
        
        Returns:
            是否全部保存成功
        """
        success = True
        
        # 保存工作流模式修改
        if self._workflow_tab.has_unsaved_changes():
            if not self._workflow_tab.save_all():
                success = False
        
        # 保存身份提示词修改
        if self._identity_tab.has_unsaved_changes():
            if not self._identity_tab.save_content():
                success = False
        
        if success:
            self._update_tab_titles()
            self._update_button_states()
            self.settings_saved.emit()
        
        return success
    
    # ============================================================
    # 关闭处理
    # ============================================================
    
    def closeEvent(self, event) -> None:
        """窗口关闭事件"""
        if self._has_any_unsaved_changes():
            reply = QMessageBox.question(
                self,
                self._get_text("dialog.confirm.title", "确认"),
                self._get_text(
                    "dialog.prompt_settings.unsaved_changes",
                    "有未保存的修改，确定要关闭吗？"
                ),
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save
            )
            
            if reply == QMessageBox.StandardButton.Save:
                if self._save_all():
                    event.accept()
                else:
                    event.ignore()
            elif reply == QMessageBox.StandardButton.Discard:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


__all__ = ["PromptEditorDialog"]
