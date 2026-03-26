# RAG Service - Re-export from domain/rag
"""
RAG 检索服务 - 已迁移到 domain/rag/ 模块

原有基于 ChromaDB 的简单向量检索实现已被移除。
当前实现基于 LightRAG 架构，位于 domain/rag/。

本文件仅作为兼容性桥接，新代码请直接 import domain.rag。

参见：设计借鉴文档/LightRAG集成设计方案.md
"""

from domain.rag.rag_service import RAGService, RAGQueryResult

__all__ = ["RAGService", "RAGQueryResult"]
