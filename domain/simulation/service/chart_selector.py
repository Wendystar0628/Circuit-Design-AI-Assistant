# ChartSelector - Chart Type Selection Service
"""
图表类型选择器

职责：
- 管理用户选择的可视化图表类型
- 支持图表的启用/禁用和显示顺序配置
- 根据分析类型推荐相关图表
- 持久化选择到项目配置

设计原则：
- 与 AnalysisSelector 分工明确：AnalysisSelector 管理"执行哪些分析"，
  本服务管理"显示哪些图表"
- 图表类型与分析类型存在关联关系
- 布局配置由 UI 层处理，领域层只关心启用状态和显示顺序

配置存储路径：
- {project_root}/.circuit_ai/chart_selection.json

使用示例：
    from domain.simulation.service.chart_selector import chart_selector
    
    # 获取选中的图表类型
    selections = chart_selector.get_selected_charts()
    
    # 启用/禁用图表
    chart_selector.set_chart_enabled(ChartType.BODE_COMBINED, True)
    
    # 根据分析类型获取推荐图表
    recommended = chart_selector.get_recommended_charts([AnalysisType.AC])
    
    # 保存到项目
    chart_selector.save_selection("/path/to/project")
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from shared.event_bus import EventBus


# ============================================================
# 常量定义
# ============================================================

CONFIG_FILE_NAME = "chart_selection.json"
CONFIG_DIR = ".circuit_ai"
CONFIG_VERSION = "1.0"

# 事件常量（在 event_types.py 中定义）
EVENT_CHART_SELECTION_CHANGED = "chart_selection_changed"


# ============================================================
# ChartType - 图表类型枚举
# ============================================================

class ChartType(Enum):
    """
    图表类型枚举
    
    基础波形图：
    - WAVEFORM_TIME: 时域波形图
    - WAVEFORM_FREQ: 频域波形图
    
    Bode 图：
    - BODE_MAGNITUDE: Bode 幅度图
    - BODE_PHASE: Bode 相位图
    - BODE_COMBINED: Bode 组合图（幅度+相位）
    
    特性曲线：
    - DC_TRANSFER: DC 传输特性曲线
    - DC_SWEEP: DC 扫描曲线
    
    频谱分析：
    - FFT_SPECTRUM: FFT 频谱图
    - HARMONIC_BAR: 谐波柱状图
    
    统计图表：
    - HISTOGRAM: 直方图（蒙特卡洛）
    - SCATTER: 散点图
    - BOX_PLOT: 箱线图
    
    参数扫描图表：
    - CONTOUR: 等高线图
    - HEATMAP: 热力图
    - SURFACE_3D: 3D 曲面图
    
    敏感度图表：
    - TORNADO: 龙卷风图
    - SENSITIVITY_BAR: 敏感度柱状图
    
    PVT 图表：
    - CORNER_COMPARISON: 角点对比图
    - CORNER_TABLE: 角点数据表格
    
    噪声图表：
    - NOISE_SPECTRUM: 噪声频谱图
    - NOISE_DENSITY: 噪声密度图
    """
    # 基础波形图
    WAVEFORM_TIME = "waveform_time"
    WAVEFORM_FREQ = "waveform_freq"
    
    # Bode 图
    BODE_MAGNITUDE = "bode_mag"
    BODE_PHASE = "bode_phase"
    BODE_COMBINED = "bode_combined"
    
    # 特性曲线
    DC_TRANSFER = "dc_transfer"
    DC_SWEEP = "dc_sweep"
    
    # 频谱分析
    FFT_SPECTRUM = "fft_spectrum"
    HARMONIC_BAR = "harmonic_bar"
    
    # 统计图表
    HISTOGRAM = "histogram"
    SCATTER = "scatter"
    BOX_PLOT = "box_plot"
    
    # 参数扫描图表
    CONTOUR = "contour"
    HEATMAP = "heatmap"
    SURFACE_3D = "surface_3d"
    
    # 敏感度图表
    TORNADO = "tornado"
    SENSITIVITY_BAR = "sensitivity_bar"
    
    # PVT 图表
    CORNER_COMPARISON = "corner_compare"
    CORNER_TABLE = "corner_table"
    
    # 噪声图表
    NOISE_SPECTRUM = "noise_spectrum"
    NOISE_DENSITY = "noise_density"
    
    @classmethod
    def get_display_name(cls, chart_type: "ChartType") -> str:
        """获取图表类型的显示名称"""
        names = {
            cls.WAVEFORM_TIME: "时域波形图",
            cls.WAVEFORM_FREQ: "频域波形图",
            cls.BODE_MAGNITUDE: "Bode 幅度图",
            cls.BODE_PHASE: "Bode 相位图",
            cls.BODE_COMBINED: "Bode 组合图",
            cls.DC_TRANSFER: "DC 传输特性",
            cls.DC_SWEEP: "DC 扫描曲线",
            cls.FFT_SPECTRUM: "FFT 频谱图",
            cls.HARMONIC_BAR: "谐波柱状图",
            cls.HISTOGRAM: "直方图",
            cls.SCATTER: "散点图",
            cls.BOX_PLOT: "箱线图",
            cls.CONTOUR: "等高线图",
            cls.HEATMAP: "热力图",
            cls.SURFACE_3D: "3D 曲面图",
            cls.TORNADO: "龙卷风图",
            cls.SENSITIVITY_BAR: "敏感度柱状图",
            cls.CORNER_COMPARISON: "角点对比图",
            cls.CORNER_TABLE: "角点数据表格",
            cls.NOISE_SPECTRUM: "噪声频谱图",
            cls.NOISE_DENSITY: "噪声密度图",
        }
        return names.get(chart_type, chart_type.value)
    
    @classmethod
    def get_category(cls, chart_type: "ChartType") -> str:
        """获取图表类型所属类别"""
        categories = {
            cls.WAVEFORM_TIME: "waveform",
            cls.WAVEFORM_FREQ: "waveform",
            cls.BODE_MAGNITUDE: "bode",
            cls.BODE_PHASE: "bode",
            cls.BODE_COMBINED: "bode",
            cls.DC_TRANSFER: "dc",
            cls.DC_SWEEP: "dc",
            cls.FFT_SPECTRUM: "spectrum",
            cls.HARMONIC_BAR: "spectrum",
            cls.HISTOGRAM: "statistics",
            cls.SCATTER: "statistics",
            cls.BOX_PLOT: "statistics",
            cls.CONTOUR: "sweep",
            cls.HEATMAP: "sweep",
            cls.SURFACE_3D: "sweep",
            cls.TORNADO: "sensitivity",
            cls.SENSITIVITY_BAR: "sensitivity",
            cls.CORNER_COMPARISON: "pvt",
            cls.CORNER_TABLE: "pvt",
            cls.NOISE_SPECTRUM: "noise",
            cls.NOISE_DENSITY: "noise",
        }
        return categories.get(chart_type, "other")


# ============================================================
# ChartSelection - 图表选择数据类
# ============================================================

@dataclass
class ChartSelection:
    """
    图表选择数据类
    
    Attributes:
        chart_type: 图表类型
        enabled: 是否显示
        display_order: 显示顺序（数字越小越靠前）
    """
    chart_type: ChartType
    enabled: bool
    display_order: int
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "type": self.chart_type.value,
            "enabled": self.enabled,
            "order": self.display_order,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChartSelection":
        """从字典反序列化"""
        return cls(
            chart_type=ChartType(data["type"]),
            enabled=data.get("enabled", False),
            display_order=data.get("order", 99),
        )


# ============================================================
# ChartValidationResult - 校验结果
# ============================================================

@dataclass
class ChartValidationResult:
    """
    图表选择校验结果
    
    Attributes:
        is_valid: 是否有效
        warnings: 警告列表
        errors: 错误列表
    """
    is_valid: bool
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    @classmethod
    def success(cls) -> "ChartValidationResult":
        """创建成功结果"""
        return cls(is_valid=True)
    
    def add_warning(self, message: str) -> None:
        """添加警告"""
        self.warnings.append(message)
    
    def add_error(self, message: str) -> None:
        """添加错误"""
        self.errors.append(message)
        self.is_valid = False


# ============================================================
# 图表与分析类型的关联映射
# ============================================================

# 延迟导入避免循环依赖
def _get_analysis_type():
    from domain.simulation.service.analysis_selector import AnalysisType
    return AnalysisType


def _build_chart_analysis_mapping() -> Dict[str, List[ChartType]]:
    """
    构建分析类型到推荐图表的映射
    
    Returns:
        Dict[str, List[ChartType]]: 分析类型值 -> 推荐图表列表
    """
    return {
        "op": [],  # 工作点分析通常不需要图表
        "ac": [
            ChartType.BODE_COMBINED,
            ChartType.BODE_MAGNITUDE,
            ChartType.BODE_PHASE,
            ChartType.WAVEFORM_FREQ,
        ],
        "dc": [
            ChartType.DC_TRANSFER,
            ChartType.DC_SWEEP,
        ],
        "tran": [
            ChartType.WAVEFORM_TIME,
            ChartType.FFT_SPECTRUM,
            ChartType.HARMONIC_BAR,
        ],
        "noise": [
            ChartType.NOISE_SPECTRUM,
            ChartType.NOISE_DENSITY,
        ],
        "pvt": [
            ChartType.CORNER_COMPARISON,
            ChartType.CORNER_TABLE,
        ],
        "monte_carlo": [
            ChartType.HISTOGRAM,
            ChartType.BOX_PLOT,
            ChartType.SCATTER,
        ],
        "parametric": [
            ChartType.CONTOUR,
            ChartType.HEATMAP,
            ChartType.SURFACE_3D,
        ],
        "worst_case": [
            ChartType.SENSITIVITY_BAR,
        ],
        "sensitivity": [
            ChartType.TORNADO,
            ChartType.SENSITIVITY_BAR,
        ],
    }


# ============================================================
# 默认选择配置
# ============================================================

def _get_default_selections() -> List[ChartSelection]:
    """获取默认选择配置"""
    return [
        # 基础波形图 - 默认启用
        ChartSelection(ChartType.WAVEFORM_TIME, enabled=True, display_order=1),
        ChartSelection(ChartType.WAVEFORM_FREQ, enabled=False, display_order=2),
        # Bode 图 - 组合图默认启用
        ChartSelection(ChartType.BODE_COMBINED, enabled=True, display_order=3),
        ChartSelection(ChartType.BODE_MAGNITUDE, enabled=False, display_order=4),
        ChartSelection(ChartType.BODE_PHASE, enabled=False, display_order=5),
        # DC 图表
        ChartSelection(ChartType.DC_TRANSFER, enabled=True, display_order=6),
        ChartSelection(ChartType.DC_SWEEP, enabled=False, display_order=7),
        # 频谱分析
        ChartSelection(ChartType.FFT_SPECTRUM, enabled=False, display_order=8),
        ChartSelection(ChartType.HARMONIC_BAR, enabled=False, display_order=9),
        # 统计图表 - 默认禁用
        ChartSelection(ChartType.HISTOGRAM, enabled=False, display_order=10),
        ChartSelection(ChartType.SCATTER, enabled=False, display_order=11),
        ChartSelection(ChartType.BOX_PLOT, enabled=False, display_order=12),
        # 参数扫描图表 - 默认禁用
        ChartSelection(ChartType.CONTOUR, enabled=False, display_order=13),
        ChartSelection(ChartType.HEATMAP, enabled=False, display_order=14),
        ChartSelection(ChartType.SURFACE_3D, enabled=False, display_order=15),
        # 敏感度图表 - 默认禁用
        ChartSelection(ChartType.TORNADO, enabled=False, display_order=16),
        ChartSelection(ChartType.SENSITIVITY_BAR, enabled=False, display_order=17),
        # PVT 图表 - 默认禁用
        ChartSelection(ChartType.CORNER_COMPARISON, enabled=False, display_order=18),
        ChartSelection(ChartType.CORNER_TABLE, enabled=False, display_order=19),
        # 噪声图表 - 默认禁用
        ChartSelection(ChartType.NOISE_SPECTRUM, enabled=False, display_order=20),
        ChartSelection(ChartType.NOISE_DENSITY, enabled=False, display_order=21),
    ]



# ============================================================
# ChartSelector - 图表类型选择器
# ============================================================

class ChartSelector:
    """
    图表类型选择器
    
    管理用户选择的可视化图表类型，支持持久化和事件通知。
    """
    
    def __init__(self, event_bus: Optional[EventBus] = None):
        """
        初始化选择器
        
        Args:
            event_bus: 事件总线（可选，用于发布选择变更事件）
        """
        self._logger = logging.getLogger(__name__)
        self._event_bus = event_bus
        self._selections: Dict[ChartType, ChartSelection] = {}
        self._chart_analysis_mapping = _build_chart_analysis_mapping()
        self._reset_to_default()
    
    def _get_event_bus(self) -> Optional[EventBus]:
        """获取事件总线"""
        if self._event_bus is not None:
            return self._event_bus
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SERVICE_EVENT_BUS
            return ServiceLocator.get(SERVICE_EVENT_BUS)
        except Exception:
            return None
    
    def _get_config_path(self, project_root: str) -> Path:
        """获取配置文件路径"""
        return Path(project_root) / CONFIG_DIR / CONFIG_FILE_NAME
    
    # ============================================================
    # 查询方法
    # ============================================================
    
    def get_available_charts(self) -> List[ChartType]:
        """
        获取所有可用的图表类型
        
        Returns:
            List[ChartType]: 所有图表类型列表
        """
        return list(ChartType)
    
    def get_charts_by_category(self, category: str) -> List[ChartType]:
        """
        获取指定类别的图表类型
        
        Args:
            category: 类别名称（waveform/bode/dc/spectrum/statistics/sweep/sensitivity/pvt/noise）
            
        Returns:
            List[ChartType]: 该类别的图表类型列表
        """
        return [ct for ct in ChartType if ChartType.get_category(ct) == category]
    
    def get_all_selections(self) -> List[ChartSelection]:
        """
        获取所有图表选择
        
        Returns:
            List[ChartSelection]: 所有选择列表
        """
        return list(self._selections.values())
    
    def get_selected_charts(self) -> List[ChartSelection]:
        """
        获取当前选中（启用）的图表列表
        
        Returns:
            List[ChartSelection]: 启用的选择列表，按显示顺序排序
        """
        enabled = [s for s in self._selections.values() if s.enabled]
        enabled.sort(key=lambda s: s.display_order)
        return enabled
    
    def get_selection(self, chart_type: ChartType) -> Optional[ChartSelection]:
        """
        获取指定图表类型的选择
        
        Args:
            chart_type: 图表类型
            
        Returns:
            Optional[ChartSelection]: 选择对象，若不存在返回 None
        """
        return self._selections.get(chart_type)
    
    def is_enabled(self, chart_type: ChartType) -> bool:
        """
        检查指定图表类型是否启用
        
        Args:
            chart_type: 图表类型
            
        Returns:
            bool: 是否启用
        """
        selection = self._selections.get(chart_type)
        return selection.enabled if selection else False
    
    def get_chart_layout(self) -> List[ChartSelection]:
        """
        获取按显示顺序排列的图表布局
        
        仅返回启用的图表，按 display_order 升序排列。
        
        Returns:
            List[ChartSelection]: 排序后的图表选择列表
        """
        return self.get_selected_charts()
    
    def get_available_charts_for_analyses(
        self,
        analysis_types: List[str],
    ) -> List[ChartType]:
        """
        根据分析类型获取可用的图表类型
        
        Args:
            analysis_types: 分析类型值列表（如 ["ac", "tran"]）
            
        Returns:
            List[ChartType]: 可用的图表类型列表（去重）
        """
        available: Set[ChartType] = set()
        for analysis_type in analysis_types:
            charts = self._chart_analysis_mapping.get(analysis_type, [])
            available.update(charts)
        return list(available)
    
    def get_recommended_charts(
        self,
        analysis_types: List[str],
    ) -> List[ChartType]:
        """
        根据分析类型获取推荐的图表类型
        
        推荐逻辑：
        - 返回与分析类型关联的图表
        - 优先返回组合图（如 BODE_COMBINED 而非单独的幅度/相位图）
        
        Args:
            analysis_types: 分析类型值列表
            
        Returns:
            List[ChartType]: 推荐的图表类型列表
        """
        recommended: List[ChartType] = []
        seen_categories: Set[str] = set()
        
        for analysis_type in analysis_types:
            charts = self._chart_analysis_mapping.get(analysis_type, [])
            for chart in charts:
                category = ChartType.get_category(chart)
                # 每个类别只推荐第一个（通常是组合图或最常用的）
                if category not in seen_categories:
                    recommended.append(chart)
                    seen_categories.add(category)
        
        return recommended
    
    # ============================================================
    # 修改方法
    # ============================================================
    
    def set_chart_enabled(
        self,
        chart_type: ChartType,
        enabled: bool,
        *,
        publish_event: bool = True,
    ) -> None:
        """
        启用/禁用指定图表
        
        Args:
            chart_type: 图表类型
            enabled: 是否启用
            publish_event: 是否发布变更事件
        """
        if chart_type not in self._selections:
            self._logger.warning(f"未知的图表类型: {chart_type}")
            return
        
        old_enabled = self._selections[chart_type].enabled
        if old_enabled == enabled:
            return
        
        self._selections[chart_type].enabled = enabled
        self._logger.debug(
            f"图表类型 {chart_type.value} 已{'启用' if enabled else '禁用'}"
        )
        
        if publish_event:
            self._publish_selection_changed_event("api")
    
    def set_chart_order(
        self,
        chart_type: ChartType,
        order: int,
    ) -> None:
        """
        设置图表显示顺序
        
        Args:
            chart_type: 图表类型
            order: 显示顺序（数字越小越靠前）
        """
        if chart_type not in self._selections:
            self._logger.warning(f"未知的图表类型: {chart_type}")
            return
        
        self._selections[chart_type].display_order = order
    
    def enable_charts_for_analyses(
        self,
        analysis_types: List[str],
        *,
        publish_event: bool = True,
    ) -> None:
        """
        根据分析类型启用推荐的图表
        
        Args:
            analysis_types: 分析类型值列表
            publish_event: 是否发布变更事件
        """
        recommended = self.get_recommended_charts(analysis_types)
        for chart_type in recommended:
            if chart_type in self._selections:
                self._selections[chart_type].enabled = True
        
        if publish_event:
            self._publish_selection_changed_event("api")
    
    def disable_all_charts(self, *, publish_event: bool = True) -> None:
        """禁用所有图表"""
        for selection in self._selections.values():
            selection.enabled = False
        
        if publish_event:
            self._publish_selection_changed_event("api")
    
    def set_selections_from_list(
        self,
        enabled_types: List[ChartType],
        *,
        publish_event: bool = True,
    ) -> None:
        """
        从列表设置启用的图表类型
        
        Args:
            enabled_types: 要启用的图表类型列表
            publish_event: 是否发布变更事件
        """
        for chart_type in ChartType:
            if chart_type in self._selections:
                self._selections[chart_type].enabled = chart_type in enabled_types
        
        if publish_event:
            self._publish_selection_changed_event("api")
    
    # ============================================================
    # 持久化方法
    # ============================================================
    
    def save_selection(self, project_root: str) -> bool:
        """
        保存选择到项目配置
        
        Args:
            project_root: 项目根目录路径
            
        Returns:
            bool: 是否保存成功
        """
        config_path = self._get_config_path(project_root)
        
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "version": CONFIG_VERSION,
                "selections": [s.to_dict() for s in self._selections.values()],
            }
            
            content = json.dumps(data, indent=2, ensure_ascii=False)
            config_path.write_text(content, encoding="utf-8")
            
            self._logger.info(f"图表选择已保存: {config_path}")
            return True
            
        except Exception as e:
            self._logger.error(f"保存图表选择失败: {e}")
            return False
    
    def load_selection(self, project_root: str) -> bool:
        """
        从项目配置加载选择
        
        如果配置文件不存在，保持当前选择不变。
        
        Args:
            project_root: 项目根目录路径
            
        Returns:
            bool: 是否加载成功
        """
        config_path = self._get_config_path(project_root)
        
        if not config_path.exists():
            self._logger.debug(f"图表选择配置不存在，使用默认配置: {config_path}")
            return True
        
        try:
            content = config_path.read_text(encoding="utf-8")
            data = json.loads(content)
            
            # 解析选择列表
            selections_data = data.get("selections", [])
            for item in selections_data:
                try:
                    selection = ChartSelection.from_dict(item)
                    self._selections[selection.chart_type] = selection
                except (KeyError, ValueError) as e:
                    self._logger.warning(f"跳过无效的选择项: {item}, 错误: {e}")
            
            self._logger.info(f"图表选择已加载: {config_path}")
            self._publish_selection_changed_event("load")
            return True
            
        except json.JSONDecodeError as e:
            self._logger.warning(f"图表选择配置 JSON 解析失败: {e}")
            return False
        except Exception as e:
            self._logger.error(f"加载图表选择失败: {e}")
            return False
    
    def reset_to_default(self, *, publish_event: bool = True) -> None:
        """
        重置为默认选择
        
        Args:
            publish_event: 是否发布变更事件
        """
        self._reset_to_default()
        
        if publish_event:
            self._publish_selection_changed_event("api")
    
    def _reset_to_default(self) -> None:
        """内部重置方法（不发布事件）"""
        self._selections.clear()
        for selection in _get_default_selections():
            self._selections[selection.chart_type] = selection
    
    # ============================================================
    # 校验方法
    # ============================================================
    
    def validate_selection(
        self,
        analysis_types: Optional[List[str]] = None,
    ) -> ChartValidationResult:
        """
        校验选择的有效性
        
        校验规则：
        - 若启用了分析类型，检查是否有对应的图表被启用
        
        Args:
            analysis_types: 当前启用的分析类型列表（可选）
            
        Returns:
            ChartValidationResult: 校验结果
        """
        result = ChartValidationResult.success()
        
        enabled_charts = self.get_selected_charts()
        
        # 检查是否有图表被启用（仅警告，不阻止）
        if not enabled_charts:
            result.add_warning("未启用任何图表，仿真结果将不会可视化显示")
        
        # 检查分析类型与图表的匹配
        if analysis_types:
            available = self.get_available_charts_for_analyses(analysis_types)
            enabled_types = {s.chart_type for s in enabled_charts}
            
            # 检查是否有可用图表未被启用
            missing = set(available) - enabled_types
            if missing and not enabled_types.intersection(available):
                missing_names = [ChartType.get_display_name(ct) for ct in list(missing)[:3]]
                result.add_warning(
                    f"当前分析类型有可用图表未启用: {', '.join(missing_names)}"
                )
        
        return result
    
    # ============================================================
    # 事件发布
    # ============================================================
    
    def _publish_selection_changed_event(self, source: str) -> None:
        """发布选择变更事件"""
        bus = self._get_event_bus()
        if bus:
            enabled = [s.chart_type.value for s in self.get_selected_charts()]
            disabled = [
                s.chart_type.value
                for s in self._selections.values()
                if not s.enabled
            ]
            
            bus.publish(EVENT_CHART_SELECTION_CHANGED, {
                "enabled_charts": enabled,
                "disabled_charts": disabled,
                "source": source,
            })


# ============================================================
# 模块级单例
# ============================================================

chart_selector = ChartSelector()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ChartType",
    "ChartSelection",
    "ChartSelector",
    "ChartValidationResult",
    "chart_selector",
    "CONFIG_FILE_NAME",
    "CONFIG_DIR",
    "EVENT_CHART_SELECTION_CHANGED",
]
