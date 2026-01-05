# Undo Manager - Iteration-Level Undo Coordinator
"""
迭代级别撤回协调器

职责：
- 协调迭代级别的撤回操作
- 确保并发安全和状态一致性
- 复用 snapshot_service 的快照功能

架构说明：
- 本模块是协调器，不重复实现快照创建/恢复逻辑
- 快照存储：复用 domain/services/snapshot_service.py
- 迭代历史：复用 domain/services/iteration_history_service.py
- 本模块职责：协调任务取消、快照恢复、事件发布

撤销机制区分：
- 编辑器级别撤销（Ctrl+Z）：由 QPlainTextEdit 内置撤销栈实现
- 迭代级别撤回（本模块）：恢复到之前的迭代检查点，覆盖所有文件

被调用方：
- main_window.py（撤回按钮/菜单）
- history_dialog.py（历史对话框）

使用示例：
    from domain.design.undo_manager import undo_manager
    
    # 检查是否可以撤回
    if undo_manager.can_undo(project_root):
        # 获取撤回信息
        info = undo_manager.get_undo_info(project_root)
        print(f"将撤回到迭代 {info.target_iteration}")
        
        # 执行撤回
        result = await undo_manager.undo_to_previous(project_root)
        if result.success:
            print(f"已恢复到迭代 {result.restored_iteration}")
"""

import asyncio
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from domain.services import snapshot_service
from shared.event_types import (
    EVENT_STATE_ITERATION_UPDATED,
    EVENT_UNDO_COMPLETED,
    EVENT_UNDO_FAILED,
    EVENT_UNDO_STARTED,
)


# ============================================================
# 常量定义
# ============================================================

# 操作锁超时时间（秒）
LOCK_TIMEOUT_SECONDS = 30

# 任务取消等待时间（秒）
TASK_CANCEL_TIMEOUT_SECONDS = 10


# ============================================================
# 错误码枚举
# ============================================================

class UndoErrorCode(Enum):
    """撤回错误码"""
    NO_SNAPSHOTS = "no_snapshots"
    """没有可用的快照"""
    
    SNAPSHOT_NOT_FOUND = "snapshot_not_found"
    """指定的快照不存在"""
    
    OPERATION_IN_PROGRESS = "operation_in_progress"
    """已有操作正在进行"""
    
    LOCK_TIMEOUT = "lock_timeout"
    """获取锁超时"""
    
    RESTORE_FAILED = "restore_failed"
    """恢复快照失败"""
    
    TASK_CANCEL_FAILED = "task_cancel_failed"
    """取消任务失败"""


# ============================================================
# 数据类定义
# ============================================================

@dataclass
class UndoResult:
    """撤回操作结果"""
    
    success: bool
    """是否成功"""
    
    message: str
    """结果消息"""
    
    restored_iteration: int = 0
    """恢复到的迭代号（成功时）"""
    
    previous_iteration: int = 0
    """撤回前的迭代号"""
    
    error_code: Optional[UndoErrorCode] = None
    """错误码（失败时）"""
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "success": self.success,
            "message": self.message,
            "restored_iteration": self.restored_iteration,
            "previous_iteration": self.previous_iteration,
            "error_code": self.error_code.value if self.error_code else None,
        }


@dataclass
class UndoInfo:
    """撤回目标信息"""
    
    can_undo: bool
    """是否可以撤回"""
    
    target_iteration: int
    """目标迭代号"""
    
    target_timestamp: str
    """目标时间戳"""
    
    current_iteration: int
    """当前迭代号"""
    
    snapshot_count: int = 0
    """可用快照数量"""
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "can_undo": self.can_undo,
            "target_iteration": self.target_iteration,
            "target_timestamp": self.target_timestamp,
            "current_iteration": self.current_iteration,
            "snapshot_count": self.snapshot_count,
        }


# ============================================================
# UndoManager 类
# ============================================================

class UndoManager:
    """
    迭代级别撤回协调器
    
    协调任务取消、快照恢复、事件发布，确保并发安全。
    """
    
    def __init__(self):
        """初始化撤回管理器"""
        self._operation_lock = threading.RLock()
        self._operation_in_progress = False
        self._operation_start_time: Optional[datetime] = None
        
        # 延迟获取的服务
        self._event_bus = None
        self._async_task_registry = None
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
    def async_task_registry(self):
        """延迟获取 AsyncTaskRegistry"""
        if self._async_task_registry is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_ASYNC_TASK_REGISTRY
                self._async_task_registry = ServiceLocator.get_optional(
                    SVC_ASYNC_TASK_REGISTRY
                )
            except Exception:
                pass
        return self._async_task_registry
    
    @property
    def logger(self):
        """延迟获取 Logger"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("undo_manager")
            except Exception:
                pass
        return self._logger
    
    # ============================================================
    # 状态查询
    # ============================================================
    
    def is_operation_in_progress(self) -> bool:
        """检查是否有操作正在进行"""
        return self._operation_in_progress
    
    def can_undo(self, project_root: str) -> bool:
        """
        检查是否可以撤回
        
        Args:
            project_root: 项目根目录
            
        Returns:
            bool: 是否可以撤回
        """
        if self._operation_in_progress:
            return False
        
        # 需要至少 2 个快照才能撤回（当前 + 上一个）
        previous = snapshot_service.get_previous_snapshot(project_root)
        return previous is not None
    
    def get_undo_info(self, project_root: str) -> UndoInfo:
        """
        获取撤回目标信息
        
        Args:
            project_root: 项目根目录
            
        Returns:
            UndoInfo: 撤回目标信息
        """
        snapshots = snapshot_service.list_snapshots(project_root)
        regular_snapshots = [s for s in snapshots if not s.snapshot_id.startswith("_")]
        
        if len(regular_snapshots) < 2:
            return UndoInfo(
                can_undo=False,
                target_iteration=0,
                target_timestamp="",
                current_iteration=regular_snapshots[0].iteration_count if regular_snapshots else 0,
                snapshot_count=len(regular_snapshots),
            )
        
        # 最新的是当前迭代，第二新的是撤回目标
        current = regular_snapshots[0]
        target = regular_snapshots[1]
        
        return UndoInfo(
            can_undo=True,
            target_iteration=target.iteration_count,
            target_timestamp=target.timestamp,
            current_iteration=current.iteration_count,
            snapshot_count=len(regular_snapshots),
        )
    
    # ============================================================
    # 撤回操作
    # ============================================================
    
    async def undo_to_previous(self, project_root: str) -> UndoResult:
        """
        撤回到上一个迭代（线性撤回）
        
        Args:
            project_root: 项目根目录
            
        Returns:
            UndoResult: 撤回结果
        """
        previous = snapshot_service.get_previous_snapshot(project_root)
        
        if previous is None:
            return UndoResult(
                success=False,
                message="没有可用的快照进行撤回",
                error_code=UndoErrorCode.NO_SNAPSHOTS,
            )
        
        return await self.undo_to_iteration(project_root, previous.snapshot_id)
    
    async def undo_to_iteration(
        self,
        project_root: str,
        snapshot_id: str
    ) -> UndoResult:
        """
        撤回到指定迭代
        
        Args:
            project_root: 项目根目录
            snapshot_id: 目标快照 ID
            
        Returns:
            UndoResult: 撤回结果
        """
        # 获取当前迭代信息
        current_info = self.get_undo_info(project_root)
        current_iteration = current_info.current_iteration
        
        # 获取目标快照信息
        target_info = snapshot_service.get_snapshot_info(project_root, snapshot_id)
        if target_info is None:
            return UndoResult(
                success=False,
                message=f"快照不存在: {snapshot_id}",
                error_code=UndoErrorCode.SNAPSHOT_NOT_FOUND,
            )
        
        target_iteration = target_info.iteration_count
        
        # 尝试获取操作锁
        acquired = self._operation_lock.acquire(timeout=LOCK_TIMEOUT_SECONDS)
        if not acquired:
            return UndoResult(
                success=False,
                message="获取操作锁超时，请稍后重试",
                error_code=UndoErrorCode.LOCK_TIMEOUT,
            )
        
        try:
            # 检查是否已有操作在进行
            if self._operation_in_progress:
                return UndoResult(
                    success=False,
                    message="已有撤回操作正在进行",
                    error_code=UndoErrorCode.OPERATION_IN_PROGRESS,
                )
            
            # 标记操作开始
            self._operation_in_progress = True
            self._operation_start_time = datetime.now()
            
            # 发布撤回开始事件
            self._publish_event(EVENT_UNDO_STARTED, {
                "target_iteration": target_iteration,
                "current_iteration": current_iteration,
            })
            
            if self.logger:
                self.logger.info(
                    f"开始撤回: 从迭代 {current_iteration} 到迭代 {target_iteration}"
                )
            
            # 取消所有运行中的异步任务
            cancelled_count = await self._cancel_all_tasks()
            if self.logger:
                self.logger.debug(f"已取消 {cancelled_count} 个任务")
            
            # 恢复快照（使用异步方法）
            try:
                await snapshot_service.restore_snapshot_async(
                    project_root,
                    snapshot_id,
                    backup_current=True
                )
            except Exception as e:
                error_msg = f"恢复快照失败: {e}"
                if self.logger:
                    self.logger.error(error_msg)
                
                self._publish_event(EVENT_UNDO_FAILED, {
                    "error_code": UndoErrorCode.RESTORE_FAILED.value,
                    "error_message": error_msg,
                    "target_iteration": target_iteration,
                })
                
                return UndoResult(
                    success=False,
                    message=error_msg,
                    error_code=UndoErrorCode.RESTORE_FAILED,
                )
            
            # 删除当前迭代的快照（弹出栈顶）
            snapshot_service.pop_snapshot(project_root)
            
            # 发布撤回完成事件
            self._publish_event(EVENT_UNDO_COMPLETED, {
                "restored_iteration": target_iteration,
                "previous_iteration": current_iteration,
            })
            
            # 发布状态更新事件（触发 UI 刷新）
            self._publish_event(EVENT_STATE_ITERATION_UPDATED, {
                "iteration_count": target_iteration,
                "source": "undo",
            })
            
            if self.logger:
                self.logger.info(
                    f"撤回完成: 已恢复到迭代 {target_iteration}"
                )
            
            return UndoResult(
                success=True,
                message=f"已恢复到迭代 {target_iteration}",
                restored_iteration=target_iteration,
                previous_iteration=current_iteration,
            )
        
        finally:
            # 清除操作状态
            self._operation_in_progress = False
            self._operation_start_time = None
            self._operation_lock.release()
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    async def _cancel_all_tasks(self) -> int:
        """
        取消所有运行中的异步任务
        
        Returns:
            int: 取消的任务数量
        """
        if self.async_task_registry is None:
            return 0
        
        try:
            cancelled_count = self.async_task_registry.cancel_all()
            
            # 等待任务取消完成
            await asyncio.sleep(0.5)
            
            return cancelled_count
        except Exception as e:
            if self.logger:
                self.logger.warning(f"取消任务时出错: {e}")
            return 0
    
    def _publish_event(self, event_type: str, data: dict) -> None:
        """发布事件"""
        if self.event_bus is None:
            return
        
        try:
            self.event_bus.publish(event_type, data, source="undo_manager")
        except Exception as e:
            if self.logger:
                self.logger.warning(f"发布事件失败: {e}")


# ============================================================
# 模块级单例
# ============================================================

undo_manager = UndoManager()
"""模块级单例，便于直接导入使用"""


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "UndoManager",
    "UndoResult",
    "UndoInfo",
    "UndoErrorCode",
    "undo_manager",
]
