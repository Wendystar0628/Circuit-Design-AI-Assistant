# In-File Search Types - Single File Search Data Types
"""
单文件搜索数据类型

定义单文件搜索的请求和响应数据结构。
用于 InFileSearchService 和 FileContentLocator。

设计原则：
- 与项目级搜索类型分离，职责单一
- 支持分层降级策略的状态标识
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class InFileSearchOptions:
    """单文件搜索选项"""
    
    max_results: int = 5
    """最大结果数"""
    
    include_exact: bool = True
    """是否包含精确匹配"""
    
    include_semantic: bool = True
    """是否包含语义匹配（仅当文件已索引时有效）"""
    
    context_lines: int = 5
    """上下文行数"""
    
    min_score: float = 0.3
    """最低相关性分数"""


@dataclass
class InFileMatch:
    """单文件匹配项"""
    
    start_line: int
    """起始行号"""
    
    end_line: int
    """结束行号"""
    
    score: float
    """相关性分数（0-1）"""
    
    match_type: str
    """匹配类型（exact/semantic/merged）"""
    
    matched_text: str = ""
    """匹配的文本片段"""
    
    context_before: List[str] = field(default_factory=list)
    """上文行"""
    
    context_after: List[str] = field(default_factory=list)
    """下文行"""


@dataclass
class InFileSearchResult:
    """单文件搜索结果"""
    
    file_path: str
    """文件路径"""
    
    query: str
    """原始查询"""
    
    matches: List[InFileMatch] = field(default_factory=list)
    """匹配结果列表"""
    
    search_time_ms: float = 0.0
    """搜索耗时（毫秒）"""
    
    exact_count: int = 0
    """精确匹配数量"""
    
    semantic_count: int = 0
    """语义匹配数量"""
    
    semantic_available: bool = False
    """语义搜索是否可用（文件是否已索引）"""
    
    @property
    def total_count(self) -> int:
        """总匹配数量"""
        return len(self.matches)
    
    @property
    def has_matches(self) -> bool:
        """是否有匹配结果"""
        return len(self.matches) > 0


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "InFileSearchOptions",
    "InFileMatch",
    "InFileSearchResult",
]
