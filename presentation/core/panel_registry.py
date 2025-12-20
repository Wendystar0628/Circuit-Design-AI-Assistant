# Panel Registry
"""
面板注册表

职责：
- 集中定义所有面板的元信息
- 支持面板的延迟加载
- 提供面板定义查询接口

设计原则：
- 面板类在首次访问时动态导入
- 减少启动时间，按需加载
- 元信息与实现分离

被调用方：
- panel_manager.py
- main_window.py
"""

from typing import Optional, Dict, Any, Type
from importlib import import_module

from PyQt6.QtWidgets import QWidget


# ============================================================
# 面板定义
# ============================================================

PANEL_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "file_browser": {
        "class": "FileBrowserPanel",
        "module": "presentation.panels.file_browser_panel",
        "region": "LEFT",
        "default_visible": True,
        "title_key": "panel.file_browser",
        "icon": "icons/panel/folder.svg",
        "min_width": 150,
    },
    "code_editor": {
        "class": "CodeEditorPanel",
        "module": "presentation.panels.code_editor_panel",
        "region": "CENTER",
        "default_visible": True,
        "title_key": "panel.code_editor",
        "icon": "icons/panel/code.svg",
        "min_width": 400,
    },
    "conversation": {
        "class": "ConversationPanel",
        "module": "presentation.panels.conversation_panel",
        "region": "RIGHT",
        "default_visible": True,
        "title_key": "panel.conversation",
        "icon": "icons/panel/chat.svg",
        "tab_id": "TAB_CONVERSATION",
        "min_width": 250,
    },
    "info": {
        "class": "InfoPanel",
        "module": "presentation.panels.info.info_panel",
        "region": "RIGHT",
        "default_visible": False,
        "title_key": "panel.info",
        "icon": "icons/panel/info.svg",
        "tab_id": "TAB_INFO",
        "phase": 9,  # 阶段九实现
    },
    "simulation": {
        "class": "SimulationPanel",
        "module": "presentation.panels.simulation.simulation_panel",
        "region": "BOTTOM",
        "default_visible": True,
        "title_key": "panel.simulation",
        "icon": "icons/panel/chart.svg",
        "min_height": 100,
        "phase": 4,  # 阶段四实现
    },
    "component": {
        "class": "ComponentPanel",
        "module": "presentation.panels.component.component_panel",
        "region": "RIGHT",
        "default_visible": False,
        "title_key": "panel.component",
        "icon": "icons/panel/chip.svg",
        "tab_id": "TAB_COMPONENT",
        "phase": 10,  # 阶段十实现
    },
}


class PanelRegistry:
    """
    面板注册表
    
    提供面板定义查询和延迟加载功能
    
    使用示例：
        # 获取面板定义
        definition = PanelRegistry.get_definition("file_browser")
        
        # 延迟加载面板类
        panel_class = PanelRegistry.load_panel_class("file_browser")
        panel = panel_class()
    """
    
    # 已加载的面板类缓存
    _loaded_classes: Dict[str, Type[QWidget]] = {}
    
    @classmethod
    def get_definition(cls, panel_id: str) -> Optional[Dict[str, Any]]:
        """
        获取面板定义
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            面板定义字典，不存在则返回 None
        """
        return PANEL_DEFINITIONS.get(panel_id)
    
    @classmethod
    def get_all_definitions(cls) -> Dict[str, Dict[str, Any]]:
        """
        获取所有面板定义
        
        Returns:
            所有面板定义的字典
        """
        return PANEL_DEFINITIONS.copy()
    
    @classmethod
    def get_panels_by_region(cls, region: str) -> Dict[str, Dict[str, Any]]:
        """
        获取指定区域的面板定义
        
        Args:
            region: 区域名称（LEFT, CENTER, RIGHT, BOTTOM）
            
        Returns:
            该区域的面板定义字典
        """
        return {
            panel_id: definition
            for panel_id, definition in PANEL_DEFINITIONS.items()
            if definition.get("region") == region
        }
    
    @classmethod
    def get_tab_panels(cls) -> Dict[str, Dict[str, Any]]:
        """
        获取所有标签页面板定义
        
        Returns:
            带有 tab_id 的面板定义字典
        """
        return {
            panel_id: definition
            for panel_id, definition in PANEL_DEFINITIONS.items()
            if "tab_id" in definition
        }
    
    @classmethod
    def is_panel_available(cls, panel_id: str, current_phase: int = 99) -> bool:
        """
        检查面板是否在当前阶段可用
        
        Args:
            panel_id: 面板唯一标识
            current_phase: 当前开发阶段
            
        Returns:
            是否可用
        """
        definition = PANEL_DEFINITIONS.get(panel_id)
        if not definition:
            return False
        
        required_phase = definition.get("phase", 1)
        return current_phase >= required_phase
    
    @classmethod
    def load_panel_class(cls, panel_id: str) -> Optional[Type[QWidget]]:
        """
        延迟加载面板类
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            面板类，加载失败则返回 None
        """
        # 检查缓存
        if panel_id in cls._loaded_classes:
            return cls._loaded_classes[panel_id]
        
        definition = PANEL_DEFINITIONS.get(panel_id)
        if not definition:
            return None
        
        module_path = definition.get("module")
        class_name = definition.get("class")
        
        if not module_path or not class_name:
            return None
        
        try:
            module = import_module(module_path)
            panel_class = getattr(module, class_name)
            
            # 缓存已加载的类
            cls._loaded_classes[panel_id] = panel_class
            
            return panel_class
            
        except (ImportError, AttributeError) as e:
            # 记录错误但不抛出，允许降级运行
            try:
                from infrastructure.utils.logger import get_logger
                logger = get_logger("panel_registry")
                logger.warning(f"Failed to load panel class '{panel_id}': {e}")
            except Exception:
                pass
            
            return None
    
    @classmethod
    def create_panel(cls, panel_id: str, *args, **kwargs) -> Optional[QWidget]:
        """
        创建面板实例
        
        Args:
            panel_id: 面板唯一标识
            *args: 传递给面板构造函数的位置参数
            **kwargs: 传递给面板构造函数的关键字参数
            
        Returns:
            面板实例，创建失败则返回 None
        """
        panel_class = cls.load_panel_class(panel_id)
        if not panel_class:
            return None
        
        try:
            return panel_class(*args, **kwargs)
        except Exception as e:
            try:
                from infrastructure.utils.logger import get_logger
                logger = get_logger("panel_registry")
                logger.error(f"Failed to create panel '{panel_id}': {e}")
            except Exception:
                pass
            
            return None
    
    @classmethod
    def clear_cache(cls):
        """清除已加载的面板类缓存"""
        cls._loaded_classes.clear()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "PanelRegistry",
    "PANEL_DEFINITIONS",
]
