"""Regression coverage for AgentLoop terminal and completion semantics."""

import asyncio

import pytest

from domain.llm.agent.agent_loop import AgentLoop
from domain.llm.agent.tool_registry import ToolRegistry
from domain.llm.agent.types import ToolContext
from infrastructure.llm_adapters.base_client import StreamChunk


class _ScriptedStreamClient:
    def __init__(self, turns):
        self._turns = [list(turn) for turn in turns]

    async def chat_stream(self, **_kwargs):
        if not self._turns:
            raise AssertionError("AgentLoop requested an unexpected extra turn")
        for chunk in self._turns.pop(0):
            yield chunk


def _run_loop(tmp_path, turns, *, max_turns=15):
    messages = [{"role": "user", "content": "ping"}]
    loop = AgentLoop(
        client=_ScriptedStreamClient(turns),
        registry=ToolRegistry(),
        context=ToolContext(project_root=str(tmp_path)),
        model="fake-model",
        max_turns=max_turns,
    )
    return asyncio.run(loop.run(messages)), messages


@pytest.mark.parametrize("finish_reason", ["stop", "end_turn"])
def test_normal_finish_reasons_complete_successfully(tmp_path, finish_reason):
    result, messages = _run_loop(tmp_path, [[StreamChunk(
        content="complete answer",
        is_finished=True,
        finish_reason=finish_reason,
    )]])

    assert result.is_error is False
    assert result.error_message == ""
    assert result.content == "complete answer"
    assert messages[-1] == {"role": "assistant", "content": "complete answer"}


def test_explicit_terminal_without_finish_reason_remains_compatible(tmp_path):
    result, _ = _run_loop(tmp_path, [[StreamChunk(
        content="done frame answer",
        is_finished=True,
    )]])

    assert result.is_error is False
    assert result.content == "done frame answer"


@pytest.mark.parametrize("finish_reason", [None, "stop", "end_turn"])
def test_empty_terminal_response_is_not_completed(tmp_path, finish_reason):
    result, _ = _run_loop(tmp_path, [[StreamChunk(
        is_finished=True,
        finish_reason=finish_reason,
    )]])

    assert result.is_error is True
    assert "no final assistant content" in result.error_message


def test_reasoning_only_terminal_is_error_but_preserves_reasoning(tmp_path):
    result, _ = _run_loop(tmp_path, [[StreamChunk(
        reasoning_content="private reasoning without a final answer",
        is_finished=True,
        finish_reason="stop",
    )]])

    assert result.is_error is True
    assert result.reasoning_content == "private reasoning without a final answer"
    assert "no final assistant content" in result.error_message


@pytest.mark.parametrize(
    "finish_reason",
    ["length", "max_tokens", "content_filter", "blocked", "safety", "unexpected_provider_reason"],
)
def test_non_success_finish_reasons_fail_closed_and_preserve_diagnostics(
    tmp_path,
    finish_reason,
):
    partial_content = f"partial output before {finish_reason}"
    result, messages = _run_loop(tmp_path, [[StreamChunk(
        content=partial_content,
        is_finished=True,
        finish_reason=finish_reason,
    )]])

    assert result.is_error is True
    assert result.content == partial_content
    assert finish_reason in result.error_message
    assert messages == [{"role": "user", "content": "ping"}]


def test_tool_calls_finish_reason_continues_to_next_turn(tmp_path):
    tool_call = {
        "id": "call-1",
        "type": "function",
        "function": {"name": "missing_tool", "arguments": "{}"},
    }
    result, _ = _run_loop(tmp_path, [
        [StreamChunk(
            tool_calls=[tool_call],
            is_finished=True,
            finish_reason="tool_calls",
        )],
        [StreamChunk(
            content="final answer after tool path",
            is_finished=True,
            finish_reason="stop",
        )],
    ])

    assert result.is_error is False
    assert result.content == "final answer after tool path"
    assert result.tool_calls_count == 1
    assert result.total_turns == 2


def test_max_turns_exhaustion_is_error_and_preserves_generated_content(tmp_path):
    tool_call = {
        "id": "call-1",
        "type": "function",
        "function": {"name": "missing_tool", "arguments": "{}"},
    }
    result, _ = _run_loop(tmp_path, [[StreamChunk(
        content="generated planning content",
        tool_calls=[tool_call],
        is_finished=True,
        finish_reason="tool_calls",
    )]], max_turns=1)

    assert result.is_error is True
    assert result.content == "generated planning content"
    assert result.tool_calls_count == 1
    assert "max turns (1)" in result.error_message
    assert "final assistant answer" in result.error_message
