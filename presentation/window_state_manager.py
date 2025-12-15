# Window State Manager - 窗口状态管理器
"""
窗口状态管理器 - 负责窗口位置/尺寸/分割比例的保存与恢复

职责：
- 保存窗口位置和尺寸
- 保存分割器比例
- 保存面板可见性
- 恢复上述状态

设计原则：
- 单一职责：仅负责窗口状态的持久化
- 延迟获取 ServiceLocator 中的服务
"""

from typing import Optional, Dict, Any, List

from PyQt6.QtWidgets import QMainWindow, QSplitter, QWidget


class WindowStateManager:
    """
    窗口状态管理器
    
    负责窗口状态（位置、尺寸、分割比例、面板可见性）的保存与恢复
    """

    def __init__(self, main_window: QMainWindow):
        """
        初始化窗口状态管理器
        
        Args:
            main_window: 主窗口引用
        """
        self._main_window = main_window
        self._config_manager = None

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


    def save_window_state(self, splitters: Dict[str, QSplitter], panels: Dict[str, QWidget]):
        """
        保存窗口状态到 ConfigManager
        
        Args:
            splitters: 分割器字典 {"horizontal": QSplitter, "vertical": QSplitter}
            panels: 面板字典 {"file_browser": QWidget, ...}
        """
        if not self.config_manager:
            return
        
        # 保存窗口位置和尺寸
        geo = self._main_window.geometry()
        self.config_manager.set("window_geometry", [geo.x(), geo.y(), geo.width(), geo.height()])
        
        # 保存分割器比例
        self.save_splitter_sizes(splitters)
        
        # 保存面板可见性
        self.save_panel_visibility(panels)

    def restore_window_state(self, splitters: Dict[str, QSplitter], panels: Dict[str, QWidget]):
        """
        从 ConfigManager 恢复窗口状态
        
        Args:
            splitters: 分割器字典
            panels: 面板字典
        """
        if not self.config_manager:
            return
        
        # 恢复窗口位置和尺寸
        geometry = self.config_manager.get("window_geometry")
        if geometry:
            try:
                x, y, w, h = geometry
                self._main_window.setGeometry(x, y, w, h)
            except (ValueError, TypeError):
                pass
        
        # 恢复分割器比例
        self.restore_splitter_sizes(splitters)
        
        # 恢复面板可见性
        self.restore_panel_visibility(panels)

    def save_splitter_sizes(self, splitters: Dict[str, QSplitter]):
        """
        保存分割器比例
        
        Args:
            splitters: 分割器字典
        """
        if not self.config_manager:
            return
        
        h_sizes = splitters.get("horizontal")
        v_sizes = splitters.get("vertical")
        
        if h_sizes and v_sizes:
            h_list = h_sizes.sizes()
            v_list = v_sizes.sizes()
            
            if all(s > 0 for s in h_list) and all(s > 0 for s in v_list):
                self.config_manager.set("splitter_sizes", {
                    "horizontal": h_list,
                    "vertical": v_list,
                })

    def restore_splitter_sizes(self, splitters: Dict[str, QSplitter]):
        """
        恢复分割器比例
        
        Args:
            splitters: 分割器字典
        """
        if not self.config_manager:
            return
        
        splitter_sizes = self.config_manager.get("splitter_sizes")
        if not splitter_sizes:
            return
        
        try:
            # 恢复水平分割器
            if "horizontal" in splitter_sizes and "horizontal" in splitters:
                h_sizes = splitter_sizes["horizontal"]
                if isinstance(h_sizes, list) and len(h_sizes) == 3:
                    min_sizes = [150, 400, 250]
                    valid_sizes = all(
                        isinstance(s, (int, float)) and s >= min_sizes[i] 
                        for i, s in enumerate(h_sizes)
                    )
                    if valid_sizes:
                        splitters["horizontal"].setSizes(h_sizes)
            
            # 恢复垂直分割器
            if "vertical" in splitter_sizes and "vertical" in splitters:
                v_sizes = splitter_sizes["vertical"]
                if isinstance(v_sizes, list) and len(v_sizes) == 2:
                    valid_sizes = (
                        isinstance(v_sizes[0], (int, float)) and v_sizes[0] >= 400 and
                        isinstance(v_sizes[1], (int, float)) and v_sizes[1] >= 100
                    )
                    if valid_sizes:
                        splitters["vertical"].setSizes(v_sizes)
        except (ValueError, TypeError):
            pass

    def save_panel_visibility(self, panels: Dict[str, QWidget]):
        """
        保存面板可见性
        
        Args:
            panels: 面板字典
        """
        if not self.config_manager:
            return
        
        panel_visibility = {}
        for panel_name, panel in panels.items():
            panel_visibility[panel_name] = panel.isVisible()
        self.config_manager.set("panel_visibility", panel_visibility)

    def restore_panel_visibility(self, panels: Dict[str, QWidget], menu_manager=None):
        """
        恢复面板可见性
        
        Args:
            panels: 面板字典
            menu_manager: 菜单管理器（用于同步勾选状态）
        """
        if not self.config_manager:
            return
        
        panel_visibility = self.config_manager.get("panel_visibility")
        if not panel_visibility or not isinstance(panel_visibility, dict):
            return
        
        for panel_name, visible in panel_visibility.items():
            if panel_name in panels:
                is_visible = bool(visible) if visible is not None else True
                panels[panel_name].setVisible(is_visible)
                # 同步菜单勾选状态
                if menu_manager:
                    action_key = f"view_{panel_name}"
                    menu_manager.set_action_checked(action_key, is_visible)


__all__ = ["WindowStateManager"]
