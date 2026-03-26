# Vector Retriever - Placeholder (Cleared for LightRAG Integration)
"""
向量语义检索器 - 已清空，等待 LightRAG 集成实现

原有基于 SVC_VECTOR_STORE 的简单向量检索实现已被移除，
将由 domain/rag/ 模块基于 LightRAG 架构重新实现。
LightRAG 使用 KV + Vector + Graph 三层存储和多模式检索（naive/local/global/hybrid/mix），
不再需要独立的 VectorRetriever。

被调用方：context_retriever.py（未来将改为调用 RAGManager）

参见：设计借鉴文档/LightRAG集成设计方案.md
"""

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class VectorMatch:
    """向量检索结果（保留数据类供 ContextAssembler 兼容）"""
    path: str
    content: str
    relevance: float
    source: str = "vector"
    token_count: int = 0
    collection: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "content": self.content,
            "relevance": self.relevance,
            "source": self.source,
            "token_count": self.token_count,
        }


class VectorRetriever:
    """
    向量语义检索器 - 占位实现
    
    LightRAG 集成后将由 RAGManager 替代。
    当前保留空壳以避免导入错误。
    """

    def __init__(self):
        pass

    def is_enabled(self) -> bool:
        return False

    def retrieve(self, query: str, top_k: int = 10) -> List[VectorMatch]:
        return []

    def get_status(self) -> Dict[str, Any]:
        return {
            "enabled": False,
            "note": "Pending LightRAG integration",
        }


__all__ = [
    "VectorRetriever",
    "VectorMatch",
]
