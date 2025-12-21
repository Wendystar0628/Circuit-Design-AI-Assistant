# Vector Retriever
"""
向量语义检索器 - 使用向量语义在知识库中检索相关内容

职责：
- 使用向量语义在知识库中检索相关内容
- 支持代码集合和论文集合的检索

阶段依赖说明：
- 本模块依赖阶段四的 vector_store
- 阶段三实现时返回空结果
- 阶段四完成后通过配置开关启用

启用条件：
- vector_store 服务已注册到 ServiceLocator
- RAG 功能已启用（从配置获取）
- 两个条件同时满足时才执行检索

检索集合：
- code 集合：工作区代码文件的向量索引
- papers 集合：论文知识库的向量索引

被调用方：context_retriever.py
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class VectorMatch:
    """向量检索结果"""
    path: str
    content: str
    relevance: float
    source: str = "vector"
    token_count: int = 0
    collection: str = ""  # "code" | "papers"
    
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
    向量语义检索器
    
    使用向量语义在知识库中检索相关内容。
    阶段三返回空结果，阶段四启用后使用 vector_store。
    """

    def __init__(self):
        self._vector_store = None
        self._session_state = None
        self._logger = None

    # ============================================================
    # 服务获取
    # ============================================================

    @property
    def vector_store(self):
        """延迟获取向量存储"""
        if self._vector_store is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_VECTOR_STORE
                self._vector_store = ServiceLocator.get_optional(SVC_VECTOR_STORE)
            except Exception:
                pass
        return self._vector_store

    @property
    def session_state(self):
        """延迟获取会话状态（只读）"""
        if self._session_state is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE
                self._session_state = ServiceLocator.get_optional(SVC_SESSION_STATE)
            except Exception:
                pass
        return self._session_state

    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("vector_retriever")
            except Exception:
                pass
        return self._logger

    # ============================================================
    # 启用检查
    # ============================================================

    def is_enabled(self) -> bool:
        """
        检查向量检索是否启用
        
        启用条件：
        1. vector_store 服务已注册
        2. RAG 功能已启用（从配置获取）
        
        Returns:
            bool: 是否启用
        """
        # 检查 vector_store 是否可用
        if self.vector_store is None:
            return False
        
        # TODO: 检查 RAG 开关（从配置或 SessionState 获取）
        # 目前默认返回 False，待 RAG 功能完善后启用
        return False


    # ============================================================
    # 主入口
    # ============================================================

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[VectorMatch]:
        """
        执行向量检索
        
        Args:
            query: 语义查询
            top_k: 返回数量
            
        Returns:
            List[VectorMatch]: 检索结果列表
        """
        if not self.is_enabled():
            if self.logger:
                self.logger.debug(
                    "Vector retrieval disabled: vector_store not available "
                    "or rag_enabled is False"
                )
            return []
        
        results = []
        
        # 在代码集合中检索
        code_results = self.search_code_collection(query, top_k)
        results.extend(code_results)
        
        # 在论文集合中检索
        papers_results = self.search_papers_collection(query, top_k)
        results.extend(papers_results)
        
        # 按相关度排序
        results.sort(key=lambda x: x.relevance, reverse=True)
        
        # 截取 top_k
        results = results[:top_k]
        
        if self.logger:
            self.logger.debug(f"Vector retrieval returned {len(results)} results")
        
        return results

    # ============================================================
    # 集合检索
    # ============================================================

    def search_code_collection(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[VectorMatch]:
        """
        在代码集合中检索
        
        Args:
            query: 语义查询
            top_k: 返回数量
            
        Returns:
            List[VectorMatch]: 检索结果列表
        """
        if self.vector_store is None:
            return []
        
        try:
            # 调用 vector_store 检索
            results = self.vector_store.search(
                query=query,
                collection="code",
                top_k=top_k,
            )
            
            return self._convert_results(results, collection="code")
            
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Code collection search failed: {e}")
            return []

    def search_papers_collection(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[VectorMatch]:
        """
        在论文集合中检索
        
        Args:
            query: 语义查询
            top_k: 返回数量
            
        Returns:
            List[VectorMatch]: 检索结果列表
        """
        if self.vector_store is None:
            return []
        
        try:
            # 调用 vector_store 检索
            results = self.vector_store.search(
                query=query,
                collection="papers",
                top_k=top_k,
            )
            
            return self._convert_results(results, collection="papers")
            
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Papers collection search failed: {e}")
            return []


    # ============================================================
    # 结果转换
    # ============================================================

    def _convert_results(
        self,
        results: List[Dict[str, Any]],
        collection: str,
    ) -> List[VectorMatch]:
        """
        转换 vector_store 返回的结果为统一格式
        
        Args:
            results: vector_store 返回的原始结果
            collection: 集合名称
            
        Returns:
            List[VectorMatch]: 转换后的结果列表
        """
        matches = []
        
        for r in results:
            content = r.get("content", "")
            
            match = VectorMatch(
                path=r.get("path", r.get("id", "")),
                content=content,
                relevance=r.get("score", r.get("similarity", 0.0)),
                source="vector",
                token_count=self._estimate_tokens(content),
                collection=collection,
            )
            matches.append(match)
        
        return matches

    # ============================================================
    # 辅助方法
    # ============================================================

    def _estimate_tokens(self, text: str) -> int:
        """
        估算文本的 Token 数
        
        优先使用 token_counter 模块的精确计算，
        若不可用则回退到简单估算。
        """
        if not text:
            return 0
        
        try:
            from domain.llm.token_counter import count_tokens
            return count_tokens(text)
        except ImportError:
            # 回退到简单估算
            return len(text) // 4

    def get_status(self) -> Dict[str, Any]:
        """
        获取向量检索器状态
        
        Returns:
            Dict: 状态信息
        """
        return {
            "enabled": self.is_enabled(),
            "vector_store_available": self.vector_store is not None,
            "rag_enabled": False,  # TODO: 从配置获取
        }


__all__ = [
    "VectorRetriever",
    "VectorMatch",
]
