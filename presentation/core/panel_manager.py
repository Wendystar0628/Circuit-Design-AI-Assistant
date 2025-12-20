# Panel Manager
"""
面板管理器

职责：
- 统一管理所有面板的生命周期
- 管理面板可见性和布局状态
- 持久化布局配置

设计原则：
- 面板通过 panel_id 唯一标识
- 面板按区域（region）组织
- 布局状态持久化到配置文件

被调用方：
- main_window.py
- menu_manager.py（视图菜单）
"""

from typing import Optional, Dict, List, Any
from enum import Enum
from pathlib import Path
import json

from PyQt6.QtWidgets import QWidget


class PanelRegion(Enum):
    """面板区域定义"""
    LEFT = "left"       # 左栏（文件浏览器）
    CENTER = "center"   # 中栏（代码编辑器）
    RIGHT = "right"     # 右栏（对话/信息/元器件标签页）
    BOTTOM = "bottom"   # 下栏（仿真结果）


class PanelInfo:
    """面板信息"""
    
    def __init__(
        self,
        panel_id: str,
        instance: QWidget,
        region: PanelRegion,
        visible: bool = True,
        title_key: str = "",
        icon_path: str = "",
    ):
        self.panel_id = panel_id
        self.instance = instance
        self.region = region
        self.visible = visible
        self.title_key = title_key
        self.icon_path = icon_path


class PanelManager:
    """
    面板管理器
    
    管理所有面板的注册、可见性、布局状态
    
    使用示例：
        panel_manager = PanelManager()
        panel_manager.register_panel("file_browser", file_browser, PanelRegion.LEFT)
        panel_manager.show_panel("file_browser")
        panel_manager.save_layout_state()
    """
    
    # 布局配置文件名
    LAYOUT_FILE = "layout.json"
    
    def __init__(self):
        # 延迟获取的服务
        self._event_bus = None
        self._config_manager = None
        self._logger = None
        
        # 面板注册表：panel_id -> PanelInfo
        self._panels: Dict[str, PanelInfo] = {}
        
        # 区域到面板的映射：region -> [panel_id, ...]
        self._region_panels: Dict[PanelRegion, List[str]] = {
            region: [] for region in PanelRegion
        }
    
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
        region: PanelRegion,
        visible: bool = True,
        title_key: str = "",
        icon_path: str = "",
    ):
        """
        注册面板到指定区域
        
        Args:
            panel_id: 面板唯一标识
            panel_instance: 面板 QWidget 实例
            region: 面板所属区域
            visible: 初始可见性
            title_key: 面板标题的 i18n key
            icon_path: 面板图标路径
        """
        if panel_id in self._panels:
            if self.logger:
                self.logger.warning(f"Panel '{panel_id}' already registered, replacing")
            self.unregister_panel(panel_id)
        
        panel_info = PanelInfo(
            panel_id=panel_id,
            instance=panel_instance,
            region=region,
            visible=visible,
            title_key=title_key,
            icon_path=icon_path,
        )
        
        self._panels[panel_id] = panel_info
        self._region_panels[region].append(panel_id)
        
        # 设置初始可见性
        panel_instance.setVisible(visible)
        
        if self.logger:
            self.logger.debug(f"Panel '{panel_id}' registered in region {region.value}")
    
    def unregister_panel(self, panel_id: str):
        """
        注销面板
        
        Args:
            panel_id: 面板唯一标识
        """
        if panel_id not in self._panels:
            return
        
        panel_info = self._panels[panel_id]
        
        # 从区域映射中移除
        if panel_id in self._region_panels[panel_info.region]:
            self._region_panels[panel_info.region].remove(panel_id)
        
        # 从注册表中移除
        del self._panels[panel_id]
        
        if self.logger:
            self.logger.debug(f"Panel '{panel_id}' unregistered")
    
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
        panel_info = self._panels.get(panel_id)
        return panel_info.instance if panel_info else None
    
    def get_panel_info(self, panel_id: str) -> Optional[PanelInfo]:
        """
        获取面板信息
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            面板信息，不存在则返回 None
        """
        return self._panels.get(panel_id)
    
    def get_all_panels(self) -> Dict[str, QWidget]:
        """
        获取所有面板实例
        
        Returns:
            panel_id -> QWidget 的映射
        """
        return {
            panel_id: info.instance
            for panel_id, info in self._panels.items()
        }
    
    def get_panels_in_region(self, region: PanelRegion) -> List[str]:
        """
        获取指定区域的所有面板 ID
        
        Args:
            region: 面板区域
            
        Returns:
            面板 ID 列表
        """
        return self._region_panels[region].copy()
    
    def get_visible_panels(self, region: Optional[PanelRegion] = None) -> List[str]:
        """
        获取可见面板列表
        
        Args:
            region: 指定区域，None 表示所有区域
            
        Returns:
            可见面板 ID 列表
        """
        result = []
        
        for panel_id, info in self._panels.items():
            if region is not None and info.region != region:
                continue
            if info.visible:
                result.append(panel_id)
        
        return result
    
    # ============================================================
    # 可见性控制
    # ============================================================
    
    def show_panel(self, panel_id: str):
        """
        显示面板
        
        Args:
            panel_id: 面板唯一标识
        """
        self._set_panel_visibility(panel_id, True)
    
    def hide_panel(self, panel_id: str):
        """
        隐藏面板
        
        Args:
            panel_id: 面板唯一标识
        """
        self._set_panel_visibility(panel_id, False)
    
    def toggle_panel(self, panel_id: str) -> bool:
        """
        切换面板可见性
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            切换后的可见性状态
        """
        panel_info = self._panels.get(panel_id)
        if not panel_info:
            if self.logger:
                self.logger.warning(f"Panel '{panel_id}' not found")
            return False
        
        new_visible = not panel_info.visible
        self._set_panel_visibility(panel_id, new_visible)
        return new_visible
    
    def is_panel_visible(self, panel_id: str) -> bool:
        """
        检查面板是否可见
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            是否可见
        """
        panel_info = self._panels.get(panel_id)
        return panel_info.visible if panel_info else False
    
    def _set_panel_visibility(self, panel_id: str, visible: bool):
        """
        设置面板可见性
        
        Args:
            panel_id: 面板唯一标识
            visible: 是否可见
        """
        panel_info = self._panels.get(panel_id)
        if not panel_info:
            if self.logger:
                self.logger.warning(f"Panel '{panel_id}' not found")
            return
        
        if panel_info.visible == visible:
            return
        
        panel_info.visible = visible
        panel_info.instance.setVisible(visible)
        
        # 发布可见性变更事件
        self._publish_visibility_changed(panel_id, visible, panel_info.region)
        
        if self.logger:
            action = "shown" if visible else "hidden"
            self.logger.debug(f"Panel '{panel_id}' {action}")
    
    def _publish_visibility_changed(
        self,
        panel_id: str,
        visible: bool,
        region: PanelRegion
    ):
        """发布面板可见性变更事件"""
        if not self.event_bus:
            return
        
        from shared.event_types import EVENT_PANEL_VISIBILITY_CHANGED
        
        self.event_bus.publish(EVENT_PANEL_VISIBILITY_CHANGED, {
            "panel_id": panel_id,
            "visible": visible,
            "region": region.value,
        })
    
    # ============================================================
    # 布局持久化
    # ============================================================
    
    def save_layout_state(self) -> bool:
        """
        保存布局状态到配置
        
        Returns:
            是否保存成功
        """
        try:
            layout_state = {
                "panels": {},
                "version": 1,
            }
            
            for panel_id, info in self._panels.items():
                layout_state["panels"][panel_id] = {
                    "visible": info.visible,
                    "region": info.region.value,
                }
            
            # 保存到配置目录
            layout_path = self._get_layout_path()
            if layout_path:
                layout_path.parent.mkdir(parents=True, exist_ok=True)
                with open(layout_path, "w", encoding="utf-8") as f:
                    json.dump(layout_state, f, indent=2)
                
                if self.logger:
                    self.logger.debug(f"Layout state saved to {layout_path}")
                return True
            
            return False
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to save layout state: {e}")
            return False
    
    def restore_layout_state(self) -> bool:
        """
        从配置恢复布局状态
        
        Returns:
            是否恢复成功
        """
        try:
            layout_path = self._get_layout_path()
            if not layout_path or not layout_path.exists():
                if self.logger:
                    self.logger.debug("No layout state file found")
                return False
            
            with open(layout_path, "r", encoding="utf-8") as f:
                layout_state = json.load(f)
            
            panels_state = layout_state.get("panels", {})
            
            for panel_id, state in panels_state.items():
                if panel_id in self._panels:
                    visible = state.get("visible", True)
                    self._set_panel_visibility(panel_id, visible)
            
            if self.logger:
                self.logger.debug(f"Layout state restored from {layout_path}")
            return True
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to restore layout state: {e}")
            return False
    
    def _get_layout_path(self) -> Optional[Path]:
        """获取布局配置文件路径"""
        try:
            from infrastructure.config.settings import GLOBAL_CONFIG_DIR
            config_dir = Path(GLOBAL_CONFIG_DIR).expanduser()
            return config_dir / self.LAYOUT_FILE
        except Exception:
            return None
    
    # ============================================================
    # 批量操作
    # ============================================================
    
    def show_all_panels(self, region: Optional[PanelRegion] = None):
        """
        显示所有面板
        
        Args:
            region: 指定区域，None 表示所有区域
        """
        for panel_id, info in self._panels.items():
            if region is not None and info.region != region:
                continue
            self.show_panel(panel_id)
    
    def hide_all_panels(self, region: Optional[PanelRegion] = None):
        """
        隐藏所有面板
        
        Args:
            region: 指定区域，None 表示所有区域
        """
        for panel_id, info in self._panels.items():
            if region is not None and info.region != region:
                continue
            self.hide_panel(panel_id)
    
    def reset_layout(self):
        """重置布局到默认状态"""
        # 从面板注册表获取默认可见性
        try:
            from presentation.core.panel_registry import PANEL_DEFINITIONS
            
            for panel_id, info in self._panels.items():
                definition = PANEL_DEFINITIONS.get(panel_id, {})
                default_visible = definition.get("default_visible", True)
                self._set_panel_visibility(panel_id, default_visible)
            
            if self.logger:
                self.logger.info("Layout reset to default")
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to reset layout: {e}")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "PanelManager",
    "PanelRegion",
    "PanelInfo",
]
