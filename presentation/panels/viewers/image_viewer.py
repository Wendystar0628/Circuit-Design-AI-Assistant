# Image Viewer Component
"""
图片预览组件

专注于图片文件的预览显示。

功能：
- 居中显示图片
- 支持缩放（放大、缩小、适应窗口）
- 支持滚动查看大图

支持格式：.png、.jpg、.jpeg、.gif、.bmp

视觉设计：
- 背景色：#f5f5f5（浅灰）
- 图片居中显示
"""

from typing import Optional

from PyQt6.QtWidgets import QScrollArea, QLabel
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap


class ImageViewer(QScrollArea):
    """
    图片预览组件
    
    功能：
    - 居中显示图片
    - 支持缩放
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 图片标签
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet("background-color: #f5f5f5;")
        
        # 原始图片
        self._original_pixmap: Optional[QPixmap] = None
        
        # 缩放比例
        self._scale_factor = 1.0
        
        # 设置滚动区域
        self.setWidget(self._image_label)
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #f5f5f5; border: none;")
    
    def load_image(self, path: str) -> bool:
        """
        加载图片
        
        Args:
            path: 图片文件路径
            
        Returns:
            bool: 是否加载成功
        """
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._image_label.setText("Failed to load image")
            return False
        
        self._original_pixmap = pixmap
        self._scale_factor = 1.0
        self._update_display()
        return True
    
    def _update_display(self):
        """更新显示"""
        if self._original_pixmap is None:
            return
        
        # 计算缩放后的尺寸
        scaled_pixmap = self._original_pixmap.scaled(
            int(self._original_pixmap.width() * self._scale_factor),
            int(self._original_pixmap.height() * self._scale_factor),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        self._image_label.setPixmap(scaled_pixmap)
    
    def zoom_in(self):
        """放大"""
        self._scale_factor *= 1.25
        self._update_display()
    
    def zoom_out(self):
        """缩小"""
        self._scale_factor *= 0.8
        self._update_display()
    
    def fit_to_window(self):
        """适应窗口"""
        if self._original_pixmap is None:
            return
        
        # 计算适应窗口的缩放比例
        viewport_size = self.viewport().size()
        img_size = self._original_pixmap.size()
        
        scale_w = viewport_size.width() / img_size.width()
        scale_h = viewport_size.height() / img_size.height()
        
        self._scale_factor = min(scale_w, scale_h, 1.0)
        self._update_display()
    
    def get_scale_factor(self) -> float:
        """获取当前缩放比例"""
        return self._scale_factor
    
    def set_scale_factor(self, factor: float):
        """设置缩放比例"""
        self._scale_factor = factor
        self._update_display()


__all__ = ["ImageViewer"]
