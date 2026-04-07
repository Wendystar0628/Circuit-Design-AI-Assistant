from shared.model_types import ModelConfig, ProviderConfig


QWEN_PROVIDER = ProviderConfig(
    id="qwen",
    name="通义千问",
    display_name="通义千问 (Qwen)",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    auth_header="Authorization",
    auth_prefix="Bearer",
    default_model="qwen3-max",
    supports_web_search=True,
    implemented=True,
    description="阿里云 DashScope 兼容接口下的通义千问对话模型",
    website="https://tongyi.aliyun.com/",
    docs_url="https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope",
)


QWEN_3_6_PLUS = ModelConfig(
    id="qwen:qwen3.6-plus",
    provider="qwen",
    name="qwen3.6-plus",
    display_name="Qwen3.6-Plus",
    supports_vision=True,
    supports_tools=True,
    supports_thinking=True,
    supports_web_search=True,
    supports_streaming=True,
    context_limit=1_000_000,
    max_input_tokens_default=991808,
    max_input_tokens_thinking=983616,
    max_tokens_default=65536,
    max_tokens_thinking=65536,
    max_reasoning_tokens=81920,
    rpm=30000,
    tpm=5000000,
    thinking_temperature=1.0,
    thinking_timeout=300,
    default_temperature=0.7,
    default_timeout=60,
    vision_fallback=None,
    is_vision_model=False,
    description="Qwen3.6-Plus 是当前千问主力原生多模态模型，支持 1M 上下文、官方输入上限、64K 输出、80K 思维链与图像输入",
)

QWEN_3_MAX = ModelConfig(
    id="qwen:qwen3-max",
    provider="qwen",
    name="qwen3-max",
    display_name="Qwen3-Max",
    supports_vision=False,
    supports_tools=True,
    supports_thinking=True,
    supports_web_search=True,
    supports_streaming=True,
    context_limit=262144,
    max_input_tokens_default=258048,
    max_input_tokens_thinking=258048,
    max_tokens_default=65536,
    max_tokens_thinking=32768,
    max_reasoning_tokens=81920,
    rpm=30000,
    tpm=5000000,
    thinking_temperature=1.0,
    thinking_timeout=300,
    default_temperature=0.7,
    default_timeout=60,
    vision_fallback="qwen:qwen3.6-plus",
    is_vision_model=False,
    description="Qwen3-Max 是当前千问旗舰文本模型，支持 256K 上下文、官方输入上限、64K/32K 输出与 80K 思维链；遇到图像输入时回退到 Qwen3.6-Plus",
)

QWEN_3_VL_PLUS = ModelConfig(
    id="qwen:qwen3-vl-plus",
    provider="qwen",
    name="qwen3-vl-plus",
    display_name="Qwen3-VL-Plus",
    supports_vision=True,
    supports_tools=True,
    supports_thinking=True,
    supports_web_search=False,
    supports_streaming=True,
    context_limit=262144,
    max_input_tokens_default=260096,
    max_input_tokens_thinking=258048,
    max_tokens_default=32768,
    max_tokens_thinking=32768,
    max_reasoning_tokens=81920,
    rpm=3000,
    tpm=5000000,
    thinking_temperature=1.0,
    thinking_timeout=300,
    default_temperature=0.7,
    default_timeout=60,
    vision_fallback=None,
    is_vision_model=True,
    description="Qwen3-VL-Plus 是当前千问高性能视觉理解模型，支持 256K 上下文、官方输入上限、32K 输出、80K 思维链与图像输入",
)


QWEN_MODELS = [
    QWEN_3_6_PLUS,
    QWEN_3_MAX,
    QWEN_3_VL_PLUS,
]


__all__ = [
    "QWEN_PROVIDER",
    "QWEN_MODELS",
    "QWEN_3_6_PLUS",
    "QWEN_3_MAX",
    "QWEN_3_VL_PLUS",
]
