# test_diagnosis_panel.py
"""
DiagnosisPanel 单元测试

测试收敛诊断面板的功能
"""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field
from typing import List, Dict, Any


# Mock SuggestedFix
@dataclass
class MockSuggestedFix:
    """模拟 SuggestedFix"""
    description: str = "在节点 out 和地之间添加高阻电阻"
    action_type: str = "add_resistor"
    parameters: Dict[str, Any] = field(default_factory=lambda: {
        "node": "out",
        "ground": "0",
        "value": "1G",
        "spice_line": "R_leak_out out 0 1G",
    })
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "action_type": self.action_type,
            "parameters": self.parameters,
        }


# Mock ConvergenceDiagnosis
@dataclass
class MockConvergenceDiagnosis:
    """模拟 ConvergenceDiagnosis"""
    issue_type: str = "floating_node"
    severity: str = "high"
    summary: str = "浮空节点 (high)，涉及节点: out, bias"
    affected_nodes: List[str] = field(default_factory=lambda: ["out", "bias"])
    suggested_fixes: List[MockSuggestedFix] = field(default_factory=lambda: [
        MockSuggestedFix(),
        MockSuggestedFix(
            description="检查电路连接",
            action_type="check_circuit",
            parameters={"nodes": ["out", "bias"]},
        ),
    ])
    auto_fix_available: bool = False


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
def diagnosis_panel(qapp):
    """创建 DiagnosisPanel 实例"""
    from presentation.panels.simulation.diagnosis_panel import DiagnosisPanel
    
    panel = DiagnosisPanel()
    yield panel
    panel.close()


class TestDiagnosisPanel:
    """DiagnosisPanel 测试类"""
    
    def test_init(self, diagnosis_panel):
        """测试初始化"""
        assert diagnosis_panel is not None
        assert diagnosis_panel._diagnosis is None
        # 检查内部状态
        assert not diagnosis_panel._empty_widget.isHidden()
    
    def test_update_diagnosis_with_valid_result(self, diagnosis_panel):
        """测试更新有效的诊断结果"""
        diagnosis = MockConvergenceDiagnosis()
        
        diagnosis_panel.update_diagnosis(diagnosis)
        
        assert diagnosis_panel._diagnosis == diagnosis
        # 检查内部状态
        assert diagnosis_panel._empty_widget.isHidden()
        assert not diagnosis_panel._issue_card.isHidden()
        assert not diagnosis_panel._action_bar.isHidden()
    
    def test_update_diagnosis_with_none(self, diagnosis_panel):
        """测试更新 None 结果"""
        diagnosis_panel.update_diagnosis(None)
        
        assert diagnosis_panel._diagnosis is None
        # 检查内部状态
        assert not diagnosis_panel._empty_widget.isHidden()
    
    def test_auto_fix_button_disabled_when_unavailable(self, diagnosis_panel):
        """测试自动修复不可用时按钮禁用"""
        diagnosis = MockConvergenceDiagnosis(auto_fix_available=False)
        
        diagnosis_panel.update_diagnosis(diagnosis)
        
        assert not diagnosis_panel._auto_fix_btn.isEnabled()
    
    def test_auto_fix_button_enabled_when_available(self, diagnosis_panel):
        """测试自动修复可用时按钮启用"""
        diagnosis = MockConvergenceDiagnosis(auto_fix_available=True)
        
        diagnosis_panel.update_diagnosis(diagnosis)
        
        assert diagnosis_panel._auto_fix_btn.isEnabled()
    
    def test_clear(self, diagnosis_panel):
        """测试清空显示"""
        diagnosis = MockConvergenceDiagnosis()
        diagnosis_panel.update_diagnosis(diagnosis)
        
        diagnosis_panel.clear()
        
        assert diagnosis_panel._diagnosis is None
        # 检查内部状态
        assert not diagnosis_panel._empty_widget.isHidden()
    
    def test_auto_fix_signal(self, diagnosis_panel, qtbot):
        """测试自动修复信号"""
        from PyQt6.QtTest import QSignalSpy
        
        diagnosis = MockConvergenceDiagnosis(auto_fix_available=True)
        diagnosis_panel.update_diagnosis(diagnosis)
        
        spy = QSignalSpy(diagnosis_panel.auto_fix_requested)
        
        # 模拟点击自动修复按钮
        diagnosis_panel._auto_fix_btn.click()
        
        assert len(spy) == 1
    
    def test_manual_guide_signal(self, diagnosis_panel, qtbot):
        """测试手动修复指南信号"""
        from PyQt6.QtTest import QSignalSpy
        
        diagnosis = MockConvergenceDiagnosis()
        diagnosis_panel.update_diagnosis(diagnosis)
        
        spy = QSignalSpy(diagnosis_panel.manual_guide_requested)
        
        # 模拟点击手动修复按钮
        diagnosis_panel._manual_btn.click()
        
        assert len(spy) == 1
    
    def test_node_clicked_signal(self, diagnosis_panel, qtbot):
        """测试节点点击信号"""
        from PyQt6.QtTest import QSignalSpy
        
        diagnosis = MockConvergenceDiagnosis()
        diagnosis_panel.update_diagnosis(diagnosis)
        
        spy = QSignalSpy(diagnosis_panel.node_clicked)
        
        # 模拟点击节点
        diagnosis_panel._affected_nodes_panel.node_clicked.emit("out")
        
        assert len(spy) == 1
        assert spy[0][0] == "out"
    
    def test_retranslate_ui(self, diagnosis_panel):
        """测试国际化"""
        # 不应抛出异常
        diagnosis_panel.retranslate_ui()


class TestIssueTypeCard:
    """IssueTypeCard 测试类"""
    
    @pytest.fixture
    def issue_card(self, qapp):
        """创建 IssueTypeCard 实例"""
        from presentation.panels.simulation.diagnosis_panel import IssueTypeCard
        
        card = IssueTypeCard()
        yield card
        card.close()
    
    def test_set_issue_floating_node(self, issue_card):
        """测试设置浮空节点问题"""
        issue_card.set_issue("floating_node", "high", "浮空节点问题")
        
        assert issue_card._type_label.text() == "浮空节点"
        assert issue_card._severity_label.text() == "高"
        assert issue_card._icon_label.text() == "🔌"
    
    def test_set_issue_dc_convergence(self, issue_card):
        """测试设置 DC 收敛问题"""
        issue_card.set_issue("dc_convergence", "critical", "DC 收敛失败")
        
        assert issue_card._type_label.text() == "DC 工作点收敛失败"
        assert issue_card._severity_label.text() == "严重"
    
    def test_set_issue_tran_convergence(self, issue_card):
        """测试设置瞬态收敛问题"""
        issue_card.set_issue("tran_convergence", "medium", "")
        
        assert issue_card._type_label.text() == "瞬态分析收敛失败"
        assert issue_card._severity_label.text() == "中"
    
    def test_set_issue_unknown(self, issue_card):
        """测试设置未知问题"""
        issue_card.set_issue("unknown", "low", "")
        
        assert issue_card._type_label.text() == "未知问题"
        assert issue_card._severity_label.text() == "低"
    
    def test_clear(self, issue_card):
        """测试清空"""
        issue_card.set_issue("floating_node", "high", "test")
        issue_card.clear()
        
        assert issue_card._type_label.text() == ""


class TestAffectedNodesPanel:
    """AffectedNodesPanel 测试类"""
    
    @pytest.fixture
    def nodes_panel(self, qapp):
        """创建 AffectedNodesPanel 实例"""
        from presentation.panels.simulation.diagnosis_panel import AffectedNodesPanel
        
        panel = AffectedNodesPanel()
        yield panel
        panel.close()
    
    def test_set_nodes(self, nodes_panel):
        """测试设置节点列表"""
        nodes = ["out", "bias", "vdd"]
        nodes_panel.set_nodes(nodes)
        
        assert len(nodes_panel._node_labels) == 3
        assert not nodes_panel._empty_label.isVisible()
    
    def test_set_nodes_max_10(self, nodes_panel):
        """测试最多显示10个节点"""
        nodes = [f"node{i}" for i in range(15)]
        nodes_panel.set_nodes(nodes)
        
        # 10个节点 + 1个 "+5" 标签
        assert len(nodes_panel._node_labels) == 11
    
    def test_set_empty_nodes(self, nodes_panel):
        """测试设置空节点列表"""
        nodes_panel.set_nodes([])
        
        assert len(nodes_panel._node_labels) == 0
        # 检查内部状态
        assert not nodes_panel._empty_label.isHidden()
    
    def test_clear(self, nodes_panel):
        """测试清空"""
        nodes_panel.set_nodes(["out", "bias"])
        nodes_panel.clear()
        
        assert len(nodes_panel._node_labels) == 0
        # 检查内部状态
        assert not nodes_panel._empty_label.isHidden()


class TestSuggestedFixesPanel:
    """SuggestedFixesPanel 测试类"""
    
    @pytest.fixture
    def fixes_panel(self, qapp):
        """创建 SuggestedFixesPanel 实例"""
        from presentation.panels.simulation.diagnosis_panel import SuggestedFixesPanel
        
        panel = SuggestedFixesPanel()
        yield panel
        panel.close()
    
    def test_set_fixes_with_objects(self, fixes_panel):
        """测试设置修复建议（对象列表）"""
        fixes = [
            MockSuggestedFix(),
            MockSuggestedFix(description="检查电路", action_type="check"),
        ]
        fixes_panel.set_fixes(fixes)
        
        assert len(fixes_panel._fix_cards) == 2
        assert not fixes_panel._empty_label.isVisible()
    
    def test_set_fixes_with_dicts(self, fixes_panel):
        """测试设置修复建议（字典列表）"""
        fixes = [
            {"description": "修复1", "action_type": "fix1", "parameters": {}},
            {"description": "修复2", "action_type": "fix2", "parameters": {}},
        ]
        fixes_panel.set_fixes(fixes)
        
        assert len(fixes_panel._fix_cards) == 2
    
    def test_set_empty_fixes(self, fixes_panel):
        """测试设置空修复列表"""
        fixes_panel.set_fixes([])
        
        assert len(fixes_panel._fix_cards) == 0
        # 检查内部状态
        assert not fixes_panel._empty_label.isHidden()
    
    def test_clear(self, fixes_panel):
        """测试清空"""
        fixes_panel.set_fixes([MockSuggestedFix()])
        fixes_panel.clear()
        
        assert len(fixes_panel._fix_cards) == 0
        # 检查内部状态
        assert not fixes_panel._empty_label.isHidden()


class TestSuggestedFixCard:
    """SuggestedFixCard 测试类"""
    
    @pytest.fixture
    def fix_card(self, qapp):
        """创建 SuggestedFixCard 实例"""
        from presentation.panels.simulation.diagnosis_panel import SuggestedFixCard
        
        fix_data = {
            "description": "添加泄漏电阻",
            "action_type": "add_resistor",
            "parameters": {
                "spice_line": "R_leak out 0 1G",
            },
        }
        card = SuggestedFixCard(fix_data, 0)
        yield card
        card.close()
    
    def test_get_fix_data(self, fix_card):
        """测试获取修复数据"""
        data = fix_card.get_fix_data()
        
        assert data["description"] == "添加泄漏电阻"
        assert data["action_type"] == "add_resistor"
        assert "spice_line" in data["parameters"]
