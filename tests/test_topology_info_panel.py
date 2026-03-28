# test_topology_info_panel.py
"""
TopologyInfoPanel 单元测试

测试拓扑识别信息面板的功能
"""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field
from typing import List


# Mock TopologyResult
@dataclass
class MockTopologyResult:
    """模拟 TopologyResult"""
    topology_type: str = "amplifier"
    sub_type: str = "common_source"
    confidence: float = 0.85
    recommended_analyses: List[str] = field(default_factory=lambda: ["ac", "tran", "noise"])
    key_metrics: List[str] = field(default_factory=lambda: ["gain", "bandwidth", "phase_margin"])
    critical_nodes: List[str] = field(default_factory=lambda: ["out", "in", "bias"])


@pytest.fixture
def qapp():
    """创建 Qt 应用实例"""
    from PyQt6.QtWidgets import QApplication
    import sys
    
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def topology_panel(qapp):
    """创建 TopologyInfoPanel 实例"""
    from presentation.panels.simulation.topology_info_panel import TopologyInfoPanel
    
    panel = TopologyInfoPanel()
    yield panel
    panel.close()


class TestTopologyInfoPanel:
    """TopologyInfoPanel 测试类"""
    
    def test_init(self, topology_panel):
        """测试初始化"""
        assert topology_panel is not None
        assert topology_panel._topology_result is None
    
    def test_update_topology_with_valid_result(self, topology_panel):
        """测试更新有效的拓扑结果"""
        result = MockTopologyResult()
        
        topology_panel.update_topology(result)
        
        assert topology_panel._topology_result == result
        # 检查内部状态而非 isVisible()，因为组件未显示时 isVisible() 总是返回 False
        assert topology_panel._empty_widget.isHidden()
        assert not topology_panel._type_card.isHidden()
    
    def test_update_topology_with_none(self, topology_panel):
        """测试更新 None 结果"""
        topology_panel.update_topology(None)
        
        assert topology_panel._topology_result is None
        # 检查内部状态
        assert not topology_panel._empty_widget.isHidden()
    
    def test_clear(self, topology_panel):
        """测试清空显示"""
        result = MockTopologyResult()
        topology_panel.update_topology(result)
        
        topology_panel.clear()
        
        assert topology_panel._topology_result is None
        # 检查内部状态
        assert not topology_panel._empty_widget.isHidden()
    
    def test_apply_config_signal(self, topology_panel, qtbot):
        """测试应用配置信号"""
        from PyQt6.QtTest import QSignalSpy
        
        result = MockTopologyResult()
        topology_panel.update_topology(result)
        
        spy = QSignalSpy(topology_panel.apply_config_requested)
        
        # 模拟点击应用按钮
        topology_panel._recommended_panel._on_apply_clicked()
        
        assert len(spy) == 1
        assert spy[0][0] == ["ac", "tran", "noise"]
    
    def test_node_clicked_signal(self, topology_panel, qtbot):
        """测试节点点击信号"""
        from PyQt6.QtTest import QSignalSpy
        
        result = MockTopologyResult()
        topology_panel.update_topology(result)
        
        spy = QSignalSpy(topology_panel.node_clicked)
        
        # 模拟点击节点
        topology_panel._critical_nodes_panel.node_clicked.emit("out")
        
        assert len(spy) == 1
        assert spy[0][0] == "out"
    
    def test_retranslate_ui(self, topology_panel):
        """测试国际化"""
        # 不应抛出异常
        topology_panel.retranslate_ui()


class TestTopologyTypeCard:
    """TopologyTypeCard 测试类"""
    
    @pytest.fixture
    def type_card(self, qapp):
        """创建 TopologyTypeCard 实例"""
        from presentation.panels.simulation.topology_info_panel import TopologyTypeCard
        
        card = TopologyTypeCard()
        yield card
        card.close()
    
    def test_set_topology_amplifier(self, type_card):
        """测试设置放大器拓扑"""
        type_card.set_topology("amplifier", "common_source", 0.9)
        
        assert type_card._type_label.text() == "放大器"
        assert type_card._subtype_label.text() == "Common Source"
        assert "90%" in type_card._confidence_label.text()
    
    def test_set_topology_filter(self, type_card):
        """测试设置滤波器拓扑"""
        type_card.set_topology("filter", "lowpass", 0.7)
        
        assert type_card._type_label.text() == "滤波器"
    
    def test_set_topology_unknown(self, type_card):
        """测试设置未知拓扑"""
        type_card.set_topology("unknown", "", 0.3)
        
        assert type_card._type_label.text() == "未知"
        assert not type_card._subtype_label.isVisible()
    
    def test_clear(self, type_card):
        """测试清空"""
        type_card.set_topology("amplifier", "common_source", 0.9)
        type_card.clear()
        
        assert type_card._type_label.text() == ""


class TestCriticalNodesPanel:
    """CriticalNodesPanel 测试类"""
    
    @pytest.fixture
    def nodes_panel(self, qapp):
        """创建 CriticalNodesPanel 实例"""
        from presentation.panels.simulation.topology_info_panel import CriticalNodesPanel
        
        panel = CriticalNodesPanel()
        yield panel
        panel.close()
    
    def test_set_nodes(self, nodes_panel):
        """测试设置节点列表"""
        nodes = ["out", "in", "bias"]
        nodes_panel.set_nodes(nodes)
        
        assert len(nodes_panel._node_labels) == 3
        assert not nodes_panel._empty_label.isVisible()
    
    def test_set_empty_nodes(self, nodes_panel):
        """测试设置空节点列表"""
        nodes_panel.set_nodes([])
        
        assert len(nodes_panel._node_labels) == 0
        # 检查内部状态
        assert not nodes_panel._empty_label.isHidden()
    
    def test_clear(self, nodes_panel):
        """测试清空"""
        nodes_panel.set_nodes(["out", "in"])
        nodes_panel.clear()
        
        assert len(nodes_panel._node_labels) == 0
        # 检查内部状态
        assert not nodes_panel._empty_label.isHidden()


class TestRecommendedAnalysesPanel:
    """RecommendedAnalysesPanel 测试类"""
    
    @pytest.fixture
    def analyses_panel(self, qapp):
        """创建 RecommendedAnalysesPanel 实例"""
        from presentation.panels.simulation.topology_info_panel import RecommendedAnalysesPanel
        
        panel = RecommendedAnalysesPanel()
        yield panel
        panel.close()
    
    def test_set_analyses(self, analyses_panel):
        """测试设置分析列表"""
        analyses = ["ac", "tran", "noise"]
        analyses_panel.set_analyses(analyses)
        
        assert len(analyses_panel._checkboxes) == 3
        assert analyses_panel._apply_btn.isEnabled()
    
    def test_get_selected_analyses(self, analyses_panel):
        """测试获取选中的分析"""
        analyses = ["ac", "tran", "noise"]
        analyses_panel.set_analyses(analyses)
        
        # 默认全选
        selected = analyses_panel.get_selected_analyses()
        assert set(selected) == set(analyses)
    
    def test_get_selected_analyses_partial(self, analyses_panel):
        """测试部分选中"""
        analyses = ["ac", "tran", "noise"]
        analyses_panel.set_analyses(analyses)
        
        # 取消选中 noise
        analyses_panel._checkboxes["noise"].setChecked(False)
        
        selected = analyses_panel.get_selected_analyses()
        assert set(selected) == {"ac", "tran"}
    
    def test_clear(self, analyses_panel):
        """测试清空"""
        analyses_panel.set_analyses(["ac", "tran"])
        analyses_panel.clear()
        
        assert len(analyses_panel._checkboxes) == 0
        assert not analyses_panel._apply_btn.isEnabled()


class TestKeyMetricsPanel:
    """KeyMetricsPanel 测试类"""
    
    @pytest.fixture
    def metrics_panel(self, qapp):
        """创建 KeyMetricsPanel 实例"""
        from presentation.panels.simulation.topology_info_panel import KeyMetricsPanel
        
        panel = KeyMetricsPanel()
        yield panel
        panel.close()
    
    def test_set_metrics(self, metrics_panel):
        """测试设置指标列表"""
        metrics = ["gain", "bandwidth", "phase_margin"]
        metrics_panel.set_metrics(metrics)
        
        assert len(metrics_panel._metric_labels) == 3
    
    def test_set_metrics_max_8(self, metrics_panel):
        """测试最多显示8个指标"""
        metrics = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9", "m10"]
        metrics_panel.set_metrics(metrics)
        
        assert len(metrics_panel._metric_labels) == 8
    
    def test_clear(self, metrics_panel):
        """测试清空"""
        metrics_panel.set_metrics(["gain", "bandwidth"])
        metrics_panel.clear()
        
        assert len(metrics_panel._metric_labels) == 0
