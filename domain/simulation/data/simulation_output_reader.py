# SimulationOutputReader - Simulation Output Log Reader
"""
仿真输出日志读取器

职责：
- 解析调用方已加载的仿真引擎输出日志
- 识别日志级别（info/warning/error）
- 提供按级别过滤
- 生成仿真摘要信息

设计原则：
- 只处理内存文本；结果路径加载统一由 SimulationResultRepository 负责
- 日志级别基于关键词匹配识别
- 提供结构化的日志行数据

使用示例：
    from domain.simulation.data.simulation_output_reader import (
        SimulationOutputReader,
        simulation_output_reader,
    )

    log_lines = simulation_output_reader.get_output_log_from_text(
        raw_output="warning: floating node",
        max_lines=1000,
    )
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ============================================================
# 常量定义
# ============================================================

# 错误关键词（不区分大小写）
ERROR_KEYWORDS = [
    "error",
    "fatal",
    "failed",
    "exception",
    "abort",
    "aborted",
    "cannot",
    "unable",
    "invalid",
    "illegal",
    "undefined",
    "no convergence",
    "singular matrix",
    "timestep too small",
]

# 警告关键词（不区分大小写）
WARNING_KEYWORDS = [
    "warning",
    "warn",
    "caution",
    "deprecated",
    "notice",
    "attention",
    "floating",
    "missing",
]

# ============================================================
# 日志级别枚举
# ============================================================

class LogLevel(str, Enum):
    """日志级别枚举"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# ============================================================
# LogLine - 日志行数据类
# ============================================================

@dataclass
class LogLine:
    """
    日志行数据类
    
    Attributes:
        line_number: 行号（从 1 开始）
        content: 日志内容
        level: 日志级别（info/warning/error）
    """
    
    line_number: int
    """行号（从 1 开始）"""
    
    content: str
    """日志内容"""
    
    level: str = LogLevel.INFO.value
    """日志级别（info/warning/error）"""
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "line_number": self.line_number,
            "content": self.content,
            "level": self.level,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LogLine":
        """从字典反序列化"""
        return cls(
            line_number=data["line_number"],
            content=data["content"],
            level=data.get("level", LogLevel.INFO.value),
        )
    
    def is_error(self) -> bool:
        """是否为错误行"""
        return self.level == LogLevel.ERROR.value
    
    def is_warning(self) -> bool:
        """是否为警告行"""
        return self.level == LogLevel.WARNING.value


# ============================================================
# SimulationSummary - 仿真摘要数据类
# ============================================================

@dataclass
class SimulationSummary:
    """Diagnostic counts derived from one complete raw log."""
    
    total_lines: int = 0
    """总行数"""
    
    error_count: int = 0
    """错误数"""
    
    warning_count: int = 0
    """警告数"""
    
    info_count: int = 0
    """信息数"""
    
    first_error: Optional[str] = None
    """第一个错误信息"""


# ============================================================
# SimulationOutputReader - 仿真输出日志读取器
# ============================================================

class SimulationOutputReader:
    """
    仿真输出日志读取器
    
    提供内存日志的解析、汇总和按级别过滤。
    """
    
    def __init__(self):
        """初始化读取器"""
        # 编译正则表达式（提高性能）
        self._error_pattern = re.compile(
            r'\b(' + '|'.join(re.escape(item) for item in ERROR_KEYWORDS) + r')\b',
            re.IGNORECASE
        )
        self._warning_pattern = re.compile(
            r'\b(' + '|'.join(re.escape(item) for item in WARNING_KEYWORDS) + r')\b',
            re.IGNORECASE
        )
        self._negative_count_pattern = re.compile(
            r"\b(?:no|zero|0)\s+"
            r"(?:(?:tests?|checks?|analyses|simulations?)\s+)?"
            r"(?:errors?|failures?|failed)\b",
            re.IGNORECASE,
        )
    
    # ============================================================
    # 公开方法
    # ============================================================
    
    def get_output_log_from_text(
        self,
        raw_output: str,
        max_lines: Optional[int] = None,
    ) -> List[LogLine]:
        """
        从文本解析日志行
        
        Args:
            raw_output: 原始输出文本
            max_lines: 最大返回行数；None 表示完整解析
            
        Returns:
            List[LogLine]: 日志行列表
        """
        if not raw_output:
            return []
        
        return self._parse_log_lines(raw_output, max_lines)

    def summarize_text(self, raw_output: str) -> SimulationSummary:
        """Count an entire log without truncating the diagnostic summary."""
        total = errors = warnings = 0
        first_error: Optional[str] = None
        for content in str(raw_output or "").splitlines():
            total += 1
            level = self._detect_log_level(content)
            if level == LogLevel.ERROR.value:
                errors += 1
                if first_error is None:
                    first_error = content
            elif level == LogLevel.WARNING.value:
                warnings += 1
        return SimulationSummary(
            total_lines=total,
            error_count=errors,
            warning_count=warnings,
            info_count=total - errors - warnings,
            first_error=first_error,
        )
    
    def filter_by_level(
        self,
        log_lines: List[LogLine],
        level: str
    ) -> List[LogLine]:
        """
        按日志级别过滤
        
        Args:
            log_lines: 日志行列表
            level: 日志级别（info/warning/error/all）
            
        Returns:
            List[LogLine]: 过滤后的日志行列表
        """
        if level == "all":
            return log_lines
        
        return [line for line in log_lines if line.level == level]
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _parse_log_lines(
        self,
        raw_output: str,
        max_lines: Optional[int]
    ) -> List[LogLine]:
        """
        解析日志行
        
        Args:
            raw_output: 原始输出文本
            max_lines: 最大行数
            
        Returns:
            List[LogLine]: 日志行列表
        """
        if not raw_output:
            return []
        
        if max_lines is not None and max_lines <= 0:
            return []
        lines = raw_output.splitlines()
        result = []

        selected = lines if max_lines is None else lines[:max_lines]
        for i, content in enumerate(selected, start=1):
            level = self._detect_log_level(content)
            result.append(LogLine(
                line_number=i,
                content=content,
                level=level,
            ))
        
        return result
    
    def _detect_log_level(self, content: str) -> str:
        """
        检测日志级别
        
        基于关键词匹配识别日志级别。
        优先级：error > warning > info
        
        Args:
            content: 日志内容
            
        Returns:
            str: 日志级别
        """
        if not content:
            return LogLevel.INFO.value

        # ngspice and wrappers often print successful summaries such as
        # "0 errors"; generic keyword matching must not turn those into a
        # failed-looking line.
        if self._negative_count_pattern.search(content):
            return LogLevel.INFO.value
        
        # 检查错误关键词
        if self._error_pattern.search(content):
            return LogLevel.ERROR.value
        
        # 检查警告关键词
        if self._warning_pattern.search(content):
            return LogLevel.WARNING.value
        
        return LogLevel.INFO.value


# ============================================================
# 模块级单例
# ============================================================

simulation_output_reader = SimulationOutputReader()
"""模块级单例，便于直接导入使用"""


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "LogLevel",
    "LogLine",
    "SimulationSummary",
    "SimulationOutputReader",
    "simulation_output_reader",
]
