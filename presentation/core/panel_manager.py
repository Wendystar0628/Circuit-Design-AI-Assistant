# Panel Manager - 面板管理器
"""
面板管理器 - 统一管理所有面板的生命周期、可见性、布局状态

职责：
- 注册面板到指定区域
- 管理面板显示/隐藏
- 保存/恢复布局状态
- 发布面板状态变更事件

设计原则：
- 统一面板管理：所有面板通过 PanelManager 统一管理
- 事件驱动：面板状态变更时发布事件
- 布局持久化：保存到配置文件

被调用方：main_window.py、menu_manager.py（视图菜单）
"""

from enum import Enum
from typing import Optional, Dict, Any, List
from PyQt6.QtWidgets import QWidget


class PanelRegion(Enum):
    """面板区域定义"""
    LEFT = "left"       # 左栏（文件浏览器）
    CENTER = "center"   # 中栏（代码编辑器）
    RIGHT = "right"     # 右栏（对话/信息/元器件标签页）
    BOTTOM = "bottom"   # 下栏（仿真结果）


class PanelManager:
    """
    面板管理器
    
    统一管理所有面板的生命周期、可见性、布局状态。
    """
    
    def __init__(self):
        """初始化面板管理器"""
        # 面板注册表：panel_id -> (panel_instance, region)
        self._panels: Dict[str, tuple] = {}
        
        # 延迟获取的服务
        self._event_bus = None
        self._config_manager = None
        self._logger = None
    
    # ============================================================
    # 延迟获取服务
    # ============================================================
    
    @property
    def event_bus(self):
        """延迟获取 EventBus"""
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus
    
    @property
    def config_manager(self):
        """延迟获取 ConfigManager"""
        if self._config_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CONFIG_MANAGER
                self._config_manager = ServiceLocator.get_optional(SVC_CONFIG_MANAGER)
            except Exception:
                pass
        return self._config_manager
    
    @property
    def logger(self):
        """延迟获取 Logger"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("panel_manager")
            except Exception:
                pass
        return self._logger
    
    # ============================================================
    # 面板注册
    # ============================================================
    
    def register_panel(
        self, 
        panel_id: str, 
        panel_instance: QWidget, 
        region: PanelRegion
    ) -> None:
        """
        注册面板到指定区域
        
        Args:
            panel_id: 面板唯一标识
            panel_instance: 面板实例
            region: 面板所属区域
        """
        self._panels[panel_id] = (panel_instance, region)
        
        if self.logger:
            self.logger.debug(f"Panel registered: {panel_id} in {region.value}")
    
    def unregister_panel(self, panel_id: str) -> None:
        """
        注销面板
        
        Args:
            panel_id: 面板唯一标识
        """
        if panel_id in self._panels:
            del self._panels[panel_id]
            
            if self.logger:
                self.logger.debug(f"Panel unregistered: {panel_id}")
    
    # ============================================================
    # 面板访问
    # ============================================================
    
    def get_panel(self, panel_id: str) -> Optional[QWidget]:
        """
        获取面板实例
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            面板实例，不存在则返回 None
        """
        entry = self._panels.get(panel_id)
        return entry[0] if entry else None
    
    def get_panel_region(self, panel_id: str) -> Optional[PanelRegion]:
        """
        获取面板所属区域
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            面板区域，不存在则返回 None
        """
        entry = self._panels.get(panel_id)
        return entry[1] if entry else None
    
    def get_all_panels(self) -> Dict[str, QWidget]:
        """
        获取所有面板
        
        Returns:
            面板字典 {panel_id: panel_instance}
        """
        return {pid: entry[0] for pid, entry in self._panels.items()}
    
    def get_visible_panels(self, region: Optional[PanelRegion] = None) -> List[str]:
        """
        获取可见面板列表
        
        Args:
            region: 指定区域，None 表示所有区域
            
        Returns:
            可见面板 ID 列表
        """
        visible = []
        for panel_id, (panel, panel_region) in self._panels.items():
            if region is None or panel_region == region:
                if panel.isVisible():
                    visible.append(panel_id)
        return visible
    
    # ============================================================
    # 面板显示/隐藏
    # ============================================================
    
    def show_panel(self, panel_id: str) -> bool:
        """
        显示面板
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            是否成功
        """
        entry = self._panels.get(panel_id)
        if not entry:
            return False
        
        panel, region = entry
        if not panel.isVisible():
            panel.setVisible(True)
            self._publish_visibility_changed(panel_id, True, region)
        
        return True
    
    def hide_panel(self, panel_id: str) -> bool:
        """
        隐藏面板
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            是否成功
        """
        entry = self._panels.get(panel_id)
        if not entry:
            return False
        
        panel, region = entry
        if panel.isVisible():
            panel.setVisible(False)
            self._publish_visibility_changed(panel_id, False, region)
        
        return True
    
    def toggle_panel(self, panel_id: str) -> bool:
        """
        切换面板可见性
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            切换后的可见性状态
        """
        entry = self._panels.get(panel_id)
        if not entry:
            return False
        
        panel, region = entry
        new_visible = not panel.isVisible()
        panel.setVisible(new_visible)
        self._publish_visibility_changed(panel_id, new_visible, region)
        
        return new_visible
    
    def set_panel_visible(self, panel_id: str, visible: bool) -> bool:
        """
        设置面板可见性
        
        Args:
            panel_id: 面板唯一标识
            visible: 是否可见
            
        Returns:
            是否成功
        """
        if visible:
            return self.show_panel(panel_id)
        else:
            return self.hide_panel(panel_id)
    
    def _publish_visibility_changed(
        self, 
        panel_id: str, 
        visible: bool, 
        region: PanelRegion
    ) -> None:
        """发布面板可见性变更事件"""
        if self.event_bus:
            try:
                from shared.event_types import EVENT_PANEL_VISIBILITY_CHANGED
                self.event_bus.publish(EVENT_PANEL_VISIBILITY_CHANGED, {
                    "panel_id": panel_id,
                    "visible": visible,
                    "region": region.value,
                })
            except Exception:
                pass
    
    # ============================================================
    # 布局状态持久化
    # ============================================================
    
    def save_layout_state(self) -> None:
        """保存布局状态到配置"""
        if not self.config_manager:
            return
        
        # 保存面板可见性
        visibility = {}
        for panel_id, (panel, _) in self._panels.items():
            visibility[panel_id] = panel.isVisible()
        
        self.config_manager.set("panel_visibility", visibility)
        
        if self.logger:
            self.logger.debug("Layout state saved")
    
    def restore_layout_state(self) -> None:
        """从配置恢复布局状态"""
        if not self.config_manager:
            return
        
        visibility = self.config_manager.get("panel_visibility")
        if not visibility or not isinstance(visibility, dict):
            return
        
        for panel_id, visible in visibility.items():
            if panel_id in self._panels:
                self.set_panel_visible(panel_id, bool(visible))
        
        if self.logger:
            self.logger.debug("Layout state restored")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "PanelManager",
    "PanelRegion",
]
