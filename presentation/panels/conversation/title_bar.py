# Title Bar Component
"""
标题栏组件

职责：
- 管理对话面板标题栏
- 会话名称显示/编辑
- 操作按钮（新开对话、历史、清空）

信号：
- new_conversation_clicked() - 新开对话按钮点击
- history_clicked() - 历史对话按钮点击
- clear_clicked() - 清空对话按钮点击
- session_name_changed(name) - 会话名称变更
"""

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QFrame,
    QToolButton,
)


# ============================================================
# 常量定义
# ============================================================

TITLE_BAR_HEIGHT = 40
TITLE_BAR_BG = "#ffffff"
TITLE_BAR_BORDER = "#e0e0e0"


# ============================================================
# TitleBar 类
# ============================================================

class TitleBar(QWidget):
    """
    对话面板标题栏组件
    
    包含会话名称显示/编辑和操作按钮。
    """
    
    # 信号定义
    new_conversation_clicked = pyqtSignal()
    history_clicked = pyqtSignal()
    clear_clicked = pyqtSignal()
    session_name_changed = pyqtSignal(str)
    
    def __init__(self, parent: Optional[QWidget] = None):
        """初始化标题栏"""
        super().__init__(parent)
        
        # 延迟获取的服务
        self._i18n = None
        
        # UI 组件引用
        self._session_name_label: Optional[QLabel] = None
        self._session_name_edit: Optional[QLineEdit] = None
        self._new_btn: Optional[QToolButton] = None
        self._history_btn: Optional[QToolButton] = None
        self._clear_btn: Optional[QToolButton] = None
        
        # 初始化 UI
        self._setup_ui()
    
    # ============================================================
    # 延迟获取服务
    # ============================================================
    
    @property
    def i18n(self):
        """延迟获取国际化管理器"""
        if self._i18n is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_I18N_MANAGER
                self._i18n = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            except Exception:
                pass
        return self._i18n
    
    def _get_text(self, key: str, default: str = "") -> str:
        """获取国际化文本"""
        if self.i18n:
            return self.i18n.get_text(key, default)
        return default
    
    # ============================================================
    # UI 初始化
    # ============================================================
    
    def _setup_ui(self) -> None:
        """设置 UI 布局"""
        self.setFixedHeight(TITLE_BAR_HEIGHT)
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {TITLE_BAR_BG};
                border-bottom: 1px solid {TITLE_BAR_BORDER};
            }}
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        
        # 会话名称标签（可点击编辑）
        self._session_name_label = QLabel(
            self._get_text("panel.new_conversation", "新对话")
        )
        self._session_name_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-weight: bold;
                color: #333333;
                background: transparent;
                border: none;
            }
        """)
        self._session_name_label.setCursor(Qt.CursorShape.IBeamCursor)
        self._session_name_label.setToolTip(
            self._get_text("hint.click_to_edit", "Click to edit")
        )
        self._session_name_label.mousePressEvent = self._on_name_clicked
        layout.addWidget(self._session_name_label)
        
        # 会话名称编辑框（初始隐藏）
        self._session_name_edit = QLineEdit()
        self._session_name_edit.setFixedWidth(150)
        self._session_name_edit.setStyleSheet("""
            QLineEdit {
                font-size: 14px;
                font-weight: bold;
                color: #333333;
                border: 1px solid #4a9eff;
                border-radius: 4px;
                padding: 2px 6px;
                background: white;
            }
        """)
        self._session_name_edit.setVisible(False)
        self._session_name_edit.editingFinished.connect(self._on_edit_finished)
        self._session_name_edit.returnPressed.connect(self._on_edit_finished)
        layout.addWidget(self._session_name_edit)
        
        layout.addStretch()
        
        # 新开对话按钮
        self._new_btn = QToolButton()
        self._new_btn.setToolTip(
            self._get_text("btn.new_conversation", "New conversation")
        )
        self._new_btn.setFixedSize(28, 28)
        self._new_btn.setStyleSheet(self._get_button_style())
        self._set_icon(self._new_btn, "plus")
        self._new_btn.clicked.connect(self.new_conversation_clicked.emit)
        layout.addWidget(self._new_btn)
        
        # 历史对话按钮
        self._history_btn = QToolButton()
        self._history_btn.setToolTip(self._get_text("btn.history", "History"))
        self._history_btn.setFixedSize(28, 28)
        self._history_btn.setStyleSheet(self._get_button_style())
        self._set_icon(self._history_btn, "history")
        self._history_btn.clicked.connect(self.history_clicked.emit)
        layout.addWidget(self._history_btn)
        
        # 清空对话按钮
        self._clear_btn = QToolButton()
        self._clear_btn.setToolTip(
            self._get_text("btn.clear_conversation", "Clear conversation")
        )
        self._clear_btn.setFixedSize(28, 28)
        self._clear_btn.setStyleSheet(self._get_button_style())
        self._set_icon(self._clear_btn, "trash")
        self._clear_btn.clicked.connect(self.clear_clicked.emit)
        layout.addWidget(self._clear_btn)
    
    def _get_button_style(self) -> str:
        """获取按钮样式"""
        return """
            QToolButton {
                background-color: transparent;
                border: none;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QToolButton:hover {
                background-color: #f0f0f0;
            }
            QToolButton:pressed {
                background-color: #e0e0e0;
            }
        """
    
    def _set_icon(self, button: QToolButton, icon_type: str, size: int = 16) -> None:
        """设置按钮图标"""
        try:
            from resources.resource_loader import get_panel_icon
            icon = get_panel_icon(icon_type)
            if not icon.isNull():
                button.setIcon(icon)
                button.setIconSize(QSize(size, size))
        except Exception:
            pass
    
    # ============================================================
    # 公共方法
    # ============================================================
    
    def set_session_name(self, name: str) -> None:
        """设置会话名称显示"""
        display_name = name or self._get_text("panel.new_conversation", "新对话")
        if self._session_name_label:
            self._session_name_label.setText(display_name)
    
    def get_session_name(self) -> str:
        """获取当前会话名称"""
        if self._session_name_label:
            return self._session_name_label.text()
        return ""
    
    def enter_edit_mode(self) -> None:
        """进入名称编辑模式"""
        if self._session_name_label and self._session_name_edit:
            current_name = self._session_name_label.text()
            self._session_name_edit.setText(current_name)
            self._session_name_label.setVisible(False)
            self._session_name_edit.setVisible(True)
            self._session_name_edit.setFocus()
            self._session_name_edit.selectAll()
    
    def exit_edit_mode(self) -> None:
        """退出编辑模式并保存"""
        self._on_edit_finished()
    
    # ============================================================
    # 事件处理
    # ============================================================
    
    def _on_name_clicked(self, event) -> None:
        """会话名称点击事件"""
        self.enter_edit_mode()
    
    def _on_edit_finished(self) -> None:
        """编辑完成事件"""
        if not self._session_name_label or not self._session_name_edit:
            return
        
        new_name = self._session_name_edit.text().strip()
        if not new_name:
            new_name = self._get_text("panel.new_conversation", "新对话")
        
        old_name = self._session_name_label.text()
        self._session_name_label.setText(new_name)
        self._session_name_edit.setVisible(False)
        self._session_name_label.setVisible(True)
        
        # 如果名称有变化，发送信号
        if new_name != old_name:
            self.session_name_changed.emit(new_name)
    
    # ============================================================
    # 国际化
    # ============================================================
    
    def retranslate_ui(self) -> None:
        """刷新 UI 文本"""
        if self._new_btn:
            self._new_btn.setToolTip(
                self._get_text("btn.new_conversation", "New conversation")
            )
        if self._history_btn:
            self._history_btn.setToolTip(
                self._get_text("btn.history", "History")
            )
        if self._clear_btn:
            self._clear_btn.setToolTip(
                self._get_text("btn.clear_conversation", "Clear conversation")
            )
        if self._session_name_label:
            self._session_name_label.setToolTip(
                self._get_text("hint.click_to_edit", "Click to edit")
            )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "TitleBar",
    "TITLE_BAR_HEIGHT",
]
