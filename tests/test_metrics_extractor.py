# test_metrics_extractor.py - Tests for MetricsExtractor Facade
"""
MetricsExtractor 门面类测试

测试内容：
- 根据拓扑类型提取指标
- 提取所有可计算指标
- 按名称提取单个指标
- 按类别提取指标
- 容错处理
"""

import numpy as np
import pytest

from domain.simulation.metrics import (
    MetricsExtractor,
    metrics_extractor,
    MetricCategory,
    MetricResult,
)
from domain.simulation.models.simulation_result import SimulationData


# ============================================================
# 测试数据工厂
# ============================================================

def create_ac_data() -> SimulationData:
    """创建 AC 分析测试数据"""
    freq = np.logspace(1, 6, 100)  # 10Hz - 1MHz
    # 模拟一阶低通响应
    fc = 10000  # 10kHz 截止频率
    gain_linear = 10 / np.sqrt(1 + (freq / fc) ** 2)
    phase = -np.arctan(freq / fc)
    
    # 复数传递函数
    transfer = gain_linear * np.exp(1j * phase)
    
    return SimulationData(
        frequency=freq,
        time=None,
        signals={
            "V(out)": transfer,
            "V(in)": np.ones_like(freq, dtype=complex),
        }
    )


def create_transient_data() -> SimulationData:
    """创建瞬态分析测试数据"""
    # 1ms 仿真，1us 步长
    time = np.linspace(0, 1e-3, 1000)
    
    # 模拟阶跃响应（带过冲）
    tau = 50e-6  # 50us 时间常数
    overshoot = 0.1  # 10% 过冲
    omega_n = 1 / tau
    zeta = 0.7
    
    # 二阶系统阶跃响应
    omega_d = omega_n * np.sqrt(1 - zeta**2)
    response = 1 - np.exp(-zeta * omega_n * time) * (
        np.cos(omega_d * time) + 
        (zeta / np.sqrt(1 - zeta**2)) * np.sin(omega_d * time)
    )
    
    # 输入阶跃
    input_signal = np.where(time >= 0, 1.0, 0.0)
    
    return SimulationData(
        frequency=None,
        time=time,
        signals={
            "V(out)": response,
            "V(in)": input_signal,
        }
    )


def create_oscillator_data() -> SimulationData:
    """创建振荡器测试数据"""
    # 10us 仿真，10ns 步长
    time = np.linspace(0, 10e-6, 1000)
    
    # 1MHz 正弦波
    freq = 1e6
    signal = np.sin(2 * np.pi * freq * time)
    
    return SimulationData(
        frequency=None,
        time=time,
        signals={
            "V(out)": signal,
        }
    )


def create_power_data() -> SimulationData:
    """创建电源分析测试数据"""
    time = np.linspace(0, 1e-3, 100)
    
    return SimulationData(
        frequency=None,
        time=time,
        signals={
            "V(out)": np.ones(100) * 3.3,
            "V(vin)": np.ones(100) * 5.0,
            "I(Vdd)": np.ones(100) * 1e-3,  # 1mA
            "I(Rload)": np.ones(100) * 10e-3,  # 10mA
        }
    )


def create_empty_data() -> SimulationData:
    """创建空数据"""
    return SimulationData(
        frequency=None,
        time=None,
        signals={}
    )


# ============================================================
# 测试类
# ============================================================

class TestMetricsExtractorInit:
    """测试 MetricsExtractor 初始化"""
    
    def test_singleton_instance(self):
        """测试模块级单例"""
        assert metrics_extractor is not None
        assert isinstance(metrics_extractor, MetricsExtractor)
    
    def test_new_instance(self):
        """测试创建新实例"""
        extractor = MetricsExtractor()
        assert extractor is not None
        assert len(extractor.METRIC_EXTRACTORS) > 0
    
    def test_supported_metrics(self):
        """测试支持的指标列表"""
        metrics = metrics_extractor.get_supported_metrics()
        assert len(metrics) > 0
        assert "gain" in metrics
        assert "bandwidth" in metrics
        assert "thd" in metrics
    
    def test_supported_topologies(self):
        """测试支持的拓扑列表"""
        topologies = metrics_extractor.get_supported_topologies()
        assert len(topologies) > 0
        assert "amplifier" in topologies
        assert "ldo" in topologies
        assert "oscillator" in topologies


class TestExtractMetricsByTopology:
    """测试根据拓扑类型提取指标"""
    
    def test_amplifier_topology_ac_data(self):
        """测试放大器拓扑 - AC 数据"""
        data = create_ac_data()
        results = metrics_extractor.extract_metrics(data, topology="amplifier")
        
        assert isinstance(results, dict)
        assert len(results) > 0
        
        # 检查关键指标
        if "gain" in results:
            assert isinstance(results["gain"], MetricResult)
        if "bandwidth" in results:
            assert isinstance(results["bandwidth"], MetricResult)
    
    def test_oscillator_topology_transient_data(self):
        """测试振荡器拓扑 - 瞬态数据"""
        data = create_oscillator_data()
        results = metrics_extractor.extract_metrics(data, topology="oscillator")
        
        assert isinstance(results, dict)
        
        # 振荡器应该能提取频率
        if "frequency" in results:
            freq_result = results["frequency"]
            assert isinstance(freq_result, MetricResult)
            if freq_result.is_valid:
                # 应该接近 1MHz
                assert 0.9e6 < freq_result.value < 1.1e6
    
    def test_ldo_topology_power_data(self):
        """测试 LDO 拓扑 - 电源数据"""
        data = create_power_data()
        results = metrics_extractor.extract_metrics(data, topology="ldo")
        
        assert isinstance(results, dict)
        
        # LDO 应该能提取静态电流
        if "quiescent_current" in results:
            iq_result = results["quiescent_current"]
            assert isinstance(iq_result, MetricResult)
    
    def test_unknown_topology(self):
        """测试未知拓扑类型"""
        data = create_ac_data()
        results = metrics_extractor.extract_metrics(data, topology="unknown_type")
        
        # 未知拓扑应该返回所有可计算指标
        assert isinstance(results, dict)
    
    def test_no_topology(self):
        """测试无拓扑类型"""
        data = create_ac_data()
        results = metrics_extractor.extract_metrics(data, topology=None)
        
        # 无拓扑应该返回所有可计算指标
        assert isinstance(results, dict)
        assert len(results) > 0


class TestExtractMetricsWithGoals:
    """测试带目标值的指标提取"""
    
    def test_simple_goals(self):
        """测试简单目标格式"""
        data = create_ac_data()
        goals = {"gain": 20, "bandwidth": 10000}
        
        results = metrics_extractor.extract_metrics(
            data, topology="amplifier", goals=goals
        )
        
        if "gain" in results and results["gain"].is_valid:
            assert results["gain"].target == 20
    
    def test_complex_goals(self):
        """测试复杂目标格式"""
        data = create_ac_data()
        goals = {
            "gain": {"value": 20, "type": "min"},
            "bandwidth": {"value": 1000, "type": "min", "max": 100000}
        }
        
        results = metrics_extractor.extract_metrics(
            data, topology="amplifier", goals=goals
        )
        
        if "gain" in results and results["gain"].is_valid:
            assert results["gain"].target == 20
            assert results["gain"].target_type == "min"


class TestExtractAllMetrics:
    """测试提取所有可计算指标"""
    
    def test_ac_data_metrics(self):
        """测试 AC 数据的所有指标"""
        data = create_ac_data()
        results = metrics_extractor.extract_all_metrics(data)
        
        assert isinstance(results, dict)
        assert len(results) > 0
        
        # AC 数据应该能提取增益和带宽
        assert "gain" in results or "bandwidth" in results
    
    def test_transient_data_metrics(self):
        """测试瞬态数据的所有指标"""
        data = create_transient_data()
        results = metrics_extractor.extract_all_metrics(data)
        
        assert isinstance(results, dict)
        assert len(results) > 0
        
        # 瞬态数据应该能提取上升时间
        assert "rise_time" in results or "settling_time" in results
    
    def test_empty_data_metrics(self):
        """测试空数据"""
        data = create_empty_data()
        results = metrics_extractor.extract_all_metrics(data)
        
        # 空数据应该返回空字典或只有错误指标
        assert isinstance(results, dict)


class TestGetMetricByName:
    """测试按名称提取单个指标"""
    
    def test_valid_metric_name(self):
        """测试有效指标名称"""
        data = create_ac_data()
        result = metrics_extractor.get_metric_by_name(data, "gain")
        
        assert isinstance(result, MetricResult)
        assert result.name == "gain"
    
    def test_invalid_metric_name(self):
        """测试无效指标名称"""
        data = create_ac_data()
        result = metrics_extractor.get_metric_by_name(data, "invalid_metric")
        
        assert isinstance(result, MetricResult)
        assert not result.is_valid
        assert result.error_message is not None
    
    def test_case_insensitive(self):
        """测试大小写不敏感"""
        data = create_ac_data()
        
        result1 = metrics_extractor.get_metric_by_name(data, "gain")
        result2 = metrics_extractor.get_metric_by_name(data, "GAIN")
        result3 = metrics_extractor.get_metric_by_name(data, "Gain")
        
        # 所有结果应该相同
        assert result1.name == result2.name == result3.name
    
    def test_with_custom_signals(self):
        """测试自定义信号名称"""
        data = create_ac_data()
        data.signals["V(output)"] = data.signals["V(out)"]
        
        result = metrics_extractor.get_metric_by_name(
            data, "gain", output_signal="V(output)"
        )
        
        assert isinstance(result, MetricResult)


class TestGetMetricsByCategory:
    """测试按类别提取指标"""
    
    def test_amplifier_category(self):
        """测试放大器类别"""
        data = create_ac_data()
        results = metrics_extractor.get_metrics_by_category(
            data, MetricCategory.AMPLIFIER
        )
        
        assert isinstance(results, dict)
        # 应该包含放大器相关指标
        assert any(name in results for name in ["gain", "bandwidth", "phase_margin"])
    
    def test_noise_category(self):
        """测试噪声类别"""
        data = create_ac_data()
        results = metrics_extractor.get_metrics_by_category(
            data, MetricCategory.NOISE
        )
        
        assert isinstance(results, dict)
    
    def test_distortion_category(self):
        """测试失真类别"""
        data = create_oscillator_data()
        results = metrics_extractor.get_metrics_by_category(
            data, MetricCategory.DISTORTION
        )
        
        assert isinstance(results, dict)
    
    def test_power_category(self):
        """测试电源类别"""
        data = create_power_data()
        results = metrics_extractor.get_metrics_by_category(
            data, MetricCategory.POWER
        )
        
        assert isinstance(results, dict)
    
    def test_transient_category(self):
        """测试瞬态类别"""
        data = create_transient_data()
        results = metrics_extractor.get_metrics_by_category(
            data, MetricCategory.TRANSIENT
        )
        
        assert isinstance(results, dict)


class TestErrorHandling:
    """测试错误处理"""
    
    def test_missing_signal(self):
        """测试缺少信号"""
        data = SimulationData(
            frequency=np.logspace(1, 6, 100),
            time=None,
            signals={}  # 无信号
        )
        
        result = metrics_extractor.get_metric_by_name(data, "gain")
        
        assert isinstance(result, MetricResult)
        assert not result.is_valid
        assert result.error_message is not None
    
    def test_insufficient_data_points(self):
        """测试数据点不足"""
        data = SimulationData(
            frequency=np.array([100]),  # 只有一个点
            time=None,
            signals={"V(out)": np.array([1.0])}
        )
        
        result = metrics_extractor.get_metric_by_name(data, "bandwidth")
        
        assert isinstance(result, MetricResult)
        # 带宽需要多个点，应该返回错误
    
    def test_nan_values(self):
        """测试 NaN 值"""
        data = SimulationData(
            frequency=np.logspace(1, 6, 100),
            time=None,
            signals={"V(out)": np.full(100, np.nan)}
        )
        
        result = metrics_extractor.get_metric_by_name(data, "gain")
        
        assert isinstance(result, MetricResult)


class TestTopologyMetricsMapping:
    """测试拓扑到指标的映射"""
    
    def test_get_metrics_for_topology(self):
        """测试获取拓扑的指标列表"""
        amplifier_metrics = metrics_extractor.get_metrics_for_topology("amplifier")
        
        assert isinstance(amplifier_metrics, list)
        assert len(amplifier_metrics) > 0
        assert "gain" in amplifier_metrics
        assert "bandwidth" in amplifier_metrics
    
    def test_unknown_topology_returns_empty(self):
        """测试未知拓扑返回空列表"""
        metrics = metrics_extractor.get_metrics_for_topology("unknown")
        
        assert isinstance(metrics, list)
        assert len(metrics) == 0
    
    def test_case_insensitive_topology(self):
        """测试拓扑名称大小写不敏感"""
        metrics1 = metrics_extractor.get_metrics_for_topology("amplifier")
        metrics2 = metrics_extractor.get_metrics_for_topology("AMPLIFIER")
        metrics3 = metrics_extractor.get_metrics_for_topology("Amplifier")
        
        assert metrics1 == metrics2 == metrics3


class TestSpecialMetrics:
    """测试特殊指标提取"""
    
    def test_slew_rate_extraction(self):
        """测试压摆率提取"""
        data = create_transient_data()
        result = metrics_extractor.get_metric_by_name(data, "slew_rate")
        
        assert isinstance(result, MetricResult)
    
    def test_propagation_delay_extraction(self):
        """测试传播延迟提取"""
        data = create_transient_data()
        result = metrics_extractor.get_metric_by_name(data, "propagation_delay")
        
        assert isinstance(result, MetricResult)
    
    def test_harmonics_extraction(self):
        """测试谐波提取"""
        data = create_oscillator_data()
        result = metrics_extractor.get_metric_by_name(data, "harmonics")
        
        assert isinstance(result, MetricResult)


# ============================================================
# 运行测试
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
