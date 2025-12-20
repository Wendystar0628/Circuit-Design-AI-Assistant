# File Intelligence Analysis Module
"""
轻量级文件分析模块

职责：
- 提供符号提取功能，用于 IDE 功能（跳转定义、查找引用、结构大纲）
- 不做深度语义分析，仅提取符号名称和位置信息

与其他模块的区别：
- 本模块：轻量级符号提取，用于 IDE 功能
- 阶段5 RAG 分块器：语法感知分块，用于向量索引
- 阶段3 dependency_analyzer：依赖图分析，用于上下文注入
"""

from infrastructure.file_intelligence.analysis.symbol_types import (
    SymbolType,
    SymbolInfo,
    FileStructure,
)
from infrastructure.file_intelligence.analysis.file_analyzer import FileAnalyzer

__all__ = [
    "SymbolType",
    "SymbolInfo",
    "FileStructure",
    "FileAnalyzer",
]
