# Zhipu Response Parser
"""
智谱 GLM 响应解析器

职责：
- 解析智谱 API 的非流式响应
- 解析流式响应的 SSE 数据
- 提取思考过程、内容、工具调用等信息
- 统一错误处理

API 文档参考：
- https://open.bigmodel.cn/dev/api
- https://zhipu-ef7018ed.mintlify.app/cn/guide/capabilities/thinking
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from infrastructure.llm_adapters.base_client import (
    ChatResponse,
    StreamChunk,
    APIError,
    AuthError,
    RateLimitError,
    ContextOverflowError,
    ResponseParseError,
)


@dataclass
class ParsedChoice:
    """解析后的选择项"""
    index: int = 0
    content: str = ""
    reasoning_content: str = ""
    tool_calls: Optional[List[Dict[str, Any]]] = None
    finish_reason: Optional[str] = None


class ZhipuResponseParser:
    """
    智谱 GLM 响应解析器
    
    负责解析智谱 API 的响应数据，包括：
    - 非流式响应解析
    - 流式 SSE 数据解析
    - 错误响应处理
    """
    
    def __init__(self):
        """初始化响应解析器"""
        self._logger = logging.getLogger(__name__)
    
    # ============================================================
    # 非流式响应解析
    # ============================================================
    
    def parse_response(self, response_data: Dict[str, Any]) -> ChatResponse:
        """
        解析非流式响应
        
        Args:
            response_data: API 响应 JSON 数据
            
        Returns:
            ChatResponse 对象
            
        Raises:
            ResponseParseError: 解析失败
        """
        try:
            # 检查错误响应
            if "error" in response_data:
                self._handle_error_response(response_data)
            
            # 解析 choices
            choices = response_data.get("choices", [])
            if not choices:
                raise ResponseParseError("Response contains no choices")
            
            # 解析第一个 choice
            choice = choices[0]
            parsed = self._parse_choice(choice)
            
            # 解析 usage
            usage = self._parse_usage(response_data.get("usage", {}))
            
            return ChatResponse(
                content=parsed.content,
                reasoning_content=parsed.reasoning_content or None,
                tool_calls=parsed.tool_calls,
                usage=usage,
                finish_reason=parsed.finish_reason
            )
            
        except (APIError, AuthError, RateLimitError, ContextOverflowError):
            raise
        except Exception as e:
            self._logger.error(f"Failed to parse response: {e}")
            raise ResponseParseError(f"Failed to parse response: {e}")
    
    def _parse_choice(self, choice: Dict[str, Any]) -> ParsedChoice:
        """
        解析单个 choice
        
        Args:
            choice: choice 数据
            
        Returns:
            ParsedChoice 对象
        """
        message = choice.get("message", {})
        
        # 提取内容
        content = message.get("content", "")
        
        # 提取思考过程（深度思考模式）
        reasoning_content = message.get("reasoning_content", "")
        
        # 提取工具调用
        tool_calls = message.get("tool_calls")
        if tool_calls:
            tool_calls = self._normalize_tool_calls(tool_calls)
        
        return ParsedChoice(
            index=choice.get("index", 0),
            content=content,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason")
        )
    
    def _normalize_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        规范化工具调用数据
        
        Args:
            tool_calls: 原始工具调用列表
            
        Returns:
            规范化后的工具调用列表
        """
        normalized = []
        
        for tc in tool_calls:
            normalized_tc = {
                "id": tc.get("id", ""),
                "type": tc.get("type", "function"),
            }
            
            if tc.get("type") == "function" or "function" in tc:
                function = tc.get("function", {})
                normalized_tc["function"] = {
                    "name": function.get("name", ""),
                    "arguments": function.get("arguments", "{}")
                }
            
            normalized.append(normalized_tc)
        
        return normalized
    
    def _parse_usage(self, usage: Dict[str, Any]) -> Dict[str, int]:
        """
        解析 token 使用统计
        
        Args:
            usage: usage 数据
            
        Returns:
            统一格式的 usage 字典
        """
        return {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
    
    # ============================================================
    # 便捷方法（符合 3.4.2.4 规范）
    # ============================================================
    
    def parse_chat_response(self, response_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        解析非流式对话响应（便捷方法）
        
        Args:
            response_data: API 响应 JSON 数据
            
        Returns:
            解析后的字典，包含：
            - content: 最终回答内容
            - reasoning_content: 思考过程（仅深度思考启用时）
            - tool_calls: 工具调用（如有）
            - usage: token 使用统计
        """
        chat_response = self.parse_response(response_data)
        return {
            "content": chat_response.content,
            "reasoning_content": chat_response.reasoning_content or "",
            "tool_calls": chat_response.tool_calls or [],
            "usage": chat_response.usage or {},
        }
    
    def parse_usage_info(self, response_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        提取 Token 使用统计和缓存信息
        
        Args:
            response_data: API 响应 JSON 数据
            
        Returns:
            包含 token 使用统计的字典，包括：
            - prompt_tokens: 输入 tokens
            - completion_tokens: 输出 tokens
            - total_tokens: 总 tokens
            - cached_tokens: 缓存命中 tokens（如有）
            - cache_hit_rate: 缓存命中率（百分比）
            - reasoning_tokens: 思考 tokens（深度思考模式）
        """
        usage = response_data.get("usage", {})
        
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", 0)
        
        result = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
        
        # 提取缓存信息（如果有）
        cached_tokens = 0
        if "prompt_tokens_details" in usage:
            details = usage["prompt_tokens_details"]
            cached_tokens = details.get("cached_tokens", 0)
            result["cached_tokens"] = cached_tokens
            
            # 计算缓存命中率
            if prompt_tokens > 0:
                cache_hit_rate = (cached_tokens / prompt_tokens) * 100
                result["cache_hit_rate"] = round(cache_hit_rate, 2)
                
                # 记录缓存命中率日志
                if cached_tokens > 0:
                    self._logger.info(
                        f"Cache hit: {cached_tokens}/{prompt_tokens} tokens "
                        f"({cache_hit_rate:.1f}%)"
                    )
        
        # 提取思考 tokens（深度思考模式）
        if "completion_tokens_details" in usage:
            details = usage["completion_tokens_details"]
            result["reasoning_tokens"] = details.get("reasoning_tokens", 0)
        
        return result
    
    def parse_tool_calls(self, response_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        解析工具调用结果
        
        Args:
            response_data: API 响应 JSON 数据
            
        Returns:
            工具调用列表，每个元素包含：
            - id: 工具调用 ID
            - type: 工具类型
            - function: 函数信息（name, arguments）
        """
        choices = response_data.get("choices", [])
        if not choices:
            return []
        
        message = choices[0].get("message", {})
        tool_calls = message.get("tool_calls", [])
        
        if tool_calls:
            return self._normalize_tool_calls(tool_calls)
        
        return []
    
    def extract_reasoning_content(self, response_data: Dict[str, Any]) -> str:
        """
        提取深度思考内容
        
        Args:
            response_data: API 响应 JSON 数据
            
        Returns:
            思考过程字符串，如果没有则返回空字符串
        """
        choices = response_data.get("choices", [])
        if not choices:
            return ""
        
        message = choices[0].get("message", {})
        return message.get("reasoning_content", "")
    
    # ============================================================
    # 流式响应解析
    # ============================================================
    
    def parse_stream_line(self, line: str) -> Optional[StreamChunk]:
        """
        解析流式响应的单行 SSE 数据
        
        Args:
            line: SSE 数据行
            
        Returns:
            StreamChunk 对象，如果是非数据行则返回 None
        """
        # 跳过空行和注释
        line = line.strip()
        if not line or line.startswith(":"):
            return None
        
        # 解析 SSE 格式
        if not line.startswith("data:"):
            return None
        
        data_str = line[5:].strip()
        
        # 检查结束标记
        if data_str == "[DONE]":
            return StreamChunk(is_finished=True)
        
        try:
            data = json.loads(data_str)
            return self._parse_stream_data(data)
        except json.JSONDecodeError as e:
            self._logger.warning(f"Failed to parse stream data: {e}")
            return None
    
    def _parse_stream_data(self, data: Dict[str, Any]) -> StreamChunk:
        """
        解析流式数据块
        
        Args:
            data: 解析后的 JSON 数据
            
        Returns:
            StreamChunk 对象
        """
        # 检查错误
        if "error" in data:
            error = data["error"]
            error_msg = error.get("message", str(error))
            self._logger.error(f"Stream error: {error_msg}")
            return StreamChunk(is_finished=True)
        
        # 解析 choices
        choices = data.get("choices", [])
        if not choices:
            return StreamChunk()
        
        choice = choices[0]
        delta = choice.get("delta", {})
        
        # 提取增量内容
        content = delta.get("content")
        reasoning_content = delta.get("reasoning_content")
        
        # 检查是否结束
        finish_reason = choice.get("finish_reason")
        is_finished = finish_reason is not None
        
        # 解析 usage（最后一块可能包含）
        usage = None
        if "usage" in data:
            usage = self._parse_usage(data["usage"])
        
        return StreamChunk(
            content=content,
            reasoning_content=reasoning_content,
            is_finished=is_finished,
            usage=usage
        )
    
    # ============================================================
    # 错误处理
    # ============================================================
    
    def _handle_error_response(self, response_data: Dict[str, Any]) -> None:
        """
        处理错误响应
        
        Args:
            response_data: 包含错误的响应数据
            
        Raises:
            对应的异常类型
        """
        error = response_data.get("error", {})
        
        if isinstance(error, str):
            error = {"message": error}
        
        error_code = error.get("code", "")
        error_message = error.get("message", "Unknown error")
        
        # 根据错误码分类
        self._raise_typed_error(error_code, error_message)
    
    def handle_http_error(
        self,
        status_code: int,
        response_body: str
    ) -> None:
        """
        处理 HTTP 错误响应
        
        Args:
            status_code: HTTP 状态码
            response_body: 响应体
            
        Raises:
            对应的异常类型
        """
        # 尝试解析响应体
        error_message = response_body
        error_code = ""
        
        try:
            data = json.loads(response_body)
            if "error" in data:
                error = data["error"]
                if isinstance(error, dict):
                    error_message = error.get("message", response_body)
                    error_code = error.get("code", "")
                else:
                    error_message = str(error)
        except json.JSONDecodeError:
            pass
        
        # 根据状态码分类
        if status_code == 401:
            raise AuthError(f"Authentication failed: {error_message}")
        elif status_code == 403:
            raise AuthError(f"Permission denied: {error_message}")
        elif status_code == 429:
            raise RateLimitError(f"Rate limit exceeded: {error_message}")
        elif status_code == 400:
            # 检查是否是上下文溢出
            if "context" in error_message.lower() or "token" in error_message.lower():
                raise ContextOverflowError(f"Context overflow: {error_message}")
            raise APIError(f"Bad request: {error_message}", status_code)
        elif status_code >= 500:
            raise APIError(f"Server error: {error_message}", status_code)
        else:
            raise APIError(f"API error: {error_message}", status_code)
    
    def _raise_typed_error(self, error_code: str, error_message: str) -> None:
        """
        根据错误码抛出对应类型的异常
        
        Args:
            error_code: 错误码
            error_message: 错误消息
        """
        error_code_lower = error_code.lower()
        error_message_lower = error_message.lower()
        
        # 认证错误
        if "auth" in error_code_lower or "key" in error_code_lower:
            raise AuthError(error_message)
        
        # 速率限制
        if "rate" in error_code_lower or "limit" in error_code_lower:
            raise RateLimitError(error_message)
        
        # 上下文溢出
        if "context" in error_message_lower or "token" in error_message_lower:
            if "overflow" in error_message_lower or "exceed" in error_message_lower:
                raise ContextOverflowError(error_message)
        
        # 默认 API 错误
        raise APIError(error_message)


# ============================================================
# 模块导出
# ============================================================

__all__ = ["ZhipuResponseParser", "ParsedChoice"]
