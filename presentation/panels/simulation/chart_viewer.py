# ChartViewer - Chart Display and Interaction Component
"""
图表查看器

职责：
- 显示仿真结果图表（图片格式）
- 提供图表标签栏切换不同图表类型
- 支持缩放、平移、重置视图
- 支持图表导出（保存图片、复制到剪贴板）
- 支持波形数据导出（CSV/MATLAB/JSON）
- 提供测量信息栏（供 measurement_tool 集成）
- 提供测量模式和波形运算的集成接口

设计原则：
- 核心图表显示和基本交互在本模块实现
- 双光标测量功能由 measurement_tool.py 实现并集成
- 波形数学运算由 waveform_math_dialog.py 实现并集成
- 数据导出由 data_exporter.py 提供底层实现
- 与 ChartSelector 配合，显示用户选中的图表类型

被调用方：
- simulation_tab.py
- measurement_tool.py
- waveform_math_dialog.py

使用示例：
    from presentation.panels.simulation.chart_viewer import ChartViewer
    
    viewer = ChartViewer()
    viewer.load_chart("/path/to/chart.png")
    viewer.set_chart_tabs(["bode_combined", "waveform_time"])
    
    # 导出波形数据
    viewer.export_data("csv", "/path/to/output.csv")
    
    # 进入测量模式
    viewer.enter_measurement_mode()
"""

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

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
    QGridLayout,
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

# 测量信息栏高度
MEASUREMENT_BAR_HEIGHT = 60


# ============================================================
# 数据类定义
# ============================================================

class MeasurementMode(Enum):
    """测量模式枚举"""
    NONE = "none"
    SINGLE_CURSOR = "single"
    DUAL_CURSOR = "dual"


@dataclass
class CursorPosition:
    """光标位置数据"""
    x: float
    y: float
    signal_name: str = ""
    
    def to_display_string(self, x_unit: str = "", y_unit: str = "") -> str:
        """转换为显示字符串"""
        x_str = f"{self.x:.4g} {x_unit}".strip()
        y_str = f"{self.y:.4g} {y_unit}".strip()
        return f"({x_str}, {y_str})"


@dataclass
class MeasurementResult:
    """测量结果数据"""
    cursor1: Optional[CursorPosition] = None
    cursor2: Optional[CursorPosition] = None
    delta_x: Optional[float] = None
    delta_y: Optional[float] = None
    slope: Optional[float] = None
    frequency: Optional[float] = None
    
    def has_dual_cursor(self) -> bool:
        """是否有双光标数据"""
        return self.cursor1 is not None and self.cursor2 is not None


class ZoomableImageLabel(QLabel):
    """
    可缩放的图片标签
    
    支持：
    - 鼠标滚轮缩放
    - 拖拽平移
    - 双击重置视图
    - 光标位置追踪（供测量工具使用）
    """
    
    zoom_changed = pyqtSignal(float)
    cursor_position_changed = pyqtSignal(float, float)  # 鼠标位置（图片坐标）
    cursor_clicked = pyqtSignal(float, float)  # 鼠标点击位置（图片坐标）
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._original_pixmap: Optional[QPixmap] = None
        self._zoom_level: float = 1.0
        self._pan_start: Optional[QPoint] = None
        self._pan_offset: QPoint = QPoint(0, 0)
        self._measurement_mode: MeasurementMode = MeasurementMode.NONE
        
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(100, 100)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        self.setMouseTracking(True)
    
    def set_measurement_mode(self, mode: MeasurementMode):
        """设置测量模式"""
        self._measurement_mode = mode
        if mode != MeasurementMode.NONE:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
    
    def get_measurement_mode(self) -> MeasurementMode:
        """获取当前测量模式"""
        return self._measurement_mode
    
    def _screen_to_image_coords(self, pos: QPoint) -> Tuple[float, float]:
        """将屏幕坐标转换为图片坐标"""
        if self._original_pixmap is None:
            return (0.0, 0.0)
        
        # 获取当前显示的 pixmap
        current_pixmap = self.pixmap()
        if current_pixmap is None or current_pixmap.isNull():
            return (0.0, 0.0)
        
        # 计算图片在 label 中的偏移（居中显示）
        label_size = self.size()
        pixmap_size = current_pixmap.size()
        
        offset_x = (label_size.width() - pixmap_size.width()) / 2
        offset_y = (label_size.height() - pixmap_size.height()) / 2
        
        # 转换到图片坐标
        img_x = (pos.x() - offset_x) / self._zoom_level
        img_y = (pos.y() - offset_y) / self._zoom_level
        
        return (img_x, img_y)
    
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
        """鼠标按下开始拖拽或放置光标"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self._measurement_mode != MeasurementMode.NONE:
                # 测量模式：发送点击位置
                img_x, img_y = self._screen_to_image_coords(event.pos())
                self.cursor_clicked.emit(img_x, img_y)
            else:
                # 普通模式：开始拖拽
                self._pan_start = event.pos()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """鼠标移动拖拽或追踪位置"""
        # 发送鼠标位置（用于测量工具显示）
        img_x, img_y = self._screen_to_image_coords(event.pos())
        self.cursor_position_changed.emit(img_x, img_y)
        
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
            if self._measurement_mode != MeasurementMode.NONE:
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)
    
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """双击重置视图"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_view()
        super().mouseDoubleClickEvent(event)


class MeasurementInfoBar(QFrame):
    """
    测量信息栏
    
    显示光标位置和测量结果，供 measurement_tool 集成使用。
    
    布局：
    - 光标1信息 | 光标2信息 | Δx | Δy | 斜率 | 频率
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("measurementInfoBar")
        self.setFixedHeight(MEASUREMENT_BAR_HEIGHT)
        
        self._setup_ui()
        self._apply_style()
        
        # 初始隐藏
        self.hide()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QGridLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        layout.setSpacing(SPACING_NORMAL)
        
        # 第一行：标签
        self._label_cursor1 = QLabel("Cursor 1:")
        self._label_cursor2 = QLabel("Cursor 2:")
        self._label_delta_x = QLabel("Δx:")
        self._label_delta_y = QLabel("Δy:")
        self._label_slope = QLabel("Slope:")
        self._label_freq = QLabel("Freq:")
        
        # 第二行：数值
        self._value_cursor1 = QLabel("--")
        self._value_cursor2 = QLabel("--")
        self._value_delta_x = QLabel("--")
        self._value_delta_y = QLabel("--")
        self._value_slope = QLabel("--")
        self._value_freq = QLabel("--")
        
        # 设置对象名用于样式
        for label in [self._label_cursor1, self._label_cursor2, 
                      self._label_delta_x, self._label_delta_y,
                      self._label_slope, self._label_freq]:
            label.setObjectName("measurementLabel")
        
        for value in [self._value_cursor1, self._value_cursor2,
                      self._value_delta_x, self._value_delta_y,
                      self._value_slope, self._value_freq]:
            value.setObjectName("measurementValue")
        
        # 添加到布局
        layout.addWidget(self._label_cursor1, 0, 0)
        layout.addWidget(self._value_cursor1, 1, 0)
        
        layout.addWidget(self._label_cursor2, 0, 1)
        layout.addWidget(self._value_cursor2, 1, 1)
        
        layout.addWidget(self._label_delta_x, 0, 2)
        layout.addWidget(self._value_delta_x, 1, 2)
        
        layout.addWidget(self._label_delta_y, 0, 3)
        layout.addWidget(self._value_delta_y, 1, 3)
        
        layout.addWidget(self._label_slope, 0, 4)
        layout.addWidget(self._value_slope, 1, 4)
        
        layout.addWidget(self._label_freq, 0, 5)
        layout.addWidget(self._value_freq, 1, 5)
        
        # 添加弹性空间
        layout.setColumnStretch(6, 1)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #measurementInfoBar {{
                background-color: {COLOR_BG_TERTIARY};
                border-top: 1px solid {COLOR_BORDER};
            }}
            
            #measurementLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #measurementValue {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
                font-family: monospace;
            }}
        """)
    
    def update_measurement(self, result: MeasurementResult):
        """
        更新测量结果显示
        
        Args:
            result: 测量结果数据
        """
        # 光标1
        if result.cursor1:
            self._value_cursor1.setText(result.cursor1.to_display_string())
        else:
            self._value_cursor1.setText("--")
        
        # 光标2
        if result.cursor2:
            self._value_cursor2.setText(result.cursor2.to_display_string())
        else:
            self._value_cursor2.setText("--")
        
        # Δx
        if result.delta_x is not None:
            self._value_delta_x.setText(f"{result.delta_x:.4g}")
        else:
            self._value_delta_x.setText("--")
        
        # Δy
        if result.delta_y is not None:
            self._value_delta_y.setText(f"{result.delta_y:.4g}")
        else:
            self._value_delta_y.setText("--")
        
        # 斜率
        if result.slope is not None:
            self._value_slope.setText(f"{result.slope:.4g}")
        else:
            self._value_slope.setText("--")
        
        # 频率
        if result.frequency is not None:
            self._value_freq.setText(f"{result.frequency:.4g} Hz")
        else:
            self._value_freq.setText("--")
    
    def clear_measurement(self):
        """清空测量结果"""
        self._value_cursor1.setText("--")
        self._value_cursor2.setText("--")
        self._value_delta_x.setText("--")
        self._value_delta_y.setText("--")
        self._value_slope.setText("--")
        self._value_freq.setText("--")
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._label_cursor1.setText(self._tr("Cursor 1:"))
        self._label_cursor2.setText(self._tr("Cursor 2:"))
        self._label_delta_x.setText("Δx:")
        self._label_delta_y.setText("Δy:")
        self._label_slope.setText(self._tr("Slope:"))
        self._label_freq.setText(self._tr("Freq:"))
    
    def _tr(self, text: str) -> str:
        """翻译文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(f"measurement.{text}", default=text)
        except ImportError:
            return text


class ChartViewer(QWidget):
    """
    图表查看器
    
    显示仿真结果图表，支持标签切换、缩放、导出。
    提供测量模式和波形运算的集成接口。
    
    Signals:
        tab_changed: 标签切换时发出，携带图表类型
        chart_exported: 图表导出时发出，携带导出路径
        data_exported: 数据导出时发出，携带导出路径
        measurement_mode_changed: 测量模式变化时发出
        cursor_clicked: 测量模式下点击时发出，携带图片坐标
    """
    
    tab_changed = pyqtSignal(str)
    chart_exported = pyqtSignal(str)
    data_exported = pyqtSignal(str)
    measurement_mode_changed = pyqtSignal(str)  # MeasurementMode.value
    cursor_clicked = pyqtSignal(float, float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # 状态
        self._chart_paths: Dict[str, str] = {}
        self._current_chart_type: Optional[str] = None
        self._chart_types: List[str] = []
        self._measurement_mode: MeasurementMode = MeasurementMode.NONE
        self._simulation_data = None  # 仿真数据引用（用于数据导出）
        
        # 回调函数（供外部模块集成）
        self._on_measurement_click: Optional[Callable[[float, float], None]] = None
        self._on_waveform_math_request: Optional[Callable[[], None]] = None
        
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
        self._image_label.cursor_clicked.connect(self._on_cursor_clicked)
        self._image_label.cursor_position_changed.connect(self._on_cursor_position_changed)
        self._scroll_area.setWidget(self._image_label)
        
        chart_layout.addWidget(self._scroll_area, 1)
        
        # 空状态提示
        self._empty_label = QLabel()
        self._empty_label.setObjectName("emptyLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chart_layout.addWidget(self._empty_label)
        self._empty_label.hide()
        
        main_layout.addWidget(self._chart_frame, 1)
        
        # 测量信息栏
        self._measurement_bar = MeasurementInfoBar()
        main_layout.addWidget(self._measurement_bar)
        
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
        
        # 测量按钮（可切换）
        self._action_measure = QAction("Measure", self)
        self._action_measure.setShortcut("Ctrl+M")
        self._action_measure.setCheckable(True)
        self._action_measure.triggered.connect(self._on_toggle_measurement)
        self._toolbar.addAction(self._action_measure)
        
        # 波形运算按钮
        self._action_math = QAction("Math", self)
        self._action_math.setShortcut("Ctrl+Shift+M")
        self._action_math.triggered.connect(self._on_waveform_math)
        self._toolbar.addAction(self._action_math)
        
        self._toolbar.addSeparator()
        
        # 保存图表
        self._action_save = QAction("Save", self)
        self._action_save.setShortcut("Ctrl+S")
        self._action_save.triggered.connect(self._on_save_chart)
        self._toolbar.addAction(self._action_save)
        
        # 复制图表
        self._action_copy = QAction("Copy", self)
        self._action_copy.setShortcut("Ctrl+C")
        self._action_copy.triggered.connect(self._on_copy_to_clipboard)
        self._toolbar.addAction(self._action_copy)
        
        # 导出数据
        self._action_export_data = QAction("Export Data", self)
        self._action_export_data.setShortcut("Ctrl+E")
        self._action_export_data.triggered.connect(self._on_export_data)
        self._toolbar.addAction(self._action_export_data)
    
    def _setup_context_menu(self):
        """设置右键菜单"""
        self._context_menu = QMenu(self)
        
        self._context_menu.addAction(self._action_zoom_in)
        self._context_menu.addAction(self._action_zoom_out)
        self._context_menu.addAction(self._action_reset)
        self._context_menu.addAction(self._action_fit)
        self._context_menu.addSeparator()
        self._context_menu.addAction(self._action_measure)
        self._context_menu.addAction(self._action_math)
        self._context_menu.addSeparator()
        self._context_menu.addAction(self._action_save)
        self._context_menu.addAction(self._action_copy)
        self._context_menu.addAction(self._action_export_data)
        
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
    # 测量模式方法
    # ============================================================
    
    def enter_measurement_mode(self, mode: MeasurementMode = MeasurementMode.DUAL_CURSOR):
        """
        进入测量模式
        
        Args:
            mode: 测量模式（单光标或双光标）
        """
        self._measurement_mode = mode
        self._image_label.set_measurement_mode(mode)
        self._measurement_bar.show()
        self._measurement_bar.clear_measurement()
        self._action_measure.setChecked(True)
        self.measurement_mode_changed.emit(mode.value)
        self._logger.debug(f"Entered measurement mode: {mode.value}")
    
    def exit_measurement_mode(self):
        """退出测量模式"""
        self._measurement_mode = MeasurementMode.NONE
        self._image_label.set_measurement_mode(MeasurementMode.NONE)
        self._measurement_bar.hide()
        self._action_measure.setChecked(False)
        self.measurement_mode_changed.emit(MeasurementMode.NONE.value)
        self._logger.debug("Exited measurement mode")
    
    def is_measurement_mode(self) -> bool:
        """检查是否处于测量模式"""
        return self._measurement_mode != MeasurementMode.NONE
    
    def get_measurement_mode(self) -> MeasurementMode:
        """获取当前测量模式"""
        return self._measurement_mode
    
    def update_measurement_result(self, result: MeasurementResult):
        """
        更新测量结果显示
        
        由 measurement_tool 调用，更新测量信息栏显示。
        
        Args:
            result: 测量结果数据
        """
        self._measurement_bar.update_measurement(result)
    
    def set_measurement_click_handler(
        self,
        handler: Optional[Callable[[float, float], None]]
    ):
        """
        设置测量点击处理器
        
        由 measurement_tool 调用，注册点击回调。
        
        Args:
            handler: 点击处理函数，接收图片坐标 (x, y)
        """
        self._on_measurement_click = handler
    
    # ============================================================
    # 波形运算方法
    # ============================================================
    
    def set_waveform_math_handler(
        self,
        handler: Optional[Callable[[], None]]
    ):
        """
        设置波形运算处理器
        
        由 waveform_math_dialog 调用，注册运算请求回调。
        
        Args:
            handler: 运算请求处理函数
        """
        self._on_waveform_math_request = handler
    
    # ============================================================
    # 数据导出方法
    # ============================================================
    
    def set_simulation_data(self, data):
        """
        设置仿真数据引用
        
        用于数据导出功能。
        
        Args:
            data: SimulationData 对象
        """
        self._simulation_data = data
    
    def export_data(
        self,
        format: str,
        path: str,
        signals: Optional[List[str]] = None,
    ) -> bool:
        """
        导出波形数据
        
        Args:
            format: 导出格式（"csv", "json", "mat", "npy", "npz"）
            path: 导出文件路径
            signals: 要导出的信号列表（None 表示全部）
            
        Returns:
            bool: 是否导出成功
        """
        if self._simulation_data is None:
            self._logger.warning("No simulation data available for export")
            return False
        
        try:
            from domain.simulation.data.data_exporter import data_exporter
            
            success = data_exporter.export(
                data=self._simulation_data,
                format=format,
                path=path,
                signals=signals,
            )
            if success:
                self.data_exported.emit(path)
                self._logger.info(f"Data exported to {format}: {path}")
            return success
        except Exception as e:
            self._logger.error(f"Failed to export data: {e}")
            return False
    
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
    
    def _on_toggle_measurement(self, checked: bool):
        """切换测量模式"""
        if checked:
            self.enter_measurement_mode()
        else:
            self.exit_measurement_mode()
    
    def _on_waveform_math(self):
        """波形运算按钮"""
        if self._on_waveform_math_request:
            self._on_waveform_math_request()
        else:
            # 默认行为：显示提示
            QMessageBox.information(
                self,
                self._tr("Waveform Math"),
                self._tr("Waveform math dialog not available. Please integrate waveform_math_dialog module.")
            )
    
    def _on_export_data(self):
        """导出数据按钮"""
        if self._simulation_data is None:
            QMessageBox.warning(
                self,
                self._tr("Export Data"),
                self._tr("No simulation data available for export.")
            )
            return
        
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            self._tr("Export Data"),
            "",
            "CSV Files (*.csv);;JSON Files (*.json);;MATLAB Files (*.mat);;NumPy Files (*.npy);;NumPy Compressed (*.npz);;All Files (*)"
        )
        
        if file_path:
            # 根据选择的过滤器或文件扩展名确定格式
            if file_path.endswith(".json") or "JSON" in selected_filter:
                format = "json"
            elif file_path.endswith(".mat") or "MATLAB" in selected_filter:
                format = "mat"
            elif file_path.endswith(".npz") or "Compressed" in selected_filter:
                format = "npz"
            elif file_path.endswith(".npy") or "NumPy Files" in selected_filter:
                format = "npy"
            else:
                format = "csv"
                if not file_path.endswith(".csv"):
                    file_path += ".csv"
            
            self.export_data(format, file_path)
    
    def _on_cursor_clicked(self, x: float, y: float):
        """测量模式下的点击事件"""
        if self._on_measurement_click:
            self._on_measurement_click(x, y)
        self.cursor_clicked.emit(x, y)
    
    def _on_cursor_position_changed(self, x: float, y: float):
        """鼠标位置变化（用于实时显示坐标）"""
        # 可由 measurement_tool 订阅处理
        pass
    
    def _show_context_menu(self, pos: QPoint):
        """显示右键菜单"""
        self._context_menu.exec(self._image_label.mapToGlobal(pos))
    
    def keyPressEvent(self, event):
        """键盘事件处理"""
        # ESC 退出测量模式
        if event.key() == Qt.Key.Key_Escape and self.is_measurement_mode():
            self.exit_measurement_mode()
            event.accept()
            return
        super().keyPressEvent(event)
    
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
        self._action_measure.setText(self._tr("Measure"))
        self._action_math.setText(self._tr("Math"))
        self._action_save.setText(self._tr("Save"))
        self._action_copy.setText(self._tr("Copy"))
        self._action_export_data.setText(self._tr("Export Data"))
        self._measurement_bar.retranslate_ui()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ChartViewer",
    "ZoomableImageLabel",
    "MeasurementInfoBar",
    "MeasurementMode",
    "MeasurementResult",
    "CursorPosition",
]
