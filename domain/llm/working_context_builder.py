from __future__ import annotations

import copy
from typing import Any, Dict, List

from langchain_core.messages import BaseMessage

from domain.llm.message_helpers import create_system_message, is_system_message

WORKING_CONTEXT_SUMMARY_KEY = "working_context_summary"
WORKING_CONTEXT_COMPRESSED_COUNT_KEY = "working_context_compressed_count"
WORKING_CONTEXT_KEEP_RECENT_KEY = "working_context_keep_recent"


def get_working_context_summary(state: Dict[str, Any]) -> str:
    return state.get(WORKING_CONTEXT_SUMMARY_KEY, "") or ""


def get_working_context_compressed_count(state: Dict[str, Any]) -> int:
    value = state.get(WORKING_CONTEXT_COMPRESSED_COUNT_KEY, 0)
    try:
        return max(0, int(value))
    except Exception:
        return 0


def get_working_context_keep_recent(state: Dict[str, Any]) -> int:
    value = state.get(WORKING_CONTEXT_KEEP_RECENT_KEY, 0)
    try:
        return max(0, int(value))
    except Exception:
        return 0


def build_working_context_state(
    state: Dict[str, Any],
    *,
    summary: str,
    compressed_count: int,
    keep_recent: int,
) -> Dict[str, Any]:
    new_state = copy.deepcopy(state)
    new_state[WORKING_CONTEXT_SUMMARY_KEY] = summary or ""
    new_state[WORKING_CONTEXT_COMPRESSED_COUNT_KEY] = max(0, int(compressed_count))
    new_state[WORKING_CONTEXT_KEEP_RECENT_KEY] = max(0, int(keep_recent))
    return new_state


def clear_working_context_state(state: Dict[str, Any]) -> Dict[str, Any]:
    return build_working_context_state(
        state,
        summary="",
        compressed_count=0,
        keep_recent=0,
    )


def get_history_messages(state: Dict[str, Any]) -> List[BaseMessage]:
    return list(state.get("messages", []))


def get_history_message_count(state: Dict[str, Any]) -> int:
    return len(get_history_messages(state))


def get_non_system_history_messages(state: Dict[str, Any]) -> List[BaseMessage]:
    return [msg for msg in get_history_messages(state) if not is_system_message(msg)]


def get_messages_covered_by_summary(state: Dict[str, Any]) -> List[BaseMessage]:
    non_system_messages = get_non_system_history_messages(state)
    compressed_count = min(
        get_working_context_compressed_count(state),
        len(non_system_messages),
    )
    return list(non_system_messages[:compressed_count])


def get_direct_working_messages(state: Dict[str, Any]) -> List[BaseMessage]:
    messages = get_history_messages(state)
    system_messages = [msg for msg in messages if is_system_message(msg)]
    non_system_messages = [msg for msg in messages if not is_system_message(msg)]
    compressed_count = min(
        get_working_context_compressed_count(state),
        len(non_system_messages),
    )
    return list(system_messages) + list(non_system_messages[compressed_count:])


def build_summary_message(state: Dict[str, Any]) -> BaseMessage | None:
    summary = get_working_context_summary(state)
    compressed_count = len(get_messages_covered_by_summary(state))
    if not summary or compressed_count <= 0:
        return None
    content = (
        f"以下摘要覆盖了更早的 {compressed_count} 条历史对话。"
        "这些历史记录仍然属于当前会话，但不会再逐条注入当前工作上下文。"
        f"\n\n{summary}"
    )
    return create_system_message(content=content)


def get_working_context_messages(state: Dict[str, Any]) -> List[BaseMessage]:
    direct_messages = get_direct_working_messages(state)
    summary_message = build_summary_message(state)
    if summary_message is None:
        return direct_messages

    system_count = 0
    for msg in direct_messages:
        if is_system_message(msg):
            system_count += 1
        else:
            break

    return (
        list(direct_messages[:system_count])
        + [summary_message]
        + list(direct_messages[system_count:])
    )


def get_working_context_message_count(state: Dict[str, Any]) -> int:
    return len(get_working_context_messages(state))


__all__ = [
    "WORKING_CONTEXT_SUMMARY_KEY",
    "WORKING_CONTEXT_COMPRESSED_COUNT_KEY",
    "WORKING_CONTEXT_KEEP_RECENT_KEY",
    "build_working_context_state",
    "clear_working_context_state",
    "get_direct_working_messages",
    "get_history_message_count",
    "get_history_messages",
    "get_messages_covered_by_summary",
    "get_non_system_history_messages",
    "get_working_context_compressed_count",
    "get_working_context_keep_recent",
    "get_working_context_message_count",
    "get_working_context_messages",
    "get_working_context_summary",
]
