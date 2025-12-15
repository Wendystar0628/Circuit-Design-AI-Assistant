# Base LLM Client Interface
"""
LLM 客户端基类接口

职责：
- 定义所有 LLM 客户端的统一接口
- 提供通用属性和异常类型
- 确保调用方只依赖抽象接口，不依赖具体实现

设计原则：
- 契约式设计：所有子类必须实现基类定义的抽象方法
- 返回值类型和异常类型保持一致，便于调用方统一处理
- 新增 LLM 提供商只需实现此接口，无需修改调用方代码

使用示例：
    from infrastructure.llm_adapters.base_client import BaseLLMClient
    
    class ZhipuClient(BaseLLMClient):
        def chat(self, messages, **kwargs):
            # 实现智谱 API 调用
            pass
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional


# ============================================================
# 异常类型定义
# ============================================================

class LLMError(Exception):
    """LLM 客户端基础异常"""
    pass


class APIError(LLMError):
    """API 调用错误"""
    
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class AuthError(LLMError):
    """认证错误（API Key 无效或权限不足）"""
    pass


class RateLimitError(LLMError):
    """速率限制错误"""
    
    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after


class ContextOverflowError(LLMError):
    """上下文溢出错误"""
    
    def __init__(self, message: str, max_tokens: Optional[int] = None):
        super().__init__(message)
        self.max_tokens = max_tokens


class ResponseParseError(LLMError):
    """响应解析错误"""
    pass


# ============================================================
# 数据结构定义
# ============================================================

@dataclass
class ModelInfo:
    """模型信息"""
    name: str                          # 模型名称
    context_limit: int                 # 上下文限制（tokens）
    supports_vision: bool = False      # 是否支持图像输入
    supports_tools: bool = False       # 是否支持工具调用
    supports_thinking: bool = False    # 是否支持深度思考


@dataclass
class ChatResponse:
    """对话响应"""
    content: str                       # 最终回答内容
    reasoning_content: Optional[str] = None  # 思考过程（深度思考模式）
    tool_calls: Optional[List[Dict[str, Any]]] = None  # 工具调用
    usage: Optional[Dict[str, int]] = None  # token 使用统计
    finish_reason: Optional[str] = None  # 完成原因


@dataclass
class StreamChunk:
    """流式响应块"""
    content: Optional[str] = None      # 内容增量
    reasoning_content: Optional[str] = None  # 思考增量
    is_finished: bool = False          # 是否结束
    usage: Optional[Dict[str, int]] = None  # token 使用统计（最后一块）


# ============================================================
# 基类定义
# ============================================================

class BaseLLMClient(ABC):
    """
    LLM 客户端抽象基类
    
    所有 LLM 提供商的客户端都必须继承此类并实现抽象方法。
    调用方只依赖此基类定义的接口，不依赖具体实现。
    """

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 60,
    ):
        """
        初始化客户端
        
        Args:
            api_key: API 密钥
            base_url: API 端点（可选，使用默认端点）
            model: 模型名称（可选，使用默认模型）
            timeout: 超时秒数
        """
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    # ============================================================
    # 抽象方法（子类必须实现）
    # ============================================================

    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        streaming: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
        thinking: bool = False,
        **kwargs,
    ) -> ChatResponse:
        """
        发送对话请求（非流式）
        
        Args:
            messages: 消息列表
            model: 模型名称（可选，使用实例默认模型）
            streaming: 是否流式输出（此方法应为 False）
            tools: 工具定义列表
            thinking: 是否启用深度思考
            **kwargs: 其他参数
            
        Returns:
            ChatResponse: 对话响应
            
        Raises:
            APIError: API 调用错误
            AuthError: 认证错误
            RateLimitError: 速率限制
            ContextOverflowError: 上下文溢出
            ResponseParseError: 响应解析错误
        """
        pass

    @abstractmethod
    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        thinking: bool = False,
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
        pass

    @abstractmethod
    def get_model_info(self, model: Optional[str] = None) -> ModelInfo:
        """
        获取模型信息
        
        Args:
            model: 模型名称（可选，使用实例默认模型）
            
        Returns:
            ModelInfo: 模型信息
        """
        pass

    # ============================================================
    # 可选方法（子类可覆盖）
    # ============================================================

    def supports_vision(self, model: Optional[str] = None) -> bool:
        """是否支持图像输入"""
        info = self.get_model_info(model)
        return info.supports_vision

    def supports_tools(self, model: Optional[str] = None) -> bool:
        """是否支持工具调用"""
        info = self.get_model_info(model)
        return info.supports_tools

    def supports_thinking(self, model: Optional[str] = None) -> bool:
        """是否支持深度思考"""
        info = self.get_model_info(model)
        return info.supports_thinking

    def get_context_limit(self, model: Optional[str] = None) -> int:
        """获取上下文限制"""
        info = self.get_model_info(model)
        return info.context_limit


# ============================================================
# 模块导出
# ============================================================

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
]
