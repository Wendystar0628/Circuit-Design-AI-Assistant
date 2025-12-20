# Tracing Logger - Memory Buffer + Async Flush
"""
追踪日志记录器

职责：
- 接收 Span 记录，缓冲后批量写入存储
- 内存缓冲 + 定时刷新，确保追踪写入不阻塞业务逻辑
- 发布事件通知 UI 更新

设计说明：
- 采用内存缓冲 + 定时刷新 + aiosqlite 方案
- 不使用独立 QThread，复用 qasync 融合事件循环
- record_span() 是同步方法，微秒级耗时
- _flush_buffer() 是异步方法，通过 asyncio.create_task 调度

初始化顺序：
- Phase 3 延迟初始化，依赖 EventBus、TracingStore
- 在 TracingStore 初始化后调用 start() 启动定时刷新
"""

import asyncio
import threading
from typing import List, Optional, TYPE_CHECKING

from PyQt6.QtCore import QTimer

from shared.tracing.tracing_types import SpanRecord

if TYPE_CHECKING:
    from shared.tracing.tracing_store import TracingStore
    from shared.event_bus import EventBus


# 默认配置
DEFAULT_FLUSH_INTERVAL_MS = 500
DEFAULT_MAX_BUFFER_SIZE = 100


class TracingLogger:
    """
    追踪日志记录器
    
    内存缓冲 + 定时刷新，确保追踪写入不阻塞业务逻辑。
    
    使用方式：
        # 初始化（Phase 3）
        logger = TracingLogger()
        logger.set_store(tracing_store)
        logger.start()
        
        # 记录 Span（由 TracingContext 自动调用）
        logger.record_span(span_record)
        
        # 关闭（应用退出时）
        await logger.shutdown()
    """
    
    def __init__(
        self,
        flush_interval_ms: int = DEFAULT_FLUSH_INTERVAL_MS,
        max_buffer_size: int = DEFAULT_MAX_BUFFER_SIZE,
    ):
        """
        初始化追踪日志记录器
        
        Args:
            flush_interval_ms: 刷新间隔（毫秒）
            max_buffer_size: 缓冲区上限
        """
        # 配置
        self._flush_interval_ms = flush_interval_ms
        self._max_buffer_size = max_buffer_size
        self._enabled = True
        
        # 内存缓冲区
        self._buffer: List[SpanRecord] = []
        self._buffer_lock = threading.Lock()
        
        # 定时器
        self._flush_timer: Optional[QTimer] = None
        self._is_running = False
        
        # 依赖（延迟注入）
        self._store: Optional['TracingStore'] = None
        self._event_bus: Optional['EventBus'] = None
        
        # 日志器（延迟获取）
        self._logger = None
        
        # 统计信息
        self._stats = {
            "total_recorded": 0,
            "total_flushed": 0,
            "flush_count": 0,
            "dropped_count": 0,
        }
    
    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("tracing_logger")
            except Exception:
                pass
        return self._logger
    
    # --------------------------------------------------------
    # 依赖注入
    # --------------------------------------------------------
    
    def set_store(self, store: 'TracingStore') -> None:
        """设置追踪存储"""
        self._store = store
    
    def set_event_bus(self, event_bus: 'EventBus') -> None:
        """设置事件总线"""
        self._event_bus = event_bus
    
    def set_enabled(self, enabled: bool) -> None:
        """设置是否启用追踪"""
        self._enabled = enabled
    
    # --------------------------------------------------------
    # 生命周期管理
    # --------------------------------------------------------
    
    def start(self) -> None:
        """
        启动定时刷新
        
        在 TracingStore 初始化后调用。
        """
        if self._is_running:
            return
        
        # 注册到 TracingContext
        from shared.tracing.tracing_context import TracingContext
        TracingContext.set_span_finished_callback(self.record_span)
        
        # 启动定时器
        self._flush_timer = QTimer()
        self._flush_timer.timeout.connect(self._on_flush_timer)
        self._flush_timer.start(self._flush_interval_ms)
        
        self._is_running = True
        
        if self.logger:
            self.logger.debug(
                f"TracingLogger started: interval={self._flush_interval_ms}ms, "
                f"max_buffer={self._max_buffer_size}"
            )
    
    def stop(self) -> None:
        """停止定时刷新（不清空缓冲区）"""
        if self._flush_timer:
            self._flush_timer.stop()
            self._flush_timer = None
        self._is_running = False
    
    async def shutdown(self) -> None:
        """
        优雅关闭
        
        停止定时器，执行最后一次刷新。
        """
        self.stop()
        
        # 最后一次刷新
        await self._flush_buffer()
        
        if self.logger:
            self.logger.info(
                f"TracingLogger shutdown: "
                f"recorded={self._stats['total_recorded']}, "
                f"flushed={self._stats['total_flushed']}, "
                f"dropped={self._stats['dropped_count']}"
            )
    
    # --------------------------------------------------------
    # 核心功能
    # --------------------------------------------------------
    
    def record_span(self, span: SpanRecord) -> None:
        """
        记录 Span
        
        同步方法，微秒级耗时，仅追加到缓冲区。
        由 TracingContext 在 Span 结束时自动调用。
        
        Args:
            span: Span 记录
        """
        if not self._enabled:
            return
        
        with self._buffer_lock:
            self._buffer.append(span)
            self._stats["total_recorded"] += 1
            buffer_size = len(self._buffer)
        
        # 缓冲区满时立即触发异步刷新
        if buffer_size >= self._max_buffer_size:
            self._schedule_flush()
    
    def _on_flush_timer(self) -> None:
        """定时器回调（主线程）"""
        self._schedule_flush()
    
    def _schedule_flush(self) -> None:
        """调度异步刷新"""
        try:
            # 获取事件循环
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._flush_buffer())
            else:
                # 事件循环未运行，同步执行（启动阶段）
                loop.run_until_complete(self._flush_buffer())
        except RuntimeError:
            # 没有事件循环，跳过刷新
            pass
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to schedule flush: {e}")
    
    async def _flush_buffer(self) -> None:
        """
        异步批量写入 SQLite
        
        从缓冲区取出所有记录，批量写入存储。
        """
        # 取出缓冲区内容
        with self._buffer_lock:
            if not self._buffer:
                return
            batch = self._buffer.copy()
            self._buffer.clear()
        
        batch_size = len(batch)
        
        # 写入存储
        if self._store is not None:
            try:
                await self._store.insert_spans(batch)
                self._stats["total_flushed"] += batch_size
                self._stats["flush_count"] += 1
            except Exception as e:
                # 写入失败，记录错误但不影响业务
                self._stats["dropped_count"] += batch_size
                if self.logger:
                    self.logger.warning(f"Failed to flush spans: {e}")
                return
        else:
            # 无存储，丢弃数据
            self._stats["dropped_count"] += batch_size
            return
        
        # 发布事件通知 UI 更新
        self._publish_flush_event(batch_size)
    
    def _publish_flush_event(self, count: int) -> None:
        """发布刷新完成事件"""
        if self._event_bus is None:
            return
        
        try:
            from shared.tracing.tracing_events import TracingEvents
            self._event_bus.publish(
                TracingEvents.SPANS_FLUSHED,
                {"count": count}
            )
        except Exception:
            # 事件发布失败不影响追踪功能
            pass
    
    # --------------------------------------------------------
    # 统计和诊断
    # --------------------------------------------------------
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        with self._buffer_lock:
            buffer_size = len(self._buffer)
        
        return {
            **self._stats,
            "buffer_size": buffer_size,
            "is_running": self._is_running,
            "enabled": self._enabled,
        }
    
    def get_buffer_size(self) -> int:
        """获取当前缓冲区大小"""
        with self._buffer_lock:
            return len(self._buffer)
    
    async def force_flush(self) -> int:
        """
        强制刷新缓冲区
        
        Returns:
            int: 刷新的记录数
        """
        with self._buffer_lock:
            count = len(self._buffer)
        
        if count > 0:
            await self._flush_buffer()
        
        return count


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "TracingLogger",
]
