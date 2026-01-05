# AnalysisResult - Advanced Analysis Result Data Classes
"""
高级分析结果数据类

职责：
- 定义高级分析（PVT/蒙特卡洛/参数扫描/最坏情况/敏感度）的统一结果结构
- 提供分析结果的序列化和反序列化
- 支持 UI 显示和图表生成

设计原则：
- 使用 dataclass 确保类型安全
- 继承基类确保结构一致性
- 提供 numpy 数组的序列化支持
- 每个分析类型有独立的结果数据类

使用示例：
    # 创建 PVT 分析结果
    result = PVTAnalysisResult(
        analysis_type="pvt",
        timestamp=datetime.now().isoformat(),
        duration_seconds=120.5,
        success=True,
        summary="5 个角点全部通过",
        corners=[...],
        corner_results={...},
        worst_corner="SS",
        all_passed=True
    )
    
    # 序列化
    data_dict = result.to_dict()
    
    # 获取显示摘要
    summary = result.get_display_summary()
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np


# ============================================================
# AnalysisResultBase - 分析结果基类
# ============================================================

@dataclass
class AnalysisResultBase:
    """
    分析结果基类
    
    所有高级分析结果的公共字段和方法
    
    Attributes:
        analysis_type: 分析类型标识
        timestamp: 分析完成时间（ISO 格式）
        duration_seconds: 分析耗时
        success: 是否成功
        error_message: 错误信息（失败时有值）
        summary: 结果摘要（用于 UI 显示）
    """
    
    analysis_type: str
    """分析类型标识（如 "pvt", "monte_carlo", "sweep"）"""
    
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    """分析完成时间（ISO 格式）"""
    
    duration_seconds: float = 0.0
    """分析耗时（秒）"""
    
    success: bool = True
    """是否成功"""
    
    error_message: Optional[str] = None
    """错误信息（失败时有值）"""
    
    summary: str = ""
    """结果摘要（用于 UI 显示）"""
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "analysis_type": self.analysis_type,
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
            "success": self.success,
            "error_message": self.error_message,
            "summary": self.summary,
        }
    
    def get_display_summary(self) -> str:
        """获取用于 UI 显示的摘要文本"""
        return self.summary
    
    def get_chart_data(self) -> Dict[str, Any]:
        """获取用于图表生成的数据（子类覆盖）"""
        return {}


# ============================================================
# PVT 分析相关数据类
# ============================================================

@dataclass
class PVTCorner:
    """
    单个 PVT 角点定义
    
    Attributes:
        name: 角点名称（TT/FF/SS/FS/SF）
        process: 工艺角（typical/fast/slow）
        voltage: 电压（V）
        temperature: 温度（°C）
    """
    
    name: str
    """角点名称（TT/FF/SS/FS/SF）"""
    
    process: str
    """工艺角（typical/fast/slow）"""
    
    voltage: float
    """电压（V）"""
    
    temperature: float
    """温度（°C）"""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "process": self.process,
            "voltage": self.voltage,
            "temperature": self.temperature,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PVTCorner":
        return cls(
            name=data["name"],
            process=data["process"],
            voltage=data["voltage"],
            temperature=data["temperature"],
        )


@dataclass
class PVTAnalysisResult(AnalysisResultBase):
    """
    PVT 角点分析结果
    
    Attributes:
        corners: 角点列表
        corner_results: 各角点仿真结果
        worst_corner: 最差角点标识
        all_passed: 是否所有角点都通过
        metrics_comparison: 各指标在各角点的值
    """
    
    corners: List[PVTCorner] = field(default_factory=list)
    """角点列表"""
    
    corner_results: Dict[str, Any] = field(default_factory=dict)
    """各角点仿真结果"""
    
    worst_corner: str = ""
    """最差角点标识"""
    
    all_passed: bool = True
    """是否所有角点都通过"""
    
    metrics_comparison: Dict[str, Dict[str, float]] = field(default_factory=dict)
    """各指标在各角点的值"""
    
    def __post_init__(self):
        if not self.analysis_type:
            self.analysis_type = "pvt"
    
    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            "corners": [c.to_dict() for c in self.corners],
            "corner_results": self.corner_results,
            "worst_corner": self.worst_corner,
            "all_passed": self.all_passed,
            "metrics_comparison": self.metrics_comparison,
        })
        return base
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PVTAnalysisResult":
        corners = [PVTCorner.from_dict(c) for c in data.get("corners", [])]
        return cls(
            analysis_type=data.get("analysis_type", "pvt"),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            duration_seconds=data.get("duration_seconds", 0.0),
            success=data.get("success", True),
            error_message=data.get("error_message"),
            summary=data.get("summary", ""),
            corners=corners,
            corner_results=data.get("corner_results", {}),
            worst_corner=data.get("worst_corner", ""),
            all_passed=data.get("all_passed", True),
            metrics_comparison=data.get("metrics_comparison", {}),
        )
    
    def get_display_summary(self) -> str:
        if not self.success:
            return f"PVT 分析失败: {self.error_message}"
        status = "全部通过" if self.all_passed else f"最差角点: {self.worst_corner}"
        return f"PVT 分析完成 ({len(self.corners)} 个角点) - {status}"


# ============================================================
# 蒙特卡洛分析相关数据类
# ============================================================

@dataclass
class MetricStatistics:
    """
    指标统计数据
    
    Attributes:
        mean: 均值
        std: 标准差
        min: 最小值
        max: 最大值
        sigma_3_low: 3σ 下限
        sigma_3_high: 3σ 上限
    """
    
    mean: float = 0.0
    std: float = 0.0
    min: float = 0.0
    max: float = 0.0
    sigma_3_low: float = 0.0
    sigma_3_high: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "mean": self.mean,
            "std": self.std,
            "min": self.min,
            "max": self.max,
            "sigma_3_low": self.sigma_3_low,
            "sigma_3_high": self.sigma_3_high,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetricStatistics":
        return cls(
            mean=data.get("mean", 0.0),
            std=data.get("std", 0.0),
            min=data.get("min", 0.0),
            max=data.get("max", 0.0),
            sigma_3_low=data.get("sigma_3_low", 0.0),
            sigma_3_high=data.get("sigma_3_high", 0.0),
        )


@dataclass
class HistogramData:
    """
    直方图数据
    
    Attributes:
        bins: 分箱边界
        counts: 各箱计数
        target_line: 目标值线
    """
    
    bins: List[float] = field(default_factory=list)
    counts: List[int] = field(default_factory=list)
    target_line: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "bins": self.bins,
            "counts": self.counts,
            "target_line": self.target_line,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HistogramData":
        return cls(
            bins=data.get("bins", []),
            counts=data.get("counts", []),
            target_line=data.get("target_line"),
        )


@dataclass
class MonteCarloResult(AnalysisResultBase):
    """
    蒙特卡洛分析结果
    
    Attributes:
        num_runs: 运行次数
        num_passed: 通过次数
        num_failed: 失败次数
        yield_percent: 良率百分比
        statistics: 各指标统计数据
        histogram_data: 直方图数据
        sensitive_params: 敏感参数列表
    """
    
    num_runs: int = 0
    """运行次数"""
    
    num_passed: int = 0
    """通过次数"""
    
    num_failed: int = 0
    """失败次数"""
    
    yield_percent: float = 0.0
    """良率百分比"""
    
    statistics: Dict[str, MetricStatistics] = field(default_factory=dict)
    """各指标统计数据"""
    
    histogram_data: Dict[str, HistogramData] = field(default_factory=dict)
    """直方图数据"""
    
    sensitive_params: List[str] = field(default_factory=list)
    """敏感参数列表"""
    
    def __post_init__(self):
        if not self.analysis_type:
            self.analysis_type = "monte_carlo"
    
    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            "num_runs": self.num_runs,
            "num_passed": self.num_passed,
            "num_failed": self.num_failed,
            "yield_percent": self.yield_percent,
            "statistics": {k: v.to_dict() for k, v in self.statistics.items()},
            "histogram_data": {k: v.to_dict() for k, v in self.histogram_data.items()},
            "sensitive_params": self.sensitive_params,
        })
        return base
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MonteCarloResult":
        statistics = {
            k: MetricStatistics.from_dict(v) 
            for k, v in data.get("statistics", {}).items()
        }
        histogram_data = {
            k: HistogramData.from_dict(v) 
            for k, v in data.get("histogram_data", {}).items()
        }
        return cls(
            analysis_type=data.get("analysis_type", "monte_carlo"),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            duration_seconds=data.get("duration_seconds", 0.0),
            success=data.get("success", True),
            error_message=data.get("error_message"),
            summary=data.get("summary", ""),
            num_runs=data.get("num_runs", 0),
            num_passed=data.get("num_passed", 0),
            num_failed=data.get("num_failed", 0),
            yield_percent=data.get("yield_percent", 0.0),
            statistics=statistics,
            histogram_data=histogram_data,
            sensitive_params=data.get("sensitive_params", []),
        )
    
    def get_display_summary(self) -> str:
        if not self.success:
            return f"蒙特卡洛分析失败: {self.error_message}"
        return f"蒙特卡洛分析完成 ({self.num_runs} 次运行) - 良率: {self.yield_percent:.1f}%"


# ============================================================
# 参数扫描相关数据类
# ============================================================

@dataclass
class SweepParam:
    """
    扫描参数定义
    
    Attributes:
        name: 参数名
        values: 扫描值列表
        unit: 单位
    """
    
    name: str
    """参数名"""
    
    values: List[float] = field(default_factory=list)
    """扫描值列表"""
    
    unit: str = ""
    """单位"""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "values": self.values,
            "unit": self.unit,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SweepParam":
        return cls(
            name=data["name"],
            values=data.get("values", []),
            unit=data.get("unit", ""),
        )


@dataclass
class SweepResult(AnalysisResultBase):
    """
    参数扫描结果
    
    Attributes:
        sweep_params: 扫描参数定义
        sweep_data: 扫描数据（序列化为列表）
        optimal_point: 最优参数点
        feasible_region: 可行区域边界
    """
    
    sweep_params: List[SweepParam] = field(default_factory=list)
    """扫描参数定义"""
    
    sweep_data: List[List[float]] = field(default_factory=list)
    """扫描数据（多维数组序列化为列表）"""
    
    optimal_point: Dict[str, float] = field(default_factory=dict)
    """最优参数点"""
    
    feasible_region: List[Dict] = field(default_factory=list)
    """可行区域边界"""
    
    def __post_init__(self):
        if not self.analysis_type:
            self.analysis_type = "sweep"
    
    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            "sweep_params": [p.to_dict() for p in self.sweep_params],
            "sweep_data": self.sweep_data,
            "optimal_point": self.optimal_point,
            "feasible_region": self.feasible_region,
        })
        return base
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SweepResult":
        sweep_params = [SweepParam.from_dict(p) for p in data.get("sweep_params", [])]
        return cls(
            analysis_type=data.get("analysis_type", "sweep"),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            duration_seconds=data.get("duration_seconds", 0.0),
            success=data.get("success", True),
            error_message=data.get("error_message"),
            summary=data.get("summary", ""),
            sweep_params=sweep_params,
            sweep_data=data.get("sweep_data", []),
            optimal_point=data.get("optimal_point", {}),
            feasible_region=data.get("feasible_region", []),
        )
    
    def get_display_summary(self) -> str:
        if not self.success:
            return f"参数扫描失败: {self.error_message}"
        param_names = [p.name for p in self.sweep_params]
        return f"参数扫描完成 ({', '.join(param_names)})"


# ============================================================
# 最坏情况分析相关数据类
# ============================================================

@dataclass
class CriticalParam:
    """
    关键参数
    
    Attributes:
        name: 参数名
        sensitivity: 敏感度系数
        contribution_percent: 贡献百分比
    """
    
    name: str
    """参数名"""
    
    sensitivity: float = 0.0
    """敏感度系数"""
    
    contribution_percent: float = 0.0
    """贡献百分比"""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "sensitivity": self.sensitivity,
            "contribution_percent": self.contribution_percent,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CriticalParam":
        return cls(
            name=data["name"],
            sensitivity=data.get("sensitivity", 0.0),
            contribution_percent=data.get("contribution_percent", 0.0),
        )


@dataclass
class WorstCaseResult(AnalysisResultBase):
    """
    最坏情况分析结果
    
    Attributes:
        method: 分析方法（RSS/EVA）
        nominal_value: 标称值
        worst_case_max: 最坏情况最大值
        worst_case_min: 最坏情况最小值
        design_margin_percent: 设计裕度百分比
        critical_params: 关键参数列表
    """
    
    method: str = "RSS"
    """分析方法（RSS/EVA）"""
    
    nominal_value: float = 0.0
    """标称值"""
    
    worst_case_max: float = 0.0
    """最坏情况最大值"""
    
    worst_case_min: float = 0.0
    """最坏情况最小值"""
    
    design_margin_percent: float = 0.0
    """设计裕度百分比"""
    
    critical_params: List[CriticalParam] = field(default_factory=list)
    """关键参数列表"""
    
    def __post_init__(self):
        if not self.analysis_type:
            self.analysis_type = "worst_case"
    
    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            "method": self.method,
            "nominal_value": self.nominal_value,
            "worst_case_max": self.worst_case_max,
            "worst_case_min": self.worst_case_min,
            "design_margin_percent": self.design_margin_percent,
            "critical_params": [p.to_dict() for p in self.critical_params],
        })
        return base
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorstCaseResult":
        critical_params = [CriticalParam.from_dict(p) for p in data.get("critical_params", [])]
        return cls(
            analysis_type=data.get("analysis_type", "worst_case"),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            duration_seconds=data.get("duration_seconds", 0.0),
            success=data.get("success", True),
            error_message=data.get("error_message"),
            summary=data.get("summary", ""),
            method=data.get("method", "RSS"),
            nominal_value=data.get("nominal_value", 0.0),
            worst_case_max=data.get("worst_case_max", 0.0),
            worst_case_min=data.get("worst_case_min", 0.0),
            design_margin_percent=data.get("design_margin_percent", 0.0),
            critical_params=critical_params,
        )
    
    def get_display_summary(self) -> str:
        if not self.success:
            return f"最坏情况分析失败: {self.error_message}"
        return f"最坏情况分析完成 ({self.method}) - 裕度: {self.design_margin_percent:.1f}%"


# ============================================================
# 敏感度分析相关数据类
# ============================================================

@dataclass
class ParamSensitivity:
    """
    参数敏感度
    
    Attributes:
        param_name: 参数名
        nominal_value: 标称值
        absolute_sensitivity: 绝对敏感度
        relative_sensitivity: 相对敏感度
        direction: 影响方向（positive/negative）
    """
    
    param_name: str
    """参数名"""
    
    nominal_value: float = 0.0
    """标称值"""
    
    absolute_sensitivity: float = 0.0
    """绝对敏感度"""
    
    relative_sensitivity: float = 0.0
    """相对敏感度"""
    
    direction: str = "positive"
    """影响方向（positive/negative）"""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "param_name": self.param_name,
            "nominal_value": self.nominal_value,
            "absolute_sensitivity": self.absolute_sensitivity,
            "relative_sensitivity": self.relative_sensitivity,
            "direction": self.direction,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParamSensitivity":
        return cls(
            param_name=data["param_name"],
            nominal_value=data.get("nominal_value", 0.0),
            absolute_sensitivity=data.get("absolute_sensitivity", 0.0),
            relative_sensitivity=data.get("relative_sensitivity", 0.0),
            direction=data.get("direction", "positive"),
        )


@dataclass
class TornadoChartData:
    """
    龙卷风图数据
    
    Attributes:
        param_names: 参数名列表
        positive_impacts: 正向影响值
        negative_impacts: 负向影响值
        baseline_value: 基准值
    """
    
    param_names: List[str] = field(default_factory=list)
    """参数名列表"""
    
    positive_impacts: List[float] = field(default_factory=list)
    """正向影响值"""
    
    negative_impacts: List[float] = field(default_factory=list)
    """负向影响值"""
    
    baseline_value: float = 0.0
    """基准值"""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "param_names": self.param_names,
            "positive_impacts": self.positive_impacts,
            "negative_impacts": self.negative_impacts,
            "baseline_value": self.baseline_value,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TornadoChartData":
        return cls(
            param_names=data.get("param_names", []),
            positive_impacts=data.get("positive_impacts", []),
            negative_impacts=data.get("negative_impacts", []),
            baseline_value=data.get("baseline_value", 0.0),
        )


@dataclass
class SensitivityResult(AnalysisResultBase):
    """
    敏感度分析结果
    
    Attributes:
        metric_name: 分析的指标名称
        param_sensitivities: 参数敏感度列表
        tornado_data: 龙卷风图数据
        optimization_suggestions: 优化建议
    """
    
    metric_name: str = ""
    """分析的指标名称"""
    
    param_sensitivities: List[ParamSensitivity] = field(default_factory=list)
    """参数敏感度列表"""
    
    tornado_data: Optional[TornadoChartData] = None
    """龙卷风图数据"""
    
    optimization_suggestions: List[str] = field(default_factory=list)
    """优化建议"""
    
    def __post_init__(self):
        if not self.analysis_type:
            self.analysis_type = "sensitivity"
    
    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            "metric_name": self.metric_name,
            "param_sensitivities": [p.to_dict() for p in self.param_sensitivities],
            "tornado_data": self.tornado_data.to_dict() if self.tornado_data else None,
            "optimization_suggestions": self.optimization_suggestions,
        })
        return base
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SensitivityResult":
        param_sensitivities = [
            ParamSensitivity.from_dict(p) 
            for p in data.get("param_sensitivities", [])
        ]
        tornado_data = None
        if data.get("tornado_data"):
            tornado_data = TornadoChartData.from_dict(data["tornado_data"])
        return cls(
            analysis_type=data.get("analysis_type", "sensitivity"),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            duration_seconds=data.get("duration_seconds", 0.0),
            success=data.get("success", True),
            error_message=data.get("error_message"),
            summary=data.get("summary", ""),
            metric_name=data.get("metric_name", ""),
            param_sensitivities=param_sensitivities,
            tornado_data=tornado_data,
            optimization_suggestions=data.get("optimization_suggestions", []),
        )
    
    def get_display_summary(self) -> str:
        if not self.success:
            return f"敏感度分析失败: {self.error_message}"
        return f"敏感度分析完成 ({self.metric_name}) - {len(self.param_sensitivities)} 个参数"


# ============================================================
# FFT 后处理相关数据类
# ============================================================

@dataclass
class HarmonicData:
    """
    谐波数据
    
    Attributes:
        order: 谐波次数
        frequency: 频率
        amplitude: 幅度
        phase: 相位
    """
    
    order: int
    """谐波次数"""
    
    frequency: float = 0.0
    """频率"""
    
    amplitude: float = 0.0
    """幅度"""
    
    phase: float = 0.0
    """相位"""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "order": self.order,
            "frequency": self.frequency,
            "amplitude": self.amplitude,
            "phase": self.phase,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HarmonicData":
        return cls(
            order=data["order"],
            frequency=data.get("frequency", 0.0),
            amplitude=data.get("amplitude", 0.0),
            phase=data.get("phase", 0.0),
        )


@dataclass
class SpectrumData:
    """
    频谱数据
    
    Attributes:
        frequencies: 频率数组
        magnitudes: 幅度数组（dB）
        phases: 相位数组
    """
    
    frequencies: List[float] = field(default_factory=list)
    """频率数组"""
    
    magnitudes: List[float] = field(default_factory=list)
    """幅度数组（dB）"""
    
    phases: List[float] = field(default_factory=list)
    """相位数组"""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "frequencies": self.frequencies,
            "magnitudes": self.magnitudes,
            "phases": self.phases,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpectrumData":
        return cls(
            frequencies=data.get("frequencies", []),
            magnitudes=data.get("magnitudes", []),
            phases=data.get("phases", []),
        )


@dataclass
class FFTResult(AnalysisResultBase):
    """
    FFT 分析结果
    
    Attributes:
        signal_name: 信号名称
        fundamental_freq: 基波频率
        thd_percent: 总谐波失真百分比
        harmonics: 谐波数据列表
        spectrum_data: 频谱数据
    """
    
    signal_name: str = ""
    """信号名称"""
    
    fundamental_freq: float = 0.0
    """基波频率"""
    
    thd_percent: float = 0.0
    """总谐波失真百分比"""
    
    harmonics: List[HarmonicData] = field(default_factory=list)
    """谐波数据列表"""
    
    spectrum_data: Optional[SpectrumData] = None
    """频谱数据"""
    
    def __post_init__(self):
        if not self.analysis_type:
            self.analysis_type = "fft"
    
    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            "signal_name": self.signal_name,
            "fundamental_freq": self.fundamental_freq,
            "thd_percent": self.thd_percent,
            "harmonics": [h.to_dict() for h in self.harmonics],
            "spectrum_data": self.spectrum_data.to_dict() if self.spectrum_data else None,
        })
        return base
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FFTResult":
        harmonics = [HarmonicData.from_dict(h) for h in data.get("harmonics", [])]
        spectrum_data = None
        if data.get("spectrum_data"):
            spectrum_data = SpectrumData.from_dict(data["spectrum_data"])
        return cls(
            analysis_type=data.get("analysis_type", "fft"),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            duration_seconds=data.get("duration_seconds", 0.0),
            success=data.get("success", True),
            error_message=data.get("error_message"),
            summary=data.get("summary", ""),
            signal_name=data.get("signal_name", ""),
            fundamental_freq=data.get("fundamental_freq", 0.0),
            thd_percent=data.get("thd_percent", 0.0),
            harmonics=harmonics,
            spectrum_data=spectrum_data,
        )
    
    def get_display_summary(self) -> str:
        if not self.success:
            return f"FFT 分析失败: {self.error_message}"
        return f"FFT 分析完成 ({self.signal_name}) - THD: {self.thd_percent:.2f}%"


# ============================================================
# 拓扑识别相关数据类
# ============================================================

@dataclass
class TopologyResult(AnalysisResultBase):
    """
    拓扑识别结果
    
    Attributes:
        topology_type: 拓扑类型（amplifier/filter/power/oscillator）
        sub_type: 子类型（如 common_source/differential_pair）
        confidence: 置信度（0-1）
        recommended_analyses: 推荐的分析类型
        key_metrics: 关键性能指标
        critical_nodes: 关键节点列表
    """
    
    topology_type: str = ""
    """拓扑类型（amplifier/filter/power/oscillator）"""
    
    sub_type: str = ""
    """子类型（如 common_source/differential_pair）"""
    
    confidence: float = 0.0
    """置信度（0-1）"""
    
    recommended_analyses: List[str] = field(default_factory=list)
    """推荐的分析类型"""
    
    key_metrics: List[str] = field(default_factory=list)
    """关键性能指标"""
    
    critical_nodes: List[str] = field(default_factory=list)
    """关键节点列表"""
    
    def __post_init__(self):
        if not self.analysis_type:
            self.analysis_type = "topology"
    
    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            "topology_type": self.topology_type,
            "sub_type": self.sub_type,
            "confidence": self.confidence,
            "recommended_analyses": self.recommended_analyses,
            "key_metrics": self.key_metrics,
            "critical_nodes": self.critical_nodes,
        })
        return base
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TopologyResult":
        return cls(
            analysis_type=data.get("analysis_type", "topology"),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            duration_seconds=data.get("duration_seconds", 0.0),
            success=data.get("success", True),
            error_message=data.get("error_message"),
            summary=data.get("summary", ""),
            topology_type=data.get("topology_type", ""),
            sub_type=data.get("sub_type", ""),
            confidence=data.get("confidence", 0.0),
            recommended_analyses=data.get("recommended_analyses", []),
            key_metrics=data.get("key_metrics", []),
            critical_nodes=data.get("critical_nodes", []),
        )
    
    def get_display_summary(self) -> str:
        if not self.success:
            return f"拓扑识别失败: {self.error_message}"
        return f"拓扑识别: {self.topology_type}/{self.sub_type} (置信度: {self.confidence:.0%})"


# ============================================================
# 收敛诊断相关数据类
# ============================================================

@dataclass
class SuggestedFix:
    """
    建议的修复方案
    
    Attributes:
        description: 修复描述
        action_type: 操作类型（add_resistor/adjust_param/add_ic）
        parameters: 操作参数
    """
    
    description: str
    """修复描述"""
    
    action_type: str
    """操作类型（add_resistor/adjust_param/add_ic）"""
    
    parameters: Dict[str, Any] = field(default_factory=dict)
    """操作参数"""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "action_type": self.action_type,
            "parameters": self.parameters,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SuggestedFix":
        return cls(
            description=data["description"],
            action_type=data["action_type"],
            parameters=data.get("parameters", {}),
        )


@dataclass
class ConvergenceDiagnosis(AnalysisResultBase):
    """
    收敛诊断结果
    
    Attributes:
        issue_type: 问题类型（dc_convergence/tran_convergence/floating_node）
        severity: 严重程度（low/medium/high/critical）
        affected_nodes: 受影响的节点
        suggested_fixes: 建议的修复方案
        auto_fix_available: 是否可自动修复
    """
    
    issue_type: str = ""
    """问题类型（dc_convergence/tran_convergence/floating_node）"""
    
    severity: str = "medium"
    """严重程度（low/medium/high/critical）"""
    
    affected_nodes: List[str] = field(default_factory=list)
    """受影响的节点"""
    
    suggested_fixes: List[SuggestedFix] = field(default_factory=list)
    """建议的修复方案"""
    
    auto_fix_available: bool = False
    """是否可自动修复"""
    
    def __post_init__(self):
        if not self.analysis_type:
            self.analysis_type = "convergence_diagnosis"
    
    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            "issue_type": self.issue_type,
            "severity": self.severity,
            "affected_nodes": self.affected_nodes,
            "suggested_fixes": [f.to_dict() for f in self.suggested_fixes],
            "auto_fix_available": self.auto_fix_available,
        })
        return base
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConvergenceDiagnosis":
        suggested_fixes = [
            SuggestedFix.from_dict(f) 
            for f in data.get("suggested_fixes", [])
        ]
        return cls(
            analysis_type=data.get("analysis_type", "convergence_diagnosis"),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            duration_seconds=data.get("duration_seconds", 0.0),
            success=data.get("success", True),
            error_message=data.get("error_message"),
            summary=data.get("summary", ""),
            issue_type=data.get("issue_type", ""),
            severity=data.get("severity", "medium"),
            affected_nodes=data.get("affected_nodes", []),
            suggested_fixes=suggested_fixes,
            auto_fix_available=data.get("auto_fix_available", False),
        )
    
    def get_display_summary(self) -> str:
        if not self.success:
            return f"收敛诊断失败: {self.error_message}"
        fix_status = "可自动修复" if self.auto_fix_available else "需手动修复"
        return f"收敛诊断: {self.issue_type} ({self.severity}) - {fix_status}"


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 基类
    "AnalysisResultBase",
    # PVT 分析
    "PVTCorner",
    "PVTAnalysisResult",
    # 蒙特卡洛分析
    "MetricStatistics",
    "HistogramData",
    "MonteCarloResult",
    # 参数扫描
    "SweepParam",
    "SweepResult",
    # 最坏情况分析
    "CriticalParam",
    "WorstCaseResult",
    # 敏感度分析
    "ParamSensitivity",
    "TornadoChartData",
    "SensitivityResult",
    # FFT 后处理
    "HarmonicData",
    "SpectrumData",
    "FFTResult",
    # 拓扑识别
    "TopologyResult",
    # 收敛诊断
    "SuggestedFix",
    "ConvergenceDiagnosis",
]
