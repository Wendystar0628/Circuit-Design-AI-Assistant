# Theme - Global Color Definitions
"""
主题配色定义

职责：
- 定义全局色彩规范，供 QSS 样式表和组件使用
- 仅实现浅色主题，主色为白色，副色为浅蓝色点缀

设计参考：
- Cursor、Trae、VS Code 等现代化 IDE 的视觉风格
"""

from typing import Dict


# ============================================================
# 基础色彩
# ============================================================

# 背景色
COLOR_BG_PRIMARY = "#ffffff"      # 主背景（纯白）
COLOR_BG_SECONDARY = "#f8f9fa"    # 面板背景（浅灰白）
COLOR_BG_TERTIARY = "#f0f0f0"     # 第三级背景

# 边框和分隔线
COLOR_BORDER = "#e0e0e0"          # 边框/分隔线
COLOR_BORDER_LIGHT = "#eeeeee"    # 浅边框

# 文本色
COLOR_TEXT_PRIMARY = "#333333"    # 主文本
COLOR_TEXT_SECONDARY = "#666666"  # 次要文本
COLOR_TEXT_TERTIARY = "#888888"   # 第三级文本
COLOR_TEXT_DISABLED = "#aaaaaa"   # 禁用文本


# ============================================================
# 强调色（浅蓝色系）
# ============================================================

COLOR_ACCENT = "#4a9eff"          # 主题强调色（浅蓝色）
COLOR_ACCENT_HOVER = "#3d8ce6"    # 强调色悬停（深一度浅蓝）
COLOR_ACCENT_PRESSED = "#2d7cd6"  # 强调色按下
COLOR_ACCENT_LIGHT = "#e3f2fd"    # 选中高亮背景（极浅蓝）
COLOR_ACCENT_LIGHTER = "#f0f7ff"  # 悬停高亮背景（淡蓝白）


# ============================================================
# 状态色
# ============================================================

COLOR_SUCCESS = "#4caf50"         # 成功色（绿色）
COLOR_SUCCESS_LIGHT = "#e8f5e9"   # 成功背景
COLOR_WARNING = "#ff9800"         # 警告色（橙色）
COLOR_WARNING_LIGHT = "#fff3e0"   # 警告背景
COLOR_ERROR = "#f44336"           # 错误色（红色）
COLOR_ERROR_LIGHT = "#ffebee"     # 错误背景
COLOR_DISABLED = "#bdbdbd"        # 禁用色（灰色）


# ============================================================
# 字体规范
# ============================================================

# 界面字体（按优先级排列）
FONT_FAMILY_UI = "Segoe UI, SF Pro Display, Roboto, Microsoft YaHei UI, sans-serif"

# 代码字体（按优先级排列）
FONT_FAMILY_CODE = "JetBrains Mono, Cascadia Code, Fira Code, SF Mono, Consolas, monospace"

# 字号
FONT_SIZE_SMALL = 11              # 小字号
FONT_SIZE_NORMAL = 13             # 界面字号
FONT_SIZE_CODE = 14               # 代码字号
FONT_SIZE_TITLE = 16              # 标题字号
FONT_SIZE_LARGE_TITLE = 18        # 大标题字号


# ============================================================
# 尺寸规范
# ============================================================

# 圆角
BORDER_RADIUS_SMALL = 4           # 小圆角
BORDER_RADIUS_NORMAL = 6          # 普通圆角
BORDER_RADIUS_LARGE = 8           # 大圆角

# 间距
SPACING_SMALL = 4                 # 小间距
SPACING_NORMAL = 8                # 普通间距
SPACING_LARGE = 16                # 大间距

# 组件尺寸
HEIGHT_INPUT = 32                 # 输入框高度
HEIGHT_BUTTON = 32                # 按钮高度
HEIGHT_PANEL_HEADER = 28          # 面板标题栏高度
WIDTH_SCROLLBAR = 8               # 滚动条宽度


# ============================================================
# 主题字典（便于批量访问）
# ============================================================

THEME: Dict[str, str] = {
    # 背景
    "bg_primary": COLOR_BG_PRIMARY,
    "bg_secondary": COLOR_BG_SECONDARY,
    "bg_tertiary": COLOR_BG_TERTIARY,
    
    # 边框
    "border": COLOR_BORDER,
    "border_light": COLOR_BORDER_LIGHT,
    
    # 文本
    "text_primary": COLOR_TEXT_PRIMARY,
    "text_secondary": COLOR_TEXT_SECONDARY,
    "text_tertiary": COLOR_TEXT_TERTIARY,
    "text_disabled": COLOR_TEXT_DISABLED,
    
    # 强调色
    "accent": COLOR_ACCENT,
    "accent_hover": COLOR_ACCENT_HOVER,
    "accent_pressed": COLOR_ACCENT_PRESSED,
    "accent_light": COLOR_ACCENT_LIGHT,
    "accent_lighter": COLOR_ACCENT_LIGHTER,
    
    # 状态色
    "success": COLOR_SUCCESS,
    "success_light": COLOR_SUCCESS_LIGHT,
    "warning": COLOR_WARNING,
    "warning_light": COLOR_WARNING_LIGHT,
    "error": COLOR_ERROR,
    "error_light": COLOR_ERROR_LIGHT,
    "disabled": COLOR_DISABLED,
}


# ============================================================
# 颜色字典（兼容测试和批量访问）
# ============================================================

COLORS: Dict[str, str] = {
    # 背景色
    "primary": COLOR_BG_PRIMARY,
    "background": COLOR_BG_PRIMARY,
    "secondary": COLOR_BG_SECONDARY,
    "tertiary": COLOR_BG_TERTIARY,
    
    # 边框
    "border": COLOR_BORDER,
    "border_light": COLOR_BORDER_LIGHT,
    
    # 文本
    "text": COLOR_TEXT_PRIMARY,
    "text_primary": COLOR_TEXT_PRIMARY,
    "text_secondary": COLOR_TEXT_SECONDARY,
    "text_tertiary": COLOR_TEXT_TERTIARY,
    "text_disabled": COLOR_TEXT_DISABLED,
    
    # 强调色
    "accent": COLOR_ACCENT,
    "accent_hover": COLOR_ACCENT_HOVER,
    "accent_pressed": COLOR_ACCENT_PRESSED,
    "accent_light": COLOR_ACCENT_LIGHT,
    "accent_lighter": COLOR_ACCENT_LIGHTER,
    
    # 状态色
    "success": COLOR_SUCCESS,
    "success_light": COLOR_SUCCESS_LIGHT,
    "warning": COLOR_WARNING,
    "warning_light": COLOR_WARNING_LIGHT,
    "error": COLOR_ERROR,
    "error_light": COLOR_ERROR_LIGHT,
    "disabled": COLOR_DISABLED,
}


# ============================================================
# 字体字典（兼容测试和批量访问）
# ============================================================

FONTS: Dict[str, any] = {
    # 字体族
    "family_ui": FONT_FAMILY_UI,
    "family_code": FONT_FAMILY_CODE,
    
    # 字号
    "size_small": FONT_SIZE_SMALL,
    "size_normal": FONT_SIZE_NORMAL,
    "size_code": FONT_SIZE_CODE,
    "size_title": FONT_SIZE_TITLE,
    "size_large_title": FONT_SIZE_LARGE_TITLE,
}


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 背景色
    "COLOR_BG_PRIMARY",
    "COLOR_BG_SECONDARY",
    "COLOR_BG_TERTIARY",
    
    # 边框
    "COLOR_BORDER",
    "COLOR_BORDER_LIGHT",
    
    # 文本色
    "COLOR_TEXT_PRIMARY",
    "COLOR_TEXT_SECONDARY",
    "COLOR_TEXT_TERTIARY",
    "COLOR_TEXT_DISABLED",
    
    # 强调色
    "COLOR_ACCENT",
    "COLOR_ACCENT_HOVER",
    "COLOR_ACCENT_PRESSED",
    "COLOR_ACCENT_LIGHT",
    "COLOR_ACCENT_LIGHTER",
    
    # 状态色
    "COLOR_SUCCESS",
    "COLOR_SUCCESS_LIGHT",
    "COLOR_WARNING",
    "COLOR_WARNING_LIGHT",
    "COLOR_ERROR",
    "COLOR_ERROR_LIGHT",
    "COLOR_DISABLED",
    
    # 字体
    "FONT_FAMILY_UI",
    "FONT_FAMILY_CODE",
    "FONT_SIZE_SMALL",
    "FONT_SIZE_NORMAL",
    "FONT_SIZE_CODE",
    "FONT_SIZE_TITLE",
    "FONT_SIZE_LARGE_TITLE",
    
    # 尺寸
    "BORDER_RADIUS_SMALL",
    "BORDER_RADIUS_NORMAL",
    "BORDER_RADIUS_LARGE",
    "SPACING_SMALL",
    "SPACING_NORMAL",
    "SPACING_LARGE",
    "HEIGHT_INPUT",
    "HEIGHT_BUTTON",
    "HEIGHT_PANEL_HEADER",
    "WIDTH_SCROLLBAR",
    
    # 主题字典
    "THEME",
    "COLORS",
    "FONTS",
]
