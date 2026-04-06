# RAG Panel - 知识库管理标签页
"""
知识库管理面板 - 与「对话」「调试」并列的顶层 Tab

设计理念：
    RAG 是项目的原生能力，无手动开关。
    打开项目 → 自动初始化 + 自动索引 → AI 智能检索。
    本面板仅用于监控状态和手动触发重新索引。

职责：
- 显示 RAG 自动状态（初始化中、已就绪、索引中、错误）
- 索引进度实时展示
- 已索引文档列表
- 手动重新索引 / 清空知识库
- 检索测试区（折叠）

位置：右栏标签页之一
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar,
    QTreeWidget, QTreeWidgetItem, QHeaderView,
    QTextEdit, QGroupBox,
    QAbstractItemView, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSlot, QTimer

from shared.event_types import (
    EVENT_RAG_INIT_COMPLETE,
    EVENT_RAG_INDEX_STARTED,
    EVENT_RAG_INDEX_PROGRESS,
    EVENT_RAG_INDEX_COMPLETE,
    EVENT_RAG_INDEX_ERROR,
)


logger = logging.getLogger(__name__)


# ============================================================
# 状态颜色映射
# ============================================================

STATUS_COLORS = {
    "processed": "#4CAF50",   # 绿
    "processing": "#2196F3",  # 蓝
    "failed": "#F44336",      # 红
    "excluded": "#FB8C00",    # 橙
    "pending": "#9E9E9E",     # 灰
}

STATUS_LABELS = {
    "processed": "已索引",
    "processing": "索引中",
    "failed": "失败",
    "excluded": "排除索引",
    "pending": "待索引",
}


# ============================================================
# RAGPanel
# ============================================================

class RAGPanel(QWidget):
    """
    知识库管理面板

    RAG 是项目原生能力，无手动开关。
    本面板显示自动状态、索引进度、文档列表，并提供手动重索引。
    """

    def __init__(self, event_bus=None, rag_manager=None, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._event_bus = event_bus
        self._rag_manager = rag_manager
        self._subscriptions: List[tuple] = []

        # 状态
        self._is_indexing = False

        # 初始化 UI
        self._init_ui()
        self._connect_signals()
        self._subscribe_events()

        # 延迟刷新初始状态
        QTimer.singleShot(500, self._refresh_state)

    # ============================================================
    # 延迟获取服务
    # ============================================================

    @property
    def event_bus(self):
        return self._event_bus

    @property
    def rag_manager(self):
        return self._rag_manager

    def bind_services(self, event_bus=None, rag_manager=None) -> None:
        """在延迟初始化完成后补绑定服务依赖。"""
        if event_bus is not None and event_bus is not self._event_bus:
            self._event_bus = event_bus
            self._subscribe_events()

        if rag_manager is not None:
            self._rag_manager = rag_manager

        self._refresh_state()

    # ============================================================
    # UI 初始化
    # ============================================================

    def _init_ui(self):
        """初始化 UI 布局"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # ---- 1. 顶栏：标题 + 状态 ----
        layout.addLayout(self._create_top_bar())

        # ---- 2. 统计概览 ----
        self._stats_label = QLabel("文档: 0  |  分块: 0  |  排除: 0  |  实体: 0  |  关系: 0")
        self._stats_label.setStyleSheet("color: #666; font-size: 12px; padding: 4px 0;")
        layout.addWidget(self._stats_label)

        # ---- 3. 索引操作区 ----
        layout.addLayout(self._create_index_actions())

        # ---- 4. 进度条（默认隐藏） ----
        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximum(100)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setVisible(False)
        self._progress_bar.setFixedHeight(18)
        layout.addWidget(self._progress_bar)

        # ---- 5. 已索引文档列表 ----
        layout.addWidget(self._create_file_list(), 1)

        # ---- 6. 检索测试区（折叠） ----
        layout.addWidget(self._create_search_test_group())

        # ---- 7. 底部信息 ----
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color: #999; font-size: 11px;")
        layout.addWidget(self._info_label)

    def _create_top_bar(self) -> QHBoxLayout:
        """创建顶栏：标题 + 状态标签"""
        bar = QHBoxLayout()

        title = QLabel("索引库")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        bar.addWidget(title)

        bar.addStretch()

        self._status_label = QLabel("等待项目")
        self._status_label.setStyleSheet(
            "color: #999; font-size: 12px; padding: 2px 8px; "
            "background: #f0f0f0; border-radius: 4px;"
        )
        bar.addWidget(self._status_label)

        return bar

    def _create_index_actions(self) -> QHBoxLayout:
        """创建索引操作按钮"""
        actions = QHBoxLayout()

        self._btn_index = QPushButton("索引项目文件")
        self._btn_index.setEnabled(False)
        self._btn_index.setStyleSheet(self._action_btn_style())
        actions.addWidget(self._btn_index)

        self._btn_clear = QPushButton("清空索引库")
        self._btn_clear.setEnabled(False)
        self._btn_clear.setStyleSheet(self._action_btn_style("#e53935", "#c62828"))
        actions.addWidget(self._btn_clear)

        actions.addStretch()

        return actions

    def _create_file_list(self) -> QTreeWidget:
        """创建已索引文档列表"""
        tree = QTreeWidget()
        tree.setHeaderLabels(["文件", "状态", "分块", "索引时间"])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tree.setStyleSheet("""
            QTreeWidget { border: 1px solid #ddd; border-radius: 4px; font-size: 12px; }
            QTreeWidget::item { padding: 3px 0; }
            QHeaderView::section {
                background: #f5f5f5; border: none; border-bottom: 1px solid #ddd;
                padding: 4px 8px; font-size: 11px; font-weight: bold;
            }
        """)

        header = tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(1, 60)
        header.resizeSection(2, 50)
        header.resizeSection(3, 130)

        self._file_tree = tree
        return tree

    def _create_search_test_group(self) -> QGroupBox:
        """创建检索测试区（可折叠）"""
        group = QGroupBox("检索测试")
        group.setCheckable(True)
        group.setChecked(False)  # 默认折叠
        group.setStyleSheet("""
            QGroupBox {
                font-size: 12px; font-weight: bold; border: 1px solid #ddd;
                border-radius: 4px; margin-top: 6px; padding-top: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px; padding: 0 4px;
            }
        """)

        inner = QVBoxLayout(group)
        inner.setContentsMargins(8, 4, 8, 8)
        inner.setSpacing(6)

        # 查询输入
        row = QHBoxLayout()
        self._search_input = QTextEdit()
        self._search_input.setPlaceholderText("输入检索内容...")
        self._search_input.setMaximumHeight(50)
        row.addWidget(self._search_input, 1)

        self._btn_search = QPushButton("检索")
        self._btn_search.setFixedWidth(50)
        self._btn_search.setStyleSheet(self._action_btn_style())
        row.addWidget(self._btn_search)

        inner.addLayout(row)

        # 结果区
        self._search_result = QTextEdit()
        self._search_result.setReadOnly(True)
        self._search_result.setMaximumHeight(150)
        self._search_result.setPlaceholderText("检索结果将显示在此处")
        self._search_result.setStyleSheet("font-size: 12px; border: 1px solid #eee; border-radius: 4px;")
        inner.addWidget(self._search_result)

        # 折叠内容可见性联动
        self._search_test_content = [self._search_input, self._btn_search, self._search_result]
        group.toggled.connect(self._on_search_group_toggled)
        # 初始折叠隐藏内容
        for w in self._search_test_content:
            w.setVisible(False)

        return group

    # ============================================================
    # 信号连接
    # ============================================================

    def _connect_signals(self):
        """连接按钮信号"""
        self._btn_index.clicked.connect(self._on_index_clicked)
        self._btn_clear.clicked.connect(self._on_clear_clicked)
        self._btn_search.clicked.connect(self._on_search_clicked)

    # ============================================================
    # 事件订阅
    # ============================================================

    def _subscribe_events(self):
        """订阅 RAG 事件和项目生命周期事件"""
        eb = self.event_bus
        if not eb:
            return

        from shared.event_types import (
            EVENT_STATE_PROJECT_OPENED,
            EVENT_STATE_PROJECT_CLOSED,
        )

        subs = [
            (EVENT_RAG_INIT_COMPLETE, self._on_init_complete),
            (EVENT_RAG_INDEX_STARTED, self._on_index_started),
            (EVENT_RAG_INDEX_PROGRESS, self._on_index_progress),
            (EVENT_RAG_INDEX_COMPLETE, self._on_index_complete),
            (EVENT_RAG_INDEX_ERROR, self._on_index_error),
            (EVENT_STATE_PROJECT_OPENED, self._on_project_opened),
            (EVENT_STATE_PROJECT_CLOSED, self._on_project_closed),
        ]
        for event_type, handler in subs:
            eb.subscribe(event_type, handler)
            self._subscriptions.append((event_type, handler))

    # ============================================================
    # 事件处理
    # ============================================================

    def _on_init_complete(self, event_data):
        """RAG 服务初始化完成 → 刷新整个面板"""
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        status = data.get("status", "") if isinstance(data, dict) else ""
        if status == "ready":
            self._refresh_state()
        elif status == "error":
            error = data.get("error", "") if isinstance(data, dict) else ""
            self._status_label.setText("初始化失败")
            self._status_label.setStyleSheet(
                "color: #c62828; font-size: 12px; padding: 2px 8px; "
                "background: #ffebee; border-radius: 4px;"
            )
            self._info_label.setText(error)
            self._info_label.setStyleSheet("color: #c62828; font-size: 11px;")
            self._update_action_buttons()

    def _on_index_started(self, event_data):
        """索引开始"""
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        self._is_indexing = True
        total = data.get("total_files", 0) if isinstance(data, dict) else 0
        self._progress_bar.setMaximum(max(total, 1))
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        self._status_label.setText(f"索引中 0/{total}")
        self._status_label.setStyleSheet(
            "color: #1565c0; font-size: 12px; padding: 2px 8px; "
            "background: #e3f2fd; border-radius: 4px;"
        )
        self._btn_index.setEnabled(False)

    def _on_index_progress(self, event_data):
        """索引进度更新"""
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        if not isinstance(data, dict):
            return
        processed = data.get("processed", 0)
        total = data.get("total", 0)
        current = data.get("current_file", "")
        self._progress_bar.setMaximum(max(total, 1))
        self._progress_bar.setValue(processed)
        self._status_label.setText(f"索引中 {processed}/{total}")
        if current:
            self._info_label.setText(f"正在处理: {current}")

    def _on_index_complete(self, event_data):
        """索引完成（包含无需索引的情况）"""
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        self._is_indexing = False
        self._progress_bar.setVisible(False)
        self._update_action_buttons()

        if isinstance(data, dict):
            total = data.get("total_indexed", 0)
            failed = data.get("failed", 0)
            duration = data.get("duration_s", 0)
            up_to_date = data.get("already_up_to_date", False)

            # 更新状态标签：显示已索引的总文件数（从 index_meta 读取）
            self._update_status_ready()

            if up_to_date:
                self._info_label.setText("索引已是最新")
                self._info_label.setStyleSheet("color: #999; font-size: 11px;")
            elif failed > 0:
                self._info_label.setText(f"索引完成：{total} 成功，{failed} 失败，耗时 {duration:.1f}s")
                self._info_label.setStyleSheet("color: #999; font-size: 11px;")
            else:
                self._info_label.setText(f"索引完成：{total} 文件，耗时 {duration:.1f}s")
                self._info_label.setStyleSheet("color: #999; font-size: 11px;")

        self._refresh_file_list()
        self._refresh_stats()

    def _on_index_error(self, event_data):
        """索引错误"""
        data = event_data.get("data", event_data) if isinstance(event_data, dict) else event_data
        if isinstance(data, dict):
            error = data.get("error", "")
            fp = data.get("file_path", "")
            msg = f"错误: {error}" if not fp else f"错误 ({fp}): {error}"
            self._info_label.setText(msg)
            self._info_label.setStyleSheet("color: #c62828; font-size: 11px;")

    def _on_project_opened(self, data):
        """项目打开 → 显示初始化状态（等待 INIT_COMPLETE 事件刷新）"""
        self._info_label.setText("")
        self._info_label.setStyleSheet("color: #999; font-size: 11px;")
        self._file_tree.clear()
        self._stats_label.setText("文档: 0  |  分块: 0  |  排除: 0  |  实体: 0  |  关系: 0")
        self._status_label.setText("初始化中...")
        self._status_label.setStyleSheet(
            "color: #1565c0; font-size: 12px; padding: 2px 8px; "
            "background: #e3f2fd; border-radius: 4px;"
        )
        self._update_action_buttons()

    def _on_project_closed(self, data):
        """项目关闭 → 重置面板状态"""
        self._is_indexing = False
        self._file_tree.clear()
        self._stats_label.setText("文档: 0  |  分块: 0  |  排除: 0  |  实体: 0  |  关系: 0")
        self._info_label.setText("")
        self._progress_bar.setVisible(False)
        self._update_status_label()
        self._update_action_buttons()

    # ============================================================
    # 按钮处理
    # ============================================================

    def _on_index_clicked(self):
        """手动重新索引项目文件（提交到工作线程，不阻塞 UI）"""
        manager = self.rag_manager
        if not manager or not manager.is_available:
            return
        manager.trigger_index()

    def _on_clear_clicked(self):
        """清空知识库"""
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "清空索引库",
            "确定要清空当前项目的索引库吗？\n已索引的内容将被全部删除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        manager = self.rag_manager
        if not manager:
            return

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._async_clear())
        except RuntimeError:
            logger.warning("No event loop for clear")

    async def _async_clear(self):
        """异步清空知识库（清空操作在工作线程执行）"""
        manager = self.rag_manager
        if not manager:
            return
        try:
            await manager.clear_index_async()
            self._file_tree.clear()
            self._stats_label.setText("文档: 0  |  分块: 0  |  排除: 0  |  实体: 0  |  关系: 0")
            self._info_label.setText("索引库已清空")
        except Exception as e:
            self._info_label.setText(f"清空失败: {e}")
            logger.error(f"Failed to clear RAG index: {e}")

    def _on_search_clicked(self):
        """检索测试"""
        query = self._search_input.toPlainText().strip()
        if not query:
            return

        manager = self.rag_manager
        if not manager or not manager.is_available:
            self._search_result.setPlainText("索引库未就绪（请等待初始化完成）")
            return

        self._search_result.setPlainText("检索中...")
        self._btn_search.setEnabled(False)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._async_search(query))
        except RuntimeError:
            self._search_result.setPlainText("无可用事件循环")
            self._btn_search.setEnabled(True)

    async def _async_search(self, query: str):
        """异步执行检索（查询在工作线程执行，主线程通过 wrap_future await）"""
        manager = self.rag_manager
        try:
            result = await manager.query_async(query)
            if result.is_empty:
                text = f"未找到与 \"{query}\" 相关的内容"
            else:
                text = result.format_as_context(max_tokens=3000)
                summary = f"片段: {result.chunks_count}\n\n"
                text = summary + text
            self._search_result.setPlainText(text)
        except Exception as e:
            self._search_result.setPlainText(f"检索失败: {e}")
        finally:
            self._btn_search.setEnabled(True)

    def _on_search_group_toggled(self, checked: bool):
        """检索测试区折叠/展开"""
        for w in self._search_test_content:
            w.setVisible(checked)

    # ============================================================
    # 可见性刷新
    # ============================================================

    def showEvent(self, event):
        """面板变为可见时刷新状态（Tab 切换等场景）"""
        super().showEvent(event)
        QTimer.singleShot(0, self._refresh_state)

    # ============================================================
    # 状态刷新
    # ============================================================

    def _refresh_state(self):
        """从 RAGManager 同步当前状态"""
        manager = self.rag_manager
        if manager:
            self._is_indexing = manager.is_indexing
        self._update_status_label()
        self._update_action_buttons()
        self._refresh_file_list()
        self._refresh_stats()

    def _update_status_ready(self):
        """将状态标签更新为「已就绪 (N 文件)」"""
        manager = self.rag_manager
        total_files = 0
        if manager:
            try:
                status = manager.get_index_status()
                total_files = status.stats.total_files if hasattr(status, "stats") else 0
            except Exception:
                pass
        self._status_label.setText(f"已就绪 ({total_files} 文件)")
        self._status_label.setStyleSheet(
            "color: #2e7d32; font-size: 12px; padding: 2px 8px; "
            "background: #e8f5e9; border-radius: 4px;"
        )

    def _update_status_label(self):
        """更新状态标签（无开关，全自动）"""
        manager = self.rag_manager

        if not manager or not manager.project_root:
            self._status_label.setText("等待项目")
            self._status_label.setStyleSheet(
                "color: #999; font-size: 12px; padding: 2px 8px; "
                "background: #f0f0f0; border-radius: 4px;"
            )
            return

        if self._is_indexing:
            return  # 索引中的状态由事件处理器设置

        if manager.init_error:
            self._status_label.setText("初始化失败")
            self._status_label.setStyleSheet(
                "color: #c62828; font-size: 12px; padding: 2px 8px; "
                "background: #ffebee; border-radius: 4px;"
            )
            return

        if manager.is_available:
            self._update_status_ready()
        else:
            self._status_label.setText("初始化中...")
            self._status_label.setStyleSheet(
                "color: #1565c0; font-size: 12px; padding: 2px 8px; "
                "background: #e3f2fd; border-radius: 4px;"
            )

    def _update_action_buttons(self):
        """更新操作按钮可用状态"""
        manager = self.rag_manager
        can_act = bool(manager and manager.is_available and not self._is_indexing)
        self._btn_index.setEnabled(can_act)
        self._btn_clear.setEnabled(can_act)

    def _refresh_file_list(self):
        """从 RAGManager 刷新已索引文档列表"""
        self._file_tree.clear()
        manager = self.rag_manager
        if not manager:
            return

        try:
            status = manager.get_index_status()
            files = status.files if hasattr(status, "files") else []

            for f in files:
                path = f.relative_path if hasattr(f, "relative_path") else ""
                st = f.status if hasattr(f, "status") else "pending"
                chunks = str(f.chunks_count if hasattr(f, "chunks_count") else 0)
                indexed_at = f.indexed_at if hasattr(f, "indexed_at") else ""
                exclude_reason = f.exclude_reason if hasattr(f, "exclude_reason") else None
                error_text = f.error if hasattr(f, "error") else None

                item = QTreeWidgetItem([path, STATUS_LABELS.get(st, st), chunks, indexed_at])
                color = STATUS_COLORS.get(st, "#999")
                item.setForeground(1, __import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(color))
                if exclude_reason:
                    item.setToolTip(1, exclude_reason)
                    item.setToolTip(0, exclude_reason)
                elif error_text:
                    item.setToolTip(1, error_text)
                    item.setToolTip(0, error_text)
                self._file_tree.addTopLevelItem(item)

        except Exception as e:
            logger.debug(f"Failed to refresh file list: {e}")

    def _refresh_stats(self):
        """刷新统计概览"""
        manager = self.rag_manager
        if not manager:
            return

        try:
            status = manager.get_index_status()
            stats = status.stats if hasattr(status, "stats") else None
            if stats:
                self._stats_label.setText(
                    f"文档: {stats.total_files}  |  分块: {stats.total_chunks}  |  排除: {stats.excluded}  |  "
                    f"实体: {stats.total_entities}  |  关系: {stats.total_relations}"
                )
        except Exception as e:
            logger.debug(f"Failed to refresh stats: {e}")

    # ============================================================
    # 国际化
    # ============================================================

    def retranslate_ui(self):
        """国际化更新（预留）"""
        pass

    # ============================================================
    # 工具方法
    # ============================================================

    @staticmethod
    def _action_btn_style(bg: str = "#4a9eff", hover: str = "#1976d2") -> str:
        return f"""
            QPushButton {{
                background: {bg}; color: white; border: none;
                border-radius: 4px; padding: 5px 14px; font-size: 12px;
            }}
            QPushButton:hover {{ background: {hover}; }}
            QPushButton:disabled {{ background: #ccc; color: #999; }}
        """


# ============================================================
# 模块导出
# ============================================================

__all__ = ["RAGPanel"]
