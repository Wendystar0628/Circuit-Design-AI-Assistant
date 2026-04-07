# RAG Domain - Embedding-only 向量知识检索域
"""
RAG 知识检索域 - Embedding-only 向量检索架构

提供：
- file_extractor  : 文件内容提取（PDF/DOCX/代码/文本）
- chunker         : 文件分块（按文件类型选策略）
- embedder        : 本地 Embedding 模型（sentence-transformers）
- vector_store    : ChromaDB 向量存储（upsert/delete/query）
- rag_manager     : 业务逻辑管理器（索引、查询、生命周期）
- document_watcher: 文件变更检测（防抖、增量索引触发）
"""

from domain.rag.chunker import Chunk, chunk_file
from domain.rag.embedder import Embedder
from domain.rag.file_extractor import FileIndexRule, extract_indexable_content, get_file_index_rule
from domain.rag.rag_manager import RAGManager
from domain.rag.vector_store import RAGQueryResult, VectorStore
from domain.rag.document_watcher import DocumentWatcher


__all__ = [
    "Chunk",
    "chunk_file",
    "Embedder",
    "extract_indexable_content",
    "FileIndexRule",
    "get_file_index_rule",
    "RAGManager",
    "RAGQueryResult",
    "VectorStore",
    "DocumentWatcher",
]
