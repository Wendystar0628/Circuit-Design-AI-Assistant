# Worker Manager - Worker Lifecycle Management
"""
Worker 生命周期管理器 - 统一管理所有后台 Worker

职责：
- Worker 注册与调度
- 任务排队（同类互斥）
- 健康检查与资源清理
- 状态变更事件发布

初始化顺序：
- Phase 3.1（延迟初始化），依赖 EventBus，在事件循环中异步执行

设计原则：
- 延迟获取 EventBus 和 Logger，避免初始化顺序问题
- 同类任务互斥排队，异类任务可并行
- Worker 与 UI 通信必须通过信号槽机制

使用示例：
    from shared.worker_manager import WorkerManager
    from shared.worker_types import WORKER_LLM
    
    worker_manager = WorkerManager()
    worker_manager.register_worker(WORKER_LLM, llm_worker_instance)
    worker_manager.start_worker(WORKER_LLM, {"prompt": "Hello"})
"""

import time
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QTimer

from shared.worker_types import (
    WorkerStatus,
    TaskPriority,
    WORKER_LLM,
    WORKER_SIMULATION,
    WORKER_RAG,
    WORKER_FILE_WATCHER,
)
from shared.event_types import (
    EVENT_WORKER_STARTED,
    EVENT_WORKER_PROGRESS,
    EVENT_WORKER_COMPLETE,
    EVENT_WORKER_ERROR,
)


# ============================================================
# 任务数据结构
# ============================================================

@dataclass
class Task:
    """任务数据结构"""
    
    # 任务参数
    params: Dict[str, Any]
    
    # 任务优先级
    priority: TaskPriority = TaskPriority.NORMAL
    
    # 创建时间戳
    created_at: float = field(default_factory=time.time)
    
    # 任务 ID（自动生成）
    task_id: str = field(default_factory=lambda: f"task_{time.time_ns()}")


@dataclass
class WorkerInfo:
    """Worker 注册信息"""
    
    # Worker 实例
    instance: Any
    
    # 当前状态
    status: WorkerStatus = WorkerStatus.IDLE
    
    # 任务队列
    task_queue: deque = field(default_factory=deque)
    
    # 当前任务
    current_task: Optional[Task] = None
    
    # 启动时间
    start_time: Optional[float] = None
    
    # 统计信息
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    total_duration_ms: float = 0.0


# ============================================================
# Worker 管理器
# ============================================================

class WorkerManager:
    """
    Worker 生命周期管理器
    
    统一管理所有后台 Worker 的创建、调度、监控和资源清理。
    
    调度策略：
    - 同类任务互斥排队（如多个 LLM 请求排队执行）
    - 异类任务可并行（如仿真与 LLM 可同时进行）
    - 任务优先级支持（用户触发 > 自动触发）
    """

    def __init__(self):
        # Worker 注册表
        self._workers: Dict[str, WorkerInfo] = {}
        
        # 线程锁
        self._lock = threading.Lock()
        
        # 延迟获取的服务
        self._event_bus = None
        self._logger = None
        
        # 健康检查定时器
        self._health_check_timer: Optional[QTimer] = None
        self._health_check_interval_ms = 30000  # 30秒

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
                self._logger = get_logger("worker_manager")
            except Exception:
                pass
        return self._logger


    # ============================================================
    # Worker 注册与管理
    # ============================================================

    def register_worker(self, worker_type: str, worker_instance: Any) -> bool:
        """
        注册 Worker 实例
        
        Args:
            worker_type: Worker 类型（使用 worker_types.py 中的常量）
            worker_instance: Worker 实例（需实现 start/stop 方法）
            
        Returns:
            bool: 是否注册成功
        """
        with self._lock:
            if worker_type in self._workers:
                if self.logger:
                    self.logger.warning(f"Worker '{worker_type}' already registered, replacing")
            
            self._workers[worker_type] = WorkerInfo(instance=worker_instance)
            
            if self.logger:
                self.logger.info(f"Worker '{worker_type}' registered")
            
            return True

    def unregister_worker(self, worker_type: str) -> bool:
        """
        注销 Worker
        
        Args:
            worker_type: Worker 类型
            
        Returns:
            bool: 是否注销成功
        """
        with self._lock:
            if worker_type not in self._workers:
                return False
            
            # 先停止 Worker
            worker_info = self._workers[worker_type]
            if worker_info.status == WorkerStatus.RUNNING:
                self._stop_worker_internal(worker_type, worker_info)
            
            del self._workers[worker_type]
            
            if self.logger:
                self.logger.info(f"Worker '{worker_type}' unregistered")
            
            return True

    # ============================================================
    # 任务调度
    # ============================================================

    def start_worker(
        self,
        worker_type: str,
        task_params: Dict[str, Any],
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> Optional[str]:
        """
        启动 Worker 执行任务
        
        如果 Worker 正在执行，任务将被排队。
        
        Args:
            worker_type: Worker 类型
            task_params: 任务参数
            priority: 任务优先级
            
        Returns:
            str: 任务 ID，失败返回 None
        """
        task = Task(params=task_params, priority=priority)
        return self.queue_task(worker_type, task)

    def queue_task(self, worker_type: str, task: Task) -> Optional[str]:
        """
        任务排队
        
        同类任务互斥排队，按优先级排序。
        
        Args:
            worker_type: Worker 类型
            task: 任务对象
            
        Returns:
            str: 任务 ID，失败返回 None
        """
        with self._lock:
            if worker_type not in self._workers:
                if self.logger:
                    self.logger.error(f"Worker '{worker_type}' not registered")
                return None
            
            worker_info = self._workers[worker_type]
            
            # 按优先级插入队列
            self._insert_by_priority(worker_info.task_queue, task)
            
            if self.logger:
                self.logger.debug(
                    f"Task '{task.task_id}' queued for '{worker_type}', "
                    f"queue size: {len(worker_info.task_queue)}"
                )
            
            # 如果 Worker 空闲，立即执行
            if worker_info.status == WorkerStatus.IDLE:
                self._execute_next_task(worker_type, worker_info)
            
            return task.task_id

    def _insert_by_priority(self, queue: deque, task: Task):
        """按优先级插入队列（高优先级在前）"""
        # 简单实现：遍历找到插入位置
        insert_pos = len(queue)
        for i, existing_task in enumerate(queue):
            if task.priority.value > existing_task.priority.value:
                insert_pos = i
                break
        
        # deque 不支持 insert，转换为 list 操作
        queue_list = list(queue)
        queue_list.insert(insert_pos, task)
        queue.clear()
        queue.extend(queue_list)


    def _execute_next_task(self, worker_type: str, worker_info: WorkerInfo):
        """执行队列中的下一个任务"""
        if not worker_info.task_queue:
            return
        
        task = worker_info.task_queue.popleft()
        worker_info.current_task = task
        worker_info.status = WorkerStatus.RUNNING
        worker_info.start_time = time.time()
        worker_info.total_tasks += 1
        
        # 发布 Worker 启动事件
        self._publish_worker_event(
            EVENT_WORKER_STARTED,
            worker_type,
            task.task_id,
            {"params": task.params}
        )
        
        if self.logger:
            self.logger.info(f"Worker '{worker_type}' started task '{task.task_id}'")
        
        # 启动 Worker（Worker 需实现 start 方法）
        try:
            worker = worker_info.instance
            if hasattr(worker, 'start'):
                worker.start(task.params)
            elif hasattr(worker, 'run'):
                worker.run(task.params)
            else:
                if self.logger:
                    self.logger.error(f"Worker '{worker_type}' has no start/run method")
        except Exception as e:
            self._handle_worker_error(worker_type, worker_info, e)

    # ============================================================
    # Worker 停止
    # ============================================================

    def stop_worker(self, worker_type: str) -> bool:
        """
        停止指定 Worker
        
        Args:
            worker_type: Worker 类型
            
        Returns:
            bool: 是否成功停止
        """
        with self._lock:
            if worker_type not in self._workers:
                return False
            
            worker_info = self._workers[worker_type]
            return self._stop_worker_internal(worker_type, worker_info)

    def _stop_worker_internal(self, worker_type: str, worker_info: WorkerInfo) -> bool:
        """内部停止 Worker 方法"""
        if worker_info.status != WorkerStatus.RUNNING:
            return True
        
        try:
            worker = worker_info.instance
            if hasattr(worker, 'stop'):
                worker.stop()
            elif hasattr(worker, 'terminate'):
                worker.terminate()
            
            worker_info.status = WorkerStatus.STOPPED
            worker_info.current_task = None
            
            if self.logger:
                self.logger.info(f"Worker '{worker_type}' stopped")
            
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to stop worker '{worker_type}': {e}")
            return False

    def stop_all_workers(self) -> None:
        """
        停止所有 Worker
        
        应用退出时调用，确保所有 Worker 优雅停止。
        """
        with self._lock:
            for worker_type, worker_info in self._workers.items():
                if worker_info.status == WorkerStatus.RUNNING:
                    self._stop_worker_internal(worker_type, worker_info)
            
            if self.logger:
                self.logger.info("All workers stopped")

    # ============================================================
    # 状态查询
    # ============================================================

    def get_worker_status(self, worker_type: str) -> Optional[WorkerStatus]:
        """
        获取 Worker 状态
        
        Args:
            worker_type: Worker 类型
            
        Returns:
            WorkerStatus: Worker 状态，未注册返回 None
        """
        with self._lock:
            if worker_type not in self._workers:
                return None
            return self._workers[worker_type].status

    def is_worker_busy(self, worker_type: str) -> bool:
        """
        检查 Worker 是否忙碌
        
        Args:
            worker_type: Worker 类型
            
        Returns:
            bool: 是否正在执行任务
        """
        status = self.get_worker_status(worker_type)
        return status == WorkerStatus.RUNNING

    def get_queue_size(self, worker_type: str) -> int:
        """
        获取任务队列大小
        
        Args:
            worker_type: Worker 类型
            
        Returns:
            int: 队列中等待的任务数
        """
        with self._lock:
            if worker_type not in self._workers:
                return 0
            return len(self._workers[worker_type].task_queue)

    def get_all_worker_types(self) -> List[str]:
        """获取所有已注册的 Worker 类型"""
        with self._lock:
            return list(self._workers.keys())


    # ============================================================
    # Worker 完成/错误回调
    # ============================================================

    def on_worker_complete(self, worker_type: str, result: Any = None):
        """
        Worker 完成回调
        
        由 Worker 在任务完成时调用。
        
        Args:
            worker_type: Worker 类型
            result: 任务结果
        """
        with self._lock:
            if worker_type not in self._workers:
                return
            
            worker_info = self._workers[worker_type]
            task = worker_info.current_task
            
            # 计算执行时间
            duration_ms = 0.0
            if worker_info.start_time:
                duration_ms = (time.time() - worker_info.start_time) * 1000
                worker_info.total_duration_ms += duration_ms
            
            worker_info.completed_tasks += 1
            worker_info.status = WorkerStatus.IDLE
            worker_info.current_task = None
            worker_info.start_time = None
            
            task_id = task.task_id if task else "unknown"
            
            if self.logger:
                self.logger.info(
                    f"Worker '{worker_type}' completed task '{task_id}' "
                    f"in {duration_ms:.0f}ms"
                )
            
            # 发布完成事件
            self._publish_worker_event(
                EVENT_WORKER_COMPLETE,
                worker_type,
                task_id,
                {"result": result, "duration_ms": duration_ms}
            )
            
            # 执行队列中的下一个任务
            self._execute_next_task(worker_type, worker_info)

    def on_worker_error(self, worker_type: str, error: Exception):
        """
        Worker 错误回调
        
        由 Worker 在发生错误时调用。
        
        Args:
            worker_type: Worker 类型
            error: 异常对象
        """
        with self._lock:
            if worker_type not in self._workers:
                return
            
            worker_info = self._workers[worker_type]
            self._handle_worker_error(worker_type, worker_info, error)

    def _handle_worker_error(
        self, worker_type: str, worker_info: WorkerInfo, error: Exception
    ):
        """处理 Worker 错误"""
        task = worker_info.current_task
        task_id = task.task_id if task else "unknown"
        
        worker_info.failed_tasks += 1
        worker_info.status = WorkerStatus.ERROR
        worker_info.current_task = None
        worker_info.start_time = None
        
        if self.logger:
            self.logger.error(
                f"Worker '{worker_type}' failed on task '{task_id}': {error}"
            )
        
        # 发布错误事件
        self._publish_worker_event(
            EVENT_WORKER_ERROR,
            worker_type,
            task_id,
            {"error": str(error), "error_type": type(error).__name__}
        )
        
        # 恢复为空闲状态，继续处理队列
        worker_info.status = WorkerStatus.IDLE
        self._execute_next_task(worker_type, worker_info)

    def on_worker_progress(self, worker_type: str, progress: int, message: str = ""):
        """
        Worker 进度回调
        
        由 Worker 在执行过程中调用以报告进度。
        
        Args:
            worker_type: Worker 类型
            progress: 进度百分比 (0-100)
            message: 进度消息
        """
        with self._lock:
            if worker_type not in self._workers:
                return
            
            worker_info = self._workers[worker_type]
            task = worker_info.current_task
            task_id = task.task_id if task else "unknown"
        
        # 发布进度事件
        self._publish_worker_event(
            EVENT_WORKER_PROGRESS,
            worker_type,
            task_id,
            {"progress": progress, "message": message}
        )


    # ============================================================
    # 健康检查
    # ============================================================

    def start_health_check(self):
        """启动健康检查定时器"""
        if self._health_check_timer is not None:
            return
        
        self._health_check_timer = QTimer()
        self._health_check_timer.timeout.connect(self._do_health_check)
        self._health_check_timer.start(self._health_check_interval_ms)
        
        if self.logger:
            self.logger.info(
                f"Health check started, interval: {self._health_check_interval_ms}ms"
            )

    def stop_health_check(self):
        """停止健康检查定时器"""
        if self._health_check_timer is not None:
            self._health_check_timer.stop()
            self._health_check_timer = None
            
            if self.logger:
                self.logger.info("Health check stopped")

    def _do_health_check(self):
        """执行健康检查"""
        with self._lock:
            for worker_type, worker_info in self._workers.items():
                # 检查运行中的 Worker 是否超时
                if worker_info.status == WorkerStatus.RUNNING and worker_info.start_time:
                    duration_s = time.time() - worker_info.start_time
                    
                    # 超过 5 分钟视为可能僵死
                    if duration_s > 300:
                        if self.logger:
                            self.logger.warning(
                                f"Worker '{worker_type}' running for {duration_s:.0f}s, "
                                f"may be stuck"
                            )

    # ============================================================
    # 统计信息
    # ============================================================

    def get_stats(self, worker_type: str) -> Optional[Dict[str, Any]]:
        """
        获取 Worker 统计信息
        
        Args:
            worker_type: Worker 类型
            
        Returns:
            dict: 统计信息，未注册返回 None
        """
        with self._lock:
            if worker_type not in self._workers:
                return None
            
            info = self._workers[worker_type]
            avg_duration = 0.0
            if info.completed_tasks > 0:
                avg_duration = info.total_duration_ms / info.completed_tasks
            
            return {
                "status": info.status.name,
                "queue_size": len(info.task_queue),
                "total_tasks": info.total_tasks,
                "completed_tasks": info.completed_tasks,
                "failed_tasks": info.failed_tasks,
                "avg_duration_ms": avg_duration,
            }

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有 Worker 的统计信息"""
        with self._lock:
            return {
                worker_type: self.get_stats(worker_type)
                for worker_type in self._workers
            }

    # ============================================================
    # 事件发布
    # ============================================================

    def _publish_worker_event(
        self,
        event_type: str,
        worker_type: str,
        task_id: str,
        extra_data: Dict[str, Any] = None,
    ):
        """发布 Worker 事件"""
        if self.event_bus is None:
            return
        
        event_data = {
            "worker_type": worker_type,
            "task_id": task_id,
        }
        if extra_data:
            event_data.update(extra_data)
        
        try:
            self.event_bus.publish(event_type, event_data, source="worker_manager")
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to publish worker event: {e}")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "WorkerManager",
    "Task",
    "WorkerInfo",
]
