# Zhipu GLM Client
"""
智谱 GLM 客户端主类

职责：
- 协调请求构建、发送、响应解析
- 提供统一的对外接口
- 管理 httpx 异步客户端
- 与 ExternalServiceManager 集成

API 端点：https://open.bigmodel.cn/api/paas/v4/chat/completions
认证方式：HTTP Bearer Token（Authorization: Bearer YOUR_API_KEY）

SDK 选择说明：
- 本项目 Chat 客户端使用 httpx 直接调用 REST API，便于深度思考模式、视觉模型自动切换、
  ModelRegistry 集成、ExternalServiceManager 集成等自定义功能的实现
- zhipuai 官方 SDK 当前未使用，Chat 客户端直接通过 httpx 调用 REST API

API 文档参考：
- https://open.bigmodel.cn/dev/api
- https://docs.bigmodel.cn/cn/guide/models/text/glm-5
"""

import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from infrastructure.llm_adapters.base_client import (
    BaseLLMClient,
    ModelInfo,
    ChatResponse,
    StreamChunk,
    APIError,
    AuthError,
    RateLimitError,
    ContextOverflowError,
    ResponseParseError,
)
from infrastructure.llm_adapters.zhipu.zhipu_request_builder import ZhipuRequestBuilder
from infrastructure.llm_adapters.zhipu.zhipu_response_parser import ZhipuResponseParser
from infrastructure.llm_adapters.zhipu.zhipu_stream_handler import ZhipuStreamHandler
from infrastructure.llm_adapters.model_configs import ZHIPU_PROVIDER
from infrastructure.config.settings import (
    DEFAULT_TIMEOUT,
    DEFAULT_THINKING_TIMEOUT,
    DEFAULT_ENABLE_THINKING,
)


# ============================================================
# 默认值（当 ModelRegistry 不可用时）
# ============================================================

_DEFAULT_CONTEXT_LIMIT = 128_000


class ZhipuClient(BaseLLMClient):
    """
    智谱 GLM 客户端
    
    实现 BaseLLMClient 接口，提供智谱 GLM API 的访问能力。
    
    特性：
    - 支持深度思考模式（GLM-5）
    - 支持流式输出
    - 支持工具调用
    - 支持多模态输入（图像）
    - 使用 httpx 异步客户端
    
    使用示例：
        client = ZhipuClient(api_key="your_api_key")
        
        # 非流式调用
        response = client.chat(messages=[{"role": "user", "content": "Hello"}])
        
        # 流式调用
        async for chunk in client.chat_stream(messages):
            print(chunk.content, end="")
    """
    
    # API 端点
    CHAT_ENDPOINT = "/chat/completions"
    
    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        """
        初始化智谱客户端
        
        Args:
            api_key: 智谱 API 密钥
            base_url: API 端点（默认 https://open.bigmodel.cn/api/paas/v4）
            model: 默认模型名称（默认 glm-5）
            timeout: 普通请求超时秒数（默认 60）
        """
        super().__init__(
            api_key=api_key,
            base_url=base_url or ZHIPU_PROVIDER.base_url,
            model=model or ZHIPU_PROVIDER.default_model,
            timeout=timeout,
        )
        
        self._logger = logging.getLogger(__name__)
        
        # 初始化协作模块
        self._request_builder = ZhipuRequestBuilder()
        self._response_parser = ZhipuResponseParser()
        self._stream_handler = ZhipuStreamHandler()
        
        # httpx 客户端（延迟初始化）
        self._sync_client: Optional[httpx.Client] = None
    
    # ============================================================
    # httpx 客户端管理
    # ============================================================
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
    
    def _create_async_client(self) -> httpx.AsyncClient:
        """获取异步 httpx 客户端（按请求创建）"""
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._get_headers(),
            timeout=httpx.Timeout(self.timeout, connect=10.0),
        )
    
    def _get_sync_client(self) -> httpx.Client:
        """获取同步 httpx 客户端（延迟初始化）"""
        if self._sync_client is None:
            self._sync_client = httpx.Client(
                base_url=self.base_url,
                headers=self._get_headers(),
                timeout=httpx.Timeout(self.timeout, connect=10.0),
            )
        return self._sync_client
    
    async def close(self) -> None:
        """关闭客户端连接"""
        if self._sync_client:
            self._sync_client.close()
            self._sync_client = None
    
    def __del__(self):
        """析构时关闭同步客户端"""
        if self._sync_client:
            try:
                self._sync_client.close()
            except Exception:
                pass
    
    # ============================================================
    # 核心方法实现
    # ============================================================
    
    def chat(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        streaming: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
        thinking: bool = DEFAULT_ENABLE_THINKING,
        **kwargs,
    ) -> ChatResponse:
        """
        发送对话请求（非流式，同步）
        
        Args:
            messages: 消息列表
            model: 模型名称（可选，使用实例默认模型）
            streaming: 是否流式输出（此方法应为 False）
            tools: 工具定义列表
            thinking: 是否启用深度思考
            **kwargs: 其他参数
            
        Returns:
            ChatResponse: 对话响应
        """
        use_model = model or self.model
        
        # 构建请求体
        request_body = self._request_builder.build_chat_request(
            messages=messages,
            model=use_model,
            stream=False,
            thinking=thinking,
            tools=tools,
            **kwargs
        )
        
        # 确定超时时间
        timeout = DEFAULT_THINKING_TIMEOUT if thinking else self.timeout
        
        # 发送请求
        client = self._get_sync_client()
        
        # 记录请求体（调试用，不记录敏感信息）
        self._logger.debug(
            f"Sending request: model={request_body.get('model')}, "
            f"thinking={request_body.get('thinking')}, "
            f"max_tokens={request_body.get('max_tokens')}, "
            f"stream={request_body.get('stream')}"
        )
        
        try:
            response = client.post(
                self.CHAT_ENDPOINT,
                json=request_body,
                timeout=timeout,
            )
            
            # 检查 HTTP 状态码
            if response.status_code != 200:
                # 记录详细错误信息
                self._logger.error(
                    f"API error: status={response.status_code}, "
                    f"model={request_body.get('model')}, "
                    f"thinking={request_body.get('thinking')}, "
                    f"response={response.text[:500]}"
                )
                self._response_parser.handle_http_error(
                    response.status_code,
                    response.text
                )
            
            # 解析响应
            return self._response_parser.parse_response(response.json())
            
        except httpx.TimeoutException as e:
            self._logger.error(f"Request timeout: {e}")
            raise APIError(f"Request timeout: {e}")
        except httpx.RequestError as e:
            self._logger.error(f"Request error: {e}")
            raise APIError(f"Request error: {e}")
    
    async def chat_async(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        thinking: bool = DEFAULT_ENABLE_THINKING,
        **kwargs,
    ) -> ChatResponse:
        """
        发送对话请求（非流式，异步）
        
        Args:
            messages: 消息列表
            model: 模型名称
            tools: 工具定义列表
            thinking: 是否启用深度思考
            **kwargs: 其他参数
            
        Returns:
            ChatResponse: 对话响应
        """
        use_model = model or self.model
        
        # 构建请求体
        request_body = self._request_builder.build_chat_request(
            messages=messages,
            model=use_model,
            stream=False,
            thinking=thinking,
            tools=tools,
            **kwargs
        )
        
        # 确定超时时间
        timeout = DEFAULT_THINKING_TIMEOUT if thinking else self.timeout
        
        # 发送请求
        try:
            async with self._create_async_client() as client:
                response = await client.post(
                    self.CHAT_ENDPOINT,
                    json=request_body,
                    timeout=timeout,
                )
            
                # 检查 HTTP 状态码
                if response.status_code != 200:
                    self._response_parser.handle_http_error(
                        response.status_code,
                        response.text
                    )
                
                # 解析响应
                return self._response_parser.parse_response(response.json())
            
        except httpx.TimeoutException as e:
            self._logger.error(f"Request timeout: {e}")
            raise APIError(f"Request timeout: {e}")
        except httpx.RequestError as e:
            self._logger.error(f"Request error: {e}")
            raise APIError(f"Request error: {e}")

    
    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        thinking: bool = DEFAULT_ENABLE_THINKING,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """
        流式对话（异步生成器）
        
        Args:
            messages: 消息列表
            model: 模型名称
            tools: 工具定义列表
            thinking: 是否启用深度思考
            **kwargs: 其他参数
            
        Yields:
            StreamChunk: 流式响应块
        """
        stop_requested = kwargs.pop("stop_requested", None)
        use_model = model or self.model
        
        # 构建请求体
        request_body = self._request_builder.build_chat_request(
            messages=messages,
            model=use_model,
            stream=True,
            thinking=thinking,
            tools=tools,
            **kwargs
        )
        
        # 确定超时时间（流式请求使用更长的超时）
        timeout = DEFAULT_THINKING_TIMEOUT if thinking else self.timeout
        
        # 记录请求体（调试用）
        self._logger.debug(
            f"Sending stream request: model={request_body.get('model')}, "
            f"thinking={request_body.get('thinking')}, "
            f"max_tokens={request_body.get('max_tokens')}"
        )
        
        # 使用显式的响应对象管理，确保在生成器关闭时正确清理
        try:
            async with self._create_async_client() as client:
                async with client.stream(
                    "POST",
                    self.CHAT_ENDPOINT,
                    json=request_body,
                ) as response:
                    # 检查 HTTP 状态码
                    if response.status_code != 200:
                        body = await response.aread()
                        # 记录详细错误信息
                        self._logger.error(
                            f"Stream API error: status={response.status_code}, "
                            f"model={request_body.get('model')}, "
                            f"thinking={request_body.get('thinking')}, "
                            f"response={body.decode('utf-8')[:500]}"
                        )
                        self._response_parser.handle_http_error(
                            response.status_code,
                            body.decode("utf-8")
                        )
                    
                    # 使用流式处理器处理响应
                    stream_iterator = self._stream_handler.create_stream_iterator(
                        response,
                        stop_requested=stop_requested,
                    )
                    async for chunk in stream_iterator:
                        yield chunk
                    
        except httpx.TimeoutException as e:
            self._logger.error(f"Stream timeout: {e}")
            raise APIError(f"Stream timeout: {e}")
        except httpx.RequestError as e:
            self._logger.error(f"Stream error: {e}")
            raise APIError(f"Stream error: {e}")
        except GeneratorExit:
            # 生成器被关闭（调用者调用了 aclose()）
            self._logger.debug("Stream generator closed by caller")
            raise
    
    def get_model_info(self, model: Optional[str] = None) -> ModelInfo:
        """
        获取模型信息（从 ModelRegistry 获取）
        
        Args:
            model: 模型名称（可选，使用实例默认模型）
            
        Returns:
            ModelInfo: 模型信息
        """
        use_model = model or self.model
        
        try:
            from shared.model_registry import ModelRegistry
            model_id = f"zhipu:{use_model}"
            model_config = ModelRegistry.get_model(model_id)
            
            if model_config:
                return ModelInfo(
                    name=model_config.name,
                    context_limit=model_config.context_limit,
                    supports_vision=model_config.supports_vision,
                    supports_tools=model_config.supports_tools,
                    supports_thinking=model_config.supports_thinking,
                )
        except Exception as e:
            self._logger.warning(f"ModelRegistry not available: {e}")
        
        # 返回基本默认信息
        return ModelInfo(
            name=use_model,
            context_limit=_DEFAULT_CONTEXT_LIMIT,
            supports_vision=False,
            supports_tools=True,
            supports_thinking=False,
        )
    
    # ============================================================
    # 便捷方法
    # ============================================================
    
    async def chat_with_thinking(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        **kwargs,
    ) -> ChatResponse:
        """
        启用深度思考的对话（便捷方法）
        
        Args:
            messages: 消息列表
            model: 模型名称
            **kwargs: 其他参数
            
        Returns:
            ChatResponse: 包含思考过程的响应
        """
        return await self.chat_async(
            messages=messages,
            model=model,
            thinking=True,
            **kwargs
        )
    
    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        model: Optional[str] = None,
        **kwargs,
    ) -> ChatResponse:
        """
        带工具调用的对话（便捷方法）
        
        Args:
            messages: 消息列表
            tools: 工具定义列表
            model: 模型名称
            **kwargs: 其他参数
            
        Returns:
            ChatResponse: 可能包含工具调用的响应
        """
        return await self.chat_async(
            messages=messages,
            model=model,
            tools=tools,
            thinking=False,  # 工具调用通常不需要深度思考
            **kwargs
        )
    
    async def chat_stream_with_thinking(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """
        启用深度思考的流式对话（便捷方法）
        
        Args:
            messages: 消息列表
            model: 模型名称
            **kwargs: 其他参数
            
        Yields:
            StreamChunk: 流式响应块（包含思考过程）
        """
        async for chunk in self.chat_stream(
            messages=messages,
            model=model,
            thinking=True,
            **kwargs
        ):
            yield chunk
    
    # ============================================================
    # ExternalServiceManager 集成
    # ============================================================
    
    async def call(
        self,
        request: Dict[str, Any],
        **kwargs
    ) -> ChatResponse:
        """
        ExternalServiceManager 调用入口
        
        此方法供 ExternalServiceManager.call_service() 使用，
        自动获得重试、熔断、统计能力。
        
        Args:
            request: 请求参数字典，包含：
                - messages: 消息列表
                - model: 模型名称（可选）
                - thinking: 是否启用深度思考（可选）
                - tools: 工具定义列表（可选）
                - stream: 是否流式（可选，此方法忽略）
            **kwargs: 其他参数
            
        Returns:
            ChatResponse: 对话响应
        """
        messages = request.get("messages", [])
        model = request.get("model")
        thinking = request.get("thinking", DEFAULT_ENABLE_THINKING)
        tools = request.get("tools")
        
        return await self.chat_async(
            messages=messages,
            model=model,
            thinking=thinking,
            tools=tools,
            **kwargs
        )
    
    async def call_stream(
        self,
        request: Dict[str, Any],
        **kwargs
    ) -> AsyncIterator[StreamChunk]:
        """
        ExternalServiceManager 流式调用入口
        
        Args:
            request: 请求参数字典
            **kwargs: 其他参数
            
        Yields:
            StreamChunk: 流式响应块
        """
        messages = request.get("messages", [])
        model = request.get("model")
        thinking = request.get("thinking", DEFAULT_ENABLE_THINKING)
        tools = request.get("tools")
        
        async for chunk in self.chat_stream(
            messages=messages,
            model=model,
            thinking=thinking,
            tools=tools,
            **kwargs
        ):
            yield chunk


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ZhipuClient",
]
