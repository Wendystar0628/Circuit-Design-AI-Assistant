# File Intelligence - Smart File Operations
"""
智能文件操作模块

职责：
- 提供智能文件搜索、内容分析、符号定位等高级功能
- 基于 file_manager.py 的基础能力构建
- 提供多策略回退机制，确保操作可靠性

架构说明：
- search/ - 实时文件搜索，不依赖向量索引
- analysis/ - 轻量级符号提取，用于跳转定义和查找引用
- location/ - 符号定位服务，支持多种定位策略（后续实现）
- models/ - 数据模型

与其他模块的关系：
- 电路依赖图分析由阶段3的 dependency_analyzer.py 负责
- 深度文档分块和向量索引由阶段5的 knowledge 模块负责
- 本模块的符号提取器是轻量级实现，仅提取符号名称和位置
"""

# 搜索模块
from infrastructure.file_intelligence.search import FileSearchService

# 分析模块
from infrastructure.file_intelligence.analysis import (
    FileAnalyzer,
    SymbolType,
    SymbolInfo,
    FileStructure,
)

# 数据模型
from infrastructure.file_intelligence.models import (
    SearchType,
    SearchResult,
    SearchOptions,
    SearchMatch,
)

__all__ = [
    # 搜索服务
    "FileSearchService",
    # 分析服务
    "FileAnalyzer",
    # 符号类型
    "SymbolType",
    "SymbolInfo",
    "FileStructure",
    # 搜索数据模型
    "SearchType",
    "SearchResult",
    "SearchOptions",
    "SearchMatch",
]
