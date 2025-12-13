# Statusbar Manager - Centralized Status Bar Management
"""
状态栏管理器 - 集中管理状态栏的多分区布局和状态更新

职责：
- 创建状态栏多分区布局
- 管理任务状态、迭代信息、Worker 状态的显示
- 刷新状态栏文本（国际化支持）

设计原则：
- 状态栏文本使用 i18n_manager.get_text("status.xxx") 获取

被调用方：main_window.py
"""

from typing import Optional

from PyQt6.QtWidgets import QMainWindow, QStatusBar, QLabel
from PyQt6.QtCore import Qt


class StatusbarManager:
    """
    状态栏管理器
    
    集中管理状态栏的多分区布局和状态更新。
    """

    def __init__(self, main_window: QMainWindow):
        """
        初始化状态栏管理器
        
        Args:
            main_window: 主窗口引用
        """
        self._main_window = main_window
        self._statusbar: Optional[QStatusBar] = None
        
        # 状态栏组件
        self._status_label: Optional[QLabel] = None      # 左侧：任务状态
        self._iteration_label: Optional[QLabel] = None   # 中间：迭代信息
        self._worker_label: Optional[QLabel] = None      # 右侧：Worker 状态
        self._project_label: Optional[QLabel] = None     # 项目路径信息

    # ============================================================
    # 服务访问（通过主窗口）
    # ============================================================

    def _get_text(self, key: str, default: Optional[str] = None) -> str:
        """获取国际化文本"""
        if hasattr(self._main_window, '_get_text'):
            return self._main_window._get_text(key, default)
        return default if default else key

    # ============================================================
    # 核心方法
    # ============================================================

    def setup_statusbar(self) -> QStatusBar:
        """
        创建状态栏布局
        
        布局结构（多分区）：
        - 左侧：任务状态文本（如"就绪"、"运行中..."）
        - 中间：当前迭代信息（如"迭代 3/20"，阶段五显示）
        - 右侧：Worker 状态指示器（阶段三显示）
        
        Returns:
            创建的 QStatusBar 对象
        """
        self._statusbar = self._main_window.statusBar()
        
        # 左侧：任务状态文本
        self._status_label = QLabel()
        self._status_label.setMinimumWidth(200)
        self._statusbar.addWidget(self._status_label, 1)
        
        # 中间：当前迭代信息（阶段五显示）
        self._iteration_label = QLabel()
        self._iteration_label.setMinimumWidth(150)
        self._iteration_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._statusbar.addWidget(self._iteration_label)
        
        # 右侧：Worker 状态指示器（阶段三显示）
        self._worker_label = QLabel()
        self._worker_label.setMinimumWidth(100)
        self._worker_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._statusbar.addPermanentWidget(self._worker_label)
        
        return self._statusbar

    def retranslate_ui(self) -> None:
        """刷新状态栏文本"""
        # 如果状态标签当前显示的是默认文本，则更新
        if self._status_label:
            current_text = self._status_label.text()
            # 检查是否是默认状态文本
            if not current_text or current_text in ["Ready", "就绪", ""]:
                self._status_label.setText(self._get_text("status.ready", "Ready"))

    def set_status(self, text: str) -> None:
        """
        设置任务状态文本
        
        Args:
            text: 状态文本（如"就绪"、"运行中..."）
        """
        if self._status_label:
            self._status_label.setText(text)

    def set_status_key(self, key: str, default: Optional[str] = None) -> None:
        """
        使用国际化键设置任务状态文本
        
        Args:
            key: 国际化键（如 "status.ready"）
            default: 默认值
        """
        text = self._get_text(key, default)
        self.set_status(text)

    def set_iteration_info(self, iteration: int, total: int) -> None:
        """
        设置迭代信息
        
        Args:
            iteration: 当前迭代次数
            total: 总迭代次数
        """
        if self._iteration_label:
            iteration_text = self._get_text("workflow.iteration", "Iteration")
            self._iteration_label.setText(f"{iteration_text} {iteration}/{total}")

    def clear_iteration_info(self) -> None:
        """清除迭代信息"""
        if self._iteration_label:
            self._iteration_label.setText("")

    def set_worker_status(self, worker_type: str, status: str) -> None:
        """
        设置 Worker 状态指示
        
        Args:
            worker_type: Worker 类型（如 "llm", "simulation"）
            status: 状态（如 "idle", "running", "error"）
        """
        if self._worker_label:
            # 根据状态设置样式
            style = ""
            if status == "running":
                style = "color: #4CAF50;"  # 绿色
            elif status == "error":
                style = "color: #f44336;"  # 红色
            else:
                style = "color: #888;"     # 灰色
            
            self._worker_label.setStyleSheet(style)
            
            # 获取状态文本
            status_text = self._get_text(f"status.{status}", status)
            self._worker_label.setText(f"{worker_type}: {status_text}")

    def clear_worker_status(self) -> None:
        """清除 Worker 状态"""
        if self._worker_label:
            self._worker_label.setText("")
            self._worker_label.setStyleSheet("")

    def set_project_info(self, path: Optional[str]) -> None:
        """
        设置项目路径信息
        
        Args:
            path: 项目路径，None 表示无项目
        """
        if self._status_label:
            if path:
                workspace_text = self._get_text("status.workspace", "Workspace")
                self._status_label.setText(f"{workspace_text}: {path}")
            else:
                self._status_label.setText(
                    self._get_text("status.no_project", "No project opened")
                )

    def get_statusbar(self) -> Optional[QStatusBar]:
        """
        获取状态栏对象
        
        Returns:
            QStatusBar 对象
        """
        return self._statusbar

    def get_status_label(self) -> Optional[QLabel]:
        """获取状态标签"""
        return self._status_label

    def get_iteration_label(self) -> Optional[QLabel]:
        """获取迭代信息标签"""
        return self._iteration_label

    def get_worker_label(self) -> Optional[QLabel]:
        """获取 Worker 状态标签"""
        return self._worker_label


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "StatusbarManager",
]
