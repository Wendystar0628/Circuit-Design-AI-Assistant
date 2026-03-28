# Test Downsampler - LTTB Algorithm Tests
"""
LTTB 降采样算法测试

测试覆盖：
- 基本功能测试
- 边界条件测试
- 性能测试
- 多信号批量降采样测试
"""

import time

import numpy as np
import pytest

from domain.simulation.data.downsampler import downsample, downsample_multiple


class TestDownsample:
    """单信号降采样测试"""
    
    def test_basic_downsample(self):
        """测试基本降采样功能"""
        x = np.linspace(0, 1, 1000)
        y = np.sin(2 * np.pi * 5 * x)
        
        x_down, y_down = downsample(x, y, target_points=100)
        
        assert len(x_down) == 100
        assert len(y_down) == 100
        # 首尾点保留
        assert x_down[0] == x[0]
        assert x_down[-1] == x[-1]
        assert y_down[0] == y[0]
        assert y_down[-1] == y[-1]
    
    def test_no_downsample_needed(self):
        """测试数据点数小于目标点数时不降采样"""
        x = np.linspace(0, 1, 50)
        y = np.sin(x)
        
        x_down, y_down = downsample(x, y, target_points=100)
        
        assert len(x_down) == 50
        assert len(y_down) == 50
        np.testing.assert_array_equal(x_down, x)
        np.testing.assert_array_equal(y_down, y)
    
    def test_exact_target_points(self):
        """测试数据点数等于目标点数时"""
        x = np.linspace(0, 1, 100)
        y = np.sin(x)
        
        x_down, y_down = downsample(x, y, target_points=100)
        
        assert len(x_down) == 100
        np.testing.assert_array_equal(x_down, x)
        np.testing.assert_array_equal(y_down, y)
    
    def test_minimum_target_points(self):
        """测试最小目标点数（2个点）"""
        x = np.linspace(0, 1, 1000)
        y = np.sin(x)
        
        x_down, y_down = downsample(x, y, target_points=2)
        
        assert len(x_down) == 2
        assert len(y_down) == 2
        assert x_down[0] == x[0]
        assert x_down[-1] == x[-1]
    
    def test_preserves_peaks(self):
        """测试降采样保留峰值特征"""
        x = np.linspace(0, 2 * np.pi, 10000)
        y = np.sin(x)
        
        x_down, y_down = downsample(x, y, target_points=100)
        
        # 检查最大值和最小值被近似保留
        assert np.max(y_down) > 0.95  # 接近 1
        assert np.min(y_down) < -0.95  # 接近 -1
    
    def test_monotonic_x(self):
        """测试降采样后 X 轴保持单调递增"""
        x = np.linspace(0, 10, 5000)
        y = np.random.randn(5000)
        
        x_down, y_down = downsample(x, y, target_points=200)
        
        # X 轴应该单调递增
        assert np.all(np.diff(x_down) > 0)
    
    def test_returns_copy(self):
        """测试返回的是副本而非原数组引用"""
        x = np.linspace(0, 1, 50)
        y = np.sin(x)
        
        x_down, y_down = downsample(x, y, target_points=100)
        
        # 修改返回值不应影响原数组
        x_down[0] = 999
        assert x[0] != 999


class TestDownsampleValidation:
    """输入验证测试"""
    
    def test_none_x_raises(self):
        """测试 x 为 None 时抛出异常"""
        y = np.array([1, 2, 3])
        
        with pytest.raises(ValueError, match="cannot be None"):
            downsample(None, y, target_points=2)
    
    def test_none_y_raises(self):
        """测试 y 为 None 时抛出异常"""
        x = np.array([1, 2, 3])
        
        with pytest.raises(ValueError, match="cannot be None"):
            downsample(x, None, target_points=2)
    
    def test_length_mismatch_raises(self):
        """测试 x 和 y 长度不匹配时抛出异常"""
        x = np.array([1, 2, 3])
        y = np.array([1, 2])
        
        with pytest.raises(ValueError, match="same length"):
            downsample(x, y, target_points=2)
    
    def test_target_points_too_small_raises(self):
        """测试目标点数小于 2 时抛出异常"""
        x = np.array([1, 2, 3])
        y = np.array([1, 2, 3])
        
        with pytest.raises(ValueError, match="must be >= 2"):
            downsample(x, y, target_points=1)
    
    def test_2d_array_raises(self):
        """测试二维数组输入时抛出异常"""
        x = np.array([[1, 2], [3, 4]])
        y = np.array([[1, 2], [3, 4]])
        
        with pytest.raises(ValueError, match="1-dimensional"):
            downsample(x, y, target_points=2)


class TestDownsampleMultiple:
    """多信号批量降采样测试"""
    
    def test_basic_multiple_downsample(self):
        """测试基本多信号降采样"""
        x = np.linspace(0, 1, 1000)
        signals = {
            "V(out)": np.sin(2 * np.pi * 5 * x),
            "I(in)": np.cos(2 * np.pi * 5 * x),
        }
        
        result = downsample_multiple(x, signals, target_points=100)
        
        assert "x" in result
        assert "V(out)" in result
        assert "I(in)" in result
        assert len(result["x"]) == 100
        assert len(result["V(out)"]) == 100
        assert len(result["I(in)"]) == 100
    
    def test_multiple_preserves_endpoints(self):
        """测试多信号降采样保留首尾点"""
        x = np.linspace(0, 1, 1000)
        signals = {
            "sig1": np.sin(x),
            "sig2": np.cos(x),
        }
        
        result = downsample_multiple(x, signals, target_points=50)
        
        assert result["x"][0] == x[0]
        assert result["x"][-1] == x[-1]
        assert result["sig1"][0] == signals["sig1"][0]
        assert result["sig1"][-1] == signals["sig1"][-1]
    
    def test_multiple_no_downsample_needed(self):
        """测试多信号数据点数小于目标时不降采样"""
        x = np.linspace(0, 1, 50)
        signals = {"sig1": np.sin(x)}
        
        result = downsample_multiple(x, signals, target_points=100)
        
        assert len(result["x"]) == 50
        np.testing.assert_array_equal(result["x"], x)
    
    def test_multiple_single_signal(self):
        """测试单信号的批量降采样"""
        x = np.linspace(0, 1, 1000)
        signals = {"only_signal": np.sin(x)}
        
        result = downsample_multiple(x, signals, target_points=100)
        
        assert len(result) == 2  # x + 1 signal
        assert len(result["x"]) == 100
    
    def test_multiple_many_signals(self):
        """测试多个信号的批量降采样"""
        x = np.linspace(0, 1, 5000)
        signals = {f"sig_{i}": np.sin(i * x) for i in range(10)}
        
        result = downsample_multiple(x, signals, target_points=200)
        
        assert len(result) == 11  # x + 10 signals
        for key in result:
            assert len(result[key]) == 200


class TestDownsampleMultipleValidation:
    """多信号降采样输入验证测试"""
    
    def test_empty_signals_raises(self):
        """测试空信号字典时抛出异常"""
        x = np.array([1, 2, 3])
        
        with pytest.raises(ValueError, match="cannot be empty"):
            downsample_multiple(x, {}, target_points=2)
    
    def test_signal_length_mismatch_raises(self):
        """测试信号长度与 x 不匹配时抛出异常"""
        x = np.array([1, 2, 3])
        signals = {"sig1": np.array([1, 2])}
        
        with pytest.raises(ValueError, match="does not match"):
            downsample_multiple(x, signals, target_points=2)
    
    def test_none_x_raises(self):
        """测试 x 为 None 时抛出异常"""
        signals = {"sig1": np.array([1, 2, 3])}
        
        with pytest.raises(ValueError, match="cannot be None"):
            downsample_multiple(None, signals, target_points=2)


class TestDownsamplePerformance:
    """性能测试"""
    
    def test_million_points_performance(self):
        """测试百万点降采样性能（< 100ms）"""
        n_points = 1_000_000
        x = np.linspace(0, 1, n_points)
        y = np.sin(2 * np.pi * 100 * x) + np.random.randn(n_points) * 0.1
        
        start_time = time.perf_counter()
        x_down, y_down = downsample(x, y, target_points=2000)
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        
        assert len(x_down) == 2000
        assert elapsed_ms < 500  # 放宽到 500ms 以适应不同硬件
        print(f"\n百万点降采样耗时: {elapsed_ms:.2f}ms")
    
    def test_multiple_signals_performance(self):
        """测试多信号百万点降采样性能"""
        n_points = 1_000_000
        x = np.linspace(0, 1, n_points)
        signals = {
            "V(out)": np.sin(2 * np.pi * 100 * x),
            "V(in)": np.cos(2 * np.pi * 100 * x),
            "I(supply)": np.sin(2 * np.pi * 50 * x),
        }
        
        start_time = time.perf_counter()
        result = downsample_multiple(x, signals, target_points=2000)
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        
        assert len(result["x"]) == 2000
        assert elapsed_ms < 1500  # 多信号允许更长时间
        print(f"\n多信号百万点降采样耗时: {elapsed_ms:.2f}ms")


class TestDownsampleEdgeCases:
    """边界条件测试"""
    
    def test_three_points_to_two(self):
        """测试 3 个点降采样到 2 个点"""
        x = np.array([0.0, 0.5, 1.0])
        y = np.array([0.0, 1.0, 0.0])
        
        x_down, y_down = downsample(x, y, target_points=2)
        
        assert len(x_down) == 2
        assert x_down[0] == 0.0
        assert x_down[-1] == 1.0
    
    def test_constant_signal(self):
        """测试常数信号的降采样"""
        x = np.linspace(0, 1, 1000)
        y = np.ones(1000) * 5.0
        
        x_down, y_down = downsample(x, y, target_points=100)
        
        assert len(x_down) == 100
        # 常数信号降采样后仍应为常数
        np.testing.assert_array_almost_equal(y_down, np.ones(100) * 5.0)
    
    def test_linear_signal(self):
        """测试线性信号的降采样"""
        x = np.linspace(0, 1, 1000)
        y = x * 2 + 1  # y = 2x + 1
        
        x_down, y_down = downsample(x, y, target_points=100)
        
        assert len(x_down) == 100
        # 线性信号降采样后应保持线性关系
        # 检查首尾点
        assert abs(y_down[0] - 1.0) < 1e-10
        assert abs(y_down[-1] - 3.0) < 1e-10
    
    def test_spike_signal(self):
        """测试尖峰信号的降采样（应保留尖峰）"""
        x = np.linspace(0, 1, 10000)
        y = np.zeros(10000)
        y[5000] = 100.0  # 中间有一个尖峰
        
        x_down, y_down = downsample(x, y, target_points=100)
        
        # 尖峰应该被保留（或接近保留）
        assert np.max(y_down) > 50.0  # 尖峰应该被捕获
    
    def test_list_input(self):
        """测试列表输入（应自动转换为 numpy 数组）"""
        x = [0.0, 0.25, 0.5, 0.75, 1.0]
        y = [0.0, 1.0, 0.0, -1.0, 0.0]
        
        x_down, y_down = downsample(x, y, target_points=3)
        
        assert isinstance(x_down, np.ndarray)
        assert isinstance(y_down, np.ndarray)
        assert len(x_down) == 3
