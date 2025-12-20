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
from presentation.core.panel_registry import PanelRegistry, PANEL_DEFINITIONS

__all__ = [
    "BaseViewModel",
    "PanelManager",
    "PanelRegion",
    "PanelRegistry",
    "PANEL_DEFINITIONS",
]
