# Error Type Constants
"""
错误类型常量定义

职责：
- 集中定义所有错误分类和类型常量
- 定义恢复策略映射
- 作为 ErrorHandler 错误分类的基础

设计原则：
- 纯常量和枚举定义，不依赖任何其他模块
- 错误类型按模块分组组织
- 每个错误类型关联一个主分类和恢复策略
"""

from enum import Enum, auto
from typing import Dict, Any


class ErrorCategory(Enum):
    """错误主分类"""
    
    # 可自动恢复（如网络超时重试）
    RECOVERABLE = auto()
    
    # 需用户操作（如 API Key 无效）
    USER_ACTIONABLE = auto()
    
    # 致命错误（需重启应用）
    FATAL = auto()


class ErrorType(Enum):
    """错误子分类 - 按模块细分"""
    
    # ============================================================
    # 网络错误
    # ============================================================
    NETWORK_TIMEOUT = "network_timeout"
    NETWORK_CONNECTION = "network_connection"
    
    # ============================================================
    # LLM API 错误
    # ============================================================
    LLM_AUTH_FAILED = "llm_auth_failed"
    LLM_RATE_LIMIT = "llm_rate_limit"
    LLM_RESPONSE_PARSE = "llm_response_parse"
    LLM_CONTEXT_OVERFLOW = "llm_context_overflow"
    
    # ============================================================
    # 仿真错误
    # ============================================================
    SIM_SYNTAX_ERROR = "sim_syntax_error"
    SIM_CONVERGENCE_DC = "sim_convergence_dc"
    SIM_CONVERGENCE_TRAN = "sim_convergence_tran"
    SIM_MODEL_MISSING = "sim_model_missing"
    SIM_NODE_FLOATING = "sim_node_floating"
    SIM_TIMEOUT = "sim_timeout"
    SIM_NGSPICE_CRASH = "sim_ngspice_crash"
    
    # ============================================================
    # 文件错误
    # ============================================================
    FILE_NOT_FOUND = "file_not_found"
    FILE_PERMISSION = "file_permission"
    FILE_LOCKED = "file_locked"
    FILE_CORRUPTED = "file_corrupted"
    
    # ============================================================
    # 系统错误
    # ============================================================
    DISK_SPACE = "disk_space"
    MEMORY_OVERFLOW = "memory_overflow"
    
    # ============================================================
    # 未知错误
    # ============================================================
    UNKNOWN = "unknown"


# ============================================================
# 错误类型到主分类的映射
# ============================================================

ERROR_CATEGORY_MAP: Dict[ErrorType, ErrorCategory] = {
    # 网络错误 - 可恢复
    ErrorType.NETWORK_TIMEOUT: ErrorCategory.RECOVERABLE,
    ErrorType.NETWORK_CONNECTION: ErrorCategory.RECOVERABLE,
    
    # LLM API 错误
    ErrorType.LLM_AUTH_FAILED: ErrorCategory.USER_ACTIONABLE,
    ErrorType.LLM_RATE_LIMIT: ErrorCategory.RECOVERABLE,
    ErrorType.LLM_RESPONSE_PARSE: ErrorCategory.RECOVERABLE,
    ErrorType.LLM_CONTEXT_OVERFLOW: ErrorCategory.USER_ACTIONABLE,
    
    # 仿真错误
    ErrorType.SIM_SYNTAX_ERROR: ErrorCategory.USER_ACTIONABLE,
    ErrorType.SIM_CONVERGENCE_DC: ErrorCategory.USER_ACTIONABLE,
    ErrorType.SIM_CONVERGENCE_TRAN: ErrorCategory.USER_ACTIONABLE,
    ErrorType.SIM_MODEL_MISSING: ErrorCategory.USER_ACTIONABLE,
    ErrorType.SIM_NODE_FLOATING: ErrorCategory.USER_ACTIONABLE,
    ErrorType.SIM_TIMEOUT: ErrorCategory.RECOVERABLE,
    ErrorType.SIM_NGSPICE_CRASH: ErrorCategory.USER_ACTIONABLE,
    
    # 文件错误
    ErrorType.FILE_NOT_FOUND: ErrorCategory.USER_ACTIONABLE,
    ErrorType.FILE_PERMISSION: ErrorCategory.USER_ACTIONABLE,
    ErrorType.FILE_LOCKED: ErrorCategory.RECOVERABLE,
    ErrorType.FILE_CORRUPTED: ErrorCategory.USER_ACTIONABLE,
    
    # 系统错误
    ErrorType.DISK_SPACE: ErrorCategory.USER_ACTIONABLE,
    ErrorType.MEMORY_OVERFLOW: ErrorCategory.FATAL,
    
    # 未知错误
    ErrorType.UNKNOWN: ErrorCategory.USER_ACTIONABLE,
}


# ============================================================
# 恢复策略定义
# ============================================================

class RecoveryStrategy:
    """恢复策略配置"""
    
    def __init__(
        self,
        retry: bool = False,
        max_retries: int = 0,
        retry_delay: float = 1.0,
        exponential_backoff: bool = False,
        user_message: str = "",
        recovery_hint: str = "",
    ):
        self.retry = retry
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.exponential_backoff = exponential_backoff
        self.user_message = user_message
        self.recovery_hint = recovery_hint


# 恢复策略映射
RECOVERY_STRATEGIES: Dict[ErrorType, RecoveryStrategy] = {
    # 网络错误
    ErrorType.NETWORK_TIMEOUT: RecoveryStrategy(
        retry=True,
        max_retries=3,
        retry_delay=1.0,
        exponential_backoff=True,
        user_message="Network timeout",
        recovery_hint="Retrying with exponential backoff...",
    ),
    ErrorType.NETWORK_CONNECTION: RecoveryStrategy(
        retry=True,
        max_retries=3,
        retry_delay=2.0,
        exponential_backoff=True,
        user_message="Network connection failed",
        recovery_hint="Please check your network connection",
    ),
    
    # LLM API 错误
    ErrorType.LLM_AUTH_FAILED: RecoveryStrategy(
        retry=False,
        user_message="API authentication failed",
        recovery_hint="Please check your API Key in settings",
    ),
    ErrorType.LLM_RATE_LIMIT: RecoveryStrategy(
        retry=True,
        max_retries=2,
        retry_delay=30.0,
        exponential_backoff=False,
        user_message="API rate limit exceeded",
        recovery_hint="Waiting before retry. Consider upgrading your API plan",
    ),
    ErrorType.LLM_RESPONSE_PARSE: RecoveryStrategy(
        retry=True,
        max_retries=1,
        retry_delay=0.5,
        user_message="Failed to parse LLM response",
        recovery_hint="Retrying request...",
    ),
    ErrorType.LLM_CONTEXT_OVERFLOW: RecoveryStrategy(
        retry=False,
        user_message="Context length exceeded",
        recovery_hint="Please compress the conversation history",
    ),

    # 仿真错误
    ErrorType.SIM_SYNTAX_ERROR: RecoveryStrategy(
        retry=False,
        user_message="SPICE syntax error",
        recovery_hint="Check the error line number and fix the syntax",
    ),
    ErrorType.SIM_CONVERGENCE_DC: RecoveryStrategy(
        retry=False,
        user_message="DC analysis convergence failed",
        recovery_hint="Check power connections, add initial conditions, or reduce accuracy",
    ),
    ErrorType.SIM_CONVERGENCE_TRAN: RecoveryStrategy(
        retry=False,
        user_message="Transient analysis convergence failed",
        recovery_hint="Reduce time step or check nonlinear components",
    ),
    ErrorType.SIM_MODEL_MISSING: RecoveryStrategy(
        retry=False,
        user_message="Missing device model",
        recovery_hint="Add .model or .lib statement for the missing model",
    ),
    ErrorType.SIM_NODE_FLOATING: RecoveryStrategy(
        retry=False,
        user_message="Floating node detected",
        recovery_hint="Add ground connection or bias to the floating node",
    ),
    ErrorType.SIM_TIMEOUT: RecoveryStrategy(
        retry=True,
        max_retries=1,
        retry_delay=0,
        user_message="Simulation timeout",
        recovery_hint="Retrying with reduced accuracy...",
    ),
    ErrorType.SIM_NGSPICE_CRASH: RecoveryStrategy(
        retry=False,
        user_message="ngspice crashed",
        recovery_hint="Simplify the circuit or check for invalid parameters",
    ),
    
    # 文件错误
    ErrorType.FILE_NOT_FOUND: RecoveryStrategy(
        retry=False,
        user_message="File not found",
        recovery_hint="Check the file path",
    ),
    ErrorType.FILE_PERMISSION: RecoveryStrategy(
        retry=False,
        user_message="File permission denied",
        recovery_hint="Check file permissions or run as administrator",
    ),
    ErrorType.FILE_LOCKED: RecoveryStrategy(
        retry=True,
        max_retries=3,
        retry_delay=1.0,
        user_message="File is locked",
        recovery_hint="Waiting for file lock to be released...",
    ),
    ErrorType.FILE_CORRUPTED: RecoveryStrategy(
        retry=False,
        user_message="File is corrupted",
        recovery_hint="Restore from backup or recreate the file",
    ),
    
    # 系统错误
    ErrorType.DISK_SPACE: RecoveryStrategy(
        retry=False,
        user_message="Insufficient disk space",
        recovery_hint="Free up disk space and try again",
    ),
    ErrorType.MEMORY_OVERFLOW: RecoveryStrategy(
        retry=False,
        user_message="Out of memory",
        recovery_hint="Close other applications and restart",
    ),
    
    # 未知错误
    ErrorType.UNKNOWN: RecoveryStrategy(
        retry=False,
        user_message="An unexpected error occurred",
        recovery_hint="Check the log file for details",
    ),
}


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ErrorCategory",
    "ErrorType",
    "RecoveryStrategy",
    "ERROR_CATEGORY_MAP",
    "RECOVERY_STRATEGIES",
]
