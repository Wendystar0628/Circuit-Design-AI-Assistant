# Parametric Sweep Analysis - Design Space Exploration
"""
参数扫描分析

职责：
- 执行参数扫描分析，探索设计空间
- 支持线性、对数、列表扫描
- 支持嵌套扫描（多参数同时扫描）
- 辅助参数优化，识别敏感度和可行区域

设计原则：
- 作为工具类按需实例化，无需显式初始化
- 与蒙特卡洛分析共享参数定义模式
- 生成可视化友好的数据结构

使用示例：
    from domain.simulation.analysis.parametric_sweep import ParametricSweepAnalyzer
    
    analyzer = ParametricSweepAnalyzer()
    
    # 定义扫描参数
    sweep_config = analyzer.define_sweep_param(
        component="R1",
        param="resistance",
        start=1e3,
        stop=10e3,
        step=1e3,
    )
    
    # 执行扫描
    result = analyzer.run_sweep(
        circuit_file="amplifier.cir",
        analysis_config={"analysis_type": "ac"},
        sweep_config=sweep_config,
    )
    
    # 找出最优点
    optimal = analyzer.find_optimal_point(result, objective="gain", constraints={"bandwidth": {"min": 1e6}})
"""

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np

from domain.simulation.executor.spice_executor import SpiceExecutor
from domain.simulation.models.simulation_result import SimulationResult


# ============================================================
# 枚举定义
# ============================================================

class SweepType(Enum):
    """扫描类型"""
    LINEAR = "linear"       # 线性扫描（等间距）
    LOG = "log"             # 对数扫描（对数间距）
    LIST = "list"           # 列表扫描（指定离散值）


# ============================================================
# 数据类定义
# ============================================================

@dataclass
class SweepParameter:
    """
    扫描参数配置
    
    Attributes:
        component: 元件名称（如 "R1", "C1"）
        param: 参数名称（如 "resistance", "capacitance"）
        sweep_type: 扫描类型
        start: 起始值（线性/对数扫描）
        stop: 终止值（线性/对数扫描）
        step: 步长（线性扫描）或点数（对数扫描）
        values: 离散值列表（列表扫描）
        unit: 单位（可选，用于显示）
    """
    component: str
    param: str
    sweep_type: SweepType
    start: Optional[float] = None
    stop: Optional[float] = None
    step: Optional[float] = None
    values: Optional[List[float]] = None
    unit: str = ""
    
    def get_sweep_values(self) -> List[float]:
        """获取扫描值列表"""
        if self.sweep_type == SweepType.LIST:
            return self.values or []
        
        if self.start is None or self.stop is None:
            return []
        
        if self.sweep_type == SweepType.LINEAR:
            if self.step is None or self.step <= 0:
                return [self.start, self.stop]
            return list(np.arange(self.start, self.stop + self.step / 2, self.step))
        
        elif self.sweep_type == SweepType.LOG:
            # step 在对数扫描中表示点数
            num_points = int(self.step) if self.step else 10
            if self.start <= 0 or self.stop <= 0:
                return []
            return list(np.logspace(np.log10(self.start), np.log10(self.stop), num_points))
        
        return []
    
    @property
    def num_points(self) -> int:
        """获取扫描点数"""
        return len(self.get_sweep_values())
    
    @property
    def key(self) -> str:
        """获取参数键名"""
        return f"{self.component}.{self.param}"
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "component": self.component,
            "param": self.param,
            "sweep_type": self.sweep_type.value,
            "start": self.start,
            "stop": self.stop,
            "step": self.step,
            "values": self.values,
            "unit": self.unit,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SweepParameter":
        """从字典反序列化"""
        return cls(
            component=data["component"],
            param=data["param"],
            sweep_type=SweepType(data["sweep_type"]),
            start=data.get("start"),
            stop=data.get("stop"),
            step=data.get("step"),
            values=data.get("values"),
            unit=data.get("unit", ""),
        )


@dataclass
class NestedSweepConfig:
    """
    嵌套扫描配置
    
    Attributes:
        params: 扫描参数列表（最多 3 层）
        total_points: 总扫描点数
        estimated_time_seconds: 预估时间（秒）
    """
    params: List[SweepParameter] = field(default_factory=list)
    
    @property
    def total_points(self) -> int:
        """计算总扫描点数"""
        if not self.params:
            return 0
        total = 1
        for p in self.params:
            total *= p.num_points
        return total
    
    @property
    def depth(self) -> int:
        """嵌套深度"""
        return len(self.params)
    
    def estimate_time(self, seconds_per_sim: float = 1.0) -> float:
        """预估总时间"""
        return self.total_points * seconds_per_sim
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "params": [p.to_dict() for p in self.params],
            "total_points": self.total_points,
            "depth": self.depth,
        }


@dataclass
class SweepPointResult:
    """
    单个扫描点结果
    
    Attributes:
        point_index: 扫描点索引
        param_values: 参数值字典
        simulation_result: 仿真结果
        metrics: 性能指标
        passed: 是否满足约束
    """
    point_index: int
    param_values: Dict[str, float]
    simulation_result: Optional[SimulationResult] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    passed: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "point_index": self.point_index,
            "param_values": self.param_values,
            "metrics": self.metrics,
            "passed": self.passed,
        }


@dataclass
class SweepAnalysisResult:
    """
    参数扫描分析结果
    
    Attributes:
        circuit_file: 电路文件路径
        analysis_type: 分析类型
        sweep_config: 扫描配置
        points: 扫描点结果列表
        optimal_point: 最优点（若已计算）
        sensitivity: 参数敏感度
        feasible_region: 可行区域边界
        timestamp: 分析时间戳
        duration_seconds: 总耗时
    """
    circuit_file: str
    analysis_type: str
    sweep_config: NestedSweepConfig
    points: List[SweepPointResult] = field(default_factory=list)
    optimal_point: Optional[SweepPointResult] = None
    sensitivity: Dict[str, float] = field(default_factory=dict)
    feasible_region: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    duration_seconds: float = 0.0
    
    @property
    def successful_points(self) -> int:
        """成功的扫描点数"""
        return sum(1 for p in self.points if p.simulation_result and p.simulation_result.success)
    
    @property
    def failed_points(self) -> int:
        """失败的扫描点数"""
        return len(self.points) - self.successful_points
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "circuit_file": self.circuit_file,
            "analysis_type": self.analysis_type,
            "sweep_config": self.sweep_config.to_dict(),
            "points": [p.to_dict() for p in self.points],
            "optimal_point": self.optimal_point.to_dict() if self.optimal_point else None,
            "sensitivity": self.sensitivity,
            "feasible_region": self.feasible_region,
            "successful_points": self.successful_points,
            "failed_points": self.failed_points,
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
        }



# ============================================================
# 常量定义
# ============================================================

# 最大嵌套深度
MAX_NESTED_DEPTH = 3

# 扫描点数警告阈值
SWEEP_POINTS_WARNING_THRESHOLD = 100

# 默认每次仿真预估时间（秒）
DEFAULT_SIM_TIME_ESTIMATE = 1.0


# ============================================================
# ParametricSweepAnalyzer - 参数扫描分析器
# ============================================================

class ParametricSweepAnalyzer:
    """
    参数扫描分析器
    
    执行参数扫描分析，探索设计空间，辅助参数优化。
    
    特性：
    - 支持线性、对数、列表扫描
    - 支持最多 3 层嵌套扫描
    - 生成曲线、等高线、热力图数据
    - 识别参数敏感度和可行区域
    """
    
    def __init__(self, executor: Optional[SpiceExecutor] = None):
        """
        初始化参数扫描分析器
        
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
    # 扫描参数定义
    # ============================================================
    
    def define_sweep_param(
        self,
        component: str,
        param: str,
        start: float,
        stop: float,
        step: float,
        sweep_type: SweepType = SweepType.LINEAR,
        unit: str = "",
    ) -> SweepParameter:
        """
        定义扫描参数
        
        Args:
            component: 元件名称
            param: 参数名称
            start: 起始值
            stop: 终止值
            step: 步长（线性）或点数（对数）
            sweep_type: 扫描类型
            unit: 单位
            
        Returns:
            SweepParameter: 扫描参数配置
        """
        return SweepParameter(
            component=component,
            param=param,
            sweep_type=sweep_type,
            start=start,
            stop=stop,
            step=step,
            unit=unit,
        )
    
    def define_list_sweep(
        self,
        component: str,
        param: str,
        values: List[float],
        unit: str = "",
    ) -> SweepParameter:
        """
        定义列表扫描参数
        
        Args:
            component: 元件名称
            param: 参数名称
            values: 离散值列表
            unit: 单位
            
        Returns:
            SweepParameter: 扫描参数配置
        """
        return SweepParameter(
            component=component,
            param=param,
            sweep_type=SweepType.LIST,
            values=values,
            unit=unit,
        )
    
    def define_nested_sweep(
        self,
        params: List[SweepParameter],
    ) -> NestedSweepConfig:
        """
        定义嵌套扫描
        
        Args:
            params: 扫描参数列表（最多 3 层）
            
        Returns:
            NestedSweepConfig: 嵌套扫描配置
            
        Raises:
            ValueError: 超过最大嵌套深度
        """
        if len(params) > MAX_NESTED_DEPTH:
            raise ValueError(f"嵌套深度超过最大限制 {MAX_NESTED_DEPTH}")
        
        return NestedSweepConfig(params=params)
    
    # ============================================================
    # 扫描执行
    # ============================================================
    
    def run_sweep(
        self,
        circuit_file: str,
        analysis_config: Optional[Dict[str, Any]] = None,
        sweep_config: Union[SweepParameter, NestedSweepConfig, None] = None,
        constraints: Optional[Dict[str, Dict[str, float]]] = None,
        on_point_complete: Optional[Callable[[SweepPointResult, int, int], None]] = None,
    ) -> SweepAnalysisResult:
        """
        执行参数扫描
        
        Args:
            circuit_file: 电路文件路径
            analysis_config: 仿真配置字典
            sweep_config: 扫描配置（单参数或嵌套）
            constraints: 约束条件（用于标记可行点）
            on_point_complete: 扫描点完成回调
            
        Returns:
            SweepAnalysisResult: 扫描分析结果
        """
        start_time = time.time()
        analysis_type = self._get_analysis_type(analysis_config)
        
        # 统一为嵌套配置
        if isinstance(sweep_config, SweepParameter):
            nested_config = NestedSweepConfig(params=[sweep_config])
        elif isinstance(sweep_config, NestedSweepConfig):
            nested_config = sweep_config
        else:
            nested_config = NestedSweepConfig()
        
        total_points = nested_config.total_points
        self._logger.info(f"开始参数扫描: {circuit_file}, {total_points} 个扫描点")
        
        # 检查扫描点数
        if total_points > SWEEP_POINTS_WARNING_THRESHOLD:
            self._logger.warning(
                f"扫描点数 ({total_points}) 超过阈值 ({SWEEP_POINTS_WARNING_THRESHOLD})，"
                f"预计耗时 {nested_config.estimate_time():.1f} 秒"
            )
        
        result = SweepAnalysisResult(
            circuit_file=circuit_file,
            analysis_type=analysis_type,
            sweep_config=nested_config,
        )
        
        # 生成所有扫描点组合
        sweep_points = self._generate_sweep_points(nested_config)
        
        # 逐点执行仿真
        for idx, param_values in enumerate(sweep_points):
            point_result = self._run_single_point(
                circuit_file=circuit_file,
                analysis_config=analysis_config,
                param_values=param_values,
                point_index=idx,
                constraints=constraints,
            )
            result.points.append(point_result)
            
            # 发布进度事件
            self._publish_point_complete_event(point_result, idx, total_points)
            
            # 调用回调
            if on_point_complete:
                on_point_complete(point_result, idx, total_points)
        
        # 计算敏感度
        result.sensitivity = self._calculate_sensitivity(result)
        
        # 识别可行区域
        result.feasible_region = self._identify_feasible_region(result)
        
        result.duration_seconds = time.time() - start_time
        self._logger.info(
            f"参数扫描完成: {result.successful_points}/{total_points} 成功, "
            f"耗时 {result.duration_seconds:.2f}s"
        )
        
        return result
    
    # ============================================================
    # 结果分析
    # ============================================================
    
    def find_optimal_point(
        self,
        result: SweepAnalysisResult,
        objective: str,
        constraints: Optional[Dict[str, Dict[str, float]]] = None,
        maximize: bool = True,
    ) -> Optional[SweepPointResult]:
        """
        找出最优参数点
        
        Args:
            result: 扫描结果
            objective: 目标指标名称
            constraints: 约束条件
            maximize: True 表示最大化目标，False 表示最小化
            
        Returns:
            Optional[SweepPointResult]: 最优点，若无有效点返回 None
        """
        # 筛选有效点
        valid_points = [
            p for p in result.points
            if p.simulation_result and p.simulation_result.success
            and objective in p.metrics
        ]
        
        # 应用约束
        if constraints:
            valid_points = [
                p for p in valid_points
                if self._check_constraints(p.metrics, constraints)
            ]
        
        if not valid_points:
            return None
        
        # 找最优
        if maximize:
            optimal = max(valid_points, key=lambda p: p.metrics[objective])
        else:
            optimal = min(valid_points, key=lambda p: p.metrics[objective])
        
        result.optimal_point = optimal
        return optimal
    
    def generate_curve_data(
        self,
        result: SweepAnalysisResult,
        x_param: str,
        y_metric: str,
    ) -> Dict[str, Any]:
        """
        生成单参数扫描曲线数据
        
        Args:
            result: 扫描结果
            x_param: X 轴参数名（如 "R1.resistance"）
            y_metric: Y 轴指标名
            
        Returns:
            Dict: 曲线数据 {"x": [...], "y": [...], "x_label": ..., "y_label": ...}
        """
        x_values = []
        y_values = []
        
        for point in result.points:
            if point.simulation_result and point.simulation_result.success:
                if x_param in point.param_values and y_metric in point.metrics:
                    x_values.append(point.param_values[x_param])
                    y_values.append(point.metrics[y_metric])
        
        return {
            "x": x_values,
            "y": y_values,
            "x_label": x_param,
            "y_label": y_metric,
        }
    
    def generate_contour_data(
        self,
        result: SweepAnalysisResult,
        x_param: str,
        y_param: str,
        z_metric: str,
    ) -> Dict[str, Any]:
        """
        生成双参数扫描等高线/热力图数据
        
        Args:
            result: 扫描结果
            x_param: X 轴参数名
            y_param: Y 轴参数名
            z_metric: Z 轴指标名
            
        Returns:
            Dict: 等高线数据 {"x": [...], "y": [...], "z": [[...]], ...}
        """
        # 收集唯一的 x, y 值
        x_set = set()
        y_set = set()
        z_map = {}
        
        for point in result.points:
            if point.simulation_result and point.simulation_result.success:
                if x_param in point.param_values and y_param in point.param_values:
                    x_val = point.param_values[x_param]
                    y_val = point.param_values[y_param]
                    x_set.add(x_val)
                    y_set.add(y_val)
                    
                    if z_metric in point.metrics:
                        z_map[(x_val, y_val)] = point.metrics[z_metric]
        
        x_sorted = sorted(x_set)
        y_sorted = sorted(y_set)
        
        # 构建 Z 矩阵
        z_matrix = []
        for y_val in y_sorted:
            row = []
            for x_val in x_sorted:
                row.append(z_map.get((x_val, y_val), float('nan')))
            z_matrix.append(row)
        
        return {
            "x": x_sorted,
            "y": y_sorted,
            "z": z_matrix,
            "x_label": x_param,
            "y_label": y_param,
            "z_label": z_metric,
        }
    
    def generate_slice_data(
        self,
        result: SweepAnalysisResult,
        fixed_param: str,
        fixed_value: float,
        x_param: str,
        y_param: str,
        z_metric: str,
        tolerance: float = 0.01,
    ) -> Dict[str, Any]:
        """
        生成三参数扫描切片数据
        
        Args:
            result: 扫描结果
            fixed_param: 固定参数名
            fixed_value: 固定参数值
            x_param: X 轴参数名
            y_param: Y 轴参数名
            z_metric: Z 轴指标名
            tolerance: 固定值容差（相对）
            
        Returns:
            Dict: 切片数据
        """
        # 筛选固定参数值附近的点
        filtered_points = []
        for point in result.points:
            if fixed_param in point.param_values:
                actual = point.param_values[fixed_param]
                if abs(actual - fixed_value) / max(abs(fixed_value), 1e-10) <= tolerance:
                    filtered_points.append(point)
        
        # 构建临时结果用于生成等高线
        temp_result = SweepAnalysisResult(
            circuit_file=result.circuit_file,
            analysis_type=result.analysis_type,
            sweep_config=result.sweep_config,
            points=filtered_points,
        )
        
        contour = self.generate_contour_data(temp_result, x_param, y_param, z_metric)
        contour["fixed_param"] = fixed_param
        contour["fixed_value"] = fixed_value
        
        return contour
    
    def generate_report(self, result: SweepAnalysisResult) -> str:
        """
        生成参数扫描报告（Markdown 格式）
        
        Args:
            result: 扫描分析结果
            
        Returns:
            str: Markdown 格式报告
        """
        lines = [
            "# 参数扫描分析报告",
            "",
            f"**电路文件**: {result.circuit_file}",
            f"**分析类型**: {result.analysis_type}",
            f"**分析时间**: {result.timestamp}",
            f"**总耗时**: {result.duration_seconds:.2f} 秒",
            "",
            "## 扫描配置",
            "",
            f"- **嵌套深度**: {result.sweep_config.depth}",
            f"- **总扫描点数**: {result.sweep_config.total_points}",
            "",
        ]
        
        for idx, param in enumerate(result.sweep_config.params, 1):
            lines.extend([
                f"### 参数 {idx}: {param.key}",
                f"- **扫描类型**: {param.sweep_type.value}",
                f"- **扫描点数**: {param.num_points}",
            ])
            if param.sweep_type != SweepType.LIST:
                lines.append(f"- **范围**: {param.start} ~ {param.stop}")
            if param.unit:
                lines.append(f"- **单位**: {param.unit}")
            lines.append("")
        
        lines.extend([
            "## 扫描结果",
            "",
            f"- **成功点数**: {result.successful_points}",
            f"- **失败点数**: {result.failed_points}",
            "",
        ])
        
        if result.sensitivity:
            lines.extend([
                "## 参数敏感度",
                "",
            ])
            sorted_sens = sorted(result.sensitivity.items(), key=lambda x: abs(x[1]), reverse=True)
            for param, sens in sorted_sens:
                lines.append(f"- **{param}**: {sens:.4f}")
            lines.append("")
        
        if result.optimal_point:
            lines.extend([
                "## 最优点",
                "",
                "**参数值**:",
            ])
            for k, v in result.optimal_point.param_values.items():
                lines.append(f"- {k}: {v}")
            lines.append("")
            lines.append("**性能指标**:")
            for k, v in result.optimal_point.metrics.items():
                lines.append(f"- {k}: {v}")
            lines.append("")
        
        if result.feasible_region:
            lines.extend([
                "## 可行区域",
                "",
            ])
            for param, (low, high) in result.feasible_region.items():
                lines.append(f"- **{param}**: [{low}, {high}]")
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
    
    def _generate_sweep_points(
        self,
        config: NestedSweepConfig,
    ) -> List[Dict[str, float]]:
        """生成所有扫描点组合"""
        if not config.params:
            return [{}]
        
        # 获取每个参数的扫描值
        param_values_list = []
        for param in config.params:
            values = param.get_sweep_values()
            param_values_list.append((param.key, values))
        
        # 生成笛卡尔积
        from itertools import product
        
        keys = [k for k, _ in param_values_list]
        value_lists = [v for _, v in param_values_list]
        
        points = []
        for combo in product(*value_lists):
            points.append(dict(zip(keys, combo)))
        
        return points
    
    def _run_single_point(
        self,
        circuit_file: str,
        analysis_config: Optional[Dict[str, Any]],
        param_values: Dict[str, float],
        point_index: int,
        constraints: Optional[Dict[str, Dict[str, float]]],
    ) -> SweepPointResult:
        """执行单个扫描点仿真"""
        # 构建本次仿真配置
        config = dict(analysis_config) if analysis_config else {}
        config["sweep_params"] = param_values
        
        # 执行仿真
        sim_result = self._executor.execute(circuit_file, config)
        
        # 提取指标
        metrics = self._extract_metrics(sim_result)
        
        # 检查约束
        passed = True
        if constraints and sim_result.success:
            passed = self._check_constraints(metrics, constraints)
        
        return SweepPointResult(
            point_index=point_index,
            param_values=param_values,
            simulation_result=sim_result,
            metrics=metrics,
            passed=passed and sim_result.success,
        )
    
    def _extract_metrics(self, sim_result: SimulationResult) -> Dict[str, Any]:
        """从仿真结果中提取性能指标"""
        if not sim_result.success:
            return {}
        
        metrics = {}
        if sim_result.metrics:
            metrics.update(sim_result.metrics)
        
        return metrics
    
    def _check_constraints(
        self,
        metrics: Dict[str, Any],
        constraints: Dict[str, Dict[str, float]],
    ) -> bool:
        """检查是否满足约束"""
        for metric_name, spec in constraints.items():
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
    
    def _calculate_sensitivity(
        self,
        result: SweepAnalysisResult,
    ) -> Dict[str, float]:
        """
        计算参数敏感度
        
        使用简化方法：计算每个参数变化对主要指标的影响
        """
        sensitivity = {}
        
        if not result.points or len(result.sweep_config.params) == 0:
            return sensitivity
        
        # 收集所有指标名
        metric_names = set()
        for point in result.points:
            if point.simulation_result and point.simulation_result.success:
                metric_names.update(point.metrics.keys())
        
        if not metric_names:
            return sensitivity
        
        # 取第一个数值指标作为主要指标
        primary_metric = None
        for name in metric_names:
            for point in result.points:
                if name in point.metrics and isinstance(point.metrics[name], (int, float)):
                    primary_metric = name
                    break
            if primary_metric:
                break
        
        if not primary_metric:
            return sensitivity
        
        # 对每个参数计算敏感度
        for param in result.sweep_config.params:
            param_key = param.key
            values = param.get_sweep_values()
            
            if len(values) < 2:
                continue
            
            # 收集该参数不同值对应的指标
            param_metrics = []
            for val in values:
                matching_points = [
                    p for p in result.points
                    if p.param_values.get(param_key) == val
                    and p.simulation_result and p.simulation_result.success
                    and primary_metric in p.metrics
                ]
                if matching_points:
                    avg_metric = sum(p.metrics[primary_metric] for p in matching_points) / len(matching_points)
                    param_metrics.append((val, avg_metric))
            
            if len(param_metrics) >= 2:
                # 计算归一化敏感度
                param_range = max(v for v, _ in param_metrics) - min(v for v, _ in param_metrics)
                metric_range = max(m for _, m in param_metrics) - min(m for _, m in param_metrics)
                
                if param_range > 0 and metric_range > 0:
                    # 敏感度 = 指标变化率 / 参数变化率
                    sensitivity[param_key] = metric_range / param_range
        
        return sensitivity
    
    def _identify_feasible_region(
        self,
        result: SweepAnalysisResult,
    ) -> Dict[str, Tuple[float, float]]:
        """识别可行区域边界"""
        feasible = {}
        
        for param in result.sweep_config.params:
            param_key = param.key
            
            # 收集通过约束的点的参数值
            feasible_values = [
                p.param_values[param_key]
                for p in result.points
                if p.passed and param_key in p.param_values
            ]
            
            if feasible_values:
                feasible[param_key] = (min(feasible_values), max(feasible_values))
        
        return feasible
    
    def _publish_point_complete_event(
        self,
        point_result: SweepPointResult,
        point_index: int,
        total_points: int,
    ) -> None:
        """发布扫描点完成事件"""
        bus = self._get_event_bus()
        if bus:
            from shared.event_types import EVENT_SWEEP_POINT_COMPLETE
            
            # 获取第一个参数名和值
            param_name = ""
            param_value = 0.0
            if point_result.param_values:
                param_name = list(point_result.param_values.keys())[0]
                param_value = point_result.param_values[param_name]
            
            bus.publish(EVENT_SWEEP_POINT_COMPLETE, {
                "param_name": param_name,
                "param_value": param_value,
                "point_index": point_index,
                "total_points": total_points,
                "result_path": "",
                "metrics": point_result.metrics,
            })


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ParametricSweepAnalyzer",
    "SweepParameter",
    "SweepType",
    "NestedSweepConfig",
    "SweepPointResult",
    "SweepAnalysisResult",
    "MAX_NESTED_DEPTH",
    "SWEEP_POINTS_WARNING_THRESHOLD",
]
