# Test GraphState - GraphState 测试
"""
测试 GraphState 和 SnapshotService

运行方式：
    cd circuit_design_ai
    python tests/test_graph_state.py
"""

import sys
import tempfile
import shutil
from pathlib import Path

# 添加项目根目录到 Python 路径
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from application.graph.state import (
    GraphState,
    create_initial_state,
    merge_state_update,
)
from application.snapshot_service import SnapshotService, SnapshotInfo


class TestGraphState:
    """测试 GraphState"""

    def test_create_initial_state(self):
        """测试创建初始状态"""
        state = create_initial_state(
            session_id="20231215_120000",
            project_root="/path/to/project",
        )

        assert state.session_id == "20231215_120000"
        assert state.project_root == "/path/to/project"
        assert state.current_node == "start"
        assert state.iteration_count == 0
        assert state.is_completed is False

    def test_default_values(self):
        """测试默认值"""
        state = GraphState()

        assert state.session_id == ""
        assert state.iteration_count == 0
        assert state.checkpoint_count == 0
        assert state.stagnation_count == 0
        assert state.design_goals_summary == {}
        assert state.last_metrics == {}

    def test_to_dict(self):
        """测试转换为字典"""
        state = GraphState(
            session_id="test_session",
            iteration_count=5,
            design_goals_summary={"gain": {"target": "20dB"}},
        )

        d = state.to_dict()

        assert d["session_id"] == "test_session"
        assert d["iteration_count"] == 5
        assert d["design_goals_summary"] == {"gain": {"target": "20dB"}}

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "session_id": "test_session",
            "iteration_count": 3,
            "circuit_file_path": "amplifier.cir",
        }

        state = GraphState.from_dict(data)

        assert state.session_id == "test_session"
        assert state.iteration_count == 3
        assert state.circuit_file_path == "amplifier.cir"

    def test_merge_state_update(self):
        """测试状态合并"""
        current = {
            "session_id": "test",
            "iteration_count": 1,
            "current_node": "node_a",
        }
        update = {
            "iteration_count": 2,
            "current_node": "node_b",
        }

        result = merge_state_update(current, update)

        assert result["session_id"] == "test"
        assert result["iteration_count"] == 2
        assert result["current_node"] == "node_b"

    def test_get_status_summary(self):
        """测试状态摘要"""
        state = GraphState(
            session_id="test",
            current_node="simulate",
            iteration_count=3,
        )

        summary = state.get_status_summary()

        assert "test" in summary
        assert "simulate" in summary
        assert "3" in summary


class TestSnapshotService:
    """测试 SnapshotService"""

    def test_create_and_list_snapshot(self):
        """测试创建和列出快照"""
        # 创建临时项目目录
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)

            # 创建一些测试文件
            (project_root / "test.cir").write_text("* Test circuit")
            (project_root / "params").mkdir()
            (project_root / "params" / "values.json").write_text("{}")

            # 创建 .circuit_ai 目录
            (project_root / ".circuit_ai").mkdir()
            (project_root / ".circuit_ai" / "snapshots").mkdir()

            # 创建快照服务
            service = SnapshotService(str(project_root))

            # 创建快照
            success, msg, snapshot_id = service.create_snapshot()

            assert success, f"创建快照失败: {msg}"
            assert snapshot_id is not None

            # 列出快照
            snapshots = service.list_snapshots()

            assert len(snapshots) >= 1
            assert snapshots[0].snapshot_id == snapshot_id

    def test_restore_snapshot(self):
        """测试恢复快照"""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)

            # 创建初始文件
            (project_root / "test.cir").write_text("* Version 1")
            (project_root / ".circuit_ai").mkdir()
            (project_root / ".circuit_ai" / "snapshots").mkdir()

            service = SnapshotService(str(project_root))

            # 创建快照
            success, msg, snapshot_id = service.create_snapshot()
            assert success

            # 修改文件
            (project_root / "test.cir").write_text("* Version 2")
            assert (project_root / "test.cir").read_text() == "* Version 2"

            # 恢复快照
            success, msg = service.restore_snapshot(snapshot_id, backup_current=False)
            assert success, f"恢复快照失败: {msg}"

            # 验证文件已恢复
            assert (project_root / "test.cir").read_text() == "* Version 1"

    def test_cleanup_old_snapshots(self):
        """测试清理旧快照"""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)

            (project_root / "test.cir").write_text("* Test")
            (project_root / ".circuit_ai").mkdir()
            (project_root / ".circuit_ai" / "snapshots").mkdir()

            service = SnapshotService(str(project_root))

            # 创建多个快照
            for i in range(5):
                service.create_snapshot(snapshot_id=f"snapshot_{i:03d}")

            # 验证有 5 个快照
            assert len(service.list_snapshots()) == 5

            # 清理，保留 2 个
            deleted_count, deleted_ids = service.cleanup_old_snapshots(keep_count=2)

            assert deleted_count == 3
            assert len(service.list_snapshots()) == 2

    def test_delete_snapshot(self):
        """测试删除快照"""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)

            (project_root / "test.cir").write_text("* Test")
            (project_root / ".circuit_ai").mkdir()
            (project_root / ".circuit_ai" / "snapshots").mkdir()

            service = SnapshotService(str(project_root))

            # 创建快照
            success, msg, snapshot_id = service.create_snapshot()
            assert success

            # 删除快照
            success, msg = service.delete_snapshot(snapshot_id)
            assert success

            # 验证已删除
            assert service.get_snapshot(snapshot_id) is None


def run_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Testing GraphState and SnapshotService")
    print("=" * 60)

    # GraphState 测试
    print("\n--- GraphState Tests ---")
    state_tests = TestGraphState()
    state_tests.test_create_initial_state()
    print("✓ test_create_initial_state")
    state_tests.test_default_values()
    print("✓ test_default_values")
    state_tests.test_to_dict()
    print("✓ test_to_dict")
    state_tests.test_from_dict()
    print("✓ test_from_dict")
    state_tests.test_merge_state_update()
    print("✓ test_merge_state_update")
    state_tests.test_get_status_summary()
    print("✓ test_get_status_summary")

    # SnapshotService 测试
    print("\n--- SnapshotService Tests ---")
    snapshot_tests = TestSnapshotService()
    snapshot_tests.test_create_and_list_snapshot()
    print("✓ test_create_and_list_snapshot")
    snapshot_tests.test_restore_snapshot()
    print("✓ test_restore_snapshot")
    snapshot_tests.test_cleanup_old_snapshots()
    print("✓ test_cleanup_old_snapshots")
    snapshot_tests.test_delete_snapshot()
    print("✓ test_delete_snapshot")

    print("\n" + "=" * 60)
    print("All tests passed! ✓")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
