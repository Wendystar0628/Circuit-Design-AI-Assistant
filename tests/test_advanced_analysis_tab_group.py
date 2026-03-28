# test_advanced_analysis_tab_group.py
"""
高级分析标签页组测试

测试 AdvancedAnalysisTabGroup 的功能：
- 初始化和子标签页创建
- 标签页切换
- 事件订阅
- 国际化支持
"""

import pytest
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    """创建 QApplication 实例"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def mock_event_bus():
    """模拟 EventBus"""
    with patch("shared.service_locator.ServiceLocator.get_optional") as mock:
        event_bus = MagicMock()
        mock.return_value = event_bus
        yield event_bus


class TestAdvancedAnalysisTabGroup:
    """AdvancedAnalysisTabGroup 测试类"""
    
    def test_init(self, app):
        """测试初始化"""
        from presentation.panels.simulation.simulation_tab import AdvancedAnalysisTabGroup
        
        widget = AdvancedAnalysisTabGroup()
        
        assert widget is not None
        assert widget._tab_widget is not None
        assert widget._tab_widget.count() == 8
    
    def test_sub_tabs_exist(self, app):
        """测试所有子标签页存在"""
        from presentation.panels.simulation.simulation_tab import AdvancedAnalysisTabGroup
        
        widget = AdvancedAnalysisTabGroup()
        
        assert widget._pvt_tab is not None
        assert widget._monte_carlo_tab is not None
        assert widget._sweep_tab is not None
        assert widget._worst_case_tab is not None
        assert widget._sensitivity_tab is not None
        assert widget._fft_tab is not None
        assert widget._topology_tab is not None
        assert widget._diagnosis_tab is not None
    
    def test_switch_to_pvt(self, app):
        """测试切换到 PVT 标签页"""
        from presentation.panels.simulation.simulation_tab import AdvancedAnalysisTabGroup
        
        widget = AdvancedAnalysisTabGroup()
        widget.switch_to_pvt()
        
        assert widget._tab_widget.currentIndex() == widget.TAB_PVT
    
    def test_switch_to_monte_carlo(self, app):
        """测试切换到蒙特卡洛标签页"""
        from presentation.panels.simulation.simulation_tab import AdvancedAnalysisTabGroup
        
        widget = AdvancedAnalysisTabGroup()
        widget.switch_to_monte_carlo()
        
        assert widget._tab_widget.currentIndex() == widget.TAB_MONTE_CARLO
    
    def test_switch_to_sweep(self, app):
        """测试切换到参数扫描标签页"""
        from presentation.panels.simulation.simulation_tab import AdvancedAnalysisTabGroup
        
        widget = AdvancedAnalysisTabGroup()
        widget.switch_to_sweep()
        
        assert widget._tab_widget.currentIndex() == widget.TAB_SWEEP
    
    def test_switch_to_worst_case(self, app):
        """测试切换到最坏情况标签页"""
        from presentation.panels.simulation.simulation_tab import AdvancedAnalysisTabGroup
        
        widget = AdvancedAnalysisTabGroup()
        widget.switch_to_worst_case()
        
        assert widget._tab_widget.currentIndex() == widget.TAB_WORST_CASE
    
    def test_switch_to_sensitivity(self, app):
        """测试切换到敏感度标签页"""
        from presentation.panels.simulation.simulation_tab import AdvancedAnalysisTabGroup
        
        widget = AdvancedAnalysisTabGroup()
        widget.switch_to_sensitivity()
        
        assert widget._tab_widget.currentIndex() == widget.TAB_SENSITIVITY
    
    def test_switch_to_fft(self, app):
        """测试切换到 FFT 标签页"""
        from presentation.panels.simulation.simulation_tab import AdvancedAnalysisTabGroup
        
        widget = AdvancedAnalysisTabGroup()
        widget.switch_to_fft()
        
        assert widget._tab_widget.currentIndex() == widget.TAB_FFT
    
    def test_switch_to_topology(self, app):
        """测试切换到拓扑识别标签页"""
        from presentation.panels.simulation.simulation_tab import AdvancedAnalysisTabGroup
        
        widget = AdvancedAnalysisTabGroup()
        widget.switch_to_topology()
        
        assert widget._tab_widget.currentIndex() == widget.TAB_TOPOLOGY
    
    def test_switch_to_diagnosis(self, app):
        """测试切换到收敛诊断标签页"""
        from presentation.panels.simulation.simulation_tab import AdvancedAnalysisTabGroup
        
        widget = AdvancedAnalysisTabGroup()
        widget.switch_to_diagnosis()
        
        assert widget._tab_widget.currentIndex() == widget.TAB_DIAGNOSIS
    
    def test_properties(self, app):
        """测试属性访问"""
        from presentation.panels.simulation.simulation_tab import AdvancedAnalysisTabGroup
        
        widget = AdvancedAnalysisTabGroup()
        
        assert widget.pvt_tab is widget._pvt_tab
        assert widget.monte_carlo_tab is widget._monte_carlo_tab
        assert widget.sweep_tab is widget._sweep_tab
        assert widget.worst_case_tab is widget._worst_case_tab
        assert widget.sensitivity_tab is widget._sensitivity_tab
        assert widget.fft_tab is widget._fft_tab
        assert widget.topology_tab is widget._topology_tab
        assert widget.diagnosis_tab is widget._diagnosis_tab
    
    def test_retranslate_ui(self, app):
        """测试国际化"""
        from presentation.panels.simulation.simulation_tab import AdvancedAnalysisTabGroup
        
        widget = AdvancedAnalysisTabGroup()
        
        # 应该不抛出异常
        widget.retranslate_ui()
        
        # 验证标签页标题已设置
        assert widget._tab_widget.tabText(widget.TAB_PVT) != ""
        assert widget._tab_widget.tabText(widget.TAB_MONTE_CARLO) != ""


class TestChartViewerPanelAdvanced:
    """ChartViewerPanel 高级分析标签页测试"""
    
    def test_advanced_tab_exists(self, app):
        """测试高级分析标签页存在"""
        from presentation.panels.simulation.simulation_tab import ChartViewerPanel
        
        panel = ChartViewerPanel()
        
        assert panel.TAB_ADVANCED == 4
        assert panel._tab_widget.count() == 5
        assert panel._advanced_analysis_widget is not None
    
    def test_switch_to_advanced(self, app):
        """测试切换到高级分析标签页"""
        from presentation.panels.simulation.simulation_tab import ChartViewerPanel
        
        panel = ChartViewerPanel()
        panel.switch_to_advanced()
        
        assert panel._tab_widget.currentIndex() == panel.TAB_ADVANCED
    
    def test_advanced_property(self, app):
        """测试高级分析属性访问"""
        from presentation.panels.simulation.simulation_tab import ChartViewerPanel
        
        panel = ChartViewerPanel()
        
        assert panel.advanced_analysis is panel._advanced_analysis_widget
