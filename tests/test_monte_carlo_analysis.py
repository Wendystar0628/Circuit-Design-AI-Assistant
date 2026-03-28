# Test Monte Carlo Analysis Module
"""
蒙特卡洛分析模块测试

测试内容：
- ParameterVariation 数据类
- DistributionType 枚举
- MonteCarloStatistics 统计计算
- MonteCarloAnalyzer 核心功能
- 随机值生成
"""

import pytest
import random
from unittest.mock import Mock, patch

from domain.simulation.analysis.monte_carlo_analysis import (
    MonteCarloAnalyzer,
    ParameterVariation,
    DistributionType,
    MonteCarloRunResult,
    MonteCarloAnalysisResult,
    MonteCarloStatistics,
    DEFAULT_RESISTOR_VARIATION,
    DEFAULT_CAPACITOR_VARIATION,
)
from domain.simulation.models.simulation_result import SimulationResult


# ============================================================
# DistributionType 枚举测试
# ============================================================

class TestDistributionType:
    """DistributionType 枚举测试"""
    
    def test_enum_values(self):
        """测试枚举值"""
        assert DistributionType.GAUSSIAN.value == "gaussian"
        assert DistributionType.UNIFORM.value == "uniform"
        assert DistributionType.LOG_NORMAL.value == "log_normal"
    
    def test_enum_from_value(self):
        """测试从值创建枚举"""
        assert DistributionType("gaussian") == DistributionType.GAUSSIAN
        assert DistributionType("uniform") == DistributionType.UNIFORM


# ============================================================
# ParameterVariation 数据类测试
# ============================================================

class TestParameterVariation:
    """ParameterVariation 数据类测试"""
    
    def test_create_variation(self):
        """测试创建参数变化"""
        var = ParameterVariation(
            component="R1",
            parameter="resistance",
            distribution=DistributionType.UNIFORM,
            tolerance=0.05,
        )
        
        assert var.component == "R1"
        assert var.parameter == "resistance"
        assert var.distribution == DistributionType.UNIFORM
        assert var.tolerance == 0.05
    
    def test_to_dict(self):
        """测试序列化"""
        var = ParameterVariation(
            component="C1",
            parameter="capacitance",
            distribution=DistributionType.GAUSSIAN,
            sigma=0.03,
        )
        
        data = var.to_dict()
        
        assert data["component"] == "C1"
        assert data["parameter"] == "capacitance"
        assert data["distribution"] == "gaussian"
        assert data["sigma"] == 0.03
    
    def test_from_dict(self):
        """测试反序列化"""
        data = {
            "component": "M1",
            "parameter": "vth0",
            "distribution": "gaussian",
            "tolerance": 0.05,
            "sigma": 0.01,
        }
        
        var = ParameterVariation.from_dict(data)
        
        assert var.component == "M1"
        assert var.parameter == "vth0"
        assert var.distribution == DistributionType.GAUSSIAN
        assert var.sigma == 0.01
    
    def test_generate_value_uniform(self):
        """测试均匀分布值生成"""
        var = ParameterVariation(
            component="R1",
            parameter="resistance",
            distribution=DistributionType.UNIFORM,
            tolerance=0.1,
        )
        
        rng = random.Random(42)
        nominal = 1000.0
        
        # 生成多个值并检查范围
        values = [var.generate_value(nominal, rng) for _ in range(100)]
        
        assert all(900.0 <= v <= 1100.0 for v in values)
    
    def test_generate_value_gaussian(self):
        """测试高斯分布值生成"""
        var = ParameterVariation(
            component="R1",
            parameter="resistance",
            distribution=DistributionType.GAUSSIAN,
            sigma=0.01,
        )
        
        rng = random.Random(42)
        nominal = 1000.0
        
        # 生成多个值
        values = [var.generate_value(nominal, rng) for _ in range(1000)]
        
        # 检查均值接近标称值
        mean = sum(values) / len(values)
        assert abs(mean - nominal) < 50  # 允许一定误差


# ============================================================
# MonteCarloStatistics 测试
# ============================================================

class TestMonteCarloStatistics:
    """MonteCarloStatistics 测试"""
    
    def test_from_values(self):
        """测试从值列表计算统计"""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        
        stats = MonteCarloStatistics.from_values("test_metric", values)
        
        assert stats.metric_name == "test_metric"
        assert stats.mean == 3.0
        assert stats.min_value == 1.0
        assert stats.max_value == 5.0
        assert stats.median == 3.0
        assert len(stats.values) == 5
    
    def test_from_empty_values(self):
        """测试空值列表"""
        stats = MonteCarloStatistics.from_values("empty", [])
        
        assert stats.metric_name == "empty"
        assert stats.mean == 0.0
        assert len(stats.values) == 0
    
    def test_to_dict(self):
        """测试序列化"""
        stats = MonteCarloStatistics.from_values("gain", [10.0, 20.0, 30.0])
        
        data = stats.to_dict()
        
        assert data["metric_name"] == "gain"
        assert data["mean"] == 20.0
        assert data["min"] == 10.0
        assert data["max"] == 30.0
        assert data["sample_count"] == 3


# ============================================================
# MonteCarloRunResult 测试
# ============================================================

class TestMonteCarloRunResult:
    """MonteCarloRunResult 测试"""
    
    def test_create_run_result(self):
        """测试创建运行结果"""
        result = MonteCarloRunResult(
            run_index=0,
            seed=12345,
            parameter_values={"R1.resistance": 1050.0},
            metrics={"gain": 20.5},
            passed=True,
        )
        
        assert result.run_index == 0
        assert result.seed == 12345
        assert result.parameter_values["R1.resistance"] == 1050.0
        assert result.metrics["gain"] == 20.5
        assert result.passed is True
    
    def test_to_dict(self):
        """测试序列化"""
        result = MonteCarloRunResult(
            run_index=5,
            seed=99999,
            metrics={"bandwidth": 1e6},
            passed=False,
        )
        
        data = result.to_dict()
        
        assert data["run_index"] == 5
        assert data["seed"] == 99999
        assert data["passed"] is False


# ============================================================
# MonteCarloAnalysisResult 测试
# ============================================================

class TestMonteCarloAnalysisResult:
    """MonteCarloAnalysisResult 测试"""
    
    def test_create_result(self):
        """测试创建分析结果"""
        result = MonteCarloAnalysisResult(
            circuit_file="test.cir",
            analysis_type="ac",
            num_runs=100,
            successful_runs=95,
            failed_runs=5,
            yield_percent=90.0,
        )
        
        assert result.circuit_file == "test.cir"
        assert result.num_runs == 100
        assert result.successful_runs == 95
        assert result.yield_percent == 90.0
    
    def test_get_statistics(self):
        """测试获取统计数据"""
        result = MonteCarloAnalysisResult(
            circuit_file="test.cir",
            analysis_type="ac",
        )
        
        stats = MonteCarloStatistics.from_values("gain", [10.0, 20.0, 30.0])
        result.statistics["gain"] = stats
        
        retrieved = result.get_statistics("gain")
        assert retrieved is not None
        assert retrieved.mean == 20.0
        
        missing = result.get_statistics("nonexistent")
        assert missing is None
    
    def test_to_dict(self):
        """测试序列化"""
        result = MonteCarloAnalysisResult(
            circuit_file="amp.cir",
            analysis_type="tran",
            num_runs=50,
            yield_percent=95.5,
        )
        
        data = result.to_dict()
        
        assert data["circuit_file"] == "amp.cir"
        assert data["num_runs"] == 50
        assert data["yield_percent"] == 95.5


# ============================================================
# MonteCarloAnalyzer 测试
# ============================================================

class TestMonteCarloAnalyzer:
    """MonteCarloAnalyzer 测试"""
    
    def test_define_variation(self):
        """测试定义参数变化"""
        analyzer = MonteCarloAnalyzer()
        
        var = analyzer.define_variation(
            component="R1",
            parameter="resistance",
            distribution=DistributionType.UNIFORM,
            tolerance=0.05,
        )
        
        assert var.component == "R1"
        assert var.parameter == "resistance"
        assert var.distribution == DistributionType.UNIFORM
        assert var.tolerance == 0.05
    
    @patch('domain.simulation.analysis.monte_carlo_analysis.SpiceExecutor')
    def test_run_monte_carlo_with_mock(self, mock_executor_class):
        """测试蒙特卡洛仿真（使用 Mock）"""
        # 设置 Mock 执行器
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor
        
        # 模拟仿真结果
        mock_result = Mock(spec=SimulationResult)
        mock_result.success = True
        mock_result.metrics = {"gain": 20.0}
        mock_executor.execute.return_value = mock_result
        
        analyzer = MonteCarloAnalyzer(executor=mock_executor)
        
        variations = [
            ParameterVariation("R1", "resistance", DistributionType.UNIFORM, tolerance=0.05),
        ]
        
        result = analyzer.run_monte_carlo(
            circuit_file="test.cir",
            analysis_config={"analysis_type": "ac"},
            num_runs=10,
            variations=variations,
            base_seed=42,
        )
        
        assert result.circuit_file == "test.cir"
        assert result.num_runs == 10
        assert result.successful_runs == 10
        assert result.failed_runs == 0
        assert mock_executor.execute.call_count == 10
    
    @patch('domain.simulation.analysis.monte_carlo_analysis.SpiceExecutor')
    def test_run_monte_carlo_with_failures(self, mock_executor_class):
        """测试蒙特卡洛仿真（包含失败）"""
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor
        
        # 模拟部分失败
        success_result = Mock(spec=SimulationResult)
        success_result.success = True
        success_result.metrics = {"gain": 20.0}
        
        fail_result = Mock(spec=SimulationResult)
        fail_result.success = False
        fail_result.metrics = {}
        
        # 交替返回成功和失败
        mock_executor.execute.side_effect = [
            success_result, fail_result, success_result, fail_result, success_result
        ]
        
        analyzer = MonteCarloAnalyzer(executor=mock_executor)
        
        result = analyzer.run_monte_carlo(
            circuit_file="test.cir",
            num_runs=5,
        )
        
        assert result.successful_runs == 3
        assert result.failed_runs == 2
    
    def test_calculate_yield(self):
        """测试良率计算"""
        analyzer = MonteCarloAnalyzer()
        
        result = MonteCarloAnalysisResult(
            circuit_file="test.cir",
            analysis_type="ac",
        )
        
        # 添加运行结果
        result.runs = [
            MonteCarloRunResult(0, 1, metrics={"gain": 25.0}, passed=True),
            MonteCarloRunResult(1, 2, metrics={"gain": 15.0}, passed=True),
            MonteCarloRunResult(2, 3, metrics={"gain": 30.0}, passed=True),
            MonteCarloRunResult(3, 4, metrics={"gain": 10.0}, passed=True),
        ]
        
        specs = {"gain": {"min": 20.0}}
        yield_pct = analyzer.calculate_yield(result, specs)
        
        # 只有 gain >= 20 的通过：25, 30 = 2/4 = 50%
        assert yield_pct == 50.0
    
    def test_generate_histogram(self):
        """测试生成直方图"""
        analyzer = MonteCarloAnalyzer()
        
        result = MonteCarloAnalysisResult(
            circuit_file="test.cir",
            analysis_type="ac",
        )
        
        # 添加统计数据
        values = [10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0]
        result.statistics["gain"] = MonteCarloStatistics.from_values("gain", values)
        
        histogram = analyzer.generate_histogram(result, "gain", bins=5)
        
        assert "edges" in histogram
        assert "counts" in histogram
        assert len(histogram["edges"]) == 6  # bins + 1
        assert len(histogram["counts"]) == 5
    
    def test_generate_report(self):
        """测试生成报告"""
        analyzer = MonteCarloAnalyzer()
        
        result = MonteCarloAnalysisResult(
            circuit_file="amplifier.cir",
            analysis_type="ac",
            num_runs=100,
            successful_runs=95,
            failed_runs=5,
            yield_percent=90.0,
            duration_seconds=30.0,
        )
        
        # 添加统计数据
        result.statistics["gain"] = MonteCarloStatistics.from_values(
            "gain", [18.0, 19.0, 20.0, 21.0, 22.0]
        )
        
        report = analyzer.generate_report(result)
        
        assert "# 蒙特卡洛分析报告" in report
        assert "amplifier.cir" in report
        assert "100" in report
        assert "90.0" in report or "90.00" in report
        assert "gain" in report
    
    def test_check_design_goals_pass(self):
        """测试设计目标检查 - 通过"""
        analyzer = MonteCarloAnalyzer()
        
        metrics = {"gain": 25.0, "bandwidth": 1e6}
        goals = {"gain": {"min": 20.0}}
        
        passed = analyzer._check_design_goals(metrics, goals)
        assert passed is True
    
    def test_check_design_goals_fail(self):
        """测试设计目标检查 - 失败"""
        analyzer = MonteCarloAnalyzer()
        
        metrics = {"gain": 15.0}
        goals = {"gain": {"min": 20.0}}
        
        passed = analyzer._check_design_goals(metrics, goals)
        assert passed is False
    
    def test_should_abort(self):
        """测试提前终止判断"""
        analyzer = MonteCarloAnalyzer()
        
        # 少于 10 次不终止
        assert analyzer._should_abort(5, 8) is False
        
        # 失败率低于阈值不终止
        assert analyzer._should_abort(1, 20) is False
        
        # 失败率超过阈值终止
        assert analyzer._should_abort(3, 20) is True  # 15% > 10%


# ============================================================
# 默认配置测试
# ============================================================

class TestDefaultVariations:
    """默认参数变化配置测试"""
    
    def test_default_resistor_variation(self):
        """测试默认电阻变化"""
        assert DEFAULT_RESISTOR_VARIATION.parameter == "resistance"
        assert DEFAULT_RESISTOR_VARIATION.distribution == DistributionType.UNIFORM
        assert DEFAULT_RESISTOR_VARIATION.tolerance == 0.05
    
    def test_default_capacitor_variation(self):
        """测试默认电容变化"""
        assert DEFAULT_CAPACITOR_VARIATION.parameter == "capacitance"
        assert DEFAULT_CAPACITOR_VARIATION.distribution == DistributionType.UNIFORM
        assert DEFAULT_CAPACITOR_VARIATION.tolerance == 0.10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
