# Parameter Extractor - Circuit Parameter Extraction Service
"""
电路参数提取服务

职责：
- 从电路文件中提取可调参数
- 解析 .param 语句
- 识别元件数值（R/C/L）
- 返回结构化的参数列表

设计原则：
- 纯领域逻辑，不依赖 UI
- 支持多种参数来源
- 自动识别参数单位和合理范围
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_logger = logging.getLogger(__name__)


class ParameterType(Enum):
    """参数类型"""
    PARAM = "param"           # .param 语句定义的参数
    RESISTOR = "resistor"     # 电阻值
    CAPACITOR = "capacitor"   # 电容值
    INDUCTOR = "inductor"     # 电感值
    VOLTAGE = "voltage"       # 电压源值
    CURRENT = "current"       # 电流源值


@dataclass
class TunableParameter:
    """
    可调参数数据类
    
    Attributes:
        name: 参数名称
        value: 当前值
        unit: 单位
        param_type: 参数类型
        min_value: 最小值
        max_value: 最大值
        step: 步进值
        line_number: 在文件中的行号
        original_text: 原始文本
        element_name: 元件名称（如 R1, C2）
    """
    name: str
    value: float
    unit: str = ""
    param_type: ParameterType = ParameterType.PARAM
    min_value: float = 0.0
    max_value: float = 0.0
    step: float = 0.0
    line_number: int = 0
    original_text: str = ""
    element_name: str = ""
    
    def __post_init__(self):
        """初始化后处理：自动计算范围和步进"""
        if self.min_value == 0.0 and self.max_value == 0.0:
            self._auto_calculate_range()
        if self.step == 0.0:
            self._auto_calculate_step()
    
    def _auto_calculate_range(self):
        """自动计算参数范围"""
        if self.value == 0:
            self.min_value = -1.0
            self.max_value = 1.0
        else:
            # 默认范围：当前值的 0.1 到 10 倍
            abs_val = abs(self.value)
            self.min_value = abs_val * 0.1
            self.max_value = abs_val * 10.0
            if self.value < 0:
                self.min_value, self.max_value = -self.max_value, -self.min_value
    
    def _auto_calculate_step(self):
        """自动计算步进值"""
        range_span = self.max_value - self.min_value
        if range_span > 0:
            # 默认 100 个步进
            self.step = range_span / 100.0
        else:
            self.step = abs(self.value) / 100.0 if self.value != 0 else 0.01


@dataclass
class ParameterExtractionResult:
    """
    参数提取结果
    
    Attributes:
        parameters: 提取的参数列表
        file_path: 源文件路径
        success: 是否成功
        error_message: 错误信息
    """
    parameters: List[TunableParameter] = field(default_factory=list)
    file_path: str = ""
    success: bool = True
    error_message: str = ""
    
    @property
    def count(self) -> int:
        """参数数量"""
        return len(self.parameters)
    
    def get_by_name(self, name: str) -> Optional[TunableParameter]:
        """按名称获取参数"""
        for param in self.parameters:
            if param.name == name:
                return param
        return None
    
    def get_by_type(self, param_type: ParameterType) -> List[TunableParameter]:
        """按类型获取参数"""
        return [p for p in self.parameters if p.param_type == param_type]


class ParameterExtractor:
    """
    电路参数提取器
    
    从 SPICE 电路文件中提取可调参数
    """
    
    # .param 语句模式
    PARAM_PATTERN = re.compile(
        r'^\s*\.param\s+(\w+)\s*=\s*([+-]?[\d.]+(?:[eE][+-]?\d+)?)\s*(\w*)',
        re.IGNORECASE
    )
    
    # 电阻模式：R<name> <node1> <node2> <value>
    RESISTOR_PATTERN = re.compile(
        r'^\s*(R\w*)\s+\S+\s+\S+\s+([+-]?[\d.]+(?:[eE][+-]?\d+)?)\s*(\w*)',
        re.IGNORECASE
    )
    
    # 电容模式：C<name> <node1> <node2> <value>
    CAPACITOR_PATTERN = re.compile(
        r'^\s*(C\w*)\s+\S+\s+\S+\s+([+-]?[\d.]+(?:[eE][+-]?\d+)?)\s*(\w*)',
        re.IGNORECASE
    )
    
    # 电感模式：L<name> <node1> <node2> <value>
    INDUCTOR_PATTERN = re.compile(
        r'^\s*(L\w*)\s+\S+\s+\S+\s+([+-]?[\d.]+(?:[eE][+-]?\d+)?)\s*(\w*)',
        re.IGNORECASE
    )
    
    # 电压源模式：V<name> <node+> <node-> <value>
    VOLTAGE_PATTERN = re.compile(
        r'^\s*(V\w*)\s+\S+\s+\S+\s+(?:DC\s+)?([+-]?[\d.]+(?:[eE][+-]?\d+)?)\s*(\w*)',
        re.IGNORECASE
    )
    
    # 电流源模式：I<name> <node+> <node-> <value>
    CURRENT_PATTERN = re.compile(
        r'^\s*(I\w*)\s+\S+\s+\S+\s+(?:DC\s+)?([+-]?[\d.]+(?:[eE][+-]?\d+)?)\s*(\w*)',
        re.IGNORECASE
    )
    
    # 单位前缀映射
    UNIT_PREFIXES = {
        'f': 1e-15,   # femto
        'p': 1e-12,   # pico
        'n': 1e-9,    # nano
        'u': 1e-6,    # micro
        'm': 1e-3,    # milli
        'k': 1e3,     # kilo
        'meg': 1e6,   # mega (must be before 'm' in matching)
        'g': 1e9,     # giga
        't': 1e12,    # tera
    }
    
    def __init__(self):
        self._logger = _logger
    
    def extract_from_file(self, file_path: str) -> ParameterExtractionResult:
        """
        从文件中提取参数
        
        Args:
            file_path: 电路文件路径
            
        Returns:
            ParameterExtractionResult: 提取结果
        """
        path = Path(file_path)
        
        if not path.exists():
            return ParameterExtractionResult(
                file_path=file_path,
                success=False,
                error_message=f"文件不存在: {file_path}"
            )
        
        try:
            content = path.read_text(encoding='utf-8', errors='ignore')
            return self.extract_from_content(content, file_path)
        except Exception as e:
            self._logger.error(f"读取文件失败: {e}")
            return ParameterExtractionResult(
                file_path=file_path,
                success=False,
                error_message=str(e)
            )
    
    def extract_from_content(
        self, 
        content: str, 
        file_path: str = ""
    ) -> ParameterExtractionResult:
        """
        从内容中提取参数
        
        Args:
            content: 电路文件内容
            file_path: 文件路径（用于记录）
            
        Returns:
            ParameterExtractionResult: 提取结果
        """
        parameters: List[TunableParameter] = []
        lines = content.splitlines()
        
        for line_num, line in enumerate(lines, start=1):
            # 跳过注释行
            stripped = line.strip()
            if stripped.startswith('*') or stripped.startswith(';'):
                continue
            
            # 尝试匹配各种模式
            param = self._try_extract_param(line, line_num)
            if param:
                parameters.append(param)
                continue
            
            param = self._try_extract_resistor(line, line_num)
            if param:
                parameters.append(param)
                continue
            
            param = self._try_extract_capacitor(line, line_num)
            if param:
                parameters.append(param)
                continue
            
            param = self._try_extract_inductor(line, line_num)
            if param:
                parameters.append(param)
                continue
            
            param = self._try_extract_voltage(line, line_num)
            if param:
                parameters.append(param)
                continue
            
            param = self._try_extract_current(line, line_num)
            if param:
                parameters.append(param)
        
        return ParameterExtractionResult(
            parameters=parameters,
            file_path=file_path,
            success=True
        )
    
    def _try_extract_param(
        self, 
        line: str, 
        line_num: int
    ) -> Optional[TunableParameter]:
        """尝试提取 .param 参数"""
        match = self.PARAM_PATTERN.match(line)
        if not match:
            return None
        
        name = match.group(1)
        value_str = match.group(2)
        unit = match.group(3) if match.group(3) else ""
        
        value = self._parse_value_with_unit(value_str, unit)
        
        return TunableParameter(
            name=name,
            value=value,
            unit=unit,
            param_type=ParameterType.PARAM,
            line_number=line_num,
            original_text=line.strip()
        )
    
    def _try_extract_resistor(
        self, 
        line: str, 
        line_num: int
    ) -> Optional[TunableParameter]:
        """尝试提取电阻参数"""
        match = self.RESISTOR_PATTERN.match(line)
        if not match:
            return None
        
        element_name = match.group(1)
        value_str = match.group(2)
        unit = match.group(3) if match.group(3) else "Ω"
        
        value = self._parse_value_with_unit(value_str, unit)
        
        return TunableParameter(
            name=element_name,
            value=value,
            unit="Ω",
            param_type=ParameterType.RESISTOR,
            line_number=line_num,
            original_text=line.strip(),
            element_name=element_name
        )
    
    def _try_extract_capacitor(
        self, 
        line: str, 
        line_num: int
    ) -> Optional[TunableParameter]:
        """尝试提取电容参数"""
        match = self.CAPACITOR_PATTERN.match(line)
        if not match:
            return None
        
        element_name = match.group(1)
        value_str = match.group(2)
        unit = match.group(3) if match.group(3) else "F"
        
        value = self._parse_value_with_unit(value_str, unit)
        
        return TunableParameter(
            name=element_name,
            value=value,
            unit="F",
            param_type=ParameterType.CAPACITOR,
            line_number=line_num,
            original_text=line.strip(),
            element_name=element_name
        )
    
    def _try_extract_inductor(
        self, 
        line: str, 
        line_num: int
    ) -> Optional[TunableParameter]:
        """尝试提取电感参数"""
        match = self.INDUCTOR_PATTERN.match(line)
        if not match:
            return None
        
        element_name = match.group(1)
        value_str = match.group(2)
        unit = match.group(3) if match.group(3) else "H"
        
        value = self._parse_value_with_unit(value_str, unit)
        
        return TunableParameter(
            name=element_name,
            value=value,
            unit="H",
            param_type=ParameterType.INDUCTOR,
            line_number=line_num,
            original_text=line.strip(),
            element_name=element_name
        )
    
    def _try_extract_voltage(
        self, 
        line: str, 
        line_num: int
    ) -> Optional[TunableParameter]:
        """尝试提取电压源参数"""
        match = self.VOLTAGE_PATTERN.match(line)
        if not match:
            return None
        
        element_name = match.group(1)
        value_str = match.group(2)
        unit = match.group(3) if match.group(3) else "V"
        
        value = self._parse_value_with_unit(value_str, unit)
        
        return TunableParameter(
            name=element_name,
            value=value,
            unit="V",
            param_type=ParameterType.VOLTAGE,
            line_number=line_num,
            original_text=line.strip(),
            element_name=element_name
        )
    
    def _try_extract_current(
        self, 
        line: str, 
        line_num: int
    ) -> Optional[TunableParameter]:
        """尝试提取电流源参数"""
        match = self.CURRENT_PATTERN.match(line)
        if not match:
            return None
        
        element_name = match.group(1)
        value_str = match.group(2)
        unit = match.group(3) if match.group(3) else "A"
        
        value = self._parse_value_with_unit(value_str, unit)
        
        return TunableParameter(
            name=element_name,
            value=value,
            unit="A",
            param_type=ParameterType.CURRENT,
            line_number=line_num,
            original_text=line.strip(),
            element_name=element_name
        )
    
    def _parse_value_with_unit(self, value_str: str, unit: str) -> float:
        """
        解析带单位前缀的数值
        
        Args:
            value_str: 数值字符串
            unit: 单位字符串（可能包含前缀）
            
        Returns:
            float: 解析后的数值
        """
        try:
            base_value = float(value_str)
        except ValueError:
            return 0.0
        
        # 检查单位前缀（按长度降序排列，确保 'meg' 在 'm' 之前匹配）
        if unit:
            unit_lower = unit.lower()
            # 按前缀长度降序排列
            sorted_prefixes = sorted(
                self.UNIT_PREFIXES.items(), 
                key=lambda x: len(x[0]), 
                reverse=True
            )
            for prefix, multiplier in sorted_prefixes:
                if unit_lower.startswith(prefix):
                    return base_value * multiplier
        
        return base_value
    
    def format_value_with_unit(self, value: float, unit: str) -> str:
        """
        格式化数值为带单位前缀的字符串
        
        Args:
            value: 数值
            unit: 基本单位
            
        Returns:
            str: 格式化后的字符串
        """
        abs_val = abs(value)
        
        if abs_val == 0:
            return f"0 {unit}"
        
        # 选择合适的前缀
        prefixes = [
            ('T', 1e12),
            ('G', 1e9),
            ('M', 1e6),
            ('k', 1e3),
            ('', 1),
            ('m', 1e-3),
            ('u', 1e-6),
            ('n', 1e-9),
            ('p', 1e-12),
            ('f', 1e-15),
        ]
        
        for prefix, multiplier in prefixes:
            if abs_val >= multiplier:
                scaled = value / multiplier
                if scaled == int(scaled):
                    return f"{int(scaled)} {prefix}{unit}"
                return f"{scaled:.3g} {prefix}{unit}"
        
        return f"{value:.3e} {unit}"


# 模块级单例
parameter_extractor = ParameterExtractor()


__all__ = [
    "ParameterExtractor",
    "ParameterType",
    "TunableParameter",
    "ParameterExtractionResult",
    "parameter_extractor",
]
