# MetricsExtractor - Metrics Extraction Facade
"""
指标提取门面类

职责：
- 作为门面类协调各子模块，提供统一的指标提取入口
- 根据拓扑类型自动提取相关指标
- 提供按名称提取单个指标的能力
- 处理指标计算容错

设计原则：
- 门面模式：简化客户端调用，隐藏子模块复杂性
- 容错设计：数据不足时返回错误指标而非抛异常
- 可扩展性：支持通过拓扑类型自动选择指标集

使用示例：
    from domain.simulation.metrics import metrics_extractor
    
    # 根据拓扑自动提取指标
    metrics = metrics_extractor.extract_metrics(
        sim_data, 
        topology="amplifier",
        goals={"gain": 20, "bandwidth": 1e6}
    )
    
    # 提取所有可计算的指标
    all_metrics = metrics_extractor.extract_all_metrics(sim_data)
    
    # 按名称提取单个指标
    gain = metrics_extractor.get_metric_by_name(sim_data, "gain")
"""

from typing import Any, Callable, Dict, List, Optional, Set

from domain.simulation.metrics.metric_result import (
    MetricCategory,
    MetricResult,
    create_error_metric,
)
from domain.simulation.metrics.amplifier_metrics import amplifier_metrics
from domain.simulation.metrics.noise_metrics import noise_metrics
from domain.simulation.metrics.distortion_metrics import distortion_metrics
from domain.simulation.metrics.power_metrics import power_metrics
from domain.simulation.metrics.transient_metrics import transient_metrics
from domain.simulation.models.simulation_result import SimulationData


class MetricsExtractor:
    """
    指标提取门面类
    
    协调各子模块提取器，提供统一的指标提取入口。
    支持根据电路拓扑类型自动选择合适的指标集。
    """
    
    # 拓扑类型到指标集的映射
    TOPOLOGY_METRICS: Dict[str, List[str]] = {
        "amplifier": [
            "gain", "bandwidth", "gbw", "phase_margin", "gain_margin",
            "input_impedance", "output_impedance", "cmrr", "psrr",
            "slew_rate", "settling_time", "overshoot", "offset_voltage",
            "quiescent_current", "power_consumption"
        ],
        "opamp": [
            "gain", "bandwidth", "gbw", "phase_margin", "gain_margin",
            "input_impedance", "output_impedance", "cmrr", "psrr",
            "slew_rate", "settling_time", "overshoot", "offset_voltage",
            "input_noise", "quiescent_current", "power_consumption"
        ],
        "ldo": [
            "load_regulation", "line_regulation", "dropout_voltage",
            "quiescent_current", "power_consumption", "efficiency",
            "psrr", "output_noise"
        ],
        "dcdc": [
            "efficiency", "load_regulation", "line_regulation",
            "power_consumption", "rise_time", "fall_time",
            "duty_cycle", "frequency"
        ],
        "oscillator": [
            "frequency", "period", "duty_cycle", "rise_time", "fall_time",
            "thd", "phase_noise"
        ],
        "filter": [
            "gain", "bandwidth", "phase_margin",
            "thd", "snr"
        ],
        "adc": [
            "sndr", "enob", "thd", "sfdr", "snr"
        ],
        "dac": [
            "sndr", "enob", "thd", "sfdr", "snr"
        ],
        "digital": [
            "rise_time", "fall_time", "propagation_delay",
            "duty_cycle", "frequency", "power_consumption"
        ],
    }
    
    # 指标名称到提取方法的映射
    METRIC_EXTRACTORS: Dict[str, Callable] = {}
    
    def __init__(self):
        """初始化指标提取门面"""
        self._init_extractors()
    
    def _init_extractors(self) -> None:
        """初始化指标提取器映射"""
        # 放大器指标
        self.METRIC_EXTRACTORS = {
            # AC 分析指标
            "gain": lambda d, **kw: amplifier_metrics.extract_gain(d, **kw),
            "bandwidth": lambda d, **kw: amplifier_metrics.extract_bandwidth(d, **kw),
            "gbw": lambda d, **kw: amplifier_metrics.extract_gbw(d, **kw),
            "phase_margin": lambda d, **kw: amplifier_metrics.extract_phase_margin(d, **kw),
            "gain_margin": lambda d, **kw: amplifier_metrics.extract_gain_margin(d, **kw),
            "input_impedance": lambda d, **kw: amplifier_metrics.extract_input_impedance(d, **kw),
            "output_impedance": lambda d, **kw: amplifier_metrics.extract_output_impedance(d, **kw),
            "cmrr": lambda d, **kw: amplifier_metrics.extract_cmrr(d, **kw),
            "psrr": lambda d, **kw: amplifier_metrics.extract_psrr(d, **kw),
            "offset_voltage": lambda d, **kw: amplifier_metrics.extract_offset_voltage(d, **kw),
            
            # 瞬态指标（放大器）
            "slew_rate": lambda d, **kw: self._extract_slew_rate(d, **kw),
            "settling_time": lambda d, **kw: amplifier_metrics.extract_settling_time(d, **kw),
            "overshoot": lambda d, **kw: amplifier_metrics.extract_overshoot(d, **kw),
            
            # 噪声指标
            "input_noise": lambda d, **kw: noise_metrics.extract_input_noise(d, **kw),
            "output_noise": lambda d, **kw: noise_metrics.extract_output_noise(d, **kw),
            "integrated_noise": lambda d, **kw: noise_metrics.extract_integrated_noise(d, **kw),
            "noise_figure": lambda d, **kw: noise_metrics.extract_noise_figure(d, **kw),
            "snr": lambda d, **kw: self._extract_snr(d, **kw),
            "corner_frequency": lambda d, **kw: noise_metrics.extract_corner_frequency(d, **kw),
            "enbw": lambda d, **kw: noise_metrics.extract_equivalent_noise_bandwidth(d, **kw),
            
            # 失真指标
            "thd": lambda d, **kw: distortion_metrics.extract_thd(d, **kw),
            "thd_n": lambda d, **kw: distortion_metrics.extract_thd_n(d, **kw),
            "imd": lambda d, **kw: distortion_metrics.extract_imd(d, **kw),
            "sfdr": lambda d, **kw: distortion_metrics.extract_sfdr(d, **kw),
            "sndr": lambda d, **kw: distortion_metrics.extract_sndr(d, **kw),
            "enob": lambda d, **kw: distortion_metrics.extract_enob(d, **kw),
            "harmonics": lambda d, **kw: self._extract_harmonics(d, **kw),
            
            # 电源指标
            "quiescent_current": lambda d, **kw: power_metrics.extract_quiescent_current(d, **kw),
            "power_consumption": lambda d, **kw: power_metrics.extract_power_consumption(d, **kw),
            "efficiency": lambda d, **kw: power_metrics.extract_efficiency(d, **kw),
            "load_regulation": lambda d, **kw: power_metrics.extract_load_regulation(d, **kw),
            "line_regulation": lambda d, **kw: power_metrics.extract_line_regulation(d, **kw),
            "dropout_voltage": lambda d, **kw: power_metrics.extract_dropout_voltage(d, **kw),
            
            # 瞬态指标
            "rise_time": lambda d, **kw: transient_metrics.extract_rise_time(d, **kw),
            "fall_time": lambda d, **kw: transient_metrics.extract_fall_time(d, **kw),
            "propagation_delay": lambda d, **kw: self._extract_propagation_delay(d, **kw),
            "duty_cycle": lambda d, **kw: transient_metrics.extract_duty_cycle(d, **kw),
            "frequency": lambda d, **kw: transient_metrics.extract_frequency(d, **kw),
            "period": lambda d, **kw: transient_metrics.extract_period(d, **kw),
        }
    
    def extract_metrics(
        self,
        sim_data: SimulationData,
        topology: Optional[str] = None,
        goals: Optional[Dict[str, Any]] = None,
        output_signal: str = "V(out)",
        input_signal: Optional[str] = None
    ) -> Dict[str, MetricResult]:
        """
        根据拓扑类型自动提取相关指标
        
        Args:
            sim_data: 仿真数据
            topology: 电路拓扑类型（如 "amplifier", "ldo", "oscillator"）
                     None 时自动检测或提取所有可计算指标
            goals: 设计目标字典，用于设置指标的目标值
            output_signal: 输出信号名称
            input_signal: 输入信号名称
            
        Returns:
            Dict[str, MetricResult]: 指标名称到结果的映射
        """
        results: Dict[str, MetricResult] = {}
        
        # 确定要提取的指标集
        if topology is not None:
            topology_lower = topology.lower()
            metric_names = self.TOPOLOGY_METRICS.get(topology_lower, [])
            if not metric_names:
                # 未知拓扑，提取所有可计算指标
                metric_names = self._get_available_metrics(sim_data)
        else:
            # 无拓扑信息，提取所有可计算指标
            metric_names = self._get_available_metrics(sim_data)
        
        # 提取每个指标
        for metric_name in metric_names:
            result = self.get_metric_by_name(
                sim_data, 
                metric_name,
                output_signal=output_signal,
                input_signal=input_signal
            )
            
            # 如果有目标值，设置目标
            if goals and metric_name in goals:
                goal_value = goals[metric_name]
                if isinstance(goal_value, dict):
                    # 复杂目标格式 {"value": 20, "type": "min"}
                    result = result.with_target(
                        target=goal_value.get("value", goal_value.get("target")),
                        target_type=goal_value.get("type", "min"),
                        target_max=goal_value.get("max")
                    )
                else:
                    # 简单目标格式
                    result = result.with_target(target=float(goal_value))
            
            results[metric_name] = result
        
        return results
    
    def extract_all_metrics(
        self,
        sim_data: SimulationData,
        output_signal: str = "V(out)",
        input_signal: Optional[str] = None
    ) -> Dict[str, MetricResult]:
        """
        提取所有可计算的指标
        
        根据仿真数据类型（AC/瞬态/DC）自动选择可提取的指标。
        
        Args:
            sim_data: 仿真数据
            output_signal: 输出信号名称
            input_signal: 输入信号名称
            
        Returns:
            Dict[str, MetricResult]: 指标名称到结果的映射
        """
        results: Dict[str, MetricResult] = {}
        available_metrics = self._get_available_metrics(sim_data)
        
        for metric_name in available_metrics:
            result = self.get_metric_by_name(
                sim_data,
                metric_name,
                output_signal=output_signal,
                input_signal=input_signal
            )
            results[metric_name] = result
        
        return results
    
    def get_metric_by_name(
        self,
        sim_data: SimulationData,
        metric_name: str,
        **kwargs
    ) -> MetricResult:
        """
        按名称提取单个指标
        
        Args:
            sim_data: 仿真数据
            metric_name: 指标名称（如 "gain", "bandwidth", "thd"）
            **kwargs: 传递给具体提取方法的参数
            
        Returns:
            MetricResult: 指标结果
        """
        metric_name_lower = metric_name.lower()
        
        if metric_name_lower not in self.METRIC_EXTRACTORS:
            return create_error_metric(
                name=metric_name,
                display_name=metric_name,
                error_message=f"未知指标: {metric_name}",
                category=MetricCategory.GENERAL
            )
        
        extractor = self.METRIC_EXTRACTORS[metric_name_lower]
        
        try:
            result = extractor(sim_data, **kwargs)
            return result
        except Exception as e:
            return create_error_metric(
                name=metric_name,
                display_name=metric_name,
                error_message=f"提取失败: {str(e)}",
                category=MetricCategory.GENERAL
            )
    
    def get_metrics_by_category(
        self,
        sim_data: SimulationData,
        category: MetricCategory,
        output_signal: str = "V(out)",
        input_signal: Optional[str] = None
    ) -> Dict[str, MetricResult]:
        """
        按类别提取指标
        
        Args:
            sim_data: 仿真数据
            category: 指标类别
            output_signal: 输出信号名称
            input_signal: 输入信号名称
            
        Returns:
            Dict[str, MetricResult]: 指标名称到结果的映射
        """
        category_metrics = self._get_metrics_for_category(category)
        results: Dict[str, MetricResult] = {}
        
        for metric_name in category_metrics:
            result = self.get_metric_by_name(
                sim_data,
                metric_name,
                output_signal=output_signal,
                input_signal=input_signal
            )
            results[metric_name] = result
        
        return results
    
    def get_supported_metrics(self) -> List[str]:
        """
        获取所有支持的指标名称列表
        
        Returns:
            List[str]: 指标名称列表
        """
        return list(self.METRIC_EXTRACTORS.keys())
    
    def get_supported_topologies(self) -> List[str]:
        """
        获取所有支持的拓扑类型列表
        
        Returns:
            List[str]: 拓扑类型列表
        """
        return list(self.TOPOLOGY_METRICS.keys())
    
    def get_metrics_for_topology(self, topology: str) -> List[str]:
        """
        获取指定拓扑类型的指标列表
        
        Args:
            topology: 拓扑类型
            
        Returns:
            List[str]: 指标名称列表
        """
        return self.TOPOLOGY_METRICS.get(topology.lower(), [])

    
    # ============================================================
    # 私有辅助方法
    # ============================================================
    
    def _get_available_metrics(self, sim_data: SimulationData) -> List[str]:
        """
        根据仿真数据类型确定可提取的指标
        
        Args:
            sim_data: 仿真数据
            
        Returns:
            List[str]: 可提取的指标名称列表
        """
        available: Set[str] = set()
        
        # AC 分析数据可用
        if sim_data.frequency is not None and len(sim_data.frequency) > 0:
            available.update([
                "gain", "bandwidth", "gbw", "phase_margin", "gain_margin",
                "input_impedance", "output_impedance", "cmrr", "psrr",
                "input_noise", "output_noise", "integrated_noise",
                "noise_figure", "corner_frequency", "enbw"
            ])
        
        # 瞬态分析数据可用
        if sim_data.time is not None and len(sim_data.time) > 0:
            available.update([
                "slew_rate", "settling_time", "overshoot",
                "rise_time", "fall_time", "propagation_delay",
                "duty_cycle", "frequency", "period",
                "thd", "thd_n", "imd", "sfdr", "sndr", "enob",
                "quiescent_current", "power_consumption", "efficiency"
            ])
        
        # DC 分析数据可用（通过信号判断）
        if sim_data.signals:
            # 检查是否有电源相关信号
            signal_names = set(sim_data.signals.keys())
            power_signals = {"I(Vdd)", "I(VDD)", "I(Vcc)", "I(VCC)", "I(V1)"}
            if signal_names & power_signals:
                available.update([
                    "quiescent_current", "power_consumption",
                    "load_regulation", "line_regulation", "dropout_voltage"
                ])
            
            # 检查是否有失调相关信号
            if "V(out)" in signal_names or any("out" in s.lower() for s in signal_names):
                available.add("offset_voltage")
        
        return sorted(list(available))
    
    def _get_metrics_for_category(self, category: MetricCategory) -> List[str]:
        """
        获取指定类别的指标列表
        
        Args:
            category: 指标类别
            
        Returns:
            List[str]: 指标名称列表
        """
        category_map = {
            MetricCategory.AMPLIFIER: [
                "gain", "bandwidth", "gbw", "phase_margin", "gain_margin",
                "input_impedance", "output_impedance", "cmrr", "psrr",
                "slew_rate", "settling_time", "overshoot", "offset_voltage"
            ],
            MetricCategory.NOISE: [
                "input_noise", "output_noise", "integrated_noise",
                "noise_figure", "snr", "corner_frequency", "enbw"
            ],
            MetricCategory.DISTORTION: [
                "thd", "thd_n", "imd", "sfdr", "sndr", "enob", "harmonics"
            ],
            MetricCategory.POWER: [
                "quiescent_current", "power_consumption", "efficiency",
                "load_regulation", "line_regulation", "dropout_voltage"
            ],
            MetricCategory.TRANSIENT: [
                "rise_time", "fall_time", "propagation_delay",
                "duty_cycle", "frequency", "period"
            ],
        }
        return category_map.get(category, [])
    
    def _extract_slew_rate(
        self,
        sim_data: SimulationData,
        output_signal: str = "V(out)",
        **kwargs
    ) -> MetricResult:
        """
        提取压摆率（返回上升压摆率）
        
        AmplifierMetrics.extract_slew_rate 返回元组，这里包装为单个结果
        """
        rise_result, fall_result = amplifier_metrics.extract_slew_rate(
            sim_data, output_signal=output_signal, **kwargs
        )
        
        # 优先返回上升压摆率，如果无效则返回下降压摆率
        if rise_result.is_valid:
            return rise_result
        elif fall_result.is_valid:
            return fall_result
        else:
            return rise_result  # 返回错误结果
    
    def _extract_propagation_delay(
        self,
        sim_data: SimulationData,
        input_signal: str = "V(in)",
        output_signal: str = "V(out)",
        **kwargs
    ) -> MetricResult:
        """
        提取传播延迟（返回平均值）
        """
        return transient_metrics.extract_average_propagation_delay(
            sim_data,
            input_signal=input_signal,
            output_signal=output_signal,
            **kwargs
        )
    
    def _extract_snr(
        self,
        sim_data: SimulationData,
        signal_level: float = 1.0,
        **kwargs
    ) -> MetricResult:
        """
        提取信噪比
        
        需要提供信号电平参数
        """
        return noise_metrics.extract_snr(
            sim_data,
            signal_level=signal_level,
            **kwargs
        )
    
    def _extract_harmonics(
        self,
        sim_data: SimulationData,
        output_signal: str = "V(out)",
        **kwargs
    ) -> MetricResult:
        """
        提取谐波分析结果
        
        返回基波结果，谐波详情在 metadata 中
        """
        fundamental, harmonics = distortion_metrics.extract_harmonics(
            sim_data, output_signal=output_signal, **kwargs
        )
        
        if fundamental.is_valid:
            # 将谐波信息添加到 metadata
            harmonic_data = [
                {
                    "order": h.metadata.get("order"),
                    "frequency": h.metadata.get("frequency"),
                    "amplitude_dbc": h.value
                }
                for h in harmonics if h.is_valid
            ]
            fundamental.metadata["harmonics"] = harmonic_data
        
        return fundamental


# 模块级单例，便于直接导入使用
metrics_extractor = MetricsExtractor()


__all__ = [
    "MetricsExtractor",
    "metrics_extractor",
]
