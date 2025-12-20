# Symbol Types - Symbol Data Structures
"""
符号数据类型定义

用于 IDE 功能：跳转定义、查找引用、结构大纲
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class SymbolType(Enum):
    """符号类型"""
    # SPICE 符号类型
    SUBCIRCUIT = "subcircuit"   # 子电路定义 (.subckt ... .ends)
    PARAMETER = "parameter"     # 参数定义 (.param)
    MODEL = "model"             # 模型定义 (.model)
    
    # Python 符号类型
    CLASS = "class"             # 类定义
    FUNCTION = "function"       # 函数定义
    METHOD = "method"           # 方法定义
    VARIABLE = "variable"       # 全局变量
    
    # 通用
    UNKNOWN = "unknown"


@dataclass
class SymbolInfo:
    """
    符号信息
    
    Attributes:
        name: 符号名称
        type: 符号类型
        line_start: 起始行号（从 1 开始）
        line_end: 结束行号（单行符号时等于 line_start）
        column_start: 起始列号（从 0 开始）
        column_end: 结束列号
        signature: 函数/方法签名（如适用）
        docstring: 文档字符串（如适用）
        parent: 父符号名称（如方法的所属类）
        children: 子符号列表（如类的方法）
        metadata: 额外元数据
    """
    name: str
    type: SymbolType
    line_start: int
    line_end: int = 0
    column_start: int = 0
    column_end: int = 0
    signature: Optional[str] = None
    docstring: Optional[str] = None
    parent: Optional[str] = None
    children: List["SymbolInfo"] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    
    def __post_init__(self):
        if self.line_end == 0:
            self.line_end = self.line_start
    
    @property
    def is_multiline(self) -> bool:
        """是否跨多行"""
        return self.line_end > self.line_start
    
    @property
    def display_name(self) -> str:
        """显示名称（带签名）"""
        if self.signature:
            return f"{self.name}{self.signature}"
        return self.name
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "name": self.name,
            "type": self.type.value,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "column_start": self.column_start,
            "column_end": self.column_end,
            "signature": self.signature,
            "docstring": self.docstring,
            "parent": self.parent,
            "children": [c.to_dict() for c in self.children],
            "metadata": self.metadata,
        }


@dataclass
class FileStructure:
    """
    文件结构（用于大纲视图）
    
    Attributes:
        file_path: 文件路径
        symbols: 顶层符号列表
        includes: 引用的文件列表（SPICE .include）
        imports: 导入列表（Python import）
    """
    file_path: str
    symbols: List[SymbolInfo] = field(default_factory=list)
    includes: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    
    @property
    def symbol_count(self) -> int:
        """符号总数（包括嵌套）"""
        count = 0
        for symbol in self.symbols:
            count += 1 + len(symbol.children)
        return count
    
    def find_symbol(self, name: str) -> Optional[SymbolInfo]:
        """
        查找符号（支持嵌套查找）
        
        Args:
            name: 符号名称
            
        Returns:
            SymbolInfo: 找到的符号，未找到返回 None
        """
        for symbol in self.symbols:
            if symbol.name == name:
                return symbol
            for child in symbol.children:
                if child.name == name:
                    return child
        return None
    
    def get_symbols_by_type(self, symbol_type: SymbolType) -> List[SymbolInfo]:
        """
        按类型获取符号
        
        Args:
            symbol_type: 符号类型
            
        Returns:
            List[SymbolInfo]: 符号列表
        """
        result = []
        for symbol in self.symbols:
            if symbol.type == symbol_type:
                result.append(symbol)
            for child in symbol.children:
                if child.type == symbol_type:
                    result.append(child)
        return result
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "file_path": self.file_path,
            "symbols": [s.to_dict() for s in self.symbols],
            "includes": self.includes,
            "imports": self.imports,
        }


__all__ = [
    "SymbolType",
    "SymbolInfo",
    "FileStructure",
]
