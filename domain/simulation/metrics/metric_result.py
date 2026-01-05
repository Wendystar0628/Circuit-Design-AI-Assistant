# MetricResult - Performance Metric Result Data Class
"""
指标结果数据类

职责：
- 定义标准化的指标结果数据结构
- 支持指标值、单位、目标值、达标状态的表示
- 提供指标结果的序列化和反序列化
- 支持指标计算失败时的错误信息记录

设计原则：
- 使用 dataclass 确保类型安全
- 提供工厂方法简化创建
- 支持与设计目标的对比
- 支持置信度标记（用于估计值）

使用示例：
    # 创建成功的指标结果
    gain = MetricResult(
        name="gain",
        display_name="增益",
        value=20.5,
        unit="dB",
        target=20.0,
        category=MetricCategory.AMPLIFIER,
        measurement_condition="f=1kHz"
    )
    
    # 检查是否达标
    if gain.is_met:
        print(f"{gain.display_name}: {gain.formatted_value} ✓")
    
    # 创建失败的指标结果
    error_metric = create_error_metric(
        name="bandwidth",
        display_name="带宽",
        error_message="AC 分析数据不足",
        category=MetricCategory.AMPLIFIER
    )
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class MetricCategory(Enum):
    """
    指标类别枚举
    
    用于对指标进行分类，便于 UI 分组显示和按类型提取
    """
    
    AMPLIFIER = "amplifier"
    """放大器指标（增益、带宽、相位裕度等）"""
    
    NOISE = "noise"
    """噪声指标（输入噪声、噪声系数、信噪比等）"""
    
    DISTORTION = "distortion"
    """失真指标（THD、IMD、SFDR 等）"""
    
    POWER = "power"
    """电源指标（功耗、效率、静态电流等）"""
    
    TRANSIENT = "transient"
    """瞬态指标（上升时间、建立时间、过冲等）"""
    
    GENERAL = "general"
    """通用指标（不属于上述类别）"""


@dataclass
class MetricResult:
    """
    单个指标结果
    
    表示从仿真数据中提取的单个性能指标，包含值、单位、目标、
    达标状态等完整信息。
    
    Attributes:
        name: 指标标识名（英文，用于程序内部引用）
        display_name: 指标显示名（中文，用于 UI 显示）
        value: 指标数值（计算失败时为 None）
        unit: 单位（如 "dB", "Hz", "V", "%"）
        target: 目标值（用于达标判断，None 表示无目标）
        target_type: 目标类型（"min", "max", "range", "exact"）
        target_max: 目标上限（target_type="range" 时使用）
        is_met: 是否达标（None 表示无目标或无法判断）
        category: 指标类别
        confidence: 置信度（0-1，1.0 表示精确值，<1.0 表示估计值）
        measurement_condition: 测量条件描述（如 "f=1kHz", "Vdd=3.3V"）
        error_message: 计算失败时的错误信息
        raw_value: 原始计算值（未经格式化，用于精确计算）
        metadata: 附加元数据（如计算方法、数据来源等）
    """
    
    name: str
    """指标标识名（英文，用于程序内部引用，如 "gain", "bandwidth"）"""
    
    display_name: str
    """指标显示名（中文，用于 UI 显示，如 "增益", "带宽"）"""
    
    value: Optional[float] = None
    """指标数值（计算失败时为 None）"""
    
    unit: str = ""
    """单位（如 "dB", "Hz", "V", "%"）"""
    
    target: Optional[float] = None
    """目标值（用于达标判断，None 表示无目标）"""
    
    target_type: str = "min"
    """
    目标类型：
    - "min": 最小值目标，value >= target 为达标
    - "max": 最大值目标，value <= target 为达标
    - "range": 范围目标，target <= value <= target_max 为达标
    - "exact": 精确目标，|value - target| <= tolerance 为达标
    """
    
    target_max: Optional[float] = None
    """目标上限（target_type="range" 时使用）"""
    
    is_met: Optional[bool] = None
    """是否达标（None 表示无目标或无法判断）"""
    
    category: MetricCategory = MetricCategory.GENERAL
    """指标类别"""
    
    confidence: float = 1.0
    """置信度（0-1，1.0 表示精确值，<1.0 表示估计值或插值）"""
    
    measurement_condition: str = ""
    """测量条件描述（如 "f=1kHz", "Vdd=3.3V", "T=25°C"）"""
    
    error_message: Optional[str] = None
    """计算失败时的错误信息"""
    
    raw_value: Optional[float] = None
    """原始计算值（未经格式化，用于精确计算和比较）"""
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    """附加元数据（如计算方法、数据来源、采样点数等）"""
    
    def __post_init__(self):
        """初始化后处理：自动计算达标状态"""
        # 如果有值和目标但未设置达标状态，自动计算
        if self.value is not None and self.target is not None and self.is_met is None:
            self.is_met = self._check_target()
        
        # 如果未设置 raw_value，使用 value
        if self.raw_value is None and self.value is not None:
            self.raw_value = self.value
    
    def _check_target(self) -> bool:
        """
        检查是否达标
        
        Returns:
            bool: 是否达标
        """
        if self.value is None or self.target is None:
            return False
        
        if self.target_type == "min":
            return self.value >= self.target
        elif self.target_type == "max":
            return self.value <= self.target
        elif self.target_type == "range":
            if self.target_max is None:
                return self.value >= self.target
            return self.target <= self.value <= self.target_max
        elif self.target_type == "exact":
            # 默认容差为目标值的 1%
            tolerance = abs(self.target) * 0.01 if self.target != 0 else 0.01
            return abs(self.value - self.target) <= tolerance
        else:
            return self.value >= self.target
    
    @property
    def is_valid(self) -> bool:
        """
        检查指标是否有效（成功计算）
        
        Returns:
            bool: 是否有效
        """
        return self.value is not None and self.error_message is None
    
    @property
    def formatted_value(self) -> str:
        """
        获取格式化的值字符串（带单位）
        
        Returns:
            str: 格式化的值，如 "20.5 dB", "10 MHz"
        """
        if self.value is None:
            return "N/A"
        
        # 根据数值大小选择合适的格式
        abs_value = abs(self.value)
        
        if abs_value == 0:
            formatted = "0"
        elif abs_value >= 1e9:
            formatted = f"{self.value / 1e9:.2f}G"
        elif abs_value >= 1e6:
            formatted = f"{self.value / 1e6:.2f}M"
        elif abs_value >= 1e3:
            formatted = f"{self.value / 1e3:.2f}k"
        elif abs_value >= 1:
            formatted = f"{self.value:.2f}"
        elif abs_value >= 1e-3:
            formatted = f"{self.value * 1e3:.2f}m"
        elif abs_value >= 1e-6:
            formatted = f"{self.value * 1e6:.2f}μ"
        elif abs_value >= 1e-9:
            formatted = f"{self.value * 1e9:.2f}n"
        elif abs_value >= 1e-12:
            formatted = f"{self.value * 1e12:.2f}p"
        else:
            formatted = f"{self.value:.2e}"
        
        if self.unit:
            return f"{formatted} {self.unit}"
        return formatted
    
    @property
    def status_icon(self) -> str:
        """
        获取状态图标（用于 UI 显示）
        
        Returns:
            str: 状态图标 "✓", "✗", "-"
        """
        if self.is_met is None:
            return "-"
        return "✓" if self.is_met else "✗"
    
    def to_dict(self) -> Dict[str, Any]:
        """
        序列化为字典
        
        Returns:
            Dict: 序列化后的字典
        """
        return {
            "name": self.name,
            "display_name": self.display_name,
            "value": self.value,
            "unit": self.unit,
            "target": self.target,
            "target_type": self.target_type,
            "target_max": self.target_max,
            "is_met": self.is_met,
            "category": self.category.value,
            "confidence": self.confidence,
            "measurement_condition": self.measurement_condition,
            "error_message": self.error_message,
            "raw_value": self.raw_value,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetricResult":
        """
        从字典反序列化
        
        Args:
            data: 序列化的字典
            
        Returns:
            MetricResult: 反序列化后的对象
        """
        category_str = data.get("category", "general")
        try:
            category = MetricCategory(category_str)
        except ValueError:
            category = MetricCategory.GENERAL
        
        return cls(
            name=data["name"],
            display_name=data["display_name"],
            value=data.get("value"),
            unit=data.get("unit", ""),
            target=data.get("target"),
            target_type=data.get("target_type", "min"),
            target_max=data.get("target_max"),
            is_met=data.get("is_met"),
            category=category,
            confidence=data.get("confidence", 1.0),
            measurement_condition=data.get("measurement_condition", ""),
            error_message=data.get("error_message"),
            raw_value=data.get("raw_value"),
            metadata=data.get("metadata", {}),
        )
    
    def with_target(
        self,
        target: float,
        target_type: str = "min",
        target_max: Optional[float] = None
    ) -> "MetricResult":
        """
        创建带目标值的新指标结果（不修改原对象）
        
        Args:
            target: 目标值
            target_type: 目标类型
            target_max: 目标上限（range 类型时使用）
            
        Returns:
            MetricResult: 新的指标结果
        """
        new_result = MetricResult(
            name=self.name,
            display_name=self.display_name,
            value=self.value,
            unit=self.unit,
            target=target,
            target_type=target_type,
            target_max=target_max,
            is_met=None,  # 让 __post_init__ 重新计算
            category=self.category,
            confidence=self.confidence,
            measurement_condition=self.measurement_condition,
            error_message=self.error_message,
            raw_value=self.raw_value,
            metadata=self.metadata.copy(),
        )
        return new_result
    
    def get_summary(self) -> str:
        """
        获取指标摘要（用于日志和调试）
        
        Returns:
            str: 指标摘要
        """
        status = self.status_icon
        value_str = self.formatted_value
        target_str = ""
        if self.target is not None:
            if self.target_type == "range" and self.target_max is not None:
                target_str = f" (目标: {self.target}-{self.target_max})"
            else:
                target_str = f" (目标: {self.target_type} {self.target})"
        
        return f"{self.display_name}: {value_str}{target_str} {status}"


def create_metric_result(
    name: str,
    display_name: str,
    value: float,
    unit: str = "",
    category: MetricCategory = MetricCategory.GENERAL,
    target: Optional[float] = None,
    target_type: str = "min",
    measurement_condition: str = "",
    confidence: float = 1.0,
    metadata: Optional[Dict[str, Any]] = None
) -> MetricResult:
    """
    创建成功的指标结果
    
    Args:
        name: 指标标识名
        display_name: 指标显示名
        value: 指标数值
        unit: 单位
        category: 指标类别
        target: 目标值
        target_type: 目标类型
        measurement_condition: 测量条件
        confidence: 置信度
        metadata: 附加元数据
        
    Returns:
        MetricResult: 指标结果
    """
    return MetricResult(
        name=name,
        display_name=display_name,
        value=value,
        unit=unit,
        target=target,
        target_type=target_type,
        category=category,
        confidence=confidence,
        measurement_condition=measurement_condition,
        metadata=metadata or {},
    )


def create_error_metric(
    name: str,
    display_name: str,
    error_message: str,
    category: MetricCategory = MetricCategory.GENERAL,
    unit: str = ""
) -> MetricResult:
    """
    创建失败的指标结果
    
    Args:
        name: 指标标识名
        display_name: 指标显示名
        error_message: 错误信息
        category: 指标类别
        unit: 单位
        
    Returns:
        MetricResult: 失败的指标结果
    """
    return MetricResult(
        name=name,
        display_name=display_name,
        value=None,
        unit=unit,
        category=category,
        error_message=error_message,
        confidence=0.0,
    )


__all__ = [
    "MetricCategory",
    "MetricResult",
    "create_metric_result",
    "create_error_metric",
]
