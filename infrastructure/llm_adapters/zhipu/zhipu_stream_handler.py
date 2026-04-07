# Zhipu Stream Handler
"""
智谱 GLM 流式输出处理器

职责：
- 处理 SSE (Server-Sent Events) 流式响应
- 管理流式输出的状态和缓冲
- 提供异步生成器接口
- 处理流式传输中的错误和中断

API 文档参考：
- https://zhipu-ef7018ed.mintlify.app/cn/guide/capabilities/streaming
"""

import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from infrastructure.llm_adapters.base_client import StreamChunk
from infrastructure.llm_adapters.zhipu.zhipu_response_parser import ZhipuResponseParser


@dataclass
class StreamState:
    """流式输出状态"""
    # 累积内容
    content_buffer: str = ""
    reasoning_buffer: str = ""
    
    # 工具调用累积
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    current_tool_call: Optional[Dict[str, Any]] = None
    
    # 统计信息
    chunk_count: int = 0
    total_content_length: int = 0
    total_reasoning_length: int = 0
    
    # 状态标记
    is_finished: bool = False
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    
    # 错误信息
    error: Optional[str] = None


class ZhipuStreamHandler:
    """
    智谱 GLM 流式输出处理器
    
    负责处理智谱 API 的流式响应，包括：
    - SSE 数据流解析
    - 内容和思考过程的累积
    - 工具调用的增量解析
    - 流式状态管理
    """
    
    def __init__(self):
        """初始化流式处理器"""
        self._logger = logging.getLogger(__name__)
        self._parser = ZhipuResponseParser()
    
    async def handle_stream(
        self,
        response_lines: AsyncIterator[str]
    ) -> AsyncIterator[StreamChunk]:
        """
        处理流式响应
        
        Args:
            response_lines: 异步行迭代器（SSE 数据行）
            
        Yields:
            StreamChunk 对象
        """
        state = StreamState()
        
        try:
            async for line in response_lines:
                chunk = self._process_line(line, state)
                if chunk:
                    yield chunk
            
            # 确保发送结束标记
            if not state.is_finished:
                yield StreamChunk(
                    is_finished=True,
                    usage=state.usage
                )
                
        except Exception as e:
            self._logger.error(f"Stream handling error: {e}")
            state.error = str(e)
            yield StreamChunk(is_finished=True)
    
    def _process_line(
        self,
        line: str,
        state: StreamState
    ) -> Optional[StreamChunk]:
        """
        处理单行 SSE 数据
        
        Args:
            line: SSE 数据行
            state: 流式状态
            
        Returns:
            StreamChunk 对象，如果无有效数据则返回 None
        """
        chunk = self._parser.parse_stream_line(line)
        
        if chunk is None:
            return None
        
        # 更新状态
        state.chunk_count += 1
        
        if chunk.content:
            state.content_buffer += chunk.content
            state.total_content_length += len(chunk.content)
        
        if chunk.reasoning_content:
            state.reasoning_buffer += chunk.reasoning_content
            state.total_reasoning_length += len(chunk.reasoning_content)
        
        # 累积工具调用增量
        # _delta_tool_calls 是 ZhipuResponseParser 暂存的原始增量数据
        delta_tool_calls = getattr(chunk, '_delta_tool_calls', None)
        if delta_tool_calls:
            self._accumulate_tool_calls(delta_tool_calls, state)
        
        if chunk.is_finished:
            state.is_finished = True
            state.finish_reason = chunk.finish_reason
            
            # 如果 finish_reason 为 "tool_calls"，将累积完成的工具调用附加到此 chunk
            if chunk.finish_reason == "tool_calls" and state.tool_calls:
                chunk.tool_calls = self._finalize_tool_calls(state)
        
        if chunk.usage:
            state.usage = chunk.usage
        
        return chunk
    
    def _accumulate_tool_calls(
        self,
        delta_tool_calls: List[Dict[str, Any]],
        state: StreamState
    ) -> None:
        """
        累积流式工具调用增量数据
        
        智谱 API / OpenAI 流式工具调用格式：
        - delta.tool_calls 数组中每个元素包含 index（标识第几个并行调用）
        - 首次出现某 index 时携带 id 和 function.name
        - 后续 chunk 携带 function.arguments 增量字符串片段
        - 需要按 index 累积，跨 chunk 拼接 arguments
        
        Args:
            delta_tool_calls: 本次 chunk 中的工具调用增量数组
            state: 流式状态
        """
        for delta_tc in delta_tool_calls:
            index = delta_tc.get("index", 0)
            
            # 确保 state.tool_calls 列表有足够的槽位
            while len(state.tool_calls) <= index:
                state.tool_calls.append({
                    "id": "",
                    "type": "function",
                    "function": {
                        "name": "",
                        "arguments": ""
                    }
                })
            
            tc = state.tool_calls[index]
            
            # 累积 id（首个 chunk 携带）
            if delta_tc.get("id"):
                tc["id"] = delta_tc["id"]
            
            # 累积 type
            if delta_tc.get("type"):
                tc["type"] = delta_tc["type"]
            
            # 累积 function 信息
            delta_func = delta_tc.get("function", {})
            if delta_func.get("name"):
                tc["function"]["name"] = delta_func["name"]
            if delta_func.get("arguments"):
                tc["function"]["arguments"] += delta_func["arguments"]
    
    def _finalize_tool_calls(
        self,
        state: StreamState
    ) -> List[Dict[str, Any]]:
        """
        最终化累积的工具调用，解析 arguments JSON 字符串
        
        Args:
            state: 流式状态
            
        Returns:
            完整的工具调用列表，arguments 已从字符串解析为字典
        """
        import json
        
        finalized = []
        for tc in state.tool_calls:
            finalized_tc = {
                "id": tc["id"],
                "type": tc["type"],
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"]
                }
            }
            
            # 尝试将 arguments 字符串解析为字典
            args_str = tc["function"]["arguments"]
            if args_str:
                try:
                    finalized_tc["function"]["arguments"] = json.loads(args_str)
                except json.JSONDecodeError:
                    self._logger.warning(
                        f"Failed to parse tool call arguments for "
                        f"{tc['function']['name']}: {args_str[:100]}"
                    )
                    # 保留原始字符串，让上层处理
                    finalized_tc["function"]["arguments"] = args_str
            
            finalized.append(finalized_tc)
        
        return finalized
    
    def create_stream_iterator(
        self,
        response
    ) -> AsyncIterator[StreamChunk]:
        """
        从 httpx 响应创建流式迭代器
        
        Args:
            response: httpx.Response 对象（流式）
            
        Returns:
            异步 StreamChunk 迭代器
        """
        return self._iterate_response(response)
    
    async def _iterate_response(self, response) -> AsyncIterator[StreamChunk]:
        """
        迭代 httpx 流式响应
        
        Args:
            response: httpx.Response 对象
            
        Yields:
            StreamChunk 对象
        """
        state = StreamState()
        buffer = ""
        
        try:
            async for chunk in response.aiter_text():
                # 将数据添加到缓冲区
                buffer += chunk
                
                # 按行处理
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    
                    stream_chunk = self._process_line(line, state)
                    if stream_chunk:
                        yield stream_chunk
            
            # 处理剩余缓冲区
            if buffer.strip():
                stream_chunk = self._process_line(buffer, state)
                if stream_chunk:
                    yield stream_chunk
            
            # 确保发送结束标记
            if not state.is_finished:
                yield StreamChunk(
                    is_finished=True,
                    usage=state.usage
                )
                
        except Exception as e:
            self._logger.error(f"Stream iteration error: {e}")
            yield StreamChunk(is_finished=True)
    
    def get_accumulated_content(self, state: StreamState) -> str:
        """
        获取累积的内容
        
        Args:
            state: 流式状态
            
        Returns:
            累积的内容字符串
        """
        return state.content_buffer
    
    def get_accumulated_reasoning(self, state: StreamState) -> str:
        """
        获取累积的思考过程
        
        Args:
            state: 流式状态
            
        Returns:
            累积的思考过程字符串
        """
        return state.reasoning_buffer
    
    def get_stream_statistics(self, state: StreamState) -> Dict[str, Any]:
        """
        获取流式传输统计信息
        
        Args:
            state: 流式状态
            
        Returns:
            统计信息字典
        """
        return {
            "chunk_count": state.chunk_count,
            "total_content_length": state.total_content_length,
            "total_reasoning_length": state.total_reasoning_length,
            "is_finished": state.is_finished,
            "finish_reason": state.finish_reason,
            "has_error": state.error is not None,
            "error": state.error,
        }


# ============================================================
# 辅助函数
# ============================================================

async def collect_stream(
    stream: AsyncIterator[StreamChunk]
) -> tuple[str, str, Optional[Dict[str, int]], Optional[List[Dict[str, Any]]], Optional[str]]:
    """
    收集流式输出的完整内容
    
    Args:
        stream: StreamChunk 异步迭代器
        
    Returns:
        (content, reasoning_content, usage, tool_calls, finish_reason) 元组
        - tool_calls: 累积完成的工具调用列表，无工具调用时为 None
        - finish_reason: 完成原因（"stop" | "tool_calls" 等）
    """
    content_parts = []
    reasoning_parts = []
    usage = None
    tool_calls = None
    finish_reason = None
    
    async for chunk in stream:
        if chunk.content:
            content_parts.append(chunk.content)
        if chunk.reasoning_content:
            reasoning_parts.append(chunk.reasoning_content)
        if chunk.usage:
            usage = chunk.usage
        if chunk.tool_calls:
            tool_calls = chunk.tool_calls
        if chunk.finish_reason:
            finish_reason = chunk.finish_reason
    
    return "".join(content_parts), "".join(reasoning_parts), usage, tool_calls, finish_reason


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ZhipuStreamHandler",
    "StreamState",
    "collect_stream",
]
