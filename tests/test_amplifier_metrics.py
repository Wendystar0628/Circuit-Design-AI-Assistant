# Test AmplifierMetrics - Amplifier Performance Metrics Extraction Tests
"""
放大器指标提取测试

测试内容：
- AC 分析指标提取（增益、带宽、相位裕度等）
- 瞬态分析指标提取（压摆率、建立时间、过冲等）
- DC 分析指标提取（失调电压）
- 错误处理
"""

import numpy as np
import pytest

from domain.simulation.metrics.amplifier_metrics import AmplifierMetrics, amplifier_metrics
from domain.simulation.metrics.metric_result import MetricCategory
from domain.simulation.models.simulation_result import SimulationData


class TestAmplifierMetricsGain:
    """测试增益提取"""
    
    def test_extract_gain_basic(self):
        """测试基本增益提取"""
        # 创建模拟 AC 数据：10 倍增益（20dB）
        freq = np.logspace(1, 6, 100)  # 10Hz - 1MHz
        gain_linear = 10.0 * np.ones_like(freq)  # 恒定 10 倍增益
        output = gain_linear.astype(complex)
        
        data = SimulationData(
            frequency=freq,
            signals={"V(out)": output}
        )
        
        extractor = AmplifierMetrics()
        result = extractor.extract_gain(data, output_signal="V(out)")
        
        assert result.is_valid
        assert result.name == "gain"
        assert result.category == MetricCategory.AMPLIFIER
        assert abs(result.value - 20.0) < 0.1  # 约 20dB
    
    def test_extract_gain_at_frequency(self):
        """测试指定频率的增益提取"""
        freq = np.logspace(1, 6, 100)
        # 一阶低通响应
        fc = 10000  # 10kHz 截止频率
        gain_linear = 10.0 / np.sqrt(1 + (freq / fc) ** 2)
        output = gain_linear.astype(complex)
        
        data = SimulationData(
            frequency=freq,
            signals={"V(out)": output}
        )
        
        extractor = AmplifierMetrics()
        result = extractor.extract_gain(data, freq_point=100)  # 100Hz
        
        assert result.is_valid
        assert abs(result.value - 20.0) < 1.0  # 低频约 20dB

    def test_extract_gain_no_frequency_data(self):
        """测试无频率数据时的错误处理"""
        data = SimulationData(
            frequency=None,
            signals={"V(out)": np.array([1.0, 2.0])}
        )
        
        extractor = AmplifierMetrics()
        result = extractor.extract_gain(data)
        
        assert not result.is_valid
        assert "无 AC 分析频率数据" in result.error_message
    
    def test_extract_gain_missing_signal(self):
        """测试缺少信号时的错误处理"""
        data = SimulationData(
            frequency=np.array([100, 1000, 10000]),
            signals={}
        )
        
        extractor = AmplifierMetrics()
        result = extractor.extract_gain(data, output_signal="V(out)")
        
        assert not result.is_valid
        assert "未找到输出信号" in result.error_message


class TestAmplifierMetricsBandwidth:
    """测试带宽提取"""
    
    def test_extract_bandwidth_basic(self):
        """测试基本带宽提取"""
        freq = np.logspace(1, 7, 200)  # 10Hz - 10MHz
        fc = 100000  # 100kHz 截止频率
        # 一阶低通响应
        gain_linear = 10.0 / np.sqrt(1 + (freq / fc) ** 2)
        output = gain_linear.astype(complex)
        
        data = SimulationData(
            frequency=freq,
            signals={"V(out)": output}
        )
        
        extractor = AmplifierMetrics()
        result = extractor.extract_bandwidth(data)
        
        assert result.is_valid
        assert result.name == "bandwidth"
        # 带宽应该接近 100kHz
        assert 80000 < result.value < 120000
    
    def test_extract_bandwidth_no_3db_point(self):
        """测试无 -3dB 点时的错误处理"""
        freq = np.logspace(1, 4, 50)  # 10Hz - 10kHz
        # 恒定增益，无衰减
        gain_linear = 10.0 * np.ones_like(freq)
        output = gain_linear.astype(complex)
        
        data = SimulationData(
            frequency=freq,
            signals={"V(out)": output}
        )
        
        extractor = AmplifierMetrics()
        result = extractor.extract_bandwidth(data)
        
        assert not result.is_valid
        assert "未找到 -3dB 点" in result.error_message


class TestAmplifierMetricsGBW:
    """测试增益带宽积提取"""
    
    def test_extract_gbw(self):
        """测试 GBW 提取"""
        freq = np.logspace(1, 7, 200)
        fc = 100000  # 100kHz
        gain_dc = 10.0  # 20dB
        gain_linear = gain_dc / np.sqrt(1 + (freq / fc) ** 2)
        output = gain_linear.astype(complex)
        
        data = SimulationData(
            frequency=freq,
            signals={"V(out)": output}
        )
        
        extractor = AmplifierMetrics()
        result = extractor.extract_gbw(data)
        
        assert result.is_valid
        # GBW ≈ 10 × 100kHz = 1MHz
        assert 800000 < result.value < 1200000


class TestAmplifierMetricsPhaseMargin:
    """测试相位裕度提取"""
    
    def test_extract_phase_margin(self):
        """测试相位裕度提取"""
        freq = np.logspace(1, 8, 300)
        # 模拟运放开环响应：单极点系统
        fc = 10  # 主极点 10Hz
        fu = 1e6  # 单位增益频率 1MHz
        gain_dc = fu / fc  # DC 增益
        
        # 传递函数：A(s) = A0 / (1 + s/wc)
        s = 1j * 2 * np.pi * freq
        wc = 2 * np.pi * fc
        transfer = gain_dc / (1 + s / wc)
        
        data = SimulationData(
            frequency=freq,
            signals={"V(out)": transfer}
        )
        
        extractor = AmplifierMetrics()
        result = extractor.extract_phase_margin(data)
        
        assert result.is_valid
        # 单极点系统相位裕度约 90°
        assert 80 < result.value < 100


class TestAmplifierMetricsSlewRate:
    """测试压摆率提取"""
    
    def test_extract_slew_rate_rising(self):
        """测试上升压摆率提取"""
        # 创建阶跃响应
        time = np.linspace(0, 1e-6, 1000)  # 0-1μs
        # 线性上升：0V -> 1V in 0.5μs
        output = np.clip(time * 2e6, 0, 1)  # 2V/μs 压摆率
        
        data = SimulationData(
            time=time,
            signals={"V(out)": output}
        )
        
        extractor = AmplifierMetrics()
        rise_result, fall_result = extractor.extract_slew_rate(data)
        
        assert rise_result.is_valid
        # 压摆率约 2V/μs
        assert 1.5 < rise_result.value < 2.5
    
    def test_extract_slew_rate_no_time_data(self):
        """测试无时间数据时的错误处理"""
        data = SimulationData(
            time=None,
            signals={"V(out)": np.array([0, 1, 2])}
        )
        
        extractor = AmplifierMetrics()
        rise_result, fall_result = extractor.extract_slew_rate(data)
        
        assert not rise_result.is_valid
        assert "无瞬态分析时间数据" in rise_result.error_message


class TestAmplifierMetricsSettlingTime:
    """测试建立时间提取"""
    
    def test_extract_settling_time(self):
        """测试建立时间提取"""
        time = np.linspace(0, 1e-3, 1000)  # 0-1ms
        # 带过冲的阶跃响应
        tau = 1e-4  # 时间常数 100μs
        zeta = 0.7  # 阻尼比
        wn = 1 / tau
        wd = wn * np.sqrt(1 - zeta**2)
        
        # 二阶系统响应
        output = 1 - np.exp(-zeta * wn * time) * (
            np.cos(wd * time) + zeta / np.sqrt(1 - zeta**2) * np.sin(wd * time)
        )
        
        data = SimulationData(
            time=time,
            signals={"V(out)": output}
        )
        
        extractor = AmplifierMetrics()
        result = extractor.extract_settling_time(data, tolerance_percent=1.0)
        
        assert result.is_valid
        assert result.value > 0
        assert result.value < 1e-3  # 应该在 1ms 内建立


class TestAmplifierMetricsOvershoot:
    """测试过冲提取"""
    
    def test_extract_overshoot(self):
        """测试过冲提取"""
        time = np.linspace(0, 1e-3, 1000)
        # 带 20% 过冲的阶跃响应
        tau = 1e-4
        output = np.zeros_like(time)
        for i, t in enumerate(time):
            if t < tau:
                output[i] = 1.2 * t / tau  # 上升到 1.2
            elif t < 2 * tau:
                output[i] = 1.2 - 0.2 * (t - tau) / tau  # 下降到 1.0
            else:
                output[i] = 1.0
        
        data = SimulationData(
            time=time,
            signals={"V(out)": output}
        )
        
        extractor = AmplifierMetrics()
        result = extractor.extract_overshoot(data, final_value=1.0)
        
        assert result.is_valid
        # 过冲约 20%
        assert 15 < result.value < 25


class TestAmplifierMetricsOffsetVoltage:
    """测试失调电压提取"""
    
    def test_extract_offset_voltage(self):
        """测试失调电压提取"""
        # DC 输出有 10mV 偏移
        data = SimulationData(
            time=np.array([0, 1e-3]),
            signals={"V(out)": np.array([0.01, 0.01])}  # 10mV
        )
        
        extractor = AmplifierMetrics()
        result = extractor.extract_offset_voltage(
            data, 
            expected_output=0.0,
            gain=100  # 100 倍增益
        )
        
        assert result.is_valid
        # 输入失调 = 10mV / 100 = 100μV
        assert abs(result.value - 0.0001) < 1e-6


class TestAmplifierMetricsSingleton:
    """测试模块级单例"""
    
    def test_singleton_exists(self):
        """测试单例存在"""
        assert amplifier_metrics is not None
        assert isinstance(amplifier_metrics, AmplifierMetrics)
    
    def test_singleton_works(self):
        """测试单例可用"""
        freq = np.logspace(1, 6, 100)
        output = 10.0 * np.ones_like(freq, dtype=complex)
        
        data = SimulationData(
            frequency=freq,
            signals={"V(out)": output}
        )
        
        result = amplifier_metrics.extract_gain(data)
        assert result.is_valid
