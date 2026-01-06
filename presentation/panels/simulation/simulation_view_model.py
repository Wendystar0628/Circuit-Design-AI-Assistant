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
- 将 MetricResult 转换为 DisplayMetric（UI 友好格式）
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
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from presentation.core.base_view_model import BaseViewModel
from domain.simulation.models.simulation_result import SimulationResult
from domain.simulation.metrics.metric_result import MetricResult, MetricCategory
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


@dataclass
class TuningParameter:
    """
    可调参数数据结构
    
    用于快速调参面板显示
    """
    
    name: str
    """参数名称"""
    
    current_value: float
    """当前值"""
    
    min_value: float
    """最小值"""
    
    max_value: float
    """最大值"""
    
    step: float
    """步进值"""
    
    unit: str
    """单位"""
    
    source_file: str
    """来源文件路径"""
    
    source_line: int
    """来源行号"""


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
        self._chart_paths: List[str] = []
        self._overall_score: float = 0.0
        self._simulation_status: SimulationStatus = SimulationStatus.IDLE
        self._progress: float = 0.0
        self._error_message: str = ""
        self._tuning_parameters: List[TuningParameter] = []
        
        # 版本校验字段
        self._current_result_id: Optional[str] = None
        self._current_result_timestamp: Optional[str] = None
        
        # 历史指标（用于计算趋势）
        self._previous_metrics: Dict[str, float] = {}
        
        # 服务引用（延迟获取）
        self._simulation_service = None
        self._metrics_extractor = None
    
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
    def chart_paths(self) -> List[str]:
        """图表文件路径列表"""
        return self._chart_paths
    
    @property
    def overall_score(self) -> float:
        """综合评分（0-100）"""
        return self._overall_score
    
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
    
    @property
    def tuning_parameters(self) -> List[TuningParameter]:
        """可调参数列表"""
        return self._tuning_parameters
    
    # ============================================================
    # 延迟获取服务
    # ============================================================
    
    @property
    def simulation_service(self):
        """延迟获取仿真服务"""
        if self._simulation_service is None:
            try:
                from domain.services.simulation_service import SimulationService
                self._simulation_service = SimulationService()
            except ImportError:
                self._logger.warning("SimulationService not available")
        return self._simulation_service
    
    @property
    def metrics_extractor(self):
        """延迟获取指标提取器"""
        if self._metrics_extractor is None:
            try:
                from domain.simulation.metrics.metrics_extractor import metrics_extractor
                self._metrics_extractor = metrics_extractor
            except ImportError:
                self._logger.warning("MetricsExtractor not available")
        return self._metrics_extractor
    
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
        
        # 更新版本校验字段
        self._current_result_id = getattr(result, 'id', None)
        self._current_result_timestamp = getattr(result, 'timestamp', None)
        
        if result.success and result.data is not None:
            # 优先使用已有的 metrics 数据
            if result.metrics:
                self._metrics_list = self._load_metrics_from_dict(result.metrics)
            elif self.metrics_extractor:
                # 从仿真数据中提取指标
                raw_metrics = self.metrics_extractor.extract_all_metrics(result.data)
                self._metrics_list = [
                    self.format_metric(m) for m in raw_metrics.values()
                ]
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
            "simulation_status": self._simulation_status,
            "error_message": self._error_message,
        })
    
    def check_for_updates(self, project_root: str) -> bool:
        """
        检查是否有更新的仿真结果
        
        Args:
            project_root: 项目根目录
            
        Returns:
            bool: 是否有更新
        """
        if self.simulation_service is None:
            return False
        
        try:
            load_result = self.simulation_service.get_latest_sim_result(project_root)
            if not load_result.success or load_result.data is None:
                return False
            
            latest_result = load_result.data
            latest_timestamp = getattr(latest_result, 'timestamp', None)
            
            # 比较时间戳
            if latest_timestamp and self._current_result_timestamp:
                return latest_timestamp > self._current_result_timestamp
            
            # 如果没有当前结果，则有更新
            if self._current_result is None:
                return True
            
            return False
            
        except Exception as e:
            self._logger.warning(f"Failed to check for updates: {e}")
            return False
    
    def format_metric(self, metric: MetricResult) -> DisplayMetric:
        """
        将原始指标转换为 UI 友好的 DisplayMetric
        
        Args:
            metric: 原始指标结果
            
        Returns:
            DisplayMetric: UI 友好格式的指标
        """
        # 计算趋势
        trend = self._calculate_trend(metric.name, metric.raw_value)
        
        # 格式化目标值描述
        target_desc = self._format_target_description(metric)
        
        # 更新历史记录
        if metric.raw_value is not None:
            self._previous_metrics[metric.name] = metric.raw_value
        
        return DisplayMetric(
            name=metric.name,
            display_name=metric.display_name,
            value=metric.formatted_value,
            unit=metric.unit,
            target=target_desc,
            is_met=metric.is_met,
            trend=trend,
            category=metric.category.value,
            raw_value=metric.raw_value,
            confidence=metric.confidence,
            error_message=metric.error_message,
        )
    
    def _load_metrics_from_dict(self, metrics_dict: Dict[str, Any]) -> List[DisplayMetric]:
        """
        从字典格式的 metrics 数据创建 DisplayMetric 列表
        
        支持两种格式：
        1. 简单格式：{"gain": "20.5 dB", "bandwidth": "10 MHz"}
        2. 完整格式：{"gain": {"value": 20.5, "unit": "dB", "target": 20.0, ...}}
        
        Args:
            metrics_dict: 指标字典
            
        Returns:
            List[DisplayMetric]: DisplayMetric 列表
        """
        display_metrics = []
        
        for name, data in metrics_dict.items():
            if isinstance(data, dict):
                # 完整格式：从字典创建 MetricResult 然后转换
                try:
                    metric = MetricResult.from_dict(data)
                    display_metrics.append(self.format_metric(metric))
                except Exception as e:
                    self._logger.warning(f"Failed to parse metric {name}: {e}")
                    # 尝试简单解析
                    display_metrics.append(self._create_simple_display_metric(
                        name, data.get("value"), data.get("unit", "")
                    ))
            else:
                # 简单格式：字符串值
                display_metrics.append(self._create_simple_display_metric(name, data))
        
        return display_metrics
    
    def _create_simple_display_metric(
        self,
        name: str,
        value: Any,
        unit: str = ""
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
        
        # 生成显示名称（将下划线转为空格，首字母大写）
        display_name = name.replace("_", " ").title()
        
        # 推断类别
        category = self._infer_category(name)
        
        return DisplayMetric(
            name=name,
            display_name=display_name,
            value=formatted_value,
            unit=unit,
            target="",
            is_met=None,
            trend="unknown",
            category=category,
            raw_value=raw_value,
            confidence=1.0,
            error_message=None,
        )
    
    def _infer_category(self, name: str) -> str:
        """
        根据指标名称推断类别
        
        Args:
            name: 指标名称
            
        Returns:
            str: 类别名称
        """
        name_lower = name.lower()
        
        if any(kw in name_lower for kw in ["gain", "bandwidth", "phase", "margin", "gbw"]):
            return "amplifier"
        elif any(kw in name_lower for kw in ["noise", "snr", "nf"]):
            return "noise"
        elif any(kw in name_lower for kw in ["thd", "distortion", "imd", "sfdr"]):
            return "distortion"
        elif any(kw in name_lower for kw in ["power", "current", "efficiency", "consumption"]):
            return "power"
        elif any(kw in name_lower for kw in ["rise", "fall", "slew", "settling", "overshoot"]):
            return "transient"
        else:
            return "general"

    def _calculate_trend(
        self,
        metric_name: str,
        current_value: Optional[float]
    ) -> str:
        """
        计算指标趋势
        
        Args:
            metric_name: 指标名称
            current_value: 当前值
            
        Returns:
            str: 趋势（"up", "down", "stable", "unknown"）
        """
        if current_value is None:
            return "unknown"
        
        previous_value = self._previous_metrics.get(metric_name)
        if previous_value is None:
            return "unknown"
        
        # 计算变化百分比
        if previous_value == 0:
            if current_value > 0:
                return "up"
            elif current_value < 0:
                return "down"
            return "stable"
        
        change_percent = (current_value - previous_value) / abs(previous_value) * 100
        
        if change_percent > 1.0:  # 上升超过 1%
            return "up"
        elif change_percent < -1.0:  # 下降超过 1%
            return "down"
        return "stable"
    
    def _format_target_description(self, metric: MetricResult) -> str:
        """
        格式化目标值描述
        
        Args:
            metric: 指标结果
            
        Returns:
            str: 目标值描述（如 "≥ 20 dB"）
        """
        if metric.target is None:
            return ""
        
        target_str = self._format_value_with_unit(metric.target, metric.unit)
        
        if metric.target_type == "min":
            return f"≥ {target_str}"
        elif metric.target_type == "max":
            return f"≤ {target_str}"
        elif metric.target_type == "range":
            if metric.target_max is not None:
                max_str = self._format_value_with_unit(metric.target_max, metric.unit)
                return f"{target_str} ~ {max_str}"
            return f"≥ {target_str}"
        elif metric.target_type == "exact":
            return f"= {target_str}"
        
        return f"≥ {target_str}"
    
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
        """计算综合评分"""
        if not self._metrics_list:
            self._overall_score = 0.0
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
            self._overall_score = (met_count / total_with_target) * 100
        else:
            # 无目标时，根据有效指标数量给分
            valid_count = sum(
                1 for m in self._metrics_list
                if m.error_message is None
            )
            if self._metrics_list:
                self._overall_score = (valid_count / len(self._metrics_list)) * 100
            else:
                self._overall_score = 0.0

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
            file_path: 电路文件路径（可选，None 时自动检测）
            project_root: 项目根目录
            analysis_config: 仿真配置
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
            if file_path and project_root:
                result = self.simulation_service.run_simulation(
                    file_path=file_path,
                    analysis_config=analysis_config,
                    project_root=project_root,
                )
            elif project_root:
                result = self.simulation_service.run_with_auto_detect(
                    project_path=project_root,
                    analysis_config=analysis_config,
                )
            else:
                self._logger.error("No project root specified")
                self._set_status(SimulationStatus.ERROR)
                self._error_message = "未指定项目路径"
                self.notify_property_changed("error_message", self._error_message)
                return
            
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
            
            # 加载最后一个成功的结果
            for analysis_type, result in reversed(list(results.items())):
                if result.success:
                    self.load_result(result)
                    break
            else:
                # 所有分析都失败
                if results:
                    first_result = next(iter(results.values()))
                    self.load_result(first_result)
                    
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
    # 数据导出方法
    # ============================================================
    
    def export_result(
        self,
        format: str,
        path: str,
        signals: Optional[List[str]] = None,
    ) -> bool:
        """
        导出仿真结果
        
        Args:
            format: 导出格式（"csv", "json", "mat"）
            path: 导出文件路径
            signals: 要导出的信号列表（None 表示全部）
            
        Returns:
            bool: 是否导出成功
        """
        if self._current_result is None or self._current_result.data is None:
            self._logger.warning("No simulation result to export")
            return False
        
        try:
            data = self._current_result.data
            
            if format == "csv":
                return self._export_csv(path, data, signals)
            elif format == "json":
                return self._export_json(path, data, signals)
            elif format == "mat":
                return self._export_mat(path, data, signals)
            else:
                self._logger.error(f"Unsupported export format: {format}")
                return False
                
        except Exception as e:
            self._logger.exception(f"Export failed: {e}")
            return False
    
    def _export_csv(
        self,
        path: str,
        data,
        signals: Optional[List[str]],
    ) -> bool:
        """导出为 CSV 格式"""
        import csv
        
        # 确定 X 轴数据
        x_data = data.time if data.time is not None else data.frequency
        x_name = "time" if data.time is not None else "frequency"
        
        if x_data is None:
            self._logger.error("No x-axis data available")
            return False
        
        # 确定要导出的信号
        signal_names = signals or list(data.signals.keys())
        
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            
            # 写入表头
            header = [x_name] + signal_names
            writer.writerow(header)
            
            # 写入数据
            for i, x_val in enumerate(x_data):
                row = [x_val]
                for sig_name in signal_names:
                    sig_data = data.signals.get(sig_name)
                    if sig_data is not None and i < len(sig_data):
                        row.append(sig_data[i])
                    else:
                        row.append("")
                writer.writerow(row)
        
        self._logger.info(f"Exported to CSV: {path}")
        return True
    
    def _export_json(
        self,
        path: str,
        data,
        signals: Optional[List[str]],
    ) -> bool:
        """导出为 JSON 格式"""
        import json
        
        export_data = {
            "time": data.time.tolist() if data.time is not None else None,
            "frequency": data.frequency.tolist() if data.frequency is not None else None,
            "signals": {},
        }
        
        signal_names = signals or list(data.signals.keys())
        for sig_name in signal_names:
            sig_data = data.signals.get(sig_name)
            if sig_data is not None:
                export_data["signals"][sig_name] = sig_data.tolist()
        
        with open(path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2)
        
        self._logger.info(f"Exported to JSON: {path}")
        return True
    
    def _export_mat(
        self,
        path: str,
        data,
        signals: Optional[List[str]],
    ) -> bool:
        """导出为 MATLAB .mat 格式"""
        try:
            from scipy.io import savemat
        except ImportError:
            self._logger.error("scipy not available for .mat export")
            return False
        
        export_data = {}
        
        if data.time is not None:
            export_data["time"] = data.time
        if data.frequency is not None:
            export_data["frequency"] = data.frequency
        
        signal_names = signals or list(data.signals.keys())
        for sig_name in signal_names:
            sig_data = data.signals.get(sig_name)
            if sig_data is not None:
                # MATLAB 变量名不能包含括号
                safe_name = sig_name.replace("(", "_").replace(")", "")
                export_data[safe_name] = sig_data
        
        savemat(path, export_data)
        self._logger.info(f"Exported to MAT: {path}")
        return True
    
    # ============================================================
    # 调参方法
    # ============================================================
    
    def update_tuning_parameter(self, name: str, value: float):
        """
        更新调参参数值
        
        Args:
            name: 参数名称
            value: 新值
        """
        for param in self._tuning_parameters:
            if param.name == name:
                param.current_value = value
                self.notify_property_changed("tuning_parameters", self._tuning_parameters)
                break
    
    def apply_tuning(self, project_root: str):
        """
        应用调参并重新仿真
        
        Args:
            project_root: 项目根目录
        """
        # TODO: 实现参数写入电路文件的逻辑
        # 这需要与 CircuitAnalyzer 配合，修改 .param 语句
        self._logger.info("Applying tuning parameters...")
        
        # 重新仿真
        if self._current_result:
            self.request_simulation(
                file_path=self._current_result.file_path,
                project_root=project_root,
            )
    
    def reset_tuning(self):
        """重置调参参数为原始值"""
        # TODO: 从电路文件重新读取原始参数值
        self._logger.info("Resetting tuning parameters...")
    
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
        self._chart_paths = []
        self._overall_score = 0.0
        self._simulation_status = SimulationStatus.IDLE
        self._progress = 0.0
        self._error_message = ""
        self._tuning_parameters = []
        
        # 重置版本校验字段
        self._current_result_id = None
        self._current_result_timestamp = None
        
        self.notify_properties_changed({
            "current_result": None,
            "metrics_list": [],
            "chart_paths": [],
            "overall_score": 0.0,
            "simulation_status": SimulationStatus.IDLE,
            "progress": 0.0,
            "error_message": "",
            "tuning_parameters": [],
        })


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SimulationViewModel",
    "SimulationStatus",
    "DisplayMetric",
    "TuningParameter",
]
