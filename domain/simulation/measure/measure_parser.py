# Measure Parser
"""
.MEASURE 结果解析器

解析 ngspice 仿真输出中的 .MEASURE 结果。

ngspice .MEASURE 输出格式示例：
    简单格式：
        gain_db                 =  2.050000e+01
        f_3db                   =  1.000000e+06
    
    带范围格式：
        rise_time               =  1.234567e-09 from=  1.000000e-09 to=  2.234567e-09
    
    TRIG/TARG 格式：
        delay                   =  5.000000e-09 targ=  1.500000e-08 trig=  1.000000e-08
    
    失败格式：
        f_3db                   =  failed

使用示例：
    parser = MeasureParser()
    results = parser.parse_measure_output(ngspice_output)
    for result in results:
        print(f"{result.name}: {result.display_value}")
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

from domain.simulation.measure.measure_result import MeasureResult, MeasureStatus


class MeasureParser:
    """
    .MEASURE 结果解析器
    
    从 ngspice 输出中提取 .MEASURE 语句的执行结果。
    支持多种 ngspice 输出格式。
    """
    
    # 匹配成功的 .MEASURE 结果（支持多种格式）
    # 格式1: name = value
    # 格式2: name = value from=xxx to=xxx
    # 格式3: name = value targ=xxx trig=xxx
    MEASURE_SUCCESS_PATTERN = re.compile(
        r"^\s*(\w+)\s*=\s*([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)"
        r"(?:\s+(?:from|targ|trig|at)\s*=\s*[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)*",
        re.MULTILINE
    )
    
    # 匹配失败的 .MEASURE 结果
    MEASURE_FAILED_PATTERN = re.compile(
        r"^\s*(\w+)\s*=\s*failed",
        re.MULTILINE | re.IGNORECASE
    )
    
    # 匹配带附加信息的测量结果（提取 from/to/trig/targ 值）
    MEASURE_DETAIL_PATTERN = re.compile(
        r"(from|to|targ|trig|at)\s*=\s*([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)",
        re.IGNORECASE
    )
    
    # 排除的变量名（ngspice 内部变量，不是测量结果）
    EXCLUDED_NAMES = {
        'time', 'frequency', 'temp', 'hertz', 'alter', 'sweep',
        'v', 'i', 'vdb', 'vp', 'vm', 'vr', 'vi',  # 信号名前缀
    }
    
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
        parsed_names = set()
        
        # 解析成功的测量
        for match in self.MEASURE_SUCCESS_PATTERN.finditer(output):
            name = match.group(1)
            value_str = match.group(2)
            full_match = match.group(0).strip()
            
            # 跳过排除的名称
            if name.lower() in self.EXCLUDED_NAMES:
                continue
            
            # 跳过已解析的名称（避免重复）
            if name in parsed_names:
                continue
            
            try:
                value = float(value_str)
                unit = self._infer_unit(name)
                
                # 提取附加信息
                details = self._extract_details(full_match)
                
                result = MeasureResult(
                    name=name,
                    value=value,
                    unit=unit,
                    status=MeasureStatus.OK,
                    raw_output=full_match,
                )
                
                results.append(result)
                parsed_names.add(name)
                
                self._logger.debug(f"Parsed measure: {name} = {value} {unit}")
                
            except ValueError as e:
                self._logger.warning(f"Failed to parse measure value: {name} = {value_str}")
                results.append(MeasureResult(
                    name=name,
                    value=None,
                    status=MeasureStatus.PARSE_ERROR,
                    error_message=str(e),
                    raw_output=full_match,
                ))
                parsed_names.add(name)
        
        # 解析失败的测量
        for match in self.MEASURE_FAILED_PATTERN.finditer(output):
            name = match.group(1)
            
            # 跳过已解析的名称
            if name in parsed_names:
                continue
            
            results.append(MeasureResult(
                name=name,
                value=None,
                status=MeasureStatus.FAILED,
                error_message="Measurement condition not met",
                raw_output=match.group(0).strip(),
            ))
            parsed_names.add(name)
            
            self._logger.debug(f"Measure failed: {name}")
        
        return results
    
    def _extract_details(self, line: str) -> Dict[str, float]:
        """
        从测量结果行中提取附加信息
        
        Args:
            line: 测量结果行
            
        Returns:
            Dict[str, float]: 附加信息字典，如 {"from": 1e-9, "to": 2e-9}
        """
        details = {}
        for match in self.MEASURE_DETAIL_PATTERN.finditer(line):
            key = match.group(1).lower()
            try:
                value = float(match.group(2))
                details[key] = value
            except ValueError:
                pass
        return details
    
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
        
        # 根据名称推断单位（按优先级排序）
        # dB 相关
        if "db" in name_lower:
            return "dB"
        # 频率相关
        if any(kw in name_lower for kw in ["freq", "f_", "bw", "gbw", "ugf", "bandwidth"]):
            return "Hz"
        # 相位相关
        if any(kw in name_lower for kw in ["phase", "margin", "pm", "deg"]):
            return "°"
        # 时间相关
        if any(kw in name_lower for kw in ["time", "rise", "fall", "delay", "period", "pw"]):
            return "s"
        # 压摆率
        if "slew" in name_lower or "sr" in name_lower:
            return "V/s"
        # 电流相关
        if name_lower.startswith("i") or "current" in name_lower or "bias" in name_lower:
            return "A"
        # 电压相关
        if name_lower.startswith("v") or "voltage" in name_lower or "offset" in name_lower:
            return "V"
        # 功率相关
        if "power" in name_lower or "pwr" in name_lower or "pdiss" in name_lower:
            return "W"
        # 电阻相关
        if name_lower.startswith("r") or "resistance" in name_lower or "impedance" in name_lower:
            return "Ω"
        # 增益（无单位或 V/V）
        if "gain" in name_lower and "db" not in name_lower:
            return "V/V"
        
        return ""
    
    def validate_measure_statement(self, statement: str) -> Tuple[bool, Optional[str]]:
        """
        验证 .MEASURE 语句语法
        
        Args:
            statement: .MEASURE 语句
            
        Returns:
            Tuple[bool, Optional[str]]: (是否有效, 错误信息)
        """
        statement = statement.strip()
        
        if not statement.upper().startswith(".MEASURE"):
            return False, "语句必须以 .MEASURE 开头"
        
        parts = statement.split()
        if len(parts) < 4:
            return False, "语句格式不完整，至少需要: .MEASURE <type> <name> <measurement>"
        
        # 检查分析类型
        analysis_type = parts[1].upper()
        valid_types = {"AC", "DC", "TRAN", "OP", "NOISE"}
        if analysis_type not in valid_types:
            return False, f"无效的分析类型 '{analysis_type}'，有效类型: {valid_types}"
        
        # 检查常见语法错误
        # 错误：使用引号包裹表达式（应使用 par()）
        if "='" in statement or "=\"" in statement:
            return False, "引用其他测量结果时应使用 par('expr') 而不是引号"
        
        return True, None


# 模块级单例
measure_parser = MeasureParser()
