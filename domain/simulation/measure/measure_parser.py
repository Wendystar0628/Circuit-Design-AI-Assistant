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
from typing import Dict, List

from domain.simulation.measure.measure_metadata import measure_metadata_resolver
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
    
    # 排除的变量名（ngspice 内部变量，不是测量结果）
    EXCLUDED_NAMES = {
        'time', 'frequency', 'temp', 'hertz', 'alter', 'sweep',
        'v', 'i', 'vdb', 'vp', 'vm', 'vr', 'vi',  # 信号名前缀
    }
    
    def __init__(self):
        self._logger = logging.getLogger(__name__)
    
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
        
        # 预处理：移除 ngspice 输出中的前缀（如 "stdout "）
        cleaned_output = self._clean_output(output)
        
        # 解析成功的测量
        for match in self.MEASURE_SUCCESS_PATTERN.finditer(cleaned_output):
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
                metadata = measure_metadata_resolver.resolve(name)
                
                result = MeasureResult(
                    name=name,
                    value=value,
                    unit=metadata.unit,
                    status=MeasureStatus.OK,
                    display_name=metadata.display_name,
                    category=metadata.category,
                    quantity_kind=metadata.quantity_kind,
                    raw_output=full_match,
                )
                
                results.append(result)
                parsed_names.add(name)
                
                self._logger.debug(f"Parsed measure: {name} = {value} {metadata.unit}")
                
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
        for match in self.MEASURE_FAILED_PATTERN.finditer(cleaned_output):
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
    
    def _clean_output(self, output: str) -> str:
        """
        清理 ngspice 输出，移除前缀
        
        ngspice 共享库模式下，输出行可能带有 "stdout " 或 "stderr " 前缀
        
        Args:
            output: 原始输出
            
        Returns:
            str: 清理后的输出
        """
        lines = []
        for line in output.splitlines():
            # 移除 "stdout " 或 "stderr " 前缀
            if line.startswith("stdout "):
                line = line[7:]
            elif line.startswith("stderr "):
                line = line[7:]
            lines.append(line)
        return "\n".join(lines)


# 模块级单例
measure_parser = MeasureParser()
