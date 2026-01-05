# DistortionMetrics - Distortion Performance Metrics Extraction
"""
失真指标提取模块

职责：
- 从瞬态分析数据中通过 FFT 提取总谐波失真（THD）
- 计算 THD+N（总谐波失真加噪声）
- 提取互调失真（IMD）
- 计算无杂散动态范围（SFDR）
- 计算信噪失真比（SNDR）
- 计算有效位数（ENOB）

设计原则：
- 每个提取函数返回 MetricResult，包含值、单位、置信度
- 数据不足时返回错误指标而非抛异常
- 使用 numpy FFT 进行频谱分析
- 支持窗函数选择以减少频谱泄漏

使用示例：
    from domain.simulation.metrics.distortion_metrics import DistortionMetrics
    
    extractor = DistortionMetrics()
    
    # 从瞬态数据提取 THD
    thd = extractor.extract_thd(sim_data, output_signal="V(out)", fundamental_freq=1000)
    
    # 提取 SFDR
    sfdr = extractor.extract_sfdr(sim_data, output_signal="V(out)")
    
    # 计算 ENOB
    enob = extractor.extract_enob(sim_data, output_signal="V(out)")
"""

from typing import List, Optional, Tuple

import numpy as np

from domain.simulation.metrics.metric_result import (
    MetricCategory,
    MetricResult,
    create_error_metric,
    create_metric_result,
)
from domain.simulation.models.simulation_result import SimulationData


class DistortionMetrics:
    """
    失真指标提取器
    
    提供从仿真数据中提取失真性能指标的方法。
    主要用于分析放大器、ADC/DAC 等电路的非线性失真特性。
    """
    
    # 默认谐波分析阶数
    DEFAULT_HARMONIC_ORDER = 10
    
    # 最小 FFT 点数
    MIN_FFT_POINTS = 256
    
    def __init__(self):
        """初始化失真指标提取器"""
        self._category = MetricCategory.DISTORTION

    # ============================================================
    # THD 提取
    # ============================================================
    
    def extract_thd(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        fundamental_freq: Optional[float] = None,
        num_harmonics: int = DEFAULT_HARMONIC_ORDER,
        window: str = "hann"
    ) -> MetricResult:
        """
        提取总谐波失真（THD）
        
        THD 定义为所有谐波分量的 RMS 值与基波分量 RMS 值的比值：
        THD = √(V2² + V3² + ... + Vn²) / V1 × 100%
        
        Args:
            data: 仿真数据（需包含瞬态分析结果）
            output_signal: 输出信号名称
            fundamental_freq: 基波频率（None 时自动检测）
            num_harmonics: 分析的谐波阶数
            window: 窗函数类型（"hann", "hamming", "blackman", "none"）
            
        Returns:
            MetricResult: THD 指标结果（百分比）
        """
        if data.time is None or len(data.time) < self.MIN_FFT_POINTS:
            return create_error_metric(
                name="thd",
                display_name="总谐波失真",
                error_message=f"瞬态分析数据点不足（需要至少 {self.MIN_FFT_POINTS} 点）",
                category=self._category,
                unit="%"
            )
        
        signal = data.signals.get(output_signal)
        if signal is None:
            return create_error_metric(
                name="thd",
                display_name="总谐波失真",
                error_message=f"未找到输出信号 {output_signal}",
                category=self._category,
                unit="%"
            )
        
        signal = np.real(signal)
        time = data.time
        
        # 计算采样率
        dt = np.mean(np.diff(time))
        fs = 1.0 / dt
        
        # 应用窗函数并计算 FFT
        spectrum, freqs = self._compute_fft(signal, fs, window)
        
        # 检测或验证基波频率
        if fundamental_freq is None:
            fundamental_freq = self._detect_fundamental(spectrum, freqs)
            if fundamental_freq is None:
                return create_error_metric(
                    name="thd",
                    display_name="总谐波失真",
                    error_message="无法自动检测基波频率",
                    category=self._category,
                    unit="%"
                )
        
        # 提取基波和谐波幅度
        fundamental_amp = self._get_amplitude_at_freq(spectrum, freqs, fundamental_freq)
        
        if fundamental_amp < 1e-12:
            return create_error_metric(
                name="thd",
                display_name="总谐波失真",
                error_message="基波幅度过小",
                category=self._category,
                unit="%"
            )
        
        # 计算谐波分量
        harmonic_power_sum = 0.0
        harmonics_found = []
        
        for n in range(2, num_harmonics + 1):
            harmonic_freq = n * fundamental_freq
            if harmonic_freq > fs / 2:  # 超过奈奎斯特频率
                break
            harmonic_amp = self._get_amplitude_at_freq(spectrum, freqs, harmonic_freq)
            harmonic_power_sum += harmonic_amp ** 2
            harmonics_found.append((n, harmonic_freq, harmonic_amp))
        
        # 计算 THD
        thd_value = np.sqrt(harmonic_power_sum) / fundamental_amp * 100.0
        
        condition = f"f0={self._format_frequency(fundamental_freq)}, {len(harmonics_found)}次谐波"
        
        return create_metric_result(
            name="thd",
            display_name="总谐波失真",
            value=thd_value,
            unit="%",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "fundamental_freq": fundamental_freq,
                "fundamental_amplitude": fundamental_amp,
                "num_harmonics": len(harmonics_found),
                "harmonics": harmonics_found,
                "window": window
            }
        )
    
    def extract_thd_n(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        fundamental_freq: Optional[float] = None,
        bandwidth: Optional[Tuple[float, float]] = None,
        window: str = "hann"
    ) -> MetricResult:
        """
        提取 THD+N（总谐波失真加噪声）
        
        THD+N 包含所有谐波失真和噪声分量：
        THD+N = √(所有非基波分量功率) / V1 × 100%
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            fundamental_freq: 基波频率
            bandwidth: 分析带宽 (f_low, f_high)，None 时使用全带宽
            window: 窗函数类型
            
        Returns:
            MetricResult: THD+N 指标结果（百分比）
        """
        if data.time is None or len(data.time) < self.MIN_FFT_POINTS:
            return create_error_metric(
                name="thd_n",
                display_name="THD+N",
                error_message=f"瞬态分析数据点不足",
                category=self._category,
                unit="%"
            )
        
        signal = data.signals.get(output_signal)
        if signal is None:
            return create_error_metric(
                name="thd_n",
                display_name="THD+N",
                error_message=f"未找到输出信号 {output_signal}",
                category=self._category,
                unit="%"
            )
        
        signal = np.real(signal)
        time = data.time
        
        dt = np.mean(np.diff(time))
        fs = 1.0 / dt
        
        spectrum, freqs = self._compute_fft(signal, fs, window)
        
        if fundamental_freq is None:
            fundamental_freq = self._detect_fundamental(spectrum, freqs)
            if fundamental_freq is None:
                return create_error_metric(
                    name="thd_n",
                    display_name="THD+N",
                    error_message="无法自动检测基波频率",
                    category=self._category,
                    unit="%"
                )
        
        # 确定分析带宽
        if bandwidth is None:
            f_low, f_high = freqs[1], fs / 2
        else:
            f_low, f_high = bandwidth
        
        # 计算基波功率（使用窄带积分）
        fundamental_amp = self._get_amplitude_at_freq(spectrum, freqs, fundamental_freq)
        
        if fundamental_amp < 1e-12:
            return create_error_metric(
                name="thd_n",
                display_name="THD+N",
                error_message="基波幅度过小",
                category=self._category,
                unit="%"
            )
        
        # 计算总功率（带宽内）
        mask = (freqs >= f_low) & (freqs <= f_high)
        total_power = np.sum(spectrum[mask] ** 2)
        
        # 减去基波功率
        fundamental_power = fundamental_amp ** 2
        noise_and_distortion_power = total_power - fundamental_power
        
        if noise_and_distortion_power < 0:
            noise_and_distortion_power = 0
        
        thd_n_value = np.sqrt(noise_and_distortion_power) / fundamental_amp * 100.0
        
        condition = f"f0={self._format_frequency(fundamental_freq)}, BW={self._format_frequency(f_low)}-{self._format_frequency(f_high)}"
        
        return create_metric_result(
            name="thd_n",
            display_name="THD+N",
            value=thd_n_value,
            unit="%",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "fundamental_freq": fundamental_freq,
                "bandwidth": (f_low, f_high),
                "fundamental_amplitude": fundamental_amp,
                "total_power": total_power,
                "noise_distortion_power": noise_and_distortion_power
            }
        )

    # ============================================================
    # IMD 提取
    # ============================================================
    
    def extract_imd(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        f1: float = 1000.0,
        f2: float = 1100.0,
        window: str = "hann"
    ) -> MetricResult:
        """
        提取互调失真（IMD）
        
        使用双音测试，测量 f1 和 f2 两个频率的互调产物。
        主要关注二阶互调（f1±f2）和三阶互调（2f1-f2, 2f2-f1）。
        
        IMD = √(IM2² + IM3²) / √(V1² + V2²) × 100%
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            f1: 第一个测试频率
            f2: 第二个测试频率
            window: 窗函数类型
            
        Returns:
            MetricResult: IMD 指标结果（百分比）
        """
        if data.time is None or len(data.time) < self.MIN_FFT_POINTS:
            return create_error_metric(
                name="imd",
                display_name="互调失真",
                error_message="瞬态分析数据点不足",
                category=self._category,
                unit="%"
            )
        
        signal = data.signals.get(output_signal)
        if signal is None:
            return create_error_metric(
                name="imd",
                display_name="互调失真",
                error_message=f"未找到输出信号 {output_signal}",
                category=self._category,
                unit="%"
            )
        
        signal = np.real(signal)
        time = data.time
        
        dt = np.mean(np.diff(time))
        fs = 1.0 / dt
        
        spectrum, freqs = self._compute_fft(signal, fs, window)
        
        # 获取基波幅度
        amp_f1 = self._get_amplitude_at_freq(spectrum, freqs, f1)
        amp_f2 = self._get_amplitude_at_freq(spectrum, freqs, f2)
        
        fundamental_rms = np.sqrt(amp_f1 ** 2 + amp_f2 ** 2)
        
        if fundamental_rms < 1e-12:
            return create_error_metric(
                name="imd",
                display_name="互调失真",
                error_message="基波幅度过小",
                category=self._category,
                unit="%"
            )
        
        # 计算互调产物频率
        im_products = []
        
        # 二阶互调产物
        im2_freqs = [abs(f1 - f2), f1 + f2]
        for freq in im2_freqs:
            if 0 < freq < fs / 2:
                amp = self._get_amplitude_at_freq(spectrum, freqs, freq)
                im_products.append(("IM2", freq, amp))
        
        # 三阶互调产物
        im3_freqs = [abs(2 * f1 - f2), abs(2 * f2 - f1), 2 * f1 + f2, 2 * f2 + f1]
        for freq in im3_freqs:
            if 0 < freq < fs / 2:
                amp = self._get_amplitude_at_freq(spectrum, freqs, freq)
                im_products.append(("IM3", freq, amp))
        
        # 计算总 IMD
        im_power_sum = sum(amp ** 2 for _, _, amp in im_products)
        imd_value = np.sqrt(im_power_sum) / fundamental_rms * 100.0
        
        condition = f"f1={self._format_frequency(f1)}, f2={self._format_frequency(f2)}"
        
        return create_metric_result(
            name="imd",
            display_name="互调失真",
            value=imd_value,
            unit="%",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "f1": f1,
                "f2": f2,
                "amp_f1": amp_f1,
                "amp_f2": amp_f2,
                "im_products": im_products
            }
        )


    # ============================================================
    # SFDR 提取
    # ============================================================
    
    def extract_sfdr(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        fundamental_freq: Optional[float] = None,
        window: str = "hann"
    ) -> MetricResult:
        """
        提取无杂散动态范围（SFDR）
        
        SFDR 定义为基波幅度与最大杂散分量幅度的比值（dB）：
        SFDR = 20 * log10(V1 / V_spur_max)
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            fundamental_freq: 基波频率
            window: 窗函数类型
            
        Returns:
            MetricResult: SFDR 指标结果（dB）
        """
        if data.time is None or len(data.time) < self.MIN_FFT_POINTS:
            return create_error_metric(
                name="sfdr",
                display_name="无杂散动态范围",
                error_message="瞬态分析数据点不足",
                category=self._category,
                unit="dB"
            )
        
        signal = data.signals.get(output_signal)
        if signal is None:
            return create_error_metric(
                name="sfdr",
                display_name="无杂散动态范围",
                error_message=f"未找到输出信号 {output_signal}",
                category=self._category,
                unit="dB"
            )
        
        signal = np.real(signal)
        time = data.time
        
        dt = np.mean(np.diff(time))
        fs = 1.0 / dt
        
        spectrum, freqs = self._compute_fft(signal, fs, window)
        
        if fundamental_freq is None:
            fundamental_freq = self._detect_fundamental(spectrum, freqs)
            if fundamental_freq is None:
                return create_error_metric(
                    name="sfdr",
                    display_name="无杂散动态范围",
                    error_message="无法自动检测基波频率",
                    category=self._category,
                    unit="dB"
                )
        
        fundamental_amp = self._get_amplitude_at_freq(spectrum, freqs, fundamental_freq)
        
        if fundamental_amp < 1e-12:
            return create_error_metric(
                name="sfdr",
                display_name="无杂散动态范围",
                error_message="基波幅度过小",
                category=self._category,
                unit="dB"
            )
        
        # 找最大杂散分量（排除基波和 DC）
        fundamental_idx = self._find_nearest_index(freqs, fundamental_freq)
        
        # 创建掩码排除基波附近的频率（±3 个 bin）
        mask = np.ones(len(spectrum), dtype=bool)
        mask[0] = False  # 排除 DC
        
        exclude_range = 3
        low_idx = max(1, fundamental_idx - exclude_range)
        high_idx = min(len(spectrum), fundamental_idx + exclude_range + 1)
        mask[low_idx:high_idx] = False
        
        # 找最大杂散
        masked_spectrum = spectrum.copy()
        masked_spectrum[~mask] = 0
        
        max_spur_idx = np.argmax(masked_spectrum)
        max_spur_amp = masked_spectrum[max_spur_idx]
        max_spur_freq = freqs[max_spur_idx]
        
        if max_spur_amp < 1e-15:
            # 杂散极小，返回很大的 SFDR
            sfdr_value = 120.0  # 限制最大值
        else:
            sfdr_value = 20 * np.log10(fundamental_amp / max_spur_amp)
        
        condition = f"f0={self._format_frequency(fundamental_freq)}"
        
        return create_metric_result(
            name="sfdr",
            display_name="无杂散动态范围",
            value=sfdr_value,
            unit="dB",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "fundamental_freq": fundamental_freq,
                "fundamental_amplitude": fundamental_amp,
                "max_spur_freq": max_spur_freq,
                "max_spur_amplitude": max_spur_amp
            }
        )

    # ============================================================
    # SNDR 提取
    # ============================================================
    
    def extract_sndr(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        fundamental_freq: Optional[float] = None,
        bandwidth: Optional[Tuple[float, float]] = None,
        window: str = "hann"
    ) -> MetricResult:
        """
        提取信噪失真比（SNDR）
        
        SNDR 定义为信号功率与噪声加失真功率的比值（dB）：
        SNDR = 10 * log10(P_signal / P_noise+distortion)
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            fundamental_freq: 基波频率
            bandwidth: 分析带宽
            window: 窗函数类型
            
        Returns:
            MetricResult: SNDR 指标结果（dB）
        """
        if data.time is None or len(data.time) < self.MIN_FFT_POINTS:
            return create_error_metric(
                name="sndr",
                display_name="信噪失真比",
                error_message="瞬态分析数据点不足",
                category=self._category,
                unit="dB"
            )
        
        signal = data.signals.get(output_signal)
        if signal is None:
            return create_error_metric(
                name="sndr",
                display_name="信噪失真比",
                error_message=f"未找到输出信号 {output_signal}",
                category=self._category,
                unit="dB"
            )
        
        signal = np.real(signal)
        time = data.time
        
        dt = np.mean(np.diff(time))
        fs = 1.0 / dt
        
        spectrum, freqs = self._compute_fft(signal, fs, window)
        
        if fundamental_freq is None:
            fundamental_freq = self._detect_fundamental(spectrum, freqs)
            if fundamental_freq is None:
                return create_error_metric(
                    name="sndr",
                    display_name="信噪失真比",
                    error_message="无法自动检测基波频率",
                    category=self._category,
                    unit="dB"
                )
        
        # 确定分析带宽
        if bandwidth is None:
            f_low, f_high = freqs[1], fs / 2
        else:
            f_low, f_high = bandwidth
        
        # 计算基波功率
        fundamental_amp = self._get_amplitude_at_freq(spectrum, freqs, fundamental_freq)
        signal_power = fundamental_amp ** 2
        
        if signal_power < 1e-24:
            return create_error_metric(
                name="sndr",
                display_name="信噪失真比",
                error_message="信号功率过小",
                category=self._category,
                unit="dB"
            )
        
        # 计算带宽内总功率
        mask = (freqs >= f_low) & (freqs <= f_high)
        total_power = np.sum(spectrum[mask] ** 2)
        
        # 噪声+失真功率
        noise_distortion_power = total_power - signal_power
        if noise_distortion_power < 1e-30:
            noise_distortion_power = 1e-30
        
        sndr_value = 10 * np.log10(signal_power / noise_distortion_power)
        
        condition = f"f0={self._format_frequency(fundamental_freq)}"
        
        return create_metric_result(
            name="sndr",
            display_name="信噪失真比",
            value=sndr_value,
            unit="dB",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "fundamental_freq": fundamental_freq,
                "signal_power": signal_power,
                "noise_distortion_power": noise_distortion_power,
                "bandwidth": (f_low, f_high)
            }
        )

    # ============================================================
    # ENOB 提取
    # ============================================================
    
    def extract_enob(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        fundamental_freq: Optional[float] = None,
        bandwidth: Optional[Tuple[float, float]] = None,
        window: str = "hann"
    ) -> MetricResult:
        """
        提取有效位数（ENOB）
        
        ENOB 从 SNDR 计算得出：
        ENOB = (SNDR - 1.76) / 6.02
        
        这是基于理想 ADC 的量化噪声公式推导的。
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            fundamental_freq: 基波频率
            bandwidth: 分析带宽
            window: 窗函数类型
            
        Returns:
            MetricResult: ENOB 指标结果（位）
        """
        # 先计算 SNDR
        sndr_result = self.extract_sndr(
            data, output_signal, fundamental_freq, bandwidth, window
        )
        
        if not sndr_result.is_valid:
            return create_error_metric(
                name="enob",
                display_name="有效位数",
                error_message=f"SNDR 计算失败: {sndr_result.error_message}",
                category=self._category,
                unit="bits"
            )
        
        sndr_db = sndr_result.value
        
        # ENOB = (SNDR - 1.76) / 6.02
        enob_value = (sndr_db - 1.76) / 6.02
        
        # ENOB 不能为负
        if enob_value < 0:
            enob_value = 0
        
        return create_metric_result(
            name="enob",
            display_name="有效位数",
            value=enob_value,
            unit="bits",
            category=self._category,
            measurement_condition=sndr_result.measurement_condition,
            metadata={
                "sndr_db": sndr_db,
                **sndr_result.metadata
            }
        )

    # ============================================================
    # 谐波分析
    # ============================================================
    
    def extract_harmonics(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        fundamental_freq: Optional[float] = None,
        num_harmonics: int = DEFAULT_HARMONIC_ORDER,
        window: str = "hann"
    ) -> Tuple[MetricResult, List[MetricResult]]:
        """
        提取各次谐波幅度
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            fundamental_freq: 基波频率
            num_harmonics: 分析的谐波阶数
            window: 窗函数类型
            
        Returns:
            Tuple[MetricResult, List[MetricResult]]: (基波结果, 各次谐波结果列表)
        """
        if data.time is None or len(data.time) < self.MIN_FFT_POINTS:
            error = create_error_metric(
                name="fundamental",
                display_name="基波",
                error_message="瞬态分析数据点不足",
                category=self._category,
                unit="V"
            )
            return error, []
        
        signal = data.signals.get(output_signal)
        if signal is None:
            error = create_error_metric(
                name="fundamental",
                display_name="基波",
                error_message=f"未找到输出信号 {output_signal}",
                category=self._category,
                unit="V"
            )
            return error, []
        
        signal = np.real(signal)
        time = data.time
        
        dt = np.mean(np.diff(time))
        fs = 1.0 / dt
        
        spectrum, freqs = self._compute_fft(signal, fs, window)
        
        if fundamental_freq is None:
            fundamental_freq = self._detect_fundamental(spectrum, freqs)
            if fundamental_freq is None:
                error = create_error_metric(
                    name="fundamental",
                    display_name="基波",
                    error_message="无法自动检测基波频率",
                    category=self._category,
                    unit="V"
                )
                return error, []
        
        # 基波
        fundamental_amp = self._get_amplitude_at_freq(spectrum, freqs, fundamental_freq)
        fundamental_result = create_metric_result(
            name="fundamental",
            display_name="基波",
            value=fundamental_amp,
            unit="V",
            category=self._category,
            measurement_condition=f"f={self._format_frequency(fundamental_freq)}"
        )
        
        # 各次谐波
        harmonic_results = []
        for n in range(2, num_harmonics + 1):
            harmonic_freq = n * fundamental_freq
            if harmonic_freq > fs / 2:
                break
            
            harmonic_amp = self._get_amplitude_at_freq(spectrum, freqs, harmonic_freq)
            
            # 计算相对于基波的 dB 值
            if fundamental_amp > 1e-12:
                relative_db = 20 * np.log10(harmonic_amp / fundamental_amp + 1e-30)
            else:
                relative_db = -120.0
            
            result = create_metric_result(
                name=f"harmonic_{n}",
                display_name=f"{n}次谐波",
                value=relative_db,
                unit="dBc",
                category=self._category,
                measurement_condition=f"f={self._format_frequency(harmonic_freq)}",
                metadata={
                    "order": n,
                    "frequency": harmonic_freq,
                    "amplitude_v": harmonic_amp
                }
            )
            harmonic_results.append(result)
        
        return fundamental_result, harmonic_results


    # ============================================================
    # 辅助方法
    # ============================================================
    
    def _compute_fft(
        self,
        signal: np.ndarray,
        fs: float,
        window: str = "hann"
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        计算信号的 FFT
        
        Args:
            signal: 时域信号
            fs: 采样率
            window: 窗函数类型
            
        Returns:
            Tuple[np.ndarray, np.ndarray]: (幅度谱, 频率数组)
        """
        n = len(signal)
        
        # 应用窗函数
        if window == "hann":
            win = np.hanning(n)
        elif window == "hamming":
            win = np.hamming(n)
        elif window == "blackman":
            win = np.blackman(n)
        else:
            win = np.ones(n)
        
        # 窗函数归一化因子（保持幅度正确）
        win_norm = np.sum(win) / n
        
        # 应用窗函数
        windowed_signal = signal * win
        
        # 计算 FFT
        fft_result = np.fft.rfft(windowed_signal)
        
        # 计算幅度谱（归一化）
        spectrum = np.abs(fft_result) * 2 / n / win_norm
        spectrum[0] /= 2  # DC 分量不需要乘 2
        
        # 频率数组
        freqs = np.fft.rfftfreq(n, 1 / fs)
        
        return spectrum, freqs
    
    def _detect_fundamental(
        self,
        spectrum: np.ndarray,
        freqs: np.ndarray,
        min_freq: float = 10.0
    ) -> Optional[float]:
        """
        自动检测基波频率
        
        通过找频谱中的最大峰值来检测基波。
        
        Args:
            spectrum: 幅度谱
            freqs: 频率数组
            min_freq: 最小搜索频率（排除 DC 附近）
            
        Returns:
            Optional[float]: 检测到的基波频率，失败返回 None
        """
        # 排除 DC 和低频
        mask = freqs >= min_freq
        if not np.any(mask):
            return None
        
        masked_spectrum = spectrum.copy()
        masked_spectrum[~mask] = 0
        
        # 找最大峰值
        peak_idx = np.argmax(masked_spectrum)
        
        if masked_spectrum[peak_idx] < 1e-12:
            return None
        
        # 使用抛物线插值提高频率精度
        if 0 < peak_idx < len(spectrum) - 1:
            alpha = spectrum[peak_idx - 1]
            beta = spectrum[peak_idx]
            gamma = spectrum[peak_idx + 1]
            
            if beta > alpha and beta > gamma:
                delta = 0.5 * (alpha - gamma) / (alpha - 2 * beta + gamma + 1e-30)
                refined_idx = peak_idx + delta
                
                # 插值得到精确频率
                df = freqs[1] - freqs[0]
                return freqs[0] + refined_idx * df
        
        return freqs[peak_idx]
    
    def _get_amplitude_at_freq(
        self,
        spectrum: np.ndarray,
        freqs: np.ndarray,
        target_freq: float
    ) -> float:
        """
        获取指定频率处的幅度
        
        使用抛物线插值提高精度。
        
        Args:
            spectrum: 幅度谱
            freqs: 频率数组
            target_freq: 目标频率
            
        Returns:
            float: 幅度值
        """
        idx = self._find_nearest_index(freqs, target_freq)
        
        # 简单情况：直接返回最近点
        if idx == 0 or idx >= len(spectrum) - 1:
            return float(spectrum[idx])
        
        # 抛物线插值
        alpha = spectrum[idx - 1]
        beta = spectrum[idx]
        gamma = spectrum[idx + 1]
        
        # 找峰值位置
        denom = alpha - 2 * beta + gamma
        if abs(denom) < 1e-30:
            return float(beta)
        
        delta = 0.5 * (alpha - gamma) / denom
        
        # 插值幅度
        interpolated_amp = beta - 0.25 * (alpha - gamma) * delta
        
        return float(max(interpolated_amp, 0))
    
    def _find_nearest_index(self, array: np.ndarray, value: float) -> int:
        """找到数组中最接近指定值的索引"""
        return int(np.argmin(np.abs(array - value)))
    
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
distortion_metrics = DistortionMetrics()


__all__ = [
    "DistortionMetrics",
    "distortion_metrics",
]
