from shared.model_types import ModelConfig, ProviderConfig


DEEPSEEK_PROVIDER = ProviderConfig(
    id="deepseek",
    name="DeepSeek",
    display_name="DeepSeek",
    base_url="https://api.deepseek.com/v1",
    auth_header="Authorization",
    auth_prefix="Bearer",
    default_model="deepseek-chat",
    supports_web_search=False,
    implemented=True,
    description="DeepSeek 提供的对话与推理模型",
    website="https://www.deepseek.com/",
    docs_url="https://api-docs.deepseek.com/",
)


DEEPSEEK_CHAT = ModelConfig(
    id="deepseek:deepseek-chat",
    provider="deepseek",
    name="deepseek-chat",
    display_name="DeepSeek Chat",
    supports_vision=False,
    supports_tools=True,
    supports_thinking=False,
    supports_web_search=False,
    supports_streaming=True,
    context_limit=64000,
    max_tokens_default=8192,
    max_tokens_thinking=8192,
    thinking_temperature=1.0,
    thinking_timeout=300,
    default_temperature=0.7,
    default_timeout=60,
    vision_fallback=None,
    is_vision_model=False,
    description="DeepSeek 通用对话模型，支持工具调用与流式输出",
)

DEEPSEEK_REASONER = ModelConfig(
    id="deepseek:deepseek-reasoner",
    provider="deepseek",
    name="deepseek-reasoner",
    display_name="DeepSeek Reasoner",
    supports_vision=False,
    supports_tools=True,
    supports_thinking=True,
    supports_web_search=False,
    supports_streaming=True,
    context_limit=64000,
    max_tokens_default=8192,
    max_tokens_thinking=8192,
    thinking_temperature=1.0,
    thinking_timeout=300,
    default_temperature=0.7,
    default_timeout=60,
    vision_fallback=None,
    is_vision_model=False,
    description="DeepSeek 推理模型，适合复杂分析与长链路思考任务",
)


DEEPSEEK_MODELS = [
    DEEPSEEK_CHAT,
    DEEPSEEK_REASONER,
]


__all__ = [
    "DEEPSEEK_PROVIDER",
    "DEEPSEEK_MODELS",
    "DEEPSEEK_CHAT",
    "DEEPSEEK_REASONER",
]
