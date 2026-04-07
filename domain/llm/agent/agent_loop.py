# Agent Loop - ReAct 循环控制器
"""
ReAct 循环控制器

职责：
- 管理 LLM → 工具调用 → 结果回传 → 再次 LLM 的多轮交互循环
- 流式转发 LLM 响应给 UI
- 三阶段工具执行：prepare → execute → finalize
- 自动判断何时结束循环（LLM 不再调用工具时）

参考来源：
- pi-mono: packages/agent/src/agent-loop.ts

架构位置：
- 被 LLMExecutor.execute_agent() 调用
- 依赖 BaseLLMClient 进行 LLM 调用
- 依赖 ToolRegistry 查找和执行工具
- 通过回调函数通知 UI 层更新

使用示例：
    loop = AgentLoop(
        client=llm_client,
        registry=tool_registry,
        context=tool_context,
        model="glm-4-plus",
    )
    result = await loop.run(messages, on_event=my_callback)
"""

import json
import logging
import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union

from infrastructure.llm_adapters.base_client import BaseLLMClient
from domain.llm.agent.types import (
    ToolCallInfo,
    ToolContext,
    ToolResult,
    create_error_result,
)
from domain.llm.agent.tool_registry import ToolRegistry


# ============================================================
# 类型定义
# ============================================================

# 事件回调：(event_type: str, data: dict) -> None 或 awaitable
AgentEventCallback = Callable[[str, Dict[str, Any]], Union[None, Coroutine]]

# Agent 事件类型常量
EVENT_STREAM_CHUNK = "stream_chunk"          # LLM 流式文本块
EVENT_TOOL_START = "tool_execution_start"    # 工具开始执行
EVENT_TOOL_END = "tool_execution_end"        # 工具执行结束


@dataclass
class TurnResult:
    """单轮 LLM 响应的累积结果"""
    content: str = ""
    reasoning_content: str = ""
    tool_calls: Optional[List[Dict[str, Any]]] = None
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None


@dataclass
class AgentResult:
    """Agent 循环的最终结果"""
    content: str = ""
    reasoning_content: str = ""
    usage: Optional[Dict[str, int]] = None
    total_turns: int = 0
    tool_calls_count: int = 0
    is_error: bool = False
    error_message: str = ""


# ============================================================
# AgentLoop
# ============================================================

class AgentLoop:
    """
    ReAct 循环控制器

    对照 pi-mono agent-loop.ts 的 runLoop() 第 155-232 行。

    循环流程：
    1. 调用 LLM（带 tools 参数），流式输出
    2. 检查 finish_reason：
       - "stop" → 循环结束
       - "tool_calls" → 执行工具，回传结果，回到步骤 1
    3. 最大轮次保护（默认 15 轮）
    """

    MAX_TURNS = 15

    def __init__(
        self,
        client: BaseLLMClient,
        registry: ToolRegistry,
        context: ToolContext,
        model: str,
        thinking: bool = False,
        stop_requested: Optional[Callable[[], bool]] = None,
        max_turns: int = MAX_TURNS,
    ):
        """
        初始化 Agent 循环

        Args:
            client: LLM 客户端实例
            registry: 工具注册表（已注册所有工具）
            context: 工具执行上下文
            model: 模型名称
            thinking: 是否启用深度思考
            stop_requested: 停止检查函数
            max_turns: 最大循环轮次
        """
        self._client = client
        self._registry = registry
        self._context = context
        self._model = model
        self._thinking = thinking
        self._stop_requested = stop_requested
        self._max_turns = max_turns
        self._logger = logging.getLogger(__name__)

    async def run(
        self,
        messages: List[Dict[str, Any]],
        on_event: Optional[AgentEventCallback] = None,
    ) -> AgentResult:
        """
        执行 ReAct 循环

        对照 pi-mono agent-loop.ts runLoop() 第 155-232 行。

        Args:
            messages: 消息列表（会被原地修改，追加 assistant 和 tool 消息）
            on_event: 事件回调函数

        Returns:
            AgentResult: 循环最终结果
        """
        schemas = self._registry.get_all_openai_schemas()
        result = AgentResult()

        try:
            for turn in range(self._max_turns):
                self._raise_if_stop_requested()
                result.total_turns = turn + 1

                # ---- 1. 流式调用 LLM ----
                turn_result = await self._stream_llm_response(
                    messages, schemas, on_event
                )

                self._raise_if_stop_requested()

                # ---- 2. 构建 assistant 消息并追加到历史 ----
                assistant_msg = self._build_assistant_message(turn_result)
                messages.append(assistant_msg)

                # 累积最终结果（只保留最后一轮的文本内容）
                if turn_result.content:
                    result.content = turn_result.content
                if turn_result.reasoning_content:
                    result.reasoning_content = turn_result.reasoning_content
                result.usage = turn_result.usage

                # ---- 3. 检查是否有工具调用 ----
                if not turn_result.tool_calls:
                    # 无工具调用，循环结束
                    break

                # ---- 4. 执行工具调用 ----
                self._raise_if_stop_requested()
                tool_results = await self._execute_tool_calls(
                    turn_result.tool_calls, on_event
                )
                result.tool_calls_count += len(turn_result.tool_calls)

                # 将工具结果追加到消息历史
                for tc, tr in zip(turn_result.tool_calls, tool_results):
                    tc_id = tc.get("id", "")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": tr.content,
                    })

                if any(tr.is_error for tr in tool_results):
                    messages.append(self._build_tool_recovery_message(tool_results))
            else:
                # 达到最大轮次
                self._logger.warning(
                    f"Agent loop reached max turns ({self._max_turns})"
                )

        except asyncio.CancelledError:
            self._logger.info("Agent loop cancelled")
            raise
        except Exception as e:
            self._logger.error(f"Agent loop error: {e}")
            result.is_error = True
            result.error_message = str(e)

        return result

    # ============================================================
    # LLM 流式调用
    # ============================================================

    async def _stream_llm_response(
        self,
        messages: List[Dict[str, Any]],
        schemas: List[Dict[str, Any]],
        on_event: Optional[AgentEventCallback],
    ) -> TurnResult:
        """
        流式调用 LLM 并累积结果

        对照 pi-mono agent-loop.ts streamAssistantResponse() 第 238-331 行。

        Args:
            messages: 当前消息历史
            schemas: 工具 schema 列表
            on_event: 事件回调

        Returns:
            TurnResult: 本轮累积的内容、工具调用等
        """
        turn = TurnResult()

        self._raise_if_stop_requested()

        tool_names = []
        for schema in schemas:
            function_def = schema.get("function", {}) if isinstance(schema, dict) else {}
            tool_names.append(str(function_def.get("name", "") or ""))

        self._logger.info(
            f"Agent turn request tools: count={len(tool_names)}, tools={tool_names}"
        )

        stream_gen = self._client.chat_stream(
            messages=messages,
            model=self._model,
            tools=schemas if schemas else None,
            thinking=self._thinking,
        )

        try:
            async for chunk in stream_gen:
                self._raise_if_stop_requested()
                # 处理思考内容
                if chunk.reasoning_content:
                    turn.reasoning_content += chunk.reasoning_content
                    await self._emit(on_event, EVENT_STREAM_CHUNK, {
                        "chunk_type": "reasoning",
                        "text": chunk.reasoning_content,
                    })

                # 处理回答内容
                if chunk.content:
                    turn.content += chunk.content
                    await self._emit(on_event, EVENT_STREAM_CHUNK, {
                        "chunk_type": "content",
                        "text": chunk.content,
                    })

                # 保存 usage
                if chunk.usage:
                    turn.usage = chunk.usage

                # 保存工具调用和完成原因
                if chunk.tool_calls:
                    turn.tool_calls = chunk.tool_calls
                if chunk.finish_reason:
                    turn.finish_reason = chunk.finish_reason

                if chunk.is_finished:
                    break
        finally:
            # 确保关闭生成器
            if hasattr(stream_gen, 'aclose'):
                try:
                    await stream_gen.aclose()
                except Exception:
                    pass

        return turn

    # ============================================================
    # 工具执行
    # ============================================================

    async def _execute_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]],
        on_event: Optional[AgentEventCallback],
    ) -> List[ToolResult]:
        """
        执行工具调用列表

        对照 pi-mono agent-loop.ts 第 336-438 行。
        当前采用顺序执行策略。

        Args:
            tool_calls: LLM 返回的工具调用列表
            on_event: 事件回调

        Returns:
            ToolResult 列表，与 tool_calls 一一对应
        """
        results = []

        for tc_raw in tool_calls:
            self._raise_if_stop_requested()
            # 解析工具调用信息
            try:
                tc_info = ToolCallInfo.from_api_format(tc_raw)
            except ValueError as e:
                self._logger.error(f"Invalid tool call format: {e}")
                results.append(create_error_result(str(e)))
                continue

            # 发射 tool_start 事件
            await self._emit(on_event, EVENT_TOOL_START, {
                "tool_call_id": tc_info.id,
                "tool_name": tc_info.name,
                "arguments": tc_info.arguments,
            })

            # 三阶段执行
            result = await self._execute_single_tool(tc_info)

            # 发射 tool_end 事件
            await self._emit(on_event, EVENT_TOOL_END, {
                "tool_call_id": tc_info.id,
                "tool_name": tc_info.name,
                "result_content": result.content[:200],
                "is_error": result.is_error,
                "details": result.details,
                "effects": result.effects,
            })

            results.append(result)

        return results

    def _raise_if_stop_requested(self) -> None:
        """在活跃停止请求下中断 Agent 循环。"""
        if self._stop_requested and self._stop_requested():
            raise asyncio.CancelledError()

    async def _execute_single_tool(self, tc_info: ToolCallInfo) -> ToolResult:
        """
        执行单个工具调用（三阶段：prepare → execute → finalize）

        对照 pi-mono agent-loop.ts 第 458-580 行。

        Args:
            tc_info: 工具调用信息

        Returns:
            ToolResult: 工具执行结果
        """
        # ---- prepare ----
        tool = self._registry.get(tc_info.name)
        if not tool:
            self._logger.warning(f"Tool not found: {tc_info.name}")
            return create_error_result(
                f"Tool '{tc_info.name}' not found. "
                f"Available tools: {', '.join(self._registry.get_names())}"
            )

        # 参数校验
        validation_error = tool.validate_params(tc_info.arguments)
        if validation_error:
            self._logger.warning(
                f"Tool '{tc_info.name}' param validation failed: {validation_error}"
            )
            return create_error_result(validation_error)

        # ---- execute ----
        try:
            result = await tool.execute(
                tc_info.id, tc_info.arguments, self._context
            )
            self._logger.info(
                f"Tool '{tc_info.name}' executed: "
                f"is_error={result.is_error}, "
                f"content_len={len(result.content)}"
            )
            return result
        except Exception as e:
            self._logger.error(
                f"Tool '{tc_info.name}' execution error: {e}"
            )
            return create_error_result(
                f"Tool execution error: {e}"
            )

    # ============================================================
    # 辅助方法
    # ============================================================

    def _build_assistant_message(
        self, turn: TurnResult
    ) -> Dict[str, Any]:
        """
        构建 assistant 消息（用于追加到消息历史）

        当 LLM 返回 tool_calls 时，assistant 消息必须包含 tool_calls 字段，
        以满足 API 的消息格式要求。

        Args:
            turn: 本轮结果

        Returns:
            符合 API 格式的 assistant 消息字典
        """
        msg: Dict[str, Any] = {
            "role": "assistant",
            "content": turn.content or "",
        }

        if turn.tool_calls:
            # 确保 arguments 是 JSON 字符串（API 要求）
            formatted_calls = []
            for tc in turn.tool_calls:
                formatted_tc = {
                    "id": tc.get("id", ""),
                    "type": tc.get("type", "function"),
                    "function": {
                        "name": tc.get("function", {}).get("name", ""),
                        "arguments": self._ensure_json_string(
                            tc.get("function", {}).get("arguments", {})
                        ),
                    },
                }
                formatted_calls.append(formatted_tc)
            msg["tool_calls"] = formatted_calls

        return msg

    def _build_tool_recovery_message(
        self,
        tool_results: List[ToolResult],
    ) -> Dict[str, Any]:
        failed = [tr.content.strip() for tr in tool_results if tr.is_error and tr.content.strip()]
        failure_summary = "\n".join(f"- {item}" for item in failed[:3])
        content = (
            "One or more tools failed. Continue the ReAct process instead of ending with an empty reply. "
            "Retry only if you can clearly correct the arguments or approach. Otherwise, provide a final answer that explains the limitation and gives the best possible help based on the available context."
        )
        if failure_summary:
            content += f"\nTool errors:\n{failure_summary}"

        return {
            "role": "system",
            "content": content,
        }

    @staticmethod
    def _ensure_json_string(value) -> str:
        """确保值是 JSON 字符串（API 回传 tool_calls 时 arguments 必须是字符串）"""
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    async def _emit(
        callback: Optional[AgentEventCallback],
        event_type: str,
        data: Dict[str, Any],
    ) -> None:
        """发射事件（支持同步和异步回调）"""
        if callback is None:
            return
        try:
            result = callback(event_type, data)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            pass  # 回调错误不应中断循环


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "AgentLoop",
    "AgentResult",
    "TurnResult",
    "AgentEventCallback",
    "EVENT_STREAM_CHUNK",
    "EVENT_TOOL_START",
    "EVENT_TOOL_END",
]
