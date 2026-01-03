# Context Retrieval Module
"""
智能上下文检索模块组

职责：
- 自动收集工作区中的隐式上下文信息
- 收集电路文件的诊断信息
- 多路检索相关代码（关键词匹配、向量语义、依赖分析）
- 融合排序并控制 Token 预算

模块结构：
- context_retriever.py          - 门面类，协调各子模块（异步接口）
- implicit_context_collector.py - 隐式上下文收集
- diagnostics_collector.py      - 诊断信息收集
- keyword_extractor.py          - 关键词提取
- keyword_retriever.py          - 精确匹配检索（独立使用）
- vector_retriever.py           - 向量语义检索（阶段四启用）
- dependency_analyzer.py        - 电路依赖图分析
- retrieval_merger.py           - 多路检索结果融合

与其他模块的职责划分：
- 阶段二 FileSearchService：基础设施层的精确文件搜索引擎
- 阶段三 context_retrieval/：专注于 LLM 对话场景的上下文收集和组装
- 阶段五 UnifiedSearchService：统一搜索门面，融合精确搜索和语义搜索结果

调用关系：
- context_retriever.py 通过 UnifiedSearchService 执行统一搜索
- 所有搜索操作通过 UnifiedSearchService 进行，确保精确搜索和语义搜索的统一融合

阶段依赖说明：
- 向量检索功能依赖阶段四的 vector_store
- 阶段三实现时，向量检索路径返回空结果
- 仅启用隐式上下文收集、关键词匹配和依赖分析
- 阶段四完成后，通过配置开关启用完整的混合检索能力
"""

from domain.llm.context_retrieval.context_retriever import (
    ContextRetriever,
    RetrievalResult,
    RetrievalContext,
    SPICE_EXTENSIONS,
    SPICE_METRICS,
)
from domain.llm.context_retrieval.implicit_context_collector import (
    ImplicitContextCollector,
    ImplicitContext,
)
from domain.llm.context_retrieval.diagnostics_collector import (
    DiagnosticsCollector,
    Diagnostics,
    DiagnosticItem,
)
from domain.llm.context_retrieval.keyword_extractor import (
    KeywordExtractor,
    ExtractedKeywords,
)
from domain.llm.context_retrieval.retrieval_merger import (
    RetrievalMerger,
    RetrievalItem,
)
from domain.llm.context_retrieval.dependency_analyzer import (
    DependencyAnalyzer,
    DependencyGraph,
    DependencyNode,
)
from domain.llm.context_retrieval.keyword_retriever import (
    KeywordRetriever,
    KeywordMatch,
)
from domain.llm.context_retrieval.vector_retriever import (
    VectorRetriever,
    VectorMatch,
)


__all__ = [
    # 门面类（主入口）
    "ContextRetriever",
    "RetrievalResult",
    "RetrievalContext",
    # 隐式上下文收集
    "ImplicitContextCollector",
    "ImplicitContext",
    # 诊断信息收集
    "DiagnosticsCollector",
    "Diagnostics",
    "DiagnosticItem",
    # 关键词提取
    "KeywordExtractor",
    "ExtractedKeywords",
    # 关键词检索（独立使用）
    "KeywordRetriever",
    "KeywordMatch",
    # 向量检索（阶段四启用）
    "VectorRetriever",
    "VectorMatch",
    # 结果融合
    "RetrievalMerger",
    "RetrievalItem",
    # 依赖分析
    "DependencyAnalyzer",
    "DependencyGraph",
    "DependencyNode",
    # 常量
    "SPICE_EXTENSIONS",
    "SPICE_METRICS",
]
