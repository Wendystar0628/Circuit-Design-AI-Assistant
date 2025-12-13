# Toolbar Manager - Centralized Toolbar Management
"""
工具栏管理器 - 集中管理工具栏的创建、动作绑定和国际化

职责：
- 创建工具栏和工具栏按钮
- 管理动作的启用/禁用状态
- 刷新所有按钮文本（国际化支持）

设计原则：
- 工具栏按钮使用 QAction，图标从 resources/icons/toolbar/ 加载 SVG
- 动作处理器回调由 MainWindow 提供

被调用方：main_window.py
"""

from typing import Dict, Optional, Callable
from pathlib import Path

from PyQt6.QtWidgets import QMainWindow, QToolBar
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QAction, QIcon


class ToolbarManager:
    """
    工具栏管理器
    
    集中管理工具栏的创建、动作绑定和国际化。
    """

    def __init__(self, main_window: QMainWindow):
        """
        初始化工具栏管理器
        
        Args:
            main_window: 主窗口引用
        """
        self._main_window = main_window
        self._toolbar: Optional[QToolBar] = None
        self._actions: Dict[str, QAction] = {}
        
        # 图标目录
        self._icon_dir = Path(__file__).parent.parent / "resources" / "icons" / "toolbar"

    # ============================================================
    # 服务访问（通过主窗口）
    # ============================================================

    def _get_text(self, key: str, default: Optional[str] = None) -> str:
        """获取国际化文本"""
        if hasattr(self._main_window, '_get_text'):
            return self._main_window._get_text(key, default)
        return default if default else key

    def _load_icon(self, name: str) -> QIcon:
        """
        加载工具栏图标
        
        Args:
            name: 图标文件名（不含扩展名）
            
        Returns:
            QIcon 对象
        """
        icon_path = self._icon_dir / f"{name}.svg"
        if icon_path.exists():
            return QIcon(str(icon_path))
        
        # 尝试 PNG 格式
        icon_path = self._icon_dir / f"{name}.png"
        if icon_path.exists():
            return QIcon(str(icon_path))
        
        # 返回空图标
        return QIcon()

    # ============================================================
    # 核心方法
    # ============================================================

    def setup_toolbar(self, callbacks: Dict[str, Callable]) -> QToolBar:
        """
        创建工具栏
        
        Args:
            callbacks: 动作回调函数字典
            
        Returns:
            创建的 QToolBar 对象
        """
        self._toolbar = QToolBar()
        self._toolbar.setMovable(False)
        self._toolbar.setIconSize(QSize(24, 24))
        self._main_window.addToolBar(self._toolbar)
        
        # 打开工作文件夹
        self._actions["toolbar_open"] = QAction(self._main_window)
        self._actions["toolbar_open"].setIcon(self._load_icon("folder_open"))
        if "on_open_workspace" in callbacks:
            self._actions["toolbar_open"].triggered.connect(callbacks["on_open_workspace"])
        self._toolbar.addAction(self._actions["toolbar_open"])
        
        # 保存当前文件
        self._actions["toolbar_save"] = QAction(self._main_window)
        self._actions["toolbar_save"].setIcon(self._load_icon("save"))
        self._actions["toolbar_save"].setEnabled(False)
        if "on_save_file" in callbacks:
            self._actions["toolbar_save"].triggered.connect(callbacks["on_save_file"])
        self._toolbar.addAction(self._actions["toolbar_save"])
        
        # 全部保存
        self._actions["toolbar_save_all"] = QAction(self._main_window)
        self._actions["toolbar_save_all"].setIcon(self._load_icon("save_all"))
        self._actions["toolbar_save_all"].setEnabled(False)
        if "on_save_all_files" in callbacks:
            self._actions["toolbar_save_all"].triggered.connect(callbacks["on_save_all_files"])
        self._toolbar.addAction(self._actions["toolbar_save_all"])
        
        self._toolbar.addSeparator()
        
        # 运行仿真（灰显，阶段四启用）
        self._actions["toolbar_run"] = QAction(self._main_window)
        self._actions["toolbar_run"].setIcon(self._load_icon("play"))
        self._actions["toolbar_run"].setEnabled(False)
        self._toolbar.addAction(self._actions["toolbar_run"])
        
        # 停止仿真（灰显，阶段四启用）
        self._actions["toolbar_stop"] = QAction(self._main_window)
        self._actions["toolbar_stop"].setIcon(self._load_icon("stop"))
        self._actions["toolbar_stop"].setEnabled(False)
        self._toolbar.addAction(self._actions["toolbar_stop"])
        
        self._toolbar.addSeparator()
        
        # 撤销（灰显，阶段五启用）
        self._actions["toolbar_undo"] = QAction(self._main_window)
        self._actions["toolbar_undo"].setIcon(self._load_icon("undo"))
        self._actions["toolbar_undo"].setEnabled(False)
        self._toolbar.addAction(self._actions["toolbar_undo"])
        
        # 重做（灰显，阶段五启用）
        self._actions["toolbar_redo"] = QAction(self._main_window)
        self._actions["toolbar_redo"].setIcon(self._load_icon("redo"))
        self._actions["toolbar_redo"].setEnabled(False)
        self._toolbar.addAction(self._actions["toolbar_redo"])
        
        return self._toolbar

    def retranslate_ui(self) -> None:
        """刷新所有按钮文本"""
        self._actions["toolbar_open"].setText(self._get_text("menu.file.open", "Open"))
        self._actions["toolbar_open"].setToolTip(self._get_text("menu.file.open", "Open Workspace"))
        
        self._actions["toolbar_save"].setText(self._get_text("btn.save", "Save"))
        self._actions["toolbar_save"].setToolTip(self._get_text("menu.file.save", "Save"))
        
        self._actions["toolbar_save_all"].setText(self._get_text("menu.file.save_all", "Save All"))
        self._actions["toolbar_save_all"].setToolTip(self._get_text("menu.file.save_all", "Save All"))
        
        self._actions["toolbar_run"].setText(self._get_text("menu.simulation.run", "Run"))
        self._actions["toolbar_run"].setToolTip(self._get_text("menu.simulation.run", "Run Simulation"))
        
        self._actions["toolbar_stop"].setText(self._get_text("btn.stop", "Stop"))
        self._actions["toolbar_stop"].setToolTip(self._get_text("menu.simulation.stop", "Stop Simulation"))
        
        self._actions["toolbar_undo"].setText(self._get_text("menu.edit.undo", "Undo"))
        self._actions["toolbar_undo"].setToolTip(self._get_text("menu.edit.undo", "Undo"))
        
        self._actions["toolbar_redo"].setText(self._get_text("menu.edit.redo", "Redo"))
        self._actions["toolbar_redo"].setToolTip(self._get_text("menu.edit.redo", "Redo"))

    def get_action(self, name: str) -> Optional[QAction]:
        """
        获取指定动作对象
        
        Args:
            name: 动作名称
            
        Returns:
            QAction 对象，不存在则返回 None
        """
        return self._actions.get(name)

    def set_action_enabled(self, name: str, enabled: bool) -> None:
        """
        设置动作启用状态
        
        Args:
            name: 动作名称
            enabled: 是否启用
        """
        action = self._actions.get(name)
        if action:
            action.setEnabled(enabled)

    def get_toolbar(self) -> Optional[QToolBar]:
        """
        获取工具栏对象
        
        Returns:
            QToolBar 对象
        """
        return self._toolbar


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ToolbarManager",
]
