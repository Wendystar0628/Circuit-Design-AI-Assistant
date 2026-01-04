# Zhipu GLM Adapter
"""
智谱 GLM 适配器模块

目录结构：
- zhipu_client.py: 客户端主类，协调各模块
- zhipu_request_builder.py: 请求体构建器
- zhipu_response_parser.py: 响应解析器
- zhipu_stream_handler.py: 流式输出处理器

SDK 选择说明：
- 本项目使用 httpx 直接调用 REST API
- 不依赖官方 SDK（zai 或 zhipuai），以减少依赖并保持灵活性

API 文档参考：
- API 文档：https://open.bigmodel.cn/dev/api
- GLM-4.7 模型：https://docs.bigmodel.cn/cn/guide/models/text/glm-4.7
- 深度思考：https://docs.bigmodel.cn/cn/guide/capabilities/thinking
- 流式输出：https://docs.bigmodel.cn/cn/guide/capabilities/streaming
- 上下文缓存：https://zhipu-ef7018ed.mintlify.app/cn/guide/capabilities/cache

使用示例：
    from infrastructure.llm_adapters.zhipu import ZhipuClient, create_zhipu_client
    
    # 方式一：直接创建
    client = ZhipuClient(api_key="your_api_key")
    
    # 方式二：使用工厂函数（自动从 ConfigManager 获取配置）
    client = create_zhipu_client()
    
    # 非流式调用
    response = client.chat(messages=[{"role": "user", "content": "Hello"}])
    print(response.content)
    
    # 流式调用
    async for chunk in client.chat_stream(messages):
        if chunk.content:
            print(chunk.content, end="")
"""

from infrastructure.llm_adapters.zhipu.zhipu_client import (
    ZhipuClient,
    create_zhipu_client,
)
from infrastructure.llm_adapters.zhipu.zhipu_request_builder import ZhipuRequestBuilder
from infrastructure.llm_adapters.zhipu.zhipu_response_parser import ZhipuResponseParser
from infrastructure.llm_adapters.zhipu.zhipu_stream_handler import (
    ZhipuStreamHandler,
    StreamState,
    collect_stream,
)

# 模型配置已迁移到 ModelRegistry
# 参见：shared/model_registry.py 和 infrastructure/llm_adapters/model_configs/

__all__ = [
    # 客户端主类和工厂函数
    "ZhipuClient",
    "create_zhipu_client",
    # 请求构建器（供高级用户使用）
    "ZhipuRequestBuilder",
    # 响应解析器（供高级用户使用）
    "ZhipuResponseParser",
    # 流式处理器（供高级用户使用）
    "ZhipuStreamHandler",
    "StreamState",
    "collect_stream",
]
