# Resource Loader
"""
资源加载器

职责：
- 加载 QSS 样式表
- 加载 SVG 图标
- 提供资源路径获取

加载时机：
- 在 bootstrap.py 的 Phase 2.1 阶段调用
"""

import os
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon


# ============================================================
# 资源路径
# ============================================================

def get_resources_dir() -> Path:
    """获取资源目录路径"""
    return Path(__file__).parent


def get_styles_dir() -> Path:
    """获取样式表目录路径"""
    return get_resources_dir() / "styles"


def get_icons_dir() -> Path:
    """获取图标目录路径"""
    return get_resources_dir() / "icons"


# ============================================================
# 样式表加载
# ============================================================

def load_stylesheet(app: QApplication) -> bool:
    """
    加载主样式表到应用
    
    Args:
        app: QApplication 实例
        
    Returns:
        是否加载成功
    """
    qss_path = get_styles_dir() / "main.qss"
    
    if not qss_path.exists():
        print(f"Warning: Stylesheet not found: {qss_path}")
        return False
    
    try:
        with open(qss_path, "r", encoding="utf-8") as f:
            stylesheet = f.read()
        
        app.setStyleSheet(stylesheet)
        return True
        
    except Exception as e:
        print(f"Error loading stylesheet: {e}")
        return False


def get_stylesheet() -> str:
    """
    获取样式表内容
    
    Returns:
        样式表字符串
    """
    qss_path = get_styles_dir() / "main.qss"
    
    if not qss_path.exists():
        return ""
    
    try:
        with open(qss_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


# ============================================================
# 图标加载
# ============================================================

def get_icon(category: str, name: str) -> QIcon:
    """
    获取 SVG 图标
    
    Args:
        category: 图标分类（toolbar/menu/panel/status/file）
        name: 图标名称（不含扩展名）
        
    Returns:
        QIcon 实例
    """
    icon_path = get_icons_dir() / category / f"{name}.svg"
    
    if icon_path.exists():
        return QIcon(str(icon_path))
    else:
        print(f"Warning: Icon not found: {icon_path}")
        return QIcon()


def get_toolbar_icon(name: str) -> QIcon:
    """获取工具栏图标 (24x24)"""
    return get_icon("toolbar", name)


def get_menu_icon(name: str) -> QIcon:
    """获取菜单图标 (16x16)"""
    return get_icon("menu", name)


def get_panel_icon(name: str) -> QIcon:
    """获取面板图标 (20x20)"""
    return get_icon("panel", name)


def get_status_icon(name: str) -> QIcon:
    """获取状态图标 (16x16)"""
    return get_icon("status", name)


def get_file_icon(name: str) -> QIcon:
    """获取文件类型图标 (16x16)"""
    return get_icon("file", name)


def get_icon_path(category: str, name: str) -> Optional[str]:
    """
    获取图标文件路径
    
    Args:
        category: 图标分类
        name: 图标名称
        
    Returns:
        图标文件路径，不存在则返回 None
    """
    icon_path = get_icons_dir() / category / f"{name}.svg"
    
    if icon_path.exists():
        return str(icon_path)
    return None


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 路径获取
    "get_resources_dir",
    "get_styles_dir",
    "get_icons_dir",
    
    # 样式表
    "load_stylesheet",
    "get_stylesheet",
    
    # 图标
    "get_icon",
    "get_toolbar_icon",
    "get_menu_icon",
    "get_panel_icon",
    "get_status_icon",
    "get_file_icon",
    "get_icon_path",
]
