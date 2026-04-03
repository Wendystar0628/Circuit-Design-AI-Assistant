# Test Sensitivity Analysis
"""
敏感度分析模块测试

测试内容：
- 数据类序列化/反序列化
- 敏感度计算方法
- 参数排序和关键参数识别
- 龙卷风图数据生成
- 优化建议生成
- LLM 上下文生成
- 报告生成
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from domain.simulation.analysis.sensitivity_analysis import (
    SensitivityAnalyzer,
    SensitivityParam,
    ParamSensitivityData,
    TornadoChartData,
    OptimizationSuggestion,
    SensitivityAnalysisResult,
    DEFAULT_PERTURBATION_PERCENT,
    CRITICAL_PARAM_THRESHOLD,
)
from domain.simulation.models.simulation_result import SimulationResult


# ============================================================
# 数据类测试
# ============================================================

class TestSensitivityParam:
    """SensitivityParam 数据类测试"""
    
    def test_create_param(self):
        """测试创建参数"""
        param = SensitivityParam(
            component="R1",
            param="resistance",
            nominal_value=10e3,
            unit="Ω",
        )
        
        assert param.component == "R1"
        assert param.param == "resistance"
        assert param.nominal_value == 10e3
        assert param.unit == "Ω"
        assert param.key == "R1.resistance"
    
    def test_to_dict(self):
        """测试序列化"""
        param = SensitivityParam(
            component="C1",
            param="capacitance",
            nominal_value=1e-9,
        )
        
        data = param.to_dict()
        
        assert data["component"] == "C1"
        assert data["param"] == "capacitance"
        assert data["nominal_value"] == 1e-9
        assert data["unit"] == ""
    
    def test_from_dict(self):
        """测试反序列化"""
        data = {
            "component": "L1",
            "param": "inductance",
            "nominal_value": 1e-6,
            "unit": "H",
        }
        
        param = SensitivityParam.from_dict(data)
        
        assert param.component == "L1"
        assert param.param == "inductance"
        assert param.nominal_value == 1e-6
        assert param.unit == "H"


class TestParamSensitivityData:
    """ParamSensitivityData 数据类测试"""
    
    def test_create_sensitivity_data(self):
        """测试创建敏感度数据"""
        sens = ParamSensitivityData(
            param_key="R1.resistance",
            nominal_value=10e3,
            absolute_sensitivity=0.5,
            relative_sensitivity=0.05,
            normalized_sensitivity=0.8,
            delta_plus=0.1,
            delta_minus=-0.08,
            direction="positive",
        )
        
        assert sens.param_key == "R1.resistance"
        assert sens.absolute_sensitivity == 0.5
        assert sens.direction == "positive"
    
    def test_to_dict_and_from_dict(self):
        """测试序列化和反序列化"""
        original = ParamSensitivityData(
            param_key="C1.capacitance",
            nominal_value=1e-9,
            absolute_sensitivity=1.2,
            relative_sensitivity=0.12,
            normalized_sensitivity=0.6,
            delta_plus=0.2,
            delta_minus=-0.15,
            direction="negative",
        )
        
        data = original.to_dict()
        restored = ParamSensitivityData.from_dict(data)
        
        assert restored.param_key == original.param_key
        assert restored.absolute_sensitivity == original.absolute_sensitivity
        assert restored.direction == original.direction


class TestTornadoChartData:
    """TornadoChartData 数据类测试"""
    
    def test_create_tornado_data(self):
        """测试创建龙卷风图数据"""
        tornado = TornadoChartData(
            param_names=["R1.resistance", "C1.capacitance"],
            positive_impacts=[0.1, 0.05],
            negative_impacts=[-0.08, -0.04],
            baseline_value=20.0,
            metric_name="gain",
        )
        
        assert len(tornado.param_names) == 2
        assert tornado.baseline_value == 20.0
        assert tornado.metric_name == "gain"
    
    def test_to_dict_and_from_dict(self):
        """测试序列化和反序列化"""
        original = TornadoChartData(
            param_names=["R1", "R2"],
            positive_impacts=[0.5, 0.3],
            negative_impacts=[-0.4, -0.25],
            baseline_value=10.0,
            metric_name="bandwidth",
        )
        
        data = original.to_dict()
        restored = TornadoChartData.from_dict(data)
        
        assert restored.param_names == original.param_names
        assert restored.positive_impacts == original.positive_impacts
        assert restored.baseline_value == original.baseline_value


class TestSensitivityAnalysisResult:
    """SensitivityAnalysisResult 数据类测试"""
    
    def test_create_result(self):
        """测试创建分析结果"""
        result = SensitivityAnalysisResult(
            circuit_file="test.cir",
            analysis_type="ac",
            metric_name="gain",
            nominal_value=20.0,
            perturbation_percent=1.0,
        )
        
        assert result.circuit_file == "test.cir"
        assert result.metric_name == "gain"
        assert result.success is True
    
    def test_get_display_summary_success(self):
        """测试成功时的显示摘要"""
        result = SensitivityAnalysisResult(
            circuit_file="test.cir",
            metric_name="gain",
            param_sensitivities=[
                ParamSensitivityData(param_key="R1", nominal_value=1e3),
                ParamSensitivityData(param_key="R2", nominal_value=2e3),
            ],
        )
        
        summary = result.get_display_summary()
        
        assert "敏感度分析完成" in summary
        assert "gain" in summary
        assert "2 个参数" in summary
    
    def test_get_display_summary_failure(self):
        """测试失败时的显示摘要"""
        result = SensitivityAnalysisResult(
            circuit_file="test.cir",
            success=False,
            error_message="仿真失败",
        )
        
        summary = result.get_display_summary()
        
        assert "失败" in summary
        assert "仿真失败" in summary
    
    def test_to_dict_and_from_dict(self):
        """测试序列化和反序列化"""
        original = SensitivityAnalysisResult(
            circuit_file="amplifier.cir",
            analysis_type="ac",
            metric_name="gain",
            nominal_value=25.0,
            perturbation_percent=2.0,
            param_sensitivities=[
                ParamSensitivityData(param_key="R1", nominal_value=1e3),
            ],
            critical_params=["R1"],
            simulation_count=3,
        )
        
        data = original.to_dict()
        restored = SensitivityAnalysisResult.from_dict(data)
        
        assert restored.circuit_file == original.circuit_file
        assert restored.metric_name == original.metric_name
        assert restored.nominal_value == original.nominal_value
        assert len(restored.param_sensitivities) == 1


# ============================================================
# SensitivityAnalyzer 测试
# ============================================================

class TestSensitivityAnalyzer:
    """SensitivityAnalyzer 类测试"""
    
    @pytest.fixture
    def mock_executor(self):
        """创建模拟执行器"""
        executor = Mock()
        return executor
    
    @pytest.fixture
    def analyzer(self, mock_executor):
        """创建分析器实例"""
        return SensitivityAnalyzer(executor=mock_executor)
    
    def test_calculate_sensitivity(self, analyzer):
        """测试敏感度计算"""
        # 参数从 10k 变到 10.1k（+1%），输出从 20 变到 20.5
        abs_sens, rel_sens = analyzer.calculate_sensitivity(
            param_nominal=10e3,
            output_nominal=20.0,
            output_perturbed=20.5,
            delta_param=100.0,  # 10k * 1%
        )
        
        # 绝对敏感度 = 0.5 / 100 = 0.005
        assert abs(abs_sens - 0.005) < 1e-6
        
        # 相对敏感度 = (0.5/20) / (100/10000) = 0.025 / 0.01 = 2.5
        assert abs(rel_sens - 2.5) < 1e-6
    
    def test_calculate_sensitivity_zero_delta(self, analyzer):
        """测试零变化量时的敏感度计算"""
        abs_sens, rel_sens = analyzer.calculate_sensitivity(
            param_nominal=10e3,
            output_nominal=20.0,
            output_perturbed=20.0,
            delta_param=0.0,
        )
        
        assert abs_sens == 0.0
        assert rel_sens == 0.0
    
    def test_rank_by_sensitivity(self, analyzer):
        """测试按敏感度排序"""
        sensitivities = [
            ParamSensitivityData(param_key="R1", normalized_sensitivity=0.3),
            ParamSensitivityData(param_key="R2", normalized_sensitivity=0.8),
            ParamSensitivityData(param_key="R3", normalized_sensitivity=0.5),
            ParamSensitivityData(param_key="R4", normalized_sensitivity=0.1),
        ]
        
        ranked = analyzer.rank_by_sensitivity(sensitivities, threshold=0.3)
        
        # 应该按降序排列，且只包含超过阈值的
        assert ranked == ["R2", "R3", "R1"]
    
    def test_rank_by_sensitivity_no_critical(self, analyzer):
        """测试无关键参数时返回前3个"""
        sensitivities = [
            ParamSensitivityData(param_key="R1", normalized_sensitivity=0.1),
            ParamSensitivityData(param_key="R2", normalized_sensitivity=0.2),
            ParamSensitivityData(param_key="R3", normalized_sensitivity=0.15),
            ParamSensitivityData(param_key="R4", normalized_sensitivity=0.05),
        ]
        
        ranked = analyzer.rank_by_sensitivity(sensitivities, threshold=0.5)
        
        # 无超过阈值的，返回前3个
        assert len(ranked) == 3
        assert ranked[0] == "R2"  # 最高
    
    def test_identify_critical_components(self, analyzer):
        """测试识别关键元件"""
        result = SensitivityAnalysisResult(
            circuit_file="test.cir",
            param_sensitivities=[
                ParamSensitivityData(param_key="R1.resistance", normalized_sensitivity=0.8),
                ParamSensitivityData(param_key="R1.tolerance", normalized_sensitivity=0.4),
                ParamSensitivityData(param_key="C1.capacitance", normalized_sensitivity=0.5),
                ParamSensitivityData(param_key="R2.resistance", normalized_sensitivity=0.1),
            ],
        )
        
        critical = analyzer.identify_critical_components(result, threshold=0.3)
        
        # R1 有两个参数超过阈值，C1 有一个
        assert "R1" in critical
        assert "C1" in critical
        assert "R2" not in critical
    
    def test_generate_tornado_chart_data(self, analyzer):
        """测试生成龙卷风图数据"""
        sensitivities = [
            ParamSensitivityData(param_key="R1", delta_plus=0.5, delta_minus=-0.4),
            ParamSensitivityData(param_key="R2", delta_plus=0.2, delta_minus=-0.15),
            ParamSensitivityData(param_key="R3", delta_plus=0.8, delta_minus=-0.7),
        ]
        
        tornado = analyzer.generate_tornado_chart_data(
            sensitivities, baseline_value=20.0, metric_name="gain", max_bars=2
        )
        
        # 应该按影响大小排序，只取前2个
        assert len(tornado.param_names) == 2
        assert tornado.param_names[0] == "R3"  # 最大影响
        assert tornado.param_names[1] == "R1"
        assert tornado.baseline_value == 20.0
        assert tornado.metric_name == "gain"
    
    def test_get_optimization_suggestions_increase(self, analyzer):
        """测试优化建议 - 需要增大"""
        result = SensitivityAnalysisResult(
            circuit_file="test.cir",
            metric_name="gain",
            nominal_value=15.0,  # 当前值低于目标
            param_sensitivities=[
                ParamSensitivityData(
                    param_key="R1",
                    normalized_sensitivity=0.8,
                    absolute_sensitivity=0.5,
                    direction="positive",
                ),
            ],
        )
        
        goals = {"gain": {"min": 20.0}}
        
        suggestions = analyzer.get_optimization_suggestions(result, goals)
        
        assert len(suggestions) == 1
        assert suggestions[0].param_key == "R1"
        assert suggestions[0].action == "increase"  # 正相关，需要增大输出，所以增大参数
    
    def test_get_optimization_suggestions_decrease(self, analyzer):
        """测试优化建议 - 需要减小"""
        result = SensitivityAnalysisResult(
            circuit_file="test.cir",
            metric_name="power",
            nominal_value=100.0,  # 当前值高于目标
            param_sensitivities=[
                ParamSensitivityData(
                    param_key="R1",
                    normalized_sensitivity=0.8,
                    absolute_sensitivity=0.5,
                    direction="positive",
                ),
            ],
        )
        
        goals = {"power": {"max": 50.0}}
        
        suggestions = analyzer.get_optimization_suggestions(result, goals)
        
        assert len(suggestions) == 1
        assert suggestions[0].action == "decrease"  # 正相关，需要减小输出，所以减小参数
    
    def test_get_optimization_suggestions_non_monotonic(self, analyzer):
        """测试优化建议 - 非单调参数"""
        result = SensitivityAnalysisResult(
            circuit_file="test.cir",
            metric_name="gain",
            nominal_value=15.0,
            param_sensitivities=[
                ParamSensitivityData(
                    param_key="R1",
                    normalized_sensitivity=0.8,
                    direction="non_monotonic",
                ),
            ],
        )
        
        goals = {"gain": {"min": 20.0}}
        
        suggestions = analyzer.get_optimization_suggestions(result, goals)
        
        assert len(suggestions) == 1
        assert suggestions[0].action == "fine_tune"
        assert "非单调" in suggestions[0].reason
    
    def test_get_optimization_suggestions_goal_met(self, analyzer):
        """测试优化建议 - 已满足目标"""
        result = SensitivityAnalysisResult(
            circuit_file="test.cir",
            metric_name="gain",
            nominal_value=25.0,  # 已满足目标
            param_sensitivities=[
                ParamSensitivityData(param_key="R1", normalized_sensitivity=0.8),
            ],
        )
        
        goals = {"gain": {"min": 20.0, "max": 30.0}}
        
        suggestions = analyzer.get_optimization_suggestions(result, goals)
        
        assert len(suggestions) == 0  # 已满足，无建议
    
    def test_generate_llm_context(self, analyzer):
        """测试生成 LLM 上下文"""
        result = SensitivityAnalysisResult(
            circuit_file="test.cir",
            metric_name="gain",
            nominal_value=20.0,
            perturbation_percent=1.0,
            param_sensitivities=[
                ParamSensitivityData(
                    param_key="R1.resistance",
                    relative_sensitivity=2.5,
                    direction="positive",
                ),
            ],
            critical_params=["R1.resistance"],
        )
        
        context = analyzer.generate_llm_context(result)
        
        assert "敏感度分析结果" in context
        assert "gain" in context
        assert "R1.resistance" in context
        assert "正相关" in context
    
    def test_generate_report(self, analyzer):
        """测试生成报告"""
        result = SensitivityAnalysisResult(
            circuit_file="amplifier.cir",
            analysis_type="ac",
            metric_name="gain",
            nominal_value=20.0,
            perturbation_percent=1.0,
            param_sensitivities=[
                ParamSensitivityData(
                    param_key="R1.resistance",
                    nominal_value=10e3,
                    absolute_sensitivity=0.5,
                    relative_sensitivity=2.5,
                    normalized_sensitivity=0.8,
                    delta_plus=0.1,
                    delta_minus=-0.08,
                    direction="positive",
                ),
            ],
            critical_params=["R1.resistance"],
            simulation_count=3,
            duration_seconds=5.5,
        )
        
        report = analyzer.generate_report(result)
        
        assert "敏感度分析报告" in report
        assert "amplifier.cir" in report
        assert "gain" in report
        assert "R1.resistance" in report
        assert "关键参数" in report
        assert "方法说明" in report


class TestSensitivityAnalyzerIntegration:
    """SensitivityAnalyzer 集成测试"""
    
    @pytest.fixture
    def mock_executor(self):
        """创建模拟执行器，返回预设结果"""
        executor = Mock()
        
        # 标称仿真结果
        nominal_result = SimulationResult(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            success=True,
            measurements=[
                {"name": "gain", "value": 20.0, "unit": "dB", "status": "OK"},
                {"name": "bandwidth", "value": 1e6, "unit": "Hz", "status": "OK"},
            ],
        )
        
        # +扰动结果
        plus_result = SimulationResult(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            success=True,
            measurements=[
                {"name": "gain", "value": 20.5, "unit": "dB", "status": "OK"},
                {"name": "bandwidth", "value": 0.95e6, "unit": "Hz", "status": "OK"},
            ],
        )
        
        # -扰动结果
        minus_result = SimulationResult(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            success=True,
            measurements=[
                {"name": "gain", "value": 19.6, "unit": "dB", "status": "OK"},
                {"name": "bandwidth", "value": 1.05e6, "unit": "Hz", "status": "OK"},
            ],
        )
        
        # 根据调用参数返回不同结果
        def execute_side_effect(circuit_file, config=None):
            if config and "sensitivity_params" in config:
                params = config["sensitivity_params"]
                # 简单判断：有参数修改就返回扰动结果
                param_value = list(params.values())[0]
                if param_value > 10e3:  # +扰动
                    return plus_result
                else:  # -扰动
                    return minus_result
            return nominal_result
        
        executor.execute = Mock(side_effect=execute_side_effect)
        return executor
    
    def test_run_sensitivity_full_flow(self, mock_executor):
        """测试完整敏感度分析流程"""
        analyzer = SensitivityAnalyzer(executor=mock_executor)
        
        params = [
            {"component": "R1", "param": "resistance", "nominal_value": 10e3},
        ]
        
        result = analyzer.run_sensitivity(
            circuit_file="test.cir",
            params=params,
            metric="gain",
            perturbation_percent=1.0,
        )
        
        assert result.success is True
        assert result.nominal_value == 20.0
        assert len(result.param_sensitivities) == 1
        assert result.simulation_count == 3  # 1 标称 + 2 扰动
        assert result.tornado_data is not None
        assert len(result.critical_params) > 0
    
    def test_run_sensitivity_with_callback(self, mock_executor):
        """测试带回调的敏感度分析"""
        analyzer = SensitivityAnalyzer(executor=mock_executor)
        
        progress_calls = []
        
        def on_progress(param_name, param_index, total_params, sensitivity):
            progress_calls.append({
                "param_name": param_name,
                "param_index": param_index,
                "total_params": total_params,
            })
        
        params = [
            {"component": "R1", "param": "resistance", "nominal_value": 10e3},
            {"component": "C1", "param": "capacitance", "nominal_value": 1e-9},
        ]
        
        # 为第二个参数添加不同的返回值
        call_count = [0]
        original_execute = mock_executor.execute
        
        def execute_with_count(circuit_file, config=None):
            call_count[0] += 1
            return original_execute(circuit_file, config)
        
        mock_executor.execute = execute_with_count
        
        result = analyzer.run_sensitivity(
            circuit_file="test.cir",
            params=params,
            metric="gain",
            on_progress=on_progress,
        )
        
        assert len(progress_calls) == 2
        assert progress_calls[0]["param_index"] == 0
        assert progress_calls[1]["param_index"] == 1
    
    def test_run_sensitivity_nominal_failure(self, mock_executor):
        """测试标称仿真失败"""
        mock_executor.execute = Mock(return_value=SimulationResult(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            success=False,
            error="仿真失败",
        ))
        
        analyzer = SensitivityAnalyzer(executor=mock_executor)
        
        params = [
            {"component": "R1", "param": "resistance", "nominal_value": 10e3},
        ]
        
        result = analyzer.run_sensitivity(
            circuit_file="test.cir",
            params=params,
            metric="gain",
        )
        
        assert result.success is False
        assert "标称仿真失败" in result.error_message
    
    def test_run_sensitivity_metric_not_found(self, mock_executor):
        """测试指标不存在"""
        mock_executor.execute = Mock(return_value=SimulationResult(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            success=True,
            measurements=[{"name": "other_metric", "value": 10.0, "status": "OK"}],
        ))
        
        analyzer = SensitivityAnalyzer(executor=mock_executor)
        
        params = [
            {"component": "R1", "param": "resistance", "nominal_value": 10e3},
        ]
        
        result = analyzer.run_sensitivity(
            circuit_file="test.cir",
            params=params,
            metric="gain",  # 不存在的指标
        )
        
        assert result.success is False
        assert "指标不存在" in result.error_message


# ============================================================
# 边界条件测试
# ============================================================

class TestEdgeCases:
    """边界条件测试"""
    
    def test_empty_params(self):
        """测试空参数列表"""
        executor = Mock()
        executor.execute = Mock(return_value=SimulationResult(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            success=True,
            measurements=[{"name": "gain", "value": 20.0, "unit": "dB", "status": "OK"}],
        ))
        
        analyzer = SensitivityAnalyzer(executor=executor)
        
        result = analyzer.run_sensitivity(
            circuit_file="test.cir",
            params=[],
            metric="gain",
        )
        
        assert result.success is True
        assert len(result.param_sensitivities) == 0
        assert result.simulation_count == 1  # 只有标称仿真
    
    def test_zero_nominal_value(self):
        """测试零标称值"""
        analyzer = SensitivityAnalyzer()
        
        # 零标称值时相对敏感度应为 0
        abs_sens, rel_sens = analyzer.calculate_sensitivity(
            param_nominal=0.0,
            output_nominal=20.0,
            output_perturbed=20.5,
            delta_param=100.0,
        )
        
        assert rel_sens == 0.0
    
    def test_zero_output_nominal(self):
        """测试零输出标称值"""
        analyzer = SensitivityAnalyzer()
        
        # 零输出标称值时相对敏感度应为 0
        abs_sens, rel_sens = analyzer.calculate_sensitivity(
            param_nominal=10e3,
            output_nominal=0.0,
            output_perturbed=0.5,
            delta_param=100.0,
        )
        
        assert rel_sens == 0.0
    
    def test_normalize_empty_list(self):
        """测试归一化空列表"""
        analyzer = SensitivityAnalyzer()
        
        sensitivities = []
        analyzer._normalize_sensitivities(sensitivities)
        
        # 不应抛出异常
        assert len(sensitivities) == 0
    
    def test_normalize_all_zero(self):
        """测试归一化全零敏感度"""
        analyzer = SensitivityAnalyzer()
        
        sensitivities = [
            ParamSensitivityData(param_key="R1", absolute_sensitivity=0.0),
            ParamSensitivityData(param_key="R2", absolute_sensitivity=0.0),
        ]
        
        analyzer._normalize_sensitivities(sensitivities)
        
        # 全零时归一化敏感度应保持为 0
        assert sensitivities[0].normalized_sensitivity == 0.0
        assert sensitivities[1].normalized_sensitivity == 0.0
