# Presentation Core Module
"""
UI层核心基础设施

包含：
- BaseViewModel: ViewModel 基类
- PanelManager: 面板管理器
- TabController: 标签页控制器
- UIEventBridge: UI事件桥接器
- PanelRegistry: 面板注册表
"""

from presentation.core.base_view_model import BaseViewModel
from presentation.core.panel_manager import PanelManager, PanelRegion
from presentation.core.panel_registry import PanelRegistry, PanelDefinition, PANEL_DEFINITIONS
from presentation.core.tab_controller import (
    TabController,
    TabInfo,
    AutoSwitchPolicy,
    TAB_CONVERSATION,
    TAB_INFO,
    TAB_COMPONENT,
)
from presentation.core.ui_event_bridge import (
    UIEventBridge,
    ensure_main_thread,
    CommonEventBridges,
)

__all__ = [
    # ViewModel
    "BaseViewModel",
    # Panel Management
    "PanelManager",
    "PanelRegion",
    "PanelRegistry",
    "PanelDefinition",
    "PANEL_DEFINITIONS",
    # Tab Controller
    "TabController",
    "TabInfo",
    "AutoSwitchPolicy",
    "TAB_CONVERSATION",
    "TAB_INFO",
    "TAB_COMPONENT",
    # UI Event Bridge
    "UIEventBridge",
    "ensure_main_thread",
    "CommonEventBridges",
]
