# Monte Carlo Analysis - Statistical Simulation Analysis
"""
蒙特卡洛分析

职责：
- 执行蒙特卡洛统计分析
- 评估工艺偏差和元件容差对电路性能的影响
- 计算良率和统计指标

设计原则：
- 作为工具类按需实例化，无需显式初始化
- 顺序执行仿真（ngspice 共享库模式不支持同进程并发）
- 支持多种参数分布类型

使用示例：
    from domain.simulation.analysis.monte_carlo_analysis import MonteCarloAnalyzer
    
    analyzer = MonteCarloAnalyzer()
    
    # 定义参数变化
    variations = [
        ParameterVariation("R1", "resistance", DistributionType.UNIFORM, tolerance=0.05),
        ParameterVariation("C1", "capacitance", DistributionType.UNIFORM, tolerance=0.10),
    ]
    
    # 执行蒙特卡洛分析
    result = analyzer.run_monte_carlo(
        circuit_file="amplifier.cir",
        analysis_config={"analysis_type": "ac"},
        num_runs=100,
        variations=variations,
    )
    
    # 获取统计结果
    print(f"良率: {result.yield_percent:.1f}%")
    print(f"增益均值: {result.statistics['gain'].mean}")
"""

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from domain.simulation.executor.spice_executor import SpiceExecutor
from domain.simulation.models.simulation_result import SimulationResult


# ============================================================
# 枚举定义
# ============================================================

class DistributionType(Enum):
    """参数分布类型"""
    GAUSSIAN = "gaussian"       # 高斯分布（正态分布）
    UNIFORM = "uniform"         # 均匀分布
    LOG_NORMAL = "log_normal"   # 对数正态分布


# ============================================================
# 数据类定义
# ============================================================

@dataclass
class ParameterVariation:
    """
    参数变化配置
    
    Attributes:
        component: 元件名称（如 "R1", "C1", "M1"）
        parameter: 参数名称（如 "resistance", "capacitance", "vth0"）
        distribution: 分布类型
        tolerance: 容差（用于均匀分布，如 0.05 表示 ±5%）
        sigma: 标准差（用于高斯分布，如 0.03 表示 3σ=9%）
        nominal_value: 标称值（可选，若不指定则从电路中读取）
    """
    component: str
    parameter: str
    distribution: DistributionType
    tolerance: float = 0.05
    sigma: float = 0.01
    nominal_value: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "component": self.component,
            "parameter": self.parameter,
            "distribution": self.distribution.value,
            "tolerance": self.tolerance,
            "sigma": self.sigma,
            "nominal_value": self.nominal_value,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParameterVariation":
        """从字典反序列化"""
        return cls(
            component=data["component"],
            parameter=data["parameter"],
            distribution=DistributionType(data["distribution"]),
            tolerance=data.get("tolerance", 0.05),
            sigma=data.get("sigma", 0.01),
            nominal_value=data.get("nominal_value"),
        )
    
    def generate_value(self, nominal: float, rng: random.Random) -> float:
        """
        根据分布类型生成随机值
        
        Args:
            nominal: 标称值
            rng: 随机数生成器
            
        Returns:
            float: 生成的随机值
        """
        if self.distribution == DistributionType.UNIFORM:
            # 均匀分布：nominal * (1 ± tolerance)
            factor = 1.0 + rng.uniform(-self.tolerance, self.tolerance)
            return nominal * factor
        
        elif self.distribution == DistributionType.GAUSSIAN:
            # 高斯分布：nominal * (1 + N(0, sigma))
            factor = 1.0 + rng.gauss(0, self.sigma)
            return nominal * factor
        
        elif self.distribution == DistributionType.LOG_NORMAL:
            # 对数正态分布
            log_nominal = np.log(nominal)
            log_value = rng.gauss(log_nominal, self.sigma)
            return np.exp(log_value)
        
        return nominal


@dataclass
class MonteCarloStatistics:
    """
    单个指标的统计数据
    
    Attributes:
        metric_name: 指标名称
        mean: 均值
        std: 标准差
        min_value: 最小值
        max_value: 最大值
        median: 中位数
        percentile_3sigma_low: 3σ 下限（0.135%）
        percentile_3sigma_high: 3σ 上限（99.865%）
        values: 所有采样值（用于生成直方图）
    """
    metric_name: str
    mean: float = 0.0
    std: float = 0.0
    min_value: float = 0.0
    max_value: float = 0.0
    median: float = 0.0
    percentile_3sigma_low: float = 0.0
    percentile_3sigma_high: float = 0.0
    values: List[float] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "metric_name": self.metric_name,
            "mean": self.mean,
            "std": self.std,
            "min": self.min_value,
            "max": self.max_value,
            "median": self.median,
            "3sigma_low": self.percentile_3sigma_low,
            "3sigma_high": self.percentile_3sigma_high,
            "sample_count": len(self.values),
        }
    
    @classmethod
    def from_values(cls, metric_name: str, values: List[float]) -> "MonteCarloStatistics":
        """从值列表计算统计数据"""
        if not values:
            return cls(metric_name=metric_name)
        
        arr = np.array(values)
        return cls(
            metric_name=metric_name,
            mean=float(np.mean(arr)),
            std=float(np.std(arr)),
            min_value=float(np.min(arr)),
            max_value=float(np.max(arr)),
            median=float(np.median(arr)),
            percentile_3sigma_low=float(np.percentile(arr, 0.135)),
            percentile_3sigma_high=float(np.percentile(arr, 99.865)),
            values=values,
        )


@dataclass
class MonteCarloRunResult:
    """
    单次蒙特卡洛运行结果
    
    Attributes:
        run_index: 运行索引
        seed: 随机种子
        parameter_values: 本次运行的参数值
        simulation_result: 仿真结果
        metrics: 性能指标
        passed: 是否通过设计目标
    """
    run_index: int
    seed: int
    parameter_values: Dict[str, float] = field(default_factory=dict)
    simulation_result: Optional[SimulationResult] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    passed: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "run_index": self.run_index,
            "seed": self.seed,
            "parameter_values": self.parameter_values,
            "metrics": self.metrics,
            "passed": self.passed,
        }


@dataclass
class MonteCarloAnalysisResult:
    """
    蒙特卡洛分析完整结果
    
    Attributes:
        circuit_file: 电路文件路径
        analysis_type: 分析类型
        num_runs: 总运行次数
        successful_runs: 成功运行次数
        failed_runs: 失败运行次数
        statistics: 各指标的统计数据
        yield_percent: 良率百分比
        sensitive_params: 敏感参数排名
        runs: 各次运行结果（可选保留）
        timestamp: 分析时间戳
        duration_seconds: 总耗时
    """
    circuit_file: str
    analysis_type: str
    num_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    statistics: Dict[str, MonteCarloStatistics] = field(default_factory=dict)
    yield_percent: float = 0.0
    sensitive_params: List[str] = field(default_factory=list)
    runs: List[MonteCarloRunResult] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    duration_seconds: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "circuit_file": self.circuit_file,
            "analysis_type": self.analysis_type,
            "num_runs": self.num_runs,
            "successful_runs": self.successful_runs,
            "failed_runs": self.failed_runs,
            "statistics": {k: v.to_dict() for k, v in self.statistics.items()},
            "yield_percent": self.yield_percent,
            "sensitive_params": self.sensitive_params,
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
        }
    
    def get_statistics(self, metric: str) -> Optional[MonteCarloStatistics]:
        """获取指定指标的统计数据"""
        return self.statistics.get(metric)


# ============================================================
# 默认参数变化配置
# ============================================================

DEFAULT_RESISTOR_VARIATION = ParameterVariation(
    component="",
    parameter="resistance",
    distribution=DistributionType.UNIFORM,
    tolerance=0.05,
)

DEFAULT_CAPACITOR_VARIATION = ParameterVariation(
    component="",
    parameter="capacitance",
    distribution=DistributionType.UNIFORM,
    tolerance=0.10,
)

DEFAULT_TRANSISTOR_VTH_VARIATION = ParameterVariation(
    component="",
    parameter="vth0",
    distribution=DistributionType.GAUSSIAN,
    sigma=0.01,  # 3σ = 3%
)


# ============================================================
# MonteCarloAnalyzer - 蒙特卡洛分析器
# ============================================================

class MonteCarloAnalyzer:
    """
    蒙特卡洛分析器
    
    执行蒙特卡洛统计分析，评估工艺偏差和元件容差对电路性能的影响。
    
    特性：
    - 支持多种参数分布（高斯、均匀、对数正态）
    - 计算统计指标（均值、标准差、3σ 范围）
    - 计算良率
    - 识别敏感参数
    
    注意：
    - 由于使用 ngspice 共享库模式，仿真顺序执行
    - 大量运行时建议分批执行并保存中间结果
    """
    
    # 失败率阈值，超过此值提前终止
    FAILURE_RATE_THRESHOLD = 0.1
    
    def __init__(self, executor: Optional[SpiceExecutor] = None):
        """
        初始化蒙特卡洛分析器
        
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
    # 公开方法
    # ============================================================
    
    def define_variation(
        self,
        component: str,
        parameter: str,
        distribution: DistributionType,
        tolerance: float = 0.05,
        sigma: float = 0.01,
    ) -> ParameterVariation:
        """
        定义元件参数变化
        
        Args:
            component: 元件名称
            parameter: 参数名称
            distribution: 分布类型
            tolerance: 容差（均匀分布）
            sigma: 标准差（高斯分布）
            
        Returns:
            ParameterVariation: 参数变化配置
        """
        return ParameterVariation(
            component=component,
            parameter=parameter,
            distribution=distribution,
            tolerance=tolerance,
            sigma=sigma,
        )
    
    def run_monte_carlo(
        self,
        circuit_file: str,
        analysis_config: Optional[Dict[str, Any]] = None,
        num_runs: int = 100,
        variations: Optional[List[ParameterVariation]] = None,
        design_goals: Optional[Dict[str, Any]] = None,
        base_seed: Optional[int] = None,
        on_run_complete: Optional[Callable[[MonteCarloRunResult, int, int], None]] = None,
        keep_all_runs: bool = False,
    ) -> MonteCarloAnalysisResult:
        """
        执行蒙特卡洛仿真
        
        Args:
            circuit_file: 电路文件路径
            analysis_config: 仿真配置字典
            num_runs: 运行次数
            variations: 参数变化列表
            design_goals: 设计目标（用于计算良率）
            base_seed: 基础随机种子（可选，用于可重复性）
            on_run_complete: 单次运行完成回调
            keep_all_runs: 是否保留所有运行结果（内存占用大）
            
        Returns:
            MonteCarloAnalysisResult: 蒙特卡洛分析结果
        """
        start_time = time.time()
        analysis_type = self._get_analysis_type(analysis_config)
        
        self._logger.info(f"开始蒙特卡洛分析: {circuit_file}, {num_runs} 次运行")
        
        result = MonteCarloAnalysisResult(
            circuit_file=circuit_file,
            analysis_type=analysis_type,
            num_runs=num_runs,
        )
        
        # 初始化随机数生成器
        rng = random.Random(base_seed)
        
        # 收集各指标的值
        metric_values: Dict[str, List[float]] = {}
        passed_count = 0
        
        for run_idx in range(num_runs):
            # 生成本次运行的种子
            run_seed = rng.randint(0, 2**31 - 1)
            run_rng = random.Random(run_seed)
            
            # 执行单次运行
            run_result = self._run_single_iteration(
                circuit_file=circuit_file,
                analysis_config=analysis_config,
                variations=variations or [],
                design_goals=design_goals,
                run_index=run_idx,
                seed=run_seed,
                rng=run_rng,
            )
            
            # 统计成功/失败
            if run_result.simulation_result and run_result.simulation_result.success:
                result.successful_runs += 1
                
                # 收集指标值
                for metric_name, value in run_result.metrics.items():
                    if isinstance(value, (int, float)):
                        if metric_name not in metric_values:
                            metric_values[metric_name] = []
                        metric_values[metric_name].append(float(value))
                
                # 统计通过数
                if run_result.passed:
                    passed_count += 1
            else:
                result.failed_runs += 1
            
            # 发布进度事件
            self._publish_run_complete_event(run_result, run_idx, num_runs)
            
            # 调用回调
            if on_run_complete:
                on_run_complete(run_result, run_idx, num_runs)
            
            # 保留运行结果（可选）
            if keep_all_runs:
                result.runs.append(run_result)
            
            # 检查失败率，提前终止
            if self._should_abort(result.failed_runs, run_idx + 1):
                self._logger.warning(
                    f"失败率超过阈值 ({self.FAILURE_RATE_THRESHOLD*100}%)，提前终止"
                )
                break
        
        # 计算统计数据
        for metric_name, values in metric_values.items():
            result.statistics[metric_name] = MonteCarloStatistics.from_values(
                metric_name, values
            )
        
        # 计算良率
        if result.successful_runs > 0:
            result.yield_percent = (passed_count / result.successful_runs) * 100
        
        # 识别敏感参数
        result.sensitive_params = self._identify_sensitive_params(
            variations or [],
            metric_values,
        )
        
        result.duration_seconds = time.time() - start_time
        self._logger.info(
            f"蒙特卡洛分析完成: {result.successful_runs}/{num_runs} 成功, "
            f"良率 {result.yield_percent:.1f}%, 耗时 {result.duration_seconds:.2f}s"
        )
        
        return result
    
    def calculate_yield(
        self,
        result: MonteCarloAnalysisResult,
        specs: Dict[str, Dict[str, float]],
    ) -> float:
        """
        根据规格计算良率
        
        Args:
            result: 蒙特卡洛分析结果
            specs: 规格字典，格式 {"metric": {"min": x, "max": y}}
            
        Returns:
            float: 良率百分比
        """
        if not result.runs:
            return result.yield_percent
        
        passed = 0
        for run in result.runs:
            if self._check_specs(run.metrics, specs):
                passed += 1
        
        return (passed / len(result.runs)) * 100 if result.runs else 0.0
    
    def generate_histogram(
        self,
        result: MonteCarloAnalysisResult,
        metric: str,
        bins: int = 20,
    ) -> Dict[str, Any]:
        """
        生成直方图数据
        
        Args:
            result: 蒙特卡洛分析结果
            metric: 指标名称
            bins: 分箱数量
            
        Returns:
            Dict: 直方图数据 {"edges": [...], "counts": [...]}
        """
        stats = result.get_statistics(metric)
        if not stats or not stats.values:
            return {"edges": [], "counts": []}
        
        counts, edges = np.histogram(stats.values, bins=bins)
        return {
            "edges": edges.tolist(),
            "counts": counts.tolist(),
            "metric": metric,
            "mean": stats.mean,
            "std": stats.std,
        }
    
    def generate_report(self, result: MonteCarloAnalysisResult) -> str:
        """
        生成蒙特卡洛分析报告（Markdown 格式）
        
        Args:
            result: 蒙特卡洛分析结果
            
        Returns:
            str: Markdown 格式报告
        """
        lines = [
            "# 蒙特卡洛分析报告",
            "",
            f"**电路文件**: {result.circuit_file}",
            f"**分析类型**: {result.analysis_type}",
            f"**分析时间**: {result.timestamp}",
            f"**总耗时**: {result.duration_seconds:.2f} 秒",
            "",
            "## 运行统计",
            "",
            f"- **总运行次数**: {result.num_runs}",
            f"- **成功运行**: {result.successful_runs}",
            f"- **失败运行**: {result.failed_runs}",
            f"- **良率**: {result.yield_percent:.2f}%",
            "",
            "## 统计结果",
            "",
        ]
        
        for metric_name, stats in result.statistics.items():
            lines.extend([
                f"### {metric_name}",
                "",
                f"- **均值**: {stats.mean:.6g}",
                f"- **标准差**: {stats.std:.6g}",
                f"- **最小值**: {stats.min_value:.6g}",
                f"- **最大值**: {stats.max_value:.6g}",
                f"- **中位数**: {stats.median:.6g}",
                f"- **3σ 范围**: [{stats.percentile_3sigma_low:.6g}, {stats.percentile_3sigma_high:.6g}]",
                "",
            ])
        
        if result.sensitive_params:
            lines.extend([
                "## 敏感参数",
                "",
            ])
            for idx, param in enumerate(result.sensitive_params, 1):
                lines.append(f"{idx}. {param}")
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
    
    def _run_single_iteration(
        self,
        circuit_file: str,
        analysis_config: Optional[Dict[str, Any]],
        variations: List[ParameterVariation],
        design_goals: Optional[Dict[str, Any]],
        run_index: int,
        seed: int,
        rng: random.Random,
    ) -> MonteCarloRunResult:
        """执行单次蒙特卡洛迭代"""
        # 生成参数值
        param_values = self._generate_parameter_values(variations, rng)
        
        # 构建本次运行的配置
        run_config = self._build_run_config(analysis_config, param_values)
        
        # 执行仿真
        sim_result = self._executor.execute(circuit_file, run_config)
        
        # 提取指标
        metrics = self._extract_metrics(sim_result)
        
        # 检查设计目标
        passed = self._check_design_goals(metrics, design_goals)
        
        return MonteCarloRunResult(
            run_index=run_index,
            seed=seed,
            parameter_values=param_values,
            simulation_result=sim_result,
            metrics=metrics,
            passed=passed and sim_result.success,
        )
    
    def _generate_parameter_values(
        self,
        variations: List[ParameterVariation],
        rng: random.Random,
    ) -> Dict[str, float]:
        """生成本次运行的参数值"""
        values = {}
        for var in variations:
            # 使用标称值或默认值 1.0
            nominal = var.nominal_value if var.nominal_value else 1.0
            key = f"{var.component}.{var.parameter}"
            values[key] = var.generate_value(nominal, rng)
        return values
    
    def _build_run_config(
        self,
        base_config: Optional[Dict[str, Any]],
        param_values: Dict[str, float],
    ) -> Dict[str, Any]:
        """构建本次运行的仿真配置"""
        config = dict(base_config) if base_config else {}
        config["monte_carlo_params"] = param_values
        return config
    
    def _extract_metrics(self, sim_result: SimulationResult) -> Dict[str, Any]:
        """从仿真结果中提取性能指标"""
        if not sim_result.success:
            return {}
        
        metrics = {}
        if sim_result.metrics:
            metrics.update(sim_result.metrics)
        
        return metrics
    
    def _check_design_goals(
        self,
        metrics: Dict[str, Any],
        design_goals: Optional[Dict[str, Any]],
    ) -> bool:
        """检查是否满足设计目标"""
        if not design_goals:
            return True
        
        for goal_name, goal_spec in design_goals.items():
            if goal_name not in metrics:
                continue
            
            actual_value = metrics[goal_name]
            
            if isinstance(goal_spec, dict):
                min_val = goal_spec.get("min")
                max_val = goal_spec.get("max")
                
                if min_val is not None and actual_value < min_val:
                    return False
                if max_val is not None and actual_value > max_val:
                    return False
            elif isinstance(goal_spec, (int, float)):
                if actual_value < goal_spec:
                    return False
        
        return True
    
    def _check_specs(
        self,
        metrics: Dict[str, Any],
        specs: Dict[str, Dict[str, float]],
    ) -> bool:
        """检查是否满足规格"""
        for metric_name, spec in specs.items():
            if metric_name not in metrics:
                continue
            
            value = metrics[metric_name]
            min_val = spec.get("min")
            max_val = spec.get("max")
            
            if min_val is not None and value < min_val:
                return False
            if max_val is not None and value > max_val:
                return False
        
        return True
    
    def _should_abort(self, failed_count: int, total_count: int) -> bool:
        """检查是否应该提前终止"""
        if total_count < 10:
            return False
        failure_rate = failed_count / total_count
        return failure_rate > self.FAILURE_RATE_THRESHOLD
    
    def _identify_sensitive_params(
        self,
        variations: List[ParameterVariation],
        metric_values: Dict[str, List[float]],
    ) -> List[str]:
        """
        识别敏感参数
        
        简化实现：返回变化幅度最大的参数
        完整实现需要相关性分析
        """
        # 简化实现：按变化配置的容差/sigma 排序
        sorted_vars = sorted(
            variations,
            key=lambda v: v.tolerance if v.distribution == DistributionType.UNIFORM else v.sigma,
            reverse=True,
        )
        return [f"{v.component}.{v.parameter}" for v in sorted_vars[:5]]
    
    def _publish_run_complete_event(
        self,
        run_result: MonteCarloRunResult,
        run_index: int,
        total_runs: int,
    ) -> None:
        """发布运行完成事件"""
        bus = self._get_event_bus()
        if bus:
            from shared.event_types import EVENT_MONTE_CARLO_RUN_COMPLETE
            bus.publish(EVENT_MONTE_CARLO_RUN_COMPLETE, {
                "run_index": run_index,
                "total_runs": total_runs,
                "seed": run_result.seed,
                "result_path": "",
                "metrics": run_result.metrics,
                "passed": run_result.passed,
            })


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "MonteCarloAnalyzer",
    "ParameterVariation",
    "DistributionType",
    "MonteCarloRunResult",
    "MonteCarloAnalysisResult",
    "MonteCarloStatistics",
    "DEFAULT_RESISTOR_VARIATION",
    "DEFAULT_CAPACITOR_VARIATION",
    "DEFAULT_TRANSISTOR_VTH_VARIATION",
]
