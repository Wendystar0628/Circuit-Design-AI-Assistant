# RAG Domain - LightRAG 知识检索域
"""
RAG 知识检索域 - 基于 LightRAG 架构

提供：
- rag_service    : LightRAG 封装层（实例管理、LLM/Embedding 适配）
- rag_manager    : 业务逻辑管理器（索引、查询、模式管理）
- document_watcher: 文件变更检测（防抖、增量索引触发）
"""

from domain.rag.rag_service import RAGService
from domain.rag.rag_manager import RAGManager
from domain.rag.document_watcher import DocumentWatcher


__all__ = [
    "RAGService",
    "RAGManager",
    "DocumentWatcher",
]
