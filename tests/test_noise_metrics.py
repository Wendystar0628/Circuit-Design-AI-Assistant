# Test NoiseMetrics - Noise Performance Metrics Extraction Tests
"""
噪声指标提取测试

测试内容：
- 输入噪声密度提取
- 输出噪声密度提取
- 积分噪声计算
- 噪声系数提取
- 信噪比计算
- 1/f 角频率提取
- 等效噪声带宽计算
- 错误处理
"""

import numpy as np
import pytest

from domain.simulation.metrics.noise_metrics import NoiseMetrics, noise_metrics
from domain.simulation.metrics.metric_result import MetricCategory
from domain.simulation.models.simulation_result import SimulationData


class TestNoiseMetricsInputNoise:
    """测试输入噪声密度提取"""
    
    def test_extract_input_noise_basic(self):
        """测试基本输入噪声密度提取"""
        freq = np.logspace(1, 6, 100)  # 10Hz - 1MHz
        # 恒定噪声密度 10 nV/√Hz
        noise_density = 10e-9 * np.ones_like(freq)
        
        data = SimulationData(
            frequency=freq,
            signals={"inoise": noise_density}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_input_noise(data)
        
        assert result.is_valid
        assert result.name == "input_noise"
        assert result.category == MetricCategory.NOISE
        assert abs(result.value - 10.0) < 0.1  # 约 10 nV/√Hz
        assert result.unit == "nV/√Hz"
    
    def test_extract_input_noise_at_frequency(self):
        """测试指定频率的噪声密度提取"""
        freq = np.logspace(1, 6, 100)
        # 1/f 噪声 + 白噪声
        white_noise = 5e-9  # 5 nV/√Hz
        flicker_corner = 1000  # 1kHz 角频率
        noise_density = white_noise * np.sqrt(1 + flicker_corner / freq)
        
        data = SimulationData(
            frequency=freq,
            signals={"inoise": noise_density}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_input_noise(data, freq_point=100000)  # 100kHz
        
        assert result.is_valid
        # 高频处接近白噪声
        assert 4 < result.value < 6
    
    def test_extract_input_noise_no_frequency_data(self):
        """测试无频率数据时的错误处理"""
        data = SimulationData(
            frequency=None,
            signals={"inoise": np.array([1e-9, 2e-9])}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_input_noise(data)
        
        assert not result.is_valid
        assert "无噪声分析频率数据" in result.error_message
    
    def test_extract_input_noise_missing_signal(self):
        """测试缺少信号时的错误处理"""
        data = SimulationData(
            frequency=np.array([100, 1000, 10000]),
            signals={}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_input_noise(data)
        
        assert not result.is_valid
        assert "未找到噪声信号" in result.error_message
    
    def test_extract_input_noise_alternative_signal_name(self):
        """测试替代信号名称"""
        freq = np.logspace(1, 6, 100)
        noise_density = 8e-9 * np.ones_like(freq)
        
        data = SimulationData(
            frequency=freq,
            signals={"inoise_total": noise_density}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_input_noise(data)
        
        assert result.is_valid
        assert abs(result.value - 8.0) < 0.1


class TestNoiseMetricsOutputNoise:
    """测试输出噪声密度提取"""
    
    def test_extract_output_noise_basic(self):
        """测试基本输出噪声密度提取"""
        freq = np.logspace(1, 6, 100)
        noise_density = 100e-9 * np.ones_like(freq)  # 100 nV/√Hz
        
        data = SimulationData(
            frequency=freq,
            signals={"onoise": noise_density}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_output_noise(data)
        
        assert result.is_valid
        assert result.name == "output_noise"
        assert abs(result.value - 100.0) < 1.0


class TestNoiseMetricsIntegratedNoise:
    """测试积分噪声提取"""
    
    def test_extract_integrated_noise_white(self):
        """测试白噪声积分"""
        freq = np.logspace(1, 5, 200)  # 10Hz - 100kHz
        # 恒定噪声密度 10 nV/√Hz
        noise_density = 10e-9 * np.ones_like(freq)
        
        data = SimulationData(
            frequency=freq,
            signals={"inoise": noise_density}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_integrated_noise(data)
        
        assert result.is_valid
        assert result.name == "integrated_noise"
        assert result.unit == "μV"
        # 积分噪声 = 10nV/√Hz × √(100kHz - 10Hz) ≈ 3.16 μV
        assert 2.5 < result.value < 4.0
    
    def test_extract_integrated_noise_with_range(self):
        """测试指定频率范围的积分噪声"""
        freq = np.logspace(1, 6, 200)
        noise_density = 10e-9 * np.ones_like(freq)
        
        data = SimulationData(
            frequency=freq,
            signals={"inoise": noise_density}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_integrated_noise(
            data, freq_range=(100, 10000)
        )
        
        assert result.is_valid
        # 积分噪声 = 10nV/√Hz × √(10kHz - 100Hz) ≈ 0.995 μV
        assert 0.8 < result.value < 1.2
    
    def test_extract_integrated_noise_insufficient_data(self):
        """测试数据不足时的错误处理"""
        data = SimulationData(
            frequency=np.array([100]),  # 只有一个点
            signals={"inoise": np.array([10e-9])}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_integrated_noise(data)
        
        assert not result.is_valid
        assert "数据不足" in result.error_message


class TestNoiseMetricsNoiseFigure:
    """测试噪声系数提取"""
    
    def test_extract_noise_figure_basic(self):
        """测试基本噪声系数提取"""
        freq = np.logspace(1, 6, 100)
        # 输入噪声密度 1 nV/√Hz
        # 50Ω 源电阻在 290K 的热噪声密度 ≈ 0.9 nV/√Hz
        noise_density = 1e-9 * np.ones_like(freq)
        
        data = SimulationData(
            frequency=freq,
            signals={"inoise": noise_density}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_noise_figure(
            data, source_resistance=50.0, temperature=290.0
        )
        
        assert result.is_valid
        assert result.name == "noise_figure"
        assert result.unit == "dB"
        # NF 应该是正值
        assert result.value > 0
    
    def test_extract_noise_figure_low_noise(self):
        """测试低噪声放大器的噪声系数"""
        freq = np.logspace(1, 6, 100)
        # 非常低的噪声密度
        noise_density = 0.5e-9 * np.ones_like(freq)  # 0.5 nV/√Hz
        
        data = SimulationData(
            frequency=freq,
            signals={"inoise": noise_density}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_noise_figure(
            data, source_resistance=50.0
        )
        
        assert result.is_valid
        # 低噪声放大器 NF 应该较小
        assert result.value < 3.0  # 小于 3dB
    
    def test_extract_noise_figure_different_source_resistance(self):
        """测试不同源电阻的噪声系数"""
        freq = np.logspace(1, 6, 100)
        noise_density = 2e-9 * np.ones_like(freq)
        
        data = SimulationData(
            frequency=freq,
            signals={"inoise": noise_density}
        )
        
        extractor = NoiseMetrics()
        
        # 50Ω 源电阻
        result_50 = extractor.extract_noise_figure(data, source_resistance=50.0)
        
        # 1kΩ 源电阻
        result_1k = extractor.extract_noise_figure(data, source_resistance=1000.0)
        
        assert result_50.is_valid
        assert result_1k.is_valid
        # 更高的源电阻意味着更高的热噪声，所以 NF 更低
        assert result_1k.value < result_50.value


class TestNoiseMetricsSNR:
    """测试信噪比提取"""
    
    def test_extract_snr_basic(self):
        """测试基本信噪比计算"""
        freq = np.logspace(1, 5, 200)  # 10Hz - 100kHz
        noise_density = 10e-9 * np.ones_like(freq)  # 10 nV/√Hz
        
        data = SimulationData(
            frequency=freq,
            signals={"inoise": noise_density}
        )
        
        extractor = NoiseMetrics()
        # 信号电平 1mV
        result = extractor.extract_snr(data, signal_level=1e-3)
        
        assert result.is_valid
        assert result.name == "snr"
        assert result.unit == "dB"
        # SNR = 20*log10(1mV / ~3μV) ≈ 50dB
        assert 45 < result.value < 55
    
    def test_extract_snr_with_freq_range(self):
        """测试指定频率范围的信噪比"""
        freq = np.logspace(1, 6, 200)
        noise_density = 10e-9 * np.ones_like(freq)
        
        data = SimulationData(
            frequency=freq,
            signals={"inoise": noise_density}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_snr(
            data, 
            signal_level=1e-3,
            freq_range=(20, 20000)  # 音频带宽
        )
        
        assert result.is_valid
        # 更窄的带宽意味着更低的噪声，更高的 SNR
        assert result.value > 50
    
    def test_extract_snr_zero_signal(self):
        """测试零信号电平时的错误处理"""
        freq = np.logspace(1, 5, 100)
        noise_density = 10e-9 * np.ones_like(freq)
        
        data = SimulationData(
            frequency=freq,
            signals={"inoise": noise_density}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_snr(data, signal_level=0)
        
        assert not result.is_valid
        assert "信号电平必须大于 0" in result.error_message


class TestNoiseMetricsCornerFrequency:
    """测试 1/f 角频率提取"""
    
    def test_extract_corner_frequency(self):
        """测试 1/f 角频率提取"""
        freq = np.logspace(0, 6, 300)  # 1Hz - 1MHz
        # 1/f 噪声 + 白噪声模型
        white_noise = 5e-9  # 5 nV/√Hz
        corner_freq = 1000  # 1kHz 角频率
        # 在角频率处，1/f 噪声 = 白噪声
        noise_density = white_noise * np.sqrt(1 + corner_freq / freq)
        
        data = SimulationData(
            frequency=freq,
            signals={"inoise": noise_density}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_corner_frequency(data)
        
        assert result.is_valid
        assert result.name == "corner_frequency"
        assert result.unit == "Hz"
        # 角频率应该接近 1kHz
        assert 500 < result.value < 2000
    
    def test_extract_corner_frequency_no_flicker(self):
        """测试无 1/f 噪声时的处理"""
        freq = np.logspace(1, 6, 100)
        # 纯白噪声
        noise_density = 10e-9 * np.ones_like(freq)
        
        data = SimulationData(
            frequency=freq,
            signals={"inoise": noise_density}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_corner_frequency(data)
        
        # 纯白噪声没有角频率
        assert not result.is_valid


class TestNoiseMetricsENBW:
    """测试等效噪声带宽提取"""
    
    def test_extract_enbw_lowpass(self):
        """测试低通滤波器的等效噪声带宽"""
        freq = np.logspace(1, 7, 300)  # 10Hz - 10MHz
        fc = 10000  # 10kHz 截止频率
        # 一阶低通响应
        gain = 1.0 / np.sqrt(1 + (freq / fc) ** 2)
        
        data = SimulationData(
            frequency=freq,
            signals={"V(out)": gain.astype(complex)}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_equivalent_noise_bandwidth(data)
        
        assert result.is_valid
        assert result.name == "enbw"
        assert result.unit == "Hz"
        # 一阶低通的 ENBW ≈ π/2 × fc ≈ 15.7kHz
        assert 10000 < result.value < 20000
    
    def test_extract_enbw_bandpass(self):
        """测试带通滤波器的等效噪声带宽"""
        freq = np.logspace(1, 7, 500)
        fc = 100000  # 100kHz 中心频率
        Q = 10  # 品质因数
        bw = fc / Q  # 带宽 10kHz
        
        # 二阶带通响应
        s = 1j * freq / fc
        gain = np.abs(s / (1 + s / Q + s ** 2))
        
        data = SimulationData(
            frequency=freq,
            signals={"V(out)": gain.astype(complex)}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_equivalent_noise_bandwidth(data)
        
        assert result.is_valid
        # ENBW 应该与带宽相近
        assert 5000 < result.value < 20000


class TestNoiseMetricsSingleton:
    """测试模块级单例"""
    
    def test_singleton_exists(self):
        """测试单例存在"""
        assert noise_metrics is not None
        assert isinstance(noise_metrics, NoiseMetrics)
    
    def test_singleton_works(self):
        """测试单例可用"""
        freq = np.logspace(1, 6, 100)
        noise_density = 10e-9 * np.ones_like(freq)
        
        data = SimulationData(
            frequency=freq,
            signals={"inoise": noise_density}
        )
        
        result = noise_metrics.extract_input_noise(data)
        assert result.is_valid


class TestNoiseMetricsEdgeCases:
    """测试边界情况"""
    
    def test_empty_frequency_array(self):
        """测试空频率数组"""
        data = SimulationData(
            frequency=np.array([]),
            signals={"inoise": np.array([])}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_input_noise(data)
        
        assert not result.is_valid
    
    def test_complex_noise_signal(self):
        """测试复数噪声信号（取模）"""
        freq = np.logspace(1, 6, 100)
        # 复数噪声信号
        noise_density = (10e-9 + 1j * 1e-9) * np.ones_like(freq)
        
        data = SimulationData(
            frequency=freq,
            signals={"inoise": noise_density}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_input_noise(data)
        
        assert result.is_valid
        # 应该取模
        assert abs(result.value - 10.05) < 0.5
    
    def test_negative_noise_values(self):
        """测试负噪声值（取绝对值）"""
        freq = np.logspace(1, 6, 100)
        # 负值噪声（不应该出现，但要处理）
        noise_density = -10e-9 * np.ones_like(freq)
        
        data = SimulationData(
            frequency=freq,
            signals={"inoise": noise_density}
        )
        
        extractor = NoiseMetrics()
        result = extractor.extract_input_noise(data)
        
        assert result.is_valid
        # 应该取绝对值
        assert result.value > 0
