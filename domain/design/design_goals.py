# DesignGoals - Design Goals Entity
"""
设计目标实体

职责：
- 结构化存储和管理从用户需求中提取的电路设计指标
- 支持设计目标的增删改查
- 支持与仿真结果的比对和达标判断
- 支持序列化/反序列化和持久化

设计原则：
- 使用 dataclass 确保类型安全
- 与 MetricResult 配合使用
- 支持从 LLM 输出创建实例

使用示例：
    from domain.design.design_goals import DesignGoalsManager
    
    # 创建管理器
    manager = DesignGoalsManager(project_root)
    
    # 添加设计目标
    manager.add_goal(DesignGoal(
        identifier="gain",
        name="增益",
        target_value=20.0,
        unit="dB",
        constraint_type=ConstraintType.MINIMUM
    ))
    
    # 保存到文件
    manager.save()
    
    # 与仿真结果比对
    score = manager.calculate_score(actual_values)
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class ConstraintType(Enum):
    """
    约束类型枚举
    
    定义设计目标的约束方式
    """
    
    MINIMUM = "minimum"
    """最小值约束：实际值 >= 目标值"""
    
    MAXIMUM = "maximum"
    """最大值约束：实际值 <= 目标值"""
    
    EXACT = "exact"
    """精确值约束：|实际值 - 目标值| <= 容差"""
    
    RANGE = "range"
    """范围约束：下限 <= 实际值 <= 上限"""
    
    MINIMIZE = "minimize"
    """最小化优化：越小越好，无硬性约束"""
    
    MAXIMIZE = "maximize"
    """最大化优化：越大越好，无硬性约束"""


@dataclass
class DesignGoal:
    """
    单个设计目标
    
    表示从用户需求中提取的单个电路设计指标目标。
    
    Attributes:
        identifier: 指标英文标识符（如 gain、bandwidth）
        name: 显示名称（如 增益、带宽）
        target_value: 期望值（使用基本单位）
        unit: 单位（如 dB、Hz、Ω）
        constraint_type: 约束类型
        weight: 权重（0-1，用于综合评分）
        tolerance_percent: 容差百分比（默认 5%）
        current_value: 当前实际值（仿真后填充）
        is_met: 是否达标
        range_max: 范围上限（constraint_type=RANGE 时使用）
    """
    
    identifier: str
    """指标英文标识符（如 gain、bandwidth、phase_margin）"""
    
    name: str
    """显示名称（如 增益、带宽、相位裕度）"""
    
    target_value: float
    """期望值（使用基本单位，如 Hz 而非 MHz）"""
    
    unit: str = ""
    """单位（如 dB、Hz、V、Ω、%）"""
    
    constraint_type: ConstraintType = ConstraintType.MINIMUM
    """约束类型"""
    
    weight: float = 1.0
    """权重（0-1，用于综合评分，默认 1.0）"""
    
    tolerance_percent: float = 5.0
    """容差百分比（用于 EXACT 约束，默认 5%）"""
    
    current_value: Optional[float] = None
    """当前实际值（仿真后填充）"""
    
    is_met: Optional[bool] = None
    """是否达标（None 表示未评估）"""
    
    range_max: Optional[float] = None
    """范围上限（constraint_type=RANGE 时使用）"""
    
    description: str = ""
    """目标描述（可选）"""
    
    def is_satisfied(self, actual_value: float) -> bool:
        """
        判断给定实际值是否满足目标
        
        Args:
            actual_value: 实际测量值
            
        Returns:
            bool: 是否满足目标
        """
        if self.constraint_type == ConstraintType.MINIMUM:
            return actual_value >= self.target_value
        
        elif self.constraint_type == ConstraintType.MAXIMUM:
            return actual_value <= self.target_value
        
        elif self.constraint_type == ConstraintType.EXACT:
            tolerance = abs(self.target_value) * (self.tolerance_percent / 100.0)
            if tolerance == 0:
                tolerance = 0.01  # 目标值为0时使用绝对容差
            return abs(actual_value - self.target_value) <= tolerance
        
        elif self.constraint_type == ConstraintType.RANGE:
            if self.range_max is None:
                return actual_value >= self.target_value
            return self.target_value <= actual_value <= self.range_max
        
        elif self.constraint_type in (ConstraintType.MINIMIZE, ConstraintType.MAXIMIZE):
            # 优化目标无硬性约束，总是返回 True
            return True
        
        return False
    
    def calculate_score(self, actual_value: float) -> float:
        """
        计算单个目标的得分（0-1）
        
        Args:
            actual_value: 实际测量值
            
        Returns:
            float: 得分（0-1，1 表示完全满足）
        """
        if self.constraint_type == ConstraintType.MINIMUM:
            if actual_value >= self.target_value:
                return 1.0
            # 部分满足：按比例计算
            if self.target_value == 0:
                return 0.0
            ratio = actual_value / self.target_value
            return max(0.0, min(1.0, ratio))
        
        elif self.constraint_type == ConstraintType.MAXIMUM:
            if actual_value <= self.target_value:
                return 1.0
            # 超出目标：按比例扣分
            if actual_value == 0:
                return 1.0
            ratio = self.target_value / actual_value
            return max(0.0, min(1.0, ratio))
        
        elif self.constraint_type == ConstraintType.EXACT:
            tolerance = abs(self.target_value) * (self.tolerance_percent / 100.0)
            if tolerance == 0:
                tolerance = 0.01
            deviation = abs(actual_value - self.target_value)
            if deviation <= tolerance:
                return 1.0
            # 超出容差：按偏差比例扣分
            return max(0.0, 1.0 - (deviation - tolerance) / tolerance)
        
        elif self.constraint_type == ConstraintType.RANGE:
            if self.range_max is None:
                return 1.0 if actual_value >= self.target_value else 0.0
            if self.target_value <= actual_value <= self.range_max:
                return 1.0
            # 超出范围：按距离扣分
            range_width = self.range_max - self.target_value
            if range_width == 0:
                return 1.0 if actual_value == self.target_value else 0.0
            if actual_value < self.target_value:
                deviation = self.target_value - actual_value
            else:
                deviation = actual_value - self.range_max
            return max(0.0, 1.0 - deviation / range_width)
        
        elif self.constraint_type == ConstraintType.MINIMIZE:
            # 最小化：值越小得分越高（相对于目标值）
            if self.target_value == 0:
                return 1.0 if actual_value <= 0 else 0.5
            ratio = self.target_value / actual_value if actual_value != 0 else 1.0
            return max(0.0, min(1.0, ratio))
        
        elif self.constraint_type == ConstraintType.MAXIMIZE:
            # 最大化：值越大得分越高（相对于目标值）
            if self.target_value == 0:
                return 1.0 if actual_value >= 0 else 0.5
            ratio = actual_value / self.target_value
            return max(0.0, min(1.0, ratio))
        
        return 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "identifier": self.identifier,
            "name": self.name,
            "target_value": self.target_value,
            "unit": self.unit,
            "constraint_type": self.constraint_type.value,
            "weight": self.weight,
            "tolerance_percent": self.tolerance_percent,
            "current_value": self.current_value,
            "is_met": self.is_met,
            "range_max": self.range_max,
            "description": self.description,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DesignGoal":
        """从字典反序列化"""
        constraint_str = data.get("constraint_type", "minimum")
        try:
            constraint_type = ConstraintType(constraint_str)
        except ValueError:
            constraint_type = ConstraintType.MINIMUM
        
        return cls(
            identifier=data["identifier"],
            name=data.get("name", data["identifier"]),
            target_value=float(data["target_value"]),
            unit=data.get("unit", ""),
            constraint_type=constraint_type,
            weight=float(data.get("weight", 1.0)),
            tolerance_percent=float(data.get("tolerance_percent", 5.0)),
            current_value=data.get("current_value"),
            is_met=data.get("is_met"),
            range_max=data.get("range_max"),
            description=data.get("description", ""),
        )



@dataclass
class DesignGoalsCollection:
    """
    设计目标集合
    
    包含多个设计目标及其元信息。
    
    Attributes:
        goals: 设计目标列表
        circuit_type: 电路类型（如 amplifier、filter）
        description: 设计需求描述
        created_at: 创建时间
        updated_at: 更新时间
        source: 来源标识（llm 或 user）
    """
    
    goals: List[DesignGoal] = field(default_factory=list)
    """设计目标列表"""
    
    circuit_type: str = ""
    """电路类型（如 amplifier、filter、ldo、oscillator）"""
    
    description: str = ""
    """设计需求描述"""
    
    created_at: str = ""
    """创建时间（ISO 格式）"""
    
    updated_at: str = ""
    """更新时间（ISO 格式）"""
    
    source: str = "user"
    """来源标识（llm 或 user）"""
    
    def __post_init__(self):
        """初始化后处理"""
        now = datetime.now().isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "goals": [g.to_dict() for g in self.goals],
            "circuit_type": self.circuit_type,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DesignGoalsCollection":
        """从字典反序列化"""
        goals = [DesignGoal.from_dict(g) for g in data.get("goals", [])]
        return cls(
            goals=goals,
            circuit_type=data.get("circuit_type", ""),
            description=data.get("description", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            source=data.get("source", "user"),
        )


class DesignGoalsManager:
    """
    设计目标管理器
    
    管理设计目标的增删改查、持久化、与仿真结果比对。
    
    Attributes:
        project_root: 项目根目录
        collection: 设计目标集合
    """
    
    CONFIG_DIR = ".circuit_ai"
    CONFIG_FILE = "design_goals.json"
    
    def __init__(self, project_root: Union[str, Path]):
        """
        初始化设计目标管理器
        
        Args:
            project_root: 项目根目录
        """
        self.project_root = Path(project_root)
        self.collection = DesignGoalsCollection()
        self._load()
    
    @property
    def _config_path(self) -> Path:
        """获取配置文件路径"""
        return self.project_root / self.CONFIG_DIR / self.CONFIG_FILE
    
    def _load(self) -> None:
        """从文件加载设计目标"""
        if self._config_path.exists():
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data:  # 非空字典
                    self.collection = DesignGoalsCollection.from_dict(data)
            except (json.JSONDecodeError, KeyError):
                # 文件损坏或格式错误，使用空集合
                self.collection = DesignGoalsCollection()
    
    def save(self) -> None:
        """保存设计目标到文件"""
        self.collection.updated_at = datetime.now().isoformat()
        
        # 确保目录存在
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(self.collection.to_dict(), f, ensure_ascii=False, indent=2)
    
    def add_goal(self, goal: DesignGoal) -> None:
        """
        添加设计目标
        
        Args:
            goal: 设计目标
        """
        # 检查是否已存在同名目标
        existing = self.get_goal(goal.identifier)
        if existing is not None:
            # 更新现有目标
            self.update_goal(goal.identifier, goal.to_dict())
        else:
            self.collection.goals.append(goal)
    
    def get_goal(self, identifier: str) -> Optional[DesignGoal]:
        """
        获取指定标识符的设计目标
        
        Args:
            identifier: 目标标识符
            
        Returns:
            DesignGoal 或 None
        """
        for goal in self.collection.goals:
            if goal.identifier == identifier:
                return goal
        return None
    
    def update_goal(self, identifier: str, updates: Dict[str, Any]) -> bool:
        """
        更新指定目标
        
        Args:
            identifier: 目标标识符
            updates: 更新字段字典
            
        Returns:
            bool: 是否成功更新
        """
        for i, goal in enumerate(self.collection.goals):
            if goal.identifier == identifier:
                # 合并更新
                goal_dict = goal.to_dict()
                goal_dict.update(updates)
                self.collection.goals[i] = DesignGoal.from_dict(goal_dict)
                return True
        return False
    
    def remove_goal(self, identifier: str) -> bool:
        """
        删除指定目标
        
        Args:
            identifier: 目标标识符
            
        Returns:
            bool: 是否成功删除
        """
        for i, goal in enumerate(self.collection.goals):
            if goal.identifier == identifier:
                del self.collection.goals[i]
                return True
        return False
    
    def validate(self) -> List[str]:
        """
        校验目标完整性
        
        Returns:
            List[str]: 校验错误列表（空列表表示通过）
        """
        errors = []
        
        # 检查必填字段
        for goal in self.collection.goals:
            if not goal.identifier:
                errors.append(f"目标缺少标识符: {goal.name}")
            if goal.target_value is None:
                errors.append(f"目标 {goal.identifier} 缺少目标值")
            if goal.weight < 0 or goal.weight > 1:
                errors.append(f"目标 {goal.identifier} 权重超出范围 [0, 1]")
            if goal.constraint_type == ConstraintType.RANGE and goal.range_max is None:
                errors.append(f"目标 {goal.identifier} 使用范围约束但未设置上限")
        
        # 检查权重之和
        total_weight = sum(g.weight for g in self.collection.goals)
        if self.collection.goals and total_weight == 0:
            errors.append("所有目标权重之和为 0")
        
        # 检查标识符唯一性
        identifiers = [g.identifier for g in self.collection.goals]
        if len(identifiers) != len(set(identifiers)):
            errors.append("存在重复的目标标识符")
        
        return errors
    
    def is_satisfied(self, actual_value: float, identifier: str) -> bool:
        """
        判断单个指标是否达标
        
        Args:
            actual_value: 实际测量值
            identifier: 目标标识符
            
        Returns:
            bool: 是否达标
        """
        goal = self.get_goal(identifier)
        if goal is None:
            return False
        return goal.is_satisfied(actual_value)
    
    def calculate_score(self, actual_values: Dict[str, float]) -> float:
        """
        计算综合达标评分（加权）
        
        Args:
            actual_values: 实际值字典 {identifier: value}
            
        Returns:
            float: 综合评分（0-1）
        """
        if not self.collection.goals:
            return 1.0
        
        total_weight = sum(g.weight for g in self.collection.goals)
        if total_weight == 0:
            return 1.0
        
        weighted_score = 0.0
        for goal in self.collection.goals:
            if goal.identifier in actual_values:
                score = goal.calculate_score(actual_values[goal.identifier])
                weighted_score += score * goal.weight
        
        return weighted_score / total_weight
    
    def update_current_values(self, actual_values: Dict[str, float]) -> None:
        """
        更新所有目标的当前值和达标状态
        
        Args:
            actual_values: 实际值字典 {identifier: value}
        """
        for goal in self.collection.goals:
            if goal.identifier in actual_values:
                goal.current_value = actual_values[goal.identifier]
                goal.is_met = goal.is_satisfied(goal.current_value)
    
    def get_unmet_goals(self) -> List[DesignGoal]:
        """
        获取未达标的目标列表
        
        Returns:
            List[DesignGoal]: 未达标目标列表
        """
        return [g for g in self.collection.goals if g.is_met is False]
    
    def get_met_goals(self) -> List[DesignGoal]:
        """
        获取已达标的目标列表
        
        Returns:
            List[DesignGoal]: 已达标目标列表
        """
        return [g for g in self.collection.goals if g.is_met is True]
    
    def all_goals_met(self) -> bool:
        """
        检查是否所有目标都已达标
        
        Returns:
            bool: 是否全部达标
        """
        if not self.collection.goals:
            return True
        return all(g.is_met is True for g in self.collection.goals)
    
    @classmethod
    def from_llm_output(
        cls,
        project_root: Union[str, Path],
        llm_json: Dict[str, Any]
    ) -> "DesignGoalsManager":
        """
        从 LLM 输出的 JSON 创建实例
        
        LLM 输出格式示例：
        {
            "circuit_type": "amplifier",
            "description": "设计一个增益20dB的放大器",
            "goals": [
                {
                    "name": "gain",
                    "display_name": "增益",
                    "value": 20,
                    "unit": "dB",
                    "type": "minimum"
                }
            ]
        }
        
        Args:
            project_root: 项目根目录
            llm_json: LLM 输出的 JSON
            
        Returns:
            DesignGoalsManager: 管理器实例
        """
        manager = cls(project_root)
        
        # 设置电路类型和描述
        manager.collection.circuit_type = llm_json.get("circuit_type", "")
        manager.collection.description = llm_json.get("description", "")
        manager.collection.source = "llm"
        
        # 解析目标
        for goal_data in llm_json.get("goals", []):
            # LLM 输出映射规则
            identifier = goal_data.get("name", goal_data.get("identifier", ""))
            name = goal_data.get("display_name", goal_data.get("name", identifier))
            target_value = goal_data.get("value", goal_data.get("target_value", 0))
            unit = goal_data.get("unit", "")
            
            # 约束类型映射
            type_str = goal_data.get("type", goal_data.get("constraint_type", "minimum"))
            try:
                constraint_type = ConstraintType(type_str)
            except ValueError:
                constraint_type = ConstraintType.MINIMUM
            
            goal = DesignGoal(
                identifier=identifier,
                name=name,
                target_value=float(target_value),
                unit=unit,
                constraint_type=constraint_type,
                weight=float(goal_data.get("weight", 1.0)),
                tolerance_percent=float(goal_data.get("tolerance", goal_data.get("tolerance_percent", 5.0))),
                range_max=goal_data.get("max", goal_data.get("range_max")),
                description=goal_data.get("description", ""),
            )
            manager.add_goal(goal)
        
        return manager
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return self.collection.to_dict()
    
    def clear(self) -> None:
        """清空所有设计目标"""
        self.collection.goals.clear()
    
    def __len__(self) -> int:
        """返回目标数量"""
        return len(self.collection.goals)
    
    def __iter__(self):
        """迭代所有目标"""
        return iter(self.collection.goals)


# 支持的指标类别（与 MetricsExtractor 对应）
SUPPORTED_METRICS = {
    # 放大器指标
    "gain": {"name": "增益", "unit": "dB", "default_constraint": "minimum"},
    "bandwidth": {"name": "带宽", "unit": "Hz", "default_constraint": "minimum"},
    "gbw": {"name": "增益带宽积", "unit": "Hz", "default_constraint": "minimum"},
    "phase_margin": {"name": "相位裕度", "unit": "°", "default_constraint": "minimum"},
    "gain_margin": {"name": "增益裕度", "unit": "dB", "default_constraint": "minimum"},
    "input_impedance": {"name": "输入阻抗", "unit": "Ω", "default_constraint": "minimum"},
    "output_impedance": {"name": "输出阻抗", "unit": "Ω", "default_constraint": "maximum"},
    "cmrr": {"name": "共模抑制比", "unit": "dB", "default_constraint": "minimum"},
    "psrr": {"name": "电源抑制比", "unit": "dB", "default_constraint": "minimum"},
    "slew_rate": {"name": "压摆率", "unit": "V/μs", "default_constraint": "minimum"},
    "settling_time": {"name": "整定时间", "unit": "s", "default_constraint": "maximum"},
    "overshoot": {"name": "过冲量", "unit": "%", "default_constraint": "maximum"},
    "offset_voltage": {"name": "失调电压", "unit": "V", "default_constraint": "maximum"},
    
    # 噪声指标
    "input_noise": {"name": "输入噪声", "unit": "nV/√Hz", "default_constraint": "maximum"},
    "integrated_noise": {"name": "积分噪声", "unit": "μVrms", "default_constraint": "maximum"},
    "noise_figure": {"name": "噪声系数", "unit": "dB", "default_constraint": "maximum"},
    "snr": {"name": "信噪比", "unit": "dB", "default_constraint": "minimum"},
    
    # 失真指标
    "thd": {"name": "总谐波失真", "unit": "%", "default_constraint": "maximum"},
    "thd_n": {"name": "THD+N", "unit": "%", "default_constraint": "maximum"},
    "imd": {"name": "互调失真", "unit": "dB", "default_constraint": "maximum"},
    "sfdr": {"name": "无杂散动态范围", "unit": "dB", "default_constraint": "minimum"},
    "sndr": {"name": "信噪失真比", "unit": "dB", "default_constraint": "minimum"},
    "enob": {"name": "有效位数", "unit": "bits", "default_constraint": "minimum"},
    
    # 电源指标
    "quiescent_current": {"name": "静态电流", "unit": "A", "default_constraint": "maximum"},
    "power_consumption": {"name": "功耗", "unit": "W", "default_constraint": "maximum"},
    "efficiency": {"name": "效率", "unit": "%", "default_constraint": "minimum"},
    "load_regulation": {"name": "负载调整率", "unit": "%", "default_constraint": "maximum"},
    "line_regulation": {"name": "线性调整率", "unit": "%", "default_constraint": "maximum"},
    "dropout_voltage": {"name": "压差", "unit": "V", "default_constraint": "maximum"},
    
    # 时域指标
    "rise_time": {"name": "上升时间", "unit": "s", "default_constraint": "maximum"},
    "fall_time": {"name": "下降时间", "unit": "s", "default_constraint": "maximum"},
    "propagation_delay": {"name": "传播延迟", "unit": "s", "default_constraint": "maximum"},
    "duty_cycle": {"name": "占空比", "unit": "%", "default_constraint": "range"},
    "frequency": {"name": "振荡频率", "unit": "Hz", "default_constraint": "exact"},
    
    # 可靠性指标
    "yield_target": {"name": "良率目标", "unit": "%", "default_constraint": "minimum"},
    "temperature_range": {"name": "温度范围", "unit": "°C", "default_constraint": "range"},
    "supply_range": {"name": "电源电压范围", "unit": "V", "default_constraint": "range"},
}


def get_metric_info(identifier: str) -> Optional[Dict[str, str]]:
    """
    获取指标信息
    
    Args:
        identifier: 指标标识符
        
    Returns:
        Dict 或 None
    """
    return SUPPORTED_METRICS.get(identifier)


def get_supported_metric_identifiers() -> List[str]:
    """
    获取所有支持的指标标识符
    
    Returns:
        List[str]: 标识符列表
    """
    return list(SUPPORTED_METRICS.keys())


__all__ = [
    "ConstraintType",
    "DesignGoal",
    "DesignGoalsCollection",
    "DesignGoalsManager",
    "SUPPORTED_METRICS",
    "get_metric_info",
    "get_supported_metric_identifiers",
]
