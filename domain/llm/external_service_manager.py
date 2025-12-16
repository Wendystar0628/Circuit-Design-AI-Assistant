# External Service Manager - Unified External Service Management
"""
外部服务统一管理器 - 管理所有外部服务的调用、重试、熔断和监控

职责：
- 统一管理 LLM API、搜索 API 等外部服务调用
- 实现指数退避重试策略
- 实现熔断机制保护系统
- 统计调用数据

初始化顺序：Phase 3 延迟初始化阶段

使用示例：
    from domain.llm.external_service_manager import ExternalServiceManager
    
    manager = ExternalServiceManager()
    result = await manager.call_service(SERVICE_LLM_ZHIPU, request)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Generator, List, Optional, Union


# ============================================================
# 服务类型常量
# ============================================================

# LLM 服务
SERVICE_LLM_ZHIPU = "llm_zhipu"           # 智谱 GLM（当前版本主要支持）
SERVICE_LLM_GEMINI = "llm_gemini"         # Google Gemini
SERVICE_LLM_OPENAI = "llm_openai"         # OpenAI GPT
SERVICE_LLM_CLAUDE = "llm_claude"         # Anthropic Claude
SERVICE_LLM_QWEN = "llm_qwen"             # 阿里通义千问
SERVICE_LLM_DEEPSEEK = "llm_deepseek"     # DeepSeek

# 搜索服务
SERVICE_SEARCH_ZHIPU = "search_zhipu"     # 智谱内置搜索（无需额外认证）
SERVICE_SEARCH_GOOGLE = "search_google"   # Google Custom Search
SERVICE_SEARCH_BING = "search_bing"       # Bing Web Search

# 所有服务类型
ALL_SERVICE_TYPES = [
    SERVICE_LLM_ZHIPU, SERVICE_LLM_GEMINI, SERVICE_LLM_OPENAI,
    SERVICE_LLM_CLAUDE, SERVICE_LLM_QWEN, SERVICE_LLM_DEEPSEEK,
    SERVICE_SEARCH_ZHIPU, SERVICE_SEARCH_GOOGLE, SERVICE_SEARCH_BING,
]


# ============================================================
# 重试和熔断配置
# ============================================================

# 默认重试配置
DEFAULT_RETRY_CONFIG = {
    "max_retries": 3,
    "initial_delay": 1.0,      # 初始延迟（秒）
    "max_delay": 30.0,         # 最大延迟（秒）
    "exponential_base": 2.0,   # 指数基数
}

# 默认熔断配置
DEFAULT_CIRCUIT_BREAKER_CONFIG = {
    "failure_threshold": 5,    # 连续失败阈值
    "recovery_timeout": 60.0,  # 熔断持续时间（秒）
    "half_open_requests": 1,   # 半开状态允许的请求数
}

# 默认超时配置
DEFAULT_TIMEOUT_CONFIG = {
    "connect": 10.0,           # 连接超时（秒）
    "read": 60.0,              # 读取超时（秒）
    "stream": 300.0,           # 流式请求超时（秒）
}

# 可重试的错误类型
RETRYABLE_ERRORS = (
    "timeout",
    "connection_error",
    "server_error",  # 5xx
    "rate_limit",    # 429
)

# 不可重试的错误类型
NON_RETRYABLE_ERRORS = (
    "auth_failed",       # 401, 403
    "invalid_request",   # 400
    "not_found",         # 404
    "context_overflow",  # Token 超限
)


# ============================================================
# 枚举和数据类
# ============================================================

class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"       # 正常状态
    OPEN = "open"           # 熔断状态
    HALF_OPEN = "half_open" # 半开状态


class ServiceStatus(Enum):
    """服务状态"""
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass
class CallStatistics:
    """调用统计"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_latency_ms: float = 0.0
    retried_calls: int = 0
    circuit_breaks: int = 0
    last_call_time: Optional[float] = None
    last_error: Optional[str] = None
    
    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_calls == 0:
            return 0.0
        return self.successful_calls / self.total_calls
    
    @property
    def average_latency_ms(self) -> float:
        """平均延迟（毫秒）"""
        if self.successful_calls == 0:
            return 0.0
        return self.total_latency_ms / self.successful_calls


@dataclass
class CircuitBreaker:
    """熔断器"""
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: Optional[float] = None
    half_open_requests: int = 0
    config: Dict[str, Any] = field(default_factory=lambda: DEFAULT_CIRCUIT_BREAKER_CONFIG.copy())
    
    def record_success(self) -> None:
        """记录成功调用"""
        self.failure_count = 0
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.half_open_requests = 0
    
    def record_failure(self) -> None:
        """记录失败调用"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.config["failure_threshold"]:
            self.state = CircuitState.OPEN
    
    def can_execute(self) -> bool:
        """检查是否可以执行请求"""
        if self.state == CircuitState.CLOSED:
            return True
        
        if self.state == CircuitState.OPEN:
            # 检查是否可以进入半开状态
            if self.last_failure_time:
                elapsed = time.time() - self.last_failure_time
                if elapsed >= self.config["recovery_timeout"]:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_requests = 0
                    return True
            return False
        
        if self.state == CircuitState.HALF_OPEN:
            # 半开状态允许有限请求
            if self.half_open_requests < self.config["half_open_requests"]:
                self.half_open_requests += 1
                return True
            return False
        
        return False


@dataclass
class ServiceCallResult:
    """服务调用结果"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    latency_ms: float = 0.0
    retries: int = 0
    is_degraded: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamingResult:
    """流式调用结果"""
    generator: Generator
    is_partial: bool = False
    received_tokens: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# ExternalServiceManager 类
# ============================================================

class ExternalServiceManager:
    """
    外部服务统一管理器
    
    职责：
    - 统一管理所有外部服务的调用
    - 实现指数退避重试策略
    - 实现熔断机制保护系统
    - 统计调用数据
    """
    
    def __init__(self):
        """初始化管理器"""
        self._logger = logging.getLogger(__name__)
        
        # 注册的服务客户端
        self._clients: Dict[str, Any] = {}
        
        # 熔断器（每个服务一个）
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        
        # 调用统计（每个服务一个）
        self._statistics: Dict[str, CallStatistics] = {}
        
        # 超时配置（每个服务可独立配置）
        self._timeout_configs: Dict[str, Dict[str, float]] = {}
        
        # 重试配置（每个服务可独立配置）
        self._retry_configs: Dict[str, Dict[str, Any]] = {}
        
        # 初始化所有服务的默认配置
        for service_type in ALL_SERVICE_TYPES:
            self._circuit_breakers[service_type] = CircuitBreaker()
            self._statistics[service_type] = CallStatistics()
            self._timeout_configs[service_type] = DEFAULT_TIMEOUT_CONFIG.copy()
            self._retry_configs[service_type] = DEFAULT_RETRY_CONFIG.copy()
    
    # ============================================================
    # 服务注册
    # ============================================================
    
    def register_service(self, service_type: str, client: Any) -> None:
        """
        注册服务客户端
        
        Args:
            service_type: 服务类型常量
            client: 服务客户端实例
        """
        self._clients[service_type] = client
        self._logger.info(f"Service registered: {service_type}")
    
    def unregister_service(self, service_type: str) -> None:
        """
        注销服务客户端
        
        Args:
            service_type: 服务类型常量
        """
        if service_type in self._clients:
            del self._clients[service_type]
            self._logger.info(f"Service unregistered: {service_type}")
    
    def get_client(self, service_type: str) -> Optional[Any]:
        """
        获取服务客户端
        
        Args:
            service_type: 服务类型常量
            
        Returns:
            服务客户端实例，未注册时返回 None
        """
        return self._clients.get(service_type)
    
    # ============================================================
    # 配置管理
    # ============================================================
    
    def set_circuit_breaker(
        self,
        service_type: str,
        config: Dict[str, Any]
    ) -> None:
        """
        配置熔断器
        
        Args:
            service_type: 服务类型
            config: 熔断配置
        """
        if service_type in self._circuit_breakers:
            self._circuit_breakers[service_type].config.update(config)
            self._logger.debug(f"Circuit breaker config updated for {service_type}")
    
    def set_timeout(
        self,
        service_type: str,
        config: Dict[str, float]
    ) -> None:
        """
        设置超时配置
        
        Args:
            service_type: 服务类型
            config: 超时配置 {"connect": float, "read": float, "stream": float}
        """
        if service_type not in self._timeout_configs:
            self._timeout_configs[service_type] = DEFAULT_TIMEOUT_CONFIG.copy()
        self._timeout_configs[service_type].update(config)
    
    def set_retry_config(
        self,
        service_type: str,
        config: Dict[str, Any]
    ) -> None:
        """
        设置重试配置
        
        Args:
            service_type: 服务类型
            config: 重试配置
        """
        if service_type not in self._retry_configs:
            self._retry_configs[service_type] = DEFAULT_RETRY_CONFIG.copy()
        self._retry_configs[service_type].update(config)
    
    def get_timeout(self, service_type: str) -> Dict[str, float]:
        """获取超时配置"""
        return self._timeout_configs.get(service_type, DEFAULT_TIMEOUT_CONFIG.copy())
    
    # ============================================================
    # 服务状态
    # ============================================================
    
    def get_service_status(self, service_type: str) -> ServiceStatus:
        """
        获取服务状态
        
        Args:
            service_type: 服务类型
            
        Returns:
            服务状态枚举
        """
        # 检查是否注册
        if service_type not in self._clients:
            return ServiceStatus.UNAVAILABLE
        
        # 检查熔断器状态
        breaker = self._circuit_breakers.get(service_type)
        if breaker:
            if breaker.state == CircuitState.OPEN:
                return ServiceStatus.UNAVAILABLE
            if breaker.state == CircuitState.HALF_OPEN:
                return ServiceStatus.DEGRADED
        
        return ServiceStatus.AVAILABLE
    
    def get_all_service_status(self) -> Dict[str, ServiceStatus]:
        """获取所有服务状态"""
        return {
            service_type: self.get_service_status(service_type)
            for service_type in ALL_SERVICE_TYPES
        }
    
    # ============================================================
    # 调用统计
    # ============================================================
    
    def get_call_statistics(self, service_type: str) -> CallStatistics:
        """
        获取调用统计
        
        Args:
            service_type: 服务类型
            
        Returns:
            调用统计对象
        """
        return self._statistics.get(service_type, CallStatistics())
    
    def get_all_statistics(self) -> Dict[str, CallStatistics]:
        """获取所有服务的调用统计"""
        return self._statistics.copy()
    
    def reset_statistics(self, service_type: Optional[str] = None) -> None:
        """
        重置调用统计
        
        Args:
            service_type: 服务类型，None 表示重置所有
        """
        if service_type:
            self._statistics[service_type] = CallStatistics()
        else:
            for st in ALL_SERVICE_TYPES:
                self._statistics[st] = CallStatistics()
    
    def export_statistics_report(self) -> Dict[str, Any]:
        """
        导出统计报告
        
        Returns:
            统计报告字典
        """
        report = {
            "timestamp": time.time(),
            "services": {}
        }
        
        for service_type, stats in self._statistics.items():
            breaker = self._circuit_breakers.get(service_type)
            report["services"][service_type] = {
                "total_calls": stats.total_calls,
                "successful_calls": stats.successful_calls,
                "failed_calls": stats.failed_calls,
                "success_rate": f"{stats.success_rate:.2%}",
                "average_latency_ms": f"{stats.average_latency_ms:.2f}",
                "retried_calls": stats.retried_calls,
                "circuit_breaks": stats.circuit_breaks,
                "circuit_state": breaker.state.value if breaker else "unknown",
                "last_error": stats.last_error,
            }
        
        return report

    
    # ============================================================
    # 服务调用
    # ============================================================
    
    async def call_service(
        self,
        service_type: str,
        request: Any,
        method: str = "call",
        is_streaming: bool = False,
        **kwargs
    ) -> ServiceCallResult:
        """
        统一服务调用入口
        
        Args:
            service_type: 服务类型
            request: 请求数据
            method: 调用方法名
            is_streaming: 是否为流式请求
            **kwargs: 额外参数
            
        Returns:
            ServiceCallResult 调用结果
        """
        start_time = time.time()
        stats = self._statistics.get(service_type, CallStatistics())
        breaker = self._circuit_breakers.get(service_type)
        
        # 更新统计
        stats.total_calls += 1
        stats.last_call_time = start_time
        
        # 检查熔断器
        if breaker and not breaker.can_execute():
            stats.circuit_breaks += 1
            self._logger.warning(f"Circuit breaker open for {service_type}")
            return self._create_degraded_response(service_type, "Circuit breaker is open")
        
        # 获取客户端
        client = self._clients.get(service_type)
        if not client:
            return ServiceCallResult(
                success=False,
                error=f"Service not registered: {service_type}",
                error_type="not_registered"
            )
        
        # 执行调用（带重试）
        if is_streaming:
            result = await self._call_streaming(
                service_type, client, request, method, **kwargs
            )
        else:
            result = await self._call_with_retry(
                service_type, client, request, method, **kwargs
            )
        
        # 更新统计和熔断器
        latency_ms = (time.time() - start_time) * 1000
        result.latency_ms = latency_ms
        
        if result.success:
            stats.successful_calls += 1
            stats.total_latency_ms += latency_ms
            if breaker:
                breaker.record_success()
        else:
            stats.failed_calls += 1
            stats.last_error = result.error
            if breaker and self._is_circuit_break_error(result.error_type):
                breaker.record_failure()
        
        if result.retries > 0:
            stats.retried_calls += 1
        
        return result
    
    async def _call_with_retry(
        self,
        service_type: str,
        client: Any,
        request: Any,
        method: str,
        **kwargs
    ) -> ServiceCallResult:
        """
        带重试的服务调用
        
        Args:
            service_type: 服务类型
            client: 服务客户端
            request: 请求数据
            method: 调用方法名
            
        Returns:
            ServiceCallResult
        """
        retry_config = self._retry_configs.get(service_type, DEFAULT_RETRY_CONFIG)
        max_retries = retry_config["max_retries"]
        initial_delay = retry_config["initial_delay"]
        max_delay = retry_config["max_delay"]
        exponential_base = retry_config["exponential_base"]
        
        last_error = None
        last_error_type = None
        retries = 0
        
        for attempt in range(max_retries + 1):
            try:
                # 获取调用方法
                call_method = getattr(client, method, None)
                if not call_method:
                    return ServiceCallResult(
                        success=False,
                        error=f"Method not found: {method}",
                        error_type="invalid_method"
                    )
                
                # 执行调用
                if asyncio.iscoroutinefunction(call_method):
                    result = await call_method(request, **kwargs)
                else:
                    result = call_method(request, **kwargs)
                
                return ServiceCallResult(
                    success=True,
                    data=result,
                    retries=retries
                )
                
            except Exception as e:
                last_error = str(e)
                last_error_type = self._classify_error(e)
                
                # 检查是否可重试
                if not self._is_retryable(last_error_type):
                    self._logger.warning(
                        f"Non-retryable error for {service_type}: {last_error}"
                    )
                    break
                
                # 最后一次尝试不重试
                if attempt >= max_retries:
                    break
                
                # 计算延迟
                delay = min(
                    initial_delay * (exponential_base ** attempt),
                    max_delay
                )
                
                self._logger.info(
                    f"Retrying {service_type} in {delay:.1f}s "
                    f"(attempt {attempt + 1}/{max_retries})"
                )
                
                await asyncio.sleep(delay)
                retries += 1
        
        return ServiceCallResult(
            success=False,
            error=last_error,
            error_type=last_error_type,
            retries=retries
        )
    
    async def _call_streaming(
        self,
        service_type: str,
        client: Any,
        request: Any,
        method: str,
        **kwargs
    ) -> ServiceCallResult:
        """
        流式服务调用
        
        流式请求特殊处理：
        - 连接阶段失败可重试
        - 数据传输阶段失败不重试
        - 熔断器仅统计连接失败
        
        Args:
            service_type: 服务类型
            client: 服务客户端
            request: 请求数据
            method: 调用方法名
            
        Returns:
            ServiceCallResult（包含生成器）
        """
        retry_config = self._retry_configs.get(service_type, DEFAULT_RETRY_CONFIG)
        max_retries = retry_config["max_retries"]
        initial_delay = retry_config["initial_delay"]
        
        last_error = None
        last_error_type = None
        
        # 连接阶段重试
        for attempt in range(max_retries + 1):
            try:
                call_method = getattr(client, method, None)
                if not call_method:
                    return ServiceCallResult(
                        success=False,
                        error=f"Method not found: {method}",
                        error_type="invalid_method"
                    )
                
                # 获取流式生成器
                if asyncio.iscoroutinefunction(call_method):
                    generator = await call_method(request, **kwargs)
                else:
                    generator = call_method(request, **kwargs)
                
                # 包装生成器以跟踪状态
                wrapped_generator = self._wrap_streaming_generator(
                    generator, service_type
                )
                
                return ServiceCallResult(
                    success=True,
                    data=wrapped_generator,
                    metadata={"is_streaming": True}
                )
                
            except Exception as e:
                last_error = str(e)
                last_error_type = self._classify_error(e)
                
                # 连接阶段错误可重试
                if not self._is_retryable(last_error_type):
                    break
                
                if attempt >= max_retries:
                    break
                
                delay = initial_delay * (2 ** attempt)
                self._logger.info(
                    f"Retrying streaming connection for {service_type} "
                    f"in {delay:.1f}s"
                )
                await asyncio.sleep(delay)
        
        return ServiceCallResult(
            success=False,
            error=last_error,
            error_type=last_error_type
        )
    
    def _wrap_streaming_generator(
        self,
        generator: Generator,
        service_type: str
    ) -> Generator:
        """
        包装流式生成器以跟踪状态
        
        Args:
            generator: 原始生成器
            service_type: 服务类型
            
        Yields:
            生成器内容
        """
        received_tokens = 0
        is_partial = False
        
        try:
            for chunk in generator:
                received_tokens += 1
                yield chunk
        except Exception as e:
            is_partial = True
            self._logger.warning(
                f"Streaming interrupted for {service_type}: {e}, "
                f"received {received_tokens} chunks"
            )
            # 传输中断不触发熔断器
        finally:
            # 记录流式调用完成
            self._logger.debug(
                f"Streaming completed for {service_type}: "
                f"partial={is_partial}, tokens={received_tokens}"
            )

    
    # ============================================================
    # 错误分类和处理
    # ============================================================
    
    def _classify_error(self, error: Exception) -> str:
        """
        分类错误类型
        
        Args:
            error: 异常对象
            
        Returns:
            错误类型字符串
        """
        error_str = str(error).lower()
        error_type = type(error).__name__.lower()
        
        # 超时错误
        if "timeout" in error_str or "timed out" in error_str:
            return "timeout"
        
        # 连接错误
        if "connection" in error_str or "connect" in error_type:
            return "connection_error"
        
        # HTTP 状态码错误
        if "401" in error_str or "403" in error_str or "unauthorized" in error_str:
            return "auth_failed"
        
        if "400" in error_str or "bad request" in error_str:
            return "invalid_request"
        
        if "404" in error_str or "not found" in error_str:
            return "not_found"
        
        if "429" in error_str or "rate limit" in error_str or "too many" in error_str:
            return "rate_limit"
        
        if "5" in error_str[:3] or "server error" in error_str:
            return "server_error"
        
        # Token 超限
        if "context" in error_str and ("overflow" in error_str or "length" in error_str):
            return "context_overflow"
        
        if "token" in error_str and ("limit" in error_str or "exceed" in error_str):
            return "context_overflow"
        
        return "unknown"
    
    def _is_retryable(self, error_type: str) -> bool:
        """
        检查错误是否可重试
        
        Args:
            error_type: 错误类型
            
        Returns:
            是否可重试
        """
        return error_type in RETRYABLE_ERRORS
    
    def _is_circuit_break_error(self, error_type: Optional[str]) -> bool:
        """
        检查错误是否应触发熔断器
        
        Args:
            error_type: 错误类型
            
        Returns:
            是否应触发熔断
        """
        if not error_type:
            return False
        
        # 只有服务端错误和连接错误触发熔断
        return error_type in ("timeout", "connection_error", "server_error")
    
    def _create_degraded_response(
        self,
        service_type: str,
        reason: str
    ) -> ServiceCallResult:
        """
        创建降级响应
        
        Args:
            service_type: 服务类型
            reason: 降级原因
            
        Returns:
            降级的 ServiceCallResult
        """
        return ServiceCallResult(
            success=False,
            error=reason,
            error_type="circuit_break",
            is_degraded=True,
            metadata={
                "service_type": service_type,
                "degraded_reason": reason,
                "suggestion": "Please try again later or use an alternative service."
            }
        )
    
    # ============================================================
    # 熔断器管理
    # ============================================================
    
    def reset_circuit_breaker(self, service_type: str) -> None:
        """
        重置熔断器
        
        Args:
            service_type: 服务类型
        """
        if service_type in self._circuit_breakers:
            self._circuit_breakers[service_type] = CircuitBreaker()
            self._logger.info(f"Circuit breaker reset for {service_type}")
    
    def force_open_circuit(self, service_type: str) -> None:
        """
        强制打开熔断器
        
        Args:
            service_type: 服务类型
        """
        if service_type in self._circuit_breakers:
            breaker = self._circuit_breakers[service_type]
            breaker.state = CircuitState.OPEN
            breaker.last_failure_time = time.time()
            self._logger.warning(f"Circuit breaker forced open for {service_type}")
    
    def get_circuit_breaker_state(self, service_type: str) -> Optional[CircuitState]:
        """
        获取熔断器状态
        
        Args:
            service_type: 服务类型
            
        Returns:
            熔断器状态
        """
        breaker = self._circuit_breakers.get(service_type)
        return breaker.state if breaker else None
    
    # ============================================================
    # 同步调用支持
    # ============================================================
    
    def call_service_sync(
        self,
        service_type: str,
        request: Any,
        method: str = "call",
        **kwargs
    ) -> ServiceCallResult:
        """
        同步服务调用（用于非异步环境）
        
        Args:
            service_type: 服务类型
            request: 请求数据
            method: 调用方法名
            
        Returns:
            ServiceCallResult
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(
            self.call_service(service_type, request, method, **kwargs)
        )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 管理器
    "ExternalServiceManager",
    # 数据类
    "ServiceCallResult",
    "StreamingResult",
    "CallStatistics",
    "CircuitBreaker",
    # 枚举
    "CircuitState",
    "ServiceStatus",
    # 服务类型常量
    "SERVICE_LLM_ZHIPU",
    "SERVICE_LLM_GEMINI",
    "SERVICE_LLM_OPENAI",
    "SERVICE_LLM_CLAUDE",
    "SERVICE_LLM_QWEN",
    "SERVICE_LLM_DEEPSEEK",
    "SERVICE_SEARCH_ZHIPU",
    "SERVICE_SEARCH_GOOGLE",
    "SERVICE_SEARCH_BING",
    "ALL_SERVICE_TYPES",
    # 配置常量
    "DEFAULT_RETRY_CONFIG",
    "DEFAULT_CIRCUIT_BREAKER_CONFIG",
    "DEFAULT_TIMEOUT_CONFIG",
    "RETRYABLE_ERRORS",
    "NON_RETRYABLE_ERRORS",
]
