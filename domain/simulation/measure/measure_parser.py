# Measure Parser
"""
.MEASURE 结果解析器

解析 ngspice 仿真输出中的 .MEASURE 结果。

ngspice .MEASURE 输出格式示例：
    gain_db                 =  2.050000e+01
    f_3db                   =  1.000000e+06
    phase_margin            =  6.500000e+01

使用示例：
    parser = MeasureParser()
    results = parser.parse_measure_output(ngspice_output)
    for result in results:
        print(f"{result.name}: {result.display_value}")
"""

import logging
import re
from typing import Dict, List, Optional

from domain.simulation.measure.measure_result import MeasureResult, MeasureStatus


class MeasureParser:
    """
    .MEASURE 结果解析器
    
    从 ngspice 输出中提取 .MEASURE 语句的执行结果。
    """
    
    # 匹配 .MEASURE 结果行的正则表达式
    # 格式: name = value 或 name = value from ... to ...
    MEASURE_PATTERN = re.compile(
        r"^\s*(\w+)\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*(?:from|targ|trig)?",
        re.MULTILINE
    )
    
    # 匹配失败的 .MEASURE 结果
    MEASURE_FAILED_PATTERN = re.compile(
        r"^\s*(\w+)\s*=\s*failed",
        re.MULTILINE | re.IGNORECASE
    )
    
    def __init__(self):
        self._logger = logging.getLogger(__name__)
        self._unit_hints: Dict[str, str] = {}
    
    def set_unit_hints(self, hints: Dict[str, str]):
        """
        设置单位提示
        
        Args:
            hints: 测量名称到单位的映射，如 {"gain_db": "dB", "f_3db": "Hz"}
        """
        self._unit_hints = hints
    
    def parse_measure_output(self, output: str) -> List[MeasureResult]:
        """
        解析 ngspice 输出中的 .MEASURE 结果
        
        Args:
            output: ngspice 完整输出文本
            
        Returns:
            List[MeasureResult]: 解析出的测量结果列表
        """
        results = []
        
        # 解析成功的测量
        for match in self.MEASURE_PATTERN.finditer(output):
            name = match.group(1)
            value_str = match.group(2)
            
            try:
                value = float(value_str)
                unit = self._infer_unit(name)
                
                results.append(MeasureResult(
                    name=name,
                    value=value,
                    unit=unit,
                    status=MeasureStatus.OK,
                    raw_output=match.group(0).strip(),
                ))
                
                self._logger.debug(f"Parsed measure: {name} = {value} {unit}")
                
            except ValueError as e:
                self._logger.warning(f"Failed to parse measure value: {name} = {value_str}")
                results.append(MeasureResult(
                    name=name,
                    value=None,
                    status=MeasureStatus.PARSE_ERROR,
                    error_message=str(e),
                    raw_output=match.group(0).strip(),
                ))
        
        # 解析失败的测量
        for match in self.MEASURE_FAILED_PATTERN.finditer(output):
            name = match.group(1)
            
            # 检查是否已经有成功的结果（避免重复）
            if not any(r.name == name for r in results):
                results.append(MeasureResult(
                    name=name,
                    value=None,
                    status=MeasureStatus.FAILED,
                    error_message="Measurement condition not met",
                    raw_output=match.group(0).strip(),
                ))
                
                self._logger.debug(f"Measure failed: {name}")
        
        return results
    
    def _infer_unit(self, name: str) -> str:
        """
        根据测量名称推断单位
        
        Args:
            name: 测量名称
            
        Returns:
            str: 推断的单位
        """
        # 优先使用用户提供的单位提示
        if name in self._unit_hints:
            return self._unit_hints[name]
        
        name_lower = name.lower()
        
        # 根据名称推断单位
        if "db" in name_lower or "gain" in name_lower:
            return "dB"
        elif "freq" in name_lower or "f_" in name_lower or "bw" in name_lower:
            return "Hz"
        elif "phase" in name_lower or "margin" in name_lower:
            return "°"
        elif "time" in name_lower or "rise" in name_lower or "fall" in name_lower:
            return "s"
        elif "slew" in name_lower:
            return "V/s"
        elif "current" in name_lower or name_lower.startswith("i"):
            return "A"
        elif "voltage" in name_lower or name_lower.startswith("v"):
            return "V"
        elif "power" in name_lower:
            return "W"
        elif "resistance" in name_lower or name_lower.startswith("r"):
            return "Ω"
        
        return ""


# 模块级单例
measure_parser = MeasureParser()
