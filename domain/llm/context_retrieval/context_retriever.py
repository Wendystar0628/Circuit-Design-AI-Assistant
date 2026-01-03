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
1. 调用 ImplicitContextCollector.collect_async() 收集隐式上下文
2. 调用 DiagnosticsCollector.collect_async() 收集诊断信息
3. 调用 KeywordExtractor.extract() 提取关键词（纯计算，无 I/O）
4. 通过 UnifiedSearchService.search_async() 执行统一搜索
5. 通过 DependencyAnalyzer.get_dependency_content_async() 获取依赖文件
6. 调用 RetrievalMerger.merge() 融合所有结果并截断到 Token 预算

依赖的服务和子模块：
- AsyncFileOps（阶段二 2.1.4）- 异步文件操作
- UnifiedSearchService（阶段五 5.0.4）- 统一搜索门面
- ImplicitContextCollector - 隐式上下文收集
- DiagnosticsCollector - 诊断信息收集
- KeywordExtractor - 关键词提取
- DependencyAnalyzer - 依赖图分析
- RetrievalMerger - 多路检索结果融合

被调用方：prompt_builder.py
"""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from domain.llm.context_retrieval.implicit_context_collector import (
    ImplicitContextCollector, ImplicitContext
)
from domain.llm.context_retrieval.diagnostics_collector import (
    DiagnosticsCollector, Diagnostics
)
from domain.llm.context_retrieval.keyword_extractor import (
    KeywordExtractor, ExtractedKeywords
)
from domain.llm.context_retrieval.dependency_analyzer import (
    DependencyAnalyzer
)
from domain.llm.context_retrieval.retrieval_merger import (
    RetrievalMerger, RetrievalItem
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

# 默认 Token 预算
DEFAULT_TOKEN_BUDGET = 2000


@dataclass
class RetrievalResult:
    """检索结果"""
    path: str
    content: str
    relevance: float
    source: str  # "keyword" | "vector" | "dependency" | "implicit" | "exact" | "semantic"
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
    implicit_context: Optional[ImplicitContext] = None
    diagnostics: Optional[Diagnostics] = None
    retrieval_results: List[RetrievalResult] = field(default_factory=list)
    keywords: Optional[ExtractedKeywords] = None
    total_tokens: int = 0
    
    @property
    def items(self) -> List[RetrievalResult]:
        """兼容旧接口的别名"""
        return self.retrieval_results


class ContextRetriever:
    """
    上下文检索门面类
    
    协调各子模块，提供统一的上下文检索入口。
    所有公开方法均为 async def，确保不阻塞事件循环。
    """

    def __init__(self):
        # 子模块实例
        self._implicit_collector = ImplicitContextCollector()
        self._diagnostics_collector = DiagnosticsCollector()
        self._keyword_extractor = KeywordExtractor()
        self._dependency_analyzer = DependencyAnalyzer()
        self._retrieval_merger = RetrievalMerger()
        
        # 延迟获取的服务
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
                # 回退：创建新实例
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
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        main_file: Optional[str] = None,
    ) -> RetrievalContext:
        """
        综合检索相关上下文（异步主入口）
        
        协调流程：
        1. 收集隐式上下文
        2. 收集诊断信息
        3. 提取关键词
        4. 通过 UnifiedSearchService 执行统一搜索
        5. 获取依赖文件内容
        6. 融合所有结果并截断到 Token 预算
        
        Args:
            message: 用户消息
            project_path: 项目路径
            token_budget: Token 预算
            main_file: 当前主文件路径（用于依赖分析）
            
        Returns:
            RetrievalContext: 完整的检索上下文
        """
        if self.logger:
            self.logger.debug(f"Retrieving context for: {message[:50]}...")
        
        context = RetrievalContext()
        
        # Step 1: 收集隐式上下文
        context.implicit_context = await self._collect_implicit_context_async(
            project_path
        )
        
        # 确定当前电路文件
        circuit_file = main_file
        if not circuit_file and context.implicit_context:
            if context.implicit_context.current_circuit:
                circuit_file = str(
                    Path(project_path) / context.implicit_context.current_circuit["path"]
                )
        
        # Step 2: 收集诊断信息
        context.diagnostics = await self._collect_diagnostics_async(
            project_path, circuit_file
        )
        
        # Step 3: 提取关键词（纯计算，无 I/O）
        context.keywords = self._keyword_extractor.extract(message)
        
        # Step 4-6: 并发执行搜索和依赖分析
        all_results = await self._collect_all_context_async(
            message=message,
            keywords=context.keywords,
            project_path=project_path,
            circuit_file=circuit_file,
            token_budget=token_budget,
        )
        
        # 融合并截断结果
        context.retrieval_results = self._merge_and_truncate(
            all_results, token_budget
        )
        
        # 计算总 Token 数
        context.total_tokens = sum(r.token_count for r in context.retrieval_results)
        
        if self.logger:
            self.logger.info(
                f"Retrieved {len(context.retrieval_results)} results "
                f"(tokens: {context.total_tokens}/{token_budget})"
            )
        
        return context

    # ============================================================
    # 内部协调方法（异步）
    # ============================================================

    async def _collect_implicit_context_async(
        self,
        project_path: str,
    ) -> ImplicitContext:
        """异步收集隐式上下文"""
        # ImplicitContextCollector.collect() 目前是同步的
        # 使用 to_thread 包装以避免阻塞
        return await asyncio.to_thread(
            self._implicit_collector.collect,
            project_path
        )

    async def _collect_diagnostics_async(
        self,
        project_path: str,
        circuit_file: Optional[str],
    ) -> Diagnostics:
        """异步收集诊断信息"""
        return await asyncio.to_thread(
            self._diagnostics_collector.collect,
            project_path,
            circuit_file
        )

    async def _collect_all_context_async(
        self,
        message: str,
        keywords: ExtractedKeywords,
        project_path: str,
        circuit_file: Optional[str],
        token_budget: int,
    ) -> List[RetrievalResult]:
        """
        协调各收集器获取上下文（并发执行）
        
        并发执行：
        - 关键词搜索（通过 UnifiedSearchService）
        - 依赖文件加载
        """
        all_results: List[RetrievalResult] = []
        
        # 创建并发任务
        tasks = []
        
        # Task 1: 通过 UnifiedSearchService 执行关键词搜索
        search_terms = self._keyword_extractor.get_search_terms(keywords)
        if search_terms:
            query = " ".join(search_terms[:10])  # 限制搜索词数量
            tasks.append(self._search_by_keywords_async(query, token_budget // 2))
        
        # Task 2: 获取依赖文件内容
        if circuit_file:
            tasks.append(self._get_dependency_content_async(
                circuit_file, project_path, token_budget // 2
            ))
        
        # 并发执行所有任务
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, Exception):
                    if self.logger:
                        self.logger.warning(f"Context collection task failed: {result}")
                elif isinstance(result, list):
                    all_results.extend(result)
        
        return all_results

    async def _search_by_keywords_async(
        self,
        query: str,
        token_budget: int,
    ) -> List[RetrievalResult]:
        """
        通过 UnifiedSearchService 执行关键词搜索
        
        Args:
            query: 搜索查询
            token_budget: Token 预算
            
        Returns:
            List[RetrievalResult]: 搜索结果
        """
        results: List[RetrievalResult] = []
        
        if not self.unified_search_service:
            if self.logger:
                self.logger.debug("UnifiedSearchService not available")
            return results
        
        try:
            # 调用统一搜索服务
            # UnifiedSearchService.search() 目前是同步的，使用 to_thread 包装
            search_result = await asyncio.to_thread(
                self.unified_search_service.search,
                query,
                token_budget=token_budget,
            )
            
            # 转换精确匹配结果
            for match in search_result.exact_matches:
                results.append(RetrievalResult(
                    path=match.file_path,
                    content=match.line_content or "",
                    relevance=match.score,
                    source="exact",
                    token_count=self._estimate_tokens(match.line_content or ""),
                ))
            
            # 转换语义匹配结果
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
                self.logger.warning(f"Unified search failed: {e}")
        
        return results

    async def _get_dependency_content_async(
        self,
        circuit_file: str,
        project_path: str,
        token_budget: int,
    ) -> List[RetrievalResult]:
        """
        获取依赖文件内容（异步）
        
        使用 AsyncFileOps.read_multiple_files_async() 并发读取依赖文件。
        
        Args:
            circuit_file: 主电路文件路径
            project_path: 项目路径
            token_budget: Token 预算
            
        Returns:
            List[RetrievalResult]: 依赖文件内容
        """
        results: List[RetrievalResult] = []
        
        # 获取依赖文件列表
        dependencies = await asyncio.to_thread(
            self._dependency_analyzer.get_dependency_content,
            circuit_file,
            max_depth=3,
            project_path=project_path,
        )
        
        if not dependencies:
            return results
        
        # 转换为 RetrievalResult
        total_tokens = 0
        for dep in dependencies:
            content = dep.get("content", "")
            token_count = self._estimate_tokens(content)
            
            # 检查 Token 预算
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
        """
        按优先级融合并截断结果
        
        使用 RetrievalMerger 执行 RRF 算法融合多路结果。
        
        Args:
            results: 所有检索结果
            token_budget: Token 预算
            
        Returns:
            List[RetrievalResult]: 融合后的结果
        """
        if not results:
            return []
        
        # 按来源分组
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
        
        # 使用 RetrievalMerger 融合
        merged_items = self._retrieval_merger.merge(
            results_dict, token_budget
        )
        
        # 转换回 RetrievalResult
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
        """
        估算文本的 Token 数
        
        委托给 token_counter 模块，若不可用则回退到简单估算。
        """
        if not text:
            return 0
        
        try:
            from domain.llm.token_counter import count_tokens
            return count_tokens(text)
        except ImportError:
            # 回退到简单估算（4 字符 ≈ 1 token）
            return len(text) // 4

    # ============================================================
    # 同步包装方法（向后兼容）
    # ============================================================

    def retrieve(
        self,
        message: str,
        project_path: str,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        main_file: Optional[str] = None,
    ) -> RetrievalContext:
        """
        综合检索相关上下文（同步包装方法）
        
        这是 retrieve_async() 的同步包装，用于向后兼容。
        在异步上下文中，请优先使用 retrieve_async()。
        
        Args:
            message: 用户消息
            project_path: 项目路径
            token_budget: Token 预算
            main_file: 当前主文件路径
            
        Returns:
            RetrievalContext: 完整的检索上下文
        """
        try:
            # 尝试获取当前事件循环
            loop = asyncio.get_running_loop()
            # 如果在事件循环中，使用 run_coroutine_threadsafe
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                self.retrieve_async(message, project_path, token_budget, main_file),
                loop
            )
            return future.result(timeout=30)
        except RuntimeError:
            # 没有运行中的事件循环，创建新的
            return asyncio.run(
                self.retrieve_async(message, project_path, token_budget, main_file)
            )

    # ============================================================
    # 错误历史管理（委托给 DiagnosticsCollector）
    # ============================================================

    def record_error(self, circuit_file: str, error: str):
        """记录错误到历史"""
        self._diagnostics_collector.record_error(circuit_file, error)

    def clear_error_history(self, circuit_file: str):
        """清除错误历史"""
        self._diagnostics_collector.clear_error_history(circuit_file)


__all__ = [
    "ContextRetriever",
    "RetrievalResult",
    "RetrievalContext",
    "SPICE_EXTENSIONS",
    "SPICE_METRICS",
]
