# PVTResultTab - PVT Corner Analysis Result Tab
"""
PVT 角点分析结果标签页

职责：
- 展示 PVT 角点仿真结果
- 支持角点对比和最差角点高亮
- 提供角点选择和指标对比功能

设计原则：
- 使用 QWidget 作为基类
- 订阅 EVENT_PVT_COMPLETE 事件自动更新
- 支持国际化

被调用方：
- simulation_tab.py
"""

import logging
from typing import Any, Dict, List, Optional

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
    SPACING_SMALL,
    SPACING_NORMAL,
    SPACING_LARGE,
    BORDER_RADIUS_NORMAL,
)


# ============================================================
# 样式常量
# ============================================================

CORNER_COLORS = {
    "TT": "#4CAF50",  # 绿色 - 典型
    "FF": "#2196F3",  # 蓝色 - 快速
    "SS": "#FF9800",  # 橙色 - 慢速
    "FS": "#9C27B0",  # 紫色 - NMOS快/PMOS慢
    "SF": "#00BCD4",  # 青色 - NMOS慢/PMOS快
}

PASS_COLOR = COLOR_SUCCESS
FAIL_COLOR = COLOR_ERROR
WORST_HIGHLIGHT_COLOR = "#FFF3E0"  # 浅橙色背景


class CornerSelectorBar(QFrame):
    """
    角点选择器栏
    
    显示角点标签按钮，支持选择和高亮
    """
    
    corner_selected = pyqtSignal(str)  # 发出角点名称
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("cornerSelectorBar")
        self.setFixedHeight(48)
        
        self._corner_buttons: Dict[str, QPushButton] = {}
        self._selected_corner: str = ""
        self._worst_corner: str = ""
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        layout.setSpacing(SPACING_SMALL)
        
        # 标签
        label = QLabel()
        label.setObjectName("cornerLabel")
        label.setText(self._get_text("pvt.corners", "角点:"))
        layout.addWidget(label)
        
        # 角点按钮容器
        self._btn_container = QWidget()
        self._btn_layout = QHBoxLayout(self._btn_container)
        self._btn_layout.setContentsMargins(0, 0, 0, 0)
        self._btn_layout.setSpacing(SPACING_SMALL)
        layout.addWidget(self._btn_container)
        
        layout.addStretch(1)
        
        # 状态摘要
        self._status_label = QLabel()
        self._status_label.setObjectName("statusLabel")
        layout.addWidget(self._status_label)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #cornerSelectorBar {{
                background-color: {COLOR_BG_SECONDARY};
                border-bottom: 1px solid {COLOR_BORDER};
            }}
            
            #cornerLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #statusLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
        """)
    
    def set_corners(self, corner_names: List[str], worst_corner: str = ""):
        """
        设置角点列表
        
        Args:
            corner_names: 角点名称列表
            worst_corner: 最差角点名称
        """
        # 清除旧按钮
        for btn in self._corner_buttons.values():
            btn.deleteLater()
        self._corner_buttons.clear()
        
        self._worst_corner = worst_corner
        
        # 创建新按钮
        for name in corner_names:
            btn = QPushButton(name)
            btn.setObjectName(f"cornerBtn_{name}")
            btn.setCheckable(True)
            btn.setFixedHeight(28)
            btn.setMinimumWidth(50)
            
            # 设置颜色
            color = CORNER_COLORS.get(name, COLOR_ACCENT)
            is_worst = name == worst_corner
            
            btn.setStyleSheet(self._get_button_style(color, is_worst))
            btn.clicked.connect(lambda checked, n=name: self._on_corner_clicked(n))
            
            self._btn_layout.addWidget(btn)
            self._corner_buttons[name] = btn
        
        # 默认选中第一个
        if corner_names:
            self._select_corner(corner_names[0])
    
    def _get_button_style(self, color: str, is_worst: bool) -> str:
        """获取按钮样式"""
        border_style = f"2px solid {FAIL_COLOR}" if is_worst else f"1px solid {color}"
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {color};
                border: {border_style};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 4px 12px;
                font-size: {FONT_SIZE_SMALL}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLOR_ACCENT_LIGHT};
            }}
            QPushButton:checked {{
                background-color: {color};
                color: white;
            }}
        """
    
    def _on_corner_clicked(self, corner_name: str):
        """处理角点按钮点击"""
        self._select_corner(corner_name)
        self.corner_selected.emit(corner_name)
    
    def _select_corner(self, corner_name: str):
        """选中指定角点"""
        self._selected_corner = corner_name
        
        for name, btn in self._corner_buttons.items():
            btn.setChecked(name == corner_name)
    
    def set_status(self, passed: int, total: int, all_passed: bool):
        """设置状态摘要"""
        status_text = f"{passed}/{total} " + self._get_text("pvt.passed", "通过")
        if all_passed:
            self._status_label.setText(f"✓ {status_text}")
            self._status_label.setStyleSheet(f"color: {PASS_COLOR}; font-weight: bold;")
        else:
            self._status_label.setText(f"✗ {status_text}")
            self._status_label.setStyleSheet(f"color: {FAIL_COLOR}; font-weight: bold;")
    
    def highlight_worst(self, corner_name: str):
        """高亮最差角点"""
        self._worst_corner = corner_name
        for name, btn in self._corner_buttons.items():
            color = CORNER_COLORS.get(name, COLOR_ACCENT)
            is_worst = name == corner_name
            btn.setStyleSheet(self._get_button_style(color, is_worst))
    
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


class MetricsComparisonTable(QTableWidget):
    """
    指标对比表格
    
    显示各角点的指标值，最差角点红色高亮
    """
    
    metric_selected = pyqtSignal(str)  # 发出指标名称
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("metricsComparisonTable")
        
        self._corner_names: List[str] = []
        self._worst_corner: str = ""
        self._metrics_data: Dict[str, Dict[str, Any]] = {}
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setShowGrid(True)
        self.verticalHeader().setVisible(False)
        
        # 表头自适应
        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        
        # 点击行选中指标
        self.cellClicked.connect(self._on_cell_clicked)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            QTableWidget {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                gridline-color: {COLOR_BORDER};
            }}
            
            QTableWidget::item {{
                padding: 8px;
            }}
            
            QTableWidget::item:selected {{
                background-color: {COLOR_ACCENT_LIGHT};
                color: {COLOR_TEXT_PRIMARY};
            }}
            
            QHeaderView::section {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_PRIMARY};
                padding: 8px;
                border: none;
                border-bottom: 1px solid {COLOR_BORDER};
                font-weight: bold;
            }}
        """)

    
    def set_data(
        self,
        corner_names: List[str],
        metrics_comparison: Dict[str, Dict[str, float]],
        worst_corner: str = "",
        corner_passed: Optional[Dict[str, bool]] = None
    ):
        """
        设置表格数据
        
        Args:
            corner_names: 角点名称列表
            metrics_comparison: 指标对比数据 {metric_name: {corner_name: value}}
            worst_corner: 最差角点名称
            corner_passed: 各角点通过状态 {corner_name: passed}
        """
        self._corner_names = corner_names
        self._worst_corner = worst_corner
        self._metrics_data = metrics_comparison
        
        # 设置列
        columns = [self._get_text("pvt.metric", "指标")] + corner_names
        self.setColumnCount(len(columns))
        self.setHorizontalHeaderLabels(columns)
        
        # 设置行
        metric_names = list(metrics_comparison.keys())
        self.setRowCount(len(metric_names))
        
        for row, metric_name in enumerate(metric_names):
            # 指标名称列
            name_item = QTableWidgetItem(metric_name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(row, 0, name_item)
            
            # 各角点值列
            metric_values = metrics_comparison.get(metric_name, {})
            
            # 找出该指标的最差值（假设最小值为最差）
            values = [metric_values.get(cn, 0) for cn in corner_names]
            min_val = min(values) if values else 0
            max_val = max(values) if values else 0
            
            for col, corner_name in enumerate(corner_names, start=1):
                value = metric_values.get(corner_name, 0)
                
                # 格式化数值
                if isinstance(value, float):
                    display_value = f"{value:.4g}"
                else:
                    display_value = str(value)
                
                item = QTableWidgetItem(display_value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                
                # 高亮最差角点
                if corner_name == worst_corner:
                    item.setBackground(QBrush(QColor(WORST_HIGHLIGHT_COLOR)))
                
                # 高亮最差值（红色文字）
                if value == min_val and min_val != max_val:
                    item.setForeground(QBrush(QColor(FAIL_COLOR)))
                
                # 角点通过/失败状态
                if corner_passed and not corner_passed.get(corner_name, True):
                    item.setForeground(QBrush(QColor(FAIL_COLOR)))
                
                self.setItem(row, col, item)
        
        # 调整列宽
        self.resizeColumnsToContents()
    
    def highlight_worst_corner(self, metric_name: str):
        """
        高亮指定指标的最差角点
        
        Args:
            metric_name: 指标名称
        """
        if metric_name not in self._metrics_data:
            return
        
        metric_values = self._metrics_data[metric_name]
        if not metric_values:
            return
        
        # 找出最差值
        min_corner = min(metric_values.keys(), key=lambda k: metric_values.get(k, 0))
        
        # 更新高亮
        for row in range(self.rowCount()):
            name_item = self.item(row, 0)
            if name_item and name_item.text() == metric_name:
                for col, corner_name in enumerate(self._corner_names, start=1):
                    item = self.item(row, col)
                    if item:
                        if corner_name == min_corner:
                            item.setBackground(QBrush(QColor(FAIL_COLOR)))
                            item.setForeground(QBrush(QColor("white")))
                        else:
                            item.setBackground(QBrush(QColor("transparent")))
                            item.setForeground(QBrush(QColor(COLOR_TEXT_PRIMARY)))
                break
    
    def _on_cell_clicked(self, row: int, col: int):
        """处理单元格点击"""
        name_item = self.item(row, 0)
        if name_item:
            self.metric_selected.emit(name_item.text())
    
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
        # 更新表头
        if self._corner_names:
            columns = [self._get_text("pvt.metric", "指标")] + self._corner_names
            self.setHorizontalHeaderLabels(columns)


class CornerDetailPanel(QFrame):
    """
    角点详情面板
    
    显示选中角点的详细信息
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("cornerDetailPanel")
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_NORMAL)
        
        # 角点名称
        self._corner_name_label = QLabel()
        self._corner_name_label.setObjectName("cornerNameLabel")
        layout.addWidget(self._corner_name_label)
        
        # 角点参数组
        params_group = QGroupBox(self._get_text("pvt.parameters", "角点参数"))
        params_layout = QVBoxLayout(params_group)
        
        # 工艺
        self._process_label = QLabel()
        params_layout.addWidget(self._process_label)
        
        # 电压
        self._voltage_label = QLabel()
        params_layout.addWidget(self._voltage_label)
        
        # 温度
        self._temperature_label = QLabel()
        params_layout.addWidget(self._temperature_label)
        
        # 描述
        self._description_label = QLabel()
        self._description_label.setWordWrap(True)
        params_layout.addWidget(self._description_label)
        
        layout.addWidget(params_group)
        
        # 状态
        self._status_frame = QFrame()
        self._status_frame.setObjectName("statusFrame")
        status_layout = QHBoxLayout(self._status_frame)
        status_layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        
        self._status_icon = QLabel()
        self._status_icon.setFixedSize(24, 24)
        status_layout.addWidget(self._status_icon)
        
        self._status_text = QLabel()
        status_layout.addWidget(self._status_text, 1)
        
        layout.addWidget(self._status_frame)
        
        # 失败目标列表
        self._failed_goals_group = QGroupBox(self._get_text("pvt.failed_goals", "未通过的设计目标"))
        self._failed_goals_layout = QVBoxLayout(self._failed_goals_group)
        self._failed_goals_label = QLabel()
        self._failed_goals_label.setWordWrap(True)
        self._failed_goals_layout.addWidget(self._failed_goals_label)
        layout.addWidget(self._failed_goals_group)
        self._failed_goals_group.hide()
        
        layout.addStretch(1)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #cornerDetailPanel {{
                background-color: {COLOR_BG_PRIMARY};
                border-left: 1px solid {COLOR_BORDER};
            }}
            
            #cornerNameLabel {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_TITLE}px;
                font-weight: bold;
            }}
            
            QGroupBox {{
                font-weight: bold;
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                margin-top: 12px;
                padding-top: 8px;
            }}
            
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
            
            #statusFrame {{
                background-color: {COLOR_BG_SECONDARY};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
        """)

    
    def set_corner_detail(
        self,
        corner_name: str,
        process: str,
        voltage_factor: float,
        temperature: float,
        description: str,
        passed: bool,
        failed_goals: Optional[List[str]] = None
    ):
        """
        设置角点详情
        
        Args:
            corner_name: 角点名称
            process: 工艺角
            voltage_factor: 电压因子
            temperature: 温度
            description: 描述
            passed: 是否通过
            failed_goals: 未通过的设计目标列表
        """
        # 角点名称（带颜色）
        color = CORNER_COLORS.get(corner_name, COLOR_ACCENT)
        self._corner_name_label.setText(corner_name)
        self._corner_name_label.setStyleSheet(f"""
            color: {color};
            font-size: {FONT_SIZE_TITLE}px;
            font-weight: bold;
        """)
        
        # 参数
        process_text = self._get_text(f"pvt.process.{process}", process)
        self._process_label.setText(f"{self._get_text('pvt.process', '工艺')}: {process_text}")
        self._voltage_label.setText(f"{self._get_text('pvt.voltage', '电压')}: {voltage_factor:.2f}x")
        self._temperature_label.setText(f"{self._get_text('pvt.temperature', '温度')}: {temperature}°C")
        self._description_label.setText(description)
        
        # 状态
        if passed:
            self._status_icon.setText("✓")
            self._status_icon.setStyleSheet(f"color: {PASS_COLOR}; font-size: 18px; font-weight: bold;")
            self._status_text.setText(self._get_text("pvt.status.passed", "通过"))
            self._status_text.setStyleSheet(f"color: {PASS_COLOR}; font-weight: bold;")
            self._status_frame.setStyleSheet(f"""
                #statusFrame {{
                    background-color: #E8F5E9;
                    border-radius: {BORDER_RADIUS_NORMAL}px;
                }}
            """)
        else:
            self._status_icon.setText("✗")
            self._status_icon.setStyleSheet(f"color: {FAIL_COLOR}; font-size: 18px; font-weight: bold;")
            self._status_text.setText(self._get_text("pvt.status.failed", "未通过"))
            self._status_text.setStyleSheet(f"color: {FAIL_COLOR}; font-weight: bold;")
            self._status_frame.setStyleSheet(f"""
                #statusFrame {{
                    background-color: #FFEBEE;
                    border-radius: {BORDER_RADIUS_NORMAL}px;
                }}
            """)
        
        # 失败目标
        if failed_goals:
            self._failed_goals_label.setText("\n".join(f"• {g}" for g in failed_goals))
            self._failed_goals_group.show()
        else:
            self._failed_goals_group.hide()
    
    def clear(self):
        """清空显示"""
        self._corner_name_label.clear()
        self._process_label.clear()
        self._voltage_label.clear()
        self._temperature_label.clear()
        self._description_label.clear()
        self._status_icon.clear()
        self._status_text.clear()
        self._failed_goals_group.hide()
    
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


class PVTResultTab(QWidget):
    """
    PVT 角点分析结果标签页
    
    展示 PVT 角点仿真结果，支持角点对比和最差角点高亮。
    
    Signals:
        export_requested: 请求导出数据
    """
    
    export_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # 数据
        self._pvt_result: Optional[Any] = None
        self._corner_results: Dict[str, Any] = {}
        
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
        
        # 顶部：角点选择器
        self._corner_selector = CornerSelectorBar()
        main_layout.addWidget(self._corner_selector)
        
        # 主内容区（左右分栏）
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setObjectName("pvtSplitter")
        self._splitter.setHandleWidth(1)
        self._splitter.setChildrenCollapsible(False)
        
        # 左侧：指标对比表格
        self._metrics_table = MetricsComparisonTable()
        self._splitter.addWidget(self._metrics_table)
        
        # 右侧：角点详情面板
        self._detail_panel = CornerDetailPanel()
        self._detail_panel.setMinimumWidth(250)
        self._detail_panel.setMaximumWidth(350)
        self._splitter.addWidget(self._detail_panel)
        
        # 设置初始比例（70:30）
        self._splitter.setSizes([700, 300])
        
        main_layout.addWidget(self._splitter, 1)
        
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
            PVTResultTab {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #pvtSplitter {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #pvtSplitter::handle {{
                background-color: {COLOR_BORDER};
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
        self._corner_selector.corner_selected.connect(self._on_corner_selected)
        self._metrics_table.metric_selected.connect(self._on_metric_selected)
    
    def _subscribe_events(self):
        """订阅事件"""
        event_bus = self._get_event_bus()
        if not event_bus:
            return
        
        from shared.event_types import EVENT_PVT_COMPLETE, EVENT_LANGUAGE_CHANGED
        
        subscriptions = [
            (EVENT_PVT_COMPLETE, self._on_pvt_complete),
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
    
    def update_results(self, pvt_result: Any):
        """
        更新 PVT 分析结果显示
        
        Args:
            pvt_result: PVTAnalysisResult 对象
        """
        self._pvt_result = pvt_result
        
        if pvt_result is None:
            self._show_empty_state()
            return
        
        self._show_content_state()
        
        # 提取角点信息
        corner_names = []
        corner_passed = {}
        self._corner_results = {}
        
        # 支持两种数据格式：PVTAnalysisResult 和 pvt_analysis.PVTAnalysisResult
        if hasattr(pvt_result, 'corners'):
            # 来自 domain/simulation/analysis/pvt_analysis.py
            for corner_result in pvt_result.corners:
                corner = corner_result.corner
                corner_names.append(corner.name)
                corner_passed[corner.name] = corner_result.passed
                self._corner_results[corner.name] = corner_result
        elif hasattr(pvt_result, 'corner_results'):
            # 来自 domain/simulation/models/analysis_result.py
            for corner in getattr(pvt_result, 'corners', []):
                corner_names.append(corner.name)
            corner_passed = {cn: True for cn in corner_names}  # 默认通过
        
        # 获取最差角点
        worst_corner = getattr(pvt_result, 'worst_corner', '')
        all_passed = getattr(pvt_result, 'all_passed', True)
        
        # 更新角点选择器
        self._corner_selector.set_corners(corner_names, worst_corner)
        passed_count = sum(1 for v in corner_passed.values() if v)
        self._corner_selector.set_status(passed_count, len(corner_names), all_passed)
        
        # 更新指标对比表格
        metrics_comparison = getattr(pvt_result, 'metrics_comparison', {})
        if not metrics_comparison and self._corner_results:
            # 从角点结果中构建指标对比
            metrics_comparison = self._build_metrics_comparison()
        
        self._metrics_table.set_data(
            corner_names=corner_names,
            metrics_comparison=metrics_comparison,
            worst_corner=worst_corner,
            corner_passed=corner_passed
        )
        
        # 默认显示第一个角点详情
        if corner_names:
            self._show_corner_detail(corner_names[0])
    
    def _build_metrics_comparison(self) -> Dict[str, Dict[str, float]]:
        """从角点结果构建指标对比数据"""
        comparison = {}
        
        for corner_name, corner_result in self._corner_results.items():
            metrics = getattr(corner_result, 'metrics', {})
            for metric_name, value in metrics.items():
                if metric_name not in comparison:
                    comparison[metric_name] = {}
                comparison[metric_name][corner_name] = value
        
        return comparison
    
    def highlight_worst_corner(self, metric: str):
        """
        高亮指定指标的最差角点
        
        Args:
            metric: 指标名称
        """
        self._metrics_table.highlight_worst_corner(metric)
    
    def export_comparison(self) -> Dict[str, Any]:
        """
        导出角点对比数据
        
        Returns:
            Dict: 导出数据
        """
        if not self._pvt_result:
            return {}
        
        return {
            "analysis_type": "pvt",
            "timestamp": getattr(self._pvt_result, 'timestamp', ''),
            "circuit_file": getattr(self._pvt_result, 'circuit_file', ''),
            "all_passed": getattr(self._pvt_result, 'all_passed', True),
            "worst_corner": getattr(self._pvt_result, 'worst_corner', ''),
            "metrics_comparison": getattr(self._pvt_result, 'metrics_comparison', {}),
            "corners": [
                {
                    "name": cr.corner.name,
                    "process": cr.corner.process.value if hasattr(cr.corner.process, 'value') else str(cr.corner.process),
                    "voltage_factor": cr.corner.voltage_factor,
                    "temperature": cr.corner.temperature,
                    "passed": cr.passed,
                    "metrics": cr.metrics,
                }
                for cr in self._corner_results.values()
            ] if self._corner_results else []
        }
    
    def clear(self):
        """清空显示"""
        self._pvt_result = None
        self._corner_results.clear()
        self._metrics_table.clearContents()
        self._metrics_table.setRowCount(0)
        self._detail_panel.clear()
        self._show_empty_state()
    
    # ============================================================
    # 事件处理
    # ============================================================
    
    def _on_pvt_complete(self, event_data: Dict[str, Any]):
        """处理 PVT 分析完成事件"""
        result = event_data.get('result')
        if result:
            self.update_results(result)
    
    def _on_language_changed(self, event_data: Dict[str, Any]):
        """处理语言变更事件"""
        self.retranslate_ui()
    
    def _on_corner_selected(self, corner_name: str):
        """处理角点选择"""
        self._show_corner_detail(corner_name)
    
    def _on_metric_selected(self, metric_name: str):
        """处理指标选择"""
        self.highlight_worst_corner(metric_name)
    
    def _on_export_clicked(self):
        """处理导出按钮点击"""
        self.export_requested.emit()
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _show_corner_detail(self, corner_name: str):
        """显示角点详情"""
        if corner_name not in self._corner_results:
            self._detail_panel.clear()
            return
        
        corner_result = self._corner_results[corner_name]
        corner = corner_result.corner
        
        # 获取工艺值
        process_value = corner.process.value if hasattr(corner.process, 'value') else str(corner.process)
        
        self._detail_panel.set_corner_detail(
            corner_name=corner.name,
            process=process_value,
            voltage_factor=corner.voltage_factor,
            temperature=corner.temperature,
            description=getattr(corner, 'description', ''),
            passed=corner_result.passed,
            failed_goals=getattr(corner_result, 'failed_goals', [])
        )
    
    def _show_empty_state(self):
        """显示空状态"""
        self._corner_selector.hide()
        self._splitter.hide()
        self._action_bar.hide()
        self._empty_widget.show()
    
    def _show_content_state(self):
        """显示内容状态"""
        self._empty_widget.hide()
        self._corner_selector.show()
        self._splitter.show()
        self._action_bar.show()
    
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
        self._empty_label.setText(self._get_text(
            "pvt.no_results",
            "暂无 PVT 分析结果"
        ))
        self._export_btn.setText(self._get_text(
            "pvt.export",
            "导出对比数据"
        ))
        
        self._corner_selector.retranslate_ui()
        self._metrics_table.retranslate_ui()
        self._detail_panel.retranslate_ui()
    
    def closeEvent(self, event):
        """关闭事件"""
        self._unsubscribe_events()
        super().closeEvent(event)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "PVTResultTab",
    "CornerSelectorBar",
    "MetricsComparisonTable",
    "CornerDetailPanel",
]
