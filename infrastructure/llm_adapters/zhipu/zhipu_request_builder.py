# Zhipu Request Builder
"""
智谱 GLM 请求体构建器

职责：
- 专注于构建符合智谱 API 规范的请求体
- 处理深度思考配置
- 处理工具调用配置
- 处理结构化输出配置
- 自动检测多模态内容并切换到视觉模型

API 文档参考：
- https://open.bigmodel.cn/dev/api
- https://docs.bigmodel.cn/cn/guide/models/vlm/glm-4.6v (GLM-4.6V 视觉模型)
- https://docs.bigmodel.cn/cn/guide/capabilities/thinking
"""

import logging
from typing import Any, Dict, List, Optional

from infrastructure.config.settings import (
    DEFAULT_MODEL,
    DEFAULT_ENABLE_THINKING,
)


# ============================================================
# 默认值（当 ModelRegistry 不可用时）
# ============================================================

_DEFAULT_MAX_TOKENS = 4096
_DEFAULT_TEMPERATURE = 0.7
_DEFAULT_THINKING_TEMPERATURE = 1.0


class ZhipuRequestBuilder:
    """
    智谱 GLM 请求体构建器
    
    负责构建符合智谱 API 规范的请求体，包括：
    - 基础对话请求
    - 深度思考配置
    - 工具调用配置
    - 结构化输出配置
    - 自动检测多模态内容并切换到视觉模型
    
    配置来源优先级：
    1. 方法参数（最高优先级）
    2. ModelRegistry（推荐，单一信息源）
    3. 硬编码回退常量（仅当 ModelRegistry 不可用时）
    """
    
    def __init__(self):
        """初始化请求构建器"""
        self._logger = logging.getLogger(__name__)
    
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
        # 规范化消息
        normalized_messages = self._normalize_messages(messages)
        
        # 检测是否包含图片，如果包含则自动切换到视觉模型
        has_images = self._contains_images(normalized_messages)
        actual_model = self._get_vision_model_if_needed(model, has_images)
        
        # 判断是否为视觉模型（优先从 ModelRegistry 获取）
        is_vision_model = self._is_vision_model(actual_model)
        
        if has_images:
            self._logger.info(f"Detected images in messages, using vision model: {actual_model}")
        
        # 基础请求体
        body: Dict[str, Any] = {
            "model": actual_model,
            "messages": normalized_messages,
            "stream": stream,
        }
        
        # 应用深度思考配置（从 ModelRegistry 获取模型特定配置）
        body = self._apply_thinking_config(
            body, thinking, max_tokens, temperature, is_vision_model, actual_model
        )
        
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
        
        # 记录请求体日志（调试用）
        self._logger.debug(
            f"Built request: model={actual_model}, thinking={thinking}, "
            f"max_tokens={body.get('max_tokens')}, is_vision={is_vision_model}"
        )
        
        return body
    
    def _contains_images(self, messages: List[Dict[str, Any]]) -> bool:
        """
        检测消息列表中是否包含图片
        
        Args:
            messages: 规范化后的消息列表
            
        Returns:
            是否包含图片
        """
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                for item in content:
                    if item.get("type") == "image_url":
                        return True
        return False
    
    def _is_vision_model(self, model: str) -> bool:
        """
        判断模型是否为视觉模型（从 ModelRegistry 获取）
        
        Args:
            model: 模型名称
            
        Returns:
            是否为视觉模型
        """
        try:
            from shared.model_registry import ModelRegistry
            model_id = f"zhipu:{model}"
            model_config = ModelRegistry.get_model(model_id)
            if model_config:
                return model_config.is_vision_model or model_config.supports_vision
        except Exception:
            pass
        return False
    
    def _get_vision_model_if_needed(self, model: str, has_images: bool) -> str:
        """
        如果消息包含图片且当前模型不支持视觉，则切换到对应的视觉模型
        
        Args:
            model: 当前模型名称
            has_images: 是否包含图片
            
        Returns:
            实际使用的模型名称
        """
        if not has_images:
            return model
        
        try:
            from shared.model_registry import ModelRegistry
            
            model_id = f"zhipu:{model}"
            model_config = ModelRegistry.get_model(model_id)
            
            if model_config:
                # 如果已经是视觉模型，无需切换
                if model_config.is_vision_model or model_config.supports_vision:
                    return model
                
                # 获取视觉回退模型
                if model_config.vision_fallback:
                    fallback_model = model_config.vision_fallback.split(":")[-1]
                    return fallback_model
        except Exception as e:
            self._logger.warning(f"ModelRegistry not available: {e}")
        
        # ModelRegistry 不可用时，返回原模型（可能导致 API 错误）
        self._logger.warning(f"Cannot determine vision model for {model}")
        return model
    
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
        temperature: Optional[float] = None,
        is_vision_model: bool = False,
        model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        应用深度思考配置
        
        优先从 ModelRegistry 获取模型特定的配置，
        如果 ModelRegistry 未初始化则使用默认值。
        
        深度思考模式特殊要求：
        - thinking.type = "enabled"
        - max_tokens 使用模型配置的 max_tokens_thinking
        - temperature 固定为 1.0
        
        Args:
            body: 请求体
            thinking: 是否启用深度思考
            max_tokens: 自定义 max_tokens
            temperature: 自定义 temperature
            is_vision_model: 是否为视觉模型（GLM-4.6V 系列）
            model_name: 模型名称（用于从 ModelRegistry 获取配置）
            
        Returns:
            更新后的请求体
        """
        # 尝试从 ModelRegistry 获取模型配置
        model_config = None
        if model_name:
            try:
                from shared.model_registry import ModelRegistry
                model_id = f"zhipu:{model_name}"
                model_config = ModelRegistry.get_model(model_id)
            except Exception:
                pass
        
        if thinking:
            # 深度思考模式
            body["thinking"] = {"type": "enabled"}
            
            if max_tokens:
                body["max_tokens"] = max_tokens
            elif model_config:
                body["max_tokens"] = model_config.max_tokens_thinking
            else:
                body["max_tokens"] = _DEFAULT_MAX_TOKENS
            
            # 深度思考模式 temperature 固定为 1.0
            body["temperature"] = model_config.thinking_temperature if model_config else _DEFAULT_THINKING_TEMPERATURE
        else:
            # 普通模式
            body["thinking"] = {"type": "disabled"}
            
            if max_tokens:
                body["max_tokens"] = max_tokens
            elif model_config:
                body["max_tokens"] = model_config.max_tokens_default
            else:
                body["max_tokens"] = _DEFAULT_MAX_TOKENS
            
            if temperature is not None:
                body["temperature"] = temperature
            elif model_config:
                body["temperature"] = model_config.default_temperature
            else:
                body["temperature"] = _DEFAULT_TEMPERATURE
        
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
