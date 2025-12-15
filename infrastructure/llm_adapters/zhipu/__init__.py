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
- GLM-4.6 模型：https://zhipu-ef7018ed.mintlify.app/cn/guide/models/text/glm-4.6
- 深度思考：https://zhipu-ef7018ed.mintlify.app/cn/guide/capabilities/thinking
- 流式输出：https://zhipu-ef7018ed.mintlify.app/cn/guide/capabilities/streaming
- 上下文缓存：https://zhipu-ef7018ed.mintlify.app/cn/guide/capabilities/cache

阶段三实现：
- zhipu_client.py
- zhipu_request_builder.py
- zhipu_response_parser.py
- zhipu_stream_handler.py
"""

# 阶段三实现后导出
# from infrastructure.llm_adapters.zhipu.zhipu_client import ZhipuClient

__all__ = [
    # 阶段三实现后导出
    # "ZhipuClient",
]
