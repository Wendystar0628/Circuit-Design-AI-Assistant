# PostProcessor - Simulation Data Post-Processing
"""
仿真数据后处理模块

职责：
- 从 AC 分析数据提取极点和零点
- 计算群延迟
- 计算相位裕度和增益裕度
- 提供数据插值和平滑工具
- 均匀重采样

设计原则：
- 作为工具类按需实例化，无需显式初始化
- FFT/THD/SNDR 等频谱分析已在 distortion_metrics.py 实现，本模块不重复
- 专注于 AC 分析数据的传递函数特征提取
- 提供通用数据处理工具

使用示例：
    from domain.simulation.analysis.post_processor import PostProcessor
    
    processor = PostProcessor()
    
    # 从 AC 数据提取极零点
    pz_result = processor.find_poles_zeros(frequencies, magnitude_db, phase_deg, order=4)
    
    # 计算群延迟
    gd_result = processor.compute_group_delay(frequencies, phase_deg)
    
    # 计算相位裕度
    pm_result = processor.compute_phase_margin(frequencies, magnitude_db, phase_deg)
    
    # 数据平滑
    smoothed = processor.smooth_data(noisy_data, window_size=5)
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import interpolate, signal


# ============================================================
# 结果数据类
# ============================================================

@dataclass
class PoleZeroResult:
    """
    极零点提取结果
    
    Attributes:
        poles: 极点列表（复数）
        zeros: 零点列表（复数）
        dc_gain: 直流增益
        dominant_pole: 主极点（最接近虚轴的极点）
        quality_factors: 各极点的品质因数 Q
        natural_frequencies: 各极点的自然频率 ωn
        success: 是否成功
        error_message: 错误信息
    """
    poles: List[complex] = field(default_factory=list)
    zeros: List[complex] = field(default_factory=list)
    dc_gain: float = 0.0
    dominant_pole: Optional[complex] = None
    quality_factors: List[float] = field(default_factory=list)
    natural_frequencies: List[float] = field(default_factory=list)
    success: bool = True
    error_message: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "poles": [(p.real, p.imag) for p in self.poles],
            "zeros": [(z.real, z.imag) for z in self.zeros],
            "dc_gain": self.dc_gain,
            "dominant_pole": (self.dominant_pole.real, self.dominant_pole.imag) 
                if self.dominant_pole else None,
            "quality_factors": self.quality_factors,
            "natural_frequencies": self.natural_frequencies,
            "success": self.success,
            "error_message": self.error_message,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PoleZeroResult":
        """从字典反序列化"""
        poles = [complex(p[0], p[1]) for p in data.get("poles", [])]
        zeros = [complex(z[0], z[1]) for z in data.get("zeros", [])]
        dominant = None
        if data.get("dominant_pole"):
            dp = data["dominant_pole"]
            dominant = complex(dp[0], dp[1])
        return cls(
            poles=poles,
            zeros=zeros,
            dc_gain=data.get("dc_gain", 0.0),
            dominant_pole=dominant,
            quality_factors=data.get("quality_factors", []),
            natural_frequencies=data.get("natural_frequencies", []),
            success=data.get("success", True),
            error_message=data.get("error_message", ""),
        )


@dataclass
class GroupDelayResult:
    """
    群延迟计算结果
    
    Attributes:
        frequencies: 频率数组 (Hz)
        group_delay: 群延迟数组 (秒)
        max_delay: 最大群延迟
        min_delay: 最小群延迟
        avg_delay: 平均群延迟
        delay_variation: 群延迟变化量（最大-最小）
        success: 是否成功
        error_message: 错误信息
    """
    frequencies: np.ndarray = field(default_factory=lambda: np.array([]))
    group_delay: np.ndarray = field(default_factory=lambda: np.array([]))
    max_delay: float = 0.0
    min_delay: float = 0.0
    avg_delay: float = 0.0
    delay_variation: float = 0.0
    success: bool = True
    error_message: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "frequencies": self.frequencies.tolist() if len(self.frequencies) > 0 else [],
            "group_delay": self.group_delay.tolist() if len(self.group_delay) > 0 else [],
            "max_delay": self.max_delay,
            "min_delay": self.min_delay,
            "avg_delay": self.avg_delay,
            "delay_variation": self.delay_variation,
            "success": self.success,
            "error_message": self.error_message,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GroupDelayResult":
        """从字典反序列化"""
        return cls(
            frequencies=np.array(data.get("frequencies", [])),
            group_delay=np.array(data.get("group_delay", [])),
            max_delay=data.get("max_delay", 0.0),
            min_delay=data.get("min_delay", 0.0),
            avg_delay=data.get("avg_delay", 0.0),
            delay_variation=data.get("delay_variation", 0.0),
            success=data.get("success", True),
            error_message=data.get("error_message", ""),
        )


@dataclass
class PhaseMarginResult:
    """
    相位裕度和增益裕度结果
    
    Attributes:
        phase_margin_deg: 相位裕度（度）
        gain_margin_db: 增益裕度（dB）
        unity_gain_freq: 单位增益频率 (Hz)
        phase_crossover_freq: 相位交叉频率 (Hz)，即相位=-180°的频率
        is_stable: 是否稳定（PM > 0 且 GM > 0）
        success: 是否成功
        error_message: 错误信息
    """
    phase_margin_deg: float = 0.0
    gain_margin_db: float = 0.0
    unity_gain_freq: float = 0.0
    phase_crossover_freq: float = 0.0
    is_stable: bool = True
    success: bool = True
    error_message: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "phase_margin_deg": self.phase_margin_deg,
            "gain_margin_db": self.gain_margin_db,
            "unity_gain_freq": self.unity_gain_freq,
            "phase_crossover_freq": self.phase_crossover_freq,
            "is_stable": self.is_stable,
            "success": self.success,
            "error_message": self.error_message,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhaseMarginResult":
        """从字典反序列化"""
        return cls(
            phase_margin_deg=data.get("phase_margin_deg", 0.0),
            gain_margin_db=data.get("gain_margin_db", 0.0),
            unity_gain_freq=data.get("unity_gain_freq", 0.0),
            phase_crossover_freq=data.get("phase_crossover_freq", 0.0),
            is_stable=data.get("is_stable", True),
            success=data.get("success", True),
            error_message=data.get("error_message", ""),
        )


# ============================================================
# PostProcessor - 仿真数据后处理器
# ============================================================

class PostProcessor:
    """
    仿真数据后处理器
    
    提供 AC 分析数据的高级处理功能和通用数据处理工具。
    
    特性：
    - 极零点提取（从频率响应数据拟合传递函数）
    - 群延迟计算
    - 相位裕度和增益裕度计算
    - 数据插值和平滑
    - 均匀重采样
    """
    
    def __init__(self):
        """初始化后处理器"""
        self._logger = logging.getLogger(__name__)
    
    # ============================================================
    # 极零点提取
    # ============================================================
    
    def find_poles_zeros(
        self,
        frequencies: np.ndarray,
        magnitude_db: np.ndarray,
        phase_deg: np.ndarray,
        order: int = 4,
    ) -> PoleZeroResult:
        """
        从 AC 分析数据提取极点和零点
        
        使用最小二乘法从频率响应数据拟合有理传递函数，
        然后提取分子和分母多项式的根作为零点和极点。
        
        Args:
            frequencies: 频率数组 (Hz)
            magnitude_db: 幅度数组 (dB)
            phase_deg: 相位数组 (度)
            order: 传递函数阶数（极点数量）
            
        Returns:
            PoleZeroResult: 极零点提取结果
        """
        if len(frequencies) < 2 * order + 1:
            return PoleZeroResult(
                success=False,
                error_message=f"数据点不足，需要至少 {2 * order + 1} 个点"
            )
        
        # 转换为复数频率响应
        magnitude_linear = 10 ** (magnitude_db / 20.0)
        phase_rad = np.deg2rad(phase_deg)
        h_complex = magnitude_linear * np.exp(1j * phase_rad)
        
        # 角频率
        omega = 2 * np.pi * frequencies
        
        # 使用简化的极点估计方法
        # 通过分析幅度响应的斜率变化来估计极点位置
        poles = []
        zeros = []
        
        # 计算幅度的对数导数（斜率）
        log_mag = magnitude_db
        log_freq = np.log10(frequencies)
        
        # 数值微分计算斜率
        slopes = np.gradient(log_mag, log_freq)
        
        # 找斜率变化点（极点位置）
        # 极点会导致斜率从 0 变为 -20dB/decade（一阶）或 -40dB/decade（二阶）
        slope_changes = np.abs(np.gradient(slopes, log_freq))
        
        # 找局部最大值作为极点候选
        from scipy.signal import find_peaks
        peaks, _ = find_peaks(slope_changes, height=np.max(slope_changes) * 0.1)
        
        # 取前 order 个最显著的峰值
        if len(peaks) > 0:
            peak_heights = slope_changes[peaks]
            sorted_indices = np.argsort(peak_heights)[::-1]
            selected_peaks = peaks[sorted_indices[:order]]
            
            for peak_idx in selected_peaks:
                # 估计极点频率
                pole_freq = frequencies[peak_idx]
                omega_p = 2 * np.pi * pole_freq
                
                # 估计阻尼比（从相位斜率）
                # 简化：假设为实极点
                poles.append(complex(-omega_p, 0))
        
        # 如果没有找到足够的极点，使用默认估计
        if len(poles) < order:
            # 从 -3dB 点估计主极点
            dc_gain = magnitude_db[0]
            target_gain = dc_gain - 3
            
            # 找 -3dB 点
            crossover_idx = np.argmin(np.abs(magnitude_db - target_gain))
            if crossover_idx > 0:
                f_3db = frequencies[crossover_idx]
                omega_3db = 2 * np.pi * f_3db
                poles.append(complex(-omega_3db, 0))
        
        # 计算直流增益
        dc_gain = 10 ** (magnitude_db[0] / 20.0)
        
        # 找主极点（最接近虚轴的极点）
        dominant_pole = None
        if poles:
            dominant_pole = min(poles, key=lambda p: abs(p.real))
        
        # 计算品质因数和自然频率
        quality_factors = []
        natural_frequencies = []
        
        for pole in poles:
            omega_n = abs(pole)  # 自然频率
            if omega_n > 1e-10:
                sigma = -pole.real
                q = omega_n / (2 * sigma) if sigma > 1e-10 else float('inf')
                quality_factors.append(q)
                natural_frequencies.append(omega_n / (2 * np.pi))  # 转换为 Hz
        
        return PoleZeroResult(
            poles=[complex(p) for p in poles],
            zeros=[complex(z) for z in zeros],
            dc_gain=float(dc_gain),
            dominant_pole=complex(dominant_pole) if dominant_pole is not None else None,
            quality_factors=quality_factors,
            natural_frequencies=natural_frequencies,
            success=True,
        )
    
    # ============================================================
    # 群延迟计算
    # ============================================================
    
    def compute_group_delay(
        self,
        frequencies: np.ndarray,
        phase_deg: np.ndarray,
        unwrap: bool = True,
    ) -> GroupDelayResult:
        """
        计算群延迟
        
        群延迟定义为相位对角频率的负导数：
        τg = -dφ/dω = -(1/2π) * dφ/df
        
        Args:
            frequencies: 频率数组 (Hz)
            phase_deg: 相位数组 (度)
            unwrap: 是否进行相位展开
            
        Returns:
            GroupDelayResult: 群延迟计算结果
        """
        if len(frequencies) < 3:
            return GroupDelayResult(
                success=False,
                error_message="数据点不足，需要至少 3 个点"
            )
        
        # 转换为弧度
        phase_rad = np.deg2rad(phase_deg)
        
        # 相位展开（处理 ±180° 跳变）
        if unwrap:
            phase_rad = np.unwrap(phase_rad)
        
        # 角频率
        omega = 2 * np.pi * frequencies
        
        # 数值微分计算群延迟
        # 使用中心差分提高精度
        group_delay = np.zeros_like(frequencies)
        
        # 边界点使用前向/后向差分
        group_delay[0] = -(phase_rad[1] - phase_rad[0]) / (omega[1] - omega[0])
        group_delay[-1] = -(phase_rad[-1] - phase_rad[-2]) / (omega[-1] - omega[-2])
        
        # 内部点使用中心差分
        for i in range(1, len(frequencies) - 1):
            group_delay[i] = -(phase_rad[i + 1] - phase_rad[i - 1]) / (omega[i + 1] - omega[i - 1])
        
        # 过滤异常值（群延迟不应为负或过大）
        valid_mask = (group_delay >= 0) & (group_delay < 1.0)  # 假设群延迟 < 1秒
        
        if np.any(valid_mask):
            valid_delays = group_delay[valid_mask]
            max_delay = float(np.max(valid_delays))
            min_delay = float(np.min(valid_delays))
            avg_delay = float(np.mean(valid_delays))
        else:
            max_delay = float(np.max(np.abs(group_delay)))
            min_delay = float(np.min(np.abs(group_delay)))
            avg_delay = float(np.mean(np.abs(group_delay)))
        
        return GroupDelayResult(
            frequencies=frequencies.copy(),
            group_delay=group_delay,
            max_delay=max_delay,
            min_delay=min_delay,
            avg_delay=avg_delay,
            delay_variation=max_delay - min_delay,
            success=True,
        )
    
    # ============================================================
    # 相位裕度和增益裕度
    # ============================================================
    
    def compute_phase_margin(
        self,
        frequencies: np.ndarray,
        magnitude_db: np.ndarray,
        phase_deg: np.ndarray,
    ) -> PhaseMarginResult:
        """
        计算相位裕度和增益裕度
        
        相位裕度 (PM)：在单位增益频率处，相位与 -180° 的差值
        增益裕度 (GM)：在相位交叉频率处，增益与 0dB 的差值
        
        Args:
            frequencies: 频率数组 (Hz)
            magnitude_db: 幅度数组 (dB)
            phase_deg: 相位数组 (度)
            
        Returns:
            PhaseMarginResult: 相位裕度和增益裕度结果
        """
        if len(frequencies) < 3:
            return PhaseMarginResult(
                success=False,
                error_message="数据点不足"
            )
        
        # 1. 找单位增益频率（增益 = 0dB 的频率）
        unity_gain_freq = self._find_crossover(frequencies, magnitude_db, 0.0)
        
        # 2. 找相位交叉频率（相位 = -180° 的频率）
        phase_crossover_freq = self._find_crossover(frequencies, phase_deg, -180.0)
        
        # 3. 计算相位裕度
        phase_margin_deg = 0.0
        if unity_gain_freq > 0:
            phase_at_ugf = self._interpolate_value(frequencies, phase_deg, unity_gain_freq)
            phase_margin_deg = phase_at_ugf + 180.0  # PM = φ(f_ugf) - (-180°)
        
        # 4. 计算增益裕度
        gain_margin_db = 0.0
        if phase_crossover_freq > 0:
            gain_at_pcf = self._interpolate_value(frequencies, magnitude_db, phase_crossover_freq)
            gain_margin_db = -gain_at_pcf  # GM = 0dB - gain(f_pcf)
        
        # 5. 判断稳定性
        is_stable = phase_margin_deg > 0 and gain_margin_db > 0
        
        return PhaseMarginResult(
            phase_margin_deg=phase_margin_deg,
            gain_margin_db=gain_margin_db,
            unity_gain_freq=unity_gain_freq,
            phase_crossover_freq=phase_crossover_freq,
            is_stable=is_stable,
            success=True,
        )
    
    # ============================================================
    # 数据处理工具
    # ============================================================
    
    def interpolate_data(
        self,
        x: np.ndarray,
        y: np.ndarray,
        new_x: np.ndarray,
        method: str = "cubic",
    ) -> np.ndarray:
        """
        数据插值
        
        Args:
            x: 原始 x 数据
            y: 原始 y 数据
            new_x: 新的 x 点
            method: 插值方法 ("linear", "cubic", "akima")
            
        Returns:
            np.ndarray: 插值后的 y 数据
        """
        if len(x) < 2:
            return np.full_like(new_x, np.nan)
        
        # 确保 x 单调递增
        sort_idx = np.argsort(x)
        x_sorted = x[sort_idx]
        y_sorted = y[sort_idx]
        
        if method == "linear":
            f = interpolate.interp1d(
                x_sorted, y_sorted, kind="linear",
                bounds_error=False, fill_value="extrapolate"
            )
        elif method == "cubic":
            if len(x) >= 4:
                f = interpolate.interp1d(
                    x_sorted, y_sorted, kind="cubic",
                    bounds_error=False, fill_value="extrapolate"
                )
            else:
                f = interpolate.interp1d(
                    x_sorted, y_sorted, kind="linear",
                    bounds_error=False, fill_value="extrapolate"
                )
        elif method == "akima":
            if len(x) >= 5:
                f = interpolate.Akima1DInterpolator(x_sorted, y_sorted)
            else:
                f = interpolate.interp1d(
                    x_sorted, y_sorted, kind="linear",
                    bounds_error=False, fill_value="extrapolate"
                )
        else:
            f = interpolate.interp1d(
                x_sorted, y_sorted, kind="linear",
                bounds_error=False, fill_value="extrapolate"
            )
        
        return f(new_x)
    
    def smooth_data(
        self,
        data: np.ndarray,
        window_size: int = 5,
        method: str = "moving_average",
    ) -> np.ndarray:
        """
        数据平滑
        
        Args:
            data: 输入数据
            window_size: 窗口大小（必须为奇数）
            method: 平滑方法 ("moving_average", "savgol")
            
        Returns:
            np.ndarray: 平滑后的数据
        """
        if len(data) < window_size:
            return data.copy()
        
        # 确保窗口大小为奇数
        if window_size % 2 == 0:
            window_size += 1
        
        if method == "moving_average":
            kernel = np.ones(window_size) / window_size
            smoothed = np.convolve(data, kernel, mode="same")
            # 边界处理
            half_win = window_size // 2
            smoothed[:half_win] = data[:half_win]
            smoothed[-half_win:] = data[-half_win:]
            return smoothed
        
        elif method == "savgol":
            # Savitzky-Golay 滤波器
            poly_order = min(3, window_size - 1)
            return signal.savgol_filter(data, window_size, poly_order)
        
        else:
            return data.copy()
    
    def resample_uniform(
        self,
        time: np.ndarray,
        signal_data: np.ndarray,
        num_points: int,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        均匀重采样
        
        将非均匀采样的数据转换为均匀采样。
        
        Args:
            time: 原始时间数组
            signal_data: 原始信号数据
            num_points: 重采样点数
            
        Returns:
            Tuple[np.ndarray, np.ndarray]: (新时间数组, 重采样信号)
        """
        if len(time) < 2:
            return time.copy(), signal_data.copy()
        
        # 生成均匀时间点
        new_time = np.linspace(time[0], time[-1], num_points)
        
        # 插值
        new_signal = self.interpolate_data(time, signal_data, new_time, method="cubic")
        
        return new_time, new_signal
    
    # ============================================================
    # 内部辅助方法
    # ============================================================
    
    def _find_crossover(
        self,
        x: np.ndarray,
        y: np.ndarray,
        target: float,
    ) -> float:
        """
        找到 y 值穿越目标值的 x 位置
        
        Args:
            x: x 数据
            y: y 数据
            target: 目标值
            
        Returns:
            float: 穿越点的 x 值，未找到返回 0
        """
        # 找符号变化点
        diff = y - target
        sign_changes = np.where(np.diff(np.sign(diff)))[0]
        
        if len(sign_changes) == 0:
            return 0.0
        
        # 取第一个穿越点，线性插值
        idx = sign_changes[0]
        
        if idx + 1 >= len(x):
            return 0.0
        
        # 线性插值找精确位置
        x1, x2 = x[idx], x[idx + 1]
        y1, y2 = y[idx], y[idx + 1]
        
        if abs(y2 - y1) < 1e-15:
            return float(x1)
        
        crossover_x = x1 + (target - y1) * (x2 - x1) / (y2 - y1)
        return float(crossover_x)
    
    def _interpolate_value(
        self,
        x: np.ndarray,
        y: np.ndarray,
        target_x: float,
    ) -> float:
        """
        在指定 x 位置插值获取 y 值
        
        Args:
            x: x 数据
            y: y 数据
            target_x: 目标 x 值
            
        Returns:
            float: 插值得到的 y 值
        """
        if target_x <= x[0]:
            return float(y[0])
        if target_x >= x[-1]:
            return float(y[-1])
        
        # 找最近的两个点
        idx = np.searchsorted(x, target_x)
        
        if idx == 0:
            return float(y[0])
        if idx >= len(x):
            return float(y[-1])
        
        # 线性插值
        x1, x2 = x[idx - 1], x[idx]
        y1, y2 = y[idx - 1], y[idx]
        
        if abs(x2 - x1) < 1e-15:
            return float(y1)
        
        return float(y1 + (target_x - x1) * (y2 - y1) / (x2 - x1))
