# Test Resolution Pyramid - Multi-resolution Waveform Data Tests
"""
多分辨率金字塔测试

测试覆盖：
- 金字塔构建测试
- 层级选择测试
- 数据获取测试
- 边界条件测试
- 性能测试
"""

import time

import numpy as np
import pytest

from domain.simulation.data.resolution_pyramid import (
    DEFAULT_PYRAMID_LEVELS,
    PyramidData,
    PyramidLevel,
    build_pyramid,
    get_level_data,
    get_optimal_data,
    select_optimal_level,
)


class TestPyramidLevel:
    """PyramidLevel 数据类测试"""
    
    def test_basic_creation(self):
        """测试基本创建"""
        x = np.array([0.0, 0.5, 1.0])
        y = np.array([1.0, 2.0, 3.0])
        
        level = PyramidLevel(target_points=100, x_data=x, y_data=y)
        
        assert level.target_points == 100
        assert level.actual_points == 3
        np.testing.assert_array_equal(level.x_data, x)
        np.testing.assert_array_equal(level.y_data, y)
    
    def test_actual_points_auto_calculated(self):
        """测试 actual_points 自动计算"""
        x = np.linspace(0, 1, 500)
        y = np.sin(x)
        
        level = PyramidLevel(target_points=1000, x_data=x, y_data=y)
        
        assert level.actual_points == 500


class TestPyramidData:
    """PyramidData 数据类测试"""
    
    def test_get_level_count(self):
        """测试获取层级数量"""
        levels = [
            PyramidLevel(100, np.array([0, 1]), np.array([0, 1])),
            PyramidLevel(200, np.array([0, 1]), np.array([0, 1])),
        ]
        pyramid = PyramidData(
            original_points=1000,
            levels=levels,
            x_range=(0.0, 1.0),
            y_range=(0.0, 1.0)
        )
        
        assert pyramid.get_level_count() == 2
    
    def test_get_level_points(self):
        """测试获取各层级点数"""
        levels = [
            PyramidLevel(100, np.linspace(0, 1, 100), np.zeros(100)),
            PyramidLevel(500, np.linspace(0, 1, 500), np.zeros(500)),
        ]
        pyramid = PyramidData(
            original_points=1000,
            levels=levels,
            x_range=(0.0, 1.0),
            y_range=(0.0, 0.0)
        )
        
        assert pyramid.get_level_points() == [100, 500]


class TestBuildPyramid:
    """build_pyramid 函数测试"""
    
    def test_basic_build(self):
        """测试基本金字塔构建"""
        x = np.linspace(0, 1, 100000)
        y = np.sin(2 * np.pi * 10 * x)
        
        pyramid = build_pyramid(x, y)
        
        assert pyramid.original_points == 100000
        assert pyramid.get_level_count() == len(DEFAULT_PYRAMID_LEVELS)
        assert pyramid.x_range == (0.0, 1.0)
    
    def test_custom_levels(self):
        """测试自定义层级"""
        x = np.linspace(0, 1, 10000)
        y = np.sin(x)
        
        pyramid = build_pyramid(x, y, levels=[100, 500, 1000])
        
        assert pyramid.get_level_count() == 3
        points = pyramid.get_level_points()
        assert points[0] == 100
        assert points[1] == 500
        assert points[2] == 1000
    
    def test_levels_sorted(self):
        """测试层级自动排序"""
        x = np.linspace(0, 1, 10000)
        y = np.sin(x)
        
        # 传入乱序层级
        pyramid = build_pyramid(x, y, levels=[1000, 100, 500])
        
        points = pyramid.get_level_points()
        # 应该按升序排列
        assert points == [100, 500, 1000]
    
    def test_levels_deduplicated(self):
        """测试层级自动去重"""
        x = np.linspace(0, 1, 10000)
        y = np.sin(x)
        
        # 传入重复层级
        pyramid = build_pyramid(x, y, levels=[100, 500, 100, 500])
        
        assert pyramid.get_level_count() == 2
    
    def test_small_data(self):
        """测试小数据量（小于所有层级）"""
        x = np.linspace(0, 1, 100)
        y = np.sin(x)
        
        pyramid = build_pyramid(x, y, levels=[500, 1000, 2000])
        
        # 所有层级都应该包含原始数据
        for level in pyramid.levels:
            assert level.actual_points == 100
    
    def test_preserves_range(self):
        """测试保留数据范围"""
        x = np.linspace(-5, 10, 10000)
        y = np.sin(x) * 3 + 2  # 范围约 [-1, 5]
        
        pyramid = build_pyramid(x, y, levels=[100])
        
        assert pyramid.x_range == (-5.0, 10.0)
        assert pyramid.y_range[0] < 0  # 最小值 < 0
        assert pyramid.y_range[1] > 4  # 最大值 > 4
    
    def test_empty_levels_uses_default(self):
        """测试空层级列表使用默认值"""
        x = np.linspace(0, 1, 100000)
        y = np.sin(x)
        
        pyramid = build_pyramid(x, y, levels=[])
        
        assert pyramid.get_level_count() == len(DEFAULT_PYRAMID_LEVELS)


class TestBuildPyramidValidation:
    """build_pyramid 输入验证测试"""
    
    def test_none_x_raises(self):
        """测试 x 为 None 时抛出异常"""
        y = np.array([1, 2, 3])
        
        with pytest.raises(ValueError, match="cannot be None"):
            build_pyramid(None, y)
    
    def test_none_y_raises(self):
        """测试 y 为 None 时抛出异常"""
        x = np.array([1, 2, 3])
        
        with pytest.raises(ValueError, match="cannot be None"):
            build_pyramid(x, None)
    
    def test_length_mismatch_raises(self):
        """测试 x 和 y 长度不匹配时抛出异常"""
        x = np.array([1, 2, 3])
        y = np.array([1, 2])
        
        with pytest.raises(ValueError, match="same length"):
            build_pyramid(x, y)
    
    def test_empty_array_raises(self):
        """测试空数组时抛出异常"""
        x = np.array([])
        y = np.array([])
        
        with pytest.raises(ValueError, match="cannot be empty"):
            build_pyramid(x, y)
    
    def test_2d_array_raises(self):
        """测试二维数组时抛出异常"""
        x = np.array([[1, 2], [3, 4]])
        y = np.array([[1, 2], [3, 4]])
        
        with pytest.raises(ValueError, match="1-dimensional"):
            build_pyramid(x, y)
    
    def test_invalid_levels_raises(self):
        """测试所有层级无效时抛出异常"""
        x = np.array([1, 2, 3])
        y = np.array([1, 2, 3])
        
        with pytest.raises(ValueError, match="No valid levels"):
            build_pyramid(x, y, levels=[0, 1, -1])


class TestSelectOptimalLevel:
    """select_optimal_level 函数测试"""
    
    def test_exact_match(self):
        """测试精确匹配"""
        x = np.linspace(0, 1, 100000)
        y = np.sin(x)
        pyramid = build_pyramid(x, y, levels=[500, 2000, 10000])
        
        # 需要 2000 点，应该返回 2000 点层级
        level_idx = select_optimal_level(pyramid, 2000)
        
        assert pyramid.levels[level_idx].actual_points == 2000
    
    def test_select_next_higher(self):
        """测试选择下一个更高层级"""
        x = np.linspace(0, 1, 100000)
        y = np.sin(x)
        pyramid = build_pyramid(x, y, levels=[500, 2000, 10000])
        
        # 需要 1500 点，应该返回 2000 点层级
        level_idx = select_optimal_level(pyramid, 1500)
        
        assert pyramid.levels[level_idx].actual_points == 2000
    
    def test_select_highest_when_insufficient(self):
        """测试需求超过最高层级时返回最高层级"""
        x = np.linspace(0, 1, 100000)
        y = np.sin(x)
        pyramid = build_pyramid(x, y, levels=[500, 2000, 10000])
        
        # 需要 50000 点，应该返回最高层级（10000 点）
        level_idx = select_optimal_level(pyramid, 50000)
        
        assert level_idx == 2  # 最后一个层级
        assert pyramid.levels[level_idx].actual_points == 10000
    
    def test_select_lowest_for_small_requirement(self):
        """测试小需求选择最低层级"""
        x = np.linspace(0, 1, 100000)
        y = np.sin(x)
        pyramid = build_pyramid(x, y, levels=[500, 2000, 10000])
        
        # 需要 100 点，应该返回 500 点层级
        level_idx = select_optimal_level(pyramid, 100)
        
        assert level_idx == 0
        assert pyramid.levels[level_idx].actual_points == 500


class TestSelectOptimalLevelValidation:
    """select_optimal_level 输入验证测试"""
    
    def test_none_pyramid_raises(self):
        """测试 pyramid 为 None 时抛出异常"""
        with pytest.raises(ValueError, match="cannot be None"):
            select_optimal_level(None, 100)
    
    def test_empty_pyramid_raises(self):
        """测试空金字塔时抛出异常"""
        pyramid = PyramidData(
            original_points=1000,
            levels=[],
            x_range=(0.0, 1.0),
            y_range=(0.0, 1.0)
        )
        
        with pytest.raises(ValueError, match="no levels"):
            select_optimal_level(pyramid, 100)
    
    def test_invalid_required_points_raises(self):
        """测试无效 required_points 时抛出异常"""
        x = np.linspace(0, 1, 1000)
        y = np.sin(x)
        pyramid = build_pyramid(x, y, levels=[100])
        
        with pytest.raises(ValueError, match="must be >= 1"):
            select_optimal_level(pyramid, 0)


class TestGetLevelData:
    """get_level_data 函数测试"""
    
    def test_basic_get(self):
        """测试基本数据获取"""
        x = np.linspace(0, 1, 10000)
        y = np.sin(x)
        pyramid = build_pyramid(x, y, levels=[100, 500])
        
        x_data, y_data = get_level_data(pyramid, 0)
        
        assert len(x_data) == 100
        assert len(y_data) == 100
    
    def test_returns_copy(self):
        """测试返回的是副本"""
        x = np.linspace(0, 1, 10000)
        y = np.sin(x)
        pyramid = build_pyramid(x, y, levels=[100])
        
        x_data, y_data = get_level_data(pyramid, 0)
        original_x0 = pyramid.levels[0].x_data[0]
        
        # 修改返回值
        x_data[0] = 999
        
        # 原数据不应改变
        assert pyramid.levels[0].x_data[0] == original_x0
    
    def test_get_all_levels(self):
        """测试获取所有层级"""
        x = np.linspace(0, 1, 100000)
        y = np.sin(x)
        pyramid = build_pyramid(x, y, levels=[100, 500, 2000])
        
        for i in range(pyramid.get_level_count()):
            x_data, y_data = get_level_data(pyramid, i)
            assert len(x_data) == pyramid.levels[i].actual_points


class TestGetLevelDataValidation:
    """get_level_data 输入验证测试"""
    
    def test_none_pyramid_raises(self):
        """测试 pyramid 为 None 时抛出异常"""
        with pytest.raises(ValueError, match="cannot be None"):
            get_level_data(None, 0)
    
    def test_index_out_of_range_raises(self):
        """测试索引越界时抛出异常"""
        x = np.linspace(0, 1, 1000)
        y = np.sin(x)
        pyramid = build_pyramid(x, y, levels=[100, 500])
        
        with pytest.raises(IndexError, match="out of range"):
            get_level_data(pyramid, 5)
    
    def test_negative_index_raises(self):
        """测试负索引时抛出异常"""
        x = np.linspace(0, 1, 1000)
        y = np.sin(x)
        pyramid = build_pyramid(x, y, levels=[100])
        
        with pytest.raises(IndexError, match="out of range"):
            get_level_data(pyramid, -1)


class TestGetOptimalData:
    """get_optimal_data 便捷方法测试"""
    
    def test_basic_usage(self):
        """测试基本使用"""
        x = np.linspace(0, 1, 100000)
        y = np.sin(x)
        pyramid = build_pyramid(x, y, levels=[500, 2000, 10000])
        
        x_data, y_data, level_idx = get_optimal_data(pyramid, 1500)
        
        assert level_idx == 1  # 2000 点层级
        assert len(x_data) == 2000
        assert len(y_data) == 2000
    
    def test_returns_correct_level_index(self):
        """测试返回正确的层级索引"""
        x = np.linspace(0, 1, 100000)
        y = np.sin(x)
        pyramid = build_pyramid(x, y, levels=[500, 2000, 10000])
        
        _, _, level_idx = get_optimal_data(pyramid, 100)
        assert level_idx == 0
        
        _, _, level_idx = get_optimal_data(pyramid, 5000)
        assert level_idx == 2


class TestPerformance:
    """性能测试"""
    
    def test_build_pyramid_performance(self):
        """测试金字塔构建性能"""
        n_points = 1_000_000
        x = np.linspace(0, 1, n_points)
        y = np.sin(2 * np.pi * 100 * x) + np.random.randn(n_points) * 0.1
        
        start_time = time.perf_counter()
        pyramid = build_pyramid(x, y)
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        
        assert pyramid.original_points == n_points
        # 构建 4 个层级应该在合理时间内完成
        assert elapsed_ms < 2000  # 2 秒内
        print(f"\n百万点金字塔构建耗时: {elapsed_ms:.2f}ms")
    
    def test_level_selection_performance(self):
        """测试层级选择性能（应该是 O(n) 其中 n 是层级数）"""
        x = np.linspace(0, 1, 1_000_000)
        y = np.sin(x)
        pyramid = build_pyramid(x, y)
        
        start_time = time.perf_counter()
        for _ in range(10000):
            select_optimal_level(pyramid, 1500)
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        
        # 10000 次选择应该非常快
        assert elapsed_ms < 100  # 100ms 内
        print(f"\n10000 次层级选择耗时: {elapsed_ms:.2f}ms")


class TestEdgeCases:
    """边界条件测试"""
    
    def test_single_point(self):
        """测试单点数据"""
        x = np.array([0.5])
        y = np.array([1.0])
        
        # 单点数据无法降采样（需要至少 2 点）
        # 但构建金字塔应该成功
        pyramid = build_pyramid(x, y, levels=[2, 10])
        
        assert pyramid.original_points == 1
        # 所有层级都应该包含原始单点
        for level in pyramid.levels:
            assert level.actual_points == 1
    
    def test_two_points(self):
        """测试两点数据"""
        x = np.array([0.0, 1.0])
        y = np.array([0.0, 1.0])
        
        pyramid = build_pyramid(x, y, levels=[2, 10, 100])
        
        assert pyramid.original_points == 2
        for level in pyramid.levels:
            assert level.actual_points == 2
    
    def test_constant_signal(self):
        """测试常数信号"""
        x = np.linspace(0, 1, 10000)
        y = np.ones(10000) * 5.0
        
        pyramid = build_pyramid(x, y, levels=[100, 500])
        
        x_data, y_data = get_level_data(pyramid, 0)
        # 常数信号降采样后仍应为常数
        np.testing.assert_array_almost_equal(y_data, np.ones(100) * 5.0)
    
    def test_list_input(self):
        """测试列表输入"""
        x = [0.0, 0.25, 0.5, 0.75, 1.0] * 1000  # 5000 点
        y = [0.0, 1.0, 0.0, -1.0, 0.0] * 1000
        
        pyramid = build_pyramid(x, y, levels=[100])
        
        assert pyramid.original_points == 5000
        assert pyramid.levels[0].actual_points == 100
