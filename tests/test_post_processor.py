# Test PostProcessor - Simulation Data Post-Processing Tests
"""
仿真数据后处理模块测试

测试内容：
- 极零点提取
- 群延迟计算
- 相位裕度和增益裕度计算
- 数据插值和平滑
- 均匀重采样
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import numpy as np
import pytest

from domain.simulation.analysis.post_processor import (
    PostProcessor,
    PoleZeroResult,
    GroupDelayResult,
    PhaseMarginResult,
)


class TestPostProcessor:
    """PostProcessor 测试类"""
    
    @pytest.fixture
    def processor(self):
        """创建 PostProcessor 实例"""
        return PostProcessor()
    
    @pytest.fixture
    def simple_lowpass_data(self):
        """
        生成简单一阶低通滤波器的频率响应数据
        
        H(s) = 1 / (1 + s/ω0)，ω0 = 2π * 1000 Hz
        """
        f0 = 1000.0  # 截止频率
        frequencies = np.logspace(1, 5, 100)  # 10 Hz to 100 kHz
        
        # 一阶低通响应
        s = 1j * 2 * np.pi * frequencies
        omega0 = 2 * np.pi * f0
        h = 1 / (1 + s / omega0)
        
        magnitude_db = 20 * np.log10(np.abs(h))
        phase_deg = np.rad2deg(np.angle(h))
        
        return frequencies, magnitude_db, phase_deg, f0
    
    @pytest.fixture
    def second_order_data(self):
        """
        生成二阶低通滤波器的频率响应数据
        
        H(s) = ω0² / (s² + 2ζω0s + ω0²)
        """
        f0 = 1000.0  # 自然频率
        zeta = 0.5   # 阻尼比
        frequencies = np.logspace(1, 5, 200)
        
        omega0 = 2 * np.pi * f0
        s = 1j * 2 * np.pi * frequencies
        h = omega0**2 / (s**2 + 2 * zeta * omega0 * s + omega0**2)
        
        magnitude_db = 20 * np.log10(np.abs(h))
        phase_deg = np.rad2deg(np.angle(h))
        
        return frequencies, magnitude_db, phase_deg, f0, zeta
    
    # ============================================================
    # 极零点提取测试
    # ============================================================
    
    def test_find_poles_zeros_first_order(self, processor, simple_lowpass_data):
        """测试一阶系统极零点提取"""
        frequencies, magnitude_db, phase_deg, f0 = simple_lowpass_data
        
        result = processor.find_poles_zeros(
            frequencies, magnitude_db, phase_deg, order=1
        )
        
        assert result.success
        # 应该能找到至少一个极点
        assert len(result.poles) >= 1 or len(result.natural_frequencies) >= 1
    
    def test_find_poles_zeros_second_order(self, processor, second_order_data):
        """测试二阶系统极零点提取"""
        frequencies, magnitude_db, phase_deg, f0, zeta = second_order_data
        
        result = processor.find_poles_zeros(
            frequencies, magnitude_db, phase_deg, order=2
        )
        
        assert result.success
        # 应该能找到极点
        assert len(result.poles) >= 1 or result.dominant_pole is not None
    
    def test_find_poles_zeros_insufficient_data(self, processor):
        """测试数据点不足的情况"""
        frequencies = np.array([100, 1000])
        magnitude_db = np.array([0, -3])
        phase_deg = np.array([0, -45])
        
        result = processor.find_poles_zeros(
            frequencies, magnitude_db, phase_deg, order=4
        )
        
        assert not result.success
        assert "数据点不足" in result.error_message
    
    def test_pole_zero_result_serialization(self):
        """测试 PoleZeroResult 序列化"""
        result = PoleZeroResult(
            poles=[complex(-1000, 500), complex(-1000, -500)],
            zeros=[complex(-500, 0)],
            dc_gain=1.0,
            dominant_pole=complex(-1000, 500),
            quality_factors=[0.5],
            natural_frequencies=[1000.0],
            success=True,
        )
        
        data = result.to_dict()
        restored = PoleZeroResult.from_dict(data)
        
        assert len(restored.poles) == 2
        assert len(restored.zeros) == 1
        assert restored.dc_gain == 1.0
        assert restored.success
    
    # ============================================================
    # 群延迟测试
    # ============================================================
    
    def test_compute_group_delay_first_order(self, processor, simple_lowpass_data):
        """测试一阶系统群延迟计算"""
        frequencies, magnitude_db, phase_deg, f0 = simple_lowpass_data
        
        result = processor.compute_group_delay(frequencies, phase_deg)
        
        assert result.success
        assert len(result.frequencies) == len(frequencies)
        assert len(result.group_delay) == len(frequencies)
        
        # 一阶低通的群延迟在低频应该接近 1/(2πf0)
        expected_low_freq_delay = 1 / (2 * np.pi * f0)
        
        # 检查低频群延迟（前几个点）
        low_freq_delay = np.mean(result.group_delay[:5])
        # 允许较大误差，因为数值微分有误差
        assert abs(low_freq_delay - expected_low_freq_delay) / expected_low_freq_delay < 0.5
    
    def test_compute_group_delay_insufficient_data(self, processor):
        """测试数据点不足的情况"""
        frequencies = np.array([100, 1000])
        phase_deg = np.array([0, -45])
        
        result = processor.compute_group_delay(frequencies, phase_deg)
        
        assert not result.success
        assert "数据点不足" in result.error_message
    
    def test_group_delay_result_serialization(self):
        """测试 GroupDelayResult 序列化"""
        result = GroupDelayResult(
            frequencies=np.array([100, 1000, 10000]),
            group_delay=np.array([1e-4, 1e-5, 1e-6]),
            max_delay=1e-4,
            min_delay=1e-6,
            avg_delay=5e-5,
            delay_variation=9e-5,
            success=True,
        )
        
        data = result.to_dict()
        restored = GroupDelayResult.from_dict(data)
        
        assert len(restored.frequencies) == 3
        assert restored.max_delay == 1e-4
        assert restored.success
    
    # ============================================================
    # 相位裕度测试
    # ============================================================
    
    def test_compute_phase_margin_stable_system(self, processor):
        """测试稳定系统的相位裕度计算"""
        # 创建一个稳定的开环传递函数响应
        # 简单的积分器 + 一阶滞后
        frequencies = np.logspace(0, 6, 500)
        
        # 模拟一个典型运放的开环响应
        # 低频增益 100dB，主极点 10Hz，单位增益频率约 1MHz
        f_pole = 10.0
        dc_gain_db = 100.0
        
        s = 1j * 2 * np.pi * frequencies
        omega_pole = 2 * np.pi * f_pole
        
        # H(s) = A0 / (1 + s/ω_pole)
        h = 10**(dc_gain_db/20) / (1 + s / omega_pole)
        
        magnitude_db = 20 * np.log10(np.abs(h))
        phase_deg = np.rad2deg(np.angle(h))
        
        result = processor.compute_phase_margin(frequencies, magnitude_db, phase_deg)
        
        assert result.success
        # 一阶系统在单位增益频率处相位应该接近 -90°
        # 所以相位裕度应该接近 90°
        assert result.phase_margin_deg > 45  # 至少 45° 裕度
        assert result.unity_gain_freq > 0
    
    def test_compute_phase_margin_insufficient_data(self, processor):
        """测试数据点不足的情况"""
        frequencies = np.array([100, 1000])
        magnitude_db = np.array([20, 0])
        phase_deg = np.array([-90, -135])
        
        result = processor.compute_phase_margin(frequencies, magnitude_db, phase_deg)
        
        assert not result.success
    
    def test_phase_margin_result_serialization(self):
        """测试 PhaseMarginResult 序列化"""
        result = PhaseMarginResult(
            phase_margin_deg=60.0,
            gain_margin_db=10.0,
            unity_gain_freq=1e6,
            phase_crossover_freq=5e6,
            is_stable=True,
            success=True,
        )
        
        data = result.to_dict()
        restored = PhaseMarginResult.from_dict(data)
        
        assert restored.phase_margin_deg == 60.0
        assert restored.gain_margin_db == 10.0
        assert restored.is_stable
    
    # ============================================================
    # 数据插值测试
    # ============================================================
    
    def test_interpolate_linear(self, processor):
        """测试线性插值"""
        x = np.array([0, 1, 2, 3, 4])
        y = np.array([0, 2, 4, 6, 8])
        new_x = np.array([0.5, 1.5, 2.5, 3.5])
        
        result = processor.interpolate_data(x, y, new_x, method="linear")
        
        expected = np.array([1, 3, 5, 7])
        np.testing.assert_array_almost_equal(result, expected)
    
    def test_interpolate_cubic(self, processor):
        """测试三次样条插值"""
        x = np.array([0, 1, 2, 3, 4, 5])
        y = np.sin(x)
        new_x = np.array([0.5, 1.5, 2.5, 3.5, 4.5])
        
        result = processor.interpolate_data(x, y, new_x, method="cubic")
        
        # 检查插值结果在合理范围内
        assert all(result >= -1.1) and all(result <= 1.1)
    
    def test_interpolate_insufficient_data(self, processor):
        """测试数据点不足的情况"""
        x = np.array([0])
        y = np.array([1])
        new_x = np.array([0.5])
        
        result = processor.interpolate_data(x, y, new_x)
        
        assert np.isnan(result[0])
    
    # ============================================================
    # 数据平滑测试
    # ============================================================
    
    def test_smooth_moving_average(self, processor):
        """测试移动平均平滑"""
        # 创建带噪声的数据
        np.random.seed(42)
        x = np.linspace(0, 10, 100)
        y_clean = np.sin(x)
        y_noisy = y_clean + np.random.normal(0, 0.1, len(x))
        
        result = processor.smooth_data(y_noisy, window_size=5, method="moving_average")
        
        # 平滑后的数据应该更接近原始干净数据
        error_noisy = np.mean((y_noisy - y_clean)**2)
        error_smoothed = np.mean((result - y_clean)**2)
        
        assert error_smoothed < error_noisy
    
    def test_smooth_savgol(self, processor):
        """测试 Savitzky-Golay 平滑"""
        np.random.seed(42)
        x = np.linspace(0, 10, 100)
        y_clean = np.sin(x)
        y_noisy = y_clean + np.random.normal(0, 0.1, len(x))
        
        result = processor.smooth_data(y_noisy, window_size=7, method="savgol")
        
        # 平滑后的数据应该更接近原始干净数据
        error_noisy = np.mean((y_noisy - y_clean)**2)
        error_smoothed = np.mean((result - y_clean)**2)
        
        assert error_smoothed < error_noisy
    
    def test_smooth_short_data(self, processor):
        """测试短数据的平滑"""
        data = np.array([1, 2, 3])
        
        result = processor.smooth_data(data, window_size=5)
        
        # 数据太短，应该返回原数据
        np.testing.assert_array_equal(result, data)
    
    # ============================================================
    # 均匀重采样测试
    # ============================================================
    
    def test_resample_uniform(self, processor):
        """测试均匀重采样"""
        # 非均匀采样的数据
        time = np.array([0, 0.1, 0.15, 0.3, 0.5, 0.8, 1.0])
        signal_data = np.sin(2 * np.pi * time)
        
        new_time, new_signal = processor.resample_uniform(time, signal_data, num_points=11)
        
        # 检查新时间是均匀的
        dt = np.diff(new_time)
        assert np.allclose(dt, dt[0])
        
        # 检查点数正确
        assert len(new_time) == 11
        assert len(new_signal) == 11
        
        # 检查边界值
        assert new_time[0] == time[0]
        assert new_time[-1] == time[-1]
    
    def test_resample_short_data(self, processor):
        """测试短数据的重采样"""
        time = np.array([0])
        signal_data = np.array([1])
        
        new_time, new_signal = processor.resample_uniform(time, signal_data, num_points=10)
        
        # 数据太短，应该返回原数据
        np.testing.assert_array_equal(new_time, time)
        np.testing.assert_array_equal(new_signal, signal_data)


class TestCrossoverFinding:
    """穿越点查找测试"""
    
    @pytest.fixture
    def processor(self):
        return PostProcessor()
    
    def test_find_crossover_simple(self, processor):
        """测试简单穿越点查找"""
        x = np.array([1, 2, 3, 4, 5])
        y = np.array([-2, -1, 0, 1, 2])
        
        crossover = processor._find_crossover(x, y, 0.0)
        
        assert crossover == 3.0
    
    def test_find_crossover_interpolated(self, processor):
        """测试需要插值的穿越点"""
        x = np.array([1, 2, 3, 4, 5])
        y = np.array([-2, -1, 1, 2, 3])  # 在 x=2 和 x=3 之间穿越 0
        
        crossover = processor._find_crossover(x, y, 0.0)
        
        # 应该在 2 和 3 之间
        assert 2 < crossover < 3
        # 线性插值：x = 2 + (0 - (-1)) * (3 - 2) / (1 - (-1)) = 2.5
        assert abs(crossover - 2.5) < 0.01
    
    def test_find_crossover_no_crossing(self, processor):
        """测试没有穿越点的情况"""
        x = np.array([1, 2, 3, 4, 5])
        y = np.array([1, 2, 3, 4, 5])  # 全部大于 0
        
        crossover = processor._find_crossover(x, y, 0.0)
        
        assert crossover == 0.0


class TestInterpolateValue:
    """插值取值测试"""
    
    @pytest.fixture
    def processor(self):
        return PostProcessor()
    
    def test_interpolate_value_exact(self, processor):
        """测试精确点的插值"""
        x = np.array([1, 2, 3, 4, 5])
        y = np.array([10, 20, 30, 40, 50])
        
        value = processor._interpolate_value(x, y, 3.0)
        
        assert value == 30.0
    
    def test_interpolate_value_between(self, processor):
        """测试中间点的插值"""
        x = np.array([1, 2, 3, 4, 5])
        y = np.array([10, 20, 30, 40, 50])
        
        value = processor._interpolate_value(x, y, 2.5)
        
        assert value == 25.0
    
    def test_interpolate_value_boundary(self, processor):
        """测试边界点的插值"""
        x = np.array([1, 2, 3, 4, 5])
        y = np.array([10, 20, 30, 40, 50])
        
        # 小于最小值
        value_low = processor._interpolate_value(x, y, 0.5)
        assert value_low == 10.0
        
        # 大于最大值
        value_high = processor._interpolate_value(x, y, 6.0)
        assert value_high == 50.0
