# SimulationOutputReader - Simulation Output Log Reader
"""
仿真输出日志读取器

职责：
- 读取和解析仿真引擎的输出日志
- 识别日志级别（info/warning/error）
- 提供日志搜索和过滤功能
- 生成仿真摘要信息

设计原则：
- 从 SimulationResult.raw_output 字段读取日志
- 支持从文件路径或内存数据读取
- 日志级别基于关键词匹配识别
- 提供结构化的日志行数据

使用示例：
    from domain.simulation.data.simulation_output_reader import (
        SimulationOutputReader,
        simulation_output_reader,
    )
    
    # 从仿真结果文件读取日志
    log_lines = simulation_output_reader.get_output_log(
        sim_result_path="sim_results/run_001.json",
        project_root="/path/to/project",
        max_lines=1000
    )
    
    # 获取错误行
    errors = simulation_output_reader.get_error_lines(
        sim_result_path="sim_results/run_001.json",
        project_root="/path/to/project"
    )
    
    # 搜索日志
    matches = simulation_output_reader.search_log(
        sim_result_path="sim_results/run_001.json",
        project_root="/path/to/project",
        keyword="convergence"
    )
    
    # 获取仿真摘要
    summary = simulation_output_reader.get_simulation_summary(
        sim_result_path="sim_results/run_001.json",
        project_root="/path/to/project"
    )
"""

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.constants.paths import SYSTEM_DIR


# ============================================================
# 常量定义
# ============================================================

# 错误关键词（不区分大小写）
ERROR_KEYWORDS = [
    "error",
    "fatal",
    "failed",
    "failure",
    "exception",
    "abort",
    "cannot",
    "unable",
    "invalid",
    "illegal",
    "undefined",
    "no convergence",
    "singular matrix",
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

# 信息关键词（用于识别重要信息行）
INFO_KEYWORDS = [
    "analysis",
    "simulation",
    "circuit",
    "temperature",
    "completed",
    "finished",
    "starting",
    "loading",
    "parsing",
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
    """
    仿真摘要数据类
    
    Attributes:
        total_lines: 总行数
        error_count: 错误数
        warning_count: 警告数
        info_count: 信息数
        analysis_type: 分析类型
        duration_seconds: 执行耗时
        success: 是否成功
        first_error: 第一个错误信息
        timestamp: 时间戳
    """
    
    total_lines: int = 0
    """总行数"""
    
    error_count: int = 0
    """错误数"""
    
    warning_count: int = 0
    """警告数"""
    
    info_count: int = 0
    """信息数"""
    
    analysis_type: str = ""
    """分析类型"""
    
    duration_seconds: float = 0.0
    """执行耗时（秒）"""
    
    success: bool = True
    """是否成功"""
    
    first_error: Optional[str] = None
    """第一个错误信息"""
    
    timestamp: str = ""
    """时间戳"""
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "total_lines": self.total_lines,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "analysis_type": self.analysis_type,
            "duration_seconds": self.duration_seconds,
            "success": self.success,
            "first_error": self.first_error,
            "timestamp": self.timestamp,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimulationSummary":
        """从字典反序列化"""
        return cls(
            total_lines=data.get("total_lines", 0),
            error_count=data.get("error_count", 0),
            warning_count=data.get("warning_count", 0),
            info_count=data.get("info_count", 0),
            analysis_type=data.get("analysis_type", ""),
            duration_seconds=data.get("duration_seconds", 0.0),
            success=data.get("success", True),
            first_error=data.get("first_error"),
            timestamp=data.get("timestamp", ""),
        )


# ============================================================
# SimulationOutputReader - 仿真输出日志读取器
# ============================================================

class SimulationOutputReader:
    """
    仿真输出日志读取器
    
    提供仿真输出日志的读取、解析、搜索和过滤功能。
    """
    
    def __init__(self):
        """初始化读取器"""
        self._logger = logging.getLogger(__name__)
        
        # 编译正则表达式（提高性能）
        self._error_pattern = re.compile(
            r'\b(' + '|'.join(ERROR_KEYWORDS) + r')\b',
            re.IGNORECASE
        )
        self._warning_pattern = re.compile(
            r'\b(' + '|'.join(WARNING_KEYWORDS) + r')\b',
            re.IGNORECASE
        )
    
    # ============================================================
    # 公开方法
    # ============================================================
    
    def get_output_log(
        self,
        sim_result_path: str,
        project_root: str,
        max_lines: int = 10000
    ) -> List[LogLine]:
        """
        获取仿真输出日志
        
        Args:
            sim_result_path: 仿真结果相对路径（相对于 .circuit_ai/）
            project_root: 项目根目录
            max_lines: 最大返回行数
            
        Returns:
            List[LogLine]: 日志行列表
        """
        raw_output = self._load_raw_output(sim_result_path, project_root)
        if not raw_output:
            return []
        
        return self._parse_log_lines(raw_output, max_lines)
    
    def get_output_log_from_text(
        self,
        raw_output: str,
        max_lines: int = 10000
    ) -> List[LogLine]:
        """
        从文本解析日志行
        
        Args:
            raw_output: 原始输出文本
            max_lines: 最大返回行数
            
        Returns:
            List[LogLine]: 日志行列表
        """
        if not raw_output:
            return []
        
        return self._parse_log_lines(raw_output, max_lines)
    
    def get_error_lines(
        self,
        sim_result_path: str,
        project_root: str
    ) -> List[LogLine]:
        """
        获取错误行
        
        Args:
            sim_result_path: 仿真结果相对路径
            project_root: 项目根目录
            
        Returns:
            List[LogLine]: 错误行列表
        """
        all_lines = self.get_output_log(sim_result_path, project_root)
        return [line for line in all_lines if line.is_error()]
    
    def get_warning_lines(
        self,
        sim_result_path: str,
        project_root: str
    ) -> List[LogLine]:
        """
        获取警告行
        
        Args:
            sim_result_path: 仿真结果相对路径
            project_root: 项目根目录
            
        Returns:
            List[LogLine]: 警告行列表
        """
        all_lines = self.get_output_log(sim_result_path, project_root)
        return [line for line in all_lines if line.is_warning()]
    
    def search_log(
        self,
        sim_result_path: str,
        project_root: str,
        keyword: str,
        case_sensitive: bool = False
    ) -> List[LogLine]:
        """
        搜索日志内容
        
        Args:
            sim_result_path: 仿真结果相对路径
            project_root: 项目根目录
            keyword: 搜索关键词
            case_sensitive: 是否区分大小写
            
        Returns:
            List[LogLine]: 匹配的日志行列表
        """
        if not keyword:
            return []
        
        all_lines = self.get_output_log(sim_result_path, project_root)
        
        if case_sensitive:
            return [line for line in all_lines if keyword in line.content]
        else:
            keyword_lower = keyword.lower()
            return [line for line in all_lines if keyword_lower in line.content.lower()]
    
    def search_log_regex(
        self,
        sim_result_path: str,
        project_root: str,
        pattern: str
    ) -> List[LogLine]:
        """
        使用正则表达式搜索日志
        
        Args:
            sim_result_path: 仿真结果相对路径
            project_root: 项目根目录
            pattern: 正则表达式模式
            
        Returns:
            List[LogLine]: 匹配的日志行列表
        """
        if not pattern:
            return []
        
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            self._logger.warning(f"无效的正则表达式: {pattern}, 错误: {e}")
            return []
        
        all_lines = self.get_output_log(sim_result_path, project_root)
        return [line for line in all_lines if regex.search(line.content)]
    
    def get_simulation_summary(
        self,
        sim_result_path: str,
        project_root: str
    ) -> SimulationSummary:
        """
        获取仿真摘要
        
        Args:
            sim_result_path: 仿真结果相对路径
            project_root: 项目根目录
            
        Returns:
            SimulationSummary: 仿真摘要
        """
        # 加载仿真结果元数据
        result_data = self._load_result_data(sim_result_path, project_root)
        
        # 解析日志行
        raw_output = result_data.get("raw_output", "") if result_data else ""
        log_lines = self._parse_log_lines(raw_output, max_lines=10000)
        
        # 统计各级别数量
        error_count = sum(1 for line in log_lines if line.is_error())
        warning_count = sum(1 for line in log_lines if line.is_warning())
        info_count = len(log_lines) - error_count - warning_count
        
        # 获取第一个错误
        first_error = None
        for line in log_lines:
            if line.is_error():
                first_error = line.content
                break
        
        return SimulationSummary(
            total_lines=len(log_lines),
            error_count=error_count,
            warning_count=warning_count,
            info_count=info_count,
            analysis_type=result_data.get("analysis_type", "") if result_data else "",
            duration_seconds=result_data.get("duration_seconds", 0.0) if result_data else 0.0,
            success=result_data.get("success", True) if result_data else True,
            first_error=first_error,
            timestamp=result_data.get("timestamp", "") if result_data else "",
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
    
    def _load_raw_output(
        self,
        sim_result_path: str,
        project_root: str
    ) -> Optional[str]:
        """
        从仿真结果文件加载原始输出
        
        Args:
            sim_result_path: 仿真结果相对路径
            project_root: 项目根目录
            
        Returns:
            Optional[str]: 原始输出文本
        """
        result_data = self._load_result_data(sim_result_path, project_root)
        if not result_data:
            return None
        
        return result_data.get("raw_output")
    
    def _load_result_data(
        self,
        sim_result_path: str,
        project_root: str
    ) -> Optional[Dict[str, Any]]:
        """
        加载仿真结果数据
        
        Args:
            sim_result_path: 仿真结果相对路径
            project_root: 项目根目录
            
        Returns:
            Optional[Dict]: 仿真结果数据
        """
        if not sim_result_path or not project_root:
            return None
        
        # 构建完整路径
        full_path = Path(project_root) / SYSTEM_DIR / sim_result_path
        
        if not full_path.exists():
            self._logger.warning(f"仿真结果文件不存在: {full_path}")
            return None
        
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            self._logger.error(f"加载仿真结果失败: {full_path}, 错误: {e}")
            return None
    
    def _parse_log_lines(
        self,
        raw_output: str,
        max_lines: int
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
        
        lines = raw_output.splitlines()
        result = []
        
        for i, content in enumerate(lines[:max_lines], start=1):
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
