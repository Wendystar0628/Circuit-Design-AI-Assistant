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
                    
                    if chunk.is_finished:
                        break
            
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
        
        if chunk.is_finished:
            state.is_finished = True
        
        if chunk.usage:
            state.usage = chunk.usage
        
        return chunk
    
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
                        
                        if stream_chunk.is_finished:
                            return
            
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
) -> tuple[str, str, Optional[Dict[str, int]]]:
    """
    收集流式输出的完整内容
    
    Args:
        stream: StreamChunk 异步迭代器
        
    Returns:
        (content, reasoning_content, usage) 元组
    """
    content_parts = []
    reasoning_parts = []
    usage = None
    
    async for chunk in stream:
        if chunk.content:
            content_parts.append(chunk.content)
        if chunk.reasoning_content:
            reasoning_parts.append(chunk.reasoning_content)
        if chunk.usage:
            usage = chunk.usage
    
    return "".join(content_parts), "".join(reasoning_parts), usage


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ZhipuStreamHandler",
    "StreamState",
    "collect_stream",
]
