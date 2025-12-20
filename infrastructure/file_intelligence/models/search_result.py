# Search Result - Search Result Data Classes
"""
搜索结果数据类

职责：
- 定义搜索结果的数据结构
- 定义搜索选项的数据结构
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class SearchType(Enum):
    """搜索类型"""
    NAME = "name"           # 按文件名搜索
    CONTENT = "content"     # 按内容搜索
    SYMBOL = "symbol"       # 按符号搜索


@dataclass
class SearchOptions:
    """
    搜索选项
    
    Attributes:
        query: 搜索查询
        search_type: 搜索类型
        file_types: 限定文件类型（如 [".cir", ".py"]）
        max_results: 最大结果数
        case_sensitive: 是否区分大小写
        fuzzy_threshold: 模糊匹配阈值（0.0-1.0）
        include_hidden: 是否包含隐藏文件
        exclude_patterns: 排除的路径模式
    """
    query: str
    search_type: SearchType = SearchType.NAME
    file_types: List[str] = field(default_factory=list)
    max_results: int = 50
    case_sensitive: bool = False
    fuzzy_threshold: float = 0.6
    include_hidden: bool = False
    exclude_patterns: List[str] = field(default_factory=lambda: [
        "__pycache__", ".git", ".circuit_ai/temp", "node_modules"
    ])


@dataclass
class SearchMatch:
    """
    单个搜索匹配
    
    Attributes:
        line_number: 匹配所在行号（从 1 开始）
        line_content: 匹配行的内容
        match_start: 匹配在行内的起始位置
        match_end: 匹配在行内的结束位置
        context_before: 匹配前的上下文行
        context_after: 匹配后的上下文行
    """
    line_number: int
    line_content: str
    match_start: int = 0
    match_end: int = 0
    context_before: List[str] = field(default_factory=list)
    context_after: List[str] = field(default_factory=list)


@dataclass
class SearchResult:
    """
    搜索结果
    
    Attributes:
        path: 文件路径（相对于工作目录）
        absolute_path: 文件绝对路径
        file_name: 文件名
        file_type: 文件类型（扩展名）
        score: 匹配分数（0.0-1.0，用于排序）
        matches: 匹配列表（内容搜索时有值）
        match_count: 匹配数量
        file_size: 文件大小（字节）
        modified_time: 修改时间（时间戳）
        metadata: 额外元数据
    """
    path: str
    absolute_path: str
    file_name: str
    file_type: str
    score: float = 1.0
    matches: List[SearchMatch] = field(default_factory=list)
    match_count: int = 0
    file_size: int = 0
    modified_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_path(
        cls,
        path: Path,
        relative_path: str,
        score: float = 1.0,
        matches: List[SearchMatch] = None
    ) -> "SearchResult":
        """
        从路径创建搜索结果
        
        Args:
            path: 文件绝对路径
            relative_path: 相对路径
            score: 匹配分数
            matches: 匹配列表
        """
        try:
            stat = path.stat()
            file_size = stat.st_size
            modified_time = stat.st_mtime
        except Exception:
            file_size = 0
            modified_time = 0.0
        
        matches = matches or []
        
        return cls(
            path=relative_path,
            absolute_path=str(path),
            file_name=path.name,
            file_type=path.suffix,
            score=score,
            matches=matches,
            match_count=len(matches),
            file_size=file_size,
            modified_time=modified_time,
        )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SearchType",
    "SearchOptions",
    "SearchMatch",
    "SearchResult",
]
