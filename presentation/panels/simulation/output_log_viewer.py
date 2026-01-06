# OutputLogViewer - Simulation Output Log Viewer
"""
仿真输出日志查看器

职责：
- 显示 ngspice 原始输出日志，便于调试
- 支持搜索关键词并高亮
- 支持按日志级别过滤
- 支持跳转到第一个错误行

设计原则：
- 使用 QPlainTextEdit 显示日志（只读）
- 通过 SimulationOutputReader 读取日志数据
- 语法高亮：错误行红色、警告行黄色
- 支持国际化

被调用方：
- simulation_tab.py
"""

import logging
from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QRegularExpression
from PyQt6.QtGui import (
    QTextCharFormat,
    QColor,
    QFont,
    QTextCursor,
    QSyntaxHighlighter,
    QTextDocument,
)
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QSizePolicy,
)

from domain.simulation.data.simulation_output_reader import (
    SimulationOutputReader,
    simulation_output_reader,
    LogLine,
    LogLevel,
    SimulationSummary,
)
from resources.theme import (
    COLOR_BG_PRIMARY,
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_BORDER,
    COLOR_ACCENT,
    COLOR_ACCENT_LIGHT,
    COLOR_ERROR,
    COLOR_WARNING,
    FONT_SIZE_SMALL,
    FONT_SIZE_NORMAL,
    SPACING_SMALL,
    SPACING_NORMAL,
    BORDER_RADIUS_NORMAL,
)


# ============================================================
# 常量定义
# ============================================================

# 错误行背景色
ERROR_BG_COLOR = "#ffebee"
# 警告行背景色
WARNING_BG_COLOR = "#fff8e1"
# 关键信息文字色
INFO_TEXT_COLOR = "#1976d2"
# 搜索高亮背景色
SEARCH_HIGHLIGHT_COLOR = "#ffff00"


# ============================================================
# LogHighlighter - 日志语法高亮器
# ============================================================

class LogHighlighter(QSyntaxHighlighter):
    """
    日志语法高亮器
    
    为不同级别的日志行应用不同的样式：
    - 错误行：红色背景
    - 警告行：黄色背景
    - 关键信息：蓝色文字
    """
    
    def __init__(self, parent: QTextDocument = None):
        super().__init__(parent)
        
        # 错误格式
        self._error_format = QTextCharFormat()
        self._error_format.setBackground(QColor(ERROR_BG_COLOR))
        self._error_format.setForeground(QColor(COLOR_ERROR))
        
        # 警告格式
        self._warning_format = QTextCharFormat()
        self._warning_format.setBackground(QColor(WARNING_BG_COLOR))
        self._warning_format.setForeground(QColor("#f57c00"))
        
        # 信息格式
        self._info_format = QTextCharFormat()
        self._info_format.setForeground(QColor(INFO_TEXT_COLOR))
        
        # 搜索高亮格式
        self._search_format = QTextCharFormat()
        self._search_format.setBackground(QColor(SEARCH_HIGHLIGHT_COLOR))
        
        # 错误关键词正则
        self._error_pattern = QRegularExpression(
            r'\b(error|fatal|failed|failure|exception|abort|cannot|unable|'
            r'invalid|illegal|undefined|no convergence|singular matrix)\b',
            QRegularExpression.PatternOption.CaseInsensitiveOption
        )
        
        # 警告关键词正则
        self._warning_pattern = QRegularExpression(
            r'\b(warning|warn|caution|deprecated|notice|attention|'
            r'floating|missing)\b',
            QRegularExpression.PatternOption.CaseInsensitiveOption
        )
        
        # 信息关键词正则
        self._info_pattern = QRegularExpression(
            r'\b(analysis|simulation|circuit|temperature|completed|'
            r'finished|starting|loading|parsing)\b',
            QRegularExpression.PatternOption.CaseInsensitiveOption
        )
        
        # 搜索关键词
        self._search_keyword: str = ""
    
    def set_search_keyword(self, keyword: str):
        """设置搜索关键词"""
        self._search_keyword = keyword
        self.rehighlight()
    
    def clear_search(self):
        """清除搜索高亮"""
        self._search_keyword = ""
        self.rehighlight()
    
    def highlightBlock(self, text: str):
        """高亮文本块"""
        if not text:
            return
        
        # 检查错误关键词
        match_iter = self._error_pattern.globalMatch(text)
        has_error = False
        while match_iter.hasNext():
            match = match_iter.next()
            has_error = True
            self.setFormat(match.capturedStart(), match.capturedLength(), self._error_format)
        
        # 如果整行包含错误，设置整行背景
        if has_error:
            block_format = QTextCharFormat()
            block_format.setBackground(QColor(ERROR_BG_COLOR))
            self.setFormat(0, len(text), block_format)
            # 重新应用错误关键词高亮
            match_iter = self._error_pattern.globalMatch(text)
            while match_iter.hasNext():
                match = match_iter.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), self._error_format)
            return
        
        # 检查警告关键词
        match_iter = self._warning_pattern.globalMatch(text)
        has_warning = False
        while match_iter.hasNext():
            match = match_iter.next()
            has_warning = True
            self.setFormat(match.capturedStart(), match.capturedLength(), self._warning_format)
        
        # 如果整行包含警告，设置整行背景
        if has_warning:
            block_format = QTextCharFormat()
            block_format.setBackground(QColor(WARNING_BG_COLOR))
            self.setFormat(0, len(text), block_format)
            # 重新应用警告关键词高亮
            match_iter = self._warning_pattern.globalMatch(text)
            while match_iter.hasNext():
                match = match_iter.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), self._warning_format)
            return
        
        # 检查信息关键词
        match_iter = self._info_pattern.globalMatch(text)
        while match_iter.hasNext():
            match = match_iter.next()
            self.setFormat(match.capturedStart(), match.capturedLength(), self._info_format)
        
        # 搜索高亮
        if self._search_keyword:
            keyword_lower = self._search_keyword.lower()
            text_lower = text.lower()
            start = 0
            while True:
                idx = text_lower.find(keyword_lower, start)
                if idx == -1:
                    break
                self.setFormat(idx, len(self._search_keyword), self._search_format)
                start = idx + 1


# ============================================================
# OutputLogViewer - 仿真输出日志查看器
# ============================================================

class OutputLogViewer(QWidget):
    """
    仿真输出日志查看器
    
    显示 ngspice 原始输出日志，支持：
    - 搜索关键词并高亮
    - 按日志级别过滤
    - 跳转到第一个错误行
    
    Signals:
        error_clicked: 点击错误行时发出，携带行号
    """
    
    error_clicked = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # 数据读取器
        self._reader: SimulationOutputReader = simulation_output_reader
        
        # 当前日志数据
        self._log_lines: List[LogLine] = []
        self._filtered_lines: List[LogLine] = []
        self._current_filter: str = "all"
        
        # 项目和结果路径
        self._project_root: Optional[str] = None
        self._sim_result_path: Optional[str] = None
        
        # 摘要信息
        self._summary: Optional[SimulationSummary] = None
        
        # 初始化 UI
        self._setup_ui()
        self._apply_style()
        self._connect_signals()
        
        # 初始化文本
        self.retranslate_ui()
    
    def _setup_ui(self):
        """初始化 UI 组件"""
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 工具栏
        self._toolbar = QFrame()
        self._toolbar.setObjectName("logToolbar")
        toolbar_layout = QHBoxLayout(self._toolbar)
        toolbar_layout.setContentsMargins(
            SPACING_SMALL, SPACING_SMALL, SPACING_SMALL, SPACING_SMALL
        )
        toolbar_layout.setSpacing(SPACING_SMALL)
        
        # 搜索框
        self._search_label = QLabel()
        self._search_edit = QLineEdit()
        self._search_edit.setObjectName("searchEdit")
        self._search_edit.setFixedWidth(200)
        self._search_edit.setClearButtonEnabled(True)
        self._search_btn = QPushButton()
        self._search_btn.setObjectName("searchBtn")
        
        toolbar_layout.addWidget(self._search_label)
        toolbar_layout.addWidget(self._search_edit)
        toolbar_layout.addWidget(self._search_btn)
        
        toolbar_layout.addSpacing(SPACING_NORMAL)
        
        # 过滤下拉框
        self._filter_label = QLabel()
        self._filter_combo = QComboBox()
        self._filter_combo.setObjectName("filterCombo")
        self._filter_combo.setFixedWidth(120)
        
        toolbar_layout.addWidget(self._filter_label)
        toolbar_layout.addWidget(self._filter_combo)
        
        toolbar_layout.addSpacing(SPACING_NORMAL)
        
        # 跳转到错误按钮
        self._jump_error_btn = QPushButton()
        self._jump_error_btn.setObjectName("jumpErrorBtn")
        toolbar_layout.addWidget(self._jump_error_btn)
        
        toolbar_layout.addStretch()
        
        # 刷新按钮
        self._refresh_btn = QPushButton()
        self._refresh_btn.setObjectName("refreshBtn")
        toolbar_layout.addWidget(self._refresh_btn)
        
        main_layout.addWidget(self._toolbar)
        
        # 日志显示区
        self._log_view = QPlainTextEdit()
        self._log_view.setObjectName("logView")
        self._log_view.setReadOnly(True)
        self._log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        
        # 设置等宽字体
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._log_view.setFont(font)
        
        # 语法高亮器
        self._highlighter = LogHighlighter(self._log_view.document())
        
        main_layout.addWidget(self._log_view, 1)
        
        # 状态栏
        self._status_bar = QFrame()
        self._status_bar.setObjectName("logStatusBar")
        status_layout = QHBoxLayout(self._status_bar)
        status_layout.setContentsMargins(
            SPACING_SMALL, SPACING_SMALL, SPACING_SMALL, SPACING_SMALL
        )
        status_layout.setSpacing(SPACING_NORMAL)
        
        self._total_label = QLabel()
        self._error_label = QLabel()
        self._warning_label = QLabel()
        
        status_layout.addWidget(self._total_label)
        status_layout.addWidget(self._error_label)
        status_layout.addWidget(self._warning_label)
        status_layout.addStretch()
        
        main_layout.addWidget(self._status_bar)

    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet(f"""
            #logToolbar {{
                background-color: {COLOR_BG_TERTIARY};
                border-bottom: 1px solid {COLOR_BORDER};
            }}
            
            #logToolbar QLabel {{
                color: {COLOR_TEXT_PRIMARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            
            #searchEdit {{
                background-color: {COLOR_BG_SECONDARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 4px 8px;
            }}
            
            #searchEdit:focus {{
                border-color: {COLOR_ACCENT};
            }}
            
            #filterCombo {{
                background-color: {COLOR_BG_SECONDARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 4px 8px;
            }}
            
            #searchBtn, #jumpErrorBtn, #refreshBtn {{
                background-color: {COLOR_BG_SECONDARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 4px 12px;
                min-height: 24px;
            }}
            
            #searchBtn:hover, #jumpErrorBtn:hover, #refreshBtn:hover {{
                background-color: {COLOR_ACCENT_LIGHT};
                border-color: {COLOR_ACCENT};
            }}
            
            #searchBtn:pressed, #jumpErrorBtn:pressed, #refreshBtn:pressed {{
                background-color: {COLOR_ACCENT};
                color: white;
            }}
            
            #jumpErrorBtn {{
                color: {COLOR_ERROR};
                border-color: {COLOR_ERROR};
            }}
            
            #jumpErrorBtn:hover {{
                background-color: #ffebee;
            }}
            
            #logView {{
                background-color: {COLOR_BG_PRIMARY};
                color: {COLOR_TEXT_PRIMARY};
                border: none;
                selection-background-color: {COLOR_ACCENT_LIGHT};
            }}
            
            #logStatusBar {{
                background-color: {COLOR_BG_TERTIARY};
                border-top: 1px solid {COLOR_BORDER};
            }}
            
            #logStatusBar QLabel {{
                color: {COLOR_TEXT_SECONDARY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
        """)
    
    def _connect_signals(self):
        """连接信号"""
        self._search_btn.clicked.connect(self._on_search)
        self._search_edit.returnPressed.connect(self._on_search)
        self._search_edit.textChanged.connect(self._on_search_text_changed)
        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        self._jump_error_btn.clicked.connect(self._on_jump_to_error)
        self._refresh_btn.clicked.connect(self._on_refresh)
    
    # ============================================================
    # 公共方法
    # ============================================================
    
    def load_log(
        self,
        sim_result_path: str,
        project_root: str
    ):
        """
        加载仿真输出日志
        
        Args:
            sim_result_path: 仿真结果相对路径
            project_root: 项目根目录
        """
        self._sim_result_path = sim_result_path
        self._project_root = project_root
        
        # 读取日志
        self._log_lines = self._reader.get_output_log(
            sim_result_path, project_root
        )
        
        # 获取摘要
        self._summary = self._reader.get_simulation_summary(
            sim_result_path, project_root
        )
        
        # 应用当前过滤器
        self._apply_filter()
        
        # 更新状态栏
        self._update_status()
        
        self._logger.info(
            f"Loaded log: {len(self._log_lines)} lines, "
            f"{self._summary.error_count if self._summary else 0} errors"
        )
    
    def load_log_from_text(self, raw_output: str):
        """
        从文本加载日志
        
        Args:
            raw_output: 原始输出文本
        """
        self._sim_result_path = None
        self._project_root = None
        
        # 解析日志
        self._log_lines = self._reader.get_output_log_from_text(raw_output)
        
        # 计算摘要
        error_count = sum(1 for line in self._log_lines if line.is_error())
        warning_count = sum(1 for line in self._log_lines if line.is_warning())
        
        self._summary = SimulationSummary(
            total_lines=len(self._log_lines),
            error_count=error_count,
            warning_count=warning_count,
            info_count=len(self._log_lines) - error_count - warning_count,
        )
        
        # 应用当前过滤器
        self._apply_filter()
        
        # 更新状态栏
        self._update_status()
    
    def clear(self):
        """清空日志"""
        self._log_lines = []
        self._filtered_lines = []
        self._summary = None
        self._sim_result_path = None
        self._project_root = None
        
        self._log_view.clear()
        self._highlighter.clear_search()
        self._update_status()
    
    def search(self, keyword: str):
        """
        搜索关键词并高亮
        
        Args:
            keyword: 搜索关键词
        """
        if not keyword:
            self._highlighter.clear_search()
            return
        
        self._highlighter.set_search_keyword(keyword)
        
        # 跳转到第一个匹配
        self._find_next(keyword, from_start=True)
    
    def filter_by_level(self, level: str):
        """
        按日志级别过滤
        
        Args:
            level: 日志级别（all/error/warning/info）
        """
        self._current_filter = level
        self._apply_filter()
    
    def jump_to_error(self) -> bool:
        """
        跳转到第一个错误行
        
        Returns:
            bool: 是否找到错误行
        """
        for line in self._filtered_lines:
            if line.is_error():
                self._jump_to_line(line.line_number)
                self.error_clicked.emit(line.line_number)
                return True
        return False
    
    def jump_to_line(self, line_number: int):
        """
        跳转到指定行
        
        Args:
            line_number: 行号（从 1 开始）
        """
        self._jump_to_line(line_number)
    
    def get_error_count(self) -> int:
        """获取错误数"""
        return self._summary.error_count if self._summary else 0
    
    def get_warning_count(self) -> int:
        """获取警告数"""
        return self._summary.warning_count if self._summary else 0
    
    def get_total_lines(self) -> int:
        """获取总行数"""
        return self._summary.total_lines if self._summary else 0
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        self._search_label.setText(self._tr("Search:"))
        self._search_edit.setPlaceholderText(self._tr("Enter keyword..."))
        self._search_btn.setText(self._tr("Find"))
        self._filter_label.setText(self._tr("Filter:"))
        self._jump_error_btn.setText(self._tr("Jump to Error"))
        self._refresh_btn.setText(self._tr("Refresh"))
        
        # 更新过滤下拉框
        current_index = self._filter_combo.currentIndex()
        self._filter_combo.clear()
        self._filter_combo.addItem(self._tr("All"), "all")
        self._filter_combo.addItem(self._tr("Errors"), "error")
        self._filter_combo.addItem(self._tr("Warnings"), "warning")
        self._filter_combo.addItem(self._tr("Info"), "info")
        self._filter_combo.setCurrentIndex(max(0, current_index))
        
        # 更新状态栏
        self._update_status()
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _apply_filter(self):
        """应用过滤器"""
        if self._current_filter == "all":
            self._filtered_lines = self._log_lines
        else:
            self._filtered_lines = self._reader.filter_by_level(
                self._log_lines, self._current_filter
            )
        
        # 更新显示
        self._update_display()
    
    def _update_display(self):
        """更新日志显示"""
        # 构建显示文本
        lines = [line.content for line in self._filtered_lines]
        text = "\n".join(lines)
        
        self._log_view.setPlainText(text)
    
    def _update_status(self):
        """更新状态栏"""
        if self._summary:
            self._total_label.setText(
                self._tr("Total: {count} lines").format(count=self._summary.total_lines)
            )
            self._error_label.setText(
                self._tr("Errors: {count}").format(count=self._summary.error_count)
            )
            self._warning_label.setText(
                self._tr("Warnings: {count}").format(count=self._summary.warning_count)
            )
            
            # 错误数大于 0 时高亮显示
            if self._summary.error_count > 0:
                self._error_label.setStyleSheet(f"color: {COLOR_ERROR}; font-weight: bold;")
            else:
                self._error_label.setStyleSheet("")
            
            # 警告数大于 0 时高亮显示
            if self._summary.warning_count > 0:
                self._warning_label.setStyleSheet(f"color: {COLOR_WARNING}; font-weight: bold;")
            else:
                self._warning_label.setStyleSheet("")
        else:
            self._total_label.setText(self._tr("Total: 0 lines"))
            self._error_label.setText(self._tr("Errors: 0"))
            self._warning_label.setText(self._tr("Warnings: 0"))
            self._error_label.setStyleSheet("")
            self._warning_label.setStyleSheet("")
    
    def _jump_to_line(self, line_number: int):
        """跳转到指定行"""
        if line_number < 1:
            return
        
        # 在过滤后的行中查找
        target_index = -1
        for i, line in enumerate(self._filtered_lines):
            if line.line_number == line_number:
                target_index = i
                break
        
        if target_index < 0:
            return
        
        # 移动光标到目标行
        cursor = self._log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        
        for _ in range(target_index):
            cursor.movePosition(QTextCursor.MoveOperation.Down)
        
        cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        self._log_view.setTextCursor(cursor)
        self._log_view.centerCursor()
    
    def _find_next(self, keyword: str, from_start: bool = False):
        """查找下一个匹配"""
        if not keyword:
            return
        
        if from_start:
            cursor = self._log_view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self._log_view.setTextCursor(cursor)
        
        # 使用 QPlainTextEdit 的查找功能
        found = self._log_view.find(keyword)
        
        if not found and not from_start:
            # 从头开始查找
            cursor = self._log_view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self._log_view.setTextCursor(cursor)
            self._log_view.find(keyword)
    
    def _on_search(self):
        """搜索按钮点击"""
        keyword = self._search_edit.text().strip()
        self.search(keyword)
    
    def _on_search_text_changed(self, text: str):
        """搜索文本变化"""
        if not text:
            self._highlighter.clear_search()
    
    def _on_filter_changed(self, index: int):
        """过滤器变化"""
        level = self._filter_combo.itemData(index)
        if level:
            self.filter_by_level(level)
    
    def _on_jump_to_error(self):
        """跳转到错误按钮点击"""
        if not self.jump_to_error():
            self._logger.info("No errors found in log")
    
    def _on_refresh(self):
        """刷新按钮点击"""
        if self._sim_result_path and self._project_root:
            self.load_log(self._sim_result_path, self._project_root)
    
    def _tr(self, text: str) -> str:
        """获取国际化文本"""
        try:
            from shared.i18n_manager import I18nManager
            i18n = I18nManager()
            return i18n.get_text(f"log_viewer.{text.lower().replace(' ', '_').replace(':', '')}", text)
        except (ImportError, Exception):
            return text


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "OutputLogViewer",
    "LogHighlighter",
]
