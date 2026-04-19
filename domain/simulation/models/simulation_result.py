# SimulationResult - Standardized Simulation Result Data Class
"""
仿真结果数据类

职责：
- 定义标准化的仿真结果数据结构
- 提供仿真数据的序列化和反序列化
- 支持仿真结果的查询和验证

设计原则：
- 使用 dataclass 确保类型安全
- 提供 numpy 数组的序列化支持
- 与 SimulationError 数据类集成

使用示例：
    # 创建仿真结果
    result = SimulationResult(
        executor="spice",
        file_path="amplifier.cir",
        analysis_type="ac",
        success=True,
        data=SimulationData(
            frequency=np.array([1e3, 1e4, 1e5]),
            signals={"V(out)": np.array([0.1, 1.0, 10.0])}
        ),
        measurements=[
            MeasureResult(name="gain", value=20.0, unit="dB"),
            MeasureResult(name="bandwidth", value=1e7, unit="Hz"),
        ],
        timestamp=datetime.now().isoformat(),
        duration_seconds=2.5,
        version=1
    )
    
    # 序列化
    data_dict = result.to_dict()
    
    # 反序列化
    loaded_result = SimulationResult.from_dict(data_dict)
    
    # 查询信号
    output_signal = result.get_signal("V(out)")
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np

from domain.simulation.measure.measure_metadata import (
    get_result_metric_value,
    normalize_measurements_payload,
    resolve_result_metric_values,
)


X_AXIS_KIND_NONE = "none"
X_AXIS_KIND_TIME = "time"
X_AXIS_KIND_FREQUENCY = "frequency"
X_AXIS_KIND_SWEEP = "sweep"

X_AXIS_SCALE_NONE = "none"
X_AXIS_SCALE_LINEAR = "linear"
X_AXIS_SCALE_LOG = "log"

_VALID_X_AXIS_KINDS = {
    X_AXIS_KIND_NONE,
    X_AXIS_KIND_TIME,
    X_AXIS_KIND_FREQUENCY,
    X_AXIS_KIND_SWEEP,
}
_VALID_X_AXIS_SCALES = {
    X_AXIS_SCALE_NONE,
    X_AXIS_SCALE_LINEAR,
    X_AXIS_SCALE_LOG,
}


def _normalize_x_axis_kind(value: Optional[str]) -> str:
    candidate = (value or X_AXIS_KIND_NONE).lower()
    return candidate if candidate in _VALID_X_AXIS_KINDS else X_AXIS_KIND_NONE


def _normalize_x_axis_scale(value: Optional[str]) -> str:
    candidate = (value or X_AXIS_SCALE_NONE).lower()
    return candidate if candidate in _VALID_X_AXIS_SCALES else X_AXIS_SCALE_NONE


def _normalize_axis_range(value: Any) -> Optional[tuple[float, float]]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        start = float(value[0])
        end = float(value[1])
    except (TypeError, ValueError):
        return None
    if not np.isfinite(start) or not np.isfinite(end):
        return None
    return (start, end)


def _infer_x_axis_kind(data: Optional["SimulationData"]) -> str:
    if data is None:
        return X_AXIS_KIND_NONE
    if data.time is not None:
        return X_AXIS_KIND_TIME
    if data.frequency is not None:
        return X_AXIS_KIND_FREQUENCY
    if data.sweep is not None:
        return X_AXIS_KIND_SWEEP
    return X_AXIS_KIND_NONE


def _infer_x_axis_label(kind: str, data: Optional["SimulationData"]) -> str:
    if kind == X_AXIS_KIND_TIME:
        return "Time (s)"
    if kind == X_AXIS_KIND_FREQUENCY:
        return "Frequency (Hz)"
    if kind == X_AXIS_KIND_SWEEP:
        return data.sweep_name if data is not None and data.sweep_name else "Sweep"
    return "X"


def _get_x_axis_array(data: Optional["SimulationData"], kind: str) -> Optional[np.ndarray]:
    if data is None:
        return None
    if kind == X_AXIS_KIND_TIME:
        return data.time
    if kind == X_AXIS_KIND_FREQUENCY:
        return data.frequency
    if kind == X_AXIS_KIND_SWEEP:
        return data.sweep
    return None


def _infer_actual_x_range(
    data: Optional["SimulationData"],
    kind: str,
) -> Optional[tuple[float, float]]:
    axis_data = _get_x_axis_array(data, kind)
    if axis_data is None or len(axis_data) == 0:
        return None
    return (float(np.min(axis_data)), float(np.max(axis_data)))


def _default_x_axis_scale(analysis_type: str, kind: str) -> str:
    if kind == X_AXIS_KIND_NONE:
        return X_AXIS_SCALE_NONE
    if (analysis_type or "").lower() in {"ac", "noise"} and kind == X_AXIS_KIND_FREQUENCY:
        return X_AXIS_SCALE_LOG
    return X_AXIS_SCALE_LINEAR


def _split_analysis_command(command: str) -> list[str]:
    if not isinstance(command, str):
        return []
    stripped = command.strip()
    return stripped.split() if stripped else []


def _infer_analysis_parameters(analysis_type: str, analysis_command: str) -> Dict[str, Any]:
    analysis = (analysis_type or "").lower()
    tokens = _split_analysis_command(analysis_command)
    if not analysis or not tokens or tokens[0].lower() != f".{analysis}":
        return {}

    if analysis == "ac":
        return {
            "sweep_type": tokens[1] if len(tokens) > 1 else "",
            "points_per_decade": tokens[2] if len(tokens) > 2 else "",
            "start_frequency": tokens[3] if len(tokens) > 3 else "",
            "stop_frequency": tokens[4] if len(tokens) > 4 else "",
        }

    if analysis == "dc":
        return {
            "source_name": tokens[1] if len(tokens) > 1 else "",
            "start_value": tokens[2] if len(tokens) > 2 else "",
            "stop_value": tokens[3] if len(tokens) > 3 else "",
            "step": tokens[4] if len(tokens) > 4 else "",
        }

    if analysis == "tran":
        extra_tokens = [token for token in tokens[3:] if token.lower() != "uic"]
        parameters = {
            "step_time": tokens[1] if len(tokens) > 1 else "",
            "stop_time": tokens[2] if len(tokens) > 2 else "",
            "start_time": extra_tokens[0] if len(extra_tokens) > 0 else "",
            "max_step": extra_tokens[1] if len(extra_tokens) > 1 else "",
        }
        if any(token.lower() == "uic" for token in tokens[3:]):
            parameters["use_initial_conditions"] = "uic"
        return parameters

    if analysis == "noise":
        return {
            "output_node": tokens[1] if len(tokens) > 1 else "",
            "input_source": tokens[2] if len(tokens) > 2 else "",
            "sweep_type": tokens[3] if len(tokens) > 3 else "",
            "points_per_decade": tokens[4] if len(tokens) > 4 else "",
            "start_frequency": tokens[5] if len(tokens) > 5 else "",
            "stop_frequency": tokens[6] if len(tokens) > 6 else "",
        }

    return {}


def _normalize_analysis_info(
    value: Any,
    *,
    analysis_type: str,
    analysis_command: str,
    x_axis_kind: str,
    x_axis_label: str,
    x_axis_scale: str,
    requested_x_range: Optional[tuple[float, float]],
    actual_x_range: Optional[tuple[float, float]],
) -> Dict[str, Any]:
    info = value if isinstance(value, dict) else {}
    resolved_analysis_type = str(info.get("analysis_type") or analysis_type or "").lower()
    resolved_analysis_command = str(info.get("analysis_command") or analysis_command or "")
    requested_range = _normalize_axis_range(info.get("requested_x_range"))
    actual_range = _normalize_axis_range(info.get("actual_x_range"))
    parameters = info.get("parameters")
    resolved_parameters = dict(parameters) if isinstance(parameters, dict) else _infer_analysis_parameters(
        resolved_analysis_type,
        resolved_analysis_command,
    )
    return {
        "analysis_type": resolved_analysis_type,
        "analysis_command": resolved_analysis_command,
        "x_axis_kind": str(info.get("x_axis_kind") or x_axis_kind or ""),
        "x_axis_label": str(info.get("x_axis_label") or x_axis_label or ""),
        "x_axis_scale": str(info.get("x_axis_scale") or x_axis_scale or ""),
        "requested_x_range": requested_range if requested_range is not None else requested_x_range,
        "actual_x_range": actual_range if actual_range is not None else actual_x_range,
        "parameters": resolved_parameters,
    }


def infer_result_axis_metadata(
    analysis_type: str,
    data: Optional["SimulationData"],
    *,
    x_axis_kind: Optional[str] = None,
    x_axis_label: Optional[str] = None,
    x_axis_scale: Optional[str] = None,
    requested_x_range: Optional[tuple[float, float]] = None,
    actual_x_range: Optional[tuple[float, float]] = None,
    analysis_command: str = "",
) -> Dict[str, Any]:
    resolved_kind = _normalize_x_axis_kind(x_axis_kind)
    if resolved_kind == X_AXIS_KIND_NONE:
        resolved_kind = _infer_x_axis_kind(data)
    resolved_label = x_axis_label or _infer_x_axis_label(resolved_kind, data)
    resolved_scale = _normalize_x_axis_scale(x_axis_scale)
    if resolved_scale == X_AXIS_SCALE_NONE and resolved_kind != X_AXIS_KIND_NONE:
        resolved_scale = _default_x_axis_scale(analysis_type, resolved_kind)
    resolved_requested_range = _normalize_axis_range(requested_x_range)
    resolved_actual_range = _normalize_axis_range(actual_x_range)
    if resolved_actual_range is None:
        resolved_actual_range = _infer_actual_x_range(data, resolved_kind)
    return {
        "x_axis_kind": resolved_kind,
        "x_axis_label": resolved_label,
        "x_axis_scale": resolved_scale,
        "requested_x_range": resolved_requested_range,
        "actual_x_range": resolved_actual_range,
        "analysis_command": analysis_command or "",
    }


# ============================================================
# SimulationData - 仿真数据容器
# ============================================================

@dataclass
class SimulationData:
    """
    仿真数据容器
    
    Attributes:
        frequency: AC 分析频率点（Hz）
        time: 瞬态分析时间点（秒）
        sweep: DC 分析扫描变量数据
        sweep_name: DC 扫描变量名称（如 "Vin"）
        signals: 信号数据字典，键为信号名称，值为 numpy 数组
    """
    
    frequency: Optional[np.ndarray] = None
    """AC 分析频率点（Hz）"""
    
    time: Optional[np.ndarray] = None
    """瞬态分析时间点（秒）"""
    
    sweep: Optional[np.ndarray] = None
    """DC 分析扫描变量数据"""
    
    sweep_name: Optional[str] = None
    """DC 扫描变量名称（如 "Vin"）"""
    
    signals: Dict[str, np.ndarray] = field(default_factory=dict)
    """信号数据字典，键为信号名称（如 "V(out)"），值为 numpy 数组"""
    
    signal_types: Dict[str, str] = field(default_factory=dict)
    """信号类型字典，键为信号名称，值为 voltage / current / other"""
    
    op_result: Dict[str, Any] = field(default_factory=dict)
    """.op 工作点结构化结果，优先供导出与 agent 读取复用"""
    
    # ============================================================
    # 序列化方法
    # ============================================================
    
    def to_dict(self) -> Dict[str, Any]:
        """
        序列化为字典
        
        Returns:
            Dict: 序列化后的字典
        """
        return {
            "frequency": self.frequency.tolist() if self.frequency is not None else None,
            "time": self.time.tolist() if self.time is not None else None,
            "sweep": self.sweep.tolist() if self.sweep is not None else None,
            "sweep_name": self.sweep_name,
            "signals": {
                name: self._serialize_array(data)
                for name, data in self.signals.items()
            },
            "signal_types": dict(self.signal_types) if self.signal_types else {},
            "op_result": dict(self.op_result) if self.op_result else {},
        }
    
    def _serialize_array(self, data: Any) -> Any:
        """
        序列化数组数据，处理复数类型
        
        Args:
            data: 数组数据（可能是实数或复数）
            
        Returns:
            可 JSON 序列化的数据
        """
        if not isinstance(data, np.ndarray):
            return data
        
        # 检查是否为复数数组
        if np.iscomplexobj(data):
            # 复数数组：分别存储实部和虚部
            return {
                "_complex": True,
                "real": np.real(data).tolist(),
                "imag": np.imag(data).tolist()
            }
        else:
            # 实数数组：直接转换为列表
            return data.tolist()
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimulationData":
        """
        从字典反序列化
        
        Args:
            data: 序列化的字典
            
        Returns:
            SimulationData: 反序列化后的对象
        """
        return cls(
            frequency=np.array(data["frequency"]) if data.get("frequency") is not None else None,
            time=np.array(data["time"]) if data.get("time") is not None else None,
            sweep=np.array(data["sweep"]) if data.get("sweep") is not None else None,
            sweep_name=data.get("sweep_name"),
            signals={
                name: cls._deserialize_array(signal_data)
                for name, signal_data in data.get("signals", {}).items()
            },
            signal_types=data.get("signal_types", {}),
            op_result=data.get("op_result", {}),
        )
    
    @classmethod
    def _deserialize_array(cls, data: Any) -> Any:
        """
        反序列化数组数据，处理复数类型
        
        Args:
            data: 序列化的数据
            
        Returns:
            numpy 数组（实数或复数）
        """
        if isinstance(data, dict) and data.get("_complex"):
            # 复数数组：从实部和虚部重建
            real = np.array(data["real"])
            imag = np.array(data["imag"])
            return real + 1j * imag
        elif isinstance(data, list):
            # 实数数组
            return np.array(data)
        else:
            return data
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def get_signal(self, name: str) -> Optional[np.ndarray]:
        """
        获取指定信号数据
        
        Args:
            name: 信号名称（如 "V(out)"）
            
        Returns:
            Optional[np.ndarray]: 信号数据，若不存在则返回 None
        """
        return self.signals.get(name)
    
    def has_signal(self, name: str) -> bool:
        """
        检查是否包含指定信号
        
        Args:
            name: 信号名称
            
        Returns:
            bool: 是否包含该信号
        """
        return name in self.signals
    
    def get_signal_names(self) -> list[str]:
        """
        获取所有信号名称列表
        
        Returns:
            list[str]: 信号名称列表
        """
        return list(self.signals.keys())


# ============================================================
# SimulationResult - 标准化仿真结果
# ============================================================

@dataclass
class SimulationResult:
    """
    标准化仿真结果
    
    Attributes:
        executor: 执行器名称（如 "spice", "python"）
        file_path: 仿真文件路径
        analysis_type: 分析类型（如 "ac", "dc", "tran", "noise"）
        success: 是否成功
        data: 仿真数据（成功时有值）
        measurements: 规范化测量结果列表（可选）
        error: 错误信息（失败时有值）
        raw_output: 原始输出（调试用）
        timestamp: ISO 格式时间戳
        duration_seconds: 执行耗时（秒）
        version: 版本号，对应 GraphState.iteration_count + 1
        session_id: 所属会话 ID（用于追踪）
    """
    
    executor: str
    """执行器名称（如 "spice", "python"）"""
    
    file_path: str
    """仿真文件路径"""
    
    analysis_type: str
    """分析类型（如 "ac", "dc", "tran", "noise"）"""
    
    success: bool
    """是否成功"""
    
    data: Optional[SimulationData] = None
    """仿真数据（成功时有值）"""
    
    measurements: Optional[list] = None
    """
    .MEASURE 测量结果列表（新格式）
    
    存储 ngspice .MEASURE 语句的执行结果。
    列表元素为 MeasureResult 对象或等效字典。
    
    示例：
        [
            MeasureResult(name="gain_db", value=20.5, unit="dB", status=OK),
            MeasureResult(name="f_3db", value=1e6, unit="Hz", status=OK),
        ]
    """
    
    error: Optional[Any] = None
    """错误信息（失败时有值，类型为 SimulationError）"""
    
    raw_output: Optional[str] = None
    """原始输出（调试用）"""
    
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    """ISO 格式时间戳（如 2024-12-20T14:30:22.123456）"""
    
    duration_seconds: float = 0.0
    """执行耗时（秒）"""
    
    version: int = 1
    """
    版本号，对应 GraphState.iteration_count + 1
    
    作用域：单个会话（session）内的同一电路文件
    递增规则：每次仿真后自动递增
    用途：
    - 追踪优化迭代过程（第 1 次、第 2 次...）
    - 验证数据新鲜度（防止使用过期缓存）
    - 支持历史对比（对比不同版本的性能）
    - 文件命名（如 run_001.json, run_002.json）
    
    注意：version 由 SimulationService 根据 GraphState.iteration_count 自动计算
    """
    
    session_id: str = ""
    """
    所属会话 ID（格式 YYYYMMDD_HHMMSS）
    
    用途：
    - 关联仿真结果到具体会话
    - 支持跨会话的结果查询
    - 便于清理过期数据
    """
    
    x_axis_kind: str = X_AXIS_KIND_NONE
    x_axis_label: str = "X"
    x_axis_scale: str = X_AXIS_SCALE_NONE
    requested_x_range: Optional[tuple[float, float]] = None
    actual_x_range: Optional[tuple[float, float]] = None
    analysis_command: str = ""
    analysis_info: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.measurements is not None:
            self.measurements = normalize_measurements_payload(self.measurements)
        axis_metadata = infer_result_axis_metadata(
            self.analysis_type,
            self.data,
            x_axis_kind=self.x_axis_kind,
            x_axis_label=self.x_axis_label,
            x_axis_scale=self.x_axis_scale,
            requested_x_range=self.requested_x_range,
            actual_x_range=self.actual_x_range,
            analysis_command=self.analysis_command,
        )
        self.x_axis_kind = axis_metadata["x_axis_kind"]
        self.x_axis_label = axis_metadata["x_axis_label"]
        self.x_axis_scale = axis_metadata["x_axis_scale"]
        self.requested_x_range = axis_metadata["requested_x_range"]
        self.actual_x_range = axis_metadata["actual_x_range"]
        self.analysis_command = axis_metadata["analysis_command"]
        self.analysis_info = _normalize_analysis_info(
            self.analysis_info,
            analysis_type=self.analysis_type,
            analysis_command=self.analysis_command,
            x_axis_kind=self.x_axis_kind,
            x_axis_label=self.x_axis_label,
            x_axis_scale=self.x_axis_scale,
            requested_x_range=self.requested_x_range,
            actual_x_range=self.actual_x_range,
        )

    # ============================================================
    # 序列化方法
    # ============================================================

    def to_dict(self) -> Dict[str, Any]:
        """
        序列化为字典
        
        Returns:
            Dict: 序列化后的字典
        """
        # 序列化 measurements
        measurements_data = None
        if self.measurements is not None:
            measurements_data = [
                m.to_dict() if hasattr(m, 'to_dict') else m
                for m in self.measurements
            ]

        analysis_info_data = dict(self.analysis_info) if self.analysis_info else {}
        if analysis_info_data.get("requested_x_range") is not None:
            analysis_info_data["requested_x_range"] = list(analysis_info_data["requested_x_range"])
        if analysis_info_data.get("actual_x_range") is not None:
            analysis_info_data["actual_x_range"] = list(analysis_info_data["actual_x_range"])

        return {
            "executor": self.executor,
            "file_path": self.file_path,
            "analysis_type": self.analysis_type,
            "success": self.success,
            "data": self.data.to_dict() if self.data is not None else None,
            "measurements": measurements_data,
            "error": self.error.to_dict() if self.error is not None and hasattr(self.error, "to_dict") else str(self.error) if self.error is not None else None,
            "raw_output": self.raw_output,
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
            "version": self.version,
            "session_id": self.session_id,
            "x_axis_kind": self.x_axis_kind,
            "x_axis_label": self.x_axis_label,
            "x_axis_scale": self.x_axis_scale,
            "requested_x_range": list(self.requested_x_range) if self.requested_x_range is not None else None,
            "actual_x_range": list(self.actual_x_range) if self.actual_x_range is not None else None,
            "analysis_command": self.analysis_command,
            "analysis_info": analysis_info_data,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimulationResult":
        """
        从字典反序列化
        
        Args:
            data: 序列化的字典
            
        Returns:
            SimulationResult: 反序列化后的对象
        """
        # 反序列化仿真数据
        sim_data = None
        if data.get("data") is not None:
            sim_data = SimulationData.from_dict(data["data"])

        # 反序列化 measurements
        measurements = None
        if data.get("measurements") is not None:
            measurements = data["measurements"]

        # 反序列化错误信息
        error = None
        error_data = data.get("error")
        if error_data is not None:
            if isinstance(error_data, dict):
                # 尝试反序列化为 SimulationError
                try:
                    from domain.simulation.models.simulation_error import SimulationError
                    error = SimulationError.from_dict(error_data)
                except (KeyError, ValueError, ImportError):
                    # 反序列化失败，保留原始字典
                    error = error_data
            else:
                # 字符串或其他类型，直接保留
                error = error_data

        return cls(
            executor=data["executor"],
            file_path=data["file_path"],
            analysis_type=data["analysis_type"],
            success=data["success"],
            data=sim_data,
            measurements=measurements,
            error=error,
            raw_output=data.get("raw_output"),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            duration_seconds=data.get("duration_seconds", 0.0),
            version=data.get("version", 1),
            session_id=data.get("session_id", ""),
            x_axis_kind=data.get("x_axis_kind", X_AXIS_KIND_NONE),
            x_axis_label=data.get("x_axis_label", "X"),
            x_axis_scale=data.get("x_axis_scale", X_AXIS_SCALE_NONE),
            requested_x_range=_normalize_axis_range(data.get("requested_x_range")),
            actual_x_range=_normalize_axis_range(data.get("actual_x_range")),
            analysis_command=data.get("analysis_command", ""),
            analysis_info=data.get("analysis_info", {}),
        )

    # ============================================================
    # 辅助方法
    # ============================================================

    def get_signal(self, name: str) -> Optional[np.ndarray]:
        """
        获取指定信号数据
        
        Args:
            name: 信号名称（如 "V(out)"）
            
        Returns:
            Optional[np.ndarray]: 信号数据，若不存在或仿真失败则返回 None
        """
        if not self.success or self.data is None:
            return None
        return self.data.get_signal(name)

    def get_x_axis_data(self) -> Optional[np.ndarray]:
        if not self.success or self.data is None:
            return None
        axis_data = _get_x_axis_array(self.data, self.x_axis_kind)
        if axis_data is not None:
            return axis_data
        return _get_x_axis_array(self.data, _infer_x_axis_kind(self.data))

    def get_x_axis_label(self) -> str:
        return self.x_axis_label or _infer_x_axis_label(self.x_axis_kind, self.data)

    def is_x_axis_log(self) -> bool:
        return self.x_axis_scale == X_AXIS_SCALE_LOG

    @property
    def metric_values(self) -> Dict[str, float]:
        return resolve_result_metric_values(self)
    
    def get_metric(self, name: str, default: Any = None) -> Any:
        """
        获取指定性能指标
        
        Args:
            name: 指标名称
            default: 默认值
            
        Returns:
            Any: 指标值，若不存在则返回默认值
        """
        return get_result_metric_value(self, name, default)


# ============================================================
# 工厂方法
# ============================================================

def create_success_result(
    executor: str,
    file_path: str,
    analysis_type: str,
    data: SimulationData,
    measurements: Optional[list] = None,
    raw_output: Optional[str] = None,
    duration_seconds: float = 0.0,
    version: int = 1,
    session_id: str = "",
    axis_metadata: Optional[Dict[str, Any]] = None,
    analysis_command: str = "",
) -> SimulationResult:
    """
    创建成功的仿真结果
    
    Args:
        executor: 执行器名称
        file_path: 仿真文件路径
        analysis_type: 分析类型
        data: 仿真数据
        measurements: 规范化测量结果列表（可选）
        raw_output: 原始输出（可选）
        duration_seconds: 执行耗时
        version: 版本号（应从 GraphState.iteration_count + 1 计算）
        session_id: 会话 ID（应从 GraphState.session_id 获取）
        
    Returns:
        SimulationResult: 成功的仿真结果
    """
    resolved_axis_metadata = infer_result_axis_metadata(
        analysis_type,
        data,
        x_axis_kind=axis_metadata.get("x_axis_kind") if axis_metadata else None,
        x_axis_label=axis_metadata.get("x_axis_label") if axis_metadata else None,
        x_axis_scale=axis_metadata.get("x_axis_scale") if axis_metadata else None,
        requested_x_range=axis_metadata.get("requested_x_range") if axis_metadata else None,
        actual_x_range=axis_metadata.get("actual_x_range") if axis_metadata else None,
        analysis_command=analysis_command or (axis_metadata.get("analysis_command") if axis_metadata else ""),
    )
    return SimulationResult(
        executor=executor,
        file_path=file_path,
        analysis_type=analysis_type,
        success=True,
        data=data,
        measurements=measurements,
        error=None,
        raw_output=raw_output,
        timestamp=datetime.now().isoformat(),
        duration_seconds=duration_seconds,
        version=version,
        session_id=session_id,
        x_axis_kind=resolved_axis_metadata["x_axis_kind"],
        x_axis_label=resolved_axis_metadata["x_axis_label"],
        x_axis_scale=resolved_axis_metadata["x_axis_scale"],
        requested_x_range=resolved_axis_metadata["requested_x_range"],
        actual_x_range=resolved_axis_metadata["actual_x_range"],
        analysis_command=resolved_axis_metadata["analysis_command"],
    )


def create_error_result(
    executor: str,
    file_path: str,
    analysis_type: str,
    error: Any,
    raw_output: Optional[str] = None,
    duration_seconds: float = 0.0,
    version: int = 1,
    session_id: str = "",
    analysis_command: str = "",
) -> SimulationResult:
    """
    创建失败的仿真结果
    
    Args:
        executor: 执行器名称
        file_path: 仿真文件路径
        analysis_type: 分析类型
        error: 错误信息（SimulationError 或字符串）
        raw_output: 原始输出（可选）
        duration_seconds: 执行耗时
        version: 版本号（应从 GraphState.iteration_count + 1 计算）
        session_id: 会话 ID（应从 GraphState.session_id 获取）
        
    Returns:
        SimulationResult: 失败的仿真结果
    """
    return SimulationResult(
        executor=executor,
        file_path=file_path,
        analysis_type=analysis_type,
        success=False,
        data=None,
        error=error,
        raw_output=raw_output,
        timestamp=datetime.now().isoformat(),
        duration_seconds=duration_seconds,
        version=version,
        session_id=session_id,
        analysis_command=analysis_command,
    )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SimulationData",
    "SimulationResult",
    "infer_result_axis_metadata",
    "create_success_result",
    "create_error_result",
]
