# Resources Module
"""
UI 资源模块

包含：
- styles/: QSS 样式表
- icons/: SVG 图标资源
- theme.py: 主题配色定义
- resource_loader.py: 资源加载器
"""

from .theme import (
    # 背景色
    COLOR_BG_PRIMARY,
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    
    # 边框
    COLOR_BORDER,
    COLOR_BORDER_LIGHT,
    
    # 文本色
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_TEXT_TERTIARY,
    COLOR_TEXT_DISABLED,
    
    # 强调色
    COLOR_ACCENT,
    COLOR_ACCENT_HOVER,
    COLOR_ACCENT_PRESSED,
    COLOR_ACCENT_LIGHT,
    COLOR_ACCENT_LIGHTER,
    
    # 状态色
    COLOR_SUCCESS,
    COLOR_WARNING,
    COLOR_ERROR,
    COLOR_DISABLED,
    
    # 字体
    FONT_FAMILY_UI,
    FONT_FAMILY_CODE,
    FONT_SIZE_NORMAL,
    FONT_SIZE_CODE,
    
    # 主题字典
    THEME,
)

from .resource_loader import (
    load_stylesheet,
    get_stylesheet,
    get_icon,
    get_toolbar_icon,
    get_menu_icon,
    get_panel_icon,
    get_status_icon,
    get_file_icon,
    get_icon_path,
)

__all__ = [
    # 主题色
    "COLOR_BG_PRIMARY",
    "COLOR_BG_SECONDARY",
    "COLOR_BG_TERTIARY",
    "COLOR_BORDER",
    "COLOR_BORDER_LIGHT",
    "COLOR_TEXT_PRIMARY",
    "COLOR_TEXT_SECONDARY",
    "COLOR_TEXT_TERTIARY",
    "COLOR_TEXT_DISABLED",
    "COLOR_ACCENT",
    "COLOR_ACCENT_HOVER",
    "COLOR_ACCENT_PRESSED",
    "COLOR_ACCENT_LIGHT",
    "COLOR_ACCENT_LIGHTER",
    "COLOR_SUCCESS",
    "COLOR_WARNING",
    "COLOR_ERROR",
    "COLOR_DISABLED",
    "FONT_FAMILY_UI",
    "FONT_FAMILY_CODE",
    "FONT_SIZE_NORMAL",
    "FONT_SIZE_CODE",
    "THEME",
    
    # 资源加载
    "load_stylesheet",
    "get_stylesheet",
    "get_icon",
    "get_toolbar_icon",
    "get_menu_icon",
    "get_panel_icon",
    "get_status_icon",
    "get_file_icon",
    "get_icon_path",
]
