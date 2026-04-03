# Test Parametric Sweep Analysis Module
"""
参数扫描分析模块测试

测试内容：
- SweepParameter 数据类
- SweepType 枚举
- NestedSweepConfig 配置
- ParametricSweepAnalyzer 核心功能
- 曲线和等高线数据生成
"""

import pytest
from unittest.mock import Mock, patch

from domain.simulation.analysis.parametric_sweep import (
    ParametricSweepAnalyzer,
    SweepParameter,
    SweepType,
    NestedSweepConfig,
    SweepPointResult,
    SweepAnalysisResult,
    MAX_NESTED_DEPTH,
)
from domain.simulation.models.simulation_result import SimulationResult


# ============================================================
# SweepType 枚举测试
# ============================================================

class TestSweepType:
    """SweepType 枚举测试"""
    
    def test_enum_values(self):
        """测试枚举值"""
        assert SweepType.LINEAR.value == "linear"
        assert SweepType.LOG.value == "log"
        assert SweepType.LIST.value == "list"
    
    def test_enum_from_value(self):
        """测试从值创建枚举"""
        assert SweepType("linear") == SweepType.LINEAR
        assert SweepType("log") == SweepType.LOG
        assert SweepType("list") == SweepType.LIST


# ============================================================
# SweepParameter 数据类测试
# ============================================================

class TestSweepParameter:
    """SweepParameter 数据类测试"""
    
    def test_create_linear_sweep(self):
        """测试创建线性扫描参数"""
        param = SweepParameter(
            component="R1",
            param="resistance",
            sweep_type=SweepType.LINEAR,
            start=1000.0,
            stop=10000.0,
            step=1000.0,
        )
        
        assert param.component == "R1"
        assert param.param == "resistance"
        assert param.sweep_type == SweepType.LINEAR
        assert param.start == 1000.0
        assert param.stop == 10000.0
        assert param.step == 1000.0
    
    def test_get_sweep_values_linear(self):
        """测试线性扫描值生成"""
        param = SweepParameter(
            component="R1",
            param="resistance",
            sweep_type=SweepType.LINEAR,
            start=1.0,
            stop=5.0,
            step=1.0,
        )
        
        values = param.get_sweep_values()
        
        assert len(values) == 5
        assert values[0] == 1.0
        assert values[-1] == 5.0
    
    def test_get_sweep_values_log(self):
        """测试对数扫描值生成"""
        param = SweepParameter(
            component="C1",
            param="capacitance",
            sweep_type=SweepType.LOG,
            start=1e-9,
            stop=1e-6,
            step=4,  # 4 个点
        )
        
        values = param.get_sweep_values()
        
        assert len(values) == 4
        assert values[0] == pytest.approx(1e-9, rel=1e-6)
        assert values[-1] == pytest.approx(1e-6, rel=1e-6)
    
    def test_get_sweep_values_list(self):
        """测试列表扫描值"""
        param = SweepParameter(
            component="R1",
            param="resistance",
            sweep_type=SweepType.LIST,
            values=[100.0, 470.0, 1000.0, 4700.0, 10000.0],
        )
        
        values = param.get_sweep_values()
        
        assert len(values) == 5
        assert values == [100.0, 470.0, 1000.0, 4700.0, 10000.0]
    
    def test_num_points(self):
        """测试扫描点数计算"""
        param = SweepParameter(
            component="R1",
            param="resistance",
            sweep_type=SweepType.LINEAR,
            start=1.0,
            stop=10.0,
            step=1.0,
        )
        
        assert param.num_points == 10
    
    def test_key_property(self):
        """测试参数键名"""
        param = SweepParameter(
            component="R1",
            param="resistance",
            sweep_type=SweepType.LINEAR,
        )
        
        assert param.key == "R1.resistance"
    
    def test_to_dict(self):
        """测试序列化"""
        param = SweepParameter(
            component="R1",
            param="resistance",
            sweep_type=SweepType.LINEAR,
            start=1000.0,
            stop=10000.0,
            step=1000.0,
            unit="Ω",
        )
        
        data = param.to_dict()
        
        assert data["component"] == "R1"
        assert data["param"] == "resistance"
        assert data["sweep_type"] == "linear"
        assert data["start"] == 1000.0
        assert data["unit"] == "Ω"
    
    def test_from_dict(self):
        """测试反序列化"""
        data = {
            "component": "C1",
            "param": "capacitance",
            "sweep_type": "log",
            "start": 1e-9,
            "stop": 1e-6,
            "step": 10,
            "unit": "F",
        }
        
        param = SweepParameter.from_dict(data)
        
        assert param.component == "C1"
        assert param.sweep_type == SweepType.LOG
        assert param.start == 1e-9


# ============================================================
# NestedSweepConfig 测试
# ============================================================

class TestNestedSweepConfig:
    """NestedSweepConfig 测试"""
    
    def test_total_points_single(self):
        """测试单参数总点数"""
        param = SweepParameter(
            component="R1",
            param="resistance",
            sweep_type=SweepType.LINEAR,
            start=1.0,
            stop=5.0,
            step=1.0,
        )
        
        config = NestedSweepConfig(params=[param])
        
        assert config.total_points == 5
    
    def test_total_points_nested(self):
        """测试嵌套扫描总点数"""
        param1 = SweepParameter(
            component="R1",
            param="resistance",
            sweep_type=SweepType.LINEAR,
            start=1.0,
            stop=5.0,
            step=1.0,
        )
        param2 = SweepParameter(
            component="C1",
            param="capacitance",
            sweep_type=SweepType.LINEAR,
            start=1.0,
            stop=3.0,
            step=1.0,
        )
        
        config = NestedSweepConfig(params=[param1, param2])
        
        # 5 * 3 = 15
        assert config.total_points == 15
    
    def test_depth(self):
        """测试嵌套深度"""
        param1 = SweepParameter("R1", "resistance", SweepType.LINEAR, 1.0, 5.0, 1.0)
        param2 = SweepParameter("C1", "capacitance", SweepType.LINEAR, 1.0, 3.0, 1.0)
        
        config = NestedSweepConfig(params=[param1, param2])
        
        assert config.depth == 2
    
    def test_estimate_time(self):
        """测试时间预估"""
        param = SweepParameter("R1", "resistance", SweepType.LINEAR, 1.0, 10.0, 1.0)
        config = NestedSweepConfig(params=[param])
        
        # 10 点 * 2 秒/点 = 20 秒
        assert config.estimate_time(2.0) == 20.0


# ============================================================
# SweepPointResult 测试
# ============================================================

class TestSweepPointResult:
    """SweepPointResult 测试"""
    
    def test_create_result(self):
        """测试创建扫描点结果"""
        result = SweepPointResult(
            point_index=0,
            param_values={"R1.resistance": 1000.0},
            metrics={"gain": 20.0},
            passed=True,
        )
        
        assert result.point_index == 0
        assert result.param_values["R1.resistance"] == 1000.0
        assert result.metrics["gain"] == 20.0
        assert result.passed is True
    
    def test_to_dict(self):
        """测试序列化"""
        result = SweepPointResult(
            point_index=5,
            param_values={"R1.resistance": 5000.0},
            metrics={"bandwidth": 1e6},
            passed=False,
        )
        
        data = result.to_dict()
        
        assert data["point_index"] == 5
        assert data["passed"] is False


# ============================================================
# SweepAnalysisResult 测试
# ============================================================

class TestSweepAnalysisResult:
    """SweepAnalysisResult 测试"""
    
    def test_successful_points(self):
        """测试成功点数统计"""
        result = SweepAnalysisResult(
            circuit_file="test.cir",
            analysis_type="ac",
            sweep_config=NestedSweepConfig(),
        )
        
        mock_sim_success = Mock(spec=SimulationResult)
        mock_sim_success.success = True
        
        mock_sim_fail = Mock(spec=SimulationResult)
        mock_sim_fail.success = False
        
        result.points = [
            SweepPointResult(0, {}, simulation_result=mock_sim_success),
            SweepPointResult(1, {}, simulation_result=mock_sim_fail),
            SweepPointResult(2, {}, simulation_result=mock_sim_success),
        ]
        
        assert result.successful_points == 2
        assert result.failed_points == 1


# ============================================================
# ParametricSweepAnalyzer 测试
# ============================================================

class TestParametricSweepAnalyzer:
    """ParametricSweepAnalyzer 测试"""
    
    def test_define_sweep_param(self):
        """测试定义扫描参数"""
        analyzer = ParametricSweepAnalyzer()
        
        param = analyzer.define_sweep_param(
            component="R1",
            param="resistance",
            start=1000.0,
            stop=10000.0,
            step=1000.0,
        )
        
        assert param.component == "R1"
        assert param.sweep_type == SweepType.LINEAR
        assert param.num_points == 10
    
    def test_define_list_sweep(self):
        """测试定义列表扫描"""
        analyzer = ParametricSweepAnalyzer()
        
        param = analyzer.define_list_sweep(
            component="R1",
            param="resistance",
            values=[100.0, 1000.0, 10000.0],
        )
        
        assert param.sweep_type == SweepType.LIST
        assert param.num_points == 3
    
    def test_define_nested_sweep(self):
        """测试定义嵌套扫描"""
        analyzer = ParametricSweepAnalyzer()
        
        param1 = analyzer.define_sweep_param("R1", "resistance", 1.0, 5.0, 1.0)
        param2 = analyzer.define_sweep_param("C1", "capacitance", 1.0, 3.0, 1.0)
        
        config = analyzer.define_nested_sweep([param1, param2])
        
        assert config.depth == 2
        assert config.total_points == 15
    
    def test_define_nested_sweep_max_depth(self):
        """测试嵌套深度限制"""
        analyzer = ParametricSweepAnalyzer()
        
        params = [
            analyzer.define_sweep_param(f"R{i}", "resistance", 1.0, 2.0, 1.0)
            for i in range(MAX_NESTED_DEPTH + 1)
        ]
        
        with pytest.raises(ValueError):
            analyzer.define_nested_sweep(params)
    
    @patch('domain.simulation.analysis.parametric_sweep.SpiceExecutor')
    def test_run_sweep_with_mock(self, mock_executor_class):
        """测试参数扫描（使用 Mock）"""
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor
        
        mock_result = Mock(spec=SimulationResult)
        mock_result.success = True
        mock_result.metric_values = {"gain": 20.0}
        mock_executor.execute.return_value = mock_result
        
        analyzer = ParametricSweepAnalyzer(executor=mock_executor)
        
        param = analyzer.define_sweep_param("R1", "resistance", 1.0, 3.0, 1.0)
        
        result = analyzer.run_sweep(
            circuit_file="test.cir",
            analysis_config={"analysis_type": "ac"},
            sweep_config=param,
        )
        
        assert result.circuit_file == "test.cir"
        assert len(result.points) == 3
        assert mock_executor.execute.call_count == 3
    
    def test_find_optimal_point(self):
        """测试找最优点"""
        analyzer = ParametricSweepAnalyzer()
        
        result = SweepAnalysisResult(
            circuit_file="test.cir",
            analysis_type="ac",
            sweep_config=NestedSweepConfig(),
        )
        
        mock_sim = Mock(spec=SimulationResult)
        mock_sim.success = True
        
        result.points = [
            SweepPointResult(0, {"R1.resistance": 1000.0}, mock_sim, {"gain": 15.0}),
            SweepPointResult(1, {"R1.resistance": 2000.0}, mock_sim, {"gain": 25.0}),
            SweepPointResult(2, {"R1.resistance": 3000.0}, mock_sim, {"gain": 20.0}),
        ]
        
        optimal = analyzer.find_optimal_point(result, "gain", maximize=True)
        
        assert optimal is not None
        assert optimal.metrics["gain"] == 25.0
        assert optimal.param_values["R1.resistance"] == 2000.0
    
    def test_find_optimal_point_with_constraints(self):
        """测试带约束的最优点查找"""
        analyzer = ParametricSweepAnalyzer()
        
        result = SweepAnalysisResult(
            circuit_file="test.cir",
            analysis_type="ac",
            sweep_config=NestedSweepConfig(),
        )
        
        mock_sim = Mock(spec=SimulationResult)
        mock_sim.success = True
        
        result.points = [
            SweepPointResult(0, {"R1.resistance": 1000.0}, mock_sim, {"gain": 30.0, "bandwidth": 0.5e6}),
            SweepPointResult(1, {"R1.resistance": 2000.0}, mock_sim, {"gain": 25.0, "bandwidth": 1.5e6}),
            SweepPointResult(2, {"R1.resistance": 3000.0}, mock_sim, {"gain": 20.0, "bandwidth": 2.0e6}),
        ]
        
        # 约束：bandwidth >= 1e6
        optimal = analyzer.find_optimal_point(
            result, "gain",
            constraints={"bandwidth": {"min": 1e6}},
            maximize=True,
        )
        
        # 第一个点 gain 最高但 bandwidth 不满足约束
        assert optimal is not None
        assert optimal.metrics["gain"] == 25.0
    
    def test_generate_curve_data(self):
        """测试生成曲线数据"""
        analyzer = ParametricSweepAnalyzer()
        
        result = SweepAnalysisResult(
            circuit_file="test.cir",
            analysis_type="ac",
            sweep_config=NestedSweepConfig(),
        )
        
        mock_sim = Mock(spec=SimulationResult)
        mock_sim.success = True
        
        result.points = [
            SweepPointResult(0, {"R1.resistance": 1000.0}, mock_sim, {"gain": 15.0}),
            SweepPointResult(1, {"R1.resistance": 2000.0}, mock_sim, {"gain": 20.0}),
            SweepPointResult(2, {"R1.resistance": 3000.0}, mock_sim, {"gain": 25.0}),
        ]
        
        curve = analyzer.generate_curve_data(result, "R1.resistance", "gain")
        
        assert curve["x"] == [1000.0, 2000.0, 3000.0]
        assert curve["y"] == [15.0, 20.0, 25.0]
        assert curve["x_label"] == "R1.resistance"
        assert curve["y_label"] == "gain"
    
    def test_generate_contour_data(self):
        """测试生成等高线数据"""
        analyzer = ParametricSweepAnalyzer()
        
        result = SweepAnalysisResult(
            circuit_file="test.cir",
            analysis_type="ac",
            sweep_config=NestedSweepConfig(),
        )
        
        mock_sim = Mock(spec=SimulationResult)
        mock_sim.success = True
        
        # 2x2 网格
        result.points = [
            SweepPointResult(0, {"R1.resistance": 1.0, "C1.capacitance": 1.0}, mock_sim, {"gain": 10.0}),
            SweepPointResult(1, {"R1.resistance": 2.0, "C1.capacitance": 1.0}, mock_sim, {"gain": 15.0}),
            SweepPointResult(2, {"R1.resistance": 1.0, "C1.capacitance": 2.0}, mock_sim, {"gain": 20.0}),
            SweepPointResult(3, {"R1.resistance": 2.0, "C1.capacitance": 2.0}, mock_sim, {"gain": 25.0}),
        ]
        
        contour = analyzer.generate_contour_data(
            result, "R1.resistance", "C1.capacitance", "gain"
        )
        
        assert contour["x"] == [1.0, 2.0]
        assert contour["y"] == [1.0, 2.0]
        assert len(contour["z"]) == 2
        assert len(contour["z"][0]) == 2
    
    def test_generate_report(self):
        """测试生成报告"""
        analyzer = ParametricSweepAnalyzer()
        
        param = SweepParameter("R1", "resistance", SweepType.LINEAR, 1.0, 5.0, 1.0)
        
        result = SweepAnalysisResult(
            circuit_file="amplifier.cir",
            analysis_type="ac",
            sweep_config=NestedSweepConfig(params=[param]),
            duration_seconds=10.0,
        )
        
        mock_sim = Mock(spec=SimulationResult)
        mock_sim.success = True
        
        result.points = [
            SweepPointResult(i, {"R1.resistance": float(i + 1)}, mock_sim, {"gain": 20.0})
            for i in range(5)
        ]
        
        report = analyzer.generate_report(result)
        
        assert "# 参数扫描分析报告" in report
        assert "amplifier.cir" in report
        assert "R1.resistance" in report


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
