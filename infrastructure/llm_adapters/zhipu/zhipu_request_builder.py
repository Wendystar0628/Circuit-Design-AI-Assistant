# Zhipu Request Builder
"""
智谱 GLM 请求体构建器

职责：
- 专注于构建符合智谱 API 规范的请求体
- 处理深度思考配置
- 处理工具调用配置
- 处理结构化输出配置

API 文档参考：
- https://open.bigmodel.cn/dev/api
- https://zhipu-ef7018ed.mintlify.app/cn/guide/capabilities/thinking
"""

from typing import Any, Dict, List, Optional

from infrastructure.config.settings import (
    DEFAULT_MODEL,
    DEFAULT_ENABLE_THINKING,
    DEFAULT_THINKING_MAX_TOKENS,
    DEFAULT_THINKING_TEMPERATURE,
)


class ZhipuRequestBuilder:
    """
    智谱 GLM 请求体构建器
    
    负责构建符合智谱 API 规范的请求体，包括：
    - 基础对话请求
    - 深度思考配置
    - 工具调用配置
    - 结构化输出配置
    """
    
    # 默认配置
    DEFAULT_MAX_TOKENS = 4096          # 普通模式下的 max_tokens
    DEFAULT_TEMPERATURE = 0.7          # 普通模式下的 temperature
    
    def __init__(self):
        """初始化请求构建器"""
        pass
    
    def build_chat_request(
        self,
        messages: List[Dict[str, Any]],
        model: str = DEFAULT_MODEL,
        stream: bool = True,
        thinking: bool = DEFAULT_ENABLE_THINKING,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        response_format: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        构建对话请求体
        
        Args:
            messages: 消息列表
            model: 模型名称
            stream: 是否流式输出
            thinking: 是否启用深度思考
            tools: 工具定义列表
            max_tokens: 最大输出 tokens
            temperature: 温度参数
            response_format: 结构化输出格式
            **kwargs: 其他参数
            
        Returns:
            符合智谱 API 规范的请求体字典
        """
        # 基础请求体
        body: Dict[str, Any] = {
            "model": model,
            "messages": self._normalize_messages(messages),
            "stream": stream,
        }
        
        # 应用深度思考配置
        body = self._apply_thinking_config(body, thinking, max_tokens, temperature)
        
        # 应用工具配置
        if tools:
            body = self._apply_tools_config(body, tools)
        
        # 应用结构化输出配置
        if response_format:
            body = self._apply_structured_output(body, response_format)
        
        # 合并其他参数
        for key, value in kwargs.items():
            if value is not None and key not in body:
                body[key] = value
        
        return body
    
    def build_tool_request(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        model: str = DEFAULT_MODEL,
        stream: bool = True,
        thinking: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        构建工具调用请求体
        
        Args:
            messages: 消息列表
            tools: 工具定义列表
            model: 模型名称
            stream: 是否流式输出
            thinking: 是否启用深度思考
            **kwargs: 其他参数
            
        Returns:
            符合智谱 API 规范的请求体字典
        """
        return self.build_chat_request(
            messages=messages,
            model=model,
            stream=stream,
            thinking=thinking,
            tools=tools,
            **kwargs
        )
    
    def _normalize_messages(
        self,
        messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        规范化消息列表
        
        确保消息格式符合智谱 API 要求：
        - role: user/assistant/system/tool
        - content: 字符串或多模态内容列表
        
        Args:
            messages: 原始消息列表
            
        Returns:
            规范化后的消息列表
        """
        normalized = []
        
        for msg in messages:
            normalized_msg = {
                "role": msg.get("role", "user"),
            }
            
            # 处理 content
            content = msg.get("content", "")
            if isinstance(content, str):
                normalized_msg["content"] = content
            elif isinstance(content, list):
                # 多模态内容（图像等）
                normalized_msg["content"] = self._normalize_multimodal_content(content)
            else:
                normalized_msg["content"] = str(content)
            
            # 处理工具调用相关字段
            if "tool_calls" in msg:
                normalized_msg["tool_calls"] = msg["tool_calls"]
            
            if "tool_call_id" in msg:
                normalized_msg["tool_call_id"] = msg["tool_call_id"]
            
            if "name" in msg and msg.get("role") == "tool":
                normalized_msg["name"] = msg["name"]
            
            normalized.append(normalized_msg)
        
        return normalized
    
    def _normalize_multimodal_content(
        self,
        content: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        规范化多模态内容
        
        Args:
            content: 多模态内容列表
            
        Returns:
            规范化后的内容列表
        """
        normalized = []
        
        for item in content:
            item_type = item.get("type", "text")
            
            if item_type == "text":
                normalized.append({
                    "type": "text",
                    "text": item.get("text", "")
                })
            elif item_type == "image_url":
                # 图像 URL
                image_url = item.get("image_url", {})
                if isinstance(image_url, str):
                    image_url = {"url": image_url}
                normalized.append({
                    "type": "image_url",
                    "image_url": image_url
                })
            else:
                # 其他类型直接保留
                normalized.append(item)
        
        return normalized
    
    def _apply_thinking_config(
        self,
        body: Dict[str, Any],
        thinking: bool,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        应用深度思考配置
        
        深度思考模式特殊要求：
        - thinking.type = "enabled"
        - max_tokens 使用 thinking_max_tokens（默认 65536）
        - temperature 固定为 1.0
        
        Args:
            body: 请求体
            thinking: 是否启用深度思考
            max_tokens: 自定义 max_tokens
            temperature: 自定义 temperature
            
        Returns:
            更新后的请求体
        """
        if thinking:
            # 深度思考模式
            body["thinking"] = {"type": "enabled"}
            body["max_tokens"] = max_tokens or DEFAULT_THINKING_MAX_TOKENS
            body["temperature"] = DEFAULT_THINKING_TEMPERATURE  # 固定为 1.0
        else:
            # 普通模式
            body["thinking"] = {"type": "disabled"}
            body["max_tokens"] = max_tokens or self.DEFAULT_MAX_TOKENS
            body["temperature"] = temperature if temperature is not None else self.DEFAULT_TEMPERATURE
        
        return body
    
    def _apply_tools_config(
        self,
        body: Dict[str, Any],
        tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        应用工具调用配置
        
        Args:
            body: 请求体
            tools: 工具定义列表
            
        Returns:
            更新后的请求体
        """
        # 规范化工具定义
        normalized_tools = []
        
        for tool in tools:
            tool_type = tool.get("type", "function")
            
            if tool_type == "function":
                function_def = tool.get("function", tool)
                normalized_tools.append({
                    "type": "function",
                    "function": {
                        "name": function_def.get("name", ""),
                        "description": function_def.get("description", ""),
                        "parameters": function_def.get("parameters", {})
                    }
                })
            elif tool_type == "web_search":
                # 智谱内置联网搜索工具
                normalized_tools.append({
                    "type": "web_search",
                    "web_search": tool.get("web_search", {"enable": True})
                })
            else:
                # 其他类型直接保留
                normalized_tools.append(tool)
        
        body["tools"] = normalized_tools
        
        return body
    
    def _apply_structured_output(
        self,
        body: Dict[str, Any],
        response_format: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        应用结构化输出配置
        
        Args:
            body: 请求体
            response_format: 结构化输出格式
            
        Returns:
            更新后的请求体
        """
        format_type = response_format.get("type", "text")
        
        if format_type == "json_object":
            body["response_format"] = {"type": "json_object"}
        elif format_type == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": response_format.get("json_schema", {})
            }
        else:
            body["response_format"] = {"type": "text"}
        
        return body


# ============================================================
# 模块导出
# ============================================================

__all__ = ["ZhipuRequestBuilder"]
