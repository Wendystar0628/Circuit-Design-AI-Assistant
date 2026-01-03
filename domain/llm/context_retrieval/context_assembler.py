# Context Assembler - Assemble Search Results with Implicit Context
"""
上下文组装器 - 将搜索结果与隐式上下文按优先级组装

职责边界说明：
- RRF 融合、去重、排序已由阶段五 SearchResultMerger 完成
- 本模块只负责将已融合的搜索结果与隐式上下文组装成最终 Prompt 上下文
- 不重复实现融合算法，遵循单一职责原则

职责：
- 将搜索结果与隐式上下文按优先级组装
- 分配 Token 预算
- 按优先级排序
- 截断到预算

被调用方：context_retriever.py
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from domain.llm.context_retrieval.context_source_protocol import (
    ContextPriority,
    ContextResult,
)


# ============================================================
# 数据类定义
# ============================================================

@dataclass
class ContextItem:
    """
    上下文项 - 组装后的单个上下文条目
    
    Attributes:
        content: 上下文内容（可能被截断）
        source: 来源标识
        priority: 优先级
        token_count: Token 数
        truncated: 是否被截断
        metadata: 元数据（文件路径、行号等）
    """
    content: str
    source: str
    priority: ContextPriority
    token_count: int
    truncated: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "source": self.source,
            "priority": self.priority.value,
            "token_count": self.token_count,
            "truncated": self.truncated,
            "metadata": self.metadata,
        }


@dataclass
class BudgetAllocation:
    """
    Token 预算分配结果
    
    Attributes:
        diagnostics: 诊断信息预算
        dependencies: 依赖文件预算
        design_goals: 设计目标预算
        simulation: 仿真结果预算
        search_results: 搜索结果预算
        total: 总预算
    """
    diagnostics: int
    dependencies: int
    design_goals: int
    simulation: int
    search_results: int
    total: int
    
    def to_dict(self) -> Dict[str, int]:
        return {
            "diagnostics": self.diagnostics,
            "dependencies": self.dependencies,
            "design_goals": self.design_goals,
            "simulation": self.simulation,
            "search_results": self.search_results,
            "total": self.total,
        }


@dataclass
class AssembledContext:
    """
    组装后的上下文
    
    Attributes:
        items: 按优先级排序的上下文项列表
        total_tokens: 实际使用的 Token 数
        budget_utilization: 预算利用率（0-1）
        truncated_count: 被截断的上下文项数量
        budget_allocation: 预算分配详情
    """
    items: List[ContextItem] = field(default_factory=list)
    total_tokens: int = 0
    budget_utilization: float = 0.0
    truncated_count: int = 0
    budget_allocation: Optional[BudgetAllocation] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "total_tokens": self.total_tokens,
            "budget_utilization": self.budget_utilization,
            "truncated_count": self.truncated_count,
            "budget_allocation": (
                self.budget_allocation.to_dict() 
                if self.budget_allocation else None
            ),
        }
    
    @property
    def is_empty(self) -> bool:
        return len(self.items) == 0


# ============================================================
# 预算分配常量
# ============================================================

# 默认预算分配（tokens）
DEFAULT_DIAGNOSTICS_BUDGET = 500
DEFAULT_DEPENDENCIES_BUDGET = 1000
DEFAULT_DESIGN_GOALS_BUDGET = 300
DEFAULT_SIMULATION_BUDGET = 500

# 来源到优先级的映射
SOURCE_PRIORITY_MAP = {
    "diagnostics": ContextPriority.CRITICAL,
    "dependency": ContextPriority.HIGH,
    "design_goals": ContextPriority.HIGH,
    "circuit_file": ContextPriority.HIGH,
    "simulation": ContextPriority.MEDIUM,
    "exact": ContextPriority.LOW,
    "semantic": ContextPriority.LOW,
}

# 字符到 Token 的估算比例
CHARS_PER_TOKEN = 4


# ============================================================
# 上下文组装器
# ============================================================

class ContextAssembler:
    """
    上下文组装器
    
    将搜索结果与隐式上下文按优先级组装，分配 Token 预算。
    不做 RRF 融合（已由阶段五 SearchResultMerger 完成）。
    """

    def __init__(self):
        self._logger = None

    @property
    def logger(self):
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("context_assembler")
            except Exception:
                pass
        return self._logger

    # ============================================================
    # 主入口
    # ============================================================

    def assemble(
        self,
        search_results: List[Any],
        implicit_contexts: List[ContextResult],
        token_budget: int,
    ) -> AssembledContext:
        """
        组装搜索结果与隐式上下文
        
        Args:
            search_results: 来自 UnifiedSearchService 的已融合搜索结果
                           （可以是 UnifiedSearchResult 或 List[RetrievalResult]）
            implicit_contexts: 来自 ImplicitContextAggregator 的隐式上下文
            token_budget: 总 Token 预算
            
        Returns:
            AssembledContext: 组装后的上下文
        """
        result = AssembledContext()
        
        # Step 1: 分配预算
        budget = self._allocate_budget(
            total_budget=token_budget,
            implicit_contexts=implicit_contexts,
            search_results=search_results,
        )
        result.budget_allocation = budget
        
        # Step 2: 转换隐式上下文为 ContextItem
        implicit_items = self._convert_implicit_contexts(implicit_contexts)
        
        # Step 3: 转换搜索结果为 ContextItem
        search_items = self._convert_search_results(search_results)
        
        # Step 4: 合并所有项
        all_items = implicit_items + search_items
        
        # Step 5: 按优先级排序
        sorted_items = self._sort_by_priority(all_items)
        
        # Step 6: 按预算截断
        final_items, truncated_count = self._truncate_to_budget(
            sorted_items, token_budget
        )
        
        # Step 7: 计算统计信息
        result.items = final_items
        result.total_tokens = sum(item.token_count for item in final_items)
        result.budget_utilization = (
            result.total_tokens / token_budget if token_budget > 0 else 0.0
        )
        result.truncated_count = truncated_count
        
        if self.logger:
            self.logger.debug(
                f"Assembled {len(final_items)} items, "
                f"tokens: {result.total_tokens}/{token_budget} "
                f"({result.budget_utilization:.1%}), "
                f"truncated: {truncated_count}"
            )
        
        return result

    # ============================================================
    # 预算分配
    # ============================================================

    def _allocate_budget(
        self,
        total_budget: int,
        implicit_contexts: List[ContextResult],
        search_results: List[Any],
    ) -> BudgetAllocation:
        """
        分配各类上下文的 Token 预算
        
        策略：
        - 诊断信息（CRITICAL）：预留 500 tokens，始终保留
        - 依赖文件（HIGH）：预留 1000 tokens
        - 设计目标（HIGH）：预留 300 tokens
        - 仿真结果（MEDIUM）：预留 500 tokens
        - 搜索结果（NORMAL）：剩余预算
        - 动态调整：若某类上下文不足预算，将剩余预算分配给搜索结果
        """
        # 计算各类隐式上下文的实际 Token 数
        actual_diagnostics = 0
        actual_dependencies = 0
        actual_design_goals = 0
        actual_simulation = 0
        
        for ctx in implicit_contexts:
            if ctx.source_name == "diagnostics":
                actual_diagnostics += ctx.token_count
            elif ctx.source_name == "dependency":
                actual_dependencies += ctx.token_count
            elif ctx.source_name == "design_goals":
                actual_design_goals += ctx.token_count
            elif ctx.source_name in ("simulation", "circuit_file"):
                actual_simulation += ctx.token_count
        
        # 分配预算（取实际值和默认值的较小者）
        diagnostics_budget = min(actual_diagnostics, DEFAULT_DIAGNOSTICS_BUDGET)
        dependencies_budget = min(actual_dependencies, DEFAULT_DEPENDENCIES_BUDGET)
        design_goals_budget = min(actual_design_goals, DEFAULT_DESIGN_GOALS_BUDGET)
        simulation_budget = min(actual_simulation, DEFAULT_SIMULATION_BUDGET)
        
        # 计算搜索结果预算（剩余预算）
        reserved = (
            diagnostics_budget + dependencies_budget + 
            design_goals_budget + simulation_budget
        )
        search_budget = max(0, total_budget - reserved)
        
        return BudgetAllocation(
            diagnostics=diagnostics_budget,
            dependencies=dependencies_budget,
            design_goals=design_goals_budget,
            simulation=simulation_budget,
            search_results=search_budget,
            total=total_budget,
        )

    # ============================================================
    # 转换方法
    # ============================================================

    def _convert_implicit_contexts(
        self,
        implicit_contexts: List[ContextResult],
    ) -> List[ContextItem]:
        """将隐式上下文转换为 ContextItem"""
        items = []
        for ctx in implicit_contexts:
            if ctx.is_empty:
                continue
            items.append(ContextItem(
                content=ctx.content,
                source=ctx.source_name,
                priority=ctx.priority,
                token_count=ctx.token_count,
                truncated=False,
                metadata=ctx.metadata,
            ))
        return items

    def _convert_search_results(
        self,
        search_results: List[Any],
    ) -> List[ContextItem]:
        """
        将搜索结果转换为 ContextItem
        
        支持多种输入格式：
        - UnifiedSearchResult（阶段五）
        - List[RetrievalResult]（当前格式）
        - List[dict]
        """
        items = []
        
        # 处理 UnifiedSearchResult 格式
        if hasattr(search_results, 'exact_matches'):
            # 精确匹配结果
            for match in search_results.exact_matches:
                content = self._extract_match_content(match)
                if content:
                    items.append(ContextItem(
                        content=content,
                        source="exact",
                        priority=ContextPriority.LOW,
                        token_count=getattr(match, 'token_count', 0) or self._estimate_tokens(content),
                        truncated=getattr(match, 'truncated', False),
                        metadata={
                            "file_path": getattr(match, 'file_path', ''),
                            "line_number": getattr(match, 'line_number', 0),
                            "score": getattr(match, 'score', 0.0),
                        },
                    ))
            # 语义匹配结果
            for match in search_results.semantic_matches:
                content = getattr(match, 'content', '')
                if content:
                    items.append(ContextItem(
                        content=content,
                        source="semantic",
                        priority=ContextPriority.LOW,
                        token_count=getattr(match, 'token_count', 0) or self._estimate_tokens(content),
                        truncated=getattr(match, 'truncated', False),
                        metadata={
                            "source": getattr(match, 'source', ''),
                            "score": getattr(match, 'score', 0.0),
                        },
                    ))
        # 处理列表格式
        elif isinstance(search_results, list):
            for result in search_results:
                if hasattr(result, 'content'):
                    # RetrievalResult 格式
                    content = result.content
                    source = getattr(result, 'source', 'search')
                    token_count = getattr(result, 'token_count', 0)
                elif isinstance(result, dict):
                    # 字典格式
                    content = result.get('content', '')
                    source = result.get('source', 'search')
                    token_count = result.get('token_count', 0)
                else:
                    continue
                
                if not content:
                    continue
                
                priority = SOURCE_PRIORITY_MAP.get(source, ContextPriority.LOW)
                
                items.append(ContextItem(
                    content=content,
                    source=source,
                    priority=priority,
                    token_count=token_count or self._estimate_tokens(content),
                    truncated=False,
                    metadata=self._extract_metadata(result),
                ))
        
        return items

    def _extract_match_content(self, match: Any) -> str:
        """从搜索匹配中提取内容"""
        # 优先使用带上下文的内容
        content_parts = []
        if hasattr(match, 'context_before') and match.context_before:
            content_parts.extend(match.context_before)
        if hasattr(match, 'line_content') and match.line_content:
            content_parts.append(f">>> {match.line_content}")
        if hasattr(match, 'context_after') and match.context_after:
            content_parts.extend(match.context_after)
        
        if content_parts:
            return "\n".join(content_parts)
        
        # 回退到 content 字段
        return getattr(match, 'content', '') or getattr(match, 'line_content', '')

    def _extract_metadata(self, result: Any) -> Dict[str, Any]:
        """从结果中提取元数据"""
        metadata = {}
        
        if hasattr(result, 'path'):
            metadata['file_path'] = result.path
        elif isinstance(result, dict) and 'path' in result:
            metadata['file_path'] = result['path']
        
        if hasattr(result, 'relevance'):
            metadata['score'] = result.relevance
        elif isinstance(result, dict) and 'relevance' in result:
            metadata['score'] = result['relevance']
        
        return metadata

    # ============================================================
    # 排序和截断
    # ============================================================

    def _sort_by_priority(
        self,
        items: List[ContextItem],
    ) -> List[ContextItem]:
        """
        按优先级排序
        
        排序规则：
        1. 诊断信息（CRITICAL）
        2. 依赖文件（HIGH）
        3. 设计目标（HIGH）
        4. 仿真结果（MEDIUM）
        5. 精确搜索结果（LOW）
        6. 语义搜索结果（LOW）
        
        同优先级内按 token_count 降序（保留更完整的内容）
        """
        # 定义来源的次级排序权重
        source_order = {
            "diagnostics": 0,
            "dependency": 1,
            "design_goals": 2,
            "circuit_file": 3,
            "simulation": 4,
            "exact": 5,
            "semantic": 6,
        }
        
        return sorted(
            items,
            key=lambda x: (
                x.priority.value,
                source_order.get(x.source, 99),
                -x.token_count,  # 同优先级内，token 多的优先
            ),
        )

    def _truncate_to_budget(
        self,
        items: List[ContextItem],
        token_budget: int,
    ) -> tuple:
        """
        按 Token 预算截断
        
        Args:
            items: 已排序的上下文项列表
            token_budget: Token 预算
            
        Returns:
            tuple: (截断后的列表, 被截断的数量)
        """
        if not items:
            return [], 0
        
        final_items = []
        total_tokens = 0
        truncated_count = 0
        
        for item in items:
            if total_tokens + item.token_count <= token_budget:
                final_items.append(item)
                total_tokens += item.token_count
            else:
                # 尝试截断内容以适应预算
                remaining_budget = token_budget - total_tokens
                if remaining_budget > 100:  # 至少保留 100 tokens
                    truncated_item = self._truncate_item(item, remaining_budget)
                    if truncated_item:
                        final_items.append(truncated_item)
                        truncated_count += 1
                else:
                    truncated_count += 1
        
        # 统计未能加入的项
        truncated_count += len(items) - len(final_items) - truncated_count
        
        return final_items, truncated_count

    def _truncate_item(
        self,
        item: ContextItem,
        max_tokens: int,
    ) -> Optional[ContextItem]:
        """
        截断单个上下文项的内容
        
        截断策略：
        - 保留开头（60%）和结尾（30%），中间省略（10%用于省略标记）
        - 代码文件：优先保留完整行，避免截断在行中间
        """
        max_chars = max_tokens * CHARS_PER_TOKEN
        
        if len(item.content) <= max_chars:
            return item
        
        # 计算保留的字符数
        head_chars = int(max_chars * 0.6)
        tail_chars = int(max_chars * 0.3)
        
        # 截断内容
        head = item.content[:head_chars]
        tail = item.content[-tail_chars:] if tail_chars > 0 else ""
        
        # 尝试在行边界截断
        last_newline = head.rfind('\n')
        if last_newline > head_chars // 2:
            head = head[:last_newline]
        
        first_newline = tail.find('\n')
        if first_newline > 0 and first_newline < tail_chars // 2:
            tail = tail[first_newline + 1:]
        
        truncated_content = f"{head}\n... [truncated] ...\n{tail}"
        
        return ContextItem(
            content=truncated_content,
            source=item.source,
            priority=item.priority,
            token_count=max_tokens,
            truncated=True,
            metadata=item.metadata,
        )

    # ============================================================
    # 辅助方法
    # ============================================================

    def _estimate_tokens(self, text: str) -> int:
        """
        估算文本的 Token 数
        
        优先使用 token_counter 模块，若不可用则回退到简单估算。
        """
        if not text:
            return 0
        
        try:
            from domain.llm.token_counter import estimate_tokens
            return estimate_tokens(text)
        except ImportError:
            # 回退到简单估算
            return len(text) // CHARS_PER_TOKEN


__all__ = [
    "ContextAssembler",
    "ContextItem",
    "AssembledContext",
    "BudgetAllocation",
]
