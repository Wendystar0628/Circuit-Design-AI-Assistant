# Zhipu Stream Handler
"""智谱 GLM 流式输出处理器。

职责边界：
- 纯粹从一个 httpx 流式响应读取 SSE 行并增量解析为 ``StreamChunk``。
- **不感知取消语义**。上层通过 ``asyncio.Task.cancel()`` 取消拥有
  流消费过程的任务；``CancelledError`` 从当前 await 点沿调用栈传播，
  本层不捕获、不转换，也不通过 watcher/``response.aclose()`` 建立
  额外取消通道。
- 只有服务端明确发送 ``[DONE]`` 或带 ``finish_reason`` 的终止块才
  算协议正常完成；底层字节流提前 EOF 会抛解析异常。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from infrastructure.llm_adapters.base_client import ResponseParseError, StreamChunk
from infrastructure.llm_adapters.zhipu.zhipu_response_parser import ZhipuResponseParser


@dataclass
class StreamState:
    """流式输出累积状态。"""

    content_buffer: str = ""
    reasoning_buffer: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    chunk_count: int = 0
    total_content_length: int = 0
    total_reasoning_length: int = 0
    is_finished: bool = False
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None


class ZhipuStreamHandler:
    """智谱 GLM 流式输出处理器。"""

    def __init__(self):
        self._logger = logging.getLogger(__name__)
        self._parser = ZhipuResponseParser()

    async def iterate_response(self, response) -> AsyncIterator[StreamChunk]:
        """迭代 httpx 流式响应，累积 SSE 行并产出 ``StreamChunk``。

        异常不在本地吞：
        - ``CancelledError`` 由拥有任务的调用者发起并继续向上传播。
        - HTTP、SSE 解析错误和 premature EOF 全部向上冒泡。
        """
        state = StreamState()
        buffer = ""
        async for chunk in response.aiter_text():
            buffer += chunk
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

        # 字节流耗尽不等于 SSE 协议正常结束。若服务端既没有发送
        # [DONE]，也没有给出 finish_reason，则这是 premature EOF。
        if not state.is_finished:
            raise ResponseParseError(
                "Zhipu stream ended before a terminal frame"
            )

    def _process_line(
        self,
        line: str,
        state: StreamState,
    ) -> Optional[StreamChunk]:
        """解析单行 SSE 数据并更新累积状态。"""
        chunk = self._parser.parse_stream_line(line)
        if chunk is None:
            return None

        state.chunk_count += 1

        if chunk.content:
            state.content_buffer += chunk.content
            state.total_content_length += len(chunk.content)

        if chunk.reasoning_content:
            state.reasoning_buffer += chunk.reasoning_content
            state.total_reasoning_length += len(chunk.reasoning_content)

        delta_tool_calls = getattr(chunk, "_delta_tool_calls", None)
        if delta_tool_calls:
            self._accumulate_tool_calls(delta_tool_calls, state)

        if chunk.is_finished:
            state.is_finished = True
            state.finish_reason = chunk.finish_reason
            if chunk.finish_reason == "tool_calls" and state.tool_calls:
                chunk.tool_calls = self._finalize_tool_calls(state)

        if chunk.usage:
            state.usage = chunk.usage

        return chunk

    def _accumulate_tool_calls(
        self,
        delta_tool_calls: List[Dict[str, Any]],
        state: StreamState,
    ) -> None:
        """按 ``index`` 累积流式工具调用增量。

        SSE 流式工具调用协议（智谱 / OpenAI 兼容）：
        - 首次出现某 index 时 chunk 携带 ``id`` 和 ``function.name``。
        - 后续 chunk 携带 ``function.arguments`` 字符串片段。
        - 必须按 index 跨 chunk 拼接，最终在 ``finish_reason=tool_calls``
          时打包为完整工具调用。
        """
        for delta_tc in delta_tool_calls:
            index = delta_tc.get("index", 0)
            while len(state.tool_calls) <= index:
                state.tool_calls.append({
                    "id": "",
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                })

            tc = state.tool_calls[index]
            if delta_tc.get("id"):
                tc["id"] = delta_tc["id"]
            if delta_tc.get("type"):
                tc["type"] = delta_tc["type"]
            delta_func = delta_tc.get("function", {})
            if delta_func.get("name"):
                tc["function"]["name"] = delta_func["name"]
            if delta_func.get("arguments"):
                tc["function"]["arguments"] += delta_func["arguments"]

    def _finalize_tool_calls(
        self,
        state: StreamState,
    ) -> List[Dict[str, Any]]:
        """把累积好的 tool_calls 中 ``arguments`` 的 JSON 字符串解析为 dict。"""
        import json

        finalized: List[Dict[str, Any]] = []
        for tc in state.tool_calls:
            finalized_tc = {
                "id": tc["id"],
                "type": tc["type"],
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                },
            }
            args_str = tc["function"]["arguments"]
            if args_str:
                try:
                    finalized_tc["function"]["arguments"] = json.loads(args_str)
                except json.JSONDecodeError:
                    self._logger.warning(
                        f"Failed to parse tool call arguments for "
                        f"{tc['function']['name']}: {args_str[:100]}"
                    )
                    finalized_tc["function"]["arguments"] = args_str
            finalized.append(finalized_tc)

        return finalized


__all__ = [
    "ZhipuStreamHandler",
    "StreamState",
]
