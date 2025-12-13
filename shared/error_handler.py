# Error Handler - Unified Error Management
"""
统一错误处理器 - 集中管理应用错误的分类、处理、恢复和用户提示

职责：
- 错误分类（主分类 + 子分类）
- 恢复策略执行
- 用户提示（状态栏/弹窗）
- 错误日志记录
- 仿真错误解析

初始化顺序：
- Phase 1.2，依赖 Logger、EventBus（延迟获取）、ConfigManager

设计原则：
- 延迟获取 EventBus，避免初始化顺序问题
- 内部错误处理不递归调用自身
- 内部错误信息使用硬编码英文，不依赖 I18nManager

使用示例：
    from shared.error_handler import ErrorHandler
    
    error_handler = ErrorHandler()
    
    try:
        # 可能出错的操作
        result = risky_operation()
    except Exception as e:
        error_handler.handle_error(e, context={"operation": "risky_operation"})
"""

import re
import time
import traceback
from typing import Any, Callable, Dict, Optional, Tuple

from shared.error_types import (
    ErrorCategory,
    ErrorType,
    RecoveryStrategy,
    ERROR_CATEGORY_MAP,
    RECOVERY_STRATEGIES,
)
from shared.event_types import EVENT_ERROR_OCCURRED, EVENT_ERROR_RECOVERED


class ErrorHandler:
    """
    统一错误处理器
    
    集中管理应用错误的分类、处理、恢复和用户提示。
    
    循环依赖防护：
    - 延迟获取 EventBus 和 Logger
    - 内部错误使用 _internal_log() 直接输出
    - 维护 _is_handling 标志位防止递归
    """

    def __init__(self):
        # 延迟获取的服务
        self._event_bus = None
        self._logger = None
        
        # 递归调用防护
        self._is_handling = False
        
        # 用户通知回调（由 UI 层设置）
        self._notify_callback: Optional[Callable] = None

    # ============================================================
    # 延迟获取服务
    # ============================================================

    @property
    def event_bus(self):
        """延迟获取 EventBus"""
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
        """延迟获取 Logger"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("error_handler")
            except Exception:
                pass
        return self._logger

    # ============================================================
    # 内部日志（不依赖外部服务）
    # ============================================================

    def _internal_log(self, level: str, message: str):
        """
        内部日志输出
        
        用于 ErrorHandler 自身的错误处理，避免递归调用。
        使用硬编码英文，不依赖 I18nManager。
        """
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [{level}] [ErrorHandler] {message}")


    # ============================================================
    # 核心功能
    # ============================================================

    def handle_error(
        self,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
        category: Optional[ErrorCategory] = None,
    ) -> Tuple[ErrorCategory, ErrorType, RecoveryStrategy]:
        """
        统一错误处理入口
        
        Args:
            error: 异常对象
            context: 错误上下文信息（操作名、参数等）
            category: 强制指定的错误分类（可选）
            
        Returns:
            Tuple[ErrorCategory, ErrorType, RecoveryStrategy]: 分类结果和恢复策略
        """
        # 递归调用防护
        if self._is_handling:
            self._internal_log("WARNING", f"Recursive error handling detected: {error}")
            return (
                ErrorCategory.USER_ACTIONABLE,
                ErrorType.UNKNOWN,
                RECOVERY_STRATEGIES[ErrorType.UNKNOWN],
            )

        self._is_handling = True
        context = context or {}

        try:
            # 1. 分类错误
            error_category, error_type = self.classify_error(error)
            
            # 允许调用方强制指定分类
            if category is not None:
                error_category = category

            # 2. 获取恢复策略
            strategy = self.get_recovery_strategy(error_type)

            # 3. 记录错误日志
            self.log_error(error, context, error_type, error_category)

            # 4. 发布错误事件
            self._publish_error_event(error, error_type, error_category, strategy, context)

            # 5. 用户提示
            self.notify_user(error, error_category, error_type, strategy)

            return error_category, error_type, strategy

        except Exception as internal_error:
            # 内部错误不递归调用
            self._internal_log("CRITICAL", f"Internal error in handle_error: {internal_error}")
            return (
                ErrorCategory.USER_ACTIONABLE,
                ErrorType.UNKNOWN,
                RECOVERY_STRATEGIES[ErrorType.UNKNOWN],
            )
        finally:
            self._is_handling = False

    def classify_error(self, error: Exception) -> Tuple[ErrorCategory, ErrorType]:
        """
        自动分类错误类型
        
        Args:
            error: 异常对象
            
        Returns:
            Tuple[ErrorCategory, ErrorType]: 主分类和子分类
        """
        error_type = self._detect_error_type(error)
        error_category = ERROR_CATEGORY_MAP.get(error_type, ErrorCategory.USER_ACTIONABLE)
        return error_category, error_type

    def _detect_error_type(self, error: Exception) -> ErrorType:
        """根据异常类型和消息检测错误类型"""
        error_str = str(error).lower()
        error_class = type(error).__name__

        # 网络错误
        if "timeout" in error_str or "timed out" in error_str:
            return ErrorType.NETWORK_TIMEOUT
        if "connection" in error_str and ("refused" in error_str or "failed" in error_str):
            return ErrorType.NETWORK_CONNECTION

        # LLM API 错误
        if "401" in error_str or "unauthorized" in error_str or "invalid api key" in error_str:
            return ErrorType.LLM_AUTH_FAILED
        if "429" in error_str or "rate limit" in error_str or "too many requests" in error_str:
            return ErrorType.LLM_RATE_LIMIT
        if "context" in error_str and ("length" in error_str or "overflow" in error_str or "exceeded" in error_str):
            return ErrorType.LLM_CONTEXT_OVERFLOW
        if "parse" in error_str or "json" in error_str and "decode" in error_str:
            return ErrorType.LLM_RESPONSE_PARSE

        # 文件错误
        if error_class == "FileNotFoundError" or "no such file" in error_str:
            return ErrorType.FILE_NOT_FOUND
        if error_class == "PermissionError" or "permission denied" in error_str:
            return ErrorType.FILE_PERMISSION
        if "locked" in error_str or "in use" in error_str:
            return ErrorType.FILE_LOCKED

        # 系统错误
        if "disk" in error_str and "space" in error_str:
            return ErrorType.DISK_SPACE
        if error_class == "MemoryError" or "out of memory" in error_str:
            return ErrorType.MEMORY_OVERFLOW

        return ErrorType.UNKNOWN


    def get_recovery_strategy(self, error_type: ErrorType) -> RecoveryStrategy:
        """
        获取恢复策略
        
        Args:
            error_type: 错误类型
            
        Returns:
            RecoveryStrategy: 恢复策略配置
        """
        return RECOVERY_STRATEGIES.get(error_type, RECOVERY_STRATEGIES[ErrorType.UNKNOWN])

    def log_error(
        self,
        error: Exception,
        context: Dict[str, Any],
        error_type: ErrorType,
        error_category: ErrorCategory,
    ):
        """
        统一错误日志记录
        
        Args:
            error: 异常对象
            context: 错误上下文
            error_type: 错误类型
            error_category: 错误分类
        """
        # 格式化上下文
        context_str = ", ".join(f"{k}={v}" for k, v in context.items()) if context else "none"
        
        # 获取堆栈信息
        tb_str = "".join(traceback.format_exception(type(error), error, error.__traceback__))

        # 构建日志消息
        log_message = (
            f"Error occurred:\n"
            f"  Type: {error_type.value}\n"
            f"  Category: {error_category.name}\n"
            f"  Message: {error}\n"
            f"  Context: {context_str}\n"
            f"  Traceback:\n{tb_str}"
        )

        # 根据分类选择日志级别
        if self.logger:
            if error_category == ErrorCategory.FATAL:
                self.logger.critical(log_message)
            elif error_category == ErrorCategory.USER_ACTIONABLE:
                self.logger.error(log_message)
            else:
                self.logger.warning(log_message)
        else:
            # 回退到内部日志
            level = "CRITICAL" if error_category == ErrorCategory.FATAL else "ERROR"
            self._internal_log(level, log_message)

    def notify_user(
        self,
        error: Exception,
        error_category: ErrorCategory,
        error_type: ErrorType,
        strategy: RecoveryStrategy,
    ):
        """
        统一用户提示
        
        根据错误分类选择提示方式：
        - RECOVERABLE: 状态栏短暂提示
        - USER_ACTIONABLE: 非阻塞弹窗
        - FATAL: 模态弹窗
        
        Args:
            error: 异常对象
            error_category: 错误分类
            error_type: 错误类型
            strategy: 恢复策略
        """
        if self._notify_callback is None:
            # 无 UI 回调时，仅记录日志
            return

        try:
            self._notify_callback(
                error_category=error_category,
                error_type=error_type,
                message=strategy.user_message,
                hint=strategy.recovery_hint,
                error=error,
            )
        except Exception as e:
            self._internal_log("WARNING", f"Failed to notify user: {e}")

    def set_notify_callback(self, callback: Callable):
        """
        设置用户通知回调
        
        由 UI 层在初始化时调用，设置通知回调函数。
        
        Args:
            callback: 回调函数，签名为 (error_category, error_type, message, hint, error) -> None
        """
        self._notify_callback = callback

    def _publish_error_event(
        self,
        error: Exception,
        error_type: ErrorType,
        error_category: ErrorCategory,
        strategy: RecoveryStrategy,
        context: Dict[str, Any],
    ):
        """发布错误事件到 EventBus"""
        if self.event_bus is None:
            return

        try:
            event_data = {
                "error_type": error_type.value,
                "error_category": error_category.name,
                "message": str(error),
                "recovery_hint": strategy.recovery_hint,
                "context": context,
                "recoverable": error_category == ErrorCategory.RECOVERABLE,
            }
            self.event_bus.publish(EVENT_ERROR_OCCURRED, event_data, source="error_handler")
        except Exception as e:
            # EventBus 不可用时静默降级
            self._internal_log("WARNING", f"Failed to publish error event: {e}")


    # ============================================================
    # 仿真错误解析
    # ============================================================

    def parse_simulation_error(self, ngspice_output: str) -> Tuple[ErrorType, Dict[str, Any]]:
        """
        解析 ngspice 输出，识别具体错误类型
        
        通过正则匹配 ngspice 输出关键词，自动识别错误类型。
        
        Args:
            ngspice_output: ngspice 的标准输出/错误输出
            
        Returns:
            Tuple[ErrorType, Dict]: 错误类型和详细信息
        """
        output_lower = ngspice_output.lower()
        details: Dict[str, Any] = {"raw_output": ngspice_output}

        # 语法错误 - 提取行号
        syntax_match = re.search(r"error[:\s]+.*?line\s+(\d+)", output_lower)
        if syntax_match or "syntax error" in output_lower:
            if syntax_match:
                details["line_number"] = int(syntax_match.group(1))
            # 尝试提取错误描述
            error_line_match = re.search(r"error[:\s]+(.+?)(?:\n|$)", ngspice_output, re.IGNORECASE)
            if error_line_match:
                details["error_description"] = error_line_match.group(1).strip()
            return ErrorType.SIM_SYNTAX_ERROR, details

        # DC 收敛失败
        if "dc" in output_lower and ("convergence" in output_lower or "singular matrix" in output_lower):
            return ErrorType.SIM_CONVERGENCE_DC, details

        # 瞬态分析收敛失败
        if "tran" in output_lower and ("convergence" in output_lower or "timestep too small" in output_lower):
            return ErrorType.SIM_CONVERGENCE_TRAN, details

        # 模型缺失 - 提取模型名
        model_match = re.search(r"unknown\s+(?:model|subcircuit)\s+[:\s]*(\S+)", output_lower)
        if model_match or "model" in output_lower and "not found" in output_lower:
            if model_match:
                details["missing_model"] = model_match.group(1)
            return ErrorType.SIM_MODEL_MISSING, details

        # 浮空节点 - 提取节点名
        floating_match = re.search(r"(?:floating|unconnected)\s+node[:\s]*(\S+)", output_lower)
        if floating_match or "floating" in output_lower:
            if floating_match:
                details["floating_node"] = floating_match.group(1)
            return ErrorType.SIM_NODE_FLOATING, details

        # ngspice 崩溃
        if "segmentation fault" in output_lower or "core dumped" in output_lower or "fatal" in output_lower:
            return ErrorType.SIM_NGSPICE_CRASH, details

        # 超时（通常由外部检测，这里作为备用）
        if "timeout" in output_lower:
            return ErrorType.SIM_TIMEOUT, details

        # 未识别的仿真错误
        return ErrorType.UNKNOWN, details

    # ============================================================
    # 恢复执行辅助
    # ============================================================

    def execute_with_retry(
        self,
        operation: Callable,
        error_type: ErrorType,
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        带重试的操作执行
        
        根据错误类型的恢复策略自动重试。
        
        Args:
            operation: 要执行的操作（无参数的 callable）
            error_type: 预期的错误类型（用于获取重试策略）
            context: 错误上下文
            
        Returns:
            操作的返回值
            
        Raises:
            Exception: 重试耗尽后抛出最后一次异常
        """
        strategy = self.get_recovery_strategy(error_type)
        
        if not strategy.retry:
            return operation()

        last_error = None
        delay = strategy.retry_delay

        for attempt in range(strategy.max_retries + 1):
            try:
                return operation()
            except Exception as e:
                last_error = e
                
                if attempt < strategy.max_retries:
                    if self.logger:
                        self.logger.warning(
                            f"Attempt {attempt + 1}/{strategy.max_retries + 1} failed: {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                    time.sleep(delay)
                    
                    if strategy.exponential_backoff:
                        delay *= 2

        # 重试耗尽，处理最后的错误
        self.handle_error(last_error, context=context)
        raise last_error

    def notify_recovery(self, error_type: ErrorType, message: str = ""):
        """
        通知错误已恢复
        
        Args:
            error_type: 已恢复的错误类型
            message: 恢复消息
        """
        if self.event_bus:
            try:
                self.event_bus.publish(
                    EVENT_ERROR_RECOVERED,
                    {"error_type": error_type.value, "message": message},
                    source="error_handler",
                )
            except Exception:
                pass


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ErrorHandler",
]
