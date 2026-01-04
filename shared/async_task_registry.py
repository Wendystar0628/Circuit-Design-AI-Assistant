# Async Task Registry - Asynchronous Task Lifecycle Management
"""
异步任务注册表 - 异步任务生命周期管理

职责：
- 管理异步任务的注册、状态追踪、取消
- 作为任务生命周期的中央协调器
- 所有 I/O 密集型任务在主线程的 asyncio 协程中执行

设计原则：
- 所有 I/O 密集型任务（LLM 调用、网络请求、文件读写）在主线程的 asyncio 协程中执行
- 不创建或管理 QThread，避免双循环同步问题
- 通过 asyncio.Task 管理任务生命周期

初始化顺序：
- Phase 3.1（延迟初始化），依赖 EventBus，在事件循环中异步执行

调度策略：
- 同类任务互斥：同一 task_type 同时只能有一个任务运行，新任务排队等待
- 异类任务并行：不同 task_type 的任务可同时运行
- 任务优先级：用户触发的任务优先于自动触发的任务

使用示例：
    from shared.async_task_registry import AsyncTaskRegistry
    
    registry = AsyncTaskRegistry()
    
    async def my_task():
        # 执行异步操作
        result = await some_async_operation()
        return result
    
    # 提交任务
    await registry.submit(TASK_LLM, "task_1", my_task())
    
    # 取消任务
    registry.cancel("task_1")
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable, Coroutine, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal


# ============================================================
# 任务类型常量
# ============================================================

TASK_LLM = "llm"                    # LLM 生成任务
TASK_RAG_INDEX = "rag_index"        # RAG 索引任务
TASK_RAG_SEARCH = "rag_search"      # RAG 检索任务
TASK_FILE_WATCH = "file_watch"      # 文件监听任务
TASK_SIMULATION = "simulation"      # 仿真任务（子进程）
TASK_SCHEMATIC = "schematic"        # 原理图生成任务
TASK_CODE_INDEX = "code_index"      # 代码索引任务


# ============================================================
# 枚举和数据类
# ============================================================

class TaskState(Enum):
    """任务状态枚举"""
    PENDING = auto()    # 等待执行
    RUNNING = auto()    # 执行中
    COMPLETED = auto()  # 已完成
    CANCELLED = auto()  # 已取消
    FAILED = auto()     # 执行失败


class TaskPriority(Enum):
    """任务优先级"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


@dataclass
class TaskInfo:
    """任务信息数据类"""
    task_id: str                        # 任务唯一标识
    task_type: str                      # 任务类型
    task: asyncio.Task                  # asyncio 任务对象
    state: TaskState                    # 当前状态
    created_at: datetime                # 创建时间
    started_at: Optional[datetime] = None  # 开始时间
    completed_at: Optional[datetime] = None  # 完成时间
    result: Any = None                  # 执行结果（完成时）
    error: Optional[Exception] = None   # 错误信息（失败时）
    priority: TaskPriority = TaskPriority.NORMAL  # 任务优先级
    
    @property
    def duration_ms(self) -> float:
        """计算任务执行时长（毫秒）"""
        if self.started_at and self.completed_at:
            delta = self.completed_at - self.started_at
            return delta.total_seconds() * 1000
        return 0.0


@dataclass
class PendingTask:
    """待执行任务"""
    task_id: str
    task_type: str
    coro: Coroutine
    priority: TaskPriority = TaskPriority.NORMAL
    created_at: datetime = field(default_factory=datetime.now)


# ============================================================
# AsyncTaskRegistry 类
# ============================================================

class AsyncTaskRegistry(QObject):
    """
    异步任务注册表
    
    管理异步任务的注册、状态追踪、取消，作为任务生命周期的中央协调器。
    
    Signals:
        task_started(str, str): 任务开始 (task_id, task_type)
        task_completed(str, str, object): 任务完成 (task_id, task_type, result)
        task_failed(str, str, str): 任务失败 (task_id, task_type, error_msg)
        task_cancelled(str, str): 任务取消 (task_id, task_type)
        task_progress(str, str, int, str): 任务进度 (task_id, task_type, percent, message)
    """
    
    # 信号定义
    task_started = pyqtSignal(str, str)  # (task_id, task_type)
    task_completed = pyqtSignal(str, str, object)  # (task_id, task_type, result)
    task_failed = pyqtSignal(str, str, str)  # (task_id, task_type, error_msg)
    task_cancelled = pyqtSignal(str, str)  # (task_id, task_type)
    task_progress = pyqtSignal(str, str, int, str)  # (task_id, task_type, percent, message)
    
    def __init__(self, parent: Optional[QObject] = None):
        """初始化任务注册表"""
        super().__init__(parent)
        
        # 运行中的任务
        self._tasks: Dict[str, TaskInfo] = {}
        
        # 待执行任务队列（按任务类型分组）
        self._pending_queues: Dict[str, deque] = {}
        
        # 任务类型的互斥锁（同类任务互斥）
        self._type_locks: Dict[str, bool] = {}
        
        # 延迟获取的服务
        self._event_bus = None
        self._logger = None
        self._stop_controller = None
        
        # 订阅停止事件
        self._subscribe_stop_events()
    
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
                self._logger = get_logger("async_task_registry")
            except Exception:
                pass
        return self._logger
    
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
    
    def _subscribe_stop_events(self) -> None:
        """订阅停止事件"""
        # 延迟订阅，避免初始化顺序问题
        try:
            if self.event_bus:
                self.event_bus.subscribe("EVENT_STOP_REQUESTED", self._on_stop_requested)
        except Exception:
            pass
    
    def _on_stop_requested(self, event_data: Dict[str, Any]) -> None:
        """
        处理停止请求事件
        
        取消所有运行中的任务，并通知 StopController 开始清理。
        
        Args:
            event_data: 事件数据，包含 task_id 和 reason
        """
        # 取消所有运行中的任务
        cancelled_count = self.cancel_all()
        
        # 通知 StopController 开始清理（仅在有任务被取消时）
        # mark_stopping() 会检查状态，非 STOP_REQUESTED 状态下会静默返回
        if self.stop_controller and cancelled_count > 0:
            self.stop_controller.mark_stopping()
        
        if self.logger:
            self.logger.info(
                f"Stop requested, cancelled {cancelled_count} tasks, "
                f"reason={event_data.get('reason', 'unknown')}"
            )
    
    # ============================================================
    # 任务提交
    # ============================================================
    
    async def submit(
        self,
        task_type: str,
        task_id: str,
        coro: Coroutine,
        priority: TaskPriority = TaskPriority.NORMAL
    ) -> bool:
        """
        提交异步任务
        
        Args:
            task_type: 任务类型（如 TASK_LLM）
            task_id: 任务唯一标识
            coro: 协程对象
            priority: 任务优先级
            
        Returns:
            bool: 是否成功提交
        """
        # 检查任务 ID 是否已存在
        if task_id in self._tasks:
            if self.logger:
                self.logger.warning(f"Task '{task_id}' already exists")
            return False
        
        # 创建待执行任务
        pending_task = PendingTask(
            task_id=task_id,
            task_type=task_type,
            coro=coro,
            priority=priority
        )
        
        # 检查同类任务是否正在运行
        if self._is_type_locked(task_type):
            # 加入待执行队列
            self._enqueue_pending_task(task_type, pending_task)
            if self.logger:
                self.logger.info(
                    f"Task '{task_id}' ({task_type}) queued, "
                    f"queue size: {len(self._pending_queues.get(task_type, []))}"
                )
            return True
        
        # 立即执行任务
        await self._execute_task(pending_task)
        return True
    
    def _is_type_locked(self, task_type: str) -> bool:
        """检查任务类型是否被锁定（有同类任务正在运行）"""
        return self._type_locks.get(task_type, False)
    
    def _lock_type(self, task_type: str) -> None:
        """锁定任务类型"""
        self._type_locks[task_type] = True
    
    def _unlock_type(self, task_type: str) -> None:
        """解锁任务类型"""
        self._type_locks[task_type] = False
    
    def _enqueue_pending_task(self, task_type: str, pending_task: PendingTask) -> None:
        """将任务加入待执行队列（按优先级排序）"""
        if task_type not in self._pending_queues:
            self._pending_queues[task_type] = deque()
        
        queue = self._pending_queues[task_type]
        
        # 按优先级插入
        insert_pos = len(queue)
        for i, existing_task in enumerate(queue):
            if pending_task.priority.value > existing_task.priority.value:
                insert_pos = i
                break
        
        # deque 不支持 insert，转换为 list 操作
        queue_list = list(queue)
        queue_list.insert(insert_pos, pending_task)
        queue.clear()
        queue.extend(queue_list)
    
    async def _execute_task(self, pending_task: PendingTask) -> None:
        """执行任务"""
        task_id = pending_task.task_id
        task_type = pending_task.task_type
        
        # 锁定任务类型
        self._lock_type(task_type)
        
        # 创建 asyncio.Task
        async_task = asyncio.create_task(self._run_task_wrapper(pending_task))
        
        # 注册任务信息
        task_info = TaskInfo(
            task_id=task_id,
            task_type=task_type,
            task=async_task,
            state=TaskState.RUNNING,
            created_at=pending_task.created_at,
            started_at=datetime.now(),
            priority=pending_task.priority
        )
        self._tasks[task_id] = task_info
        
        # 发送任务开始信号
        self.task_started.emit(task_id, task_type)
        
        # 发布事件
        self._publish_event("EVENT_TASK_STARTED", task_id, task_type)
        
        if self.logger:
            self.logger.info(f"Task '{task_id}' ({task_type}) started")
    
    async def _run_task_wrapper(self, pending_task: PendingTask) -> Any:
        """任务执行包装器，处理完成/错误/取消"""
        task_id = pending_task.task_id
        task_type = pending_task.task_type
        
        try:
            # 执行协程
            result = await pending_task.coro
            
            # 更新任务状态
            if task_id in self._tasks:
                task_info = self._tasks[task_id]
                task_info.state = TaskState.COMPLETED
                task_info.completed_at = datetime.now()
                task_info.result = result
                
                # 发送完成信号
                self.task_completed.emit(task_id, task_type, result)
                
                # 发布事件
                self._publish_event("EVENT_TASK_COMPLETED", task_id, task_type, {"result": result})
                
                if self.logger:
                    self.logger.info(
                        f"Task '{task_id}' ({task_type}) completed in {task_info.duration_ms:.0f}ms"
                    )
            
            return result
            
        except asyncio.CancelledError:
            # 任务被取消 - 执行清理逻辑
            if self.logger:
                self.logger.info(f"Task '{task_id}' ({task_type}) received cancellation signal")
            
            # 执行清理逻辑
            partial_result = await self._cleanup_cancelled_task(task_id, task_type)
            
            # 更新任务状态
            if task_id in self._tasks:
                task_info = self._tasks[task_id]
                task_info.state = TaskState.CANCELLED
                task_info.completed_at = datetime.now()
                task_info.result = partial_result  # 保存部分结果
                
                # 发送取消信号
                self.task_cancelled.emit(task_id, task_type)
                
                # 发布事件（包含部分结果）
                event_data = {"partial_result": partial_result} if partial_result else {}
                self._publish_event("EVENT_TASK_CANCELLED", task_id, task_type, event_data)
                
                if self.logger:
                    has_partial = "with partial result" if partial_result else "without result"
                    self.logger.info(f"Task '{task_id}' ({task_type}) cancelled {has_partial}")
            
            raise
            
        except Exception as e:
            # 任务执行失败
            if task_id in self._tasks:
                task_info = self._tasks[task_id]
                task_info.state = TaskState.FAILED
                task_info.completed_at = datetime.now()
                task_info.error = e
                
                error_msg = str(e)
                
                # 发送失败信号
                self.task_failed.emit(task_id, task_type, error_msg)
                
                # 发布事件
                self._publish_event("EVENT_TASK_FAILED", task_id, task_type, {"error": error_msg})
                
                if self.logger:
                    self.logger.error(f"Task '{task_id}' ({task_type}) failed: {e}")
            
            raise
            
        finally:
            # 解锁任务类型
            self._unlock_type(task_type)
            
            # 执行队列中的下一个同类任务
            await self._execute_next_pending_task(task_type)
    
    async def _execute_next_pending_task(self, task_type: str) -> None:
        """执行队列中的下一个同类任务"""
        if task_type not in self._pending_queues:
            return
        
        queue = self._pending_queues[task_type]
        if not queue:
            return
        
        # 取出下一个任务
        next_task = queue.popleft()
        
        # 执行任务
        await self._execute_task(next_task)
    
    async def _cleanup_cancelled_task(self, task_id: str, task_type: str) -> Optional[Any]:
        """
        清理被取消的任务
        
        执行必要的清理逻辑，如刷新缓冲区、关闭连接等。
        
        Args:
            task_id: 任务标识
            task_type: 任务类型
            
        Returns:
            Any: 部分结果（如果有）
        """
        partial_result = None
        
        try:
            # 针对不同任务类型执行特定清理
            if task_type == TASK_LLM:
                # LLM 任务：刷新流式输出缓冲区
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_STREAM_THROTTLER
                
                throttler = ServiceLocator.get_optional(SVC_STREAM_THROTTLER)
                if throttler:
                    # 立即刷新缓冲区，保存已接收的内容
                    await throttler.flush_all(task_id)
                    
                    if self.logger:
                        self.logger.debug(f"Flushed stream buffer for task '{task_id}'")
            
            elif task_type in (TASK_RAG_INDEX, TASK_CODE_INDEX):
                # 索引任务：保存已索引的进度
                if self.logger:
                    self.logger.debug(f"Saving partial index progress for task '{task_id}'")
            
            # 通知 StopController 清理完成
            # mark_stopping() 会检查状态，非 STOP_REQUESTED 状态下会静默返回
            if self.stop_controller:
                self.stop_controller.mark_stopping()
            
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Error during task cleanup for '{task_id}': {e}")
        
        return partial_result
    
    # ============================================================
    # 任务取消
    # ============================================================
    
    def cancel(self, task_id: str) -> bool:
        """
        取消指定任务
        
        Args:
            task_id: 任务标识
            
        Returns:
            bool: 是否成功取消
        """
        if task_id not in self._tasks:
            # 检查是否在待执行队列中
            for task_type, queue in self._pending_queues.items():
                for i, pending_task in enumerate(queue):
                    if pending_task.task_id == task_id:
                        # 从队列中移除
                        queue_list = list(queue)
                        queue_list.pop(i)
                        queue.clear()
                        queue.extend(queue_list)
                        
                        if self.logger:
                            self.logger.info(f"Pending task '{task_id}' removed from queue")
                        return True
            
            return False
        
        task_info = self._tasks[task_id]
        
        # 取消 asyncio.Task
        if not task_info.task.done():
            task_info.task.cancel()
            
            if self.logger:
                self.logger.info(f"Task '{task_id}' ({task_info.task_type}) cancellation requested")
            
            return True
        
        return False
    
    def cancel_by_type(self, task_type: str) -> int:
        """
        取消指定类型的所有任务
        
        Args:
            task_type: 任务类型
            
        Returns:
            int: 取消的任务数量
        """
        cancelled_count = 0
        
        # 取消运行中的任务
        for task_id, task_info in list(self._tasks.items()):
            if task_info.task_type == task_type:
                if self.cancel(task_id):
                    cancelled_count += 1
        
        # 清空待执行队列
        if task_type in self._pending_queues:
            queue_size = len(self._pending_queues[task_type])
            self._pending_queues[task_type].clear()
            cancelled_count += queue_size
        
        if self.logger:
            self.logger.info(f"Cancelled {cancelled_count} tasks of type '{task_type}'")
        
        return cancelled_count
    
    def cancel_all(self) -> int:
        """
        取消所有运行中的任务
        
        Returns:
            int: 取消的任务数量
        """
        cancelled_count = 0
        
        # 取消所有运行中的任务
        for task_id in list(self._tasks.keys()):
            if self.cancel(task_id):
                cancelled_count += 1
        
        # 清空所有待执行队列
        for queue in self._pending_queues.values():
            cancelled_count += len(queue)
            queue.clear()
        
        if self.logger:
            self.logger.info(f"Cancelled all tasks, total: {cancelled_count}")
        
        return cancelled_count
    
    # ============================================================
    # 状态查询
    # ============================================================
    
    def get_task_state(self, task_id: str) -> Optional[TaskState]:
        """
        获取任务状态
        
        Args:
            task_id: 任务标识
            
        Returns:
            TaskState: 任务状态，未找到返回 None
        """
        task_info = self._tasks.get(task_id)
        return task_info.state if task_info else None
    
    def get_task_info(self, task_id: str) -> Optional[TaskInfo]:
        """
        获取任务信息
        
        Args:
            task_id: 任务标识
            
        Returns:
            TaskInfo: 任务信息，未找到返回 None
        """
        return self._tasks.get(task_id)
    
    def get_running_tasks(self, task_type: Optional[str] = None) -> List[TaskInfo]:
        """
        获取运行中的任务列表
        
        Args:
            task_type: 任务类型（可选），None 表示所有类型
            
        Returns:
            List[TaskInfo]: 运行中的任务列表
        """
        running_tasks = [
            task_info for task_info in self._tasks.values()
            if task_info.state == TaskState.RUNNING
        ]
        
        if task_type:
            running_tasks = [
                task_info for task_info in running_tasks
                if task_info.task_type == task_type
            ]
        
        return running_tasks
    
    def is_task_running(self, task_type: str) -> bool:
        """
        检查指定类型是否有任务在运行
        
        Args:
            task_type: 任务类型
            
        Returns:
            bool: 是否有任务在运行
        """
        return self._is_type_locked(task_type)
    
    def get_queue_size(self, task_type: str) -> int:
        """
        获取待执行队列大小
        
        Args:
            task_type: 任务类型
            
        Returns:
            int: 队列中等待的任务数
        """
        if task_type not in self._pending_queues:
            return 0
        return len(self._pending_queues[task_type])
    
    # ============================================================
    # 清理
    # ============================================================
    
    def cleanup_completed_tasks(self, max_age_seconds: int = 3600) -> int:
        """
        清理已完成的任务记录
        
        Args:
            max_age_seconds: 最大保留时间（秒）
            
        Returns:
            int: 清理的任务数量
        """
        now = datetime.now()
        cleaned_count = 0
        
        for task_id, task_info in list(self._tasks.items()):
            if task_info.state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
                if task_info.completed_at:
                    age_seconds = (now - task_info.completed_at).total_seconds()
                    if age_seconds > max_age_seconds:
                        del self._tasks[task_id]
                        cleaned_count += 1
        
        if cleaned_count > 0 and self.logger:
            self.logger.info(f"Cleaned up {cleaned_count} completed tasks")
        
        return cleaned_count
    
    # ============================================================
    # 事件发布
    # ============================================================
    
    def _publish_event(
        self,
        event_type: str,
        task_id: str,
        task_type: str,
        extra_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """发布任务事件"""
        if self.event_bus is None:
            return
        
        event_data = {
            "task_id": task_id,
            "task_type": task_type,
        }
        if extra_data:
            event_data.update(extra_data)
        
        try:
            self.event_bus.publish(event_type, event_data, source="async_task_registry")
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to publish task event: {e}")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "AsyncTaskRegistry",
    "TaskState",
    "TaskPriority",
    "TaskInfo",
    "PendingTask",
    # 任务类型常量
    "TASK_LLM",
    "TASK_RAG_INDEX",
    "TASK_RAG_SEARCH",
    "TASK_FILE_WATCH",
    "TASK_SIMULATION",
    "TASK_SCHEMATIC",
    "TASK_CODE_INDEX",
]
