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
        
        # ============================================================
        # 仿真按钮设计（阶段四实现）
        # ============================================================
        # 
        # **三层分离说明**：
        # - 按钮控制的是"文件选择方式"（自动扫描 vs 手动选择）
        # - 与"仿真执行方式"（SPICE vs Python）无关
        # - 系统根据选中文件的扩展名自动选择对应的执行器
        #
        # **两种仿真触发方式**：
        # - [▶ 自动运行] 按钮：使用 AutoScanStrategy 自动扫描并执行
        # - [📁 选择运行] 按钮：使用 ManualSelectStrategy 弹出对话框选择
        #
        # **按钮状态管理**：
        # - 仿真运行中两个运行按钮均禁用，停止按钮启用
        # - 工作流锁定时（workflow_locked = True）两个运行按钮均禁用
        # ============================================================
        
        # [▶ 自动运行] 按钮（阶段四实现中）
        # 点击时调用 simulation_service.run_with_auto_detect()
        # - 使用被引用分析法扫描项目中的可仿真文件
        # - 检测到唯一主电路时，直接启动仿真
        # - 检测到多个主电路时，自动弹出选择对话框让用户选择
        # - 适用场景：常规仿真运行，自动模式工作流中使用此方式
        self._actions["toolbar_run_auto"] = QAction(self._main_window)
        self._actions["toolbar_run_auto"].setIcon(self._load_icon("play"))
        # 保持启用状态以响应悬停和点击，点击时显示提示
        if "on_run_auto_simulation" in callbacks:
            self._actions["toolbar_run_auto"].triggered.connect(callbacks["on_run_auto_simulation"])
        self._toolbar.addAction(self._actions["toolbar_run_auto"])
        
        # [📁 选择运行] 按钮（阶段四实现中）
        # 点击时调用 simulation_service.run_with_manual_select()
        # - 弹出 select_simulation_file_dialog 对话框
        # - 对话框显示所有支持的文件类型（从 executor_registry 获取）
        # - 用户选择文件后，根据扩展名自动选择执行器并启动仿真
        # - 适用场景：用户希望明确指定仿真文件，或运行 Python 脚本
        self._actions["toolbar_run_select"] = QAction(self._main_window)
        self._actions["toolbar_run_select"].setIcon(self._load_icon("folder_play"))
        # 保持启用状态以响应悬停和点击，点击时显示提示
        if "on_run_select_simulation" in callbacks:
            self._actions["toolbar_run_select"].triggered.connect(callbacks["on_run_select_simulation"])
        self._toolbar.addAction(self._actions["toolbar_run_select"])
        
        # [停止] 按钮（阶段四实现中）
        self._actions["toolbar_stop"] = QAction(self._main_window)
        self._actions["toolbar_stop"].setIcon(self._load_icon("stop"))
        # 保持启用状态以响应悬停和点击，点击时显示提示
        if "on_stop_simulation" in callbacks:
            self._actions["toolbar_stop"].triggered.connect(callbacks["on_stop_simulation"])
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
        
        self._actions["toolbar_run_auto"].setText(self._get_text("toolbar.run_auto", "Auto Run"))
        self._actions["toolbar_run_auto"].setToolTip(self._get_text("toolbar.run_auto_tip", "Auto-detect main circuit and run simulation"))
        
        self._actions["toolbar_run_select"].setText(self._get_text("toolbar.run_select", "Select Run"))
        self._actions["toolbar_run_select"].setToolTip(self._get_text("toolbar.run_select_tip", "Select simulation file and run"))
        
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
