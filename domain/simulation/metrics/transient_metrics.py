# TransientMetrics - Transient Performance Metrics Extraction
"""
瞬态指标提取模块

职责：
- 从瞬态分析数据中提取上升时间、下降时间
- 计算传播延迟
- 提取占空比和振荡频率

设计原则：
- 每个提取函数返回 MetricResult，包含值、单位、置信度
- 数据不足时返回错误指标而非抛异常
- 使用插值提高测量精度

使用示例：
    from domain.simulation.metrics.transient_metrics import TransientMetrics
    
    extractor = TransientMetrics()
    
    # 提取上升时间
    rise_time = extractor.extract_rise_time(sim_data, output_signal="V(out)")
    
    # 提取传播延迟
    delay = extractor.extract_propagation_delay(sim_data, input_signal="V(in)", output_signal="V(out)")
    
    # 提取振荡频率
    freq = extractor.extract_frequency(sim_data, output_signal="V(out)")
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


class TransientMetrics:
    """
    瞬态指标提取器
    
    提供从瞬态分析数据中提取时域性能指标的方法。
    适用于数字电路、时钟电路、脉冲响应分析等场景。
    """

    def __init__(self):
        """初始化瞬态指标提取器"""
        self._category = MetricCategory.TRANSIENT

    # ============================================================
    # 上升/下降时间提取
    # ============================================================
    
    def extract_rise_time(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        low_percent: float = 10.0,
        high_percent: float = 90.0
    ) -> MetricResult:
        """
        提取上升时间
        
        上升时间定义为信号从低电平百分比上升到高电平百分比所需的时间。
        默认使用 10%-90% 定义。
        
        Args:
            data: 仿真数据（需包含瞬态分析结果）
            output_signal: 输出信号名称
            low_percent: 低电平百分比（默认 10%）
            high_percent: 高电平百分比（默认 90%）
            
        Returns:
            MetricResult: 上升时间指标结果（秒）
        """
        if data.time is None or len(data.time) < 3:
            return create_error_metric(
                name="rise_time",
                display_name="上升时间",
                error_message="瞬态分析时间数据不足",
                category=self._category,
                unit="s"
            )
        
        signal = data.signals.get(output_signal)
        if signal is None:
            return create_error_metric(
                name="rise_time",
                display_name="上升时间",
                error_message=f"未找到输出信号 {output_signal}",
                category=self._category,
                unit="s"
            )
        
        signal = np.real(signal)
        time = data.time
        
        # 计算电平阈值
        v_min = np.min(signal)
        v_max = np.max(signal)
        v_range = v_max - v_min
        
        if v_range < 1e-12:
            return create_error_metric(
                name="rise_time",
                display_name="上升时间",
                error_message="信号幅度过小",
                category=self._category,
                unit="s"
            )
        
        v_low = v_min + v_range * low_percent / 100.0
        v_high = v_min + v_range * high_percent / 100.0
        
        # 找上升沿
        rise_time_value = self._find_edge_time(time, signal, v_low, v_high, rising=True)
        
        if rise_time_value is None:
            return create_error_metric(
                name="rise_time",
                display_name="上升时间",
                error_message="未找到有效上升沿",
                category=self._category,
                unit="s"
            )
        
        condition = f"{low_percent:.0f}%-{high_percent:.0f}%"
        
        return create_metric_result(
            name="rise_time",
            display_name="上升时间",
            value=rise_time_value,
            unit="s",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "low_percent": low_percent,
                "high_percent": high_percent,
                "v_low": v_low,
                "v_high": v_high,
                "output_signal": output_signal
            }
        )
    
    def extract_fall_time(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        low_percent: float = 10.0,
        high_percent: float = 90.0
    ) -> MetricResult:
        """
        提取下降时间
        
        下降时间定义为信号从高电平百分比下降到低电平百分比所需的时间。
        默认使用 90%-10% 定义。
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            low_percent: 低电平百分比（默认 10%）
            high_percent: 高电平百分比（默认 90%）
            
        Returns:
            MetricResult: 下降时间指标结果（秒）
        """
        if data.time is None or len(data.time) < 3:
            return create_error_metric(
                name="fall_time",
                display_name="下降时间",
                error_message="瞬态分析时间数据不足",
                category=self._category,
                unit="s"
            )
        
        signal = data.signals.get(output_signal)
        if signal is None:
            return create_error_metric(
                name="fall_time",
                display_name="下降时间",
                error_message=f"未找到输出信号 {output_signal}",
                category=self._category,
                unit="s"
            )
        
        signal = np.real(signal)
        time = data.time
        
        v_min = np.min(signal)
        v_max = np.max(signal)
        v_range = v_max - v_min
        
        if v_range < 1e-12:
            return create_error_metric(
                name="fall_time",
                display_name="下降时间",
                error_message="信号幅度过小",
                category=self._category,
                unit="s"
            )
        
        v_low = v_min + v_range * low_percent / 100.0
        v_high = v_min + v_range * high_percent / 100.0
        
        # 找下降沿
        fall_time_value = self._find_edge_time(time, signal, v_low, v_high, rising=False)
        
        if fall_time_value is None:
            return create_error_metric(
                name="fall_time",
                display_name="下降时间",
                error_message="未找到有效下降沿",
                category=self._category,
                unit="s"
            )
        
        condition = f"{high_percent:.0f}%-{low_percent:.0f}%"
        
        return create_metric_result(
            name="fall_time",
            display_name="下降时间",
            value=fall_time_value,
            unit="s",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "low_percent": low_percent,
                "high_percent": high_percent,
                "v_low": v_low,
                "v_high": v_high,
                "output_signal": output_signal
            }
        )

    # ============================================================
    # 传播延迟提取
    # ============================================================
    
    def extract_propagation_delay(
        self,
        data: SimulationData,
        input_signal: str = "V(in)",
        output_signal: str = "V(out)",
        threshold_percent: float = 50.0
    ) -> Tuple[MetricResult, MetricResult]:
        """
        提取传播延迟
        
        传播延迟分为：
        - tpLH: 输入下降沿到输出上升沿的延迟（低到高）
        - tpHL: 输入上升沿到输出下降沿的延迟（高到低）
        
        Args:
            data: 仿真数据
            input_signal: 输入信号名称
            output_signal: 输出信号名称
            threshold_percent: 阈值百分比（默认 50%）
            
        Returns:
            Tuple[MetricResult, MetricResult]: (tpLH, tpHL)
        """
        if data.time is None or len(data.time) < 3:
            error = create_error_metric(
                name="tpLH",
                display_name="传播延迟(LH)",
                error_message="瞬态分析时间数据不足",
                category=self._category,
                unit="s"
            )
            return error, error
        
        sig_in = data.signals.get(input_signal)
        sig_out = data.signals.get(output_signal)
        
        if sig_in is None:
            error = create_error_metric(
                name="tpLH",
                display_name="传播延迟(LH)",
                error_message=f"未找到输入信号 {input_signal}",
                category=self._category,
                unit="s"
            )
            return error, error
        
        if sig_out is None:
            error = create_error_metric(
                name="tpLH",
                display_name="传播延迟(LH)",
                error_message=f"未找到输出信号 {output_signal}",
                category=self._category,
                unit="s"
            )
            return error, error
        
        sig_in = np.real(sig_in)
        sig_out = np.real(sig_out)
        time = data.time
        
        # 计算输入和输出的阈值
        in_min, in_max = np.min(sig_in), np.max(sig_in)
        out_min, out_max = np.min(sig_out), np.max(sig_out)
        
        in_threshold = in_min + (in_max - in_min) * threshold_percent / 100.0
        out_threshold = out_min + (out_max - out_min) * threshold_percent / 100.0
        
        # 找输入边沿穿越点
        in_crossings = self._find_threshold_crossings(time, sig_in, in_threshold)
        out_crossings = self._find_threshold_crossings(time, sig_out, out_threshold)
        
        tpLH_value = None
        tpHL_value = None
        
        # tpLH: 输入下降沿 -> 输出上升沿（反相器行为）
        for t_in, direction_in in in_crossings:
            if direction_in == "falling":
                # 找输入下降沿后的第一个输出上升沿
                for t_out, direction_out in out_crossings:
                    if direction_out == "rising" and t_out > t_in:
                        tpLH_value = t_out - t_in
                        break
                if tpLH_value is not None:
                    break
        
        # tpHL: 输入上升沿 -> 输出下降沿（反相器行为）
        for t_in, direction_in in in_crossings:
            if direction_in == "rising":
                # 找输入上升沿后的第一个输出下降沿
                for t_out, direction_out in out_crossings:
                    if direction_out == "falling" and t_out > t_in:
                        tpHL_value = t_out - t_in
                        break
                if tpHL_value is not None:
                    break
        
        condition = f"阈值={threshold_percent:.0f}%"
        
        tpLH_result = create_metric_result(
            name="tpLH",
            display_name="传播延迟(LH)",
            value=tpLH_value,
            unit="s",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "threshold_percent": threshold_percent,
                "input_signal": input_signal,
                "output_signal": output_signal
            }
        ) if tpLH_value is not None else create_error_metric(
            name="tpLH",
            display_name="传播延迟(LH)",
            error_message="未找到有效的 LH 传播延迟",
            category=self._category,
            unit="s"
        )
        
        tpHL_result = create_metric_result(
            name="tpHL",
            display_name="传播延迟(HL)",
            value=tpHL_value,
            unit="s",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "threshold_percent": threshold_percent,
                "input_signal": input_signal,
                "output_signal": output_signal
            }
        ) if tpHL_value is not None else create_error_metric(
            name="tpHL",
            display_name="传播延迟(HL)",
            error_message="未找到有效的 HL 传播延迟",
            category=self._category,
            unit="s"
        )
        
        return tpLH_result, tpHL_result
    
    def extract_average_propagation_delay(
        self,
        data: SimulationData,
        input_signal: str = "V(in)",
        output_signal: str = "V(out)",
        threshold_percent: float = 50.0
    ) -> MetricResult:
        """
        提取平均传播延迟
        
        tp = (tpLH + tpHL) / 2
        
        Args:
            data: 仿真数据
            input_signal: 输入信号名称
            output_signal: 输出信号名称
            threshold_percent: 阈值百分比
            
        Returns:
            MetricResult: 平均传播延迟指标结果
        """
        tpLH, tpHL = self.extract_propagation_delay(
            data, input_signal, output_signal, threshold_percent
        )
        
        if not tpLH.is_valid and not tpHL.is_valid:
            return create_error_metric(
                name="propagation_delay",
                display_name="传播延迟",
                error_message="无法计算传播延迟",
                category=self._category,
                unit="s"
            )
        
        # 如果只有一个有效，使用该值
        if tpLH.is_valid and not tpHL.is_valid:
            return create_metric_result(
                name="propagation_delay",
                display_name="传播延迟",
                value=tpLH.value,
                unit="s",
                category=self._category,
                measurement_condition=f"tpLH only, 阈值={threshold_percent:.0f}%",
                confidence=0.8
            )
        
        if tpHL.is_valid and not tpLH.is_valid:
            return create_metric_result(
                name="propagation_delay",
                display_name="传播延迟",
                value=tpHL.value,
                unit="s",
                category=self._category,
                measurement_condition=f"tpHL only, 阈值={threshold_percent:.0f}%",
                confidence=0.8
            )
        
        # 两者都有效，计算平均值
        avg_delay = (tpLH.value + tpHL.value) / 2.0
        
        return create_metric_result(
            name="propagation_delay",
            display_name="传播延迟",
            value=avg_delay,
            unit="s",
            category=self._category,
            measurement_condition=f"阈值={threshold_percent:.0f}%",
            metadata={
                "tpLH": tpLH.value,
                "tpHL": tpHL.value,
                "threshold_percent": threshold_percent
            }
        )

    # ============================================================
    # 占空比提取
    # ============================================================
    
    def extract_duty_cycle(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        threshold_percent: float = 50.0
    ) -> MetricResult:
        """
        提取占空比
        
        占空比定义为信号高电平时间占周期的百分比。
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            threshold_percent: 阈值百分比（默认 50%）
            
        Returns:
            MetricResult: 占空比指标结果（百分比）
        """
        if data.time is None or len(data.time) < 3:
            return create_error_metric(
                name="duty_cycle",
                display_name="占空比",
                error_message="瞬态分析时间数据不足",
                category=self._category,
                unit="%"
            )
        
        signal = data.signals.get(output_signal)
        if signal is None:
            return create_error_metric(
                name="duty_cycle",
                display_name="占空比",
                error_message=f"未找到输出信号 {output_signal}",
                category=self._category,
                unit="%"
            )
        
        signal = np.real(signal)
        time = data.time
        
        v_min = np.min(signal)
        v_max = np.max(signal)
        v_range = v_max - v_min
        
        if v_range < 1e-12:
            return create_error_metric(
                name="duty_cycle",
                display_name="占空比",
                error_message="信号幅度过小",
                category=self._category,
                unit="%"
            )
        
        threshold = v_min + v_range * threshold_percent / 100.0
        
        # 找所有阈值穿越点
        crossings = self._find_threshold_crossings(time, signal, threshold)
        
        if len(crossings) < 2:
            return create_error_metric(
                name="duty_cycle",
                display_name="占空比",
                error_message="未找到足够的阈值穿越点",
                category=self._category,
                unit="%"
            )
        
        # 计算高电平时间和周期
        high_times = []
        periods = []
        
        i = 0
        while i < len(crossings) - 1:
            t1, dir1 = crossings[i]
            t2, dir2 = crossings[i + 1]
            
            if dir1 == "rising" and dir2 == "falling":
                # 上升沿到下降沿 = 高电平时间
                high_times.append(t2 - t1)
                
                # 找下一个上升沿计算周期
                if i + 2 < len(crossings):
                    t3, dir3 = crossings[i + 2]
                    if dir3 == "rising":
                        periods.append(t3 - t1)
                        i += 2
                        continue
            
            i += 1
        
        if not high_times or not periods:
            return create_error_metric(
                name="duty_cycle",
                display_name="占空比",
                error_message="无法计算占空比（未找到完整周期）",
                category=self._category,
                unit="%"
            )
        
        avg_high_time = np.mean(high_times)
        avg_period = np.mean(periods)
        
        duty_cycle = (avg_high_time / avg_period) * 100.0
        
        condition = f"阈值={threshold_percent:.0f}%"
        
        return create_metric_result(
            name="duty_cycle",
            display_name="占空比",
            value=duty_cycle,
            unit="%",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "threshold_percent": threshold_percent,
                "avg_high_time": avg_high_time,
                "avg_period": avg_period,
                "num_cycles": len(periods),
                "output_signal": output_signal
            }
        )

    # ============================================================
    # 振荡频率提取
    # ============================================================
    
    def extract_frequency(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        threshold_percent: float = 50.0
    ) -> MetricResult:
        """
        提取振荡频率
        
        通过测量周期来计算频率：f = 1 / T
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            threshold_percent: 阈值百分比（默认 50%）
            
        Returns:
            MetricResult: 振荡频率指标结果（Hz）
        """
        if data.time is None or len(data.time) < 3:
            return create_error_metric(
                name="frequency",
                display_name="振荡频率",
                error_message="瞬态分析时间数据不足",
                category=self._category,
                unit="Hz"
            )
        
        signal = data.signals.get(output_signal)
        if signal is None:
            return create_error_metric(
                name="frequency",
                display_name="振荡频率",
                error_message=f"未找到输出信号 {output_signal}",
                category=self._category,
                unit="Hz"
            )
        
        signal = np.real(signal)
        time = data.time
        
        v_min = np.min(signal)
        v_max = np.max(signal)
        v_range = v_max - v_min
        
        if v_range < 1e-12:
            return create_error_metric(
                name="frequency",
                display_name="振荡频率",
                error_message="信号幅度过小",
                category=self._category,
                unit="Hz"
            )
        
        threshold = v_min + v_range * threshold_percent / 100.0
        
        # 找所有上升沿穿越点
        crossings = self._find_threshold_crossings(time, signal, threshold)
        rising_times = [t for t, direction in crossings if direction == "rising"]
        
        if len(rising_times) < 2:
            return create_error_metric(
                name="frequency",
                display_name="振荡频率",
                error_message="未找到足够的周期",
                category=self._category,
                unit="Hz"
            )
        
        # 计算周期
        periods = np.diff(rising_times)
        
        if len(periods) == 0:
            return create_error_metric(
                name="frequency",
                display_name="振荡频率",
                error_message="无法计算周期",
                category=self._category,
                unit="Hz"
            )
        
        avg_period = np.mean(periods)
        
        if avg_period <= 0:
            return create_error_metric(
                name="frequency",
                display_name="振荡频率",
                error_message="周期计算异常",
                category=self._category,
                unit="Hz"
            )
        
        frequency = 1.0 / avg_period
        
        # 计算频率稳定性（标准差）
        period_std = np.std(periods) if len(periods) > 1 else 0.0
        freq_stability = (period_std / avg_period) * 100.0 if avg_period > 0 else 0.0
        
        condition = f"阈值={threshold_percent:.0f}%, {len(periods)}个周期"
        
        return create_metric_result(
            name="frequency",
            display_name="振荡频率",
            value=frequency,
            unit="Hz",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "threshold_percent": threshold_percent,
                "avg_period": avg_period,
                "period_std": period_std,
                "freq_stability_percent": freq_stability,
                "num_periods": len(periods),
                "output_signal": output_signal
            }
        )
    
    def extract_period(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        threshold_percent: float = 50.0
    ) -> MetricResult:
        """
        提取振荡周期
        
        Args:
            data: 仿真数据
            output_signal: 输出信号名称
            threshold_percent: 阈值百分比
            
        Returns:
            MetricResult: 振荡周期指标结果（秒）
        """
        freq_result = self.extract_frequency(data, output_signal, threshold_percent)
        
        if not freq_result.is_valid:
            return create_error_metric(
                name="period",
                display_name="振荡周期",
                error_message=freq_result.error_message,
                category=self._category,
                unit="s"
            )
        
        period = 1.0 / freq_result.value
        
        return create_metric_result(
            name="period",
            display_name="振荡周期",
            value=period,
            unit="s",
            category=self._category,
            measurement_condition=freq_result.measurement_condition,
            metadata=freq_result.metadata
        )

    # ============================================================
    # 辅助方法
    # ============================================================
    
    def _find_edge_time(
        self,
        time: np.ndarray,
        signal: np.ndarray,
        v_low: float,
        v_high: float,
        rising: bool = True
    ) -> Optional[float]:
        """
        找边沿时间（上升或下降）
        
        Args:
            time: 时间数组
            signal: 信号数组
            v_low: 低电平阈值
            v_high: 高电平阈值
            rising: True 为上升沿，False 为下降沿
            
        Returns:
            Optional[float]: 边沿时间，未找到返回 None
        """
        if rising:
            # 上升沿：找从 v_low 到 v_high 的时间
            t_low = self._find_crossing_time(time, signal, v_low, direction="rising")
            t_high = self._find_crossing_time(time, signal, v_high, direction="rising")
        else:
            # 下降沿：找从 v_high 到 v_low 的时间
            t_high = self._find_crossing_time(time, signal, v_high, direction="falling")
            t_low = self._find_crossing_time(time, signal, v_low, direction="falling")
        
        if t_low is None or t_high is None:
            return None
        
        edge_time = abs(t_high - t_low)
        return edge_time if edge_time > 0 else None
    
    def _find_crossing_time(
        self,
        time: np.ndarray,
        signal: np.ndarray,
        threshold: float,
        direction: str = "rising"
    ) -> Optional[float]:
        """
        找信号穿越阈值的时间点
        
        Args:
            time: 时间数组
            signal: 信号数组
            threshold: 阈值
            direction: "rising" 或 "falling"
            
        Returns:
            Optional[float]: 穿越时间，未找到返回 None
        """
        for i in range(len(signal) - 1):
            if direction == "rising":
                if signal[i] <= threshold < signal[i + 1]:
                    # 线性插值
                    ratio = (threshold - signal[i]) / (signal[i + 1] - signal[i])
                    return time[i] + ratio * (time[i + 1] - time[i])
            else:  # falling
                if signal[i] >= threshold > signal[i + 1]:
                    ratio = (signal[i] - threshold) / (signal[i] - signal[i + 1])
                    return time[i] + ratio * (time[i + 1] - time[i])
        
        return None
    
    def _find_threshold_crossings(
        self,
        time: np.ndarray,
        signal: np.ndarray,
        threshold: float
    ) -> List[Tuple[float, str]]:
        """
        找所有阈值穿越点
        
        Args:
            time: 时间数组
            signal: 信号数组
            threshold: 阈值
            
        Returns:
            List[Tuple[float, str]]: 穿越点列表，每项为 (时间, 方向)
        """
        crossings = []
        
        for i in range(len(signal) - 1):
            if signal[i] <= threshold < signal[i + 1]:
                # 上升沿穿越
                ratio = (threshold - signal[i]) / (signal[i + 1] - signal[i])
                t_cross = time[i] + ratio * (time[i + 1] - time[i])
                crossings.append((t_cross, "rising"))
            elif signal[i] >= threshold > signal[i + 1]:
                # 下降沿穿越
                ratio = (signal[i] - threshold) / (signal[i] - signal[i + 1])
                t_cross = time[i] + ratio * (time[i + 1] - time[i])
                crossings.append((t_cross, "falling"))
        
        return crossings
    
    def _format_time(self, t: float) -> str:
        """格式化时间显示"""
        if t >= 1.0:
            return f"{t:.3f}s"
        elif t >= 1e-3:
            return f"{t * 1e3:.3f}ms"
        elif t >= 1e-6:
            return f"{t * 1e6:.3f}μs"
        elif t >= 1e-9:
            return f"{t * 1e9:.3f}ns"
        else:
            return f"{t * 1e12:.3f}ps"
    
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
transient_metrics = TransientMetrics()


__all__ = [
    "TransientMetrics",
    "transient_metrics",
]
