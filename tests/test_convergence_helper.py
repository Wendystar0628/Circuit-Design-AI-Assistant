# Tests for ConvergenceHelper
"""
收敛诊断工具测试

测试内容：
- 问题类型识别
- 受影响节点提取
- 修复建议生成
- 网表连通性验证
"""

import pytest

from domain.simulation.helpers.convergence_helper import (
    ConvergenceHelper,
    convergence_helper,
    ISSUE_DC_CONVERGENCE,
    ISSUE_TRAN_CONVERGENCE,
    ISSUE_FLOATING_NODE,
    ISSUE_MODEL_PROBLEM,
    ISSUE_UNKNOWN,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
)


class TestConvergenceHelper:
    """ConvergenceHelper 测试类"""
    
    @pytest.fixture
    def helper(self):
        """创建测试用的 helper 实例"""
        return ConvergenceHelper()
    
    # ============================================================
    # 问题类型识别测试
    # ============================================================
    
    def test_identify_floating_node(self, helper):
        """测试浮空节点识别"""
        error_outputs = [
            "Error: node out is floating",
            "No DC path to ground for node vbias",
            "Warning: floating node detected at net1",
        ]
        
        for error in error_outputs:
            diagnosis = helper.diagnose_convergence_issue(error)
            assert diagnosis.issue_type == ISSUE_FLOATING_NODE

    def test_identify_dc_convergence(self, helper):
        """测试 DC 收敛问题识别"""
        error_outputs = [
            "DC analysis did not converge",
            "No convergence in DC operating point",
            "Error: singular matrix in DC analysis",
            "gmin stepping failed",
        ]
        
        for error in error_outputs:
            diagnosis = helper.diagnose_convergence_issue(error)
            assert diagnosis.issue_type == ISSUE_DC_CONVERGENCE
    
    def test_identify_tran_convergence(self, helper):
        """测试瞬态收敛问题识别"""
        error_outputs = [
            "Transient analysis failed to converge",
            "timestep too small",
            "time = 1.5e-6: convergence problem",
            "internal timestep limit exceeded",
        ]
        
        for error in error_outputs:
            diagnosis = helper.diagnose_convergence_issue(error)
            assert diagnosis.issue_type == ISSUE_TRAN_CONVERGENCE
    
    def test_identify_model_problem(self, helper):
        """测试模型问题识别"""
        error_outputs = [
            "model nmos not found",
            "Error: model pmos_3v3 undefined",
            "unknown model: opamp_ideal",
        ]
        
        for error in error_outputs:
            diagnosis = helper.diagnose_convergence_issue(error)
            assert diagnosis.issue_type == ISSUE_MODEL_PROBLEM
    
    def test_identify_unknown_issue(self, helper):
        """测试未知问题识别"""
        diagnosis = helper.diagnose_convergence_issue("Some random error message")
        assert diagnosis.issue_type == ISSUE_UNKNOWN
    
    # ============================================================
    # 节点提取测试
    # ============================================================
    
    def test_extract_affected_nodes(self, helper):
        """测试受影响节点提取"""
        error = "Error: node out is floating. Also node vbias has no DC path."
        diagnosis = helper.diagnose_convergence_issue(error)
        
        assert "out" in diagnosis.affected_nodes
        assert "vbias" in diagnosis.affected_nodes

    # ============================================================
    # 修复建议测试
    # ============================================================
    
    def test_fixes_for_floating_node(self, helper):
        """测试浮空节点修复建议"""
        error = "Error: node out is floating"
        diagnosis = helper.diagnose_convergence_issue(error)
        
        assert len(diagnosis.suggested_fixes) > 0
        
        # 应该有添加电阻的建议
        resistor_fix = next(
            (f for f in diagnosis.suggested_fixes if f.action_type == "add_resistor"),
            None
        )
        assert resistor_fix is not None
        assert "out" in resistor_fix.parameters.get("node", "")
    
    def test_fixes_for_dc_convergence(self, helper):
        """测试 DC 收敛问题修复建议"""
        error = "DC analysis did not converge"
        diagnosis = helper.diagnose_convergence_issue(error)
        
        assert len(diagnosis.suggested_fixes) > 0
        
        # 应该有调整参数的建议
        param_fix = next(
            (f for f in diagnosis.suggested_fixes if f.action_type == "adjust_param"),
            None
        )
        assert param_fix is not None
    
    def test_fixes_for_tran_convergence(self, helper):
        """测试瞬态收敛问题修复建议"""
        error = "timestep too small"
        diagnosis = helper.diagnose_convergence_issue(error)
        
        assert len(diagnosis.suggested_fixes) > 0
        
        # 应该有减小时间步长的建议
        timestep_fix = next(
            (f for f in diagnosis.suggested_fixes if f.action_type == "reduce_timestep"),
            None
        )
        assert timestep_fix is not None
    
    # ============================================================
    # 严重程度测试
    # ============================================================
    
    def test_severity_for_floating_node(self, helper):
        """测试浮空节点严重程度"""
        # 少量节点
        error = "Error: node out is floating"
        diagnosis = helper.diagnose_convergence_issue(error)
        assert diagnosis.severity == SEVERITY_MEDIUM
    
    def test_severity_for_dc_convergence(self, helper):
        """测试 DC 收敛问题严重程度"""
        error = "DC analysis did not converge"
        diagnosis = helper.diagnose_convergence_issue(error)
        assert diagnosis.severity == SEVERITY_HIGH

    # ============================================================
    # 初始条件建议测试
    # ============================================================
    
    def test_suggest_initial_conditions(self, helper):
        """测试初始条件建议"""
        netlist = """
        * Test circuit
        Vdd vdd 0 3.3
        C1 out 0 1p
        C2 vbias 0 100f
        """
        
        suggestions = helper.suggest_initial_conditions(netlist, ["out", "vbias"])
        
        assert len(suggestions) == 2
        assert any(".ic V(out)" in s for s in suggestions)
        assert any(".ic V(vbias)" in s for s in suggestions)
    
    # ============================================================
    # 网表连通性验证测试
    # ============================================================
    
    def test_validate_netlist_with_ground(self, helper):
        """测试有地节点的网表"""
        netlist = """
        * Test circuit
        Vdd vdd 0 3.3
        R1 vdd out 1k
        """
        
        issues = helper.validate_netlist_connectivity(netlist)
        assert not any("地节点" in issue for issue in issues)
    
    def test_validate_netlist_without_ground(self, helper):
        """测试无地节点的网表"""
        netlist = """
        * Test circuit
        R1 a b 1k
        """
        
        issues = helper.validate_netlist_connectivity(netlist)
        assert any("地节点" in issue for issue in issues)
    
    def test_validate_netlist_without_source(self, helper):
        """测试无电源的网表"""
        netlist = """
        * Test circuit
        R1 a 0 1k
        """
        
        issues = helper.validate_netlist_connectivity(netlist)
        assert any("电源" in issue for issue in issues)
    
    # ============================================================
    # 收敛参数建议测试
    # ============================================================
    
    def test_convergence_param_suggestions_dc(self, helper):
        """测试 DC 收敛参数建议"""
        suggestions = helper.get_convergence_param_suggestions(ISSUE_DC_CONVERGENCE)
        
        assert "gmin" in suggestions
        assert "reltol" in suggestions
        assert suggestions["gmin"] > 1e-12  # 应该比默认值大
    
    def test_convergence_param_suggestions_tran(self, helper):
        """测试瞬态收敛参数建议"""
        suggestions = helper.get_convergence_param_suggestions(ISSUE_TRAN_CONVERGENCE)
        
        assert "reltol" in suggestions
        assert "itl4" in suggestions


class TestModuleSingleton:
    """模块级单例测试"""
    
    def test_singleton_exists(self):
        """测试单例存在"""
        assert convergence_helper is not None
        assert isinstance(convergence_helper, ConvergenceHelper)
    
    def test_singleton_works(self):
        """测试单例功能正常"""
        diagnosis = convergence_helper.diagnose_convergence_issue(
            "DC analysis did not converge"
        )
        assert diagnosis.issue_type == ISSUE_DC_CONVERGENCE


class TestDiagnosisResult:
    """诊断结果测试"""
    
    def test_diagnosis_has_required_fields(self):
        """测试诊断结果包含必要字段"""
        diagnosis = convergence_helper.diagnose_convergence_issue(
            "Error: node out is floating"
        )
        
        assert diagnosis.analysis_type == "convergence_diagnosis"
        assert diagnosis.timestamp is not None
        assert diagnosis.success is True
        assert diagnosis.issue_type is not None
        assert diagnosis.severity is not None
        assert diagnosis.suggested_fixes is not None
        assert diagnosis.auto_fix_available is False  # 不支持自动修复
    
    def test_diagnosis_summary(self):
        """测试诊断摘要"""
        diagnosis = convergence_helper.diagnose_convergence_issue(
            "DC analysis did not converge"
        )
        
        assert diagnosis.summary is not None
        assert len(diagnosis.summary) > 0
        assert "DC" in diagnosis.summary or "收敛" in diagnosis.summary
