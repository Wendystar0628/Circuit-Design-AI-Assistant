# AnalysisSelector - Analysis Type Selection Service
"""
分析类型选择器

职责：
- 管理用户选择的仿真分析类型
- 支持基础分析和高级分析的选择
- 持久化选择到项目配置
- 提供按优先级排序的执行顺序

设计原则：
- 与 SimulationConfigService 分工明确：本服务管理"执行哪些分析"，
  SimulationConfigService 管理"分析的参数配置"
- 基础分析默认启用，高级分析默认禁用
- 选择变更时发布事件通知订阅者

配置存储路径：
- {project_root}/.circuit_ai/analysis_selection.json

使用示例：
    from domain.simulation.service.analysis_selector import analysis_selector
    
    # 获取选中的分析类型
    selections = analysis_selector.get_selected_analyses()
    
    # 启用/禁用分析
    analysis_selector.set_analysis_enabled(AnalysisType.PVT, True)
    
    # 获取执行顺序
    order = analysis_selector.get_execution_order()
    
    # 保存到项目
    analysis_selector.save_selection("/path/to/project")
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.event_bus import EventBus
from shared.event_types import EVENT_ANALYSIS_SELECTION_CHANGED


# ============================================================
# 常量定义
# ============================================================

CONFIG_FILE_NAME = "analysis_selection.json"
CONFIG_DIR = ".circuit_ai"
CONFIG_VERSION = "1.0"


# ============================================================
# AnalysisType - 分析类型枚举
# ============================================================

class AnalysisType(Enum):
    """
    分析类型枚举
    
    基础分析：
    - OP: 工作点分析（通常作为其他分析的前置）
    - AC: AC 小信号分析
    - DC: DC 扫描分析
    - TRANSIENT: 瞬态分析
    - NOISE: 噪声分析
    
    高级分析：
    - PVT: PVT 角点分析
    - MONTE_CARLO: 蒙特卡洛分析
    - PARAMETRIC: 参数扫描
    - WORST_CASE: 最坏情况分析
    - SENSITIVITY: 敏感度分析
    """
    # 基础分析
    OP = "op"
    AC = "ac"
    DC = "dc"
    TRANSIENT = "tran"
    NOISE = "noise"
    
    # 高级分析
    PVT = "pvt"
    MONTE_CARLO = "monte_carlo"
    PARAMETRIC = "parametric"
    WORST_CASE = "worst_case"
    SENSITIVITY = "sensitivity"
    
    @classmethod
    def is_basic(cls, analysis_type: "AnalysisType") -> bool:
        """判断是否为基础分析类型"""
        return analysis_type in (cls.OP, cls.AC, cls.DC, cls.TRANSIENT, cls.NOISE)
    
    @classmethod
    def is_advanced(cls, analysis_type: "AnalysisType") -> bool:
        """判断是否为高级分析类型"""
        return analysis_type in (
            cls.PVT, cls.MONTE_CARLO, cls.PARAMETRIC,
            cls.WORST_CASE, cls.SENSITIVITY
        )
    
    @classmethod
    def get_display_name(cls, analysis_type: "AnalysisType") -> str:
        """获取分析类型的显示名称"""
        names = {
            cls.OP: "工作点分析 (OP)",
            cls.AC: "AC 小信号分析",
            cls.DC: "DC 扫描分析",
            cls.TRANSIENT: "瞬态分析 (TRAN)",
            cls.NOISE: "噪声分析",
            cls.PVT: "PVT 角点分析",
            cls.MONTE_CARLO: "蒙特卡洛分析",
            cls.PARAMETRIC: "参数扫描",
            cls.WORST_CASE: "最坏情况分析",
            cls.SENSITIVITY: "敏感度分析",
        }
        return names.get(analysis_type, analysis_type.value)


# ============================================================
# AnalysisSelection - 分析选择数据类
# ============================================================

@dataclass
class AnalysisSelection:
    """
    分析选择数据类
    
    Attributes:
        analysis_type: 分析类型
        enabled: 是否启用
        priority: 执行优先级（数字越小越先执行）
    """
    analysis_type: AnalysisType
    enabled: bool
    priority: int
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "type": self.analysis_type.value,
            "enabled": self.enabled,
            "priority": self.priority,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnalysisSelection":
        """从字典反序列化"""
        return cls(
            analysis_type=AnalysisType(data["type"]),
            enabled=data.get("enabled", False),
            priority=data.get("priority", 99),
        )


# ============================================================
# ValidationResult - 校验结果
# ============================================================

@dataclass
class SelectionValidationResult:
    """
    选择校验结果
    
    Attributes:
        is_valid: 是否有效
        warnings: 警告列表（不阻止执行，但提示用户）
        errors: 错误列表（阻止执行）
    """
    is_valid: bool
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    @classmethod
    def success(cls) -> "SelectionValidationResult":
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
# 默认选择配置
# ============================================================

def _get_default_selections() -> List[AnalysisSelection]:
    """获取默认选择配置"""
    return [
        # 基础分析 - 默认启用
        AnalysisSelection(AnalysisType.OP, enabled=True, priority=0),
        AnalysisSelection(AnalysisType.AC, enabled=True, priority=1),
        AnalysisSelection(AnalysisType.DC, enabled=True, priority=2),
        AnalysisSelection(AnalysisType.TRANSIENT, enabled=True, priority=3),
        AnalysisSelection(AnalysisType.NOISE, enabled=False, priority=4),
        # 高级分析 - 默认禁用
        AnalysisSelection(AnalysisType.PVT, enabled=False, priority=10),
        AnalysisSelection(AnalysisType.MONTE_CARLO, enabled=False, priority=11),
        AnalysisSelection(AnalysisType.PARAMETRIC, enabled=False, priority=12),
        AnalysisSelection(AnalysisType.WORST_CASE, enabled=False, priority=13),
        AnalysisSelection(AnalysisType.SENSITIVITY, enabled=False, priority=14),
    ]


# ============================================================
# AnalysisSelector - 分析类型选择器
# ============================================================

class AnalysisSelector:
    """
    分析类型选择器
    
    管理用户选择的仿真分析类型，支持持久化和事件通知。
    """
    
    def __init__(self, event_bus: Optional[EventBus] = None):
        """
        初始化选择器
        
        Args:
            event_bus: 事件总线（可选，用于发布选择变更事件）
        """
        self._logger = logging.getLogger(__name__)
        self._event_bus = event_bus
        self._selections: Dict[AnalysisType, AnalysisSelection] = {}
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
    
    def get_available_analyses(self) -> List[AnalysisType]:
        """
        获取所有可用的分析类型
        
        Returns:
            List[AnalysisType]: 所有分析类型列表
        """
        return list(AnalysisType)
    
    def get_basic_analyses(self) -> List[AnalysisType]:
        """
        获取基础分析类型列表
        
        Returns:
            List[AnalysisType]: 基础分析类型列表
        """
        return [t for t in AnalysisType if AnalysisType.is_basic(t)]
    
    def get_advanced_analyses(self) -> List[AnalysisType]:
        """
        获取高级分析类型列表
        
        Returns:
            List[AnalysisType]: 高级分析类型列表
        """
        return [t for t in AnalysisType if AnalysisType.is_advanced(t)]
    
    def get_all_selections(self) -> List[AnalysisSelection]:
        """
        获取所有分析选择
        
        Returns:
            List[AnalysisSelection]: 所有选择列表
        """
        return list(self._selections.values())
    
    def get_selected_analyses(self) -> List[AnalysisSelection]:
        """
        获取当前选中（启用）的分析列表
        
        Returns:
            List[AnalysisSelection]: 启用的选择列表
        """
        return [s for s in self._selections.values() if s.enabled]
    
    def get_selection(self, analysis_type: AnalysisType) -> Optional[AnalysisSelection]:
        """
        获取指定分析类型的选择
        
        Args:
            analysis_type: 分析类型
            
        Returns:
            Optional[AnalysisSelection]: 选择对象，若不存在返回 None
        """
        return self._selections.get(analysis_type)
    
    def is_enabled(self, analysis_type: AnalysisType) -> bool:
        """
        检查指定分析类型是否启用
        
        Args:
            analysis_type: 分析类型
            
        Returns:
            bool: 是否启用
        """
        selection = self._selections.get(analysis_type)
        return selection.enabled if selection else False
    
    def get_execution_order(self) -> List[AnalysisType]:
        """
        获取按优先级排序的执行顺序
        
        仅返回启用的分析类型，按 priority 升序排列。
        
        Returns:
            List[AnalysisType]: 排序后的分析类型列表
        """
        enabled = [s for s in self._selections.values() if s.enabled]
        enabled.sort(key=lambda s: s.priority)
        return [s.analysis_type for s in enabled]
    
    # ============================================================
    # 修改方法
    # ============================================================
    
    def set_analysis_enabled(
        self,
        analysis_type: AnalysisType,
        enabled: bool,
        *,
        publish_event: bool = True,
    ) -> None:
        """
        启用/禁用指定分析
        
        Args:
            analysis_type: 分析类型
            enabled: 是否启用
            publish_event: 是否发布变更事件
        """
        if analysis_type not in self._selections:
            self._logger.warning(f"未知的分析类型: {analysis_type}")
            return
        
        old_enabled = self._selections[analysis_type].enabled
        if old_enabled == enabled:
            return
        
        self._selections[analysis_type].enabled = enabled
        self._logger.debug(
            f"分析类型 {analysis_type.value} 已{'启用' if enabled else '禁用'}"
        )
        
        if publish_event:
            self._publish_selection_changed_event("api")
    
    def set_analysis_priority(
        self,
        analysis_type: AnalysisType,
        priority: int,
    ) -> None:
        """
        设置分析执行优先级
        
        Args:
            analysis_type: 分析类型
            priority: 优先级（数字越小越先执行）
        """
        if analysis_type not in self._selections:
            self._logger.warning(f"未知的分析类型: {analysis_type}")
            return
        
        self._selections[analysis_type].priority = priority
    
    def enable_all_basic(self, *, publish_event: bool = True) -> None:
        """启用所有基础分析"""
        for analysis_type in self.get_basic_analyses():
            self._selections[analysis_type].enabled = True
        
        if publish_event:
            self._publish_selection_changed_event("api")
    
    def disable_all_advanced(self, *, publish_event: bool = True) -> None:
        """禁用所有高级分析"""
        for analysis_type in self.get_advanced_analyses():
            self._selections[analysis_type].enabled = False
        
        if publish_event:
            self._publish_selection_changed_event("api")
    
    def set_selections_from_list(
        self,
        enabled_types: List[AnalysisType],
        *,
        publish_event: bool = True,
    ) -> None:
        """
        从列表设置启用的分析类型
        
        Args:
            enabled_types: 要启用的分析类型列表
            publish_event: 是否发布变更事件
        """
        for analysis_type in AnalysisType:
            self._selections[analysis_type].enabled = analysis_type in enabled_types
        
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
            
            self._logger.info(f"分析选择已保存: {config_path}")
            return True
            
        except Exception as e:
            self._logger.error(f"保存分析选择失败: {e}")
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
            self._logger.debug(f"分析选择配置不存在，使用默认配置: {config_path}")
            return True
        
        try:
            content = config_path.read_text(encoding="utf-8")
            data = json.loads(content)
            
            # 解析选择列表
            selections_data = data.get("selections", [])
            for item in selections_data:
                try:
                    selection = AnalysisSelection.from_dict(item)
                    self._selections[selection.analysis_type] = selection
                except (KeyError, ValueError) as e:
                    self._logger.warning(f"跳过无效的选择项: {item}, 错误: {e}")
            
            self._logger.info(f"分析选择已加载: {config_path}")
            self._publish_selection_changed_event("load")
            return True
            
        except json.JSONDecodeError as e:
            self._logger.warning(f"分析选择配置 JSON 解析失败: {e}")
            return False
        except Exception as e:
            self._logger.error(f"加载分析选择失败: {e}")
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
            self._selections[selection.analysis_type] = selection
    
    # ============================================================
    # 校验方法
    # ============================================================
    
    def validate_selection(self) -> SelectionValidationResult:
        """
        校验选择的有效性
        
        校验规则：
        - 至少启用一个分析类型
        - 高级分析依赖基础分析（警告）
        
        Returns:
            SelectionValidationResult: 校验结果
        """
        result = SelectionValidationResult.success()
        
        enabled = self.get_selected_analyses()
        
        # 检查是否至少启用一个分析
        if not enabled:
            result.add_error("至少需要启用一个分析类型")
        
        # 检查高级分析依赖
        enabled_types = {s.analysis_type for s in enabled}
        
        # PVT/蒙特卡洛/最坏情况通常需要基础分析结果
        advanced_enabled = [
            t for t in enabled_types if AnalysisType.is_advanced(t)
        ]
        basic_enabled = [
            t for t in enabled_types if AnalysisType.is_basic(t)
        ]
        
        if advanced_enabled and not basic_enabled:
            result.add_warning(
                "启用了高级分析但未启用任何基础分析，"
                "高级分析可能需要基础分析结果作为输入"
            )
        
        return result
    
    # ============================================================
    # 事件发布
    # ============================================================
    
    def _publish_selection_changed_event(self, source: str) -> None:
        """发布选择变更事件"""
        bus = self._get_event_bus()
        if bus:
            enabled = [s.analysis_type.value for s in self.get_selected_analyses()]
            disabled = [
                s.analysis_type.value
                for s in self._selections.values()
                if not s.enabled
            ]
            
            bus.publish(EVENT_ANALYSIS_SELECTION_CHANGED, {
                "enabled_analyses": enabled,
                "disabled_analyses": disabled,
                "source": source,
            })


# ============================================================
# 模块级单例
# ============================================================

analysis_selector = AnalysisSelector()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "AnalysisType",
    "AnalysisSelection",
    "AnalysisSelector",
    "SelectionValidationResult",
    "analysis_selector",
    "CONFIG_FILE_NAME",
    "CONFIG_DIR",
]
