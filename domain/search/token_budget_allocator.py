# Token Budget Allocator
"""
Token 预算分配器

职责：
- 管理搜索结果的 Token 预算
- 根据预算截断搜索结果
- 估算文本的 Token 数量

设计原则：
- 精确搜索优先（精确匹配通常更有价值）
- 保留开头和结尾，中间省略（截断策略）
- 简单的 Token 估算（4 字符 ≈ 1 token）
"""

from typing import List, Tuple

from domain.search.models.unified_search_result import (
    TokenBudgetConfig,
    ExactMatchResult,
    SemanticMatchResult,
)


class TokenBudgetAllocator:
    """
    Token 预算分配器
    
    负责根据 Token 预算截断搜索结果，
    确保返回给 LLM 的上下文不会超出限制。
    """
    
    # Token 估算系数（平均 4 字符 ≈ 1 token）
    CHARS_PER_TOKEN = 4
    
    def __init__(self, config: TokenBudgetConfig = None):
        """
        初始化预算分配器
        
        Args:
            config: Token 预算配置，默认使用 TokenBudgetConfig 默认值
        """
        self.config = config or TokenBudgetConfig()
    
    def estimate_tokens(self, text: str) -> int:
        """
        估算文本的 Token 数量
        
        使用简单的字符数估算，适用于大多数场景。
        
        Args:
            text: 输入文本
            
        Returns:
            int: 估算的 Token 数
        """
        if not text:
            return 0
        return max(1, len(text) // self.CHARS_PER_TOKEN)
    
    def truncate_text(
        self,
        text: str,
        max_tokens: int,
        preserve_ends: bool = True
    ) -> Tuple[str, bool]:
        """
        截断文本以符合 Token 预算
        
        Args:
            text: 输入文本
            max_tokens: 最大 Token 数
            preserve_ends: 是否保留开头和结尾
            
        Returns:
            Tuple[str, bool]: (截断后的文本, 是否被截断)
        """
        if not text:
            return "", False
        
        current_tokens = self.estimate_tokens(text)
        if current_tokens <= max_tokens:
            return text, False
        
        # 计算目标字符数
        target_chars = max_tokens * self.CHARS_PER_TOKEN
        
        if preserve_ends and target_chars > 100:
            # 保留开头和结尾，中间省略
            head_chars = target_chars // 2 - 10
            tail_chars = target_chars // 2 - 10
            truncated = (
                text[:head_chars] +
                "\n... [truncated] ...\n" +
                text[-tail_chars:]
            )
        else:
            # 简单截断
            truncated = text[:target_chars - 20] + "... [truncated]"
        
        return truncated, True
    
    def allocate_exact_results(
        self,
        results: List[ExactMatchResult]
    ) -> Tuple[List[ExactMatchResult], int]:
        """
        分配精确搜索结果的 Token 预算
        
        Args:
            results: 精确匹配结果列表
            
        Returns:
            Tuple[List[ExactMatchResult], int]: (截断后的结果, 使用的 Token 数)
        """
        if not results:
            return [], 0
        
        budget = self.config.exact_budget
        allocated = []
        tokens_used = 0
        
        for result in results:
            # 估算单条结果的 Token 数
            result_text = self._format_exact_result(result)
            result_tokens = self.estimate_tokens(result_text)
            
            # 检查是否超出单条结果限制
            if result_tokens > self.config.max_result_tokens:
                # 截断内容
                if result.line_content:
                    truncated, _ = self.truncate_text(
                        result.line_content,
                        self.config.max_result_tokens // 2
                    )
                    result.line_content = truncated
                result_tokens = self.config.max_result_tokens
            
            # 检查是否超出总预算
            if tokens_used + result_tokens > budget:
                break
            
            result.token_count = result_tokens
            allocated.append(result)
            tokens_used += result_tokens
        
        return allocated, tokens_used
    
    def allocate_semantic_results(
        self,
        results: List[SemanticMatchResult]
    ) -> Tuple[List[SemanticMatchResult], int]:
        """
        分配语义搜索结果的 Token 预算
        
        Args:
            results: 语义匹配结果列表
            
        Returns:
            Tuple[List[SemanticMatchResult], int]: (截断后的结果, 使用的 Token 数)
        """
        if not results:
            return [], 0
        
        budget = self.config.semantic_budget
        allocated = []
        tokens_used = 0
        
        for result in results:
            # 估算单条结果的 Token 数
            result_tokens = self.estimate_tokens(result.content)
            
            # 检查是否超出单条结果限制
            if result_tokens > self.config.max_result_tokens:
                # 截断内容
                truncated, _ = self.truncate_text(
                    result.content,
                    self.config.max_result_tokens
                )
                result.content = truncated
                result_tokens = self.config.max_result_tokens
            
            # 检查是否超出总预算
            if tokens_used + result_tokens > budget:
                break
            
            result.token_count = result_tokens
            allocated.append(result)
            tokens_used += result_tokens
        
        return allocated, tokens_used
    
    def _format_exact_result(self, result: ExactMatchResult) -> str:
        """格式化精确匹配结果为文本（用于 Token 估算）"""
        parts = [
            f"File: {result.file_path}",
        ]
        
        if result.line_number:
            parts.append(f"Line: {result.line_number}")
        
        if result.context_before:
            parts.extend(result.context_before)
        
        if result.line_content:
            parts.append(result.line_content)
        
        if result.context_after:
            parts.extend(result.context_after)
        
        return "\n".join(parts)


# ============================================================
# 模块导出
# ============================================================

__all__ = ["TokenBudgetAllocator"]
