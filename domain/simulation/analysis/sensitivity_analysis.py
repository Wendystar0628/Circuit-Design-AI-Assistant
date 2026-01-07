# Sensitivity Analysis - Parameter Impact Evaluation
"""
敏感度分析

职责：
- 分析各参数对输出的影响程度
- 识别关键元件，指导优化方向
- 生成龙卷风图数据
- 提供优化建议

设计原则：
- 作为工具类按需实例化，无需显式初始化
- 与最坏情况分析共享容差定义模式
- 生成可视化友好的数据结构
- 支持与 LLM 优化协同

使用示例：
    from domain.simulation.analysis.sensitivity_analysis import SensitivityAnalyzer
    
    analyzer = SensitivityAnalyzer()
    
    # 定义要分析的参数
    params = [
        {"component": "R1", "param": "resistance", "nominal": 10e3},
        {"component": "C1", "param": "capacitance", "nominal": 1e-9},
    ]
    
    # 执行敏感度分析
    result = analyzer.run_sensitivity(
        circuit_file="amplifier.cir",
        params=params,
        metric="gain",
        perturbation_percent=1.0,
    )
    
    # 获取龙卷风图数据
    tornado = analyzer.generate_tornado_chart_data(result)
    
    # 获取优化建议
    suggestions = analyzer.get_optimization_suggestions(result, goals={"gain": {"min": 20.0}})
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from domain.simulation.executor.spice_executor import SpiceExecutor
from domain.simulation.models.simulation_result import SimulationResult


# ============================================================
# 数据类定义
# ============================================================

@dataclass
class SensitivityParam:
    """
    敏感度分析参数定义
    
    Attributes:
        component: 元件名称（如 "R1", "C1"）
        param: 参数名称（如 "resistance", "capacitance"）
        nominal_value: 标称值
        unit: 单位（可选，用于显示）
    """
    component: str
    param: str
    nominal_value: float
    unit: str = ""
    
    @property
    def key(self) -> str:
        """获取参数键名"""
        return f"{self.component}.{self.param}"
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "component": self.component,
            "param": self.param,
            "nominal_value": self.nominal_value,
            "unit": self.unit,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SensitivityParam":
        """从字典反序列化"""
        return cls(
            component=data["component"],
            param=data["param"],
            nominal_value=data["nominal_value"],
            unit=data.get("unit", ""),
        )


@dataclass
class ParamSensitivityData:
    """
    单个参数的敏感度数据
    
    Attributes:
        param_key: 参数键名
        nominal_value: 标称值
        absolute_sensitivity: 绝对敏感度 S = ∂Output / ∂Param
        relative_sensitivity: 相对敏感度 S_rel = (∂Output/Output) / (∂Param/Param)
        normalized_sensitivity: 归一化敏感度（0-1 范围）
        delta_plus: +扰动时的输出变化
        delta_minus: -扰动时的输出变化
        direction: 影响方向（"positive", "negative", "non_monotonic"）
    """
    param_key: str
    nominal_value: float = 0.0
    absolute_sensitivity: float = 0.0
    relative_sensitivity: float = 0.0
    normalized_sensitivity: float = 0.0
    delta_plus: float = 0.0
    delta_minus: float = 0.0
    direction: str = "positive"
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "param_key": self.param_key,
            "nominal_value": self.nominal_value,
            "absolute_sensitivity": self.absolute_sensitivity,
            "relative_sensitivity": self.relative_sensitivity,
            "normalized_sensitivity": self.normalized_sensitivity,
            "delta_plus": self.delta_plus,
            "delta_minus": self.delta_minus,
            "direction": self.direction,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParamSensitivityData":
        """从字典反序列化"""
        return cls(
            param_key=data["param_key"],
            nominal_value=data.get("nominal_value", 0.0),
            absolute_sensitivity=data.get("absolute_sensitivity", 0.0),
            relative_sensitivity=data.get("relative_sensitivity", 0.0),
            normalized_sensitivity=data.get("normalized_sensitivity", 0.0),
            delta_plus=data.get("delta_plus", 0.0),
            delta_minus=data.get("delta_minus", 0.0),
            direction=data.get("direction", "positive"),
        )


@dataclass
class TornadoChartData:
    """
    龙卷风图数据
    
    Attributes:
        param_names: 参数名列表（按敏感度绝对值降序排列）
        positive_impacts: 正向影响值（+扰动导致的输出变化）
        negative_impacts: 负向影响值（-扰动导致的输出变化）
        baseline_value: 基准值（标称仿真结果）
        metric_name: 指标名称
    """
    param_names: List[str] = field(default_factory=list)
    positive_impacts: List[float] = field(default_factory=list)
    negative_impacts: List[float] = field(default_factory=list)
    baseline_value: float = 0.0
    metric_name: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "param_names": self.param_names,
            "positive_impacts": self.positive_impacts,
            "negative_impacts": self.negative_impacts,
            "baseline_value": self.baseline_value,
            "metric_name": self.metric_name,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TornadoChartData":
        """从字典反序列化"""
        return cls(
            param_names=data.get("param_names", []),
            positive_impacts=data.get("positive_impacts", []),
            negative_impacts=data.get("negative_impacts", []),
            baseline_value=data.get("baseline_value", 0.0),
            metric_name=data.get("metric_name", ""),
        )


@dataclass
class OptimizationSuggestion:
    """
    优化建议
    
    Attributes:
        param_key: 参数键名
        action: 建议动作（"increase", "decrease", "fine_tune"）
        estimated_change: 预估变化量
        priority: 优先级（1-5，1 最高）
        reason: 建议原因
    """
    param_key: str
    action: str
    estimated_change: float = 0.0
    priority: int = 3
    reason: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "param_key": self.param_key,
            "action": self.action,
            "estimated_change": self.estimated_change,
            "priority": self.priority,
            "reason": self.reason,
        }


@dataclass
class SensitivityAnalysisResult:
    """
    敏感度分析结果
    
    Attributes:
        circuit_file: 电路文件路径
        analysis_type: 分析类型
        metric_name: 分析的指标名称
        nominal_value: 标称值
        perturbation_percent: 扰动百分比
        param_sensitivities: 参数敏感度列表
        critical_params: 关键参数列表（按敏感度排序）
        tornado_data: 龙卷风图数据
        optimization_suggestions: 优化建议列表
        simulation_count: 仿真次数
        timestamp: 分析时间戳
        duration_seconds: 总耗时
        success: 是否成功
        error_message: 错误信息
    """
    circuit_file: str
    analysis_type: str = "ac"
    metric_name: str = ""
    nominal_value: float = 0.0
    perturbation_percent: float = 1.0
    param_sensitivities: List[ParamSensitivityData] = field(default_factory=list)
    critical_params: List[str] = field(default_factory=list)
    tornado_data: Optional[TornadoChartData] = None
    optimization_suggestions: List[OptimizationSuggestion] = field(default_factory=list)
    simulation_count: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    duration_seconds: float = 0.0
    success: bool = True
    error_message: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "circuit_file": self.circuit_file,
            "analysis_type": self.analysis_type,
            "metric_name": self.metric_name,
            "nominal_value": self.nominal_value,
            "perturbation_percent": self.perturbation_percent,
            "param_sensitivities": [p.to_dict() for p in self.param_sensitivities],
            "critical_params": self.critical_params,
            "tornado_data": self.tornado_data.to_dict() if self.tornado_data else None,
            "optimization_suggestions": [s.to_dict() for s in self.optimization_suggestions],
            "simulation_count": self.simulation_count,
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
            "success": self.success,
            "error_message": self.error_message,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SensitivityAnalysisResult":
        """从字典反序列化"""
        param_sensitivities = [
            ParamSensitivityData.from_dict(p) 
            for p in data.get("param_sensitivities", [])
        ]
        tornado_data = None
        if data.get("tornado_data"):
            tornado_data = TornadoChartData.from_dict(data["tornado_data"])
        return cls(
            circuit_file=data["circuit_file"],
            analysis_type=data.get("analysis_type", "ac"),
            metric_name=data.get("metric_name", ""),
            nominal_value=data.get("nominal_value", 0.0),
            perturbation_percent=data.get("perturbation_percent", 1.0),
            param_sensitivities=param_sensitivities,
            critical_params=data.get("critical_params", []),
            tornado_data=tornado_data,
            optimization_suggestions=[],
            simulation_count=data.get("simulation_count", 0),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            duration_seconds=data.get("duration_seconds", 0.0),
            success=data.get("success", True),
            error_message=data.get("error_message", ""),
        )
    
    def get_display_summary(self) -> str:
        """获取用于 UI 显示的摘要文本"""
        if not self.success:
            return f"敏感度分析失败: {self.error_message}"
        return f"敏感度分析完成 ({self.metric_name}) - {len(self.param_sensitivities)} 个参数"


# ============================================================
# 常量定义
# ============================================================

# 默认扰动百分比
DEFAULT_PERTURBATION_PERCENT = 1.0

# 关键参数阈值（归一化敏感度超过此值视为关键参数）
CRITICAL_PARAM_THRESHOLD = 0.3

# 最大参数数量警告阈值
MAX_PARAMS_WARNING_THRESHOLD = 20



# ============================================================
# SensitivityAnalyzer - 敏感度分析器
# ============================================================

class SensitivityAnalyzer:
    """
    敏感度分析器
    
    分析各参数对输出的影响程度，识别关键元件，生成优化建议。
    
    特性：
    - 支持绝对敏感度和相对敏感度计算
    - 生成龙卷风图数据
    - 识别关键参数
    - 生成优化建议供 LLM 或用户参考
    
    敏感度计算方法：
    - 绝对敏感度：S = ∂Output / ∂Param
    - 相对敏感度：S_rel = (∂Output / Output) / (∂Param / Param)
    - 归一化敏感度：将敏感度归一化到 0-1 范围
    """
    
    def __init__(self, executor: Optional[SpiceExecutor] = None):
        """
        初始化敏感度分析器
        
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
    # 敏感度分析
    # ============================================================
    
    def run_sensitivity(
        self,
        circuit_file: str,
        params: List[Dict[str, Any]],
        metric: str,
        perturbation_percent: float = DEFAULT_PERTURBATION_PERCENT,
        analysis_config: Optional[Dict[str, Any]] = None,
        on_progress: Optional[Callable[[str, int, int, float], None]] = None,
    ) -> SensitivityAnalysisResult:
        """
        执行敏感度分析
        
        Args:
            circuit_file: 电路文件路径
            params: 参数列表，每项包含 component, param, nominal_value
            metric: 要分析的指标名称
            perturbation_percent: 扰动百分比（默认 1%）
            analysis_config: 仿真配置字典
            on_progress: 进度回调 (param_name, param_index, total_params, sensitivity)
            
        Returns:
            SensitivityAnalysisResult: 敏感度分析结果
        """
        start_time = time.time()
        analysis_type = self._get_analysis_type(analysis_config)
        
        # 转换参数列表
        sensitivity_params = [
            SensitivityParam(
                component=p["component"],
                param=p["param"],
                nominal_value=p["nominal_value"],
                unit=p.get("unit", ""),
            )
            for p in params
        ]
        
        n_params = len(sensitivity_params)
        total_sims = 2 * n_params + 1  # 标称 + 每个参数的 +/- 扰动
        
        self._logger.info(
            f"开始敏感度分析: {circuit_file}, "
            f"指标={metric}, 参数数={n_params}, 扰动={perturbation_percent}%"
        )
        
        # 检查参数数量
        if n_params > MAX_PARAMS_WARNING_THRESHOLD:
            self._logger.warning(
                f"参数数量 ({n_params}) 超过阈值 ({MAX_PARAMS_WARNING_THRESHOLD})，"
                f"分析可能耗时较长"
            )
        
        # 发布开始事件
        self._publish_started_event(circuit_file, metric, n_params, perturbation_percent)
        
        result = SensitivityAnalysisResult(
            circuit_file=circuit_file,
            analysis_type=analysis_type,
            metric_name=metric,
            perturbation_percent=perturbation_percent,
        )
        
        # 1. 执行标称仿真
        nominal_result = self._run_nominal(circuit_file, analysis_config)
        if not nominal_result.success or metric not in (nominal_result.metrics or {}):
            result.success = False
            result.error_message = "标称仿真失败或指标不存在"
            result.duration_seconds = time.time() - start_time
            self._logger.error(result.error_message)
            return result
        
        result.nominal_value = nominal_result.metrics[metric]
        result.simulation_count = 1
        
        # 2. 对每个参数执行 +/- 扰动仿真
        sensitivities = []
        
        for idx, param in enumerate(sensitivity_params):
            sens_data = self._analyze_single_param(
                circuit_file=circuit_file,
                analysis_config=analysis_config,
                param=param,
                metric=metric,
                nominal_output=result.nominal_value,
                perturbation_percent=perturbation_percent,
            )
            sensitivities.append(sens_data)
            result.simulation_count += 2
            
            # 发布进度事件
            self._publish_progress_event(
                param.key, idx, n_params, sens_data.absolute_sensitivity
            )
            
            # 调用回调
            if on_progress:
                on_progress(param.key, idx, n_params, sens_data.absolute_sensitivity)
        
        # 3. 归一化敏感度
        self._normalize_sensitivities(sensitivities)
        
        result.param_sensitivities = sensitivities
        
        # 4. 按敏感度排序，识别关键参数
        result.critical_params = self.rank_by_sensitivity(sensitivities)
        
        # 5. 生成龙卷风图数据
        result.tornado_data = self.generate_tornado_chart_data(
            sensitivities, result.nominal_value, metric
        )
        
        result.duration_seconds = time.time() - start_time
        
        # 发布完成事件
        self._publish_complete_event(result)
        
        self._logger.info(
            f"敏感度分析完成: 标称={result.nominal_value:.4g}, "
            f"关键参数={result.critical_params[:3]}, "
            f"耗时 {result.duration_seconds:.2f}s"
        )
        
        return result
    
    def calculate_sensitivity(
        self,
        param_nominal: float,
        output_nominal: float,
        output_perturbed: float,
        delta_param: float,
    ) -> Tuple[float, float]:
        """
        计算单个参数的敏感度
        
        Args:
            param_nominal: 参数标称值
            output_nominal: 输出标称值
            output_perturbed: 扰动后的输出值
            delta_param: 参数变化量
            
        Returns:
            Tuple[float, float]: (绝对敏感度, 相对敏感度)
        """
        # 绝对敏感度：S = ∂Output / ∂Param
        delta_output = output_perturbed - output_nominal
        absolute_sens = delta_output / delta_param if delta_param != 0 else 0.0
        
        # 相对敏感度：S_rel = (∂Output/Output) / (∂Param/Param)
        relative_sens = 0.0
        if output_nominal != 0 and param_nominal != 0 and delta_param != 0:
            relative_sens = (delta_output / output_nominal) / (delta_param / param_nominal)
        
        return absolute_sens, relative_sens
    
    def rank_by_sensitivity(
        self,
        sensitivities: List[ParamSensitivityData],
        threshold: float = CRITICAL_PARAM_THRESHOLD,
    ) -> List[str]:
        """
        按敏感度排序参数，返回关键参数列表
        
        Args:
            sensitivities: 参数敏感度列表
            threshold: 关键参数阈值
            
        Returns:
            List[str]: 按敏感度降序排列的参数键名列表
        """
        # 按归一化敏感度绝对值降序排序
        sorted_sens = sorted(
            sensitivities,
            key=lambda s: abs(s.normalized_sensitivity),
            reverse=True
        )
        
        # 返回超过阈值的参数
        critical = [
            s.param_key for s in sorted_sens
            if abs(s.normalized_sensitivity) >= threshold
        ]
        
        # 如果没有超过阈值的，返回前 3 个
        if not critical and sorted_sens:
            critical = [s.param_key for s in sorted_sens[:3]]
        
        return critical
    
    def identify_critical_components(
        self,
        result: SensitivityAnalysisResult,
        threshold: float = CRITICAL_PARAM_THRESHOLD,
    ) -> List[str]:
        """
        识别关键元件
        
        Args:
            result: 敏感度分析结果
            threshold: 关键参数阈值
            
        Returns:
            List[str]: 关键元件名称列表
        """
        critical_components = set()
        
        for sens in result.param_sensitivities:
            if abs(sens.normalized_sensitivity) >= threshold:
                # 从 param_key 提取元件名（格式：component.param）
                component = sens.param_key.split(".")[0]
                critical_components.add(component)
        
        return list(critical_components)
    
    def generate_tornado_chart_data(
        self,
        sensitivities: List[ParamSensitivityData],
        baseline_value: float,
        metric_name: str,
        max_bars: int = 10,
    ) -> TornadoChartData:
        """
        生成龙卷风图数据
        
        Args:
            sensitivities: 参数敏感度列表
            baseline_value: 基准值
            metric_name: 指标名称
            max_bars: 最大显示条数
            
        Returns:
            TornadoChartData: 龙卷风图数据
        """
        # 按敏感度绝对值降序排序
        sorted_sens = sorted(
            sensitivities,
            key=lambda s: max(abs(s.delta_plus), abs(s.delta_minus)),
            reverse=True
        )[:max_bars]
        
        return TornadoChartData(
            param_names=[s.param_key for s in sorted_sens],
            positive_impacts=[s.delta_plus for s in sorted_sens],
            negative_impacts=[s.delta_minus for s in sorted_sens],
            baseline_value=baseline_value,
            metric_name=metric_name,
        )
    
    def get_optimization_suggestions(
        self,
        result: SensitivityAnalysisResult,
        goals: Dict[str, Dict[str, float]],
        max_suggestions: int = 5,
    ) -> List[OptimizationSuggestion]:
        """
        获取优化建议
        
        Args:
            result: 敏感度分析结果
            goals: 设计目标，格式 {"metric": {"min": x, "max": y, "target": z}}
            max_suggestions: 最大建议数量
            
        Returns:
            List[OptimizationSuggestion]: 优化建议列表
        """
        suggestions = []
        
        if result.metric_name not in goals:
            return suggestions
        
        goal = goals[result.metric_name]
        current_value = result.nominal_value
        
        # 确定需要的变化方向
        target_direction = self._determine_target_direction(current_value, goal)
        
        if target_direction == 0:
            # 已满足目标
            return suggestions
        
        # 按敏感度排序参数
        sorted_sens = sorted(
            result.param_sensitivities,
            key=lambda s: abs(s.normalized_sensitivity),
            reverse=True
        )
        
        for idx, sens in enumerate(sorted_sens[:max_suggestions]):
            suggestion = self._create_suggestion(
                sens, target_direction, current_value, goal, idx + 1
            )
            if suggestion:
                suggestions.append(suggestion)
        
        result.optimization_suggestions = suggestions
        return suggestions
    
    def generate_llm_context(
        self,
        result: SensitivityAnalysisResult,
        goals: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> str:
        """
        生成供 LLM 使用的敏感度分析上下文
        
        Args:
            result: 敏感度分析结果
            goals: 设计目标（可选）
            
        Returns:
            str: 格式化的上下文文本
        """
        lines = [
            "## 敏感度分析结果",
            "",
            f"**分析指标**: {result.metric_name}",
            f"**当前值**: {result.nominal_value:.4g}",
            f"**扰动量**: ±{result.perturbation_percent}%",
            "",
            "### 参数敏感度排名（按影响程度降序）",
            "",
        ]
        
        for idx, param_key in enumerate(result.critical_params[:5], 1):
            sens = next(
                (s for s in result.param_sensitivities if s.param_key == param_key),
                None
            )
            if sens:
                direction_text = {
                    "positive": "正相关（增大参数→增大输出）",
                    "negative": "负相关（增大参数→减小输出）",
                    "non_monotonic": "非单调",
                }.get(sens.direction, "未知")
                
                lines.append(
                    f"{idx}. **{param_key}**: "
                    f"相对敏感度={sens.relative_sensitivity:.4g}, "
                    f"{direction_text}"
                )
        
        lines.append("")
        
        if goals and result.optimization_suggestions:
            lines.extend([
                "### 优化建议",
                "",
            ])
            for suggestion in result.optimization_suggestions[:3]:
                action_text = {
                    "increase": "增大",
                    "decrease": "减小",
                    "fine_tune": "微调",
                }.get(suggestion.action, suggestion.action)
                
                lines.append(
                    f"- **{suggestion.param_key}**: {action_text} "
                    f"（优先级 {suggestion.priority}）- {suggestion.reason}"
                )
            lines.append("")
        
        lines.extend([
            "### 优化策略建议",
            "",
            "1. 优先调整高敏感度参数以快速接近目标",
            "2. 注意参数间的相互影响，避免过度调整",
            "3. 对于非单调参数，需要更细致的扫描分析",
        ])
        
        return "\n".join(lines)
    
    def generate_report(self, result: SensitivityAnalysisResult) -> str:
        """
        生成敏感度分析报告（Markdown 格式）
        
        Args:
            result: 敏感度分析结果
            
        Returns:
            str: Markdown 格式报告
        """
        lines = [
            "# 敏感度分析报告",
            "",
            f"**电路文件**: {result.circuit_file}",
            f"**分析类型**: {result.analysis_type}",
            f"**分析指标**: {result.metric_name}",
            f"**分析时间**: {result.timestamp}",
            f"**总耗时**: {result.duration_seconds:.2f} 秒",
            f"**仿真次数**: {result.simulation_count}",
            "",
            "## 分析配置",
            "",
            f"- **扰动百分比**: ±{result.perturbation_percent}%",
            f"- **参数数量**: {len(result.param_sensitivities)}",
            "",
            "## 分析结果",
            "",
            f"- **标称值**: {result.nominal_value:.6g}",
            "",
        ]
        
        if result.critical_params:
            lines.extend([
                "## 关键参数（按敏感度排序）",
                "",
            ])
            for idx, param_key in enumerate(result.critical_params, 1):
                sens = next(
                    (s for s in result.param_sensitivities if s.param_key == param_key),
                    None
                )
                if sens:
                    lines.append(
                        f"{idx}. **{param_key}**: "
                        f"归一化敏感度 = {sens.normalized_sensitivity:.4f}, "
                        f"相对敏感度 = {sens.relative_sensitivity:.4g}"
                    )
            lines.append("")
        
        if result.param_sensitivities:
            lines.extend([
                "## 参数敏感度详情",
                "",
                "| 参数 | 标称值 | Δ(+扰动) | Δ(-扰动) | 绝对敏感度 | 相对敏感度 | 方向 |",
                "|------|--------|----------|----------|------------|------------|------|",
            ])
            for sens in result.param_sensitivities:
                direction = {
                    "positive": "正相关",
                    "negative": "负相关",
                    "non_monotonic": "非单调",
                }.get(sens.direction, "未知")
                lines.append(
                    f"| {sens.param_key} | {sens.nominal_value:.4g} | "
                    f"{sens.delta_plus:.4g} | {sens.delta_minus:.4g} | "
                    f"{sens.absolute_sensitivity:.4g} | {sens.relative_sensitivity:.4g} | "
                    f"{direction} |"
                )
            lines.append("")
        
        if result.optimization_suggestions:
            lines.extend([
                "## 优化建议",
                "",
            ])
            for suggestion in result.optimization_suggestions:
                action_text = {
                    "increase": "增大",
                    "decrease": "减小",
                    "fine_tune": "微调",
                }.get(suggestion.action, suggestion.action)
                lines.append(
                    f"- **{suggestion.param_key}**: {action_text} "
                    f"（优先级 {suggestion.priority}）"
                )
                if suggestion.reason:
                    lines.append(f"  - {suggestion.reason}")
            lines.append("")
        
        lines.extend([
            "## 方法说明",
            "",
            "**敏感度计算方法**：",
            "",
            "- **绝对敏感度**: S = ∂Output / ∂Param",
            "- **相对敏感度**: S_rel = (∂Output/Output) / (∂Param/Param)",
            "- **归一化敏感度**: 将敏感度归一化到 0-1 范围，便于比较",
            "",
            "**分析流程**：",
            "",
            "1. 执行标称值仿真获取基准结果",
            "2. 对每个参数分别进行 +扰动% 和 -扰动% 仿真",
            "3. 计算敏感度系数",
            "4. 按敏感度绝对值排序",
            "5. 生成龙卷风图数据和优化建议",
            "",
        ])
        
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
        config["sensitivity_params"] = {param_key: param_value}
        return self._executor.execute(circuit_file, config)
    
    def _analyze_single_param(
        self,
        circuit_file: str,
        analysis_config: Optional[Dict[str, Any]],
        param: SensitivityParam,
        metric: str,
        nominal_output: float,
        perturbation_percent: float,
    ) -> ParamSensitivityData:
        """分析单个参数的敏感度"""
        nominal_value = param.nominal_value
        delta = nominal_value * perturbation_percent / 100.0
        
        # +扰动仿真
        plus_value = nominal_value + delta
        plus_result = self._run_with_param(
            circuit_file, analysis_config, param.key, plus_value
        )
        
        # -扰动仿真
        minus_value = nominal_value - delta
        minus_result = self._run_with_param(
            circuit_file, analysis_config, param.key, minus_value
        )
        
        # 计算输出变化
        delta_plus = 0.0
        delta_minus = 0.0
        
        if plus_result.success and metric in (plus_result.metrics or {}):
            delta_plus = plus_result.metrics[metric] - nominal_output
        
        if minus_result.success and metric in (minus_result.metrics or {}):
            delta_minus = minus_result.metrics[metric] - nominal_output
        
        # 计算敏感度
        abs_sens_plus, rel_sens_plus = self.calculate_sensitivity(
            nominal_value, nominal_output, nominal_output + delta_plus, delta
        )
        abs_sens_minus, rel_sens_minus = self.calculate_sensitivity(
            nominal_value, nominal_output, nominal_output + delta_minus, -delta
        )
        
        # 取平均或较大值
        absolute_sensitivity = (abs(abs_sens_plus) + abs(abs_sens_minus)) / 2
        relative_sensitivity = (abs(rel_sens_plus) + abs(rel_sens_minus)) / 2
        
        # 确定影响方向
        direction = self._determine_direction(delta_plus, delta_minus)
        
        return ParamSensitivityData(
            param_key=param.key,
            nominal_value=nominal_value,
            absolute_sensitivity=absolute_sensitivity,
            relative_sensitivity=relative_sensitivity,
            normalized_sensitivity=0.0,  # 稍后归一化
            delta_plus=delta_plus,
            delta_minus=delta_minus,
            direction=direction,
        )
    
    def _determine_direction(self, delta_plus: float, delta_minus: float) -> str:
        """确定参数影响方向"""
        if delta_plus > 0 and delta_minus < 0:
            return "positive"
        elif delta_plus < 0 and delta_minus > 0:
            return "negative"
        else:
            return "non_monotonic"
    
    def _normalize_sensitivities(
        self,
        sensitivities: List[ParamSensitivityData],
    ) -> None:
        """归一化敏感度到 0-1 范围"""
        if not sensitivities:
            return
        
        # 找最大绝对敏感度
        max_abs_sens = max(
            abs(s.absolute_sensitivity) for s in sensitivities
        )
        
        if max_abs_sens == 0:
            return
        
        # 归一化
        for sens in sensitivities:
            sens.normalized_sensitivity = abs(sens.absolute_sensitivity) / max_abs_sens
    
    def _determine_target_direction(
        self,
        current_value: float,
        goal: Dict[str, float],
    ) -> int:
        """
        确定目标变化方向
        
        Returns:
            int: 1 表示需要增大，-1 表示需要减小，0 表示已满足
        """
        min_val = goal.get("min")
        max_val = goal.get("max")
        target = goal.get("target")
        
        if target is not None:
            if current_value < target:
                return 1
            elif current_value > target:
                return -1
            return 0
        
        if min_val is not None and current_value < min_val:
            return 1
        if max_val is not None and current_value > max_val:
            return -1
        
        return 0
    
    def _create_suggestion(
        self,
        sens: ParamSensitivityData,
        target_direction: int,
        current_value: float,
        goal: Dict[str, float],
        priority: int,
    ) -> Optional[OptimizationSuggestion]:
        """创建单个优化建议"""
        # 根据敏感度方向和目标方向确定动作
        if sens.direction == "non_monotonic":
            return OptimizationSuggestion(
                param_key=sens.param_key,
                action="fine_tune",
                priority=priority + 1,  # 非单调参数优先级降低
                reason="参数影响非单调，需要细致扫描确定最优值",
            )
        
        # 正相关：增大参数→增大输出
        # 负相关：增大参数→减小输出
        if sens.direction == "positive":
            action = "increase" if target_direction > 0 else "decrease"
        else:
            action = "decrease" if target_direction > 0 else "increase"
        
        # 估算变化量
        target = goal.get("target") or goal.get("min") or goal.get("max") or current_value
        gap = target - current_value
        estimated_change = 0.0
        if sens.absolute_sensitivity != 0:
            estimated_change = gap / sens.absolute_sensitivity
        
        action_text = "增大" if action == "increase" else "减小"
        reason = (
            f"该参数敏感度高（归一化={sens.normalized_sensitivity:.2f}），"
            f"{action_text}可有效{'提升' if target_direction > 0 else '降低'}指标值"
        )
        
        return OptimizationSuggestion(
            param_key=sens.param_key,
            action=action,
            estimated_change=estimated_change,
            priority=priority,
            reason=reason,
        )
    
    # ============================================================
    # 事件发布
    # ============================================================
    
    def _publish_started_event(
        self,
        circuit_file: str,
        metric: str,
        param_count: int,
        perturbation_percent: float,
    ) -> None:
        """发布分析开始事件"""
        bus = self._get_event_bus()
        if bus:
            from shared.event_types import EVENT_SENSITIVITY_STARTED
            bus.publish(EVENT_SENSITIVITY_STARTED, {
                "circuit_file": circuit_file,
                "metric": metric,
                "param_count": param_count,
                "perturbation_percent": perturbation_percent,
            })
    
    def _publish_progress_event(
        self,
        param_name: str,
        param_index: int,
        total_params: int,
        sensitivity: float,
    ) -> None:
        """发布分析进度事件"""
        bus = self._get_event_bus()
        if bus:
            from shared.event_types import EVENT_SENSITIVITY_PROGRESS
            bus.publish(EVENT_SENSITIVITY_PROGRESS, {
                "param_name": param_name,
                "param_index": param_index,
                "total_params": total_params,
                "sensitivity": sensitivity,
            })
    
    def _publish_complete_event(self, result: SensitivityAnalysisResult) -> None:
        """发布分析完成事件"""
        bus = self._get_event_bus()
        if bus:
            from shared.event_types import EVENT_SENSITIVITY_COMPLETE
            bus.publish(EVENT_SENSITIVITY_COMPLETE, {
                "circuit_file": result.circuit_file,
                "metric": result.metric_name,
                "param_count": len(result.param_sensitivities),
                "critical_params": result.critical_params,
                "duration_seconds": result.duration_seconds,
            })


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SensitivityAnalyzer",
    "SensitivityParam",
    "ParamSensitivityData",
    "TornadoChartData",
    "OptimizationSuggestion",
    "SensitivityAnalysisResult",
    "DEFAULT_PERTURBATION_PERCENT",
    "CRITICAL_PARAM_THRESHOLD",
]
