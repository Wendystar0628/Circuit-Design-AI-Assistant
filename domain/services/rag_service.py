# RAG Service - Re-export from domain/rag
"""
RAG 检索服务 - 兼容性桥接

已迁移到 domain/rag/ 模块。
新代码请直接使用 domain.rag.RAGQueryResult。
"""

from domain.rag.vector_store import RAGQueryResult

__all__ = ["RAGQueryResult"]
