# Stop Controller - Global Stop State Management
"""
停止控制器 - 全局停止状态管理

职责：
- 提供全局统一的停止状态管理
- 向当前活跃任务广播停止请求与停止完成信号
- 停止原因记录
- 停止超时保护（3.0.10）

设计原则：
- 线程安全：所有状态访问通过锁保护
- 单例模式：通过 ServiceLocator 注册和获取
- 即时响应：停止请求应在 500ms 内开始中断
- 优雅降级：停止时保存已生成的部分内容
- 超时保护：停止请求后最多等待 5 秒，超时后强制终止

停止链设计：
- StopController 是停止请求状态的唯一持有者
- ConversationViewModel 只负责发起停止请求和消费停止完成结果
- LLMExecutor 是对话停止的唯一收尾者，负责调用 complete_stop()

初始化顺序：
- Phase 3.3.1，依赖 Logger，注册到 ServiceLocator

"""

import threading
import time
from enum import Enum
from typing import Any, Dict, Optional

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
    
    Thread Safety:
        所有状态访问通过 _lock 保护，信号发送确保在主线程执行。
    
    超时保护（3.0.10）：
        停止请求后最多等待 5 秒，超时后强制终止并记录警告日志。
    """
    
    # 信号定义
    stop_requested = pyqtSignal(str, str)  # (task_id, reason)
    stop_completed = pyqtSignal(str, dict)  # (task_id, result)
    
    def __init__(self, parent: Optional[QObject] = None):
        """初始化停止控制器"""
        super().__init__(parent)
        
        # 状态属性
        self._state: StopState = StopState.IDLE
        self._stop_reason: Optional[StopReason] = None
        self._active_task_id: Optional[str] = None
        
        # 线程同步
        self._lock = threading.RLock()
        
        # 停止请求时间戳
        self._stop_requested_at: Optional[float] = None
        
        # 超时保护（3.0.10）
        self._timeout_timer: Optional[threading.Timer] = None
        self._force_stopped: bool = False
        self._logger = None
    
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
            if self._state == StopState.STOP_REQUESTED:
                if self.logger:
                    self.logger.warning(
                        f"Stop already requested or in progress, current state: {self._state.value}"
                    )
                return False
            
            if self._state != StopState.RUNNING:
                if self.logger:
                    self.logger.info("No active running task to stop")
                return False
            
            old_state = self._state
            self._state = StopState.STOP_REQUESTED
            self._stop_reason = reason
            self._stop_requested_at = time.time()
            self._force_stopped = False

            task_id = self._active_task_id or "unknown"
            
            if self.logger:
                self.logger.info(
                    f"Stop requested: task_id={task_id}, reason={reason.value}, "
                    f"old_state={old_state.value}"
                )
            
            # 启动超时保护定时器（3.0.10）
            self._start_timeout_timer(task_id)
        
        self._emit_stop_requested(task_id, reason.value)
        
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
            if self._state != StopState.STOP_REQUESTED:
                return
            
            self._force_stopped = True
            
            if self.logger:
                self.logger.warning(
                    f"Stop timeout after {STOP_TIMEOUT_SECONDS}s, forcing termination: "
                    f"task_id={task_id}"
                )
        
        self.complete_stop({
            "is_partial": True,
            "cleanup_success": False,
            "force_stopped": True,
            "timeout": True,
        })

    def complete_stop(self, result: Optional[Dict[str, Any]] = None) -> bool:
        """
        标记停止完成
        
        由执行器在确认当前任务已经停止后调用。
        
        Args:
            result: 停止结果，包含部分结果、清理状态等
            
        Returns:
            bool: 是否成功完成停止
        """
        with self._lock:
            self._cancel_timeout_timer()
            
            if self._state != StopState.STOP_REQUESTED:
                return False

            task_id = self._active_task_id or "unknown"
            reason = self._stop_reason.value if self._stop_reason else "unknown"

            duration_ms = 0.0
            if self._stop_requested_at:
                duration_ms = (time.time() - self._stop_requested_at) * 1000

            force_stopped = self._force_stopped

            self._state = StopState.IDLE
            self._stop_reason = None
            self._active_task_id = None
            self._stop_requested_at = None
            self._force_stopped = False

            if self.logger:
                self.logger.info(
                    f"Stop completed: task_id={task_id}, reason={reason}, "
                    f"duration={duration_ms:.0f}ms, force_stopped={force_stopped}"
                )

        stop_result = result or {}
        stop_result.update({
            "task_id": task_id,
            "reason": reason,
            "duration_ms": duration_ms,
            "is_partial": stop_result.get("is_partial", True),
            "cleanup_success": stop_result.get("cleanup_success", True),
            "force_stopped": force_stopped,
        })

        self._emit_stop_completed(task_id, stop_result)

        return True

    def reset(self) -> None:
        """
        重置状态为 IDLE

        在任务正常完成或异常结束后调用，准备接受新任务。
        """
        with self._lock:
            self._cancel_timeout_timer()

            self._state = StopState.IDLE
            self._stop_reason = None
            self._active_task_id = None
            self._stop_requested_at = None
            self._force_stopped = False

            if self.logger:
                self.logger.debug("StopController reset to idle")

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
            self._force_stopped = False

            if self.logger:
                self.logger.info(f"Task registered: task_id={task_id}")

        return True

    def is_stop_requested(self) -> bool:
        """
        检查是否已请求停止（线程安全）

        Returns:
            bool: True 表示已请求停止
        """
        with self._lock:
            return self._state == StopState.STOP_REQUESTED
    
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
    
    # 槽函数（用于跨线程信号发送）
    def _emit_stop_requested_slot(self, task_id: str, reason: str) -> None:
        """停止请求信号槽"""
        self.stop_requested.emit(task_id, reason)
    
    def _emit_stop_completed_slot(self, task_id: str, result: Dict[str, Any]) -> None:
        """停止完成信号槽"""
        self.stop_completed.emit(task_id, result)


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
