# History Dialog - Conversation History Viewer
"""
对话历史查看对话框

职责：
- 显示所有会话列表
- 支持打开、导出和删除历史对话
- 与 SessionStateManager 集成进行会话切换

会话自动保存机制：
- 每轮 LLM 输出完成后自动保存当前会话
- 切换会话时自动保存当前会话
- 无需手动归档，所有会话实时持久化

国际化支持：
- 实现 retranslate_ui() 方法
- 订阅 EVENT_LANGUAGE_CHANGED 事件
"""

import json
from datetime import datetime
from html import escape
from typing import Any, Dict, List, Optional

from domain.llm.session_state_manager import SessionInfo
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
        
        # 会话数据
        self._sessions: List[SessionInfo] = []
        self._current_session_id: Optional[str] = None
        self._current_messages: List[Dict[str, Any]] = []
        
        # UI 组件引用
        self._session_list: Optional[QListWidget] = None
        self._detail_text: Optional[QTextEdit] = None
        self._open_btn: Optional[QPushButton] = None
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
    def session_state_manager(self):
        """延迟获取 SessionStateManager"""
        if not hasattr(self, '_session_state_manager'):
            self._session_state_manager = None
        if self._session_state_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE_MANAGER
                self._session_state_manager = ServiceLocator.get_optional(SVC_SESSION_STATE_MANAGER)
            except Exception:
                pass
        return self._session_state_manager

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
                font-family: "JetBrains Mono", "Cascadia Code", "SF Mono", "Consolas", monospace;
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
        
        # 打开按钮
        self._open_btn = QPushButton()
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._on_open_clicked)
        layout.addWidget(self._open_btn)
        
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

    def load_sessions(self, preferred_session_id: Optional[str] = None) -> None:
        """加载所有会话列表"""
        if self._session_list is None:
            return

        self._sync_current_session_for_history()

        selected_session_id = (
            preferred_session_id
            or self._current_session_id
            or self._get_current_manager_session_id()
        )

        self._sessions.clear()
        self._session_list.blockSignals(True)
        self._session_list.clear()

        sessions = self._get_sessions_from_manager()
        
        for session in sessions:
            self._sessions.append(session)
            
            # 创建列表项
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, session.session_id)
            
            # 格式化显示文本
            display_text = self._format_session_item(session)
            item.setText(display_text)
            
            self._session_list.addItem(item)

        self._session_list.blockSignals(False)

        if selected_session_id and self._select_session_by_id(selected_session_id):
            if self.logger:
                self.logger.info(f"Loaded {len(self._sessions)} sessions")
            return

        if self._session_list.count() > 0:
            self._session_list.setCurrentRow(0)
        else:
            self._reset_detail_state()
        
        if self.logger:
            self.logger.info(f"Loaded {len(self._sessions)} sessions")

    def _get_sessions_from_manager(self) -> List[SessionInfo]:
        """从 SessionStateManager 获取会话列表"""
        sessions = []
        
        try:
            # 获取项目路径
            project_path = self._get_project_path()
            if not project_path:
                if self.logger:
                    self.logger.debug("No project path, cannot load sessions")
                return sessions
            
            # 使用 ServiceLocator 获取 SessionStateManager 单例
            if not self.session_state_manager:
                if self.logger:
                    self.logger.warning("SessionStateManager not available")
                return sessions
            
            sessions = self.session_state_manager.get_all_sessions(project_path)
            
            if self.logger:
                self.logger.info(f"Loaded {len(sessions)} sessions from SessionStateManager")
                
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to load sessions: {e}")
        
        return sessions
    
    def _get_project_path(self) -> Optional[str]:
        """获取当前项目路径"""
        if self.session_state_manager:
            try:
                project_root = self.session_state_manager.get_project_root()
                if project_root:
                    return project_root
            except Exception:
                pass

        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_SESSION_STATE
            
            session_state = ServiceLocator.get_optional(SVC_SESSION_STATE)
            if session_state:
                return session_state.project_root
        except Exception:
            pass
        return None

    def _get_current_manager_session_id(self) -> Optional[str]:
        if not self.session_state_manager:
            return None

        try:
            session_id = self.session_state_manager.get_current_session_id()
            return session_id or None
        except Exception:
            return None

    def _sync_current_session_for_history(self) -> None:
        project_path = self._get_project_path()
        if not project_path or not self.session_state_manager:
            return

        try:
            self.session_state_manager.ensure_current_session_persisted(project_path)
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to persist current session for history: {e}")

    def _find_session_info(self, session_id: str) -> Optional[SessionInfo]:
        for session in self._sessions:
            if session.session_id == session_id:
                return session
        return None

    def _select_session_by_id(self, session_id: Optional[str]) -> bool:
        if not session_id or self._session_list is None:
            return False

        for row, session in enumerate(self._sessions):
            if session.session_id == session_id:
                self._session_list.setCurrentRow(row)
                return True
        return False

    def _reset_detail_state(self) -> None:
        self._current_session_id = None
        self._current_messages = []
        if self._detail_text:
            self._detail_text.clear()
        if self._open_btn:
            self._open_btn.setEnabled(False)
        if self._export_btn:
            self._export_btn.setEnabled(False)
        if self._delete_btn:
            self._delete_btn.setEnabled(False)

    def _format_session_item(self, session: SessionInfo) -> str:
        """格式化会话列表项显示文本"""
        try:
            updated_at = datetime.fromisoformat(session.updated_at) if session.updated_at else datetime.now()
        except ValueError:
            updated_at = datetime.now()

        date_str = updated_at.strftime("%Y-%m-%d %H:%M")
        preview = session.preview[:30] + "..." if len(session.preview) > 30 else session.preview
        return f"{session.name}\n{date_str} | {session.message_count} msgs\n{preview}"

    def show_session_detail(self, session_id: str) -> None:
        """显示会话详情"""
        session = self._find_session_info(session_id)
        if session is None:
            self._reset_detail_state()
            return

        self._current_session_id = session_id
        self._current_messages = []
        
        messages = self._load_session_messages(session_id)
        self._current_messages = messages
        
        html_content = self._format_messages_for_display(session, messages)
        self._detail_text.setHtml(html_content)
        
        self._open_btn.setEnabled(True)
        self._export_btn.setEnabled(True)
        self._delete_btn.setEnabled(True)

    def _load_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """加载会话消息"""
        messages = []
        
        try:
            # 获取项目路径
            project_path = self._get_project_path()
            if not project_path:
                return messages

            if not self.session_state_manager:
                if self.logger:
                    self.logger.warning("SessionStateManager not available")
                return messages

            messages = self.session_state_manager.get_session_messages(
                session_id=session_id,
                project_root=project_path,
            )
            
            if self.logger:
                self.logger.debug(f"Loaded {len(messages)} messages for session: {session_id}")
                    
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Error loading session messages: {e}")
        
        return messages

    def _get_message_timestamp(self, message: Dict[str, Any]) -> str:
        additional_kwargs = message.get("additional_kwargs", {})
        if isinstance(additional_kwargs, dict):
            timestamp = additional_kwargs.get("timestamp", "")
            if timestamp:
                return str(timestamp)
        return str(message.get("timestamp", "") or "")

    def _format_detail_timestamp(self, timestamp: str) -> str:
        if not timestamp:
            return ""

        try:
            return datetime.fromisoformat(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return timestamp

    def _get_message_content(self, message: Dict[str, Any]) -> str:
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content
            )
        return str(content or "")

    def _format_messages_for_display(self, session: SessionInfo, messages: List[Dict[str, Any]]) -> str:
        """格式化消息用于显示"""
        detail_parts = [
            f"<div style='margin-bottom: 16px;'>"
            f"<div style='font-size: 16px; font-weight: 600; margin-bottom: 6px;'>{escape(session.name)}</div>"
            f"<div style='color: #666; font-size: 12px;'>"
            f"{escape(self._format_detail_timestamp(session.updated_at))} | {session.message_count} msgs"
            f"</div>"
            f"</div>"
        ]

        if not messages:
            detail_parts.append(
                f"<p style='color: #999;'>{escape(self._get_text('dialog.history.no_messages', 'No messages in this session'))}</p>"
            )
            return "".join(detail_parts)
        
        html_parts = []
        
        for msg in messages:
            role = msg.get("type", "unknown")
            content = self._get_message_content(msg)
            timestamp = self._format_detail_timestamp(self._get_message_timestamp(msg))
            
            if role == "user":
                role_color = "#4a9eff"
                role_label = self._get_text("role.user", "User")
            elif role == "assistant":
                role_color = "#4caf50"
                role_label = self._get_text("role.assistant", "Assistant")
            else:
                role_color = "#999999"
                role_label = self._get_text("role.system", "System")
            
            content_escaped = escape(content)
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
        
        detail_parts.extend(html_parts)
        return "".join(detail_parts)

    def open_session(self, session_id: str) -> bool:
        """打开会话（委托给 SessionStateManager 切换会话）"""
        if not session_id:
            return False
        
        try:
            project_path = self._get_project_path()
            if not project_path:
                if self.logger:
                    self.logger.error("No project path available")
                return False

            if not self.session_state_manager:
                if self.logger:
                    self.logger.error("SessionStateManager not available")
                return False

            self.session_state_manager.ensure_current_session_persisted(project_path)
            
            new_state = self.session_state_manager.switch_session(
                project_root=project_path,
                session_id=session_id,
                sync_to_context_manager=True
            )
            
            if new_state is not None:
                if self.logger:
                    self.logger.info(f"Session opened: {session_id}")
                return True
            else:
                if self.logger:
                    self.logger.warning(f"Failed to open session: {session_id}")
                return False
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to open session: {e}")
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
                role = msg.get("type", "unknown").upper()
                content = self._get_message_content(msg)
                timestamp = self._get_message_timestamp(msg)
                lines.append(f"[{role}] {timestamp}")
                lines.append(content)
                lines.append("")
            return "\n".join(lines)
        
        elif format == "md":
            lines = ["# Conversation Export", ""]
            for msg in messages:
                role = msg.get("type", "unknown")
                content = self._get_message_content(msg)
                timestamp = self._get_message_timestamp(msg)
                
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
        """删除会话（委托给 SessionStateManager）"""
        if not session_id:
            return False
        
        try:
            # 获取项目路径
            project_path = self._get_project_path()
            if not project_path:
                if self.logger:
                    self.logger.error("No project path available")
                return False
            
            # 使用 ServiceLocator 获取 SessionStateManager 单例
            if not self.session_state_manager:
                if self.logger:
                    self.logger.error("SessionStateManager not available")
                return False
            
            success = self.session_state_manager.delete_session(project_root=project_path, session_id=session_id)
            
            if success:
                if self.logger:
                    self.logger.info(f"Session deleted: {session_id}")
                return True
            else:
                if self.logger:
                    self.logger.warning(f"Failed to delete session: {session_id}")
                return False
                
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
            self._reset_detail_state()
            return
        
        session_id = current.data(Qt.ItemDataRole.UserRole)
        self.show_session_detail(session_id)

    def _on_session_double_clicked(self, item: QListWidgetItem) -> None:
        """会话双击（快速打开）"""
        session_id = item.data(Qt.ItemDataRole.UserRole)
        self._on_open_clicked()

    def _on_open_clicked(self) -> None:
        """打开按钮点击"""
        if not self._current_session_id:
            return
        
        # 直接打开会话，无需确认（当前会话会自动保存）
        if self.open_session(self._current_session_id):
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
            self.load_sessions(preferred_session_id=self._get_current_manager_session_id())

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
        if self._open_btn:
            self._open_btn.setText(self._get_text("btn.open", "Open"))
        if self._export_btn:
            self._export_btn.setText(self._get_text("btn.export", "Export"))
        if self._delete_btn:
            self._delete_btn.setText(self._get_text("btn.delete", "Delete"))
        if self._close_btn:
            self._close_btn.setText(self._get_text("btn.close", "Close"))

    def _subscribe_events(self) -> None:
        """订阅事件"""
        if self.event_bus:
            from shared.event_types import EVENT_LANGUAGE_CHANGED, EVENT_SESSION_CHANGED
            self.event_bus.subscribe(EVENT_LANGUAGE_CHANGED, self._on_language_changed)
            self.event_bus.subscribe(EVENT_SESSION_CHANGED, self._on_session_changed)

    def _unsubscribe_events(self) -> None:
        if self.event_bus:
            from shared.event_types import EVENT_LANGUAGE_CHANGED, EVENT_SESSION_CHANGED
            self.event_bus.unsubscribe(EVENT_LANGUAGE_CHANGED, self._on_language_changed)
            self.event_bus.unsubscribe(EVENT_SESSION_CHANGED, self._on_session_changed)

    def _on_language_changed(self, event_data: Dict[str, Any]) -> None:
        """语言变更事件处理"""
        self.retranslate_ui()

    def _on_session_changed(self, event_data: Dict[str, Any]) -> None:
        data = event_data.get("data", event_data)
        session_id = data.get("session_id", "") or self._current_session_id

        self.load_sessions(preferred_session_id=session_id)

        if not session_id:
            return

        if self._select_session_by_id(session_id):
            return

        self._reset_detail_state()

    def closeEvent(self, event) -> None:
        self._unsubscribe_events()
        super().closeEvent(event)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "HistoryDialog",
]
