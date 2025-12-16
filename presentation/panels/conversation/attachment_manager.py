# Attachment Manager Component
"""
附件管理器

职责：
- 管理附件的添加、预览和删除
- 验证图片格式和大小
- 提供附件列表访问

信号：
- attachments_changed(count) - 附件数量变化
- attachment_error(message) - 附件错误
"""

import os
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import pyqtSignal, QSize
from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLabel,
    QFrame,
    QToolButton,
)


# ============================================================
# 常量定义
# ============================================================

# 图片上传限制
MAX_IMAGE_SIZE_MB = 10
ALLOWED_IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp"]

# 附件类型
ATTACHMENT_TYPE_IMAGE = "image"
ATTACHMENT_TYPE_FILE = "file"


# ============================================================
# AttachmentManager 类
# ============================================================

class AttachmentManager(QWidget):
    """
    附件管理器组件
    
    管理附件的添加、预览和删除。
    """
    
    # 信号定义
    attachments_changed = pyqtSignal(int)  # 附件数量变化
    attachment_error = pyqtSignal(str)     # 附件错误
    
    def __init__(self, parent: Optional[QWidget] = None):
        """初始化附件管理器"""
        super().__init__(parent)
        
        # 延迟获取的服务
        self._i18n = None
        self._logger = None
        
        # 内部状态
        self._attachments: List[Dict[str, Any]] = []
        
        # UI 组件引用
        self._preview_layout: Optional[QHBoxLayout] = None
        
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
    
    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("attachment_manager")
            except Exception:
                pass
        return self._logger
    
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
        self.setVisible(False)  # 初始隐藏
        
        self._preview_layout = QHBoxLayout(self)
        self._preview_layout.setContentsMargins(0, 0, 0, 0)
        self._preview_layout.setSpacing(6)
        self._preview_layout.addStretch()
    
    # ============================================================
    # 公共方法
    # ============================================================
    
    def add_attachment(self, path: str, att_type: str) -> bool:
        """
        添加附件
        
        Args:
            path: 文件路径
            att_type: 附件类型 ("image" | "file")
            
        Returns:
            是否添加成功
        """
        # 验证文件存在
        if not os.path.isfile(path):
            self.attachment_error.emit(
                self._get_text("error.file_not_found", "File not found")
            )
            return False
        
        # 验证图片
        if att_type == ATTACHMENT_TYPE_IMAGE:
            error = self.validate_image(path)
            if error:
                self.attachment_error.emit(error)
                return False
        
        # 添加到列表
        attachment = {
            "type": att_type,
            "path": path,
            "name": os.path.basename(path),
        }
        self._attachments.append(attachment)
        
        # 更新 UI
        self._update_preview_ui()
        
        # 发送信号
        self.attachments_changed.emit(len(self._attachments))
        
        if self.logger:
            self.logger.debug(f"Added attachment: {path}")
        
        return True
    
    def remove_attachment(self, index: int) -> bool:
        """
        移除附件
        
        Args:
            index: 附件索引
            
        Returns:
            是否移除成功
        """
        if 0 <= index < len(self._attachments):
            removed = self._attachments.pop(index)
            self._update_preview_ui()
            self.attachments_changed.emit(len(self._attachments))
            
            if self.logger:
                self.logger.debug(f"Removed attachment: {removed.get('path')}")
            
            return True
        return False
    
    def clear_attachments(self) -> None:
        """清空所有附件"""
        if self._attachments:
            self._attachments.clear()
            self._update_preview_ui()
            self.attachments_changed.emit(0)
            
            if self.logger:
                self.logger.debug("Cleared all attachments")
    
    def get_attachments(self) -> List[Dict[str, Any]]:
        """获取附件列表"""
        return self._attachments.copy()
    
    def get_attachment_count(self) -> int:
        """获取附件数量"""
        return len(self._attachments)
    
    def validate_image(self, path: str) -> Optional[str]:
        """
        验证图片
        
        Args:
            path: 图片路径
            
        Returns:
            错误消息，None 表示验证通过
        """
        # 检查扩展名
        ext = os.path.splitext(path)[1].lower()
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            return self._get_text(
                "error.invalid_image_format",
                f"Invalid image format. Allowed: {', '.join(ALLOWED_IMAGE_EXTENSIONS)}"
            )
        
        # 检查文件大小
        try:
            file_size = os.path.getsize(path)
            max_size = MAX_IMAGE_SIZE_MB * 1024 * 1024
            if file_size > max_size:
                return self._get_text(
                    "error.image_too_large",
                    f"Image size exceeds {MAX_IMAGE_SIZE_MB}MB limit"
                )
        except OSError as e:
            return self._get_text(
                "error.file_access_error",
                f"Cannot access file: {e}"
            )
        
        return None
    
    def is_image_file(self, path: str) -> bool:
        """检查是否为图片文件"""
        ext = os.path.splitext(path)[1].lower()
        return ext in ALLOWED_IMAGE_EXTENSIONS
    
    # ============================================================
    # UI 更新
    # ============================================================
    
    def _update_preview_ui(self) -> None:
        """更新附件预览 UI"""
        if self._preview_layout is None:
            return
        
        # 清空现有预览（保留最后的 stretch）
        while self._preview_layout.count() > 1:
            item = self._preview_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # 添加新预览
        for i, att in enumerate(self._attachments):
            preview = self._create_preview_item(att, i)
            self._preview_layout.insertWidget(i, preview)
        
        # 显示/隐藏
        self.setVisible(len(self._attachments) > 0)
    
    def _create_preview_item(
        self, attachment: Dict[str, Any], index: int
    ) -> QWidget:
        """创建附件预览项"""
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
        
        # 文件名（截断显示）
        name = self._truncate_filename(attachment["name"])
        name_label = QLabel(name)
        name_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #333333;
                background: transparent;
                border: none;
            }
        """)
        name_label.setToolTip(attachment["name"])
        layout.addWidget(name_label)
        
        # 删除按钮
        delete_btn = QToolButton()
        delete_btn.setFixedSize(18, 18)
        delete_btn.setStyleSheet("""
            QToolButton {
                background-color: transparent;
                border: none;
                border-radius: 9px;
            }
            QToolButton:hover {
                background-color: rgba(0, 0, 0, 0.1);
            }
        """)
        self._set_close_icon(delete_btn)
        delete_btn.clicked.connect(lambda: self.remove_attachment(index))
        layout.addWidget(delete_btn)
        
        return container
    
    def _truncate_filename(self, name: str, max_length: int = 20) -> str:
        """截断文件名"""
        if len(name) <= max_length:
            return name
        
        base, ext = os.path.splitext(name)
        max_base_len = max_length - len(ext) - 3  # 3 for "..."
        
        if max_base_len > 3:
            return base[:max_base_len] + "..." + ext
        else:
            return name[:max_length - 3] + "..."
    
    def _set_close_icon(self, button: QToolButton) -> None:
        """设置关闭图标"""
        try:
            from resources.resource_loader import get_panel_icon
            icon = get_panel_icon("close")
            if not icon.isNull():
                button.setIcon(icon)
                button.setIconSize(QSize(12, 12))
        except Exception:
            pass


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "AttachmentManager",
    "MAX_IMAGE_SIZE_MB",
    "ALLOWED_IMAGE_EXTENSIONS",
    "ATTACHMENT_TYPE_IMAGE",
    "ATTACHMENT_TYPE_FILE",
]
