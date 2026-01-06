# LTTB Downsampler - Largest Triangle Three Buckets Algorithm
"""
LTTB 降采样算法实现

职责：
- 实现 Largest Triangle Three Buckets 降采样算法
- 保持波形视觉特征的同时减少数据点数量
- 支持单信号和批量信号降采样

算法原理：
LTTB 算法将数据分成若干个桶（bucket），每个桶选择一个最能代表
该区域视觉特征的点。选择标准是使该点与前一个选中点和下一个桶
的平均点构成的三角形面积最大。

性能要求：
- 百万点降采样到 2000 点 < 100ms

参考文献：
- Sveinn Steinarsson, "Downsampling Time Series for Visual Representation"
  https://skemman.is/bitstream/1946/15343/3/SS_MSthesis.pdf

使用示例：
    import numpy as np
    from domain.simulation.data.downsampler import downsample, downsample_multiple
    
    # 单信号降采样
    x = np.linspace(0, 1, 1_000_000)
    y = np.sin(2 * np.pi * 10 * x)
    x_down, y_down = downsample(x, y, target_points=2000)
    
    # 批量降采样（共享 X 轴）
    signals = {
        "V(out)": np.sin(2 * np.pi * 10 * x),
        "V(in)": np.cos(2 * np.pi * 10 * x),
    }
    result = downsample_multiple(x, signals, target_points=2000)
    # result = {"x": x_down, "V(out)": y_down1, "V(in)": y_down2}
"""

from typing import Dict, Tuple

import numpy as np


def downsample(
    x: np.ndarray,
    y: np.ndarray,
    target_points: int
) -> Tuple[np.ndarray, np.ndarray]:
    """
    执行 LTTB 降采样
    
    使用 Largest Triangle Three Buckets 算法对时间序列数据进行降采样，
    在减少数据点数量的同时保持波形的视觉特征。
    
    Args:
        x: X 轴数据（时间或频率），必须为一维数组
        y: Y 轴数据（信号值），必须与 x 长度相同
        target_points: 目标数据点数量，必须 >= 2
        
    Returns:
        Tuple[np.ndarray, np.ndarray]: 降采样后的 (x, y) 数据
        
    Raises:
        ValueError: 当输入参数无效时
        
    Note:
        - 如果原始数据点数 <= target_points，直接返回原始数据的副本
        - 算法始终保留第一个和最后一个数据点
        - 时间复杂度 O(n)，空间复杂度 O(target_points)
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
    
    if target_points < 2:
        raise ValueError(f"target_points must be >= 2, got {target_points}")
    
    n = len(x)
    
    # 如果数据点数不超过目标点数，直接返回副本
    if n <= target_points:
        return x.copy(), y.copy()
    
    # 特殊情况：目标点数为 2，只保留首尾
    if target_points == 2:
        return np.array([x[0], x[-1]]), np.array([y[0], y[-1]])
    
    # 执行 LTTB 算法
    return _lttb_core(x, y, target_points)


def _lttb_core(
    x: np.ndarray,
    y: np.ndarray,
    target_points: int
) -> Tuple[np.ndarray, np.ndarray]:
    """
    LTTB 算法核心实现
    
    Args:
        x: X 轴数据（已验证）
        y: Y 轴数据（已验证）
        target_points: 目标点数（已验证 >= 2）
        
    Returns:
        Tuple[np.ndarray, np.ndarray]: 降采样后的 (x, y) 数据
    """
    n = len(x)
    
    # 预分配输出数组
    x_out = np.empty(target_points, dtype=np.float64)
    y_out = np.empty(target_points, dtype=np.float64)
    
    # 第一个点始终保留
    x_out[0] = x[0]
    y_out[0] = y[0]
    
    # 计算每个桶的大小（不包括首尾两个点）
    # 中间有 target_points - 2 个桶
    bucket_size = (n - 2) / (target_points - 2)
    
    # 上一个选中点的索引
    prev_selected_idx = 0
    
    # 遍历每个桶（从第 1 个到第 target_points - 2 个）
    for bucket_idx in range(target_points - 2):
        # 当前桶的起始和结束索引
        bucket_start = int((bucket_idx) * bucket_size) + 1
        bucket_end = int((bucket_idx + 1) * bucket_size) + 1
        bucket_end = min(bucket_end, n - 1)  # 不超过倒数第二个点
        
        # 下一个桶的平均点（用于计算三角形面积）
        next_bucket_start = bucket_end
        next_bucket_end = int((bucket_idx + 2) * bucket_size) + 1
        next_bucket_end = min(next_bucket_end, n)
        
        # 计算下一个桶的平均 x 和 y
        if next_bucket_end > next_bucket_start:
            avg_x = np.mean(x[next_bucket_start:next_bucket_end])
            avg_y = np.mean(y[next_bucket_start:next_bucket_end])
        else:
            # 最后一个桶，使用最后一个点
            avg_x = x[-1]
            avg_y = y[-1]
        
        # 在当前桶中找到使三角形面积最大的点
        max_area = -1.0
        max_area_idx = bucket_start
        
        # 上一个选中点的坐标
        prev_x = x[prev_selected_idx]
        prev_y = y[prev_selected_idx]
        
        for i in range(bucket_start, bucket_end):
            # 计算三角形面积（使用叉积公式的绝对值的一半）
            # 三角形顶点：(prev_x, prev_y), (x[i], y[i]), (avg_x, avg_y)
            # 面积 = 0.5 * |x1(y2-y3) + x2(y3-y1) + x3(y1-y2)|
            area = abs(
                prev_x * (y[i] - avg_y) +
                x[i] * (avg_y - prev_y) +
                avg_x * (prev_y - y[i])
            )
            
            if area > max_area:
                max_area = area
                max_area_idx = i
        
        # 记录选中的点
        x_out[bucket_idx + 1] = x[max_area_idx]
        y_out[bucket_idx + 1] = y[max_area_idx]
        prev_selected_idx = max_area_idx
    
    # 最后一个点始终保留
    x_out[-1] = x[-1]
    y_out[-1] = y[-1]
    
    return x_out, y_out


def downsample_multiple(
    x: np.ndarray,
    signals: Dict[str, np.ndarray],
    target_points: int
) -> Dict[str, np.ndarray]:
    """
    批量降采样多个共享 X 轴的信号
    
    对于共享同一 X 轴的多个信号，使用统一的采样点索引进行降采样，
    确保所有信号在相同的 X 坐标处采样。
    
    采样策略：
    - 基于所有信号的综合特征选择采样点
    - 每个桶选择使所有信号三角形面积之和最大的点
    
    Args:
        x: 共享的 X 轴数据
        signals: 信号字典，键为信号名称，值为 Y 轴数据数组
        target_points: 目标数据点数量
        
    Returns:
        Dict[str, np.ndarray]: 降采样结果字典，包含：
            - "x": 降采样后的 X 轴数据
            - 各信号名称: 对应的降采样后 Y 轴数据
            
    Raises:
        ValueError: 当输入参数无效时
        
    Example:
        >>> x = np.linspace(0, 1, 100000)
        >>> signals = {"V(out)": np.sin(x), "I(in)": np.cos(x)}
        >>> result = downsample_multiple(x, signals, 1000)
        >>> result["x"].shape
        (1000,)
    """
    # 参数验证
    if x is None:
        raise ValueError("x array cannot be None")
    
    if not signals:
        raise ValueError("signals dictionary cannot be empty")
    
    x = np.asarray(x, dtype=np.float64)
    
    if x.ndim != 1:
        raise ValueError("x must be a 1-dimensional array")
    
    if target_points < 2:
        raise ValueError(f"target_points must be >= 2, got {target_points}")
    
    n = len(x)
    
    # 验证所有信号长度
    for name, y in signals.items():
        y_arr = np.asarray(y, dtype=np.float64)
        if y_arr.ndim != 1:
            raise ValueError(f"Signal '{name}' must be a 1-dimensional array")
        if len(y_arr) != n:
            raise ValueError(
                f"Signal '{name}' length ({len(y_arr)}) does not match x length ({n})"
            )
    
    # 如果数据点数不超过目标点数，直接返回副本
    if n <= target_points:
        result = {"x": x.copy()}
        for name, y in signals.items():
            result[name] = np.asarray(y, dtype=np.float64).copy()
        return result
    
    # 特殊情况：目标点数为 2，只保留首尾
    if target_points == 2:
        result = {"x": np.array([x[0], x[-1]])}
        for name, y in signals.items():
            y_arr = np.asarray(y, dtype=np.float64)
            result[name] = np.array([y_arr[0], y_arr[-1]])
        return result
    
    # 转换信号为 numpy 数组
    signal_arrays = {
        name: np.asarray(y, dtype=np.float64)
        for name, y in signals.items()
    }
    
    # 执行多信号 LTTB 算法
    return _lttb_multiple_core(x, signal_arrays, target_points)


def _lttb_multiple_core(
    x: np.ndarray,
    signals: Dict[str, np.ndarray],
    target_points: int
) -> Dict[str, np.ndarray]:
    """
    多信号 LTTB 算法核心实现
    
    Args:
        x: X 轴数据（已验证）
        signals: 信号字典（已验证）
        target_points: 目标点数（已验证）
        
    Returns:
        Dict[str, np.ndarray]: 降采样结果
    """
    n = len(x)
    signal_names = list(signals.keys())
    num_signals = len(signal_names)
    
    # 预分配输出数组
    x_out = np.empty(target_points, dtype=np.float64)
    y_outs = {name: np.empty(target_points, dtype=np.float64) for name in signal_names}
    
    # 第一个点始终保留
    x_out[0] = x[0]
    for name in signal_names:
        y_outs[name][0] = signals[name][0]
    
    # 计算每个桶的大小
    bucket_size = (n - 2) / (target_points - 2)
    
    # 上一个选中点的索引
    prev_selected_idx = 0
    
    # 遍历每个桶
    for bucket_idx in range(target_points - 2):
        bucket_start = int((bucket_idx) * bucket_size) + 1
        bucket_end = int((bucket_idx + 1) * bucket_size) + 1
        bucket_end = min(bucket_end, n - 1)
        
        # 下一个桶的范围
        next_bucket_start = bucket_end
        next_bucket_end = int((bucket_idx + 2) * bucket_size) + 1
        next_bucket_end = min(next_bucket_end, n)
        
        # 计算下一个桶的平均值（所有信号）
        if next_bucket_end > next_bucket_start:
            avg_x = np.mean(x[next_bucket_start:next_bucket_end])
            avg_ys = {
                name: np.mean(signals[name][next_bucket_start:next_bucket_end])
                for name in signal_names
            }
        else:
            avg_x = x[-1]
            avg_ys = {name: signals[name][-1] for name in signal_names}
        
        # 在当前桶中找到使所有信号三角形面积之和最大的点
        max_total_area = -1.0
        max_area_idx = bucket_start
        
        prev_x = x[prev_selected_idx]
        prev_ys = {name: signals[name][prev_selected_idx] for name in signal_names}
        
        for i in range(bucket_start, bucket_end):
            total_area = 0.0
            
            for name in signal_names:
                # 计算该信号的三角形面积
                area = abs(
                    prev_x * (signals[name][i] - avg_ys[name]) +
                    x[i] * (avg_ys[name] - prev_ys[name]) +
                    avg_x * (prev_ys[name] - signals[name][i])
                )
                total_area += area
            
            if total_area > max_total_area:
                max_total_area = total_area
                max_area_idx = i
        
        # 记录选中的点
        x_out[bucket_idx + 1] = x[max_area_idx]
        for name in signal_names:
            y_outs[name][bucket_idx + 1] = signals[name][max_area_idx]
        prev_selected_idx = max_area_idx
    
    # 最后一个点始终保留
    x_out[-1] = x[-1]
    for name in signal_names:
        y_outs[name][-1] = signals[name][-1]
    
    # 构建结果字典
    result = {"x": x_out}
    result.update(y_outs)
    
    return result


__all__ = [
    "downsample",
    "downsample_multiple",
]
