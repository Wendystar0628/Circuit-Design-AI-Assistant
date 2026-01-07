# DiagnosisPanel - Convergence Diagnosis Panel
"""
收敛诊断面板

职责：
- 展示仿真收敛问题诊断结果
- 显示问题类型、严重程度、受影响节点
- 提供建议修复方案列表
- 支持应用自动修复和手动修复指南

设计原则：
- 使用 QWidget 作为基类
- 订阅 EVENT_CONVERGENCE_DIAGNOSED 事件自动更新
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
    QSizePolicy,
    QScrollArea,
    QTextEdit,
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

SEVERITY_COLORS = {
    "low": COLOR_SUCCESS,
    "medium": COLOR_WARNING,
    "high": COLOR_ERROR,
    "critical": "#B71C1C",  # 深红色
}

SEVERITY_NAMES = {
    "low": "低",
    "medium": "中",
    "high": "高",
    "critical": "严重",
}

ISSUE_TYPE_NAMES = {
    "dc_convergence": "DC 工作点收敛失败",
    "tran_convergence": "瞬态分析收敛失败",
    "floating_node": "浮空节点",
    "model_problem": "模型问题",
    "unknown": "未知问题",
}

ISSUE_TYPE_ICONS = {
    "dc_convergence": "⚡",
    "tran_convergence": "📈",
    "floating_node": "🔌",
    "model_problem": "📦",
    "unknown": "❓",
}


class IssueTypeCard(QFrame):
    """
    问题类型卡片
    
    显示问题类型和严重程度
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("issueTypeCard")
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_NORMAL)
        
        # 左侧：图标
        self._icon_label = QLabel()
        self._icon_label.setObjectName("issueIcon")
        self._icon_label.setFixedSize(48, 48)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon_label)
        
        # 中间：问题类型和描述
        info_container = QWidget()
        info_layout = QVBoxLayout(info_container)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(SPACING_SMALL)
        
        self._type_label = QLabel()
        self._type_label.setObjectName("issueTypeLabel")
        info_layout.addWidget(self._type_label)
        
        self._description_label = QLabel()
        self._description_label.setObjectName("issueDescLabel")
        self._description_label.setWordWrap(True)
        info_layout.addWidget(self._description_label)
        
        layout.addWidget(info_container, 1)
        
        # 右侧：严重程度标签
        self._severity_label = QLabel()
        self._severity_label.setObjectName("severityLabel")
        self._severity_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._severity_label.setFixedWidth(60)
        layout.addWidget(self._severity_label)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #issueTypeCard {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #issueIcon {{
                font-size: 32px;
            }}
            
            #issueTypeLabel {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_TITLE}px;
                font-weight: bold;
            }}
            
            #issueDescLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #severityLabel {{
                padding: 4px 8px;
                border-radius: {BORDER_RADIUS_NORMAL}px;
                font-size: {FONT_SIZE_SMALL}px;
                font-weight: bold;
            }}
        """)
    
    def set_issue(self, issue_type: str, severity: str, summary: str = ""):
        """
        设置问题信息
        
        Args:
            issue_type: 问题类型
            severity: 严重程度
            summary: 摘要描述
        """
        # 图标
        icon = ISSUE_TYPE_ICONS.get(issue_type, "❓")
        self._icon_label.setText(icon)
        
        # 问题类型
        type_name = ISSUE_TYPE_NAMES.get(issue_type, issue_type)
        self._type_label.setText(type_name)
        
        # 描述
        if summary:
            self._description_label.setText(summary)
            self._description_label.show()
        else:
            self._description_label.hide()
        
        # 严重程度
        severity_name = SEVERITY_NAMES.get(severity, severity)
        severity_color = SEVERITY_COLORS.get(severity, COLOR_TEXT_SECONDARY)
        self._severity_label.setText(severity_name)
        self._severity_label.setStyleSheet(f"""
            background-color: {severity_color};
            color: white;
            padding: 4px 8px;
            border-radius: {BORDER_RADIUS_NORMAL}px;
            font-size: {FONT_SIZE_SMALL}px;
            font-weight: bold;
        """)
    
    def clear(self):
        """清空显示"""
        self._icon_label.clear()
        self._type_label.clear()
        self._description_label.clear()
        self._severity_label.clear()
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        pass


class AffectedNodesPanel(QFrame):
    """
    受影响节点面板
    
    显示受影响的节点列表
    """
    
    node_clicked = pyqtSignal(str)  # 发出节点名称
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("affectedNodesPanel")
        
        self._node_labels: List[QLabel] = []
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_SMALL)
        
        # 标题
        self._title = QLabel(self._get_text("diagnosis.affected_nodes", "受影响节点"))
        self._title.setObjectName("panelTitle")
        layout.addWidget(self._title)
        
        # 节点列表容器
        self._nodes_container = QWidget()
        self._nodes_layout = QHBoxLayout(self._nodes_container)
        self._nodes_layout.setContentsMargins(0, 0, 0, 0)
        self._nodes_layout.setSpacing(SPACING_SMALL)
        layout.addWidget(self._nodes_container)
        
        # 空状态提示
        self._empty_label = QLabel(self._get_text("diagnosis.no_affected_nodes", "无受影响节点"))
        self._empty_label.setObjectName("emptyLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_label)
        self._empty_label.hide()
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #affectedNodesPanel {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #panelTitle {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
                font-weight: bold;
            }}
            
            .nodeTag {{
                background-color: #FFEBEE;
                color: {COLOR_ERROR};
                padding: 2px 8px;
                border-radius: 10px;
                font-size: {FONT_SIZE_SMALL}px;
                font-family: monospace;
            }}
            
            .nodeTag:hover {{
                background-color: {COLOR_ERROR};
                color: white;
                cursor: pointer;
            }}
            
            #emptyLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
        """)
    
    def set_nodes(self, nodes: List[str]):
        """设置受影响节点列表"""
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
        
        for node in nodes[:10]:  # 最多显示10个
            label = QLabel(node)
            label.setProperty("class", "nodeTag")
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            label.mousePressEvent = lambda e, n=node: self.node_clicked.emit(n)
            self._nodes_layout.addWidget(label)
            self._node_labels.append(label)
        
        if len(nodes) > 10:
            more_label = QLabel(f"+{len(nodes) - 10}")
            more_label.setProperty("class", "nodeTag")
            self._nodes_layout.addWidget(more_label)
            self._node_labels.append(more_label)
        
        self._nodes_layout.addStretch(1)
    
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
        self._title.setText(self._get_text("diagnosis.affected_nodes", "受影响节点"))
        self._empty_label.setText(self._get_text("diagnosis.no_affected_nodes", "无受影响节点"))


class SuggestedFixCard(QFrame):
    """
    建议修复方案卡片
    
    显示单个修复建议
    """
    
    apply_clicked = pyqtSignal(dict)  # 发出修复参数
    
    def __init__(self, fix_data: Dict[str, Any], index: int, parent=None):
        super().__init__(parent)
        
        self.setObjectName(f"suggestedFixCard_{index}")
        self._fix_data = fix_data
        self._index = index
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        layout.setSpacing(SPACING_SMALL)
        
        # 顶部：序号和描述
        header_layout = QHBoxLayout()
        header_layout.setSpacing(SPACING_SMALL)
        
        # 序号
        index_label = QLabel(f"{self._index + 1}.")
        index_label.setObjectName("fixIndex")
        index_label.setFixedWidth(24)
        header_layout.addWidget(index_label)
        
        # 描述
        description = self._fix_data.get("description", "")
        desc_label = QLabel(description)
        desc_label.setObjectName("fixDescription")
        desc_label.setWordWrap(True)
        header_layout.addWidget(desc_label, 1)
        
        layout.addLayout(header_layout)
        
        # SPICE 代码（如果有）
        parameters = self._fix_data.get("parameters", {})
        spice_line = parameters.get("spice_line") or parameters.get("spice_options")
        if spice_line:
            code_label = QLabel(spice_line)
            code_label.setObjectName("spiceCode")
            code_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(code_label)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            QFrame[objectName^="suggestedFixCard"] {{
                background-color: {COLOR_BG_SECONDARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #fixIndex {{
                color: {COLOR_ACCENT};
                font-size: {FONT_SIZE_NORMAL}px;
                font-weight: bold;
            }}
            
            #fixDescription {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #spiceCode {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_PRIMARY};
                padding: 4px 8px;
                border-radius: {BORDER_RADIUS_NORMAL}px;
                font-size: {FONT_SIZE_SMALL}px;
                font-family: monospace;
            }}
        """)
    
    def get_fix_data(self) -> Dict[str, Any]:
        """获取修复数据"""
        return self._fix_data



class SuggestedFixesPanel(QFrame):
    """
    建议修复方案面板
    
    显示所有修复建议列表
    """
    
    fix_selected = pyqtSignal(dict)  # 发出选中的修复方案
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("suggestedFixesPanel")
        
        self._fix_cards: List[SuggestedFixCard] = []
        
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_SMALL)
        
        # 标题
        self._title = QLabel(self._get_text("diagnosis.suggested_fixes", "建议修复方案"))
        self._title.setObjectName("panelTitle")
        layout.addWidget(self._title)
        
        # 修复方案列表容器
        self._fixes_container = QWidget()
        self._fixes_layout = QVBoxLayout(self._fixes_container)
        self._fixes_layout.setContentsMargins(0, 0, 0, 0)
        self._fixes_layout.setSpacing(SPACING_SMALL)
        layout.addWidget(self._fixes_container)
        
        # 空状态提示
        self._empty_label = QLabel(self._get_text("diagnosis.no_fixes", "无修复建议"))
        self._empty_label.setObjectName("emptyLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_label)
        self._empty_label.hide()
        
        layout.addStretch(1)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #suggestedFixesPanel {{
                background-color: {COLOR_BG_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            
            #panelTitle {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_NORMAL}px;
                font-weight: bold;
            }}
            
            #emptyLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
        """)
    
    def set_fixes(self, fixes: List[Any]):
        """
        设置修复建议列表
        
        Args:
            fixes: SuggestedFix 对象列表或字典列表
        """
        # 清除旧卡片
        for card in self._fix_cards:
            card.deleteLater()
        self._fix_cards.clear()
        
        if not fixes:
            self._fixes_container.hide()
            self._empty_label.show()
            return
        
        self._empty_label.hide()
        self._fixes_container.show()
        
        for idx, fix in enumerate(fixes):
            # 支持 SuggestedFix 对象和字典
            if hasattr(fix, 'to_dict'):
                fix_data = fix.to_dict()
            elif isinstance(fix, dict):
                fix_data = fix
            else:
                fix_data = {
                    "description": str(fix),
                    "action_type": "unknown",
                    "parameters": {},
                }
            
            card = SuggestedFixCard(fix_data, idx)
            self._fixes_layout.addWidget(card)
            self._fix_cards.append(card)
    
    def clear(self):
        """清空显示"""
        for card in self._fix_cards:
            card.deleteLater()
        self._fix_cards.clear()
        self._fixes_container.hide()
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
        self._title.setText(self._get_text("diagnosis.suggested_fixes", "建议修复方案"))
        self._empty_label.setText(self._get_text("diagnosis.no_fixes", "无修复建议"))


class DiagnosisPanel(QWidget):
    """
    收敛诊断面板
    
    展示仿真收敛问题诊断结果，提供自动修复功能。
    
    Signals:
        auto_fix_requested: 请求应用自动修复
        manual_guide_requested: 请求显示手动修复指南
        node_clicked: 点击问题节点，携带节点名称
    """
    
    auto_fix_requested = pyqtSignal()
    manual_guide_requested = pyqtSignal()
    node_clicked = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # 数据
        self._diagnosis: Optional[Any] = None
        
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
        scroll_area.setObjectName("diagnosisScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        
        # 内容容器
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(SPACING_NORMAL)
        
        # 问题类型卡片
        self._issue_card = IssueTypeCard()
        content_layout.addWidget(self._issue_card)
        
        # 受影响节点面板
        self._affected_nodes_panel = AffectedNodesPanel()
        content_layout.addWidget(self._affected_nodes_panel)
        
        # 建议修复方案面板
        self._fixes_panel = SuggestedFixesPanel()
        content_layout.addWidget(self._fixes_panel)
        
        content_layout.addStretch(1)
        
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area, 1)
        
        # 底部操作栏
        self._action_bar = QFrame()
        self._action_bar.setObjectName("actionBar")
        self._action_bar.setFixedHeight(48)
        action_layout = QHBoxLayout(self._action_bar)
        action_layout.setContentsMargins(SPACING_NORMAL, SPACING_SMALL, SPACING_NORMAL, SPACING_SMALL)
        action_layout.setSpacing(SPACING_NORMAL)
        
        action_layout.addStretch(1)
        
        # 手动修复指南按钮
        self._manual_btn = QPushButton()
        self._manual_btn.setObjectName("manualBtn")
        self._manual_btn.clicked.connect(self.manual_guide_requested.emit)
        action_layout.addWidget(self._manual_btn)
        
        # 应用自动修复按钮
        self._auto_fix_btn = QPushButton()
        self._auto_fix_btn.setObjectName("autoFixBtn")
        self._auto_fix_btn.clicked.connect(self.auto_fix_requested.emit)
        action_layout.addWidget(self._auto_fix_btn)
        
        main_layout.addWidget(self._action_bar)
        
        # 空状态提示
        self._empty_widget = QFrame()
        self._empty_widget.setObjectName("emptyWidget")
        empty_layout = QVBoxLayout(self._empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 空状态图标
        empty_icon = QLabel("✓")
        empty_icon.setObjectName("emptyIcon")
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_icon)
        
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
            DiagnosisPanel {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #diagnosisScrollArea {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #actionBar {{
                background-color: {COLOR_BG_SECONDARY};
                border-top: 1px solid {COLOR_BORDER};
            }}
            
            #manualBtn {{
                background-color: transparent;
                color: {COLOR_ACCENT};
                border: 1px solid {COLOR_ACCENT};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 8px 16px;
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #manualBtn:hover {{
                background-color: {COLOR_ACCENT_LIGHT};
            }}
            
            #autoFixBtn {{
                background-color: {COLOR_ACCENT};
                color: white;
                border: none;
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 8px 16px;
                font-size: {FONT_SIZE_NORMAL}px;
            }}
            
            #autoFixBtn:hover {{
                background-color: {COLOR_ACCENT};
                opacity: 0.9;
            }}
            
            #autoFixBtn:disabled {{
                background-color: {COLOR_BG_TERTIARY};
                color: {COLOR_TEXT_SECONDARY};
            }}
            
            #emptyWidget {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            
            #emptyIcon {{
                color: {COLOR_SUCCESS};
                font-size: 48px;
            }}
            
            #emptyLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_NORMAL}px;
            }}
        """)
    
    def _connect_signals(self):
        """连接信号"""
        self._affected_nodes_panel.node_clicked.connect(self.node_clicked.emit)
    
    def _subscribe_events(self):
        """订阅事件"""
        event_bus = self._get_event_bus()
        if not event_bus:
            return
        
        from shared.event_types import EVENT_CONVERGENCE_DIAGNOSED, EVENT_LANGUAGE_CHANGED
        
        subscriptions = [
            (EVENT_CONVERGENCE_DIAGNOSED, self._on_diagnosis_complete),
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
    
    def update_diagnosis(self, diagnosis: Any):
        """
        更新诊断结果显示
        
        Args:
            diagnosis: ConvergenceDiagnosis 对象
        """
        self._diagnosis = diagnosis
        
        if diagnosis is None:
            self._show_empty_state()
            return
        
        self._show_content_state()
        
        # 更新问题类型卡片
        issue_type = getattr(diagnosis, 'issue_type', 'unknown')
        severity = getattr(diagnosis, 'severity', 'medium')
        summary = getattr(diagnosis, 'summary', '')
        self._issue_card.set_issue(issue_type, severity, summary)
        
        # 更新受影响节点
        affected_nodes = getattr(diagnosis, 'affected_nodes', [])
        self._affected_nodes_panel.set_nodes(affected_nodes)
        
        # 更新修复建议
        suggested_fixes = getattr(diagnosis, 'suggested_fixes', [])
        self._fixes_panel.set_fixes(suggested_fixes)
        
        # 更新自动修复按钮状态
        auto_fix_available = getattr(diagnosis, 'auto_fix_available', False)
        self._auto_fix_btn.setEnabled(auto_fix_available)
        if not auto_fix_available:
            self._auto_fix_btn.setToolTip(self._get_text(
                "diagnosis.auto_fix_unavailable",
                "此问题需要手动修复"
            ))
        else:
            self._auto_fix_btn.setToolTip("")
    
    def apply_auto_fix(self):
        """应用自动修复"""
        if self._diagnosis is None:
            return
        
        auto_fix_available = getattr(self._diagnosis, 'auto_fix_available', False)
        if not auto_fix_available:
            self._logger.warning("自动修复不可用")
            return
        
        self.auto_fix_requested.emit()
    
    def show_manual_fix_guide(self):
        """显示手动修复指南"""
        self.manual_guide_requested.emit()
    
    def jump_to_problem_node(self, node_name: str):
        """
        跳转到问题节点
        
        Args:
            node_name: 节点名称
        """
        self.node_clicked.emit(node_name)
    
    def clear(self):
        """清空显示"""
        self._diagnosis = None
        self._issue_card.clear()
        self._affected_nodes_panel.clear()
        self._fixes_panel.clear()
        self._show_empty_state()
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _show_empty_state(self):
        """显示空状态（无问题）"""
        self._empty_widget.show()
        self._issue_card.hide()
        self._affected_nodes_panel.hide()
        self._fixes_panel.hide()
        self._action_bar.hide()
    
    def _show_content_state(self):
        """显示内容状态"""
        self._empty_widget.hide()
        self._issue_card.show()
        self._affected_nodes_panel.show()
        self._fixes_panel.show()
        self._action_bar.show()
    
    def _on_diagnosis_complete(self, event_data: Dict[str, Any]):
        """处理诊断完成事件"""
        diagnosis = event_data.get("diagnosis")
        if diagnosis:
            self.update_diagnosis(diagnosis)
    
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
            "diagnosis.no_issues",
            "仿真正常，无收敛问题"
        ))
        self._manual_btn.setText(self._get_text(
            "diagnosis.manual_guide",
            "手动修复指南"
        ))
        self._auto_fix_btn.setText(self._get_text(
            "diagnosis.apply_auto_fix",
            "应用自动修复"
        ))
        self._issue_card.retranslate_ui()
        self._affected_nodes_panel.retranslate_ui()
        self._fixes_panel.retranslate_ui()
    
    def closeEvent(self, event):
        """关闭事件"""
        self._unsubscribe_events()
        super().closeEvent(event)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "DiagnosisPanel",
    "IssueTypeCard",
    "AffectedNodesPanel",
    "SuggestedFixesPanel",
    "SuggestedFixCard",
]
