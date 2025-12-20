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
- tab_controller.py
"""

from typing import Optional, Dict, Any, Type, List
from dataclasses import dataclass
from importlib import import_module

from PyQt6.QtWidgets import QWidget


# ============================================================
# 面板定义数据类
# ============================================================

@dataclass
class PanelDefinition:
    """面板定义数据类"""
    panel_id: str
    class_name: str
    module_path: str
    region: str
    default_visible: bool = True
    title_key: str = ""
    icon: str = ""
    tab_id: Optional[str] = None
    phase: int = 1
    min_width: Optional[int] = None
    min_height: Optional[int] = None
    
    @classmethod
    def from_dict(cls, panel_id: str, data: Dict[str, Any]) -> "PanelDefinition":
        """从字典创建 PanelDefinition"""
        return cls(
            panel_id=panel_id,
            class_name=data.get("class", ""),
            module_path=data.get("module", ""),
            region=data.get("region", ""),
            default_visible=data.get("default_visible", True),
            title_key=data.get("title_key", ""),
            icon=data.get("icon", ""),
            tab_id=data.get("tab_id"),
            phase=data.get("phase", 1),
            min_width=data.get("min_width"),
            min_height=data.get("min_height"),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            "class": self.class_name,
            "module": self.module_path,
            "region": self.region,
            "default_visible": self.default_visible,
            "title_key": self.title_key,
            "icon": self.icon,
            "phase": self.phase,
        }
        if self.tab_id:
            result["tab_id"] = self.tab_id
        if self.min_width:
            result["min_width"] = self.min_width
        if self.min_height:
            result["min_height"] = self.min_height
        return result


# ============================================================
# 面板定义常量
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
        "phase": 9,
    },
    "simulation": {
        "class": "SimulationPanel",
        "module": "presentation.panels.simulation.simulation_panel",
        "region": "BOTTOM",
        "default_visible": True,
        "title_key": "panel.simulation",
        "icon": "icons/panel/chart.svg",
        "min_height": 100,
        "phase": 4,
    },
    "component": {
        "class": "ComponentPanel",
        "module": "presentation.panels.component.component_panel",
        "region": "RIGHT",
        "default_visible": False,
        "title_key": "panel.component",
        "icon": "icons/panel/chip.svg",
        "tab_id": "TAB_COMPONENT",
        "phase": 10,
    },
}


# ============================================================
# 面板注册表类
# ============================================================

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
        
        # 获取面板标题
        title = PanelRegistry.get_title("file_browser", i18n_manager)
    """
    
    # 已加载的面板类缓存
    _loaded_classes: Dict[str, Type[QWidget]] = {}
    
    # ============================================================
    # 基础查询方法
    # ============================================================
    
    @classmethod
    def get_definition(cls, panel_id: str) -> Optional[Dict[str, Any]]:
        """
        获取面板定义（字典形式）
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            面板定义字典，不存在则返回 None
        """
        return PANEL_DEFINITIONS.get(panel_id)
    
    @classmethod
    def get_panel_definition(cls, panel_id: str) -> Optional[PanelDefinition]:
        """
        获取面板定义（数据类形式）
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            PanelDefinition 实例，不存在则返回 None
        """
        data = PANEL_DEFINITIONS.get(panel_id)
        if data:
            return PanelDefinition.from_dict(panel_id, data)
        return None
    
    @classmethod
    def get_all_definitions(cls) -> Dict[str, Dict[str, Any]]:
        """
        获取所有面板定义
        
        Returns:
            所有面板定义的字典副本
        """
        return PANEL_DEFINITIONS.copy()
    
    @classmethod
    def get_all_panel_ids(cls) -> List[str]:
        """
        获取所有面板 ID 列表
        
        Returns:
            面板 ID 列表
        """
        return list(PANEL_DEFINITIONS.keys())
    
    # ============================================================
    # 按条件查询
    # ============================================================
    
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
    def get_panel_by_tab_id(cls, tab_id: str) -> Optional[str]:
        """
        根据 tab_id 获取面板 ID
        
        Args:
            tab_id: 标签页 ID（如 TAB_CONVERSATION）
            
        Returns:
            面板 ID，不存在则返回 None
        """
        for panel_id, definition in PANEL_DEFINITIONS.items():
            if definition.get("tab_id") == tab_id:
                return panel_id
        return None
    
    @classmethod
    def get_available_panels(cls, current_phase: int = 99) -> Dict[str, Dict[str, Any]]:
        """
        获取当前阶段可用的面板定义
        
        Args:
            current_phase: 当前开发阶段
            
        Returns:
            可用面板定义字典
        """
        return {
            panel_id: definition
            for panel_id, definition in PANEL_DEFINITIONS.items()
            if definition.get("phase", 1) <= current_phase
        }
    
    # ============================================================
    # 属性获取
    # ============================================================
    
    @classmethod
    def get_title_key(cls, panel_id: str) -> str:
        """
        获取面板标题的 i18n key
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            i18n key，不存在则返回空字符串
        """
        definition = PANEL_DEFINITIONS.get(panel_id)
        return definition.get("title_key", "") if definition else ""
    
    @classmethod
    def get_title(cls, panel_id: str, i18n_manager=None, default: str = "") -> str:
        """
        获取面板标题（已翻译）
        
        Args:
            panel_id: 面板唯一标识
            i18n_manager: I18nManager 实例（可选）
            default: 默认标题
            
        Returns:
            翻译后的标题
        """
        title_key = cls.get_title_key(panel_id)
        if not title_key:
            return default or panel_id
        
        if i18n_manager:
            return i18n_manager.get_text(title_key, default or panel_id)
        
        return default or panel_id
    
    @classmethod
    def get_icon_path(cls, panel_id: str) -> str:
        """
        获取面板图标路径
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            图标路径，不存在则返回空字符串
        """
        definition = PANEL_DEFINITIONS.get(panel_id)
        return definition.get("icon", "") if definition else ""
    
    @classmethod
    def get_tab_id(cls, panel_id: str) -> Optional[str]:
        """
        获取面板的 tab_id
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            tab_id，不存在则返回 None
        """
        definition = PANEL_DEFINITIONS.get(panel_id)
        return definition.get("tab_id") if definition else None
    
    @classmethod
    def get_default_visible(cls, panel_id: str) -> bool:
        """
        获取面板默认可见性
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            默认可见性
        """
        definition = PANEL_DEFINITIONS.get(panel_id)
        return definition.get("default_visible", True) if definition else True
    
    @classmethod
    def get_min_size(cls, panel_id: str) -> tuple:
        """
        获取面板最小尺寸
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            (min_width, min_height) 元组，None 表示未设置
        """
        definition = PANEL_DEFINITIONS.get(panel_id)
        if not definition:
            return (None, None)
        return (definition.get("min_width"), definition.get("min_height"))
    
    # ============================================================
    # 可用性检查
    # ============================================================
    
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
    def is_tab_panel(cls, panel_id: str) -> bool:
        """
        检查面板是否为标签页面板
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            是否为标签页面板
        """
        definition = PANEL_DEFINITIONS.get(panel_id)
        return "tab_id" in definition if definition else False
    
    # ============================================================
    # 延迟加载
    # ============================================================
    
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
            cls._log_error(f"Failed to load panel class '{panel_id}': {e}")
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
            cls._log_error(f"Failed to create panel '{panel_id}': {e}")
            return None
    
    @classmethod
    def is_class_loaded(cls, panel_id: str) -> bool:
        """
        检查面板类是否已加载
        
        Args:
            panel_id: 面板唯一标识
            
        Returns:
            是否已加载
        """
        return panel_id in cls._loaded_classes
    
    @classmethod
    def clear_cache(cls):
        """清除已加载的面板类缓存"""
        cls._loaded_classes.clear()
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    @classmethod
    def _log_error(cls, message: str):
        """记录错误日志"""
        try:
            from infrastructure.utils.logger import get_logger
            logger = get_logger("panel_registry")
            logger.error(message)
        except Exception:
            pass
    
    @classmethod
    def _log_warning(cls, message: str):
        """记录警告日志"""
        try:
            from infrastructure.utils.logger import get_logger
            logger = get_logger("panel_registry")
            logger.warning(message)
        except Exception:
            pass


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "PanelRegistry",
    "PanelDefinition",
    "PANEL_DEFINITIONS",
]
