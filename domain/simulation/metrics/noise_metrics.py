# NoiseMetrics - Noise Performance Metrics Extraction
"""
噪声指标提取模块

职责：
- 从噪声分析数据中提取输入等效噪声电压密度
- 计算积分噪声（RMS 噪声）
- 提取噪声系数（Noise Figure）
- 计算信噪比（SNR）

设计原则：
- 每个提取函数返回 MetricResult，包含值、单位、置信度
- 数据不足时返回错误指标而非抛异常
- 使用数值积分提高精度
- 支持频率范围选择

使用示例：
    from domain.simulation.metrics.noise_metrics import NoiseMetrics
    
    extractor = NoiseMetrics()
    
    # 从噪声数据提取输入噪声密度
    input_noise = extractor.extract_input_noise(sim_data, freq_point=1000)
    
    # 计算积分噪声
    integrated = extractor.extract_integrated_noise(sim_data, freq_range=(10, 100000))
    
    # 提取噪声系数
    nf = extractor.extract_noise_figure(sim_data)
    
    # 计算信噪比
    snr = extractor.extract_snr(sim_data, signal_level=1.0)
"""

from typing import Optional, Tuple

import numpy as np

from domain.simulation.metrics.metric_result import (
    MetricCategory,
    MetricResult,
    create_error_metric,
    create_metric_result,
)
from domain.simulation.models.simulation_result import SimulationData


class NoiseMetrics:
    """
    噪声指标提取器
    
    提供从噪声分析数据中提取噪声性能指标的方法。
    
    噪声分析数据通常包含：
    - inoise: 输入等效噪声电压密度 (V/√Hz)
    - onoise: 输出噪声电压密度 (V/√Hz)
    - 各噪声源贡献
    """
    
    # 玻尔兹曼常数
    K_BOLTZMANN = 1.380649e-23  # J/K
    
    # 参考温度 (290K，用于噪声系数计算)
    T_REF = 290.0  # K
    
    def __init__(self):
        """初始化噪声指标提取器"""
        self._category = MetricCategory.NOISE

    # ============================================================
    # 噪声密度提取
    # ============================================================
    
    def extract_input_noise(
        self,
        data: SimulationData,
        noise_signal: str = "inoise",
        freq_point: Optional[float] = None
    ) -> MetricResult:
        """
        提取输入等效噪声电压密度
        
        输入等效噪声是将所有噪声源折算到输入端的等效噪声电压密度，
        单位为 V/√Hz 或 nV/√Hz。
        
        Args:
            data: 仿真数据（需包含噪声分析结果）
            noise_signal: 噪声信号名称（默认 "inoise"）
            freq_point: 测量频率点（None 时使用 1kHz 或最近点）
            
        Returns:
            MetricResult: 输入噪声密度指标结果
        """
        if data.frequency is None or len(data.frequency) == 0:
            return create_error_metric(
                name="input_noise",
                display_name="输入噪声密度",
                error_message="无噪声分析频率数据",
                category=self._category,
                unit="nV/√Hz"
            )
        
        noise = data.signals.get(noise_signal)
        if noise is None:
            # 尝试其他常见命名
            for alt_name in ["inoise_total", "input_noise", "V(inoise)"]:
                noise = data.signals.get(alt_name)
                if noise is not None:
                    break
        
        if noise is None:
            return create_error_metric(
                name="input_noise",
                display_name="输入噪声密度",
                error_message=f"未找到噪声信号 {noise_signal}",
                category=self._category,
                unit="nV/√Hz"
            )
        
        # 确保是实数（噪声密度是功率谱密度的平方根，应为实数）
        noise = np.abs(noise)
        
        # 确定测量点
        if freq_point is None:
            # 默认使用 1kHz
            freq_point = 1000.0
        
        idx = self._find_nearest_index(data.frequency, freq_point)
        freq_used = data.frequency[idx]
        noise_value = float(noise[idx])
        
        # 转换为 nV/√Hz
        noise_nv = noise_value * 1e9
        
        condition = f"f={self._format_frequency(freq_used)}"
        
        return create_metric_result(
            name="input_noise",
            display_name="输入噪声密度",
            value=noise_nv,
            unit="nV/√Hz",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "frequency": freq_used,
                "noise_signal": noise_signal,
                "raw_value_v": noise_value
            }
        )
    
    def extract_output_noise(
        self,
        data: SimulationData,
        noise_signal: str = "onoise",
        freq_point: Optional[float] = None
    ) -> MetricResult:
        """
        提取输出噪声电压密度
        
        Args:
            data: 仿真数据
            noise_signal: 噪声信号名称（默认 "onoise"）
            freq_point: 测量频率点
            
        Returns:
            MetricResult: 输出噪声密度指标结果
        """
        if data.frequency is None or len(data.frequency) == 0:
            return create_error_metric(
                name="output_noise",
                display_name="输出噪声密度",
                error_message="无噪声分析频率数据",
                category=self._category,
                unit="nV/√Hz"
            )
        
        noise = data.signals.get(noise_signal)
        if noise is None:
            for alt_name in ["onoise_total", "output_noise", "V(onoise)"]:
                noise = data.signals.get(alt_name)
                if noise is not None:
                    break
        
        if noise is None:
            return create_error_metric(
                name="output_noise",
                display_name="输出噪声密度",
                error_message=f"未找到噪声信号 {noise_signal}",
                category=self._category,
                unit="nV/√Hz"
            )
        
        noise = np.abs(noise)
        
        if freq_point is None:
            freq_point = 1000.0
        
        idx = self._find_nearest_index(data.frequency, freq_point)
        freq_used = data.frequency[idx]
        noise_value = float(noise[idx])
        noise_nv = noise_value * 1e9
        
        condition = f"f={self._format_frequency(freq_used)}"
        
        return create_metric_result(
            name="output_noise",
            display_name="输出噪声密度",
            value=noise_nv,
            unit="nV/√Hz",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "frequency": freq_used,
                "noise_signal": noise_signal,
                "raw_value_v": noise_value
            }
        )

    # ============================================================
    # 积分噪声提取
    # ============================================================
    
    def extract_integrated_noise(
        self,
        data: SimulationData,
        freq_range: Optional[Tuple[float, float]] = None,
        noise_signal: str = "inoise"
    ) -> MetricResult:
        """
        提取积分噪声（RMS 噪声）
        
        积分噪声是在指定频率范围内对噪声功率谱密度积分后开方得到的
        总 RMS 噪声电压。
        
        计算公式：V_rms = √(∫ Sn(f) df)
        其中 Sn(f) 是噪声功率谱密度 (V²/Hz)
        
        Args:
            data: 仿真数据
            freq_range: 积分频率范围 (f_low, f_high)，None 时使用全范围
            noise_signal: 噪声信号名称
            
        Returns:
            MetricResult: 积分噪声指标结果（μV RMS）
        """
        if data.frequency is None or len(data.frequency) < 2:
            return create_error_metric(
                name="integrated_noise",
                display_name="积分噪声",
                error_message="噪声分析频率数据不足",
                category=self._category,
                unit="μV"
            )
        
        noise = data.signals.get(noise_signal)
        if noise is None:
            for alt_name in ["inoise_total", "input_noise", "V(inoise)"]:
                noise = data.signals.get(alt_name)
                if noise is not None:
                    break
        
        if noise is None:
            return create_error_metric(
                name="integrated_noise",
                display_name="积分噪声",
                error_message=f"未找到噪声信号 {noise_signal}",
                category=self._category,
                unit="μV"
            )
        
        noise = np.abs(noise)
        freq = data.frequency
        
        # 确定积分范围
        if freq_range is None:
            f_low, f_high = freq[0], freq[-1]
        else:
            f_low, f_high = freq_range
        
        # 找到范围内的索引
        mask = (freq >= f_low) & (freq <= f_high)
        if np.sum(mask) < 2:
            return create_error_metric(
                name="integrated_noise",
                display_name="积分噪声",
                error_message=f"频率范围 {f_low}-{f_high} Hz 内数据点不足",
                category=self._category,
                unit="μV"
            )
        
        freq_range_data = freq[mask]
        noise_range_data = noise[mask]
        
        # 计算噪声功率谱密度 (V²/Hz)
        noise_psd = noise_range_data ** 2
        
        # 使用梯形积分
        integrated_power = np.trapezoid(noise_psd, freq_range_data)
        
        # RMS 噪声
        rms_noise = np.sqrt(integrated_power)
        rms_noise_uv = rms_noise * 1e6  # 转换为 μV
        
        condition = f"{self._format_frequency(f_low)}-{self._format_frequency(f_high)}"
        
        return create_metric_result(
            name="integrated_noise",
            display_name="积分噪声",
            value=rms_noise_uv,
            unit="μV",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "freq_low": f_low,
                "freq_high": f_high,
                "integrated_power_v2": integrated_power,
                "raw_value_v": rms_noise
            }
        )

    # ============================================================
    # 噪声系数提取
    # ============================================================
    
    def extract_noise_figure(
        self,
        data: SimulationData,
        input_noise_signal: str = "inoise",
        source_resistance: float = 50.0,
        temperature: float = 290.0,
        freq_point: Optional[float] = None
    ) -> MetricResult:
        """
        提取噪声系数（Noise Figure）
        
        噪声系数定义为：NF = 10 * log10(F)
        其中 F = (Si/Ni) / (So/No) = 1 + (Vn² / 4kTRs)
        
        对于放大器，噪声系数表示放大器引入的额外噪声相对于
        源电阻热噪声的比值。
        
        Args:
            data: 仿真数据
            input_noise_signal: 输入噪声信号名称
            source_resistance: 源电阻（Ω），默认 50Ω
            temperature: 温度（K），默认 290K
            freq_point: 测量频率点
            
        Returns:
            MetricResult: 噪声系数指标结果（dB）
        """
        if data.frequency is None or len(data.frequency) == 0:
            return create_error_metric(
                name="noise_figure",
                display_name="噪声系数",
                error_message="无噪声分析频率数据",
                category=self._category,
                unit="dB"
            )
        
        noise = data.signals.get(input_noise_signal)
        if noise is None:
            for alt_name in ["inoise_total", "input_noise", "V(inoise)"]:
                noise = data.signals.get(alt_name)
                if noise is not None:
                    break
        
        if noise is None:
            return create_error_metric(
                name="noise_figure",
                display_name="噪声系数",
                error_message=f"未找到噪声信号 {input_noise_signal}",
                category=self._category,
                unit="dB"
            )
        
        noise = np.abs(noise)
        
        if freq_point is None:
            freq_point = 1000.0
        
        idx = self._find_nearest_index(data.frequency, freq_point)
        freq_used = data.frequency[idx]
        vn_density = float(noise[idx])  # V/√Hz
        
        # 计算源电阻热噪声密度
        # Vth = √(4kTR) V/√Hz
        vth_density = np.sqrt(4 * self.K_BOLTZMANN * temperature * source_resistance)
        
        # 噪声因子 F = 1 + (Vn² / Vth²)
        # 这里 Vn 是放大器的等效输入噪声，Vth 是源电阻热噪声
        noise_factor = 1 + (vn_density ** 2) / (vth_density ** 2)
        
        # 噪声系数 NF = 10 * log10(F)
        noise_figure_db = 10 * np.log10(noise_factor)
        
        condition = f"f={self._format_frequency(freq_used)}, Rs={source_resistance}Ω"
        
        return create_metric_result(
            name="noise_figure",
            display_name="噪声系数",
            value=noise_figure_db,
            unit="dB",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "frequency": freq_used,
                "source_resistance": source_resistance,
                "temperature": temperature,
                "noise_factor": noise_factor,
                "input_noise_density_v": vn_density,
                "thermal_noise_density_v": vth_density
            }
        )

    # ============================================================
    # 信噪比提取
    # ============================================================
    
    def extract_snr(
        self,
        data: SimulationData,
        signal_level: float,
        freq_range: Optional[Tuple[float, float]] = None,
        noise_signal: str = "inoise"
    ) -> MetricResult:
        """
        提取信噪比（SNR）
        
        SNR = 20 * log10(Vsignal / Vnoise)
        
        其中 Vnoise 是在指定频率范围内的积分噪声（RMS）。
        
        Args:
            data: 仿真数据
            signal_level: 信号电平（V RMS）
            freq_range: 噪声积分频率范围
            noise_signal: 噪声信号名称
            
        Returns:
            MetricResult: 信噪比指标结果（dB）
        """
        if signal_level <= 0:
            return create_error_metric(
                name="snr",
                display_name="信噪比",
                error_message="信号电平必须大于 0",
                category=self._category,
                unit="dB"
            )
        
        # 先计算积分噪声
        integrated_result = self.extract_integrated_noise(
            data, freq_range, noise_signal
        )
        
        if not integrated_result.is_valid:
            return create_error_metric(
                name="snr",
                display_name="信噪比",
                error_message=f"积分噪声计算失败: {integrated_result.error_message}",
                category=self._category,
                unit="dB"
            )
        
        # 获取 RMS 噪声（从 μV 转换回 V）
        noise_rms_v = integrated_result.metadata.get("raw_value_v", 
                                                      integrated_result.value * 1e-6)
        
        if noise_rms_v <= 0:
            return create_error_metric(
                name="snr",
                display_name="信噪比",
                error_message="噪声电平为零或负值",
                category=self._category,
                unit="dB"
            )
        
        # 计算 SNR
        snr_db = 20 * np.log10(signal_level / noise_rms_v)
        
        condition = integrated_result.measurement_condition
        
        return create_metric_result(
            name="snr",
            display_name="信噪比",
            value=snr_db,
            unit="dB",
            category=self._category,
            measurement_condition=f"Vs={signal_level}V, {condition}",
            metadata={
                "signal_level_v": signal_level,
                "noise_rms_v": noise_rms_v,
                "freq_range": freq_range
            }
        )

    # ============================================================
    # 1/f 噪声角频率提取
    # ============================================================
    
    def extract_corner_frequency(
        self,
        data: SimulationData,
        noise_signal: str = "inoise"
    ) -> MetricResult:
        """
        提取 1/f 噪声角频率
        
        1/f 噪声角频率是 1/f 噪声与白噪声相等的频率点。
        在此频率以下，1/f 噪声占主导；以上则白噪声占主导。
        
        Args:
            data: 仿真数据
            noise_signal: 噪声信号名称
            
        Returns:
            MetricResult: 角频率指标结果（Hz）
        """
        if data.frequency is None or len(data.frequency) < 10:
            return create_error_metric(
                name="corner_frequency",
                display_name="1/f 角频率",
                error_message="噪声分析频率数据不足",
                category=self._category,
                unit="Hz"
            )
        
        noise = data.signals.get(noise_signal)
        if noise is None:
            for alt_name in ["inoise_total", "input_noise", "V(inoise)"]:
                noise = data.signals.get(alt_name)
                if noise is not None:
                    break
        
        if noise is None:
            return create_error_metric(
                name="corner_frequency",
                display_name="1/f 角频率",
                error_message=f"未找到噪声信号 {noise_signal}",
                category=self._category,
                unit="Hz"
            )
        
        noise = np.abs(noise)
        freq = data.frequency
        
        # 估算高频白噪声电平（取最高频率段的平均值）
        high_freq_idx = int(len(freq) * 0.8)
        white_noise_level = np.mean(noise[high_freq_idx:])
        
        # 找到噪声密度等于 √2 倍白噪声的频率点
        # 在角频率处，1/f 噪声 = 白噪声，总噪声 = √2 × 白噪声
        target_level = white_noise_level * np.sqrt(2)
        
        corner_freq = self._find_crossover_frequency(
            freq, noise, target_level, direction="down"
        )
        
        if corner_freq is None:
            return create_error_metric(
                name="corner_frequency",
                display_name="1/f 角频率",
                error_message="未找到 1/f 角频率",
                category=self._category,
                unit="Hz"
            )
        
        return create_metric_result(
            name="corner_frequency",
            display_name="1/f 角频率",
            value=corner_freq,
            unit="Hz",
            category=self._category,
            metadata={
                "white_noise_level": white_noise_level,
                "target_level": target_level
            }
        )

    # ============================================================
    # 等效噪声带宽提取
    # ============================================================
    
    def extract_equivalent_noise_bandwidth(
        self,
        data: SimulationData,
        gain_signal: str = "V(out)"
    ) -> MetricResult:
        """
        提取等效噪声带宽（ENBW）
        
        等效噪声带宽是一个理想矩形滤波器的带宽，该滤波器通过的
        白噪声功率与实际滤波器相同。
        
        ENBW = ∫|H(f)|² df / |H(f_peak)|²
        
        Args:
            data: 仿真数据（需包含 AC 分析结果）
            gain_signal: 增益信号名称
            
        Returns:
            MetricResult: 等效噪声带宽指标结果（Hz）
        """
        if data.frequency is None or len(data.frequency) < 2:
            return create_error_metric(
                name="enbw",
                display_name="等效噪声带宽",
                error_message="AC 分析频率数据不足",
                category=self._category,
                unit="Hz"
            )
        
        gain = data.signals.get(gain_signal)
        if gain is None:
            return create_error_metric(
                name="enbw",
                display_name="等效噪声带宽",
                error_message=f"未找到增益信号 {gain_signal}",
                category=self._category,
                unit="Hz"
            )
        
        gain_mag = np.abs(gain)
        freq = data.frequency
        
        # 找峰值增益
        peak_gain = np.max(gain_mag)
        if peak_gain <= 0:
            return create_error_metric(
                name="enbw",
                display_name="等效噪声带宽",
                error_message="增益峰值为零",
                category=self._category,
                unit="Hz"
            )
        
        # 归一化增益
        normalized_gain = gain_mag / peak_gain
        
        # 计算 ENBW = ∫|H(f)|² df
        enbw = np.trapezoid(normalized_gain ** 2, freq)
        
        return create_metric_result(
            name="enbw",
            display_name="等效噪声带宽",
            value=enbw,
            unit="Hz",
            category=self._category,
            metadata={
                "peak_gain": peak_gain,
                "freq_range": (freq[0], freq[-1])
            }
        )

    # ============================================================
    # 辅助方法
    # ============================================================
    
    def _find_nearest_index(self, array: np.ndarray, value: float) -> int:
        """找到数组中最接近指定值的索引"""
        return int(np.argmin(np.abs(array - value)))
    
    def _find_crossover_frequency(
        self,
        freq: np.ndarray,
        values: np.ndarray,
        target: float,
        direction: str = "down"
    ) -> Optional[float]:
        """
        找到值穿越目标的频率点
        
        Args:
            freq: 频率数组
            values: 值数组
            target: 目标值
            direction: "down" 表示从上往下穿越，"up" 表示从下往上穿越
            
        Returns:
            Optional[float]: 穿越频率，未找到返回 None
        """
        for i in range(len(values) - 1):
            if direction == "down":
                if values[i] >= target and values[i + 1] < target:
                    ratio = (target - values[i]) / (values[i + 1] - values[i])
                    return freq[i] + ratio * (freq[i + 1] - freq[i])
            else:
                if values[i] <= target and values[i + 1] > target:
                    ratio = (target - values[i]) / (values[i + 1] - values[i])
                    return freq[i] + ratio * (freq[i + 1] - freq[i])
        
        return None
    
    def _format_frequency(self, freq: float) -> str:
        """格式化频率显示"""
        if freq >= 1e9:
            return f"{freq / 1e9:.2f}GHz"
        elif freq >= 1e6:
            return f"{freq / 1e6:.2f}MHz"
        elif freq >= 1e3:
            return f"{freq / 1e3:.2f}kHz"
        else:
            return f"{freq:.2f}Hz"


# 模块级单例，便于直接导入使用
noise_metrics = NoiseMetrics()


__all__ = [
    "NoiseMetrics",
    "noise_metrics",
]
