# TopologyInfoPanel - Circuit Topology Information Panel
"""
拓扑识别信息面板

职责：
- 展示电路拓扑识别结果
- 显示拓扑类型、置信度、识别依据
- 提供推荐分析列表和关键节点
- 支持应用推荐配置功能

设计原则：
- 使用 QWidget 作为基类
- 订阅 EVENT_TOPOLOGY_DETECTED 事件自动更新
- 支持国际化

被调用方：
- simulation_tab.py
"""

import logging
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QPushButton,
    QGroupBox,
    QCheckBox,
    QSizePolicy,
    QScrollArea,
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

CONFIDENCE_HIGH_THRESHOLD = 0.8
CONFIDENCE_MEDIUM_THRESHOLD = 0.5

TOPOLOGY_TYPE_COLORS = {
    "amplifier": "#4CAF50",
    "filter": "#2196F3",
    "power": "#FF9800",
    "oscillator": "#9C27B0",
    "comparator": "#00BCD4",
    "converter": "#E91E63",
    "unknown": "#9E9E9E",
}

TOPOLOGY_TYPE_NAMES = {
    "amplifier": "放大器",
    "filter": "滤波器",
    "power": "电源",
    "oscillator": "振荡器",
    "comparator": "比较器",
    "converter": "数据转换器",
    "unknown": "未知",
}


class TopologyTypeCard(QFrame):
    """
    拓扑类型卡片
    
    大字体显示拓扑类型和置信度
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("topologyTypeCard")
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_SMALL)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 拓扑类型（大字体）
        self._type_label = QLabel()
        self._type_label.setObjectName("topologyTypeLabel")
        self._type_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._type_label)
        
        # 子类型
        self._subtype_label = QLabel()
        self._subtype_label.setObjectName("subtypeLabel")
        self._subtype_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._subtype_label)
        
        # 置信度
        self._confidence_label = QLabel()
        self._confidence_label.setObjectName("confidenceLabel")
        self._confidence_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._confidence_label)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #topologyTypeCard {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #topologyTypeLabel {{
                font-size: {FONT_SIZE_LARGE_TITLE + 4}px;
                font-weight: bold;
            }}
            
            #subtypeLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #confidenceLabel {{
                font-size: {FONT_SIZE_SMALL}px;
            }}
        """)
    
    def set_topology(self, topology_type: str, sub_type: str, confidence: float):
        """
        设置拓扑信息
        
        Args:
            topology_type: 拓扑类型
            sub_type: 子类型
            confidence: 置信度 (0-1)
        """
        # 获取类型名称和颜色
        type_name = TOPOLOGY_TYPE_NAMES.get(topology_type, topology_type)
        type_color = TOPOLOGY_TYPE_COLORS.get(topology_type, COLOR_TEXT_PRIMARY)
        
        self._type_label.setText(type_name)
        self._type_label.setStyleSheet(f"""
            color: {type_color};
            font-size: {FONT_SIZE_LARGE_TITLE + 4}px;
            font-weight: bold;
        """)
        
        # 子类型
        if sub_type and sub_type != "unknown":
            self._subtype_label.setText(sub_type.replace("_", " ").title())
            self._subtype_label.show()
        else:
            self._subtype_label.hide()
        
        # 置信度
        confidence_pct = confidence * 100
        if confidence >= CONFIDENCE_HIGH_THRESHOLD:
            conf_color = COLOR_SUCCESS
            conf_text = self._get_text("topology.confidence_high", "高置信度")
        elif confidence >= CONFIDENCE_MEDIUM_THRESHOLD:
            conf_color = COLOR_WARNING
            conf_text = self._get_text("topology.confidence_medium", "中等置信度")
        else:
            conf_color = COLOR_TEXT_SECONDARY
            conf_text = self._get_text("topology.confidence_low", "低置信度")
        
        self._confidence_label.setText(f"{conf_text}: {confidence_pct:.0f}%")
        self._confidence_label.setStyleSheet(f"""
            color: {conf_color};
            font-size: {FONT_SIZE_SMALL}px;
        """)
    
    def clear(self):
        """清空显示"""
        self._type_label.clear()
        self._subtype_label.clear()
        self._confidence_label.clear()
    
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


class CriticalNodesPanel(QFrame):
    """
    关键节点面板
    
    显示识别出的关键节点列表
    """
    
    node_clicked = pyqtSignal(str)  # 发出节点名称
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("criticalNodesPanel")
        
        self._node_labels: List[QLabel] = []
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_SMALL)
        
        # 标题
        self._title = QLabel(self._get_text("topology.critical_nodes", "关键节点"))
        self._title.setObjectName("panelTitle")
        layout.addWidget(self._title)
        
        # 节点列表容器
        self._nodes_container = QWidget()
        self._nodes_layout = QVBoxLayout(self._nodes_container)
        self._nodes_layout.setContentsMargins(0, 0, 0, 0)
        self._nodes_layout.setSpacing(SPACING_SMALL)
        layout.addWidget(self._nodes_container)
        
        # 空状态提示
        self._empty_label = QLabel(self._get_text("topology.no_critical_nodes", "无关键节点"))
        self._empty_label.setObjectName("emptyLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_label)
        self._empty_label.hide()
        
        layout.addStretch(1)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #criticalNodesPanel {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #panelTitle {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
                font-weight: bold;
            }}
            
            .nodeLabel {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_PRIMARY};
                padding: 4px 8px;
                border-radius: {BORDER_RADIUS_NORMAL}px;
                font-size: {FONT_SIZE_SMALL}px;
                font-family: monospace;
            }}
            
            .nodeLabel:hover {{
                background-color: {COLOR_ACCENT_LIGHT};
                cursor: pointer;
            }}
            
            #emptyLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
        """)
    
    def set_nodes(self, nodes: List[str]):
        """设置关键节点列表"""
        # 清除旧标签
        for label in self._node_labels:
            label.deleteLater()
        self._node_labels.clear()
        
        if not nodes:
            self._nodes_container.hide()
            self._empty_label.show()
            return
        
        self._empty_label.hide()
        self._nodes_container.show()
        
        for node in nodes:
            label = QLabel(node)
            label.setProperty("class", "nodeLabel")
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            label.mousePressEvent = lambda e, n=node: self.node_clicked.emit(n)
            self._nodes_layout.addWidget(label)
            self._node_labels.append(label)
    
    def clear(self):
        """清空显示"""
        for label in self._node_labels:
            label.deleteLater()
        self._node_labels.clear()
        self._nodes_container.hide()
        self._empty_label.show()
    
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
        self._title.setText(self._get_text("topology.critical_nodes", "关键节点"))
        self._empty_label.setText(self._get_text("topology.no_critical_nodes", "无关键节点"))


class RecommendedAnalysesPanel(QFrame):
    """
    推荐分析面板
    
    显示推荐的分析类型列表，带复选框
    """
    
    apply_config_requested = pyqtSignal(list)  # 发出选中的分析类型列表
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("recommendedAnalysesPanel")
        
        self._checkboxes: Dict[str, QCheckBox] = {}
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_SMALL)
        
        # 标题
        self._title = QLabel(self._get_text("topology.recommended_analyses", "推荐分析"))
        self._title.setObjectName("panelTitle")
        layout.addWidget(self._title)
        
        # 复选框容器
        self._checkbox_container = QWidget()
        self._checkbox_layout = QVBoxLayout(self._checkbox_container)
        self._checkbox_layout.setContentsMargins(0, 0, 0, 0)
        self._checkbox_layout.setSpacing(SPACING_SMALL)
        layout.addWidget(self._checkbox_container)
        
        layout.addStretch(1)
        
        # 应用按钮
        self._apply_btn = QPushButton()
        self._apply_btn.setObjectName("applyBtn")
        self._apply_btn.clicked.connect(self._on_apply_clicked)
        layout.addWidget(self._apply_btn)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #recommendedAnalysesPanel {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #panelTitle {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
                font-weight: bold;
            }}
            
            QCheckBox {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_SMALL}px;
                spacing: 8px;
            }}
            
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
            }}
            
            #applyBtn {{
                background-color: {COLOR_ACCENT};
                color: white;
                border: none;
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 8px 16px;
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #applyBtn:hover {{
                background-color: {COLOR_ACCENT};
                opacity: 0.9;
            }}
            
            #applyBtn:disabled {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_SECONDARY};
            }}
        """)
    
    def set_analyses(self, analyses: List[str]):
        """设置推荐分析列表"""
        # 清除旧复选框
        for cb in self._checkboxes.values():
            cb.deleteLater()
        self._checkboxes.clear()
        
        # 分析类型显示名称
        analysis_names = {
            "ac": "AC 小信号分析",
            "dc": "DC 扫描分析",
            "tran": "瞬态分析",
            "noise": "噪声分析",
            "op": "工作点分析",
            "tf": "传递函数分析",
            "sens": "敏感度分析",
        }
        
        for analysis in analyses:
            display_name = analysis_names.get(analysis, analysis.upper())
            cb = QCheckBox(display_name)
            cb.setChecked(True)  # 默认选中
            self._checkbox_layout.addWidget(cb)
            self._checkboxes[analysis] = cb
        
        self._apply_btn.setEnabled(bool(analyses))
    
    def get_selected_analyses(self) -> List[str]:
        """获取选中的分析类型"""
        return [
            analysis for analysis, cb in self._checkboxes.items()
            if cb.isChecked()
        ]
    
    def _on_apply_clicked(self):
        """处理应用按钮点击"""
        selected = self.get_selected_analyses()
        if selected:
            self.apply_config_requested.emit(selected)
    
    def clear(self):
        """清空显示"""
        for cb in self._checkboxes.values():
            cb.deleteLater()
        self._checkboxes.clear()
        self._apply_btn.setEnabled(False)
    
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
        self._title.setText(self._get_text("topology.recommended_analyses", "推荐分析"))
        self._apply_btn.setText(self._get_text("topology.apply_config", "应用推荐配置"))



class KeyMetricsPanel(QFrame):
    """
    关键指标面板
    
    显示该拓扑类型的关键性能指标
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("keyMetricsPanel")
        
        self._metric_labels: List[QLabel] = []
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_SMALL)
        
        # 标题
        self._title = QLabel(self._get_text("topology.key_metrics", "关键指标"))
        self._title.setObjectName("panelTitle")
        layout.addWidget(self._title)
        
        # 指标列表容器（使用流式布局）
        self._metrics_container = QWidget()
        self._metrics_layout = QHBoxLayout(self._metrics_container)
        self._metrics_layout.setContentsMargins(0, 0, 0, 0)
        self._metrics_layout.setSpacing(SPACING_SMALL)
        layout.addWidget(self._metrics_container)
        
        layout.addStretch(1)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #keyMetricsPanel {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #panelTitle {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
                font-weight: bold;
            }}
            
            .metricTag {{
                background-color: {COLOR_ACCENT_LIGHT};
                color: {COLOR_ACCENT};
                padding: 2px 8px;
                border-radius: 10px;
                font-size: {FONT_SIZE_SMALL}px;
            }}
        """)
    
    def set_metrics(self, metrics: List[str]):
        """设置关键指标列表"""
        # 清除旧标签
        for label in self._metric_labels:
            label.deleteLater()
        self._metric_labels.clear()
        
        # 指标显示名称
        metric_names = {
            "gain": "增益",
            "bandwidth": "带宽",
            "gbw": "增益带宽积",
            "phase_margin": "相位裕度",
            "gain_margin": "增益裕度",
            "input_impedance": "输入阻抗",
            "output_impedance": "输出阻抗",
            "slew_rate": "压摆率",
            "cmrr": "CMRR",
            "psrr": "PSRR",
            "noise": "噪声",
            "cutoff_frequency": "截止频率",
            "passband_gain": "通带增益",
            "stopband_attenuation": "阻带衰减",
            "quality_factor": "品质因数",
            "efficiency": "效率",
            "load_regulation": "负载调整率",
            "line_regulation": "线性调整率",
            "frequency": "频率",
            "phase_noise": "相位噪声",
            "thd": "THD",
            "snr": "SNR",
        }
        
        for metric in metrics[:8]:  # 最多显示8个
            display_name = metric_names.get(metric, metric)
            label = QLabel(display_name)
            label.setProperty("class", "metricTag")
            self._metrics_layout.addWidget(label)
            self._metric_labels.append(label)
        
        self._metrics_layout.addStretch(1)
    
    def clear(self):
        """清空显示"""
        for label in self._metric_labels:
            label.deleteLater()
        self._metric_labels.clear()
    
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
        self._title.setText(self._get_text("topology.key_metrics", "关键指标"))


class TopologyInfoPanel(QWidget):
    """
    拓扑识别信息面板
    
    展示电路拓扑识别结果，提供推荐配置应用功能。
    
    Signals:
        apply_config_requested: 请求应用推荐配置，携带分析类型列表
        node_clicked: 点击关键节点，携带节点名称
    """
    
    apply_config_requested = pyqtSignal(list)
    node_clicked = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # 数据
        self._topology_result: Optional[Any] = None
        
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
        main_layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        main_layout.setSpacing(SPACING_NORMAL)
        
        # 滚动区域
        scroll_area = QScrollArea()
        scroll_area.setObjectName("topologyScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        
        # 内容容器
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(SPACING_NORMAL)
        
        # 拓扑类型卡片
        self._type_card = TopologyTypeCard()
        content_layout.addWidget(self._type_card)
        
        # 关键指标面板
        self._key_metrics_panel = KeyMetricsPanel()
        content_layout.addWidget(self._key_metrics_panel)
        
        # 关键节点面板
        self._critical_nodes_panel = CriticalNodesPanel()
        content_layout.addWidget(self._critical_nodes_panel)
        
        # 推荐分析面板
        self._recommended_panel = RecommendedAnalysesPanel()
        content_layout.addWidget(self._recommended_panel)
        
        content_layout.addStretch(1)
        
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area, 1)
        
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
            TopologyInfoPanel {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #topologyScrollArea {{
                background-color: {COLOR_BG_PRIMARY};
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
        self._recommended_panel.apply_config_requested.connect(
            self.apply_config_requested.emit
        )
        self._critical_nodes_panel.node_clicked.connect(
            self.node_clicked.emit
        )
    
    def _subscribe_events(self):
        """订阅事件"""
        event_bus = self._get_event_bus()
        if not event_bus:
            return
        
        from shared.event_types import EVENT_TOPOLOGY_DETECTED, EVENT_LANGUAGE_CHANGED
        
        subscriptions = [
            (EVENT_TOPOLOGY_DETECTED, self._on_topology_detected),
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
    
    def update_topology(self, topology_result: Any):
        """
        更新拓扑识别结果显示
        
        Args:
            topology_result: TopologyResult 对象
        """
        self._topology_result = topology_result
        
        if topology_result is None:
            self._show_empty_state()
            return
        
        self._show_content_state()
        
        # 更新拓扑类型卡片
        topology_type = getattr(topology_result, 'topology_type', 'unknown')
        sub_type = getattr(topology_result, 'sub_type', '')
        confidence = getattr(topology_result, 'confidence', 0.0)
        self._type_card.set_topology(topology_type, sub_type, confidence)
        
        # 更新关键指标
        key_metrics = getattr(topology_result, 'key_metrics', [])
        self._key_metrics_panel.set_metrics(key_metrics)
        
        # 更新关键节点
        critical_nodes = getattr(topology_result, 'critical_nodes', [])
        self._critical_nodes_panel.set_nodes(critical_nodes)
        
        # 更新推荐分析
        recommended_analyses = getattr(topology_result, 'recommended_analyses', [])
        self._recommended_panel.set_analyses(recommended_analyses)
    
    def show_topology_details(self):
        """显示详细的拓扑分析信息"""
        if self._topology_result is None:
            return
        
        # 可以弹出详情对话框，这里暂时只记录日志
        self._logger.info(f"拓扑详情: {self._topology_result}")
    
    def apply_recommended_config(self):
        """应用推荐的仿真配置"""
        selected = self._recommended_panel.get_selected_analyses()
        if selected:
            self.apply_config_requested.emit(selected)
    
    def clear(self):
        """清空显示"""
        self._topology_result = None
        self._type_card.clear()
        self._key_metrics_panel.clear()
        self._critical_nodes_panel.clear()
        self._recommended_panel.clear()
        self._show_empty_state()
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _show_empty_state(self):
        """显示空状态"""
        self._empty_widget.show()
        self._type_card.hide()
        self._key_metrics_panel.hide()
        self._critical_nodes_panel.hide()
        self._recommended_panel.hide()
    
    def _show_content_state(self):
        """显示内容状态"""
        self._empty_widget.hide()
        self._type_card.show()
        self._key_metrics_panel.show()
        self._critical_nodes_panel.show()
        self._recommended_panel.show()
    
    def _on_topology_detected(self, event_data: Dict[str, Any]):
        """处理拓扑识别完成事件"""
        topology_result = event_data.get("topology_result")
        if topology_result:
            self.update_topology(topology_result)
    
    def _on_language_changed(self, event_data: Dict[str, Any]):
        """处理语言变更事件"""
        self.retranslate_ui()
    
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
            "topology.no_result",
            "暂无拓扑识别结果"
        ))
        self._type_card.retranslate_ui()
        self._key_metrics_panel.retranslate_ui()
        self._critical_nodes_panel.retranslate_ui()
        self._recommended_panel.retranslate_ui()
    
    def closeEvent(self, event):
        """关闭事件"""
        self._unsubscribe_events()
        super().closeEvent(event)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "TopologyInfoPanel",
    "TopologyTypeCard",
    "CriticalNodesPanel",
    "RecommendedAnalysesPanel",
    "KeyMetricsPanel",
]
