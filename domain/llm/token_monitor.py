# Token Monitor - Token Usage Monitoring
"""
Token 监控。

职责：
- 计算工作上下文的 Token 占用
- 提供工作上下文占用比例
"""

from typing import Any, Dict

from domain.llm.token_counter import (
    count_tokens,
    count_message_tokens,
    get_model_context_limit,
    get_model_output_limit,
)
from domain.llm.working_context_builder import (
    get_direct_working_messages,
    get_history_message_count,
    get_working_context_message_count,
    get_working_context_messages,
    get_working_context_summary,
)


# ============================================================
# Token 监控器
# ============================================================

class TokenMonitor:
    """
    Token 使用监控器
    
    专注于工作上下文 Token 使用量的计算和监控，不涉及压缩决策。
    """
    
    def calculate_usage(
        self,
        state: Dict[str, Any],
        model: str = "default"
    ) -> Dict[str, Any]:
        """
        计算当前 Token 占用
        
        Args:
            state: GraphState 状态，包含完整历史 messages 与工作上下文压缩状态
            model: 模型名称
            
        Returns:
            使用情况字典：
            - total_tokens: 总 token 数
            - message_tokens: 消息 token 数
            - summary_tokens: 摘要 token 数
            - history_message_count: 历史消息数
            - working_message_count: 工作上下文消息数
            - context_limit: 上下文限制
            - output_reserve: 输出预留
            - input_limit: 输入限制
            - available: 可用空间
            - usage_ratio: 占用比例
        """
        direct_messages = get_direct_working_messages(state)
        working_messages = get_working_context_messages(state)
        history_message_count = get_history_message_count(state)
        working_message_count = get_working_context_message_count(state)

        message_tokens = self._count_messages(direct_messages, model)

        summary_tokens = 0
        summary = get_working_context_summary(state)
        if summary:
            summary_messages = [msg for msg in working_messages if msg not in direct_messages]
            if summary_messages:
                summary_tokens = self._count_messages(summary_messages, model)
            else:
                summary_tokens = count_tokens(summary, model)

        total_tokens = message_tokens + summary_tokens
        
        # 获取限制
        context_limit = get_model_context_limit(model)
        output_reserve = get_model_output_limit(model)
        available = context_limit - output_reserve - total_tokens
        
        # 计算占用比例（相对于可用输入空间）
        input_limit = context_limit - output_reserve
        usage_ratio = total_tokens / input_limit if input_limit > 0 else 1.0
        
        return {
            "total_tokens": total_tokens,
            "message_tokens": message_tokens,
            "summary_tokens": summary_tokens,
            "history_message_count": history_message_count,
            "working_message_count": working_message_count,
            "context_limit": context_limit,
            "output_reserve": output_reserve,
            "input_limit": input_limit,
            "available": max(0, available),
            "usage_ratio": min(1.0, usage_ratio),
        }
    
    def _count_messages(self, messages: list, model: str) -> int:
        """
        计算消息列表的 token 数
        
        支持两种消息格式：
        - LangChain 消息对象（有 content 属性）
        - 字典格式消息
        
        Args:
            messages: 消息列表
            model: 模型名称
            
        Returns:
            Token 数量
        """
        if not messages:
            return 0
        
        # 检查消息格式
        first_msg = messages[0]
        
        if hasattr(first_msg, "content"):
            # LangChain 消息对象
            return self._count_langchain_messages(messages, model)
        else:
            # 字典格式，使用 token_counter 的函数
            return count_message_tokens(messages, model)
    
    def _count_langchain_messages(self, messages: list, model: str) -> int:
        """
        计算 LangChain 消息的 token 数
        
        Args:
            messages: LangChain 消息列表
            model: 模型名称
            
        Returns:
            Token 数量
        """
        total = 0
        
        for msg in messages:
            # 角色开销（约 4 tokens）
            total += 4
            
            # 内容
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                total += count_tokens(content, model)
            elif isinstance(content, list):
                # 多模态内容
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        total += count_tokens(item["text"], model)
            
            # 扩展字段中的 reasoning_content
            kwargs = getattr(msg, "additional_kwargs", {}) or {}
            reasoning = kwargs.get("reasoning_content", "")
            if reasoning:
                total += count_tokens(reasoning, model)
        
        # 消息格式开销（约 3 tokens）
        total += 3
        return total
    
    def get_usage_ratio(
        self,
        state: Dict[str, Any],
        model: str = "default"
    ) -> float:
        """
        获取占用比例
        
        Args:
            state: GraphState 状态
            model: 模型名称
            
        Returns:
            占用比例（0.0 - 1.0）
        """
        usage = self.calculate_usage(state, model)
        return usage["usage_ratio"]


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "TokenMonitor",
]
