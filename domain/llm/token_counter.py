# Token Counter - Token Counting Utilities
"""
Token 计数工具 - 提供 Token 计数功能

职责：
- 计算文本的 Token 数量
- 支持不同模型的 Token 计数
- 提供模型上下文限制信息

使用示例：
    from domain.llm.token_counter import count_tokens, get_model_context_limit
    
    tokens = count_tokens("Hello, world!", model="glm-4")
    limit = get_model_context_limit("glm-4")
"""

from typing import Any, Dict, List, Optional, Union


# ============================================================
# 模型上下文限制配置
# ============================================================

# 模型上下文限制（tokens）
MODEL_CONTEXT_LIMITS: Dict[str, int] = {
    # ============================================================
    # 智谱 GLM 系列（当前版本主要支持）
    # ============================================================
    "glm-4.6": 200_000,       # 最新旗舰模型，355B/32B MoE，支持深度思考
    "glm-4.5": 128_000,       # 平衡性能与成本
    "glm-4.5-flash": 128_000, # 快速响应，适合简单任务
    "glm-4.6v": 200_000,      # 多模态模型，支持图像理解
    
    # ============================================================
    # OpenAI 系列（后续扩展）
    # ============================================================
    
    # ============================================================
    # Anthropic Claude 系列（后续扩展）
    # ============================================================
    
    # ============================================================
    # Google Gemini 系列（后续扩展）
    # ============================================================
    
    # ============================================================
    # 阿里通义千问系列（后续扩展）
    # ============================================================
    
    # ============================================================
    # DeepSeek 系列（后续扩展）
    # ============================================================
    
    # 默认值
    "default": 128_000,
}

# 模型输出限制（tokens）
MODEL_OUTPUT_LIMITS: Dict[str, int] = {
    # ============================================================
    # 智谱 GLM 系列
    # ============================================================
    "glm-4.6": 16_384,
    "glm-4.5": 16_384,
    "glm-4.5-flash": 16_384,
    "glm-4.6v": 16_384,
    
    # ============================================================
    # OpenAI 系列（后续扩展）
    # ============================================================
    
    # ============================================================
    # Anthropic Claude 系列（后续扩展）
    # ============================================================
    
    # ============================================================
    # Google Gemini 系列（后续扩展）
    # ============================================================
    
    # ============================================================
    # 阿里通义千问系列（后续扩展）
    # ============================================================
    
    # ============================================================
    # DeepSeek 系列（后续扩展）
    # ============================================================
    
    # 默认值
    "default": 4_096,
}


# ============================================================
# Token 计数器
# ============================================================

# 缓存的 tokenizer
_tokenizer_cache: Dict[str, Any] = {}


def _get_tokenizer(model: str = "default") -> Any:
    """
    获取 tokenizer（带缓存）
    
    Args:
        model: 模型名称
        
    Returns:
        tokenizer 实例
    """
    if model in _tokenizer_cache:
        return _tokenizer_cache[model]
    
    try:
        import tiktoken
        # 智谱 GLM 使用 cl100k_base 编码（与 GPT-4 相同）
        tokenizer = tiktoken.get_encoding("cl100k_base")
        _tokenizer_cache[model] = tokenizer
        return tokenizer
    except ImportError:
        # tiktoken 未安装，使用简单估算
        return None
    except Exception:
        return None


def count_tokens(
    text: Union[str, List[str]],
    model: str = "default"
) -> int:
    """
    计算文本的 Token 数量
    
    Args:
        text: 文本内容（字符串或字符串列表）
        model: 模型名称
        
    Returns:
        Token 数量
    """
    if isinstance(text, list):
        return sum(count_tokens(t, model) for t in text)
    
    if not text:
        return 0
    
    tokenizer = _get_tokenizer(model)
    
    if tokenizer is not None:
        try:
            return len(tokenizer.encode(text))
        except Exception:
            pass
    
    # 回退：简单估算（中文约 2 字符/token，英文约 4 字符/token）
    return _estimate_tokens(text)


def _estimate_tokens(text: str) -> int:
    """
    简单估算 Token 数量
    
    中文字符约 2 字符/token
    英文字符约 4 字符/token
    """
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    
    return int(chinese_chars / 1.5 + other_chars / 4)


def count_message_tokens(
    messages: List[Dict[str, Any]],
    model: str = "default"
) -> int:
    """
    计算消息列表的 Token 数量
    
    Args:
        messages: 消息列表（字典格式）
        model: 模型名称
        
    Returns:
        Token 数量
    """
    total = 0
    
    for msg in messages:
        # 角色标记开销（约 4 tokens）
        total += 4
        
        # 内容
        content = msg.get("content", "")
        if isinstance(content, str):
            total += count_tokens(content, model)
        elif isinstance(content, list):
            # 多模态内容
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    total += count_tokens(item["text"], model)
        
        # 思考内容
        reasoning = msg.get("reasoning_content", "")
        if reasoning:
            total += count_tokens(reasoning, model)
    
    # 消息格式开销（约 3 tokens）
    total += 3
    
    return total


# ============================================================
# 模型限制查询
# ============================================================

def get_model_context_limit(model: str = "default") -> int:
    """
    获取模型的上下文限制
    
    Args:
        model: 模型名称
        
    Returns:
        上下文限制（tokens）
    """
    # 尝试精确匹配
    if model in MODEL_CONTEXT_LIMITS:
        return MODEL_CONTEXT_LIMITS[model]
    
    # 尝试前缀匹配
    for key in MODEL_CONTEXT_LIMITS:
        if model.startswith(key):
            return MODEL_CONTEXT_LIMITS[key]
    
    return MODEL_CONTEXT_LIMITS["default"]


def get_model_output_limit(model: str = "default") -> int:
    """
    获取模型的输出限制
    
    Args:
        model: 模型名称
        
    Returns:
        输出限制（tokens）
    """
    if model in MODEL_OUTPUT_LIMITS:
        return MODEL_OUTPUT_LIMITS[model]
    
    for key in MODEL_OUTPUT_LIMITS:
        if model.startswith(key):
            return MODEL_OUTPUT_LIMITS[key]
    
    return MODEL_OUTPUT_LIMITS["default"]


def get_available_context(
    model: str,
    used_tokens: int,
    reserve_output: bool = True
) -> int:
    """
    计算可用的上下文空间
    
    Args:
        model: 模型名称
        used_tokens: 已使用的 tokens
        reserve_output: 是否预留输出空间
        
    Returns:
        可用的 tokens 数量
    """
    limit = get_model_context_limit(model)
    
    if reserve_output:
        output_limit = get_model_output_limit(model)
        limit -= output_limit
    
    return max(0, limit - used_tokens)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 计数函数
    "count_tokens",
    "count_message_tokens",
    # 限制查询
    "get_model_context_limit",
    "get_model_output_limit",
    "get_available_context",
    # 常量
    "MODEL_CONTEXT_LIMITS",
    "MODEL_OUTPUT_LIMITS",
]
