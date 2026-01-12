# Measure Injector
"""
.MEASURE 语句注入器

将 .MEASURE 语句注入到 SPICE 网表中。

使用示例：
    injector = MeasureInjector()
    
    measures = [
        ".MEASURE AC gain_db MAX VDB(out)",
        ".MEASURE AC f_3db WHEN VDB(out)=gain_db-3 FALL=1",
    ]
    
    modified_netlist = injector.inject_measures(original_netlist, measures)
"""

import logging
import re
from typing import List, Optional


class MeasureInjector:
    """
    .MEASURE 语句注入器
    
    将 LLM 生成的 .MEASURE 语句注入到 SPICE 网表中。
    """
    
    def __init__(self):
        self._logger = logging.getLogger(__name__)
    
    def inject_measures(
        self,
        netlist: str,
        measures: List[str],
        position: str = "before_end"
    ) -> str:
        """
        将 .MEASURE 语句注入到网表中
        
        Args:
            netlist: 原始网表内容
            measures: .MEASURE 语句列表
            position: 注入位置
                - "before_end": 在 .END 语句之前（默认）
                - "after_analysis": 在分析语句之后
                
        Returns:
            str: 修改后的网表内容
        """
        if not measures:
            return netlist
        
        # 过滤空语句和注释
        valid_measures = [
            m.strip() for m in measures
            if m.strip() and not m.strip().startswith("*")
        ]
        
        if not valid_measures:
            return netlist
        
        # 确保每个语句以 .MEASURE 开头
        normalized_measures = []
        for m in valid_measures:
            if not m.upper().startswith(".MEASURE"):
                self._logger.warning(f"Invalid measure statement (missing .MEASURE): {m}")
                continue
            normalized_measures.append(m)
        
        if not normalized_measures:
            return netlist
        
        # 构建注入块
        measure_block = "\n* === LLM Generated Measurements ===\n"
        measure_block += "\n".join(normalized_measures)
        measure_block += "\n* === End Measurements ===\n"
        
        # 根据位置注入
        if position == "before_end":
            return self._inject_before_end(netlist, measure_block)
        elif position == "after_analysis":
            return self._inject_after_analysis(netlist, measure_block)
        else:
            self._logger.warning(f"Unknown injection position: {position}, using before_end")
            return self._inject_before_end(netlist, measure_block)
    
    def _inject_before_end(self, netlist: str, measure_block: str) -> str:
        """在 .END 语句之前注入"""
        # 查找 .END 语句
        end_pattern = re.compile(r"^\.END\s*$", re.MULTILINE | re.IGNORECASE)
        match = end_pattern.search(netlist)
        
        if match:
            # 在 .END 之前插入
            insert_pos = match.start()
            return netlist[:insert_pos] + measure_block + "\n" + netlist[insert_pos:]
        else:
            # 没有 .END，追加到末尾
            self._logger.warning("No .END statement found, appending measures to end")
            return netlist + "\n" + measure_block + "\n.END\n"
    
    def _inject_after_analysis(self, netlist: str, measure_block: str) -> str:
        """在分析语句之后注入"""
        # 查找最后一个分析语句（.AC, .DC, .TRAN, .OP, .NOISE 等）
        analysis_pattern = re.compile(
            r"^\.(AC|DC|TRAN|OP|NOISE|TF|SENS)\s+.*$",
            re.MULTILINE | re.IGNORECASE
        )
        
        matches = list(analysis_pattern.finditer(netlist))
        
        if matches:
            # 在最后一个分析语句之后插入
            last_match = matches[-1]
            insert_pos = last_match.end()
            return netlist[:insert_pos] + "\n" + measure_block + netlist[insert_pos:]
        else:
            # 没有分析语句，使用 before_end
            self._logger.warning("No analysis statement found, using before_end")
            return self._inject_before_end(netlist, measure_block)
    
    def remove_measures(self, netlist: str) -> str:
        """
        从网表中移除已注入的 .MEASURE 语句
        
        Args:
            netlist: 网表内容
            
        Returns:
            str: 移除 .MEASURE 后的网表
        """
        # 移除 LLM 生成的测量块
        block_pattern = re.compile(
            r"\n?\* === LLM Generated Measurements ===\n.*?\n\* === End Measurements ===\n?",
            re.DOTALL
        )
        netlist = block_pattern.sub("", netlist)
        
        # 移除所有 .MEASURE 语句
        measure_pattern = re.compile(r"^\.MEASURE\s+.*$\n?", re.MULTILINE | re.IGNORECASE)
        netlist = measure_pattern.sub("", netlist)
        
        return netlist
    
    def extract_measures(self, netlist: str) -> List[str]:
        """
        从网表中提取现有的 .MEASURE 语句
        
        Args:
            netlist: 网表内容
            
        Returns:
            List[str]: .MEASURE 语句列表
        """
        measure_pattern = re.compile(r"^\.MEASURE\s+.*$", re.MULTILINE | re.IGNORECASE)
        return [m.group(0) for m in measure_pattern.finditer(netlist)]


# 模块级单例
measure_injector = MeasureInjector()
