# Unified Search Result Models
"""
统一搜索结果数据模型

职责：
- 定义统一搜索的输入输出数据结构
- 支持精确匹配和语义匹配的分组展示
- 包含 Token 预算配置
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SearchScope(Enum):
    """搜索范围"""
    ALL = "all"           # 全部搜索（精确 + 语义）
    CODE = "code"         # 仅代码文件（精确搜索）
    DOCS = "docs"         # 仅文档（语义搜索）
    EXACT = "exact"       # 仅精确搜索
    SEMANTIC = "semantic" # 仅语义搜索


@dataclass
class TokenBudgetConfig:
    """
    Token 预算配置
    
    默认总预算：4000 tokens
    精确搜索结果预算：40%（1600 tokens）
    语义搜索结果预算：60%（2400 tokens）
    单条结果最大长度：500 tokens
    """
    total_budget: int = 4000
    """总 Token 预算"""
    
    exact_ratio: float = 0.4
    """精确搜索结果预算比例"""
    
    semantic_ratio: float = 0.6
    """语义搜索结果预算比例"""
    
    max_result_tokens: int = 500
    """单条结果最大 Token 数"""
    
    @property
    def exact_budget(self) -> int:
        """精确搜索预算"""
        return int(self.total_budget * self.exact_ratio)
    
    @property
    def semantic_budget(self) -> int:
        """语义搜索预算"""
        return int(self.total_budget * self.semantic_ratio)


@dataclass
class ExactMatchResult:
    """精确匹配结果"""
    file_path: str
    """文件相对路径"""
    
    file_name: str
    """文件名"""
    
    match_type: str
    """匹配类型：name/content/symbol"""
    
    score: float
    """匹配分数（0-1）"""
    
    line_number: Optional[int] = None
    """匹配行号（内容/符号搜索时有值）"""
    
    line_content: Optional[str] = None
    """匹配行内容"""
    
    context_before: List[str] = field(default_factory=list)
    """上文（2行）"""
    
    context_after: List[str] = field(default_factory=list)
    """下文（2行）"""
    
    symbol_info: Optional[Dict[str, Any]] = None
    """符号信息（符号搜索时有值）"""
    
    token_count: int = 0
    """估算的 Token 数"""


@dataclass
class SemanticMatchResult:
    """语义匹配结果"""
    content: str
    """文档内容片段"""
    
    source: str
    """来源（文件路径或 URL）"""
    
    score: float
    """相关性分数（0-1）"""
    
    chunk_id: str = ""
    """文档块 ID"""
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    """元数据"""
    
    token_count: int = 0
    """估算的 Token 数"""


@dataclass
class UnifiedSearchResult:
    """
    统一搜索结果
    
    包含精确匹配和语义匹配两个分组，
    让 LLM 自己判断哪个更有用。
    """
    query: str
    """原始查询"""
    
    scope: SearchScope
    """搜索范围"""
    
    exact_matches: List[ExactMatchResult] = field(default_factory=list)
    """精确匹配结果（来自 FileSearchService）"""
    
    semantic_matches: List[SemanticMatchResult] = field(default_factory=list)
    """语义匹配结果（来自 RAGService）"""
    
    total_exact_count: int = 0
    """精确匹配总数（截断前）"""
    
    total_semantic_count: int = 0
    """语义匹配总数（截断前）"""
    
    exact_tokens_used: int = 0
    """精确匹配使用的 Token 数"""
    
    semantic_tokens_used: int = 0
    """语义匹配使用的 Token 数"""
    
    search_time_ms: float = 0.0
    """搜索耗时（毫秒）"""
    
    @property
    def total_matches(self) -> int:
        """返回的匹配总数"""
        return len(self.exact_matches) + len(self.semantic_matches)
    
    @property
    def total_tokens_used(self) -> int:
        """使用的总 Token 数"""
        return self.exact_tokens_used + self.semantic_tokens_used
    
    @property
    def has_results(self) -> bool:
        """是否有搜索结果"""
        return self.total_matches > 0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 JSON 序列化）"""
        return {
            "query": self.query,
            "scope": self.scope.value,
            "exact_matches": [
                {
                    "file_path": m.file_path,
                    "file_name": m.file_name,
                    "match_type": m.match_type,
                    "score": m.score,
                    "line_number": m.line_number,
                    "line_content": m.line_content,
                    "context_before": m.context_before,
                    "context_after": m.context_after,
                }
                for m in self.exact_matches
            ],
            "semantic_matches": [
                {
                    "content": m.content,
                    "source": m.source,
                    "score": m.score,
                }
                for m in self.semantic_matches
            ],
            "stats": {
                "total_exact_count": self.total_exact_count,
                "total_semantic_count": self.total_semantic_count,
                "exact_tokens_used": self.exact_tokens_used,
                "semantic_tokens_used": self.semantic_tokens_used,
                "search_time_ms": self.search_time_ms,
            },
        }


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SearchScope",
    "TokenBudgetConfig",
    "ExactMatchResult",
    "SemanticMatchResult",
    "UnifiedSearchResult",
]
