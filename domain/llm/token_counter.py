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

import logging
from typing import Any, Dict, List, Optional, Union

_logger = logging.getLogger(__name__)


# ============================================================
# 模型上下文限制配置
# ============================================================

# 模型上下文限制（tokens）
MODEL_CONTEXT_LIMITS: Dict[str, int] = {
    # ============================================================
    # 智谱 GLM 系列（已实现）
    # ============================================================
    "glm-4.6": 200_000,       # 最新旗舰模型，355B/32B MoE，支持深度思考
    "glm-4.5": 128_000,       # 平衡性能与成本
    "glm-4.5-flash": 128_000, # 快速响应，适合简单任务
    "glm-4.6v": 200_000,      # 多模态模型，支持图像理解
    "codegeex-4": 128_000,    # 代码生成专用模型
    
    # ============================================================
    # DeepSeek 系列（占位）
    # ============================================================
    "deepseek-chat": 64_000,
    "deepseek-coder": 64_000,
    
    # ============================================================
    # 阿里通义千问系列（占位）
    # ============================================================
    "qwen-max": 32_000,
    "qwen-plus": 32_000,
    "qwen-turbo": 8_000,
    
    # ============================================================
    # OpenAI 系列（占位）
    # ============================================================
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    
    # ============================================================
    # Anthropic Claude 系列（占位）
    # ============================================================
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-5-haiku-20241022": 200_000,
    
    # 默认值
    "default": 128_000,
}

# 模型输出限制（tokens）
MODEL_OUTPUT_LIMITS: Dict[str, int] = {
    # ============================================================
    # 智谱 GLM 系列（已实现）
    # ============================================================
    "glm-4.6": 16_384,
    "glm-4.5": 16_384,
    "glm-4.5-flash": 16_384,
    "glm-4.6v": 16_384,
    "codegeex-4": 16_384,
    
    # ============================================================
    # DeepSeek 系列（占位）
    # ============================================================
    "deepseek-chat": 8_192,
    "deepseek-coder": 8_192,
    
    # ============================================================
    # 阿里通义千问系列（占位）
    # ============================================================
    "qwen-max": 8_192,
    "qwen-plus": 8_192,
    "qwen-turbo": 8_192,
    
    # ============================================================
    # OpenAI 系列（占位）
    # ============================================================
    "gpt-4o": 16_384,
    "gpt-4o-mini": 16_384,
    "gpt-4-turbo": 4_096,
    
    # ============================================================
    # Anthropic Claude 系列（占位）
    # ============================================================
    "claude-3-5-sonnet-20241022": 8_192,
    "claude-3-5-haiku-20241022": 8_192,
    
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
    
    Tokenizer 选择策略：
    - 智谱 GLM 系列：使用 tiktoken 的 cl100k_base 编码器
    - OpenAI 系列：使用 cl100k_base 编码器
    - Anthropic Claude 系列：使用 cl100k_base 作为近似（误差在 5% 以内）
    - 加载失败时回退到近似计算，记录 WARNING 日志
    
    Args:
        model: 模型名称
        
    Returns:
        tokenizer 实例，加载失败返回 None
    """
    if model in _tokenizer_cache:
        return _tokenizer_cache[model]
    
    try:
        import tiktoken
        # 智谱 GLM / OpenAI GPT-4 / Claude 均使用 cl100k_base 编码
        tokenizer = tiktoken.get_encoding("cl100k_base")
        _tokenizer_cache[model] = tokenizer
        return tokenizer
    except ImportError:
        # tiktoken 未安装，使用简单估算
        _logger.warning(
            "tiktoken not installed, falling back to approximate token counting. "
            "Install tiktoken for accurate counting: pip install tiktoken"
        )
        _tokenizer_cache[model] = None
        return None
    except Exception as e:
        _logger.warning(f"Failed to load tokenizer for model '{model}': {e}")
        _tokenizer_cache[model] = None
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
    近似估算 Token 数量
    
    计算规则：
    - 中文字符：约 1.5 字符/token（每个汉字约 0.67 token）
    - 英文单词：约 1.3 token/word（常见词 1 token，长词 2-3 tokens）
    - 数字：约 1-2 token/数字串
    - 标点符号：通常 1 token/符号
    - 换行符：通常 1 token
    - 空格：通常 4 个合并为 1 token
    
    近似公式：tokens ≈ chinese_chars / 1.5 + other_chars / 4
    """
    if not text:
        return 0
    
    chinese_chars = 0
    punctuation_chars = 0
    newline_chars = 0
    space_chars = 0
    other_chars = 0
    
    for c in text:
        if '\u4e00' <= c <= '\u9fff':
            # 中文字符
            chinese_chars += 1
        elif '\u3000' <= c <= '\u303f' or '\uff00' <= c <= '\uffef':
            # 中文标点
            punctuation_chars += 1
        elif c in '.,;:!?()[]{}"\'-':
            # 英文标点
            punctuation_chars += 1
        elif c == '\n':
            newline_chars += 1
        elif c in ' \t':
            space_chars += 1
        else:
            other_chars += 1
    
    # 计算 Token 数
    tokens = 0
    tokens += chinese_chars / 1.5          # 中文约 1.5 字符/token
    tokens += punctuation_chars            # 标点通常 1 token
    tokens += newline_chars                # 换行通常 1 token
    tokens += space_chars / 4              # 空格约 4 个/token
    tokens += other_chars / 4              # 其他字符约 4 个/token
    
    return int(tokens)


def count_message_tokens(
    messages: List[Dict[str, Any]],
    model: str = "default"
) -> int:
    """
    计算消息列表的 Token 数量
    
    消息格式开销：
    - 每条消息的角色标记（role）：约 4 tokens
    - 消息分隔符：约 3 tokens
    - 系统消息额外开销：约 4 tokens
    
    Args:
        messages: 消息列表（字典格式）
        model: 模型名称
        
    Returns:
        Token 数量
    """
    total = 0
    
    for msg in messages:
        role = msg.get("role", "")
        
        # 角色标记开销（约 4 tokens）
        total += 4
        
        # 系统消息额外开销
        if role == "system":
            total += 4
        
        # 内容
        content = msg.get("content", "")
        if isinstance(content, str):
            total += count_tokens(content, model)
        elif isinstance(content, list):
            # 多模态内容
            for item in content:
                if isinstance(item, dict):
                    if "text" in item:
                        total += count_tokens(item["text"], model)
                    elif "image_url" in item:
                        # 图片内容，使用默认估算
                        total += 85  # 基础图片开销
        
        # 思考内容（reasoning_content）
        reasoning = msg.get("reasoning_content", "")
        if reasoning:
            total += count_tokens(reasoning, model)
    
    # 消息格式开销（约 3 tokens）
    total += 3
    
    return total


def count_image_tokens(
    width: int,
    height: int,
    model: str = "default",
    detail: str = "auto"
) -> int:
    """
    估算图片的 Token 数量
    
    智谱 GLM-4V 系列计算规则：
    - 基础消耗：85 tokens
    - 分块计算：每 512x512 像素区块约 170 tokens
    - 计算公式：tokens = 85 + ceil(width/512) * ceil(height/512) * 170
    - 最大尺寸限制：4096x4096 像素
    
    Args:
        width: 图片宽度（像素）
        height: 图片高度（像素）
        model: 模型名称
        detail: 详细程度（"low", "high", "auto"）
        
    Returns:
        Token 数量
    """
    import math
    
    # 最大尺寸限制
    MAX_SIZE = 4096
    
    # 应用尺寸限制
    if width > MAX_SIZE or height > MAX_SIZE:
        scale = MAX_SIZE / max(width, height)
        width = int(width * scale)
        height = int(height * scale)
    
    # 基础消耗
    BASE_TOKENS = 85
    
    # 低详细度模式
    if detail == "low":
        return BASE_TOKENS
    
    # 高详细度模式或自动模式
    TILE_SIZE = 512
    TOKENS_PER_TILE = 170
    
    tiles_x = math.ceil(width / TILE_SIZE)
    tiles_y = math.ceil(height / TILE_SIZE)
    
    return BASE_TOKENS + tiles_x * tiles_y * TOKENS_PER_TILE


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
    "count_image_tokens",
    # 限制查询
    "get_model_context_limit",
    "get_model_output_limit",
    "get_available_context",
    # 常量
    "MODEL_CONTEXT_LIMITS",
    "MODEL_OUTPUT_LIMITS",
]
