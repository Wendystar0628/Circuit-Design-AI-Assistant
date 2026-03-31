# Zhipu Model Configurations
"""
智谱 AI 模型配置

职责：
- 定义智谱厂商配置
- 定义智谱所有模型的详细配置

API 文档参考：
- https://open.bigmodel.cn/dev/api
- https://docs.bigmodel.cn/cn/guide/capabilities/thinking
- https://docs.bigmodel.cn/cn/guide/models/text/glm-5
"""

from shared.model_types import ModelConfig, ProviderConfig


# ============================================================
# 厂商配置
# ============================================================

ZHIPU_PROVIDER = ProviderConfig(
    id="zhipu",
    name="智谱 AI",
    display_name="智谱 AI (Zhipu)",
    base_url="https://open.bigmodel.cn/api/paas/v4",
    auth_header="Authorization",
    auth_prefix="Bearer",
    default_model="glm-5",
    supports_web_search=True,
    implemented=True,
    description="智谱 AI 提供的 GLM 系列大语言模型",
    website="https://www.zhipuai.cn/",
    docs_url="https://open.bigmodel.cn/dev/api",
)


# ============================================================
# 模型配置
# ============================================================

# GLM-5 - 纯文本旗舰模型，支持深度思考（744B 参数，28.5T 训练数据）
GLM_5 = ModelConfig(
    id="zhipu:glm-5",
    provider="zhipu",
    name="glm-5",
    display_name="GLM-5",
    
    # 能力
    supports_vision=False,
    supports_tools=True,
    supports_thinking=True,
    supports_web_search=True,
    supports_streaming=True,
    
    # Token 限制（参考智谱官方文档：200K 上下文，64K 最大输出）
    context_limit=200000,
    max_tokens_default=65536,     # 普通模式 64K 输出
    max_tokens_thinking=65536,    # 深度思考模式 64K 输出
    
    # 深度思考配置
    thinking_temperature=1.0,
    thinking_timeout=300,
    
    # 普通模式配置
    default_temperature=0.7,
    default_timeout=60,
    
    # 视觉回退：当消息包含图片时，自动切换到 GLM-4.6V
    vision_fallback="zhipu:glm-4.6v",
    is_vision_model=False,
    
    description="GLM-5 是智谱最新旗舰模型，744B 参数（28.5T 训练），支持 Agentic Coding、长程任务规划、工具协同和深度思考",
)

# GLM-4.6V - 视觉模型，支持深度思考
GLM_4_6V = ModelConfig(
    id="zhipu:glm-4.6v",
    provider="zhipu",
    name="glm-4.6v",
    display_name="GLM-4.6V",
    
    # 能力
    supports_vision=True,
    supports_tools=True,
    supports_thinking=True,
    supports_web_search=True,
    supports_streaming=True,
    
    # Token 限制（视觉模型限制较纯文本模型小）
    context_limit=128000,
    max_tokens_default=16384,     # 普通模式 16K 输出
    max_tokens_thinking=16384,    # 视觉模型深度思考 max_tokens 限制
    
    # 深度思考配置
    thinking_temperature=1.0,
    thinking_timeout=300,
    
    # 普通模式配置
    default_temperature=0.7,
    default_timeout=60,
    
    # 已经是视觉模型，无需回退
    vision_fallback=None,
    is_vision_model=True,
    
    description="GLM-4.6V 是智谱的多模态视觉模型，支持图像理解和深度思考",
)

# GLM-4.6V-Flash - 视觉模型快速版
GLM_4_6V_FLASH = ModelConfig(
    id="zhipu:glm-4.6v-flash",
    provider="zhipu",
    name="glm-4.6v-flash",
    display_name="GLM-4.6V Flash",
    
    # 能力
    supports_vision=True,
    supports_tools=True,
    supports_thinking=True,
    supports_web_search=True,
    supports_streaming=True,
    
    # Token 限制
    context_limit=128000,
    max_tokens_default=16384,     # 普通模式 16K 输出
    max_tokens_thinking=16384,    # 深度思考模式 16K 输出
    
    # 深度思考配置
    thinking_temperature=1.0,
    thinking_timeout=300,
    
    # 普通模式配置
    default_temperature=0.7,
    default_timeout=60,
    
    # 已经是视觉模型，无需回退
    vision_fallback=None,
    is_vision_model=True,
    
    description="GLM-4.6V Flash 是 GLM-4.6V 的快速版本，响应更快",
)


# ============================================================
# 模型列表
# ============================================================

ZHIPU_MODELS = [
    GLM_5,
    GLM_4_6V,
    GLM_4_6V_FLASH,
]


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ZHIPU_PROVIDER",
    "ZHIPU_MODELS",
    "GLM_5",
    "GLM_4_6V",
    "GLM_4_6V_FLASH",
]
