# MonteCarloResultTab - Monte Carlo Analysis Result Tab
"""
蒙特卡洛分析结果标签页

职责：
- 展示蒙特卡洛统计分析结果
- 支持直方图和良率显示
- 显示敏感参数排名

设计原则：
- 使用 QWidget 作为基类
- 订阅 EVENT_MC_COMPLETE 事件自动更新
- 支持国际化

被调用方：
- simulation_tab.py
"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QFont
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QFrame,
    QLabel,
    QPushButton,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSizePolicy,
    QGroupBox,
    QProgressBar,
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
    COLOR_WARNING,
    FONT_SIZE_NORMAL,
    FONT_SIZE_SMALL,
    FONT_SIZE_TITLE,
    FONT_SIZE_LARGE_TITLE,
    SPACING_SMALL,
    SPACING_NORMAL,
    SPACING_LARGE,
    BORDER_RADIUS_NORMAL,
)


# ============================================================
# 样式常量
# ============================================================

YIELD_GOOD_THRESHOLD = 95.0  # 良率 >= 95% 显示绿色
YIELD_WARN_THRESHOLD = 80.0  # 良率 >= 80% 显示黄色，否则红色


class MetricSelector(QFrame):
    """
    指标选择器
    
    顶部下拉框，选择要查看的指标
    """
    
    metric_changed = pyqtSignal(str)  # 发出指标名称
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("metricSelector")
        self.setFixedHeight(48)
        
        self._metrics: List[str] = []
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        layout.setSpacing(SPACING_NORMAL)
        
        # 标签
        label = QLabel()
        label.setObjectName("selectorLabel")
        label.setText(self._get_text("mc.select_metric", "选择指标:"))
        layout.addWidget(label)
        self._label = label
        
        # 下拉框
        self._combo = QComboBox()
        self._combo.setObjectName("metricCombo")
        self._combo.setMinimumWidth(200)
        self._combo.currentTextChanged.connect(self._on_metric_changed)
        layout.addWidget(self._combo)
        
        layout.addStretch(1)
        
        # 运行统计
        self._stats_label = QLabel()
        self._stats_label.setObjectName("statsLabel")
        layout.addWidget(self._stats_label)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #metricSelector {{
                background-color: {COLOR_BG_SECONDARY};
                border-bottom: 1px solid {COLOR_BORDER};
            }}
            
            #selectorLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #metricCombo {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 4px 8px;
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #metricCombo::drop-down {{
                border: none;
                width: 20px;
            }}
            
            #statsLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
        """)
    
    def set_metrics(self, metric_names: List[str]):
        """设置可选指标列表"""
        self._metrics = metric_names
        self._combo.blockSignals(True)
        self._combo.clear()
        self._combo.addItems(metric_names)
        self._combo.blockSignals(False)
        
        if metric_names:
            self._combo.setCurrentIndex(0)
    
    def set_run_stats(self, successful: int, total: int, failed: int):
        """设置运行统计"""
        text = self._get_text(
            "mc.run_stats",
            f"运行: {successful}/{total} 成功, {failed} 失败"
        ).format(successful=successful, total=total, failed=failed)
        # 简化处理
        self._stats_label.setText(f"{successful}/{total} 成功, {failed} 失败")
    
    def current_metric(self) -> str:
        """获取当前选中的指标"""
        return self._combo.currentText()
    
    def _on_metric_changed(self, metric_name: str):
        """处理指标变更"""
        if metric_name:
            self.metric_changed.emit(metric_name)
    
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
        self._label.setText(self._get_text("mc.select_metric", "选择指标:"))



class StatisticsSummaryCard(QFrame):
    """
    统计摘要卡片
    
    显示均值、标准差、最小值、最大值、3σ 范围
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("statisticsCard")
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_SMALL)
        
        # 标题
        title = QLabel(self._get_text("mc.statistics", "统计数据"))
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        self._title = title
        
        # 统计项容器
        stats_frame = QFrame()
        stats_layout = QVBoxLayout(stats_frame)
        stats_layout.setContentsMargins(0, SPACING_SMALL, 0, 0)
        stats_layout.setSpacing(SPACING_SMALL)
        
        # 均值
        self._mean_row = self._create_stat_row("mc.mean", "均值", "—")
        stats_layout.addWidget(self._mean_row)
        
        # 标准差
        self._std_row = self._create_stat_row("mc.std", "标准差", "—")
        stats_layout.addWidget(self._std_row)
        
        # 最小值
        self._min_row = self._create_stat_row("mc.min", "最小值", "—")
        stats_layout.addWidget(self._min_row)
        
        # 最大值
        self._max_row = self._create_stat_row("mc.max", "最大值", "—")
        stats_layout.addWidget(self._max_row)
        
        # 中位数
        self._median_row = self._create_stat_row("mc.median", "中位数", "—")
        stats_layout.addWidget(self._median_row)
        
        # 3σ 范围
        self._sigma_row = self._create_stat_row("mc.3sigma", "3σ 范围", "—")
        stats_layout.addWidget(self._sigma_row)
        
        layout.addWidget(stats_frame)
        layout.addStretch(1)
    
    def _create_stat_row(self, key: str, default_label: str, default_value: str) -> QFrame:
        """创建统计行"""
        row = QFrame()
        row.setObjectName("statRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(SPACING_SMALL)
        
        label = QLabel(self._get_text(key, default_label))
        label.setObjectName("statLabel")
        row_layout.addWidget(label)
        
        row_layout.addStretch(1)
        
        value = QLabel(default_value)
        value.setObjectName("statValue")
        value.setAlignment(Qt.AlignmentFlag.AlignRight)
        row_layout.addWidget(value)
        
        # 存储引用
        row.label_widget = label
        row.value_widget = value
        row.i18n_key = key
        row.default_label = default_label
        
        return row
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #statisticsCard {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #cardTitle {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
                font-weight: bold;
            }}
            
            #statLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #statValue {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_SMALL}px;
                font-weight: bold;
            }}
        """)
    
    def update_statistics(
        self,
        mean: float,
        std: float,
        min_val: float,
        max_val: float,
        median: float,
        sigma_low: float,
        sigma_high: float
    ):
        """更新统计数据"""
        self._mean_row.value_widget.setText(f"{mean:.4g}")
        self._std_row.value_widget.setText(f"{std:.4g}")
        self._min_row.value_widget.setText(f"{min_val:.4g}")
        self._max_row.value_widget.setText(f"{max_val:.4g}")
        self._median_row.value_widget.setText(f"{median:.4g}")
        self._sigma_row.value_widget.setText(f"[{sigma_low:.4g}, {sigma_high:.4g}]")
    
    def clear(self):
        """清空显示"""
        for row in [self._mean_row, self._std_row, self._min_row, 
                    self._max_row, self._median_row, self._sigma_row]:
            row.value_widget.setText("—")
    
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
        self._title.setText(self._get_text("mc.statistics", "统计数据"))
        for row in [self._mean_row, self._std_row, self._min_row,
                    self._max_row, self._median_row, self._sigma_row]:
            row.label_widget.setText(self._get_text(row.i18n_key, row.default_label))



class HistogramChart(QFrame):
    """
    直方图组件
    
    基于 pyqtgraph 显示指标分布直方图
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("histogramChart")
        
        self._plot_widget = None
        self._bar_item = None
        self._mean_line = None
        self._spec_lines = []
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        try:
            import pyqtgraph as pg
            
            # 配置 pyqtgraph
            pg.setConfigOptions(antialias=True, background='w', foreground='k')
            
            # 创建绘图组件
            self._plot_widget = pg.PlotWidget()
            self._plot_widget.setObjectName("histogramPlot")
            self._plot_widget.showGrid(x=True, y=True, alpha=0.3)
            self._plot_widget.setLabel('left', self._get_text("mc.frequency", "频次"))
            self._plot_widget.setLabel('bottom', self._get_text("mc.value", "值"))
            
            layout.addWidget(self._plot_widget)
            
        except ImportError:
            # pyqtgraph 不可用，显示占位
            placeholder = QLabel(self._get_text(
                "mc.pyqtgraph_missing",
                "直方图需要 pyqtgraph 库"
            ))
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
            layout.addWidget(placeholder)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #histogramChart {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
        """)
    
    def update_histogram(
        self,
        values: List[float],
        bins: int = 20,
        mean: Optional[float] = None,
        spec_min: Optional[float] = None,
        spec_max: Optional[float] = None
    ):
        """
        更新直方图
        
        Args:
            values: 数据值列表
            bins: 分箱数量
            mean: 均值（显示垂直线）
            spec_min: 规格下限
            spec_max: 规格上限
        """
        if self._plot_widget is None or not values:
            return
        
        try:
            import pyqtgraph as pg
            
            # 清除旧图形
            self._plot_widget.clear()
            self._spec_lines.clear()
            
            # 计算直方图
            counts, edges = np.histogram(values, bins=bins)
            
            # 计算柱宽
            width = (edges[1] - edges[0]) * 0.8
            
            # 绘制柱状图
            bar_item = pg.BarGraphItem(
                x=edges[:-1] + width / 2,
                height=counts,
                width=width,
                brush=pg.mkBrush(COLOR_ACCENT),
                pen=pg.mkPen(COLOR_ACCENT, width=1)
            )
            self._plot_widget.addItem(bar_item)
            self._bar_item = bar_item
            
            # 绘制均值线
            if mean is not None:
                mean_line = pg.InfiniteLine(
                    pos=mean,
                    angle=90,
                    pen=pg.mkPen(COLOR_SUCCESS, width=2, style=Qt.PenStyle.DashLine),
                    label=f'μ={mean:.4g}',
                    labelOpts={'position': 0.9, 'color': COLOR_SUCCESS}
                )
                self._plot_widget.addItem(mean_line)
                self._mean_line = mean_line
            
            # 绘制规格限
            if spec_min is not None:
                spec_line = pg.InfiniteLine(
                    pos=spec_min,
                    angle=90,
                    pen=pg.mkPen(COLOR_ERROR, width=2),
                    label=f'Min={spec_min:.4g}',
                    labelOpts={'position': 0.1, 'color': COLOR_ERROR}
                )
                self._plot_widget.addItem(spec_line)
                self._spec_lines.append(spec_line)
            
            if spec_max is not None:
                spec_line = pg.InfiniteLine(
                    pos=spec_max,
                    angle=90,
                    pen=pg.mkPen(COLOR_ERROR, width=2),
                    label=f'Max={spec_max:.4g}',
                    labelOpts={'position': 0.1, 'color': COLOR_ERROR}
                )
                self._plot_widget.addItem(spec_line)
                self._spec_lines.append(spec_line)
            
            # 自动缩放
            self._plot_widget.autoRange()
            
        except Exception as e:
            logging.getLogger(__name__).warning(f"更新直方图失败: {e}")
    
    def clear(self):
        """清空图表"""
        if self._plot_widget:
            self._plot_widget.clear()
            self._bar_item = None
            self._mean_line = None
            self._spec_lines.clear()
    
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
        if self._plot_widget:
            self._plot_widget.setLabel('left', self._get_text("mc.frequency", "频次"))
            self._plot_widget.setLabel('bottom', self._get_text("mc.value", "值"))



class YieldDisplay(QFrame):
    """
    良率显示组件
    
    大字体百分比 + 进度环
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("yieldDisplay")
        
        self._yield_percent: float = 0.0
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_SMALL)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 标题
        title = QLabel(self._get_text("mc.yield", "良率"))
        title.setObjectName("yieldTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        self._title = title
        
        # 良率值（大字体）
        self._value_label = QLabel("—")
        self._value_label.setObjectName("yieldValue")
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._value_label)
        
        # 进度条
        self._progress_bar = QProgressBar()
        self._progress_bar.setObjectName("yieldProgress")
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(8)
        layout.addWidget(self._progress_bar)
        
        # 状态文本
        self._status_label = QLabel()
        self._status_label.setObjectName("yieldStatus")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #yieldDisplay {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #yieldTitle {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #yieldValue {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_LARGE_TITLE + 8}px;
                font-weight: bold;
            }}
            
            #yieldProgress {{
                background-color: #e0e0e0;
                border: none;
                border-radius: 4px;
            }}
            
            #yieldProgress::chunk {{
                border-radius: 4px;
            }}
            
            #yieldStatus {{
                font-size: {FONT_SIZE_SMALL}px;
            }}
        """)
    
    def set_yield(self, yield_percent: float):
        """设置良率"""
        self._yield_percent = max(0.0, min(100.0, yield_percent))
        
        # 更新显示
        self._value_label.setText(f"{self._yield_percent:.1f}%")
        self._progress_bar.setValue(int(self._yield_percent))
        
        # 根据良率设置颜色
        if self._yield_percent >= YIELD_GOOD_THRESHOLD:
            color = COLOR_SUCCESS
            status = self._get_text("mc.yield_good", "良好")
        elif self._yield_percent >= YIELD_WARN_THRESHOLD:
            color = COLOR_WARNING
            status = self._get_text("mc.yield_warn", "需关注")
        else:
            color = COLOR_ERROR
            status = self._get_text("mc.yield_bad", "需改进")
        
        self._value_label.setStyleSheet(f"""
            color: {color};
            font-size: {FONT_SIZE_LARGE_TITLE + 8}px;
            font-weight: bold;
        """)
        
        self._progress_bar.setStyleSheet(f"""
            #yieldProgress {{
                background-color: #e0e0e0;
                border: none;
                border-radius: 4px;
            }}
            #yieldProgress::chunk {{
                background-color: {color};
                border-radius: 4px;
            }}
        """)
        
        self._status_label.setText(status)
        self._status_label.setStyleSheet(f"color: {color}; font-size: {FONT_SIZE_SMALL}px;")
    
    def clear(self):
        """清空显示"""
        self._yield_percent = 0.0
        self._value_label.setText("—")
        self._progress_bar.setValue(0)
        self._status_label.clear()
    
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
        self._title.setText(self._get_text("mc.yield", "良率"))



class SensitiveParamsPanel(QFrame):
    """
    敏感参数排名面板
    
    显示按敏感度排序的参数列表
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("sensitiveParamsPanel")
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_SMALL)
        
        # 标题
        title = QLabel(self._get_text("mc.sensitive_params", "敏感参数"))
        title.setObjectName("panelTitle")
        layout.addWidget(title)
        self._title = title
        
        # 参数列表
        self._table = QTableWidget()
        self._table.setObjectName("paramsTable")
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels([
            self._get_text("mc.rank", "排名"),
            self._get_text("mc.parameter", "参数")
        ])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 50)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table, 1)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #sensitiveParamsPanel {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #panelTitle {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
                font-weight: bold;
            }}
            
            #paramsTable {{
                background-color: {COLOR_BG_PRIMARY};
                border: none;
                gridline-color: {COLOR_BORDER};
            }}
            
            #paramsTable::item {{
                padding: 4px;
            }}
            
            #paramsTable::item:selected {{
                background-color: {COLOR_ACCENT_LIGHT};
                color: {COLOR_TEXT_PRIMARY};
            }}
            
            #paramsTable QHeaderView::section {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_PRIMARY};
                padding: 6px;
                border: none;
                border-bottom: 1px solid {COLOR_BORDER};
                font-weight: bold;
            }}
        """)
    
    def set_params(self, params: List[str]):
        """设置敏感参数列表"""
        self._table.setRowCount(len(params))
        
        for idx, param in enumerate(params):
            # 排名
            rank_item = QTableWidgetItem(str(idx + 1))
            rank_item.setFlags(rank_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            rank_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(idx, 0, rank_item)
            
            # 参数名
            param_item = QTableWidgetItem(param)
            param_item.setFlags(param_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(idx, 1, param_item)
    
    def clear(self):
        """清空列表"""
        self._table.setRowCount(0)
    
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
        self._title.setText(self._get_text("mc.sensitive_params", "敏感参数"))
        self._table.setHorizontalHeaderLabels([
            self._get_text("mc.rank", "排名"),
            self._get_text("mc.parameter", "参数")
        ])



class MonteCarloResultTab(QWidget):
    """
    蒙特卡洛分析结果标签页
    
    展示蒙特卡洛统计分析结果，支持直方图和良率显示。
    
    Signals:
        export_requested: 请求导出数据
    """
    
    export_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # 数据
        self._mc_result: Optional[Any] = None
        self._current_metric: str = ""
        
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
        
        # 顶部：指标选择器
        self._metric_selector = MetricSelector()
        main_layout.addWidget(self._metric_selector)
        
        # 主内容区
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        content_layout.setSpacing(SPACING_NORMAL)
        
        # 左侧面板（统计摘要 + 良率）
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(SPACING_NORMAL)
        
        # 统计摘要卡片
        self._statistics_card = StatisticsSummaryCard()
        left_layout.addWidget(self._statistics_card)
        
        # 良率显示
        self._yield_display = YieldDisplay()
        left_layout.addWidget(self._yield_display)
        
        # 敏感参数面板
        self._sensitive_params = SensitiveParamsPanel()
        left_layout.addWidget(self._sensitive_params, 1)
        
        left_panel.setFixedWidth(280)
        content_layout.addWidget(left_panel)
        
        # 右侧：直方图
        self._histogram = HistogramChart()
        content_layout.addWidget(self._histogram, 1)
        
        main_layout.addWidget(content_widget, 1)
        
        # 底部：操作栏
        self._action_bar = QFrame()
        self._action_bar.setObjectName("actionBar")
        self._action_bar.setFixedHeight(48)
        action_layout = QHBoxLayout(self._action_bar)
        action_layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        
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
            MonteCarloResultTab {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #actionBar {{
                background-color: {COLOR_BG_SECONDARY};
                border-top: 1px solid {COLOR_BORDER};
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
        self._metric_selector.metric_changed.connect(self._on_metric_changed)
    
    def _subscribe_events(self):
        """订阅事件"""
        event_bus = self._get_event_bus()
        if not event_bus:
            return
        
        from shared.event_types import EVENT_MC_COMPLETE, EVENT_LANGUAGE_CHANGED
        
        subscriptions = [
            (EVENT_MC_COMPLETE, self._on_mc_complete),
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
    
    def update_results(self, mc_result: Any):
        """
        更新蒙特卡洛分析结果显示
        
        Args:
            mc_result: MonteCarloAnalysisResult 对象
        """
        self._mc_result = mc_result
        
        if mc_result is None:
            self._show_empty_state()
            return
        
        self._show_content_state()
        
        # 提取指标列表
        statistics = getattr(mc_result, 'statistics', {})
        metric_names = list(statistics.keys())
        
        # 更新指标选择器
        self._metric_selector.set_metrics(metric_names)
        
        # 更新运行统计
        successful = getattr(mc_result, 'successful_runs', 0)
        total = getattr(mc_result, 'num_runs', 0)
        failed = getattr(mc_result, 'failed_runs', 0)
        self._metric_selector.set_run_stats(successful, total, failed)
        
        # 更新良率
        yield_percent = getattr(mc_result, 'yield_percent', 0.0)
        self._yield_display.set_yield(yield_percent)
        
        # 更新敏感参数
        sensitive_params = getattr(mc_result, 'sensitive_params', [])
        self._sensitive_params.set_params(sensitive_params)
        
        # 显示第一个指标
        if metric_names:
            self._current_metric = metric_names[0]
            self._update_metric_display(metric_names[0])
    
    def switch_metric(self, metric_name: str):
        """切换显示的指标"""
        if self._mc_result is None:
            return
        
        self._current_metric = metric_name
        self._update_metric_display(metric_name)
    
    def _update_metric_display(self, metric_name: str):
        """更新指定指标的显示"""
        if self._mc_result is None:
            return
        
        statistics = getattr(self._mc_result, 'statistics', {})
        stats = statistics.get(metric_name)
        
        if stats is None:
            self._statistics_card.clear()
            self._histogram.clear()
            return
        
        # 更新统计摘要
        # 支持两种数据格式：MonteCarloStatistics 对象或字典
        if hasattr(stats, 'mean'):
            mean = stats.mean
            std = stats.std
            min_val = stats.min_value
            max_val = stats.max_value
            median = stats.median
            sigma_low = stats.percentile_3sigma_low
            sigma_high = stats.percentile_3sigma_high
            values = getattr(stats, 'values', [])
        else:
            # 字典格式
            mean = stats.get('mean', 0)
            std = stats.get('std', 0)
            min_val = stats.get('min', 0)
            max_val = stats.get('max', 0)
            median = stats.get('median', 0)
            sigma_low = stats.get('3sigma_low', 0)
            sigma_high = stats.get('3sigma_high', 0)
            values = stats.get('values', [])
        
        self._statistics_card.update_statistics(
            mean=mean,
            std=std,
            min_val=min_val,
            max_val=max_val,
            median=median,
            sigma_low=sigma_low,
            sigma_high=sigma_high
        )
        
        # 更新直方图
        if values:
            self._histogram.update_histogram(
                values=values,
                bins=20,
                mean=mean
            )
        else:
            self._histogram.clear()
    
    def show_distribution_details(self):
        """显示详细分布信息"""
        # 可扩展：弹出详细分布对话框
        pass
    
    def export_statistics(self):
        """导出统计数据"""
        self.export_requested.emit()
    
    def clear(self):
        """清空显示"""
        self._mc_result = None
        self._current_metric = ""
        self._statistics_card.clear()
        self._yield_display.clear()
        self._sensitive_params.clear()
        self._histogram.clear()
        self._show_empty_state()
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _show_empty_state(self):
        """显示空状态"""
        self._metric_selector.hide()
        self._empty_widget.show()
        self._action_bar.hide()
        
        # 隐藏内容区的父容器
        for i in range(self.layout().count()):
            widget = self.layout().itemAt(i).widget()
            if widget and widget not in [self._metric_selector, self._empty_widget, self._action_bar]:
                widget.hide()
    
    def _show_content_state(self):
        """显示内容状态"""
        self._metric_selector.show()
        self._empty_widget.hide()
        self._action_bar.show()
        
        # 显示内容区的父容器
        for i in range(self.layout().count()):
            widget = self.layout().itemAt(i).widget()
            if widget and widget not in [self._empty_widget]:
                widget.show()
    
    # ============================================================
    # 事件处理
    # ============================================================
    
    def _on_metric_changed(self, metric_name: str):
        """处理指标变更"""
        self.switch_metric(metric_name)
    
    def _on_mc_complete(self, event_data: Dict[str, Any]):
        """处理蒙特卡洛分析完成事件"""
        result = event_data.get('result')
        if result:
            self.update_results(result)
    
    def _on_language_changed(self, event_data: Dict[str, Any]):
        """处理语言变更事件"""
        self.retranslate_ui()
    
    def _on_export_clicked(self):
        """处理导出按钮点击"""
        self.export_statistics()
    
    # ============================================================
    # 国际化
    # ============================================================
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._empty_label.setText(self._get_text(
            "mc.no_results",
            "暂无蒙特卡洛分析结果"
        ))
        self._export_btn.setText(self._get_text(
            "mc.export",
            "导出数据"
        ))
        
        self._metric_selector.retranslate_ui()
        self._statistics_card.retranslate_ui()
        self._yield_display.retranslate_ui()
        self._sensitive_params.retranslate_ui()
        self._histogram.retranslate_ui()
    
    def _get_text(self, key: str, default: str) -> str:
        """获取国际化文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(key, default)
        except ImportError:
            return default
    
    # ============================================================
    # 生命周期
    # ============================================================
    
    def closeEvent(self, event):
        """关闭事件"""
        self._unsubscribe_events()
        super().closeEvent(event)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "MonteCarloResultTab",
    "MetricSelector",
    "StatisticsSummaryCard",
    "HistogramChart",
    "YieldDisplay",
    "SensitiveParamsPanel",
]
