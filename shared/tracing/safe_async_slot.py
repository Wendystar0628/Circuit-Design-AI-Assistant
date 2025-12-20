# Safe Async Slot - Exception Capture Decorator for qasync
"""
qasync 异常捕获装饰器

职责：
- 增强 qasync 的异常捕获能力
- 确保异步槽函数的异常被正确处理和记录
- 与追踪系统集成，记录错误 Span

设计说明：
- qasync 的 @asyncSlot() 在协程抛出异常时会静默失败
- @safe_async_slot 装饰器捕获异常并记录到追踪系统
- 两者配合使用，顺序为：@asyncSlot() 在外，@safe_async_slot() 在内

使用示例：
    from qasync import asyncSlot
    from shared.tracing import safe_async_slot
    
    class ConversationPanel(QWidget):
        @asyncSlot()
        @safe_async_slot()
        async def on_send_clicked(self):
            message = self.input_area.get_text()
            await self._send_message(message)
"""

import asyncio
import functools
import traceback
from typing import Any, Callable, TypeVar, Union

F = TypeVar('F', bound=Callable[..., Any])


def safe_async_slot(*args, reraise: bool = None) -> Union[F, Callable[[F], F]]:
    """
    与 @asyncSlot 配合使用的异常捕获装饰器
    
    捕获异步槽函数中的异常，记录到追踪系统和日志，
    并发布错误事件通知 UI 组件。
    
    Args:
        reraise: 是否重新抛出异常。
                 None = 使用配置 debug.reraise_async_errors（默认 False）
                 True = 总是重新抛出
                 False = 总是吞掉异常
    
    Usage:
        # 方式1：无参数
        @asyncSlot()
        @safe_async_slot
        async def on_click(self):
            ...
        
        # 方式2：带括号
        @asyncSlot()
        @safe_async_slot()
        async def on_click(self):
            ...
        
        # 方式3：指定参数
        @asyncSlot()
        @safe_async_slot(reraise=True)
        async def on_click(self):
            ...
    """
    
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            func_name = func.__name__
            
            try:
                return await func(*args, **kwargs)
                
            except asyncio.CancelledError:
                # 任务取消不视为错误，仅记录 debug 日志
                _log_debug(f"Async slot '{func_name}' was cancelled")
                raise
                
            except Exception as e:
                # 记录到追踪系统
                _record_error_to_tracing(func_name, e)
                
                # 记录到日志
                _log_exception(func_name, e)
                
                # 发布错误事件
                _publish_error_event(func_name, e)
                
                # 决定是否重新抛出
                should_reraise = _should_reraise(reraise)
                if should_reraise:
                    raise
        
        return wrapper  # type: ignore
    
    # 支持 @safe_async_slot 和 @safe_async_slot() 两种用法
    if len(args) == 1 and callable(args[0]):
        # @safe_async_slot 无括号调用
        return decorator(args[0])
    
    # @safe_async_slot() 或 @safe_async_slot(reraise=True)
    return decorator


def _record_error_to_tracing(func_name: str, error: Exception) -> None:
    """记录错误到追踪系统"""
    try:
        from shared.tracing.tracing_context import TracingContext
        TracingContext.record_error(f"async_slot.{func_name}", error)
    except Exception:
        # 追踪系统不应影响业务逻辑
        pass


def _log_debug(message: str) -> None:
    """记录 debug 日志"""
    try:
        from infrastructure.utils.logger import get_logger
        logger = get_logger("safe_async_slot")
        logger.debug(message)
    except Exception:
        pass


def _log_exception(func_name: str, error: Exception) -> None:
    """记录异常日志"""
    try:
        from infrastructure.utils.logger import get_logger
        logger = get_logger("safe_async_slot")
        logger.exception(f"Error in async slot '{func_name}': {error}")
    except Exception:
        # 回退到 print
        print(f"[safe_async_slot ERROR] {func_name}: {error}")
        traceback.print_exc()


def _publish_error_event(func_name: str, error: Exception) -> None:
    """发布错误事件"""
    try:
        from shared.service_locator import ServiceLocator
        from shared.service_names import SVC_EVENT_BUS
        from shared.event_types import EVENT_ASYNC_SLOT_ERROR
        
        event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
        if event_bus:
            event_bus.publish(
                EVENT_ASYNC_SLOT_ERROR,
                {
                    "function": func_name,
                    "error": str(error),
                    "error_type": type(error).__name__,
                    "traceback": traceback.format_exc(),
                },
                source="safe_async_slot",
            )
    except Exception:
        # 事件发布失败不应影响业务逻辑
        pass


def _should_reraise(reraise_param: bool = None) -> bool:
    """
    决定是否重新抛出异常
    
    优先级：
    1. 装饰器参数 reraise
    2. 配置 debug.reraise_async_errors
    3. 默认 False
    """
    if reraise_param is not None:
        return reraise_param
    
    try:
        from shared.service_locator import ServiceLocator
        from shared.service_names import SVC_CONFIG_MANAGER
        
        config_manager = ServiceLocator.get_optional(SVC_CONFIG_MANAGER)
        if config_manager:
            return config_manager.get("debug.reraise_async_errors", False)
    except Exception:
        pass
    
    return False


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "safe_async_slot",
]
