# SPICE Symbol Extractor - Lightweight Symbol Extraction for SPICE Files
"""
SPICE 符号提取器

职责：
- 从 SPICE 文件中提取符号信息（轻量级，用于 IDE 功能）
- 支持跳转定义、查找引用、结构大纲

提取的符号类型：
- subcircuit: 子电路定义 (.subckt ... .ends)
- parameter: 参数定义 (.param)
- model: 模型定义 (.model)

与阶段5的区别：
- 本模块仅提取符号名称和位置，用于跳转定义
- 阶段5的 spice_chunker.py 做语法感知分块，用于 RAG 索引
"""

import re
from pathlib import Path
from typing import List, Optional, Tuple

from infrastructure.file_intelligence.analysis.symbol_types import (
    SymbolType,
    SymbolInfo,
    FileStructure,
)


class SpiceSymbolExtractor:
    """
    SPICE 符号提取器
    
    轻量级实现，仅提取符号名称和位置信息。
    """
    
    # 支持的文件扩展名
    SUPPORTED_EXTENSIONS = {".cir", ".sp", ".spice", ".net", ".ckt"}
    
    # 正则模式
    SUBCKT_START_PATTERN = re.compile(
        r'^\.subckt\s+(\w+)',
        re.IGNORECASE
    )
    SUBCKT_END_PATTERN = re.compile(
        r'^\.ends\b',
        re.IGNORECASE
    )
    PARAM_PATTERN = re.compile(
        r'^\.param\s+(\w+)\s*=',
        re.IGNORECASE
    )
    MODEL_PATTERN = re.compile(
        r'^\.model\s+(\w+)\s+(\w+)',
        re.IGNORECASE
    )
    INCLUDE_PATTERN = re.compile(
        r'^\.include\s+["\']?([^"\']+)["\']?',
        re.IGNORECASE
    )
    LIB_PATTERN = re.compile(
        r'^\.lib\s+["\']?([^"\']+)["\']?',
        re.IGNORECASE
    )
    
    @classmethod
    def supports(cls, file_path: str) -> bool:
        """检查是否支持该文件类型"""
        return Path(file_path).suffix.lower() in cls.SUPPORTED_EXTENSIONS
    
    def extract_symbols(self, file_path: str) -> FileStructure:
        """
        提取文件中的所有符号
        
        Args:
            file_path: 文件路径
            
        Returns:
            FileStructure: 文件结构信息
        """
        file_path = str(file_path)
        structure = FileStructure(file_path=file_path)
        
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return structure
        
        lines = content.splitlines()
        
        # 跟踪当前子电路
        current_subckt: Optional[SymbolInfo] = None
        
        for line_num, line in enumerate(lines, start=1):
            line_stripped = line.strip()
            
            # 跳过空行和注释
            if not line_stripped or line_stripped.startswith("*"):
                continue
            
            # 处理续行（以 + 开头）
            if line_stripped.startswith("+"):
                continue
            
            # 检查 .subckt 开始
            match = self.SUBCKT_START_PATTERN.match(line_stripped)
            if match:
                name = match.group(1)
                # 提取端口列表作为签名
                parts = line_stripped.split()
                ports = parts[2:] if len(parts) > 2 else []
                signature = f"({', '.join(ports)})" if ports else None
                
                current_subckt = SymbolInfo(
                    name=name,
                    type=SymbolType.SUBCIRCUIT,
                    line_start=line_num,
                    column_start=line.find("."),
                    signature=signature,
                )
                continue
            
            # 检查 .ends 结束
            if self.SUBCKT_END_PATTERN.match(line_stripped):
                if current_subckt:
                    current_subckt.line_end = line_num
                    structure.symbols.append(current_subckt)
                    current_subckt = None
                continue
            
            # 检查 .param
            match = self.PARAM_PATTERN.match(line_stripped)
            if match:
                name = match.group(1)
                # 提取完整的参数表达式
                eq_pos = line_stripped.find("=")
                value = line_stripped[eq_pos + 1:].strip() if eq_pos > 0 else None
                
                symbol = SymbolInfo(
                    name=name,
                    type=SymbolType.PARAMETER,
                    line_start=line_num,
                    column_start=line.find("."),
                    metadata={"value": value} if value else {},
                )
                
                if current_subckt:
                    symbol.parent = current_subckt.name
                    current_subckt.children.append(symbol)
                else:
                    structure.symbols.append(symbol)
                continue
            
            # 检查 .model
            match = self.MODEL_PATTERN.match(line_stripped)
            if match:
                name = match.group(1)
                model_type = match.group(2)
                
                symbol = SymbolInfo(
                    name=name,
                    type=SymbolType.MODEL,
                    line_start=line_num,
                    column_start=line.find("."),
                    metadata={"model_type": model_type},
                )
                
                if current_subckt:
                    symbol.parent = current_subckt.name
                    current_subckt.children.append(symbol)
                else:
                    structure.symbols.append(symbol)
                continue
            
            # 检查 .include
            match = self.INCLUDE_PATTERN.match(line_stripped)
            if match:
                include_path = match.group(1).strip()
                structure.includes.append(include_path)
                continue
            
            # 检查 .lib
            match = self.LIB_PATTERN.match(line_stripped)
            if match:
                lib_path = match.group(1).strip()
                structure.includes.append(lib_path)
                continue
        
        # 处理未闭合的子电路
        if current_subckt:
            current_subckt.line_end = len(lines)
            structure.symbols.append(current_subckt)
        
        return structure
    
    def find_symbol(
        self,
        file_path: str,
        symbol_name: str
    ) -> Optional[SymbolInfo]:
        """
        查找符号定义位置
        
        Args:
            file_path: 文件路径
            symbol_name: 符号名称
            
        Returns:
            SymbolInfo: 符号信息，未找到返回 None
        """
        structure = self.extract_symbols(file_path)
        return structure.find_symbol(symbol_name)
    
    def get_includes(self, file_path: str) -> List[str]:
        """
        获取 .include 引用列表
        
        Args:
            file_path: 文件路径
            
        Returns:
            List[str]: 引用的文件路径列表
        """
        structure = self.extract_symbols(file_path)
        return structure.includes
    
    def find_symbol_references(
        self,
        file_path: str,
        symbol_name: str
    ) -> List[Tuple[int, str]]:
        """
        查找符号引用（简单实现：文本搜索）
        
        Args:
            file_path: 文件路径
            symbol_name: 符号名称
            
        Returns:
            List[Tuple[int, str]]: [(行号, 行内容), ...]
        """
        references = []
        
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return references
        
        # 构建匹配模式：符号名作为独立单词
        pattern = re.compile(rf'\b{re.escape(symbol_name)}\b', re.IGNORECASE)
        
        for line_num, line in enumerate(content.splitlines(), start=1):
            if pattern.search(line):
                references.append((line_num, line.strip()))
        
        return references


__all__ = ["SpiceSymbolExtractor"]
