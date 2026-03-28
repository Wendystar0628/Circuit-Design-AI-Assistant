# Test Worst Case Analysis Module
"""
最坏情况分析模块测试

测试内容：
- ToleranceSpec 数据类
- WorstCaseMethod 枚举
- ParameterSensitivity 数据类
- WorstCaseAnalyzer 核心功能
- RSS 和 EVA 方法计算
"""

import pytest
from unittest.mock import Mock, patch

from domain.simulation.analysis.worst_case_analysis import (
    WorstCaseAnalyzer,
    WorstCaseMethod,
    ToleranceSpec,
    ParameterSensitivity,
    WorstCaseResult,
)
from domain.simulation.models.simulation_result import SimulationResult


# ============================================================
# WorstCaseMethod 枚举测试
# ============================================================

class TestWorstCaseMethod:
    """WorstCaseMethod 枚举测试"""
    
    def test_enum_values(self):
        """测试枚举值"""
        assert WorstCaseMethod.RSS.value == "rss"
        assert WorstCaseMethod.EVA.value == "eva"
    
    def test_enum_from_value(self):
        """测试从值创建枚举"""
        assert WorstCaseMethod("rss") == WorstCaseMethod.RSS
        assert WorstCaseMethod("eva") == WorstCaseMethod.EVA


# ============================================================
# ToleranceSpec 数据类测试
# ============================================================

class TestToleranceSpec:
    """ToleranceSpec 数据类测试"""
    
    def test_create_tolerance(self):
        """测试创建容差规格"""
        tol = ToleranceSpec(
            component="R1",
            param="resistance",
            tolerance_percent=5.0,
            nominal_value=1000.0,
        )
        
        assert tol.component == "R1"
        assert tol.param == "resistance"
        assert tol.tolerance_percent == 5.0
        assert tol.nominal_value == 1000.0
    
    def test_key_property(self):
        """测试参数键名"""
        tol = ToleranceSpec("R1", "resistance", 5.0)
        assert tol.key == "R1.resistance"
    
    def test_tolerance_factor(self):
        """测试容差因子"""
        tol = ToleranceSpec("R1", "resistance", 5.0)
        assert tol.tolerance_factor == 0.05
    
    def test_get_min_max_value(self):
        """测试最小最大值计算"""
        tol = ToleranceSpec("R1", "resistance", 10.0, nominal_value=1000.0)
        
        assert tol.get_min_value(1000.0) == 900.0
        assert tol.get_max_value(1000.0) == 1100.0
    
    def test_to_dict(self):
        """测试序列化"""
        tol = ToleranceSpec("R1", "resistance", 5.0, 1000.0)
        
        data = tol.to_dict()
        
        assert data["component"] == "R1"
        assert data["param"] == "resistance"
        assert data["tolerance_percent"] == 5.0
        assert data["nominal_value"] == 1000.0
    
    def test_from_dict(self):
        """测试反序列化"""
        data = {
            "component": "C1",
            "param": "capacitance",
            "tolerance_percent": 10.0,
            "nominal_value": 1e-9,
        }
        
        tol = ToleranceSpec.from_dict(data)
        
        assert tol.component == "C1"
        assert tol.tolerance_percent == 10.0


# ============================================================
# ParameterSensitivity 测试
# ============================================================

class TestParameterSensitivity:
    """ParameterSensitivity 测试"""
    
    def test_create_sensitivity(self):
        """测试创建敏感度数据"""
        sens = ParameterSensitivity(
            param_key="R1.resistance",
            delta_plus=2.0,
            delta_minus=-1.5,
            sensitivity_coefficient=0.035,
            influence_direction=1,
        )
        
        assert sens.param_key == "R1.resistance"
        assert sens.delta_plus == 2.0
        assert sens.delta_minus == -1.5
        assert sens.sensitivity_coefficient == 0.035
        assert sens.influence_direction == 1
    
    def test_to_dict(self):
        """测试序列化"""
        sens = ParameterSensitivity(
            param_key="R1.resistance",
            delta_plus=2.0,
            delta_minus=-1.5,
            sensitivity_coefficient=0.035,
            influence_direction=1,
        )
        
        data = sens.to_dict()
        
        assert data["param_key"] == "R1.resistance"
        assert data["delta_plus"] == 2.0


# ============================================================
# WorstCaseResult 测试
# ============================================================

class TestWorstCaseResult:
    """WorstCaseResult 测试"""
    
    def test_create_result(self):
        """测试创建结果"""
        result = WorstCaseResult(
            circuit_file="test.cir",
            analysis_type="ac",
            method=WorstCaseMethod.RSS,
            metric="gain",
            nominal_value=20.0,
            worst_case_max=22.0,
            worst_case_min=18.0,
        )
        
        assert result.circuit_file == "test.cir"
        assert result.method == WorstCaseMethod.RSS
        assert result.nominal_value == 20.0
        assert result.worst_case_max == 22.0
        assert result.worst_case_min == 18.0
    
    def test_to_dict(self):
        """测试序列化"""
        result = WorstCaseResult(
            circuit_file="test.cir",
            analysis_type="ac",
            method=WorstCaseMethod.EVA,
            metric="gain",
            nominal_value=20.0,
            design_margin_percent=10.0,
        )
        
        data = result.to_dict()
        
        assert data["circuit_file"] == "test.cir"
        assert data["method"] == "eva"
        assert data["design_margin_percent"] == 10.0


# ============================================================
# WorstCaseAnalyzer 测试
# ============================================================

class TestWorstCaseAnalyzer:
    """WorstCaseAnalyzer 测试"""
    
    def test_define_tolerance(self):
        """测试定义容差"""
        analyzer = WorstCaseAnalyzer()
        
        tol = analyzer.define_tolerance(
            component="R1",
            param="resistance",
            tolerance_percent=5.0,
            nominal_value=1000.0,
        )
        
        assert tol.component == "R1"
        assert tol.tolerance_percent == 5.0
        assert tol.nominal_value == 1000.0
    
    @patch('domain.simulation.analysis.worst_case_analysis.SpiceExecutor')
    def test_run_worst_case_rss(self, mock_executor_class):
        """测试 RSS 方法最坏情况分析"""
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor
        
        # 标称仿真结果
        nominal_result = Mock(spec=SimulationResult)
        nominal_result.success = True
        nominal_result.metrics = {"gain": 20.0}
        
        # +tolerance 结果
        plus_result = Mock(spec=SimulationResult)
        plus_result.success = True
        plus_result.metrics = {"gain": 21.0}  # +1
        
        # -tolerance 结果
        minus_result = Mock(spec=SimulationResult)
        minus_result.success = True
        minus_result.metrics = {"gain": 19.0}  # -1
        
        mock_executor.execute.side_effect = [
            nominal_result, plus_result, minus_result
        ]
        
        analyzer = WorstCaseAnalyzer(executor=mock_executor)
        
        tolerances = [
            analyzer.define_tolerance("R1", "resistance", 5.0, 1000.0),
        ]
        
        result = analyzer.run_worst_case(
            circuit_file="test.cir",
            tolerances=tolerances,
            method=WorstCaseMethod.RSS,
            metric="gain",
        )
        
        assert result.circuit_file == "test.cir"
        assert result.method == WorstCaseMethod.RSS
        assert result.nominal_value == 20.0
        assert result.simulation_count == 3  # 标称 + 2 * 1 参数
        assert len(result.sensitivities) == 1
    
    @patch('domain.simulation.analysis.worst_case_analysis.SpiceExecutor')
    def test_run_worst_case_eva(self, mock_executor_class):
        """测试 EVA 方法最坏情况分析"""
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor
        
        # 标称仿真结果
        nominal_result = Mock(spec=SimulationResult)
        nominal_result.success = True
        nominal_result.metrics = {"gain": 20.0}
        
        # +tolerance 结果
        plus_result = Mock(spec=SimulationResult)
        plus_result.success = True
        plus_result.metrics = {"gain": 22.0}
        
        # -tolerance 结果
        minus_result = Mock(spec=SimulationResult)
        minus_result.success = True
        minus_result.metrics = {"gain": 18.0}
        
        # EVA 最坏情况仿真结果
        eva_min_result = Mock(spec=SimulationResult)
        eva_min_result.success = True
        eva_min_result.metrics = {"gain": 17.0}
        
        eva_max_result = Mock(spec=SimulationResult)
        eva_max_result.success = True
        eva_max_result.metrics = {"gain": 23.0}
        
        mock_executor.execute.side_effect = [
            nominal_result, plus_result, minus_result,
            eva_min_result, eva_max_result
        ]
        
        analyzer = WorstCaseAnalyzer(executor=mock_executor)
        
        tolerances = [
            analyzer.define_tolerance("R1", "resistance", 5.0, 1000.0),
        ]
        
        result = analyzer.run_worst_case(
            circuit_file="test.cir",
            tolerances=tolerances,
            method=WorstCaseMethod.EVA,
            metric="gain",
        )
        
        assert result.method == WorstCaseMethod.EVA
        assert result.worst_combination is not None
    
    def test_calculate_design_margin_pass(self):
        """测试设计裕度计算 - 满足规格"""
        analyzer = WorstCaseAnalyzer()
        
        result = WorstCaseResult(
            circuit_file="test.cir",
            analysis_type="ac",
            method=WorstCaseMethod.RSS,
            metric="gain",
            nominal_value=20.0,
            worst_case_max=22.0,
            worst_case_min=18.0,
        )
        
        # 规格：gain >= 15
        margin = analyzer.calculate_design_margin(result, {"gain": {"min": 15.0}})
        
        # 裕度 = (18 - 15) / 20 * 100 = 15%
        assert margin == pytest.approx(15.0, rel=0.01)
    
    def test_calculate_design_margin_fail(self):
        """测试设计裕度计算 - 不满足规格"""
        analyzer = WorstCaseAnalyzer()
        
        result = WorstCaseResult(
            circuit_file="test.cir",
            analysis_type="ac",
            method=WorstCaseMethod.RSS,
            metric="gain",
            nominal_value=20.0,
            worst_case_max=22.0,
            worst_case_min=18.0,
        )
        
        # 规格：gain >= 19
        margin = analyzer.calculate_design_margin(result, {"gain": {"min": 19.0}})
        
        # 裕度 = (18 - 19) / 20 * 100 = -5%
        assert margin == pytest.approx(-5.0, rel=0.01)
    
    def test_get_worst_combination(self):
        """测试获取最坏参数组合"""
        analyzer = WorstCaseAnalyzer()
        
        result = WorstCaseResult(
            circuit_file="test.cir",
            analysis_type="ac",
            method=WorstCaseMethod.RSS,
            metric="gain",
        )
        
        result.sensitivities = [
            ParameterSensitivity("R1.resistance", delta_plus=2.0, delta_minus=-1.0),
            ParameterSensitivity("C1.capacitance", delta_plus=-1.0, delta_minus=1.5),
        ]
        
        # 最小化 gain
        combo = analyzer.get_worst_combination(result, "gain", minimize=True)
        
        # R1: delta_plus > delta_minus，所以取 min 使 gain 减小
        # C1: delta_minus > delta_plus，所以取 max 使 gain 减小
        assert combo["R1.resistance"] == "min"
        assert combo["C1.capacitance"] == "max"
    
    def test_generate_worst_case_report(self):
        """测试生成报告"""
        analyzer = WorstCaseAnalyzer()
        
        result = WorstCaseResult(
            circuit_file="amplifier.cir",
            analysis_type="ac",
            method=WorstCaseMethod.RSS,
            metric="gain",
            nominal_value=20.0,
            worst_case_max=22.0,
            worst_case_min=18.0,
            design_margin_percent=15.0,
            simulation_count=5,
            duration_seconds=2.5,
        )
        
        result.critical_params = ["R1.resistance", "C1.capacitance"]
        result.sensitivities = [
            ParameterSensitivity("R1.resistance", 1.0, -1.0, 0.02, 1),
            ParameterSensitivity("C1.capacitance", -0.5, 0.5, 0.01, -1),
        ]
        
        report = analyzer.generate_worst_case_report(result)
        
        assert "# 最坏情况分析报告" in report
        assert "amplifier.cir" in report
        assert "RSS" in report
        assert "gain" in report
        assert "20" in report
        assert "R1.resistance" in report
    
    def test_rss_calculation(self):
        """测试 RSS 计算逻辑"""
        analyzer = WorstCaseAnalyzer()
        
        sensitivities = [
            ParameterSensitivity("R1", delta_plus=3.0, delta_minus=-2.0),
            ParameterSensitivity("C1", delta_plus=4.0, delta_minus=-3.0),
        ]
        
        # RSS: sqrt(3^2 + 4^2) = 5
        wc_max, wc_min = analyzer._calculate_rss(20.0, sensitivities)
        
        assert wc_max == pytest.approx(25.0, rel=0.01)
        assert wc_min == pytest.approx(15.0, rel=0.01)


# ============================================================
# 集成测试
# ============================================================

class TestWorstCaseIntegration:
    """集成测试"""
    
    @patch('domain.simulation.analysis.worst_case_analysis.SpiceExecutor')
    def test_full_analysis_flow(self, mock_executor_class):
        """测试完整分析流程"""
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor
        
        # 设置仿真结果
        # R1 影响更大：delta = 2.0，C1 影响较小：delta = 0.5
        # 使用相同量级的标称值以便比较敏感度
        results = [
            Mock(success=True, metrics={"gain": 20.0}),  # 标称
            Mock(success=True, metrics={"gain": 22.0}),  # R1 +tol (+2)
            Mock(success=True, metrics={"gain": 18.0}),  # R1 -tol (-2)
            Mock(success=True, metrics={"gain": 20.5}),  # C1 +tol (+0.5)
            Mock(success=True, metrics={"gain": 19.5}),  # C1 -tol (-0.5)
        ]
        mock_executor.execute.side_effect = results
        
        analyzer = WorstCaseAnalyzer(executor=mock_executor)
        
        # 使用相同量级的标称值
        tolerances = [
            analyzer.define_tolerance("R1", "resistance", 5.0, 1000.0),
            analyzer.define_tolerance("C1", "capacitance", 5.0, 1000.0),  # 相同容差和标称值
        ]
        
        result = analyzer.run_worst_case(
            circuit_file="test.cir",
            tolerances=tolerances,
            method=WorstCaseMethod.RSS,
            metric="gain",
        )
        
        # 验证结果
        assert result.nominal_value == 20.0
        assert result.simulation_count == 5
        assert len(result.sensitivities) == 2
        assert len(result.critical_params) == 2
        
        # 验证敏感度排序（R1 影响更大，应该排在前面）
        # R1: delta=2.0, param_change=50, sens=0.04
        # C1: delta=0.5, param_change=50, sens=0.01
        assert result.critical_params[0] == "R1.resistance"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
