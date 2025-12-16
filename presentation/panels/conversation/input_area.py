# Input Area Component
"""
输入区域组件

职责：
- 专注于用户输入和附件管理
- 处理文本输入、附件上传、发送操作
- 支持拖放上传和键盘快捷键

使用示例：
    from presentation.panels.conversation.input_area import InputArea
    
    input_area = InputArea()
    input_area.send_clicked.connect(on_send)
    text = input_area.get_text()
"""

import os
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QKeyEvent
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QPushButton,
    QTextEdit,
    QToolButton,
    QFileDialog,
    QMessageBox,
    QSizePolicy,
    QProgressBar,
)

# ============================================================
# 样式常量
# ============================================================

PRIMARY_COLOR = "#4a9eff"
BORDER_COLOR = "#e0e0e0"
BACKGROUND_COLOR = "#f5f5f5"
INPUT_BORDER_RADIUS = 8

# 附件限制
MAX_IMAGE_SIZE_MB = 10
ALLOWED_IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp"]

# 上下文占用阈值
WARNING_THRESHOLD = 0.60
CRITICAL_THRESHOLD = 0.80
COLOR_NORMAL = "#4caf50"
COLOR_WARNING = "#ff9800"
COLOR_CRITICAL = "#f44336"


# ============================================================
# InputArea 类
# ============================================================

class InputArea(QWidget):
    """
    输入区域组件
    
    专注于用户输入和附件管理。
    """
    
    # 信号定义
    send_clicked = pyqtSignal()                    # 发送按钮点击
    text_changed = pyqtSignal(str)                 # 文本变化
    attachment_added = pyqtSignal(dict)            # 附件添加
    attachment_removed = pyqtSignal(int)           # 附件移除
    upload_image_clicked = pyqtSignal()            # 上传图片按钮点击
    select_file_clicked = pyqtSignal()             # 选择文件按钮点击
    
    def __init__(self, parent: Optional[QWidget] = None):
        """初始化输入区域"""
        super().__init__(parent)
        
        # 内部状态
        self._attachments: List[Dict[str, Any]] = []
        self._enabled = True
        
        # UI 组件引用
        self._input_text: Optional[QTextEdit] = None
        self._send_button: Optional[QPushButton] = None
        self._attachments_area: Optional[QWidget] = None
        self._attachments_layout: Optional[QHBoxLayout] = None
        self._progress_bar: Optional[QProgressBar] = None
        self._usage_label: Optional[QLabel] = None
        self._token_label: Optional[QLabel] = None
        
        # 延迟获取的服务
        self._i18n = None
        
        # 初始化 UI
        self._setup_ui()
        
        # 启用拖放
        self.setAcceptDrops(True)
    
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


    def _setup_ui(self) -> None:
        """设置 UI 布局（参考 Cursor 风格）"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 0, 12, 12)
        main_layout.setSpacing(8)
        
        # 移除输入区域的白色背景
        self.setStyleSheet("background-color: transparent;")
        
        # 附件预览区（初始隐藏，位于输入框上方）
        self._attachments_area = QWidget()
        self._attachments_area.setVisible(False)
        self._attachments_layout = QHBoxLayout(self._attachments_area)
        self._attachments_layout.setContentsMargins(0, 0, 0, 0)
        self._attachments_layout.setSpacing(6)
        self._attachments_layout.addStretch()
        main_layout.addWidget(self._attachments_area)
        
        # 输入框容器（包含输入框和内部按钮）
        input_container = QWidget()
        input_container_layout = QVBoxLayout(input_container)
        input_container_layout.setContentsMargins(0, 0, 0, 0)
        input_container_layout.setSpacing(0)
        
        # 输入框
        self._input_text = QTextEdit()
        self._input_text.setPlaceholderText(
            self._get_text("hint.enter_message", "Enter your message...")
        )
        self._input_text.setMaximumHeight(100)
        self._input_text.setMinimumHeight(60)
        self._input_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {BACKGROUND_COLOR};
                border: 1px solid {BORDER_COLOR};
                border-radius: {INPUT_BORDER_RADIUS}px;
                padding: 8px 70px 28px 8px;
                font-size: 14px;
            }}
            QTextEdit:focus {{
                border-color: {PRIMARY_COLOR};
            }}
        """)
        self._input_text.textChanged.connect(self._on_text_changed)
        self._input_text.installEventFilter(self)
        input_container_layout.addWidget(self._input_text)
        
        # 底部按钮区（位于输入框内部底部，左侧附件按钮，右侧发送按钮）
        self._bottom_buttons = QWidget(self._input_text)
        bottom_btn_layout = QHBoxLayout(self._bottom_buttons)
        bottom_btn_layout.setContentsMargins(4, 0, 4, 4)
        bottom_btn_layout.setSpacing(2)
        
        # 上传图片按钮（SVG 图标）
        self._upload_image_btn = QToolButton()
        self._upload_image_btn.setToolTip(self._get_text("btn.upload_image", "Upload image"))
        self._upload_image_btn.setFixedSize(24, 24)
        self._upload_image_btn.setStyleSheet(self._get_inline_button_style())
        self._upload_image_btn.clicked.connect(self._on_upload_image_clicked)
        self._set_svg_icon(self._upload_image_btn, "image")
        bottom_btn_layout.addWidget(self._upload_image_btn)
        
        # 选择文件按钮（SVG 图标）
        self._select_file_btn = QToolButton()
        self._select_file_btn.setToolTip(self._get_text("btn.select_file", "Attach file"))
        self._select_file_btn.setFixedSize(24, 24)
        self._select_file_btn.setStyleSheet(self._get_inline_button_style())
        self._select_file_btn.clicked.connect(self._on_select_file_clicked)
        self._set_svg_icon(self._select_file_btn, "paperclip")
        bottom_btn_layout.addWidget(self._select_file_btn)
        
        bottom_btn_layout.addStretch()
        
        # 上下文占用信息区（居中显示）
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setFixedWidth(80)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._update_progress_style(COLOR_NORMAL)
        bottom_btn_layout.addWidget(self._progress_bar)
        
        self._usage_label = QLabel("0%")
        self._usage_label.setStyleSheet("""
            QLabel {
                color: #666666;
                font-size: 10px;
                background: transparent;
                border: none;
            }
        """)
        self._usage_label.setFixedWidth(28)
        bottom_btn_layout.addWidget(self._usage_label)
        
        self._token_label = QLabel("")
        self._token_label.setStyleSheet("""
            QLabel {
                color: #999999;
                font-size: 10px;
                background: transparent;
                border: none;
            }
        """)
        bottom_btn_layout.addWidget(self._token_label)
        
        bottom_btn_layout.addStretch()
        
        # 发送按钮（位于输入框内部右下角）
        self._send_button = QPushButton()
        self._send_button.setText(self._get_text("btn.send", "Send"))
        self._send_button.setFixedSize(56, 24)
        self._send_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {PRIMARY_COLOR};
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
                padding: 0px 4px;
            }}
            QPushButton:hover {{
                background-color: #3d8be8;
            }}
            QPushButton:pressed {{
                background-color: #2d7bd8;
            }}
            QPushButton:disabled {{
                background-color: #cccccc;
            }}
        """)
        self._send_button.clicked.connect(self._on_send_clicked)
        bottom_btn_layout.addWidget(self._send_button)
        
        main_layout.addWidget(input_container)
    
    def _get_tool_button_style(self) -> str:
        """获取工具按钮样式"""
        return """
            QToolButton {
                background-color: transparent;
                border: none;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 16px;
            }
            QToolButton:hover {
                background-color: #f0f0f0;
            }
            QToolButton:pressed {
                background-color: #e0e0e0;
            }
        """
    
    def _get_inline_button_style(self) -> str:
        """获取输入框内部按钮样式"""
        return """
            QToolButton {
                background-color: transparent;
                border: none;
                border-radius: 4px;
                padding: 2px;
            }
            QToolButton:hover {
                background-color: rgba(0, 0, 0, 0.08);
            }
            QToolButton:pressed {
                background-color: rgba(0, 0, 0, 0.12);
            }
        """
    
    def _set_svg_icon(self, button: QToolButton, icon_type: str, size: int = 16) -> None:
        """
        设置 SVG 图标（从本地文件加载）
        
        Args:
            button: 目标按钮
            icon_type: 图标类型名称（对应 resources/icons/panel/ 下的文件名）
            size: 图标尺寸
        """
        from PyQt6.QtCore import QSize
        try:
            from resources.resource_loader import get_panel_icon
            icon = get_panel_icon(icon_type)
            if not icon.isNull():
                button.setIcon(icon)
                button.setIconSize(QSize(size, size))
        except Exception:
            pass  # 图标加载失败时静默处理
    
    # ============================================================
    # 公共方法
    # ============================================================
    
    def get_text(self) -> str:
        """获取输入文本"""
        if self._input_text:
            return self._input_text.toPlainText()
        return ""
    
    def set_text(self, text: str) -> None:
        """设置输入文本"""
        if self._input_text:
            self._input_text.setPlainText(text)
    
    def clear(self) -> None:
        """清空输入"""
        if self._input_text:
            self._input_text.clear()
        self.clear_attachments()
    
    def add_attachment(self, path: str, att_type: str = "file") -> bool:
        """
        添加附件
        
        Args:
            path: 文件路径
            att_type: 附件类型（image/file）
            
        Returns:
            bool: 是否添加成功
        """
        # 检查文件是否存在
        if not os.path.isfile(path):
            return False
        
        # 检查图片大小
        if att_type == "image":
            file_size = os.path.getsize(path)
            if file_size > MAX_IMAGE_SIZE_MB * 1024 * 1024:
                return False
        
        # 添加到列表
        attachment = {
            "type": att_type,
            "path": path,
            "name": os.path.basename(path),
            "size": os.path.getsize(path),
        }
        self._attachments.append(attachment)
        
        # 更新 UI
        self._update_attachments_ui()
        
        # 发出信号
        self.attachment_added.emit(attachment)
        
        return True
    
    def remove_attachment(self, index: int) -> None:
        """移除附件"""
        if 0 <= index < len(self._attachments):
            self._attachments.pop(index)
            self._update_attachments_ui()
            self.attachment_removed.emit(index)
    
    def clear_attachments(self) -> None:
        """清空所有附件"""
        self._attachments.clear()
        self._update_attachments_ui()
    
    def get_attachments(self) -> List[Dict[str, Any]]:
        """获取附件列表"""
        return self._attachments.copy()
    
    def set_enabled(self, enabled: bool) -> None:
        """设置输入状态"""
        self._enabled = enabled
        
        if self._send_button:
            self._send_button.setEnabled(enabled)
            if enabled:
                self._send_button.setText(self._get_text("btn.send", "Send"))
            else:
                self._send_button.setText("...")
        
        # 输入框始终可编辑
        # if self._input_text:
        #     self._input_text.setEnabled(enabled)
    
    def set_send_enabled(self, enabled: bool) -> None:
        """设置发送按钮状态（别名方法）"""
        self.set_enabled(enabled)
    
    def is_enabled(self) -> bool:
        """检查是否启用"""
        return self._enabled
    
    def clear_text(self) -> None:
        """清空输入文本"""
        if self._input_text:
            self._input_text.clear()
    
    def focus_input(self) -> None:
        """聚焦到输入框"""
        if self._input_text:
            self._input_text.setFocus()
    
    def update_usage(self, ratio: float, current_tokens: int = 0, max_tokens: int = 0) -> None:
        """
        更新上下文占用显示
        
        Args:
            ratio: 占用比例 (0.0 - 1.0)
            current_tokens: 当前使用的 token 数
            max_tokens: 最大 token 数
        """
        ratio = max(0.0, min(1.0, ratio))
        percentage = int(ratio * 100)
        
        # 更新进度条值
        if self._progress_bar:
            self._progress_bar.setValue(percentage)
        
        # 更新百分比标签
        if self._usage_label:
            self._usage_label.setText(f"{percentage}%")
        
        # 更新 token 数量标签
        if self._token_label:
            if max_tokens > 0:
                self._token_label.setText(f"{self._format_tokens(current_tokens)} / {self._format_tokens(max_tokens)}")
            else:
                self._token_label.setText("")
        
        # 根据占用率更新样式
        if ratio >= CRITICAL_THRESHOLD:
            self._update_progress_style(COLOR_CRITICAL)
        elif ratio >= WARNING_THRESHOLD:
            self._update_progress_style(COLOR_WARNING)
        else:
            self._update_progress_style(COLOR_NORMAL)
    
    def _format_tokens(self, tokens: int) -> str:
        """格式化 token 数量显示"""
        if tokens >= 1000:
            return f"{tokens / 1000:.1f}k"
        return str(tokens)
    
    def _update_progress_style(self, color: str) -> None:
        """更新进度条样式"""
        if self._progress_bar:
            self._progress_bar.setStyleSheet(f"""
                QProgressBar {{
                    background-color: #e0e0e0;
                    border-radius: 3px;
                    border: none;
                }}
                QProgressBar::chunk {{
                    background-color: {color};
                    border-radius: 3px;
                }}
            """)


    # ============================================================
    # 附件 UI 管理
    # ============================================================
    
    def _update_attachments_ui(self) -> None:
        """更新附件预览 UI"""
        if self._attachments_area is None or self._attachments_layout is None:
            return
        
        # 清空现有预览（保留最后的 stretch）
        while self._attachments_layout.count() > 1:
            item = self._attachments_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # 添加新预览
        for i, att in enumerate(self._attachments):
            preview = self._create_attachment_preview(att, i)
            self._attachments_layout.insertWidget(i, preview)
        
        # 显示/隐藏附件区
        self._attachments_area.setVisible(len(self._attachments) > 0)
    
    def _create_attachment_preview(
        self, attachment: Dict[str, Any], index: int
    ) -> QWidget:
        """创建附件预览组件（紧凑标签样式）"""
        container = QFrame()
        container.setFixedHeight(26)
        container.setStyleSheet("""
            QFrame {
                background-color: #f0f0f0;
                border: 1px solid #e0e0e0;
                border-radius: 4px;
            }
        """)
        
        layout = QHBoxLayout(container)
        layout.setContentsMargins(8, 2, 4, 2)
        layout.setSpacing(4)
        
        # 文件名（截断显示，保留扩展名）
        name = attachment["name"]
        if len(name) > 20:
            # 保留扩展名
            base, ext = os.path.splitext(name)
            max_base_len = 16 - len(ext)
            if max_base_len > 3:
                name = base[:max_base_len] + "..." + ext
            else:
                name = base[:13] + "..."
        
        name_label = QLabel(name)
        name_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #333333;
                background: transparent;
                border: none;
            }
        """)
        layout.addWidget(name_label)
        
        # 删除按钮（小叉号）
        delete_btn = QToolButton()
        delete_btn.setFixedSize(20, 20)
        delete_btn.setStyleSheet("""
            QToolButton {
                background-color: transparent;
                border: none;
                border-radius: 10px;
                padding: 0px;
            }
            QToolButton:hover {
                background-color: rgba(0, 0, 0, 0.1);
            }
        """)
        # 设置关闭图标
        self._set_close_icon(delete_btn, 16)
        delete_btn.clicked.connect(lambda: self.remove_attachment(index))
        layout.addWidget(delete_btn)
        
        return container
    
    def _set_close_icon(self, button: QToolButton, size: int = 16) -> None:
        """设置关闭图标（从本地文件加载）"""
        from PyQt6.QtCore import QSize
        try:
            from resources.resource_loader import get_panel_icon
            icon = get_panel_icon("close")
            if not icon.isNull():
                button.setIcon(icon)
                button.setIconSize(QSize(size, size))
        except Exception:
            pass  # 图标加载失败时静默处理
    
    # ============================================================
    # 事件处理
    # ============================================================
    
    def _on_text_changed(self) -> None:
        """处理文本变化"""
        if self._input_text:
            self.text_changed.emit(self._input_text.toPlainText())
    
    def _on_send_clicked(self) -> None:
        """处理发送按钮点击"""
        if self._enabled:
            self.send_clicked.emit()
    
    def _on_upload_image_clicked(self) -> None:
        """处理上传图片按钮点击"""
        # 只发出信号，由 ConversationPanel 处理文件选择
        self.upload_image_clicked.emit()
    
    def _on_select_file_clicked(self) -> None:
        """处理选择文件按钮点击"""
        # 只发出信号，由 ConversationPanel 处理文件选择
        self.select_file_clicked.emit()
    
    # ============================================================
    # 拖放处理
    # ============================================================
    
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """处理拖入事件"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def dropEvent(self, event: QDropEvent) -> None:
        """处理放下事件"""
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path):
                ext = os.path.splitext(path)[1].lower()
                if ext in ALLOWED_IMAGE_EXTENSIONS:
                    self.add_attachment(path, "image")
                else:
                    self.add_attachment(path, "file")
    
    # ============================================================
    # 键盘事件处理
    # ============================================================
    
    def eventFilter(self, obj, event) -> bool:
        """事件过滤器，处理输入框的键盘事件"""
        if obj == self._input_text and event.type() == event.Type.KeyPress:
            key_event = event
            if (key_event.key() == Qt.Key.Key_Return and
                not key_event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                # Enter 发送消息
                if self._enabled:
                    self.send_clicked.emit()
                return True
        return super().eventFilter(obj, event)
    
    # ============================================================
    # 布局调整
    # ============================================================
    
    def resizeEvent(self, event) -> None:
        """处理大小变化，调整底部按钮位置"""
        super().resizeEvent(event)
        self._update_bottom_buttons_position()
    
    def _update_bottom_buttons_position(self) -> None:
        """更新底部按钮位置（输入框内部底部，横跨整个宽度）"""
        if hasattr(self, '_bottom_buttons') and self._input_text:
            # 将按钮区放在输入框内部底部
            btn_height = 28
            margin = 4
            y_pos = self._input_text.height() - btn_height - margin
            width = self._input_text.width() - margin * 2
            self._bottom_buttons.setGeometry(margin, y_pos, width, btn_height)
    
    def showEvent(self, event) -> None:
        """显示时更新按钮位置"""
        super().showEvent(event)
        self._update_bottom_buttons_position()
    
    # ============================================================
    # 国际化
    # ============================================================
    
    def retranslate_ui(self) -> None:
        """刷新 UI 文本"""
        if self._send_button and self._enabled:
            self._send_button.setText(self._get_text("btn.send", "Send"))
        
        if self._input_text:
            self._input_text.setPlaceholderText(
                self._get_text("hint.enter_message", "Enter your message...")
            )
        
        # 更新按钮提示
        if hasattr(self, '_upload_image_btn'):
            self._upload_image_btn.setToolTip(
                self._get_text("btn.upload_image", "Upload image")
            )
        if hasattr(self, '_select_file_btn'):
            self._select_file_btn.setToolTip(
                self._get_text("btn.select_file", "Attach file")
            )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "InputArea",
    "MAX_IMAGE_SIZE_MB",
    "ALLOWED_IMAGE_EXTENSIONS",
]

