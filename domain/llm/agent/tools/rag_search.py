# RAG Search Tool - Agent RAG 检索工具
"""
Agent RAG 检索工具

职责：
- 在项目向量知识库中搜索与查询相关的文档片段
- 仅在 RAGManager 可用时注册到 ToolRegistry

架构位置：
- 被 ToolRegistry 注册
- 依赖 RAGManager（向量相似度检索）
- 通过 ServiceLocator 延迟获取 RAGManager
"""

import asyncio
from typing import Any, Dict, List, Optional

from domain.llm.agent.types import BaseTool, ToolContext, ToolResult


class RAGSearchTool(BaseTool):
    """
    RAG 知识库检索工具

    供 Agent 主动调用，从项目向量库中检索与查询相关的文档片段。
    """

    @property
    def name(self) -> str:
        return "rag_search"

    @property
    def label(self) -> str:
        return "RAG Search"

    @property
    def description(self) -> str:
        return (
            "Search the project knowledge base for document chunks related to a query. "
            "Uses local embedding-based vector retrieval (ChromaDB + sentence-transformers). "
            "Returns relevant text from indexed project files including circuit files, "
            "code, documentation, and PDFs."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Search query text. Can be a question, keyword, "
                        "or description of what you're looking for."
                    ),
                },
            },
            "required": ["query"],
        }

    @property
    def prompt_snippet(self) -> Optional[str]:
        return "Search the project knowledge base for document chunks using vector similarity"

    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        return [
            "Use rag_search to find information about circuit components, "
            "parameters, standards, or design patterns in the project.",
            "rag_search is most effective for domain-specific queries about "
            "the project's circuit designs and documentation.",
        ]

    async def execute(
        self,
        tool_call_id: str,
        params: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """
        执行 RAG 检索

        Args:
            tool_call_id: 工具调用 ID
            params: {"query": str, "mode": str (optional)}
            context: 工具执行上下文

        Returns:
            ToolResult: 格式化的检索结果
        """
        query = params.get("query", "")

        if not query.strip():
            return ToolResult(
                content="Error: query parameter is required and cannot be empty.",
                is_error=True,
            )

        # 获取 RAGManager
        rag_manager = self._get_rag_manager()
        if not rag_manager or not rag_manager.is_available:
            return ToolResult(
                content="RAG service is not available. Please open a project first.",
                is_error=True,
            )

        try:
            result = await rag_manager.query_async(query)

            if result.is_empty:
                return ToolResult(
                    content=f"No results found for query: \"{query}\"",
                    details={"query": query, "results_count": 0},
                )

            formatted = result.format_as_context(max_tokens=3000)
            content = f"Found {result.chunks_count} document chunks.\n\n{formatted}"

            return ToolResult(
                content=content,
                details={
                    "query": query,
                    "chunks_count": result.chunks_count,
                },
            )

        except Exception as e:
            return ToolResult(
                content=f"RAG search failed: {e}",
                is_error=True,
            )

    @staticmethod
    def _get_rag_manager():
        """延迟获取 RAGManager"""
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_RAG_MANAGER

            return ServiceLocator.get_optional(SVC_RAG_MANAGER)
        except Exception:
            return None


# ============================================================
# 模块导出
# ============================================================

__all__ = ["RAGSearchTool"]
