# ChartViewer - Chart Display and Interaction Component
"""
图表查看器（基础版）

职责：
- 显示仿真结果图表（图片格式）
- 提供图表标签栏切换不同图表类型
- 支持缩放、平移、重置视图
- 支持图表导出（保存图片、复制到剪贴板）

设计原则：
- 基础版专注于图表显示和基本交互
- 高级功能（双光标测量、波形运算）由后续模块实现
- 与 ChartSelector 配合，显示用户选中的图表类型

被调用方：
- simulation_tab.py

使用示例：
    from presentation.panels.simulation.chart_viewer import ChartViewer
    
    viewer = ChartViewer()
    viewer.load_chart("/path/to/chart.png")
    viewer.set_chart_tabs(["bode_combined", "waveform_time"])
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QPoint, QSize, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QClipboard,
    QGuiApplication,
    QImage,
    QPixmap,
    QWheelEvent,
    QMouseEvent,
    QPainter,
)
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTabBar,
    QToolBar,
    QToolButton,
    QScrollArea,
    QFrame,
    QMenu,
    QFileDialog,
    QSizePolicy,
    QMessageBox,
)

from resources.theme import (
    COLOR_BG_PRIMARY,
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_BORDER,
    COLOR_ACCENT,
    COLOR_ACCENT_LIGHT,
    FONT_SIZE_NORMAL,
    FONT_SIZE_SMALL,
    SPACING_SMALL,
    SPACING_NORMAL,
    BORDER_RADIUS_NORMAL,
)


# ============================================================
# 常量定义
# ============================================================

# 缩放限制
ZOOM_MIN = 0.1
ZOOM_MAX = 10.0
ZOOM_STEP = 0.1
ZOOM_WHEEL_FACTOR = 0.001

# 图表背景色（深色，便于查看图表）
CHART_BG_COLOR = "#2d2d2d"


class ZoomableImageLabel(QLabel):
    """
    可缩放的图片标签
    
    支持：
    - 鼠标滚轮缩放
    - 拖拽平移
    - 双击重置视图
    """
    
    zoom_changed = pyqtSignal(float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._original_pixmap: Optional[QPixmap] = None
        self._zoom_level: float = 1.0
        self._pan_start: Optional[QPoint] = None
        self._pan_offset: QPoint = QPoint(0, 0)
        
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(100, 100)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        self.setMouseTracking(True)
    
    def set_pixmap(self, pixmap: Optional[QPixmap]):
        """设置图片"""
        self._original_pixmap = pixmap
        self._zoom_level = 1.0
        self._pan_offset = QPoint(0, 0)
        self._update_display()
    
    def get_zoom_level(self) -> float:
        """获取当前缩放级别"""
        return self._zoom_level
    
    def set_zoom_level(self, level: float):
        """设置缩放级别"""
        self._zoom_level = max(ZOOM_MIN, min(ZOOM_MAX, level))
        self._update_display()
        self.zoom_changed.emit(self._zoom_level)
    
    def zoom_in(self):
        """放大"""
        self.set_zoom_level(self._zoom_level + ZOOM_STEP)
    
    def zoom_out(self):
        """缩小"""
        self.set_zoom_level(self._zoom_level - ZOOM_STEP)
    
    def reset_view(self):
        """重置视图"""
        self._zoom_level = 1.0
        self._pan_offset = QPoint(0, 0)
        self._update_display()
        self.zoom_changed.emit(self._zoom_level)
    
    def fit_to_view(self):
        """适应视图大小"""
        if self._original_pixmap is None:
            return
        
        view_size = self.size()
        img_size = self._original_pixmap.size()
        
        if img_size.width() == 0 or img_size.height() == 0:
            return
        
        scale_x = view_size.width() / img_size.width()
        scale_y = view_size.height() / img_size.height()
        
        self._zoom_level = min(scale_x, scale_y) * 0.95
        self._pan_offset = QPoint(0, 0)
        self._update_display()
        self.zoom_changed.emit(self._zoom_level)
    
    def _update_display(self):
        """更新显示"""
        if self._original_pixmap is None:
            self.clear()
            return
        
        original_size = self._original_pixmap.size()
        scaled_width = int(original_size.width() * self._zoom_level)
        scaled_height = int(original_size.height() * self._zoom_level)
        scaled_size = QSize(scaled_width, scaled_height)
        
        scaled_pixmap = self._original_pixmap.scaled(
            scaled_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        super().setPixmap(scaled_pixmap)
    
    def wheelEvent(self, event: QWheelEvent):
        """鼠标滚轮缩放"""
        delta = event.angleDelta().y()
        zoom_delta = delta * ZOOM_WHEEL_FACTOR
        self.set_zoom_level(self._zoom_level + zoom_delta)
        event.accept()
    
    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下开始拖拽"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._pan_start = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """鼠标移动拖拽"""
        if self._pan_start is not None:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            # 简化实现：通过滚动区域实现平移
            parent = self.parent()
            if isinstance(parent, QScrollArea):
                h_bar = parent.horizontalScrollBar()
                v_bar = parent.verticalScrollBar()
                h_bar.setValue(h_bar.value() - delta.x())
                v_bar.setValue(v_bar.value() - delta.y())
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        """鼠标释放结束拖拽"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._pan_start = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)
    
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """双击重置视图"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_view()
        super().mouseDoubleClickEvent(event)


class ChartViewer(QWidget):
    """
    图表查看器
    
    显示仿真结果图表，支持标签切换、缩放、导出。
    
    Signals:
        tab_changed: 标签切换时发出，携带图表类型
        chart_exported: 图表导出时发出，携带导出路径
    """
    
    tab_changed = pyqtSignal(str)
    chart_exported = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # 状态
        self._chart_paths: Dict[str, str] = {}
        self._current_chart_type: Optional[str] = None
        self._chart_types: List[str] = []
        
        # 初始化 UI
        self._setup_ui()
        self._setup_context_menu()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI 组件"""
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 标签栏
        self._tab_bar = QTabBar()
        self._tab_bar.setObjectName("chartTabBar")
        self._tab_bar.setExpanding(False)
        self._tab_bar.setDrawBase(False)
        self._tab_bar.currentChanged.connect(self._on_tab_changed)
        main_layout.addWidget(self._tab_bar)
        
        # 图表显示区域
        self._chart_frame = QFrame()
        self._chart_frame.setObjectName("chartFrame")
        chart_layout = QVBoxLayout(self._chart_frame)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(0)
        
        # 滚动区域
        self._scroll_area = QScrollArea()
        self._scroll_area.setObjectName("chartScrollArea")
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        
        # 图片标签
        self._image_label = ZoomableImageLabel()
        self._image_label.setObjectName("chartImageLabel")
        self._image_label.zoom_changed.connect(self._on_zoom_changed)
        self._scroll_area.setWidget(self._image_label)
        
        chart_layout.addWidget(self._scroll_area, 1)
        
        # 空状态提示
        self._empty_label = QLabel()
        self._empty_label.setObjectName("emptyLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chart_layout.addWidget(self._empty_label)
        self._empty_label.hide()
        
        main_layout.addWidget(self._chart_frame, 1)
        
        # 工具栏
        self._toolbar = QToolBar()
        self._toolbar.setObjectName("chartToolbar")
        self._toolbar.setIconSize(QSize(16, 16))
        self._toolbar.setMovable(False)
        self._setup_toolbar()
        main_layout.addWidget(self._toolbar)
        
        # 状态栏（显示缩放级别）
        self._status_bar = QHBoxLayout()
        self._status_bar.setContentsMargins(
            SPACING_NORMAL, SPACING_SMALL,
            SPACING_NORMAL, SPACING_SMALL
        )
        
        self._zoom_label = QLabel("100%")
        self._zoom_label.setObjectName("zoomLabel")
        self._status_bar.addStretch()
        self._status_bar.addWidget(self._zoom_label)
        
        main_layout.addLayout(self._status_bar)
        
        # 初始化文本
        self.retranslate_ui()
    
    def _setup_toolbar(self):
        """设置工具栏"""
        # 放大
        self._action_zoom_in = QAction("Zoom In", self)
        self._action_zoom_in.setShortcut("Ctrl++")
        self._action_zoom_in.triggered.connect(self._on_zoom_in)
        self._toolbar.addAction(self._action_zoom_in)
        
        # 缩小
        self._action_zoom_out = QAction("Zoom Out", self)
        self._action_zoom_out.setShortcut("Ctrl+-")
        self._action_zoom_out.triggered.connect(self._on_zoom_out)
        self._toolbar.addAction(self._action_zoom_out)
        
        # 重置
        self._action_reset = QAction("Reset", self)
        self._action_reset.setShortcut("Ctrl+0")
        self._action_reset.triggered.connect(self._on_reset_view)
        self._toolbar.addAction(self._action_reset)
        
        # 适应窗口
        self._action_fit = QAction("Fit", self)
        self._action_fit.setShortcut("Ctrl+F")
        self._action_fit.triggered.connect(self._on_fit_to_view)
        self._toolbar.addAction(self._action_fit)
        
        self._toolbar.addSeparator()
        
        # 保存
        self._action_save = QAction("Save", self)
        self._action_save.setShortcut("Ctrl+S")
        self._action_save.triggered.connect(self._on_save_chart)
        self._toolbar.addAction(self._action_save)
        
        # 复制
        self._action_copy = QAction("Copy", self)
        self._action_copy.setShortcut("Ctrl+C")
        self._action_copy.triggered.connect(self._on_copy_to_clipboard)
        self._toolbar.addAction(self._action_copy)
    
    def _setup_context_menu(self):
        """设置右键菜单"""
        self._context_menu = QMenu(self)
        
        self._context_menu.addAction(self._action_zoom_in)
        self._context_menu.addAction(self._action_zoom_out)
        self._context_menu.addAction(self._action_reset)
        self._context_menu.addAction(self._action_fit)
        self._context_menu.addSeparator()
        self._context_menu.addAction(self._action_save)
        self._context_menu.addAction(self._action_copy)
        
        self._image_label.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._image_label.customContextMenuRequested.connect(
            self._show_context_menu
        )
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            ChartViewer {{
                background-color: {COLOR_BG_SECONDARY};
            }}
            
            #chartTabBar {{
                background-color: {COLOR_BG_TERTIARY};
                border-bottom: 1px solid {COLOR_BORDER};
            }}
            
            #chartTabBar::tab {{
                background-color: transparent;
                color: {COLOR_TEXT_SECONDARY};
                padding: 6px 12px;
                margin-right: 2px;
                border: none;
                border-bottom: 2px solid transparent;
            }}
            
            #chartTabBar::tab:selected {{
                color: {COLOR_ACCENT};
                border-bottom: 2px solid {COLOR_ACCENT};
            }}
            
            #chartTabBar::tab:hover:!selected {{
                color: {COLOR_TEXT_PRIMARY};
                background-color: {COLOR_ACCENT_LIGHT};
            }}
            
            #chartFrame {{
                background-color: {CHART_BG_COLOR};
                border: none;
            }}
            
            #chartScrollArea {{
                background-color: {CHART_BG_COLOR};
                border: none;
            }}
            
            #chartImageLabel {{
                background-color: {CHART_BG_COLOR};
            }}
            
            #emptyLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #chartToolbar {{
                background-color: {COLOR_BG_TERTIARY};
                border-top: 1px solid {COLOR_BORDER};
                spacing: {SPACING_SMALL}px;
                padding: {SPACING_SMALL}px;
            }}
            
            #chartToolbar QToolButton {{
                background-color: transparent;
                color: {COLOR_TEXT_PRIMARY};
                border: none;
                padding: 4px 8px;
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #chartToolbar QToolButton:hover {{
                background-color: {COLOR_ACCENT_LIGHT};
            }}
            
            #chartToolbar QToolButton:pressed {{
                background-color: {COLOR_ACCENT};
                color: white;
            }}
            
            #zoomLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
        """)
    
    # ============================================================
    # 公共方法
    # ============================================================
    
    def set_chart_tabs(self, chart_types: List[str]):
        """
        设置图表类型标签
        
        Args:
            chart_types: 图表类型列表（如 ["bode_combined", "waveform_time"]）
        """
        self._chart_types = chart_types
        
        # 清除现有标签
        while self._tab_bar.count() > 0:
            self._tab_bar.removeTab(0)
        
        # 添加新标签
        for chart_type in chart_types:
            display_name = self._get_chart_display_name(chart_type)
            self._tab_bar.addTab(display_name)
        
        # 选中第一个标签
        if chart_types:
            self._tab_bar.setCurrentIndex(0)
            self._current_chart_type = chart_types[0]
    
    def load_chart(self, chart_path: str, chart_type: Optional[str] = None):
        """
        加载图表图片
        
        Args:
            chart_path: 图表文件路径
            chart_type: 图表类型（可选，用于关联到标签）
        """
        if chart_type:
            self._chart_paths[chart_type] = chart_path
        
        path = Path(chart_path)
        if not path.exists():
            self._logger.warning(f"Chart file not found: {chart_path}")
            self._show_empty_state()
            return
        
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._logger.warning(f"Failed to load chart: {chart_path}")
            self._show_empty_state()
            return
        
        self._image_label.set_pixmap(pixmap)
        self._hide_empty_state()
        self._update_zoom_label()
        
        self._logger.debug(f"Chart loaded: {chart_path}")
    
    def load_charts(self, chart_paths: Dict[str, str]):
        """
        批量加载图表
        
        Args:
            chart_paths: 图表类型到路径的映射
        """
        self._chart_paths = chart_paths.copy()
        
        # 设置标签
        self.set_chart_tabs(list(chart_paths.keys()))
        
        # 加载第一个图表
        if chart_paths:
            first_type = list(chart_paths.keys())[0]
            first_path = chart_paths[first_type]
            self.load_chart(first_path, first_type)
    
    def clear(self):
        """清空图表"""
        self._chart_paths.clear()
        self._current_chart_type = None
        self._chart_types.clear()
        
        while self._tab_bar.count() > 0:
            self._tab_bar.removeTab(0)
        
        self._image_label.set_pixmap(None)
        self._show_empty_state()
    
    def get_current_chart_type(self) -> Optional[str]:
        """获取当前图表类型"""
        return self._current_chart_type
    
    def get_current_chart_path(self) -> Optional[str]:
        """获取当前图表路径"""
        if self._current_chart_type:
            return self._chart_paths.get(self._current_chart_type)
        return None
    
    def zoom_in(self):
        """放大"""
        self._image_label.zoom_in()
    
    def zoom_out(self):
        """缩小"""
        self._image_label.zoom_out()
    
    def reset_zoom(self):
        """重置缩放"""
        self._image_label.reset_view()
    
    def fit_to_view(self):
        """适应视图"""
        self._image_label.fit_to_view()
    
    def export_chart(self, path: str) -> bool:
        """
        导出图表到文件
        
        Args:
            path: 导出路径
            
        Returns:
            bool: 是否成功
        """
        current_path = self.get_current_chart_path()
        if not current_path:
            return False
        
        try:
            source = Path(current_path)
            dest = Path(path)
            
            # 复制文件
            import shutil
            shutil.copy2(source, dest)
            
            self.chart_exported.emit(str(dest))
            self._logger.info(f"Chart exported: {dest}")
            return True
            
        except Exception as e:
            self._logger.error(f"Failed to export chart: {e}")
            return False
    
    def copy_to_clipboard(self) -> bool:
        """
        复制图表到剪贴板
        
        Returns:
            bool: 是否成功
        """
        pixmap = self._image_label.pixmap()
        if pixmap is None or pixmap.isNull():
            return False
        
        clipboard = QGuiApplication.clipboard()
        clipboard.setPixmap(pixmap)
        
        self._logger.debug("Chart copied to clipboard")
        return True
    
    # ============================================================
    # 事件处理
    # ============================================================
    
    def _on_tab_changed(self, index: int):
        """标签切换"""
        if index < 0 or index >= len(self._chart_types):
            return
        
        chart_type = self._chart_types[index]
        self._current_chart_type = chart_type
        
        # 加载对应图表
        chart_path = self._chart_paths.get(chart_type)
        if chart_path:
            self.load_chart(chart_path)
        else:
            self._show_empty_state()
        
        self.tab_changed.emit(chart_type)
    
    def _on_zoom_changed(self, level: float):
        """缩放级别变化"""
        self._update_zoom_label()
    
    def _on_zoom_in(self):
        """放大按钮"""
        self.zoom_in()
    
    def _on_zoom_out(self):
        """缩小按钮"""
        self.zoom_out()
    
    def _on_reset_view(self):
        """重置视图按钮"""
        self.reset_zoom()
    
    def _on_fit_to_view(self):
        """适应窗口按钮"""
        self.fit_to_view()
    
    def _on_save_chart(self):
        """保存图表"""
        current_path = self.get_current_chart_path()
        if not current_path:
            return
        
        # 获取文件扩展名
        source_ext = Path(current_path).suffix
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self._tr("Save Chart"),
            "",
            f"Image Files (*{source_ext});;PNG Files (*.png);;All Files (*)"
        )
        
        if file_path:
            self.export_chart(file_path)
    
    def _on_copy_to_clipboard(self):
        """复制到剪贴板"""
        if self.copy_to_clipboard():
            # 可选：显示提示
            pass
    
    def _show_context_menu(self, pos: QPoint):
        """显示右键菜单"""
        self._context_menu.exec(self._image_label.mapToGlobal(pos))
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def _get_chart_display_name(self, chart_type: str) -> str:
        """获取图表类型的显示名称"""
        try:
            from domain.simulation.service.chart_selector import ChartType
            ct = ChartType(chart_type)
            return ChartType.get_display_name(ct)
        except (ImportError, ValueError):
            # 简单的名称转换
            return chart_type.replace("_", " ").title()
    
    def _show_empty_state(self):
        """显示空状态"""
        self._scroll_area.hide()
        self._empty_label.show()
    
    def _hide_empty_state(self):
        """隐藏空状态"""
        self._empty_label.hide()
        self._scroll_area.show()
    
    def _update_zoom_label(self):
        """更新缩放标签"""
        level = self._image_label.get_zoom_level()
        self._zoom_label.setText(f"{int(level * 100)}%")
    
    def _tr(self, text: str) -> str:
        """翻译文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(f"chart_viewer.{text}", default=text)
        except ImportError:
            return text
    
    def retranslate_ui(self):
        """重新翻译 UI 文本（国际化支持）"""
        self._empty_label.setText(self._tr("No chart available"))
        self._action_zoom_in.setText(self._tr("Zoom In"))
        self._action_zoom_out.setText(self._tr("Zoom Out"))
        self._action_reset.setText(self._tr("Reset"))
        self._action_fit.setText(self._tr("Fit"))
        self._action_save.setText(self._tr("Save"))
        self._action_copy.setText(self._tr("Copy"))


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ChartViewer",
    "ZoomableImageLabel",
]
