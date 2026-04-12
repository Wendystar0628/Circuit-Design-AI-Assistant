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
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QWidget,
    QSizePolicy,
)

from domain.simulation.data.simulation_output_reader import (
    SimulationOutputReader,
    simulation_output_reader,
    LogLine,
    SimulationSummary,
)
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
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._logger = logging.getLogger(__name__)
        
        # 数据读取器
        self._reader: SimulationOutputReader = simulation_output_reader
        
        # 当前日志数据
        self._log_lines: List[LogLine] = []
        self._filtered_lines: List[LogLine] = []
        self._current_filter: str = "all"
        self._search_keyword: str = ""
        self._selected_line_number: Optional[int] = None
        
        # 项目和结果路径
        self._project_root: Optional[str] = None
        self._sim_result_path: Optional[str] = None
        
        # 摘要信息
        self._summary: Optional[SimulationSummary] = None

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        self.setStyleSheet("")
        self.retranslate_ui()
    
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
        
        self._store_log_state(
            self._reader.get_output_log(sim_result_path, project_root),
            self._reader.get_simulation_summary(sim_result_path, project_root),
            reset_view_state=True,
        )
        
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
        
        log_lines = self._reader.get_output_log_from_text(raw_output)
        
        # 计算摘要
        error_count = sum(1 for line in log_lines if line.is_error())
        warning_count = sum(1 for line in log_lines if line.is_warning())
        
        summary = SimulationSummary(
            total_lines=len(log_lines),
            error_count=error_count,
            warning_count=warning_count,
            info_count=len(log_lines) - error_count - warning_count,
        )
        self._store_log_state(log_lines, summary, reset_view_state=True)

    def clear(self):
        """清空日志"""
        self._log_lines = []
        self._filtered_lines = []
        self._summary = None
        self._current_filter = "all"
        self._search_keyword = ""
        self._selected_line_number = None
        self._sim_result_path = None
        self._project_root = None
    
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
    
    def jump_to_error(self) -> bool:
        """
        跳转到第一个错误行
        
        Returns:
            bool: 是否找到错误行
        """
        for line in self._filtered_lines:
            if line.is_error():
                self._selected_line_number = int(line.line_number)
                return True
        return False
    
    def jump_to_line(self, line_number: int):
        """
        跳转到指定行
        
        Args:
            line_number: 行号（从 1 开始）
        """
        self._jump_to_line(line_number)

    def refresh_log(self):
        """重新加载当前日志文件"""
        if self._sim_result_path and self._project_root:
            self._store_log_state(
                self._reader.get_output_log(self._sim_result_path, self._project_root),
                self._reader.get_simulation_summary(self._sim_result_path, self._project_root),
                reset_view_state=False,
            )
    
    def get_error_count(self) -> int:
        """获取错误数"""
        return self._summary.error_count if self._summary else 0
    
    def get_warning_count(self) -> int:
        """获取警告数"""
        return self._summary.warning_count if self._summary else 0
    
    def get_total_lines(self) -> int:
        """获取总行数"""
        return self._summary.total_lines if self._summary else 0
    
    def get_web_snapshot(self, *, max_lines: int = 1000) -> Dict[str, Any]:
        total_filtered_lines = len(self._filtered_lines)
        selected_line_number = self._current_selected_line_number()
        summary = self._summary.to_dict() if self._summary is not None else {
            "total_lines": 0,
            "error_count": 0,
            "warning_count": 0,
            "info_count": 0,
            "analysis_type": "",
            "duration_seconds": 0.0,
            "success": True,
            "first_error": None,
            "timestamp": "",
        }
        if max_lines <= 0:
            return {
                "has_log": bool(self._log_lines),
                "line_count": len(self._log_lines),
                "filtered_line_count": total_filtered_lines,
                "can_refresh": bool(self._sim_result_path and self._project_root),
                "can_add_to_conversation": bool(self._log_lines),
                "current_filter": str(self._current_filter or "all"),
                "search_keyword": self._search_keyword,
                "summary": summary,
                "lines": [],
                "window_start": 0,
                "window_end": 0,
                "has_more_before": False,
                "has_more_after": total_filtered_lines > 0,
                "selected_line_number": selected_line_number,
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
            "line_count": len(self._log_lines),
            "filtered_line_count": total_filtered_lines,
            "can_refresh": bool(self._sim_result_path and self._project_root),
            "can_add_to_conversation": bool(self._log_lines),
            "current_filter": str(self._current_filter or "all"),
            "search_keyword": self._search_keyword,
            "summary": summary,
            "lines": [line.to_dict() for line in visible_lines],
            "window_start": window_start + 1 if visible_lines else 0,
            "window_end": window_end,
            "has_more_before": window_start > 0,
            "has_more_after": window_end < total_filtered_lines,
            "selected_line_number": selected_line_number,
        }
    
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
    
    def _jump_to_line(self, line_number: int):
        """跳转到指定行"""
        normalized_line_number = int(line_number)
        if normalized_line_number < 1:
            return

        if not self._is_line_visible(normalized_line_number):
            return
        self._selected_line_number = normalized_line_number

    def _store_log_state(
        self,
        log_lines: List[LogLine],
        summary: Optional[SimulationSummary],
        *,
        reset_view_state: bool,
    ):
        self._log_lines = list(log_lines)
        self._summary = summary
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

    def _is_line_visible(self, line_number: Optional[int]) -> bool:
        if line_number is None:
            return False
        return any(int(line.line_number) == int(line_number) for line in self._filtered_lines)

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
