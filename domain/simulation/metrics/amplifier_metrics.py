# AmplifierMetrics - Amplifier Performance Metrics Extraction
"""
放大器指标提取模块

职责：
- 从 AC 分析数据中提取增益、带宽、相位裕度等指标
- 从瞬态分析数据中提取压摆率、建立时间、过冲等指标
- 从 DC 分析数据中提取失调电压等指标

设计原则：
- 每个提取函数返回 MetricResult，包含值、单位、置信度
- 数据不足时返回错误指标而非抛异常
- 使用插值提高测量精度
- 支持复数信号（AC 分析）

使用示例：
    from domain.simulation.metrics.amplifier_metrics import AmplifierMetrics
    
    extractor = AmplifierMetrics()
    
    # 从 AC 数据提取增益
    gain = extractor.extract_gain(sim_data, freq_point=1000)
    
    # 从 AC 数据提取带宽
    bandwidth = extractor.extract_bandwidth(sim_data, output_signal="V(out)")
    
    # 从瞬态数据提取压摆率
    slew_rate = extractor.extract_slew_rate(sim_data, output_signal="V(out)")
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


class AmplifierMetrics:
    """
    放大器指标提取器
    
    提供从仿真数据中提取放大器性能指标的方法
    """
    
    def __init__(self):
        """初始化放大器指标提取器"""
        self._category = MetricCategory.AMPLIFIER

    # ============================================================
    # AC 分析指标提取
    # ============================================================
    
    def extract_gain(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        input_signal: Optional[str] = None,
        freq_point: Optional[float] = None
    ) -> MetricResult:
        """
        提取指定频率的增益（dB）
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            input_signal: 输入信号名称（None 时假设输入为 1V）
            freq_point: 测量频率点（None 时使用低频增益）
            
        Returns:
            MetricResult: 增益指标结果
        """
        if data.frequency is None or len(data.frequency) == 0:
            return create_error_metric(
                name="gain",
                display_name="增益",
                error_message="无 AC 分析频率数据",
                category=self._category,
                unit="dB"
            )
        
        output = data.signals.get(output_signal)
        if output is None:
            return create_error_metric(
                name="gain",
                display_name="增益",
                error_message=f"未找到输出信号 {output_signal}",
                category=self._category,
                unit="dB"
            )
        
        # 计算增益
        if input_signal is not None:
            input_data = data.signals.get(input_signal)
            if input_data is None:
                return create_error_metric(
                    name="gain",
                    display_name="增益",
                    error_message=f"未找到输入信号 {input_signal}",
                    category=self._category,
                    unit="dB"
                )
            gain_linear = np.abs(output) / np.abs(input_data)
        else:
            # 假设输入为 1V
            gain_linear = np.abs(output)
        
        # 转换为 dB
        gain_db = 20 * np.log10(gain_linear + 1e-30)  # 避免 log(0)
        
        # 确定测量点
        if freq_point is None:
            # 使用最低频率点作为低频增益
            idx = 0
            freq_used = data.frequency[0]
        else:
            # 插值到指定频率
            idx = self._find_nearest_index(data.frequency, freq_point)
            freq_used = data.frequency[idx]
        
        gain_value = float(gain_db[idx])
        condition = f"f={self._format_frequency(freq_used)}"
        
        return create_metric_result(
            name="gain",
            display_name="增益",
            value=gain_value,
            unit="dB",
            category=self._category,
            measurement_condition=condition,
            metadata={"frequency": freq_used, "output_signal": output_signal}
        )
    
    def extract_bandwidth(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        input_signal: Optional[str] = None,
        ref_gain_db: Optional[float] = None
    ) -> MetricResult:
        """
        提取 -3dB 带宽
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            input_signal: 输入信号名称
            ref_gain_db: 参考增益（None 时使用低频增益）
            
        Returns:
            MetricResult: 带宽指标结果
        """
        if data.frequency is None or len(data.frequency) < 2:
            return create_error_metric(
                name="bandwidth",
                display_name="带宽",
                error_message="AC 分析频率数据不足",
                category=self._category,
                unit="Hz"
            )
        
        output = data.signals.get(output_signal)
        if output is None:
            return create_error_metric(
                name="bandwidth",
                display_name="带宽",
                error_message=f"未找到输出信号 {output_signal}",
                category=self._category,
                unit="Hz"
            )
        
        # 计算增益
        if input_signal is not None:
            input_data = data.signals.get(input_signal)
            if input_data is None:
                gain_linear = np.abs(output)
            else:
                gain_linear = np.abs(output) / (np.abs(input_data) + 1e-30)
        else:
            gain_linear = np.abs(output)
        
        gain_db = 20 * np.log10(gain_linear + 1e-30)
        
        # 确定参考增益
        if ref_gain_db is None:
            ref_gain_db = gain_db[0]  # 低频增益
        
        # 找 -3dB 点
        target_gain = ref_gain_db - 3.0
        bw_freq = self._find_crossover_frequency(
            data.frequency, gain_db, target_gain, direction="down"
        )
        
        if bw_freq is None:
            return create_error_metric(
                name="bandwidth",
                display_name="带宽",
                error_message="未找到 -3dB 点",
                category=self._category,
                unit="Hz"
            )
        
        return create_metric_result(
            name="bandwidth",
            display_name="带宽",
            value=bw_freq,
            unit="Hz",
            category=self._category,
            measurement_condition=f"ref={ref_gain_db:.1f}dB",
            metadata={"reference_gain_db": ref_gain_db}
        )

    def extract_gbw(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        input_signal: Optional[str] = None
    ) -> MetricResult:
        """
        提取增益带宽积（GBW）
        
        GBW = 低频增益 × 带宽
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            input_signal: 输入信号名称
            
        Returns:
            MetricResult: GBW 指标结果
        """
        # 先提取增益和带宽
        gain_result = self.extract_gain(data, output_signal, input_signal)
        bw_result = self.extract_bandwidth(data, output_signal, input_signal)
        
        if not gain_result.is_valid:
            return create_error_metric(
                name="gbw",
                display_name="增益带宽积",
                error_message=f"增益提取失败: {gain_result.error_message}",
                category=self._category,
                unit="Hz"
            )
        
        if not bw_result.is_valid:
            return create_error_metric(
                name="gbw",
                display_name="增益带宽积",
                error_message=f"带宽提取失败: {bw_result.error_message}",
                category=self._category,
                unit="Hz"
            )
        
        # 计算 GBW
        gain_linear = 10 ** (gain_result.value / 20)
        gbw = gain_linear * bw_result.value
        
        return create_metric_result(
            name="gbw",
            display_name="增益带宽积",
            value=gbw,
            unit="Hz",
            category=self._category,
            metadata={
                "gain_db": gain_result.value,
                "bandwidth_hz": bw_result.value
            }
        )
    
    def extract_phase_margin(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        input_signal: Optional[str] = None
    ) -> MetricResult:
        """
        提取相位裕度
        
        在单位增益频率（0dB 交叉点）处测量相位与 -180° 的差值
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            input_signal: 输入信号名称
            
        Returns:
            MetricResult: 相位裕度指标结果
        """
        if data.frequency is None or len(data.frequency) < 2:
            return create_error_metric(
                name="phase_margin",
                display_name="相位裕度",
                error_message="AC 分析频率数据不足",
                category=self._category,
                unit="°"
            )
        
        output = data.signals.get(output_signal)
        if output is None:
            return create_error_metric(
                name="phase_margin",
                display_name="相位裕度",
                error_message=f"未找到输出信号 {output_signal}",
                category=self._category,
                unit="°"
            )
        
        # 计算增益和相位
        if input_signal is not None:
            input_data = data.signals.get(input_signal)
            if input_data is not None:
                transfer = output / (input_data + 1e-30)
            else:
                transfer = output
        else:
            transfer = output
        
        gain_db = 20 * np.log10(np.abs(transfer) + 1e-30)
        phase_deg = np.angle(transfer, deg=True)
        
        # 找单位增益频率（0dB 交叉点）
        unity_freq = self._find_crossover_frequency(
            data.frequency, gain_db, 0.0, direction="down"
        )
        
        if unity_freq is None:
            return create_error_metric(
                name="phase_margin",
                display_name="相位裕度",
                error_message="未找到单位增益频率",
                category=self._category,
                unit="°"
            )
        
        # 在单位增益频率处插值相位
        phase_at_unity = np.interp(unity_freq, data.frequency, phase_deg)
        
        # 相位裕度 = 180° + 相位（相位通常为负值）
        phase_margin = 180.0 + phase_at_unity
        
        return create_metric_result(
            name="phase_margin",
            display_name="相位裕度",
            value=phase_margin,
            unit="°",
            category=self._category,
            measurement_condition=f"f_unity={self._format_frequency(unity_freq)}",
            metadata={"unity_gain_frequency": unity_freq}
        )
    
    def extract_gain_margin(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        input_signal: Optional[str] = None
    ) -> MetricResult:
        """
        提取增益裕度
        
        在相位为 -180° 时测量增益与 0dB 的差值
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            input_signal: 输入信号名称
            
        Returns:
            MetricResult: 增益裕度指标结果
        """
        if data.frequency is None or len(data.frequency) < 2:
            return create_error_metric(
                name="gain_margin",
                display_name="增益裕度",
                error_message="AC 分析频率数据不足",
                category=self._category,
                unit="dB"
            )
        
        output = data.signals.get(output_signal)
        if output is None:
            return create_error_metric(
                name="gain_margin",
                display_name="增益裕度",
                error_message=f"未找到输出信号 {output_signal}",
                category=self._category,
                unit="dB"
            )
        
        # 计算增益和相位
        if input_signal is not None:
            input_data = data.signals.get(input_signal)
            if input_data is not None:
                transfer = output / (input_data + 1e-30)
            else:
                transfer = output
        else:
            transfer = output
        
        gain_db = 20 * np.log10(np.abs(transfer) + 1e-30)
        phase_deg = np.angle(transfer, deg=True)
        
        # 找 -180° 相位交叉频率
        phase_cross_freq = self._find_crossover_frequency(
            data.frequency, phase_deg, -180.0, direction="down"
        )
        
        if phase_cross_freq is None:
            return create_error_metric(
                name="gain_margin",
                display_name="增益裕度",
                error_message="未找到 -180° 相位交叉点",
                category=self._category,
                unit="dB"
            )
        
        # 在相位交叉频率处插值增益
        gain_at_cross = np.interp(phase_cross_freq, data.frequency, gain_db)
        
        # 增益裕度 = -增益（增益裕度为正表示稳定）
        gain_margin = -gain_at_cross
        
        return create_metric_result(
            name="gain_margin",
            display_name="增益裕度",
            value=gain_margin,
            unit="dB",
            category=self._category,
            measurement_condition=f"f_cross={self._format_frequency(phase_cross_freq)}",
            metadata={"phase_crossover_frequency": phase_cross_freq}
        )

    def extract_input_impedance(
        self,
        data: SimulationData,
        input_voltage: str = "V(in)",
        input_current: str = "I(Vin)"
    ) -> MetricResult:
        """
        提取输入阻抗（低频）
        
        Args:
            data: 仿真数据
            input_voltage: 输入电压信号名称
            input_current: 输入电流信号名称
            
        Returns:
            MetricResult: 输入阻抗指标结果
        """
        if data.frequency is None or len(data.frequency) == 0:
            return create_error_metric(
                name="input_impedance",
                display_name="输入阻抗",
                error_message="无 AC 分析频率数据",
                category=self._category,
                unit="Ω"
            )
        
        v_in = data.signals.get(input_voltage)
        i_in = data.signals.get(input_current)
        
        if v_in is None or i_in is None:
            return create_error_metric(
                name="input_impedance",
                display_name="输入阻抗",
                error_message="未找到输入电压或电流信号",
                category=self._category,
                unit="Ω"
            )
        
        # 计算阻抗（低频点）
        z_in = np.abs(v_in[0]) / (np.abs(i_in[0]) + 1e-30)
        
        return create_metric_result(
            name="input_impedance",
            display_name="输入阻抗",
            value=z_in,
            unit="Ω",
            category=self._category,
            measurement_condition=f"f={self._format_frequency(data.frequency[0])}"
        )
    
    def extract_output_impedance(
        self,
        data: SimulationData,
        output_voltage: str = "V(out)",
        output_current: str = "I(Rload)"
    ) -> MetricResult:
        """
        提取输出阻抗（低频）
        
        Args:
            data: 仿真数据
            output_voltage: 输出电压信号名称
            output_current: 输出电流信号名称
            
        Returns:
            MetricResult: 输出阻抗指标结果
        """
        if data.frequency is None or len(data.frequency) == 0:
            return create_error_metric(
                name="output_impedance",
                display_name="输出阻抗",
                error_message="无 AC 分析频率数据",
                category=self._category,
                unit="Ω"
            )
        
        v_out = data.signals.get(output_voltage)
        i_out = data.signals.get(output_current)
        
        if v_out is None or i_out is None:
            return create_error_metric(
                name="output_impedance",
                display_name="输出阻抗",
                error_message="未找到输出电压或电流信号",
                category=self._category,
                unit="Ω"
            )
        
        # 计算阻抗（低频点）
        z_out = np.abs(v_out[0]) / (np.abs(i_out[0]) + 1e-30)
        
        return create_metric_result(
            name="output_impedance",
            display_name="输出阻抗",
            value=z_out,
            unit="Ω",
            category=self._category,
            measurement_condition=f"f={self._format_frequency(data.frequency[0])}"
        )
    
    def extract_cmrr(
        self,
        data: SimulationData,
        diff_gain_signal: str = "V(out_diff)",
        cm_gain_signal: str = "V(out_cm)"
    ) -> MetricResult:
        """
        提取共模抑制比（CMRR）
        
        CMRR = 差模增益 / 共模增益（dB）
        
        Args:
            data: 仿真数据
            diff_gain_signal: 差模增益测量信号
            cm_gain_signal: 共模增益测量信号
            
        Returns:
            MetricResult: CMRR 指标结果
        """
        if data.frequency is None or len(data.frequency) == 0:
            return create_error_metric(
                name="cmrr",
                display_name="共模抑制比",
                error_message="无 AC 分析频率数据",
                category=self._category,
                unit="dB"
            )
        
        diff_gain = data.signals.get(diff_gain_signal)
        cm_gain = data.signals.get(cm_gain_signal)
        
        if diff_gain is None or cm_gain is None:
            return create_error_metric(
                name="cmrr",
                display_name="共模抑制比",
                error_message="未找到差模或共模增益信号",
                category=self._category,
                unit="dB"
            )
        
        # 计算 CMRR（低频点）
        cmrr_linear = np.abs(diff_gain[0]) / (np.abs(cm_gain[0]) + 1e-30)
        cmrr_db = 20 * np.log10(cmrr_linear + 1e-30)
        
        return create_metric_result(
            name="cmrr",
            display_name="共模抑制比",
            value=cmrr_db,
            unit="dB",
            category=self._category,
            measurement_condition=f"f={self._format_frequency(data.frequency[0])}"
        )
    
    def extract_psrr(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        supply_signal: str = "V(vdd)"
    ) -> MetricResult:
        """
        提取电源抑制比（PSRR）
        
        PSRR = 电源变化 / 输出变化（dB）
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            supply_signal: 电源信号名称
            
        Returns:
            MetricResult: PSRR 指标结果
        """
        if data.frequency is None or len(data.frequency) == 0:
            return create_error_metric(
                name="psrr",
                display_name="电源抑制比",
                error_message="无 AC 分析频率数据",
                category=self._category,
                unit="dB"
            )
        
        v_out = data.signals.get(output_signal)
        v_supply = data.signals.get(supply_signal)
        
        if v_out is None or v_supply is None:
            return create_error_metric(
                name="psrr",
                display_name="电源抑制比",
                error_message="未找到输出或电源信号",
                category=self._category,
                unit="dB"
            )
        
        # 计算 PSRR（低频点）
        psrr_linear = np.abs(v_supply[0]) / (np.abs(v_out[0]) + 1e-30)
        psrr_db = 20 * np.log10(psrr_linear + 1e-30)
        
        return create_metric_result(
            name="psrr",
            display_name="电源抑制比",
            value=psrr_db,
            unit="dB",
            category=self._category,
            measurement_condition=f"f={self._format_frequency(data.frequency[0])}"
        )

    # ============================================================
    # 瞬态分析指标提取
    # ============================================================
    
    def extract_slew_rate(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        low_percent: float = 10.0,
        high_percent: float = 90.0
    ) -> Tuple[MetricResult, MetricResult]:
        """
        提取压摆率（上升和下降）
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            low_percent: 低电平百分比
            high_percent: 高电平百分比
            
        Returns:
            Tuple[MetricResult, MetricResult]: (上升压摆率, 下降压摆率)
        """
        if data.time is None or len(data.time) < 2:
            error = create_error_metric(
                name="slew_rate_rise",
                display_name="上升压摆率",
                error_message="无瞬态分析时间数据",
                category=self._category,
                unit="V/μs"
            )
            return error, error
        
        output = data.signals.get(output_signal)
        if output is None:
            error = create_error_metric(
                name="slew_rate_rise",
                display_name="上升压摆率",
                error_message=f"未找到输出信号 {output_signal}",
                category=self._category,
                unit="V/μs"
            )
            return error, error
        
        # 确保是实数
        output = np.real(output)
        
        v_min = np.min(output)
        v_max = np.max(output)
        v_range = v_max - v_min
        
        if v_range < 1e-9:
            error = create_error_metric(
                name="slew_rate_rise",
                display_name="上升压摆率",
                error_message="输出信号变化太小",
                category=self._category,
                unit="V/μs"
            )
            return error, error
        
        v_low = v_min + v_range * low_percent / 100.0
        v_high = v_min + v_range * high_percent / 100.0
        
        # 计算上升压摆率
        sr_rise = self._calculate_slew_rate(
            data.time, output, v_low, v_high, rising=True
        )
        
        # 计算下降压摆率
        sr_fall = self._calculate_slew_rate(
            data.time, output, v_low, v_high, rising=False
        )
        
        rise_result = create_metric_result(
            name="slew_rate_rise",
            display_name="上升压摆率",
            value=sr_rise * 1e-6 if sr_rise else None,  # 转换为 V/μs
            unit="V/μs",
            category=self._category,
            measurement_condition=f"{low_percent:.0f}%-{high_percent:.0f}%"
        ) if sr_rise else create_error_metric(
            name="slew_rate_rise",
            display_name="上升压摆率",
            error_message="未找到上升沿",
            category=self._category,
            unit="V/μs"
        )
        
        fall_result = create_metric_result(
            name="slew_rate_fall",
            display_name="下降压摆率",
            value=abs(sr_fall * 1e-6) if sr_fall else None,  # 转换为 V/μs，取绝对值
            unit="V/μs",
            category=self._category,
            measurement_condition=f"{low_percent:.0f}%-{high_percent:.0f}%"
        ) if sr_fall else create_error_metric(
            name="slew_rate_fall",
            display_name="下降压摆率",
            error_message="未找到下降沿",
            category=self._category,
            unit="V/μs"
        )
        
        return rise_result, fall_result
    
    def extract_settling_time(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        target_value: Optional[float] = None,
        tolerance_percent: float = 1.0
    ) -> MetricResult:
        """
        提取建立时间
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            target_value: 目标值（None 时使用最终值）
            tolerance_percent: 容差百分比
            
        Returns:
            MetricResult: 建立时间指标结果
        """
        if data.time is None or len(data.time) < 2:
            return create_error_metric(
                name="settling_time",
                display_name="建立时间",
                error_message="无瞬态分析时间数据",
                category=self._category,
                unit="s"
            )
        
        output = data.signals.get(output_signal)
        if output is None:
            return create_error_metric(
                name="settling_time",
                display_name="建立时间",
                error_message=f"未找到输出信号 {output_signal}",
                category=self._category,
                unit="s"
            )
        
        output = np.real(output)
        
        # 确定目标值
        if target_value is None:
            target_value = output[-1]  # 使用最终值
        
        # 计算容差带
        tolerance = abs(target_value) * tolerance_percent / 100.0
        if tolerance < 1e-12:
            tolerance = 1e-12
        
        # 从后向前找第一个超出容差带的点
        settling_idx = len(output) - 1
        for i in range(len(output) - 1, -1, -1):
            if abs(output[i] - target_value) > tolerance:
                settling_idx = i + 1
                break
        
        if settling_idx >= len(data.time):
            settling_idx = len(data.time) - 1
        
        settling_time = data.time[settling_idx] - data.time[0]
        
        return create_metric_result(
            name="settling_time",
            display_name="建立时间",
            value=settling_time,
            unit="s",
            category=self._category,
            measurement_condition=f"±{tolerance_percent:.1f}%",
            metadata={"target_value": target_value, "tolerance": tolerance}
        )
    
    def extract_overshoot(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        final_value: Optional[float] = None
    ) -> MetricResult:
        """
        提取过冲量
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            final_value: 最终值（None 时使用最后一个点）
            
        Returns:
            MetricResult: 过冲量指标结果（百分比）
        """
        if data.time is None or len(data.time) < 2:
            return create_error_metric(
                name="overshoot",
                display_name="过冲",
                error_message="无瞬态分析时间数据",
                category=self._category,
                unit="%"
            )
        
        output = data.signals.get(output_signal)
        if output is None:
            return create_error_metric(
                name="overshoot",
                display_name="过冲",
                error_message=f"未找到输出信号 {output_signal}",
                category=self._category,
                unit="%"
            )
        
        output = np.real(output)
        
        if final_value is None:
            final_value = output[-1]
        
        initial_value = output[0]
        step_size = final_value - initial_value
        
        if abs(step_size) < 1e-12:
            return create_error_metric(
                name="overshoot",
                display_name="过冲",
                error_message="阶跃幅度太小",
                category=self._category,
                unit="%"
            )
        
        # 计算过冲
        if step_size > 0:
            # 上升阶跃
            peak = np.max(output)
            overshoot = (peak - final_value) / step_size * 100.0
        else:
            # 下降阶跃
            peak = np.min(output)
            overshoot = (final_value - peak) / abs(step_size) * 100.0
        
        overshoot = max(0, overshoot)  # 过冲不能为负
        
        return create_metric_result(
            name="overshoot",
            display_name="过冲",
            value=overshoot,
            unit="%",
            category=self._category,
            metadata={"final_value": final_value, "peak_value": peak}
        )

    # ============================================================
    # DC 分析指标提取
    # ============================================================
    
    def extract_offset_voltage(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        expected_output: float = 0.0,
        gain: Optional[float] = None
    ) -> MetricResult:
        """
        提取输入失调电压
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            expected_output: 期望输出电压
            gain: 放大器增益（用于计算输入失调）
            
        Returns:
            MetricResult: 输入失调电压指标结果
        """
        output = data.signals.get(output_signal)
        if output is None:
            return create_error_metric(
                name="offset_voltage",
                display_name="输入失调电压",
                error_message=f"未找到输出信号 {output_signal}",
                category=self._category,
                unit="V"
            )
        
        # 获取 DC 输出值
        if data.time is not None and len(data.time) > 0:
            # 瞬态分析，取最终值
            dc_output = np.real(output[-1])
        else:
            # DC 分析或 AC 分析的 DC 点
            dc_output = np.real(output[0]) if len(output) > 0 else 0.0
        
        output_offset = dc_output - expected_output
        
        # 计算输入失调
        if gain is not None and gain != 0:
            input_offset = output_offset / gain
        else:
            input_offset = output_offset  # 假设单位增益
        
        return create_metric_result(
            name="offset_voltage",
            display_name="输入失调电压",
            value=input_offset,
            unit="V",
            category=self._category,
            metadata={"output_offset": output_offset, "gain": gain}
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
                    # 线性插值
                    ratio = (target - values[i]) / (values[i + 1] - values[i])
                    return freq[i] + ratio * (freq[i + 1] - freq[i])
            else:
                if values[i] <= target and values[i + 1] > target:
                    ratio = (target - values[i]) / (values[i + 1] - values[i])
                    return freq[i] + ratio * (freq[i + 1] - freq[i])
        
        return None
    
    def _calculate_slew_rate(
        self,
        time: np.ndarray,
        signal: np.ndarray,
        v_low: float,
        v_high: float,
        rising: bool
    ) -> Optional[float]:
        """
        计算压摆率
        
        Args:
            time: 时间数组
            signal: 信号数组
            v_low: 低电平阈值
            v_high: 高电平阈值
            rising: True 表示上升沿，False 表示下降沿
            
        Returns:
            Optional[float]: 压摆率 (V/s)，未找到返回 None
        """
        if rising:
            # 找上升沿
            for i in range(len(signal) - 1):
                if signal[i] < v_low and signal[i + 1] >= v_low:
                    t_low = np.interp(v_low, [signal[i], signal[i + 1]], [time[i], time[i + 1]])
                    # 继续找高电平点
                    for j in range(i, len(signal) - 1):
                        if signal[j] < v_high and signal[j + 1] >= v_high:
                            t_high = np.interp(v_high, [signal[j], signal[j + 1]], [time[j], time[j + 1]])
                            dt = t_high - t_low
                            if dt > 0:
                                return (v_high - v_low) / dt
                            break
                    break
        else:
            # 找下降沿
            for i in range(len(signal) - 1):
                if signal[i] > v_high and signal[i + 1] <= v_high:
                    t_high = np.interp(v_high, [signal[i + 1], signal[i]], [time[i + 1], time[i]])
                    # 继续找低电平点
                    for j in range(i, len(signal) - 1):
                        if signal[j] > v_low and signal[j + 1] <= v_low:
                            t_low = np.interp(v_low, [signal[j + 1], signal[j]], [time[j + 1], time[j]])
                            dt = t_low - t_high
                            if dt > 0:
                                return -(v_high - v_low) / dt  # 负值表示下降
                            break
                    break
        
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
amplifier_metrics = AmplifierMetrics()


__all__ = [
    "AmplifierMetrics",
    "amplifier_metrics",
]
