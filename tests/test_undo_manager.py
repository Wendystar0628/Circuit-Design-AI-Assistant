# Test Undo Manager
"""
迭代级别撤回协调器测试

测试内容：
- UndoInfo 数据类
- UndoResult 数据类
- can_undo 状态检查
- get_undo_info 信息获取
- undo_to_previous 线性撤回
- undo_to_iteration 指定撤回
- 并发安全机制
"""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from domain.design.undo_manager import (
    UndoErrorCode,
    UndoInfo,
    UndoManager,
    UndoResult,
)
from domain.services.snapshot_service import SnapshotInfo


# ============================================================
# 数据类测试
# ============================================================

class TestUndoResult:
    """UndoResult 数据类测试"""
    
    def test_success_result(self):
        """测试成功结果"""
        result = UndoResult(
            success=True,
            message="已恢复到迭代 5",
            restored_iteration=5,
            previous_iteration=6,
        )
        
        assert result.success is True
        assert result.restored_iteration == 5
        assert result.previous_iteration == 6
        assert result.error_code is None
    
    def test_failure_result(self):
        """测试失败结果"""
        result = UndoResult(
            success=False,
            message="没有可用的快照",
            error_code=UndoErrorCode.NO_SNAPSHOTS,
        )
        
        assert result.success is False
        assert result.error_code == UndoErrorCode.NO_SNAPSHOTS
    
    def test_to_dict(self):
        """测试转换为字典"""
        result = UndoResult(
            success=True,
            message="成功",
            restored_iteration=3,
            previous_iteration=4,
        )
        
        d = result.to_dict()
        assert d["success"] is True
        assert d["restored_iteration"] == 3
        assert d["error_code"] is None
    
    def test_to_dict_with_error(self):
        """测试带错误码的字典转换"""
        result = UndoResult(
            success=False,
            message="失败",
            error_code=UndoErrorCode.LOCK_TIMEOUT,
        )
        
        d = result.to_dict()
        assert d["error_code"] == "lock_timeout"


class TestUndoInfo:
    """UndoInfo 数据类测试"""
    
    def test_can_undo_true(self):
        """测试可以撤回的情况"""
        info = UndoInfo(
            can_undo=True,
            target_iteration=5,
            target_timestamp="2024-12-20T10:00:00",
            current_iteration=6,
            snapshot_count=3,
        )
        
        assert info.can_undo is True
        assert info.target_iteration == 5
        assert info.current_iteration == 6
    
    def test_can_undo_false(self):
        """测试不能撤回的情况"""
        info = UndoInfo(
            can_undo=False,
            target_iteration=0,
            target_timestamp="",
            current_iteration=1,
            snapshot_count=1,
        )
        
        assert info.can_undo is False
    
    def test_to_dict(self):
        """测试转换为字典"""
        info = UndoInfo(
            can_undo=True,
            target_iteration=2,
            target_timestamp="2024-12-20T10:00:00",
            current_iteration=3,
            snapshot_count=5,
        )
        
        d = info.to_dict()
        assert d["can_undo"] is True
        assert d["target_iteration"] == 2
        assert d["snapshot_count"] == 5


# ============================================================
# UndoManager 测试
# ============================================================

class TestUndoManager:
    """UndoManager 测试"""
    
    def test_is_operation_in_progress_initial(self):
        """测试初始状态无操作进行"""
        manager = UndoManager()
        assert manager.is_operation_in_progress() is False
    
    @patch("domain.design.undo_manager.snapshot_service")
    def test_can_undo_no_snapshots(self, mock_snapshot_service):
        """测试没有快照时不能撤回"""
        mock_snapshot_service.get_previous_snapshot.return_value = None
        
        manager = UndoManager()
        assert manager.can_undo("/test/project") is False
    
    @patch("domain.design.undo_manager.snapshot_service")
    def test_can_undo_with_snapshots(self, mock_snapshot_service):
        """测试有快照时可以撤回"""
        mock_snapshot_service.get_previous_snapshot.return_value = SnapshotInfo(
            snapshot_id="iter_001",
            timestamp="2024-12-20T10:00:00",
            size_bytes=1000,
            file_count=5,
            path="/test/.circuit_ai/snapshots/iter_001",
            iteration_count=1,
        )
        
        manager = UndoManager()
        assert manager.can_undo("/test/project") is True
    
    @patch("domain.design.undo_manager.snapshot_service")
    def test_get_undo_info_no_snapshots(self, mock_snapshot_service):
        """测试没有快照时的撤回信息"""
        mock_snapshot_service.list_snapshots.return_value = []
        
        manager = UndoManager()
        info = manager.get_undo_info("/test/project")
        
        assert info.can_undo is False
        assert info.snapshot_count == 0
    
    @patch("domain.design.undo_manager.snapshot_service")
    def test_get_undo_info_one_snapshot(self, mock_snapshot_service):
        """测试只有一个快照时的撤回信息"""
        mock_snapshot_service.list_snapshots.return_value = [
            SnapshotInfo(
                snapshot_id="iter_001",
                timestamp="2024-12-20T10:00:00",
                size_bytes=1000,
                file_count=5,
                path="/test/.circuit_ai/snapshots/iter_001",
                iteration_count=1,
            )
        ]
        
        manager = UndoManager()
        info = manager.get_undo_info("/test/project")
        
        assert info.can_undo is False
        assert info.current_iteration == 1
        assert info.snapshot_count == 1
    
    @patch("domain.design.undo_manager.snapshot_service")
    def test_get_undo_info_multiple_snapshots(self, mock_snapshot_service):
        """测试多个快照时的撤回信息"""
        mock_snapshot_service.list_snapshots.return_value = [
            SnapshotInfo(
                snapshot_id="iter_003",
                timestamp="2024-12-20T12:00:00",
                size_bytes=1000,
                file_count=5,
                path="/test/.circuit_ai/snapshots/iter_003",
                iteration_count=3,
            ),
            SnapshotInfo(
                snapshot_id="iter_002",
                timestamp="2024-12-20T11:00:00",
                size_bytes=1000,
                file_count=5,
                path="/test/.circuit_ai/snapshots/iter_002",
                iteration_count=2,
            ),
            SnapshotInfo(
                snapshot_id="iter_001",
                timestamp="2024-12-20T10:00:00",
                size_bytes=1000,
                file_count=5,
                path="/test/.circuit_ai/snapshots/iter_001",
                iteration_count=1,
            ),
        ]
        
        manager = UndoManager()
        info = manager.get_undo_info("/test/project")
        
        assert info.can_undo is True
        assert info.current_iteration == 3
        assert info.target_iteration == 2
        assert info.snapshot_count == 3


# ============================================================
# 异步撤回操作测试
# ============================================================

class TestUndoManagerAsync:
    """UndoManager 异步操作测试"""
    
    @patch("domain.design.undo_manager.snapshot_service")
    def test_undo_to_previous_no_snapshots(self, mock_snapshot_service):
        """测试没有快照时撤回失败"""
        mock_snapshot_service.get_previous_snapshot.return_value = None
        
        manager = UndoManager()
        result = asyncio.get_event_loop().run_until_complete(
            manager.undo_to_previous("/test/project")
        )
        
        assert result.success is False
        assert result.error_code == UndoErrorCode.NO_SNAPSHOTS
    
    @patch("domain.design.undo_manager.snapshot_service")
    def test_undo_to_iteration_not_found(self, mock_snapshot_service):
        """测试快照不存在时撤回失败"""
        mock_snapshot_service.list_snapshots.return_value = []
        mock_snapshot_service.get_snapshot_info.return_value = None
        
        manager = UndoManager()
        result = asyncio.get_event_loop().run_until_complete(
            manager.undo_to_iteration("/test/project", "nonexistent")
        )
        
        assert result.success is False
        assert result.error_code == UndoErrorCode.SNAPSHOT_NOT_FOUND
    
    @patch("domain.design.undo_manager.snapshot_service")
    def test_undo_to_iteration_success(self, mock_snapshot_service):
        """测试成功撤回"""
        # 设置 mock
        mock_snapshot_service.list_snapshots.return_value = [
            SnapshotInfo(
                snapshot_id="iter_002",
                timestamp="2024-12-20T11:00:00",
                size_bytes=1000,
                file_count=5,
                path="/test/.circuit_ai/snapshots/iter_002",
                iteration_count=2,
            ),
            SnapshotInfo(
                snapshot_id="iter_001",
                timestamp="2024-12-20T10:00:00",
                size_bytes=1000,
                file_count=5,
                path="/test/.circuit_ai/snapshots/iter_001",
                iteration_count=1,
            ),
        ]
        mock_snapshot_service.get_snapshot_info.return_value = SnapshotInfo(
            snapshot_id="iter_001",
            timestamp="2024-12-20T10:00:00",
            size_bytes=1000,
            file_count=5,
            path="/test/.circuit_ai/snapshots/iter_001",
            iteration_count=1,
        )
        mock_snapshot_service.restore_snapshot_async = AsyncMock(return_value=None)
        mock_snapshot_service.pop_snapshot.return_value = "iter_002"
        
        manager = UndoManager()
        result = asyncio.get_event_loop().run_until_complete(
            manager.undo_to_iteration("/test/project", "iter_001")
        )
        
        assert result.success is True
        assert result.restored_iteration == 1
        assert result.previous_iteration == 2
    
    @patch("domain.design.undo_manager.snapshot_service")
    def test_undo_restore_failed(self, mock_snapshot_service):
        """测试恢复快照失败"""
        mock_snapshot_service.list_snapshots.return_value = [
            SnapshotInfo(
                snapshot_id="iter_002",
                timestamp="2024-12-20T11:00:00",
                size_bytes=1000,
                file_count=5,
                path="/test/.circuit_ai/snapshots/iter_002",
                iteration_count=2,
            ),
        ]
        mock_snapshot_service.get_snapshot_info.return_value = SnapshotInfo(
            snapshot_id="iter_001",
            timestamp="2024-12-20T10:00:00",
            size_bytes=1000,
            file_count=5,
            path="/test/.circuit_ai/snapshots/iter_001",
            iteration_count=1,
        )
        
        mock_snapshot_service.restore_snapshot_async = AsyncMock(
            side_effect=RuntimeError("恢复失败")
        )
        
        manager = UndoManager()
        result = asyncio.get_event_loop().run_until_complete(
            manager.undo_to_iteration("/test/project", "iter_001")
        )
        
        assert result.success is False
        assert result.error_code == UndoErrorCode.RESTORE_FAILED


# ============================================================
# 并发安全测试
# ============================================================

class TestUndoManagerConcurrency:
    """UndoManager 并发安全测试"""
    
    def test_operation_lock_prevents_concurrent(self):
        """测试操作锁阻止并发"""
        manager = UndoManager()
        
        # 模拟操作进行中
        manager._operation_in_progress = True
        
        assert manager.can_undo("/test/project") is False
    
    @patch("domain.design.undo_manager.snapshot_service")
    def test_operation_flag_set_during_undo(self, mock_snapshot_service):
        """测试撤回期间操作标志被设置"""
        mock_snapshot_service.list_snapshots.return_value = [
            SnapshotInfo(
                snapshot_id="iter_002",
                timestamp="2024-12-20T11:00:00",
                size_bytes=1000,
                file_count=5,
                path="/test/.circuit_ai/snapshots/iter_002",
                iteration_count=2,
            ),
        ]
        mock_snapshot_service.get_snapshot_info.return_value = SnapshotInfo(
            snapshot_id="iter_001",
            timestamp="2024-12-20T10:00:00",
            size_bytes=1000,
            file_count=5,
            path="/test/.circuit_ai/snapshots/iter_001",
            iteration_count=1,
        )
        
        manager = UndoManager()
        operation_flag_during_restore = None
        
        async def capture_flag(*args, **kwargs):
            nonlocal operation_flag_during_restore
            operation_flag_during_restore = manager._operation_in_progress
        
        mock_snapshot_service.restore_snapshot_async = capture_flag
        mock_snapshot_service.pop_snapshot.return_value = "iter_002"
        
        asyncio.get_event_loop().run_until_complete(
            manager.undo_to_iteration("/test/project", "iter_001")
        )
        
        # 恢复期间标志应该为 True
        assert operation_flag_during_restore is True
        # 完成后标志应该为 False
        assert manager._operation_in_progress is False
