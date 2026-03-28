# Test Iteration History Dialog
"""
迭代历史记录对话框测试
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime


class TestIterationRecord:
    """测试 IterationRecord 数据类"""
    
    def test_create_record(self):
        """测试创建迭代记录"""
        from presentation.dialogs.iteration_history_dialog import IterationRecord
        
        record = IterationRecord(
            snapshot_id="snap_001",
            iteration_count=1,
            timestamp="2026-01-07 10:00:00",
            overall_score=85.5,
            status="completed",
            metrics_summary={"gain": 20.0, "bandwidth": 1e6},
            parameter_changes={"R1": "1k -> 2k"},
            llm_feedback="增益已达标",
        )
        
        assert record.snapshot_id == "snap_001"
        assert record.iteration_count == 1
        assert record.overall_score == 85.5
        assert record.status == "completed"
        assert "gain" in record.metrics_summary


class TestIterationHistoryDialog:
    """测试 IterationHistoryDialog"""
    
    @pytest.fixture
    def mock_snapshot_service(self):
        """模拟 snapshot_service"""
        with patch("presentation.dialogs.iteration_history_dialog.snapshot_service") as mock:
            yield mock
    
    @pytest.fixture
    def mock_undo_manager(self):
        """模拟 undo_manager"""
        with patch("presentation.dialogs.iteration_history_dialog.undo_manager") as mock:
            yield mock
    
    def test_dialog_creation(self, qtbot, mock_snapshot_service):
        """测试对话框创建"""
        mock_snapshot_service.list_snapshots.return_value = []
        
        from presentation.dialogs.iteration_history_dialog import IterationHistoryDialog
        
        dialog = IterationHistoryDialog()
        qtbot.addWidget(dialog)
        
        assert dialog is not None
        assert dialog._history_table is not None
        assert dialog._detail_text is not None
        assert dialog._restore_btn is not None
    
    def test_load_empty_history(self, qtbot, mock_snapshot_service):
        """测试加载空历史"""
        mock_snapshot_service.list_snapshots.return_value = []
        
        from presentation.dialogs.iteration_history_dialog import IterationHistoryDialog
        
        dialog = IterationHistoryDialog()
        qtbot.addWidget(dialog)
        
        dialog.load_history("/test/project")
        
        assert dialog._history_table.rowCount() == 0
        assert len(dialog._iterations) == 0
    
    def test_load_history_with_snapshots(self, qtbot, mock_snapshot_service):
        """测试加载有快照的历史"""
        # 创建模拟快照
        mock_snapshot = MagicMock()
        mock_snapshot.snapshot_id = "snap_001"
        mock_snapshot.iteration_count = 1
        mock_snapshot.timestamp = "2026-01-07T10:00:00"
        mock_snapshot.overall_score = 85.5
        mock_snapshot.metrics_summary = {"gain": 20.0}
        
        mock_snapshot_service.list_snapshots.return_value = [mock_snapshot]
        
        from presentation.dialogs.iteration_history_dialog import IterationHistoryDialog
        
        dialog = IterationHistoryDialog()
        qtbot.addWidget(dialog)
        
        dialog.load_history("/test/project")
        
        assert dialog._history_table.rowCount() == 1
        assert len(dialog._iterations) == 1
        assert dialog._iterations[0].snapshot_id == "snap_001"
    
    def test_retranslate_ui(self, qtbot, mock_snapshot_service):
        """测试国际化文本刷新"""
        mock_snapshot_service.list_snapshots.return_value = []
        
        from presentation.dialogs.iteration_history_dialog import IterationHistoryDialog
        
        dialog = IterationHistoryDialog()
        qtbot.addWidget(dialog)
        
        # 调用 retranslate_ui 不应抛出异常
        dialog.retranslate_ui()
        
        assert dialog._restore_btn.text() != ""
        assert dialog._close_btn.text() != ""


class TestSelectSimulationFileDialog:
    """测试 SelectSimulationFileDialog"""
    
    def test_dialog_creation(self, qtbot):
        """测试对话框创建"""
        from presentation.dialogs.select_simulation_file_dialog import SelectSimulationFileDialog
        
        dialog = SelectSimulationFileDialog()
        qtbot.addWidget(dialog)
        
        assert dialog is not None
        assert dialog._file_list is not None
        assert dialog._preview_text is not None
        assert dialog._filter_combo is not None
    
    def test_get_selected_file_none(self, qtbot):
        """测试未选择文件时返回 None"""
        from presentation.dialogs.select_simulation_file_dialog import SelectSimulationFileDialog
        
        dialog = SelectSimulationFileDialog()
        qtbot.addWidget(dialog)
        
        assert dialog.get_selected_file() is None
    
    def test_set_candidates(self, qtbot):
        """测试设置候选文件列表"""
        from presentation.dialogs.select_simulation_file_dialog import SelectSimulationFileDialog
        
        dialog = SelectSimulationFileDialog()
        qtbot.addWidget(dialog)
        
        candidates = ["/test/circuit1.cir", "/test/circuit2.cir"]
        dialog.set_candidates(candidates)
        
        assert dialog._is_degraded_mode is True
        assert len(dialog._files) == 2
        assert dialog._file_list.count() == 2
    
    def test_should_remember_selection(self, qtbot):
        """测试记住选择复选框"""
        from presentation.dialogs.select_simulation_file_dialog import SelectSimulationFileDialog
        
        dialog = SelectSimulationFileDialog()
        qtbot.addWidget(dialog)
        
        assert dialog.should_remember_selection() is False
        
        dialog._remember_checkbox.setChecked(True)
        assert dialog.should_remember_selection() is True
    
    def test_retranslate_ui(self, qtbot):
        """测试国际化文本刷新"""
        from presentation.dialogs.select_simulation_file_dialog import SelectSimulationFileDialog
        
        dialog = SelectSimulationFileDialog()
        qtbot.addWidget(dialog)
        
        # 调用 retranslate_ui 不应抛出异常
        dialog.retranslate_ui()
        
        assert dialog._run_btn.text() != ""
        assert dialog._cancel_btn.text() != ""
