# OutputLogViewer - Simulation Output Log Viewer
"""
仿真输出日志查看器

职责：
- 显示 ngspice 原始输出日志，便于调试
- 支持搜索关键词并高亮
- 支持按日志级别过滤
- 支持跳转到第一个错误行

设计原则：
- 仅保留 React 界面所需的结构化状态，不创建隐藏 Qt 控件
- 直接消费已加载 SimulationResult 的 raw_output，不重复解析结果包
- 语法高亮：错误行红色、警告行黄色
- 支持国际化

被调用方：
- simulation_tab.py
"""

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject

from domain.simulation.data.simulation_output_reader import (
    SimulationOutputReader,
    simulation_output_reader,
    LogLine,
)
# ============================================================
# OutputLogViewer - 仿真输出日志查看器
# ============================================================

class OutputLogViewer(QObject):
    """
    仿真输出日志查看器
    
    显示 ngspice 原始输出日志，支持：
    - 搜索关键词并高亮
    - 按日志级别过滤
    - 跳转到第一个错误行
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 数据读取器
        self._reader: SimulationOutputReader = simulation_output_reader
        
        # 当前日志数据
        self._log_lines: List[LogLine] = []
        self._filtered_lines: List[LogLine] = []
        self._current_filter: str = "all"
        self._search_keyword: str = ""
        self._selected_line_number: Optional[int] = None
        
    # ============================================================
    # 公共方法
    # ============================================================
    
    def load_log_from_text(self, raw_output: str):
        """
        从文本加载日志
        
        Args:
            raw_output: 原始输出文本
        """
        # The viewer owns search/filter/copy over the complete log.  A
        # parser-side row cap would silently make those operations incomplete;
        # only the WebChannel snapshot below is windowed for rendering.
        log_lines = self._reader.get_output_log_from_text(raw_output, max_lines=None)
        
        self._store_log_state(log_lines, reset_view_state=True)

    def clear(self):
        """清空日志"""
        self._log_lines = []
        self._filtered_lines = []
        self._current_filter = "all"
        self._search_keyword = ""
        self._selected_line_number = None
    
    def search(self, keyword: str):
        """
        搜索关键词并高亮
        
        Args:
            keyword: 搜索关键词
        """
        self._search_keyword = str(keyword or "").strip()
        if not self._search_keyword:
            if not self._is_line_visible(self._selected_line_number):
                self._selected_line_number = None
            return
        self._selected_line_number = self._find_matching_line_number(self._search_keyword)
    
    def filter_by_level(self, level: str):
        """
        按日志级别过滤
        
        Args:
            level: 日志级别（all/error/warning/info）
        """
        normalized_level = str(level or "all").strip().lower()
        if normalized_level not in {"all", "error", "warning", "info"}:
            normalized_level = "all"
        self._current_filter = normalized_level
        self._apply_filter()
    
    def get_web_snapshot(self, *, max_lines: int = 1000) -> Dict[str, Any]:
        total_filtered_lines = len(self._filtered_lines)
        selected_line_number = self._current_selected_line_number()
        if max_lines <= 0:
            return {
                "has_log": bool(self._log_lines),
                "can_add_to_conversation": bool(self._log_lines),
                "current_filter": str(self._current_filter or "all"),
                "search_keyword": self._search_keyword,
                "lines": [],
                "selected_line_number": selected_line_number,
                "total_line_count": total_filtered_lines,
                "visible_line_count": 0,
                "is_truncated": total_filtered_lines > 0,
            }
        if total_filtered_lines <= max_lines:
            window_start = 0
            window_end = total_filtered_lines
        elif selected_line_number is not None:
            selected_index = next(
                (index for index, line in enumerate(self._filtered_lines) if line.line_number == selected_line_number),
                0,
            )
            half_window = max_lines // 2
            window_start = max(0, min(selected_index - half_window, total_filtered_lines - max_lines))
            window_end = min(total_filtered_lines, window_start + max_lines)
        else:
            window_start = 0
            window_end = max_lines
        visible_lines = self._filtered_lines[window_start:window_end]
        return {
            "has_log": bool(self._log_lines),
            "can_add_to_conversation": bool(self._log_lines),
            "current_filter": str(self._current_filter or "all"),
            "search_keyword": self._search_keyword,
            "lines": [line.to_dict() for line in visible_lines],
            "selected_line_number": selected_line_number,
            "total_line_count": total_filtered_lines,
            "visible_line_count": len(visible_lines),
            "is_truncated": len(visible_lines) < total_filtered_lines,
        }

    def get_filtered_text(self) -> str:
        """Return the complete filtered log, never the 1000-row UI window."""
        return "\n".join(str(line.content) for line in self._filtered_lines)
    
    def retranslate_ui(self):
        """重新翻译 UI 文本"""
        return

    # ============================================================
    # 内部方法
    # ============================================================

    def _apply_filter(self):
        """应用过滤器"""
        if self._current_filter == "all":
            self._filtered_lines = list(self._log_lines)
        else:
            self._filtered_lines = self._reader.filter_by_level(
                self._log_lines, self._current_filter
            )
        self._selected_line_number = self._resolve_selected_line_number()

    def _current_selected_line_number(self) -> Optional[int]:
        if self._is_line_visible(self._selected_line_number):
            return self._selected_line_number
        return None
    
    def _is_line_visible(self, line_number: Optional[int]) -> bool:
        if line_number is None:
            return False
        return any(int(line.line_number) == int(line_number) for line in self._filtered_lines)

    def _store_log_state(
        self,
        log_lines: List[LogLine],
        *,
        reset_view_state: bool,
    ):
        self._log_lines = list(log_lines)
        if reset_view_state:
            self._current_filter = "all"
            self._search_keyword = ""
            self._selected_line_number = None
        self._apply_filter()

    def _resolve_selected_line_number(self) -> Optional[int]:
        if self._is_line_visible(self._selected_line_number):
            return self._selected_line_number
        if not self._search_keyword:
            return None
        return self._find_matching_line_number(self._search_keyword)

    def _find_matching_line_number(self, keyword: str) -> Optional[int]:
        normalized_keyword = str(keyword or "").strip().lower()
        if not normalized_keyword:
            return None
        for line in self._filtered_lines:
            if normalized_keyword in str(line.content or "").lower():
                return int(line.line_number)
        return None


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "OutputLogViewer",
]
