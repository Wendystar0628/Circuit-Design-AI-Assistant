# Stop Controller - Global Stop State Management
"""
停止控制器 - 全局停止状态管理

职责：
- 提供全局统一的停止状态管理
- 停止信号广播机制
- 停止原因记录
- 协调多个组件的停止操作
- 停止超时保护（3.0.10）

设计原则：
- 线程安全：所有状态访问通过锁保护
- 单例模式：通过 ServiceLocator 注册和获取
- 即时响应：停止请求应在 500ms 内开始中断
- 优雅降级：停止时保存已生成的部分内容
- 超时保护：停止请求后最多等待 5 秒，超时后强制终止

初始化顺序：
- Phase 3.3.1，依赖 Logger、EventBus，注册到 ServiceLocator

使用示例：
    from shared.stop_controller import StopController, StopReason
    
    controller = StopController()
    
    # 请求停止
    controller.request_stop(StopReason.USER_REQUESTED)
    
    # 检查是否停止
    if controller.is_stop_requested():
        # 清理资源
        controller.mark_stopping()
        # 完成清理
        controller.mark_stopped({"partial_result": data})
"""

import asyncio
import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QObject, QMetaObject, Qt, Q_ARG, pyqtSignal


# ============================================================
# 常量定义
# ============================================================

# 停止超时时间（秒）
STOP_TIMEOUT_SECONDS = 5.0

# 强制终止前的警告阈值（秒）
FORCE_STOP_WARNING_THRESHOLD = 4.0


# ============================================================
# 枚举定义
# ============================================================

class StopReason(Enum):
    """停止原因枚举"""
    USER_REQUESTED = "user_requested"      # 用户主动停止
    TIMEOUT = "timeout"                    # 超时自动停止
    ERROR = "error"                        # 错误导致停止
    SESSION_SWITCH = "session_switch"      # 切换会话时停止
    APP_SHUTDOWN = "app_shutdown"          # 应用关闭时停止


class StopState(Enum):
    """停止状态枚举"""
    IDLE = "idle"                          # 空闲，无活跃任务
    RUNNING = "running"                    # 任务运行中
    STOP_REQUESTED = "stop_requested"      # 已请求停止，等待响应
    STOPPING = "stopping"                  # 正在停止中（清理资源）
    STOPPED = "stopped"                    # 已完全停止


# ============================================================
# StopController 类
# ============================================================

class StopController(QObject):
    """
    停止控制器
    
    提供全局统一的停止状态管理和信号广播机制。
    
    Signals:
        stop_requested(str, str): 停止请求 (task_id, reason)
        stop_completed(str, dict): 停止完成 (task_id, result)
        state_changed(str): 状态变更 (new_state)
        stop_timeout(str): 停止超时 (task_id)
    
    Thread Safety:
        所有状态访问通过 _lock 保护，信号发送确保在主线程执行。
    
    超时保护（3.0.10）：
        停止请求后最多等待 5 秒，超时后强制终止并记录警告日志。
    """
    
    # 信号定义
    stop_requested = pyqtSignal(str, str)  # (task_id, reason)
    stop_completed = pyqtSignal(str, dict)  # (task_id, result)
    state_changed = pyqtSignal(str)  # (new_state)
    stop_timeout = pyqtSignal(str)  # (task_id) - 停止超时信号
    
    def __init__(self, parent: Optional[QObject] = None):
        """初始化停止控制器"""
        super().__init__(parent)
        
        # 状态属性
        self._state: StopState = StopState.IDLE
        self._stop_reason: Optional[StopReason] = None
        self._active_task_id: Optional[str] = None
        
        # 线程同步
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        
        # 停止请求时间戳
        self._stop_requested_at: Optional[float] = None
        
        # 超时保护（3.0.10）
        self._timeout_timer: Optional[threading.Timer] = None
        self._force_stopped: bool = False
        
        # 资源清理回调（3.0.10）
        self._cleanup_callbacks: List[Callable[[], None]] = []
        
        # 延迟获取的服务
        self._event_bus = None
        self._logger = None
    
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
                self._logger = get_logger("stop_controller")
            except Exception:
                pass
        return self._logger
    
    # ============================================================
    # 核心方法
    # ============================================================
    
    def request_stop(self, reason: StopReason = StopReason.USER_REQUESTED) -> bool:
        """
        请求停止当前任务
        
        Args:
            reason: 停止原因
            
        Returns:
            bool: 是否成功请求停止（如果已经在停止中，返回 False）
        
        Note:
            请求停止后会启动超时保护定时器（5秒），超时后强制终止。
        """
        with self._lock:
            # 检查当前状态
            if self._state in (StopState.STOP_REQUESTED, StopState.STOPPING, StopState.STOPPED):
                if self.logger:
                    self.logger.warning(
                        f"Stop already requested or in progress, current state: {self._state.value}"
                    )
                return False
            
            # 如果没有活跃任务，直接返回
            if self._state == StopState.IDLE:
                if self.logger:
                    self.logger.info("No active task to stop")
                return False
            
            # 更新状态
            old_state = self._state
            self._state = StopState.STOP_REQUESTED
            self._stop_reason = reason
            self._stop_requested_at = time.time()
            self._force_stopped = False
            
            # 设置停止事件
            self._stop_event.set()
            
            task_id = self._active_task_id or "unknown"
            
            if self.logger:
                self.logger.info(
                    f"Stop requested: task_id={task_id}, reason={reason.value}, "
                    f"old_state={old_state.value}"
                )
            
            # 启动超时保护定时器（3.0.10）
            self._start_timeout_timer(task_id)
        
        # 在锁外发送信号和事件
        self._emit_state_changed(self._state.value)
        self._emit_stop_requested(task_id, reason.value)
        self._publish_event("EVENT_STOP_REQUESTED", task_id, reason.value)
        
        return True
    
    def _start_timeout_timer(self, task_id: str) -> None:
        """
        启动停止超时保护定时器（3.0.10）
        
        Args:
            task_id: 任务标识
        """
        # 取消之前的定时器
        if self._timeout_timer:
            self._timeout_timer.cancel()
        
        def on_timeout():
            self._handle_stop_timeout(task_id)
        
        self._timeout_timer = threading.Timer(STOP_TIMEOUT_SECONDS, on_timeout)
        self._timeout_timer.daemon = True
        self._timeout_timer.start()
        
        if self.logger:
            self.logger.debug(f"Stop timeout timer started: {STOP_TIMEOUT_SECONDS}s")
    
    def _cancel_timeout_timer(self) -> None:
        """取消超时保护定时器"""
        if self._timeout_timer:
            self._timeout_timer.cancel()
            self._timeout_timer = None
    
    def _handle_stop_timeout(self, task_id: str) -> None:
        """
        处理停止超时（3.0.10）
        
        超时后强制终止，尽可能保存已有数据。
        
        Args:
            task_id: 任务标识
        """
        with self._lock:
            # 检查是否已经完成停止
            if self._state == StopState.STOPPED or self._state == StopState.IDLE:
                return
            
            self._force_stopped = True
            
            if self.logger:
                self.logger.warning(
                    f"Stop timeout after {STOP_TIMEOUT_SECONDS}s, forcing termination: "
                    f"task_id={task_id}"
                )
        
        # 执行强制清理回调
        self._execute_cleanup_callbacks()
        
        # 发送超时信号
        self._emit_stop_timeout(task_id)
        
        # 强制标记为已停止
        self.mark_stopped({
            "is_partial": True,
            "cleanup_success": False,
            "force_stopped": True,
            "timeout": True,
        })
    
    def _emit_stop_timeout(self, task_id: str) -> None:
        """发送停止超时信号（线程安全）"""
        if threading.current_thread() is threading.main_thread():
            self.stop_timeout.emit(task_id)
        else:
            QMetaObject.invokeMethod(
                self,
                "_emit_stop_timeout_slot",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, task_id)
            )
    
    def _emit_stop_timeout_slot(self, task_id: str) -> None:
        """停止超时信号槽"""
        self.stop_timeout.emit(task_id)
    
    def is_stop_requested(self) -> bool:
        """
        检查是否已请求停止（线程安全）
        
        Returns:
            bool: True 表示已请求停止
        """
        with self._lock:
            return self._state in (StopState.STOP_REQUESTED, StopState.STOPPING, StopState.STOPPED)
    
    def wait_for_stop(self, timeout: Optional[float] = None) -> bool:
        """
        等待停止完成
        
        Args:
            timeout: 超时时间（秒），None 表示无限等待
            
        Returns:
            bool: True 表示停止完成，False 表示超时
        """
        return self._stop_event.wait(timeout)
    
    def mark_stopping(self) -> bool:
        """
        标记正在停止（资源清理中）
        
        由执行器在开始清理资源时调用。
        
        Returns:
            bool: 是否成功标记为 STOPPING 状态
        
        Note:
            在非 STOP_REQUESTED 状态下调用是正常的竞态情况（如任务已完成或未注册），
            此时静默返回 False，不打印警告。
            
            常见的正常竞态场景：
            - 任务未通过 register_task() 注册就被停止
            - 任务已经完成，状态已重置为 IDLE
            - 多个组件同时响应停止事件，第一个已经完成状态转换
        """
        with self._lock:
            if self._state != StopState.STOP_REQUESTED:
                # 非预期状态是正常的竞态情况，静默返回
                # 不打印警告，因为这是预期的行为
                return False
            
            old_state = self._state
            self._state = StopState.STOPPING
            
            if self.logger:
                self.logger.info(
                    f"Stopping: task_id={self._active_task_id}, "
                    f"old_state={old_state.value}"
                )
        
        self._emit_state_changed(self._state.value)
        self._publish_event("EVENT_STOP_STATE_CHANGED", self._active_task_id or "unknown", {
            "old_state": old_state.value,
            "new_state": self._state.value
        })
        
        return True
    
    def mark_stopped(self, result: Optional[Dict[str, Any]] = None) -> bool:
        """
        标记停止完成
        
        由执行器在完成资源清理后调用。
        
        Args:
            result: 停止结果，包含部分结果、清理状态等
            
        Returns:
            bool: 是否成功标记为 STOPPED 状态
        
        Note:
            在非 STOP_REQUESTED/STOPPING 状态下调用是正常的竞态情况，
            此时静默返回 False。
        """
        with self._lock:
            # 取消超时定时器（3.0.10）
            self._cancel_timeout_timer()
            
            if self._state not in (StopState.STOP_REQUESTED, StopState.STOPPING):
                # 非预期状态是正常的竞态情况，静默返回
                return False
            
            old_state = self._state
            self._state = StopState.STOPPED
            
            task_id = self._active_task_id or "unknown"
            reason = self._stop_reason.value if self._stop_reason else "unknown"
            
            # 计算停止耗时
            duration_ms = 0.0
            if self._stop_requested_at:
                duration_ms = (time.time() - self._stop_requested_at) * 1000
            
            if self.logger:
                self.logger.info(
                    f"Stopped: task_id={task_id}, reason={reason}, "
                    f"duration={duration_ms:.0f}ms, old_state={old_state.value}, "
                    f"force_stopped={self._force_stopped}"
                )
        
        # 构建结果
        stop_result = result or {}
        stop_result.update({
            "task_id": task_id,
            "reason": reason,
            "duration_ms": duration_ms,
            "is_partial": stop_result.get("is_partial", True),
            "cleanup_success": stop_result.get("cleanup_success", True),
            "force_stopped": self._force_stopped,
        })
        
        # 在锁外发送信号和事件
        self._emit_state_changed(self._state.value)
        self._emit_stop_completed(task_id, stop_result)
        self._publish_event("EVENT_STOP_COMPLETED", task_id, stop_result)
        
        return True
    
    def reset(self) -> None:
        """
        重置状态为 IDLE
        
        在任务完成或停止后调用，准备接受新任务。
        """
        with self._lock:
            # 取消超时定时器（3.0.10）
            self._cancel_timeout_timer()
            
            old_state = self._state
            self._state = StopState.IDLE
            self._stop_reason = None
            self._active_task_id = None
            self._stop_requested_at = None
            self._force_stopped = False
            
            # 清除停止事件
            self._stop_event.clear()
            
            if self.logger:
                self.logger.debug(f"Reset: old_state={old_state.value}")
        
        self._emit_state_changed(self._state.value)
    
    def register_task(self, task_id: str) -> bool:
        """
        注册新任务
        
        Args:
            task_id: 任务标识
            
        Returns:
            bool: 是否成功注册（如果已有活跃任务，返回 False）
        """
        with self._lock:
            if self._state != StopState.IDLE:
                if self.logger:
                    self.logger.warning(
                        f"Cannot register task '{task_id}', current state: {self._state.value}"
                    )
                return False
            
            self._state = StopState.RUNNING
            self._active_task_id = task_id
            self._stop_reason = None
            self._stop_requested_at = None
            
            # 清除停止事件
            self._stop_event.clear()
            
            if self.logger:
                self.logger.info(f"Task registered: task_id={task_id}")
        
        self._emit_state_changed(self._state.value)
        return True
    
    def get_state(self) -> StopState:
        """
        获取当前状态
        
        Returns:
            StopState: 当前停止状态
        """
        with self._lock:
            return self._state
    
    def get_stop_reason(self) -> Optional[StopReason]:
        """
        获取停止原因
        
        Returns:
            StopReason: 停止原因，未停止时返回 None
        """
        with self._lock:
            return self._stop_reason
    
    def get_active_task_id(self) -> Optional[str]:
        """
        获取当前活跃任务 ID
        
        Returns:
            str: 任务 ID，无活跃任务时返回 None
        """
        with self._lock:
            return self._active_task_id
    
    # ============================================================
    # 资源清理回调管理（3.0.10）
    # ============================================================
    
    def register_cleanup_callback(self, callback: Callable[[], None]) -> None:
        """
        注册资源清理回调
        
        当停止超时强制终止时，会调用所有注册的清理回调。
        
        Args:
            callback: 清理回调函数（无参数，无返回值）
        """
        with self._lock:
            if callback not in self._cleanup_callbacks:
                self._cleanup_callbacks.append(callback)
                if self.logger:
                    self.logger.debug(f"Cleanup callback registered: {callback.__name__}")
    
    def unregister_cleanup_callback(self, callback: Callable[[], None]) -> None:
        """
        注销资源清理回调
        
        Args:
            callback: 要注销的回调函数
        """
        with self._lock:
            if callback in self._cleanup_callbacks:
                self._cleanup_callbacks.remove(callback)
                if self.logger:
                    self.logger.debug(f"Cleanup callback unregistered: {callback.__name__}")
    
    def _execute_cleanup_callbacks(self) -> None:
        """
        执行所有资源清理回调
        
        在停止超时强制终止时调用。
        """
        with self._lock:
            callbacks = list(self._cleanup_callbacks)
        
        for callback in callbacks:
            try:
                callback()
                if self.logger:
                    self.logger.debug(f"Cleanup callback executed: {callback.__name__}")
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Cleanup callback failed: {callback.__name__}, error={e}")
    
    def is_force_stopped(self) -> bool:
        """
        检查是否为强制停止（超时）
        
        Returns:
            bool: True 表示是超时强制停止
        """
        with self._lock:
            return self._force_stopped
    
    # ============================================================
    # 信号发送（确保在主线程执行）
    # ============================================================
    
    def _emit_stop_requested(self, task_id: str, reason: str) -> None:
        """发送停止请求信号（线程安全）"""
        if threading.current_thread() is threading.main_thread():
            self.stop_requested.emit(task_id, reason)
        else:
            QMetaObject.invokeMethod(
                self,
                "_emit_stop_requested_slot",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, task_id),
                Q_ARG(str, reason)
            )
    
    def _emit_stop_completed(self, task_id: str, result: Dict[str, Any]) -> None:
        """发送停止完成信号（线程安全）"""
        if threading.current_thread() is threading.main_thread():
            self.stop_completed.emit(task_id, result)
        else:
            QMetaObject.invokeMethod(
                self,
                "_emit_stop_completed_slot",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, task_id),
                Q_ARG(dict, result)
            )
    
    def _emit_state_changed(self, new_state: str) -> None:
        """发送状态变更信号（线程安全）"""
        if threading.current_thread() is threading.main_thread():
            self.state_changed.emit(new_state)
        else:
            QMetaObject.invokeMethod(
                self,
                "_emit_state_changed_slot",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, new_state)
            )
    
    # 槽函数（用于跨线程信号发送）
    def _emit_stop_requested_slot(self, task_id: str, reason: str) -> None:
        """停止请求信号槽"""
        self.stop_requested.emit(task_id, reason)
    
    def _emit_stop_completed_slot(self, task_id: str, result: Dict[str, Any]) -> None:
        """停止完成信号槽"""
        self.stop_completed.emit(task_id, result)
    
    def _emit_state_changed_slot(self, new_state: str) -> None:
        """状态变更信号槽"""
        self.state_changed.emit(new_state)
    
    # ============================================================
    # 事件发布
    # ============================================================
    
    def _publish_event(
        self,
        event_type: str,
        task_id: str,
        data: Any
    ) -> None:
        """发布事件到 EventBus"""
        if self.event_bus is None:
            return
        
        event_data = {
            "task_id": task_id,
            "timestamp": time.time(),
        }
        
        if isinstance(data, dict):
            event_data.update(data)
        else:
            event_data["reason"] = data
        
        try:
            self.event_bus.publish(event_type, event_data, source="stop_controller")
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to publish event: {e}")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "StopController",
    "StopReason",
    "StopState",
    "STOP_TIMEOUT_SECONDS",
    "FORCE_STOP_WARNING_THRESHOLD",
]
