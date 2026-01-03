# Context Retrieval Module
"""
智能上下文检索模块组

职责：
- 自动收集工作区中的隐式上下文信息
- 收集电路文件的诊断信息
- 多路检索相关代码（关键词匹配、向量语义、依赖分析）
- 融合排序并控制 Token 预算

模块结构：
- context_retriever.py              - 门面类，协调各子模块（异步接口）
- context_source_protocol.py        - 上下文源协议定义
- implicit_context_aggregator.py    - 隐式上下文聚合器
- circuit_file_collector.py         - 电路文件收集器
- simulation_context_collector.py   - 仿真上下文收集器
- design_goals_collector.py         - 设计目标收集器
- diagnostics_collector.py          - 诊断信息收集
- keyword_extractor.py              - 关键词提取
- dependency_analyzer.py            - 电路依赖图分析
- retrieval_merger.py               - 多路检索结果融合

调用关系：
- context_retriever.py 通过 ImplicitContextAggregator 收集隐式上下文
- context_retriever.py 通过 UnifiedSearchService 执行统一搜索
"""

from domain.llm.context_retrieval.context_retriever import (
    ContextRetriever,
    RetrievalResult,
    RetrievalContext,
    SPICE_EXTENSIONS,
    SPICE_METRICS,
)

# 上下文源协议
from domain.llm.context_retrieval.context_source_protocol import (
    ContextSource,
    ContextPriority,
    CollectionContext,
    ContextResult,
    build_collection_context,
)

# 隐式上下文聚合器
from domain.llm.context_retrieval.implicit_context_aggregator import (
    ImplicitContextAggregator,
)

# 专职收集器
from domain.llm.context_retrieval.circuit_file_collector import (
    CircuitFileCollector,
)
from domain.llm.context_retrieval.simulation_context_collector import (
    SimulationContextCollector,
)
from domain.llm.context_retrieval.design_goals_collector import (
    DesignGoalsCollector,
)

# 诊断信息收集
from domain.llm.context_retrieval.diagnostics_collector import (
    DiagnosticsCollector,
    Diagnostics,
    DiagnosticItem,
)

# 关键词提取
from domain.llm.context_retrieval.keyword_extractor import (
    KeywordExtractor,
    ExtractedKeywords,
)

# 结果融合
from domain.llm.context_retrieval.retrieval_merger import (
    RetrievalMerger,
    RetrievalItem,
)

# 依赖分析
from domain.llm.context_retrieval.dependency_analyzer import (
    DependencyAnalyzer,
    DependencyGraph,
    DependencyNode,
)

# 关键词检索
from domain.llm.context_retrieval.keyword_retriever import (
    KeywordRetriever,
    KeywordMatch,
)

# 向量检索（阶段四启用）
from domain.llm.context_retrieval.vector_retriever import (
    VectorRetriever,
    VectorMatch,
)


__all__ = [
    # 门面类（主入口）
    "ContextRetriever",
    "RetrievalResult",
    "RetrievalContext",
    # 上下文源协议
    "ContextSource",
    "ContextPriority",
    "CollectionContext",
    "ContextResult",
    "build_collection_context",
    # 隐式上下文聚合器
    "ImplicitContextAggregator",
    # 专职收集器
    "CircuitFileCollector",
    "SimulationContextCollector",
    "DesignGoalsCollector",
    # 诊断信息收集
    "DiagnosticsCollector",
    "Diagnostics",
    "DiagnosticItem",
    # 关键词提取
    "KeywordExtractor",
    "ExtractedKeywords",
    # 关键词检索
    "KeywordRetriever",
    "KeywordMatch",
    # 向量检索
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
