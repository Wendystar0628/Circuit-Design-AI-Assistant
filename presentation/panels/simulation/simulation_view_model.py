# Simulation ViewModel
"""
仿真面板 ViewModel

职责：
- 作为 UI 与仿真服务之间的中间层
- 隔离 simulation_tab 与 SimulationService 的直接依赖
- 订阅仿真事件并转换为 UI 友好格式
- 管理仿真状态和进度

设计原则：
- 继承 BaseViewModel，使用统一的事件订阅和属性通知机制
- 将 .MEASURE 结果转换为 DisplayMetric（UI 友好格式）
- 通过 property_changed 信号通知 UI 更新

被调用方：
- simulation_tab.py

使用示例：
    view_model = SimulationViewModel()
    view_model.property_changed.connect(on_property_changed)
    view_model.initialize()
    
    # 请求仿真
    view_model.request_simulation()
    
    # 响应属性变更
    def on_property_changed(name, value):
        if name == "metrics_list":
            update_metrics_display(value)
        elif name == "simulation_status":
            update_status_indicator(value)
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from domain.simulation.measure.measure_metadata import measure_metadata_resolver
from domain.simulation.measure.measure_result import MeasureResult, MeasureStatus
from presentation.core.base_view_model import BaseViewModel
from domain.simulation.models.simulation_result import SimulationResult
from shared.event_types import (
    EVENT_SIM_STARTED,
    EVENT_SIM_PROGRESS,
    EVENT_SIM_COMPLETE,
    EVENT_SIM_ERROR,
    EVENT_SIM_CANCELLED,
    EVENT_ALL_ANALYSES_COMPLETE,
)


class SimulationStatus(Enum):
    """仿真状态枚举"""
    
    IDLE = "idle"
    """空闲状态，等待用户操作"""
    
    RUNNING = "running"
    """仿真运行中"""
    
    COMPLETE = "complete"
    """仿真完成"""
    
    ERROR = "error"
    """仿真出错"""
    
    CANCELLED = "cancelled"
    """仿真已取消"""


@dataclass
class DisplayMetric:
    """
    UI 友好的指标显示格式
    
    从 MetricResult 转换而来，专为 UI 显示优化
    """
    
    name: str
    """指标标识名（英文）"""
    
    display_name: str
    """指标显示名（已国际化）"""
    
    value: str
    """格式化后的数值字符串（如 "20.5 dB"）"""
    
    unit: str
    """单位"""
    
    target: str
    """目标值描述（如 "≥ 20 dB"）"""
    
    is_met: Optional[bool]
    """是否达标（None 表示无目标）"""
    
    trend: str
    """趋势（"up", "down", "stable", "unknown"）"""
    
    category: str
    """指标类别（"gain", "bandwidth", "noise" 等）"""
    
    raw_value: Optional[float] = None
    """原始数值（用于排序和计算）"""
    
    confidence: float = 1.0
    """置信度（0-1）"""
    
    error_message: Optional[str] = None
    """错误信息（若计算失败）"""


class SimulationViewModel(BaseViewModel):
    """
    仿真面板 ViewModel
    
    管理仿真状态、结果和指标的展示逻辑。
    订阅仿真事件，将数据转换为 UI 友好格式后通知 View 更新。
    """
    
    def __init__(self):
        super().__init__()
        
        self._logger = logging.getLogger(__name__)
        
        # 核心状态
        self._current_result: Optional[SimulationResult] = None
        self._metrics_list: List[DisplayMetric] = []
        self._overall_score: float = 0.0
        self._simulation_status: SimulationStatus = SimulationStatus.IDLE
        self._progress: float = 0.0
        self._error_message: str = ""
        self._has_goals: bool = False  # 是否有设计目标

        # 服务引用（延迟获取）
        self._simulation_service = None
    
    # ============================================================
    # 属性访问器
    # ============================================================
    
    @property
    def current_result(self) -> Optional[SimulationResult]:
        """当前仿真结果"""
        return self._current_result
    
    @property
    def metrics_list(self) -> List[DisplayMetric]:
        """格式化后的指标列表"""
        return self._metrics_list
    
    @property
    def overall_score(self) -> float:
        """综合评分（0-100，-1.0 表示无目标模式无评分）"""
        return self._overall_score
    
    @property
    def has_goals(self) -> bool:
        """是否有设计目标"""
        return self._has_goals
    
    @property
    def simulation_status(self) -> SimulationStatus:
        """仿真状态"""
        return self._simulation_status
    
    @property
    def progress(self) -> float:
        """仿真进度（0-100）"""
        return self._progress
    
    @property
    def error_message(self) -> str:
        """错误信息"""
        return self._error_message
    
    # ============================================================
    # 延迟获取服务
    # ============================================================
    
    @property
    def simulation_service(self):
        """延迟获取仿真服务"""
        if self._simulation_service is None:
            from domain.services.simulation_service import SimulationService
            self._simulation_service = SimulationService()
        return self._simulation_service
    
    # ============================================================
    # 生命周期
    # ============================================================
    
    def initialize(self):
        """初始化 ViewModel，订阅仿真事件"""
        super().initialize()
        
        # 订阅仿真事件
        self.subscribe(EVENT_SIM_STARTED, self._on_simulation_started)
        self.subscribe(EVENT_SIM_PROGRESS, self._on_simulation_progress)
        self.subscribe(EVENT_SIM_COMPLETE, self._on_simulation_complete)
        self.subscribe(EVENT_SIM_ERROR, self._on_simulation_error)
        self.subscribe(EVENT_SIM_CANCELLED, self._on_simulation_cancelled)
        self.subscribe(EVENT_ALL_ANALYSES_COMPLETE, self._on_all_analyses_complete)
        
        self._logger.info("SimulationViewModel initialized")

    # ============================================================
    # 事件处理
    # ============================================================
    
    def _on_simulation_started(self, event_data: Dict[str, Any]):
        """处理仿真开始事件"""
        self._set_status(SimulationStatus.RUNNING)
        self._progress = 0.0
        self._error_message = ""
        
        self.notify_property_changed("simulation_status", self._simulation_status)
        self.notify_property_changed("progress", self._progress)
        self.notify_property_changed("error_message", self._error_message)
        
        self._logger.info(
            f"Simulation started: {event_data.get('circuit_file', 'unknown')}"
        )
    
    def _on_simulation_progress(self, event_data: Dict[str, Any]):
        """处理仿真进度事件"""
        progress = event_data.get("progress", 0.0)
        self._progress = progress * 100  # 转换为百分比
        
        self.notify_property_changed("progress", self._progress)
    
    def _on_simulation_complete(self, event_data: Dict[str, Any]):
        """处理仿真完成事件"""
        self._set_status(SimulationStatus.COMPLETE)
        self._progress = 100.0
        
        self.notify_property_changed("simulation_status", self._simulation_status)
        self.notify_property_changed("progress", self._progress)
        
        self._logger.info("Simulation complete")
    
    def _on_simulation_error(self, event_data: Dict[str, Any]):
        """处理仿真错误事件"""
        self._set_status(SimulationStatus.ERROR)
        self._error_message = event_data.get("error_message", "Unknown error")
        
        self.notify_property_changed("simulation_status", self._simulation_status)
        self.notify_property_changed("error_message", self._error_message)
        
        self._logger.error(f"Simulation error: {self._error_message}")
    
    def _on_simulation_cancelled(self, event_data: Dict[str, Any]):
        """处理仿真取消事件"""
        self._set_status(SimulationStatus.CANCELLED)
        
        self.notify_property_changed("simulation_status", self._simulation_status)
        
        self._logger.info("Simulation cancelled")
    
    def _on_all_analyses_complete(self, event_data: Dict[str, Any]):
        """处理所有分析完成事件"""
        self._set_status(SimulationStatus.COMPLETE)
        self._progress = 100.0
        
        # 计算综合评分
        success_count = event_data.get("success_count", 0)
        total_count = event_data.get("total_count", 1)
        if total_count > 0:
            self._overall_score = (success_count / total_count) * 100
        
        self.notify_property_changed("simulation_status", self._simulation_status)
        self.notify_property_changed("progress", self._progress)
        self.notify_property_changed("overall_score", self._overall_score)
        
        self._logger.info(
            f"All analyses complete: {success_count}/{total_count} succeeded"
        )
    
    def _set_status(self, status: SimulationStatus):
        """设置仿真状态"""
        self._simulation_status = status
    
    # ============================================================
    # 核心方法
    # ============================================================
    
    def load_result(self, result: SimulationResult):
        """
        加载仿真结果并转换为显示格式
        
        Args:
            result: 仿真结果对象
        """
        self._current_result = result
        
        if result.success and result.data is not None:
            if result.measurements:
                self._metrics_list = self._load_metrics_from_measurements(result.measurements)
            else:
                self._metrics_list = []
            
            # 计算综合评分
            self._calculate_overall_score()
            
            # 更新状态
            self._set_status(SimulationStatus.COMPLETE)
            self._error_message = ""
        else:
            # 仿真失败
            self._metrics_list = []
            self._overall_score = 0.0
            self._set_status(SimulationStatus.ERROR)
            
            if result.error:
                if hasattr(result.error, "message"):
                    self._error_message = result.error.message
                else:
                    self._error_message = str(result.error)
        
        # 通知 UI 更新
        self.notify_properties_changed({
            "current_result": self._current_result,
            "metrics_list": self._metrics_list,
            "overall_score": self._overall_score,
            "has_goals": self._has_goals,
            "simulation_status": self._simulation_status,
            "error_message": self._error_message,
        })
    
    def _load_metrics_from_measurements(self, measurements: List[Any]) -> List[DisplayMetric]:
        """
        从 .MEASURE 结果创建 DisplayMetric 列表
        
        Args:
            measurements: MeasureResult 列表
            
        Returns:
            List[DisplayMetric]: DisplayMetric 列表
        """
        display_metrics = []
        
        for measure in measurements:
            if not isinstance(measure, MeasureResult):
                continue
            name = measure.name
            value = measure.value
            unit = measure.unit
            display_name = measure.display_name
            category = measure.category
            description = measure.description
            statement = measure.statement
            is_valid = measure.status == MeasureStatus.OK and value is not None
            
            # 跳过无效的测量
            if not is_valid:
                continue
            
            metadata = measure_metadata_resolver.resolve(
                name,
                statement=statement,
                description=description,
                fallback_unit=unit,
            )

            display_metrics.append(self._create_display_metric(
                name,
                value,
                unit=metadata.unit,
                display_name=display_name or metadata.display_name,
                category=category or metadata.category,
            ))
        
        return display_metrics
    
    def _create_display_metric(
        self,
        name: str,
        value: Any,
        unit: str = "",
        display_name: str = "",
        category: str = "",
    ) -> DisplayMetric:
        """
        从简单值创建 DisplayMetric
        
        Args:
            name: 指标名称
            value: 指标值（可以是数字或字符串）
            unit: 单位
            
        Returns:
            DisplayMetric: 显示指标
        """
        # 解析值和单位
        raw_value = None
        formatted_value = str(value) if value is not None else "N/A"
        
        if isinstance(value, (int, float)):
            raw_value = float(value)
            formatted_value = self._format_value_with_unit(raw_value, unit)
        elif isinstance(value, str):
            # 尝试从字符串中提取数值
            import re
            match = re.match(r'^([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*(.*)$', value.strip())
            if match:
                try:
                    raw_value = float(match.group(1))
                    unit = match.group(2) or unit
                    formatted_value = value
                except ValueError:
                    pass
        
        metadata = measure_metadata_resolver.resolve(
            name,
            description=display_name,
            fallback_unit=unit,
        )
        
        return DisplayMetric(
            name=name,
            display_name=display_name or metadata.display_name,
            value=formatted_value,
            unit=metadata.unit,
            target="",
            is_met=None,
            trend="unknown",
            category=category or metadata.category,
            raw_value=raw_value,
            confidence=1.0,
            error_message=None,
        )
    
    def _format_value_with_unit(self, value: float, unit: str) -> str:
        """格式化数值（带单位）"""
        abs_value = abs(value)
        
        if abs_value == 0:
            formatted = "0"
        elif abs_value >= 1e9:
            formatted = f"{value / 1e9:.2f}G"
        elif abs_value >= 1e6:
            formatted = f"{value / 1e6:.2f}M"
        elif abs_value >= 1e3:
            formatted = f"{value / 1e3:.2f}k"
        elif abs_value >= 1:
            formatted = f"{value:.2f}"
        elif abs_value >= 1e-3:
            formatted = f"{value * 1e3:.2f}m"
        elif abs_value >= 1e-6:
            formatted = f"{value * 1e6:.2f}μ"
        elif abs_value >= 1e-9:
            formatted = f"{value * 1e9:.2f}n"
        else:
            formatted = f"{value:.2e}"
        
        if unit:
            return f"{formatted} {unit}"
        return formatted
    
    def _calculate_overall_score(self):
        """
        计算综合评分
        
        有目标模式：返回达标指标比例（0-100）
        无目标模式：返回 -1.0 表示无评分
        """
        if not self._metrics_list:
            self._overall_score = 0.0
            self._has_goals = False
            return
        
        # 统计达标指标数量
        met_count = sum(
            1 for m in self._metrics_list
            if m.is_met is True
        )
        total_with_target = sum(
            1 for m in self._metrics_list
            if m.is_met is not None
        )
        
        if total_with_target > 0:
            # 有目标模式：计算达标比例
            self._overall_score = (met_count / total_with_target) * 100
            self._has_goals = True
        else:
            # 无目标模式：返回 -1.0 表示无评分
            self._has_goals = False
            self._overall_score = -1.0

    # ============================================================
    # 仿真控制方法
    # ============================================================
    
    def request_simulation(
        self,
        file_path: Optional[str] = None,
        project_root: Optional[str] = None,
        analysis_config: Optional[Dict[str, Any]] = None,
    ):
        """
        请求执行仿真
        
        Args:
            file_path: 电路文件路径
            project_root: 项目根目录
            analysis_config: 仿真配置
        """
        if self.simulation_service is None:
            self._logger.error("SimulationService not available")
            self._set_status(SimulationStatus.ERROR)
            self._error_message = "仿真服务不可用"
            self.notify_property_changed("error_message", self._error_message)
            return
        
        if not file_path or not project_root:
            self._logger.error("file_path and project_root are required")
            self._set_status(SimulationStatus.ERROR)
            self._error_message = "未指定电路文件或项目路径"
            self.notify_property_changed("error_message", self._error_message)
            return
        
        # 重置状态
        self._set_status(SimulationStatus.RUNNING)
        self._progress = 0.0
        self._error_message = ""
        
        self.notify_properties_changed({
            "simulation_status": self._simulation_status,
            "progress": self._progress,
            "error_message": self._error_message,
        })
        
        try:
            result = self.simulation_service.run_simulation(
                file_path=file_path,
                analysis_config=analysis_config,
                project_root=project_root,
            )
            
            # 加载结果
            self.load_result(result)
            
        except Exception as e:
            self._logger.exception(f"Simulation request failed: {e}")
            self._set_status(SimulationStatus.ERROR)
            self._error_message = str(e)
            self.notify_properties_changed({
                "simulation_status": self._simulation_status,
                "error_message": self._error_message,
            })
    
    def request_batch_simulation(self, project_root: str, file_path: str):
        """
        请求执行批量仿真（执行用户选中的所有分析类型）
        
        Args:
            project_root: 项目根目录
            file_path: 电路文件路径
        """
        if self.simulation_service is None:
            self._logger.error("SimulationService not available")
            self._set_status(SimulationStatus.ERROR)
            self._error_message = "仿真服务不可用"
            self.notify_property_changed("error_message", self._error_message)
            return
        
        # 重置状态
        self._set_status(SimulationStatus.RUNNING)
        self._progress = 0.0
        self._error_message = ""
        
        self.notify_properties_changed({
            "simulation_status": self._simulation_status,
            "progress": self._progress,
            "error_message": self._error_message,
        })
        
        try:
            results = self.simulation_service.run_selected_analyses(
                file_path=file_path,
                project_root=project_root,
            )
            
            # 加载最后一个成功的分析结果
            for analysis_type, result in reversed(list(results.items())):
                if hasattr(result, 'success') and result.success:
                    self.load_result(result)
                    break
            else:
                # 所有分析都失败，尝试加载第一个结果
                for analysis_type, result in results.items():
                    if hasattr(result, 'success'):
                        self.load_result(result)
                        break
                    
        except Exception as e:
            self._logger.exception(f"Batch simulation failed: {e}")
            self._set_status(SimulationStatus.ERROR)
            self._error_message = str(e)
            self.notify_properties_changed({
                "simulation_status": self._simulation_status,
                "error_message": self._error_message,
            })
    
    def cancel_simulation(self):
        """取消当前仿真"""
        if self.simulation_service is None:
            return
        
        if self._simulation_status == SimulationStatus.RUNNING:
            self.simulation_service.cancel_simulation()
            self._set_status(SimulationStatus.CANCELLED)
            self.notify_property_changed("simulation_status", self._simulation_status)

    # ============================================================
    # 辅助方法
    # ============================================================
    
    def get_metrics_by_category(self, category: str) -> List[DisplayMetric]:
        """
        按类别获取指标列表
        
        Args:
            category: 指标类别
            
        Returns:
            List[DisplayMetric]: 该类别的指标列表
        """
        return [m for m in self._metrics_list if m.category == category]
    
    def get_metric_by_name(self, name: str) -> Optional[DisplayMetric]:
        """
        按名称获取指标
        
        Args:
            name: 指标名称
            
        Returns:
            Optional[DisplayMetric]: 指标对象，若不存在则返回 None
        """
        for metric in self._metrics_list:
            if metric.name == name:
                return metric
        return None
    
    def clear(self):
        """清空所有数据"""
        self._current_result = None
        self._metrics_list = []
        self._overall_score = 0.0
        self._simulation_status = SimulationStatus.IDLE
        self._progress = 0.0
        self._error_message = ""
        
        self.notify_properties_changed({
            "current_result": None,
            "metrics_list": [],
            "overall_score": 0.0,
            "simulation_status": SimulationStatus.IDLE,
            "progress": 0.0,
            "error_message": "",
        })


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SimulationViewModel",
    "SimulationStatus",
    "DisplayMetric",
]
