# test_distortion_metrics.py - Tests for Distortion Metrics Extraction
"""
失真指标提取模块测试

测试内容：
- THD 提取
- THD+N 提取
- IMD 提取
- SFDR 提取
- SNDR 提取
- ENOB 提取
- 谐波分析
"""

import numpy as np
import pytest

from domain.simulation.metrics.distortion_metrics import (
    DistortionMetrics,
    distortion_metrics,
)
from domain.simulation.metrics.metric_result import MetricCategory
from domain.simulation.models.simulation_result import SimulationData


class TestDistortionMetrics:
    """失真指标提取器测试"""
    
    @pytest.fixture
    def extractor(self):
        """创建提取器实例"""
        return DistortionMetrics()
    
    @pytest.fixture
    def pure_sine_data(self):
        """创建纯正弦波测试数据"""
        fs = 100000  # 100kHz 采样率
        duration = 0.1  # 100ms
        f0 = 1000  # 1kHz 基波
        
        t = np.linspace(0, duration, int(fs * duration), endpoint=False)
        signal = np.sin(2 * np.pi * f0 * t)
        
        return SimulationData(
            frequency=None,
            time=t,
            signals={"V(out)": signal}
        )
    
    @pytest.fixture
    def distorted_sine_data(self):
        """创建带谐波失真的正弦波测试数据"""
        fs = 100000
        duration = 0.1
        f0 = 1000
        
        t = np.linspace(0, duration, int(fs * duration), endpoint=False)
        
        # 基波 + 2次谐波(10%) + 3次谐波(5%)
        signal = (
            1.0 * np.sin(2 * np.pi * f0 * t) +
            0.1 * np.sin(2 * np.pi * 2 * f0 * t) +
            0.05 * np.sin(2 * np.pi * 3 * f0 * t)
        )
        
        return SimulationData(
            frequency=None,
            time=t,
            signals={"V(out)": signal}
        )
    
    @pytest.fixture
    def two_tone_data(self):
        """创建双音测试数据"""
        fs = 100000
        duration = 0.1
        f1 = 1000
        f2 = 1100
        
        t = np.linspace(0, duration, int(fs * duration), endpoint=False)
        
        # 双音信号 + 互调产物
        signal = (
            0.5 * np.sin(2 * np.pi * f1 * t) +
            0.5 * np.sin(2 * np.pi * f2 * t) +
            0.02 * np.sin(2 * np.pi * (2 * f1 - f2) * t) +  # IM3
            0.02 * np.sin(2 * np.pi * (2 * f2 - f1) * t)    # IM3
        )
        
        return SimulationData(
            frequency=None,
            time=t,
            signals={"V(out)": signal}
        )

    # ============================================================
    # THD 测试
    # ============================================================
    
    def test_extract_thd_pure_sine(self, extractor, pure_sine_data):
        """测试纯正弦波的 THD（应接近 0）"""
        result = extractor.extract_thd(
            pure_sine_data,
            output_signal="V(out)",
            fundamental_freq=1000
        )
        
        assert result.is_valid
        assert result.name == "thd"
        assert result.category == MetricCategory.DISTORTION
        assert result.unit == "%"
        # 纯正弦波 THD 应该很小（< 0.1%）
        assert result.value < 0.1
    
    def test_extract_thd_distorted_sine(self, extractor, distorted_sine_data):
        """测试带谐波失真的正弦波 THD"""
        result = extractor.extract_thd(
            distorted_sine_data,
            output_signal="V(out)",
            fundamental_freq=1000
        )
        
        assert result.is_valid
        # THD = sqrt(0.1^2 + 0.05^2) / 1.0 * 100 ≈ 11.18%
        expected_thd = np.sqrt(0.1**2 + 0.05**2) * 100
        assert abs(result.value - expected_thd) < 1.0  # 允许 1% 误差
    
    def test_extract_thd_auto_detect_freq(self, extractor, distorted_sine_data):
        """测试自动检测基波频率"""
        result = extractor.extract_thd(
            distorted_sine_data,
            output_signal="V(out)",
            fundamental_freq=None  # 自动检测
        )
        
        assert result.is_valid
        assert "fundamental_freq" in result.metadata
        # 检测到的频率应接近 1000Hz
        assert abs(result.metadata["fundamental_freq"] - 1000) < 10
    
    def test_extract_thd_missing_signal(self, extractor, pure_sine_data):
        """测试信号不存在的情况"""
        result = extractor.extract_thd(
            pure_sine_data,
            output_signal="V(nonexistent)"
        )
        
        assert not result.is_valid
        assert result.error_message is not None
        assert "未找到" in result.error_message
    
    def test_extract_thd_insufficient_data(self, extractor):
        """测试数据点不足的情况"""
        data = SimulationData(
            frequency=None,
            time=np.linspace(0, 0.001, 100),  # 只有 100 点
            signals={"V(out)": np.sin(np.linspace(0, 2*np.pi, 100))}
        )
        
        result = extractor.extract_thd(data, output_signal="V(out)")
        
        assert not result.is_valid
        assert "数据点不足" in result.error_message

    # ============================================================
    # THD+N 测试
    # ============================================================
    
    def test_extract_thd_n(self, extractor, distorted_sine_data):
        """测试 THD+N 提取"""
        result = extractor.extract_thd_n(
            distorted_sine_data,
            output_signal="V(out)",
            fundamental_freq=1000
        )
        
        assert result.is_valid
        assert result.name == "thd_n"
        assert result.unit == "%"
        # THD+N 应该 >= THD
        thd_result = extractor.extract_thd(
            distorted_sine_data,
            output_signal="V(out)",
            fundamental_freq=1000
        )
        assert result.value >= thd_result.value - 0.5  # 允许小误差

    # ============================================================
    # IMD 测试
    # ============================================================
    
    def test_extract_imd(self, extractor, two_tone_data):
        """测试互调失真提取"""
        result = extractor.extract_imd(
            two_tone_data,
            output_signal="V(out)",
            f1=1000,
            f2=1100
        )
        
        assert result.is_valid
        assert result.name == "imd"
        assert result.unit == "%"
        assert result.value > 0
        assert "im_products" in result.metadata

    # ============================================================
    # SFDR 测试
    # ============================================================
    
    def test_extract_sfdr_pure_sine(self, extractor, pure_sine_data):
        """测试纯正弦波的 SFDR（应该很高）"""
        result = extractor.extract_sfdr(
            pure_sine_data,
            output_signal="V(out)",
            fundamental_freq=1000
        )
        
        assert result.is_valid
        assert result.name == "sfdr"
        assert result.unit == "dB"
        # 纯正弦波 SFDR 应该很高（> 60dB）
        assert result.value > 60
    
    def test_extract_sfdr_distorted(self, extractor, distorted_sine_data):
        """测试带失真信号的 SFDR"""
        result = extractor.extract_sfdr(
            distorted_sine_data,
            output_signal="V(out)",
            fundamental_freq=1000
        )
        
        assert result.is_valid
        # SFDR = 20*log10(1.0/0.1) = 20dB
        expected_sfdr = 20 * np.log10(1.0 / 0.1)
        assert abs(result.value - expected_sfdr) < 3  # 允许 3dB 误差

    # ============================================================
    # SNDR 测试
    # ============================================================
    
    def test_extract_sndr(self, extractor, distorted_sine_data):
        """测试 SNDR 提取"""
        result = extractor.extract_sndr(
            distorted_sine_data,
            output_signal="V(out)",
            fundamental_freq=1000
        )
        
        assert result.is_valid
        assert result.name == "sndr"
        assert result.unit == "dB"
        assert result.value > 0

    # ============================================================
    # ENOB 测试
    # ============================================================
    
    def test_extract_enob(self, extractor, distorted_sine_data):
        """测试 ENOB 提取"""
        result = extractor.extract_enob(
            distorted_sine_data,
            output_signal="V(out)",
            fundamental_freq=1000
        )
        
        assert result.is_valid
        assert result.name == "enob"
        assert result.unit == "bits"
        assert result.value >= 0
        assert "sndr_db" in result.metadata

    # ============================================================
    # 谐波分析测试
    # ============================================================
    
    def test_extract_harmonics(self, extractor, distorted_sine_data):
        """测试谐波分析"""
        fundamental, harmonics = extractor.extract_harmonics(
            distorted_sine_data,
            output_signal="V(out)",
            fundamental_freq=1000,
            num_harmonics=5
        )
        
        assert fundamental.is_valid
        assert fundamental.name == "fundamental"
        assert abs(fundamental.value - 1.0) < 0.1  # 基波幅度约 1V
        
        assert len(harmonics) >= 2  # 至少有 2 次和 3 次谐波
        
        # 2 次谐波约 -20dBc (10%)
        h2 = harmonics[0]
        assert h2.name == "harmonic_2"
        assert h2.unit == "dBc"
        assert abs(h2.value - (-20)) < 3  # 允许 3dB 误差
        
        # 3 次谐波约 -26dBc (5%)
        h3 = harmonics[1]
        assert h3.name == "harmonic_3"
        assert abs(h3.value - (-26)) < 3

    # ============================================================
    # 窗函数测试
    # ============================================================
    
    def test_different_windows(self, extractor, distorted_sine_data):
        """测试不同窗函数"""
        windows = ["hann", "hamming", "blackman", "none"]
        results = []
        
        for window in windows:
            result = extractor.extract_thd(
                distorted_sine_data,
                output_signal="V(out)",
                fundamental_freq=1000,
                window=window
            )
            assert result.is_valid
            results.append(result.value)
        
        # 所有窗函数应该给出相近的结果
        assert max(results) - min(results) < 2.0  # 差异 < 2%

    # ============================================================
    # 模块级单例测试
    # ============================================================
    
    def test_module_singleton(self):
        """测试模块级单例"""
        assert distortion_metrics is not None
        assert isinstance(distortion_metrics, DistortionMetrics)


class TestDistortionMetricsEdgeCases:
    """边界情况测试"""
    
    @pytest.fixture
    def extractor(self):
        return DistortionMetrics()
    
    def test_dc_signal(self, extractor):
        """测试直流信号"""
        t = np.linspace(0, 0.1, 10000)
        signal = np.ones_like(t) * 1.0  # 纯直流
        
        data = SimulationData(
            frequency=None,
            time=t,
            signals={"V(out)": signal}
        )
        
        result = extractor.extract_thd(data, output_signal="V(out)")
        
        # 直流信号无法检测基波
        assert not result.is_valid or result.value < 0.01
    
    def test_very_low_amplitude(self, extractor):
        """测试极低幅度信号"""
        t = np.linspace(0, 0.1, 10000)
        signal = 1e-15 * np.sin(2 * np.pi * 1000 * t)
        
        data = SimulationData(
            frequency=None,
            time=t,
            signals={"V(out)": signal}
        )
        
        result = extractor.extract_thd(data, output_signal="V(out)")
        
        # 应该返回错误或处理极小值
        assert not result.is_valid or result.value is not None
    
    def test_high_frequency_signal(self, extractor):
        """测试高频信号（接近奈奎斯特频率）"""
        fs = 100000
        f0 = 40000  # 接近 fs/2
        t = np.linspace(0, 0.1, int(fs * 0.1), endpoint=False)
        signal = np.sin(2 * np.pi * f0 * t)
        
        data = SimulationData(
            frequency=None,
            time=t,
            signals={"V(out)": signal}
        )
        
        result = extractor.extract_thd(
            data,
            output_signal="V(out)",
            fundamental_freq=f0,
            num_harmonics=2  # 只分析 2 次谐波（会超过奈奎斯特）
        )
        
        assert result.is_valid
        # 高频时谐波会被截断
        assert result.metadata["num_harmonics"] <= 1
    
    def test_noisy_signal(self, extractor):
        """测试带噪声的信号"""
        fs = 100000
        t = np.linspace(0, 0.1, int(fs * 0.1), endpoint=False)
        
        # 信号 + 噪声
        np.random.seed(42)
        signal = np.sin(2 * np.pi * 1000 * t) + 0.01 * np.random.randn(len(t))
        
        data = SimulationData(
            frequency=None,
            time=t,
            signals={"V(out)": signal}
        )
        
        result = extractor.extract_thd(
            data,
            output_signal="V(out)",
            fundamental_freq=1000
        )
        
        assert result.is_valid
        # 噪声会略微增加 THD
        assert result.value < 5.0  # 但不应该太大
