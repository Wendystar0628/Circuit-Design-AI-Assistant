# DevTools Panel - Tracing Visualization
"""
调试工具面板 - 追踪数据可视化

职责：
- 可视化展示追踪数据
- 辅助调试 LLM 调用、工具执行、工作流节点
- 提供性能分析和错误定位

位置：右栏标签页之一

设计原则：
- 通过 EventBus 订阅追踪事件实时更新，不轮询数据库
- 延迟获取 ServiceLocator 中的服务
- 实现 retranslate_ui() 方法支持语言切换
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QTextEdit,
    QPushButton, QComboBox, QLabel, QFileDialog,
    QHeaderView, QAbstractItemView, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QColor, QBrush, QFont

from shared.tracing.tracing_types import TraceStatus


# ============================================================
# 常量
# ============================================================

# 状态图标
STATUS_ICONS = {
    TraceStatus.SUCCESS: "✓",
    TraceStatus.ERROR: "✗",
    TraceStatus.RUNNING: "⟳",
    TraceStatus.CANCELLED: "⊘",
}

# 状态颜色
STATUS_COLORS = {
    TraceStatus.SUCCESS: QColor("#4CAF50"),  # 绿色
    TraceStatus.ERROR: QColor("#F44336"),    # 红色
    TraceStatus.RUNNING: QColor("#2196F3"),  # 蓝色
    TraceStatus.CANCELLED: QColor("#9E9E9E"), # 灰色
}

# 错误行背景色
ERROR_BG_COLOR = QColor("#FFEBEE")


# ============================================================
# DevToolsPanel
# ============================================================

class DevToolsPanel(QWidget):
    """
    调试工具面板
    
    提供追踪数据的可视化展示，帮助开发者调试和分析性能。
    """
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        # 服务引用（延迟获取）
        self._event_bus = None
        self._tracing_store = None
        self._i18n = None
        
        # 数据缓存
        self._traces: List[Dict[str, Any]] = []
        self._current_trace_id: Optional[str] = None
        self._current_span_id: Optional[str] = None
        
        # 初始化 UI
        self._init_ui()
        self._connect_signals()
        self._subscribe_events()
    
    # --------------------------------------------------------
    # UI 初始化
    # --------------------------------------------------------
    
    def _init_ui(self):
        """初始化 UI 布局"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 工具栏
        toolbar = self._create_toolbar()
        layout.addLayout(toolbar)
        
        # 主内容区（分割器）
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧：追踪树
        self._trace_tree = self._create_trace_tree()
        splitter.addWidget(self._trace_tree)
        
        # 右侧：详情面板
        self._detail_panel = self._create_detail_panel()
        splitter.addWidget(self._detail_panel)
        
        # 设置分割比例
        splitter.setSizes([300, 400])
        layout.addWidget(splitter, 1)
        
        # 底部：统计信息
        self._stats_label = QLabel()
        self._stats_label.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self._stats_label)
        
        # 初始化文本
        self._retranslate_ui()
    
    def _create_toolbar(self) -> QHBoxLayout:
        """创建工具栏"""
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        
        # 刷新按钮
        self._refresh_btn = QPushButton()
        self._refresh_btn.setFixedWidth(80)
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)
        toolbar.addWidget(self._refresh_btn)
        
        # 清除按钮
        self._clear_btn = QPushButton()
        self._clear_btn.setFixedWidth(80)
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        toolbar.addWidget(self._clear_btn)
        
        # 导出按钮
        self._export_btn = QPushButton()
        self._export_btn.setFixedWidth(80)
        self._export_btn.clicked.connect(self._on_export_clicked)
        toolbar.addWidget(self._export_btn)
        
        toolbar.addStretch()
        
        # 状态过滤器
        self._filter_label = QLabel()
        toolbar.addWidget(self._filter_label)
        
        self._status_filter = QComboBox()
        self._status_filter.setFixedWidth(120)
        self._status_filter.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._status_filter)
        
        return toolbar
    
    def _create_trace_tree(self) -> QTreeWidget:
        """创建追踪树"""
        tree = QTreeWidget()
        tree.setHeaderLabels(["Operation", "Duration", "Status"])
        tree.setColumnCount(3)
        tree.setAlternatingRowColors(True)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tree.itemClicked.connect(self._on_tree_item_clicked)
        
        # 设置列宽
        header = tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        tree.setColumnWidth(1, 80)
        tree.setColumnWidth(2, 60)
        
        return tree
    
    def _create_detail_panel(self) -> QTextEdit:
        """创建详情面板"""
        detail = QTextEdit()
        detail.setReadOnly(True)
        # 使用现代等宽字体
        font = QFont()
        for font_name in ["JetBrains Mono", "Cascadia Code", "SF Mono", "Consolas"]:
            font.setFamily(font_name)
            if font.exactMatch():
                break
        font.setPointSize(10)
        detail.setFont(font)
        detail.setStyleSheet("""
            QTextEdit {
                background-color: #FAFAFA;
                border: 1px solid #E0E0E0;
                border-radius: 4px;
            }
        """)
        return detail
    
    def _connect_signals(self):
        """连接信号"""
        pass  # 信号已在创建时连接
    
    def _subscribe_events(self):
        """订阅 EventBus 事件"""
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_EVENT_BUS
            from shared.tracing.tracing_events import TracingEvents
            from shared.event_types import EVENT_LANGUAGE_CHANGED
            
            self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            if self._event_bus:
                self._event_bus.subscribe(
                    TracingEvents.SPANS_FLUSHED, self._on_spans_flushed
                )
                self._event_bus.subscribe(
                    TracingEvents.SPAN_ERROR, self._on_span_error
                )
                self._event_bus.subscribe(
                    EVENT_LANGUAGE_CHANGED, self._on_language_changed
                )
        except Exception:
            pass
    
    # --------------------------------------------------------
    # 国际化
    # --------------------------------------------------------
    
    def _retranslate_ui(self):
        """更新 UI 文本（国际化）"""
        # 按钮
        self._refresh_btn.setText(self._tr("refresh", "刷新"))
        self._clear_btn.setText(self._tr("clear", "清除"))
        self._export_btn.setText(self._tr("export", "导出"))
        
        # 过滤器
        self._filter_label.setText(self._tr("filter", "过滤:"))
        
        # 更新过滤器选项
        current_index = self._status_filter.currentIndex()
        self._status_filter.clear()
        self._status_filter.addItem(self._tr("all", "全部"), None)
        self._status_filter.addItem(
            f"✓ {self._tr('success', '成功')}", TraceStatus.SUCCESS
        )
        self._status_filter.addItem(
            f"✗ {self._tr('error', '错误')}", TraceStatus.ERROR
        )
        self._status_filter.addItem(
            f"⟳ {self._tr('running', '运行中')}", TraceStatus.RUNNING
        )
        if current_index >= 0:
            self._status_filter.setCurrentIndex(current_index)
        
        # 统计标签
        self._update_stats_label()
    
    def _tr(self, key: str, default: str) -> str:
        """获取翻译文本"""
        if self._i18n is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_I18N_MANAGER
                self._i18n = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            except Exception:
                pass
        
        if self._i18n:
            return self._i18n.get_text(f"devtools.{key}", default)
        return default
    
    # --------------------------------------------------------
    # 数据加载
    # --------------------------------------------------------
    
    async def refresh(self):
        """从 TracingStore 加载最近的追踪数据"""
        store = self._get_tracing_store()
        if not store:
            return
        
        try:
            # 获取最近的追踪
            self._traces = await store.get_recent_traces(limit=50)
            
            # 更新树形视图
            self._update_trace_tree()
            
            # 更新统计
            stats = await store.get_stats(hours=24)
            self._update_stats(stats)
            
        except Exception as e:
            self._log_error(f"加载追踪数据失败: {e}")
    
    def _update_trace_tree(self):
        """更新追踪树形视图"""
        self._trace_tree.clear()
        
        # 获取当前过滤状态
        filter_status = self._status_filter.currentData()
        
        for trace in self._traces:
            # 应用过滤
            if filter_status is not None:
                if trace.get("has_error") and filter_status != TraceStatus.ERROR:
                    continue
                if not trace.get("has_error") and filter_status == TraceStatus.ERROR:
                    continue
            
            # 创建追踪节点
            trace_item = self._create_trace_item(trace)
            self._trace_tree.addTopLevelItem(trace_item)
    
    def _create_trace_item(self, trace: Dict[str, Any]) -> QTreeWidgetItem:
        """创建追踪树节点"""
        # 格式化时间
        start_time = trace.get("start_time", 0)
        time_str = datetime.fromtimestamp(start_time).strftime("%H:%M:%S")
        
        # 格式化耗时
        duration_ms = trace.get("duration_ms")
        duration_str = f"{duration_ms:.0f}ms" if duration_ms else "-"
        
        # 状态
        has_error = trace.get("has_error", False)
        status = TraceStatus.ERROR if has_error else TraceStatus.SUCCESS
        status_icon = STATUS_ICONS.get(status, "")
        
        # 创建节点
        item = QTreeWidgetItem([
            f"{time_str} {trace.get('root_operation', 'unknown')}",
            duration_str,
            status_icon,
        ])
        
        # 存储数据
        item.setData(0, Qt.ItemDataRole.UserRole, {
            "type": "trace",
            "trace_id": trace.get("trace_id"),
        })
        
        # 设置颜色
        color = STATUS_COLORS.get(status)
        if color:
            item.setForeground(2, QBrush(color))
        
        # 错误背景
        if has_error:
            for col in range(3):
                item.setBackground(col, QBrush(ERROR_BG_COLOR))
        
        # 添加 span 数量提示
        span_count = trace.get("span_count", 0)
        item.setToolTip(0, f"Trace ID: {trace.get('trace_id')}\nSpans: {span_count}")
        
        return item
    
    def _update_stats(self, stats: Dict[str, Any]):
        """更新统计信息"""
        self._stats = stats
        self._update_stats_label()
    
    def _update_stats_label(self):
        """更新统计标签"""
        if not hasattr(self, '_stats'):
            self._stats_label.setText("")
            return
        
        stats = self._stats
        total = stats.get("total_spans", 0)
        traces = stats.get("total_traces", 0)
        errors = stats.get("error_count", 0)
        error_rate = stats.get("error_rate", 0) * 100
        avg_duration = stats.get("avg_duration_ms", 0)
        
        text = (
            f"{self._tr('stats', '统计')}: "
            f"{traces} {self._tr('traces', '追踪')} | "
            f"{total} Spans | "
            f"{self._tr('avg_duration', '平均耗时')} {avg_duration:.0f}ms | "
            f"{self._tr('error_rate', '错误率')} {error_rate:.1f}%"
        )
        self._stats_label.setText(text)
    
    # --------------------------------------------------------
    # 详情显示
    # --------------------------------------------------------
    
    async def _show_trace_detail(self, trace_id: str):
        """显示追踪详情"""
        store = self._get_tracing_store()
        if not store:
            return
        
        try:
            spans = await store.get_trace(trace_id)
            if not spans:
                self._detail_panel.setText("No spans found")
                return
            
            # 格式化显示
            lines = [f"Trace: {trace_id}", "=" * 50, ""]
            
            for span in spans:
                status_icon = STATUS_ICONS.get(span.status, "")
                duration = span.duration_ms()
                duration_str = f"{duration:.0f}ms" if duration else "running"
                
                indent = "  " if span.parent_span_id else ""
                lines.append(
                    f"{indent}{status_icon} {span.operation_name} "
                    f"({span.service_name}) - {duration_str}"
                )
                
                if span.error_message:
                    lines.append(f"{indent}  Error: {span.error_message}")
            
            self._detail_panel.setText("\n".join(lines))
            self._current_trace_id = trace_id
            
        except Exception as e:
            self._detail_panel.setText(f"Error loading trace: {e}")
    
    async def _show_span_detail(self, span_id: str):
        """显示 Span 详情"""
        store = self._get_tracing_store()
        if not store:
            return
        
        try:
            span = await store.get_span_with_data(span_id)
            if not span:
                self._detail_panel.setText("Span not found")
                return
            
            # 格式化 JSON
            detail = {
                "span_id": span.span_id,
                "trace_id": span.trace_id,
                "operation": span.operation_name,
                "service": span.service_name,
                "status": span.status.value,
                "duration_ms": span.duration_ms(),
                "start_time": datetime.fromtimestamp(
                    span.start_time
                ).isoformat(),
            }
            
            if span.end_time:
                detail["end_time"] = datetime.fromtimestamp(
                    span.end_time
                ).isoformat()
            
            if span.error_message:
                detail["error"] = span.error_message
            
            if span.error_traceback:
                detail["error_traceback"] = span.error_traceback
            
            if span.inputs:
                detail["inputs"] = span.inputs
            
            if span.outputs:
                detail["outputs"] = span.outputs
            
            if span.metadata:
                detail["metadata"] = span.metadata
            
            self._detail_panel.setText(
                json.dumps(detail, indent=2, ensure_ascii=False)
            )
            self._current_span_id = span_id
            
        except Exception as e:
            self._detail_panel.setText(f"Error loading span: {e}")
    
    # --------------------------------------------------------
    # 事件处理
    # --------------------------------------------------------
    
    @pyqtSlot()
    def _on_refresh_clicked(self):
        """刷新按钮点击"""
        asyncio.create_task(self.refresh())
    
    @pyqtSlot()
    def _on_clear_clicked(self):
        """清除按钮点击"""
        self._trace_tree.clear()
        self._detail_panel.clear()
        self._traces = []
        self._current_trace_id = None
        self._current_span_id = None
    
    @pyqtSlot()
    def _on_export_clicked(self):
        """导出按钮点击"""
        if not self._current_trace_id:
            QMessageBox.information(
                self,
                self._tr("export", "导出"),
                self._tr("select_trace_first", "请先选择一个追踪")
            )
            return
        
        asyncio.create_task(self._export_trace(self._current_trace_id))
    
    async def _export_trace(self, trace_id: str):
        """导出追踪数据为 JSON"""
        store = self._get_tracing_store()
        if not store:
            return
        
        try:
            spans = await store.get_trace(trace_id)
            if not spans:
                return
            
            # 构建导出数据
            export_data = {
                "trace_id": trace_id,
                "exported_at": datetime.now().isoformat(),
                "spans": [span.to_dict() for span in spans],
            }
            
            # 选择保存路径
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                self._tr("export_trace", "导出追踪"),
                f"trace_{trace_id}.json",
                "JSON Files (*.json)"
            )
            
            if file_path:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, indent=2, ensure_ascii=False)
                
                QMessageBox.information(
                    self,
                    self._tr("export", "导出"),
                    self._tr("export_success", "导出成功")
                )
                
        except Exception as e:
            QMessageBox.warning(
                self,
                self._tr("error", "错误"),
                f"{self._tr('export_failed', '导出失败')}: {e}"
            )
    
    @pyqtSlot(int)
    def _on_filter_changed(self, index: int):
        """过滤器变更"""
        self._update_trace_tree()
    
    @pyqtSlot(QTreeWidgetItem, int)
    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        """树节点点击"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        
        item_type = data.get("type")
        if item_type == "trace":
            trace_id = data.get("trace_id")
            if trace_id:
                asyncio.create_task(self._show_trace_detail(trace_id))
                # 展开加载子 Spans
                asyncio.create_task(self._load_trace_spans(item, trace_id))
        elif item_type == "span":
            span_id = data.get("span_id")
            if span_id:
                asyncio.create_task(self._show_span_detail(span_id))
                # 展开加载子 Spans
                asyncio.create_task(self._load_child_spans(item, span_id))
    
    async def _load_trace_spans(self, parent_item: QTreeWidgetItem, trace_id: str):
        """加载追踪的所有 Spans 并构建树"""
        # 避免重复加载
        if parent_item.childCount() > 0:
            return
        
        store = self._get_tracing_store()
        if not store:
            return
        
        try:
            spans = await store.get_trace(trace_id)
            if not spans:
                return
            
            # 构建 span_id -> span 映射
            span_map = {span.span_id: span for span in spans}
            
            # 构建 parent_span_id -> children 映射
            children_map: Dict[str, List] = {}
            root_spans = []
            
            for span in spans:
                if span.parent_span_id:
                    if span.parent_span_id not in children_map:
                        children_map[span.parent_span_id] = []
                    children_map[span.parent_span_id].append(span)
                else:
                    root_spans.append(span)
            
            # 递归构建树
            def build_span_tree(parent: QTreeWidgetItem, span):
                span_item = self._create_span_item(span)
                parent.addChild(span_item)
                
                # 添加子 Spans
                if span.span_id in children_map:
                    for child_span in children_map[span.span_id]:
                        build_span_tree(span_item, child_span)
            
            # 添加根 Spans
            for root_span in root_spans:
                build_span_tree(parent_item, root_span)
            
            # 展开第一层
            parent_item.setExpanded(True)
            
        except Exception as e:
            self._log_error(f"加载追踪 Spans 失败: {e}")
    
    async def _load_child_spans(self, parent_item: QTreeWidgetItem, span_id: str):
        """加载指定 Span 的子 Spans"""
        # 避免重复加载
        if parent_item.childCount() > 0:
            return
        
        store = self._get_tracing_store()
        if not store:
            return
        
        try:
            children = await store.get_child_spans(span_id, include_data=False)
            if not children:
                return
            
            for child_span in children:
                span_item = self._create_span_item(child_span)
                parent_item.addChild(span_item)
                
                # 检查是否有孙子节点（用于显示展开箭头）
                grandchildren = await store.get_child_spans(
                    child_span.span_id, include_data=False
                )
                if grandchildren:
                    # 添加占位符，点击时再加载
                    placeholder = QTreeWidgetItem(["..."])
                    span_item.addChild(placeholder)
            
            parent_item.setExpanded(True)
            
        except Exception as e:
            self._log_error(f"加载子 Spans 失败: {e}")
    
    def _create_span_item(self, span) -> QTreeWidgetItem:
        """创建 Span 树节点"""
        # 格式化耗时
        duration = span.duration_ms()
        duration_str = f"{duration:.0f}ms" if duration else "running"
        
        # 状态图标
        status_icon = STATUS_ICONS.get(span.status, "")
        
        # 服务名称标记
        service_tag = f"[{span.service_name}]" if span.service_name else ""
        
        # 检查是否从 checkpoint 恢复
        resumed_tag = ""
        if span.metadata and span.metadata.get("resumed_from_checkpoint"):
            resumed_tag = " ⟲"  # 恢复标记
        
        # 创建节点
        item = QTreeWidgetItem([
            f"{service_tag} {span.operation_name}{resumed_tag}",
            duration_str,
            status_icon,
        ])
        
        # 存储数据
        item.setData(0, Qt.ItemDataRole.UserRole, {
            "type": "span",
            "span_id": span.span_id,
            "trace_id": span.trace_id,
        })
        
        # 设置颜色
        color = STATUS_COLORS.get(span.status)
        if color:
            item.setForeground(2, QBrush(color))
        
        # 错误背景
        if span.status == TraceStatus.ERROR:
            for col in range(3):
                item.setBackground(col, QBrush(ERROR_BG_COLOR))
        
        # 工具提示
        tooltip_lines = [
            f"Span ID: {span.span_id}",
            f"Service: {span.service_name}",
            f"Status: {span.status.value}",
        ]
        if span.error_message:
            tooltip_lines.append(f"Error: {span.error_message}")
        item.setToolTip(0, "\n".join(tooltip_lines))
        
        return item
    
    def _on_spans_flushed(self, event_data: Dict[str, Any]):
        """Spans 刷新完成事件"""
        # 增量刷新
        asyncio.create_task(self.refresh())
    
    def _on_span_error(self, event_data: Dict[str, Any]):
        """Span 错误事件"""
        # 可以高亮显示错误 span
        span_id = event_data.get("data", {}).get("span_id")
        if span_id:
            self._highlight_error_span(span_id)
    
    def _highlight_error_span(self, span_id: str):
        """高亮显示错误 Span"""
        # 遍历树查找并高亮
        for i in range(self._trace_tree.topLevelItemCount()):
            item = self._trace_tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("span_id") == span_id:
                self._trace_tree.setCurrentItem(item)
                break
    
    def _on_language_changed(self, event_data: Dict[str, Any]):
        """语言切换事件"""
        self._i18n = None  # 清除缓存
        self._retranslate_ui()
    
    # --------------------------------------------------------
    # 辅助方法
    # --------------------------------------------------------
    
    def _get_tracing_store(self):
        """获取 TracingStore"""
        if self._tracing_store is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_TRACING_STORE
                self._tracing_store = ServiceLocator.get_optional(SVC_TRACING_STORE)
            except Exception:
                pass
        return self._tracing_store
    
    def _log_error(self, message: str):
        """记录错误日志"""
        try:
            from infrastructure.utils.logger import get_logger
            logger = get_logger("devtools_panel")
            logger.error(message)
        except Exception:
            print(f"[DevToolsPanel ERROR] {message}")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "DevToolsPanel",
]
