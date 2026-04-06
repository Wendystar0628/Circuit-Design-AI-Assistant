from shared.model_types import ModelConfig, ProviderConfig


QWEN_PROVIDER = ProviderConfig(
    id="qwen",
    name="通义千问",
    display_name="通义千问 (Qwen)",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    auth_header="Authorization",
    auth_prefix="Bearer",
    default_model="qwen-max",
    supports_web_search=False,
    implemented=True,
    description="阿里云 DashScope 兼容接口下的通义千问对话模型",
    website="https://tongyi.aliyun.com/",
    docs_url="https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope",
)


QWEN_MAX = ModelConfig(
    id="qwen:qwen-max",
    provider="qwen",
    name="qwen-max",
    display_name="Qwen Max",
    supports_vision=False,
    supports_tools=True,
    supports_thinking=False,
    supports_web_search=False,
    supports_streaming=True,
    context_limit=32000,
    max_tokens_default=8192,
    max_tokens_thinking=8192,
    thinking_temperature=1.0,
    thinking_timeout=300,
    default_temperature=0.7,
    default_timeout=60,
    vision_fallback=None,
    is_vision_model=False,
    description="千问旗舰对话模型，适合通用复杂任务",
)

QWEN_PLUS = ModelConfig(
    id="qwen:qwen-plus",
    provider="qwen",
    name="qwen-plus",
    display_name="Qwen Plus",
    supports_vision=False,
    supports_tools=True,
    supports_thinking=False,
    supports_web_search=False,
    supports_streaming=True,
    context_limit=128000,
    max_tokens_default=8192,
    max_tokens_thinking=8192,
    thinking_temperature=1.0,
    thinking_timeout=300,
    default_temperature=0.7,
    default_timeout=60,
    vision_fallback=None,
    is_vision_model=False,
    description="千问增强模型，提供更长上下文与稳定响应",
)

QWEN_TURBO = ModelConfig(
    id="qwen:qwen-turbo",
    provider="qwen",
    name="qwen-turbo",
    display_name="Qwen Turbo",
    supports_vision=False,
    supports_tools=True,
    supports_thinking=False,
    supports_web_search=False,
    supports_streaming=True,
    context_limit=1000000,
    max_tokens_default=8192,
    max_tokens_thinking=8192,
    thinking_temperature=1.0,
    thinking_timeout=300,
    default_temperature=0.7,
    default_timeout=60,
    vision_fallback=None,
    is_vision_model=False,
    description="千问高吞吐模型，适合快速响应场景",
)


QWEN_MODELS = [
    QWEN_MAX,
    QWEN_PLUS,
    QWEN_TURBO,
]


__all__ = [
    "QWEN_PROVIDER",
    "QWEN_MODELS",
    "QWEN_MAX",
    "QWEN_PLUS",
    "QWEN_TURBO",
]
