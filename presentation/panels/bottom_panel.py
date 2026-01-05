# BottomPanel - Bottom Panel Container
"""
下栏面板容器

职责：
- 管理下栏的标签页切换
- 协调仿真结果和报告生成两个功能模块
- 响应项目打开/关闭事件

设计原则：
- 使用 QTabWidget 管理标签页
- 当前只包含 SimulationTab，ReportTab 在阶段16实现
- 支持国际化

被调用方：
- main_window.py
"""

import logging
from typing import Optional, List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTabWidget

from presentation.panels.simulation.simulation_tab import SimulationTab
from shared.event_types import (
    EVENT_STATE_PROJECT_OPENED,
    EVENT_STATE_PROJECT_CLOSED,
    EVENT_LANGUAGE_CHANGED,
    EVENT_SIM_COMPLETE,
)


# ============================================================
# 标签页索引常量
# ============================================================

TAB_SIMULATION = 0
TAB_REPORT = 1


class BottomPanel(QWidget):
    """
    下栏面板容器
    
    管理仿真结果和报告生成标签页。
    
    Signals:
        tab_changed: 标签页切换信号，携带新标签页索引
        history_requested: 请求查看历史记录
        settings_requested: 请求打开仿真设置
    """
    
    tab_changed = pyqtSignal(int)
    history_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # EventBus 引用
        self._event_bus = None
        self._subscriptions: List[tuple] = []
        
        # 项目状态
        self._project_root: Optional[str] = None
        
        # 初始化 UI
        self._setup_ui()
        self._connect_signals()
        
        # 订阅事件
        self._subscribe_events()
        
        # 初始化文本
        self.retranslate_ui()
    
    def _setup_ui(self):
        """初始化 UI 组件"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 标签页容器
        self._tab_widget = QTabWidget()
        self._tab_widget.setObjectName("bottomTabWidget")
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        layout.addWidget(self._tab_widget)
        
        # 仿真结果标签页
        self._simulation_tab = SimulationTab()
        self._tab_widget.addTab(self._simulation_tab, "")
        
        # ReportTab 在阶段16实现，此处预留位置
        self._report_tab: Optional[QWidget] = None
    
    def _connect_signals(self):
        """连接信号"""
        # 标签页切换
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
        
        # 仿真标签页信号
        self._simulation_tab.history_requested.connect(self.history_requested.emit)
        self._simulation_tab.settings_requested.connect(self.settings_requested.emit)
    
    def _subscribe_events(self):
        """订阅事件"""
        event_bus = self._get_event_bus()
        if not event_bus:
            return
        
        subscriptions = [
            (EVENT_STATE_PROJECT_OPENED, self._on_project_opened),
            (EVENT_STATE_PROJECT_CLOSED, self._on_project_closed),
            (EVENT_LANGUAGE_CHANGED, self._on_language_changed),
            (EVENT_SIM_COMPLETE, self._on_simulation_complete),
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
    # 事件处理
    # ============================================================
    
    def _on_tab_changed(self, index: int):
        """处理标签页切换"""
        self.tab_changed.emit(index)
    
    def _on_project_opened(self, event_data: dict):
        """处理项目打开事件"""
        data = event_data.get("data", event_data)
        if isinstance(data, dict):
            self._project_root = data.get("path", "")
        else:
            self._project_root = ""
        
        # 传递给仿真标签页
        self._simulation_tab.set_project_root(self._project_root)
        
        self._logger.info(f"BottomPanel: Project opened - {self._project_root}")
    
    def _on_project_closed(self, event_data: dict):
        """处理项目关闭事件"""
        self._project_root = None
        
        # 清空仿真标签页
        self._simulation_tab.clear()
        
        self._logger.info("BottomPanel: Project closed")
    
    def _on_language_changed(self, event_data: dict):
        """处理语言切换事件"""
        self.retranslate_ui()
    
    def _on_simulation_complete(self, event_data: dict):
        """处理仿真完成事件，自动切换到仿真标签页"""
        self.switch_to_simulation()
    
    # ============================================================
    # 公共方法
    # ============================================================
    
    def switch_to_simulation(self):
        """切换到仿真结果标签页"""
        self._tab_widget.setCurrentIndex(TAB_SIMULATION)
    
    def switch_to_report(self):
        """切换到报告生成标签页"""
        if self._report_tab is not None:
            self._tab_widget.setCurrentIndex(TAB_REPORT)
    
    def get_current_tab(self) -> int:
        """获取当前标签页索引"""
        return self._tab_widget.currentIndex()
    
    def get_simulation_tab(self) -> SimulationTab:
        """获取仿真结果标签页"""
        return self._simulation_tab
    
    def add_report_tab(self, report_tab: QWidget):
        """
        添加报告生成标签页（阶段16调用）
        
        Args:
            report_tab: ReportTab 实例
        """
        if self._report_tab is not None:
            self._logger.warning("Report tab already exists")
            return
        
        self._report_tab = report_tab
        self._tab_widget.addTab(
            self._report_tab,
            self._get_text("panel.report", "报告生成")
        )
        
        self._logger.info("Report tab added to BottomPanel")
    
    def refresh(self):
        """刷新当前标签页"""
        current_index = self._tab_widget.currentIndex()
        if current_index == TAB_SIMULATION:
            self._simulation_tab.refresh()
        elif current_index == TAB_REPORT and self._report_tab is not None:
            if hasattr(self._report_tab, "refresh"):
                self._report_tab.refresh()
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        # 仿真标签页标题
        self._tab_widget.setTabText(
            TAB_SIMULATION,
            self._get_text("panel.simulation", "仿真结果")
        )
        
        # 报告标签页标题（如果存在）
        if self._report_tab is not None:
            self._tab_widget.setTabText(
                TAB_REPORT,
                self._get_text("panel.report", "报告生成")
            )
        
        # 子组件国际化
        self._simulation_tab.retranslate_ui()
        
        if self._report_tab is not None and hasattr(self._report_tab, "retranslate_ui"):
            self._report_tab.retranslate_ui()
    
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
        """处理关闭事件"""
        self._unsubscribe_events()
        super().closeEvent(event)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "BottomPanel",
    "TAB_SIMULATION",
    "TAB_REPORT",
]
