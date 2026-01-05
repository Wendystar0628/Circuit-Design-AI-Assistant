# Worst Case Analysis - Extreme Condition Evaluation
"""
最坏情况分析

职责：
- 分析元件容差组合的最坏情况
- 快速评估设计裕度
- 支持 RSS 和 EVA 两种分析方法

设计原则：
- 作为工具类按需实例化，无需显式初始化
- 比蒙特卡洛更快速地找到极端情况（2N+1 次仿真 vs 100-1000 次）
- 与蒙特卡洛分析共享容差定义模式

使用示例：
    from domain.simulation.analysis.worst_case_analysis import WorstCaseAnalyzer
    
    analyzer = WorstCaseAnalyzer()
    
    # 定义元件容差
    tolerances = [
        analyzer.define_tolerance("R1", "resistance", 0.05),
        analyzer.define_tolerance("C1", "capacitance", 0.10),
    ]
    
    # 执行最坏情况分析
    result = analyzer.run_worst_case(
        circuit_file="amplifier.cir",
        tolerances=tolerances,
        method=WorstCaseMethod.RSS,
        metric="gain",
    )
    
    # 获取设计裕度
    margin = analyzer.calculate_design_margin(result, spec={"gain": {"min": 20.0}})
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from domain.simulation.executor.spice_executor import SpiceExecutor
from domain.simulation.models.simulation_result import SimulationResult


# ============================================================
# 枚举定义
# ============================================================

class WorstCaseMethod(Enum):
    """最坏情况分析方法"""
    RSS = "rss"     # Root Sum Square 方法
    EVA = "eva"     # Extreme Value Analysis 方法


# ============================================================
# 数据类定义
# ============================================================

@dataclass
class ToleranceSpec:
    """
    元件容差规格
    
    Attributes:
        component: 元件名称（如 "R1", "C1"）
        param: 参数名称（如 "resistance", "capacitance"）
        tolerance_percent: 容差百分比（如 5.0 表示 ±5%）
        nominal_value: 标称值（可选，若不指定则从电路中读取）
    """
    component: str
    param: str
    tolerance_percent: float
    nominal_value: Optional[float] = None
    
    @property
    def key(self) -> str:
        """获取参数键名"""
        return f"{self.component}.{self.param}"
    
    @property
    def tolerance_factor(self) -> float:
        """获取容差因子（如 0.05 表示 ±5%）"""
        return self.tolerance_percent / 100.0
    
    def get_min_value(self, nominal: float) -> float:
        """获取最小值"""
        return nominal * (1.0 - self.tolerance_factor)
    
    def get_max_value(self, nominal: float) -> float:
        """获取最大值"""
        return nominal * (1.0 + self.tolerance_factor)
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "component": self.component,
            "param": self.param,
            "tolerance_percent": self.tolerance_percent,
            "nominal_value": self.nominal_value,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToleranceSpec":
        """从字典反序列化"""
        return cls(
            component=data["component"],
            param=data["param"],
            tolerance_percent=data["tolerance_percent"],
            nominal_value=data.get("nominal_value"),
        )


@dataclass
class ParameterSensitivity:
    """
    参数敏感度数据
    
    Attributes:
        param_key: 参数键名
        delta_plus: +tolerance 时的指标变化
        delta_minus: -tolerance 时的指标变化
        sensitivity_coefficient: 敏感度系数
        influence_direction: 影响方向（1 表示正相关，-1 表示负相关）
    """
    param_key: str
    delta_plus: float = 0.0
    delta_minus: float = 0.0
    sensitivity_coefficient: float = 0.0
    influence_direction: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "param_key": self.param_key,
            "delta_plus": self.delta_plus,
            "delta_minus": self.delta_minus,
            "sensitivity_coefficient": self.sensitivity_coefficient,
            "influence_direction": self.influence_direction,
        }


@dataclass
class WorstCaseResult:
    """
    最坏情况分析结果
    
    Attributes:
        circuit_file: 电路文件路径
        analysis_type: 分析类型
        method: 分析方法
        metric: 分析的指标名称
        nominal_value: 标称值
        worst_case_max: 最坏情况最大值
        worst_case_min: 最坏情况最小值
        design_margin_percent: 设计裕度百分比
        critical_params: 关键参数列表（按影响程度排序）
        sensitivities: 各参数敏感度
        worst_combination: 导致最差性能的参数组合
        simulation_count: 仿真次数
        timestamp: 分析时间戳
        duration_seconds: 总耗时
    """
    circuit_file: str
    analysis_type: str
    method: WorstCaseMethod
    metric: str
    nominal_value: float = 0.0
    worst_case_max: float = 0.0
    worst_case_min: float = 0.0
    design_margin_percent: float = 0.0
    critical_params: List[str] = field(default_factory=list)
    sensitivities: List[ParameterSensitivity] = field(default_factory=list)
    worst_combination: Dict[str, float] = field(default_factory=dict)
    simulation_count: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    duration_seconds: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "circuit_file": self.circuit_file,
            "analysis_type": self.analysis_type,
            "method": self.method.value,
            "metric": self.metric,
            "nominal_value": self.nominal_value,
            "worst_case_max": self.worst_case_max,
            "worst_case_min": self.worst_case_min,
            "design_margin_percent": self.design_margin_percent,
            "critical_params": self.critical_params,
            "sensitivities": [s.to_dict() for s in self.sensitivities],
            "worst_combination": self.worst_combination,
            "simulation_count": self.simulation_count,
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
        }


# ============================================================
# WorstCaseAnalyzer - 最坏情况分析器
# ============================================================

class WorstCaseAnalyzer:
    """
    最坏情况分析器
    
    分析元件容差组合的最坏情况，快速评估设计裕度。
    
    特性：
    - 支持 RSS（Root Sum Square）方法
    - 支持 EVA（Extreme Value Analysis）方法
    - 仿真次数少（2N+1 次），比蒙特卡洛快速
    - 识别关键参数和敏感度
    
    RSS vs EVA：
    - RSS：假设参数变化独立且服从正态分布，计算均方根叠加效应
    - EVA：考虑所有参数同时取极端值，结果更保守
    """
    
    def __init__(self, executor: Optional[SpiceExecutor] = None):
        """
        初始化最坏情况分析器
        
        Args:
            executor: SPICE 执行器（可选，默认创建新实例）
        """
        self._logger = logging.getLogger(__name__)
        self._executor = executor or SpiceExecutor()
        self._event_bus = None
    
    def _get_event_bus(self):
        """延迟获取事件总线"""
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SERVICE_EVENT_BUS
                self._event_bus = ServiceLocator.get(SERVICE_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus
    
    # ============================================================
    # 容差定义
    # ============================================================
    
    def define_tolerance(
        self,
        component: str,
        param: str,
        tolerance_percent: float,
        nominal_value: Optional[float] = None,
    ) -> ToleranceSpec:
        """
        定义元件容差
        
        Args:
            component: 元件名称
            param: 参数名称
            tolerance_percent: 容差百分比（如 5.0 表示 ±5%）
            nominal_value: 标称值（可选）
            
        Returns:
            ToleranceSpec: 容差规格
        """
        return ToleranceSpec(
            component=component,
            param=param,
            tolerance_percent=tolerance_percent,
            nominal_value=nominal_value,
        )
    
    # ============================================================
    # 最坏情况分析
    # ============================================================
    
    def run_worst_case(
        self,
        circuit_file: str,
        tolerances: List[ToleranceSpec],
        method: WorstCaseMethod = WorstCaseMethod.RSS,
        metric: str = "gain",
        analysis_config: Optional[Dict[str, Any]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> WorstCaseResult:
        """
        执行最坏情况分析
        
        Args:
            circuit_file: 电路文件路径
            tolerances: 容差规格列表
            method: 分析方法（RSS 或 EVA）
            metric: 要分析的指标名称
            analysis_config: 仿真配置字典
            on_progress: 进度回调
            
        Returns:
            WorstCaseResult: 最坏情况分析结果
        """
        start_time = time.time()
        analysis_type = self._get_analysis_type(analysis_config)
        
        n_params = len(tolerances)
        total_sims = 2 * n_params + 1  # 标称 + 每个参数的 +/- 容差
        
        self._logger.info(
            f"开始最坏情况分析: {circuit_file}, "
            f"方法={method.value}, 参数数={n_params}, 仿真次数={total_sims}"
        )
        
        result = WorstCaseResult(
            circuit_file=circuit_file,
            analysis_type=analysis_type,
            method=method,
            metric=metric,
        )
        
        # 1. 执行标称仿真
        nominal_result = self._run_nominal(circuit_file, analysis_config)
        if not nominal_result.success or metric not in (nominal_result.metrics or {}):
            self._logger.error("标称仿真失败或指标不存在")
            result.duration_seconds = time.time() - start_time
            return result
        
        result.nominal_value = nominal_result.metrics[metric]
        result.simulation_count = 1
        
        if on_progress:
            on_progress(1, total_sims)
        
        # 2. 对每个参数执行 +/- 容差仿真
        sensitivities = []
        sim_idx = 1
        
        for tol in tolerances:
            nominal = tol.nominal_value if tol.nominal_value else 1.0
            
            # +tolerance 仿真
            plus_value = tol.get_max_value(nominal)
            plus_result = self._run_with_param(
                circuit_file, analysis_config, tol.key, plus_value
            )
            sim_idx += 1
            
            # -tolerance 仿真
            minus_value = tol.get_min_value(nominal)
            minus_result = self._run_with_param(
                circuit_file, analysis_config, tol.key, minus_value
            )
            sim_idx += 1
            
            if on_progress:
                on_progress(sim_idx, total_sims)
            
            # 计算敏感度
            delta_plus = 0.0
            delta_minus = 0.0
            
            if plus_result.success and metric in (plus_result.metrics or {}):
                delta_plus = plus_result.metrics[metric] - result.nominal_value
            
            if minus_result.success and metric in (minus_result.metrics or {}):
                delta_minus = minus_result.metrics[metric] - result.nominal_value
            
            # 敏感度系数 = 指标变化 / 参数变化
            param_change = tol.tolerance_factor * nominal
            sens_coef = 0.0
            if param_change != 0:
                sens_coef = max(abs(delta_plus), abs(delta_minus)) / param_change
            
            # 影响方向
            direction = 0
            if delta_plus > 0 and delta_minus < 0:
                direction = 1  # 正相关
            elif delta_plus < 0 and delta_minus > 0:
                direction = -1  # 负相关
            
            sensitivities.append(ParameterSensitivity(
                param_key=tol.key,
                delta_plus=delta_plus,
                delta_minus=delta_minus,
                sensitivity_coefficient=sens_coef,
                influence_direction=direction,
            ))
        
        result.sensitivities = sensitivities
        result.simulation_count = sim_idx
        
        # 3. 根据方法计算最坏情况
        if method == WorstCaseMethod.RSS:
            wc_max, wc_min = self._calculate_rss(result.nominal_value, sensitivities)
        else:  # EVA
            wc_max, wc_min, worst_combo = self._calculate_eva(
                circuit_file, analysis_config, tolerances, sensitivities, metric
            )
            result.worst_combination = worst_combo
            result.simulation_count += 1  # EVA 需要额外一次仿真
        
        result.worst_case_max = wc_max
        result.worst_case_min = wc_min
        
        # 4. 排序关键参数
        sorted_sens = sorted(sensitivities, key=lambda s: abs(s.sensitivity_coefficient), reverse=True)
        result.critical_params = [s.param_key for s in sorted_sens]
        
        result.duration_seconds = time.time() - start_time
        
        # 发布完成事件
        self._publish_complete_event(result)
        
        self._logger.info(
            f"最坏情况分析完成: 标称={result.nominal_value:.4g}, "
            f"最坏=[{result.worst_case_min:.4g}, {result.worst_case_max:.4g}], "
            f"耗时 {result.duration_seconds:.2f}s"
        )
        
        return result
    
    def get_worst_combination(
        self,
        result: WorstCaseResult,
        metric: str,
        minimize: bool = True,
    ) -> Dict[str, float]:
        """
        获取导致最差性能的参数组合
        
        Args:
            result: 最坏情况分析结果
            metric: 指标名称
            minimize: True 表示最小值为最差，False 表示最大值为最差
            
        Returns:
            Dict[str, float]: 参数组合
        """
        if result.worst_combination:
            return result.worst_combination
        
        # 根据敏感度推断
        combination = {}
        for sens in result.sensitivities:
            # 如果要最小化，选择使指标减小的方向
            if minimize:
                if sens.delta_plus < sens.delta_minus:
                    combination[sens.param_key] = "max"
                else:
                    combination[sens.param_key] = "min"
            else:
                if sens.delta_plus > sens.delta_minus:
                    combination[sens.param_key] = "max"
                else:
                    combination[sens.param_key] = "min"
        
        return combination
    
    def calculate_design_margin(
        self,
        result: WorstCaseResult,
        spec: Dict[str, Dict[str, float]],
    ) -> float:
        """
        计算设计裕度
        
        Args:
            result: 最坏情况分析结果
            spec: 规格字典，格式 {"metric": {"min": x, "max": y}}
            
        Returns:
            float: 设计裕度百分比（正值表示满足规格，负值表示不满足）
        """
        if result.metric not in spec:
            return 0.0
        
        metric_spec = spec[result.metric]
        min_spec = metric_spec.get("min")
        max_spec = metric_spec.get("max")
        
        margin = float('inf')
        
        if min_spec is not None:
            # 最坏情况最小值与规格最小值的裕度
            if result.nominal_value != 0:
                margin_min = (result.worst_case_min - min_spec) / abs(result.nominal_value) * 100
                margin = min(margin, margin_min)
        
        if max_spec is not None:
            # 规格最大值与最坏情况最大值的裕度
            if result.nominal_value != 0:
                margin_max = (max_spec - result.worst_case_max) / abs(result.nominal_value) * 100
                margin = min(margin, margin_max)
        
        result.design_margin_percent = margin if margin != float('inf') else 0.0
        return result.design_margin_percent
    
    def generate_worst_case_report(self, result: WorstCaseResult) -> str:
        """
        生成最坏情况报告（Markdown 格式）
        
        Args:
            result: 最坏情况分析结果
            
        Returns:
            str: Markdown 格式报告
        """
        lines = [
            "# 最坏情况分析报告",
            "",
            f"**电路文件**: {result.circuit_file}",
            f"**分析类型**: {result.analysis_type}",
            f"**分析方法**: {result.method.value.upper()}",
            f"**分析指标**: {result.metric}",
            f"**分析时间**: {result.timestamp}",
            f"**总耗时**: {result.duration_seconds:.2f} 秒",
            f"**仿真次数**: {result.simulation_count}",
            "",
            "## 分析结果",
            "",
            f"- **标称值**: {result.nominal_value:.6g}",
            f"- **最坏情况最大值**: {result.worst_case_max:.6g}",
            f"- **最坏情况最小值**: {result.worst_case_min:.6g}",
            f"- **设计裕度**: {result.design_margin_percent:.2f}%",
            "",
        ]
        
        if result.critical_params:
            lines.extend([
                "## 关键参数（按影响程度排序）",
                "",
            ])
            for idx, param in enumerate(result.critical_params, 1):
                sens = next((s for s in result.sensitivities if s.param_key == param), None)
                if sens:
                    lines.append(
                        f"{idx}. **{param}**: 敏感度系数 = {sens.sensitivity_coefficient:.4g}"
                    )
            lines.append("")
        
        if result.sensitivities:
            lines.extend([
                "## 参数敏感度详情",
                "",
                "| 参数 | Δ(+tol) | Δ(-tol) | 敏感度系数 | 影响方向 |",
                "|------|---------|---------|------------|----------|",
            ])
            for sens in result.sensitivities:
                direction = "正相关" if sens.influence_direction > 0 else (
                    "负相关" if sens.influence_direction < 0 else "非单调"
                )
                lines.append(
                    f"| {sens.param_key} | {sens.delta_plus:.4g} | "
                    f"{sens.delta_minus:.4g} | {sens.sensitivity_coefficient:.4g} | {direction} |"
                )
            lines.append("")
        
        if result.worst_combination:
            lines.extend([
                "## 最坏参数组合",
                "",
            ])
            for param, value in result.worst_combination.items():
                lines.append(f"- **{param}**: {value}")
            lines.append("")
        
        # 方法说明
        lines.extend([
            "## 方法说明",
            "",
        ])
        
        if result.method == WorstCaseMethod.RSS:
            lines.extend([
                "**RSS（Root Sum Square）方法**：",
                "",
                "假设参数变化独立且服从正态分布，计算均方根叠加效应。",
                "",
                "计算公式：",
                "- 总变化量 = √(Σ Δᵢ²)",
                "- 最坏情况 = 标称值 ± 总变化量",
                "",
                "适用于大多数情况，结果较为合理。",
            ])
        else:
            lines.extend([
                "**EVA（Extreme Value Analysis）方法**：",
                "",
                "考虑所有参数同时取极端值的情况，结果更保守。",
                "",
                "计算方法：",
                "1. 确定每个参数对指标的影响方向",
                "2. 将所有参数设为使指标变差的极端值",
                "3. 执行一次仿真得到最坏情况",
                "",
                "适用于高可靠性要求的场景。",
            ])
        
        lines.append("")
        
        return "\n".join(lines)
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _get_analysis_type(self, analysis_config: Optional[Dict[str, Any]]) -> str:
        """从配置中提取分析类型"""
        if analysis_config is None:
            return "ac"
        return analysis_config.get("analysis_type", "ac")
    
    def _run_nominal(
        self,
        circuit_file: str,
        analysis_config: Optional[Dict[str, Any]],
    ) -> SimulationResult:
        """执行标称仿真"""
        return self._executor.execute(circuit_file, analysis_config)
    
    def _run_with_param(
        self,
        circuit_file: str,
        analysis_config: Optional[Dict[str, Any]],
        param_key: str,
        param_value: float,
    ) -> SimulationResult:
        """执行带参数修改的仿真"""
        config = dict(analysis_config) if analysis_config else {}
        config["worst_case_params"] = {param_key: param_value}
        return self._executor.execute(circuit_file, config)
    
    def _calculate_rss(
        self,
        nominal: float,
        sensitivities: List[ParameterSensitivity],
    ) -> Tuple[float, float]:
        """
        RSS 方法计算最坏情况
        
        Returns:
            Tuple[float, float]: (最大值, 最小值)
        """
        # 计算各参数影响量的平方和
        sum_sq_plus = 0.0
        sum_sq_minus = 0.0
        
        for sens in sensitivities:
            # 取绝对值较大的作为该参数的影响量
            delta = max(abs(sens.delta_plus), abs(sens.delta_minus))
            sum_sq_plus += delta ** 2
            sum_sq_minus += delta ** 2
        
        # 总变化量
        total_delta = np.sqrt(sum_sq_plus)
        
        return nominal + total_delta, nominal - total_delta
    
    def _calculate_eva(
        self,
        circuit_file: str,
        analysis_config: Optional[Dict[str, Any]],
        tolerances: List[ToleranceSpec],
        sensitivities: List[ParameterSensitivity],
        metric: str,
    ) -> Tuple[float, float, Dict[str, float]]:
        """
        EVA 方法计算最坏情况
        
        Returns:
            Tuple[float, float, Dict]: (最大值, 最小值, 最坏参数组合)
        """
        # 构建使指标最小化的参数组合
        worst_min_params = {}
        worst_max_params = {}
        
        for tol in tolerances:
            sens = next((s for s in sensitivities if s.param_key == tol.key), None)
            nominal = tol.nominal_value if tol.nominal_value else 1.0
            
            if sens:
                # 使指标减小的方向
                if sens.delta_plus < sens.delta_minus:
                    worst_min_params[tol.key] = tol.get_max_value(nominal)
                    worst_max_params[tol.key] = tol.get_min_value(nominal)
                else:
                    worst_min_params[tol.key] = tol.get_min_value(nominal)
                    worst_max_params[tol.key] = tol.get_max_value(nominal)
            else:
                # 无敏感度信息，取最小值
                worst_min_params[tol.key] = tol.get_min_value(nominal)
                worst_max_params[tol.key] = tol.get_max_value(nominal)
        
        # 执行最坏情况仿真（最小化）
        config_min = dict(analysis_config) if analysis_config else {}
        config_min["worst_case_params"] = worst_min_params
        result_min = self._executor.execute(circuit_file, config_min)
        
        wc_min = 0.0
        if result_min.success and metric in (result_min.metrics or {}):
            wc_min = result_min.metrics[metric]
        
        # 执行最坏情况仿真（最大化）
        config_max = dict(analysis_config) if analysis_config else {}
        config_max["worst_case_params"] = worst_max_params
        result_max = self._executor.execute(circuit_file, config_max)
        
        wc_max = 0.0
        if result_max.success and metric in (result_max.metrics or {}):
            wc_max = result_max.metrics[metric]
        
        return wc_max, wc_min, worst_min_params
    
    def _publish_complete_event(self, result: WorstCaseResult) -> None:
        """发布分析完成事件"""
        bus = self._get_event_bus()
        if bus:
            from shared.event_types import EVENT_WORST_CASE_COMPLETE
            bus.publish(EVENT_WORST_CASE_COMPLETE, {
                "circuit_file": result.circuit_file,
                "method": result.method.value,
                "metric": result.metric,
                "nominal_value": result.nominal_value,
                "worst_case_max": result.worst_case_max,
                "worst_case_min": result.worst_case_min,
                "design_margin_percent": result.design_margin_percent,
                "critical_params": result.critical_params,
                "simulation_count": result.simulation_count,
            })


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "WorstCaseAnalyzer",
    "WorstCaseMethod",
    "ToleranceSpec",
    "ParameterSensitivity",
    "WorstCaseResult",
]
