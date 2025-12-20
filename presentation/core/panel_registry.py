# Panel Registry - 面板注册表
"""
面板注册表 - 集中定义所有面板的元信息

职责：
- 定义所有面板的元信息（类名、模块、区域、默认可见性等）
- 支持面板的延迟加载
- 提供面板元信息查询接口

设计原则：
- 集中管理：所有面板定义在一处
- 延迟加载：面板类在首次访问时动态导入
- 可扩展：新面板只需添加定义即可

被调用方：panel_manager.py、main_window.py
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
    },
    "code_editor": {
        "class": "CodeEditorPanel",
        "module": "presentation.panels.code_editor_panel",
        "region": "CENTER",
        "default_visible": True,
        "title_key": "panel.code_editor",
        "icon": "icons/panel/code.svg",
    },
    "conversation": {
        "class": "ConversationPanel",
        "module": "presentation.panels.conversation_panel",
        "region": "RIGHT",
        "default_visible": True,
        "title_key": "panel.conversation",
        "icon": "icons/panel/chat.svg",
        "tab_id": "TAB_CONVERSATION",
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
    
    集中定义所有面板的元信息，支持延迟加载。
    """
    
    # 已加载的面板类缓存
    _loaded_classes: Dict[str, Type[QWidget]] = {}
    
    @classmethod
    def get_panel_definition(cls, panel_id: str) -> Optional[Dict[str, Any]]:
        """
        获取面板定义
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            面板定义字典，不存在则返回 None
        """
        return PANEL_DEFINITIONS.get(panel_id)
    
    @classmethod
    def get_all_panel_ids(cls) -> list:
        """
        获取所有面板 ID
        
        Returns:
            面板 ID 列表
        """
        return list(PANEL_DEFINITIONS.keys())
    
    @classmethod
    def get_panels_by_region(cls, region: str) -> list:
        """
        获取指定区域的面板 ID 列表
        
        Args:
            region: 区域名称（LEFT, CENTER, RIGHT, BOTTOM）
            
        Returns:
            面板 ID 列表
        """
        return [
            pid for pid, definition in PANEL_DEFINITIONS.items()
            if definition.get("region") == region
        ]
    
    @classmethod
    def get_panels_by_phase(cls, max_phase: int) -> list:
        """
        获取指定阶段及之前实现的面板 ID 列表
        
        Args:
            max_phase: 最大阶段号
            
        Returns:
            面板 ID 列表
        """
        return [
            pid for pid, definition in PANEL_DEFINITIONS.items()
            if definition.get("phase", 1) <= max_phase
        ]
    
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
        
        # 获取定义
        definition = PANEL_DEFINITIONS.get(panel_id)
        if not definition:
            return None
        
        module_name = definition.get("module")
        class_name = definition.get("class")
        
        if not module_name or not class_name:
            return None
        
        try:
            # 动态导入模块
            module = import_module(module_name)
            # 获取类
            panel_class = getattr(module, class_name)
            # 缓存
            cls._loaded_classes[panel_id] = panel_class
            return panel_class
            
        except (ImportError, AttributeError) as e:
            # 模块或类不存在（可能是后续阶段实现）
            return None
    
    @classmethod
    def create_panel_instance(cls, panel_id: str, **kwargs) -> Optional[QWidget]:
        """
        创建面板实例
        
        Args:
            panel_id: 面板唯一标识
            **kwargs: 传递给面板构造函数的参数
            
        Returns:
            面板实例，创建失败则返回 None
        """
        panel_class = cls.load_panel_class(panel_id)
        if not panel_class:
            return None
        
        try:
            return panel_class(**kwargs)
        except Exception:
            return None
    
    @classmethod
    def is_panel_available(cls, panel_id: str) -> bool:
        """
        检查面板是否可用（类是否可加载）
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            是否可用
        """
        return cls.load_panel_class(panel_id) is not None
    
    @classmethod
    def get_tab_panels(cls) -> list:
        """
        获取需要放入标签页的面板 ID 列表
        
        Returns:
            面板 ID 列表
        """
        return [
            pid for pid, definition in PANEL_DEFINITIONS.items()
            if "tab_id" in definition
        ]
    
    @classmethod
    def get_default_visible_panels(cls) -> list:
        """
        获取默认可见的面板 ID 列表
        
        Returns:
            面板 ID 列表
        """
        return [
            pid for pid, definition in PANEL_DEFINITIONS.items()
            if definition.get("default_visible", False)
        ]


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "PanelRegistry",
    "PANEL_DEFINITIONS",
]
