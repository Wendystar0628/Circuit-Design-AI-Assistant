# SweepResultTab - Parametric Sweep Result Tab
"""
参数扫描结果标签页

职责：
- 展示参数扫描结果
- 支持曲线图和等高线图/热力图显示
- 显示最优点信息和可行区域

设计原则：
- 使用 QWidget 作为基类
- 订阅 EVENT_SWEEP_COMPLETE 事件自动更新
- 支持国际化

被调用方：
- simulation_tab.py
"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QFrame,
    QLabel,
    QPushButton,
    QComboBox,
    QSizePolicy,
    QGroupBox,
    QStackedWidget,
)

from resources.theme import (
    COLOR_BG_PRIMARY,
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_ACCENT,
    COLOR_ACCENT_LIGHT,
    COLOR_BORDER,
    COLOR_SUCCESS,
    COLOR_ERROR,
    FONT_SIZE_NORMAL,
    FONT_SIZE_SMALL,
    FONT_SIZE_TITLE,
    SPACING_SMALL,
    SPACING_NORMAL,
    SPACING_LARGE,
    BORDER_RADIUS_NORMAL,
)


# ============================================================
# 视图模式枚举
# ============================================================

class ViewMode:
    """视图模式"""
    CURVE = "curve"           # 曲线图（单参数扫描）
    CONTOUR = "contour"       # 等高线图（双参数扫描）
    HEATMAP = "heatmap"       # 热力图（双参数扫描）


# ============================================================
# 子组件
# ============================================================

class SweepSelectorBar(QFrame):
    """
    参数和指标选择器栏
    """
    
    selection_changed = pyqtSignal(str, str, str)  # x_param, y_param, metric
    view_mode_changed = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("sweepSelectorBar")
        self.setFixedHeight(56)
        
        self._params: List[str] = []
        self._metrics: List[str] = []
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        layout.setSpacing(SPACING_NORMAL)
        
        # X 轴参数
        x_label = QLabel(self._get_text("sweep.x_param", "X 轴:"))
        x_label.setObjectName("selectorLabel")
        layout.addWidget(x_label)
        
        self._x_combo = QComboBox()
        self._x_combo.setObjectName("paramCombo")
        self._x_combo.setMinimumWidth(120)
        self._x_combo.currentTextChanged.connect(self._on_selection_changed)
        layout.addWidget(self._x_combo)
        
        # Y 轴参数（双参数扫描时使用）
        self._y_label = QLabel(self._get_text("sweep.y_param", "Y 轴:"))
        self._y_label.setObjectName("selectorLabel")
        layout.addWidget(self._y_label)
        
        self._y_combo = QComboBox()
        self._y_combo.setObjectName("paramCombo")
        self._y_combo.setMinimumWidth(120)
        self._y_combo.currentTextChanged.connect(self._on_selection_changed)
        layout.addWidget(self._y_combo)
        
        layout.addSpacing(SPACING_LARGE)
        
        # 指标选择
        metric_label = QLabel(self._get_text("sweep.metric", "指标:"))
        metric_label.setObjectName("selectorLabel")
        layout.addWidget(metric_label)
        
        self._metric_combo = QComboBox()
        self._metric_combo.setObjectName("metricCombo")
        self._metric_combo.setMinimumWidth(150)
        self._metric_combo.currentTextChanged.connect(self._on_selection_changed)
        layout.addWidget(self._metric_combo)
        
        layout.addStretch(1)
        
        # 视图模式切换
        self._view_combo = QComboBox()
        self._view_combo.setObjectName("viewCombo")
        self._view_combo.addItems([
            self._get_text("sweep.view.curve", "曲线图"),
            self._get_text("sweep.view.contour", "等高线图"),
            self._get_text("sweep.view.heatmap", "热力图"),
        ])
        self._view_combo.currentIndexChanged.connect(self._on_view_mode_changed)
        layout.addWidget(self._view_combo)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #sweepSelectorBar {{
                background-color: {COLOR_BG_SECONDARY};
                border-bottom: 1px solid {COLOR_BORDER};
            }}
            
            #selectorLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            QComboBox {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 4px 8px;
                font-size: {FONT_SIZE_NORMAL}px;
            }}
        """)
    
    def set_params(self, params: List[str]):
        """设置参数列表"""
        self._params = params
        
        self._x_combo.blockSignals(True)
        self._y_combo.blockSignals(True)
        
        self._x_combo.clear()
        self._y_combo.clear()
        
        self._x_combo.addItems(params)
        self._y_combo.addItem("—")  # 无 Y 轴选项
        self._y_combo.addItems(params)
        
        self._x_combo.blockSignals(False)
        self._y_combo.blockSignals(False)
        
        # 单参数时隐藏 Y 轴选择
        is_single = len(params) <= 1
        self._y_label.setVisible(not is_single)
        self._y_combo.setVisible(not is_single)
    
    def set_metrics(self, metrics: List[str]):
        """设置指标列表"""
        self._metrics = metrics
        
        self._metric_combo.blockSignals(True)
        self._metric_combo.clear()
        self._metric_combo.addItems(metrics)
        self._metric_combo.blockSignals(False)
    
    def _on_selection_changed(self):
        """处理选择变更"""
        x_param = self._x_combo.currentText()
        y_param = self._y_combo.currentText()
        if y_param == "—":
            y_param = ""
        metric = self._metric_combo.currentText()
        self.selection_changed.emit(x_param, y_param, metric)
    
    def _on_view_mode_changed(self, index: int):
        """处理视图模式变更"""
        modes = [ViewMode.CURVE, ViewMode.CONTOUR, ViewMode.HEATMAP]
        if 0 <= index < len(modes):
            self.view_mode_changed.emit(modes[index])
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(key, default)
        except ImportError:
            return default
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        pass


class OptimalPointCard(QFrame):
    """
    最优点信息卡片
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("optimalPointCard")
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_SMALL)
        
        # 标题
        title = QLabel(self._get_text("sweep.optimal_point", "最优点"))
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        self._title = title
        
        # 参数值容器
        self._params_frame = QFrame()
        self._params_layout = QVBoxLayout(self._params_frame)
        self._params_layout.setContentsMargins(0, SPACING_SMALL, 0, 0)
        self._params_layout.setSpacing(4)
        layout.addWidget(self._params_frame)
        
        # 分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(f"background-color: {COLOR_BORDER};")
        separator.setFixedHeight(1)
        layout.addWidget(separator)
        
        # 指标值容器
        self._metrics_frame = QFrame()
        self._metrics_layout = QVBoxLayout(self._metrics_frame)
        self._metrics_layout.setContentsMargins(0, SPACING_SMALL, 0, 0)
        self._metrics_layout.setSpacing(4)
        layout.addWidget(self._metrics_frame)
        
        layout.addStretch(1)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #optimalPointCard {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #cardTitle {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
                font-weight: bold;
            }}
        """)
    
    def set_optimal_point(
        self,
        param_values: Dict[str, float],
        metric_values: Dict[str, float]
    ):
        """设置最优点数据"""
        # 清除旧内容
        self._clear_layout(self._params_layout)
        self._clear_layout(self._metrics_layout)
        
        # 添加参数值
        for name, value in param_values.items():
            row = self._create_value_row(name, f"{value:.4g}")
            self._params_layout.addWidget(row)
        
        # 添加指标值
        for name, value in metric_values.items():
            row = self._create_value_row(name, f"{value:.4g}", highlight=True)
            self._metrics_layout.addWidget(row)
    
    def _create_value_row(self, label: str, value: str, highlight: bool = False) -> QFrame:
        """创建值显示行"""
        row = QFrame()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(SPACING_SMALL)
        
        label_widget = QLabel(label)
        label_widget.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: {FONT_SIZE_SMALL}px;")
        row_layout.addWidget(label_widget)
        
        row_layout.addStretch(1)
        
        value_widget = QLabel(value)
        color = COLOR_SUCCESS if highlight else COLOR_TEXT_PRIMARY
        value_widget.setStyleSheet(f"color: {color}; font-size: {FONT_SIZE_SMALL}px; font-weight: bold;")
        row_layout.addWidget(value_widget)
        
        return row
    
    def _clear_layout(self, layout):
        """清除布局中的所有组件"""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
    
    def clear(self):
        """清空显示"""
        self._clear_layout(self._params_layout)
        self._clear_layout(self._metrics_layout)
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(key, default)
        except ImportError:
            return default
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._title.setText(self._get_text("sweep.optimal_point", "最优点"))


class FeasibleRegionCard(QFrame):
    """
    可行区域信息卡片
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("feasibleRegionCard")
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_SMALL)
        
        # 标题
        title = QLabel(self._get_text("sweep.feasible_region", "可行区域"))
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        self._title = title
        
        # 区域信息容器
        self._regions_frame = QFrame()
        self._regions_layout = QVBoxLayout(self._regions_frame)
        self._regions_layout.setContentsMargins(0, SPACING_SMALL, 0, 0)
        self._regions_layout.setSpacing(4)
        layout.addWidget(self._regions_frame)
        
        layout.addStretch(1)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #feasibleRegionCard {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #cardTitle {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
                font-weight: bold;
            }}
        """)
    
    def set_feasible_region(self, regions: Dict[str, tuple]):
        """设置可行区域数据"""
        # 清除旧内容
        while self._regions_layout.count():
            item = self._regions_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # 添加区域信息
        for param, (low, high) in regions.items():
            row = QFrame()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(SPACING_SMALL)
            
            label = QLabel(param)
            label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: {FONT_SIZE_SMALL}px;")
            row_layout.addWidget(label)
            
            row_layout.addStretch(1)
            
            value = QLabel(f"[{low:.4g}, {high:.4g}]")
            value.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: {FONT_SIZE_SMALL}px;")
            row_layout.addWidget(value)
            
            self._regions_layout.addWidget(row)
    
    def clear(self):
        """清空显示"""
        while self._regions_layout.count():
            item = self._regions_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(key, default)
        except ImportError:
            return default
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._title.setText(self._get_text("sweep.feasible_region", "可行区域"))


class SweepChartWidget(QFrame):
    """
    扫描图表组件
    
    支持曲线图、等高线图、热力图
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("sweepChartWidget")
        
        self._plot_widget = None
        self._view_mode = ViewMode.CURVE
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        try:
            import pyqtgraph as pg
            
            pg.setConfigOptions(antialias=True, background='w', foreground='k')
            
            self._plot_widget = pg.PlotWidget()
            self._plot_widget.setObjectName("sweepPlot")
            self._plot_widget.showGrid(x=True, y=True, alpha=0.3)
            
            layout.addWidget(self._plot_widget)
            
        except ImportError:
            placeholder = QLabel(self._get_text(
                "sweep.pyqtgraph_missing",
                "图表需要 pyqtgraph 库"
            ))
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
            layout.addWidget(placeholder)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #sweepChartWidget {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
        """)
    
    def set_view_mode(self, mode: str):
        """设置视图模式"""
        self._view_mode = mode
    
    def update_curve(self, x: List[float], y: List[float], x_label: str, y_label: str):
        """更新曲线图"""
        if self._plot_widget is None:
            return
        
        try:
            import pyqtgraph as pg
            
            self._plot_widget.clear()
            self._plot_widget.setLabel('bottom', x_label)
            self._plot_widget.setLabel('left', y_label)
            
            # 绘制曲线
            pen = pg.mkPen(color=COLOR_ACCENT, width=2)
            self._plot_widget.plot(x, y, pen=pen, symbol='o', symbolSize=6, symbolBrush=COLOR_ACCENT)
            
            self._plot_widget.autoRange()
            
        except Exception as e:
            logging.getLogger(__name__).warning(f"更新曲线图失败: {e}")
    
    def update_contour(
        self,
        x: List[float],
        y: List[float],
        z: List[List[float]],
        x_label: str,
        y_label: str,
        z_label: str
    ):
        """更新等高线图/热力图"""
        if self._plot_widget is None:
            return
        
        try:
            import pyqtgraph as pg
            
            self._plot_widget.clear()
            self._plot_widget.setLabel('bottom', x_label)
            self._plot_widget.setLabel('left', y_label)
            
            # 转换为 numpy 数组
            z_array = np.array(z)
            
            # 创建图像项
            img = pg.ImageItem()
            
            # 设置颜色映射
            colormap = pg.colormap.get('viridis')
            img.setColorMap(colormap)
            
            # 设置数据
            img.setImage(z_array.T)
            
            # 设置位置和缩放
            if len(x) > 1 and len(y) > 1:
                x_scale = (x[-1] - x[0]) / (len(x) - 1)
                y_scale = (y[-1] - y[0]) / (len(y) - 1)
                img.setRect(x[0], y[0], x[-1] - x[0], y[-1] - y[0])
            
            self._plot_widget.addItem(img)
            
            # 添加颜色条
            # 注意：pyqtgraph 的颜色条需要额外处理
            
            self._plot_widget.autoRange()
            
        except Exception as e:
            logging.getLogger(__name__).warning(f"更新等高线图失败: {e}")
    
    def highlight_optimal(self, x: float, y: float):
        """高亮最优点"""
        if self._plot_widget is None:
            return
        
        try:
            import pyqtgraph as pg
            
            # 添加最优点标记
            scatter = pg.ScatterPlotItem(
                [x], [y],
                symbol='star',
                size=20,
                brush=pg.mkBrush(COLOR_SUCCESS),
                pen=pg.mkPen('w', width=2)
            )
            self._plot_widget.addItem(scatter)
            
        except Exception as e:
            logging.getLogger(__name__).warning(f"高亮最优点失败: {e}")
    
    def clear(self):
        """清空图表"""
        if self._plot_widget:
            self._plot_widget.clear()
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(key, default)
        except ImportError:
            return default
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        pass



# ============================================================
# SweepResultTab - 主组件
# ============================================================

class SweepResultTab(QWidget):
    """
    参数扫描结果标签页
    
    展示参数扫描结果，支持曲线图和等高线图/热力图显示。
    
    Signals:
        export_requested: 请求导出数据
    """
    
    export_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # 数据
        self._sweep_result: Optional[Any] = None
        self._current_x_param: str = ""
        self._current_y_param: str = ""
        self._current_metric: str = ""
        self._view_mode: str = ViewMode.CURVE
        
        # EventBus 引用
        self._event_bus = None
        self._subscriptions: List[tuple] = []
        
        # 初始化 UI
        self._setup_ui()
        self._apply_style()
        self._connect_signals()
        
        # 订阅事件
        self._subscribe_events()
        
        # 初始化文本
        self.retranslate_ui()
    
    def _setup_ui(self):
        """初始化 UI 组件"""
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 顶部：选择器栏
        self._selector_bar = SweepSelectorBar()
        main_layout.addWidget(self._selector_bar)
        
        # 主内容区
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        content_layout.setSpacing(SPACING_NORMAL)
        
        # 左侧：图表
        self._chart_widget = SweepChartWidget()
        content_layout.addWidget(self._chart_widget, 1)
        
        # 右侧面板
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(SPACING_NORMAL)
        
        # 最优点卡片
        self._optimal_card = OptimalPointCard()
        right_layout.addWidget(self._optimal_card)
        
        # 可行区域卡片
        self._feasible_card = FeasibleRegionCard()
        right_layout.addWidget(self._feasible_card)
        
        right_layout.addStretch(1)
        
        right_panel.setFixedWidth(250)
        content_layout.addWidget(right_panel)
        
        main_layout.addWidget(content_widget, 1)
        
        # 底部：操作栏
        self._action_bar = QFrame()
        self._action_bar.setObjectName("actionBar")
        self._action_bar.setFixedHeight(48)
        action_layout = QHBoxLayout(self._action_bar)
        action_layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        
        # 统计信息
        self._stats_label = QLabel()
        self._stats_label.setObjectName("statsLabel")
        action_layout.addWidget(self._stats_label)
        
        action_layout.addStretch(1)
        
        # 导出按钮
        self._export_btn = QPushButton()
        self._export_btn.setObjectName("exportBtn")
        self._export_btn.clicked.connect(self._on_export_clicked)
        action_layout.addWidget(self._export_btn)
        
        main_layout.addWidget(self._action_bar)
        
        # 空状态提示
        self._empty_widget = QFrame()
        self._empty_widget.setObjectName("emptyWidget")
        empty_layout = QVBoxLayout(self._empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self._empty_label = QLabel()
        self._empty_label.setObjectName("emptyLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._empty_label)
        
        main_layout.addWidget(self._empty_widget)
        
        # 初始显示空状态
        self._show_empty_state()
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            SweepResultTab {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #actionBar {{
                background-color: {COLOR_BG_SECONDARY};
                border-top: 1px solid {COLOR_BORDER};
            }}
            
            #statsLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #exportBtn {{
                background-color: {COLOR_ACCENT};
                color: white;
                border: none;
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 8px 16px;
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #exportBtn:hover {{
                background-color: {COLOR_ACCENT};
                opacity: 0.9;
            }}
            
            #emptyWidget {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #emptyLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
        """)
    
    def _connect_signals(self):
        """连接信号"""
        self._selector_bar.selection_changed.connect(self._on_selection_changed)
        self._selector_bar.view_mode_changed.connect(self._on_view_mode_changed)
    
    def _subscribe_events(self):
        """订阅事件"""
        event_bus = self._get_event_bus()
        if not event_bus:
            return
        
        from shared.event_types import EVENT_SWEEP_COMPLETE, EVENT_LANGUAGE_CHANGED
        
        subscriptions = [
            (EVENT_SWEEP_COMPLETE, self._on_sweep_complete),
            (EVENT_LANGUAGE_CHANGED, self._on_language_changed),
        ]
        
        for event_type, handler in subscriptions:
            event_bus.subscribe(event_type, handler)
            self._subscriptions.append((event_type, handler))
    
    def _unsubscribe_events(self):
        """取消事件订阅"""
        event_bus = self._get_event_bus()
        if not event_bus:
            return
        
        for event_type, handler in self._subscriptions:
            try:
                event_bus.unsubscribe(event_type, handler)
            except Exception:
                pass
        
        self._subscriptions.clear()
    
    def _get_event_bus(self):
        """获取 EventBus"""
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus
    
    # ============================================================
    # 公开方法
    # ============================================================
    
    def update_results(self, sweep_result: Any):
        """
        更新参数扫描结果显示
        
        Args:
            sweep_result: SweepAnalysisResult 对象
        """
        self._sweep_result = sweep_result
        
        if sweep_result is None:
            self._show_empty_state()
            return
        
        self._show_content_state()
        
        # 提取参数和指标列表
        params = []
        metrics = set()
        
        sweep_config = getattr(sweep_result, 'sweep_config', None)
        if sweep_config:
            for param in getattr(sweep_config, 'params', []):
                params.append(param.key)
        
        points = getattr(sweep_result, 'points', [])
        for point in points:
            point_metrics = getattr(point, 'metrics', {})
            metrics.update(point_metrics.keys())
        
        # 更新选择器
        self._selector_bar.set_params(params)
        self._selector_bar.set_metrics(list(metrics))
        
        # 更新最优点
        optimal = getattr(sweep_result, 'optimal_point', None)
        if optimal:
            self._optimal_card.set_optimal_point(
                getattr(optimal, 'param_values', {}),
                getattr(optimal, 'metrics', {})
            )
        else:
            self._optimal_card.clear()
        
        # 更新可行区域
        feasible = getattr(sweep_result, 'feasible_region', {})
        if feasible:
            self._feasible_card.set_feasible_region(feasible)
        else:
            self._feasible_card.clear()
        
        # 更新统计信息
        successful = getattr(sweep_result, 'successful_points', 0)
        failed = getattr(sweep_result, 'failed_points', 0)
        total = successful + failed
        self._stats_label.setText(f"{successful}/{total} 成功, {failed} 失败")
        
        # 默认显示第一个参数和指标
        if params and metrics:
            self._current_x_param = params[0]
            self._current_metric = list(metrics)[0]
            self._update_chart()
    
    def _update_chart(self):
        """更新图表显示"""
        if self._sweep_result is None:
            return
        
        if self._view_mode == ViewMode.CURVE or not self._current_y_param:
            # 单参数曲线图
            self._update_curve_chart()
        else:
            # 双参数等高线/热力图
            self._update_contour_chart()
    
    def _update_curve_chart(self):
        """更新曲线图"""
        if not self._current_x_param or not self._current_metric:
            return
        
        # 从结果中提取曲线数据
        x_values = []
        y_values = []
        
        points = getattr(self._sweep_result, 'points', [])
        for point in points:
            sim_result = getattr(point, 'simulation_result', None)
            if sim_result and getattr(sim_result, 'success', False):
                param_values = getattr(point, 'param_values', {})
                metrics = getattr(point, 'metrics', {})
                
                if self._current_x_param in param_values and self._current_metric in metrics:
                    x_values.append(param_values[self._current_x_param])
                    y_values.append(metrics[self._current_metric])
        
        # 排序
        if x_values:
            sorted_pairs = sorted(zip(x_values, y_values))
            x_values = [p[0] for p in sorted_pairs]
            y_values = [p[1] for p in sorted_pairs]
        
        self._chart_widget.update_curve(
            x_values, y_values,
            self._current_x_param, self._current_metric
        )
        
        # 高亮最优点
        optimal = getattr(self._sweep_result, 'optimal_point', None)
        if optimal:
            opt_params = getattr(optimal, 'param_values', {})
            opt_metrics = getattr(optimal, 'metrics', {})
            if self._current_x_param in opt_params and self._current_metric in opt_metrics:
                self._chart_widget.highlight_optimal(
                    opt_params[self._current_x_param],
                    opt_metrics[self._current_metric]
                )
    
    def _update_contour_chart(self):
        """更新等高线/热力图"""
        if not self._current_x_param or not self._current_y_param or not self._current_metric:
            return
        
        # 从结果中提取等高线数据
        x_set = set()
        y_set = set()
        z_map = {}
        
        points = getattr(self._sweep_result, 'points', [])
        for point in points:
            sim_result = getattr(point, 'simulation_result', None)
            if sim_result and getattr(sim_result, 'success', False):
                param_values = getattr(point, 'param_values', {})
                metrics = getattr(point, 'metrics', {})
                
                if (self._current_x_param in param_values and 
                    self._current_y_param in param_values and
                    self._current_metric in metrics):
                    x_val = param_values[self._current_x_param]
                    y_val = param_values[self._current_y_param]
                    x_set.add(x_val)
                    y_set.add(y_val)
                    z_map[(x_val, y_val)] = metrics[self._current_metric]
        
        x_sorted = sorted(x_set)
        y_sorted = sorted(y_set)
        
        # 构建 Z 矩阵
        z_matrix = []
        for y_val in y_sorted:
            row = []
            for x_val in x_sorted:
                row.append(z_map.get((x_val, y_val), float('nan')))
            z_matrix.append(row)
        
        self._chart_widget.update_contour(
            x_sorted, y_sorted, z_matrix,
            self._current_x_param, self._current_y_param, self._current_metric
        )
    
    def _show_empty_state(self):
        """显示空状态"""
        self._selector_bar.hide()
        self._chart_widget.hide()
        self._optimal_card.hide()
        self._feasible_card.hide()
        self._action_bar.hide()
        
        self._empty_label.setText(self._get_text(
            "sweep.no_results",
            "暂无参数扫描结果"
        ))
        self._empty_widget.show()
    
    def _show_content_state(self):
        """显示内容状态"""
        self._empty_widget.hide()
        
        self._selector_bar.show()
        self._chart_widget.show()
        self._optimal_card.show()
        self._feasible_card.show()
        self._action_bar.show()
    
    # ============================================================
    # 事件处理
    # ============================================================
    
    def _on_selection_changed(self, x_param: str, y_param: str, metric: str):
        """处理选择变更"""
        self._current_x_param = x_param
        self._current_y_param = y_param
        self._current_metric = metric
        self._update_chart()
    
    def _on_view_mode_changed(self, mode: str):
        """处理视图模式变更"""
        self._view_mode = mode
        self._chart_widget.set_view_mode(mode)
        self._update_chart()
    
    def _on_sweep_complete(self, event_data: Dict[str, Any]):
        """处理扫描完成事件"""
        result = event_data.get("result")
        if result:
            self.update_results(result)
    
    def _on_language_changed(self, event_data: Dict[str, Any]):
        """处理语言变更事件"""
        self.retranslate_ui()
    
    def _on_export_clicked(self):
        """处理导出按钮点击"""
        self.export_requested.emit()
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(key, default)
        except ImportError:
            return default
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._export_btn.setText(self._get_text("sweep.export", "导出数据"))
        self._empty_label.setText(self._get_text("sweep.no_results", "暂无参数扫描结果"))
        
        self._selector_bar.retranslate_ui()
        self._optimal_card.retranslate_ui()
        self._feasible_card.retranslate_ui()
        self._chart_widget.retranslate_ui()
    
    def closeEvent(self, event):
        """关闭事件"""
        self._unsubscribe_events()
        super().closeEvent(event)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SweepResultTab",
    "ViewMode",
]
