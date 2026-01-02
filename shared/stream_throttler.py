# Circuit Design AI - Stream Throttler
"""
流式数据节流聚合器

职责：
- 对高频流式数据进行节流聚合，减少 UI 更新频率
- 在保证实时性的同时避免 UI 卡顿
- 支持多任务并行的流式数据处理

设计背景：
- LLM 流式输出可能每秒产生数十个 chunk
- 直接更新 UI 会导致卡顿和性能问题
- 需要在保证实时性的同时减少更新频率

节流逻辑：
1. 数据推送到缓冲区
2. 如果没有待执行的刷新任务，创建延迟刷新任务
3. 延迟时间到达后，聚合缓冲区数据并发送 data_ready 信号
4. 清空缓冲区，等待下一批数据

使用方式：
    throttler = StreamThrottler(interval_ms=50)
    throttler.data_ready.connect(on_data_ready)
    
    # 在异步上下文中
    await throttler.push("task_1", "Hello ")
    await throttler.push("task_1", "World!")
    
    # 任务结束时
    await throttler.flush_all("task_1")
"""

import asyncio
from enum import Enum, auto
from typing import Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal


class StreamState(Enum):
    """
    流式状态枚举
    
    用于追踪每个任务的流式处理状态
    """
    IDLE = auto()       # 空闲，未开始或已结束
    STREAMING = auto()  # 正在接收流式数据
    PAUSED = auto()     # 暂停（如工具执行期间）
    COMPLETE = auto()   # 完成


class StreamThrottler(QObject):
    """
    流式数据节流聚合器
    
    对高频流式数据进行节流聚合，减少 UI 更新频率。
    支持多任务并行处理，每个任务有独立的缓冲区。
    
    Signals:
        data_ready(str, str): 聚合数据就绪
            - task_id: 任务标识
            - aggregated_content: 聚合后的内容
        state_changed(str, StreamState): 任务状态变更
            - task_id: 任务标识
            - state: 新状态
    
    Example:
        throttler = StreamThrottler(interval_ms=50)
        throttler.data_ready.connect(lambda tid, content: print(f"[{tid}] {content}"))
        
        async def stream_data():
            for chunk in chunks:
                await throttler.push("task_1", chunk)
            await throttler.flush_all("task_1")
    """
    
    # 信号定义
    data_ready = pyqtSignal(str, str)  # (task_id, aggregated_content)
    state_changed = pyqtSignal(str, object)  # (task_id, StreamState)
    
    # 默认节流间隔（毫秒）
    DEFAULT_INTERVAL_MS = 50
    
    def __init__(self, interval_ms: int = DEFAULT_INTERVAL_MS, parent: Optional[QObject] = None):
        """
        初始化节流器
        
        Args:
            interval_ms: 节流间隔（毫秒），默认 50ms
            parent: Qt 父对象
        """
        super().__init__(parent)
        
        self._interval_ms = interval_ms
        self._interval_sec = interval_ms / 1000.0
        
        # 每个任务的数据缓冲区
        self._buffers: Dict[str, List[str]] = {}
        
        # 每个任务的延迟刷新任务
        self._flush_tasks: Dict[str, asyncio.Task] = {}
        
        # 每个任务的状态
        self._states: Dict[str, StreamState] = {}
        
        # 锁，保护并发访问
        self._lock = asyncio.Lock()
        
        # 延迟获取的服务
        self._stop_controller = None
        self._logger = None
    
    @property
    def interval_ms(self) -> int:
        """获取节流间隔（毫秒）"""
        return self._interval_ms
    
    @interval_ms.setter
    def interval_ms(self, value: int) -> None:
        """设置节流间隔（毫秒）"""
        self._interval_ms = max(1, value)  # 最小 1ms
        self._interval_sec = self._interval_ms / 1000.0
    
    def get_state(self, task_id: str) -> StreamState:
        """
        获取任务的流式状态
        
        Args:
            task_id: 任务标识
            
        Returns:
            StreamState: 任务状态，未知任务返回 IDLE
        """
        return self._states.get(task_id, StreamState.IDLE)
    
    def _set_state(self, task_id: str, state: StreamState) -> None:
        """
        设置任务状态并发送信号
        
        Args:
            task_id: 任务标识
            state: 新状态
        """
        old_state = self._states.get(task_id, StreamState.IDLE)
        if old_state != state:
            self._states[task_id] = state
            self.state_changed.emit(task_id, state)
    
    async def push(self, task_id: str, chunk: str) -> None:
        """
        推送数据块到缓冲区
        
        数据会被缓冲，在节流间隔后聚合发送。
        
        Args:
            task_id: 任务标识
            chunk: 数据块内容
        """
        if not chunk:
            return
        
        # 停止检查点：在推送数据前检查是否请求停止
        if await self._check_stop_requested(task_id):
            if self._logger:
                self._logger.debug(f"Stop requested, skipping push for task '{task_id}'")
            return
        
        async with self._lock:
            # 确保缓冲区存在
            if task_id not in self._buffers:
                self._buffers[task_id] = []
            
            # 添加数据到缓冲区
            self._buffers[task_id].append(chunk)
            
            # 更新状态为 STREAMING
            self._set_state(task_id, StreamState.STREAMING)
            
            # 如果没有待执行的刷新任务，创建一个
            if task_id not in self._flush_tasks or self._flush_tasks[task_id].done():
                self._flush_tasks[task_id] = asyncio.create_task(
                    self._delayed_flush(task_id)
                )
    
    async def _delayed_flush(self, task_id: str) -> None:
        """
        延迟刷新任务
        
        等待节流间隔后刷新缓冲区。
        
        Args:
            task_id: 任务标识
        """
        try:
            await asyncio.sleep(self._interval_sec)
            await self._do_flush(task_id)
        except asyncio.CancelledError:
            # 任务被取消，不做处理
            pass
    
    async def _do_flush(self, task_id: str) -> None:
        """
        执行实际的刷新操作
        
        聚合缓冲区数据并发送信号。
        
        Args:
            task_id: 任务标识
        """
        async with self._lock:
            buffer = self._buffers.get(task_id)
            if not buffer:
                return
            
            # 聚合数据
            aggregated = ''.join(buffer)
            
            # 清空缓冲区
            buffer.clear()
        
        # 在锁外发送信号，避免死锁
        if aggregated:
            self.data_ready.emit(task_id, aggregated)
    
    async def flush(self, task_id: str) -> None:
        """
        立即刷新指定任务的缓冲区
        
        取消待执行的延迟刷新任务，立即发送缓冲区数据。
        
        Args:
            task_id: 任务标识
        """
        # 取消待执行的延迟刷新任务
        if task_id in self._flush_tasks:
            task = self._flush_tasks[task_id]
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # 立即刷新
        await self._do_flush(task_id)
    
    async def flush_all(self, task_id: str) -> None:
        """
        强制刷新并清理任务
        
        任务结束时调用，确保所有数据发送完毕并清理资源。
        
        Args:
            task_id: 任务标识
        """
        # 先刷新缓冲区
        await self.flush(task_id)
        
        async with self._lock:
            # 清理资源
            self._buffers.pop(task_id, None)
            self._flush_tasks.pop(task_id, None)
            
            # 更新状态为 COMPLETE
            self._set_state(task_id, StreamState.COMPLETE)
    
    def clear(self, task_id: str) -> None:
        """
        清除指定任务的缓冲区（同步方法）
        
        取消时调用，丢弃未发送的数据。
        
        Args:
            task_id: 任务标识
        """
        # 取消待执行的延迟刷新任务
        if task_id in self._flush_tasks:
            task = self._flush_tasks[task_id]
            if not task.done():
                task.cancel()
        
        # 清理资源
        self._buffers.pop(task_id, None)
        self._flush_tasks.pop(task_id, None)
        
        # 更新状态为 IDLE
        self._set_state(task_id, StreamState.IDLE)
    
    def pause(self, task_id: str) -> None:
        """
        暂停任务的流式处理
        
        工具执行期间可调用此方法暂停流式更新。
        
        Args:
            task_id: 任务标识
        """
        if self.get_state(task_id) == StreamState.STREAMING:
            self._set_state(task_id, StreamState.PAUSED)
    
    def resume(self, task_id: str) -> None:
        """
        恢复任务的流式处理
        
        工具执行完成后调用此方法恢复流式更新。
        
        Args:
            task_id: 任务标识
        """
        if self.get_state(task_id) == StreamState.PAUSED:
            self._set_state(task_id, StreamState.STREAMING)
    
    def clear_all(self) -> None:
        """
        清除所有任务的缓冲区
        
        应用关闭或重置时调用。
        """
        # 取消所有待执行的刷新任务
        for task in self._flush_tasks.values():
            if not task.done():
                task.cancel()
        
        # 清理所有资源
        self._buffers.clear()
        self._flush_tasks.clear()
        
        # 更新所有任务状态为 IDLE
        for task_id in list(self._states.keys()):
            self._set_state(task_id, StreamState.IDLE)
        self._states.clear()
    
    def get_buffer_size(self, task_id: str) -> int:
        """
        获取指定任务的缓冲区大小
        
        用于调试和监控。
        
        Args:
            task_id: 任务标识
            
        Returns:
            int: 缓冲区中的数据块数量
        """
        buffer = self._buffers.get(task_id)
        return len(buffer) if buffer else 0
    
    def get_active_tasks(self) -> List[str]:
        """
        获取所有活跃任务的 ID 列表
        
        Returns:
            List[str]: 活跃任务 ID 列表
        """
        return [
            task_id for task_id, state in self._states.items()
            if state in (StreamState.STREAMING, StreamState.PAUSED)
        ]
    
    # ============================================================
    # 停止控制集成
    # ============================================================
    
    @property
    def stop_controller(self):
        """延迟获取 StopController"""
        if self._stop_controller is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_STOP_CONTROLLER
                self._stop_controller = ServiceLocator.get_optional(SVC_STOP_CONTROLLER)
            except Exception:
                pass
        return self._stop_controller
    
    @property
    def logger(self):
        """延迟获取 Logger"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("stream_throttler")
            except Exception:
                pass
        return self._logger
    
    async def _check_stop_requested(self, task_id: str) -> bool:
        """
        检查是否请求停止
        
        Args:
            task_id: 任务标识
            
        Returns:
            bool: True 表示已请求停止
        """
        if self.stop_controller:
            return self.stop_controller.is_stop_requested()
        return False


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "StreamThrottler",
    "StreamState",
]
