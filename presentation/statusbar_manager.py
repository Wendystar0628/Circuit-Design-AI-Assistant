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
        self._rag_label: Optional[QLabel] = None         # RAG 状态指示
        self._worker_label: Optional[QLabel] = None      # 右侧：Worker 状态
        self._project_label: Optional[QLabel] = None     # 项目路径信息
        
        # 事件订阅
        self._subscriptions = []

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
        
        # RAG 状态指示（点击可切换到知识库 Tab）
        self._rag_label = QLabel()
        self._rag_label.setMinimumWidth(80)
        self._rag_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rag_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rag_label.setVisible(False)  # 默认隐藏，RAG 开启后显示
        self._rag_label.mousePressEvent = self._on_rag_label_clicked
        self._statusbar.addPermanentWidget(self._rag_label)
        
        # 右侧：Worker 状态指示器（阶段三显示）
        self._worker_label = QLabel()
        self._worker_label.setMinimumWidth(100)
        self._worker_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._statusbar.addPermanentWidget(self._worker_label)
        
        # 订阅 RAG 事件
        self._subscribe_rag_events()
        
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

    # ============================================================
    # RAG 状态指示
    # ============================================================

    def _subscribe_rag_events(self):
        """订阅 RAG 相关事件（RAG 是项目原生能力，无开关）"""
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_EVENT_BUS
            from shared.event_types import (
                EVENT_RAG_INIT_COMPLETE,
                EVENT_RAG_INDEX_STARTED,
                EVENT_RAG_INDEX_PROGRESS,
                EVENT_RAG_INDEX_COMPLETE,
                EVENT_STATE_PROJECT_OPENED,
                EVENT_STATE_PROJECT_CLOSED,
            )
            eb = ServiceLocator.get_optional(SVC_EVENT_BUS)
            if not eb:
                return
            for evt, handler in [
                (EVENT_STATE_PROJECT_OPENED, self._on_rag_project_opened),
                (EVENT_STATE_PROJECT_CLOSED, self._on_rag_project_closed),
                (EVENT_RAG_INIT_COMPLETE, self._on_rag_init_complete),
                (EVENT_RAG_INDEX_STARTED, self._on_rag_index_started),
                (EVENT_RAG_INDEX_PROGRESS, self._on_rag_index_progress),
                (EVENT_RAG_INDEX_COMPLETE, self._on_rag_index_complete),
            ]:
                eb.subscribe(evt, handler)
                self._subscriptions.append((evt, handler))
        except Exception:
            pass

    def _on_rag_project_opened(self, data):
        """项目打开 → 显示 RAG 标签（RAG 自动激活）"""
        if self._rag_label:
            self._rag_label.setVisible(True)
            self._rag_label.setText("RAG")
            self._rag_label.setStyleSheet(
                "color: #1565c0; font-size: 11px; padding: 1px 6px; "
                "background: #e3f2fd; border-radius: 3px;"
            )

    def _on_rag_init_complete(self, event_data):
        """RAG 初始化完成 → 显示就绪或错误"""
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        status = data.get("status", "") if isinstance(data, dict) else ""
        if self._rag_label:
            if status == "ready":
                self._rag_label.setText("RAG")
                self._rag_label.setStyleSheet(
                    "color: #2e7d32; font-size: 11px; padding: 1px 6px; "
                    "background: #e8f5e9; border-radius: 3px;"
                )
            elif status == "error":
                self._rag_label.setText("RAG ✗")
                self._rag_label.setStyleSheet(
                    "color: #c62828; font-size: 11px; padding: 1px 6px; "
                    "background: #ffebee; border-radius: 3px;"
                )

    def _on_rag_project_closed(self, data):
        """项目关闭 → 隐藏 RAG 标签"""
        if self._rag_label:
            self._rag_label.setVisible(False)

    def _on_rag_index_started(self, event_data):
        """RAG 索引开始"""
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        if self._rag_label:
            self._rag_label.setVisible(True)
            total = data.get("total_files", 0) if isinstance(data, dict) else 0
            self._rag_label.setText(f"索引中 0/{total}")
            self._rag_label.setStyleSheet(
                "color: #1565c0; font-size: 11px; padding: 1px 6px; "
                "background: #e3f2fd; border-radius: 3px;"
            )

    def _on_rag_index_progress(self, event_data):
        """RAG 索引进度"""
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        if self._rag_label and isinstance(data, dict):
            p = data.get("processed", 0)
            t = data.get("total", 0)
            self._rag_label.setText(f"索引中 {p}/{t}")

    def _on_rag_index_complete(self, event_data):
        """RAG 索引完成"""
        if self._rag_label:
            self._rag_label.setText("RAG")
            self._rag_label.setStyleSheet(
                "color: #2e7d32; font-size: 11px; padding: 1px 6px; "
                "background: #e8f5e9; border-radius: 3px;"
            )

    def _on_rag_label_clicked(self, event):
        """点击 RAG 标签切换到知识库 Tab"""
        try:
            from presentation.core.tab_controller import TAB_RAG
            tc = getattr(self._main_window, 'tab_controller', None)
            if tc:
                tc.switch_to_tab(TAB_RAG)
        except Exception:
            pass

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
