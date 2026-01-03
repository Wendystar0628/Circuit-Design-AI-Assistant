# Context Retriever - Facade for Context Retrieval
"""
上下文检索门面类 - 协调各子模块，提供统一的上下文检索入口

职责：
- 作为门面类协调各子模块
- 提供统一的上下文检索入口
- 综合检索相关上下文

异步设计原则：
- 所有公开方法均为 async def，确保不阻塞事件循环
- 文件读取通过 AsyncFileOps.read_multiple_files_async() 并发执行
- 禁止在本模块中使用同步文件 I/O

协调流程：
1. 从 state_context 构建 CollectionContext 对象
2. 调用 ImplicitContextAggregator.collect_async() 收集隐式上下文
3. 调用 DiagnosticsCollector.collect_async() 收集诊断信息
4. 调用 KeywordExtractor.extract() 提取关键词（纯计算，无 I/O）
5. 通过 UnifiedSearchService.search() 执行统一搜索
6. 通过 DependencyAnalyzer.get_dependency_content_async() 获取依赖文件
7. 调用 RetrievalMerger.merge() 融合所有结果并截断到 Token 预算

依赖的服务和子模块：
- AsyncFileOps（阶段二 2.1.4）- 异步文件操作
- UnifiedSearchService（阶段五 5.0.4）- 统一搜索门面
- ImplicitContextAggregator - 隐式上下文聚合器
- DiagnosticsCollector - 诊断信息收集
- KeywordExtractor - 关键词提取
- DependencyAnalyzer - 依赖图分析
- RetrievalMerger - 多路检索结果融合

被调用方：prompt_builder.py
"""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.llm.context_retrieval.context_source_protocol import (
    CollectionContext,
    ContextResult,
    build_collection_context,
)
from domain.llm.context_retrieval.implicit_context_aggregator import (
    ImplicitContextAggregator,
)
from domain.llm.context_retrieval.diagnostics_collector import (
    DiagnosticsCollector,
)
from domain.llm.context_retrieval.keyword_extractor import (
    KeywordExtractor,
    ExtractedKeywords,
)
from domain.llm.context_retrieval.dependency_analyzer import DependencyAnalyzer
from domain.llm.context_retrieval.retrieval_merger import (
    RetrievalMerger,
    RetrievalItem,
)


# ============================================================
# 常量定义
# ============================================================

SPICE_EXTENSIONS = {".cir", ".sp", ".spice", ".lib", ".inc"}
SPICE_METRICS = {
    "gain", "bandwidth", "phase", "margin", "impedance", "resistance",
    "capacitance", "inductance", "frequency", "voltage", "current",
    "power", "noise", "distortion", "slew", "offset", "cmrr", "psrr",
}

DEFAULT_TOKEN_BUDGET = 2000


# ============================================================
# 数据类定义
# ============================================================

@dataclass
class RetrievalResult:
    """检索结果"""
    path: str
    content: str
    relevance: float
    source: str
    token_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "content": self.content,
            "relevance": self.relevance,
            "source": self.source,
            "token_count": self.token_count,
        }


@dataclass
class RetrievalContext:
    """完整的检索上下文"""
    implicit_results: List[ContextResult] = field(default_factory=list)
    retrieval_results: List[RetrievalResult] = field(default_factory=list)
    keywords: Optional[ExtractedKeywords] = None
    total_tokens: int = 0

    @property
    def items(self) -> List[RetrievalResult]:
        """获取所有检索结果"""
        return self.retrieval_results
    
    @property
    def has_diagnostics(self) -> bool:
        """检查是否包含诊断信息"""
        return any(r.source == "diagnostics" for r in self.retrieval_results)


# ============================================================
# 门面类
# ============================================================

class ContextRetriever:
    """
    上下文检索门面类

    协调各子模块，提供统一的上下文检索入口。
    """

    def __init__(self):
        self._implicit_aggregator = ImplicitContextAggregator()
        self._keyword_extractor = KeywordExtractor()
        self._dependency_analyzer = DependencyAnalyzer()
        self._retrieval_merger = RetrievalMerger()
        
        # 保留对 DiagnosticsCollector 的引用，用于 record_error/clear_error_history
        self._diagnostics_collector: Optional[DiagnosticsCollector] = None

        self._unified_search_service = None
        self._async_file_ops = None
        self._logger = None

    # ============================================================
    # 服务获取（延迟加载）
    # ============================================================

    @property
    def unified_search_service(self):
        """延迟获取统一搜索服务"""
        if self._unified_search_service is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_UNIFIED_SEARCH_SERVICE
                self._unified_search_service = ServiceLocator.get_optional(
                    SVC_UNIFIED_SEARCH_SERVICE
                )
            except Exception:
                pass
        return self._unified_search_service

    @property
    def async_file_ops(self):
        """延迟获取异步文件操作服务"""
        if self._async_file_ops is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_ASYNC_FILE_OPS
                self._async_file_ops = ServiceLocator.get_optional(SVC_ASYNC_FILE_OPS)
            except Exception:
                try:
                    from infrastructure.persistence.async_file_ops import AsyncFileOps
                    self._async_file_ops = AsyncFileOps()
                except Exception:
                    pass
        return self._async_file_ops

    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("context_retriever")
            except Exception:
                pass
        return self._logger

    # ============================================================
    # 主入口（异步）
    # ============================================================

    async def retrieve_async(
        self,
        message: str,
        project_path: str,
        state_context: Optional[Dict[str, Any]] = None,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
    ) -> RetrievalContext:
        """
        综合检索相关上下文（异步主入口）

        Args:
            message: 用户消息
            project_path: 项目路径
            state_context: 状态上下文字典（从 GraphState 提取的路径信息）
            token_budget: Token 预算

        Returns:
            RetrievalContext: 完整的检索上下文
        """
        if self.logger:
            self.logger.debug(f"Retrieving context for: {message[:50]}...")

        context = RetrievalContext()

        # Step 1: 构建 CollectionContext
        collection_context = self._build_collection_context(
            project_path, state_context or {}
        )

        # Step 2: 收集隐式上下文（包含诊断信息）
        context.implicit_results = await self._implicit_aggregator.collect_async(
            collection_context
        )

        # Step 3: 提取关键词
        context.keywords = self._keyword_extractor.extract(message)

        # Step 4: 并发执行搜索和依赖分析
        search_results = await self._collect_search_results_async(
            message=message,
            keywords=context.keywords,
            collection_context=collection_context,
            token_budget=token_budget,
        )

        # Step 5: 融合所有结果
        all_results = self._convert_implicit_to_retrieval(context.implicit_results)
        all_results.extend(search_results)

        context.retrieval_results = self._merge_and_truncate(
            all_results, token_budget
        )

        context.total_tokens = sum(r.token_count for r in context.retrieval_results)

        if self.logger:
            self.logger.info(
                f"Retrieved {len(context.retrieval_results)} results "
                f"(tokens: {context.total_tokens}/{token_budget})"
            )

        return context

    def _build_collection_context(
        self,
        project_path: str,
        state_context: Dict[str, Any],
    ) -> CollectionContext:
        """从状态上下文构建 CollectionContext"""
        return build_collection_context(project_path, state_context)

    def _convert_implicit_to_retrieval(
        self,
        implicit_results: List[ContextResult],
    ) -> List[RetrievalResult]:
        """将隐式上下文结果转换为检索结果"""
        results = []
        for r in implicit_results:
            if not r.is_empty:
                results.append(RetrievalResult(
                    path=r.metadata.get("file_path", r.source_name),
                    content=r.content,
                    relevance=1.0 - (r.priority.value / 100),
                    source=r.source_name,
                    token_count=r.token_count,
                ))
        return results

    # ============================================================
    # 内部协调方法（异步）
    # ============================================================

    def _get_diagnostics_collector(self) -> Optional[DiagnosticsCollector]:
        """获取 DiagnosticsCollector 实例（从聚合器中查找）"""
        if self._diagnostics_collector is None:
            for collector in self._implicit_aggregator._collectors:
                if isinstance(collector, DiagnosticsCollector):
                    self._diagnostics_collector = collector
                    break
        return self._diagnostics_collector

    async def _collect_search_results_async(
        self,
        message: str,
        keywords: ExtractedKeywords,
        collection_context: CollectionContext,
        token_budget: int,
    ) -> List[RetrievalResult]:
        """并发执行搜索和依赖分析"""
        all_results: List[RetrievalResult] = []
        tasks = []

        # Task 1: 关键词搜索
        search_terms = self._keyword_extractor.get_search_terms(keywords)
        if search_terms:
            query = " ".join(search_terms[:10])
            tasks.append(self._search_by_keywords_async(query, token_budget // 2))

        # Task 2: 依赖文件
        if collection_context.circuit_file_path:
            circuit_file = collection_context.get_absolute_path(
                collection_context.circuit_file_path
            )
            tasks.append(self._get_dependency_content_async(
                circuit_file,
                collection_context.project_path,
                token_budget // 2,
            ))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    if self.logger:
                        self.logger.warning(f"Task failed: {result}")
                elif isinstance(result, list):
                    all_results.extend(result)

        return all_results

    async def _search_by_keywords_async(
        self,
        query: str,
        token_budget: int,
    ) -> List[RetrievalResult]:
        """通过 UnifiedSearchService 执行关键词搜索"""
        results: List[RetrievalResult] = []

        if not self.unified_search_service:
            return results

        try:
            search_result = await asyncio.to_thread(
                self.unified_search_service.search,
                query,
                token_budget=token_budget,
            )

            for match in search_result.exact_matches:
                results.append(RetrievalResult(
                    path=match.file_path,
                    content=match.line_content or "",
                    relevance=match.score,
                    source="exact",
                    token_count=self._estimate_tokens(match.line_content or ""),
                ))

            for match in search_result.semantic_matches:
                results.append(RetrievalResult(
                    path=match.source,
                    content=match.content,
                    relevance=match.score,
                    source="semantic",
                    token_count=self._estimate_tokens(match.content),
                ))

        except Exception as e:
            if self.logger:
                self.logger.warning(f"Search failed: {e}")

        return results

    async def _get_dependency_content_async(
        self,
        circuit_file: str,
        project_path: str,
        token_budget: int,
    ) -> List[RetrievalResult]:
        """获取依赖文件内容"""
        results: List[RetrievalResult] = []

        dependencies = await asyncio.to_thread(
            self._dependency_analyzer.get_dependency_content,
            circuit_file,
            max_depth=3,
            project_path=project_path,
        )

        if not dependencies:
            return results

        total_tokens = 0
        for dep in dependencies:
            content = dep.get("content", "")
            token_count = self._estimate_tokens(content)

            if total_tokens + token_count > token_budget:
                break

            results.append(RetrievalResult(
                path=dep.get("path", ""),
                content=content,
                relevance=0.9 if dep.get("depth", 0) <= 1 else 0.7,
                source="dependency",
                token_count=token_count,
            ))
            total_tokens += token_count

        return results

    # ============================================================
    # 结果融合
    # ============================================================

    def _merge_and_truncate(
        self,
        results: List[RetrievalResult],
        token_budget: int,
    ) -> List[RetrievalResult]:
        """按优先级融合并截断结果"""
        if not results:
            return []

        results_dict: Dict[str, List[RetrievalItem]] = {}
        for r in results:
            source = r.source
            if source not in results_dict:
                results_dict[source] = []
            results_dict[source].append(RetrievalItem(
                path=r.path,
                content=r.content,
                relevance=r.relevance,
                source=r.source,
                token_count=r.token_count,
            ))

        merged_items = self._retrieval_merger.merge(results_dict, token_budget)

        return [
            RetrievalResult(
                path=item.path,
                content=item.content,
                relevance=item.relevance,
                source=item.source,
                token_count=item.token_count,
            )
            for item in merged_items
        ]

    # ============================================================
    # 辅助方法
    # ============================================================

    def _estimate_tokens(self, text: str) -> int:
        """估算 Token 数"""
        if not text:
            return 0
        try:
            from domain.llm.token_counter import count_tokens
            return count_tokens(text)
        except ImportError:
            return len(text) // 4

    # ============================================================
    # 同步包装方法
    # ============================================================

    def retrieve(
        self,
        message: str,
        project_path: str,
        state_context: Optional[Dict[str, Any]] = None,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
    ) -> RetrievalContext:
        """同步包装方法"""
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                self.retrieve_async(message, project_path, state_context, token_budget),
                loop,
            )
            return future.result(timeout=30)
        except RuntimeError:
            return asyncio.run(
                self.retrieve_async(message, project_path, state_context, token_budget)
            )

    # ============================================================
    # 错误历史管理
    # ============================================================

    def record_error(
        self,
        circuit_file: str,
        error: str,
        error_type: str = "simulation",
        command: Optional[str] = None,
    ) -> None:
        """
        记录错误到历史
        
        Args:
            circuit_file: 电路文件路径
            error: 错误消息
            error_type: 错误类型（默认 "simulation"）
            command: 失败的仿真命令（可选）
        """
        collector = self._get_diagnostics_collector()
        if collector:
            collector.record_error(circuit_file, error_type, error, command)

    def clear_error_history(self, circuit_file: str) -> None:
        """
        清除错误历史
        
        Args:
            circuit_file: 电路文件路径
        """
        collector = self._get_diagnostics_collector()
        if collector:
            collector.clear_error_history(circuit_file)


__all__ = [
    "ContextRetriever",
    "RetrievalResult",
    "RetrievalContext",
    "SPICE_EXTENSIONS",
    "SPICE_METRICS",
]
