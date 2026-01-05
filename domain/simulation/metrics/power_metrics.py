# PowerMetrics - Power Performance Metrics Extraction
"""
电源指标提取模块

职责：
- 从 DC 分析数据中提取静态电流、功耗
- 从瞬态分析数据中提取效率、调整率
- 计算元件功耗分布和温升估算

设计原则：
- 每个提取函数返回 MetricResult，包含值、单位、置信度
- 数据不足时返回错误指标而非抛异常
- 支持多种电源电路类型（LDO、DC-DC、放大器）

使用示例：
    from domain.simulation.metrics.power_metrics import PowerMetrics
    
    extractor = PowerMetrics()
    
    # 从 DC 数据提取静态电流
    iq = extractor.extract_quiescent_current(sim_data, supply_current="I(Vdd)")
    
    # 从瞬态数据提取效率
    eff = extractor.extract_efficiency(sim_data, input_power_signal="P(in)", output_power_signal="P(out)")
    
    # 提取负载调整率
    load_reg = extractor.extract_load_regulation(sim_data, output_signal="V(out)", load_current_signal="I(Rload)")
"""

from typing import Dict, List, Optional, Tuple

import numpy as np

from domain.simulation.metrics.metric_result import (
    MetricCategory,
    MetricResult,
    create_error_metric,
    create_metric_result,
)
from domain.simulation.models.simulation_result import SimulationData


class PowerMetrics:
    """
    电源指标提取器
    
    提供从仿真数据中提取电源性能指标的方法。
    适用于 LDO、DC-DC 转换器、放大器等电路的功耗分析。
    """

    def __init__(self):
        """初始化电源指标提取器"""
        self._category = MetricCategory.POWER

    # ============================================================
    # 静态功耗指标
    # ============================================================
    
    def extract_quiescent_current(
        self,
        data: SimulationData,
        supply_current: str = "I(Vdd)",
        no_load: bool = True
    ) -> MetricResult:
        """
        提取静态电流（Iq）
        
        静态电流是电路在无负载或空载条件下从电源汲取的电流。
        对于 LDO 和放大器，这是衡量功耗效率的关键指标。
        
        Args:
            data: 仿真数据（DC 或瞬态分析）
            supply_current: 电源电流信号名称
            no_load: 是否为无负载条件
            
        Returns:
            MetricResult: 静态电流指标结果（A 或 μA）
        """
        current = data.signals.get(supply_current)
        if current is None:
            # 尝试其他常见命名
            for alt_name in ["I(VDD)", "I(Vcc)", "I(VCC)", "I(vdd)", "I(V1)"]:
                current = data.signals.get(alt_name)
                if current is not None:
                    break
        
        if current is None:
            return create_error_metric(
                name="quiescent_current",
                display_name="静态电流",
                error_message=f"未找到电源电流信号 {supply_current}",
                category=self._category,
                unit="A"
            )
        
        # 取绝对值（电流方向可能为负）
        current = np.abs(np.real(current))
        
        # 根据数据类型确定测量值
        if data.time is not None and len(data.time) > 0:
            # 瞬态分析：取稳态值（最后 10% 的平均值）
            steady_start = int(len(current) * 0.9)
            iq_value = float(np.mean(current[steady_start:]))
            condition = "稳态平均"
        else:
            # DC 分析：取第一个点
            iq_value = float(current[0]) if len(current) > 0 else 0.0
            condition = "DC 工作点"
        
        if no_load:
            condition += ", 无负载"
        
        return create_metric_result(
            name="quiescent_current",
            display_name="静态电流",
            value=iq_value,
            unit="A",
            category=self._category,
            measurement_condition=condition,
            metadata={"supply_current_signal": supply_current, "no_load": no_load}
        )
    
    def extract_power_consumption(
        self,
        data: SimulationData,
        supply_voltage: str = "V(vdd)",
        supply_current: str = "I(Vdd)",
        vdd_value: Optional[float] = None
    ) -> MetricResult:
        """
        提取总功耗
        
        功耗 = 电源电压 × 电源电流
        
        Args:
            data: 仿真数据
            supply_voltage: 电源电压信号名称
            supply_current: 电源电流信号名称
            vdd_value: 已知电源电压值（若提供则不从信号读取）
            
        Returns:
            MetricResult: 功耗指标结果（W 或 mW）
        """
        # 获取电流
        current = data.signals.get(supply_current)
        if current is None:
            for alt_name in ["I(VDD)", "I(Vcc)", "I(VCC)", "I(vdd)", "I(V1)"]:
                current = data.signals.get(alt_name)
                if current is not None:
                    break
        
        if current is None:
            return create_error_metric(
                name="power_consumption",
                display_name="功耗",
                error_message=f"未找到电源电流信号 {supply_current}",
                category=self._category,
                unit="W"
            )
        
        current = np.abs(np.real(current))
        
        # 获取电压
        if vdd_value is not None:
            voltage = vdd_value
        else:
            v_signal = data.signals.get(supply_voltage)
            if v_signal is None:
                for alt_name in ["V(VDD)", "V(Vcc)", "V(VCC)", "V(vdd)"]:
                    v_signal = data.signals.get(alt_name)
                    if v_signal is not None:
                        break
            
            if v_signal is None:
                return create_error_metric(
                    name="power_consumption",
                    display_name="功耗",
                    error_message=f"未找到电源电压信号 {supply_voltage}，请提供 vdd_value",
                    category=self._category,
                    unit="W"
                )
            voltage = np.abs(np.real(v_signal))
        
        # 计算功耗
        if isinstance(voltage, np.ndarray):
            power = voltage * current
            # 取稳态平均值
            if data.time is not None and len(data.time) > 0:
                steady_start = int(len(power) * 0.9)
                power_value = float(np.mean(power[steady_start:]))
                condition = "稳态平均"
            else:
                power_value = float(power[0]) if len(power) > 0 else 0.0
                condition = "DC 工作点"
        else:
            # 电压为标量
            if data.time is not None and len(data.time) > 0:
                steady_start = int(len(current) * 0.9)
                avg_current = float(np.mean(current[steady_start:]))
                condition = "稳态平均"
            else:
                avg_current = float(current[0]) if len(current) > 0 else 0.0
                condition = "DC 工作点"
            power_value = voltage * avg_current
        
        return create_metric_result(
            name="power_consumption",
            display_name="功耗",
            value=power_value,
            unit="W",
            category=self._category,
            measurement_condition=condition,
            metadata={"supply_voltage": supply_voltage, "supply_current": supply_current}
        )

    # ============================================================
    # 效率指标
    # ============================================================
    
    def extract_efficiency(
        self,
        data: SimulationData,
        output_voltage: str = "V(out)",
        output_current: str = "I(Rload)",
        input_voltage: str = "V(vin)",
        input_current: str = "I(Vin)"
    ) -> MetricResult:
        """
        提取效率（电源电路）
        
        效率 = 输出功率 / 输入功率 × 100%
        
        Args:
            data: 仿真数据（瞬态分析）
            output_voltage: 输出电压信号名称
            output_current: 输出电流信号名称
            input_voltage: 输入电压信号名称
            input_current: 输入电流信号名称
            
        Returns:
            MetricResult: 效率指标结果（%）
        """
        # 获取输出信号
        v_out = data.signals.get(output_voltage)
        i_out = data.signals.get(output_current)
        
        if v_out is None or i_out is None:
            return create_error_metric(
                name="efficiency",
                display_name="效率",
                error_message="未找到输出电压或电流信号",
                category=self._category,
                unit="%"
            )
        
        # 获取输入信号
        v_in = data.signals.get(input_voltage)
        i_in = data.signals.get(input_current)
        
        if v_in is None or i_in is None:
            return create_error_metric(
                name="efficiency",
                display_name="效率",
                error_message="未找到输入电压或电流信号",
                category=self._category,
                unit="%"
            )
        
        v_out = np.abs(np.real(v_out))
        i_out = np.abs(np.real(i_out))
        v_in = np.abs(np.real(v_in))
        i_in = np.abs(np.real(i_in))
        
        # 计算功率
        p_out = v_out * i_out
        p_in = v_in * i_in
        
        # 取稳态平均值
        if data.time is not None and len(data.time) > 0:
            steady_start = int(len(p_out) * 0.9)
            avg_p_out = float(np.mean(p_out[steady_start:]))
            avg_p_in = float(np.mean(p_in[steady_start:]))
            condition = "稳态平均"
        else:
            avg_p_out = float(p_out[0]) if len(p_out) > 0 else 0.0
            avg_p_in = float(p_in[0]) if len(p_in) > 0 else 0.0
            condition = "DC 工作点"
        
        if avg_p_in < 1e-12:
            return create_error_metric(
                name="efficiency",
                display_name="效率",
                error_message="输入功率过小",
                category=self._category,
                unit="%"
            )
        
        efficiency = (avg_p_out / avg_p_in) * 100.0
        
        return create_metric_result(
            name="efficiency",
            display_name="效率",
            value=efficiency,
            unit="%",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "output_power_w": avg_p_out,
                "input_power_w": avg_p_in,
                "power_loss_w": avg_p_in - avg_p_out
            }
        )
    
    def extract_efficiency_curve(
        self,
        data: SimulationData,
        output_voltage: str = "V(out)",
        output_current: str = "I(Rload)",
        input_voltage: str = "V(vin)",
        input_current: str = "I(Vin)",
        num_points: int = 20
    ) -> MetricResult:
        """
        提取效率随负载变化曲线
        
        从瞬态数据中提取效率随时间（负载）变化的曲线数据。
        
        Args:
            data: 仿真数据（瞬态分析，负载扫描）
            output_voltage: 输出电压信号名称
            output_current: 输出电流信号名称
            input_voltage: 输入电压信号名称
            input_current: 输入电流信号名称
            num_points: 采样点数
            
        Returns:
            MetricResult: 效率曲线数据
        """
        if data.time is None or len(data.time) < num_points:
            return create_error_metric(
                name="efficiency_curve",
                display_name="效率曲线",
                error_message="瞬态数据点不足",
                category=self._category,
                unit="%"
            )
        
        v_out = data.signals.get(output_voltage)
        i_out = data.signals.get(output_current)
        v_in = data.signals.get(input_voltage)
        i_in = data.signals.get(input_current)
        
        if any(s is None for s in [v_out, i_out, v_in, i_in]):
            return create_error_metric(
                name="efficiency_curve",
                display_name="效率曲线",
                error_message="缺少必要的电压或电流信号",
                category=self._category,
                unit="%"
            )
        
        v_out = np.abs(np.real(v_out))
        i_out = np.abs(np.real(i_out))
        v_in = np.abs(np.real(v_in))
        i_in = np.abs(np.real(i_in))
        
        p_out = v_out * i_out
        p_in = v_in * i_in
        
        # 避免除零
        p_in = np.where(p_in < 1e-12, 1e-12, p_in)
        efficiency = (p_out / p_in) * 100.0
        
        # 降采样
        indices = np.linspace(0, len(efficiency) - 1, num_points, dtype=int)
        sampled_load = i_out[indices].tolist()
        sampled_eff = efficiency[indices].tolist()
        
        # 找峰值效率
        peak_idx = np.argmax(efficiency)
        peak_efficiency = float(efficiency[peak_idx])
        peak_load_current = float(i_out[peak_idx])
        
        return create_metric_result(
            name="efficiency_curve",
            display_name="效率曲线",
            value=peak_efficiency,
            unit="%",
            category=self._category,
            measurement_condition=f"峰值效率 @ Iload={self._format_current(peak_load_current)}",
            metadata={
                "load_current_a": sampled_load,
                "efficiency_percent": sampled_eff,
                "peak_efficiency": peak_efficiency,
                "peak_load_current_a": peak_load_current
            }
        )

    # ============================================================
    # 调整率指标
    # ============================================================
    
    def extract_load_regulation(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        load_current_signal: str = "I(Rload)",
        no_load_current: float = 0.0,
        full_load_current: Optional[float] = None
    ) -> MetricResult:
        """
        提取负载调整率
        
        负载调整率 = (V_no_load - V_full_load) / V_no_load × 100%
        
        衡量输出电压随负载电流变化的稳定性。
        
        Args:
            data: 仿真数据（DC 扫描或瞬态分析）
            output_signal: 输出电压信号名称
            load_current_signal: 负载电流信号名称
            no_load_current: 无负载电流值（A）
            full_load_current: 满负载电流值（A），None 时使用最大电流
            
        Returns:
            MetricResult: 负载调整率指标结果（%）
        """
        v_out = data.signals.get(output_signal)
        i_load = data.signals.get(load_current_signal)
        
        if v_out is None:
            return create_error_metric(
                name="load_regulation",
                display_name="负载调整率",
                error_message=f"未找到输出电压信号 {output_signal}",
                category=self._category,
                unit="%"
            )
        
        if i_load is None:
            return create_error_metric(
                name="load_regulation",
                display_name="负载调整率",
                error_message=f"未找到负载电流信号 {load_current_signal}",
                category=self._category,
                unit="%"
            )
        
        v_out = np.real(v_out)
        i_load = np.abs(np.real(i_load))
        
        # 确定满负载电流
        if full_load_current is None:
            full_load_current = float(np.max(i_load))
        
        # 找无负载和满负载点
        no_load_idx = self._find_nearest_index(i_load, no_load_current)
        full_load_idx = self._find_nearest_index(i_load, full_load_current)
        
        v_no_load = float(v_out[no_load_idx])
        v_full_load = float(v_out[full_load_idx])
        
        if abs(v_no_load) < 1e-9:
            return create_error_metric(
                name="load_regulation",
                display_name="负载调整率",
                error_message="无负载电压过小",
                category=self._category,
                unit="%"
            )
        
        load_reg = ((v_no_load - v_full_load) / v_no_load) * 100.0
        
        condition = f"Iload: {self._format_current(no_load_current)} → {self._format_current(full_load_current)}"
        
        return create_metric_result(
            name="load_regulation",
            display_name="负载调整率",
            value=load_reg,
            unit="%",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "v_no_load": v_no_load,
                "v_full_load": v_full_load,
                "no_load_current_a": no_load_current,
                "full_load_current_a": full_load_current
            }
        )
    
    def extract_line_regulation(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        input_signal: str = "V(vin)",
        vin_nominal: Optional[float] = None
    ) -> MetricResult:
        """
        提取线性调整率
        
        线性调整率 = ΔVout / ΔVin × 100%
        
        衡量输出电压随输入电压变化的稳定性。
        
        Args:
            data: 仿真数据（DC 扫描）
            output_signal: 输出电压信号名称
            input_signal: 输入电压信号名称
            vin_nominal: 标称输入电压（用于计算百分比变化）
            
        Returns:
            MetricResult: 线性调整率指标结果（%/V 或 mV/V）
        """
        v_out = data.signals.get(output_signal)
        v_in = data.signals.get(input_signal)
        
        if v_out is None:
            return create_error_metric(
                name="line_regulation",
                display_name="线性调整率",
                error_message=f"未找到输出电压信号 {output_signal}",
                category=self._category,
                unit="mV/V"
            )
        
        if v_in is None:
            return create_error_metric(
                name="line_regulation",
                display_name="线性调整率",
                error_message=f"未找到输入电压信号 {input_signal}",
                category=self._category,
                unit="mV/V"
            )
        
        v_out = np.real(v_out)
        v_in = np.real(v_in)
        
        if len(v_in) < 2:
            return create_error_metric(
                name="line_regulation",
                display_name="线性调整率",
                error_message="输入电压数据点不足",
                category=self._category,
                unit="mV/V"
            )
        
        # 计算 ΔVout / ΔVin
        delta_vout = float(v_out[-1] - v_out[0])
        delta_vin = float(v_in[-1] - v_in[0])
        
        if abs(delta_vin) < 1e-9:
            return create_error_metric(
                name="line_regulation",
                display_name="线性调整率",
                error_message="输入电压变化过小",
                category=self._category,
                unit="mV/V"
            )
        
        # 线性调整率 (mV/V)
        line_reg = (delta_vout / delta_vin) * 1000.0  # 转换为 mV/V
        
        condition = f"Vin: {v_in[0]:.2f}V → {v_in[-1]:.2f}V"
        
        return create_metric_result(
            name="line_regulation",
            display_name="线性调整率",
            value=line_reg,
            unit="mV/V",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "delta_vout_v": delta_vout,
                "delta_vin_v": delta_vin,
                "vin_range": (float(v_in[0]), float(v_in[-1])),
                "vout_range": (float(v_out[0]), float(v_out[-1]))
            }
        )
    
    def extract_dropout_voltage(
        self,
        data: SimulationData,
        output_signal: str = "V(out)",
        input_signal: str = "V(vin)",
        target_vout: Optional[float] = None,
        dropout_threshold: float = 0.99
    ) -> MetricResult:
        """
        提取压差（LDO）
        
        压差是 LDO 正常调节所需的最小输入输出电压差。
        定义为输出电压下降到标称值 99% 时的 Vin - Vout。
        
        Args:
            data: 仿真数据（DC 扫描，Vin 从高到低）
            output_signal: 输出电压信号名称
            input_signal: 输入电压信号名称
            target_vout: 目标输出电压（None 时使用最大输出电压）
            dropout_threshold: 压差判定阈值（默认 0.99，即 99%）
            
        Returns:
            MetricResult: 压差指标结果（V）
        """
        v_out = data.signals.get(output_signal)
        v_in = data.signals.get(input_signal)
        
        if v_out is None or v_in is None:
            return create_error_metric(
                name="dropout_voltage",
                display_name="压差",
                error_message="未找到输入或输出电压信号",
                category=self._category,
                unit="V"
            )
        
        v_out = np.real(v_out)
        v_in = np.real(v_in)
        
        # 确定目标输出电压
        if target_vout is None:
            target_vout = float(np.max(v_out))
        
        # 找到输出电压下降到阈值的点
        threshold_vout = target_vout * dropout_threshold
        
        # 从高 Vin 向低 Vin 搜索
        dropout_idx = None
        for i in range(len(v_out) - 1, -1, -1):
            if v_out[i] < threshold_vout:
                dropout_idx = i
                break
        
        if dropout_idx is None:
            return create_error_metric(
                name="dropout_voltage",
                display_name="压差",
                error_message="未找到压差点（输出电压始终高于阈值）",
                category=self._category,
                unit="V"
            )
        
        # 计算压差
        dropout_vin = float(v_in[dropout_idx])
        dropout_vout = float(v_out[dropout_idx])
        dropout_voltage = dropout_vin - dropout_vout
        
        condition = f"Vout={target_vout:.2f}V, 阈值={dropout_threshold*100:.0f}%"
        
        return create_metric_result(
            name="dropout_voltage",
            display_name="压差",
            value=dropout_voltage,
            unit="V",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "target_vout": target_vout,
                "dropout_vin": dropout_vin,
                "dropout_vout": dropout_vout,
                "threshold": dropout_threshold
            }
        )

    # ============================================================
    # 元件功耗分析
    # ============================================================
    
    def extract_component_power(
        self,
        data: SimulationData,
        component_name: str,
        voltage_signal: Optional[str] = None,
        current_signal: Optional[str] = None
    ) -> MetricResult:
        """
        提取单个元件功耗
        
        Args:
            data: 仿真数据
            component_name: 元件名称（如 "R1", "M1"）
            voltage_signal: 元件电压信号名称（None 时自动推断）
            current_signal: 元件电流信号名称（None 时自动推断）
            
        Returns:
            MetricResult: 元件功耗指标结果（W）
        """
        # 自动推断信号名称
        if voltage_signal is None:
            voltage_signal = f"V({component_name})"
        if current_signal is None:
            current_signal = f"I({component_name})"
        
        voltage = data.signals.get(voltage_signal)
        current = data.signals.get(current_signal)
        
        if voltage is None:
            # 尝试节点电压差
            # 对于两端元件，可能需要 V(node1) - V(node2)
            return create_error_metric(
                name=f"power_{component_name}",
                display_name=f"{component_name} 功耗",
                error_message=f"未找到元件电压信号 {voltage_signal}",
                category=self._category,
                unit="W"
            )
        
        if current is None:
            return create_error_metric(
                name=f"power_{component_name}",
                display_name=f"{component_name} 功耗",
                error_message=f"未找到元件电流信号 {current_signal}",
                category=self._category,
                unit="W"
            )
        
        voltage = np.abs(np.real(voltage))
        current = np.abs(np.real(current))
        power = voltage * current
        
        # 计算平均功耗
        if data.time is not None and len(data.time) > 0:
            avg_power = float(np.mean(power))
            peak_power = float(np.max(power))
            condition = "时间平均"
        else:
            avg_power = float(power[0]) if len(power) > 0 else 0.0
            peak_power = avg_power
            condition = "DC 工作点"
        
        return create_metric_result(
            name=f"power_{component_name}",
            display_name=f"{component_name} 功耗",
            value=avg_power,
            unit="W",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "component": component_name,
                "peak_power_w": peak_power,
                "voltage_signal": voltage_signal,
                "current_signal": current_signal
            }
        )
    
    def extract_power_distribution(
        self,
        data: SimulationData,
        component_list: Optional[List[str]] = None,
        total_power_signal: Optional[str] = None
    ) -> Tuple[MetricResult, List[MetricResult]]:
        """
        提取各元件功耗分布
        
        Args:
            data: 仿真数据
            component_list: 要分析的元件列表（None 时自动检测）
            total_power_signal: 总功耗信号名称（用于计算百分比）
            
        Returns:
            Tuple[MetricResult, List[MetricResult]]: (总功耗, 各元件功耗列表)
        """
        # 自动检测元件
        if component_list is None:
            component_list = self._detect_power_components(data)
        
        if not component_list:
            error = create_error_metric(
                name="power_distribution",
                display_name="功耗分布",
                error_message="未找到可分析的元件",
                category=self._category,
                unit="W"
            )
            return error, []
        
        # 提取各元件功耗
        component_results = []
        total_power = 0.0
        
        for comp in component_list:
            result = self.extract_component_power(data, comp)
            if result.is_valid and result.value is not None:
                total_power += result.value
                component_results.append(result)
        
        if total_power < 1e-15:
            error = create_error_metric(
                name="power_distribution",
                display_name="功耗分布",
                error_message="总功耗过小",
                category=self._category,
                unit="W"
            )
            return error, component_results
        
        # 计算百分比
        for result in component_results:
            if result.value is not None:
                percentage = (result.value / total_power) * 100.0
                result.metadata["percentage"] = percentage
        
        total_result = create_metric_result(
            name="total_power",
            display_name="总功耗",
            value=total_power,
            unit="W",
            category=self._category,
            measurement_condition=f"{len(component_results)} 个元件",
            metadata={"component_count": len(component_results)}
        )
        
        return total_result, component_results
    
    def extract_power_loss_breakdown(
        self,
        data: SimulationData,
        input_power: float,
        output_power: float,
        loss_components: Optional[Dict[str, str]] = None
    ) -> MetricResult:
        """
        功耗损耗分解
        
        将总损耗分解为各部分（如导通损耗、开关损耗、静态损耗等）。
        
        Args:
            data: 仿真数据
            input_power: 输入功率（W）
            output_power: 输出功率（W）
            loss_components: 损耗分量信号映射 {名称: 信号名}
            
        Returns:
            MetricResult: 功耗损耗分解结果
        """
        total_loss = input_power - output_power
        
        if total_loss < 0:
            return create_error_metric(
                name="power_loss_breakdown",
                display_name="功耗损耗分解",
                error_message="输出功率大于输入功率（数据异常）",
                category=self._category,
                unit="W"
            )
        
        breakdown = {
            "total_loss_w": total_loss,
            "input_power_w": input_power,
            "output_power_w": output_power,
            "efficiency_percent": (output_power / input_power) * 100.0 if input_power > 0 else 0.0
        }
        
        # 如果提供了损耗分量信号，尝试提取
        if loss_components:
            identified_loss = 0.0
            for name, signal_name in loss_components.items():
                signal = data.signals.get(signal_name)
                if signal is not None:
                    loss_value = float(np.mean(np.abs(np.real(signal))))
                    breakdown[f"{name}_w"] = loss_value
                    identified_loss += loss_value
            
            # 未识别的损耗
            breakdown["unidentified_loss_w"] = max(0, total_loss - identified_loss)
        
        return create_metric_result(
            name="power_loss_breakdown",
            display_name="功耗损耗分解",
            value=total_loss,
            unit="W",
            category=self._category,
            measurement_condition=f"效率={breakdown['efficiency_percent']:.1f}%",
            metadata=breakdown
        )

    # ============================================================
    # 热分析
    # ============================================================
    
    def estimate_thermal_rise(
        self,
        power_dissipation: float,
        thermal_resistance: float,
        ambient_temperature: float = 25.0
    ) -> MetricResult:
        """
        估算元件温升
        
        温升 = 功耗 × 热阻
        结温 = 环境温度 + 温升
        
        Args:
            power_dissipation: 功耗（W）
            thermal_resistance: 热阻（°C/W）
            ambient_temperature: 环境温度（°C）
            
        Returns:
            MetricResult: 温升估算结果（°C）
        """
        if power_dissipation < 0:
            return create_error_metric(
                name="thermal_rise",
                display_name="温升",
                error_message="功耗不能为负值",
                category=self._category,
                unit="°C"
            )
        
        if thermal_resistance < 0:
            return create_error_metric(
                name="thermal_rise",
                display_name="温升",
                error_message="热阻不能为负值",
                category=self._category,
                unit="°C"
            )
        
        temperature_rise = power_dissipation * thermal_resistance
        junction_temperature = ambient_temperature + temperature_rise
        
        condition = f"Pd={power_dissipation:.3f}W, Rth={thermal_resistance}°C/W"
        
        return create_metric_result(
            name="thermal_rise",
            display_name="温升",
            value=temperature_rise,
            unit="°C",
            category=self._category,
            measurement_condition=condition,
            metadata={
                "power_dissipation_w": power_dissipation,
                "thermal_resistance_c_per_w": thermal_resistance,
                "ambient_temperature_c": ambient_temperature,
                "junction_temperature_c": junction_temperature
            }
        )

    # ============================================================
    # 辅助方法
    # ============================================================
    
    def _find_nearest_index(self, array: np.ndarray, value: float) -> int:
        """找到数组中最接近指定值的索引"""
        return int(np.argmin(np.abs(array - value)))
    
    def _format_current(self, current: float) -> str:
        """格式化电流显示"""
        abs_current = abs(current)
        if abs_current >= 1:
            return f"{current:.2f}A"
        elif abs_current >= 1e-3:
            return f"{current * 1e3:.2f}mA"
        elif abs_current >= 1e-6:
            return f"{current * 1e6:.2f}μA"
        elif abs_current >= 1e-9:
            return f"{current * 1e9:.2f}nA"
        else:
            return f"{current:.2e}A"
    
    def _format_power(self, power: float) -> str:
        """格式化功率显示"""
        abs_power = abs(power)
        if abs_power >= 1:
            return f"{power:.2f}W"
        elif abs_power >= 1e-3:
            return f"{power * 1e3:.2f}mW"
        elif abs_power >= 1e-6:
            return f"{power * 1e6:.2f}μW"
        elif abs_power >= 1e-9:
            return f"{power * 1e9:.2f}nW"
        else:
            return f"{power:.2e}W"
    
    def _detect_power_components(self, data: SimulationData) -> List[str]:
        """
        自动检测可分析功耗的元件
        
        通过信号名称模式匹配检测电阻、晶体管等元件。
        
        Args:
            data: 仿真数据
            
        Returns:
            List[str]: 元件名称列表
        """
        components = []
        signal_names = data.get_signal_names()
        
        # 查找电流信号，推断元件名称
        for name in signal_names:
            if name.startswith("I(") and name.endswith(")"):
                comp_name = name[2:-1]
                # 检查是否有对应的电压信号
                if f"V({comp_name})" in signal_names:
                    components.append(comp_name)
        
        return components


# 模块级单例，便于直接导入使用
power_metrics = PowerMetrics()


__all__ = [
    "PowerMetrics",
    "power_metrics",
]
