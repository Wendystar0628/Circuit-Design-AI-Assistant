# Waveform Data Service - Unified Waveform Data Access Layer
"""
波形数据服务

职责：
- 作为波形数据访问的统一入口
- 协调降采样和多分辨率金字塔
- 管理信号级缓存
- 为 UI 层提供标准化的数据接口

设计原则：
- 延迟加载：金字塔数据按需构建
- 缓存复用：相同信号的金字塔数据缓存复用
- 视口优化：根据显示区域返回最优分辨率数据

使用示例：
    from domain.simulation.data.waveform_data_service import WaveformDataService
    
    service = WaveformDataService()
    
    # 获取初始显示数据（低分辨率）
    data = service.get_initial_data(result, "V(out)", target_points=500)
    
    # 获取视口范围数据（缩放时调用）
    data = service.get_viewport_data(result, "V(out)", x_min=0.0, x_max=0.001, target_points=1000)
    
    # 构建原始数据表格快照
    table_snapshot = service.build_table_snapshot(result)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import OrderedDict

import numpy as np

from domain.simulation.data.resolution_pyramid import (
    PyramidData,
    build_pyramid,
    select_optimal_level,
    get_level_data,
    DEFAULT_PYRAMID_LEVELS,
)
from domain.simulation.models.simulation_result import SimulationResult, SimulationData


# ============================================================
# 数据类定义
# ============================================================

@dataclass
class WaveformData:
    """
    波形数据容器
    
    Attributes:
        signal_name: 信号名称（如 "V(out)"）
        x_data: X 轴数据（时间或频率）
        y_data: Y 轴数据（信号值）
        point_count: 数据点数量
        x_range: X 轴范围 (min, max)
        y_range: Y 轴范围 (min, max)
        is_downsampled: 是否经过降采样
        original_points: 原始数据点数（降采样前）
    """
    signal_name: str
    x_data: np.ndarray
    y_data: np.ndarray
    point_count: int = field(init=False)
    x_range: Tuple[float, float] = field(init=False)
    y_range: Tuple[float, float] = field(init=False)
    is_downsampled: bool = False
    original_points: int = 0
    
    def __post_init__(self):
        self.point_count = len(self.x_data)
        if self.point_count > 0:
            self.x_range = (float(np.min(self.x_data)), float(np.max(self.x_data)))
            self.y_range = (float(np.min(self.y_data)), float(np.max(self.y_data)))
        else:
            self.x_range = (0.0, 0.0)
            self.y_range = (0.0, 0.0)
        if self.original_points == 0:
            self.original_points = self.point_count


@dataclass
class TableSnapshot:
    result_path: str
    analysis_type: str
    version: int
    session_id: str
    timestamp: str
    x_label: str
    signal_names: List[str]
    x_values: np.ndarray
    signal_columns: Dict[str, np.ndarray]

    @property
    def total_rows(self) -> int:
        return int(len(self.x_values))


TABLE_COMPLEX_SUFFIXES = ("_mag", "_phase", "_real", "_imag")
TABLE_COMPLEX_SUFFIX_PRIORITY = {
    suffix: index for index, suffix in enumerate(TABLE_COMPLEX_SUFFIXES)
}


# ============================================================
# LRU 缓存实现
# ============================================================

class LRUCache:
    """
    简单的 LRU 缓存实现
    
    用于缓存信号的金字塔数据，避免重复构建。
    """
    
    def __init__(self, max_size: int = 32):
        """
        初始化缓存
        
        Args:
            max_size: 最大缓存条目数
        """
        self._max_size = max_size
        self._cache: OrderedDict[str, PyramidData] = OrderedDict()
    
    def get(self, key: str) -> Optional[PyramidData]:
        """获取缓存项，命中时移动到末尾"""
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None
    
    def put(self, key: str, value: PyramidData) -> None:
        """添加缓存项，超出容量时淘汰最旧的"""
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)
        self._cache[key] = value
    
    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()
    
    def size(self) -> int:
        """获取当前缓存大小"""
        return len(self._cache)


# ============================================================
# WaveformDataService - 波形数据服务
# ============================================================

class WaveformDataService:
    """
    波形数据服务
    
    提供波形数据访问的统一入口，协调降采样、缓存和多分辨率金字塔。
    
    特性：
    - 延迟构建：金字塔数据在首次访问时构建
    - LRU 缓存：相同信号的金字塔数据缓存复用
    - 视口优化：根据显示区域和目标点数返回最优分辨率
    """
    
    def __init__(self, cache_size: int = 32):
        """
        初始化服务
        
        Args:
            cache_size: 金字塔缓存大小（信号数量）
        """
        self._pyramid_cache = LRUCache(max_size=cache_size)
    
    def get_initial_data(
        self,
        result: SimulationResult,
        signal_name: str,
        target_points: int = 500,
    ) -> Optional[WaveformData]:
        """
        获取初始显示数据
        
        用于首次加载时显示低分辨率预览。
        
        Args:
            result: 仿真结果对象
            signal_name: 信号名称
            target_points: 目标点数（默认 500）
            
        Returns:
            WaveformData: 波形数据，若信号不存在返回 None
        """
        if not result.success or result.data is None:
            return None

        resolved_signal_name = self.resolve_display_signal_name(result, signal_name)
        if resolved_signal_name is None:
            return None
        
        x_data = self._get_x_axis(result.data)
        y_data = result.data.get_signal(resolved_signal_name)
        
        if x_data is None or y_data is None:
            return None
        
        pyramid = self._get_or_build_pyramid(result, resolved_signal_name, x_data, y_data)
        level_idx = select_optimal_level(pyramid, target_points)
        x_out, y_out = get_level_data(pyramid, level_idx)
        
        return WaveformData(
            signal_name=resolved_signal_name,
            x_data=x_out,
            y_data=y_out,
            is_downsampled=len(x_out) < pyramid.original_points,
            original_points=pyramid.original_points,
        )

    def get_viewport_data(
        self,
        result: SimulationResult,
        signal_name: str,
        x_min: float,
        x_max: float,
        target_points: int = 1000,
    ) -> Optional[WaveformData]:
        """
        获取视口范围数据
        
        用于缩放时获取指定范围的数据。
        
        Args:
            result: 仿真结果对象
            signal_name: 信号名称
            x_min: X 轴最小值
            x_max: X 轴最大值
            target_points: 目标点数
            
        Returns:
            WaveformData: 视口范围内的波形数据
        """
        if not result.success or result.data is None:
            return None

        resolved_signal_name = self.resolve_display_signal_name(result, signal_name)
        if resolved_signal_name is None:
            return None
        
        x_data = self._get_x_axis(result.data)
        y_data = result.data.get_signal(resolved_signal_name)
        
        if x_data is None or y_data is None:
            return None
        
        # 获取金字塔
        pyramid = self._get_or_build_pyramid(result, resolved_signal_name, x_data, y_data)
        
        # 计算视口范围内的数据点比例
        total_range = pyramid.x_range[1] - pyramid.x_range[0]
        if total_range <= 0:
            return None
        
        viewport_range = x_max - x_min
        viewport_ratio = viewport_range / total_range
        
        # 根据视口比例调整所需点数
        # 视口越小，需要的原始点数越少，可以使用更低分辨率
        estimated_points_in_viewport = int(pyramid.original_points * viewport_ratio)
        required_points = min(target_points, max(estimated_points_in_viewport, target_points))
        
        # 选择最优层级
        level_idx = select_optimal_level(pyramid, required_points)
        x_level, y_level = get_level_data(pyramid, level_idx)
        
        # 裁剪到视口范围
        mask = (x_level >= x_min) & (x_level <= x_max)
        x_out = x_level[mask]
        y_out = y_level[mask]
        
        if len(x_out) == 0:
            return None
        
        return WaveformData(
            signal_name=resolved_signal_name,
            x_data=x_out,
            y_data=y_out,
            is_downsampled=len(x_out) < pyramid.original_points,
            original_points=pyramid.original_points,
        )

    def get_full_resolution_data(
        self,
        result: SimulationResult,
        signal_name: str,
    ) -> Optional[WaveformData]:
        """
        获取原始分辨率数据
        
        用于数据导出或精确测量。
        
        Args:
            result: 仿真结果对象
            signal_name: 信号名称
            
        Returns:
            WaveformData: 完整分辨率的波形数据
        """
        if not result.success or result.data is None:
            return None

        resolved_signal_name = self.resolve_display_signal_name(result, signal_name)
        if resolved_signal_name is None:
            return None
        
        x_data = self._get_x_axis(result.data)
        y_data = result.data.get_signal(resolved_signal_name)
        
        if x_data is None or y_data is None:
            return None
        
        return WaveformData(
            signal_name=resolved_signal_name,
            x_data=x_data.copy(),
            y_data=y_data.copy(),
            is_downsampled=False,
            original_points=len(x_data),
        )
    
    def get_available_signals(self, result: SimulationResult) -> List[str]:
        """
        获取可用信号列表
        
        Args:
            result: 仿真结果对象
            
        Returns:
            List[str]: 信号名称列表
        """
        if not result.success or result.data is None:
            return []
        return result.data.get_signal_names()

    def get_display_signal_names(
        self,
        result: SimulationResult,
        signal_names: Optional[List[str]] = None,
    ) -> List[str]:
        if not result.success or result.data is None:
            return []

        data = result.data
        available_signals = data.get_signal_names()
        requested_signals = signal_names or available_signals

        resolved: List[str] = []
        seen = set()
        for signal_name in requested_signals:
            for resolved_name in self._expand_table_signal_name(data, signal_name):
                if resolved_name not in seen:
                    resolved.append(resolved_name)
                    seen.add(resolved_name)

        if signal_names is None:
            for signal_name in available_signals:
                for resolved_name in self._expand_table_signal_name(data, signal_name):
                    if resolved_name not in seen:
                        resolved.append(resolved_name)
                        seen.add(resolved_name)

        return sorted(
            resolved,
            key=lambda name: self._get_table_signal_sort_key(data, name),
        )

    def resolve_display_signal_name(
        self,
        result: SimulationResult,
        signal_name: str,
    ) -> Optional[str]:
        if not result.success or result.data is None:
            return None

        resolved_names = self._expand_table_signal_name(result.data, signal_name)
        if not resolved_names:
            return None

        return sorted(
            resolved_names,
            key=lambda name: self._get_table_signal_sort_key(result.data, name),
        )[0]

    def get_preferred_display_signal(self, result: SimulationResult) -> Optional[str]:
        if not result.success or result.data is None:
            return None

        display_signals = self.get_display_signal_names(result)
        if not display_signals:
            return None

        signal_types = getattr(result.data, 'signal_types', {})

        for signal_name in display_signals:
            if self.get_signal_type(signal_name, signal_types) == "voltage":
                return signal_name

        return display_signals[0]
    
    def get_classified_signals(self, result: SimulationResult) -> Dict[str, List[str]]:
        """
        获取分类后的信号列表
        
        将信号按类型分组，优先使用 SimulationData.signal_types 中的类型信息，
        回退时通过信号名称前缀推断。
        
        Args:
            result: 仿真结果对象
            
        Returns:
            Dict[str, List[str]]: {"电压": [...], "电流": [...], "其他": [...]}
        """
        classified: Dict[str, List[str]] = {
            "voltage": [],
            "current": [],
            "other": [],
        }
        
        if not result.success or result.data is None:
            return classified
        
        signal_types = getattr(result.data, 'signal_types', {})
        
        for name in self.get_display_signal_names(result):
            sig_type = self.get_signal_type(name, signal_types)
            classified[sig_type].append(name)
        
        return classified
    
    @staticmethod
    def get_signal_type(
        name: str,
        signal_types: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        判断单个信号的类型
        
        优先使用 signal_types 字典，回退时根据名称前缀推断。
        
        Args:
            name: 信号名称
            signal_types: 信号类型字典（可选）
            
        Returns:
            str: "voltage" / "current" / "other"
        """
        if signal_types and name in signal_types:
            return signal_types[name]
        
        upper = name.upper()
        if upper.startswith('V(') or upper.endswith(('_MAG', '_PHASE', '_REAL', '_IMAG')):
            base = name.rsplit('_', 1)[0] if '_' in name else name
            if signal_types and base in signal_types:
                return signal_types[base]
            if base.upper().startswith('V('):
                return "voltage"
            if base.upper().startswith('I('):
                return "current"
        if upper.startswith('I('):
            return "current"
        if upper.startswith('V('):
            return "voltage"
        return "other"
    
    @staticmethod
    def is_voltage_signal(name: str, signal_types: Optional[Dict[str, str]] = None) -> bool:
        """判断是否为电压信号"""
        return WaveformDataService.get_signal_type(name, signal_types) == "voltage"
    
    @staticmethod
    def is_current_signal(name: str, signal_types: Optional[Dict[str, str]] = None) -> bool:
        """判断是否为电流信号"""
        return WaveformDataService.get_signal_type(name, signal_types) == "current"
    
    def get_x_axis_label(self, result: SimulationResult) -> str:
        """
        获取 X 轴标签
        
        Args:
            result: 仿真结果对象
            
        Returns:
            str: "Time (s)" / "Frequency (Hz)" / "Sweep"
        """
        if not result.success or result.data is None:
            return "X"
        
        if result.data.time is not None:
            return "Time (s)"
        elif result.data.frequency is not None:
            return "Frequency (Hz)"
        elif result.data.sweep is not None:
            return result.data.sweep_name or "Sweep"
        return "X"

    def build_table_snapshot(
        self,
        result: SimulationResult,
        signal_names: Optional[List[str]] = None,
    ) -> Optional[TableSnapshot]:
        if not result.success or result.data is None:
            return None

        x_data, x_label = self._get_table_x_axis(result.data)
        if x_data is None:
            return None

        x_values = np.asarray(x_data, dtype=float).copy()
        resolved_signal_names = self.get_table_signal_names(result, signal_names)
        signal_columns: Dict[str, np.ndarray] = {}
        total_rows = len(x_values)

        for signal_name in resolved_signal_names:
            signal_data = result.data.get_signal(signal_name)
            column = np.full(total_rows, np.nan, dtype=float)
            if signal_data is not None:
                limit = min(len(signal_data), total_rows)
                for row in range(limit):
                    scalar_value = self._to_table_scalar_value(signal_data[row])
                    if scalar_value is not None:
                        column[row] = scalar_value
            signal_columns[signal_name] = column

        return TableSnapshot(
            result_path=result.file_path,
            analysis_type=result.analysis_type,
            version=result.version,
            session_id=result.session_id,
            timestamp=result.timestamp,
            x_label=x_label,
            signal_names=resolved_signal_names,
            x_values=x_values,
            signal_columns=signal_columns,
        )

    def get_signal_statistics(
        self,
        result: SimulationResult,
        signal_name: str,
    ) -> Optional[Dict[str, float]]:
        """
        获取信号统计信息
        
        Args:
            result: 仿真结果对象
            signal_name: 信号名称
            
        Returns:
            Dict: 统计信息字典，包含 min, max, mean, std, rms
        """
        if not result.success or result.data is None:
            return None
        
        y_data = result.data.get_signal(signal_name)
        if y_data is None or len(y_data) == 0:
            return None
        
        return {
            "min": float(np.min(y_data)),
            "max": float(np.max(y_data)),
            "mean": float(np.mean(y_data)),
            "std": float(np.std(y_data)),
            "rms": float(np.sqrt(np.mean(y_data ** 2))),
            "peak_to_peak": float(np.max(y_data) - np.min(y_data)),
        }
    
    def clear_cache(self) -> None:
        """清空金字塔缓存"""
        self._pyramid_cache.clear()
    
    def get_cache_size(self) -> int:
        """获取当前缓存大小"""
        return self._pyramid_cache.size()

    def get_table_signal_names(
        self,
        result: SimulationResult,
        signal_names: Optional[List[str]] = None,
    ) -> List[str]:
        if not result.success or result.data is None:
            return []

        data = result.data
        available_signals = data.get_signal_names()
        requested_signals = signal_names or available_signals

        resolved: List[str] = []
        seen = set()
        for signal_name in requested_signals:
            for resolved_name in self._expand_table_signal_name(data, signal_name):
                if resolved_name not in seen:
                    resolved.append(resolved_name)
                    seen.add(resolved_name)

        if signal_names is None:
            for signal_name in available_signals:
                for resolved_name in self._expand_table_signal_name(data, signal_name):
                    if resolved_name not in seen:
                        resolved.append(resolved_name)
                        seen.add(resolved_name)

        return sorted(
            resolved,
            key=lambda name: self._get_table_signal_sort_key(data, name),
        )

    # ============================================================
    # 内部辅助方法
    # ============================================================

    def _expand_table_signal_name(
        self,
        data: SimulationData,
        signal_name: str,
    ) -> List[str]:
        available_signals = set(data.get_signal_names())
        if signal_name not in available_signals:
            expanded_names = [
                f"{signal_name}{suffix}"
                for suffix in TABLE_COMPLEX_SUFFIXES
                if f"{signal_name}{suffix}" in available_signals
            ]
            return expanded_names

        signal_data = data.get_signal(signal_name)
        if signal_data is None:
            return []

        if np.iscomplexobj(signal_data):
            expanded_names = [
                f"{signal_name}{suffix}"
                for suffix in TABLE_COMPLEX_SUFFIXES
                if f"{signal_name}{suffix}" in available_signals
            ]
            return expanded_names

        return [signal_name]

    def _get_table_signal_sort_key(
        self,
        data: SimulationData,
        signal_name: str,
    ) -> Tuple[int, int, str, int, str]:
        signal_types = getattr(data, 'signal_types', {})
        base_name = self._get_table_signal_base_name(signal_name)
        component_suffix = signal_name[len(base_name):] if signal_name.startswith(base_name) else ""
        signal_type = self.get_signal_type(base_name, signal_types)

        type_rank = {
            "voltage": 0,
            "current": 1,
            "other": 2,
        }.get(signal_type, 2)

        name_lower = base_name.lower()
        if "out" in name_lower:
            role_rank = 0
        elif "in" in name_lower:
            role_rank = 1
        else:
            role_rank = 2

        component_rank = TABLE_COMPLEX_SUFFIX_PRIORITY.get(component_suffix, len(TABLE_COMPLEX_SUFFIX_PRIORITY))
        return (role_rank, type_rank, base_name.lower(), component_rank, signal_name.lower())

    def _get_table_signal_base_name(self, signal_name: str) -> str:
        for suffix in TABLE_COMPLEX_SUFFIXES:
            if signal_name.endswith(suffix):
                return signal_name[:-len(suffix)]
        return signal_name

    def _to_table_scalar_value(self, value: object) -> Optional[float]:
        if value is None:
            return None

        if np.iscomplexobj(value):
            complex_value = complex(value)
            if abs(complex_value.imag) > 1e-15:
                return None
            return float(complex_value.real)

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _get_table_x_axis(self, data: SimulationData) -> Tuple[Optional[np.ndarray], str]:
        if data.time is not None:
            return data.time, "Time (s)"
        if data.frequency is not None:
            return data.frequency, "Frequency (Hz)"
        if data.sweep is not None:
            return data.sweep, data.sweep_name or "Sweep"

        row_count = 0
        for signal_name in data.get_signal_names():
            signal_data = data.get_signal(signal_name)
            if signal_data is not None:
                row_count = max(row_count, len(signal_data))

        if row_count > 0:
            return np.arange(row_count, dtype=float), "Index"

        return None, "X"
    
    def _get_x_axis(self, data: SimulationData) -> Optional[np.ndarray]:
        """获取 X 轴数据（时间、频率或 DC 扫描轴）"""
        if data.time is not None:
            return data.time
        elif data.frequency is not None:
            return data.frequency
        elif data.sweep is not None:
            return data.sweep
        return None
    
    def _get_or_build_pyramid(
        self,
        result: SimulationResult,
        signal_name: str,
        x_data: np.ndarray,
        y_data: np.ndarray,
    ) -> PyramidData:
        """
        获取或构建信号的金字塔数据
        
        使用 result.timestamp + signal_name 作为缓存键。
        """
        cache_key = f"{result.timestamp}:{signal_name}"
        
        # 尝试从缓存获取
        cached = self._pyramid_cache.get(cache_key)
        if cached is not None:
            return cached
        
        # 构建新的金字塔
        pyramid = build_pyramid(x_data, y_data, DEFAULT_PYRAMID_LEVELS)
        
        # 存入缓存
        self._pyramid_cache.put(cache_key, pyramid)
        
        return pyramid


# ============================================================
# 模块级单例
# ============================================================

waveform_data_service = WaveformDataService()
"""模块级单例实例，便于直接导入使用"""


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 数据类
    "WaveformData",
    "TableSnapshot",
    # 服务类
    "WaveformDataService",
    # 单例
    "waveform_data_service",
]
