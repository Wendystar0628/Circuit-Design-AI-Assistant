"""Minimal Server-Sent Events framing for provider streams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterable, AsyncIterator, Optional


@dataclass(frozen=True, slots=True)
class SSEEvent:
    """One event dispatched at a blank-line SSE boundary."""

    data: str
    event: Optional[str] = None
    event_id: Optional[str] = None


def _parse_event(lines: list[str]) -> Optional[SSEEvent]:
    data_lines: list[str] = []
    event_type: Optional[str] = None
    event_id: Optional[str] = None

    for line in lines:
        if not line or line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if field == "data":
            data_lines.append(value)
        elif field == "event":
            event_type = value or None
        elif field == "id" and "\x00" not in value:
            event_id = value

    if not data_lines and event_type is None and event_id is None:
        return None
    return SSEEvent(
        data="\n".join(data_lines),
        event=event_type,
        event_id=event_id,
    )


async def iter_sse_events(source: AsyncIterable[str]) -> AsyncIterator[SSEEvent]:
    """Decode arbitrary text chunks into complete SSE events.

    Network chunks and SSE events have no one-to-one relationship. This parser
    therefore buffers physical lines and dispatches only at a blank line. A
    final complete line at EOF is accepted, which accommodates providers that
    omit the last newline while still keeping JSON parsing at event granularity.
    """
    buffer = ""
    event_lines: list[str] = []

    async for chunk in source:
        if not chunk:
            continue
        buffer += chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            if line.endswith("\r"):
                line = line[:-1]
            if line:
                event_lines.append(line)
                continue
            event = _parse_event(event_lines)
            event_lines = []
            if event is not None:
                yield event

    if buffer:
        event_lines.append(buffer[:-1] if buffer.endswith("\r") else buffer)
    event = _parse_event(event_lines)
    if event is not None:
        yield event


__all__ = ["SSEEvent", "iter_sse_events"]
