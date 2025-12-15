# Token Monitor - Token Usage Monitoring
"""
Token 监控 - 监控 Token 使用量

职责：
- 计算当前 Token 占用
- 获取占用比例
- 判断是否需要压缩上下文

使用示例：
    from domain.llm.token_monitor import TokenMonitor
    
    monitor = TokenMonitor()
    usage = monitor.calculate_usage(state, model)
    if monitor.should_compress(state, model):
        # 执行压缩
        pass
"""

from typing import Any, Dict, List, Optional

from domain.llm.token_counter import (
    count_tokens,
    count_message_tokens,
    get_model_context_limit,
    get_model_output_limit,
)


# ============================================================
# 常量
# ============================================================

# 默认压缩阈值（上下文占用比例）
DEFAULT_COMPRESS_THRESHOLD = 0.8

# 压缩后目标占用比例
TARGET_USAGE_AFTER_COMPRESS = 0.5


# ============================================================
# Token 监控器
# ============================================================

class TokenMonitor:
    """
    Token 使用监控器
    
    监控上下文 Token 使用情况，判断是否需要压缩。
    """
    
    def __init__(self, compress_threshold: float = DEFAULT_COMPRESS_THRESHOLD):
        """
        初始化监控器
        
        Args:
            compress_threshold: 触发压缩的阈值（0.0 - 1.0）
        """
        self._compress_threshold = compress_threshold
        self._logger = None
    
    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("token_monitor")
            except Exception:
                pass
        return self._logger
    
    def calculate_usage(
        self,
        state: Dict[str, Any],
        model: str = "default"
    ) -> Dict[str, Any]:
        """
        计算当前 Token 占用
        
        Args:
            state: GraphState 状态
            model: 模型名称
            
        Returns:
            使用情况字典：
            - total_tokens: 总 token 数
            - context_limit: 上下文限制
            - output_reserve: 输出预留
            - available: 可用空间
            - usage_ratio: 占用比例
        """
        messages = state.get("messages", [])
        
        # 计算消息 tokens
        if messages:
            # 检查是否为 LangChain 消息
            if hasattr(messages[0], "content"):
                total_tokens = self._count_langchain_messages(messages, model)
            else:
                total_tokens = count_message_tokens(messages, model)
        else:
            total_tokens = 0
        
        # 添加摘要 tokens（如果有）
        summary = state.get("conversation_summary", "")
        if summary:
            total_tokens += count_tokens(summary, model)
        
        # 获取限制
        context_limit = get_model_context_limit(model)
        output_reserve = get_model_output_limit(model)
        available = context_limit - output_reserve - total_tokens
        
        # 计算占用比例（相对于可用输入空间）
        input_limit = context_limit - output_reserve
        usage_ratio = total_tokens / input_limit if input_limit > 0 else 1.0
        
        return {
            "total_tokens": total_tokens,
            "context_limit": context_limit,
            "output_reserve": output_reserve,
            "available": max(0, available),
            "usage_ratio": min(1.0, usage_ratio),
        }
    
    def _count_langchain_messages(
        self,
        messages: List[Any],
        model: str
    ) -> int:
        """计算 LangChain 消息的 token 数"""
        total = 0
        
        for msg in messages:
            # 角色开销
            total += 4
            
            # 内容
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                total += count_tokens(content, model)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        total += count_tokens(item["text"], model)
            
            # 扩展字段
            kwargs = getattr(msg, "additional_kwargs", {}) or {}
            reasoning = kwargs.get("reasoning_content", "")
            if reasoning:
                total += count_tokens(reasoning, model)
        
        total += 3  # 格式开销
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
    
    def should_compress(
        self,
        state: Dict[str, Any],
        model: str = "default",
        threshold: Optional[float] = None
    ) -> bool:
        """
        判断是否需要压缩上下文
        
        Args:
            state: GraphState 状态
            model: 模型名称
            threshold: 自定义阈值（可选）
            
        Returns:
            是否需要压缩
        """
        threshold = threshold or self._compress_threshold
        ratio = self.get_usage_ratio(state, model)
        
        should = ratio >= threshold
        
        if should and self.logger:
            self.logger.info(
                f"上下文需要压缩: 占用比例 {ratio:.1%} >= 阈值 {threshold:.1%}"
            )
        
        return should
    
    def get_model_limit(self, model: str = "default") -> int:
        """
        获取模型上下文限制
        
        Args:
            model: 模型名称
            
        Returns:
            上下文限制（tokens）
        """
        return get_model_context_limit(model)
    
    def estimate_tokens_to_remove(
        self,
        state: Dict[str, Any],
        model: str = "default",
        target_ratio: float = TARGET_USAGE_AFTER_COMPRESS
    ) -> int:
        """
        估算需要移除的 token 数量
        
        Args:
            state: GraphState 状态
            model: 模型名称
            target_ratio: 目标占用比例
            
        Returns:
            需要移除的 token 数量
        """
        usage = self.calculate_usage(state, model)
        current_tokens = usage["total_tokens"]
        input_limit = usage["context_limit"] - usage["output_reserve"]
        
        target_tokens = int(input_limit * target_ratio)
        tokens_to_remove = current_tokens - target_tokens
        
        return max(0, tokens_to_remove)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "TokenMonitor",
    "DEFAULT_COMPRESS_THRESHOLD",
    "TARGET_USAGE_AFTER_COMPRESS",
]
