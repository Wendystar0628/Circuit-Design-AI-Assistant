# Iteration History Dialog - Design Iteration History Viewer
"""
迭代历史记录对话框

职责：
- 展示完整的优化迭代历史记录
- 支持查看迭代详情（参数变化、性能指标、LLM 反馈）
- 支持恢复到指定迭代检查点

与对话历史对话框的区别：
- history_dialog.py（阶段3）：对话会话历史，管理 LLM 对话记录
- iteration_history_dialog.py（本文件）：设计迭代历史，管理电路优化检查点

被调用方：
- main_window.py（设计菜单 → 查看迭代历史）
- simulation_tab.py（查看历史按钮）
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QPushButton,
    QLabel,
    QGroupBox,
    QWidget,
    QHeaderView,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt

from domain.services import snapshot_service


@dataclass
class IterationRecord:
    """迭代记录"""
    snapshot_id: str
    iteration_count: int
    timestamp: str
    overall_score: float
    status: str  # "completed" | "restored"
    metrics_summary: Dict[str, float]
    parameter_changes: Dict[str, Any]
    llm_feedback: str


class IterationHistoryDialog(QDialog):
    """
    迭代历史记录对话框
    
    功能：
    - 显示所有迭代检查点列表
    - 查看迭代详情（参数变化、性能指标）
    - 恢复到指定检查点
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self._i18n_manager = None
        self._event_bus = None
        self._logger = None
        
        self._iterations: List[IterationRecord] = []
        self._current_snapshot_id: Optional[str] = None
        self._project_root: Optional[str] = None
        
        self._history_table: Optional[QTableWidget] = None
        self._detail_text: Optional[QTextEdit] = None
        self._close_btn: Optional[QPushButton] = None
        
        self._setup_dialog()
        self._setup_ui()
        self.retranslate_ui()
        self._subscribe_events()

    @property
    def i18n_manager(self):
        if self._i18n_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_I18N_MANAGER
                self._i18n_manager = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            except Exception:
                pass
        return self._i18n_manager

    @property
    def event_bus(self):
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus

    @property
    def logger(self):
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("iteration_history_dialog")
            except Exception:
                pass
        return self._logger

    def _get_text(self, key: str, default: Optional[str] = None) -> str:
        if self.i18n_manager:
            return self.i18n_manager.get_text(key, default)
        return default if default else key

    def _setup_dialog(self):
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setMinimumSize(900, 600)
        self.resize(1000, 700)
        self.setModal(True)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        left_widget = self._create_history_table_widget()
        splitter.addWidget(left_widget)
        
        right_widget = self._create_detail_widget()
        splitter.addWidget(right_widget)
        
        splitter.setSizes([400, 600])
        main_layout.addWidget(splitter, 1)
        main_layout.addWidget(self._create_button_area())

    def _create_history_table_widget(self) -> QWidget:
        group = QGroupBox()
        group.setProperty("group_type", "history_list")
        layout = QVBoxLayout(group)
        
        self._history_table = QTableWidget()
        self._history_table.setColumnCount(4)
        self._history_table.setHorizontalHeaderLabels(["#", "时间", "评分", "状态"])
        self._history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._history_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._history_table.setAlternatingRowColors(True)
        self._history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._history_table.verticalHeader().setVisible(False)
        
        header = self._history_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._history_table.setColumnWidth(0, 50)
        self._history_table.setColumnWidth(2, 80)
        self._history_table.setColumnWidth(3, 80)
        
        self._history_table.itemSelectionChanged.connect(self._on_selection_changed)
        
        layout.addWidget(self._history_table)
        return group

    def _create_detail_widget(self) -> QWidget:
        group = QGroupBox()
        group.setProperty("group_type", "iteration_detail")
        layout = QVBoxLayout(group)
        
        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setStyleSheet("""
            QTextEdit {
                background-color: #fafafa;
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 8px;
                font-family: "JetBrains Mono", "Cascadia Code", "Consolas", monospace;
                font-size: 13px;
            }
        """)
        layout.addWidget(self._detail_text)
        return group

    def _create_button_area(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 10, 0, 0)
        
        layout.addStretch()
        
        self._close_btn = QPushButton()
        self._close_btn.clicked.connect(self.accept)
        layout.addWidget(self._close_btn)
        
        return widget

    def load_history(self, project_root: str) -> None:
        """加载迭代历史"""
        self._project_root = project_root
        self._iterations.clear()
        self._history_table.setRowCount(0)
        
        snapshots = snapshot_service.list_snapshots(project_root)
        regular_snapshots = [s for s in snapshots if not s.snapshot_id.startswith("_")]
        
        for snapshot in regular_snapshots:
            try:
                created_at = datetime.fromisoformat(snapshot.timestamp) if snapshot.timestamp else datetime.now()
            except ValueError:
                created_at = datetime.now()
            
            record = IterationRecord(
                snapshot_id=snapshot.snapshot_id,
                iteration_count=snapshot.iteration_count,
                timestamp=created_at.strftime("%Y-%m-%d %H:%M:%S"),
                overall_score=snapshot.overall_score if hasattr(snapshot, 'overall_score') else 0.0,
                status="completed",
                metrics_summary=snapshot.metrics_summary if hasattr(snapshot, 'metrics_summary') else {},
                parameter_changes={},
                llm_feedback="",
            )
            self._iterations.append(record)
        
        self._populate_table()
        
        if self.logger:
            self.logger.info(f"Loaded {len(self._iterations)} iteration records")

    def _populate_table(self):
        self._history_table.setRowCount(len(self._iterations))
        
        for row, record in enumerate(self._iterations):
            iter_item = QTableWidgetItem(str(record.iteration_count))
            iter_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            iter_item.setData(Qt.ItemDataRole.UserRole, record.snapshot_id)
            self._history_table.setItem(row, 0, iter_item)
            
            time_item = QTableWidgetItem(record.timestamp)
            self._history_table.setItem(row, 1, time_item)
            
            score_item = QTableWidgetItem(f"{record.overall_score:.1f}%")
            score_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._history_table.setItem(row, 2, score_item)
            
            status_text = self._get_text(f"iteration.status.{record.status}", record.status)
            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._history_table.setItem(row, 3, status_item)

    def _show_iteration_detail(self, snapshot_id: str):
        self._current_snapshot_id = snapshot_id
        
        record = next((r for r in self._iterations if r.snapshot_id == snapshot_id), None)
        if not record:
            self._detail_text.clear()
            return
        
        html = self._format_detail_html(record)
        self._detail_text.setHtml(html)

    def _format_detail_html(self, record: IterationRecord) -> str:
        html_parts = [
            f"<h3>{self._get_text('iteration.detail.title', '迭代详情')} #{record.iteration_count}</h3>",
            f"<p><b>{self._get_text('iteration.detail.time', '时间')}:</b> {record.timestamp}</p>",
            f"<p><b>{self._get_text('iteration.detail.score', '综合评分')}:</b> {record.overall_score:.1f}%</p>",
        ]
        
        if record.metrics_summary:
            html_parts.append(f"<h4>{self._get_text('iteration.detail.metrics', '性能指标')}</h4>")
            html_parts.append("<ul>")
            for name, value in record.metrics_summary.items():
                html_parts.append(f"<li><b>{name}:</b> {value}</li>")
            html_parts.append("</ul>")
        
        if record.parameter_changes:
            html_parts.append(f"<h4>{self._get_text('iteration.detail.params', '参数变化')}</h4>")
            html_parts.append("<ul>")
            for name, change in record.parameter_changes.items():
                html_parts.append(f"<li><b>{name}:</b> {change}</li>")
            html_parts.append("</ul>")
        
        if record.llm_feedback:
            html_parts.append(f"<h4>{self._get_text('iteration.detail.feedback', 'LLM 反馈')}</h4>")
            html_parts.append(f"<p>{record.llm_feedback}</p>")
        
        return "".join(html_parts)

    def _on_selection_changed(self):
        selected = self._history_table.selectedItems()
        if not selected:
            self._detail_text.clear()
            return
        
        row = selected[0].row()
        snapshot_id = self._history_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        self._show_iteration_detail(snapshot_id)

    def retranslate_ui(self):
        self.setWindowTitle(self._get_text("dialog.iteration_history.title", "迭代历史记录"))
        
        for group in self.findChildren(QGroupBox):
            group_type = group.property("group_type")
            if group_type == "history_list":
                group.setTitle(self._get_text("dialog.iteration_history.list", "迭代列表"))
            elif group_type == "iteration_detail":
                group.setTitle(self._get_text("dialog.iteration_history.detail", "迭代详情"))
        
        if self._history_table:
            self._history_table.setHorizontalHeaderLabels([
                self._get_text("iteration.column.number", "#"),
                self._get_text("iteration.column.time", "时间"),
                self._get_text("iteration.column.score", "评分"),
                self._get_text("iteration.column.status", "状态"),
            ])
        if self._close_btn:
            self._close_btn.setText(self._get_text("btn.close", "关闭"))

    def _subscribe_events(self):
        if self.event_bus:
            from shared.event_types import EVENT_LANGUAGE_CHANGED
            self.event_bus.subscribe(EVENT_LANGUAGE_CHANGED, self._on_language_changed)

    def _unsubscribe_events(self):
        if self.event_bus:
            from shared.event_types import EVENT_LANGUAGE_CHANGED
            self.event_bus.unsubscribe(EVENT_LANGUAGE_CHANGED, self._on_language_changed)

    def _on_language_changed(self, event_data: Dict[str, Any]):
        self.retranslate_ui()

    def closeEvent(self, event) -> None:
        self._unsubscribe_events()
        super().closeEvent(event)


__all__ = ["IterationHistoryDialog", "IterationRecord"]
