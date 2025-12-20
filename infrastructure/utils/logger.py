"""
统一日志管理器

职责：配置和管理应用日志系统，提供统一的日志规范和敏感信息过滤

初始化顺序：Phase 0.1，最先初始化，其他模块都依赖日志

使用方式：
    from infrastructure.utils.logger import setup_logger, get_logger
    
    # 程序启动时初始化
    setup_logger()
    
    # 在各模块中获取日志器
    logger = get_logger("my_module")
    logger.info("操作完成")
    
    # 记录性能日志
    log_performance("llm_call", 1234, "success")
    
    # 记录 API 调用日志
    log_api_call("openai", "/chat/completions", 200)
"""

import logging
import re
import sys
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

# 导入配置常量
from infrastructure.config.settings import GLOBAL_LOG_DIR


# ============================================================
# 模块级状态变量
# ============================================================

_initialized: bool = False
_loggers: dict = {}
_lock = threading.Lock()

# 敏感信息匹配模式
_SENSITIVE_PATTERNS = [
    # API 密钥模式（各种格式）
    (re.compile(r'(api[_-]?key|apikey|api_secret|secret[_-]?key)\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?', re.IGNORECASE), r'\1=***REDACTED***'),
    (re.compile(r'(sk-[a-zA-Z0-9]{20,})'), r'***REDACTED***'),
    (re.compile(r'(Bearer\s+)([a-zA-Z0-9_\-\.]{20,})', re.IGNORECASE), r'\1***REDACTED***'),
    # Authorization header
    (re.compile(r'(Authorization["\']?\s*:\s*["\']?)([^"\']+)(["\']?)', re.IGNORECASE), r'\1***REDACTED***\3'),
]

# 日志级别颜色（用于控制台输出）
_LEVEL_COLORS = {
    'DEBUG': '\033[36m',     # 青色
    'INFO': '\033[32m',      # 绿色
    'WARNING': '\033[33m',   # 黄色
    'ERROR': '\033[31m',     # 红色
    'CRITICAL': '\033[35m',  # 紫色
}
_RESET_COLOR = '\033[0m'


# ============================================================
# 自定义格式化器
# ============================================================

class SensitiveInfoFilter(logging.Filter):
    """
    敏感信息过滤器
    
    过滤日志消息中的敏感信息（API 密钥等）
    """
    
    def filter(self, record: logging.LogRecord) -> bool:
        """过滤并替换敏感信息"""
        if record.msg:
            record.msg = sanitize_message(str(record.msg))
        if record.args:
            record.args = tuple(
                sanitize_message(str(arg)) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True


class ColoredFormatter(logging.Formatter):
    """
    彩色日志格式化器（用于控制台输出）
    
    格式：[时间] [级别] [模块名] [线程ID] 消息
    """
    
    def __init__(self, use_color: bool = True):
        self.use_color = use_color
        super().__init__(
            fmt='[%(asctime)s] [%(levelname)-8s] [%(name)-20s] [%(thread)d] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    def format(self, record: logging.LogRecord) -> str:
        # 截断过长的模块名
        if len(record.name) > 20:
            record.name = record.name[:17] + '...'
        
        formatted = super().format(record)
        
        if self.use_color and sys.stdout.isatty():
            color = _LEVEL_COLORS.get(record.levelname, '')
            if color:
                formatted = f"{color}{formatted}{_RESET_COLOR}"
        
        return formatted


class FileFormatter(logging.Formatter):
    """
    文件日志格式化器（无颜色）
    
    格式：[时间] [级别] [模块名] [线程ID] 消息
    """
    
    def __init__(self):
        super().__init__(
            fmt='[%(asctime)s] [%(levelname)-8s] [%(name)-20s] [%(thread)d] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    def format(self, record: logging.LogRecord) -> str:
        # 截断过长的模块名
        if len(record.name) > 20:
            record.name = record.name[:17] + '...'
        return super().format(record)


# ============================================================
# 核心功能
# ============================================================

def setup_logger(
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
    log_dir: Optional[Path] = None
) -> None:
    """
    初始化日志系统
    
    配置控制台和文件输出，设置敏感信息过滤
    
    Args:
        console_level: 控制台日志级别，默认 INFO
        file_level: 文件日志级别，默认 DEBUG
        log_dir: 日志目录，默认使用 GLOBAL_LOG_DIR
    """
    global _initialized
    
    with _lock:
        if _initialized:
            return
        
        # 确定日志目录
        if log_dir is None:
            log_dir = GLOBAL_LOG_DIR
        
        # 确保日志目录存在
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # 获取根日志器
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)  # 根日志器设置最低级别
        
        # 清除已有的处理器
        root_logger.handlers.clear()
        
        # 添加敏感信息过滤器
        sensitive_filter = SensitiveInfoFilter()
        
        # 配置控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_level)
        console_handler.setFormatter(ColoredFormatter(use_color=True))
        console_handler.addFilter(sensitive_filter)
        root_logger.addHandler(console_handler)
        
        # 配置文件处理器（按大小轮转）
        log_file = log_dir / "app.log"
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(file_level)
        file_handler.setFormatter(FileFormatter())
        file_handler.addFilter(sensitive_filter)
        root_logger.addHandler(file_handler)
        
        # 配置每日轮转文件处理器（按时间轮转，保留7天）
        daily_log_file = log_dir / "app_daily.log"
        daily_handler = TimedRotatingFileHandler(
            daily_log_file,
            when='midnight',
            interval=1,
            backupCount=7,
            encoding='utf-8'
        )
        daily_handler.setLevel(file_level)
        daily_handler.setFormatter(FileFormatter())
        daily_handler.addFilter(sensitive_filter)
        daily_handler.suffix = "%Y-%m-%d"
        root_logger.addHandler(daily_handler)
        
        _initialized = True
    
    # 记录初始化完成（在锁外执行，避免死锁）
    logger = logging.getLogger("logger")
    logger.info(f"日志系统初始化完成，日志目录: {log_dir}")


def get_logger(name: str) -> logging.Logger:
    """
    获取命名日志器
    
    如果日志系统未初始化，会自动初始化
    
    Args:
        name: 日志器名称（通常为模块名）
        
    Returns:
        logging.Logger: 配置好的日志器
    """
    global _initialized
    
    # 确保日志系统已初始化
    if not _initialized:
        setup_logger()
    
    with _lock:
        if name not in _loggers:
            _loggers[name] = logging.getLogger(name)
        return _loggers[name]


# ============================================================
# 敏感信息过滤
# ============================================================

def sanitize_message(message: str) -> str:
    """
    过滤消息中的敏感信息
    
    替换 API 密钥等敏感内容为 ***REDACTED***
    
    Args:
        message: 原始消息
        
    Returns:
        str: 过滤后的消息
    """
    if not message:
        return message
    
    result = message
    for pattern, replacement in _SENSITIVE_PATTERNS:
        result = pattern.sub(replacement, result)
    
    return result


def truncate_content(content: str, max_length: int = 100, suffix: str = "...[truncated]") -> str:
    """
    截断过长的内容
    
    用于日志中截断用户输入、文件内容等
    
    Args:
        content: 原始内容
        max_length: 最大长度
        suffix: 截断后缀
        
    Returns:
        str: 截断后的内容
    """
    if not content or len(content) <= max_length:
        return content
    return content[:max_length] + suffix


# ============================================================
# 性能日志
# ============================================================

def log_performance(
    operation: str,
    duration_ms: float,
    status: str = "success",
    extra: Optional[dict] = None
) -> None:
    """
    记录性能日志
    
    格式：[PERF] operation=xxx duration=xxxms status=xxx
    
    Args:
        operation: 操作名称（如 llm_call, simulation, file_read）
        duration_ms: 耗时（毫秒）
        status: 状态（success/error/timeout）
        extra: 额外信息
    """
    logger = get_logger("performance")
    
    parts = [
        f"[PERF] operation={operation}",
        f"duration={duration_ms:.0f}ms",
        f"status={status}"
    ]
    
    if extra:
        for key, value in extra.items():
            parts.append(f"{key}={value}")
    
    logger.info(" ".join(parts))


def log_api_call(
    provider: str,
    endpoint: str,
    status_code: int,
    duration_ms: Optional[float] = None,
    error: Optional[str] = None
) -> None:
    """
    记录 API 调用日志
    
    Args:
        provider: 提供者（openai/claude/gemini 等）
        endpoint: API 端点
        status_code: HTTP 状态码
        duration_ms: 耗时（毫秒）
        error: 错误信息（如有）
    """
    logger = get_logger("api")
    
    parts = [
        f"[API] provider={provider}",
        f"endpoint={endpoint}",
        f"status={status_code}"
    ]
    
    if duration_ms is not None:
        parts.append(f"duration={duration_ms:.0f}ms")
    
    if error:
        parts.append(f"error={sanitize_message(error)}")
    
    if status_code >= 400:
        logger.warning(" ".join(parts))
    else:
        logger.info(" ".join(parts))


# ============================================================
# 日志清理
# ============================================================

def cleanup_old_logs(log_dir: Optional[Path] = None, max_age_days: int = 7) -> int:
    """
    清理过期的日志文件
    
    自动清理超过指定天数的日志文件，包括：
    - 按大小轮转的日志文件（app.log.1, app.log.2 等）
    - 按时间轮转的日志文件（app_daily.log.2024-01-01 等）
    
    Args:
        log_dir: 日志目录，默认使用 GLOBAL_LOG_DIR
        max_age_days: 最大保留天数，默认 7 天
        
    Returns:
        int: 删除的文件数量
    """
    if log_dir is None:
        log_dir = GLOBAL_LOG_DIR
    
    if not log_dir.exists():
        return 0
    
    deleted_count = 0
    cutoff_time = datetime.now().timestamp() - (max_age_days * 24 * 60 * 60)
    
    # 清理所有日志文件（包括轮转文件）
    log_patterns = ["*.log", "*.log.*"]
    for pattern in log_patterns:
        for log_file in log_dir.glob(pattern):
            try:
                if log_file.stat().st_mtime < cutoff_time:
                    log_file.unlink()
                    deleted_count += 1
            except Exception as e:
                # 删除失败不影响其他文件
                logger = get_logger("logger")
                logger.warning(f"删除日志文件失败: {log_file}, 错误: {e}")
    
    if deleted_count > 0:
        logger = get_logger("logger")
        logger.info(f"清理了 {deleted_count} 个过期日志文件")
    
    return deleted_count


# ============================================================
# 便捷函数
# ============================================================

def log_file_operation(
    operation: str,
    file_path: str,
    char_count: Optional[int] = None,
    success: bool = True
) -> None:
    """
    记录文件操作日志
    
    仅记录路径和字符数，不记录文件内容
    
    Args:
        operation: 操作类型（read/write/delete）
        file_path: 文件路径
        char_count: 字符数（读写操作时）
        success: 是否成功
    """
    logger = get_logger("file")
    
    parts = [f"[FILE] operation={operation}", f"path={file_path}"]
    
    if char_count is not None:
        parts.append(f"chars={char_count}")
    
    parts.append(f"success={success}")
    
    if success:
        logger.debug(" ".join(parts))
    else:
        logger.warning(" ".join(parts))


def log_simulation(
    operation: str,
    data_points: Optional[int] = None,
    duration_ms: Optional[float] = None,
    success: bool = True,
    error: Optional[str] = None
) -> None:
    """
    记录仿真操作日志
    
    仅记录数据点数量，不记录具体值
    
    Args:
        operation: 操作类型（run/parse/plot）
        data_points: 数据点数量
        duration_ms: 耗时（毫秒）
        success: 是否成功
        error: 错误信息
    """
    logger = get_logger("simulation")
    
    parts = [f"[SIM] operation={operation}"]
    
    if data_points is not None:
        parts.append(f"data_points={data_points}")
    
    if duration_ms is not None:
        parts.append(f"duration={duration_ms:.0f}ms")
    
    parts.append(f"success={success}")
    
    if error:
        parts.append(f"error={error}")
    
    if success:
        logger.info(" ".join(parts))
    else:
        logger.error(" ".join(parts))


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 核心功能
    "setup_logger",
    "get_logger",
    # 敏感信息过滤
    "sanitize_message",
    "truncate_content",
    # 性能日志
    "log_performance",
    "log_api_call",
    # 便捷函数
    "log_file_operation",
    "log_simulation",
    # 日志清理
    "cleanup_old_logs",
]
