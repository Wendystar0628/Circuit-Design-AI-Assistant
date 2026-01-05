# PVT Analysis - Process-Voltage-Temperature Corner Simulation
"""
PVT 角点仿真

职责：
- 执行工艺-电压-温度（Process-Voltage-Temperature）角点仿真
- 验证电路在极端条件下的性能
- 生成 PVT 分析报告

设计原则：
- 作为工具类按需实例化，无需显式初始化
- 通过修改仿真配置实现不同角点
- 与设计目标集成，检查所有角点是否满足要求

使用示例：
    from domain.simulation.analysis.pvt_analysis import PVTAnalyzer
    
    analyzer = PVTAnalyzer()
    
    # 使用默认角点执行 PVT 分析
    result = analyzer.run_pvt_corners(
        circuit_file="amplifier.cir",
        analysis_config={"analysis_type": "ac"},
    )
    
    # 检查结果
    if result.all_passed:
        print("所有角点通过")
    else:
        print(f"失败角点: {result.failed_corners}")
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from domain.simulation.executor.spice_executor import SpiceExecutor
from domain.simulation.models.simulation_result import SimulationResult


# ============================================================
# 枚举定义
# ============================================================

class ProcessCorner(Enum):
    """工艺角点枚举"""
    TYPICAL = "typical"
    FAST = "fast"
    SLOW = "slow"
    FAST_NMOS_SLOW_PMOS = "fs"
    SLOW_NMOS_FAST_PMOS = "sf"


# ============================================================
# 数据类定义
# ============================================================

@dataclass
class PVTCorner:
    """
    PVT 角点配置
    
    Attributes:
        name: 角点名称（如 "TT", "FF", "SS"）
        process: 工艺角点
        voltage_factor: 电压因子（1.0 为标称，1.1 为 +10%）
        temperature: 温度（摄氏度）
        description: 角点描述
    """
    name: str
    process: ProcessCorner
    voltage_factor: float
    temperature: float
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "name": self.name,
            "process": self.process.value,
            "voltage_factor": self.voltage_factor,
            "temperature": self.temperature,
            "description": self.description,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PVTCorner":
        """从字典反序列化"""
        return cls(
            name=data["name"],
            process=ProcessCorner(data["process"]),
            voltage_factor=data["voltage_factor"],
            temperature=data["temperature"],
            description=data.get("description", ""),
        )


@dataclass
class PVTCornerResult:
    """
    单个角点的仿真结果
    
    Attributes:
        corner: 角点配置
        simulation_result: 仿真结果
        metrics: 性能指标
        passed: 是否通过设计目标检查
        failed_goals: 未通过的设计目标列表
    """
    corner: PVTCorner
    simulation_result: SimulationResult
    metrics: Dict[str, Any] = field(default_factory=dict)
    passed: bool = True
    failed_goals: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "corner": self.corner.to_dict(),
            "simulation_result": self.simulation_result.to_dict(),
            "metrics": self.metrics,
            "passed": self.passed,
            "failed_goals": self.failed_goals,
        }


@dataclass
class PVTAnalysisResult:
    """
    PVT 分析完整结果
    
    Attributes:
        circuit_file: 电路文件路径
        analysis_type: 分析类型
        corners: 角点结果列表
        all_passed: 是否所有角点都通过
        worst_corner: 最差角点名称
        worst_metrics: 最差角点的指标
        timestamp: 分析时间戳
        duration_seconds: 总耗时
    """
    circuit_file: str
    analysis_type: str
    corners: List[PVTCornerResult] = field(default_factory=list)
    all_passed: bool = True
    worst_corner: str = ""
    worst_metrics: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    duration_seconds: float = 0.0
    
    @property
    def failed_corners(self) -> List[str]:
        """获取失败的角点名称列表"""
        return [r.corner.name for r in self.corners if not r.passed]
    
    @property
    def passed_corners(self) -> List[str]:
        """获取通过的角点名称列表"""
        return [r.corner.name for r in self.corners if r.passed]
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "circuit_file": self.circuit_file,
            "analysis_type": self.analysis_type,
            "corners": [r.to_dict() for r in self.corners],
            "all_passed": self.all_passed,
            "worst_corner": self.worst_corner,
            "worst_metrics": self.worst_metrics,
            "failed_corners": self.failed_corners,
            "passed_corners": self.passed_corners,
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
        }


# ============================================================
# 默认角点配置
# ============================================================

DEFAULT_PVT_CORNERS = [
    PVTCorner(
        name="TT",
        process=ProcessCorner.TYPICAL,
        voltage_factor=1.0,
        temperature=25.0,
        description="典型工艺、标称电压、室温",
    ),
    PVTCorner(
        name="FF",
        process=ProcessCorner.FAST,
        voltage_factor=1.1,
        temperature=-40.0,
        description="快速工艺、高电压(+10%)、低温(-40°C)",
    ),
    PVTCorner(
        name="SS",
        process=ProcessCorner.SLOW,
        voltage_factor=0.9,
        temperature=85.0,
        description="慢速工艺、低电压(-10%)、高温(85°C)",
    ),
    PVTCorner(
        name="FS",
        process=ProcessCorner.FAST_NMOS_SLOW_PMOS,
        voltage_factor=1.0,
        temperature=25.0,
        description="NMOS快/PMOS慢、标称电压、室温",
    ),
    PVTCorner(
        name="SF",
        process=ProcessCorner.SLOW_NMOS_FAST_PMOS,
        voltage_factor=1.0,
        temperature=25.0,
        description="NMOS慢/PMOS快、标称电压、室温",
    ),
]


# ============================================================
# PVTAnalyzer - PVT 角点分析器
# ============================================================

class PVTAnalyzer:
    """
    PVT 角点分析器
    
    执行工艺-电压-温度角点仿真，验证电路在极端条件下的性能。
    
    特性：
    - 支持默认 5 角点（TT/FF/SS/FS/SF）
    - 支持自定义角点配置
    - 与设计目标集成检查
    - 发布进度事件
    """
    
    def __init__(self, executor: Optional[SpiceExecutor] = None):
        """
        初始化 PVT 分析器
        
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
    
    def get_default_corners(self) -> List[PVTCorner]:
        """
        获取默认角点配置
        
        Returns:
            List[PVTCorner]: 默认角点列表
        """
        return DEFAULT_PVT_CORNERS.copy()
    
    def add_custom_corner(
        self,
        name: str,
        process: ProcessCorner,
        voltage_factor: float,
        temperature: float,
        description: str = "",
    ) -> PVTCorner:
        """
        创建自定义角点
        
        Args:
            name: 角点名称
            process: 工艺角点
            voltage_factor: 电压因子
            temperature: 温度
            description: 描述
            
        Returns:
            PVTCorner: 创建的角点配置
        """
        return PVTCorner(
            name=name,
            process=process,
            voltage_factor=voltage_factor,
            temperature=temperature,
            description=description,
        )
    
    def run_pvt_corners(
        self,
        circuit_file: str,
        analysis_config: Optional[Dict[str, Any]] = None,
        corners: Optional[List[PVTCorner]] = None,
        design_goals: Optional[Dict[str, Any]] = None,
        on_corner_complete: Optional[Callable[[PVTCornerResult, int, int], None]] = None,
    ) -> PVTAnalysisResult:
        """
        执行多角点 PVT 仿真
        
        Args:
            circuit_file: 电路文件路径
            analysis_config: 仿真配置字典
            corners: 角点列表（可选，默认使用 5 角点）
            design_goals: 设计目标字典（可选，用于检查是否满足）
            on_corner_complete: 单角点完成回调
            
        Returns:
            PVTAnalysisResult: PVT 分析结果
        """
        start_time = time.time()
        analysis_type = self._get_analysis_type(analysis_config)
        
        # 使用默认角点或自定义角点
        corners_to_run = corners if corners else self.get_default_corners()
        total_corners = len(corners_to_run)
        
        self._logger.info(f"开始 PVT 分析: {circuit_file}, {total_corners} 个角点")
        
        result = PVTAnalysisResult(
            circuit_file=circuit_file,
            analysis_type=analysis_type,
        )
        
        # 逐个执行角点仿真
        for idx, corner in enumerate(corners_to_run):
            corner_result = self._run_single_corner(
                circuit_file=circuit_file,
                analysis_config=analysis_config,
                corner=corner,
                design_goals=design_goals,
            )
            result.corners.append(corner_result)
            
            # 发布进度事件
            self._publish_corner_complete_event(
                corner=corner,
                corner_result=corner_result,
                corner_index=idx,
                total_corners=total_corners,
            )
            
            # 调用回调
            if on_corner_complete:
                on_corner_complete(corner_result, idx, total_corners)
            
            # 更新整体通过状态
            if not corner_result.passed:
                result.all_passed = False
        
        # 找出最差角点
        result.worst_corner, result.worst_metrics = self._find_worst_corner(
            result.corners,
            design_goals,
        )
        
        result.duration_seconds = time.time() - start_time
        self._logger.info(
            f"PVT 分析完成: {result.passed_corners}/{total_corners} 通过, "
            f"耗时 {result.duration_seconds:.2f}s"
        )
        
        return result
    
    def find_worst_case(
        self,
        results: List[PVTCornerResult],
        metric: str,
        minimize: bool = True,
    ) -> Optional[PVTCornerResult]:
        """
        找出指定指标的最差角点
        
        Args:
            results: 角点结果列表
            metric: 指标名称
            minimize: True 表示最小值为最差，False 表示最大值为最差
            
        Returns:
            Optional[PVTCornerResult]: 最差角点结果，若无有效数据返回 None
        """
        valid_results = [
            r for r in results
            if r.simulation_result.success and metric in r.metrics
        ]
        
        if not valid_results:
            return None
        
        if minimize:
            return min(valid_results, key=lambda r: r.metrics[metric])
        else:
            return max(valid_results, key=lambda r: r.metrics[metric])
    
    def generate_pvt_report(self, result: PVTAnalysisResult) -> str:
        """
        生成 PVT 分析报告（Markdown 格式）
        
        Args:
            result: PVT 分析结果
            
        Returns:
            str: Markdown 格式报告
        """
        lines = [
            "# PVT 角点分析报告",
            "",
            f"**电路文件**: {result.circuit_file}",
            f"**分析类型**: {result.analysis_type}",
            f"**分析时间**: {result.timestamp}",
            f"**总耗时**: {result.duration_seconds:.2f} 秒",
            "",
            "## 总体结果",
            "",
            f"- **通过角点**: {len(result.passed_corners)}/{len(result.corners)}",
            f"- **整体状态**: {'✅ 全部通过' if result.all_passed else '❌ 存在失败'}",
        ]
        
        if result.worst_corner:
            lines.extend([
                f"- **最差角点**: {result.worst_corner}",
            ])
        
        lines.extend([
            "",
            "## 各角点详情",
            "",
        ])
        
        for corner_result in result.corners:
            status = "✅" if corner_result.passed else "❌"
            corner = corner_result.corner
            lines.extend([
                f"### {status} {corner.name}",
                "",
                f"- **工艺**: {corner.process.value}",
                f"- **电压因子**: {corner.voltage_factor:.2f}",
                f"- **温度**: {corner.temperature}°C",
                f"- **描述**: {corner.description}",
                "",
            ])
            
            if corner_result.metrics:
                lines.append("**性能指标**:")
                for key, value in corner_result.metrics.items():
                    lines.append(f"- {key}: {value}")
                lines.append("")
            
            if corner_result.failed_goals:
                lines.append("**未通过的设计目标**:")
                for goal in corner_result.failed_goals:
                    lines.append(f"- {goal}")
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
    
    def _run_single_corner(
        self,
        circuit_file: str,
        analysis_config: Optional[Dict[str, Any]],
        corner: PVTCorner,
        design_goals: Optional[Dict[str, Any]],
    ) -> PVTCornerResult:
        """执行单个角点仿真"""
        self._logger.debug(f"执行角点 {corner.name}: {corner.description}")
        
        # 构建角点特定的配置
        corner_config = self._build_corner_config(analysis_config, corner)
        
        # 执行仿真
        sim_result = self._executor.execute(circuit_file, corner_config)
        
        # 提取指标
        metrics = self._extract_metrics(sim_result)
        
        # 检查设计目标
        passed, failed_goals = self._check_design_goals(metrics, design_goals)
        
        return PVTCornerResult(
            corner=corner,
            simulation_result=sim_result,
            metrics=metrics,
            passed=passed and sim_result.success,
            failed_goals=failed_goals,
        )
    
    def _build_corner_config(
        self,
        base_config: Optional[Dict[str, Any]],
        corner: PVTCorner,
    ) -> Dict[str, Any]:
        """
        构建角点特定的仿真配置
        
        通过修改温度和电压参数实现不同角点。
        工艺角点通过调整器件参数模拟（简化实现）。
        """
        config = dict(base_config) if base_config else {}
        
        # 设置温度
        config["temperature"] = corner.temperature
        
        # 设置电压因子（用于调整电源电压）
        config["voltage_factor"] = corner.voltage_factor
        
        # 设置工艺角点标识（供执行器使用）
        config["process_corner"] = corner.process.value
        
        return config
    
    def _extract_metrics(self, sim_result: SimulationResult) -> Dict[str, Any]:
        """从仿真结果中提取性能指标"""
        if not sim_result.success:
            return {}
        
        metrics = {}
        
        # 复制已有指标
        if sim_result.metrics:
            metrics.update(sim_result.metrics)
        
        # 从仿真数据中提取常用指标
        if sim_result.data and sim_result.data.signals:
            # 这里可以添加自动指标提取逻辑
            # 例如：增益、带宽、相位裕度等
            pass
        
        return metrics
    
    def _check_design_goals(
        self,
        metrics: Dict[str, Any],
        design_goals: Optional[Dict[str, Any]],
    ) -> tuple[bool, List[str]]:
        """
        检查是否满足设计目标
        
        Returns:
            tuple[bool, List[str]]: (是否通过, 失败的目标列表)
        """
        if not design_goals:
            return True, []
        
        failed_goals = []
        
        for goal_name, goal_spec in design_goals.items():
            if goal_name not in metrics:
                continue
            
            actual_value = metrics[goal_name]
            
            # 支持多种目标格式
            if isinstance(goal_spec, dict):
                min_val = goal_spec.get("min")
                max_val = goal_spec.get("max")
                target = goal_spec.get("target")
                
                if min_val is not None and actual_value < min_val:
                    failed_goals.append(f"{goal_name}: {actual_value} < {min_val} (最小值)")
                if max_val is not None and actual_value > max_val:
                    failed_goals.append(f"{goal_name}: {actual_value} > {max_val} (最大值)")
            elif isinstance(goal_spec, (int, float)):
                # 简单数值目标，检查是否达到
                if actual_value < goal_spec:
                    failed_goals.append(f"{goal_name}: {actual_value} < {goal_spec}")
        
        return len(failed_goals) == 0, failed_goals
    
    def _find_worst_corner(
        self,
        corners: List[PVTCornerResult],
        design_goals: Optional[Dict[str, Any]],
    ) -> tuple[str, Dict[str, Any]]:
        """找出最差角点"""
        if not corners:
            return "", {}
        
        # 优先返回失败的角点
        failed = [c for c in corners if not c.passed]
        if failed:
            worst = failed[0]
            return worst.corner.name, worst.metrics
        
        # 如果都通过，返回第一个（可以根据具体指标优化）
        return corners[0].corner.name, corners[0].metrics
    
    def _publish_corner_complete_event(
        self,
        corner: PVTCorner,
        corner_result: PVTCornerResult,
        corner_index: int,
        total_corners: int,
    ) -> None:
        """发布角点完成事件"""
        bus = self._get_event_bus()
        if bus:
            from shared.event_types import EVENT_PVT_CORNER_COMPLETE
            bus.publish(EVENT_PVT_CORNER_COMPLETE, {
                "corner_name": corner.name,
                "process": corner.process.value,
                "voltage": corner.voltage_factor,
                "temperature": corner.temperature,
                "result_path": "",
                "metrics": corner_result.metrics,
                "corner_index": corner_index,
                "total_corners": total_corners,
                "passed": corner_result.passed,
            })


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "PVTAnalyzer",
    "PVTCorner",
    "PVTCornerResult",
    "PVTAnalysisResult",
    "ProcessCorner",
    "DEFAULT_PVT_CORNERS",
]
