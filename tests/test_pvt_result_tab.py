# test_pvt_result_tab.py - PVT Result Tab Tests
"""
PVT 角点分析结果标签页测试

测试内容：
- PVTResultTab 组件初始化
- 角点选择器功能
- 指标对比表格功能
- 角点详情面板功能
- 数据更新和导出
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


# ============================================================
# Mock 数据类
# ============================================================

class MockProcessCorner(Enum):
    """Mock 工艺角点枚举"""
    TYPICAL = "typical"
    FAST = "fast"
    SLOW = "slow"
    FAST_NMOS_SLOW_PMOS = "fs"
    SLOW_NMOS_FAST_PMOS = "sf"


@dataclass
class MockPVTCorner:
    """Mock PVT 角点配置"""
    name: str
    process: MockProcessCorner
    voltage_factor: float
    temperature: float
    description: str = ""


@dataclass
class MockSimulationResult:
    """Mock 仿真结果"""
    success: bool = True
    data: Any = None
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MockPVTCornerResult:
    """Mock 单个角点的仿真结果"""
    corner: MockPVTCorner
    simulation_result: MockSimulationResult
    metrics: Dict[str, Any] = field(default_factory=dict)
    passed: bool = True
    failed_goals: List[str] = field(default_factory=list)


@dataclass
class MockPVTAnalysisResult:
    """Mock PVT 分析完整结果"""
    circuit_file: str
    analysis_type: str
    corners: List[MockPVTCornerResult] = field(default_factory=list)
    all_passed: bool = True
    worst_corner: str = ""
    worst_metrics: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = "2026-01-07T10:00:00"
    duration_seconds: float = 0.0
    metrics_comparison: Dict[str, Dict[str, float]] = field(default_factory=dict)


def create_mock_pvt_result() -> MockPVTAnalysisResult:
    """创建 Mock PVT 分析结果"""
    corners = [
        MockPVTCornerResult(
            corner=MockPVTCorner(
                name="TT",
                process=MockProcessCorner.TYPICAL,
                voltage_factor=1.0,
                temperature=25.0,
                description="典型工艺、标称电压、室温",
            ),
            simulation_result=MockSimulationResult(success=True),
            metrics={"gain": 20.5, "bandwidth": 1e6, "phase_margin": 60.0},
            passed=True,
        ),
        MockPVTCornerResult(
            corner=MockPVTCorner(
                name="FF",
                process=MockProcessCorner.FAST,
                voltage_factor=1.1,
                temperature=-40.0,
                description="快速工艺、高电压、低温",
            ),
            simulation_result=MockSimulationResult(success=True),
            metrics={"gain": 22.0, "bandwidth": 1.2e6, "phase_margin": 55.0},
            passed=True,
        ),
        MockPVTCornerResult(
            corner=MockPVTCorner(
                name="SS",
                process=MockProcessCorner.SLOW,
                voltage_factor=0.9,
                temperature=85.0,
                description="慢速工艺、低电压、高温",
            ),
            simulation_result=MockSimulationResult(success=True),
            metrics={"gain": 18.0, "bandwidth": 0.8e6, "phase_margin": 65.0},
            passed=False,
            failed_goals=["gain >= 20 dB"],
        ),
    ]
    
    return MockPVTAnalysisResult(
        circuit_file="test.cir",
        analysis_type="ac",
        corners=corners,
        all_passed=False,
        worst_corner="SS",
        worst_metrics={"gain": 18.0},
        metrics_comparison={
            "gain": {"TT": 20.5, "FF": 22.0, "SS": 18.0},
            "bandwidth": {"TT": 1e6, "FF": 1.2e6, "SS": 0.8e6},
            "phase_margin": {"TT": 60.0, "FF": 55.0, "SS": 65.0},
        },
    )


# ============================================================
# 测试类
# ============================================================

class TestCornerSelectorBar:
    """角点选择器栏测试"""
    
    @pytest.fixture
    def qtbot_available(self):
        """检查 pytest-qt 是否可用"""
        try:
            from pytestqt.qtbot import QtBot
            return True
        except ImportError:
            return False
    
    def test_set_corners(self, qtbot_available):
        """测试设置角点列表"""
        if not qtbot_available:
            pytest.skip("pytest-qt not available")
        
        from PyQt6.QtWidgets import QApplication
        import sys
        
        app = QApplication.instance() or QApplication(sys.argv)
        
        from presentation.panels.simulation.pvt_result_tab import CornerSelectorBar
        
        selector = CornerSelectorBar()
        selector.set_corners(["TT", "FF", "SS"], worst_corner="SS")
        
        assert len(selector._corner_buttons) == 3
        assert "TT" in selector._corner_buttons
        assert "FF" in selector._corner_buttons
        assert "SS" in selector._corner_buttons
        assert selector._worst_corner == "SS"
    
    def test_set_status(self, qtbot_available):
        """测试设置状态摘要"""
        if not qtbot_available:
            pytest.skip("pytest-qt not available")
        
        from PyQt6.QtWidgets import QApplication
        import sys
        
        app = QApplication.instance() or QApplication(sys.argv)
        
        from presentation.panels.simulation.pvt_result_tab import CornerSelectorBar
        
        selector = CornerSelectorBar()
        selector.set_status(passed=2, total=3, all_passed=False)
        
        assert "2/3" in selector._status_label.text()


class TestMetricsComparisonTable:
    """指标对比表格测试"""
    
    @pytest.fixture
    def qtbot_available(self):
        """检查 pytest-qt 是否可用"""
        try:
            from pytestqt.qtbot import QtBot
            return True
        except ImportError:
            return False
    
    def test_set_data(self, qtbot_available):
        """测试设置表格数据"""
        if not qtbot_available:
            pytest.skip("pytest-qt not available")
        
        from PyQt6.QtWidgets import QApplication
        import sys
        
        app = QApplication.instance() or QApplication(sys.argv)
        
        from presentation.panels.simulation.pvt_result_tab import MetricsComparisonTable
        
        table = MetricsComparisonTable()
        
        corner_names = ["TT", "FF", "SS"]
        metrics_comparison = {
            "gain": {"TT": 20.5, "FF": 22.0, "SS": 18.0},
            "bandwidth": {"TT": 1e6, "FF": 1.2e6, "SS": 0.8e6},
        }
        
        table.set_data(
            corner_names=corner_names,
            metrics_comparison=metrics_comparison,
            worst_corner="SS",
        )
        
        assert table.rowCount() == 2
        assert table.columnCount() == 4  # 指标名 + 3个角点


class TestCornerDetailPanel:
    """角点详情面板测试"""
    
    @pytest.fixture
    def qtbot_available(self):
        """检查 pytest-qt 是否可用"""
        try:
            from pytestqt.qtbot import QtBot
            return True
        except ImportError:
            return False
    
    def test_set_corner_detail(self, qtbot_available):
        """测试设置角点详情"""
        if not qtbot_available:
            pytest.skip("pytest-qt not available")
        
        from PyQt6.QtWidgets import QApplication
        import sys
        
        app = QApplication.instance() or QApplication(sys.argv)
        
        from presentation.panels.simulation.pvt_result_tab import CornerDetailPanel
        
        panel = CornerDetailPanel()
        panel.set_corner_detail(
            corner_name="TT",
            process="typical",
            voltage_factor=1.0,
            temperature=25.0,
            description="典型角点",
            passed=True,
            failed_goals=[],
        )
        
        assert "TT" in panel._corner_name_label.text()
        assert "✓" in panel._status_icon.text()
    
    def test_set_corner_detail_failed(self, qtbot_available):
        """测试设置失败角点详情"""
        if not qtbot_available:
            pytest.skip("pytest-qt not available")
        
        from PyQt6.QtWidgets import QApplication
        import sys
        
        app = QApplication.instance() or QApplication(sys.argv)
        
        from presentation.panels.simulation.pvt_result_tab import CornerDetailPanel
        
        panel = CornerDetailPanel()
        panel.set_corner_detail(
            corner_name="SS",
            process="slow",
            voltage_factor=0.9,
            temperature=85.0,
            description="慢速角点",
            passed=False,
            failed_goals=["gain >= 20 dB"],
        )
        
        assert "SS" in panel._corner_name_label.text()
        assert "✗" in panel._status_icon.text()
        # 检查 failed_goals_group 不是隐藏状态（而非 isVisible，因为父组件未显示）
        assert not panel._failed_goals_group.isHidden()


class TestPVTResultTab:
    """PVT 结果标签页测试"""
    
    @pytest.fixture
    def qtbot_available(self):
        """检查 pytest-qt 是否可用"""
        try:
            from pytestqt.qtbot import QtBot
            return True
        except ImportError:
            return False
    
    def test_initialization(self, qtbot_available):
        """测试组件初始化"""
        if not qtbot_available:
            pytest.skip("pytest-qt not available")
        
        from PyQt6.QtWidgets import QApplication
        import sys
        
        app = QApplication.instance() or QApplication(sys.argv)
        
        from presentation.panels.simulation.pvt_result_tab import PVTResultTab
        
        tab = PVTResultTab()
        
        assert tab._pvt_result is None
        assert len(tab._corner_results) == 0
        # 检查 empty_widget 不是隐藏状态（而非 isVisible，因为父组件未显示）
        assert not tab._empty_widget.isHidden()
    
    def test_update_results(self, qtbot_available):
        """测试更新结果"""
        if not qtbot_available:
            pytest.skip("pytest-qt not available")
        
        from PyQt6.QtWidgets import QApplication
        import sys
        
        app = QApplication.instance() or QApplication(sys.argv)
        
        from presentation.panels.simulation.pvt_result_tab import PVTResultTab
        
        tab = PVTResultTab()
        mock_result = create_mock_pvt_result()
        
        tab.update_results(mock_result)
        
        assert tab._pvt_result is not None
        assert len(tab._corner_results) == 3
        # 检查 empty_widget 是隐藏状态
        assert tab._empty_widget.isHidden()
        # 检查 splitter 不是隐藏状态
        assert not tab._splitter.isHidden()
    
    def test_export_comparison(self, qtbot_available):
        """测试导出对比数据"""
        if not qtbot_available:
            pytest.skip("pytest-qt not available")
        
        from PyQt6.QtWidgets import QApplication
        import sys
        
        app = QApplication.instance() or QApplication(sys.argv)
        
        from presentation.panels.simulation.pvt_result_tab import PVTResultTab
        
        tab = PVTResultTab()
        mock_result = create_mock_pvt_result()
        
        tab.update_results(mock_result)
        export_data = tab.export_comparison()
        
        assert export_data["analysis_type"] == "pvt"
        assert export_data["worst_corner"] == "SS"
        assert len(export_data["corners"]) == 3
    
    def test_clear(self, qtbot_available):
        """测试清空显示"""
        if not qtbot_available:
            pytest.skip("pytest-qt not available")
        
        from PyQt6.QtWidgets import QApplication
        import sys
        
        app = QApplication.instance() or QApplication(sys.argv)
        
        from presentation.panels.simulation.pvt_result_tab import PVTResultTab
        
        tab = PVTResultTab()
        mock_result = create_mock_pvt_result()
        
        tab.update_results(mock_result)
        tab.clear()
        
        assert tab._pvt_result is None
        assert len(tab._corner_results) == 0
        # 检查 empty_widget 不是隐藏状态
        assert not tab._empty_widget.isHidden()


class TestEventIntegration:
    """事件集成测试"""
    
    def test_event_pv_complete_defined(self):
        """测试 EVENT_PVT_COMPLETE 事件已定义"""
        from shared.event_types import EVENT_PVT_COMPLETE
        
        assert EVENT_PVT_COMPLETE == "sim_pvt_complete"
    
    def test_event_pvt_corner_complete_defined(self):
        """测试 EVENT_PVT_CORNER_COMPLETE 事件已定义"""
        from shared.event_types import EVENT_PVT_CORNER_COMPLETE
        
        assert EVENT_PVT_CORNER_COMPLETE == "sim_pvt_corner_complete"


# ============================================================
# 运行测试
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
