# History Dialog - Conversation History Viewer
"""
对话历史查看对话框

职责：
- 显示所有会话列表
- 支持查看、恢复、导出和删除历史对话
- 与 Checkpointer 集成获取会话数据

国际化支持：
- 实现 retranslate_ui() 方法
- 订阅 EVENT_LANGUAGE_CHANGED 事件
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QListWidget,
    QListWidgetItem,
    QTextEdit,
    QPushButton,
    QLabel,
    QGroupBox,
    QMessageBox,
    QFileDialog,
    QWidget,
)
from PyQt6.QtCore import Qt


# ============================================================
# 数据结构
# ============================================================

@dataclass
class SessionInfo:
    """会话信息"""
    session_id: str           # 会话 ID（thread_id）
    created_at: datetime      # 创建时间
    updated_at: datetime      # 最后更新时间
    message_count: int        # 消息数量
    preview: str              # 预览文本（首条用户消息摘要）


# ============================================================
# 对话历史对话框
# ============================================================

class HistoryDialog(QDialog):
    """
    对话历史查看对话框
    
    功能：
    - 显示所有会话列表
    - 查看会话详情
    - 恢复、导出、删除会话
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        # 延迟获取的服务
        self._i18n_manager = None
        self._event_bus = None
        self._logger = None
        self._context_manager = None
        
        # 会话数据
        self._sessions: List[SessionInfo] = []
        self._current_session_id: Optional[str] = None
        self._current_messages: List[Dict[str, Any]] = []
        
        # UI 组件引用
        self._session_list: Optional[QListWidget] = None
        self._detail_text: Optional[QTextEdit] = None
        self._restore_btn: Optional[QPushButton] = None
        self._export_btn: Optional[QPushButton] = None
        self._delete_btn: Optional[QPushButton] = None
        self._close_btn: Optional[QPushButton] = None
        
        # 初始化 UI
        self._setup_dialog()
        self._setup_ui()
        
        # 加载会话列表
        self.load_sessions()
        
        # 应用国际化文本
        self.retranslate_ui()
        
        # 订阅事件
        self._subscribe_events()

    # ============================================================
    # 延迟获取服务
    # ============================================================

    @property
    def i18n_manager(self):
        """延迟获取 I18nManager"""
        if self._i18n_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_I18N_MANAGER
                self._i18n_manager = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            except Exception:
                pass
        return self._i18n_manager

    @property
    def event_bus(self):
        """延迟获取 EventBus"""
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus

    @property
    def logger(self):
        """延迟获取 Logger"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("history_dialog")
            except Exception:
                pass
        return self._logger

    @property
    def context_manager(self):
        """延迟获取 ContextManager"""
        if self._context_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CONTEXT_MANAGER
                self._context_manager = ServiceLocator.get_optional(SVC_CONTEXT_MANAGER)
            except Exception:
                pass
        return self._context_manager

    def _get_text(self, key: str, default: Optional[str] = None) -> str:
        """获取国际化文本"""
        if self.i18n_manager:
            return self.i18n_manager.get_text(key, default)
        return default if default else key

    # ============================================================
    # UI 初始化
    # ============================================================

    def _setup_dialog(self):
        """设置对话框基本属性"""
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setMinimumSize(800, 600)
        self.resize(900, 650)
        self.setModal(True)

    def _setup_ui(self):
        """设置 UI 布局"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        
        # 主分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧：会话列表
        left_widget = self._create_session_list_widget()
        splitter.addWidget(left_widget)
        
        # 右侧：会话详情
        right_widget = self._create_detail_widget()
        splitter.addWidget(right_widget)
        
        # 设置分割比例
        splitter.setSizes([300, 600])
        
        main_layout.addWidget(splitter, 1)
        
        # 底部按钮区
        main_layout.addWidget(self._create_button_area())

    def _create_session_list_widget(self) -> QWidget:
        """创建会话列表组件"""
        group = QGroupBox()
        group.setProperty("group_type", "session_list")
        layout = QVBoxLayout(group)
        
        # 会话列表
        self._session_list = QListWidget()
        self._session_list.setAlternatingRowColors(True)
        self._session_list.currentItemChanged.connect(self._on_session_selected)
        self._session_list.itemDoubleClicked.connect(self._on_session_double_clicked)
        layout.addWidget(self._session_list)
        
        return group

    def _create_detail_widget(self) -> QWidget:
        """创建会话详情组件"""
        group = QGroupBox()
        group.setProperty("group_type", "session_detail")
        layout = QVBoxLayout(group)
        
        # 详情文本区
        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setStyleSheet("""
            QTextEdit {
                background-color: #fafafa;
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 8px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 13px;
            }
        """)
        layout.addWidget(self._detail_text)
        
        return group


    def _create_button_area(self) -> QWidget:
        """创建按钮区域"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 10, 0, 0)
        
        # 恢复按钮
        self._restore_btn = QPushButton()
        self._restore_btn.setEnabled(False)
        self._restore_btn.clicked.connect(self._on_restore_clicked)
        layout.addWidget(self._restore_btn)
        
        # 导出按钮
        self._export_btn = QPushButton()
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._on_export_clicked)
        layout.addWidget(self._export_btn)
        
        # 删除按钮
        self._delete_btn = QPushButton()
        self._delete_btn.setEnabled(False)
        self._delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        layout.addWidget(self._delete_btn)
        
        layout.addStretch()
        
        # 关闭按钮
        self._close_btn = QPushButton()
        self._close_btn.clicked.connect(self.accept)
        layout.addWidget(self._close_btn)
        
        return widget

    # ============================================================
    # 核心功能
    # ============================================================

    def load_sessions(self) -> None:
        """加载所有会话列表"""
        self._sessions.clear()
        self._session_list.clear()
        
        # 从 Checkpointer 获取会话列表
        sessions = self._get_sessions_from_checkpointer()
        
        for session in sessions:
            self._sessions.append(session)
            
            # 创建列表项
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, session.session_id)
            
            # 格式化显示文本
            display_text = self._format_session_item(session)
            item.setText(display_text)
            
            self._session_list.addItem(item)
        
        if self.logger:
            self.logger.info(f"Loaded {len(self._sessions)} sessions")

    def _get_sessions_from_checkpointer(self) -> List[SessionInfo]:
        """从 Checkpointer 获取会话列表"""
        sessions = []
        
        # TODO: 实际实现需要与 Checkpointer 集成
        # 这里提供模拟数据用于 UI 测试
        try:
            # 尝试从 ContextManager 获取会话历史
            if self.context_manager:
                # 如果 ContextManager 有获取历史会话的方法
                pass
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to load sessions: {e}")
        
        return sessions

    def _format_session_item(self, session: SessionInfo) -> str:
        """格式化会话列表项显示文本"""
        date_str = session.updated_at.strftime("%Y-%m-%d %H:%M")
        preview = session.preview[:30] + "..." if len(session.preview) > 30 else session.preview
        return f"{date_str} | {session.message_count} msgs\n{preview}"

    def show_session_detail(self, session_id: str) -> None:
        """显示会话详情"""
        self._current_session_id = session_id
        self._current_messages = []
        
        # 加载会话消息
        messages = self._load_session_messages(session_id)
        self._current_messages = messages
        
        # 格式化显示
        html_content = self._format_messages_for_display(messages)
        self._detail_text.setHtml(html_content)
        
        # 启用操作按钮
        self._restore_btn.setEnabled(True)
        self._export_btn.setEnabled(True)
        self._delete_btn.setEnabled(True)

    def _load_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """加载会话消息"""
        messages = []
        
        # TODO: 从 Checkpointer 加载指定会话的消息
        # 这里返回空列表，实际实现需要与 Checkpointer 集成
        
        return messages

    def _format_messages_for_display(self, messages: List[Dict[str, Any]]) -> str:
        """格式化消息用于显示"""
        if not messages:
            return f"<p style='color: #999;'>{self._get_text('dialog.history.no_messages', 'No messages in this session')}</p>"
        
        html_parts = []
        
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            timestamp = msg.get("timestamp", "")
            
            # 根据角色设置样式
            if role == "user":
                role_color = "#4a9eff"
                role_label = self._get_text("role.user", "User")
            elif role == "assistant":
                role_color = "#4caf50"
                role_label = self._get_text("role.assistant", "Assistant")
            else:
                role_color = "#999999"
                role_label = self._get_text("role.system", "System")
            
            # 转义 HTML
            content_escaped = content.replace("<", "&lt;").replace(">", "&gt;")
            content_escaped = content_escaped.replace("\n", "<br>")
            
            html_parts.append(f"""
                <div style="margin-bottom: 16px;">
                    <div style="color: {role_color}; font-weight: bold; margin-bottom: 4px;">
                        [{role_label}] <span style="color: #999; font-weight: normal; font-size: 11px;">{timestamp}</span>
                    </div>
                    <div style="padding-left: 12px; border-left: 2px solid {role_color};">
                        {content_escaped}
                    </div>
                </div>
            """)
        
        return "".join(html_parts)

    def restore_session(self, session_id: str) -> bool:
        """恢复会话到当前对话"""
        if not session_id:
            return False
        
        try:
            # 调用 ContextManager 恢复会话
            if self.context_manager:
                # TODO: 实现 context_manager.restore_session(session_id)
                pass
            
            if self.logger:
                self.logger.info(f"Session restored: {session_id}")
            
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to restore session: {e}")
            return False

    def export_session(self, session_id: str, format: str) -> bool:
        """导出会话"""
        if not session_id or not self._current_messages:
            return False
        
        # 选择保存路径
        file_filter = {
            "json": "JSON Files (*.json)",
            "txt": "Text Files (*.txt)",
            "md": "Markdown Files (*.md)",
        }.get(format, "All Files (*.*)")
        
        default_name = f"conversation_{session_id[:8]}.{format}"
        
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._get_text("dialog.export.title", "Export Conversation"),
            default_name,
            file_filter
        )
        
        if not path:
            return False
        
        try:
            content = self._format_session_for_export(self._current_messages, format)
            
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            
            if self.logger:
                self.logger.info(f"Session exported to: {path}")
            
            QMessageBox.information(
                self,
                self._get_text("dialog.info", "Information"),
                self._get_text("dialog.export.success", "Conversation exported successfully")
            )
            
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to export session: {e}")
            
            QMessageBox.warning(
                self,
                self._get_text("dialog.error", "Error"),
                self._get_text("dialog.export.failed", "Failed to export conversation")
            )
            
            return False

    def _format_session_for_export(
        self, messages: List[Dict[str, Any]], format: str
    ) -> str:
        """格式化会话用于导出"""
        if format == "json":
            return json.dumps(messages, ensure_ascii=False, indent=2)
        
        elif format == "txt":
            lines = []
            for msg in messages:
                role = msg.get("role", "unknown").upper()
                content = msg.get("content", "")
                timestamp = msg.get("timestamp", "")
                lines.append(f"[{role}] {timestamp}")
                lines.append(content)
                lines.append("")
            return "\n".join(lines)
        
        elif format == "md":
            lines = ["# Conversation Export", ""]
            for msg in messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                timestamp = msg.get("timestamp", "")
                
                if role == "user":
                    lines.append(f"## 👤 User ({timestamp})")
                elif role == "assistant":
                    lines.append(f"## 🤖 Assistant ({timestamp})")
                else:
                    lines.append(f"## ⚙️ System ({timestamp})")
                
                lines.append("")
                lines.append(content)
                lines.append("")
            return "\n".join(lines)
        
        return ""

    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        if not session_id:
            return False
        
        try:
            # TODO: 从 Checkpointer 删除会话
            # checkpointer.delete(session_id)
            
            if self.logger:
                self.logger.info(f"Session deleted: {session_id}")
            
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to delete session: {e}")
            return False


    # ============================================================
    # 事件处理
    # ============================================================

    def _on_session_selected(self, current: QListWidgetItem, previous: QListWidgetItem) -> None:
        """会话选择变化"""
        if current is None:
            self._detail_text.clear()
            self._restore_btn.setEnabled(False)
            self._export_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
            return
        
        session_id = current.data(Qt.ItemDataRole.UserRole)
        self.show_session_detail(session_id)

    def _on_session_double_clicked(self, item: QListWidgetItem) -> None:
        """会话双击（快速恢复）"""
        session_id = item.data(Qt.ItemDataRole.UserRole)
        self._on_restore_clicked()

    def _on_restore_clicked(self) -> None:
        """恢复按钮点击"""
        if not self._current_session_id:
            return
        
        # 确认对话框
        result = QMessageBox.question(
            self,
            self._get_text("dialog.confirm", "Confirm"),
            self._get_text(
                "dialog.history.restore_confirm",
                "Archive current conversation and restore this session?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if result != QMessageBox.StandardButton.Yes:
            return
        
        if self.restore_session(self._current_session_id):
            self.accept()

    def _on_export_clicked(self) -> None:
        """导出按钮点击"""
        if not self._current_session_id:
            return
        
        # 选择导出格式
        format_dialog = QMessageBox(self)
        format_dialog.setWindowTitle(self._get_text("dialog.export.format", "Export Format"))
        format_dialog.setText(self._get_text("dialog.export.select_format", "Select export format:"))
        
        json_btn = format_dialog.addButton("JSON", QMessageBox.ButtonRole.ActionRole)
        txt_btn = format_dialog.addButton("TXT", QMessageBox.ButtonRole.ActionRole)
        md_btn = format_dialog.addButton("Markdown", QMessageBox.ButtonRole.ActionRole)
        format_dialog.addButton(QMessageBox.StandardButton.Cancel)
        
        format_dialog.exec()
        
        clicked = format_dialog.clickedButton()
        if clicked == json_btn:
            self.export_session(self._current_session_id, "json")
        elif clicked == txt_btn:
            self.export_session(self._current_session_id, "txt")
        elif clicked == md_btn:
            self.export_session(self._current_session_id, "md")

    def _on_delete_clicked(self) -> None:
        """删除按钮点击"""
        if not self._current_session_id:
            return
        
        # 确认对话框
        result = QMessageBox.warning(
            self,
            self._get_text("dialog.warning", "Warning"),
            self._get_text(
                "dialog.history.delete_confirm",
                "Are you sure you want to delete this session? This action cannot be undone."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if result != QMessageBox.StandardButton.Yes:
            return
        
        if self.delete_session(self._current_session_id):
            # 从列表中移除
            current_item = self._session_list.currentItem()
            if current_item:
                row = self._session_list.row(current_item)
                self._session_list.takeItem(row)
            
            # 清空详情
            self._detail_text.clear()
            self._current_session_id = None
            self._current_messages = []
            
            # 禁用按钮
            self._restore_btn.setEnabled(False)
            self._export_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)

    # ============================================================
    # 国际化支持
    # ============================================================

    def retranslate_ui(self) -> None:
        """刷新所有 UI 文本"""
        # 对话框标题
        self.setWindowTitle(
            self._get_text("dialog.history.title", "Conversation History")
        )
        
        # 组标题
        for group in self.findChildren(QGroupBox):
            group_type = group.property("group_type")
            if group_type == "session_list":
                group.setTitle(self._get_text("dialog.history.sessions", "Sessions"))
            elif group_type == "session_detail":
                group.setTitle(self._get_text("dialog.history.detail", "Session Detail"))
        
        # 按钮文本
        if self._restore_btn:
            self._restore_btn.setText(self._get_text("btn.restore", "Restore"))
        if self._export_btn:
            self._export_btn.setText(self._get_text("btn.export", "Export"))
        if self._delete_btn:
            self._delete_btn.setText(self._get_text("btn.delete", "Delete"))
        if self._close_btn:
            self._close_btn.setText(self._get_text("btn.close", "Close"))

    def _subscribe_events(self) -> None:
        """订阅事件"""
        if self.event_bus:
            from shared.event_types import EVENT_LANGUAGE_CHANGED
            self.event_bus.subscribe(EVENT_LANGUAGE_CHANGED, self._on_language_changed)

    def _on_language_changed(self, event_data: Dict[str, Any]) -> None:
        """语言变更事件处理"""
        self.retranslate_ui()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "HistoryDialog",
    "SessionInfo",
]
