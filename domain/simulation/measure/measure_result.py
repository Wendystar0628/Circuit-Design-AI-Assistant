# Measure Result Data Class
"""
.MEASURE 结果数据类

定义 ngspice .MEASURE 语句执行结果的标准化数据结构。

使用示例：
    result = MeasureResult(
        name="gain_db",
        value=20.5,
        unit="dB",
        status=MeasureStatus.OK,
        statement=".MEASURE AC gain_db MAX VDB(out)"
    )
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class MeasureStatus(Enum):
    """测量状态枚举"""
    
    OK = "OK"
    """测量成功"""
    
    FAILED = "FAILED"
    """测量失败（如条件未满足）"""
    
    NOT_FOUND = "NOT_FOUND"
    """测量结果未找到"""
    
    PARSE_ERROR = "PARSE_ERROR"
    """解析错误"""


@dataclass
class MeasureResult:
    """
    单个 .MEASURE 测量结果
    
    存储 ngspice .MEASURE 语句的执行结果，包括测量值、单位、状态等信息。
    """
    
    name: str
    """测量名称（.MEASURE 语句中定义的名称）"""
    
    value: Optional[float] = None
    """测量值（失败时为 None）"""
    
    unit: str = ""
    """单位（如 dB, Hz, V, A）"""
    
    status: MeasureStatus = MeasureStatus.OK
    """测量状态"""
    
    statement: str = ""
    """原始 .MEASURE 语句"""
    
    description: str = ""
    """测量描述（用于 UI 显示）"""
    
    display_name: str = ""
    """显示名称"""
    
    category: str = ""
    """分类"""
    
    quantity_kind: str = ""
    """物理量种类"""
    
    raw_output: str = ""
    """ngspice 原始输出行"""
    
    error_message: str = ""
    """错误信息（失败时）"""
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "status": self.status.value,
            "statement": self.statement,
            "description": self.description,
            "display_name": self.display_name,
            "category": self.category,
            "quantity_kind": self.quantity_kind,
            "raw_output": self.raw_output,
            "error_message": self.error_message,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MeasureResult":
        """从字典反序列化"""
        status_str = data.get("status", "OK")
        try:
            status = MeasureStatus(status_str)
        except ValueError:
            status = MeasureStatus.PARSE_ERROR
        
        return cls(
            name=data.get("name", "unknown"),
            value=data.get("value"),
            unit=data.get("unit", ""),
            status=status,
            statement=data.get("statement", ""),
            description=data.get("description", ""),
            display_name=data.get("display_name", ""),
            category=data.get("category", ""),
            quantity_kind=data.get("quantity_kind", ""),
            raw_output=data.get("raw_output", ""),
            error_message=data.get("error_message", ""),
        )
    
    @property
    def is_valid(self) -> bool:
        """测量是否有效"""
        return self.status == MeasureStatus.OK and self.value is not None
    
    @property
    def display_value(self) -> str:
        """格式化显示值"""
        if not self.is_valid:
            return "N/A"
        
        if self.value is None:
            return "N/A"
        
        # 格式化数值
        abs_val = abs(self.value)
        if abs_val == 0:
            formatted = "0"
        elif abs_val >= 1e9:
            formatted = f"{self.value / 1e9:.3g}G"
        elif abs_val >= 1e6:
            formatted = f"{self.value / 1e6:.3g}M"
        elif abs_val >= 1e3:
            formatted = f"{self.value / 1e3:.3g}k"
        elif abs_val >= 1:
            formatted = f"{self.value:.3g}"
        elif abs_val >= 1e-3:
            formatted = f"{self.value * 1e3:.3g}m"
        elif abs_val >= 1e-6:
            formatted = f"{self.value * 1e6:.3g}μ"
        elif abs_val >= 1e-9:
            formatted = f"{self.value * 1e9:.3g}n"
        else:
            formatted = f"{self.value:.3e}"
        
        if self.unit:
            return f"{formatted} {self.unit}"
        return formatted
