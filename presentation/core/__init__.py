# Presentation Core - UI层核心基础设施
"""
UI层核心基础设施模块

包含：
- BaseViewModel: ViewModel 基类
- PanelManager: 面板管理器
- TabController: 标签页控制器
- UIEventBridge: UI事件桥接器
- PanelRegistry: 面板注册表
"""

from presentation.core.base_view_model import BaseViewModel
from presentation.core.panel_manager import PanelManager, PanelRegion
from presentation.core.tab_controller import TabController, TabId, AutoSwitchPolicy
from presentation.core.ui_event_bridge import UIEventBridge
from presentation.core.panel_registry import PanelRegistry, PANEL_DEFINITIONS

__all__ = [
    "BaseViewModel",
    "PanelManager",
    "PanelRegion",
    "TabController",
    "TabId",
    "AutoSwitchPolicy",
    "UIEventBridge",
    "PanelRegistry",
    "PANEL_DEFINITIONS",
]
