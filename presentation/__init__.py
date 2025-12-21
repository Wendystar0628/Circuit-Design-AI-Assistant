# Presentation Layer
"""
表示层 - UI面板、对话框、用户交互

包含：
- main_window.py: 主窗口（布局协调和组件初始化）
- ui_state.py: 纯 UI 状态容器（窗口布局、面板可见性、编辑器状态）
- window_state_manager.py: 窗口状态管理器（位置/尺寸/分割比例）
- session_manager.py: 会话管理器（项目路径/打开文件）
- action_handlers.py: 动作处理器集合（菜单/工具栏回调）
- menu_manager.py: 菜单栏管理器
- toolbar_manager.py: 工具栏管理器
- statusbar_manager.py: 状态栏管理器
- panels/: UI面板（文件浏览器、代码编辑器、对话面板、仿真结果）
- dialogs/: 对话框（API配置、关于、设置等）
- widgets/: 自定义控件
- core/: UI 核心组件（面板管理、事件桥接、ViewModel 基类）

三层状态分离架构：
- Layer 1: UIState (Presentation) - 纯 UI 状态，本层管理
- Layer 2: SessionState (Application) - GraphState 的只读投影，UI 组件只读
- Layer 3: GraphState (Domain) - LangGraph 工作流的唯一真理来源
"""

from presentation.main_window import MainWindow
from presentation.ui_state import (
    UIState,
    UIStateChangeHandler,
    UI_WINDOW_GEOMETRY,
    UI_PANEL_VISIBILITY,
    UI_CURRENT_TAB,
    UI_EDITOR_ACTIVE_FILE,
    UI_IS_GENERATING,
)
from presentation.menu_manager import MenuManager
from presentation.toolbar_manager import ToolbarManager
from presentation.statusbar_manager import StatusbarManager
from presentation.window_state_manager import WindowStateManager
from presentation.session_manager import SessionManager
from presentation.action_handlers import ActionHandlers

__all__ = [
    "MainWindow",
    # UI 状态
    "UIState",
    "UIStateChangeHandler",
    "UI_WINDOW_GEOMETRY",
    "UI_PANEL_VISIBILITY",
    "UI_CURRENT_TAB",
    "UI_EDITOR_ACTIVE_FILE",
    "UI_IS_GENERATING",
    # 管理器
    "MenuManager",
    "ToolbarManager",
    "StatusbarManager",
    "WindowStateManager",
    "SessionManager",
    "ActionHandlers",
]
