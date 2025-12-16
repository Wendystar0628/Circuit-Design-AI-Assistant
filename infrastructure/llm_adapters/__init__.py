# LLM Adapters
"""
LLM 提供商适配器模块

设计说明：
- LLM 客户端是外部服务的适配器，按 DDD 原则属于基础设施层
- 封装与各 LLM 提供商 API 的交互细节，为领域层提供统一接口

目录结构：
- base_client.py: 客户端抽象基类，定义统一接口
- zhipu/: 智谱 GLM 适配器目录（当前版本实现）
  - zhipu_client.py: 智谱客户端主类
  - zhipu_request_builder.py: 请求体构建
  - zhipu_response_parser.py: 响应解析
  - zhipu_stream_handler.py: 流式处理

后续扩展：
- openai/: OpenAI 适配器目录
- claude/: Claude 适配器目录
- gemini/: Gemini 适配器目录
- qwen/: Qwen 适配器目录
- deepseek/: DeepSeek 适配器目录

使用示例：
    from infrastructure.llm_adapters import ZhipuClient, create_zhipu_client
    
    # 创建智谱客户端
    client = create_zhipu_client()
    
    # 非流式调用
    response = client.chat(messages=[{"role": "user", "content": "Hello"}])
    
    # 流式调用
    async for chunk in client.chat_stream(messages):
        print(chunk.content, end="")
"""

from infrastructure.llm_adapters.base_client import (
    BaseLLMClient,
    ModelInfo,
    ChatResponse,
    StreamChunk,
    LLMError,
    APIError,
    AuthError,
    RateLimitError,
    ContextOverflowError,
    ResponseParseError,
)

# 智谱 GLM 适配器
from infrastructure.llm_adapters.zhipu import (
    ZhipuClient,
    create_zhipu_client,
    ZHIPU_MODELS,
)

__all__ = [
    # 基类
    "BaseLLMClient",
    # 数据结构
    "ModelInfo",
    "ChatResponse",
    "StreamChunk",
    # 异常类型
    "LLMError",
    "APIError",
    "AuthError",
    "RateLimitError",
    "ContextOverflowError",
    "ResponseParseError",
    # 智谱客户端
    "ZhipuClient",
    "create_zhipu_client",
    "ZHIPU_MODELS",
]
