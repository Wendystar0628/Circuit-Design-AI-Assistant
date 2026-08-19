from shared.model_types import ModelConfig, ProviderConfig


DEEPSEEK_PROVIDER = ProviderConfig(
    id="deepseek",
    name="DeepSeek",
    display_name="DeepSeek",
    base_url="https://api.deepseek.com",
    auth_header="Authorization",
    auth_prefix="Bearer",
    default_model="deepseek-v4-flash",
    supports_web_search=False,
    implemented=True,
    description="DeepSeek 提供的对话与推理模型",
    website="https://www.deepseek.com/",
    docs_url="https://api-docs.deepseek.com/",
)


# ============================================================
# DeepSeek V4 系列（当前主力模型）
# ============================================================

DEEPSEEK_V4_FLASH = ModelConfig(
    id="deepseek:deepseek-v4-flash",
    provider="deepseek",
    name="deepseek-v4-flash",
    display_name="DeepSeek V4 Flash",
    supports_vision=False,
    supports_tools=True,
    supports_thinking=True,
    supports_web_search=False,
    supports_streaming=True,
    context_limit=128000,
    max_tokens_default=64000,
    max_tokens_thinking=64000,
    thinking_temperature=1.0,
    thinking_timeout=300,
    reasoning_effort="high",
    default_temperature=0.7,
    default_timeout=60,
    vision_fallback=None,
    is_vision_model=False,
    description="DeepSeek V4 Flash — 主力快速模型，支持 thinking 模式切换",
)

DEEPSEEK_V4_PRO = ModelConfig(
    id="deepseek:deepseek-v4-pro",
    provider="deepseek",
    name="deepseek-v4-pro",
    display_name="DeepSeek V4 Pro",
    supports_vision=False,
    supports_tools=True,
    supports_thinking=True,
    supports_web_search=False,
    supports_streaming=True,
    context_limit=128000,
    max_tokens_default=64000,
    max_tokens_thinking=64000,
    thinking_temperature=1.0,
    thinking_timeout=300,
    reasoning_effort="high",
    default_temperature=0.7,
    default_timeout=60,
    vision_fallback=None,
    is_vision_model=False,
    description="DeepSeek V4 Pro — 旗舰专业模型，适合复杂分析与长链路思考任务",
)


# ============================================================
# 旧版模型（将于 2026/07/24 停止服务，保留以支持向后兼容）
# ============================================================

DEEPSEEK_CHAT = ModelConfig(
    id="deepseek:deepseek-chat",
    provider="deepseek",
    name="deepseek-chat",
    display_name="DeepSeek Chat (即将废弃)",
    supports_vision=False,
    supports_tools=True,
    supports_thinking=True,
    supports_web_search=False,
    supports_streaming=True,
    context_limit=128000,
    max_tokens_default=64000,
    max_tokens_thinking=64000,
    thinking_temperature=1.0,
    thinking_timeout=300,
    default_temperature=0.7,
    default_timeout=60,
    vision_fallback=None,
    is_vision_model=False,
    deprecated=True,
    description="[已废弃] DeepSeek 通用对话模型，将于 2026/07/24 停止服务。请迁移到 deepseek-v4-flash",
)

DEEPSEEK_REASONER = ModelConfig(
    id="deepseek:deepseek-reasoner",
    provider="deepseek",
    name="deepseek-reasoner",
    display_name="DeepSeek Reasoner (即将废弃)",
    supports_vision=False,
    supports_tools=True,
    supports_thinking=True,
    supports_web_search=False,
    supports_streaming=True,
    context_limit=128000,
    max_tokens_default=64000,
    max_tokens_thinking=64000,
    thinking_temperature=1.0,
    thinking_timeout=300,
    default_temperature=0.7,
    default_timeout=60,
    vision_fallback=None,
    is_vision_model=False,
    deprecated=True,
    description="[已废弃] DeepSeek 推理模型，将于 2026/07/24 停止服务。请迁移到 deepseek-v4-pro 或 deepseek-v4-flash（thinking 模式）",
)


DEEPSEEK_MODELS = [
    # V4 系列（推荐使用）
    DEEPSEEK_V4_FLASH,
    DEEPSEEK_V4_PRO,
    # 旧版模型（将于 2026/07/24 停止服务）
    DEEPSEEK_CHAT,
    DEEPSEEK_REASONER,
]


__all__ = [
    "DEEPSEEK_PROVIDER",
    "DEEPSEEK_MODELS",
    "DEEPSEEK_V4_FLASH",
    "DEEPSEEK_V4_PRO",
    "DEEPSEEK_CHAT",
    "DEEPSEEK_REASONER",
]
