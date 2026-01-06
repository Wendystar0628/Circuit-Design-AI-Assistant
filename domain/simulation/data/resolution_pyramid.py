# Resolution Pyramid - Multi-resolution Waveform Data Management
"""
多分辨率金字塔模块

职责：
- 管理波形数据的多分辨率金字塔
- 支持快速缩放时的数据访问
- 按需构建，缓存在内存中

设计原则：
- 金字塔数据不单独持久化（原始数据已在仿真结果文件中）
- 作为 WaveformDataService 的内部实现细节
- 使用 LTTB 算法进行降采样，保持波形视觉特征

使用示例：
    import numpy as np
    from domain.simulation.data.resolution_pyramid import (
        build_pyramid,
        select_optimal_level,
        get_level_data,
    )
    
    # 构建金字塔
    x = np.linspace(0, 1, 1_000_000)
    y = np.sin(2 * np.pi * 10 * x)
    pyramid = build_pyramid(x, y)
    
    # 选择最优层级（需要显示 1500 个点）
    level_idx = select_optimal_level(pyramid, required_points=1500)
    
    # 获取该层级数据
    x_data, y_data = get_level_data(pyramid, level_idx)
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from domain.simulation.data.downsampler import downsample


# 默认金字塔层级（按点数升序）
DEFAULT_PYRAMID_LEVELS: List[int] = [500, 2000, 10000, 50000]


@dataclass
class PyramidLevel:
    """
    单个分辨率层级
    
    Attributes:
        target_points: 目标点数（构建时指定）
        x_data: X 轴数据
        y_data: Y 轴数据
        actual_points: 实际点数（可能小于目标点数，当原始数据点数不足时）
    """
    target_points: int
    x_data: np.ndarray
    y_data: np.ndarray
    actual_points: int = field(init=False)
    
    def __post_init__(self):
        self.actual_points = len(self.x_data)


@dataclass
class PyramidData:
    """
    金字塔数据容器
    
    Attributes:
        original_points: 原始数据点数
        levels: 各层级数据（按点数升序排列）
        x_range: X 轴范围 (min, max)
        y_range: Y 轴范围 (min, max)
    """
    original_points: int
    levels: List[PyramidLevel]
    x_range: Tuple[float, float]
    y_range: Tuple[float, float]
    
    def get_level_count(self) -> int:
        """获取层级数量"""
        return len(self.levels)
    
    def get_level_points(self) -> List[int]:
        """获取各层级的实际点数列表"""
        return [level.actual_points for level in self.levels]


def build_pyramid(
    x: np.ndarray,
    y: np.ndarray,
    levels: Optional[List[int]] = None
) -> PyramidData:
    """
    构建多分辨率金字塔
    
    使用 LTTB 算法对原始数据进行多级降采样，生成不同分辨率的数据层级。
    层级按点数升序排列，便于快速查找。
    
    Args:
        x: X 轴数据（时间或频率），必须为一维数组
        y: Y 轴数据（信号值），必须与 x 长度相同
        levels: 目标层级点数列表，默认使用 DEFAULT_PYRAMID_LEVELS
                列表会自动排序为升序
        
    Returns:
        PyramidData: 包含所有层级数据的金字塔对象
        
    Raises:
        ValueError: 当输入参数无效时
        
    Note:
        - 如果原始数据点数小于某层级的目标点数，该层级将包含原始数据
        - 层级列表会自动去重并排序
        - 空层级列表将使用默认层级
    """
    # 参数验证
    if x is None or y is None:
        raise ValueError("x and y arrays cannot be None")
    
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    
    if x.ndim != 1 or y.ndim != 1:
        raise ValueError("x and y must be 1-dimensional arrays")
    
    if len(x) != len(y):
        raise ValueError(f"x and y must have the same length, got {len(x)} and {len(y)}")
    
    if len(x) == 0:
        raise ValueError("x and y arrays cannot be empty")
    
    # 处理层级列表
    if levels is None or len(levels) == 0:
        levels = DEFAULT_PYRAMID_LEVELS.copy()
    else:
        # 去重并排序
        levels = sorted(set(levels))
    
    # 过滤无效层级（小于 2 的）
    levels = [lv for lv in levels if lv >= 2]
    
    if len(levels) == 0:
        raise ValueError("No valid levels specified (all levels must be >= 2)")
    
    original_points = len(x)
    x_range = (float(np.min(x)), float(np.max(x)))
    y_range = (float(np.min(y)), float(np.max(y)))
    
    # 构建各层级
    pyramid_levels: List[PyramidLevel] = []
    
    for target_points in levels:
        if original_points <= target_points:
            # 原始数据点数不足，直接使用原始数据
            level = PyramidLevel(
                target_points=target_points,
                x_data=x.copy(),
                y_data=y.copy()
            )
        else:
            # 执行降采样
            x_down, y_down = downsample(x, y, target_points)
            level = PyramidLevel(
                target_points=target_points,
                x_data=x_down,
                y_data=y_down
            )
        pyramid_levels.append(level)
    
    return PyramidData(
        original_points=original_points,
        levels=pyramid_levels,
        x_range=x_range,
        y_range=y_range
    )


def select_optimal_level(pyramid: PyramidData, required_points: int) -> int:
    """
    选择最优分辨率层级
    
    根据所需的显示点数，选择最合适的金字塔层级。
    策略：选择第一个 actual_points >= required_points 的层级，
    若无则返回最高分辨率层级（最后一个）。
    
    Args:
        pyramid: 金字塔数据对象
        required_points: 所需的显示点数
        
    Returns:
        int: 最优层级的索引（0-based）
        
    Raises:
        ValueError: 当金字塔为空或 required_points < 1 时
        
    Example:
        >>> pyramid = build_pyramid(x, y)  # levels: [500, 2000, 10000, 50000]
        >>> select_optimal_level(pyramid, 1500)  # 返回 1（2000 点层级）
        >>> select_optimal_level(pyramid, 100000)  # 返回 3（最高分辨率）
    """
    if pyramid is None:
        raise ValueError("pyramid cannot be None")
    
    if len(pyramid.levels) == 0:
        raise ValueError("pyramid has no levels")
    
    if required_points < 1:
        raise ValueError(f"required_points must be >= 1, got {required_points}")
    
    # 遍历层级（已按点数升序排列）
    for i, level in enumerate(pyramid.levels):
        if level.actual_points >= required_points:
            return i
    
    # 没有足够点数的层级，返回最高分辨率层级
    return len(pyramid.levels) - 1


def get_level_data(
    pyramid: PyramidData,
    level_index: int
) -> Tuple[np.ndarray, np.ndarray]:
    """
    获取指定层级的数据
    
    Args:
        pyramid: 金字塔数据对象
        level_index: 层级索引（0-based）
        
    Returns:
        Tuple[np.ndarray, np.ndarray]: (x_data, y_data) 数据副本
        
    Raises:
        ValueError: 当参数无效时
        IndexError: 当层级索引越界时
    """
    if pyramid is None:
        raise ValueError("pyramid cannot be None")
    
    if len(pyramid.levels) == 0:
        raise ValueError("pyramid has no levels")
    
    if level_index < 0 or level_index >= len(pyramid.levels):
        raise IndexError(
            f"level_index {level_index} out of range [0, {len(pyramid.levels) - 1}]"
        )
    
    level = pyramid.levels[level_index]
    return level.x_data.copy(), level.y_data.copy()


def get_optimal_data(
    pyramid: PyramidData,
    required_points: int
) -> Tuple[np.ndarray, np.ndarray, int]:
    """
    获取最优层级的数据（便捷方法）
    
    组合 select_optimal_level 和 get_level_data 的功能。
    
    Args:
        pyramid: 金字塔数据对象
        required_points: 所需的显示点数
        
    Returns:
        Tuple[np.ndarray, np.ndarray, int]: (x_data, y_data, level_index)
        
    Raises:
        ValueError: 当参数无效时
    """
    level_index = select_optimal_level(pyramid, required_points)
    x_data, y_data = get_level_data(pyramid, level_index)
    return x_data, y_data, level_index


__all__ = [
    "DEFAULT_PYRAMID_LEVELS",
    "PyramidLevel",
    "PyramidData",
    "build_pyramid",
    "select_optimal_level",
    "get_level_data",
    "get_optimal_data",
]
